# HANDOVER — SRE + FinOps Platform (aws-finops-toolkit)

> Read this file first in any new Claude Code session to get full project context.

## Project Overview

**What**: SRE + FinOps platform that treats error budgets and cost budgets as co-equal, interdependent constraints. Every cost optimization is gated on safety analysis — traffic patterns, dependent resources, error budget state, user impact.

**Why**: No existing tool combines SRE (error budgets, SLOs) with FinOps (cost optimization). Sedai is closest but lacks transparency. Harness CCM has cost but no SRE integration. This fills the market gap.

**Unique angle**: "Save money without breaking things" with explainable AI recommendations.

**Target user**: SRE/Platform team (3-10 engineers) managing multi-cloud (AWS + Azure + GCP).

**Author**: June Gu (Jiung Gu) — SRE at Placen/NAVER Corporation, relocating to Canada.

**Repo**: github.com/junegu/aws-finops-toolkit

**Timeline**: 4-week MVP sprint starting April 2026.

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
    │   ├── ScannerService        — async scan orchestration
    │   ├── ErrorBudgetService    — SLO tracking + burn rate
    │   ├── BudgetService         — financial budget + forecast
    │   ├── CostService           — trends, comparison, attribution
    │   ├── RecommendationService — AI + safety analysis
    │   ├── SafetyAnalyzer        — traffic patterns, dependencies, blast radius
    │   ├── IncidentImpactService — user churn tracking
    │   └── ImportExportService
    │
    ├── Provider Layer (pluggable)
    │   ├── AWS Provider (boto3)     — full implementation
    │   ├── Azure Provider           — stub for Phase 2
    │   ├── GCP Provider             — stub for Phase 2
    │   └── LLM Provider (pluggable) — Claude / OpenAI
    │
    ├── Delegate System (background workers)
    │   ├── DelegateManager (asyncio task queue)
    │   └── DelegateWorker (run checks, collect cost data)
    │
    └── SQLite (aiosqlite) — persistence
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI + uvicorn |
| Frontend | Jinja2 + HTMX + Chart.js + D3.js |
| Database | SQLite via aiosqlite |
| Cloud | boto3 (AWS), azure-mgmt (stub), google-cloud (stub) |
| LLM | anthropic SDK, openai SDK (pluggable, user brings API key) |
| CLI | Click + Rich (preserved from v0.1) |
| Testing | pytest + moto + httpx (TestClient) |
| CI | GitHub Actions |

## Key Decisions (already made — do NOT revisit)

1. **FastAPI + HTMX** over React SPA — no JS build step, pip-installable, SRE-friendly
2. **SQLite via aiosqlite** — zero external deps, async to avoid blocking FastAPI
3. **Pluggable LLM** — users bring their own API key (Claude or OpenAI)
4. **Safety-first** — every recommendation goes through 5-step safety analysis before user can accept
5. **Multi-cloud abstraction** — CloudProvider ABC so Azure/GCP can be added without changing core
6. **Existing CLI preserved** — `finops scan` still works, web dashboard is additive via `finops dashboard`
7. **Medium as blog platform** — not dev.to (Canadian recruiters read Medium)

## Current State

**What exists (v0.1 scaffold)**:
- Click CLI with 4 commands (scan, preflight, report, watch)
- 10 check modules in `src/finops/checks/` — boto3 calls are commented out (TODO)
- Report generator (HTML/CSV/JSON/Rich terminal) — fully working
- Config system (YAML) — working
- Scanner orchestrator (ScanResults dataclasses) — working
- 1,003 lines of tests
- pyproject.toml with setuptools

**What needs to be built (v0.2 MVP)**:
- Uncomment all boto3 calls in 10 checks
- FastAPI web application + HTMX dashboard
- SQLite persistence (16 tables)
- Error budget tracking
- Financial budget tracking
- AI recommendations (pluggable LLM)
- Safety analyzer (traffic, dependencies, error budget gate)
- Incident → user impact tracking
- Dependency graph (D3.js)
- Alerts, onboarding wizard, import/export

## Data Model

