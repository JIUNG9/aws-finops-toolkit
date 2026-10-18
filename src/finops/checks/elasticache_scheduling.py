"""ElastiCache Scheduling Check — Detect dev/staging clusters that should be stopped off-hours.

ElastiCache (Redis/Memcached) clusters in non-production environments often
run 24/7 when they're only needed during business hours. Stopping them during
off-hours (e.g., 8pm-8am weekdays, all day weekends) saves roughly 50%.

Note: ElastiCache Serverless automatically scales to zero, but traditional
clusters (which are far more common) require manual stopping or automation.

This check:
  1. Lists all ElastiCache clusters
  2. Identifies non-production clusters by tags/name
  3. Calculates potential savings from off-hours scheduling
  4. Recommends scheduling or migration to Serverless

Typical savings: ~50% per non-prod cluster.

AWS APIs used:
  - elasticache:DescribeCacheClusters
  - elasticache:DescribeReplicationGroups
  - elasticache:ListTagsForResource
"""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from finops.checks.base import BaseCheck, CheckResult

# ElastiCache node pricing (us-east-1, approximate)
ELASTICACHE_NODE_PRICING: dict[str, float] = {
    "cache.t3.micro": 0.017,
    "cache.t3.small": 0.034,
    "cache.t3.medium": 0.068,
    "cache.m5.large": 0.156,
    "cache.m5.xlarge": 0.311,
    "cache.m5.2xlarge": 0.622,
    "cache.m6g.large": 0.137,
    "cache.m6g.xlarge": 0.274,
    "cache.r5.large": 0.166,
    "cache.r5.xlarge": 0.332,
    "cache.r6g.large": 0.146,
    "cache.r6g.xlarge": 0.292,
    "cache.r6g.2xlarge": 0.584,
}

HOURS_PER_MONTH = 730

# Off-hours ratio: assuming 12 hours off on weekdays + all day weekends
# Weekdays: 12/24 = 50% off. Weekends: 48/168 = 29% of the week.
# Total off-hours: (5 * 12 + 2 * 24) / (7 * 24) = 108/168 = 64%
# But we use 50% as a conservative estimate (some teams work odd hours)
OFF_HOURS_SAVINGS_RATIO = 0.50


class ElastiCacheSchedulingCheck(BaseCheck):
    """Detect dev/staging ElastiCache clusters that should be stopped off-hours."""

    name = "elasticache_scheduling"
    description = "Find non-production ElastiCache clusters running 24/7 that could be scheduled"

    def run(self, session: Any, region: str) -> list[CheckResult]:
        """Execute ElastiCache scheduling check.

        Args:
            session: Authenticated boto3.Session.
            region: AWS region to scan.

        Returns:
            List of CheckResult for non-prod clusters that should be scheduled.
        """
        ec_client = session.client("elasticache", region_name=region)

        # Step 1: collect available clusters, grouping replication-group members.
        # Every node of a Redis replication group is its own cache cluster, but
        # you can only schedule the group as a whole, so it gets one finding.
        groups: dict[str, list[dict]] = {}
        paginator = ec_client.get_paginator("describe_cache_clusters")
        for page in paginator.paginate(ShowCacheNodeInfo=True):
            for cluster in page["CacheClusters"]:
                if cluster.get("CacheClusterStatus") != "available":
                    continue
                key = cluster.get("ReplicationGroupId") or cluster["CacheClusterId"]
                groups.setdefault(key, []).append(cluster)

        results: list[CheckResult] = []
        for group_id, members in groups.items():
            node_type = members[0]["CacheNodeType"]
            engine = members[0]["Engine"]
            num_nodes = sum(m.get("NumCacheNodes", 1) for m in members)

            # Step 2: environment. Unreadable tags are not "no tags": without
            # them we can't tell prod from dev, so the group is skipped.
            member_tags = self._member_tags(ec_client, members)
            if member_tags is None:
                continue
            # Judge each member on its own tags: merged, the first Environment
            # tag would hide a prod member behind a dev one.
            if self.is_production(None, group_id) or any(
                self.is_production(t, self.get_resource_name(t)) for t in member_tags
            ):
                continue
            name = self.get_resource_name(member_tags[0])
            label = name if name != "(unnamed)" else group_id

            # Step 3: cost. Unknown node types price at 0 and are skipped
            # rather than reported with a made-up number.
            monthly_cost = self._estimate_monthly_cost(node_type, num_nodes)
            if monthly_cost == 0:
                continue
            savings = monthly_cost * OFF_HOURS_SAVINGS_RATIO

            # Step 4: ElastiCache has no stop. The saving comes from deleting
            # the cluster off-hours, so what survives the delete matters.
            if engine == "redis":
                action = (
                    f"Schedule off-hours snapshot + delete, restore in the morning "
                    f"(8pm-8am, weekends) — {num_nodes}x {node_type} ({engine}), "
                    f"~{OFF_HOURS_SAVINGS_RATIO * 100:.0f}% savings"
                )
            else:
                action = (
                    f"Consider ElastiCache Serverless — {num_nodes}x {node_type} "
                    f"({engine}) has no snapshots, so a scheduled delete loses the cache"
                )

            results.append(CheckResult(
                check_name=self.name,
                resource_type="ElastiCache Cluster",
                resource_id=group_id,
                resource_name=label,
                current_monthly_cost=monthly_cost,
                recommended_action=action,
                estimated_monthly_savings=savings,
                severity="medium",
                details={
                    "engine": engine,
                    "node_type": node_type,
                    "num_nodes": num_nodes,
                    "replication_group": members[0].get("ReplicationGroupId"),
                    "off_hours_ratio": OFF_HOURS_SAVINGS_RATIO,
                },
            ))

        return results

    def _member_tags(self, ec_client: Any, members: list[dict]) -> list[list[dict]] | None:
        """Tags per member, or None if any member's tags can't be read."""
        out: list[list[dict]] = []
        for member in members:
            try:
                resp = ec_client.list_tags_for_resource(ResourceName=member["ARN"])
            except (ClientError, KeyError):
                return None
            out.append(resp.get("TagList", []))
        return out

    def _estimate_monthly_cost(self, node_type: str, num_nodes: int) -> float:
        """Estimate monthly cost for an ElastiCache cluster.

        Args:
            node_type: ElastiCache node type (e.g., "cache.r6g.large").
            num_nodes: Number of cache nodes in the cluster.

        Returns:
            Estimated monthly cost in USD.
        """
        hourly = ELASTICACHE_NODE_PRICING.get(node_type)
        if hourly is None:
            # TODO: Fall back to AWS Pricing API
            return 0.0
        return hourly * HOURS_PER_MONTH * num_nodes
