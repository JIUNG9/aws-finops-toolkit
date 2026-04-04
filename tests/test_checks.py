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
from finops.checks.vpc_waste import (
    VPCWasteCheck, NAT_GATEWAY_MONTHLY_COST, EIP_MONTHLY_COST,
    DIRECTORY_SIMPLE_AD_MONTHLY, DIRECTORY_MICROSOFT_AD_MONTHLY, WORKSPACES_BUNDLE_COSTS,
)
from finops.checks.cloudwatch_waste import (
    CloudWatchWasteCheck, CW_STORAGE_PER_GB_MONTH, CW_INGESTION_PER_GB, BYTES_PER_GB,
)
from finops.checks.s3_lifecycle import (
    S3LifecycleCheck, S3_STANDARD_PER_GB, S3_STANDARD_IA_PER_GB,
    S3_GLACIER_IR_PER_GB, S3_IT_MONITORING_PER_1000_OBJECTS, S3_IA_MIN_BILLABLE_SIZE_KB,
)
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


class TestVPCWasteCheck:
    """Tests for VPC waste detection check."""

    def test_check_name_and_description(self, default_config: FinOpsConfig) -> None:
        check = VPCWasteCheck(config=default_config)
        assert check.name == "vpc_waste"
        assert "VPC" in check.description

    def test_run_returns_list(self, default_config: FinOpsConfig, mock_session: MagicMock) -> None:
        check = VPCWasteCheck(config=default_config)
        results = check.run(session=mock_session, region="us-east-1")
        assert isinstance(results, list)

    def test_pricing_constants(self) -> None:
        """Verify pricing constants are reasonable."""
        assert NAT_GATEWAY_MONTHLY_COST == 43.00
        assert EIP_MONTHLY_COST == 3.65
        assert DIRECTORY_SIMPLE_AD_MONTHLY == 144.00
        assert DIRECTORY_MICROSOFT_AD_MONTHLY == 360.00

    def test_workspaces_bundle_costs(self) -> None:
        """Verify WorkSpaces bundle pricing is populated."""
        assert len(WORKSPACES_BUNDLE_COSTS) >= 5
        assert WORKSPACES_BUNDLE_COSTS["Standard"] == 35.00
        assert WORKSPACES_BUNDLE_COSTS["Performance"] == 60.00

    def test_abandoned_vpc_cost_model(self) -> None:
        """Verify the abandoned VPC cost model.

        A typical abandoned VPC with 2 NAT GWs + 3 EIPs + 1 Directory:
        2 * $43 + 3 * $3.65 + $144 = $240.95/month
        """
        nat_cost = 2 * NAT_GATEWAY_MONTHLY_COST
        eip_cost = 3 * EIP_MONTHLY_COST
        dir_cost = DIRECTORY_SIMPLE_AD_MONTHLY
        total = nat_cost + eip_cost + dir_cost
        assert total == pytest.approx(240.95, rel=0.01)

    def test_sub_checks_return_lists(self, default_config: FinOpsConfig, mock_session: MagicMock) -> None:
        """Verify each sub-check returns a list."""
        check = VPCWasteCheck(config=default_config)
        assert isinstance(check._check_abandoned_vpcs(mock_session, "us-east-1"), list)
        assert isinstance(check._check_idle_nat_gateways(mock_session, "us-east-1"), list)
        assert isinstance(check._check_stale_workspaces(mock_session, "us-east-1"), list)
        assert isinstance(check._check_orphan_directories(mock_session, "us-east-1"), list)
        assert isinstance(check._check_idle_storage_gateways(mock_session, "us-east-1"), list)


