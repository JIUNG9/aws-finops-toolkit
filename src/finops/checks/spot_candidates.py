"""Spot Instance Candidates Check — Find workloads suitable for Spot Instances.

Spot Instances offer 60-70% savings over On-Demand pricing for fault-tolerant
workloads. This check identifies Auto Scaling Groups (ASGs) and EKS managed
node groups in non-production environments that are good Spot candidates.

A good Spot candidate is:
  - In a non-production environment (dev, staging, test)
  - Stateless (no persistent EBS volumes attached beyond root)
  - Part of an Auto Scaling Group or EKS node group (can handle interruptions)
  - Not running critical singleton workloads

Typical savings: 60-70% per instance moved to Spot.

AWS APIs used:
  - autoscaling:DescribeAutoScalingGroups
  - ec2:DescribeInstances
  - ec2:DescribeVolumes
  - ec2:DescribeSpotPriceHistory (for current Spot pricing)
  - eks:ListNodegroups / eks:DescribeNodegroup
"""

from __future__ import annotations

from typing import Any

from finops.checks.base import BaseCheck, CheckResult


# Approximate Spot discount percentages by instance family
# Actual discounts vary by AZ and time; these are conservative estimates
SPOT_DISCOUNT_ESTIMATE: dict[str, float] = {
    "t3": 0.50,    # t3 Spot savings ~50%
    "m5": 0.65,    # m5 Spot savings ~65%
    "m6i": 0.65,
    "c5": 0.65,    # c5 Spot savings ~65%
    "c6i": 0.65,
    "r5": 0.60,    # r5 Spot savings ~60%
    "r6i": 0.60,
}

DEFAULT_SPOT_DISCOUNT = 0.60  # Conservative default: 60% savings


