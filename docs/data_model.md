# Data Model

## accounts
The core entity. One row per customer account.
`account_id, company_name, industry, segment, region, csm_owner, account_status, contract_value, start_date, renewal_date`

## contacts
People at the account. Many-to-one with `accounts`.
`contact_id, account_id, full_name, role, department, engagement_status`

## opportunities
The sales deal that created the account. One-to-one with `accounts` in this
model (each account originates from exactly one Closed Won opportunity).
`opportunity_id, account_id, sales_owner, opportunity_stage, amount, close_date, outcome`

## customer_success
The sales -> CS handoff and onboarding record. One row per account.
`account_id, csm_owner, handoff_created_at, handoff_accepted_at, onboarding_status, onboarding_started_at, onboarding_completed_at, success_plan, health_status`

Handoff duration = `handoff_accepted_at - handoff_created_at`.
Onboarding duration = `onboarding_completed_at - onboarding_started_at`.

## support_tickets
Many-to-one with `accounts`.
`ticket_id, account_id, priority, category, created_date, resolved_date, sla_hours, status`

SLA breach = `resolved_date - created_date > sla_hours` (or still Open past SLA).

## product_usage
Monthly usage snapshot per account (12 months generated).
`usage_id, account_id, usage_date, sessions, active_users, feature_usage_pct`

## surveys
CSAT/NPS responses, 1-3 per account.
`survey_id, account_id, survey_date, csat_score, nps_score, feedback_category`

## renewals
`renewal_id, account_id, renewal_date, renewal_value, renewal_status, churn_reason`

---

## Phase 2 additions

## health_scores
One row per account per scoring run.
`account_id, score_date, engagement_score, support_score, csat_score, nps_score, renewal_score, overall_score, health_status`

Weights (see `src/scoring/`):
Engagement 25% · Support 15% · CSAT 20% · NPS 15% · Renewal proximity 15% · Account status 10%

## action_center
The operational output of the risk engine — what a CSM should actually do.
`action_id, account_id, risk_level, reason, recommended_action, owner, due_date, status, created_at`
