"""Unused Resource Detection — Find resources you're paying for but not using.

This is often the lowest-hanging fruit in FinOps. Common culprits:
  - Unattached EBS volumes (leftover from terminated instances)
  - Unused Elastic IPs ($3.60/month each since Feb 2024)
  - Old snapshots nobody remembers creating (> 90 days)
  - Idle load balancers with no traffic for 7+ days
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

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from finops.checks.base import BaseCheck, CheckResult


# EBS volume pricing (gp3, us-east-1)
EBS_GP3_PER_GB_MONTH = 0.08      # $/GB/month
EBS_GP2_PER_GB_MONTH = 0.10      # $/GB/month
EBS_IO1_PER_GB_MONTH = 0.125     # $/GB/month
EBS_ST1_PER_GB_MONTH = 0.045     # $/GB/month (throughput optimized HDD)
EBS_SC1_PER_GB_MONTH = 0.015     # $/GB/month (cold HDD)
EBS_STANDARD_PER_GB_MONTH = 0.05  # $/GB/month (previous-generation magnetic)

# Per-GB rate by EBS volume type. Types not listed fall back to the gp3 rate.
EBS_PRICE_PER_GB_MONTH = {
    "gp3": EBS_GP3_PER_GB_MONTH,
    "gp2": EBS_GP2_PER_GB_MONTH,
    "io1": EBS_IO1_PER_GB_MONTH,
    "io2": EBS_IO1_PER_GB_MONTH,
    "st1": EBS_ST1_PER_GB_MONTH,
    "sc1": EBS_SC1_PER_GB_MONTH,
    "standard": EBS_STANDARD_PER_GB_MONTH,
}

# Volumes younger than this are skipped, so one just created and not yet attached
# (or detached for a deploy) isn't reported.
DEFAULT_UNATTACHED_VOLUME_GRACE_DAYS = 7

# EIP pricing (since Feb 2024, all EIPs incur charges)
EIP_MONTHLY_COST = 3.60          # $0.005/hr * 730 hrs

# Snapshot pricing
SNAPSHOT_PER_GB_MONTH = 0.05     # $/GB/month

# ALB and NLB pricing (same hourly rate; fixed cost only, LCU charges excluded)
LB_MONTHLY_FIXED = 16.43         # $0.0225/hr * 730 hrs

# elbv2 Type -> (finding label, CloudWatch namespace, traffic metric)
LB_TRAFFIC_METRICS = {
    "application": ("ALB", "AWS/ApplicationELB", "RequestCount"),
    "network": ("NLB", "AWS/NetworkELB", "NewFlowCount"),
}

# "User initiated (2026-01-15 10:30:00 GMT)" -> the timestamp inside the parentheses
STATE_REASON_TIME = re.compile(r"\((\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (?:GMT|UTC)\)")


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
        storage charges for as long as they exist. Volumes younger than the
        `unattached_volume_grace_days` threshold (default 7) are skipped.
        """
        results: list[CheckResult] = []

        grace_days = self.config.thresholds.get(
            "unattached_volume_grace_days", DEFAULT_UNATTACHED_VOLUME_GRACE_DAYS
        )
        ec2_client = session.client("ec2", region_name=region)

        # status=available is filtered server-side, so in-use volumes never come back.
        paginator = ec2_client.get_paginator("describe_volumes")
        for page in paginator.paginate(
            Filters=[{"Name": "status", "Values": ["available"]}]
        ):
            for volume in page["Volumes"]:
                vol_id = volume["VolumeId"]
                size_gb = volume["Size"]
                vol_type = volume["VolumeType"]
                tags = volume.get("Tags", [])
                name = self.get_resource_name(tags)
                create_time = volume["CreateTime"]

                # CreateTime is when the volume was made, not when it was detached.
                # DescribeVolumes has no detach timestamp, so this is age, not idle time.
                age_days = (datetime.now(timezone.utc) - create_time).days
                if age_days < grace_days:
                    continue

                rate = EBS_PRICE_PER_GB_MONTH.get(vol_type, EBS_GP3_PER_GB_MONTH)
                monthly_cost = size_gb * rate

                results.append(CheckResult(
                    check_name=self.name,
                    resource_type="EBS Volume",
                    resource_id=vol_id,
                    resource_name=name,
                    current_monthly_cost=monthly_cost,
                    recommended_action=(
                        f"Delete — unattached {vol_type} volume "
                        f"({size_gb} GB, created {age_days} days ago)"
                    ),
                    estimated_monthly_savings=monthly_cost,
                    severity="medium" if monthly_cost < 50 else "high",
                    details={
                        "volume_type": vol_type,
                        "size_gb": size_gb,
                        "age_days": age_days,
                        "sub_check": "unattached_ebs",
                    },
                ))

        return results

    def _check_unused_eips(self, session: Any, region: str) -> list[CheckResult]:
        """Find Elastic IPs not associated with any instance or ENI.

        Since February 2024, AWS charges $3.60/month for ALL Elastic IPs,
        including those associated with running instances. Unassociated EIPs
        are pure waste.
        """
        results: list[CheckResult] = []

        ec2_client = session.client("ec2", region_name=region)

        # DescribeAddresses has no paginator and no server-side "unassociated" filter.
        # An EIP with no AssociationId isn't attached to an instance or an ENI.
        response = ec2_client.describe_addresses()
        for eip in response["Addresses"]:
            if eip.get("AssociationId"):
                continue

            allocation_id = eip.get("AllocationId", "")
            public_ip = eip.get("PublicIp", "")
            name = self.get_resource_name(eip.get("Tags", []))

            results.append(CheckResult(
                check_name=self.name,
                resource_type="Elastic IP",
                resource_id=allocation_id or public_ip,
                resource_name=name if name != "(unnamed)" else public_ip,
                current_monthly_cost=EIP_MONTHLY_COST,
                recommended_action="Release — not associated with any resource",
                estimated_monthly_savings=EIP_MONTHLY_COST,
                severity="low",
                details={
                    "public_ip": public_ip,
                    "sub_check": "unused_eip",
                },
            ))

        return results

    def _check_old_snapshots(self, session: Any, region: str) -> list[CheckResult]:
        """Find EBS snapshots older than the configured threshold (default: 90 days).

        Old snapshots accumulate over time and are easy to forget. They're
        charged at $0.05/GB/month and can add up significantly.

        Skipped on purpose:
        - Snapshots that back one of this account's AMIs. AWS refuses to delete
          them until the AMI is deregistered, so "Delete" would be wrong advice.
        - Snapshots created by AWS Backup, which manages their lifecycle.
        - Snapshots still pending; they have no final size yet.

        The cost is an upper bound. Snapshots are incremental, so the billed
        size is usually below the source volume size, and DescribeSnapshots
        does not report it.
        """
        results: list[CheckResult] = []
        age_threshold = self.config.thresholds.get("snapshot_age_days", 90)

        ec2_client = session.client("ec2", region_name=region)

        ami_snapshot_ids = self._ami_snapshot_ids(ec2_client)

        # OwnerIds=self leaves out the public and shared snapshots we don't pay for.
        paginator = ec2_client.get_paginator("describe_snapshots")
        for page in paginator.paginate(OwnerIds=["self"]):
            for snapshot in page["Snapshots"]:
                snap_id = snapshot["SnapshotId"]
                if snapshot.get("State") == "pending" or snap_id in ami_snapshot_ids:
                    continue

                size_gb = snapshot["VolumeSize"]
                tags = snapshot.get("Tags", [])
                description = snapshot.get("Description", "")

                age_days = (datetime.now(timezone.utc) - snapshot["StartTime"]).days
                if age_days < age_threshold:
                    continue

                if self._is_aws_backup_snapshot(tags, description):
                    continue

                name = self.get_resource_name(tags)
                monthly_cost = size_gb * SNAPSHOT_PER_GB_MONTH

                results.append(CheckResult(
                    check_name=self.name,
                    resource_type="EBS Snapshot",
                    resource_id=snap_id,
                    resource_name=name if name != "(unnamed)" else (description[:50] or snap_id),
                    current_monthly_cost=monthly_cost,
                    recommended_action=(
                        f"Delete — {age_days} days old ({size_gb} GB), "
                        f"exceeds {age_threshold}-day threshold"
                    ),
                    estimated_monthly_savings=monthly_cost,
                    severity="low" if monthly_cost < 10 else "medium",
                    details={
                        "size_gb": size_gb,
                        "age_days": age_days,
                        "description": description,
                        "cost_is_upper_bound": True,
                        "sub_check": "old_snapshot",
                    },
                ))

        return results

    @staticmethod
    def _ami_snapshot_ids(ec2_client: Any) -> set[str]:
        """Snapshot IDs referenced by the block device mappings of our own AMIs."""
        snapshot_ids: set[str] = set()
        paginator = ec2_client.get_paginator("describe_images")
        for page in paginator.paginate(Owners=["self"]):
            for image in page["Images"]:
                for mapping in image.get("BlockDeviceMappings", []):
                    snap_id = mapping.get("Ebs", {}).get("SnapshotId")
                    if snap_id:
                        snapshot_ids.add(snap_id)
        return snapshot_ids

    def _is_aws_backup_snapshot(self, tags: list[dict[str, str]], description: str) -> bool:
        """AWS Backup tags its snapshots with aws:backup:source-resource."""
        return (
            self.get_tag_value(tags, "aws:backup:source-resource") is not None
            or "aws backup" in description.lower()
        )

    def _check_idle_load_balancers(self, session: Any, region: str) -> list[CheckResult]:
        """Find ALBs and NLBs that served no traffic over the past 7 days.

        An idle load balancer costs about $16/month in fixed charges alone.
        Traffic is read from CloudWatch: `RequestCount` for ALBs, `NewFlowCount`
        for NLBs. Both are only published while traffic flows, so a missing or
        all-zero series means idle.

        Skipped on purpose:
        - Load balancers younger than the window, which can't show 7 idle days yet.
        - Gateway load balancers and Classic ELBs, which use other APIs and prices.
        """
        results: list[CheckResult] = []
        idle_days = self.config.thresholds.get("idle_lb_days", 7)

        elbv2_client = session.client("elbv2", region_name=region)
        cw_client = session.client("cloudwatch", region_name=region)

        now = datetime.now(timezone.utc)
        paginator = elbv2_client.get_paginator("describe_load_balancers")
        for page in paginator.paginate():
            for lb in page["LoadBalancers"]:
                lb_type = lb["Type"]
                if lb_type not in LB_TRAFFIC_METRICS:
                    continue

                created = lb.get("CreatedTime")
                if created is not None and (now - created).days < idle_days:
                    continue

                label, namespace, metric_name = LB_TRAFFIC_METRICS[lb_type]
                lb_arn = lb["LoadBalancerArn"]
                lb_name = lb["LoadBalancerName"]
                # CloudWatch identifies the LB by the ARN tail: app/<name>/<id>.
                arn_suffix = "/".join(lb_arn.split("/")[-3:])

                stats = cw_client.get_metric_statistics(
                    Namespace=namespace,
                    MetricName=metric_name,
                    Dimensions=[{"Name": "LoadBalancer", "Value": arn_suffix}],
                    StartTime=now - timedelta(days=idle_days),
                    EndTime=now,
                    Period=86400 * idle_days,
                    Statistics=["Sum"],
                )
                if sum(dp["Sum"] for dp in stats.get("Datapoints", [])) > 0:
                    continue

                results.append(CheckResult(
                    check_name=self.name,
                    resource_type=label,
                    resource_id=lb_arn,
                    resource_name=lb_name,
                    current_monthly_cost=LB_MONTHLY_FIXED,
                    recommended_action=(
                        f"Delete — no traffic ({metric_name}) over {idle_days} days"
                    ),
                    estimated_monthly_savings=LB_MONTHLY_FIXED,
                    severity="medium",
                    details={
                        "lb_type": lb_type,
                        "idle_days_checked": idle_days,
                        "metric": metric_name,
                        "cost_is_fixed_charge_only": True,
                        "sub_check": "idle_load_balancer",
                    },
                ))

        return results

    def _check_stopped_instances(self, session: Any, region: str) -> list[CheckResult]:
        """Find EC2 instances stopped for more than 7 days (`stopped_instance_days`).

        A stopped instance has no compute charge, but its EBS volumes keep billing.
        The stop time comes from `StateTransitionReason`, which reads like
        "User initiated (2026-01-15 10:30:00 GMT)". Instances whose reason has no
        timestamp (for example an empty reason) are skipped, because their stop time
        can't be shown. Volume sizes and types are read with DescribeVolumes.

        The savings figure is the volumes' monthly cost. Terminating the instance
        frees it, but keeping an AMI first costs snapshot storage, so treat it as
        an upper bound.
        """
        results: list[CheckResult] = []
        days_threshold = self.config.thresholds.get("stopped_instance_days", 7)

        ec2_client = session.client("ec2", region_name=region)

        now = datetime.now(timezone.utc)
        paginator = ec2_client.get_paginator("describe_instances")
        for page in paginator.paginate(
            Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]
        ):
            for reservation in page["Reservations"]:
                for instance in reservation["Instances"]:
                    state_reason = instance.get("StateTransitionReason", "")
                    stopped_at = self._parse_stop_time(state_reason)
                    if stopped_at is None:
                        continue
                    stopped_days = (now - stopped_at).days
                    if stopped_days < days_threshold:
                        continue

                    volume_ids = [
                        bdm["Ebs"]["VolumeId"]
                        for bdm in instance.get("BlockDeviceMappings", [])
                        if bdm.get("Ebs", {}).get("VolumeId")
                    ]
                    # Instance-store-only instances have no volumes and no ongoing cost.
                    if not volume_ids:
                        continue
                    ebs_monthly = self._volumes_monthly_cost(ec2_client, volume_ids)

                    results.append(CheckResult(
                        check_name=self.name,
                        resource_type="EC2 Instance (stopped)",
                        resource_id=instance["InstanceId"],
                        resource_name=self.get_resource_name(instance.get("Tags", [])),
                        current_monthly_cost=ebs_monthly,
                        recommended_action=(
                            f"Terminate or create an AMI — stopped for {stopped_days} days, "
                            f"still paying for {len(volume_ids)} EBS volume(s)"
                        ),
                        estimated_monthly_savings=ebs_monthly,
                        severity="low" if ebs_monthly < 50 else "medium",
                        details={
                            "instance_type": instance["InstanceType"],
                            "stopped_days": stopped_days,
                            "state_reason": state_reason,
                            "volume_ids": volume_ids,
                            "cost_is_upper_bound": True,
                            "sub_check": "stopped_instance",
                        },
                    ))

        return results

    @staticmethod
    def _parse_stop_time(state_reason: str) -> datetime | None:
        """The timestamp in a StateTransitionReason, or None if it has none.

        AWS writes the zone as GMT; moto writes UTC. Both are UTC.
        """
        match = STATE_REASON_TIME.search(state_reason)
        if match is None:
            return None
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

    @staticmethod
    def _volumes_monthly_cost(ec2_client: Any, volume_ids: list[str]) -> float:
        """Monthly storage cost of the given volumes, priced by size and type."""
        total = 0.0
        paginator = ec2_client.get_paginator("describe_volumes")
        for page in paginator.paginate(VolumeIds=volume_ids):
            for volume in page["Volumes"]:
                rate = EBS_PRICE_PER_GB_MONTH.get(volume["VolumeType"], EBS_GP3_PER_GB_MONTH)
                total += volume["Size"] * rate
        return total
