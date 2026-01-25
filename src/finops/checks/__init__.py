"""Check registry — central registry of all cost optimization checks.

Each check is a class that inherits from BaseCheck. This module provides
a registry that maps check names to their implementations and handles
filtering based on configuration.
"""

from __future__ import annotations

from typing import Optional

from finops.checks.base import BaseCheck
from finops.checks.ec2_rightsizing import EC2RightsizingCheck
from finops.checks.nat_gateway import NATGatewayCheck
from finops.checks.spot_candidates import SpotCandidatesCheck
from finops.checks.unused_resources import UnusedResourcesCheck
from finops.checks.reserved_instances import ReservedInstancesCheck
from finops.checks.elasticache_scheduling import ElastiCacheSchedulingCheck
from finops.checks.rds_rightsizing import RDSRightsizingCheck
from finops.config import FinOpsConfig


# Registry of all available checks, keyed by their name
CHECKS: dict[str, type[BaseCheck]] = {
    "ec2_rightsizing": EC2RightsizingCheck,
    "nat_gateway": NATGatewayCheck,
    "spot_candidates": SpotCandidatesCheck,
    "unused_resources": UnusedResourcesCheck,
    "reserved_instances": ReservedInstancesCheck,
    "elasticache_scheduling": ElastiCacheSchedulingCheck,
    "rds_rightsizing": RDSRightsizingCheck,
}


def get_enabled_checks(
    config: FinOpsConfig,
    check_names: Optional[list[str]] = None,
) -> list[BaseCheck]:
    """Return instantiated check objects filtered by config and CLI args.

    Args:
        config: The loaded FinOps configuration with enable/disable flags.
        check_names: Optional list of check names from CLI --checks flag.
                     If provided, only these checks run (overrides config).

    Returns:
        List of instantiated BaseCheck subclasses ready to run.
    """
    enabled: list[BaseCheck] = []

    for name, check_cls in CHECKS.items():
        # If CLI specifies checks, use that as the filter
        if check_names is not None:
            if name in check_names:
                enabled.append(check_cls(config=config))
        else:
            # Otherwise, use the config enable/disable flags
            if config.checks.get(name, True):
                enabled.append(check_cls(config=config))

    return enabled


def list_checks() -> dict[str, str]:
    """Return a mapping of check names to descriptions.

    Useful for CLI help and documentation.
    """
    return {name: cls.description for name, cls in CHECKS.items()}
