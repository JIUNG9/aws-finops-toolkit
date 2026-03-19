"""AWS cloud provider implementation."""

from __future__ import annotations

from typing import Any

import boto3

from finops.providers.base import CloudProvider, CloudResource, CostDataPoint, register_provider


class AWSProvider(CloudProvider):
    """AWS provider wrapping boto3."""

    name = "aws"

    async def test_connection(self, config: dict) -> bool:
        try:
            session = boto3.Session(
                profile_name=config.get("profile"),
                region_name=config.get("region", "us-east-1"),
            )
            sts = session.client("sts")
            sts.get_caller_identity()
            return True
        except Exception:
            return False

    async def get_session(self, config: dict) -> Any:
        return boto3.Session(
            profile_name=config.get("profile"),
            region_name=config.get("region", "us-east-1"),
        )

    async def list_resources(self, session: Any, resource_type: str, region: str) -> list[CloudResource]:
        resources = []
        if resource_type == "ec2":
            ec2 = session.client("ec2", region_name=region)
            paginator = ec2.get_paginator("describe_instances")
            for page in paginator.paginate():
                for reservation in page["Reservations"]:
                    for inst in reservation["Instances"]:
                        tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                        resources.append(CloudResource(
                            provider="aws",
                            resource_type="ec2",
                            resource_id=inst["InstanceId"],
                            resource_name=tags.get("Name", inst["InstanceId"]),
                            region=region,
                            tags=tags,
                            details={"instance_type": inst["InstanceType"], "state": inst["State"]["Name"]},
                        ))
        return resources

    async def get_metrics(self, session: Any, resource_id: str, metric_name: str,
                          period_days: int = 14) -> list[dict]:
        from datetime import datetime, timezone, timedelta
        cw = session.client("cloudwatch")
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=period_days)
        response = cw.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName=metric_name,
            Dimensions=[{"Name": "InstanceId", "Value": resource_id}],
            StartTime=start,
            EndTime=end,
            Period=3600,
            Statistics=["Average"],
        )
        return [{"timestamp": dp["Timestamp"].isoformat(), "value": dp["Average"]}
                for dp in response.get("Datapoints", [])]

    async def get_cost_data(self, session: Any, start_date: str, end_date: str,
                            granularity: str = "DAILY") -> list[CostDataPoint]:
        ce = session.client("ce")
        response = ce.get_cost_and_usage(
            TimePeriod={"Start": start_date, "End": end_date},
            Granularity=granularity,
            Metrics=["BlendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        points = []
        for result in response.get("ResultsByTime", []):
            date = result["TimePeriod"]["Start"]
            for group in result.get("Groups", []):
                points.append(CostDataPoint(
                    date=date,
                    amount=float(group["Metrics"]["BlendedCost"]["Amount"]),
                    service=group["Keys"][0],
                ))
        return points

    def get_supported_checks(self) -> list[str]:
        return [
            "ec2_rightsizing", "nat_gateway", "spot_candidates", "unused_resources",
            "reserved_instances", "elasticache_scheduling", "rds_rightsizing",
            "vpc_waste", "cloudwatch_waste", "s3_lifecycle",
        ]


# Register on import
register_provider("aws", AWSProvider)
