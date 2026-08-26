"""
Data Quality Layer.

Runs a fixed set of checks against the raw tables and produces:
  1. A list of individual issues (for debugging / the data quality dashboard)
  2. A single Data Quality Score per table and an overall score

Design choice: checks operate on plain pandas DataFrames, not directly on the
DB connection. That makes them unit-testable (see tests/test_data_quality.py)
without needing Postgres running, and reusable whether the data came from
CSV or a live query.
"""

from dataclasses import dataclass, field
from typing import Dict, List

import pandas as pd


@dataclass
class QualityIssue:
    table: str
    check: str
    severity: str          # "critical" | "warning"
    record_count: int
    detail: str


@dataclass
class QualityReport:
    issues: List[QualityIssue] = field(default_factory=list)
    total_records_checked: int = 0

    def add(self, table, check, severity, record_count, detail):
        if record_count > 0:
            self.issues.append(QualityIssue(table, check, severity, record_count, detail))

    @property
    def critical_issue_records(self) -> int:
        return sum(i.record_count for i in self.issues if i.severity == "critical")

    @property
    def warning_issue_records(self) -> int:
        return sum(i.record_count for i in self.issues if i.severity == "warning")

    @property
    def score(self) -> float:
        """
        Data Quality Score = 100 - penalty.
        Critical issues penalize 2x as hard as warnings, both scaled by how
        many records they touch relative to the total checked.
        """
        if self.total_records_checked == 0:
            return 100.0
        penalty = (
            (self.critical_issue_records * 2 + self.warning_issue_records)
            / self.total_records_checked
        ) * 100
        return round(max(0.0, 100.0 - penalty), 2)

    def as_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([i.__dict__ for i in self.issues])


def check_missing_required_fields(df: pd.DataFrame, table: str, required_cols: List[str], report: QualityReport):
    for col in required_cols:
        if col not in df.columns:
            continue
        missing = df[col].isna().sum()
        report.add(table, f"missing_{col}", "critical", int(missing), f"{missing} rows missing required field '{col}'")


def check_duplicate_keys(df: pd.DataFrame, table: str, key_col: str, report: QualityReport):
    dupes = df[key_col].duplicated().sum()
    report.add(table, "duplicate_primary_key", "critical", int(dupes), f"{dupes} duplicate values in '{key_col}'")


def check_orphan_records(child_df: pd.DataFrame, child_table: str, fk_col: str,
                          parent_df: pd.DataFrame, parent_key: str, report: QualityReport):
    valid_ids = set(parent_df[parent_key])
    orphans = ~child_df[fk_col].isin(valid_ids)
    n = int(orphans.sum())
    report.add(child_table, "orphan_foreign_key", "critical", n,
               f"{n} rows in {child_table} reference a non-existent {parent_key}")


def check_date_logic(df: pd.DataFrame, table: str, start_col: str, end_col: str, report: QualityReport):
    if start_col not in df.columns or end_col not in df.columns:
        return
    both_present = df[start_col].notna() & df[end_col].notna()
    invalid = both_present & (pd.to_datetime(df[end_col]) < pd.to_datetime(df[start_col]))
    n = int(invalid.sum())
    report.add(table, f"invalid_date_order_{start_col}_{end_col}", "critical", n,
               f"{n} rows where {end_col} is earlier than {start_col}")


def check_value_range(df: pd.DataFrame, table: str, col: str, min_val, max_val, report: QualityReport):
    if col not in df.columns:
        return
    out_of_range = df[col].notna() & ((df[col] < min_val) | (df[col] > max_val))
    n = int(out_of_range.sum())
    report.add(table, f"out_of_range_{col}", "warning", n,
               f"{n} rows where {col} is outside expected range [{min_val}, {max_val}]")


def check_status_consistency(df: pd.DataFrame, table: str, status_col: str, date_col: str,
                              status_requiring_date: str, report: QualityReport):
    """E.g. status='Resolved' but resolved_date is null, or vice versa."""
    inconsistent = (df[status_col] == status_requiring_date) & df[date_col].isna()
    n = int(inconsistent.sum())
    report.add(table, f"status_date_mismatch_{status_col}", "warning", n,
               f"{n} rows with status '{status_requiring_date}' but no {date_col}")


def run_all_checks(tables: Dict[str, pd.DataFrame]) -> QualityReport:
    """
    tables: dict of table_name -> DataFrame, expects keys:
        accounts, contacts, opportunities, customer_success,
        support_tickets, product_usage, surveys, renewals
    """
    report = QualityReport()
    report.total_records_checked = sum(len(df) for df in tables.values())

    accounts = tables["accounts"]

    # --- accounts ---
    check_missing_required_fields(accounts, "accounts",
        ["account_id", "company_name", "account_status", "contract_value"], report)
    check_duplicate_keys(accounts, "accounts", "account_id", report)
    check_value_range(accounts, "accounts", "contract_value", 0, 10_000_000, report)

    # --- contacts ---
    if "contacts" in tables:
        check_missing_required_fields(tables["contacts"], "contacts", ["contact_id", "account_id"], report)
        check_duplicate_keys(tables["contacts"], "contacts", "contact_id", report)
        check_orphan_records(tables["contacts"], "contacts", "account_id", accounts, "account_id", report)

    # --- opportunities ---
    if "opportunities" in tables:
        check_duplicate_keys(tables["opportunities"], "opportunities", "opportunity_id", report)
        check_orphan_records(tables["opportunities"], "opportunities", "account_id", accounts, "account_id", report)

    # --- customer_success ---
    if "customer_success" in tables:
        cs = tables["customer_success"]
        check_orphan_records(cs, "customer_success", "account_id", accounts, "account_id", report)
        check_date_logic(cs, "customer_success", "handoff_created_at", "handoff_accepted_at", report)
        check_date_logic(cs, "customer_success", "onboarding_started_at", "onboarding_completed_at", report)

    # --- support_tickets ---
    if "support_tickets" in tables:
        tix = tables["support_tickets"]
        check_duplicate_keys(tix, "support_tickets", "ticket_id", report)
        check_orphan_records(tix, "support_tickets", "account_id", accounts, "account_id", report)
        check_date_logic(tix, "support_tickets", "created_date", "resolved_date", report)
        check_status_consistency(tix, "support_tickets", "status", "resolved_date", "Resolved", report)

    # --- product_usage ---
    if "product_usage" in tables:
        usage = tables["product_usage"]
        check_orphan_records(usage, "product_usage", "account_id", accounts, "account_id", report)
        check_value_range(usage, "product_usage", "feature_usage_pct", 0, 100, report)

    # --- surveys ---
    if "surveys" in tables:
        surveys = tables["surveys"]
        check_orphan_records(surveys, "surveys", "account_id", accounts, "account_id", report)
        check_value_range(surveys, "surveys", "csat_score", 0, 100, report)
        check_value_range(surveys, "surveys", "nps_score", -100, 100, report)

    # --- renewals ---
    if "renewals" in tables:
        renewals = tables["renewals"]
        check_duplicate_keys(renewals, "renewals", "renewal_id", report)
        check_orphan_records(renewals, "renewals", "account_id", accounts, "account_id", report)

    return report
