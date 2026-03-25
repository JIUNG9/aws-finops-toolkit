# SRE + FinOps Platform — MVP Plan

## Context

Evolving `aws-finops-toolkit` into a full SRE + FinOps platform that treats **error budgets and cost budgets as co-equal, interdependent constraints**. No existing tool does this — Sedai is closest but lacks transparency and dependency graphs.

**Unique angle**: Every cost optimization decision is gated on safety analysis — traffic patterns, dependent resources, error budget state, user impact. "Save money without breaking things" with explainable AI.

**Target**: SRE/Platform team (3-10 engineers), multi-cloud (AWS + Azure + GCP).

---

## Architecture

```
Browser (HTMX + Chart.js + D3.js)
    │
    │ HTTP / SSE
    │
FastAPI Application
    ├── HTMX Pages (server-rendered)
    ├── REST API (/api/v1/*)
    ├── SSE Events (async scan/analysis progress)
    │
    ├── Service Layer
    │   ├── ScannerService (async scan orchestration)
    │   ├── ErrorBudgetService (SLO tracking + burn rate)
    │   ├── BudgetService (financial budget + forecast)
    │   ├── CostService (trends, comparison, attribution)
    │   ├── RecommendationService (AI + safety analysis)
    │   ├── SafetyAnalyzer (traffic patterns, dependencies, blast radius)
    │   ├── IncidentImpactService (user churn tracking)
    │   └── ImportExportService
    │
    ├── Provider Layer (pluggable)
    │   ├── AWS Provider (boto3) — full implementation
    │   ├── Azure Provider (stub → Phase 2)
    │   ├── GCP Provider (stub → Phase 2)
    │   └── LLM Provider (Claude / OpenAI / pluggable)
    │
    ├── Delegate System (background workers)
    │   ├── DelegateManager (asyncio task queue)
    │   └── DelegateWorker (run checks, collect cost data)
    │
    └── SQLite (aiosqlite) — persistence
```

---

## Safety-First Design (Core Differentiator)

Before ANY recommendation (downsize, remove, scale down), the system runs a **Safety Analysis**:

```
User clicks "Analyze" or "Accept Recommendation"
    │
    ▼
1. TRAFFIC ANALYSIS (1 year history)
   - Peak/avg ratio, seasonal patterns, weekend drops
   - Holiday/event spikes (Black Friday, lunar new year)
   - Growth trend (is traffic increasing?)
   → Verdict: "Traffic has grown 15% YoY. Peak is 3x avg on Fridays."
    │
    ▼
2. DEPENDENCY CHECK
   - What resources depend on this one?
   - What services are affected?
   - Blast radius: N services, M users impacted if this fails
   → Verdict: "4 services depend on this RDS. Blast radius: 12,000 users."
    │
    ▼
3. ERROR BUDGET CHECK
   - Current error budget remaining (%)
   - Burn rate trend
   - Is there an active incident?
   → Verdict: "Error budget at 62%. Safe to proceed."
    │
    ▼
4. AI ANALYSIS (LLM)
   - Given all above context, is this safe?
   - What could go wrong?
   - What's the recommended approach + rollback plan?
   → Verdict: "Recommend downsizing during low-traffic window (Sun 3AM).
      Pre-warm cache after. Rollback: scale back within 5 minutes."
    │
    ▼
5. USER CONFIRMATION
   - Show full safety report in UI
   - Checklist: ☐ Reviewed traffic patterns ☐ Checked dependencies ☐ Approved by lead
   - User clicks "Approve" or "Defer"
```

---

## MVP Scope (4 weeks)

### Week 1: Foundation
- FastAPI app skeleton + SQLite DB + base templates
- Cloud account CRUD + AWS provider (uncomment boto3 in all 10 checks)
- Dashboard page (static mockup → live data)
- Findings list + detail pages

### Week 2: Core Features
- Error budget: set SLO targets, track burn, record incidents
- Financial budget: set budgets, track actual vs target, forecast
- Cost dashboard: trends, before/after comparison
- Async scan with SSE progress
- Background delegate workers

### Week 3: AI + Safety + Impact
- LLM integration (pluggable: Claude/OpenAI)
- Safety Analyzer: traffic patterns, dependency check, error budget gate
- What-if analysis: simulate downsize/removal with projected impact
- Incident → user impact tracking (APM + custom metrics)
- Dependency graph (D3.js force-directed)
- Alerts & notifications (Slack webhook MVP)

### Week 4: Polish + Ship
- Onboarding wizard (step-by-step first-time setup)
- Import/export (JSON/CSV)
- Watch list for findings
- Scheduled reports (daily/weekly email)
- Error handling, edge cases, responsive UI
- Demo mode (works without AWS creds)
- Documentation, README, tag v0.2.0

---

## Data Model (key tables)

