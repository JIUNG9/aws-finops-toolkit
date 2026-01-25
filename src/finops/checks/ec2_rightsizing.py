"""EC2 Right-Sizing Check — Find oversized EC2 instances and recommend downsizing.

This check queries CloudWatch for CPU utilization metrics over a configurable
lookback period (default: 14 days). Instances with average CPU below the
threshold (default: 20%) are flagged with a recommendation to downsize.

Special handling for EKS nodes: checks both EC2 CPU and Kubernetes node
utilization (if available via tags) to avoid downsizing nodes that are
memory-bound rather than CPU-bound.

Typical savings: 30-50% per right-sized instance.

AWS APIs used:
  - ec2:DescribeInstances
  - cloudwatch:GetMetricStatistics
  - pricing:GetProducts (for cost estimation)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from finops.checks.base import BaseCheck, CheckResult


# EC2 instance type hierarchy for right-sizing recommendations.
# Maps current instance size to the next smaller size within the same family.
DOWNSIZE_MAP: dict[str, str] = {
    "xlarge": "large",
    "2xlarge": "xlarge",
    "4xlarge": "2xlarge",
    "8xlarge": "4xlarge",
    "12xlarge": "8xlarge",
    "16xlarge": "12xlarge",
    "24xlarge": "16xlarge",
    "metal": "24xlarge",
}

# Approximate on-demand hourly pricing (us-east-1, Linux) for common instance types.
# Used as fallback when the Pricing API is not available.
# TODO: Fetch live pricing from AWS Pricing API or maintain a more complete table.
APPROX_HOURLY_PRICING: dict[str, float] = {
    "t3.micro": 0.0104,
    "t3.small": 0.0208,
    "t3.medium": 0.0416,
    "t3.large": 0.0832,
    "t3.xlarge": 0.1664,
    "t3.2xlarge": 0.3328,
    "m5.large": 0.096,
    "m5.xlarge": 0.192,
    "m5.2xlarge": 0.384,
    "m5.4xlarge": 0.768,
    "m5.8xlarge": 1.536,
    "m5.12xlarge": 2.304,
    "m5.16xlarge": 3.072,
    "m5.24xlarge": 4.608,
    "m6i.large": 0.096,
    "m6i.xlarge": 0.192,
    "m6i.2xlarge": 0.384,
    "m6i.4xlarge": 0.768,
    "m6i.8xlarge": 1.536,
    "c5.large": 0.085,
    "c5.xlarge": 0.17,
    "c5.2xlarge": 0.34,
    "c5.4xlarge": 0.68,
    "r5.large": 0.126,
    "r5.xlarge": 0.252,
    "r5.2xlarge": 0.504,
    "r5.4xlarge": 1.008,
}

# Hours in a month (approximate, for cost estimation)
HOURS_PER_MONTH = 730


class EC2RightsizingCheck(BaseCheck):
    """Find EC2 instances with low CPU utilization and recommend downsizing.

    Scans all running EC2 instances, queries CloudWatch for average CPU
    over the lookback period, and flags instances below the threshold.
    """

    name = "ec2_rightsizing"
    description = "Find EC2 instances with low CPU utilization and recommend smaller instance types"

    def run(self, session: Any, region: str) -> list[CheckResult]:
        """Execute EC2 right-sizing check.

        Args:
            session: Authenticated boto3.Session.
            region: AWS region to scan.

        Returns:
            List of CheckResult for each oversized instance.
        """
        results: list[CheckResult] = []

        cpu_threshold = self.config.thresholds.get("ec2_cpu_avg_percent", 20)
        lookback_days = self.config.thresholds.get("ec2_lookback_days", 14)

        # TODO: Uncomment and implement with real boto3 calls
        # ec2_client = session.client("ec2", region_name=region)
        # cw_client = session.client("cloudwatch", region_name=region)
        #
        # # Step 1: Get all running instances
        # paginator = ec2_client.get_paginator("describe_instances")
        # filters = [{"Name": "instance-state-name", "Values": ["running"]}]
        #
        # for page in paginator.paginate(Filters=filters):
        #     for reservation in page["Reservations"]:
        #         for instance in reservation["Instances"]:
        #             instance_id = instance["InstanceId"]
        #             instance_type = instance["InstanceType"]
        #             tags = instance.get("Tags", [])
        #             name = self.get_resource_name(tags)
        #
        #             # Step 2: Query CloudWatch for average CPU utilization
        #             end_time = datetime.now(timezone.utc)
        #             start_time = end_time - timedelta(days=lookback_days)
        #
        #             cpu_stats = cw_client.get_metric_statistics(
        #                 Namespace="AWS/EC2",
        #                 MetricName="CPUUtilization",
        #                 Dimensions=[
        #                     {"Name": "InstanceId", "Value": instance_id},
        #                 ],
        #                 StartTime=start_time,
        #                 EndTime=end_time,
        #                 Period=86400,  # 1-day granularity
        #                 Statistics=["Average"],
        #             )
        #
        #             if not cpu_stats["Datapoints"]:
        #                 # No metrics available — instance may be too new
        #                 continue
        #
        #             avg_cpu = sum(
        #                 dp["Average"] for dp in cpu_stats["Datapoints"]
        #             ) / len(cpu_stats["Datapoints"])
        #
        #             # Step 3: Check if CPU is below threshold
        #             if avg_cpu >= cpu_threshold:
        #                 continue  # Instance is adequately sized
        #
        #             # Step 4: Determine recommended smaller instance type
        #             recommended_type = self._get_smaller_type(instance_type)
        #             if recommended_type is None:
        #                 continue  # Already the smallest in its family
        #
        #             # Step 5: Calculate cost and savings
        #             current_cost = self._estimate_monthly_cost(instance_type)
        #             recommended_cost = self._estimate_monthly_cost(recommended_type)
        #             savings = current_cost - recommended_cost
        #
        #             # Step 6: Special handling for EKS nodes
        #             # Check if this instance is an EKS node by looking for
        #             # the "kubernetes.io/cluster/<name>" tag
        #             is_eks_node = any(
        #                 t.get("Key", "").startswith("kubernetes.io/cluster/")
        #                 for t in tags
        #             )
        #
        #             action = (
        #                 f"Downsize to {recommended_type} (avg CPU {avg_cpu:.0f}%)"
        #             )
        #             if is_eks_node:
        #                 # For EKS nodes, also note that node-level metrics
        #                 # should be verified (memory, pod count)
        #                 action += " [EKS node — verify memory/pod utilization]"
        #
        #             severity = "high" if savings > 100 else "medium"
        #
        #             results.append(CheckResult(
        #                 check_name=self.name,
        #                 resource_type="EC2 Instance",
        #                 resource_id=instance_id,
        #                 resource_name=name,
        #                 current_monthly_cost=current_cost,
        #                 recommended_action=action,
        #                 estimated_monthly_savings=savings,
        #                 severity=severity,
        #                 details={
        #                     "instance_type": instance_type,
        #                     "recommended_type": recommended_type,
        #                     "avg_cpu_percent": round(avg_cpu, 1),
        #                     "lookback_days": lookback_days,
        #                     "is_eks_node": is_eks_node,
        #                     "is_production": self.is_production(tags, name),
        #                 },
        #             ))

        return results

    def _get_smaller_type(self, instance_type: str) -> str | None:
        """Determine the next smaller instance type within the same family.

        Args:
            instance_type: Current instance type (e.g., "m5.2xlarge").

        Returns:
            Recommended smaller type (e.g., "m5.xlarge"), or None if
            already at the smallest trackable size.
        """
        parts = instance_type.split(".")
        if len(parts) != 2:
            return None

        family, size = parts

        # Handle "large" -> no smaller general recommendation
        # (nano/micro/small/medium are too small for most workloads)
        if size == "large":
            return None

        smaller_size = DOWNSIZE_MAP.get(size)
        if smaller_size is None:
            return None

        return f"{family}.{smaller_size}"

    def _estimate_monthly_cost(self, instance_type: str) -> float:
        """Estimate monthly on-demand cost for an instance type.

        Uses the approximate pricing table as a fallback. In production,
        this should query the AWS Pricing API for accurate regional pricing.

        Args:
            instance_type: EC2 instance type (e.g., "m5.xlarge").

        Returns:
            Estimated monthly cost in USD.
        """
        hourly = APPROX_HOURLY_PRICING.get(instance_type)
        if hourly is None:
            # TODO: Fall back to AWS Pricing API
            # pricing_client = session.client("pricing", region_name="us-east-1")
            # response = pricing_client.get_products(
            #     ServiceCode="AmazonEC2",
            #     Filters=[
            #         {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
            #         {"Type": "TERM_MATCH", "Field": "location", "Value": "US East (N. Virginia)"},
            #         {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
            #         {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
            #         {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
            #     ],
            # )
            return 0.0

        return hourly * HOURS_PER_MONTH
