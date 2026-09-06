"""
Automation scheduler. Orchestrates: quality checks -> scoring -> action
center -> digest, and logs every run (success or failure) to the
automation_runs table for auditability.

Two ways to run this in production:

1. Windows Task Scheduler (recommended for this project — no long-running
   process needed):
       python src/automation/scheduler.py --once
   Schedule this command daily via Task Scheduler > Create Basic Task.

2. Built-in loop (useful for local demos without touching Task Scheduler):
       python src/automation/scheduler.py --daemon --time 06:00
   Runs in the foreground and fires once a day at the given time.

Usage:
    python src/automation/scheduler.py --once
    python src/automation/scheduler.py --daemon --time 06:00
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scoring.run_scoring import run_pipeline
from automation.notifier import generate_digest

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://csops_admin:csops_pass@localhost:5432/csops")

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/automation.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("csops.scheduler")


def log_run_to_db(engine, started_at, completed_at, status, summary=None, error_message=None):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO automation_runs
                (run_started_at, run_completed_at, status, data_quality_score,
                 total_accounts, healthy_count, monitor_count, at_risk_count,
                 critical_count, action_items_created, error_message)
            VALUES
                (:started, :completed, :status, :dq, :total, :healthy, :monitor,
                 :at_risk, :critical, :actions, :error)
        """), {
            "started": started_at,
            "completed": completed_at,
            "status": status,
            "dq": summary.get("data_quality_score") if summary else None,
            "total": summary.get("total_accounts") if summary else None,
            "healthy": summary.get("healthy_count") if summary else None,
            "monitor": summary.get("monitor_count") if summary else None,
            "at_risk": summary.get("at_risk_count") if summary else None,
            "critical": summary.get("critical_count") if summary else None,
            "actions": summary.get("action_items_created") if summary else None,
            "error": error_message,
        })


def run_once():
    engine = create_engine(DATABASE_URL)
    started_at = datetime.now()
    logger.info("=== Automation run starting ===")

    try:
        summary = run_pipeline(engine, verbose=False)
        logger.info(
            f"Pipeline complete. Quality={summary['data_quality_score']}, "
            f"Critical={summary['critical_count']}, AtRisk={summary['at_risk_count']}, "
            f"Actions={summary['action_items_created']}"
        )

        digest_path = generate_digest(engine, summary)
        logger.info(f"Digest written: {digest_path}")

        completed_at = datetime.now()
        log_run_to_db(engine, started_at, completed_at, "Success", summary=summary)
        logger.info(f"=== Run completed successfully in {(completed_at - started_at).total_seconds():.1f}s ===")

    except Exception as e:
        completed_at = datetime.now()
        logger.exception("Automation run failed")
        try:
            log_run_to_db(engine, started_at, completed_at, "Failed", error_message=str(e))
        except Exception:
            logger.exception("Additionally failed to write failure record to automation_runs")
        # Don't re-raise in daemon mode — the loop should survive one bad run.
        # In --once mode (e.g. Task Scheduler), a non-zero exit is useful so
        # the task shows as failed, so we re-raise there (see main()).
        raise


def main():
    parser = argparse.ArgumentParser(description="Run or schedule the CS Ops automation pipeline")
    parser.add_argument("--once", action="store_true", help="Run the pipeline a single time and exit")
    parser.add_argument("--daemon", action="store_true", help="Run continuously, firing once a day at --time")
    parser.add_argument("--time", default="06:00", help="Daily run time for --daemon mode, 24h HH:MM (default 06:00)")
    args = parser.parse_args()

    if args.once:
        run_once()
        return

    if args.daemon:
        import schedule
        schedule.every().day.at(args.time).do(lambda: _safe_run_once())
        logger.info(f"Scheduler started. Will run daily at {args.time}. Press Ctrl+C to stop.")
        while True:
            schedule.run_pending()
            time.sleep(30)
        return

    parser.print_help()


def _safe_run_once():
    """Wraps run_once() so the daemon loop survives a failed run instead of crashing."""
    try:
        run_once()
    except Exception:
        logger.error("Run failed but daemon will continue to next scheduled time.")


if __name__ == "__main__":
    main()