class SpotCandidatesCheck(BaseCheck):
    """Find non-production ASGs and EKS node groups suitable for Spot Instances."""

    name = "spot_candidates"
    description = "Identify stateless non-production workloads that could run on Spot Instances (60-70% savings)"

    def run(self, session: Any, region: str) -> list[CheckResult]:
        """Execute Spot Instance candidate check.

        Args:
            session: Authenticated boto3.Session.
            region: AWS region to scan.

        Returns:
            List of CheckResult for each ASG/node group that could use Spot.
        """
        results: list[CheckResult] = []

        # TODO: Uncomment and implement with real boto3 calls
        #
        # asg_client = session.client("autoscaling", region_name=region)
        # ec2_client = session.client("ec2", region_name=region)
        #
        # # ──────────────────────────────────────────────
        # # Part 1: Check Auto Scaling Groups
        # # ──────────────────────────────────────────────
        # paginator = asg_client.get_paginator("describe_auto_scaling_groups")
        #
        # for page in paginator.paginate():
        #     for asg in page["AutoScalingGroups"]:
        #         asg_name = asg["AutoScalingGroupName"]
        #         tags = [
        #             {"Key": t["Key"], "Value": t.get("Value", "")}
        #             for t in asg.get("Tags", [])
        #         ]
        #
        #         # Skip if already using Spot or mixed instances
        #         mixed_policy = asg.get("MixedInstancesPolicy")
        #         if mixed_policy:
        #             continue  # Already configured for Spot
        #
        #         # Skip production ASGs
        #         if self.is_production(tags, asg_name):
        #             continue
        #
        #         # Check if workload is stateless by examining instances
        #         instance_ids = [
        #             i["InstanceId"] for i in asg.get("Instances", [])
        #         ]
        #         if not instance_ids:
        #             continue
        #
        #         # Check for non-root EBS volumes (indicates statefulness)
        #         is_stateless = self._check_stateless(ec2_client, instance_ids)
        #         if not is_stateless:
        #             continue  # Has persistent storage, not a good Spot candidate
        #
        #         # Calculate current cost and potential savings
        #         # Get instance type from launch configuration or template
        #         instance_type = self._get_asg_instance_type(asg)
        #         if not instance_type:
        #             continue
        #
        #         instance_count = asg.get("DesiredCapacity", 0)
        #         current_monthly = self._estimate_asg_monthly_cost(
        #             instance_type, instance_count
        #         )
        #         discount = self._get_spot_discount(instance_type)
        #         savings = current_monthly * discount
        #
        #         results.append(CheckResult(
        #             check_name=self.name,
        #             resource_type="Auto Scaling Group",
        #             resource_id=asg_name,
        #             resource_name=self.get_resource_name(tags) or asg_name,
        #             current_monthly_cost=current_monthly,
        #             recommended_action=(
        #                 f"Switch to Spot Instances — {instance_count}x {instance_type}, "
        #                 f"stateless non-prod workload (~{discount*100:.0f}% savings)"
        #             ),
        #             estimated_monthly_savings=savings,
        #             severity="high" if savings > 200 else "medium",
        #             details={
        #                 "instance_type": instance_type,
        #                 "instance_count": instance_count,
        #                 "spot_discount_estimate": discount,
        #                 "is_stateless": True,
        #                 "is_eks_nodegroup": False,
        #             },
        #         ))
        #
        # # ──────────────────────────────────────────────
        # # Part 2: Check EKS Managed Node Groups
        # # ──────────────────────────────────────────────
        # try:
        #     eks_client = session.client("eks", region_name=region)
        #     clusters = eks_client.list_clusters()["clusters"]
        #
        #     for cluster_name in clusters:
        #         nodegroups = eks_client.list_nodegroups(
        #             clusterName=cluster_name
        #         )["nodegroups"]
        #
        #         for ng_name in nodegroups:
        #             ng = eks_client.describe_nodegroup(
        #                 clusterName=cluster_name,
        #                 nodegroupName=ng_name,
        #             )["nodegroup"]
        #
        #             # Skip if already using Spot
        #             if ng.get("capacityType") == "SPOT":
        #                 continue
        #
        #             # Skip production clusters
        #             ng_tags = [
        #                 {"Key": k, "Value": v}
        #                 for k, v in ng.get("tags", {}).items()
        #             ]
        #             if self.is_production(ng_tags, cluster_name):
        #                 continue
        #
        #             instance_types = ng.get("instanceTypes", [])
        #             instance_type = instance_types[0] if instance_types else "unknown"
        #             desired = ng.get("scalingConfig", {}).get("desiredSize", 0)
        #
        #             current_monthly = self._estimate_asg_monthly_cost(
        #                 instance_type, desired
        #             )
        #             discount = self._get_spot_discount(instance_type)
        #             savings = current_monthly * discount
        #
        #             results.append(CheckResult(
        #                 check_name=self.name,
        #                 resource_type="EKS Node Group",
        #                 resource_id=f"{cluster_name}/{ng_name}",
        #                 resource_name=ng_name,
        #                 current_monthly_cost=current_monthly,
        #                 recommended_action=(
        #                     f"Switch to Spot capacity — {desired}x {instance_type}, "
        #                     f"non-prod EKS cluster (~{discount*100:.0f}% savings)"
        #                 ),
        #                 estimated_monthly_savings=savings,
        #                 severity="high" if savings > 200 else "medium",
        #                 details={
        #                     "cluster_name": cluster_name,
        #                     "nodegroup_name": ng_name,
        #                     "instance_type": instance_type,
        #                     "desired_size": desired,
        #                     "spot_discount_estimate": discount,
        #                     "is_eks_nodegroup": True,
        #                 },
        #             ))
        #
        # except Exception:
        #     pass  # EKS not available or no permissions

        return results

    def _check_stateless(self, ec2_client: Any, instance_ids: list[str]) -> bool:
        """Check if instances in an ASG are stateless (no extra EBS volumes).

        A stateless workload only has the root volume. If instances have
        additional EBS volumes attached, the workload is likely stateful
        and not a good Spot candidate.

        Args:
            ec2_client: boto3 EC2 client.
            instance_ids: List of EC2 instance IDs to check.

        Returns:
            True if all instances appear stateless (root volume only).
        """
        # TODO: Implement — check first instance as representative sample
        # response = ec2_client.describe_instances(InstanceIds=instance_ids[:1])
        # for reservation in response["Reservations"]:
        #     for instance in reservation["Instances"]:
        #         block_devices = instance.get("BlockDeviceMappings", [])
        #         # Root device is always present; more than 1 means extra volumes
        #         if len(block_devices) > 1:
        #             return False
        return True

    def _get_asg_instance_type(self, asg: dict[str, Any]) -> str | None:
        """Extract instance type from an ASG's launch config or template.

        Args:
            asg: ASG description dict from AWS API.

        Returns:
            Instance type string, or None if not determinable.
        """
        # TODO: Implement — check LaunchConfigurationName or LaunchTemplate
        # If using launch template, need to describe it to get instance type
        # launch_config = asg.get("LaunchConfigurationName")
        # launch_template = asg.get("LaunchTemplate", {})
        return None

    def _estimate_asg_monthly_cost(self, instance_type: str, count: int) -> float:
        """Estimate monthly cost for an ASG based on instance type and count.

        Args:
            instance_type: EC2 instance type.
            count: Number of instances (desired capacity).

        Returns:
            Estimated monthly cost in USD.
        """
        # Import pricing from EC2 rightsizing check
        from finops.checks.ec2_rightsizing import APPROX_HOURLY_PRICING, HOURS_PER_MONTH

        hourly = APPROX_HOURLY_PRICING.get(instance_type, 0.10)  # Default fallback
        return hourly * HOURS_PER_MONTH * count

    def _get_spot_discount(self, instance_type: str) -> float:
        """Get estimated Spot discount for an instance type.

        Args:
            instance_type: EC2 instance type (e.g., "m5.xlarge").

        Returns:
            Discount as a fraction (e.g., 0.65 = 65% savings).
        """
        family = instance_type.split(".")[0] if "." in instance_type else instance_type
        return SPOT_DISCOUNT_ESTIMATE.get(family, DEFAULT_SPOT_DISCOUNT)
