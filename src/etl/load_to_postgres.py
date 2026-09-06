"""
Loads generated CSVs into PostgreSQL using TRUNCATE CASCADE to support 
idempotent pipeline re-runs without dropping schema constraints or views.

Usage:
    python -m src.etl.load_to_postgres
"""

import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://csops_admin:csops_pass@localhost:5432/csops")
DATA_DIR = "data/generated"

# Order matters: Parents must come before children for insertions
TABLES = [
    ("accounts.csv", "accounts"),
    ("contacts.csv", "contacts"),
    ("opportunities.csv", "opportunities"),
    ("customer_success.csv", "customer_success"),
    ("support_tickets.csv", "support_tickets"),
    ("product_usage.csv", "product_usage"),
    ("surveys.csv", "surveys"),
    ("renewals.csv", "renewals"),
]


def main():
    engine = create_engine(DATABASE_URL)

    with engine.begin() as conn:
        print("Clearing existing data from target tables...")
        # Truncate tables in reverse order to respect foreign key constraints safely
        for _, table_name in reversed(TABLES):
            conn.execute(text(f"TRUNCATE TABLE {table_name} CASCADE;"))

        # Append fresh data into existing schema structure
        for csv_file, table_name in TABLES:
            path = os.path.join(DATA_DIR, csv_file)
            if not os.path.exists(path):
                print(f"Skipping {table_name}: {path} not found. Run generate_data.py first.")
                continue

            df = pd.read_csv(path)
            df.to_sql(table_name, conn, if_exists="append", index=False)
            print(f"Loaded {len(df)} rows into {table_name}")

    print("ETL Ingestion Completed Successfully.")


if __name__ == "__main__":
    main()