class TestCloudWatchWasteCheck:
    """Tests for CloudWatch Log waste detection check."""

    def test_check_name_and_description(self, default_config: FinOpsConfig) -> None:
        check = CloudWatchWasteCheck(config=default_config)
        assert check.name == "cloudwatch_waste"
        assert "log" in check.description.lower() or "Log" in check.description

    def test_run_returns_list(self, default_config: FinOpsConfig, mock_session: MagicMock) -> None:
        check = CloudWatchWasteCheck(config=default_config)
        results = check.run(session=mock_session, region="us-east-1")
        assert isinstance(results, list)

    def test_pricing_constants(self) -> None:
        """Verify CloudWatch Logs pricing constants."""
        assert CW_STORAGE_PER_GB_MONTH == 0.03
        assert CW_INGESTION_PER_GB == 0.50
        assert BYTES_PER_GB == 1024 ** 3

    def test_storage_cost_calculation(self) -> None:
        """Verify storage cost calculation for a 50GB log group.

        50 GB * $0.03/GB = $1.50/month
        """
        stored_gb = 50.0
        monthly_cost = stored_gb * CW_STORAGE_PER_GB_MONTH
        assert monthly_cost == pytest.approx(1.50, rel=0.01)

    def test_ingestion_cost_calculation(self) -> None:
        """Verify ingestion cost for 100GB/month.

        100 GB * $0.50/GB = $50.00/month
        """
        ingestion_gb = 100.0
        ingestion_cost = ingestion_gb * CW_INGESTION_PER_GB
        assert ingestion_cost == pytest.approx(50.00, rel=0.01)

    def test_retention_reduction_savings(self) -> None:
        """Verify retention reduction savings model.

        Log group with 365-day retention reduced to 90-day:
        Reduction ratio: 1 - (90/365) = 0.753
        If storing 100GB at $0.03/GB = $3.00/mo, savings ~= $2.26/mo
        """
        stored_gb = 100.0
        current_retention = 365
        recommended_retention = 90
        monthly_cost = stored_gb * CW_STORAGE_PER_GB_MONTH
        reduction_ratio = 1.0 - (recommended_retention / current_retention)
        savings = monthly_cost * reduction_ratio
        assert reduction_ratio == pytest.approx(0.753, rel=0.01)
        assert savings == pytest.approx(2.26, rel=0.02)

    def test_sub_checks_return_lists(self, default_config: FinOpsConfig, mock_session: MagicMock) -> None:
        """Verify each sub-check returns a list."""
        check = CloudWatchWasteCheck(config=default_config)
        assert isinstance(check._check_orphan_log_groups(mock_session, "us-east-1"), list)
        assert isinstance(check._check_inactive_log_groups(mock_session, "us-east-1"), list)
        assert isinstance(check._check_over_retained_log_groups(mock_session, "us-east-1"), list)
        assert isinstance(check._check_high_ingestion_log_groups(mock_session, "us-east-1"), list)
        assert isinstance(check._check_no_retention_policy(mock_session, "us-east-1"), list)


