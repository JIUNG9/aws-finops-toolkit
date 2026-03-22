"""CloudWatch Log Waste Detection — Find log groups silently burning money.

Based on real-world FinOps work finding $110-165/month in CloudWatch Logs
waste. The pattern: applications are deployed, log groups are created, but
nobody configures retention policies. Logs pile up forever at $0.03/GB/month
for storage plus $0.50/GB for ingestion.

Common culprits:
  - Orphan log groups from deleted Lambda functions, ECS services, or pods
  - Log groups with infinite retention (no retention policy set)
  - Non-prod log groups retaining data for 365+ days
  - High-ingestion log groups that should be sampled or filtered

This check scans for:
  1. Orphan log groups: no log streams, or all streams empty/expired
  2. Inactive log groups: no new events in 90+ days but retaining data
  3. Over-retained log groups: retention too long for the environment
  4. High-ingestion log groups: > 100GB/month ingestion
  5. Log groups with no retention policy (infinite retention)

Typical savings: $110-165/month in accumulated log waste.

AWS APIs used:
  - logs:DescribeLogGroups (storedBytes, retentionInDays)
  - logs:DescribeLogStreams (lastEventTimestamp, lastIngestionTime)
  - cloudwatch:GetMetricStatistics (IncomingBytes for high-ingestion detection)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from finops.checks.base import BaseCheck, CheckResult


# --- CloudWatch Logs Pricing (us-east-1) ---

# Storage: $0.03 per GB per month (standard)
CW_STORAGE_PER_GB_MONTH = 0.03

# Ingestion: $0.50 per GB (varies by region; $0.50 is default)
CW_INGESTION_PER_GB = 0.50

# Infrequent Access storage: $0.0165 per GB per month
CW_IA_STORAGE_PER_GB_MONTH = 0.0165

# Bytes-to-GB conversion
BYTES_PER_GB = 1024 ** 3


class CloudWatchWasteCheck(BaseCheck):
    """Detect CloudWatch Log waste — orphan groups, missing retention, over-retention.

    Scans all log groups and identifies cost optimization opportunities
    based on retention settings, activity patterns, and ingestion volume.
    """

    name = "cloudwatch_waste"
    description = "Find orphan log groups, missing retention policies, and over-retained logs ($110-165/mo typical)"

    def run(self, session: Any, region: str) -> list[CheckResult]:
        """Execute all CloudWatch Logs waste sub-checks.

        Args:
            session: Authenticated boto3.Session.
            region: AWS region to scan.

        Returns:
            Combined list of CheckResult from all sub-checks.
        """
        results: list[CheckResult] = []

        results.extend(self._check_orphan_log_groups(session, region))
        results.extend(self._check_inactive_log_groups(session, region))
        results.extend(self._check_over_retained_log_groups(session, region))
        results.extend(self._check_high_ingestion_log_groups(session, region))
        results.extend(self._check_no_retention_policy(session, region))

        return results

    def _check_orphan_log_groups(self, session: Any, region: str) -> list[CheckResult]:
        """Find log groups with no log streams or all streams empty/expired.

        These are typically left behind when Lambda functions, ECS services,
        or EKS pods are deleted. The log group persists and retains old data
        at $0.03/GB/month.
        """
        results: list[CheckResult] = []

        # TODO: Uncomment and implement with real boto3 calls
        # logs_client = session.client("logs", region_name=region)
        #
        # paginator = logs_client.get_paginator("describe_log_groups")
        # for page in paginator.paginate():
        #     for lg in page["logGroups"]:
        #         log_group_name = lg["logGroupName"]
        #         stored_bytes = lg.get("storedBytes", 0)
        #
        #         # Step 1: Check if log group has any log streams
        #         streams_resp = logs_client.describe_log_streams(
        #             logGroupName=log_group_name,
        #             orderBy="LastEventTime",
        #             descending=True,
        #             limit=1,
        #         )
        #         streams = streams_resp.get("logStreams", [])
        #
        #         is_orphan = False
        #
        #         if not streams:
        #             # No log streams at all — definite orphan
        #             is_orphan = True
        #         else:
        #             # Check if the most recent stream has any data
        #             latest_stream = streams[0]
        #             last_event_ts = latest_stream.get("lastEventTimestamp")
        #             last_ingestion_ts = latest_stream.get("lastIngestionTime")
        #             stored_stream_bytes = latest_stream.get("storedBytes", 0)
        #
        #             # If no events were ever written, or stored bytes is 0
        #             if last_event_ts is None and stored_stream_bytes == 0:
        #                 is_orphan = True
        #
        #         if not is_orphan:
        #             continue
        #
        #         # Calculate storage cost
        #         stored_gb = stored_bytes / BYTES_PER_GB
        #         monthly_cost = stored_gb * CW_STORAGE_PER_GB_MONTH
        #
        #         # Only flag if there's meaningful cost (> $0.01/mo)
        #         if monthly_cost < 0.01 and stored_bytes == 0:
        #             # Completely empty log group — still flag for cleanup
        #             # but with zero cost
        #             results.append(CheckResult(
        #                 check_name=self.name,
        #                 resource_type="CloudWatch Log Group (orphan)",
        #                 resource_id=log_group_name,
        #                 resource_name=log_group_name,
        #                 current_monthly_cost=0.0,
        #                 recommended_action="Delete — empty orphan log group",
        #                 estimated_monthly_savings=0.0,
        #                 severity="low",
        #                 details={
        #                     "stored_bytes": 0,
        #                     "stored_gb": 0.0,
        #                     "stream_count": len(streams),
        #                     "sub_check": "orphan_log_group",
        #                 },
        #             ))
        #         else:
        #             results.append(CheckResult(
        #                 check_name=self.name,
        #                 resource_type="CloudWatch Log Group (orphan)",
        #                 resource_id=log_group_name,
        #                 resource_name=log_group_name,
        #                 current_monthly_cost=monthly_cost,
        #                 recommended_action=(
        #                     f"Delete — orphan log group retaining "
        #                     f"{stored_gb:.1f} GB of old data"
        #                 ),
        #                 estimated_monthly_savings=monthly_cost,
        #                 severity="low" if monthly_cost < 5 else "medium",
        #                 details={
        #                     "stored_bytes": stored_bytes,
        #                     "stored_gb": round(stored_gb, 2),
        #                     "stream_count": len(streams),
        #                     "sub_check": "orphan_log_group",
        #                 },
        #             ))

        return results

    def _check_inactive_log_groups(self, session: Any, region: str) -> list[CheckResult]:
        """Find log groups with no new events in 90+ days but still retaining data.

        These are log groups where the source application is still running
        (or was running recently enough that streams exist), but no new log
        events have been written in a long time. Setting a short retention
        policy would clean up old data automatically.
        """
        results: list[CheckResult] = []
        inactive_days = self.config.thresholds.get("log_inactive_days", 90)

        # TODO: Uncomment and implement with real boto3 calls
        # logs_client = session.client("logs", region_name=region)
        #
        # paginator = logs_client.get_paginator("describe_log_groups")
        # for page in paginator.paginate():
        #     for lg in page["logGroups"]:
        #         log_group_name = lg["logGroupName"]
        #         stored_bytes = lg.get("storedBytes", 0)
        #         retention_days = lg.get("retentionInDays")  # None = infinite
        #
        #         if stored_bytes == 0:
        #             continue  # Handled by orphan check
        #
        #         # Check the most recent log stream for last event time
        #         streams_resp = logs_client.describe_log_streams(
        #             logGroupName=log_group_name,
        #             orderBy="LastEventTime",
        #             descending=True,
        #             limit=1,
        #         )
        #         streams = streams_resp.get("logStreams", [])
        #         if not streams:
        #             continue  # Handled by orphan check
        #
        #         latest_stream = streams[0]
        #         last_event_ts = latest_stream.get("lastEventTimestamp")
        #
        #         if last_event_ts is None:
        #             continue  # No events — handled by orphan check
        #
        #         # Convert timestamp (milliseconds since epoch) to datetime
        #         last_event_time = datetime.fromtimestamp(
        #             last_event_ts / 1000, tz=timezone.utc
        #         )
        #         days_inactive = (
        #             datetime.now(timezone.utc) - last_event_time
        #         ).days
        #
        #         if days_inactive < inactive_days:
        #             continue  # Still active
        #
        #         stored_gb = stored_bytes / BYTES_PER_GB
        #         monthly_cost = stored_gb * CW_STORAGE_PER_GB_MONTH
        #
        #         if monthly_cost < 0.10:
        #             continue  # Negligible cost
        #
        #         # Recommend setting retention to 30 days to clean up
        #         # Savings = current storage cost (data will expire and cost drops)
        #         recommended_retention = 30
        #
        #         retention_label = (
        #             f"{retention_days} days"
        #             if retention_days is not None
        #             else "infinite (no policy)"
        #         )
        #
        #         results.append(CheckResult(
        #             check_name=self.name,
        #             resource_type="CloudWatch Log Group (inactive)",
        #             resource_id=log_group_name,
        #             resource_name=log_group_name,
        #             current_monthly_cost=monthly_cost,
        #             recommended_action=(
        #                 f"Set {recommended_retention}-day retention — "
        #                 f"no events for {days_inactive} days, "
        #                 f"retaining {stored_gb:.1f} GB "
        #                 f"(current retention: {retention_label})"
        #             ),
        #             estimated_monthly_savings=monthly_cost * 0.8,  # ~80% savings
        #             severity="medium",
        #             details={
        #                 "stored_bytes": stored_bytes,
        #                 "stored_gb": round(stored_gb, 2),
        #                 "days_inactive": days_inactive,
        #                 "current_retention": retention_days,
        #                 "recommended_retention": recommended_retention,
        #                 "sub_check": "inactive_log_group",
        #             },
        #         ))

        return results

    def _check_over_retained_log_groups(self, session: Any, region: str) -> list[CheckResult]:
        """Find log groups with retention policies longer than necessary.

        Recommended retention by environment:
          - Non-prod (dev/staging): 14-30 days
          - Production: 90 days (unless compliance requires more)
          - Anything > 365 days: almost always excessive

        Over-retention means you're paying $0.03/GB/month for data nobody
        will ever look at.
        """
        results: list[CheckResult] = []
        non_prod_max_retention = self.config.thresholds.get(
            "log_retention_non_prod_days", 90
        )
        prod_max_retention = self.config.thresholds.get(
            "log_retention_prod_days", 365
        )

        # TODO: Uncomment and implement with real boto3 calls
        # logs_client = session.client("logs", region_name=region)
        #
        # paginator = logs_client.get_paginator("describe_log_groups")
        # for page in paginator.paginate():
        #     for lg in page["logGroups"]:
        #         log_group_name = lg["logGroupName"]
        #         stored_bytes = lg.get("storedBytes", 0)
        #         retention_days = lg.get("retentionInDays")
        #
        #         if stored_bytes == 0:
        #             continue  # No data — no cost
        #
        #         if retention_days is None:
        #             continue  # Handled by no_retention_policy check
        #
        #         # Determine environment from log group name
        #         # Common patterns: /aws/lambda/dev-, /ecs/staging-, etc.
        #         name_lower = log_group_name.lower()
        #         is_prod = self.is_production(None, log_group_name)
        #
        #         # Also check for common non-prod indicators
        #         non_prod_indicators = [
        #             "dev", "staging", "stg", "test", "qa", "sandbox",
        #             "experiment", "demo", "tmp", "temp",
        #         ]
        #         is_non_prod = any(
        #             ind in name_lower for ind in non_prod_indicators
        #         )
        #
        #         # Determine appropriate max retention
        #         if is_non_prod:
        #             max_retention = non_prod_max_retention
        #             env_label = "non-prod"
        #         elif is_prod:
        #             max_retention = prod_max_retention
        #             env_label = "production"
        #         else:
        #             # Unknown environment — use prod thresholds
        #             max_retention = prod_max_retention
        #             env_label = "unknown (using prod threshold)"
        #
        #         if retention_days <= max_retention:
        #             continue  # Retention is within acceptable range
        #
        #         stored_gb = stored_bytes / BYTES_PER_GB
        #         monthly_cost = stored_gb * CW_STORAGE_PER_GB_MONTH
        #
        #         if monthly_cost < 0.50:
        #             continue  # Negligible cost, not worth flagging
        #
        #         # Estimate savings: proportional reduction
        #         # If retention is 365 and we recommend 90, savings ~= 75% of storage
        #         reduction_ratio = 1.0 - (max_retention / retention_days)
        #         estimated_savings = monthly_cost * reduction_ratio
        #
        #         results.append(CheckResult(
        #             check_name=self.name,
        #             resource_type="CloudWatch Log Group (over-retained)",
        #             resource_id=log_group_name,
        #             resource_name=log_group_name,
        #             current_monthly_cost=monthly_cost,
        #             recommended_action=(
        #                 f"Reduce retention from {retention_days}d to "
        #                 f"{max_retention}d — {env_label} log group "
        #                 f"({stored_gb:.1f} GB)"
        #             ),
        #             estimated_monthly_savings=estimated_savings,
        #             severity="low" if estimated_savings < 5 else "medium",
        #             details={
        #                 "stored_gb": round(stored_gb, 2),
        #                 "current_retention_days": retention_days,
        #                 "recommended_retention_days": max_retention,
        #                 "environment": env_label,
        #                 "reduction_ratio": round(reduction_ratio, 2),
        #                 "sub_check": "over_retained_log_group",
        #             },
        #         ))

        return results

    def _check_high_ingestion_log_groups(self, session: Any, region: str) -> list[CheckResult]:
        """Find log groups with high ingestion volume (>100GB/month).

        At $0.50/GB ingestion cost, a log group ingesting 100GB/month costs
        $50/month just in ingestion fees (plus storage). These should be
        reviewed for:
          - Log level reduction (DEBUG -> INFO in production)
          - Sampling (e.g., log 1 in 10 requests)
          - Filtering at the source (don't ship health check logs)
          - Subscription filters to route to cheaper storage (S3)
        """
        results: list[CheckResult] = []
        ingestion_threshold_gb = self.config.thresholds.get(
            "log_ingestion_threshold_gb", 100
        )

        # TODO: Uncomment and implement with real boto3 calls
        # logs_client = session.client("logs", region_name=region)
        # cw_client = session.client("cloudwatch", region_name=region)
        #
        # paginator = logs_client.get_paginator("describe_log_groups")
        # for page in paginator.paginate():
        #     for lg in page["logGroups"]:
        #         log_group_name = lg["logGroupName"]
        #
        #         # Query CloudWatch for IncomingBytes metric
        #         end_time = datetime.now(timezone.utc)
        #         start_time = end_time - timedelta(days=30)
        #
        #         stats = cw_client.get_metric_statistics(
        #             Namespace="AWS/Logs",
        #             MetricName="IncomingBytes",
        #             Dimensions=[
        #                 {"Name": "LogGroupName", "Value": log_group_name},
        #             ],
        #             StartTime=start_time,
        #             EndTime=end_time,
        #             Period=86400 * 30,  # 30-day aggregate
        #             Statistics=["Sum"],
        #         )
        #
        #         total_bytes = sum(
        #             dp["Sum"] for dp in stats.get("Datapoints", [])
        #         )
        #         monthly_gb = total_bytes / BYTES_PER_GB
        #
        #         if monthly_gb < ingestion_threshold_gb:
        #             continue
        #
        #         # Calculate costs
        #         ingestion_cost = monthly_gb * CW_INGESTION_PER_GB
        #         stored_bytes = lg.get("storedBytes", 0)
        #         stored_gb = stored_bytes / BYTES_PER_GB
        #         storage_cost = stored_gb * CW_STORAGE_PER_GB_MONTH
        #         total_cost = ingestion_cost + storage_cost
        #
        #         # Estimate savings: 50% ingestion reduction through
        #         # log level tuning, sampling, or filtering
        #         estimated_savings = ingestion_cost * 0.50
        #
        #         results.append(CheckResult(
        #             check_name=self.name,
        #             resource_type="CloudWatch Log Group (high ingestion)",
        #             resource_id=log_group_name,
        #             resource_name=log_group_name,
        #             current_monthly_cost=total_cost,
        #             recommended_action=(
        #                 f"Review log verbosity — ingesting {monthly_gb:.0f} GB/mo "
        #                 f"(${ingestion_cost:.0f}/mo ingestion + "
        #                 f"${storage_cost:.0f}/mo storage). "
        #                 f"Consider log level reduction, sampling, or S3 export."
        #             ),
        #             estimated_monthly_savings=estimated_savings,
        #             severity="high" if ingestion_cost > 100 else "medium",
        #             details={
        #                 "monthly_ingestion_gb": round(monthly_gb, 1),
        #                 "ingestion_cost": round(ingestion_cost, 2),
        #                 "stored_gb": round(stored_gb, 2),
        #                 "storage_cost": round(storage_cost, 2),
        #                 "sub_check": "high_ingestion_log_group",
        #             },
        #         ))

        return results

    def _check_no_retention_policy(self, session: Any, region: str) -> list[CheckResult]:
        """Find log groups with no retention policy set (infinite retention).

        By default, CloudWatch Logs retains data forever. Without a retention
        policy, storage costs grow linearly over time with no upper bound.
        This is the single most common CloudWatch Logs cost mistake.

        A log group with 50GB of data and no retention costs $1.50/month
        and that cost only ever goes UP.
        """
        results: list[CheckResult] = []

        # TODO: Uncomment and implement with real boto3 calls
        # logs_client = session.client("logs", region_name=region)
        #
        # paginator = logs_client.get_paginator("describe_log_groups")
        # for page in paginator.paginate():
        #     for lg in page["logGroups"]:
        #         log_group_name = lg["logGroupName"]
        #         stored_bytes = lg.get("storedBytes", 0)
        #         retention_days = lg.get("retentionInDays")
        #
        #         # Only flag log groups with NO retention policy
        #         if retention_days is not None:
        #             continue  # Has a retention policy — skip
        #
        #         stored_gb = stored_bytes / BYTES_PER_GB
        #         monthly_cost = stored_gb * CW_STORAGE_PER_GB_MONTH
        #
        #         if stored_gb < 0.1:
        #             continue  # Tiny log group, not worth flagging
        #
        #         # Determine recommended retention based on environment
        #         name_lower = log_group_name.lower()
        #         non_prod_indicators = [
        #             "dev", "staging", "stg", "test", "qa", "sandbox",
        #         ]
        #         is_non_prod = any(
        #             ind in name_lower for ind in non_prod_indicators
        #         )
        #
        #         if is_non_prod:
        #             recommended_retention = 30
        #         elif self.is_production(None, log_group_name):
        #             recommended_retention = 90
        #         else:
        #             recommended_retention = 90  # Safe default
        #
        #         # Estimate savings: with retention set, old data expires.
        #         # Conservatively estimate 60% of current storage will be cleaned.
        #         estimated_savings = monthly_cost * 0.60
        #
        #         results.append(CheckResult(
        #             check_name=self.name,
        #             resource_type="CloudWatch Log Group (no retention)",
        #             resource_id=log_group_name,
        #             resource_name=log_group_name,
        #             current_monthly_cost=monthly_cost,
        #             recommended_action=(
        #                 f"Set {recommended_retention}-day retention — "
        #                 f"infinite retention on {stored_gb:.1f} GB "
        #                 f"(${monthly_cost:.2f}/mo, growing)"
        #             ),
        #             estimated_monthly_savings=estimated_savings,
        #             severity="medium" if monthly_cost < 10 else "high",
        #             details={
        #                 "stored_bytes": stored_bytes,
        #                 "stored_gb": round(stored_gb, 2),
        #                 "current_retention": None,
        #                 "recommended_retention": recommended_retention,
        #                 "sub_check": "no_retention_policy",
        #             },
        #         ))

        return results
