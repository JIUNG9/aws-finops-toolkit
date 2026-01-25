"""Reserved Instance Recommendations — Calculate RI and Savings Plans ROI.

For instances running 24/7 in production, Reserved Instances (RIs) or
Savings Plans offer 30-40% savings over On-Demand pricing. This check
identifies always-on production instances and calculates the potential
savings from 1-year No Upfront commitments.

The check:
  1. Finds EC2 instances in production environments running 24/7
  2. Filters out instances already covered by RIs or Savings Plans
  3. Calculates savings for 1-year No Upfront RI vs On-Demand
  4. Also shows Compute Savings Plans comparison

Typical savings: 30-40% per committed instance.

AWS APIs used:
  - ec2:DescribeInstances
  - ec2:DescribeReservedInstances
  - savingsplans:DescribeSavingsPlans
  - pricing:GetProducts (for RI pricing)
"""

from __future__ import annotations

from typing import Any

from finops.checks.base import BaseCheck, CheckResult


# Approximate RI discount rates (1-year No Upfront, us-east-1, Linux)
# These are rough estimates; actual rates vary by instance type and region.
RI_1YR_NO_UPFRONT_DISCOUNT: dict[str, float] = {
    "t3": 0.28,     # ~28% savings
    "m5": 0.33,     # ~33% savings
    "m6i": 0.33,
    "c5": 0.33,
    "c6i": 0.33,
    "r5": 0.33,
    "r6i": 0.33,
    "m5a": 0.33,
    "c5a": 0.33,
}

# Compute Savings Plans discount (1-year No Upfront)
# More flexible than RIs but slightly lower discount
SAVINGS_PLAN_1YR_DISCOUNT = 0.28  # ~28% average

DEFAULT_RI_DISCOUNT = 0.30

HOURS_PER_MONTH = 730


class ReservedInstancesCheck(BaseCheck):
    """Find production On-Demand instances that should have RI or Savings Plans coverage."""

    name = "reserved_instances"
    description = "Recommend Reserved Instances or Savings Plans for always-on production workloads"

    def run(self, session: Any, region: str) -> list[CheckResult]:
        """Execute Reserved Instance recommendation check.

        Args:
            session: Authenticated boto3.Session.
            region: AWS region to scan.

        Returns:
            List of CheckResult for uncovered production instances.
        """
        results: list[CheckResult] = []

        # TODO: Uncomment and implement with real boto3 calls
        #
        # ec2_client = session.client("ec2", region_name=region)
        #
        # # Step 1: Get existing RI coverage to avoid duplicate recommendations
        # existing_ris = self._get_existing_ri_coverage(ec2_client)
        #
        # # Step 2: Get existing Savings Plans coverage
        # # savings_plans_coverage = self._get_savings_plans_coverage(session, region)
        #
        # # Step 3: Find running production instances
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
        #             # Only recommend RIs for production instances
        #             if not self.is_production(tags, name):
        #                 continue
        #
        #             # Skip instances already covered by RIs
        #             # (Check by matching instance type and AZ)
        #             az = instance["Placement"]["AvailabilityZone"]
        #             ri_key = f"{instance_type}:{az}"
        #             if ri_key in existing_ris:
        #                 # Decrement coverage count
        #                 existing_ris[ri_key] -= 1
        #                 if existing_ris[ri_key] <= 0:
        #                     del existing_ris[ri_key]
        #                 continue
        #
        #             # Step 4: Calculate savings
        #             on_demand_monthly = self._estimate_monthly_cost(instance_type)
        #             if on_demand_monthly == 0:
        #                 continue
        #
        #             ri_discount = self._get_ri_discount(instance_type)
        #             ri_savings = on_demand_monthly * ri_discount
        #             sp_savings = on_demand_monthly * SAVINGS_PLAN_1YR_DISCOUNT
        #
        #             # Choose the better recommendation
        #             if ri_discount >= SAVINGS_PLAN_1YR_DISCOUNT:
        #                 action = (
        #                     f"Purchase 1-year No Upfront RI — "
        #                     f"{instance_type} in {az} "
        #                     f"(~{ri_discount*100:.0f}% savings vs On-Demand)"
        #                 )
        #                 savings = ri_savings
        #             else:
        #                 action = (
        #                     f"Purchase Compute Savings Plan — "
        #                     f"{instance_type} "
        #                     f"(~{SAVINGS_PLAN_1YR_DISCOUNT*100:.0f}% savings, more flexible than RI)"
        #                 )
        #                 savings = sp_savings
        #
        #             results.append(CheckResult(
        #                 check_name=self.name,
        #                 resource_type="EC2 Instance (On-Demand)",
        #                 resource_id=instance_id,
        #                 resource_name=name,
        #                 current_monthly_cost=on_demand_monthly,
        #                 recommended_action=action,
        #                 estimated_monthly_savings=savings,
        #                 severity="medium",
        #                 details={
        #                     "instance_type": instance_type,
        #                     "availability_zone": az,
        #                     "ri_1yr_discount": ri_discount,
        #                     "savings_plan_discount": SAVINGS_PLAN_1YR_DISCOUNT,
        #                     "ri_monthly_savings": round(ri_savings, 2),
        #                     "sp_monthly_savings": round(sp_savings, 2),
        #                 },
        #             ))

        return results

    def _get_existing_ri_coverage(self, ec2_client: Any) -> dict[str, int]:
        """Get existing active Reserved Instance coverage.

        Returns a dict mapping "instance_type:az" to count of active RIs.
        This is used to avoid recommending RIs for already-covered instances.

        Args:
            ec2_client: boto3 EC2 client.

        Returns:
            Dict of RI coverage keyed by "type:az".
        """
        coverage: dict[str, int] = {}

        # TODO: Implement
        # response = ec2_client.describe_reserved_instances(
        #     Filters=[{"Name": "state", "Values": ["active"]}]
        # )
        # for ri in response["ReservedInstances"]:
        #     instance_type = ri["InstanceType"]
        #     az = ri.get("AvailabilityZone", "")  # Regional RIs have no AZ
        #     count = ri["InstanceCount"]
        #     key = f"{instance_type}:{az}" if az else instance_type
        #     coverage[key] = coverage.get(key, 0) + count

        return coverage

    def _get_ri_discount(self, instance_type: str) -> float:
        """Get estimated RI discount for an instance type family.

        Args:
            instance_type: EC2 instance type (e.g., "m5.xlarge").

        Returns:
            Discount as a fraction (e.g., 0.33 = 33% savings).
        """
        family = instance_type.split(".")[0] if "." in instance_type else instance_type
        return RI_1YR_NO_UPFRONT_DISCOUNT.get(family, DEFAULT_RI_DISCOUNT)

    def _estimate_monthly_cost(self, instance_type: str) -> float:
        """Estimate monthly On-Demand cost for an instance type.

        Args:
            instance_type: EC2 instance type.

        Returns:
            Estimated monthly cost in USD.
        """
        from finops.checks.ec2_rightsizing import APPROX_HOURLY_PRICING

        hourly = APPROX_HOURLY_PRICING.get(instance_type)
        if hourly is None:
            return 0.0
        return hourly * HOURS_PER_MONTH
