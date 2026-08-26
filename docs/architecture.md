# Architecture

```
 DATA SOURCES (synthetic)          BUSINESS WORKFLOWS MODELED
 accounts, contacts,                Sales -> CS handoff
 opportunities, tickets,            Onboarding
 usage, surveys, renewals           Support
                                     Renewal
        │                                │
        └────────────────┬───────────────┘
                          ▼
              PYTHON DATA GENERATION
              (src/data_generation)
                          │
                          ▼
                  CSV (data/generated)
                          │
                          ▼
              PYTHON ETL (src/etl)
                          │
                          ▼
               POSTGRESQL (Docker)
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
      DATA QUALITY   HEALTH SCORE   RISK / SLA
        (Phase 2)      ENGINE        DETECTION
                          │
                          ▼
                      POWER BI
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
        Executive      Customer      CSM
        Overview       Health        Performance
                          │
                          ▼
                 AUTOMATION LAYER
              (src/automation, Phase 4)
                          │
                          ▼
                   ACTION CENTER
```

## Design decisions

- **Synthetic data over scraped/public data**: no legitimate public dataset
  matches a CRM + CS operational model. The generator instead assigns each
  account a hidden risk profile that correlates usage, tickets, CSAT, and
  renewal outcome — so downstream scoring has real signal to detect, not
  random noise. This is documented explicitly rather than presented as real
  customer data.
- **PostgreSQL over flat files**: models the account -> tickets/usage/surveys
  relationships properly and is what a real CS ops stack would use.
- **Python for scoring/automation, not SQL views only**: keeps the health
  score formula, weights, and thresholds in one readable, testable place
  (`src/scoring/`) rather than buried in nested SQL.
- **Power BI over embedding charts in Python**: matches what CS/RevOps teams
  actually use day to day; screenshots + .pbix are committed so the project
  is reviewable without opening Power BI.
