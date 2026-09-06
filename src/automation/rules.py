"""
Business rules for the Action Center: what happens when an account is
flagged at a given risk level. Kept separate from health_score.py (which
only computes scores) and from the scheduler (which only orchestrates)
so the actual "if risk then action" logic lives in exactly one place.

If you change an SLA target or an escalation rule, this is the only file
that should need editing.
"""

from datetime import timedelta

import pandas as pd

# risk_level -> (base recommended action, base due-in-days)
RISK_ACTIONS = {
    "Critical": ("CSM intervention required within 48 hours", 2),
    "At Risk": ("Schedule account review call this week", 5),
    "Monitor": ("Add to weekly watchlist review", 14),
}

# An account within this many days of renewal gets its due date escalated,
# regardless of risk level — matches the "Renewal Risk" rule from the
# original spec, applied as urgency, not as a scoring input (see ADR 002).
RENEWAL_URGENCY_WINDOW_DAYS = 60
RENEWAL_URGENCY_DUE_DAYS = 2


def build_action_center(scores_df: pd.DataFrame, accounts_df: pd.DataFrame, today=None) -> pd.DataFrame:
    """
    scores_df: output of compute_health_scores() — needs account_id,
        health_status, risk_drivers.
    accounts_df: needs account_id, csm_owner, renewal_date.
    """
    import datetime as _dt
    today = today or _dt.datetime.now().date()

    at_risk = scores_df[scores_df["health_status"].isin(["Critical", "At Risk", "Monitor"])].copy()
    at_risk = at_risk.merge(accounts_df[["account_id", "csm_owner", "renewal_date"]], on="account_id", how="left")

    rows = []
    for _, r in at_risk.iterrows():
        action, due_in_days = RISK_ACTIONS[r["health_status"]]

        renewal_date = pd.to_datetime(r["renewal_date"]).date() if pd.notna(r["renewal_date"]) else None
        days_to_renewal = (renewal_date - today).days if renewal_date else None
        if days_to_renewal is not None and 0 <= days_to_renewal <= RENEWAL_URGENCY_WINDOW_DAYS:
            due_in_days = min(due_in_days, RENEWAL_URGENCY_DUE_DAYS)
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
    return pd.DataFrame(rows, columns=[
        "account_id", "risk_level", "reason", "recommended_action", "owner", "due_date", "status",
    ])
