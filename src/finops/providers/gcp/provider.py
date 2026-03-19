"""GCP cloud provider stub — Phase 2."""

from __future__ import annotations

from typing import Any

from finops.providers.base import CloudProvider, CloudResource, CostDataPoint, register_provider


class GCPProvider(CloudProvider):
    """GCP provider — not yet implemented."""

    name = "gcp"

    async def test_connection(self, config: dict) -> bool:
        raise NotImplementedError("GCP provider coming in Phase 2")

    async def get_session(self, config: dict) -> Any:
        raise NotImplementedError("GCP provider coming in Phase 2")

    async def list_resources(self, session: Any, resource_type: str, region: str) -> list[CloudResource]:
        raise NotImplementedError("GCP provider coming in Phase 2")

    async def get_metrics(self, session: Any, resource_id: str, metric_name: str,
                          period_days: int = 14) -> list[dict]:
        raise NotImplementedError("GCP provider coming in Phase 2")

    async def get_cost_data(self, session: Any, start_date: str, end_date: str,
                            granularity: str = "DAILY") -> list[CostDataPoint]:
        raise NotImplementedError("GCP provider coming in Phase 2")

    def get_supported_checks(self) -> list[str]:
        return []


register_provider("gcp", GCPProvider)
