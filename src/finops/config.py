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
    "s3_high_object_count": 1_000_000,
}

# Default check enable/disable flags
DEFAULT_CHECKS: dict[str, bool] = {
    "ec2_rightsizing": True,
    "nat_gateway": True,
    "spot_candidates": True,
    "unused_resources": True,
    "reserved_instances": True,
    "elasticache_scheduling": True,
    "rds_rightsizing": True,
    "vpc_waste": True,
    "cloudwatch_waste": True,
    "s3_lifecycle": True,
}

# Default preflight configuration
DEFAULT_PREFLIGHT: dict[str, Any] = {
    "traffic": {
        "peak_avg_ratio_warn": 3.0,
        "lookback_days": 30,
        "low_traffic_window": "02:00-06:00",
    },
    "slo": {
        "p99_latency_ms": 200,
        "availability_pct": 99.9,
        "error_budget_go_pct": 70,
        "error_budget_warn_pct": 40,
    },
    "apm": {
        "provider": "cloudwatch",
        "endpoint": "",
        "api_key_env": "",
    },
    "cache": {
        "high_dependency_pct": 80,
    },
    "incidents": {
        "lookback_days": 90,
        "capacity_cooldown_days": 60,
        "source": "cloudwatch",
    },
    "priority": {
        "tag_key": "Priority",
        "freeze_tag_key": "DeployFreeze",
        "levels": {
            "P0": {
                "label": "Critical path", "prod_changes": "maintenance_window",
                "requires_approval": True, "approval_from": "team lead + SRE",
            },
            "P1": {"label": "Important", "prod_changes": "off_peak", "requires_approval": True, "approval_from": "SRE"},
            "P2": {"label": "Standard", "prod_changes": "business_hours", "requires_approval": False},
            "P3": {"label": "Non-critical", "prod_changes": "anytime", "requires_approval": False},
        },
    },
    "services": [],
}


@dataclass
class ServiceConfig:
    """A service definition from the service catalog.

    Maps AWS resources to a logical service with SLO targets,
    dependencies, and priority classification.
    """
    name: str
    priority: str = "P2"                                # P0, P1, P2, P3
    stateless: bool = False
    resources: list[str] = field(default_factory=list)  # Instance IDs or tag patterns
    cache_cluster: str = ""                             # ElastiCache cluster ID
    dependencies_upstream: list[str] = field(default_factory=list)
    dependencies_downstream: list[str] = field(default_factory=list)
    slo_overrides: dict[str, Any] = field(default_factory=dict)  # Per-service SLO overrides


@dataclass
class PreflightConfig:
    """Pre-flight analysis configuration.

    Controls SLO targets, APM integration, priority rules,
    and service catalog. All values have sensible defaults —
    users override what's relevant to their environment.
    """
    traffic: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_PREFLIGHT["traffic"]))
    slo: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_PREFLIGHT["slo"]))
    apm: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_PREFLIGHT["apm"]))
    cache: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_PREFLIGHT["cache"]))
    incidents: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_PREFLIGHT["incidents"]))
    priority: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_PREFLIGHT["priority"]))
    services: list[ServiceConfig] = field(default_factory=list)

    def get_service(self, name: str) -> Optional[ServiceConfig]:
        """Look up a service by name."""
        for svc in self.services:
            if svc.name == name:
                return svc
        return None

    def get_service_by_resource(self, resource_id: str) -> Optional[ServiceConfig]:
        """Look up a service by one of its resource IDs."""
        for svc in self.services:
            if resource_id in svc.resources:
                return svc
        return None

    def get_slo_for_service(self, service_name: str) -> dict[str, Any]:
        """Get SLO targets for a service (per-service override or global default)."""
        svc = self.get_service(service_name)
        if svc and svc.slo_overrides:
            merged = dict(self.slo)
            merged.update(svc.slo_overrides)
            return merged
        return dict(self.slo)

    def get_priority_rules(self, level: str) -> dict[str, Any]:
        """Get priority rules for a given level (P0, P1, P2, P3)."""
        levels = self.priority.get("levels", {})
        return levels.get(level, levels.get("P2", {}))


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
class FinOpsConfig:
    """Parsed FinOps toolkit configuration.

    Attributes:
        thresholds: Dict of threshold values (CPU %, age days, etc.)
        accounts: List of account configs (each with 'profile', 'name')
        checks: Dict of check name -> enabled boolean
        preflight: Pre-flight analysis configuration
        web: Web dashboard settings
        llm: LLM provider settings
        database: Database settings
        delegates: Background worker settings
        raw: The raw parsed YAML dict (for extension)
    """

    thresholds: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    accounts: list[dict[str, str]] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_CHECKS))
    preflight: PreflightConfig = field(default_factory=PreflightConfig)
    web: WebConfig = field(default_factory=WebConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    delegates: DelegateConfig = field(default_factory=DelegateConfig)
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

    # Parse preflight configuration
    raw_preflight = raw_config.get("preflight", {})
    preflight_traffic = dict(DEFAULT_PREFLIGHT["traffic"])
    preflight_traffic.update(raw_preflight.get("traffic", {}))
    preflight_slo = dict(DEFAULT_PREFLIGHT["slo"])
    preflight_slo.update(raw_preflight.get("slo", {}))
    preflight_apm = dict(DEFAULT_PREFLIGHT["apm"])
    preflight_apm.update(raw_preflight.get("apm", {}))
    preflight_cache = dict(DEFAULT_PREFLIGHT["cache"])
    preflight_cache.update(raw_preflight.get("cache", {}))
    preflight_incidents = dict(DEFAULT_PREFLIGHT["incidents"])
    preflight_incidents.update(raw_preflight.get("incidents", {}))
    preflight_priority = dict(DEFAULT_PREFLIGHT["priority"])
    preflight_priority.update(raw_preflight.get("priority", {}))

    # Parse service catalog
    services: list[ServiceConfig] = []
    for svc_raw in raw_preflight.get("services", []):
        deps = svc_raw.get("dependencies", {})
        services.append(ServiceConfig(
            name=svc_raw.get("name", ""),
            priority=svc_raw.get("priority", "P2"),
            stateless=svc_raw.get("stateless", False),
            resources=svc_raw.get("resources", []),
            cache_cluster=svc_raw.get("cache_cluster", ""),
            dependencies_upstream=deps.get("upstream", []),
            dependencies_downstream=deps.get("downstream", []),
            slo_overrides=svc_raw.get("slo", {}),
        ))

    preflight_config = PreflightConfig(
        traffic=preflight_traffic,
        slo=preflight_slo,
        apm=preflight_apm,
        cache=preflight_cache,
        incidents=preflight_incidents,
        priority=preflight_priority,
        services=services,
    )

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

    return FinOpsConfig(
        thresholds=thresholds,
        accounts=normalized_accounts,
        checks=checks,
        preflight=preflight_config,
        web=web_config,
        llm=llm_config,
        database=db_config,
        delegates=delegate_config,
        raw=raw_config,
    )