| Table | Purpose |
|-------|---------|
| `cloud_accounts` | Multi-cloud account configs (AWS/Azure/GCP) |
| `scans` | Scan runs with status (pending/running/completed/failed) |
| `findings` | Individual cost findings with severity + status (open/accepted/dismissed/snoozed) + watch_list flag |
| `services` | Service catalog for dependency graph |
| `service_dependencies` | Service→Service dependency edges |
| `service_resources` | Service→Cloud Resource mapping |
| `error_budgets` | SLO targets per service with burn tracking |
| `error_budget_events` | Individual incidents that burn error budget |
| `budgets` | Financial budgets per account/service |
| `budget_snapshots` | Daily cost snapshots for trend charts |
| `cost_snapshots` | Before/after cost tracking |
| `ai_recommendations` | LLM-generated recommendations with status |
| `safety_analyses` | Pre-action safety reports (traffic, deps, error budget) |
| `incidents` | Incident records with user impact data |
| `alerts` | Alert configurations + delivery status |
| `delegates` | Background worker registrations |

---

## API Design (key endpoints)

```
# Accounts
POST /api/v1/accounts                    — Add cloud account
POST /api/v1/accounts/{id}/test          — Test connection

# Scans
POST /api/v1/scans                       — Trigger async scan
GET  /api/v1/events/scans/{id}           — SSE scan progress

# Error Budgets
POST /api/v1/error-budgets               — Set SLO target for service
POST /api/v1/error-budgets/{id}/events   — Record incident
GET  /api/v1/error-budgets/summary       — All services overview

# Financial Budgets
POST /api/v1/budgets                     — Set budget
GET  /api/v1/budgets/{id}/snapshots      — Daily cost trend

# Cost Tracking
GET  /api/v1/costs/comparison            — Before/after
GET  /api/v1/costs/trend                 — Historical trend

# Safety Analysis
POST /api/v1/safety/analyze              — Run full safety check before action
GET  /api/v1/safety/traffic-patterns/{resource_id}  — 1-year traffic analysis

# AI
POST /api/v1/ai/analyze                  — Deep AI analysis (async + SSE)
POST /api/v1/ai/what-if                  — What-if simulation
GET  /api/v1/ai/recommendations          — List recommendations

# Incidents & User Impact
POST /api/v1/incidents                   — Record incident
GET  /api/v1/incidents/{id}/user-impact  — User churn data

# Services & Dependencies
GET  /api/v1/services/dependency-graph   — D3.js format
POST /api/v1/services/{id}/resources     — Link resources to service

# Import/Export
POST /api/v1/import                      — Import data
GET  /api/v1/export/{type}               — Export data

# Alerts
POST /api/v1/alerts                      — Configure alert
```

---

## Pages (HTMX)

| Route | Content |
|-------|---------|
| `/dashboard` | Summary cards, cost trend chart, error budget gauges, top findings |
| `/scans` | Scan history + trigger button (SSE progress) |
| `/findings` | Filterable table, severity badges, accept/dismiss/watch actions |
| `/error-budgets` | Per-service SLO bars, burn rate, incident timeline |
| `/budgets` | Budget vs actual bars, forecast, AI advice |
| `/costs` | Before/after comparison, stacked cost charts, RI/SP coverage |
| `/services` | Service catalog + D3.js dependency graph |
| `/recommendations` | AI recommendations with safety analysis, what-if simulator |
| `/incidents` | Incident timeline with user impact metrics |
| `/alerts` | Alert configuration (Slack, email, webhook) |
| `/settings` | Accounts, LLM config, thresholds, import/export |
| `/onboarding` | Step-by-step wizard for first-time setup |

---

## Claude Code Sub-Agent Setup (4 agents, parallel)

### Agent 1: "Backend Core"
**Owns**: `db/`, `web/routes/`, `web/schemas.py`, `web/deps.py`, `services/`, `app.py`
**Focus**: Database, API routes, service layer, Pydantic models

### Agent 2: "Frontend"
**Owns**: `templates/`, `static/`, `web/routes/pages.py`
**Focus**: HTMX templates, Chart.js charts, D3.js dependency graph, CSS, onboarding wizard

### Agent 3: "Cloud + LLM Providers"
**Owns**: `providers/`, `llm/`, `delegates/`, `checks/` (uncomment boto3)
**Focus**: AWS provider, LLM abstraction (Claude/OpenAI), delegate workers, safety analyzer

### Agent 4: "Integration + Config"
**Owns**: `pyproject.toml`, `config.py`, `tests/conftest.py`, CI, docs
**Focus**: Dependencies, config system, test infrastructure, documentation

### Coordination
- Shared contracts (Pydantic schemas, DB models, provider interfaces) defined in Week 1 Day 1
- Branch strategy: `feat/mvp-platform` → per-agent feature branches → merge weekly
- Merge order: Agent 4 → Agent 1 → Agent 3 → Agent 2

---

## File Structure

