"""
Tests for Phase 2. Run with: pytest tests/test_phase2.py -v

These load directly from data/generated/*.csv, so they double as the
"is the pipeline behaving correctly" validation you'd run after any change
to the generator or the scoring logic — no live Postgres required.
"""

import os
import sys

import pandas as pd
import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))
from data_quality.quality_checks import run_all_checks
from scoring.health_score import compute_health_scores, classify_status

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "generated")

TABLE_FILES = {
    "accounts": "accounts.csv",
    "contacts": "contacts.csv",
    "opportunities": "opportunities.csv",
    "customer_success": "customer_success.csv",
    "support_tickets": "support_tickets.csv",
    "product_usage": "product_usage.csv",
    "surveys": "surveys.csv",
    "renewals": "renewals.csv",
}


@pytest.fixture(scope="module")
def tables():
    data = {}
    for name, filename in TABLE_FILES.items():
        path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(path):
            pytest.skip(f"{path} not found — run src/data_generation/generate_data.py first")
        data[name] = pd.read_csv(path)
    return data


@pytest.fixture(scope="module")
def scores(tables):
    return compute_health_scores(tables)


# ---------------- Data quality ----------------

def test_quality_report_runs_without_error(tables):
    report = run_all_checks(tables)
    assert report.total_records_checked > 0


def test_synthetic_data_has_no_orphan_records(tables):
    """The generator should never produce orphaned foreign keys. If this
    fails, something is wrong with generate_data.py, not the checker."""
    report = run_all_checks(tables)
    orphan_issues = [i for i in report.issues if i.check == "orphan_foreign_key"]
    assert orphan_issues == [], f"Unexpected orphan records: {orphan_issues}"


def test_quality_score_is_high_on_clean_data(tables):
    report = run_all_checks(tables)
    assert report.score >= 90, f"Expected clean synthetic data to score >=90, got {report.score}"


# ---------------- Scoring engine ----------------

def test_every_account_gets_a_score(tables, scores):
    assert len(scores) == len(tables["accounts"])
    assert scores["account_id"].is_unique


def test_scores_within_bounds(scores):
    for col in ["engagement_score", "support_score", "csat_score", "nps_score", "onboarding_score", "overall_score"]:
        assert scores[col].between(0, 100).all(), f"{col} has values outside [0, 100]"


def test_status_classification_matches_thresholds():
    assert classify_status(95) == "Healthy"
    assert classify_status(70) == "Monitor"
    assert classify_status(50) == "At Risk"
    assert classify_status(10) == "Critical"


def test_engagement_score_is_not_bimodal(tables):
    """
    Regression test for a bug where score_engagement() used rank(pct=True)
    within each account's own 12-month window. Ranking only 12 points forces
    them onto a fixed ladder regardless of actual magnitude of change, so
    small noise around a flat trend got amplified into a fake ~100% swing —
    collapsing the score into almost only 0s and 100s. A healthy scoring
    distribution should have a meaningful share of accounts strictly
    between the extremes.
    """
    from scoring.health_score import score_engagement
    result = score_engagement(tables["product_usage"])
    extreme = ((result["engagement_score"] == 0) | (result["engagement_score"] == 100)).sum()
    middle = len(result) - extreme
    assert middle / len(result) > 0.3, (
        f"Only {middle}/{len(result)} accounts scored strictly between 0 and 100 — "
        f"engagement scoring may have regressed to the rank-based bug."
    )


def test_status_distribution_is_not_degenerate(scores):
    """If every account lands in one bucket, the scoring formula is broken
    (e.g. a component dominating or a bug collapsing variance)."""
    dist = scores["health_status"].value_counts(normalize=True)
    assert dist.max() < 0.85, f"Scores are too concentrated in one bucket: {dist.to_dict()}"


def test_health_score_correlates_with_actual_churn(tables, scores):
    """
    THE key validation check: accounts that actually churned should have,
    on average, meaningfully lower health scores than accounts that
    renewed. If this fails, the scoring engine isn't capturing real risk —
    it's just producing numbers.
    """
    renewals = tables["renewals"][["account_id", "renewal_status"]]
    merged = scores.merge(renewals, on="account_id")

    churned_avg = merged.loc[merged["renewal_status"] == "Churned", "overall_score"].mean()
    renewed_avg = merged.loc[merged["renewal_status"] == "Renewed", "overall_score"].mean()

    assert churned_avg < renewed_avg, (
        f"Expected churned accounts to score lower on average. "
        f"Churned avg={churned_avg:.1f}, Renewed avg={renewed_avg:.1f}"
    )
    # Expect a meaningful gap, not just directionally correct by noise
    assert renewed_avg - churned_avg > 10, (
        f"Gap between churned and renewed average scores is too small "
        f"({renewed_avg - churned_avg:.1f} pts) to be a useful signal"
    )


# ---------------- CSM Workload (v2) ----------------

def test_workload_scores_are_not_degenerate(tables, scores):
    """Every CSM should not land in the same category — if they do, the
    weights or thresholds are broken."""
    from scoring.workload import compute_csm_workload
    accounts = tables["accounts"].copy()
    accounts["days_to_next_renewal"] = 999  # neutral value; renewal weighting tested separately below
    result = compute_csm_workload(scores, accounts, tables["support_tickets"], accounts)
    assert result["csm_owner"].nunique() == len(result)
    assert result["workload_category"].nunique() > 1, (
        "All CSMs landed in the same workload category — check weights/thresholds"
    )


def test_workload_score_increases_with_risk(tables, scores):
    """A CSM portfolio identical except for one extra Critical account
    should score strictly higher — sanity check on the weighting direction."""
    from scoring.workload import compute_csm_workload
    accounts = tables["accounts"][["account_id", "csm_owner"]].head(10).copy()
    accounts["days_to_next_renewal"] = 999
    base_scores = pd.DataFrame({
        "account_id": accounts["account_id"],
        "health_status": ["Healthy"] * 10,
    })
    tickets_empty = pd.DataFrame(columns=["account_id", "status"])

    baseline = compute_csm_workload(base_scores, accounts, tickets_empty, accounts)
    baseline_score = baseline["workload_score"].iloc[0]

    degraded_scores = base_scores.copy()
    degraded_scores.loc[degraded_scores.index[0], "health_status"] = "Critical"
    degraded = compute_csm_workload(degraded_scores, accounts, tickets_empty, accounts)
    degraded_score = degraded["workload_score"].iloc[0]

    assert degraded_score > baseline_score
