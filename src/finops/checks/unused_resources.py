"""Unused Resource Detection — Find resources you're paying for but not using.

This is often the lowest-hanging fruit in FinOps. Common culprits:
  - Unattached EBS volumes (leftover from terminated instances)
  - Unused Elastic IPs ($3.60/month each since Feb 2024)
  - Old snapshots nobody remembers creating (> 90 days)
  - Idle load balancers with 0 connections for 7+ days
  - Stopped instances still paying for EBS storage

Each sub-check runs independently and produces separate findings.

Typical savings: Varies widely — often $50-500/month in accumulated waste.

AWS APIs used:
  - ec2:DescribeVolumes
  - ec2:DescribeAddresses
  - ec2:DescribeSnapshots
  - ec2:DescribeInstances
  - elasticloadbalancingv2:DescribeLoadBalancers
  - cloudwatch:GetMetricStatistics
"""

from __future__ import annotations

from typing import Any

from finops.checks.base import BaseCheck, CheckResult


# EBS volume pricing (gp3, us-east-1)
EBS_GP3_PER_GB_MONTH = 0.08      # $/GB/month
EBS_GP2_PER_GB_MONTH = 0.10      # $/GB/month
EBS_IO1_PER_GB_MONTH = 0.125     # $/GB/month

# EIP pricing (since Feb 2024, all EIPs incur charges)
EIP_MONTHLY_COST = 3.60          # $0.005/hr * 730 hrs

# Snapshot pricing
SNAPSHOT_PER_GB_MONTH = 0.05     # $/GB/month

# ALB pricing
ALB_MONTHLY_FIXED = 16.43        # $0.0225/hr * 730 hrs (fixed cost only)


