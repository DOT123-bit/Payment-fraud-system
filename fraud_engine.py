"""Rule-based fraud scoring engine. Pure Python + pandas/numpy, no ML libraries.

Each transaction gets points for every suspicious signal it triggers.
Score is capped at 100 and mapped to: Low -> Approve, Medium -> Review/OTP, High -> Block.
"""
import numpy as np
import pandas as pd

REQUIRED = ["txn_id", "timestamp", "user_id", "amount", "merchant_category", "payment_method",
            "txn_country", "home_country", "device_id", "failed_attempts"]

HIGH_RISK_CATEGORIES = {"crypto", "gift cards", "gambling", "wire transfer"}

# rule column -> (label shown to the analyst, points)
RULES = {
    "r_high_amount": ("High amount", 25),
    "r_amount_spike": ("Amount far above user's normal", 20),
    "r_night": ("Night-time transaction (12am-5am)", 10),
    "r_country": ("Transaction outside home country", 20),
    "r_velocity": ("Many transactions in a short time", 25),
    "r_new_device": ("New device for this user", 15),
    "r_failed": ("Multiple failed attempts before success", 20),
    "r_risky_cat": ("High-risk merchant category", 15),
}

DEFAULT_CFG = {
    "high_amount": 50000,        # INR
    "spike_multiplier": 5,       # x user's usual (median) amount
    "velocity_count": 4,         # this many txns ...
    "velocity_window_min": 10,   # ... within this many minutes
    "failed_attempts": 3,
    "review_threshold": 30,
    "block_threshold": 60,
}


def clean(raw):
    """Returns (cleaned_df, stats). Bad rows are dropped, not guessed."""
    df = raw.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError("CSV is missing columns: " + ", ".join(missing))
    rows_in = len(df)

    for c in ["txn_id", "user_id", "merchant_category", "payment_method", "txn_country", "home_country", "device_id"]:
        df[c] = df[c].fillna("").astype(str).str.strip()
    df["device_id"] = df["device_id"].replace("", "UNKNOWN")
    df["txn_country"] = df["txn_country"].replace("", "Unknown")
    df["home_country"] = df["home_country"].replace("", "Unknown")
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["failed_attempts"] = pd.to_numeric(df["failed_attempts"], errors="coerce").fillna(0).clip(lower=0)
    if "is_fraud" in df.columns:
        df["is_fraud"] = pd.to_numeric(df["is_fraud"], errors="coerce").fillna(0).astype(int)

    df = df[(df["txn_id"] != "") & (df["user_id"] != "")
            & df["timestamp"].notna() & df["amount"].notna() & (df["amount"] > 0)]
    df = df.drop_duplicates(subset="txn_id", keep="first").reset_index(drop=True)
    return df, {"rows_in": rows_in, "rows_out": len(df), "rows_dropped": rows_in - len(df)}


def score(clean_df, cfg=None):
    """Adds rule flags, risk_score (0-100), risk_level, decision and reasons."""
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    df = clean_df.sort_values(["user_id", "timestamp"], kind="stable").reset_index(drop=True)
    g = df.groupby("user_id")

    # 1. high amount
    df["r_high_amount"] = df["amount"] >= cfg["high_amount"]

    # 2. amount spike vs the user's own previous median (needs 3+ earlier transactions)
    prior_median = g["amount"].transform(lambda s: s.shift().expanding(min_periods=3).median())
    df["r_amount_spike"] = df["amount"] > cfg["spike_multiplier"] * prior_median   # NaN -> False

    # 3. night-time
    df["r_night"] = df["timestamp"].dt.hour.between(0, 4)

    # 4. foreign country
    df["r_country"] = df["txn_country"].str.upper() != df["home_country"].str.upper()

    # 5. velocity: txns by the same user inside the time window (including this one)
    window = np.timedelta64(int(cfg["velocity_window_min"]), "m")
    ts_all = df["timestamp"].to_numpy()
    counts = np.ones(len(df), dtype=int)
    for _, idx in df.groupby("user_id").indices.items():
        ts = ts_all[idx]
        start = np.searchsorted(ts, ts - window, side="left")
        counts[idx] = np.arange(len(ts)) - start + 1
    df["recent_txns"] = counts
    df["r_velocity"] = counts >= cfg["velocity_count"]

    # 6. new device (first time this user uses it, and not the user's very first transaction)
    first_seen = ~df.duplicated(["user_id", "device_id"])
    df["r_new_device"] = first_seen & (g.cumcount() > 0)

    # 7. failed attempts
    df["r_failed"] = df["failed_attempts"] >= cfg["failed_attempts"]

    # 8. risky merchant category
    df["r_risky_cat"] = df["merchant_category"].str.lower().isin(HIGH_RISK_CATEGORIES)

    points = np.zeros(len(df), dtype=int)
    reasons = pd.Series([""] * len(df))
    for col, (label, pts) in RULES.items():
        points += df[col].to_numpy().astype(int) * pts
        reasons = reasons + np.where(df[col], label + "; ", "")
    df["risk_score"] = np.minimum(points, 100)
    df["reasons"] = reasons.str.rstrip("; ").replace("", "None")
    df["risk_level"] = np.select(
        [df["risk_score"] >= cfg["block_threshold"], df["risk_score"] >= cfg["review_threshold"]],
        ["High", "Medium"], default="Low")
    df["decision"] = df["risk_level"].map({"High": "Block", "Medium": "Review / OTP", "Low": "Approve"})
    return df.sort_values("timestamp", kind="stable").reset_index(drop=True)


def score_single(clean_history, new_txn, cfg=None):
    """Scores one new transaction against the existing history. Returns the scored row (Series)."""
    row = {**new_txn, "txn_id": "TEST-NEW"}
    combined = pd.concat([clean_history, pd.DataFrame([row])], ignore_index=True)
    scored = score(combined, cfg)
    return scored[scored["txn_id"] == "TEST-NEW"].iloc[0]


def evaluate(scored):
    """Precision/recall of the rules - only possible if the file has an is_fraud column."""
    if "is_fraud" not in scored.columns:
        return None
    actual = scored["is_fraud"] == 1
    out = []
    for name, flagged in [("Flagged (Review + Block)", scored["risk_level"] != "Low"),
                          ("Blocked only (High)", scored["risk_level"] == "High")]:
        tp = int((flagged & actual).sum())
        fp = int((flagged & ~actual).sum())
        fn = int((~flagged & actual).sum())
        out.append({
            "Rule outcome": name, "Frauds caught": tp, "Frauds missed": fn, "False alarms": fp,
            "Precision %": round(tp / (tp + fp) * 100, 1) if tp + fp else 0.0,
            "Recall %": round(tp / (tp + fn) * 100, 1) if tp + fn else 0.0,
        })
    return pd.DataFrame(out)
