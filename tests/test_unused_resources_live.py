"""Real behaviour tests for the unattached-EBS part of the unused_resources check.

These tests only look at EBS findings (filtered on sub_check). EIPs are covered in
test_unused_eip_live.py. Snapshots, idle load balancers and stopped instances are
still commented out and return nothing.

Most tests use moto for real volumes, attachments and tags. Two things moto can't do
for this check:

- It ignores MaxResults on DescribeVolumes and never returns a NextToken, so it can't
  exercise the paginator past one page.
- It stamps every volume's CreateTime as "now", so it can't produce an old volume.

The pagination test covers both with botocore's Stubber: two canned pages joined by a
NextToken, walked by botocore's real paginator, with a 45-day-old CreateTime.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber
from moto import mock_aws

from finops.checks.unused_resources import (
    EBS_GP2_PER_GB_MONTH,
    EBS_GP3_PER_GB_MONTH,
    EBS_IO1_PER_GB_MONTH,
    EBS_SC1_PER_GB_MONTH,
    EBS_ST1_PER_GB_MONTH,
    UnusedResourcesCheck,
)
from finops.config import FinOpsConfig

REGION = "us-east-1"
AZ = "us-east-1a"
AVAILABLE_FILTER = [{"Name": "status", "Values": ["available"]}]


class _SessionWithClient:
    """Hands a pre-built (stubbed) ec2 client to the check."""

    def __init__(self, ec2_client: Any) -> None:
        self._ec2 = ec2_client

    def client(self, name: str, **kwargs: Any) -> Any:
        assert name == "ec2", f"unexpected client requested: {name}"
        return self._ec2


@pytest.fixture
def check() -> UnusedResourcesCheck:
    # Grace period off: moto stamps every volume as created just now.
    config = FinOpsConfig()
    config.thresholds["unattached_volume_grace_days"] = 0
    return UnusedResourcesCheck(config)


def _ebs(results: list[Any]) -> list[Any]:
    return [r for r in results if r.details.get("sub_check") == "unattached_ebs"]


def _volume(ec2: Any, size: int, vol_type: str, name: str | None = None) -> str:
    kwargs: dict[str, Any] = {"AvailabilityZone": AZ, "Size": size, "VolumeType": vol_type}
    if vol_type in ("io1", "io2"):
        kwargs["Iops"] = 1000
    if name:
        kwargs["TagSpecifications"] = [
            {"ResourceType": "volume", "Tags": [{"Key": "Name", "Value": name}]}
        ]
    return ec2.create_volume(**kwargs)["VolumeId"]


@mock_aws
def test_unattached_volumes_priced_by_type(check: UnusedResourcesCheck) -> None:
    """gp3, gp2 and io1 each come back with the rate from their own price table."""
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2", region_name=REGION)
    gp3 = _volume(ec2, 100, "gp3")
    gp2 = _volume(ec2, 100, "gp2")
    io1 = _volume(ec2, 100, "io1")

    by_id = {r.resource_id: r for r in _ebs(check.run(session, REGION))}

    assert set(by_id) == {gp3, gp2, io1}
    assert by_id[gp3].current_monthly_cost == pytest.approx(100 * EBS_GP3_PER_GB_MONTH)
    assert by_id[gp2].current_monthly_cost == pytest.approx(100 * EBS_GP2_PER_GB_MONTH)
    assert by_id[io1].current_monthly_cost == pytest.approx(100 * EBS_IO1_PER_GB_MONTH)
    for r in by_id.values():
        # Deleting an unattached volume recovers its whole cost.
        assert r.estimated_monthly_savings == r.current_monthly_cost
        assert r.resource_type == "EBS Volume"
        assert r.recommended_action.startswith("Delete")
        assert r.details["age_days"] == 0  # moto stamps CreateTime as now


@mock_aws
def test_io2_uses_io1_rate(check: UnusedResourcesCheck) -> None:
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2", region_name=REGION)
    _volume(ec2, 200, "io2")

    [r] = _ebs(check.run(session, REGION))

    assert r.details["volume_type"] == "io2"
    assert r.current_monthly_cost == pytest.approx(200 * EBS_IO1_PER_GB_MONTH)


@mock_aws
def test_severity_turns_high_at_fifty_dollars(check: UnusedResourcesCheck) -> None:
    """500 GB gp3 is $40/mo (medium); 500 GB gp2 is $50/mo, which crosses into high."""
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2", region_name=REGION)
    gp3 = _volume(ec2, 500, "gp3")
    gp2 = _volume(ec2, 500, "gp2")

    by_id = {r.resource_id: r for r in _ebs(check.run(session, REGION))}

    assert by_id[gp3].current_monthly_cost == pytest.approx(40.0)
    assert by_id[gp3].severity == "medium"
    assert by_id[gp2].current_monthly_cost == pytest.approx(50.0)
    assert by_id[gp2].severity == "high"


@mock_aws
def test_attached_volumes_are_not_flagged(check: UnusedResourcesCheck) -> None:
    """Root volumes from a running instance and a manually attached data volume stay quiet."""
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2", region_name=REGION)
    image_id = ec2.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]
    instance = ec2.run_instances(
        ImageId=image_id, MinCount=1, MaxCount=1, Placement={"AvailabilityZone": AZ}
    )["Instances"][0]
    data_vol = _volume(ec2, 50, "gp3", name="attached-data")
    ec2.attach_volume(VolumeId=data_vol, InstanceId=instance["InstanceId"], Device="/dev/sdf")
    orphan = _volume(ec2, 20, "gp3", name="orphan")

    findings = _ebs(check.run(session, REGION))

    assert [r.resource_id for r in findings] == [orphan]


@mock_aws
def test_name_tag_is_used_and_untagged_is_unnamed(check: UnusedResourcesCheck) -> None:
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2", region_name=REGION)
    named = _volume(ec2, 10, "gp3", name="old-build-cache")
    untagged = _volume(ec2, 10, "gp3")

    by_id = {r.resource_id: r for r in _ebs(check.run(session, REGION))}

    assert by_id[named].resource_name == "old-build-cache"
    assert by_id[untagged].resource_name == "(unnamed)"


@mock_aws
def test_no_volumes_yields_no_findings(check: UnusedResourcesCheck) -> None:
    session = boto3.Session(region_name=REGION)
    assert check.run(session, REGION) == []


def test_paginates_past_first_page_and_reports_age(check: UnusedResourcesCheck) -> None:
    """Two pages joined by a NextToken: both get read, and the filter goes to the API."""
    session = boto3.Session(
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        region_name=REGION,
    )
    ec2 = session.client("ec2", region_name=REGION)
    created = datetime.now(timezone.utc) - timedelta(days=45)

    def vol(vol_id: str) -> dict[str, Any]:
        return {
            "VolumeId": vol_id,
            "Size": 100,
            "VolumeType": "gp2",
            "State": "available",
            "CreateTime": created,
            "AvailabilityZone": AZ,
        }

    stubber = Stubber(ec2)
    stubber.add_response(
        "describe_volumes",
        {"Volumes": [vol("vol-0000000000000001"), vol("vol-0000000000000002")], "NextToken": "page-2"},
        expected_params={"Filters": AVAILABLE_FILTER},
    )
    stubber.add_response(
        "describe_volumes",
        {"Volumes": [vol("vol-0000000000000003")]},
        expected_params={"Filters": AVAILABLE_FILTER, "NextToken": "page-2"},
    )

    with stubber:
        # Straight to the EBS sub-check: run() would also call DescribeAddresses on this
        # stubbed client, which has nothing queued for it.
        findings = _ebs(check._check_unattached_ebs(_SessionWithClient(ec2), REGION))
        stubber.assert_no_pending_responses()

    assert [r.resource_id for r in findings] == [
        "vol-0000000000000001",
        "vol-0000000000000002",
        "vol-0000000000000003",
    ]
    assert all(r.details["age_days"] == 45 for r in findings)
    assert "created 45 days ago" in findings[0].recommended_action


@mock_aws
def test_hdd_volumes_use_their_own_rates(check: UnusedResourcesCheck) -> None:
    """st1 and sc1 are far cheaper than the gp3 fallback they used to get."""
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2", region_name=REGION)
    st1 = _volume(ec2, 500, "st1")
    sc1 = _volume(ec2, 500, "sc1")

    by_id = {r.resource_id: r for r in _ebs(check.run(session, REGION))}

    assert by_id[st1].current_monthly_cost == pytest.approx(500 * EBS_ST1_PER_GB_MONTH)
    assert by_id[sc1].current_monthly_cost == pytest.approx(500 * EBS_SC1_PER_GB_MONTH)


def _stubbed_findings(created_days_ago: int, thresholds: dict[str, Any] | None = None) -> list[Any]:
    session = boto3.Session(
        aws_access_key_id="testing", aws_secret_access_key="testing", region_name=REGION
    )
    ec2 = session.client("ec2", region_name=REGION)
    config = FinOpsConfig()
    config.thresholds.update(thresholds or {})
    volume = {
        "VolumeId": "vol-0000000000000001",
        "Size": 100,
        "VolumeType": "gp3",
        "State": "available",
        "CreateTime": datetime.now(timezone.utc) - timedelta(days=created_days_ago),
        "AvailabilityZone": AZ,
    }
    stubber = Stubber(ec2)
    stubber.add_response("describe_volumes", {"Volumes": [volume]})
    with stubber:
        return _ebs(UnusedResourcesCheck(config)._check_unattached_ebs(_SessionWithClient(ec2), REGION))


def test_default_grace_skips_volumes_under_seven_days_old() -> None:
    assert _stubbed_findings(created_days_ago=3) == []


def test_default_grace_reports_volumes_seven_days_or_older() -> None:
    assert [r.resource_id for r in _stubbed_findings(created_days_ago=7)] == ["vol-0000000000000001"]


def test_grace_days_is_configurable() -> None:
    assert _stubbed_findings(created_days_ago=20, thresholds={"unattached_volume_grace_days": 30}) == []
    assert len(_stubbed_findings(created_days_ago=20, thresholds={"unattached_volume_grace_days": 14})) == 1
