"""S3 Lifecycle Optimization — flag large buckets that have no lifecycle policy.

Objects stay in S3 Standard forever without lifecycle rules. A static policy
(Standard -> IA at 30d -> Glacier IR at 90d) cuts the storage bill for data that
ages out of frequent access. The savings figure is a model: it assumes 40% of the
data stays in Standard, 35% moves to IA and 25% to Glacier IR.

The check scans for large buckets (>100GB, `s3_large_bucket_gb`) in the scanned
region with no lifecycle configuration. `compare_it_vs_lifecycle` is a standalone
cost helper (Intelligent-Tiering monitoring fee vs lifecycle rules); no check calls it.

AWS APIs used:
  - s3:ListBuckets
  - s3:GetBucketLocation
  - s3:GetBucketLifecycleConfiguration
  - cloudwatch:GetMetricStatistics (BucketSizeBytes)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from botocore.exceptions import ClientError

from finops.checks.base import BaseCheck, CheckResult


# --- S3 Pricing Constants (us-east-1) ---

# Storage class pricing (per GB per month)
S3_STANDARD_PER_GB = 0.023         # First 50TB tier
S3_STANDARD_IA_PER_GB = 0.0125     # Standard-Infrequent Access
S3_GLACIER_IR_PER_GB = 0.004       # Glacier Instant Retrieval

# Intelligent-Tiering costs
S3_IT_MONITORING_PER_1000_OBJECTS = 0.0025  # $/1000 objects/month
S3_IT_FREQUENT_PER_GB = 0.023      # Same as Standard
S3_IT_INFREQUENT_PER_GB = 0.0125   # Same as Standard-IA (after 30d)

# Assumed spread of a bucket's data once a Standard -> IA (30d) -> Glacier IR (90d) policy runs
LIFECYCLE_SHARE_STANDARD = 0.40
LIFECYCLE_SHARE_IA = 0.35
LIFECYCLE_SHARE_GLACIER_IR = 0.25

# Thresholds
DEFAULT_LARGE_BUCKET_GB = 100


def _bucket_region(location: dict[str, Any]) -> str:
    """Region from a GetBucketLocation response.

    S3 returns no constraint for us-east-1 and the legacy value "EU" for eu-west-1.
    """
    constraint = location.get("LocationConstraint") or "us-east-1"
    return "eu-west-1" if constraint == "EU" else constraint


class S3LifecycleCheck(BaseCheck):
    """Flag large S3 buckets that have no lifecycle policy."""

    name = "s3_lifecycle"
    description = "Optimize S3 storage — flag large buckets with no lifecycle policy"

    def run(self, session: Any, region: str) -> list[CheckResult]:
        """Run the S3 lifecycle check.

        Args:
            session: Authenticated boto3.Session.
            region: AWS region to scan.

        Returns:
            List of CheckResult, one per large bucket without a lifecycle policy.
        """
        return self._check_no_lifecycle_policy(session, region)

    @staticmethod
    def _standard_storage_gb(cw_client: Any, bucket_name: str) -> float | None:
        """Largest daily BucketSizeBytes of the last 2 days in GB, or None without data.

        S3 publishes this metric once a day, and not at all for an empty bucket.
        """
        end_time = datetime.now(timezone.utc)
        stats = cw_client.get_metric_statistics(
            Namespace="AWS/S3",
            MetricName="BucketSizeBytes",
            Dimensions=[
                {"Name": "BucketName", "Value": bucket_name},
                {"Name": "StorageType", "Value": "StandardStorage"},
            ],
            StartTime=end_time - timedelta(days=2),
            EndTime=end_time,
            Period=86400,
            Statistics=["Average"],
        )
        datapoints = stats.get("Datapoints")
        if not datapoints:
            return None
        return float(max(dp["Average"] for dp in datapoints)) / (1024 ** 3)

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
        min_size_gb = self.config.thresholds.get("s3_large_bucket_gb", DEFAULT_LARGE_BUCKET_GB)

        s3_client = session.client("s3", region_name=region)
        cw_client = session.client("cloudwatch", region_name=region)

        for bucket in s3_client.list_buckets().get("Buckets", []):
            bucket_name = bucket["Name"]

            # CloudWatch publishes S3 metrics in the bucket's own region, so only
            # buckets in the region being scanned can be sized here.
            try:
                location = s3_client.get_bucket_location(Bucket=bucket_name)
            except ClientError:
                continue
            if _bucket_region(location) != region:
                continue

            bucket_gb = self._standard_storage_gb(cw_client, bucket_name)
            if not bucket_gb or bucket_gb < min_size_gb:
                continue

            try:
                s3_client.get_bucket_lifecycle_configuration(Bucket=bucket_name)
                continue  # Already has lifecycle rules
            except ClientError as e:
                # Any other error (AccessDenied, ...) means we can't tell, so don't flag it.
                if e.response["Error"]["Code"] != "NoSuchLifecycleConfiguration":
                    continue

            current_cost = bucket_gb * S3_STANDARD_PER_GB
            lifecycle_cost = bucket_gb * (
                LIFECYCLE_SHARE_STANDARD * S3_STANDARD_PER_GB
                + LIFECYCLE_SHARE_IA * S3_STANDARD_IA_PER_GB
                + LIFECYCLE_SHARE_GLACIER_IR * S3_GLACIER_IR_PER_GB
            )
            savings = current_cost - lifecycle_cost

            results.append(CheckResult(
                check_name=self.name,
                resource_type="S3 Bucket (no lifecycle)",
                resource_id=bucket_name,
                resource_name=bucket_name,
                current_monthly_cost=current_cost,
                recommended_action=(
                    f"Add lifecycle policy — {bucket_gb:.0f} GB in Standard, "
                    f"recommend IA at 30d + Glacier IR at 90d "
                    f"(~{savings / current_cost * 100:.0f}% savings)"
                ),
                estimated_monthly_savings=savings,
                severity="high" if savings > 50 else "medium",
                details={
                    "bucket_size_gb": round(bucket_gb, 1),
                    "current_storage_class": "Standard",
                    "recommended_lifecycle": {
                        "30_days": "Standard-IA",
                        "90_days": "Glacier Instant Retrieval",
                    },
                    "cost_model": {
                        "current": round(current_cost, 2),
                        "with_lifecycle": round(lifecycle_cost, 2),
                    },
                    "sub_check": "no_lifecycle_policy",
                },
            ))

        return results

    @staticmethod
    def compare_it_vs_lifecycle(
        bucket_gb: float,
        object_count: int,
        frequent_access_ratio: float = 0.40,
    ) -> dict[str, float | str]:
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
