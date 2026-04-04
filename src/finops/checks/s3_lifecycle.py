"""S3 Lifecycle Optimization — Right-size storage classes and lifecycle policies.

Based on real-world FinOps analysis of 1,293GB + 238GB + 352GB buckets, and
the key insight that S3 Intelligent-Tiering is NOT always cheaper than
lifecycle rules.

The problem: Teams default to S3 Standard or enable Intelligent-Tiering
without calculating whether the monitoring fee ($0.0025/1000 objects/month)
exceeds the storage tier savings. For buckets with millions of small objects,
a static lifecycle policy (Standard -> IA at 30d -> Glacier IR at 90d) can
save significantly more.

This check scans for:
  1. Large buckets (>100GB) with no lifecycle policy
  2. Buckets using Intelligent-Tiering where monitoring costs exceed savings
  3. Buckets with predominantly small objects (<128KB) — IA minimum charge
  4. Buckets with no access logging or S3 Analytics configured

Key insight: S3 Intelligent-Tiering monitoring fee is $0.0025 per 1,000
objects/month. A bucket with 10M objects pays $25/month just for monitoring.
If those objects are small or frequently accessed, lifecycle rules are cheaper.

Typical savings: 30-50% on storage costs per optimized bucket.

AWS APIs used:
  - s3:ListBuckets
  - s3:GetBucketLifecycleConfiguration
  - s3:GetBucketIntelligentTieringConfiguration
  - s3:GetBucketLocation
  - cloudwatch:GetMetricStatistics (BucketSizeBytes, NumberOfObjects)
"""

from __future__ import annotations

from typing import Any

from finops.checks.base import BaseCheck, CheckResult


# --- S3 Pricing Constants (us-east-1) ---

# Storage class pricing (per GB per month)
S3_STANDARD_PER_GB = 0.023         # First 50TB tier
S3_STANDARD_IA_PER_GB = 0.0125     # Standard-Infrequent Access
S3_ONE_ZONE_IA_PER_GB = 0.01       # One Zone-IA
S3_GLACIER_IR_PER_GB = 0.004       # Glacier Instant Retrieval
S3_GLACIER_FLEX_PER_GB = 0.0036    # Glacier Flexible Retrieval
S3_DEEP_ARCHIVE_PER_GB = 0.00099   # Glacier Deep Archive

# Intelligent-Tiering costs
S3_IT_MONITORING_PER_1000_OBJECTS = 0.0025  # $/1000 objects/month
S3_IT_FREQUENT_PER_GB = 0.023      # Same as Standard
S3_IT_INFREQUENT_PER_GB = 0.0125   # Same as Standard-IA (after 30d)
S3_IT_ARCHIVE_IR_PER_GB = 0.004    # Archive Instant Access (after 90d)

# Transition costs
S3_TRANSITION_TO_IA_PER_1000 = 0.01         # Per 1,000 PUT requests
S3_TRANSITION_TO_GLACIER_PER_1000 = 0.02    # Per 1,000 lifecycle transitions

# Important: IA minimum object size charge is 128KB
S3_IA_MIN_BILLABLE_SIZE_KB = 128

# Thresholds
DEFAULT_LARGE_BUCKET_GB = 100
DEFAULT_HIGH_OBJECT_COUNT = 1_000_000