```
aws-finops-toolkit/                    # Keep existing name (rebrand later if product)
├── pyproject.toml                     # Updated deps
├── migrations/001_initial.sql         # SQLite schema
├── config/default.yaml                # Extended config
├── src/finops/
│   ├── app.py                         # FastAPI factory
│   ├── cli.py                         # Existing CLI (add `dashboard` command)
│   ├── web/
│   │   ├── routes/                    # API + page routes (12 files)
│   │   ├── schemas.py                 # Pydantic models
│   │   └── deps.py                    # FastAPI dependencies
│   ├── services/                      # Business logic (8 services)
│   ├── db/
│   │   ├── database.py                # aiosqlite connection
│   │   ├── models.py                  # Dataclass models
│   │   └── queries/                   # SQL query functions (10 files)
│   ├── providers/
│   │   ├── base.py                    # CloudProvider ABC
│   │   ├── aws/                       # Full implementation
│   │   ├── azure/                     # Stub
│   │   └── gcp/                       # Stub
│   ├── llm/
│   │   ├── base.py                    # LLMProvider ABC
│   │   ├── claude.py                  # Anthropic
│   │   ├── openai_provider.py         # OpenAI
│   │   └── prompts/                   # Jinja2 prompt templates
│   ├── delegates/                     # Background workers
│   ├── checks/                        # Existing 10 checks (boto3 uncommented)
│   ├── templates/                     # Jinja2 (base + 15 pages + 10 components)
│   └── static/                        # CSS + JS (app.css, charts.js, dependency-graph.js, htmx.min.js)
└── tests/                             # test_api/, test_services/, test_providers/, test_llm/, test_db/
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI + uvicorn |
| Frontend | Jinja2 + HTMX + Chart.js + D3.js |
| Database | SQLite via aiosqlite |
| Cloud | boto3 (AWS), azure-mgmt (stub), google-cloud (stub) |
| LLM | anthropic SDK, openai SDK (pluggable) |
| CLI | Click + Rich (preserved) |
| Testing | pytest + moto + httpx (TestClient) |
| CI | GitHub Actions |

---

## Verification

1. **Smoke test**: `pip install -e ".[web]" && finops dashboard` → opens dashboard at localhost:8080
2. **Scan test**: Add AWS account → trigger scan → see findings populate
3. **Error budget test**: Define SLO → record incident → see budget burn in chart
4. **Budget test**: Set $10K/month budget → see actual cost tracking
5. **AI test**: Click "Analyze" on a finding → see safety report + AI recommendation
6. **Demo mode**: `finops dashboard --demo` → realistic mock data without AWS creds
7. **CLI backward compat**: `finops scan --profile my-aws` still works as before

---

## Reusable Agent Framework

Create `~/.claude/agent-framework/` with templates reusable across future projects.
Create project-specific agent files in `oss/aws-finops-toolkit/.claude/agents/`.
Create a global blog agent that works across all projects.

### Files to Create

**Global framework** (`~/.claude/agent-framework/`):
- `README.md` — How to use the agent framework
- `TEMPLATE-HANDOVER.md` — Copy to new projects, fill in blanks
- `TEMPLATE-AGENT.md` — Agent instruction template
- `TEMPLATE-STATUS.md` — Progress tracking template
- `agents/pm-pl.md` — PM/PL reusable template
- `agents/backend.md` — Backend agent template
- `agents/frontend.md` — Frontend agent template
- `agents/qa-risk.md` — QA agent template
- `agents/integration.md` — Integration agent template
- `agents/content-blog.md` — Blog publisher agent (cross-project)

**Project-specific** (`oss/aws-finops-toolkit/`):
- `HANDOVER.md` — Full context for other sessions
- `STATUS.md` — Sprint tracker
- `.claude/agents/agent-0-pm.md` — PM/PL for this project
- `.claude/agents/agent-1-backend.md` — Backend Core
- `.claude/agents/agent-2-frontend.md` — Frontend
- `.claude/agents/agent-3-providers.md` — Cloud + LLM
- `.claude/agents/agent-4-integration.md` — Config + CI
- `.claude/agents/agent-5-qa.md` — QA & Risk
- `.claude/agents/agent-6-content.md` — Content & Blog (Medium publisher)

**Git branches**:
- `feat/backend-core`
- `feat/frontend-htmx`
- `feat/providers-llm`
- `feat/integration-config`

### Agent Roster (7 agents)

| # | Agent | Branch | Owned Files | Merge Order |
|---|-------|--------|-------------|-------------|
| 0 | PM/PL | `main` | STATUS.md, merge reviews | Merges others |
| 1 | Backend Core | `feat/backend-core` | db/, services/, web/routes/, web/schemas.py | 2nd |
| 2 | Frontend | `feat/frontend-htmx` | templates/, static/, web/routes/pages.py | 4th |
| 3 | Cloud + LLM | `feat/providers-llm` | providers/, llm/, delegates/, checks/ | 3rd |
| 4 | Integration | `feat/integration-config` | pyproject.toml, config.py, conftest.py, CI | 1st |
| 5 | QA & Risk | `feat/qa-risk` | Reviews all branches, writes test reports | After each merge |
| 6 | Content & Blog | N/A (cross-project) | articles/, README.md, LinkedIn posts | Post-ship |
