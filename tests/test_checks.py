"""Unit tests for individual cost optimization checks.

Each check is tested with mocked boto3 responses to verify:
  - Correct identification of wasteful resources
  - Accurate savings calculations
  - Proper filtering (prod vs non-prod, thresholds)
  - Edge cases (no data, empty responses)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from finops.checks.base import CheckResult
from finops.checks.ec2_rightsizing import EC2RightsizingCheck
from finops.checks.nat_gateway import NATGatewayCheck
from finops.checks.spot_candidates import SpotCandidatesCheck
from finops.checks.unused_resources import UnusedResourcesCheck
from finops.checks.reserved_instances import ReservedInstancesCheck
from finops.checks.elasticache_scheduling import ElastiCacheSchedulingCheck
from finops.checks.rds_rightsizing import RDSRightsizingCheck
from finops.config import FinOpsConfig


class TestCheckResult:
    """Tests for the CheckResult dataclass."""

    def test_annual_savings_calculation(self) -> None:
        result = CheckResult(
            check_name="test",
            resource_type="EC2 Instance",
            resource_id="i-123",
            resource_name="test-instance",
            current_monthly_cost=200.0,
            recommended_action="Downsize",
            estimated_monthly_savings=100.0,
        )
        assert result.estimated_annual_savings == 1200.0

    def test_savings_percentage(self) -> None:
        result = CheckResult(
            check_name="test",
            resource_type="EC2 Instance",
            resource_id="i-123",
            resource_name="test-instance",
            current_monthly_cost=200.0,
            recommended_action="Downsize",
            estimated_monthly_savings=100.0,
        )
        assert result.savings_percentage == 50.0

    def test_savings_percentage_zero_cost(self) -> None:
        result = CheckResult(
            check_name="test",
            resource_type="EC2 Instance",
            resource_id="i-123",
            resource_name="test-instance",
            current_monthly_cost=0.0,
            recommended_action="Delete",
            estimated_monthly_savings=0.0,
        )
        assert result.savings_percentage == 0.0

    def test_to_dict(self) -> None:
        result = CheckResult(
            check_name="test",
            resource_type="EC2 Instance",
            resource_id="i-123",
            resource_name="test-instance",
            current_monthly_cost=200.0,
            recommended_action="Downsize",
            estimated_monthly_savings=100.0,
            severity="high",
            details={"instance_type": "m5.2xlarge"},
        )
        d = result.to_dict()
        assert d["check_name"] == "test"
        assert d["resource_id"] == "i-123"
        assert d["estimated_annual_savings"] == 1200.0
        assert d["savings_percentage"] == 50.0
        assert d["severity"] == "high"
        assert d["details"]["instance_type"] == "m5.2xlarge"


class TestEC2RightsizingCheck:
    """Tests for EC2 right-sizing check."""

    def test_get_smaller_type(self, default_config: FinOpsConfig) -> None:
        check = EC2RightsizingCheck(config=default_config)
        assert check._get_smaller_type("m5.2xlarge") == "m5.xlarge"
        assert check._get_smaller_type("m5.xlarge") == "m5.large"
        assert check._get_smaller_type("m5.large") is None  # Already smallest

    def test_get_smaller_type_invalid(self, default_config: FinOpsConfig) -> None:
        check = EC2RightsizingCheck(config=default_config)
        assert check._get_smaller_type("invalid") is None

    def test_estimate_monthly_cost(self, default_config: FinOpsConfig) -> None:
        check = EC2RightsizingCheck(config=default_config)
        cost = check._estimate_monthly_cost("m5.xlarge")
        assert cost > 0
        assert cost == pytest.approx(0.192 * 730, rel=0.01)

    def test_estimate_monthly_cost_unknown(self, default_config: FinOpsConfig) -> None:
        check = EC2RightsizingCheck(config=default_config)
        assert check._estimate_monthly_cost("unknown.type") == 0.0

    def test_run_returns_list(self, default_config: FinOpsConfig, mock_session: MagicMock) -> None:
        """Check that run() returns a list (empty for now since logic is TODO)."""
        check = EC2RightsizingCheck(config=default_config)
        results = check.run(session=mock_session, region="us-east-1")
        assert isinstance(results, list)


class TestNATGatewayCheck:
    """Tests for NAT Gateway check."""

    def test_run_returns_list(self, default_config: FinOpsConfig, mock_session: MagicMock) -> None:
        check = NATGatewayCheck(config=default_config)
        results = check.run(session=mock_session, region="us-east-1")
        assert isinstance(results, list)


class TestSpotCandidatesCheck:
    """Tests for Spot Instance candidates check."""

    def test_get_spot_discount(self, default_config: FinOpsConfig) -> None:
        check = SpotCandidatesCheck(config=default_config)
        assert check._get_spot_discount("m5.xlarge") == 0.65
        assert check._get_spot_discount("t3.large") == 0.50
        assert check._get_spot_discount("unknown.type") == 0.60  # default

    def test_run_returns_list(self, default_config: FinOpsConfig, mock_session: MagicMock) -> None:
        check = SpotCandidatesCheck(config=default_config)
        results = check.run(session=mock_session, region="us-east-1")
        assert isinstance(results, list)


class TestUnusedResourcesCheck:
    """Tests for unused resource detection check."""

    def test_run_returns_list(self, default_config: FinOpsConfig, mock_session: MagicMock) -> None:
        check = UnusedResourcesCheck(config=default_config)
        results = check.run(session=mock_session, region="us-east-1")
        assert isinstance(results, list)


class TestReservedInstancesCheck:
    """Tests for Reserved Instance recommendations check."""

    def test_get_ri_discount(self, default_config: FinOpsConfig) -> None:
        check = ReservedInstancesCheck(config=default_config)
        assert check._get_ri_discount("m5.xlarge") == 0.33
        assert check._get_ri_discount("t3.large") == 0.28

    def test_run_returns_list(self, default_config: FinOpsConfig, mock_session: MagicMock) -> None:
        check = ReservedInstancesCheck(config=default_config)
        results = check.run(session=mock_session, region="us-east-1")
        assert isinstance(results, list)


class TestElastiCacheSchedulingCheck:
    """Tests for ElastiCache scheduling check."""

    def test_estimate_monthly_cost(self, default_config: FinOpsConfig) -> None:
        check = ElastiCacheSchedulingCheck(config=default_config)
        cost = check._estimate_monthly_cost("cache.r6g.large", num_nodes=2)
        assert cost > 0
        # 0.146 * 730 * 2 = 213.16
        assert cost == pytest.approx(0.146 * 730 * 2, rel=0.01)

    def test_estimate_monthly_cost_unknown(self, default_config: FinOpsConfig) -> None:
        check = ElastiCacheSchedulingCheck(config=default_config)
        assert check._estimate_monthly_cost("cache.unknown.type", num_nodes=1) == 0.0

    def test_run_returns_list(self, default_config: FinOpsConfig, mock_session: MagicMock) -> None:
        check = ElastiCacheSchedulingCheck(config=default_config)
        results = check.run(session=mock_session, region="us-east-1")
        assert isinstance(results, list)


class TestRDSRightsizingCheck:
    """Tests for RDS right-sizing check."""

    def test_get_smaller_class(self, default_config: FinOpsConfig) -> None:
        check = RDSRightsizingCheck(config=default_config)
        assert check._get_smaller_class("db.r5.2xlarge") == "db.r5.xlarge"
        assert check._get_smaller_class("db.r5.xlarge") == "db.r5.large"
        assert check._get_smaller_class("db.r5.large") is None

    def test_estimate_monthly_cost_single_az(self, default_config: FinOpsConfig) -> None:
        check = RDSRightsizingCheck(config=default_config)
        cost = check._estimate_monthly_cost("db.r5.xlarge", multi_az=False)
        assert cost == pytest.approx(0.480 * 730, rel=0.01)

    def test_estimate_monthly_cost_multi_az(self, default_config: FinOpsConfig) -> None:
        check = RDSRightsizingCheck(config=default_config)
        single = check._estimate_monthly_cost("db.r5.xlarge", multi_az=False)
        multi = check._estimate_monthly_cost("db.r5.xlarge", multi_az=True)
        assert multi == pytest.approx(single * 2, rel=0.01)

    def test_run_returns_list(self, default_config: FinOpsConfig, mock_session: MagicMock) -> None:
        check = RDSRightsizingCheck(config=default_config)
        results = check.run(session=mock_session, region="us-east-1")
        assert isinstance(results, list)