16 SQLite tables: cloud_accounts, scans, findings, services, service_dependencies, service_resources, error_budgets, error_budget_events, budgets, budget_snapshots, cost_snapshots, ai_recommendations, safety_analyses, incidents, alerts, delegates.

Full schema in `PLAN.md`.

## API Design

~30 REST endpoints under `/api/v1/`. Key groups: accounts, scans, findings, services, error-budgets, budgets, costs, safety, ai, incidents, import/export, alerts, delegates, events (SSE).

Full endpoint list in `PLAN.md`.

## Agent Setup

| # | Agent | Branch | Scope | Merge Order |
|---|-------|--------|-------|-------------|
| 0 | PM/PL | `main` | Orchestration, merges | Merges others |
| 1 | Backend Core | `feat/backend-core` | db/, services/, web/routes/, schemas | 2nd |
| 2 | Frontend | `feat/frontend-htmx` | templates/, static/, pages.py | 4th |
| 3 | Cloud + LLM | `feat/providers-llm` | providers/, llm/, delegates/, checks/ | 3rd |
| 4 | Integration | `feat/integration-config` | pyproject.toml, config, CI, docs | 1st |
| 5 | QA & Risk | `feat/qa-risk` | Reviews all code, security, testing | After each merge |
| 6 | Content & Blog | N/A | articles/, Medium, LinkedIn | Post-ship |

Agent instruction files: `.claude/agents/agent-N-*.md`

## 4-Week Schedule

- **Week 1**: Foundation — FastAPI skeleton, SQLite, AWS provider, dashboard page, findings
- **Week 2**: Core — Error budgets, financial budgets, cost tracking, async scans, delegates
- **Week 3**: AI + Safety — LLM integration, safety analyzer, what-if, dependency graph, alerts
- **Week 4**: Polish — Onboarding wizard, import/export, demo mode, docs, ship v0.2.0

## File Structure

```
aws-finops-toolkit/
├── PLAN.md                            ← Full implementation plan
├── HANDOVER.md                        ← This file
├── STATUS.md                          ← Sprint progress tracker
├── .claude/agents/                    ← Agent instruction files
│   ├── agent-0-pm.md
│   ├── agent-1-backend.md
│   ├── agent-2-frontend.md
│   ├── agent-3-providers.md
│   ├── agent-4-integration.md
│   ├── agent-5-qa.md
│   └── agent-6-content.md
├── pyproject.toml
├── migrations/001_initial.sql
├── config/default.yaml
├── src/finops/
│   ├── app.py                         ← FastAPI factory (NEW)
│   ├── cli.py                         ← Existing CLI + dashboard command
│   ├── web/                           ← NEW: web application
│   ├── services/                      ← NEW: business logic
│   ├── db/                            ← NEW: persistence
│   ├── providers/                     ← NEW: multi-cloud abstraction
│   ├── llm/                           ← NEW: AI integration
│   ├── delegates/                     ← NEW: background workers
│   ├── checks/                        ← EXISTING: 10 checks (uncomment boto3)
│   ├── templates/                     ← NEW: HTMX pages
│   └── static/                        ← NEW: CSS + JS
└── tests/
```

## How to Continue

1. Read `PLAN.md` for full architecture, API design, data model, week-by-week schedule
2. Read `.claude/agents/agent-N-*.md` for your specific agent's instructions
3. Read `STATUS.md` for current sprint progress
4. Check `git log` and `git branch` for recent changes
5. Start building from where the last session left off

## Related Projects

- `future/` project at `/Users/jiung.gu/Downloads/projects/future/` — career planning, blog articles
- `future/articles/` — 20+ written articles in 7 series, linked to this repo
- `nexus/` project at `/Users/jiung.gu/Downloads/projects/nexus/` — real work context at Placen/NAVER
- Global agent framework at `~/.claude/agent-framework/` — reusable templates

## Competitive Landscape (key findings)

- **No tool combines SRE + FinOps** — this is the unique differentiator
- Closest: Sedai (autonomous optimization, no transparency), Harness CCM (perspectives + budgets, no error budget gating)
- OpenCost/Kubecost: Kubernetes-only. Cloud Custodian: policy-only, no dashboard.
- Market gap: error budget-gated cost optimization with explainable AI and dependency graphs
