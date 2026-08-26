-- ============================================================
-- Reporting views for Power BI.
--
-- Why views instead of pointing Power BI straight at raw tables:
-- business logic (SLA breach definition, latest-survey-per-account,
-- ticket aging) would otherwise get re-implemented in DAX, and DAX
-- and Python would quietly drift out of sync. Keeping it in SQL means
-- one definition, testable the same way the Python logic is.
-- See docs/decisions/003-reporting-layer.md
-- ============================================================

-- One row per account: the main fact table for Power BI, latest
-- health score + core account attributes + latest renewal info joined in.
CREATE OR REPLACE VIEW vw_account_health AS
SELECT
    a.account_id,
    a.company_name,
    a.industry,
    a.segment,
    a.region,
    a.csm_owner,
    a.account_status,
    a.contract_value,
    a.start_date,
    a.renewal_date,
    hs.score_date,
    hs.engagement_score,
    hs.support_score,
    hs.csat_score,
    hs.nps_score,
    hs.onboarding_score,
    hs.overall_score,
    hs.health_status,
    hs.risk_drivers,
    r.renewal_status,
    r.renewal_value,
    r.churn_reason,
    (a.renewal_date - CURRENT_DATE) AS days_to_renewal,
    -- renewal_date is the account's original single renewal date and can be
    -- in the past for older accounts; roll it forward to the next annual
    -- cycle so "renewal pipeline" visuals show a forward-looking date.
    a.renewal_date
        + (GREATEST(0, CEIL((CURRENT_DATE - a.renewal_date) / 365.0)) * 365)::int AS next_renewal_date,
    (a.renewal_date + (GREATEST(0, CEIL((CURRENT_DATE - a.renewal_date) / 365.0)) * 365)::int) - CURRENT_DATE
        AS days_to_next_renewal
FROM accounts a
LEFT JOIN LATERAL (
    SELECT * FROM health_scores h
    WHERE h.account_id = a.account_id
    ORDER BY h.score_date DESC
    LIMIT 1
) hs ON true
LEFT JOIN renewals r ON r.account_id = a.account_id;


-- Support ticket fact table with SLA breach pre-calculated
CREATE OR REPLACE VIEW vw_ticket_sla AS
SELECT
    t.ticket_id,
    t.account_id,
    a.company_name,
    a.csm_owner,
    a.segment,
    t.priority,
    t.category,
    t.created_date,
    t.resolved_date,
    t.sla_hours,
    t.status,
    ROUND(EXTRACT(EPOCH FROM (COALESCE(t.resolved_date, NOW()) - t.created_date)) / 3600.0, 1) AS age_or_resolution_hours,
    CASE
        WHEN t.resolved_date IS NOT NULL
             AND EXTRACT(EPOCH FROM (t.resolved_date - t.created_date)) / 3600.0 > t.sla_hours
            THEN TRUE
        WHEN t.resolved_date IS NULL
             AND EXTRACT(EPOCH FROM (NOW() - t.created_date)) / 3600.0 > t.sla_hours
            THEN TRUE
        ELSE FALSE
    END AS sla_breached
FROM support_tickets t
JOIN accounts a ON a.account_id = t.account_id;


-- Monthly usage trend, joined to account attributes for slicing
CREATE OR REPLACE VIEW vw_usage_trend AS
SELECT
    u.account_id,
    a.company_name,
    a.segment,
    a.csm_owner,
    u.usage_date,
    u.sessions,
    u.active_users,
    u.feature_usage_pct
FROM product_usage u
JOIN accounts a ON a.account_id = u.account_id;


-- Latest survey response per account (CSAT/NPS trend uses all rows;
-- this view is for "current" snapshots on the health dashboard)
CREATE OR REPLACE VIEW vw_latest_survey AS
SELECT DISTINCT ON (s.account_id)
    s.account_id,
    s.survey_date,
    s.csat_score,
    s.nps_score,
    s.feedback_category
FROM surveys s
ORDER BY s.account_id, s.survey_date DESC;


-- CSM-level rollup: the source table for the CSM Performance dashboard
CREATE OR REPLACE VIEW vw_csm_performance AS
SELECT
    a.csm_owner,
    COUNT(DISTINCT a.account_id) AS total_accounts,
    COUNT(DISTINCT a.account_id) FILTER (WHERE h.health_status = 'Critical') AS critical_accounts,
    COUNT(DISTINCT a.account_id) FILTER (WHERE h.health_status = 'At Risk') AS at_risk_accounts,
    ROUND(AVG(h.overall_score), 1) AS avg_health_score,
    ROUND(AVG(h.csat_score), 1) AS avg_csat,
    ROUND(AVG(h.nps_score), 1) AS avg_nps,
    COUNT(DISTINCT t.ticket_id) FILTER (WHERE t.status = 'Open') AS open_tickets,
    SUM(a.contract_value) AS total_portfolio_value
FROM accounts a
LEFT JOIN vw_account_health h ON h.account_id = a.account_id
LEFT JOIN support_tickets t ON t.account_id = a.account_id
GROUP BY a.csm_owner;


-- Action Center enriched with account context, for the operational
-- table visual on the Customer Health dashboard
CREATE OR REPLACE VIEW vw_action_center AS
SELECT
    ac.action_id,
    ac.account_id,
    a.company_name,
    a.segment,
    ac.risk_level,
    ac.reason,
    ac.recommended_action,
    ac.owner,
    ac.due_date,
    ac.status,
    ac.created_at
FROM action_center ac
JOIN accounts a ON a.account_id = ac.account_id;
