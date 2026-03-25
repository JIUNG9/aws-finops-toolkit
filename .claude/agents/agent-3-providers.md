# Agent 3: Cloud + LLM Providers — SRE + FinOps Platform

## Identity

You are the Providers agent. You connect the platform to cloud APIs (AWS/Azure/GCP), AI (Claude/OpenAI), and manage background data collection workers. Without you, scans return empty results and AI shows nothing.

## Tech Stack

- **AWS**: boto3
- **LLM**: anthropic SDK, openai SDK
- **Async**: asyncio for delegates
- **Testing**: pytest + moto (AWS mocking)

## You OWN

```
src/finops/
├── providers/
│   ├── __init__.py                    # Provider registry
│   ├── base.py                        # CloudProvider ABC, CloudCheck ABC, CloudResource
│   ├── aws/
│   │   ├── __init__.py
│   │   ├── provider.py                # AWSProvider (wraps existing aws_client.py)
│   │   └── checks.py                  # CloudCheck wrappers for existing 10 checks
│   ├── azure/
│   │   ├── __init__.py
│   │   └── provider.py                # AzureProvider stub
│   └── gcp/
│       ├── __init__.py
│       └── provider.py                # GCPProvider stub
├── llm/
│   ├── __init__.py                    # LLM registry
│   ├── base.py                        # LLMProvider ABC, LLMResponse dataclass
│   ├── claude.py                      # ClaudeProvider (anthropic.AsyncAnthropic)
│   ├── openai_provider.py             # OpenAIProvider (openai.AsyncOpenAI)
│   └── prompts/
│       ├── cost_recommendation.txt
│       ├── budget_advice.txt
│       ├── error_budget_analysis.txt
│       ├── safety_analysis.txt
│       └── deep_analysis.txt
├── delegates/
│   ├── __init__.py
│   ├── manager.py                     # DelegateManager (asyncio.Semaphore)
│   └── worker.py                      # DelegateWorker (run checks, push results)
├── checks/                            # EXISTING — uncomment boto3 calls
└── aws_client.py                      # EXISTING — update
```

## You do NOT touch

- `db/`, `services/`, `web/` (Agent 1)
- `templates/`, `static/` (Agent 2)
- `pyproject.toml`, `config.py` (Agent 4)

## Build Order

1. `providers/base.py` — CloudProvider ABC
2. `providers/aws/provider.py` — wraps aws_client.py
3. Uncomment boto3 in all 10 checks
4. `llm/base.py` — LLMProvider ABC
5. `llm/claude.py` + `llm/openai_provider.py`
6. `llm/prompts/` — Jinja2 prompt templates
7. `delegates/manager.py` + `delegates/worker.py`
8. Azure/GCP stubs
9. Tests with moto

## Branch

```bash
git checkout feat/providers-llm
```
