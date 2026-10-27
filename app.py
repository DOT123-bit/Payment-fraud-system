"""Online Payment Fraud Management System - pure Python (pandas + Streamlit)."""
import datetime as dt
import hashlib
import os
import tempfile

import pandas as pd
import plotly.express as px
import streamlit as st

import fraud_engine as fe

st.set_page_config(page_title="Payment Fraud Management", page_icon="🛡️", layout="wide")
HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "transactions.csv")
LEVEL_COLORS = {"Low": "#2e9e5b", "Medium": "#f0a020", "High": "#d64545"}


@st.cache_data(show_spinner="Reading and cleaning data...")
def load_clean(path, key):
    return fe.clean(pd.read_csv(path, dtype=str))


@st.cache_data(show_spinner="Scoring transactions...")
def run_scoring(path, key, cfg):
    clean_df, _ = load_clean(path, key)
    return fe.score(clean_df, cfg)


# ---------------- sidebar ----------------
st.sidebar.title("🛡️ Controls")
up = st.sidebar.file_uploader("Upload transactions CSV", type="csv")
if up is not None:
    content = up.getvalue()
    key = hashlib.md5(content).hexdigest()
    path = os.path.join(tempfile.gettempdir(), f"upload_{key}.csv")
    with open(path, "wb") as fh:
        fh.write(content)
    source = f"Uploaded: {up.name}"
else:
    path, key, source = SAMPLE, "sample", "Sample data (generated, not real bank data)"

with st.sidebar.expander("Rule settings", expanded=False):
    high_amount = st.number_input("High amount (₹)", 1000, 1000000, fe.DEFAULT_CFG["high_amount"], step=5000)
    spike = st.slider("Spike: times user's usual amount", 2, 20, fe.DEFAULT_CFG["spike_multiplier"])
    vel_n = st.slider("Velocity: transactions...", 2, 10, fe.DEFAULT_CFG["velocity_count"])
    vel_w = st.slider("...within (minutes)", 1, 60, fe.DEFAULT_CFG["velocity_window_min"])
    failed = st.slider("Failed attempts limit", 1, 10, fe.DEFAULT_CFG["failed_attempts"])
    review_t = st.slider("Review threshold (score)", 10, 90, fe.DEFAULT_CFG["review_threshold"])
    block_t = st.slider("Block threshold (score)", 20, 100, fe.DEFAULT_CFG["block_threshold"])
cfg = {"high_amount": int(high_amount), "spike_multiplier": spike, "velocity_count": vel_n,
       "velocity_window_min": vel_w, "failed_attempts": failed,
       "review_threshold": review_t, "block_threshold": block_t}
if block_t <= review_t:
    st.sidebar.error("Block threshold must be higher than review threshold.")
    st.stop()

try:
    clean_df, stats = load_clean(path, key)
    scored = run_scoring(path, key, cfg)
except Exception as e:
    st.error(f"Could not read this file: {e}")
    st.stop()
if scored.empty:
    st.error("No valid transactions left after cleaning. Check your CSV columns and values.")
    st.stop()

dmin, dmax = scored["timestamp"].dt.date.min(), scored["timestamp"].dt.date.max()
date_range = st.sidebar.date_input("Date range", value=(dmin, dmax), min_value=dmin, max_value=dmax)
cats = sorted(scored["merchant_category"].unique())
methods = sorted(scored["payment_method"].unique())
sel_cats = st.sidebar.multiselect("Merchant category", cats, default=cats)
sel_methods = st.sidebar.multiselect("Payment method", methods, default=methods)

if isinstance(date_range, tuple) and len(date_range) == 2:
    d0, d1 = date_range
else:
    d0 = d1 = date_range[0] if isinstance(date_range, (tuple, list)) else date_range

# filters are applied AFTER scoring, so history-based rules (velocity, new device) stay correct
view = scored[(scored["timestamp"].dt.date >= d0) & (scored["timestamp"].dt.date <= d1)
              & scored["merchant_category"].isin(sel_cats) & scored["payment_method"].isin(sel_methods)]

# ---------------- header ----------------
st.title("🛡️ Online Payment Fraud Management System")
st.caption(f"Source: {source} · {stats['rows_in']} rows read, {stats['rows_dropped']} invalid rows removed, "
           f"{stats['rows_out']} kept · Rule-based scoring in pure Python")

if view.empty:
    st.info("No transactions match the current filters.")
    st.stop()

