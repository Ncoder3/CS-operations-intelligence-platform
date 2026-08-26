"""
Synthetic data generator for the Customer Success Operations Intelligence Platform.

Why synthetic (not scraped/public) data:
We don't have access to real CRM data, so we generate it — but generate it with
DELIBERATE correlations, not pure randomness. Each account is assigned a hidden
"risk profile" that drives usage decline, ticket volume, CSAT, and renewal outcome
together. This is what lets the health-score engine in Phase 2 find real signal
instead of scoring noise.

Usage:
    python src/data_generation/generate_data.py --num-accounts 150
"""

import argparse
import random
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)

INDUSTRIES = ["Healthcare", "SaaS", "Finance", "Manufacturing", "Retail", "Education", "Logistics"]
SEGMENTS = ["Enterprise", "Mid-Market", "SMB"]
REGIONS = ["North America", "EMEA", "APAC", "LATAM"]
CSMS = [fake.name() for _ in range(8)]
SALES_OWNERS = [fake.name() for _ in range(6)]
TICKET_CATEGORIES = ["Bug", "Feature Request", "Onboarding", "Billing", "Performance", "Training"]
FEEDBACK_CATEGORIES = ["Support", "Product", "Onboarding", "Performance", "Billing", "Training", "Other"]

# Risk profile: (probability weight, usage_trend, ticket_multiplier, csat_range, renewal_outcome_bias)
RISK_PROFILES = {
    "healthy":  {"weight": 0.55, "usage_trend": (0.0, 0.05),  "ticket_mult": 1.0, "csat_range": (75, 98), "churn_bias": 0.03},
    "monitor":  {"weight": 0.20, "usage_trend": (-0.05, 0.0), "ticket_mult": 1.5, "csat_range": (60, 80), "churn_bias": 0.12},
    "at_risk":  {"weight": 0.15, "usage_trend": (-0.15, -0.05), "ticket_mult": 2.2, "csat_range": (40, 65), "churn_bias": 0.35},
    "critical": {"weight": 0.10, "usage_trend": (-0.30, -0.15), "ticket_mult": 3.5, "csat_range": (15, 45), "churn_bias": 0.65},
}


def pickrisk_profile():
    profiles = list(RISK_PROFILES.keys())
    weights = [RISK_PROFILES[p]["weight"] for p in profiles]
    return random.choices(profiles, weights=weights, k=1)[0]


def generate_accounts(n):
    rows = []
    for account_id in range(1, n + 1):
        start_date = fake.date_between(start_date="-3y", end_date="-30d")
        renewal_date = start_date + timedelta(days=365)
        risk_profile = pickrisk_profile()
        rows.append({
            "account_id": account_id,
            "company_name": fake.company(),
            "industry": random.choice(INDUSTRIES),
            "segment": random.choice(SEGMENTS),
            "region": random.choice(REGIONS),
            "csm_owner": random.choice(CSMS),
            "account_status": "Active",
            "contract_value": round(random.uniform(8_000, 250_000), 2),
            "start_date": start_date,
            "renewal_date": renewal_date,
            "risk_profile": risk_profile,  # internal only, not written to accounts.csv
        })
    return pd.DataFrame(rows)


def generate_contacts(accounts_df):
    rows = []
    contact_id = 1
    for _, acc in accounts_df.iterrows():
        for _ in range(random.randint(1, 4)):
            rows.append({
                "contact_id": contact_id,
                "account_id": acc["account_id"],
                "full_name": fake.name(),
                "role": random.choice(["Admin", "End User", "Executive Sponsor", "Billing Contact"]),
                "department": random.choice(["IT", "Operations", "Finance", "Clinical", "Executive"]),
                "engagement_status": random.choices(["Active", "Inactive"], weights=[0.8, 0.2])[0],
            })
            contact_id += 1
    return pd.DataFrame(rows)


def generate_opportunities(accounts_df):
    rows = []
    for i, acc in enumerate(accounts_df.itertuples(), start=1):
        close_date = acc.start_date - timedelta(days=random.randint(10, 45))
        rows.append({
            "opportunity_id": i,
            "account_id": acc.account_id,
            "sales_owner": random.choice(SALES_OWNERS),
            "opportunity_stage": "Closed Won",
            "amount": acc.contract_value,
            "close_date": close_date,
            "outcome": "Won",
        })
    return pd.DataFrame(rows)


