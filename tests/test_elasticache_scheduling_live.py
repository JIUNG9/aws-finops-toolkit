"""Behaviour tests for the ElastiCache scheduling check.

moto serves real clusters, tags and ARNs. It doesn't model replication-group members
or tag-read failures, so those two cases use a small stub client.
"""

from __future__ import annotations

from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from finops.checks.elasticache_scheduling import (
    ELASTICACHE_NODE_PRICING,
    HOURS_PER_MONTH,
    ElastiCacheSchedulingCheck,
)
from finops.config import FinOpsConfig

REGION = "us-east-1"


@pytest.fixture
def check() -> ElastiCacheSchedulingCheck:
    return ElastiCacheSchedulingCheck(FinOpsConfig())


def _make(ec: Any, cid: str, env: str | None, engine: str = "redis",
          node_type: str = "cache.t3.medium", nodes: int = 1) -> None:
    ec.create_cache_cluster(
        CacheClusterId=cid,
        Engine=engine,
        CacheNodeType=node_type,
        NumCacheNodes=nodes,
        Tags=[{"Key": "Environment", "Value": env}] if env else [],
    )


@mock_aws
def test_non_prod_redis_cluster_is_flagged(check: ElastiCacheSchedulingCheck) -> None:
    session = boto3.Session(region_name=REGION)
    _make(session.client("elasticache"), "dev-cache", "dev")

    results = check.run(session, REGION)

    assert len(results) == 1
    r = results[0]
    assert r.resource_id == "dev-cache"
    monthly = ELASTICACHE_NODE_PRICING["cache.t3.medium"] * HOURS_PER_MONTH
    assert r.current_monthly_cost == pytest.approx(monthly)
    assert r.estimated_monthly_savings == pytest.approx(monthly * 0.5)
    # ElastiCache can't be stopped; the advice must not say it can.
    assert "snapshot" in r.recommended_action
    assert "stop" not in r.recommended_action.lower()


@mock_aws
def test_production_cluster_is_never_flagged(check: ElastiCacheSchedulingCheck) -> None:
    session = boto3.Session(region_name=REGION)
    ec = session.client("elasticache")
    _make(ec, "orders-cache", "production")
    _make(ec, "prod-sessions", None)  # prod only in the name

    assert check.run(session, REGION) == []


@mock_aws
def test_memcached_gets_serverless_advice_not_a_schedule(
    check: ElastiCacheSchedulingCheck,
) -> None:
    session = boto3.Session(region_name=REGION)
    _make(session.client("elasticache"), "stg-mc", "staging", engine="memcached", nodes=2)

    (r,) = check.run(session, REGION)

    assert "Serverless" in r.recommended_action
    assert r.details["num_nodes"] == 2


@mock_aws
def test_unknown_node_type_is_skipped_not_priced_at_zero(
    check: ElastiCacheSchedulingCheck,
) -> None:
    session = boto3.Session(region_name=REGION)
    _make(session.client("elasticache"), "dev-big", "dev", node_type="cache.r7g.16xlarge")

    assert check.run(session, REGION) == []


class _StubElastiCache:
    def __init__(self, clusters: list[dict], tags: dict[str, list[dict]],
                 fail_tags_for: set[str] | None = None) -> None:
        self._clusters = clusters
        self._tags = tags
        self._fail = fail_tags_for or set()

    def get_paginator(self, name: str) -> Any:
        assert name == "describe_cache_clusters"
        clusters = self._clusters

        class _P:
            def paginate(self, **_: Any) -> list[dict]:
                return [{"CacheClusters": clusters}]

        return _P()

    def list_tags_for_resource(self, ResourceName: str) -> dict:
        if ResourceName in self._fail:
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}},
                              "ListTagsForResource")
        return {"TagList": self._tags.get(ResourceName, [])}


class _StubSession:
    def __init__(self, ec: _StubElastiCache) -> None:
        self._ec = ec

    def client(self, name: str, **_: Any) -> _StubElastiCache:
        assert name == "elasticache"
        return self._ec


def _member(cid: str, group: str | None = "dev-rg") -> dict:
    return {
        "CacheClusterId": cid, "ARN": f"arn:{cid}", "Engine": "redis",
        "CacheNodeType": "cache.t3.medium", "NumCacheNodes": 1,
        "CacheClusterStatus": "available", "ReplicationGroupId": group,
    }


def test_replication_group_is_one_finding_with_summed_nodes(
    check: ElastiCacheSchedulingCheck,
) -> None:
    dev = [{"Key": "Environment", "Value": "dev"}]
    ec = _StubElastiCache(
        [_member("dev-rg-001"), _member("dev-rg-002"), _member("dev-rg-003")],
        {f"arn:dev-rg-00{i}": dev for i in (1, 2, 3)},
    )

    (r,) = check.run(_StubSession(ec), REGION)

    assert r.resource_id == "dev-rg"
    assert r.details["num_nodes"] == 3
    assert r.details["replication_group"] == "dev-rg"


def test_one_prod_member_protects_the_whole_group(check: ElastiCacheSchedulingCheck) -> None:
    ec = _StubElastiCache(
        [_member("rg-001", group="rg"), _member("rg-002", group="rg")],
        {"arn:rg-001": [{"Key": "Environment", "Value": "dev"}],
         "arn:rg-002": [{"Key": "Environment", "Value": "prod"}]},
    )

    assert check.run(_StubSession(ec), REGION) == []


def test_unreadable_tags_fail_closed(check: ElastiCacheSchedulingCheck) -> None:
    """AccessDenied on tags must not turn an unknown cluster into a 'dev' one."""
    ec = _StubElastiCache([_member("cache-1", group=None)], {}, fail_tags_for={"arn:cache-1"})

    assert check.run(_StubSession(ec), REGION) == []


def test_only_available_clusters_are_considered(check: ElastiCacheSchedulingCheck) -> None:
    m = _member("dev-1", group=None)
    m["CacheClusterStatus"] = "creating"
    ec = _StubElastiCache([m], {})

    assert check.run(_StubSession(ec), REGION) == []
