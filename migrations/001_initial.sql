-- SRE + FinOps Platform — Initial Schema
-- 16 tables for the MVP

CREATE TABLE IF NOT EXISTS cloud_accounts (
    id              TEXT PRIMARY KEY,
    provider        TEXT NOT NULL DEFAULT 'aws',
    name            TEXT NOT NULL,
    config          TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'active',
    last_synced     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scans (
    id                      TEXT PRIMARY KEY,
    account_id              TEXT,
    status                  TEXT NOT NULL DEFAULT 'pending',
    started_at              TEXT,
    completed_at            TEXT,
    total_findings          INTEGER NOT NULL DEFAULT 0,
    total_monthly_savings   REAL NOT NULL DEFAULT 0.0,
    checks_run              TEXT DEFAULT '[]',
    error_message           TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (account_id) REFERENCES cloud_accounts(id)
);

CREATE TABLE IF NOT EXISTS findings (
    id                          TEXT PRIMARY KEY,
    scan_id                     TEXT NOT NULL,
    account_id                  TEXT NOT NULL,
    check_name                  TEXT NOT NULL,
    resource_type               TEXT NOT NULL,
    resource_id                 TEXT NOT NULL,
    resource_name               TEXT DEFAULT '',
    severity                    TEXT NOT NULL DEFAULT 'medium',
    current_monthly_cost        REAL NOT NULL DEFAULT 0.0,
    estimated_monthly_savings   REAL NOT NULL DEFAULT 0.0,
    recommended_action          TEXT NOT NULL DEFAULT '',
    details                     TEXT DEFAULT '{}',
    status                      TEXT NOT NULL DEFAULT 'open',
    snoozed_until               TEXT,
    watch_list                  INTEGER NOT NULL DEFAULT 0,
    created_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (scan_id) REFERENCES scans(id),
    FOREIGN KEY (account_id) REFERENCES cloud_accounts(id)
);
CREATE INDEX IF NOT EXISTS idx_findings_scan ON findings(scan_id);
CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity);
CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status);