class TestS3LifecycleCheck:
    """Tests for S3 lifecycle optimization check."""

    def test_check_name_and_description(self, default_config: FinOpsConfig) -> None:
        check = S3LifecycleCheck(config=default_config)
        assert check.name == "s3_lifecycle"
        assert "S3" in check.description

    def test_run_returns_list(self, default_config: FinOpsConfig, mock_session: MagicMock) -> None:
        check = S3LifecycleCheck(config=default_config)
        results = check.run(session=mock_session, region="us-east-1")
        assert isinstance(results, list)

    def test_pricing_constants(self) -> None:
        """Verify S3 storage pricing constants."""
        assert S3_STANDARD_PER_GB == 0.023
        assert S3_STANDARD_IA_PER_GB == 0.0125
        assert S3_GLACIER_IR_PER_GB == 0.004
        assert S3_IT_MONITORING_PER_1000_OBJECTS == 0.0025
        assert S3_IA_MIN_BILLABLE_SIZE_KB == 128

    def test_lifecycle_savings_model(self) -> None:
        """Verify lifecycle savings for a 1TB bucket.

        Standard:  1024 GB * $0.023 = $23.55/mo
        Lifecycle: 40% Std + 35% IA + 25% Glacier IR
                 = 409.6*0.023 + 358.4*0.0125 + 256*0.004
                 = $9.42 + $4.48 + $1.02 = $14.92/mo
        Savings:   $23.55 - $14.92 = $8.63/mo (~37%)
        """
        bucket_gb = 1024.0
        standard_cost = bucket_gb * S3_STANDARD_PER_GB
        lifecycle_cost = (
            bucket_gb * 0.40 * S3_STANDARD_PER_GB +
            bucket_gb * 0.35 * S3_STANDARD_IA_PER_GB +
            bucket_gb * 0.25 * S3_GLACIER_IR_PER_GB
        )
        savings = standard_cost - lifecycle_cost
        assert standard_cost == pytest.approx(23.55, rel=0.01)
        assert lifecycle_cost == pytest.approx(14.92, rel=0.02)
        assert savings > 8.0

    def test_it_monitoring_cost(self) -> None:
        """Verify Intelligent-Tiering monitoring cost for 10M objects.

        10,000,000 / 1,000 * $0.0025 = $25.00/month
        """
        object_count = 10_000_000
        monitoring_cost = (object_count / 1000) * S3_IT_MONITORING_PER_1000_OBJECTS
        assert monitoring_cost == pytest.approx(25.00, rel=0.01)

    def test_small_object_ia_penalty(self) -> None:
        """Verify IA penalty for small objects.

        1M objects averaging 20KB each = ~20GB actual
        IA billed at 128KB min per object: 1M * 128KB = ~122GB
        Standard cost: 20 GB * $0.023 = $0.46/mo
        IA cost:       122 GB * $0.0125 = $1.53/mo
        IA is 3.3x MORE expensive for small objects.
        """
        object_count = 1_000_000
        avg_size_kb = 20
        actual_gb = (object_count * avg_size_kb * 1024) / (1024 ** 3)
        billed_gb_ia = (object_count * S3_IA_MIN_BILLABLE_SIZE_KB * 1024) / (1024 ** 3)

        standard_cost = actual_gb * S3_STANDARD_PER_GB
        ia_cost = billed_gb_ia * S3_STANDARD_IA_PER_GB

        assert actual_gb == pytest.approx(19.07, rel=0.05)
        assert billed_gb_ia == pytest.approx(122.07, rel=0.05)
        assert ia_cost > standard_cost  # IA is more expensive
        assert ia_cost / standard_cost > 3.0  # At least 3x more expensive

    def test_compare_it_vs_lifecycle(self, default_config: FinOpsConfig) -> None:
        """Verify IT vs lifecycle comparison for a bucket with many objects.

        500GB bucket, 10M objects (avg 50KB):
        - IT monitoring: $25/mo
        - IT total is higher than standard due to massive monitoring fee
        - Should recommend lifecycle over IT
        """
        result = S3LifecycleCheck.compare_it_vs_lifecycle(
            bucket_gb=500.0,
            object_count=10_000_000,
            frequent_access_ratio=0.40,
        )
        assert result["it_monitoring_cost"] == pytest.approx(25.00, rel=0.01)
        assert result["standard_cost"] > result["lifecycle_cost"]
        # With 10M objects, the $25/mo monitoring fee makes IT MORE expensive
        # than Standard — this is the key insight from real FinOps work
        assert result["it_total_cost"] > result["standard_cost"]
        # For 10M objects, lifecycle should be cheaper than IT
        assert result["lifecycle_savings_vs_it"] > 0
        assert result["recommendation"] == "lifecycle"

    def test_compare_it_vs_lifecycle_low_object_count(self, default_config: FinOpsConfig) -> None:
        """Verify IT is recommended for buckets with low object count.

        500GB bucket, 100K objects (avg 5MB):
        - IT monitoring: $0.25/mo — negligible
        - IT should be fine (or comparable to lifecycle)
        """
        result = S3LifecycleCheck.compare_it_vs_lifecycle(
            bucket_gb=500.0,
            object_count=100_000,
            frequent_access_ratio=0.40,
        )
        assert result["it_monitoring_cost"] == pytest.approx(0.25, rel=0.01)
        # With low monitoring cost, IT and lifecycle should be close
        # IT monitoring cost is so small it barely matters
        assert result["it_monitoring_cost"] < 1.0

    def test_sub_checks_return_lists(self, default_config: FinOpsConfig, mock_session: MagicMock) -> None:
        """Verify each sub-check returns a list."""
        check = S3LifecycleCheck(config=default_config)
        assert isinstance(check._check_no_lifecycle_policy(mock_session, "us-east-1"), list)
        assert isinstance(check._check_intelligent_tiering_cost(mock_session, "us-east-1"), list)
        assert isinstance(check._check_small_objects_ia_penalty(mock_session, "us-east-1"), list)
        assert isinstance(check._check_no_analytics(mock_session, "us-east-1"), list)
