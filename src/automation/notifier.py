"""
Digest generator. Compares the health_scores from the run that just
completed against the previous run's scores (by score_date), so alerts are
about what CHANGED — not the same 30 critical accounts repeated every day,
which is how real alerting systems get ignored.

Writes a Markdown report to data/reports/ and prints a console summary.
Email sending is optional and off by default (see send_email_if_configured).

Usage (called by scheduler.py, but can run standalone against the latest run):
    python src/automation/notifier.py
"""

import os
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://csops_admin:csops_pass@localhost:5432/csops")
REPORTS_DIR = "data/reports"
SCORE_DROP_THRESHOLD = 10  # points; flag accounts that dropped by more than this


def get_current_and_previous_scores(engine):
    dates = pd.read_sql(
        "SELECT DISTINCT score_date FROM health_scores ORDER BY score_date DESC LIMIT 2", engine
    )["score_date"].tolist()

    if not dates:
        return None, None, None, None

    current_date = dates[0]
    current = pd.read_sql(
        "SELECT account_id, health_status, overall_score, risk_drivers FROM health_scores WHERE score_date = %(d)s",
        engine, params={"d": current_date},
    )

    previous_date = dates[1] if len(dates) > 1 else None
    if previous_date is not None:
        previous = pd.read_sql(
            "SELECT account_id, health_status, overall_score FROM health_scores WHERE score_date = %(d)s",
            engine, params={"d": previous_date},
        )
    else:
        previous = pd.DataFrame(columns=["account_id", "health_status", "overall_score"])

    return current, previous, current_date, previous_date


