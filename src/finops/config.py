"""Configuration — Load and manage FinOps toolkit settings.

Configuration sources (in order of precedence):
  1. CLI flags (--checks, --profile, etc.)
  2. finops.yaml in the current directory
  3. ~/.finops/config.yaml
  4. Built-in defaults (config/default.yaml in the package)

The configuration controls:
  - Thresholds (CPU %, age limits, idle periods)
  - Account list (profiles to scan)
  - Check enable/disable flags
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


# Default thresholds — used when no config file is found
DEFAULT_THRESHOLDS: dict[str, Any] = {
    "ec2_cpu_avg_percent": 20,
    "ec2_lookback_days": 14,
    "snapshot_age_days": 90,
    "unattached_volume_grace_days": 7,
    "idle_lb_days": 7,
    "stopped_instance_days": 7,
    "nat_idle_days": 14,
    "workspace_stale_days": 30,
    "storage_gw_idle_days": 30,
    "log_inactive_days": 90,
    "log_retention_non_prod_days": 90,
    "log_retention_prod_days": 365,
    "log_ingestion_threshold_gb": 100,
    "s3_large_bucket_gb": 100,
}

# Default check enable/disable flags
DEFAULT_CHECKS: dict[str, bool] = {
    "nat_gateway": True,
    "unused_resources": True,
    "elasticache_scheduling": True,
    "s3_lifecycle": True,
}


@dataclass
class WebConfig:
    """Web dashboard configuration."""
    host: str = "127.0.0.1"
    port: int = 8080
    debug: bool = False


@dataclass
class LLMConfig:
    """LLM provider configuration."""
    provider: str = "claude"            # 'claude', 'openai'
    api_key_env: str = ""               # env var name holding the API key
    model: str = ""                     # model ID (empty = provider default)


@dataclass
class DatabaseConfig:
    """Database configuration."""
    path: str = ""                      # empty = ~/.finops/finops.db

    @property
    def resolved_path(self) -> Path:
        if self.path:
            return Path(self.path)
        return Path.home() / ".finops" / "finops.db"


@dataclass
class DelegateConfig:
    """Delegate worker configuration."""
    max_concurrent: int = 3
    default_schedule: str = "0 8 * * 1"  # Weekly Monday 8am


@dataclass
class SloConfig:
    """Live error budget source for the safety gate (Prometheus)."""
    prometheus_url: str = ""            # empty = use only the error_budgets table
    timeout_seconds: float = 5.0
    services: dict[str, str] = field(default_factory=dict)  # service name -> PromQL (remaining budget ratio)


@dataclass
class FinOpsConfig:
    """Parsed FinOps toolkit configuration.

    Attributes:
        thresholds: Dict of threshold values (CPU %, age days, etc.)
        accounts: List of account configs (each with 'profile', 'name')
        checks: Dict of check name -> enabled boolean
        web: Web dashboard settings
        llm: LLM provider settings
        database: Database settings
        delegates: Background worker settings
        slo: Live error budget source settings
        raw: The raw parsed YAML dict (for extension)
    """

    thresholds: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    accounts: list[dict[str, str]] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_CHECKS))
    web: WebConfig = field(default_factory=WebConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    delegates: DelegateConfig = field(default_factory=DelegateConfig)
    slo: SloConfig = field(default_factory=SloConfig)
    raw: dict[str, Any] = field(default_factory=dict)


def load_config(config_path: Optional[Path] = None) -> FinOpsConfig:
    """Load configuration from a YAML file or use defaults.

    Searches for configuration in this order:
      1. Explicit path provided via --config CLI flag
      2. finops.yaml in the current working directory
      3. ~/.finops/config.yaml
      4. config/default.yaml relative to the package
      5. Built-in defaults (no file needed)

    Args:
        config_path: Optional explicit path to a YAML config file.

    Returns:
        A FinOpsConfig object with merged settings.
    """
    # Determine which config file to load
    paths_to_try: list[Path] = []

    if config_path:
        paths_to_try.append(config_path)
    else:
        paths_to_try.extend([
            Path.cwd() / "finops.yaml",
            Path.home() / ".finops" / "config.yaml",
            Path(__file__).parent.parent.parent / "config" / "default.yaml",
        ])

    # Try each path in order
    raw_config: dict[str, Any] = {}
    for path in paths_to_try:
        if path.exists():
            with open(path) as f:
                raw_config = yaml.safe_load(f) or {}
            break

    # Merge with defaults
    thresholds = dict(DEFAULT_THRESHOLDS)
    thresholds.update(raw_config.get("thresholds", {}))

    checks = dict(DEFAULT_CHECKS)
    checks.update(raw_config.get("checks", {}))

    accounts = raw_config.get("accounts", [])
    # Normalize account entries — support both string and dict formats
    normalized_accounts: list[dict[str, str]] = []
    for account in accounts:
        if isinstance(account, str):
            normalized_accounts.append({"profile": account, "name": account})
        elif isinstance(account, dict):
            normalized_accounts.append(account)

    # Parse web configuration
    raw_web = raw_config.get("web", {})
    web_config = WebConfig(
        host=raw_web.get("host", "127.0.0.1"),
        port=raw_web.get("port", 8080),
        debug=raw_web.get("debug", False),
    )

    # Parse LLM configuration
    raw_llm = raw_config.get("llm", {})
    llm_config = LLMConfig(
        provider=raw_llm.get("provider", "claude"),
        api_key_env=raw_llm.get("api_key_env", ""),
        model=raw_llm.get("model", ""),
    )

    # Parse database configuration
    raw_db = raw_config.get("database", {})
    db_config = DatabaseConfig(
        path=raw_db.get("path", ""),
    )

    # Parse delegate configuration
    raw_delegates = raw_config.get("delegates", {})
    delegate_config = DelegateConfig(
        max_concurrent=raw_delegates.get("max_concurrent", 3),
        default_schedule=raw_delegates.get("default_schedule", "0 8 * * 1"),
    )

    # Parse the live error budget source
    raw_slo = raw_config.get("slo") or {}
    slo_config = SloConfig(
        prometheus_url=raw_slo.get("prometheus_url", ""),
        timeout_seconds=float(raw_slo.get("timeout_seconds", 5.0)),
        services={str(k): str(v) for k, v in (raw_slo.get("services") or {}).items()},
    )

    return FinOpsConfig(
        thresholds=thresholds,
        accounts=normalized_accounts,
        checks=checks,
        web=web_config,
        llm=llm_config,
        database=db_config,
        delegates=delegate_config,
        slo=slo_config,
        raw=raw_config,
    )
