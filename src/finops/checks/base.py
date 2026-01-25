"""Base check class — abstract interface for all cost optimization checks.

Every check must implement:
  - name:        A unique identifier string (e.g., "ec2_rightsizing")
  - description: A human-readable description of what the check finds
  - run():       Execute the check and return a list of CheckResult findings
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from finops.config import FinOpsConfig


@dataclass
class CheckResult:
    """A single cost optimization finding.

    Represents one resource that has a cost optimization opportunity,
    including what it is, what it costs, what to do, and how much you'd save.
    """

    check_name: str
    resource_type: str          # e.g., "EC2 Instance", "NAT Gateway", "EBS Volume"
    resource_id: str            # e.g., "i-0a1b2c3d", "nat-0abc1234", "vol-0ff1234a"
    resource_name: str          # e.g., "web-prod", from Name tag
    current_monthly_cost: float # Current estimated monthly cost in USD
    recommended_action: str     # e.g., "Downsize to m5.large (avg CPU 8%)"
    estimated_monthly_savings: float  # Estimated monthly savings in USD
    severity: str = "medium"    # "low", "medium", "high", "critical"
    details: dict[str, Any] = field(default_factory=dict)  # Additional context

    @property
    def estimated_annual_savings(self) -> float:
        """Calculate annualized savings."""
        return self.estimated_monthly_savings * 12

    @property
    def savings_percentage(self) -> float:
        """Calculate savings as a percentage of current cost."""
        if self.current_monthly_cost == 0:
            return 0.0
        return (self.estimated_monthly_savings / self.current_monthly_cost) * 100

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON export."""
        return {
            "check_name": self.check_name,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "current_monthly_cost": self.current_monthly_cost,
            "recommended_action": self.recommended_action,
            "estimated_monthly_savings": self.estimated_monthly_savings,
            "estimated_annual_savings": self.estimated_annual_savings,
            "savings_percentage": round(self.savings_percentage, 1),
            "severity": self.severity,
            "details": self.details,
        }


class BaseCheck(ABC):
    """Abstract base class for all cost optimization checks.

    Subclasses must set `name` and `description` as class attributes,
    and implement the `run()` method.

    Example:
        class MyCheck(BaseCheck):
            name = "my_check"
            description = "Find wasted resources of type X"

            def run(self, session, region):
                # Use session to create boto3 clients
                # Scan resources and return findings
                return [CheckResult(...)]
    """

    name: str = ""
    description: str = ""

    def __init__(self, config: FinOpsConfig) -> None:
        """Initialize the check with configuration.

        Args:
            config: The FinOps configuration containing thresholds and settings.
        """
        self.config = config

    @abstractmethod
    def run(self, session: Any, region: str) -> list[CheckResult]:
        """Execute the check against an AWS account.

        Args:
            session: An authenticated boto3.Session for the target account.
            region: The AWS region to scan.

        Returns:
            A list of CheckResult findings. Empty list if no issues found.
        """
        ...

    def get_resource_name(self, tags: Optional[list[dict[str, str]]]) -> str:
        """Extract the Name tag value from a list of AWS resource tags.

        Args:
            tags: List of {"Key": "...", "Value": "..."} dicts from AWS API.

        Returns:
            The Name tag value, or "(unnamed)" if not found.
        """
        if not tags:
            return "(unnamed)"
        for tag in tags:
            if tag.get("Key") == "Name":
                return tag.get("Value", "(unnamed)")
        return "(unnamed)"

    def get_tag_value(self, tags: Optional[list[dict[str, str]]], key: str) -> Optional[str]:
        """Extract a specific tag value from AWS resource tags.

        Args:
            tags: List of {"Key": "...", "Value": "..."} dicts from AWS API.
            key: The tag key to look for.

        Returns:
            The tag value, or None if not found.
        """
        if not tags:
            return None
        for tag in tags:
            if tag.get("Key") == key:
                return tag.get("Value")
        return None

    def is_production(self, tags: Optional[list[dict[str, str]]], name: str = "") -> bool:
        """Heuristic to determine if a resource is in a production environment.

        Checks the 'Environment' tag and the Name tag for common patterns.

        Args:
            tags: AWS resource tags.
            name: Resource name (from Name tag).

        Returns:
            True if the resource appears to be in production.
        """
        env_tag = self.get_tag_value(tags, "Environment") or ""
        env_tag = env_tag.lower()

        prod_indicators = ["prod", "production", "prd"]
        for indicator in prod_indicators:
            if indicator in env_tag or indicator in name.lower():
                return True

        return False