def generate_customer_success(accounts_df):
    rows = []
    for acc in accounts_df.itertuples():
        handoff_created = datetime.combine(acc.start_date, datetime.min.time()) - timedelta(days=random.randint(1, 10))
        # Riskier accounts are more likely to have had a messy handoff
        delay_days = {
            "healthy": random.randint(0, 2),
            "monitor": random.randint(1, 4),
            "at_risk": random.randint(2, 7),
            "critical": random.randint(4, 12),
        }[acc.risk_profile]
        handoff_accepted = handoff_created + timedelta(days=delay_days)
        onboarding_started = handoff_accepted + timedelta(days=random.randint(1, 3))
        onboarding_days = {
            "healthy": random.randint(5, 14),
            "monitor": random.randint(10, 21),
            "at_risk": random.randint(15, 35),
            "critical": random.randint(25, 60),
        }[acc.risk_profile]
        onboarding_completed = onboarding_started + timedelta(days=onboarding_days)
        rows.append({
            "account_id": acc.account_id,
            "csm_owner": acc.csm_owner,
            "handoff_created_at": handoff_created,
            "handoff_accepted_at": handoff_accepted,
            "onboarding_status": "Complete",
            "onboarding_started_at": onboarding_started,
            "onboarding_completed_at": onboarding_completed,
            "success_plan": fake.sentence(nb_words=10),
            "health_status": None,  # filled by Phase 2 scoring engine
        })
    return pd.DataFrame(rows)


def generate_support_tickets(accounts_df):
    rows = []
    ticket_id = 1
    today = datetime.now()
    for acc in accounts_df.itertuples():
        profile = RISK_PROFILES[acc.risk_profile]
        base_tickets = int(random.randint(3, 10) * profile["ticket_mult"])
        for _ in range(base_tickets):
            created = fake.date_time_between(start_date=acc.start_date, end_date=today)
            priority = random.choices(
                ["Low", "Medium", "High", "Critical"],
                weights=[0.4, 0.35, 0.18, 0.07] if acc.risk_profile in ("healthy", "monitor")
                else [0.2, 0.3, 0.3, 0.2],
            )[0]
            sla_hours = {"Low": 72, "Medium": 48, "High": 24, "Critical": 8}[priority]
            # riskier accounts resolve slower relative to SLA
            resolution_multiplier = {"healthy": 0.6, "monitor": 0.9, "at_risk": 1.4, "critical": 2.2}[acc.risk_profile]
            is_resolved = random.random() > (0.05 if acc.risk_profile == "critical" else 0.02)
            resolved = None
            status = "Open"
            if is_resolved:
                resolved = created + timedelta(hours=sla_hours * resolution_multiplier * random.uniform(0.5, 1.5))
                status = "Resolved"
            rows.append({
                "ticket_id": ticket_id,
                "account_id": acc.account_id,
                "priority": priority,
                "category": random.choice(TICKET_CATEGORIES),
                "created_date": created,
                "resolved_date": resolved,
                "sla_hours": sla_hours,
                "status": status,
            })
            ticket_id += 1
    return pd.DataFrame(rows)


def generate_product_usage(accounts_df, months=12):
    rows = []
    usage_id = 1
    today = datetime.now()
    for acc in accounts_df.itertuples():
        profile = RISK_PROFILES[acc.risk_profile]
        trend = random.uniform(*profile["usage_trend"])  # monthly % change
        base_sessions = random.randint(200, 2000)
        base_users = random.randint(5, 200)
        base_feature_pct = random.uniform(30, 70)
        for m in range(months, 0, -1):
            usage_date = (today - timedelta(days=30 * m)).replace(day=1).date()
            decay = (1 + trend) ** (months - m)
            sessions = max(0, int(base_sessions * decay * random.uniform(0.9, 1.1)))
            active_users = max(0, int(base_users * decay * random.uniform(0.9, 1.1)))
            feature_pct = min(100, max(0, base_feature_pct * decay * random.uniform(0.9, 1.1)))
            rows.append({
                "usage_id": usage_id,
                "account_id": acc.account_id,
                "usage_date": usage_date,
                "sessions": sessions,
                "active_users": active_users,
                "feature_usage_pct": round(feature_pct, 2),
            })
            usage_id += 1
    return pd.DataFrame(rows)


