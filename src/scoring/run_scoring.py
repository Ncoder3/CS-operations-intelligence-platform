"""
Phase 2 pipeline: reads all tables from Postgres, runs data quality checks,
computes health scores, writes health_scores, and generates the Action
Center queue for at-risk accounts.

run_pipeline() is the reusable entry point — both this file's CLI and
the Phase 4 scheduler (src/automation/scheduler.py) call it, so there is
exactly one code path that does the actual work.

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
from scoring.workload import compute_csm_workload
from automation.rules import build_action_center

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://csops_admin:csops_pass@localhost:5432/csops")

TABLE_NAMES = [
    "accounts", "contacts", "opportunities", "customer_success",
    "support_tickets", "product_usage", "surveys", "renewals",
]


def load_tables(engine) -> dict:
    return {name: pd.read_sql_table(name, engine) for name in TABLE_NAMES}


def _add_days_to_next_renewal(accounts_df: pd.DataFrame, today=None) -> pd.DataFrame:
    """
    Mirrors the rollover logic in sql/reporting_views.sql (vw_account_health):
    renewal_date is the account's single original date and can be in the
    past for older accounts, so roll it forward to the next annual cycle.
    Computed here too (not just in the view) so workload scoring doesn't
    depend on the views having been applied.
    """
    today = today or datetime.now().date()
    df = accounts_df.copy()
    renewal_date = pd.to_datetime(df["renewal_date"]).dt.date
    days_since = renewal_date.apply(lambda d: (today - d).days)
    cycles = days_since.apply(lambda d: max(0, -(-d // 365)))  # ceil division, floored at 0
    df["days_to_next_renewal"] = [
        (renewal_date.iloc[i] + timedelta(days=int(cycles.iloc[i]) * 365) - today).days
        for i in range(len(df))
    ]
    return df


def run_pipeline(engine, verbose: bool = True) -> dict:
    """
    Runs the full quality -> scoring -> action center -> workload pipeline
    once. Returns a summary dict (used by the scheduler for logging to
    automation_runs and by the notifier for the digest email).
    Raises on failure — caller decides how to log/handle it.
    """
    tables = load_tables(engine)

    report = run_all_checks(tables)
    if verbose:
        print(f"Data Quality Score: {report.score}/100  "
              f"({len(report.issues)} issue types, "
              f"{report.critical_issue_records} critical / {report.warning_issue_records} warning records)")
        if report.issues:
            print(report.as_dataframe().to_string(index=False))

    scores_df = compute_health_scores(tables)
    status_counts = scores_df["health_status"].value_counts().to_dict()
    if verbose:
        print("\nHealth status distribution:", status_counts)

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM health_scores WHERE score_date = :d"), {"d": scores_df["score_date"].iloc[0]})
        scores_df.to_sql("health_scores", conn, if_exists="append", index=False)
    if verbose:
        print(f"Wrote {len(scores_df)} rows to health_scores")

    actions_df = build_action_center(scores_df, tables["accounts"])
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM action_center"))  # simple full-refresh for now
        actions_df.to_sql("action_center", conn, if_exists="append", index=False)
    if verbose:
        print(f"Wrote {len(actions_df)} rows to action_center")

    # --- CSM workload / capacity planning ---
    accounts_with_renewal = _add_days_to_next_renewal(tables["accounts"])
    workload_df = compute_csm_workload(scores_df, accounts_with_renewal, tables["support_tickets"], accounts_with_renewal)
    run_date = scores_df["score_date"].iloc[0]
    workload_df["run_date"] = run_date
    workload_df["workload_category"] = workload_df["workload_category"].astype(str)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM csm_workload WHERE run_date = :d"), {"d": run_date})
        workload_df.to_sql("csm_workload", conn, if_exists="append", index=False)
    if verbose:
        print(f"Wrote {len(workload_df)} rows to csm_workload")
        print(workload_df[["csm_owner", "workload_score", "workload_category"]].to_string(index=False))

    return {
        "data_quality_score": report.score,
        "total_accounts": len(scores_df),
        "healthy_count": status_counts.get("Healthy", 0),
        "monitor_count": status_counts.get("Monitor", 0),
        "at_risk_count": status_counts.get("At Risk", 0),
        "critical_count": status_counts.get("Critical", 0),
        "action_items_created": len(actions_df),
        "overloaded_csm_count": int((workload_df["workload_category"] == "Overloaded").sum()),
        "score_date": str(scores_df["score_date"].iloc[0]),
    }


def main():
    engine = create_engine(DATABASE_URL)
    summary = run_pipeline(engine, verbose=True)
    print("\nDone.", summary)


if __name__ == "__main__":
    main()
