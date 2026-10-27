"""Generates transactions.csv (SAMPLE data, not real bank data).
Run:  python generate_sample_data.py
Includes an is_fraud column (ground truth) so the dashboard can measure the rules.
"""
import csv
import random
from datetime import datetime, timedelta

random.seed(7)

NORMAL_CATS = {  # category: (min, max) in INR
    "Grocery": (150, 1800), "Food Delivery": (120, 900), "Fashion": (500, 6000),
    "Electronics": (2000, 45000), "Travel": (1500, 25000), "Utilities": (300, 4000),
    "Entertainment": (150, 1500), "Fuel": (300, 3000),
}
CAT_WEIGHTS = [5, 5, 3, 1.2, 1.5, 3, 2, 2.5]
RISKY = ["Crypto", "Gift Cards", "Gambling", "Wire Transfer"]
METHODS = ["UPI", "Credit Card", "Debit Card", "Net Banking", "Wallet"]
FOREIGN = ["USA", "UK", "UAE", "Singapore", "Russia", "Nigeria", "Brazil"]
START = datetime(2026, 9, 27)
DAYS = 30

users = []
for i in range(1, 41):
    uid = f"U{1000 + i}"
    users.append({
        "id": uid,
        "home": random.choices(["India", "USA", "UK"], weights=[8, 1, 1])[0],
        "devices": [f"D-{uid}-A"] + ([f"D-{uid}-B"] if random.random() < 0.4 else []),
        "scale": random.uniform(0.6, 1.8),
        "methods": random.sample(METHODS, 2),
    })

rows = []  # (timestamp, user, amount, cat, method, txn_country, home, device, failed, fraud)


def rand_time(night=False):
    day = START + timedelta(days=random.randrange(DAYS))
    if night:
        hour = random.randint(0, 4)
    else:
        hour = random.choices(range(24), weights=[1] * 6 + [3, 5, 6, 6, 6, 6, 6, 6, 6, 5, 5, 6, 7, 7, 6, 4, 3, 2])[0]
    return day.replace(hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59))


# ---- legitimate traffic ----
for u in users:
    for _ in range(random.randint(45, 75)):
        cat = random.choices(list(NORMAL_CATS), weights=CAT_WEIGHTS)[0]
        lo, hi = NORMAL_CATS[cat]
        amount = round(random.uniform(lo, hi) * u["scale"], 2)
        device = random.choice(u["devices"])
        country = u["home"]
        failed = random.choices([0, 1, 3], weights=[94, 5, 1])[0]
        if random.random() < 0.03:
            device = f"D-{u['id']}-N{random.randint(1, 99)}"       # legit new phone
        if random.random() < 0.02:
            country = random.choice(FOREIGN)                       # legit travel
            cat = "Travel"
        rows.append((rand_time(), u["id"], amount, cat, random.choice(u["methods"]),
                     country, u["home"], device, failed, 0))

# ---- fraud: account takeover ----
for n in range(25):
    u = random.choice(users)
    cat = random.choice(RISKY) if random.random() < 0.6 else random.choice(["Electronics", "Travel"])
    rows.append((rand_time(night=random.random() < 0.7), u["id"], round(random.uniform(25000, 120000), 2), cat,
                 random.choice(METHODS), random.choice(FOREIGN) if random.random() < 0.8 else u["home"],
                 u["home"], f"D-FRAUD-{n}", random.choice([0, 1, 3, 4]), 1))

# ---- fraud: card-testing bursts (many tiny payments within minutes) ----
for n in range(8):
    u = random.choice(users)
    t0 = rand_time(night=random.random() < 0.5)
    device = f"D-FRAUD-B{n}"
    country = random.choice(FOREIGN)
    for k in range(random.randint(5, 8)):
        rows.append((t0 + timedelta(seconds=random.randint(20, 70) * k), u["id"], round(random.uniform(10, 99), 2),
                     random.choice(["Entertainment", "Gift Cards"]), "Credit Card", country, u["home"],
                     device, random.choice([0, 1, 2]), 1))

# ---- fraud: "stealth" cases that look fairly normal (rules may miss these) ----
for n in range(10):
    u = random.choice(users)
    rows.append((rand_time(), u["id"], round(random.uniform(8000, 20000), 2), "Electronics",
                 random.choice(u["methods"]), u["home"], u["home"], random.choice(u["devices"]), 0, 1))

rows.sort(key=lambda r: r[0])

with open("transactions.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["txn_id", "timestamp", "user_id", "amount", "merchant_category", "payment_method",
                "txn_country", "home_country", "device_id", "failed_attempts", "is_fraud"])
    for i, r in enumerate(rows, 1):
        w.writerow([f"T{i:06d}", r[0].strftime("%Y-%m-%d %H:%M:%S"), r[1], r[2], r[3], r[4],
                    r[5], r[6], r[7], r[8], r[9]])
    # a few deliberately dirty rows so the cleaning step has something to do
    w.writerow(["T900001", "2026-10-05 10:00:00", "U1001", "abc", "Grocery", "UPI", "India", "India", "D-U1001-A", 0, 0])
    w.writerow(["T900002", "not-a-time", "U1002", 500, "Fuel", "UPI", "India", "India", "D-U1002-A", 0, 0])
    w.writerow(["T900003", "2026-10-06 11:00:00", "U1003", -250, "Fuel", "UPI", "India", "India", "D-U1003-A", 0, 0])
    w.writerow(["T000001", "2026-10-07 12:00:00", "U1004", 300, "Grocery", "UPI", "India", "India", "D-U1004-A", 0, 0])  # duplicate id
print(f"transactions.csv written with {len(rows) + 4} rows ({sum(r[9] for r in rows)} fraud)")
