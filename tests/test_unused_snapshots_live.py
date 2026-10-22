"""Real behaviour tests for the old-snapshot part of the unused_resources check.

Moto supplies real volumes, snapshots, AMIs and tags. Its account starts with
snapshots for its built-in AMIs, so findings are compared against that baseline. It stamps every snapshot's
StartTime as "now", so a 90-day-old snapshot can't be made there. Tests that need
age use threshold 0 under moto; the age cut-off itself is tested with botocore's
Stubber, which also walks the real paginator across two pages.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber
from moto import mock_aws

from finops.checks.unused_resources import SNAPSHOT_PER_GB_MONTH, UnusedResourcesCheck
from finops.config import FinOpsConfig

REGION = "us-east-1"
AZ = "us-east-1a"


def _check(age_days: int = 0) -> UnusedResourcesCheck:
    config = FinOpsConfig()
    config.thresholds["snapshot_age_days"] = age_days
    return UnusedResourcesCheck(config)


_baseline: set[str] = set()


@pytest.fixture
def ec2() -> Any:
    with mock_aws():
        client = boto3.client("ec2", region_name=REGION)
        _baseline.clear()
        _baseline.update(
            snap["SnapshotId"]
            for snap in client.describe_snapshots(OwnerIds=["self"])["Snapshots"]
        )
        yield client


def _scan(check: UnusedResourcesCheck) -> list[Any]:
    """Findings for snapshots the test made, not the ones moto starts with."""
    results = check._check_old_snapshots(boto3.Session(region_name=REGION), REGION)
    return [r for r in results if r.resource_id not in _baseline]


def _snapshot(ec2: Any, size: int = 20, **kwargs: Any) -> str:
    volume = ec2.create_volume(AvailabilityZone=AZ, Size=size)["VolumeId"]
    return ec2.create_snapshot(VolumeId=volume, **kwargs)["SnapshotId"]


def test_snapshot_past_threshold_is_flagged_with_size_based_cost(ec2: Any) -> None:
    snap_id = _snapshot(ec2, size=40, Description="nightly db copy")

    findings = _scan(_check())

    assert len(findings) == 1
    f = findings[0]
    assert f.resource_id == snap_id
    assert f.resource_type == "EBS Snapshot"
    assert f.resource_name == "nightly db copy"
    assert f.current_monthly_cost == pytest.approx(40 * SNAPSHOT_PER_GB_MONTH)
    assert f.estimated_monthly_savings == f.current_monthly_cost
    assert f.severity == "low"
    assert f.details["size_gb"] == 40
    assert f.details["cost_is_upper_bound"] is True


def test_large_snapshot_gets_medium_severity(ec2: Any) -> None:
    _snapshot(ec2, size=500)  # 500 GB * $0.05 = $25/month

    assert [f.severity for f in _scan(_check())] == ["medium"]


def test_young_snapshot_is_not_flagged(ec2: Any) -> None:
    _snapshot(ec2)

    assert _scan(_check(age_days=90)) == []


def test_name_tag_is_preferred_over_description(ec2: Any) -> None:
    _snapshot(
        ec2,
        Description="copy",
        TagSpecifications=[{
            "ResourceType": "snapshot",
            "Tags": [{"Key": "Name", "Value": "pre-upgrade"}],
        }],
    )

    assert [f.resource_name for f in _scan(_check())] == ["pre-upgrade"]


def _create_ami(ec2: Any) -> tuple[str, str]:
    """Image an instance; returns (image id, id of the snapshot behind it).

    Moto ignores a caller-supplied SnapshotId in RegisterImage and invents its own,
    so the AMI is made from an instance and the snapshot is read back from the image.
    """
    instance = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)["Instances"][0]
    image_id = ec2.create_image(InstanceId=instance["InstanceId"], Name="golden-image")["ImageId"]
    image = ec2.describe_images(ImageIds=[image_id])["Images"][0]
    return image_id, image["BlockDeviceMappings"][0]["Ebs"]["SnapshotId"]


def test_snapshot_backing_an_ami_is_not_flagged(ec2: Any) -> None:
    _image_id, in_ami = _create_ami(ec2)
    orphan = _snapshot(ec2)

    flagged = [f.resource_id for f in _scan(_check())]

    assert orphan in flagged
    assert in_ami not in flagged


def test_snapshot_is_reported_again_once_its_ami_is_deregistered(ec2: Any) -> None:
    image_id, snap_id = _create_ami(ec2)
    assert snap_id not in [f.resource_id for f in _scan(_check())]

    ec2.deregister_image(ImageId=image_id)

    assert snap_id in [f.resource_id for f in _scan(_check())]


def test_aws_backup_snapshots_are_not_flagged(ec2: Any) -> None:
    _snapshot(
        ec2,
        TagSpecifications=[{
            "ResourceType": "snapshot",
            "Tags": [{"Key": "aws:backup:source-resource", "Value": "vol-0abc"}],
        }],
    )
    _snapshot(ec2, Description="This is a backup created by AWS Backup job 1234")
    manual = _snapshot(ec2, Description="hand-made")

    assert [f.resource_id for f in _scan(_check())] == [manual]


def test_no_snapshots_returns_empty(ec2: Any) -> None:
    assert _scan(_check()) == []


class _SessionWithClient:
    """Hands a pre-built (stubbed) ec2 client to the check."""

    def __init__(self, ec2_client: Any) -> None:
        self._ec2 = ec2_client

    def client(self, name: str, **kwargs: Any) -> Any:
        assert name == "ec2", f"unexpected client requested: {name}"
        return self._ec2


def _snap(snap_id: str, days_old: int, size: int = 10) -> dict[str, Any]:
    return {
        "SnapshotId": snap_id,
        "VolumeSize": size,
        "State": "completed",
        "StartTime": datetime.now(timezone.utc) - timedelta(days=days_old),
        "Description": "",
        "Tags": [],
    }


def test_age_cutoff_and_pagination_with_stubbed_pages() -> None:
    ec2 = boto3.client("ec2", region_name=REGION, aws_access_key_id="x", aws_secret_access_key="y")
    with Stubber(ec2) as stub:
        stub.add_response("describe_images", {"Images": []}, {"Owners": ["self"]})
        stub.add_response(
            "describe_snapshots",
            {"Snapshots": [_snap("snap-old1", 200), _snap("snap-new", 89)], "NextToken": "p2"},
            {"OwnerIds": ["self"]},
        )
        stub.add_response(
            "describe_snapshots",
            {"Snapshots": [_snap("snap-old2", 91)]},
            {"OwnerIds": ["self"], "NextToken": "p2"},
        )
        results = _check(age_days=90)._check_old_snapshots(_SessionWithClient(ec2), REGION)
        stub.assert_no_pending_responses()

    ids = [r.resource_id for r in results]
    assert ids == ["snap-old1", "snap-old2"]
