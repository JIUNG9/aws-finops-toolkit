"""Real behaviour tests for the stopped-instance part of the unused_resources check.

Moto supplies instances, volumes and tags. It stamps the stop time as "now", so
under moto the threshold is 0 days. The age cut-off, the timestamp parsing and the
paginators are tested with botocore's Stubber, which uses AWS's "GMT" wording.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber
from moto import mock_aws

from finops.checks.unused_resources import (
    EBS_GP3_PER_GB_MONTH,
    EBS_ST1_PER_GB_MONTH,
    UnusedResourcesCheck,
)
from finops.config import FinOpsConfig

REGION = "us-east-1"
AZ = "us-east-1a"
STOPPED_FILTER = [{"Name": "instance-state-name", "Values": ["stopped"]}]


def _check(days: int = 7) -> UnusedResourcesCheck:
    config = FinOpsConfig()
    config.thresholds["stopped_instance_days"] = days
    return UnusedResourcesCheck(config)


def _scan(check: UnusedResourcesCheck) -> list[Any]:
    return check._check_stopped_instances(boto3.Session(region_name=REGION), REGION)


@pytest.fixture
def ec2() -> Any:
    with mock_aws():
        yield boto3.client("ec2", region_name=REGION)


def _stopped_instance(ec2: Any, **kwargs: Any) -> str:
    instance_id = ec2.run_instances(
        ImageId="ami-12c6146b", MinCount=1, MaxCount=1, InstanceType="t3.micro", **kwargs
    )["Instances"][0]["InstanceId"]
    ec2.stop_instances(InstanceIds=[instance_id])
    return instance_id


def test_stopped_instance_is_flagged_with_volume_cost(ec2: Any) -> None:
    instance_id = _stopped_instance(
        ec2, TagSpecifications=[{"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "old-bastion"}]}]
    )
    volume = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0][
        "BlockDeviceMappings"
    ][0]["Ebs"]["VolumeId"]
    size = ec2.describe_volumes(VolumeIds=[volume])["Volumes"][0]["Size"]
    volume_type = ec2.describe_volumes(VolumeIds=[volume])["Volumes"][0]["VolumeType"]
    assert volume_type == "gp2"

    findings = _scan(_check(days=0))

    assert len(findings) == 1
    f = findings[0]
    assert f.resource_id == instance_id
    assert f.resource_type == "EC2 Instance (stopped)"
    assert f.resource_name == "old-bastion"
    assert f.current_monthly_cost == pytest.approx(size * 0.10)
    assert f.estimated_monthly_savings == f.current_monthly_cost
    assert f.details["volume_ids"] == [volume]
    assert f.details["sub_check"] == "stopped_instance"


def test_recently_stopped_instance_is_not_flagged(ec2: Any) -> None:
    _stopped_instance(ec2)

    assert _scan(_check(days=7)) == []


def test_running_instance_is_not_flagged(ec2: Any) -> None:
    ec2.run_instances(ImageId="ami-12c6146b", MinCount=1, MaxCount=1)

    assert _scan(_check(days=0)) == []


class _SessionWithClient:
    """Hands a pre-built (stubbed) ec2 client to the check."""

    def __init__(self, ec2_client: Any) -> None:
        self._ec2 = ec2_client

    def client(self, name: str, **kwargs: Any) -> Any:
        assert name == "ec2", f"unexpected client requested: {name}"
        return self._ec2


def _reason(days_ago: int) -> str:
    when = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=1)
    return f"User initiated ({when:%Y-%m-%d %H:%M:%S} GMT)"


def _instance(instance_id: str, reason: str, volume_ids: list[str]) -> dict[str, Any]:
    return {
        "InstanceId": instance_id,
        "InstanceType": "m5.large",
        "StateTransitionReason": reason,
        "BlockDeviceMappings": [
            {"DeviceName": f"/dev/sd{i}", "Ebs": {"VolumeId": v}} for i, v in enumerate(volume_ids)
        ],
    }


def test_age_cutoff_volume_pricing_and_pagination_with_stubbed_pages() -> None:
    ec2 = boto3.client("ec2", region_name=REGION, aws_access_key_id="x", aws_secret_access_key="y")
    with Stubber(ec2) as stub:
        stub.add_response(
            "describe_instances",
            {
                "Reservations": [
                    {"Instances": [_instance("i-old", _reason(30), ["vol-1", "vol-2"])]},
                    {"Instances": [_instance("i-new", _reason(3), ["vol-3"])]},
                ],
                "NextToken": "p2",
            },
            {"Filters": STOPPED_FILTER},
        )
        stub.add_response(
            "describe_volumes",
            {
                "Volumes": [
                    {"VolumeId": "vol-1", "Size": 100, "VolumeType": "gp3"},
                    {"VolumeId": "vol-2", "Size": 500, "VolumeType": "st1"},
                ]
            },
            {"VolumeIds": ["vol-1", "vol-2"]},
        )
        stub.add_response(
            "describe_instances",
            {"Reservations": [{"Instances": [_instance("i-older", _reason(8), ["vol-4"])]}]},
            {"Filters": STOPPED_FILTER, "NextToken": "p2"},
        )
        stub.add_response(
            "describe_volumes",
            {"Volumes": [{"VolumeId": "vol-4", "Size": 10, "VolumeType": "gp3"}]},
            {"VolumeIds": ["vol-4"]},
        )
        results = _check(days=7)._check_stopped_instances(_SessionWithClient(ec2), REGION)
        stub.assert_no_pending_responses()

    assert [r.resource_id for r in results] == ["i-old", "i-older"]
    assert results[0].current_monthly_cost == pytest.approx(
        100 * EBS_GP3_PER_GB_MONTH + 500 * EBS_ST1_PER_GB_MONTH
    )
    assert results[0].details["stopped_days"] == 30
    assert results[0].severity == "low"  # $30.50/month


@pytest.mark.parametrize(
    "reason", ["", "Client.UserInitiatedShutdown: User initiated shutdown", "User initiated"]
)
def test_instance_without_a_stop_timestamp_is_skipped(reason: str) -> None:
    ec2 = boto3.client("ec2", region_name=REGION, aws_access_key_id="x", aws_secret_access_key="y")
    with Stubber(ec2) as stub:
        stub.add_response(
            "describe_instances",
            {"Reservations": [{"Instances": [_instance("i-1", reason, ["vol-1"])]}]},
            {"Filters": STOPPED_FILTER},
        )
        results = _check(days=0)._check_stopped_instances(_SessionWithClient(ec2), REGION)
        stub.assert_no_pending_responses()

    assert results == []
