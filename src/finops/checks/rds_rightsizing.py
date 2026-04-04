"""RDS Right-Sizing Check — Find oversized RDS instances and unnecessary Multi-AZ.

RDS instances are often over-provisioned "just in case" and never right-sized.
Common issues:
  1. Instances with very low CPU and connection counts
  2. Multi-AZ enabled in dev/staging (doubles the cost for no benefit)
  3. Provisioned IOPS when gp3 would suffice

This check:
  1. Lists all RDS instances
  2. Queries CloudWatch for CPU and database connections
  3. Flags instances with low utilization
  4. Flags Multi-AZ in non-production environments
  5. Recommends smaller instance classes
  6. Parameter group compatibility when changing instance class (memory-dependent params)
  7. CDC/logical replication impact — replication slots, WAL retention, lag risk
  8. Cold buffer pool cache after instance change — warm-up period needed

Typical savings: 30-50% per right-sized instance.

AWS APIs used:
  - rds:DescribeDBInstances
  - cloudwatch:GetMetricStatistics
"""

from __future__ import annotations

from typing import Any

from finops.checks.base import BaseCheck, CheckResult


# RDS instance pricing (us-east-1, Single-AZ, approximate hourly)
RDS_INSTANCE_PRICING: dict[str, float] = {
    "db.t3.micro": 0.017,
    "db.t3.small": 0.034,
    "db.t3.medium": 0.068,
    "db.t3.large": 0.136,
    "db.m5.large": 0.171,
    "db.m5.xlarge": 0.342,
    "db.m5.2xlarge": 0.684,
    "db.m5.4xlarge": 1.368,
    "db.m6i.large": 0.171,
    "db.m6i.xlarge": 0.342,
    "db.m6i.2xlarge": 0.684,
    "db.r5.large": 0.240,
    "db.r5.xlarge": 0.480,
    "db.r5.2xlarge": 0.960,
    "db.r5.4xlarge": 1.920,
    "db.r6i.large": 0.240,
    "db.r6i.xlarge": 0.480,
    "db.r6i.2xlarge": 0.960,
    "db.r6g.large": 0.210,
    "db.r6g.xlarge": 0.418,
    "db.r6g.2xlarge": 0.836,
}

# RDS downsizing map: current size -> recommended smaller size
RDS_DOWNSIZE_MAP: dict[str, str] = {
    "xlarge": "large",
    "2xlarge": "xlarge",
    "4xlarge": "2xlarge",
    "8xlarge": "4xlarge",
    "12xlarge": "8xlarge",
    "16xlarge": "12xlarge",
}

HOURS_PER_MONTH = 730

# Memory-dependent parameters that change with instance size
# When downsizing, these may need reconfiguration
MEMORY_DEPENDENT_PARAMS = [
    "shared_buffers",        # PostgreSQL: typically 25% of RAM
    "effective_cache_size",  # PostgreSQL: typically 75% of RAM
    "work_mem",              # PostgreSQL: scales with available RAM
    "innodb_buffer_pool_size",  # MySQL: typically 70-80% of RAM
    "innodb_log_buffer_size",   # MySQL: scales with buffer pool
]


