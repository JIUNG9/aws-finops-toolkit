"""Real behaviour tests for the NAT Gateway check.

The existing suite asserted `isinstance(results, list)`, which passed while every
check returned an empty list. These use moto to stand up actual AWS resources and
assert on the findings that come back.

CloudWatch metrics are the one thing moto won't serve usefully for this check, so
the client is stubbed per-test with the byte count each scenario needs. Everything
else — NAT Gateways, VPCs, tags, pagination — is real moto.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws

from finops.checks.nat_gateway import (
    NAT_GATEWAY_MONTHLY_FIXED,
    NAT_INSTANCE_MONTHLY_COST,
    NATGatewayCheck,
)
from finops.config import FinOpsConfig

REGION = "us-east-1"


class _SessionWithFakeCloudWatch:
    """Real moto session, but `cloudwatch` returns a stub with canned datapoints."""

    def __init__(self, session: boto3.Session, bytes_out: float) -> None:
        self._session = session
        cw = MagicMock()
        cw.get_metric_statistics.return_value = {
            "Datapoints": [{"Sum": bytes_out}] if bytes_out is not None else []
        }
        self._cw = cw

    def client(self, name: str, **kwargs: Any) -> Any:
        if name == "cloudwatch":
            return self._cw
        return self._session.client(name, **kwargs)


def _make_nat(ec2: Any, *, vpc_tags: list[dict], nat_tags: list[dict]) -> str:
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")
    vpc_id = vpc["Vpc"]["VpcId"]
    if vpc_tags:
        ec2.create_tags(Resources=[vpc_id], Tags=vpc_tags)

    subnet = ec2.create_subnet(VpcId=vpc_id, CidrBlock="10.0.1.0/24")
    eip = ec2.allocate_address(Domain="vpc")
    nat = ec2.create_nat_gateway(
        SubnetId=subnet["Subnet"]["SubnetId"],
        AllocationId=eip["AllocationId"],
        TagSpecifications=(
            [{"ResourceType": "natgateway", "Tags": nat_tags}] if nat_tags else []
        ),
    )
    return nat["NatGateway"]["NatGatewayId"]


@pytest.fixture
def check() -> NATGatewayCheck:
    return NATGatewayCheck(FinOpsConfig())


@mock_aws
def test_unused_nat_gateway_is_flagged_for_deletion(check: NATGatewayCheck) -> None:
    """0 bytes over 7 days means nothing is routing through it — delete, don't downsize."""
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2", region_name=REGION)
    nat_id = _make_nat(
        ec2,
        vpc_tags=[{"Key": "Environment", "Value": "production"}],
        nat_tags=[{"Key": "Name", "Value": "prod-nat"}],
    )

    results = check.run(_SessionWithFakeCloudWatch(session, 0), REGION)

    assert len(results) == 1, f"expected one finding, got {results}"
    r = results[0]
    assert r.resource_id == nat_id
    assert "Delete" in r.recommended_action
    assert r.severity == "high"
    assert r.details["reason"] == "unused"
    # An unused gateway's whole fixed cost is recoverable.
    assert r.estimated_monthly_savings == pytest.approx(NAT_GATEWAY_MONTHLY_FIXED)


@mock_aws
def test_nonprod_nat_gateway_is_flagged_for_nat_instance(check: NATGatewayCheck) -> None:
    """A busy dev gateway shouldn't be deleted — it should be a cheaper NAT instance."""
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2", region_name=REGION)
    nat_id = _make_nat(
        ec2,
        vpc_tags=[{"Key": "Environment", "Value": "dev"}],
        nat_tags=[{"Key": "Name", "Value": "dev-nat"}],
    )

    seven_day_gb = 14.0
    results = check.run(
        _SessionWithFakeCloudWatch(session, seven_day_gb * (1024**3)), REGION
    )

    assert len(results) == 1
    r = results[0]
    assert r.resource_id == nat_id
    assert "NAT Instance" in r.recommended_action
    assert r.severity == "medium"
    assert r.details["reason"] == "non_production"
    # 14 GB over 7 days extrapolates to 60 GB/month.
    assert r.details["monthly_data_gb"] == pytest.approx(60.0, rel=0.01)
    # Savings is fixed + data cost, minus the t3.nano.
    assert r.estimated_monthly_savings == pytest.approx(
        r.current_monthly_cost - NAT_INSTANCE_MONTHLY_COST
    )
    assert r.current_monthly_cost > NAT_GATEWAY_MONTHLY_FIXED  # data cost included


@mock_aws
def test_busy_production_nat_gateway_is_not_flagged(check: NATGatewayCheck) -> None:
    """The check must stay quiet on prod traffic — a false positive here is an outage."""
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2", region_name=REGION)
    _make_nat(
        ec2,
        vpc_tags=[{"Key": "Environment", "Value": "production"}],
        nat_tags=[{"Key": "Name", "Value": "prod-egress"}],
    )

    results = check.run(_SessionWithFakeCloudWatch(session, 500 * (1024**3)), REGION)

    assert results == [], f"production gateway should not be flagged: {results}"


@mock_aws
def test_environment_detected_from_vpc_tags_when_nat_is_untagged(
    check: NATGatewayCheck,
) -> None:
    """NAT Gateways often carry no tags; the VPC's tags have to be consulted."""
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2", region_name=REGION)
    _make_nat(
        ec2,
        vpc_tags=[{"Key": "Environment", "Value": "staging"}],
        nat_tags=[],
    )

    results = check.run(_SessionWithFakeCloudWatch(session, 7 * (1024**3)), REGION)

    assert len(results) == 1
    assert results[0].details["reason"] == "non_production"


@mock_aws
def test_no_nat_gateways_yields_no_findings(check: NATGatewayCheck) -> None:
    session = boto3.Session(region_name=REGION)
    assert check.run(_SessionWithFakeCloudWatch(session, 0), REGION) == []


@mock_aws
def test_multiple_gateways_are_all_evaluated(check: NATGatewayCheck) -> None:
    """Exercises the paginator with more than one gateway in the account."""
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2", region_name=REGION)
    for env in ("dev", "staging", "production"):
        _make_nat(
            ec2,
            vpc_tags=[{"Key": "Environment", "Value": env}],
            nat_tags=[{"Key": "Name", "Value": f"{env}-nat"}],
        )

    # All idle, so every one is reported as unused regardless of environment.
    results = check.run(_SessionWithFakeCloudWatch(session, 0), REGION)

    assert len(results) == 3
    assert all(r.details["reason"] == "unused" for r in results)


@mock_aws
def test_missing_cloudwatch_datapoints_treated_as_unused(check: NATGatewayCheck) -> None:
    """An empty Datapoints list means no traffic was recorded, not unknown traffic."""
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2", region_name=REGION)
    _make_nat(
        ec2,
        vpc_tags=[{"Key": "Environment", "Value": "production"}],
        nat_tags=[],
    )

    results = check.run(_SessionWithFakeCloudWatch(session, None), REGION)

    assert len(results) == 1
    assert results[0].details["reason"] == "unused"
