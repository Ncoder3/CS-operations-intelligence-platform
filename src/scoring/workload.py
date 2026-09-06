"""
CSM Workload & Capacity Planning.

Answers: "which CSMs need additional headcount support, and which have
room to take on more accounts?" — directly maps to the job requirement to
"facilitate planning for the growth of our customer success team."

Design choice: weighted score, not raw account count. A CSM with 30 healthy
accounts is in a completely different position than one with 30 accounts
where 10 are critical — raw headcount hides that. Weights and thresholds
are constants below; change them here, not scattered elsewhere.
"""

import pandas as pd

# Points contributed per unit — riskier accounts and open tickets cost more
# CSM attention than a healthy account or a routine renewal.
WEIGHT_ACTIVE_ACCOUNT = 1.0
WEIGHT_AT_RISK_ACCOUNT = 2.0
WEIGHT_CRITICAL_ACCOUNT = 3.0
WEIGHT_OPEN_TICKET = 0.5
WEIGHT_UPCOMING_RENEWAL = 1.5  # renewal due within RENEWAL_WINDOW_DAYS

RENEWAL_WINDOW_DAYS = 60

# Category thresholds are quartile-based (computed at runtime from the
# actual distribution), not fixed numbers — a fixed "score > 50 = Overloaded"
# threshold would be meaningless without knowing the portfolio's scale.
# See docs/decisions/005-workload-planning.md for why.
CATEGORY_LABELS = ["Balanced", "Elevated", "High", "Overloaded"]


def compute_csm_workload(scores_df: pd.DataFrame, accounts_df: pd.DataFrame,
                          tickets_df: pd.DataFrame, renewals_upcoming: pd.DataFrame) -> pd.DataFrame:
    """
    scores_df: output of compute_health_scores() — account_id, health_status
    accounts_df: account_id, csm_owner
    tickets_df: account_id, status
    renewals_upcoming: account_id, days_to_next_renewal (or similar) —
        only rows within RENEWAL_WINDOW_DAYS should be passed in, or pass
        the full table and this function will filter if the column exists.
    """
    merged = accounts_df[["account_id", "csm_owner"]].merge(
        scores_df[["account_id", "health_status"]], on="account_id", how="left"
    )

    open_tickets = tickets_df[tickets_df["status"] == "Open"].groupby("account_id").size()
    merged["open_ticket_count"] = merged["account_id"].map(open_tickets).fillna(0)

    if "days_to_next_renewal" in renewals_upcoming.columns:
        upcoming_ids = set(renewals_upcoming.loc[
            renewals_upcoming["days_to_next_renewal"].between(0, RENEWAL_WINDOW_DAYS), "account_id"
        ])
    else:
        upcoming_ids = set()
    merged["upcoming_renewal"] = merged["account_id"].isin(upcoming_ids)

    rows = []
    for csm, g in merged.groupby("csm_owner"):
        total_accounts = len(g)
        at_risk = (g["health_status"] == "At Risk").sum()
        critical = (g["health_status"] == "Critical").sum()
        open_tickets_total = g["open_ticket_count"].sum()
        upcoming_renewals = g["upcoming_renewal"].sum()

        workload_score = (
            total_accounts * WEIGHT_ACTIVE_ACCOUNT
            + at_risk * WEIGHT_AT_RISK_ACCOUNT
            + critical * WEIGHT_CRITICAL_ACCOUNT
            + open_tickets_total * WEIGHT_OPEN_TICKET
            + upcoming_renewals * WEIGHT_UPCOMING_RENEWAL
        )

        rows.append({
            "csm_owner": csm,
            "total_accounts": total_accounts,
            "at_risk_accounts": int(at_risk),
            "critical_accounts": int(critical),
            "open_tickets": int(open_tickets_total),
            "upcoming_renewals": int(upcoming_renewals),
            "workload_score": round(workload_score, 1),
        })

    result = pd.DataFrame(rows)

    # Quartile-based categories: relative to THIS portfolio's actual
    # distribution, not an arbitrary fixed number. With only 8 CSMs (small
    # n), quartiles can tie; qcut with duplicates='drop' handles that by
    # collapsing categories rather than erroring.
    try:
        result["workload_category"] = pd.qcut(
            result["workload_score"], q=4, labels=CATEGORY_LABELS, duplicates="drop"
        )
    except ValueError:
        # Fewer than 4 distinct values overall — fall back to a simple split
        median = result["workload_score"].median()
        result["workload_category"] = result["workload_score"].apply(
            lambda x: "Overloaded" if x > median else "Balanced"
        )

    return result.sort_values("workload_score", ascending=False).reset_index(drop=True)
