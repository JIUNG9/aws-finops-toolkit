"""Real behaviour tests for the unused-EIP part of the unused_resources check.

Every test builds real addresses, instances and ENIs in moto and asserts on the
findings. DescribeAddresses has no paginator, so there's nothing to stub here.
"""

from __future__ import annotations

from typing import Any

import boto3
import pytest
from moto import mock_aws

from finops.checks.unused_resources import EIP_MONTHLY_COST, UnusedResourcesCheck
from finops.config import FinOpsConfig

REGION = "us-east-1"


@pytest.fixture
def check() -> UnusedResourcesCheck:
    return UnusedResourcesCheck(FinOpsConfig())


def _eips(results: list[Any]) -> list[Any]:
    return [r for r in results if r.details.get("sub_check") == "unused_eip"]


def _scan(check: UnusedResourcesCheck) -> list[Any]:
    return _eips(check.run(boto3.Session(region_name=REGION), REGION))


@mock_aws
def test_unassociated_eip_is_flagged_with_flat_cost(check: UnusedResourcesCheck) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    addr = ec2.allocate_address(Domain="vpc")

    findings = _scan(check)

    assert len(findings) == 1
    f = findings[0]
    assert f.resource_id == addr["AllocationId"]
    assert f.details["public_ip"] == addr["PublicIp"]
    assert f.current_monthly_cost == EIP_MONTHLY_COST
    assert f.estimated_monthly_savings == EIP_MONTHLY_COST
    assert f.severity == "low"
    assert f.resource_type == "Elastic IP"


@mock_aws
def test_eip_attached_to_instance_is_not_flagged(check: UnusedResourcesCheck) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    inst = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)["Instances"][0]
    addr = ec2.allocate_address(Domain="vpc")
    ec2.associate_address(AllocationId=addr["AllocationId"], InstanceId=inst["InstanceId"])

    assert _scan(check) == []


@mock_aws
def test_eip_attached_to_eni_only_is_not_flagged(check: UnusedResourcesCheck) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
    eni = ec2.create_network_interface(SubnetId=subnet)["NetworkInterface"]["NetworkInterfaceId"]
    addr = ec2.allocate_address(Domain="vpc")
    ec2.associate_address(AllocationId=addr["AllocationId"], NetworkInterfaceId=eni)

    assert _scan(check) == []


@mock_aws
def test_only_the_orphan_is_flagged_among_mixed_addresses(check: UnusedResourcesCheck) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    inst = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)["Instances"][0]
    used = ec2.allocate_address(Domain="vpc")
    ec2.associate_address(AllocationId=used["AllocationId"], InstanceId=inst["InstanceId"])
    orphan = ec2.allocate_address(Domain="vpc")

    findings = _scan(check)

    assert [f.resource_id for f in findings] == [orphan["AllocationId"]]


@mock_aws
def test_name_tag_used_else_public_ip(check: UnusedResourcesCheck) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    tagged = ec2.allocate_address(
        Domain="vpc",
        TagSpecifications=[{
            "ResourceType": "elastic-ip",
            "Tags": [{"Key": "Name", "Value": "old-bastion"}],
        }],
    )
    bare = ec2.allocate_address(Domain="vpc")

    by_id = {f.resource_id: f for f in _scan(check)}

    assert by_id[tagged["AllocationId"]].resource_name == "old-bastion"
    assert by_id[bare["AllocationId"]].resource_name == bare["PublicIp"]


@mock_aws
def test_no_addresses_returns_empty(check: UnusedResourcesCheck) -> None:
    assert _scan(check) == []


@mock_aws
def test_released_eip_stops_being_reported(check: UnusedResourcesCheck) -> None:
    ec2 = boto3.client("ec2", region_name=REGION)
    addr = ec2.allocate_address(Domain="vpc")
    assert len(_scan(check)) == 1

    ec2.release_address(AllocationId=addr["AllocationId"])

    assert _scan(check) == []
