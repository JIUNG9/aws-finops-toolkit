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
}


@dataclass
class FinOpsConfig:
    """Parsed FinOps toolkit configuration.

    Attributes:
        thresholds: Dict of threshold values (CPU %, age days, etc.)
        accounts: List of account configs (each with 'profile', 'name')
        checks: Dict of check name -> enabled boolean
        raw: The raw parsed YAML dict (for extension)
    """

    thresholds: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    accounts: list[dict[str, str]] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_CHECKS))
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

    return FinOpsConfig(
        thresholds=thresholds,
        accounts=normalized_accounts,
        checks=checks,
        raw=raw_config,
    )
