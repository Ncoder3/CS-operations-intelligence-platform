"""
Health Score Engine.

Computes a transparent, explainable health score per account from five
components. Weights and thresholds are constants at the top of this file —
change them there, not scattered through the code, so the scoring logic
stays auditable.

Design note on what's NOT included: the original project spec included a
"Renewal Proximity" score component and a "Payment/Account Status" component.
Both were dropped here in favor of an "Onboarding & Handoff Health" component.
Reasoning: renewal_status/churn_reason in our data represents a KNOWN OUTCOME,
not a leading indicator — baking it into the score would be circular (the
score would partly explain itself). Renewal proximity is instead used as an
URGENCY MULTIPLIER in the Action Center (src/scoring/run_scoring.py), which
is a more honest use of that field. See docs/decisions/002-scoring-engine.md.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

import numpy as np
import pandas as pd

WEIGHTS = {
    "engagement": 0.25,
    "support": 0.20,
    "csat": 0.20,
    "nps": 0.15,
    "onboarding": 0.20,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9

STATUS_THRESHOLDS = [
    (80, 100, "Healthy"),
    (65, 79.999, "Monitor"),
    (45, 64.999, "At Risk"),
    (0, 44.999, "Critical"),
]

HANDOFF_SLA_DAYS = 3
ONBOARDING_SLA_DAYS = 14


def classify_status(score: float) -> str:
    for low, high, label in STATUS_THRESHOLDS:
        if low <= score <= high:
            return label
    return "Unknown"


def _clip(x, lo=0, hi=100):
    return max(lo, min(hi, x))


def score_engagement(usage_df: pd.DataFrame) -> pd.DataFrame:
    """Compares last 3 months of usage vs first 3 months per account."""
    results = []
    for account_id, g in usage_df.sort_values("usage_date").groupby("account_id"):
        g = g.reset_index(drop=True)
        if len(g) < 4:
            results.append({"account_id": account_id, "engagement_score": 60.0})  # insufficient history -> neutral
            continue
        g["index_val"] = g["sessions"].rank(pct=True) * 0.4 + \
                          g["active_users"].rank(pct=True) * 0.4 + \
                          g["feature_usage_pct"].rank(pct=True) * 0.2
        early = g.iloc[: max(1, len(g) // 4)]["index_val"].mean()
        late = g.iloc[-max(1, len(g) // 4):]["index_val"].mean()
        pct_change = 0.0 if early == 0 else (late - early) / (early + 1e-9)
        score = _clip(50 + pct_change * 150)
        results.append({"account_id": account_id, "engagement_score": round(score, 2)})
    return pd.DataFrame(results)


def score_support(tickets_df: pd.DataFrame) -> pd.DataFrame:
    results = []
    for account_id, g in tickets_df.groupby("account_id"):
        total = len(g)
        critical_high_pct = ((g["priority"].isin(["High", "Critical"])).sum()) / total if total else 0

        created = pd.to_datetime(g["created_date"])
        resolved = pd.to_datetime(g["resolved_date"])
        resolution_hours = (resolved - created).dt.total_seconds() / 3600
        breached = resolution_hours > g["sla_hours"]
        # unresolved tickets past their SLA also count as breaches
        now = pd.Timestamp.now()
        still_open_breach = g["resolved_date"].isna() & ((now - created).dt.total_seconds() / 3600 > g["sla_hours"])
        breach_pct = (breached.fillna(False) | still_open_breach).sum() / total if total else 0

        open_count = (g["status"] == "Open").sum()

        score = 100
        score -= critical_high_pct * 40
        score -= breach_pct * 40
        score -= min(20, open_count * 3)
        results.append({"account_id": account_id, "support_score": round(_clip(score), 2)})
    return pd.DataFrame(results)


def score_csat_nps(surveys_df: pd.DataFrame) -> pd.DataFrame:
    latest = surveys_df.sort_values("survey_date").groupby("account_id").tail(1)
    latest = latest[["account_id", "csat_score", "nps_score"]].copy()
    latest["csat_health_score"] = latest["csat_score"].clip(0, 100)
    latest["nps_health_score"] = ((latest["nps_score"] + 100) / 2).clip(0, 100)
    return latest[["account_id", "csat_health_score", "nps_health_score"]]


def score_onboarding(cs_df: pd.DataFrame) -> pd.DataFrame:
    results = []
    for _, row in cs_df.iterrows():
        score = 100.0
        if pd.notna(row.get("handoff_created_at")) and pd.notna(row.get("handoff_accepted_at")):
            handoff_days = (pd.to_datetime(row["handoff_accepted_at"]) - pd.to_datetime(row["handoff_created_at"])).days
            if handoff_days > HANDOFF_SLA_DAYS:
                score -= min(30, (handoff_days - HANDOFF_SLA_DAYS) * 4)
        if pd.notna(row.get("onboarding_started_at")) and pd.notna(row.get("onboarding_completed_at")):
            onboarding_days = (pd.to_datetime(row["onboarding_completed_at"]) - pd.to_datetime(row["onboarding_started_at"])).days
            if onboarding_days > ONBOARDING_SLA_DAYS:
                score -= min(50, (onboarding_days - ONBOARDING_SLA_DAYS) * 2)
        results.append({"account_id": row["account_id"], "onboarding_score": round(_clip(score), 2)})
    return pd.DataFrame(results)


def build_risk_drivers(row: pd.Series) -> str:
    """Returns a short, human-readable explanation of why the score is what it is."""
    drivers = []
    if row["engagement_score"] < 50:
        drivers.append(f"product usage declining (engagement {row['engagement_score']:.0f}/100)")
    if row["support_score"] < 50:
        drivers.append(f"high support burden / SLA breaches (support {row['support_score']:.0f}/100)")
    if row["csat_health_score"] < 60:
        drivers.append(f"low CSAT ({row['csat_health_score']:.0f}/100)")
    if row["nps_health_score"] < 50:
        drivers.append(f"negative NPS trend ({row['nps_health_score']:.0f}/100)")
    if row["onboarding_score"] < 60:
        drivers.append(f"slow onboarding/handoff (onboarding {row['onboarding_score']:.0f}/100)")
    if not drivers:
        return "No significant risk drivers"
    return "; ".join(drivers)


def compute_health_scores(tables: Dict[str, pd.DataFrame], score_date: Optional[str] = None) -> pd.DataFrame:
    """
    tables must include: accounts, product_usage, support_tickets, surveys, customer_success
    Returns one row per account with component scores, overall score, status, and drivers.
    """
    score_date = score_date or datetime.now().strftime("%Y-%m-%d")

    accounts = tables["accounts"][["account_id"]].copy()

    engagement = score_engagement(tables["product_usage"])
    support = score_support(tables["support_tickets"])
    csat_nps = score_csat_nps(tables["surveys"])
    onboarding = score_onboarding(tables["customer_success"])

    df = accounts.merge(engagement, on="account_id", how="left") \
                 .merge(support, on="account_id", how="left") \
                 .merge(csat_nps, on="account_id", how="left") \
                 .merge(onboarding, on="account_id", how="left")

    # Neutral fallback (50) for accounts missing a given signal entirely,
    # rather than silently dropping them from the report.
    for col in ["engagement_score", "support_score", "csat_health_score", "nps_health_score", "onboarding_score"]:
        df[col] = df[col].fillna(50.0)

    df["overall_score"] = (
        df["engagement_score"] * WEIGHTS["engagement"]
        + df["support_score"] * WEIGHTS["support"]
        + df["csat_health_score"] * WEIGHTS["csat"]
        + df["nps_health_score"] * WEIGHTS["nps"]
        + df["onboarding_score"] * WEIGHTS["onboarding"]
    ).round(2)

    df["health_status"] = df["overall_score"].apply(classify_status)
    df["risk_drivers"] = df.apply(build_risk_drivers, axis=1)
    df["score_date"] = score_date

    return df.rename(columns={
        "csat_health_score": "csat_score",
        "nps_health_score": "nps_score",
    })[[
        "account_id", "score_date", "engagement_score", "support_score",
        "csat_score", "nps_score", "onboarding_score", "overall_score",
        "health_status", "risk_drivers",
    ]]