def find_newly_critical(current: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    prev_status = previous.set_index("account_id")["health_status"] if len(previous) else pd.Series(dtype=object)
    def is_new_critical(row):
        was = prev_status.get(row["account_id"])  # None if first-ever run
        return row["health_status"] == "Critical" and was != "Critical"
    mask = current.apply(is_new_critical, axis=1)
    return current[mask]


def find_score_drops(current: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    if not len(previous):
        return pd.DataFrame(columns=["account_id", "overall_score", "previous_score", "drop"])
    merged = current.merge(previous, on="account_id", suffixes=("", "_previous"))
    merged["drop"] = merged["overall_score_previous"] - merged["overall_score"]
    return merged[merged["drop"] >= SCORE_DROP_THRESHOLD].sort_values("drop", ascending=False)


def get_urgent_action_items(engine, days_ahead: int = 2) -> pd.DataFrame:
    cutoff = (datetime.now().date() + timedelta(days=days_ahead))
    return pd.read_sql(
        """
        SELECT ac.account_id, a.company_name, ac.risk_level, ac.recommended_action,
               ac.owner, ac.due_date
        FROM action_center ac
        JOIN accounts a ON a.account_id = ac.account_id
        WHERE ac.due_date <= %(cutoff)s AND ac.status = 'Open'
        ORDER BY ac.due_date ASC
        """,
        engine, params={"cutoff": cutoff},
    )


def get_account_names(engine, account_ids) -> pd.DataFrame:
    if not len(account_ids):
        return pd.DataFrame(columns=["account_id", "company_name"])
    # psycopg2 can't adapt numpy int types (e.g. numpy.int64 from a pandas
    # Series) directly to a SQL array parameter — cast to native Python int.
    ids = [int(i) for i in account_ids]
    return pd.read_sql(
        "SELECT account_id, company_name FROM accounts WHERE account_id = ANY(%(ids)s)",
        engine, params={"ids": ids},
    )


def build_digest_markdown(summary: dict, newly_critical: pd.DataFrame, score_drops: pd.DataFrame,
                           urgent_actions: pd.DataFrame, names: pd.DataFrame, current_date, previous_date) -> str:
    names_map = names.set_index("account_id")["company_name"].to_dict() if len(names) else {}
    lines = [
        f"# Customer Success Daily Digest — {current_date}",
        "",
        f"Compared against previous run: {previous_date if previous_date else 'none (first run)'}",
        "",
        "## Summary",
        f"- Data Quality Score: **{summary['data_quality_score']}/100**",
        f"- Total accounts: {summary['total_accounts']}",
        f"- Healthy: {summary['healthy_count']} · Monitor: {summary['monitor_count']} "
        f"· At Risk: {summary['at_risk_count']} · Critical: {summary['critical_count']}",
        f"- Open action items: {summary['action_items_created']}",
        "",
    ]

    lines.append("## Newly Critical Accounts")
    if len(newly_critical):
        for _, r in newly_critical.iterrows():
            name = names_map.get(r["account_id"], f"Account {r['account_id']}")
            lines.append(f"- **{name}** (score {r['overall_score']:.0f}) — {r['risk_drivers']}")
    else:
        lines.append("- None. No accounts newly entered Critical status since the last run.")
    lines.append("")

    lines.append(f"## Accounts With Significant Score Drops (>{SCORE_DROP_THRESHOLD} pts)")
    if len(score_drops):
        for _, r in score_drops.iterrows():
            name = names_map.get(r["account_id"], f"Account {r['account_id']}")
            lines.append(f"- **{name}**: {r['overall_score_previous']:.0f} -> {r['overall_score']:.0f} "
                         f"(-{r['drop']:.0f})")
    else:
        lines.append("- None.")
    lines.append("")

    lines.append("## Action Items Due in the Next 2 Days")
    if len(urgent_actions):
        for _, r in urgent_actions.iterrows():
            lines.append(f"- **{r['company_name']}** ({r['risk_level']}) — {r['recommended_action']} "
                         f"— owner: {r['owner']} — due {r['due_date']}")
    else:
        lines.append("- None.")
    lines.append("")

    return "\n".join(lines)


def send_email_if_configured(subject: str, body: str):
    """
    Only runs if all SMTP_* env vars are set. Safe to leave unconfigured —
    this function silently no-ops rather than failing the pipeline, since a
    portfolio project shouldn't require a live mail server to demo.
    """
    host = os.getenv("SMTP_HOST")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    to_addr = os.getenv("ALERT_EMAIL_TO")
    if not all([host, user, password, to_addr]):
        print("SMTP not configured (SMTP_HOST/SMTP_USER/SMTP_PASSWORD/ALERT_EMAIL_TO) — skipping email, digest file was still written.")
        return

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr

    port = int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(user, [to_addr], msg.as_string())
    print(f"Digest emailed to {to_addr}")


def generate_digest(engine, summary: dict) -> str:
    """Returns the path to the written digest file."""
    current, previous, current_date, previous_date = get_current_and_previous_scores(engine)
    if current is None:
        raise RuntimeError("No health_scores found — run the scoring pipeline before generating a digest.")

    newly_critical = find_newly_critical(current, previous)
    score_drops = find_score_drops(current, previous)
    urgent_actions = get_urgent_action_items(engine)

    all_ids = pd.concat([newly_critical["account_id"], score_drops["account_id"]]) if len(score_drops) or len(newly_critical) else pd.Series(dtype=int)
    names = get_account_names(engine, all_ids.unique())

    markdown = build_digest_markdown(summary, newly_critical, score_drops, urgent_actions, names, current_date, previous_date)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    out_path = os.path.join(REPORTS_DIR, f"digest_{current_date}.md")
    with open(out_path, "w") as f:
        f.write(markdown)

    print(f"\nDigest written to {out_path}")
    print(f"  Newly critical: {len(newly_critical)} | Score drops: {len(score_drops)} | Urgent actions: {len(urgent_actions)}")

    send_email_if_configured(f"CS Ops Daily Digest — {current_date}", markdown)

    return out_path


if __name__ == "__main__":
    engine = create_engine(DATABASE_URL)
    # Standalone mode: rebuild a minimal summary from the DB rather than re-running the pipeline
    current, _, current_date, _ = get_current_and_previous_scores(engine)
    if current is None:
        raise SystemExit("No health_scores found. Run src/scoring/run_scoring.py first.")
    status_counts = current["health_status"].value_counts().to_dict()
    quality_score = pd.read_sql("SELECT COUNT(*) AS n FROM accounts", engine)["n"].iloc[0]  # placeholder if run standalone
    summary = {
        "data_quality_score": "N/A (standalone run)",
        "total_accounts": len(current),
        "healthy_count": status_counts.get("Healthy", 0),
        "monitor_count": status_counts.get("Monitor", 0),
        "at_risk_count": status_counts.get("At Risk", 0),
        "critical_count": status_counts.get("Critical", 0),
        "action_items_created": pd.read_sql("SELECT COUNT(*) AS n FROM action_center", engine)["n"].iloc[0],
    }
    generate_digest(engine, summary)
