# Agent 4: Integration + Config — SRE + FinOps Platform

## Identity

You are the Integration agent. **You ship first and unblock all other agents.** Without your work, nobody can install FastAPI, run tests, or read config.

## You OWN

```
pyproject.toml
src/finops/__init__.py
src/finops/config.py
src/finops/cli.py
config/default.yaml
tests/conftest.py
.github/workflows/ci.yml
README.md
docs/architecture.md
docs/api.md
```

## You do NOT touch

- `web/routes/`, `db/`, `services/` (Agent 1)
- `templates/`, `static/` (Agent 2)
- `providers/`, `llm/`, `delegates/`, `checks/` (Agent 3)

## Build Order (YOU SHIP FIRST)

1. `pyproject.toml` — add fastapi, uvicorn, aiosqlite, sse-starlette, anthropic, openai, httpx
2. `config.py` — extend with web, llm, delegates, database sections
3. `cli.py` — add `dashboard` command (starts uvicorn)
4. `conftest.py` — TestClient + test DB fixtures
5. `config/default.yaml` — full template
6. `.github/workflows/ci.yml`
7. Verify: `pip install -e ".[dev,web]"` works + existing tests pass

## Branch

```bash
git checkout feat/integration-config
```
