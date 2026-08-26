"""
Phase 2 runner: reads all tables from Postgres, runs data quality checks,
computes health scores, writes health_scores, and generates the Action
Center queue for at-risk accounts.

Usage:
    python src/scoring/run_scoring.py
"""

import os
import sys
from datetime import datetime, timedelta

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_quality.quality_checks import run_all_checks
from scoring.health_score import compute_health_scores

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://csops_admin:csops_pass@localhost:5432/csops")

TABLE_NAMES = [
    "accounts", "contacts", "opportunities", "customer_success",
    "support_tickets", "product_usage", "surveys", "renewals",
]

RISK_ACTIONS = {
    "Critical": ("CSM intervention required within 48 hours", 2),
    "At Risk": ("Schedule account review call this week", 5),
    "Monitor": ("Add to weekly watchlist review", 14),
}


def load_tables(engine) -> dict:
    return {name: pd.read_sql_table(name, engine) for name in TABLE_NAMES}


def build_action_center(scores_df: pd.DataFrame, accounts_df: pd.DataFrame, renewals_df: pd.DataFrame) -> pd.DataFrame:
    at_risk = scores_df[scores_df["health_status"].isin(["Critical", "At Risk", "Monitor"])].copy()
    at_risk = at_risk.merge(accounts_df[["account_id", "csm_owner", "renewal_date"]], on="account_id", how="left")

    rows = []
    today = datetime.now().date()
    for _, r in at_risk.iterrows():
        action, due_in_days = RISK_ACTIONS[r["health_status"]]
        # Urgency multiplier: renewal within 60 days escalates the due date, not the score
        renewal_date = pd.to_datetime(r["renewal_date"]).date() if pd.notna(r["renewal_date"]) else None
        days_to_renewal = (renewal_date - today).days if renewal_date else None
        if days_to_renewal is not None and 0 <= days_to_renewal <= 60:
            due_in_days = min(due_in_days, 2)
            action = f"{action} (renewal in {days_to_renewal} days)"

        rows.append({
            "account_id": r["account_id"],
            "risk_level": r["health_status"],
            "reason": r["risk_drivers"],
            "recommended_action": action,
            "owner": r["csm_owner"],
            "due_date": today + timedelta(days=due_in_days),
            "status": "Open",
        })
    return pd.DataFrame(rows)


def main():
    engine = create_engine(DATABASE_URL)
    tables = load_tables(engine)

    # --- Data quality gate ---
    print("Running data quality checks...")
    report = run_all_checks(tables)
    print(f"Data Quality Score: {report.score}/100  "
          f"({len(report.issues)} issue types, "
          f"{report.critical_issue_records} critical / {report.warning_issue_records} warning records)")
    if report.issues:
        print(report.as_dataframe().to_string(index=False))

    # --- Scoring ---
    print("\nComputing health scores...")
    scores_df = compute_health_scores(tables)
    print(scores_df["health_status"].value_counts())

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM health_scores WHERE score_date = :d"), {"d": scores_df["score_date"].iloc[0]})
        scores_df.to_sql("health_scores", conn, if_exists="append", index=False)
    print(f"Wrote {len(scores_df)} rows to health_scores")

    # --- Action Center ---
    print("\nBuilding Action Center queue...")
    actions_df = build_action_center(scores_df, tables["accounts"], tables["renewals"])
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM action_center"))  # simple full-refresh for now
        actions_df.to_sql("action_center", conn, if_exists="append", index=False)
    print(f"Wrote {len(actions_df)} rows to action_center")

    print("\nDone.")


if __name__ == "__main__":
    main()