class UnusedResourcesCheck(BaseCheck):
    """Detect unused AWS resources that are still incurring charges."""

    name = "unused_resources"
    description = "Find unattached EBS volumes, unused EIPs, old snapshots, idle LBs, and long-stopped instances"

    def run(self, session: Any, region: str) -> list[CheckResult]:
        """Execute all unused resource sub-checks.

        Args:
            session: Authenticated boto3.Session.
            region: AWS region to scan.

        Returns:
            Combined list of CheckResult from all sub-checks.
        """
        results: list[CheckResult] = []

        # Run each sub-check and aggregate results
        results.extend(self._check_unattached_ebs(session, region))
        results.extend(self._check_unused_eips(session, region))
        results.extend(self._check_old_snapshots(session, region))
        results.extend(self._check_idle_load_balancers(session, region))
        results.extend(self._check_stopped_instances(session, region))

        return results

    def _check_unattached_ebs(self, session: Any, region: str) -> list[CheckResult]:
        """Find EBS volumes in 'available' state (not attached to any instance).

        These are typically leftover from terminated instances. They incur
        storage charges for as long as they exist.
        """
        results: list[CheckResult] = []

        # TODO: Uncomment and implement with real boto3 calls
        # ec2_client = session.client("ec2", region_name=region)
        #
        # paginator = ec2_client.get_paginator("describe_volumes")
        # for page in paginator.paginate(
        #     Filters=[{"Name": "status", "Values": ["available"]}]
        # ):
        #     for volume in page["Volumes"]:
        #         vol_id = volume["VolumeId"]
        #         size_gb = volume["Size"]
        #         vol_type = volume["VolumeType"]
        #         tags = volume.get("Tags", [])
        #         name = self.get_resource_name(tags)
        #         create_time = volume["CreateTime"]
        #
        #         # Calculate monthly cost based on volume type
        #         if vol_type == "gp3":
        #             monthly_cost = size_gb * EBS_GP3_PER_GB_MONTH
        #         elif vol_type == "gp2":
        #             monthly_cost = size_gb * EBS_GP2_PER_GB_MONTH
        #         elif vol_type == "io1" or vol_type == "io2":
        #             monthly_cost = size_gb * EBS_IO1_PER_GB_MONTH
        #         else:
        #             monthly_cost = size_gb * EBS_GP3_PER_GB_MONTH  # fallback
        #
        #         days_unattached = (datetime.now(timezone.utc) - create_time).days
        #
        #         results.append(CheckResult(
        #             check_name=self.name,
        #             resource_type="EBS Volume",
        #             resource_id=vol_id,
        #             resource_name=name,
        #             current_monthly_cost=monthly_cost,
        #             recommended_action=(
        #                 f"Delete — unattached {vol_type} volume "
        #                 f"({size_gb} GB, unattached ~{days_unattached} days)"
        #             ),
        #             estimated_monthly_savings=monthly_cost,
        #             severity="medium" if monthly_cost < 50 else "high",
        #             details={
        #                 "volume_type": vol_type,
        #                 "size_gb": size_gb,
        #                 "days_unattached": days_unattached,
        #                 "sub_check": "unattached_ebs",
        #             },
        #         ))

        return results

    def _check_unused_eips(self, session: Any, region: str) -> list[CheckResult]:
        """Find Elastic IPs not associated with any instance or ENI.

        Since February 2024, AWS charges $3.60/month for ALL Elastic IPs,
        including those associated with running instances. Unassociated EIPs
        are pure waste.
        """
        results: list[CheckResult] = []

        # TODO: Uncomment and implement with real boto3 calls
        # ec2_client = session.client("ec2", region_name=region)
        #
        # response = ec2_client.describe_addresses()
        # for eip in response["Addresses"]:
        #     allocation_id = eip.get("AllocationId", "")
        #     public_ip = eip.get("PublicIp", "")
        #     association_id = eip.get("AssociationId")
        #     tags = eip.get("Tags", [])
        #     name = self.get_resource_name(tags)
        #
        #     # Flag unassociated EIPs (no AssociationId means not attached)
        #     if not association_id:
        #         results.append(CheckResult(
        #             check_name=self.name,
        #             resource_type="Elastic IP",
        #             resource_id=allocation_id or public_ip,
        #             resource_name=name or public_ip,
        #             current_monthly_cost=EIP_MONTHLY_COST,
        #             recommended_action="Release — not associated with any resource",
        #             estimated_monthly_savings=EIP_MONTHLY_COST,
        #             severity="low",
        #             details={
        #                 "public_ip": public_ip,
        #                 "sub_check": "unused_eip",
        #             },
        #         ))

        return results

    def _check_old_snapshots(self, session: Any, region: str) -> list[CheckResult]:
        """Find EBS snapshots older than the configured threshold (default: 90 days).

        Old snapshots accumulate over time and are easy to forget. They're
        charged at $0.05/GB/month and can add up significantly.
        """
        results: list[CheckResult] = []
        # Threshold used by TODO implementation below
        self.config.thresholds.get("snapshot_age_days", 90)

        # TODO: Uncomment and implement with real boto3 calls
        # ec2_client = session.client("ec2", region_name=region)
        #
        # # Only check snapshots owned by this account
        # paginator = ec2_client.get_paginator("describe_snapshots")
        # for page in paginator.paginate(OwnerIds=["self"]):
        #     for snapshot in page["Snapshots"]:
        #         snap_id = snapshot["SnapshotId"]
        #         size_gb = snapshot["VolumeSize"]
        #         start_time = snapshot["StartTime"]
        #         tags = snapshot.get("Tags", [])
        #         name = self.get_resource_name(tags)
        #         description = snapshot.get("Description", "")
        #
        #         age_days = (datetime.now(timezone.utc) - start_time).days
        #
        #         if age_days < age_threshold:
        #             continue
        #
        #         # Skip snapshots created by AWS Backup (they have lifecycle management)
        #         if "aws:backup" in description.lower() or self.get_tag_value(tags, "aws:backup:source-resource"):
        #             continue
        #
        #         monthly_cost = size_gb * SNAPSHOT_PER_GB_MONTH
        #
        #         results.append(CheckResult(
        #             check_name=self.name,
        #             resource_type="EBS Snapshot",
        #             resource_id=snap_id,
        #             resource_name=name or description[:50] or snap_id,
        #             current_monthly_cost=monthly_cost,
        #             recommended_action=(
        #                 f"Delete — {age_days} days old ({size_gb} GB), "
        #                 f"exceeds {age_threshold}-day threshold"
        #             ),
        #             estimated_monthly_savings=monthly_cost,
        #             severity="low" if monthly_cost < 10 else "medium",
        #             details={
        #                 "size_gb": size_gb,
        #                 "age_days": age_days,
        #                 "description": description,
        #                 "sub_check": "old_snapshot",
        #             },
        #         ))

        return results

    def _check_idle_load_balancers(self, session: Any, region: str) -> list[CheckResult]:
        """Find ALBs/NLBs with 0 active connections over the past 7 days.

        Idle load balancers cost ~$16/month in fixed charges alone, plus
        any associated target groups and rules.
        """
        results: list[CheckResult] = []
        # Threshold used by TODO implementation below
        self.config.thresholds.get("idle_lb_days", 7)

        # TODO: Uncomment and implement with real boto3 calls
        # elbv2_client = session.client("elbv2", region_name=region)
        # cw_client = session.client("cloudwatch", region_name=region)
        #
        # paginator = elbv2_client.get_paginator("describe_load_balancers")
        # for page in paginator.paginate():
        #     for lb in page["LoadBalancers"]:
        #         lb_arn = lb["LoadBalancerArn"]
        #         lb_name = lb["LoadBalancerName"]
        #         lb_type = lb["Type"]  # "application" or "network"
        #
        #         # Extract the ARN suffix for CloudWatch dimension
        #         # Format: app/my-alb/1234567890abcdef
        #         arn_suffix = "/".join(lb_arn.split("/")[-3:])
        #
        #         # Query CloudWatch for active connections
        #         end_time = datetime.now(timezone.utc)
        #         start_time = end_time - timedelta(days=idle_days)
        #
        #         metric_name = (
        #             "ActiveConnectionCount" if lb_type == "application"
        #             else "ActiveFlowCount"
        #         )
        #         namespace = "AWS/ApplicationELB" if lb_type == "application" else "AWS/NetworkELB"
        #
        #         stats = cw_client.get_metric_statistics(
        #             Namespace=namespace,
        #             MetricName=metric_name,
        #             Dimensions=[
        #                 {"Name": "LoadBalancer", "Value": arn_suffix},
        #             ],
        #             StartTime=start_time,
        #             EndTime=end_time,
        #             Period=86400,
        #             Statistics=["Sum"],
        #         )
        #
        #         total_connections = sum(
        #             dp["Sum"] for dp in stats.get("Datapoints", [])
        #         )
        #
        #         if total_connections == 0:
        #             results.append(CheckResult(
        #                 check_name=self.name,
        #                 resource_type=f"{'ALB' if lb_type == 'application' else 'NLB'}",
        #                 resource_id=lb_name,
        #                 resource_name=lb_name,
        #                 current_monthly_cost=ALB_MONTHLY_FIXED,
        #                 recommended_action=(
        #                     f"Delete — 0 connections over {idle_days} days"
        #                 ),
        #                 estimated_monthly_savings=ALB_MONTHLY_FIXED,
        #                 severity="medium",
        #                 details={
        #                     "lb_type": lb_type,
        #                     "lb_arn": lb_arn,
        #                     "idle_days_checked": idle_days,
        #                     "total_connections": 0,
        #                     "sub_check": "idle_load_balancer",
        #                 },
        #             ))

        return results

    def _check_stopped_instances(self, session: Any, region: str) -> list[CheckResult]:
        """Find EC2 instances stopped for more than 7 days.

        Stopped instances don't incur compute charges, but you still pay for:
        - All attached EBS volumes
        - Any associated Elastic IPs
        These costs can be significant for instances with large root volumes.
        """
        results: list[CheckResult] = []
        # Threshold used by TODO implementation below
        self.config.thresholds.get("stopped_instance_days", 7)

        # TODO: Uncomment and implement with real boto3 calls
        # ec2_client = session.client("ec2", region_name=region)
        #
        # paginator = ec2_client.get_paginator("describe_instances")
        # for page in paginator.paginate(
        #     Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]
        # ):
        #     for reservation in page["Reservations"]:
        #         for instance in reservation["Instances"]:
        #             instance_id = instance["InstanceId"]
        #             tags = instance.get("Tags", [])
        #             name = self.get_resource_name(tags)
        #
        #             # Check state transition reason timestamp
        #             state_reason = instance.get("StateTransitionReason", "")
        #             # StateTransitionReason looks like:
        #             # "User initiated (2026-01-15 10:30:00 GMT)"
        #             # We need to parse the date to check how long it's been stopped
        #
        #             # Calculate EBS cost for attached volumes
        #             ebs_monthly = 0.0
        #             for bdm in instance.get("BlockDeviceMappings", []):
        #                 vol_id = bdm.get("Ebs", {}).get("VolumeId")
        #                 if vol_id:
        #                     # TODO: Look up volume size and type for accurate pricing
        #                     # For now, estimate based on typical root volume
        #                     ebs_monthly += 8.0 * EBS_GP3_PER_GB_MONTH  # 8 GB root vol
        #
        #             # TODO: Parse state_reason to get actual stopped date
        #             # For now, flag all stopped instances with a note to check
        #             if ebs_monthly > 0:
        #                 results.append(CheckResult(
        #                     check_name=self.name,
        #                     resource_type="EC2 Instance (stopped)",
        #                     resource_id=instance_id,
        #                     resource_name=name,
        #                     current_monthly_cost=ebs_monthly,
        #                     recommended_action=(
        #                         f"Terminate or create AMI — stopped for >{stopped_days_threshold} days, "
        #                         f"still paying for EBS"
        #                     ),
        #                     estimated_monthly_savings=ebs_monthly,
        #                     severity="low",
        #                     details={
        #                         "instance_type": instance["InstanceType"],
        #                         "state_reason": state_reason,
        #                         "ebs_monthly_cost": ebs_monthly,
        #                         "sub_check": "stopped_instance",
        #                     },
        #                 ))

        return results