flagged = view[view["risk_level"] != "Low"]
blocked = view[view["risk_level"] == "High"]
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Transactions", f"{len(view):,}")
c2.metric("Total value", f"₹{view['amount'].sum():,.0f}")
c3.metric("Flagged (review + block)", f"{len(flagged):,}", f"{len(flagged) / len(view) * 100:.1f}% of all", delta_color="off")
c4.metric("Blocked", f"{len(blocked):,}")
c5.metric("Value blocked", f"₹{blocked['amount'].sum():,.0f}")

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["Overview", "Review queue", "Check a transaction", "Rule performance", "How it works"])

# ---------------- overview ----------------
with tab1:
    a, b = st.columns(2)
    lvl = view["risk_level"].value_counts().reindex(["Low", "Medium", "High"]).fillna(0).reset_index()
    lvl.columns = ["risk_level", "transactions"]
    a.plotly_chart(px.pie(lvl, names="risk_level", values="transactions", hole=0.45, color="risk_level",
                          color_discrete_map=LEVEL_COLORS, title="Transactions by risk level"))
    daily = flagged.assign(date=flagged["timestamp"].dt.date).groupby(["date", "risk_level"]).size().reset_index(name="count")
    if daily.empty:
        b.info("No flagged transactions in this selection.")
    else:
        b.plotly_chart(px.bar(daily, x="date", y="count", color="risk_level", color_discrete_map=LEVEL_COLORS,
                              title="Flagged transactions per day", labels={"date": "Date", "count": "Flagged"}))

    if not flagged.empty:
        c, d = st.columns(2)
        hours = flagged.groupby(flagged["timestamp"].dt.hour).size().reindex(range(24), fill_value=0).reset_index()
        hours.columns = ["hour", "flagged"]
        c.plotly_chart(px.bar(hours, x="hour", y="flagged", title="Flagged transactions by hour of day",
                              labels={"hour": "Hour (0-23)", "flagged": "Flagged"}))
        by_cat = flagged.groupby("merchant_category")["amount"].sum().sort_values(ascending=False).reset_index()
        d.plotly_chart(px.bar(by_cat, x="merchant_category", y="amount", title="Flagged value by merchant category (₹)",
                              labels={"merchant_category": "Category", "amount": "₹"}))

        trig = pd.DataFrame({"Rule": [lbl for lbl, _ in fe.RULES.values()],
                             "Times triggered": [int(flagged[col].sum()) for col in fe.RULES]}
                            ).sort_values("Times triggered", ascending=False)
        st.plotly_chart(px.bar(trig, x="Times triggered", y="Rule", orientation="h",
                               title="Which rules fire most on flagged transactions"))

        st.subheader("Riskiest users")
        users = (flagged.groupby("user_id")
                 .agg(flagged_txns=("txn_id", "count"), flagged_value=("amount", "sum"), max_score=("risk_score", "max"))
                 .sort_values(["flagged_txns", "flagged_value"], ascending=False).head(10).reset_index())
        st.dataframe(users, hide_index=True)

# ---------------- review queue ----------------
with tab2:
    st.subheader("Alerts waiting for an analyst")
    queue = (flagged.sort_values(["risk_score", "amount"], ascending=False).head(300)
             [["txn_id", "timestamp", "user_id", "amount", "merchant_category", "txn_country",
               "risk_score", "risk_level", "decision", "reasons"]])
    if queue.empty:
        st.success("Nothing to review for the current filters.")
    else:
        st.dataframe(queue, hide_index=True)
        st.download_button("⬇️ Download alerts (CSV)", queue.to_csv(index=False).encode(), "fraud_alerts.csv", "text/csv")

        st.subheader("Record an analyst decision")
        if "decisions" not in st.session_state:
            st.session_state["decisions"] = {}
        pick = st.selectbox("Transaction", queue["txn_id"].head(200).tolist())
        row = queue[queue["txn_id"] == pick].iloc[0]
        st.write(f"**{row['user_id']}** · ₹{row['amount']:,.2f} · {row['merchant_category']} · {row['txn_country']} "
                 f"· score **{row['risk_score']}** ({row['risk_level']})")
        st.caption("Why flagged: " + row["reasons"])
        b1, b2 = st.columns(2)
        if b1.button("🚫 Confirm fraud"):
            st.session_state["decisions"][pick] = "Confirmed fraud"
        if b2.button("✅ Mark legitimate"):
            st.session_state["decisions"][pick] = "Legitimate"
        if st.session_state["decisions"]:
            dec = pd.DataFrame(list(st.session_state["decisions"].items()), columns=["txn_id", "analyst_decision"])
            st.dataframe(dec, hide_index=True)
            st.download_button("⬇️ Download decisions (CSV)", dec.to_csv(index=False).encode(),
                               "analyst_decisions.csv", "text/csv")
            st.caption("Decisions are kept only for this browser session (no database in this version).")