class S3LifecycleCheck(BaseCheck):
    """Optimize S3 storage costs through lifecycle policies and tier analysis.

    Compares Intelligent-Tiering monitoring costs vs. lifecycle rule savings,
    flags buckets missing lifecycle policies, and warns about IA minimum
    object size charges.
    """

    name = "s3_lifecycle"
    description = "Optimize S3 storage — lifecycle policies, Intelligent-Tiering vs lifecycle cost analysis"

    def run(self, session: Any, region: str) -> list[CheckResult]:
        """Execute all S3 lifecycle optimization sub-checks.

        Args:
            session: Authenticated boto3.Session.
            region: AWS region to scan.

        Returns:
            Combined list of CheckResult from all sub-checks.
        """
        results: list[CheckResult] = []

        results.extend(self._check_no_lifecycle_policy(session, region))
        results.extend(self._check_intelligent_tiering_cost(session, region))
        results.extend(self._check_small_objects_ia_penalty(session, region))
        results.extend(self._check_no_analytics(session, region))

        return results

    def _check_no_lifecycle_policy(self, session: Any, region: str) -> list[CheckResult]:
        """Find large buckets (>100GB) with no lifecycle policy.

        Without lifecycle rules, objects stay in S3 Standard forever.
        A simple Standard -> IA (30d) -> Glacier IR (90d) policy typically
        saves 30-50% on storage for data that ages out of frequent access.

        Savings model for a 1TB bucket:
          Standard:          1,024 GB * $0.023 = $23.55/mo
          With lifecycle*:   ~$14.50/mo (blended across tiers)
          Savings:           ~$9.05/mo (~38%)

        * Assumes 40% stays Standard, 35% moves to IA, 25% to Glacier IR
        """
        results: list[CheckResult] = []
        # Threshold used by TODO implementation below
        self.config.thresholds.get("s3_large_bucket_gb", DEFAULT_LARGE_BUCKET_GB)

        # TODO: Uncomment and implement with real boto3 calls
        # s3_client = session.client("s3", region_name=region)
        # cw_client = session.client("cloudwatch", region_name=region)
        #
        # buckets_resp = s3_client.list_buckets()
        #
        # for bucket in buckets_resp.get("Buckets", []):
        #     bucket_name = bucket["Name"]
        #
        #     # Check bucket region — only scan buckets in the target region
        #     try:
        #         loc_resp = s3_client.get_bucket_location(Bucket=bucket_name)
        #         bucket_region = loc_resp.get("LocationConstraint") or "us-east-1"
        #         if bucket_region != region:
        #             continue
        #     except Exception:
        #         continue
        #
        #     # Get bucket size from CloudWatch
        #     end_time = datetime.now(timezone.utc)
        #     start_time = end_time - timedelta(days=2)
        #
        #     size_stats = cw_client.get_metric_statistics(
        #         Namespace="AWS/S3",
        #         MetricName="BucketSizeBytes",
        #         Dimensions=[
        #             {"Name": "BucketName", "Value": bucket_name},
        #             {"Name": "StorageType", "Value": "StandardStorage"},
        #         ],
        #         StartTime=start_time,
        #         EndTime=end_time,
        #         Period=86400,
        #         Statistics=["Average"],
        #     )
        #
        #     if not size_stats.get("Datapoints"):
        #         continue
        #
        #     bucket_bytes = max(
        #         dp["Average"] for dp in size_stats["Datapoints"]
        #     )
        #     bucket_gb = bucket_bytes / (1024 ** 3)
        #
        #     if bucket_gb < min_size_gb:
        #         continue  # Too small to bother
        #
        #     # Check if bucket has a lifecycle configuration
        #     has_lifecycle = False
        #     try:
        #         s3_client.get_bucket_lifecycle_configuration(Bucket=bucket_name)
        #         has_lifecycle = True
        #     except s3_client.exceptions.ClientError as e:
        #         if e.response["Error"]["Code"] == "NoSuchLifecycleConfiguration":
        #             has_lifecycle = False
        #         else:
        #             continue  # Permission error or other issue
        #
        #     if has_lifecycle:
        #         continue  # Already has lifecycle rules
        #
        #     # Calculate current cost and potential savings
        #     current_cost = bucket_gb * S3_STANDARD_PER_GB
        #
        #     # Model lifecycle savings:
        #     # Assume after lifecycle:
        #     #   40% Standard, 35% IA, 25% Glacier IR
        #     lifecycle_cost = (
        #         bucket_gb * 0.40 * S3_STANDARD_PER_GB +
        #         bucket_gb * 0.35 * S3_STANDARD_IA_PER_GB +
        #         bucket_gb * 0.25 * S3_GLACIER_IR_PER_GB
        #     )
        #     savings = current_cost - lifecycle_cost
        #
        #     results.append(CheckResult(
        #         check_name=self.name,
        #         resource_type="S3 Bucket (no lifecycle)",
        #         resource_id=bucket_name,
        #         resource_name=bucket_name,
        #         current_monthly_cost=current_cost,
        #         recommended_action=(
        #             f"Add lifecycle policy — {bucket_gb:.0f} GB in Standard, "
        #             f"recommend IA at 30d + Glacier IR at 90d "
        #             f"(~{savings / current_cost * 100:.0f}% savings)"
        #         ),
        #         estimated_monthly_savings=savings,
        #         severity="high" if savings > 50 else "medium",
        #         details={
        #             "bucket_size_gb": round(bucket_gb, 1),
        #             "current_storage_class": "Standard",
        #             "recommended_lifecycle": {
        #                 "30_days": "Standard-IA",
        #                 "90_days": "Glacier Instant Retrieval",
        #             },
        #             "cost_model": {
        #                 "current": round(current_cost, 2),
        #                 "with_lifecycle": round(lifecycle_cost, 2),
        #             },
        #             "sub_check": "no_lifecycle_policy",
        #         },
        #     ))

        return results

    def _check_intelligent_tiering_cost(self, session: Any, region: str) -> list[CheckResult]:
        """Find buckets where Intelligent-Tiering monitoring cost exceeds savings.

        S3 Intelligent-Tiering charges $0.0025 per 1,000 objects/month for
        monitoring. For buckets with millions of small objects, this fee can
        exceed the storage tier savings.

        Example: 10M objects, avg 50KB each (~500GB total)
          - IT monitoring fee:  10,000 * $0.0025 = $25.00/month
          - IT storage savings: maybe $3-8/month (if most objects are infrequently accessed)
          - Net: LOSING $17-22/month vs static lifecycle

        This is a real finding from production — Intelligent-Tiering is marketed
        as a "set and forget" solution, but for high-object-count buckets with
        small objects, it's actually MORE expensive.
        """
        results: list[CheckResult] = []
        # Threshold used by TODO implementation below
        self.config.thresholds.get("s3_high_object_count", DEFAULT_HIGH_OBJECT_COUNT)

        # TODO: Uncomment and implement with real boto3 calls
        # s3_client = session.client("s3", region_name=region)
        # cw_client = session.client("cloudwatch", region_name=region)
        #
        # buckets_resp = s3_client.list_buckets()
        #
        # for bucket in buckets_resp.get("Buckets", []):
        #     bucket_name = bucket["Name"]
        #
        #     # Check bucket region
        #     try:
        #         loc_resp = s3_client.get_bucket_location(Bucket=bucket_name)
        #         bucket_region = loc_resp.get("LocationConstraint") or "us-east-1"
        #         if bucket_region != region:
        #             continue
        #     except Exception:
        #         continue
        #
        #     # Check if bucket has Intelligent-Tiering configuration
        #     has_it = False
        #     try:
        #         it_resp = s3_client.get_bucket_intelligent_tiering_configuration(
        #             Bucket=bucket_name,
        #             Id="default",  # Common convention
        #         )
        #         has_it = True
        #     except Exception:
        #         # Try listing all IT configs
        #         try:
        #             it_list = s3_client.list_bucket_intelligent_tiering_configurations(
        #                 Bucket=bucket_name,
        #             )
        #             has_it = len(
        #                 it_list.get("IntelligentTieringConfigurationList", [])
        #             ) > 0
        #         except Exception:
        #             has_it = False
        #
        #     if not has_it:
        #         continue  # Not using IT — skip
        #
        #     # Get object count from CloudWatch
        #     end_time = datetime.now(timezone.utc)
        #     start_time = end_time - timedelta(days=2)
        #
        #     count_stats = cw_client.get_metric_statistics(
        #         Namespace="AWS/S3",
        #         MetricName="NumberOfObjects",
        #         Dimensions=[
        #             {"Name": "BucketName", "Value": bucket_name},
        #             {"Name": "StorageType", "Value": "AllStorageTypes"},
        #         ],
        #         StartTime=start_time,
        #         EndTime=end_time,
        #         Period=86400,
        #         Statistics=["Average"],
        #     )
        #
        #     if not count_stats.get("Datapoints"):
        #         continue
        #
        #     object_count = int(max(
        #         dp["Average"] for dp in count_stats["Datapoints"]
        #     ))
        #
        #     if object_count < high_object_count:
        #         continue  # Object count is manageable
        #
        #     # Get bucket size
        #     size_stats = cw_client.get_metric_statistics(
        #         Namespace="AWS/S3",
        #         MetricName="BucketSizeBytes",
        #         Dimensions=[
        #             {"Name": "BucketName", "Value": bucket_name},
        #             {"Name": "StorageType", "Value": "IntelligentTieringStorage"},
        #         ],
        #         StartTime=start_time,
        #         EndTime=end_time,
        #         Period=86400,
        #         Statistics=["Average"],
        #     )
        #
        #     bucket_bytes = 0
        #     if size_stats.get("Datapoints"):
        #         bucket_bytes = max(
        #             dp["Average"] for dp in size_stats["Datapoints"]
        #         )
        #     bucket_gb = bucket_bytes / (1024 ** 3)
        #
        #     # Calculate average object size
        #     avg_object_kb = (bucket_bytes / object_count / 1024) if object_count > 0 else 0
        #
        #     # Calculate monitoring cost
        #     monitoring_cost = (object_count / 1000) * S3_IT_MONITORING_PER_1000_OBJECTS
        #
        #     # Estimate IT storage savings vs Standard
        #     # Assume IT moves ~50% of data to IA tier
        #     it_storage_cost = (
        #         bucket_gb * 0.50 * S3_IT_FREQUENT_PER_GB +
        #         bucket_gb * 0.50 * S3_IT_INFREQUENT_PER_GB
        #     )
        #     standard_cost = bucket_gb * S3_STANDARD_PER_GB
        #     it_tier_savings = standard_cost - it_storage_cost
        #
        #     # Compare: lifecycle rule savings vs IT (monitoring + storage)
        #     lifecycle_cost = (
        #         bucket_gb * 0.40 * S3_STANDARD_PER_GB +
        #         bucket_gb * 0.35 * S3_STANDARD_IA_PER_GB +
        #         bucket_gb * 0.25 * S3_GLACIER_IR_PER_GB
        #     )
        #     lifecycle_savings = standard_cost - lifecycle_cost
        #
        #     # Net IT cost = storage cost + monitoring - vs lifecycle
        #     it_total_cost = it_storage_cost + monitoring_cost
        #     net_waste = monitoring_cost - it_tier_savings
        #
        #     # Flag if monitoring cost exceeds tier savings, OR if lifecycle
        #     # would be significantly cheaper than IT
        #     if net_waste > 0 or (lifecycle_savings > it_tier_savings + monitoring_cost):
        #         savings_vs_lifecycle = it_total_cost - lifecycle_cost
        #         if savings_vs_lifecycle <= 0:
        #             continue  # IT is actually cheaper — skip
        #
        #         results.append(CheckResult(
        #             check_name=self.name,
        #             resource_type="S3 Bucket (IT monitoring waste)",
        #             resource_id=bucket_name,
        #             resource_name=bucket_name,
        #             current_monthly_cost=it_total_cost,
        #             recommended_action=(
        #                 f"Switch from Intelligent-Tiering to lifecycle rules — "
        #                 f"{object_count:,} objects, "
        #                 f"monitoring fee ${monitoring_cost:.2f}/mo "
        #                 f"{'exceeds' if net_waste > 0 else 'adds to'} "
        #                 f"tier savings ${it_tier_savings:.2f}/mo. "
        #                 f"Lifecycle rules save ${savings_vs_lifecycle:.2f}/mo more."
        #             ),
        #             estimated_monthly_savings=savings_vs_lifecycle,
        #             severity="medium" if savings_vs_lifecycle < 25 else "high",
        #             details={
        #                 "bucket_size_gb": round(bucket_gb, 1),
        #                 "object_count": object_count,
        #                 "avg_object_size_kb": round(avg_object_kb, 1),
        #                 "it_monitoring_cost": round(monitoring_cost, 2),
        #                 "it_tier_savings": round(it_tier_savings, 2),
        #                 "lifecycle_cost": round(lifecycle_cost, 2),
        #                 "it_total_cost": round(it_total_cost, 2),
        #                 "net_monitoring_waste": round(net_waste, 2),
        #                 "sub_check": "it_monitoring_waste",
        #             },
        #         ))

        return results

    def _check_small_objects_ia_penalty(self, session: Any, region: str) -> list[CheckResult]:
        """Warn about buckets transitioning small objects (<128KB) to IA storage.

        S3 Standard-IA charges a minimum of 128KB per object. If you transition
        a 10KB object to IA, you're billed for 128KB — that's a 12.8x storage
        cost increase for that object. For buckets with many small objects, this
        completely negates the per-GB savings of IA.

        Example: 1M objects averaging 20KB each (~20GB)
          Standard: 20 GB * $0.023 = $0.46/mo
          IA (billed at 128KB min): 1M * 128KB = ~122GB billed
          IA cost: 122 GB * $0.0125 = $1.53/mo  <- 3x MORE expensive!
        """
        results: list[CheckResult] = []

        # TODO: Uncomment and implement with real boto3 calls
        # s3_client = session.client("s3", region_name=region)
        # cw_client = session.client("cloudwatch", region_name=region)
        #
        # buckets_resp = s3_client.list_buckets()
        #
        # for bucket in buckets_resp.get("Buckets", []):
        #     bucket_name = bucket["Name"]
        #
        #     # Check bucket region
        #     try:
        #         loc_resp = s3_client.get_bucket_location(Bucket=bucket_name)
        #         bucket_region = loc_resp.get("LocationConstraint") or "us-east-1"
        #         if bucket_region != region:
        #             continue
        #     except Exception:
        #         continue
        #
        #     # Check if bucket has lifecycle rules that transition to IA
        #     has_ia_transition = False
        #     try:
        #         lc_resp = s3_client.get_bucket_lifecycle_configuration(
        #             Bucket=bucket_name,
        #         )
        #         for rule in lc_resp.get("Rules", []):
        #             if rule.get("Status") != "Enabled":
        #                 continue
        #             for transition in rule.get("Transitions", []):
        #                 sc = transition.get("StorageClass", "")
        #                 if "IA" in sc or "ONEZONE" in sc:
        #                     has_ia_transition = True
        #                     break
        #     except Exception:
        #         continue
        #
        #     if not has_ia_transition:
        #         continue  # No IA transition — skip
        #
        #     # Get object count and bucket size from CloudWatch
        #     end_time = datetime.now(timezone.utc)
        #     start_time = end_time - timedelta(days=2)
        #
        #     count_stats = cw_client.get_metric_statistics(
        #         Namespace="AWS/S3",
        #         MetricName="NumberOfObjects",
        #         Dimensions=[
        #             {"Name": "BucketName", "Value": bucket_name},
        #             {"Name": "StorageType", "Value": "AllStorageTypes"},
        #         ],
        #         StartTime=start_time,
        #         EndTime=end_time,
        #         Period=86400,
        #         Statistics=["Average"],
        #     )
        #
        #     size_stats = cw_client.get_metric_statistics(
        #         Namespace="AWS/S3",
        #         MetricName="BucketSizeBytes",
        #         Dimensions=[
        #             {"Name": "BucketName", "Value": bucket_name},
        #             {"Name": "StorageType", "Value": "StandardStorage"},
        #         ],
        #         StartTime=start_time,
        #         EndTime=end_time,
        #         Period=86400,
        #         Statistics=["Average"],
        #     )
        #
        #     if not count_stats.get("Datapoints") or not size_stats.get("Datapoints"):
        #         continue
        #
        #     object_count = int(max(
        #         dp["Average"] for dp in count_stats["Datapoints"]
        #     ))
        #     bucket_bytes = max(
        #         dp["Average"] for dp in size_stats["Datapoints"]
        #     )
        #     bucket_gb = bucket_bytes / (1024 ** 3)
        #
        #     if object_count == 0:
        #         continue
        #
        #     # Calculate average object size
        #     avg_object_bytes = bucket_bytes / object_count
        #     avg_object_kb = avg_object_bytes / 1024
        #
        #     # Only flag if average object size is below 128KB
        #     if avg_object_kb >= S3_IA_MIN_BILLABLE_SIZE_KB:
        #         continue  # Objects are large enough for IA to make sense
        #
        #     # Calculate cost penalty
        #     # Standard cost (actual bytes)
        #     standard_cost = bucket_gb * S3_STANDARD_PER_GB
        #
        #     # IA cost (billed at 128KB minimum per object)
        #     billed_bytes_ia = object_count * S3_IA_MIN_BILLABLE_SIZE_KB * 1024
        #     billed_gb_ia = billed_bytes_ia / (1024 ** 3)
        #     ia_cost = billed_gb_ia * S3_STANDARD_IA_PER_GB
        #
        #     # If IA is more expensive than Standard, flag it
        #     if ia_cost > standard_cost:
        #         overpay = ia_cost - standard_cost
        #         results.append(CheckResult(
        #             check_name=self.name,
        #             resource_type="S3 Bucket (small object IA penalty)",
        #             resource_id=bucket_name,
        #             resource_name=bucket_name,
        #             current_monthly_cost=ia_cost,
        #             recommended_action=(
        #                 f"Remove IA transition — avg object size {avg_object_kb:.0f}KB "
        #                 f"< 128KB minimum. IA billed at {billed_gb_ia:.0f}GB "
        #                 f"(actual {bucket_gb:.0f}GB). "
        #                 f"Keep in Standard or use lifecycle only for objects >128KB."
        #             ),
        #             estimated_monthly_savings=overpay,
        #             severity="medium" if overpay < 20 else "high",
        #             details={
        #                 "bucket_size_gb": round(bucket_gb, 1),
        #                 "object_count": object_count,
        #                 "avg_object_size_kb": round(avg_object_kb, 1),
        #                 "billed_size_gb_ia": round(billed_gb_ia, 1),
        #                 "standard_cost": round(standard_cost, 2),
        #                 "ia_cost": round(ia_cost, 2),
        #                 "overpay": round(overpay, 2),
        #                 "sub_check": "small_objects_ia_penalty",
        #             },
        #         ))

        return results

    def _check_no_analytics(self, session: Any, region: str) -> list[CheckResult]:
        """Find large buckets with no access logging or S3 Analytics configured.

        Without S3 Analytics or access logs, you can't make informed decisions
        about lifecycle policies or storage class transitions. S3 Analytics
        provides access pattern data that shows which objects are frequently
        accessed and which are cold.

        S3 Analytics is free for the first configuration per bucket. The data
        it provides is essential for making lifecycle policy decisions.
        """
        results: list[CheckResult] = []
        # Threshold used by TODO implementation below
        self.config.thresholds.get("s3_large_bucket_gb", DEFAULT_LARGE_BUCKET_GB)

        # TODO: Uncomment and implement with real boto3 calls
        # s3_client = session.client("s3", region_name=region)
        # cw_client = session.client("cloudwatch", region_name=region)
        #
        # buckets_resp = s3_client.list_buckets()
        #
        # for bucket in buckets_resp.get("Buckets", []):
        #     bucket_name = bucket["Name"]
        #
        #     # Check bucket region
        #     try:
        #         loc_resp = s3_client.get_bucket_location(Bucket=bucket_name)
        #         bucket_region = loc_resp.get("LocationConstraint") or "us-east-1"
        #         if bucket_region != region:
        #             continue
        #     except Exception:
        #         continue
        #
        #     # Get bucket size from CloudWatch
        #     end_time = datetime.now(timezone.utc)
        #     start_time = end_time - timedelta(days=2)
        #
        #     size_stats = cw_client.get_metric_statistics(
        #         Namespace="AWS/S3",
        #         MetricName="BucketSizeBytes",
        #         Dimensions=[
        #             {"Name": "BucketName", "Value": bucket_name},
        #             {"Name": "StorageType", "Value": "StandardStorage"},
        #         ],
        #         StartTime=start_time,
        #         EndTime=end_time,
        #         Period=86400,
        #         Statistics=["Average"],
        #     )
        #
        #     if not size_stats.get("Datapoints"):
        #         continue
        #
        #     bucket_bytes = max(
        #         dp["Average"] for dp in size_stats["Datapoints"]
        #     )
        #     bucket_gb = bucket_bytes / (1024 ** 3)
        #
        #     if bucket_gb < min_size_gb:
        #         continue  # Too small to warrant analytics setup
        #
        #     # Check for S3 Analytics configurations
        #     has_analytics = False
        #     try:
        #         analytics_resp = s3_client.list_bucket_analytics_configurations(
        #             Bucket=bucket_name,
        #         )
        #         has_analytics = len(
        #             analytics_resp.get("AnalyticsConfigurationList", [])
        #         ) > 0
        #     except Exception:
        #         pass
        #
        #     if has_analytics:
        #         continue  # Already has analytics — skip
        #
        #     # Estimate potential savings if lifecycle were properly configured
        #     current_cost = bucket_gb * S3_STANDARD_PER_GB
        #
        #     # Conservative estimate: lifecycle could save 30% once access
        #     # patterns are understood via analytics
        #     potential_savings = current_cost * 0.30
        #
        #     results.append(CheckResult(
        #         check_name=self.name,
        #         resource_type="S3 Bucket (no analytics)",
        #         resource_id=bucket_name,
        #         resource_name=bucket_name,
        #         current_monthly_cost=current_cost,
        #         recommended_action=(
        #             f"Enable S3 Analytics — {bucket_gb:.0f} GB bucket "
        #             f"with no access pattern data. Analytics is free and "
        #             f"provides data to optimize lifecycle policies "
        #             f"(est. ~{potential_savings / current_cost * 100:.0f}% potential savings)."
        #         ),
        #         estimated_monthly_savings=potential_savings,
        #         severity="low",
        #         details={
        #             "bucket_size_gb": round(bucket_gb, 1),
        #             "current_cost": round(current_cost, 2),
        #             "potential_savings_with_lifecycle": round(potential_savings, 2),
        #             "sub_check": "no_analytics",
        #         },
        #     ))

        return results

    @staticmethod
    def compare_it_vs_lifecycle(
        bucket_gb: float,
        object_count: int,
        frequent_access_ratio: float = 0.40,
    ) -> dict[str, float]:
        """Compare Intelligent-Tiering vs static lifecycle rule costs.

        This is the core analysis from real FinOps work. IT is not always
        cheaper — for buckets with many objects, the monitoring fee tips
        the balance toward lifecycle rules.

        Args:
            bucket_gb: Total bucket size in GB.
            object_count: Total number of objects.
            frequent_access_ratio: Fraction of data frequently accessed (0-1).

        Returns:
            Dict with cost breakdown and recommendation.
        """
        # Intelligent-Tiering costs
        it_monitoring = (object_count / 1000) * S3_IT_MONITORING_PER_1000_OBJECTS
        it_storage = (
            bucket_gb * frequent_access_ratio * S3_IT_FREQUENT_PER_GB +
            bucket_gb * (1 - frequent_access_ratio) * S3_IT_INFREQUENT_PER_GB
        )
        it_total = it_monitoring + it_storage

        # Lifecycle costs (Standard -> IA at 30d -> Glacier IR at 90d)
        # Assume: frequent_access_ratio in Standard, rest split IA/Glacier IR
        ia_ratio = (1 - frequent_access_ratio) * 0.60
        glacier_ratio = (1 - frequent_access_ratio) * 0.40
        lifecycle_storage = (
            bucket_gb * frequent_access_ratio * S3_STANDARD_PER_GB +
            bucket_gb * ia_ratio * S3_STANDARD_IA_PER_GB +
            bucket_gb * glacier_ratio * S3_GLACIER_IR_PER_GB
        )
        lifecycle_total = lifecycle_storage  # No monitoring fee

        # Standard (no optimization)
        standard_total = bucket_gb * S3_STANDARD_PER_GB

        return {
            "standard_cost": round(standard_total, 2),
            "it_monitoring_cost": round(it_monitoring, 2),
            "it_storage_cost": round(it_storage, 2),
            "it_total_cost": round(it_total, 2),
            "lifecycle_cost": round(lifecycle_total, 2),
            "it_savings_vs_standard": round(standard_total - it_total, 2),
            "lifecycle_savings_vs_standard": round(standard_total - lifecycle_total, 2),
            "lifecycle_savings_vs_it": round(it_total - lifecycle_total, 2),
            "recommendation": (
                "lifecycle" if lifecycle_total < it_total else "intelligent_tiering"
            ),
        }
