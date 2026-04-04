"""Abstract base classes for cloud providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CloudResource:
    """Normalized cloud resource across providers."""
    provider: str
    resource_type: str
    resource_id: str
    resource_name: str
    region: str
    tags: dict[str, str] = field(default_factory=dict)
    monthly_cost: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CostDataPoint:
    """Normalized cost data point."""
    date: str
    amount: float
    currency: str = "USD"
    service: str = ""
    account_id: str = ""


class CloudProvider(ABC):
    """Abstract base class for cloud providers."""

    name: str

    @abstractmethod
    async def test_connection(self, config: dict) -> bool:
        """Test if credentials are valid."""
        ...

    @abstractmethod
    async def get_session(self, config: dict) -> Any:
        """Create an authenticated session."""
        ...

    @abstractmethod
    async def list_resources(self, session: Any, resource_type: str, region: str) -> list[CloudResource]:
        """List resources of a given type."""
        ...

    @abstractmethod
    async def get_metrics(self, session: Any, resource_id: str, metric_name: str,
                          period_days: int = 14) -> list[dict]:
        """Get CloudWatch-style metrics for a resource."""
        ...

    @abstractmethod
    async def get_cost_data(self, session: Any, start_date: str, end_date: str,
                            granularity: str = "DAILY") -> list[CostDataPoint]:
        """Get cost data for a date range."""
        ...

    @abstractmethod
    def get_supported_checks(self) -> list[str]:
        """Return list of check names this provider supports."""
        ...


# Provider registry
_PROVIDERS: dict[str, type[CloudProvider]] = {}


def register_provider(name: str, cls: type[CloudProvider]) -> None:
    _PROVIDERS[name] = cls


def get_provider(name: str) -> CloudProvider:
    if name not in _PROVIDERS:
        raise ValueError(f"Unknown provider: {name}. Available: {list(_PROVIDERS.keys())}")
    return _PROVIDERS[name]()