def generate_surveys(accounts_df):
    rows = []
    survey_id = 1
    today = datetime.now()
    for acc in accounts_df.itertuples():
        profile = RISK_PROFILES[acc.risk_profile]
        for _ in range(random.randint(1, 3)):
            survey_date = fake.date_between(start_date=acc.start_date, end_date=today.date())
            csat = round(random.uniform(*profile["csat_range"]), 2)
            # NPS roughly correlated to CSAT
            nps = int(np.clip((csat - 50) * 2 + random.uniform(-15, 15), -100, 100))
            rows.append({
                "survey_id": survey_id,
                "account_id": acc.account_id,
                "survey_date": survey_date,
                "csat_score": csat,
                "nps_score": nps,
                "feedback_category": random.choice(FEEDBACK_CATEGORIES),
            })
            survey_id += 1
    return pd.DataFrame(rows)


def generate_renewals(accounts_df):
    rows = []
    for i, acc in enumerate(accounts_df.itertuples(), start=1):
        profile = RISK_PROFILES[acc.risk_profile]
        churned = random.random() < profile["churn_bias"]
        if churned:
            status = "Churned"
            churn_reason = random.choice([
                "Low product adoption", "Budget cuts", "Switched to competitor",
                "Poor support experience", "Lack of executive sponsorship",
            ])
            value = 0
        else:
            status = random.choices(["Renewed", "Pending", "At Risk"], weights=[0.7, 0.2, 0.1])[0]
            churn_reason = None
            value = acc.contract_value * random.uniform(0.95, 1.15)
        rows.append({
            "renewal_id": i,
            "account_id": acc.account_id,
            "renewal_date": acc.renewal_date,
            "renewal_value": round(value, 2),
            "renewal_status": status,
            "churn_reason": churn_reason,
        })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic Customer Success dataset")
    parser.add_argument("--num-accounts", type=int, default=150)
    parser.add_argument("--out-dir", type=str, default="data/generated")
    args = parser.parse_args()

    accounts_df = generate_accounts(args.num_accounts)
    contacts_df = generate_contacts(accounts_df)
    opportunities_df = generate_opportunities(accounts_df)
    cs_df = generate_customer_success(accounts_df)
    tickets_df = generate_support_tickets(accounts_df)
    usage_df = generate_product_usage(accounts_df)
    surveys_df = generate_surveys(accounts_df)
    renewals_df = generate_renewals(accounts_df)

    # Drop internal-only helper column before writing accounts.csv
    accounts_out = accounts_df.drop(columns=["risk_profile"])

    import os
    os.makedirs(args.out_dir, exist_ok=True)

    accounts_out.to_csv(f"{args.out_dir}/accounts.csv", index=False)
    contacts_df.to_csv(f"{args.out_dir}/contacts.csv", index=False)
    opportunities_df.to_csv(f"{args.out_dir}/opportunities.csv", index=False)
    cs_df.to_csv(f"{args.out_dir}/customer_success.csv", index=False)
    tickets_df.to_csv(f"{args.out_dir}/support_tickets.csv", index=False)
    usage_df.to_csv(f"{args.out_dir}/product_usage.csv", index=False)
    surveys_df.to_csv(f"{args.out_dir}/surveys.csv", index=False)
    renewals_df.to_csv(f"{args.out_dir}/renewals.csv", index=False)

    print(f"Generated {args.num_accounts} accounts and related records into {args.out_dir}/")
    print(f"  contacts: {len(contacts_df)}")
    print(f"  opportunities: {len(opportunities_df)}")
    print(f"  support_tickets: {len(tickets_df)}")
    print(f"  product_usage: {len(usage_df)}")
    print(f"  surveys: {len(surveys_df)}")
    print(f"  renewals: {len(renewals_df)}")


if __name__ == "__main__":
    main()
