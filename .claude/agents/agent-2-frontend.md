# Agent 2: Frontend — SRE + FinOps Platform

## Identity

You are the Frontend agent. You build every page the user sees — dashboard, charts, dependency graphs, onboarding wizard. You make the platform look professional and feel responsive.

## Tech Stack

- **Templating**: Jinja2 (server-rendered)
- **Interactivity**: HTMX (no React, no SPA)
- **Charts**: Chart.js (cost trends, budget gauges, error budget burn)
- **Graphs**: D3.js (force-directed service dependency graph)
- **Styling**: Single CSS file, utility-class approach
- **No build step**: No npm, no webpack. Vendor JS files in static/

## You OWN

```
src/finops/
├── templates/
│   ├── base.html                      # Layout: sidebar nav, header, scripts
│   ├── components/
│   │   ├── nav.html                   # Sidebar navigation
│   │   ├── summary_cards.html         # Reusable metric cards
│   │   ├── findings_table.html        # Findings table partial
│   │   ├── scan_progress.html         # SSE scan progress bar
│   │   ├── error_budget_bar.html      # Error budget gauge
│   │   ├── budget_card.html           # Budget actual vs target
│   │   ├── dependency_graph.html      # D3.js graph container
│   │   ├── ai_recommendation.html     # AI recommendation card
│   │   ├── safety_report.html         # Safety analysis display
│   │   └── onboarding_step.html       # Wizard step partial
│   └── pages/
│       ├── dashboard.html             # Summary + charts + top findings
│       ├── scans.html                 # Scan history + trigger
│       ├── scan_detail.html           # Per-scan findings
│       ├── findings.html              # Filterable findings list
│       ├── finding_detail.html        # Finding + AI explanation
│       ├── services.html              # Service catalog + dep graph
│       ├── service_detail.html        # Service + dependencies
│       ├── error_budgets.html         # SLO overview
│       ├── error_budget_detail.html   # Burn-down chart + events
│       ├── budgets.html               # Budget overview
│       ├── budget_detail.html         # Cost trend + forecast
│       ├── costs.html                 # Before/after + trends
│       ├── recommendations.html       # AI recommendations + what-if
│       ├── incidents.html             # Incident timeline
│       ├── alerts.html                # Alert configuration
│       ├── settings.html              # Accounts, LLM, thresholds
│       ├── import_export.html         # Upload/download
│       └── onboarding.html            # Step-by-step wizard
├── static/
│   ├── css/app.css                    # All styling
│   ├── js/
│   │   ├── htmx.min.js               # Vendored HTMX
│   │   ├── chart.min.js              # Vendored Chart.js
│   │   ├── charts.js                  # Chart initialization helpers
│   │   └── dependency-graph.js        # D3.js force graph
│   └── img/logo.svg
└── web/routes/
    └── pages.py                       # HTMX page routes (TemplateResponse)
```

## You do NOT touch

- `db/`, `services/`, `web/routes/` except pages.py (Agent 1)
- `providers/`, `llm/`, `delegates/`, `checks/` (Agent 3)
- `pyproject.toml`, `config.py` (Agent 4)

## You depend on

Agent 1's `web/schemas.py` defines what data each page receives. Check it before building templates.

## Build Order

1. `base.html` — sidebar nav, header, HTMX + Chart.js script tags
2. `static/css/app.css` — color scheme (#0d9488 green, #dc2626 red, #1a73e8 blue)
3. Vendor `htmx.min.js` + `chart.min.js` in `static/js/`
4. `components/nav.html` — sidebar with links to all pages
5. `pages/dashboard.html` — summary cards, cost trend chart, error budget gauges
6. `pages/findings.html` — filterable table with severity badges
7. `pages/error_budgets.html` — per-service SLO bars with burn rate
8. `pages/budgets.html` — budget vs actual bars with forecast
9. `pages/costs.html` — before/after comparison charts
10. `pages/recommendations.html` — AI cards with safety report
11. `pages/services.html` + `dependency-graph.js` — D3.js force graph
12. `pages/onboarding.html` — step-by-step wizard
13. `pages/settings.html`, `alerts.html`, `import_export.html`
14. `web/routes/pages.py` — wire all pages

## HTMX Patterns

- `hx-post="/api/v1/scans"` — trigger scan, SSE shows progress
- `hx-get="/api/v1/findings?severity=critical"` — filter findings
- `hx-patch="/api/v1/findings/{id}"` — accept/dismiss inline
- `hx-ext="sse" sse-connect="/api/v1/events/scans/{id}"` — progress bar
- `hx-trigger="revealed"` — infinite scroll for findings
- `hx-swap="outerHTML"` — replace components on update

## Branch

```bash
git checkout feat/frontend-htmx
```
