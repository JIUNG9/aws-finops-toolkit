"""NAT Gateway Optimization Check — Detect expensive NAT Gateways in non-prod environments.

NAT Gateways are one of the sneakiest cost drivers on AWS. Each one costs
~$32/month ($0.045/hr) just to exist, plus $0.045/GB for data processing.
In dev/staging environments, a NAT Instance (t3.nano at ~$3.80/month) does
the same job at a fraction of the cost.

This check:
  1. Lists all NAT Gateways in the account
  2. Flags NAT Gateways in non-production VPCs (based on tags)
  3. Detects unused NAT Gateways (0 bytes processed over 7 days)
  4. Calculates cost difference vs NAT Instance alternative
  5. Estimates data processing costs from CloudWatch metrics

Typical savings: $28-45/month per NAT Gateway replaced or removed.

AWS APIs used:
  - ec2:DescribeNatGateways
  - ec2:DescribeVpcs
  - cloudwatch:GetMetricStatistics
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from finops.checks.base import BaseCheck, CheckResult


# NAT Gateway fixed costs (us-east-1)
NAT_GATEWAY_HOURLY_COST = 0.045       # $/hr
NAT_GATEWAY_PER_GB_COST = 0.045       # $/GB processed
NAT_GATEWAY_MONTHLY_FIXED = NAT_GATEWAY_HOURLY_COST * 730  # ~$32.85/month

# NAT Instance alternative costs (t3.nano in us-east-1)
NAT_INSTANCE_MONTHLY_COST = 3.80      # t3.nano on-demand


class NATGatewayCheck(BaseCheck):
    """Detect NAT Gateways that are unnecessary or could be replaced cheaper.

    Flags:
    - NAT Gateways in dev/staging VPCs (recommend NAT Instance)
    - Unused NAT Gateways (0 bytes processed — recommend deletion)
    """

    name = "nat_gateway"
    description = "Detect NAT Gateways in dev/staging environments and flag unused gateways"

    def run(self, session: Any, region: str) -> list[CheckResult]:
        """Execute NAT Gateway check.

        Args:
            session: Authenticated boto3.Session.
            region: AWS region to scan.

        Returns:
            List of CheckResult for each NAT Gateway finding.
        """
        results: list[CheckResult] = []

        # TODO: Uncomment and implement with real boto3 calls
        # ec2_client = session.client("ec2", region_name=region)
        # cw_client = session.client("cloudwatch", region_name=region)
        #
        # # Step 1: Get all NAT Gateways
        # paginator = ec2_client.get_paginator("describe_nat_gateways")
        # nat_gateways = []
        # for page in paginator.paginate(
        #     Filters=[{"Name": "state", "Values": ["available"]}]
        # ):
        #     nat_gateways.extend(page["NatGateways"])
        #
        # # Step 2: Build a VPC tag lookup for environment detection
        # vpc_ids = list(set(ng["VpcId"] for ng in nat_gateways))
        # vpc_tags: dict[str, list[dict]] = {}
        # if vpc_ids:
        #     vpcs = ec2_client.describe_vpcs(VpcIds=vpc_ids)
        #     for vpc in vpcs["Vpcs"]:
        #         vpc_tags[vpc["VpcId"]] = vpc.get("Tags", [])
        #
        # for ng in nat_gateways:
        #     nat_id = ng["NatGatewayId"]
        #     vpc_id = ng["VpcId"]
        #     tags = ng.get("Tags", [])
        #     name = self.get_resource_name(tags)
        #
        #     # Step 3: Check CloudWatch for bytes processed (detect unused)
        #     end_time = datetime.now(timezone.utc)
        #     start_time = end_time - timedelta(days=7)
        #
        #     bytes_out = cw_client.get_metric_statistics(
        #         Namespace="AWS/NATGateway",
        #         MetricName="BytesOutToDestination",
        #         Dimensions=[
        #             {"Name": "NatGatewayId", "Value": nat_id},
        #         ],
        #         StartTime=start_time,
        #         EndTime=end_time,
        #         Period=86400 * 7,  # 7-day aggregate
        #         Statistics=["Sum"],
        #     )
        #
        #     total_bytes = sum(
        #         dp["Sum"] for dp in bytes_out.get("Datapoints", [])
        #     )
        #     total_gb = total_bytes / (1024 ** 3)
        #
        #     # Step 4a: Flag completely unused NAT Gateways
        #     if total_bytes == 0:
        #         results.append(CheckResult(
        #             check_name=self.name,
        #             resource_type="NAT Gateway",
        #             resource_id=nat_id,
        #             resource_name=name or f"VPC: {vpc_id}",
        #             current_monthly_cost=NAT_GATEWAY_MONTHLY_FIXED,
        #             recommended_action="Delete — 0 bytes processed in 7 days",
        #             estimated_monthly_savings=NAT_GATEWAY_MONTHLY_FIXED,
        #             severity="high",
        #             details={
        #                 "vpc_id": vpc_id,
        #                 "bytes_processed_7d": 0,
        #                 "reason": "unused",
        #             },
        #         ))
        #         continue
        #
        #     # Step 4b: Check if NAT Gateway is in a non-production environment
        #     # Use VPC tags and NAT Gateway tags to determine environment
        #     all_tags = tags + vpc_tags.get(vpc_id, [])
        #     is_prod = self.is_production(all_tags, name)
        #
        #     if not is_prod:
        #         # Estimate total monthly cost including data processing
        #         # Extrapolate 7-day data to monthly
        #         monthly_gb = total_gb * (30 / 7)
        #         data_cost = monthly_gb * NAT_GATEWAY_PER_GB_COST
        #         total_monthly = NAT_GATEWAY_MONTHLY_FIXED + data_cost
        #
        #         # NAT Instance alternative: fixed cost only (data is free)
        #         savings = total_monthly - NAT_INSTANCE_MONTHLY_COST
        #
        #         if savings > 0:
        #             results.append(CheckResult(
        #                 check_name=self.name,
        #                 resource_type="NAT Gateway",
        #                 resource_id=nat_id,
        #                 resource_name=name or f"VPC: {vpc_id}",
        #                 current_monthly_cost=total_monthly,
        #                 recommended_action=(
        #                     f"Replace with NAT Instance (t3.nano) — "
        #                     f"non-prod VPC, {monthly_gb:.1f} GB/month"
        #                 ),
        #                 estimated_monthly_savings=savings,
        #                 severity="medium",
        #                 details={
        #                     "vpc_id": vpc_id,
        #                     "monthly_data_gb": round(monthly_gb, 2),
        #                     "fixed_cost": NAT_GATEWAY_MONTHLY_FIXED,
        #                     "data_processing_cost": round(data_cost, 2),
        #                     "nat_instance_cost": NAT_INSTANCE_MONTHLY_COST,
        #                     "reason": "non_production",
        #                 },
        #             ))

        return results
