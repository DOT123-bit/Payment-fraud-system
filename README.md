# Online Payment Fraud Management System (pure Python)

A rule-based fraud detection dashboard built with Python, pandas and Streamlit. No ML libraries,
no database. Each transaction is scored 0-100 from 8 suspicious signals and mapped to
Approve / Review (OTP) / Block.

**Data:** `transactions.csv` is generated SAMPLE data (`generate_sample_data.py`), not real bank
records. It contains a few intentionally bad rows to show data cleaning, and an `is_fraud`
column so the rules can be measured.

## Files
- `app.py` - Streamlit dashboard (overview, review queue, check-a-transaction, rule performance)
- `fraud_engine.py` - cleaning + rule scoring logic (the core)
- `generate_sample_data.py` - creates `transactions.csv`
- `requirements.txt`

## CSV columns
Required: `txn_id, timestamp, user_id, amount, merchant_category, payment_method, txn_country,
home_country, device_id, failed_attempts`. Optional: `is_fraud` (1/0).
Timestamp format: `YYYY-MM-DD HH:MM:SS`.

## Run locally
    pip install -r requirements.txt
    streamlit run app.py
