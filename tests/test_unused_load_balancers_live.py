"""Real behaviour tests for the idle load balancer part of the unused_resources check.

Moto supplies the load balancers. CloudWatch is stubbed with the request count each
scenario needs, as in the NAT Gateway tests. Moto stamps CreatedTime as "now", so
tests that need an old load balancer use idle_lb_days=0, and the age cut-off is tested
with botocore's Stubber.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import boto3
import pytest
from botocore.stub import Stubber
from moto import mock_aws

from finops.checks.unused_resources import LB_MONTHLY_FIXED, UnusedResourcesCheck
from finops.config import FinOpsConfig

REGION = "us-east-1"


def _check(idle_days: int = 0) -> UnusedResourcesCheck:
    config = FinOpsConfig()
    config.thresholds["idle_lb_days"] = idle_days
    return UnusedResourcesCheck(config)


class _SessionWithFakeCloudWatch:
    """Real moto session, but `cloudwatch` answers from a {arn suffix: sum} map."""

    def __init__(self, session: boto3.Session, sums: dict[str, float]) -> None:
        self._session = session
        self.cw = MagicMock()
        self.cw.get_metric_statistics.side_effect = self._answer
        self._sums = sums

    def _answer(self, **kwargs: Any) -> dict[str, Any]:
        suffix = kwargs["Dimensions"][0]["Value"]
        total = self._sums.get(suffix)
        return {"Datapoints": [] if total is None else [{"Sum": total}]}

    def client(self, name: str, **kwargs: Any) -> Any:
        if name == "cloudwatch":
            return self.cw
        return self._session.client(name, **kwargs)


@pytest.fixture
def elbv2() -> Any:
    with mock_aws():
        ec2 = boto3.client("ec2", region_name=REGION)
        vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
        subnets = [
            ec2.create_subnet(VpcId=vpc, CidrBlock=cidr, AvailabilityZone=az)["Subnet"]["SubnetId"]
            for cidr, az in (("10.0.1.0/24", "us-east-1a"), ("10.0.2.0/24", "us-east-1b"))
        ]
        client = boto3.client("elbv2", region_name=REGION)
        client.test_subnets = subnets  # type: ignore[attr-defined]
        yield client


def _lb(elbv2: Any, name: str, lb_type: str = "application") -> str:
    """Create a load balancer; returns the CloudWatch dimension value (ARN tail)."""
    arn = elbv2.create_load_balancer(
        Name=name, Subnets=elbv2.test_subnets, Type=lb_type
    )["LoadBalancers"][0]["LoadBalancerArn"]
    return "/".join(arn.split("/")[-3:])


def _scan(check: UnusedResourcesCheck, sums: dict[str, float]) -> tuple[list[Any], Any]:
    session = _SessionWithFakeCloudWatch(boto3.Session(region_name=REGION), sums)
    return check._check_idle_load_balancers(session, REGION), session.cw


def test_alb_without_requests_is_flagged(elbv2: Any) -> None:
    suffix = _lb(elbv2, "orders-alb")

    findings, _ = _scan(_check(), {suffix: 0.0})

    assert len(findings) == 1
    f = findings[0]
    assert f.resource_type == "ALB"
    assert f.resource_name == "orders-alb"
    assert f.resource_id.startswith("arn:aws:elasticloadbalancing:")
    assert f.current_monthly_cost == pytest.approx(LB_MONTHLY_FIXED)
    assert f.estimated_monthly_savings == f.current_monthly_cost
    assert f.details["metric"] == "RequestCount"
    assert f.details["cost_is_fixed_charge_only"] is True


def test_missing_datapoints_count_as_idle(elbv2: Any) -> None:
    """CloudWatch publishes RequestCount only while requests flow."""
    _lb(elbv2, "quiet-alb")

    findings, _ = _scan(_check(), {})

    assert [f.resource_name for f in findings] == ["quiet-alb"]


def test_alb_with_requests_is_not_flagged(elbv2: Any) -> None:
    busy = _lb(elbv2, "busy-alb")
    idle = _lb(elbv2, "idle-alb")

    findings, _ = _scan(_check(), {busy: 1200.0, idle: 0.0})

    assert [f.resource_name for f in findings] == ["idle-alb"]


def test_nlb_uses_its_own_namespace_and_metric(elbv2: Any) -> None:
    suffix = _lb(elbv2, "edge-nlb", lb_type="network")

    findings, cw = _scan(_check(), {suffix: 0.0})

    assert [(f.resource_type, f.details["metric"]) for f in findings] == [("NLB", "NewFlowCount")]
    kwargs = cw.get_metric_statistics.call_args.kwargs
    assert kwargs["Namespace"] == "AWS/NetworkELB"
    assert kwargs["MetricName"] == "NewFlowCount"
    assert kwargs["Dimensions"] == [{"Name": "LoadBalancer", "Value": suffix}]


def test_gateway_load_balancers_are_skipped(elbv2: Any) -> None:
    _lb(elbv2, "inspect-gwlb", lb_type="gateway")

    findings, cw = _scan(_check(), {})

    assert findings == []
    cw.get_metric_statistics.assert_not_called()


def test_no_load_balancers_returns_empty(elbv2: Any) -> None:
    findings, _ = _scan(_check(), {})

    assert findings == []


class _SessionWithClients:
    """Hands pre-built (stubbed) elbv2 and cloudwatch clients to the check."""

    def __init__(self, elbv2_client: Any, cw_client: Any) -> None:
        self._clients = {"elbv2": elbv2_client, "cloudwatch": cw_client}

    def client(self, name: str, **kwargs: Any) -> Any:
        return self._clients[name]


def _lb_desc(name: str, days_old: int) -> dict[str, Any]:
    return {
        "LoadBalancerArn": (
            f"arn:aws:elasticloadbalancing:{REGION}:123456789012:loadbalancer/app/{name}/0123456789abcdef"
        ),
        "LoadBalancerName": name,
        "Type": "application",
        "CreatedTime": datetime.now(timezone.utc) - timedelta(days=days_old),
    }


def test_young_load_balancer_is_skipped_and_pages_are_walked() -> None:
    creds = {"aws_access_key_id": "x", "aws_secret_access_key": "y"}
    elbv2 = boto3.client("elbv2", region_name=REGION, **creds)
    cw = MagicMock()
    cw.get_metric_statistics.return_value = {"Datapoints": []}
    with Stubber(elbv2) as stub:
        stub.add_response(
            "describe_load_balancers",
            {"LoadBalancers": [_lb_desc("old-one", 30), _lb_desc("just-made", 6)], "NextMarker": "p2"},
            {},
        )
        stub.add_response(
            "describe_load_balancers",
            {"LoadBalancers": [_lb_desc("old-two", 8)]},
            {"Marker": "p2"},
        )
        results = _check(idle_days=7)._check_idle_load_balancers(
            _SessionWithClients(elbv2, cw), REGION
        )
        stub.assert_no_pending_responses()

    assert [r.resource_name for r in results] == ["old-one", "old-two"]
    kwargs = cw.get_metric_statistics.call_args.kwargs
    assert kwargs["Period"] == 86400 * 7
    assert kwargs["Dimensions"] == [{"Name": "LoadBalancer", "Value": "app/old-two/0123456789abcdef"}]
