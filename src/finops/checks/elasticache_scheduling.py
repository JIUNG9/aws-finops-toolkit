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
        results: list[CheckResult] = []

        # TODO: Uncomment and implement with real boto3 calls
        #
        # ec_client = session.client("elasticache", region_name=region)
        #
        # # Step 1: List all cache clusters
        # paginator = ec_client.get_paginator("describe_cache_clusters")
        #
        # for page in paginator.paginate(ShowCacheNodeInfo=True):
        #     for cluster in page["CacheClusters"]:
        #         cluster_id = cluster["CacheClusterId"]
        #         node_type = cluster["CacheNodeType"]
        #         engine = cluster["Engine"]  # "redis" or "memcached"
        #         num_nodes = cluster.get("NumCacheNodes", 1)
        #         status = cluster["CacheClusterStatus"]
        #
        #         if status != "available":
        #             continue
        #
        #         # Step 2: Get tags for environment detection
        #         # ElastiCache ARN format:
        #         # arn:aws:elasticache:{region}:{account}:cluster:{id}
        #         try:
        #             arn = cluster["ARN"]
        #             tag_response = ec_client.list_tags_for_resource(
        #                 ResourceName=arn
        #             )
        #             tags = [
        #                 {"Key": t["Key"], "Value": t["Value"]}
        #                 for t in tag_response.get("TagList", [])
        #             ]
        #         except Exception:
        #             tags = []
        #
        #         # Step 3: Skip production clusters
        #         if self.is_production(tags, cluster_id):
        #             continue
        #
        #         # Step 4: Calculate monthly cost and potential savings
        #         monthly_cost = self._estimate_monthly_cost(node_type, num_nodes)
        #         savings = monthly_cost * OFF_HOURS_SAVINGS_RATIO
        #
        #         if monthly_cost == 0:
        #             continue
        #
        #         # Step 5: Determine recommendation
        #         # For Redis, we can stop/start the cluster
        #         # For Memcached, data is lost on stop — might recommend Serverless instead
        #         if engine == "redis":
        #             action = (
        #                 f"Schedule off-hours stop (8pm-8am, weekends) — "
        #                 f"{num_nodes}x {node_type} ({engine}), ~{OFF_HOURS_SAVINGS_RATIO*100:.0f}% savings"
        #             )
        #         else:
        #             action = (
        #                 f"Consider ElastiCache Serverless or schedule teardown — "
        #                 f"{num_nodes}x {node_type} ({engine}), non-prod"
        #             )
        #
        #         # Check if this is part of a replication group
        #         replication_group = cluster.get("ReplicationGroupId")
        #
        #         results.append(CheckResult(
        #             check_name=self.name,
        #             resource_type="ElastiCache Cluster",
        #             resource_id=cluster_id,
        #             resource_name=cluster_id,
        #             current_monthly_cost=monthly_cost,
        #             recommended_action=action,
        #             estimated_monthly_savings=savings,
        #             severity="medium",
        #             details={
        #                 "engine": engine,
        #                 "node_type": node_type,
        #                 "num_nodes": num_nodes,
        #                 "replication_group": replication_group,
        #                 "off_hours_ratio": OFF_HOURS_SAVINGS_RATIO,
        #             },
        #         ))

        return results

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