CREATE TABLE IF NOT EXISTS services (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    priority    TEXT NOT NULL DEFAULT 'P2',
    stateless   INTEGER NOT NULL DEFAULT 0,
    owner_team  TEXT DEFAULT '',
    config      TEXT DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS service_dependencies (
    id              TEXT PRIMARY KEY,
    service_id      TEXT NOT NULL,
    depends_on_id   TEXT NOT NULL,
    dependency_type TEXT NOT NULL DEFAULT 'runtime',
    FOREIGN KEY (service_id) REFERENCES services(id),
    FOREIGN KEY (depends_on_id) REFERENCES services(id),
    UNIQUE(service_id, depends_on_id)
);

CREATE TABLE IF NOT EXISTS service_resources (
    id              TEXT PRIMARY KEY,
    service_id      TEXT NOT NULL,
    account_id      TEXT NOT NULL,
    resource_id     TEXT NOT NULL,
    resource_type   TEXT NOT NULL,
    FOREIGN KEY (service_id) REFERENCES services(id),
    FOREIGN KEY (account_id) REFERENCES cloud_accounts(id)
);

CREATE TABLE IF NOT EXISTS error_budgets (
    id                      TEXT PRIMARY KEY,
    service_id              TEXT NOT NULL,
    period_type             TEXT NOT NULL DEFAULT 'monthly',
    period_start            TEXT NOT NULL,
    period_end              TEXT NOT NULL,
    slo_target_pct          REAL NOT NULL DEFAULT 99.9,
    budget_total_minutes    REAL NOT NULL,
    budget_consumed_minutes REAL NOT NULL DEFAULT 0.0,
    p99_latency_target_ms   REAL,
    p99_latency_current_ms  REAL,
    status                  TEXT NOT NULL DEFAULT 'healthy',
    last_updated            TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (service_id) REFERENCES services(id)
);
CREATE INDEX IF NOT EXISTS idx_error_budgets_service ON error_budgets(service_id);

CREATE TABLE IF NOT EXISTS error_budget_events (
    id                  TEXT PRIMARY KEY,
    error_budget_id     TEXT NOT NULL,
    event_type          TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    ended_at            TEXT,
    duration_minutes    REAL NOT NULL DEFAULT 0.0,
    description         TEXT DEFAULT '',
    source              TEXT DEFAULT 'manual',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (error_budget_id) REFERENCES error_budgets(id)
);

CREATE TABLE IF NOT EXISTS budgets (
    id                      TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    account_id              TEXT,
    service_id              TEXT,
    period_type             TEXT NOT NULL DEFAULT 'monthly',
    period_start            TEXT NOT NULL,
    period_end              TEXT NOT NULL,
    budget_amount           REAL NOT NULL,
    actual_amount           REAL NOT NULL DEFAULT 0.0,
    forecasted_amount       REAL,
    alert_threshold_pct     REAL NOT NULL DEFAULT 80.0,
    status                  TEXT NOT NULL DEFAULT 'on_track',
    ai_recommendation       TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (account_id) REFERENCES cloud_accounts(id),
    FOREIGN KEY (service_id) REFERENCES services(id)
);

CREATE TABLE IF NOT EXISTS budget_snapshots (
    id                  TEXT PRIMARY KEY,
    budget_id           TEXT NOT NULL,
    snapshot_date       TEXT NOT NULL,
    actual_amount       REAL NOT NULL,
    forecasted_amount   REAL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (budget_id) REFERENCES budgets(id)
);
CREATE INDEX IF NOT EXISTS idx_budget_snapshots_date ON budget_snapshots(budget_id, snapshot_date);

CREATE TABLE IF NOT EXISTS cost_snapshots (
    id              TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL,
    snapshot_date   TEXT NOT NULL,
    total_cost      REAL NOT NULL,
    cost_by_service TEXT DEFAULT '{}',
    cost_by_check   TEXT DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (account_id) REFERENCES cloud_accounts(id)
);
CREATE INDEX IF NOT EXISTS idx_cost_snapshots_date ON cost_snapshots(account_id, snapshot_date);

CREATE TABLE IF NOT EXISTS ai_recommendations (
    id                      TEXT PRIMARY KEY,
    finding_id              TEXT,
    budget_id               TEXT,
    service_id              TEXT,
    recommendation_type     TEXT NOT NULL DEFAULT 'cost_optimization',
    title                   TEXT NOT NULL,
    body                    TEXT NOT NULL,
    severity                TEXT NOT NULL DEFAULT 'info',
    llm_provider            TEXT,
    llm_model               TEXT,
    confidence              REAL,
    status                  TEXT NOT NULL DEFAULT 'pending',
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (finding_id) REFERENCES findings(id),
    FOREIGN KEY (budget_id) REFERENCES budgets(id),
    FOREIGN KEY (service_id) REFERENCES services(id)
);

CREATE TABLE IF NOT EXISTS safety_analyses (
    id                  TEXT PRIMARY KEY,
    finding_id          TEXT,
    traffic_verdict     TEXT DEFAULT '{}',
    dependency_verdict  TEXT DEFAULT '{}',
    error_budget_verdict TEXT DEFAULT '{}',
    ai_verdict          TEXT DEFAULT '{}',
    overall_verdict     TEXT NOT NULL DEFAULT 'pending',
    checklist           TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (finding_id) REFERENCES findings(id)
);

CREATE TABLE IF NOT EXISTS incidents (
    id                  TEXT PRIMARY KEY,
    service_id          TEXT,
    title               TEXT NOT NULL,
    description         TEXT DEFAULT '',
    severity            TEXT NOT NULL DEFAULT 'medium',
    started_at          TEXT NOT NULL,
    ended_at            TEXT,
    user_impact_before  INTEGER,
    user_impact_after   INTEGER,
    user_churn          INTEGER,
    cost_impact         REAL,
    source              TEXT DEFAULT 'manual',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (service_id) REFERENCES services(id)
);

CREATE TABLE IF NOT EXISTS alerts (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    alert_type      TEXT NOT NULL,
    channel         TEXT NOT NULL DEFAULT 'slack',
    config          TEXT NOT NULL DEFAULT '{}',
    enabled         INTEGER NOT NULL DEFAULT 1,
    last_triggered  TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS delegates (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    account_id      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    last_heartbeat  TEXT,
    config          TEXT DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (account_id) REFERENCES cloud_accounts(id)
);
