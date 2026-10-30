"""Real behaviour tests for the no-lifecycle-policy part of the s3_lifecycle check.

Moto supplies real buckets and lifecycle configurations. Bucket size comes from CloudWatch
(BucketSizeBytes), which S3 fills in on its own. Moto cannot stand in for that: it adds a
0-byte datapoint of its own to every bucket and averages it with whatever a test publishes,
which halves the size. The tests use a small CloudWatch fake that honours the metric,
dimensions and time window the check asks for.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from finops.checks.s3_lifecycle import S3_STANDARD_PER_GB, S3LifecycleCheck, _bucket_region
from finops.config import FinOpsConfig

REGION = "us-east-1"
GB = 1024 ** 3
LIFECYCLE = {
    "Rules": [{
        "ID": "expire-tmp",
        "Status": "Enabled",
        "Filter": {"Prefix": "tmp/"},
        "Expiration": {"Days": 7},
    }]
}


def _check(min_gb: float = 100) -> S3LifecycleCheck:
    config = FinOpsConfig()
    config.thresholds["s3_large_bucket_gb"] = min_gb
    return S3LifecycleCheck(config)


class _FakeCloudWatch:
    """Serves BucketSizeBytes datapoints per bucket, filtered to the requested window."""

    def __init__(self) -> None:
        self.sizes: dict[str, list[tuple[datetime, float]]] = {}

    def get_metric_statistics(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["Namespace"] == "AWS/S3"
        assert kwargs["MetricName"] == "BucketSizeBytes"
        dims = {d["Name"]: d["Value"] for d in kwargs["Dimensions"]}
        assert dims["StorageType"] == "StandardStorage"
        points = self.sizes.get(dims["BucketName"], [])
        return {
            "Datapoints": [
                {"Timestamp": ts, "Average": gb * GB, "Unit": "Bytes"}
                for ts, gb in points
                if kwargs["StartTime"] <= ts <= kwargs["EndTime"]
            ]
        }


class _Session:
    """Moto for S3, the fake for CloudWatch."""

    def __init__(self, cloudwatch: _FakeCloudWatch, region: str) -> None:
        self._cloudwatch = cloudwatch
        self._real = boto3.Session(region_name=region)

    def client(self, name: str, **kwargs: Any) -> Any:
        return self._cloudwatch if name == "cloudwatch" else self._real.client(name, **kwargs)


@pytest.fixture
def cloudwatch() -> _FakeCloudWatch:
    return _FakeCloudWatch()


def _bucket(
    cw: _FakeCloudWatch,
    name: str,
    size_gb: float | None,
    region: str = REGION,
    age_hours: int = 12,
) -> None:
    s3 = boto3.client("s3", region_name=region)
    if region == "us-east-1":
        s3.create_bucket(Bucket=name)
    else:
        s3.create_bucket(Bucket=name, CreateBucketConfiguration={"LocationConstraint": region})
    if size_gb is not None:
        when = datetime.now(timezone.utc) - timedelta(hours=age_hours)
        cw.sizes[name] = [(when, size_gb)]


def _scan(check: S3LifecycleCheck, cw: _FakeCloudWatch, region: str = REGION) -> list[Any]:
    return check._check_no_lifecycle_policy(_Session(cw, region), region)


@mock_aws
def test_large_bucket_without_lifecycle_is_flagged_with_modelled_savings(cloudwatch) -> None:
    _bucket(cloudwatch, "acme-logs", 1000)

    findings = _scan(_check(), cloudwatch)

    assert len(findings) == 1
    f = findings[0]
    assert f.resource_id == "acme-logs"
    assert f.resource_type == "S3 Bucket (no lifecycle)"
    assert f.current_monthly_cost == pytest.approx(1000 * S3_STANDARD_PER_GB)
    # 40% Standard, 35% IA, 25% Glacier IR: 1000 GB drops from $23.00 to $14.58
    assert f.details["cost_model"]["with_lifecycle"] == pytest.approx(14.575, abs=0.01)  # rounded to cents
    assert f.estimated_monthly_savings == pytest.approx(8.425)
    assert f.severity == "medium"
    assert f.details["bucket_size_gb"] == 1000
    assert f.details["sub_check"] == "no_lifecycle_policy"


@mock_aws
def test_severity_is_high_above_fifty_dollars_of_savings(cloudwatch) -> None:
    _bucket(cloudwatch, "acme-archive", 7000)  # ~$59/month saved

    assert [f.severity for f in _scan(_check(), cloudwatch)] == ["high"]


@mock_aws
def test_bucket_with_lifecycle_rules_is_not_flagged(cloudwatch) -> None:
    _bucket(cloudwatch, "acme-managed", 1000)
    boto3.client("s3", region_name=REGION).put_bucket_lifecycle_configuration(
        Bucket="acme-managed", LifecycleConfiguration=LIFECYCLE
    )

    assert _scan(_check(), cloudwatch) == []


@mock_aws
def test_bucket_below_size_threshold_is_not_flagged(cloudwatch) -> None:
    _bucket(cloudwatch, "acme-small", 99)

    assert _scan(_check(), cloudwatch) == []
    assert [f.resource_id for f in _scan(_check(min_gb=50), cloudwatch)] == ["acme-small"]


@mock_aws
def test_bucket_without_size_metric_is_skipped(cloudwatch) -> None:
    _bucket(cloudwatch, "acme-empty", None)

    assert _scan(_check(min_gb=0), cloudwatch) == []


@mock_aws
def test_zero_byte_bucket_is_skipped_even_with_a_zero_threshold(cloudwatch) -> None:
    _bucket(cloudwatch, "acme-zero", 0)

    assert _scan(_check(min_gb=0), cloudwatch) == []


@mock_aws
def test_size_metric_older_than_two_days_is_ignored(cloudwatch) -> None:
    _bucket(cloudwatch, "acme-stale", 1000, age_hours=72)

    assert _scan(_check(), cloudwatch) == []


@mock_aws
def test_only_buckets_in_the_scanned_region_are_flagged(cloudwatch) -> None:
    _bucket(cloudwatch, "acme-us", 1000)
    _bucket(cloudwatch, "acme-eu", 1000, region="eu-west-1")

    assert [f.resource_id for f in _scan(_check(), cloudwatch)] == ["acme-us"]
    assert [f.resource_id for f in _scan(_check(), cloudwatch, "eu-west-1")] == ["acme-eu"]


@mock_aws
def test_only_oversized_buckets_among_several_are_flagged(cloudwatch) -> None:
    _bucket(cloudwatch, "acme-a", 500)
    _bucket(cloudwatch, "acme-b", 10)
    _bucket(cloudwatch, "acme-c", 200)

    assert sorted(f.resource_id for f in _scan(_check(), cloudwatch)) == ["acme-a", "acme-c"]


@mock_aws
def test_access_denied_on_lifecycle_lookup_skips_the_bucket(
    cloudwatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bucket(cloudwatch, "acme-locked", 1000)
    session = _Session(cloudwatch, REGION)
    s3 = session.client("s3", region_name=REGION)

    def denied(**_: Any) -> None:
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "GetBucketLifecycle")

    monkeypatch.setattr(s3, "get_bucket_lifecycle_configuration", denied)

    class _Locked:
        def client(self, name: str, **kwargs: Any) -> Any:
            return s3 if name == "s3" else session.client(name, **kwargs)

    assert _check()._check_no_lifecycle_policy(_Locked(), REGION) == []


@mock_aws
def test_run_includes_the_finding(cloudwatch) -> None:
    _bucket(cloudwatch, "acme-logs", 1000)

    results = _check().run(_Session(cloudwatch, REGION), REGION)

    assert [r.resource_id for r in results if r.details["sub_check"] == "no_lifecycle_policy"] == [
        "acme-logs"
    ]


@pytest.mark.parametrize(
    "location,expected",
    [
        ({"LocationConstraint": None}, "us-east-1"),
        ({}, "us-east-1"),
        ({"LocationConstraint": "EU"}, "eu-west-1"),
        ({"LocationConstraint": "ap-southeast-2"}, "ap-southeast-2"),
    ],
)
def test_bucket_region_normalises_get_bucket_location(location: dict[str, Any], expected: str) -> None:
    assert _bucket_region(location) == expected