class RDSRightsizingCheck(BaseCheck):
    """Find oversized RDS instances and unnecessary Multi-AZ in non-production."""

    name = "rds_rightsizing"
    description = "Find RDS instances with low utilization and unnecessary Multi-AZ in non-prod"

    def run(self, session: Any, region: str) -> list[CheckResult]:
        """Execute RDS right-sizing check.

        Args:
            session: Authenticated boto3.Session.
            region: AWS region to scan.

        Returns:
            List of CheckResult for each RDS optimization found.
        """
        results: list[CheckResult] = []

        # Thresholds used by TODO implementation below
        self.config.thresholds.get("ec2_cpu_avg_percent", 20)
        self.config.thresholds.get("ec2_lookback_days", 14)

        # TODO: Uncomment and implement with real boto3 calls
        #
        # rds_client = session.client("rds", region_name=region)
        # cw_client = session.client("cloudwatch", region_name=region)
        #
        # # Step 1: List all RDS instances
        # paginator = rds_client.get_paginator("describe_db_instances")
        #
        # for page in paginator.paginate():
        #     for db in page["DBInstances"]:
        #         db_id = db["DBInstanceIdentifier"]
        #         db_class = db["DBInstanceClass"]
        #         engine = db["Engine"]          # "postgres", "mysql", "aurora-postgresql", etc.
        #         multi_az = db["MultiAZ"]
        #         status = db["DBInstanceStatus"]
        #
        #         if status != "available":
        #             continue
        #
        #         # Get tags for environment detection
        #         tags_response = rds_client.list_tags_for_resource(
        #             ResourceName=db["DBInstanceArn"]
        #         )
        #         tags = [
        #             {"Key": t["Key"], "Value": t["Value"]}
        #             for t in tags_response.get("TagList", [])
        #         ]
        #         is_prod = self.is_production(tags, db_id)
        #
        #         # Step 2: Query CloudWatch for CPU utilization
        #         end_time = datetime.now(timezone.utc)
        #         start_time = end_time - timedelta(days=lookback_days)
        #
        #         cpu_stats = cw_client.get_metric_statistics(
        #             Namespace="AWS/RDS",
        #             MetricName="CPUUtilization",
        #             Dimensions=[
        #                 {"Name": "DBInstanceIdentifier", "Value": db_id},
        #             ],
        #             StartTime=start_time,
        #             EndTime=end_time,
        #             Period=86400,
        #             Statistics=["Average"],
        #         )
        #
        #         avg_cpu = 0.0
        #         if cpu_stats["Datapoints"]:
        #             avg_cpu = sum(
        #                 dp["Average"] for dp in cpu_stats["Datapoints"]
        #             ) / len(cpu_stats["Datapoints"])
        #
        #         # Step 3: Query CloudWatch for database connections
        #         conn_stats = cw_client.get_metric_statistics(
        #             Namespace="AWS/RDS",
        #             MetricName="DatabaseConnections",
        #             Dimensions=[
        #                 {"Name": "DBInstanceIdentifier", "Value": db_id},
        #             ],
        #             StartTime=start_time,
        #             EndTime=end_time,
        #             Period=86400,
        #             Statistics=["Average"],
        #         )
        #
        #         avg_connections = 0.0
        #         if conn_stats["Datapoints"]:
        #             avg_connections = sum(
        #                 dp["Average"] for dp in conn_stats["Datapoints"]
        #             ) / len(conn_stats["Datapoints"])
        #
        #         # Step 4: Check for right-sizing opportunity (low CPU)
        #         current_monthly = self._estimate_monthly_cost(db_class, multi_az)
        #
        #         if avg_cpu < cpu_threshold and avg_cpu > 0:
        #             smaller_class = self._get_smaller_class(db_class)
        #             if smaller_class:
        #                 smaller_monthly = self._estimate_monthly_cost(smaller_class, multi_az)
        #                 savings = current_monthly - smaller_monthly
        #
        #                 results.append(CheckResult(
        #                     check_name=self.name,
        #                     resource_type="RDS Instance",
        #                     resource_id=db_id,
        #                     resource_name=db_id,
        #                     current_monthly_cost=current_monthly,
        #                     recommended_action=(
        #                         f"Downsize to {smaller_class} — "
        #                         f"avg CPU {avg_cpu:.0f}%, "
        #                         f"avg {avg_connections:.0f} connections"
        #                     ),
        #                     estimated_monthly_savings=savings,
        #                     severity="high" if savings > 100 else "medium",
        #                     details={
        #                         "db_class": db_class,
        #                         "recommended_class": smaller_class,
        #                         "engine": engine,
        #                         "avg_cpu": round(avg_cpu, 1),
        #                         "avg_connections": round(avg_connections, 1),
        #                         "multi_az": multi_az,
        #                         "reason": "low_cpu",
        #                     },
        #                 ))
        #
        #         # Step 5: Check for unnecessary Multi-AZ in non-prod
        #         if multi_az and not is_prod:
        #             # Multi-AZ doubles the cost
        #             single_az_cost = self._estimate_monthly_cost(db_class, multi_az=False)
        #             multi_az_savings = current_monthly - single_az_cost
        #
        #             results.append(CheckResult(
        #                 check_name=self.name,
        #                 resource_type="RDS Instance",
        #                 resource_id=db_id,
        #                 resource_name=db_id,
        #                 current_monthly_cost=current_monthly,
        #                 recommended_action=(
        #                     f"Convert to Single-AZ — "
        #                     f"Multi-AZ in non-production ({engine})"
        #                 ),
        #                 estimated_monthly_savings=multi_az_savings,
        #                 severity="medium",
        #                 details={
        #                     "db_class": db_class,
        #                     "engine": engine,
        #                     "multi_az": True,
        #                     "is_production": False,
        #                     "reason": "multi_az_non_prod",
        #                 },
        #             ))
        #
        #         # Step 6: Check parameter group and replication risks
        #         replication_risks = self._check_replication_and_params(db_id, db_class, engine)
        #         if replication_risks["has_custom_param_group"]:
        #             # Add warning: custom parameter group needs review after downsize
        #             pass
        #         if replication_risks["has_logical_replication"]:
        #             # Add warning: CDC active — monitor replication lag after downsize
        #             pass
        #         # Always note cold cache risk in details

        return results

    def _get_smaller_class(self, db_class: str) -> str | None:
        """Determine the next smaller RDS instance class.

        Args:
            db_class: Current RDS instance class (e.g., "db.r5.2xlarge").

        Returns:
            Recommended smaller class (e.g., "db.r5.xlarge"), or None.
        """
        # db_class format: "db.{family}.{size}" e.g., "db.r5.xlarge"
        parts = db_class.split(".")
        if len(parts) != 3:
            return None

        prefix, family, size = parts  # "db", "r5", "xlarge"

        if size == "large":
            return None  # Already the smallest practical size

        smaller_size = RDS_DOWNSIZE_MAP.get(size)
        if smaller_size is None:
            return None

        return f"{prefix}.{family}.{smaller_size}"

    def _estimate_monthly_cost(self, db_class: str, multi_az: bool = False) -> float:
        """Estimate monthly RDS cost.

        Args:
            db_class: RDS instance class (e.g., "db.r5.xlarge").
            multi_az: Whether Multi-AZ is enabled (doubles compute cost).

        Returns:
            Estimated monthly cost in USD.
        """
        hourly = RDS_INSTANCE_PRICING.get(db_class)
        if hourly is None:
            # TODO: Fall back to AWS Pricing API
            return 0.0

        monthly = hourly * HOURS_PER_MONTH
        if multi_az:
            monthly *= 2  # Multi-AZ doubles the instance cost

        return monthly

    def _check_replication_and_params(self, db_id: str, db_class: str, engine: str) -> dict[str, Any]:
        """Check for CDC/logical replication and parameter group risks.

        When downsizing RDS:
        - Parameter groups: Memory-dependent params (shared_buffers, innodb_buffer_pool_size)
          may need adjustment for the smaller instance. Default parameter groups auto-scale,
          but custom groups with hardcoded values will break.
        - CDC/Logical replication: If wal_level=logical (PostgreSQL) or binlog is enabled (MySQL),
          downsizing increases replication lag risk. Smaller instances have less I/O and memory
          for WAL processing.
        - Cold cache: After instance modification, the buffer pool starts empty. Factor in
          warm-up period (30-60 minutes) during low-traffic window.

        Returns dict with risk flags and details.
        """
        risks: dict[str, Any] = {
            "has_custom_param_group": False,
            "memory_dependent_params": [],
            "has_logical_replication": False,
            "replication_slot_count": 0,
            "cold_cache_risk": True,  # Always true for RDS modifications
            "cold_cache_warmup_minutes": 30,  # Estimate
        }

        # TODO: Implement with real boto3 calls
        # Step 1: Check parameter group
        # rds_client.describe_db_instances() → db["DBParameterGroups"]
        # If parameter group name != "default.postgres*" / "default.mysql*":
        #   risks["has_custom_param_group"] = True
        #   rds_client.describe_db_parameters(DBParameterGroupName=pg_name)
        #   Check for MEMORY_DEPENDENT_PARAMS with hardcoded (non-default) values

        # Step 2: Check logical replication (CDC)
        # PostgreSQL: check parameter "rds.logical_replication" == "1"
        # MySQL: check parameter "log_bin" / "binlog_format"
        # If logical replication enabled:
        #   risks["has_logical_replication"] = True
        #   Check pg_replication_slots (via CloudWatch ReplicationSlotDiskUsage metric)

        # Step 3: Estimate cold cache warmup
        # Larger instances = longer warmup (more buffer pool to fill)
        # db.r6g.xlarge (~32GB RAM, ~8GB shared_buffers) → ~45 min warmup
        # db.r6g.large (~16GB RAM, ~4GB shared_buffers) → ~30 min warmup

        return risks
