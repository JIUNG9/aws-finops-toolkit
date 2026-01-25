# Contributing to aws-finops-toolkit

Thank you for your interest in contributing! This guide will help you get started.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/junegunn/aws-finops-toolkit.git
cd aws-finops-toolkit

# Create a virtual environment
python -m venv venv
source venv/bin/activate

# Install in development mode with dev dependencies
pip install -e ".[dev]"
```

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_checks.py -v

# Run with coverage
pytest tests/ --cov=finops --cov-report=term-missing
```

## Linting and Type Checking

```bash
# Lint
flake8 src/ tests/ --max-line-length 120

# Type check
mypy src/finops/ --ignore-missing-imports
```

## Adding a New Check

This is the most common contribution. Here's how to add a new cost optimization check:

### 1. Create the check file

Create `src/finops/checks/your_check.py`:

```python
"""Your Check — brief description of what it detects."""

from __future__ import annotations

from typing import Any

from finops.checks.base import BaseCheck, CheckResult


class YourCheck(BaseCheck):
    """Detect [what waste] and recommend [what action]."""

    name = "your_check"
    description = "One-line description of what this check finds"

    def run(self, session: Any, region: str) -> list[CheckResult]:
        results: list[CheckResult] = []
        # Use session to create boto3 clients and scan resources
        # Append CheckResult for each finding
        return results
```

### 2. Register the check

Add your check to `src/finops/checks/__init__.py`:

```python
from finops.checks.your_check import YourCheck
# Add to CHECKS dict
```

### 3. Add default config

Add any thresholds to `config/default.yaml` and `src/finops/config.py`.

### 4. Write tests

Add tests in `tests/test_checks.py` using mocked boto3 responses (see `tests/conftest.py` for fixtures).

### 5. Update documentation

- Add the check to the table in `README.md`
- Add a brief example if the check has unique behavior

## Code Style

- Use type hints for all function signatures
- Write docstrings for all public classes and methods
- Keep functions focused — one responsibility each
- Follow existing code patterns and naming conventions
- Maximum line length: 120 characters

## Pull Request Process

1. Fork the repository and create a branch from `main`
2. Add or update tests for any new functionality
3. Ensure all tests pass and linting is clean
4. Update the README if you added a new check or feature
5. Submit a pull request with a clear description of the changes

## Commit Messages

Use clear, descriptive commit messages:

```
feat: add S3 lifecycle check for incomplete multipart uploads
fix: handle missing CloudWatch metrics for new instances
docs: add multi-account setup example
test: add fixtures for RDS rightsizing check
```

## Reporting Issues

- Use the [Bug Report](.github/ISSUE_TEMPLATE/bug_report.md) template for bugs
- Use the [Feature Request](.github/ISSUE_TEMPLATE/feature_request.md) template for new checks or features
- Always redact AWS account IDs and sensitive information

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