# ---------------- check a transaction ----------------
with tab3:
    st.subheader("Simulate a new payment and see the decision")
    all_users = sorted(clean_df["user_id"].unique())
    with st.form("check_form"):
        f1, f2, f3 = st.columns(3)
        user = f1.selectbox("User", all_users)
        amount = f2.number_input("Amount (₹)", 1.0, 10000000.0, 1500.0, step=500.0)
        category = f3.selectbox("Merchant category", sorted(set(cats) | {"Crypto", "Gift Cards", "Gambling", "Wire Transfer"}))
        g1, g2, g3 = st.columns(3)
        method = g1.selectbox("Payment method", methods)
        countries = sorted(set(clean_df["txn_country"]) | set(clean_df["home_country"]))
        country = g2.selectbox("Payment country", countries)
        device = g3.text_input("Device ID", "NEW-DEVICE-1", help="Use the user's usual device to see a lower score.")
        h1, h2, h3 = st.columns(3)
        day = h1.date_input("Date", dt.date.fromisoformat(str(scored["timestamp"].max().date())))
        clock = h2.time_input("Time", dt.time(14, 0))
        tries = h3.number_input("Failed attempts before this", 0, 10, 0)
        go = st.form_submit_button("Check transaction")
    if go:
        hist = clean_df[clean_df["user_id"] == user]
        home = hist.sort_values("timestamp")["home_country"].iloc[-1] if len(hist) else country
        new = {"timestamp": pd.Timestamp(dt.datetime.combine(day, clock)), "user_id": user, "amount": float(amount),
               "merchant_category": category, "payment_method": method, "txn_country": country,
               "home_country": home, "device_id": device.strip() or "UNKNOWN", "failed_attempts": int(tries)}
        res = fe.score_single(clean_df, new, cfg)
        m1, m2, m3 = st.columns(3)
        m1.metric("Risk score", f"{int(res['risk_score'])} / 100")
        m2.metric("Risk level", res["risk_level"])
        m3.metric("Decision", res["decision"])
        if res["risk_level"] == "High":
            st.error("Block this payment.")
        elif res["risk_level"] == "Medium":
            st.warning("Ask for extra verification (OTP) or send to manual review.")
        else:
            st.success("Approve this payment.")
        table = pd.DataFrame([{"Rule": lbl, "Triggered": "Yes" if bool(res[col]) else "No",
                               "Points": pts if bool(res[col]) else 0} for col, (lbl, pts) in fe.RULES.items()])
        st.dataframe(table, hide_index=True)
        st.caption(f"User's home country (from history): {home}")

# ---------------- rule performance ----------------
with tab4:
    st.subheader("How well do the rules catch fraud?")
    perf = fe.evaluate(view)
    if perf is None:
        st.info("Your file has no `is_fraud` column (1 = confirmed fraud, 0 = genuine), so accuracy can't be measured.")
    else:
        st.dataframe(perf, hide_index=True)
        st.caption("Precision = of the alerts raised, how many were real fraud. "
                   "Recall = of all real fraud, how much was caught. "
                   "The sample data was generated with patterns these rules look for, so real-world results would be lower.")
        miss = view[(view["is_fraud"] == 1) & (view["risk_level"] == "Low")]
        st.write(f"**Missed frauds ({len(miss)}):** these looked like normal payments to the rules.")
        if not miss.empty:
            st.dataframe(miss[["txn_id", "timestamp", "user_id", "amount", "merchant_category", "risk_score"]].head(50),
                         hide_index=True)

# ---------------- how it works ----------------
with tab5:
    st.subheader("Scoring rules")
    st.write("Every transaction collects points for each suspicious signal. The total (max 100) decides the action.")
    st.dataframe(pd.DataFrame([{"Rule": lbl, "Points": pts} for lbl, pts in fe.RULES.values()]), hide_index=True)
    st.write(f"**Low** (below {review_t}) → Approve · **Medium** ({review_t}-{block_t - 1}) → Review / OTP · "
             f"**High** ({block_t}+) → Block")
    st.write("Limits for 'high amount', 'spike', 'velocity' and 'failed attempts' can be changed in the sidebar.")
    st.caption("Limitations: this is a rule-based demo. Real systems add machine learning, device fingerprinting, "
               "IP/geo checks and chargeback feedback.")
