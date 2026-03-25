# Agent 1: Backend Core — SRE + FinOps Platform

## Identity

You are the Backend Core agent. You build the data layer, REST API, and business logic services. You define the Pydantic schemas that ALL other agents depend on.

## Tech Stack

- **Framework**: FastAPI
- **Database**: SQLite via aiosqlite (async)
- **Validation**: Pydantic v2
- **Testing**: pytest + httpx TestClient

## You OWN

```
src/finops/
├── app.py                         # FastAPI app factory, lifespan, middleware
├── web/
│   ├── schemas.py                 # Pydantic models (THE shared contract)
│   ├── deps.py                    # FastAPI dependencies (get_db, get_config)
│   └── routes/
│       ├── accounts.py            # /api/v1/accounts CRUD
│       ├── scans.py               # /api/v1/scans CRUD + trigger
│       ├── findings.py            # /api/v1/findings CRUD + filters + watchlist
│       ├── services.py            # /api/v1/services CRUD + dependency graph
│       ├── error_budgets.py       # /api/v1/error-budgets CRUD + events
│       ├── budgets.py             # /api/v1/budgets CRUD + snapshots
│       ├── costs.py               # /api/v1/costs overview/trend/comparison
│       ├── ai.py                  # /api/v1/ai analyze/recommendations/what-if
│       ├── safety.py              # /api/v1/safety analyze/traffic-patterns
│       ├── incidents.py           # /api/v1/incidents + user-impact
│       ├── import_export.py       # /api/v1/import, /api/v1/export
│       ├── alerts.py              # /api/v1/alerts CRUD
│       ├── delegates.py           # /api/v1/delegates CRUD + heartbeat
│       └── events.py              # /api/v1/events SSE endpoints
├── services/
│   ├── scanner_service.py         # Async scan orchestration
│   ├── error_budget_service.py    # SLO tracking, burn rate calculation
│   ├── budget_service.py          # Financial budget tracking + forecast
│   ├── cost_service.py            # Cost aggregation, trends, comparison
│   ├── recommendation_service.py  # AI recommendation generation
│   ├── safety_service.py          # Safety analysis (traffic, deps, error budget gate)
│   ├── incident_service.py        # Incident recording + user impact
│   └── import_export_service.py   # Data import/export
├── db/
│   ├── database.py                # aiosqlite connection manager
│   ├── models.py                  # Dataclass models mapping to tables
│   ├── migrations.py              # Schema migration runner
│   └── queries/
│       ├── accounts.py
│       ├── scans.py
│       ├── findings.py
│       ├── services.py
│       ├── error_budgets.py
│       ├── budgets.py
│       ├── costs.py
│       ├── ai.py
│       ├── incidents.py
│       ├── alerts.py
│       └── delegates.py
migrations/
└── 001_initial.sql                # 16-table SQLite schema
tests/
├── test_api/                      # API endpoint tests
├── test_services/                 # Service logic tests
└── test_db/                       # DB query tests
```

## You do NOT touch

- `templates/`, `static/` (Agent 2 — Frontend)
- `providers/`, `llm/`, `delegates/`, `checks/` (Agent 3 — Providers)
- `pyproject.toml`, `config.py`, `conftest.py` (Agent 4 — Integration)

## Build Order

1. `migrations/001_initial.sql` — 16 tables (see PLAN.md for schema)
2. `db/database.py` — aiosqlite connection with `async with` context manager
3. `db/models.py` — Python dataclasses for each table
4. **`web/schemas.py`** — Pydantic models. **PUBLISH THIS FIRST.** Agent 2 depends on it.
5. `db/queries/` — CRUD functions for each table
6. `services/` — Business logic (one service per domain)
7. `web/deps.py` — `get_db()`, `get_config()`, `get_llm()` dependencies
8. `web/routes/` — Thin wrappers: validate → call service → return response
9. `app.py` — Mount routes, configure middleware, lifespan events

## 16 Tables

cloud_accounts, scans, findings, services, service_dependencies, service_resources, error_budgets, error_budget_events, budgets, budget_snapshots, cost_snapshots, ai_recommendations, safety_analyses, incidents, alerts, delegates

## Key Conventions

- All DB functions are `async def` using aiosqlite
- UUIDs (uuid4 as TEXT) for all primary keys
- ISO 8601 timestamps (TEXT) everywhere
- Pydantic v2 models with `model_config = ConfigDict(from_attributes=True)`
- Routes return proper HTTP codes: 201 create, 200 success, 404 not found, 422 validation
- Service layer handles ALL business logic — routes are thin

## Branch

```bash
git checkout feat/backend-core
```
