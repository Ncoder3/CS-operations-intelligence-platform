"""
Loads generated CSVs into PostgreSQL (assumes docker-compose postgres is running
and sql/schema.sql has already created the tables — it runs automatically on
first container start via docker-entrypoint-initdb.d).

Usage:
    python src/etl/load_to_postgres.py
"""

import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy import text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://csops_admin:csops_pass@localhost:5432/csops")
DATA_DIR = "data/generated"

# (csv filename, table name) — order matters: parents before children
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

    with engine.connect() as conn:
        # Wipe old data in correct order to respect foreign key constraints
        conn.execute(text("TRUNCATE TABLE action_center, health_scores, renewals, surveys, product_usage, support_tickets, customer_success, opportunities, contacts, accounts CASCADE;"))
        conn.commit()

        for csv_file, table_name in TABLES:
            path = os.path.join(DATA_DIR, csv_file)
            if not os.path.exists(path):
                print(f"Skipping {table_name}: {path} not found. Run generate_data.py first.")
                continue

            df = pd.read_csv(path)
            df.to_sql(table_name, conn, if_exists="append", index=False)
            print(f"Loaded {len(df)} rows into {table_name}")

    print("Done.")


if __name__ == "__main__":
    main()
