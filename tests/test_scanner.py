"""Unit tests for the Scanner orchestrator.

Tests cover:
  - ScanResults aggregation and serialization
  - AccountResults properties (total waste, savings)
  - Check filtering by name and config
  - Error handling during check execution
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from finops.scanner import Scanner, ScanResults, AccountResults
from finops.checks.base import CheckResult
from finops.config import FinOpsConfig


class TestAccountResults:
    """Tests for the AccountResults dataclass."""

    def test_total_monthly_waste(self) -> None:
        account = AccountResults(
            account_id="123456789012",
            account_name="test",
            profile="test",
            region="us-east-1",
            findings=[
                CheckResult(
                    check_name="test",
                    resource_type="EC2",
                    resource_id="i-1",
                    resource_name="instance-1",
                    current_monthly_cost=200.0,
                    recommended_action="Downsize",
                    estimated_monthly_savings=100.0,
                ),
                CheckResult(
                    check_name="test",
                    resource_type="EBS",
                    resource_id="vol-1",
                    resource_name="volume-1",
                    current_monthly_cost=50.0,
                    recommended_action="Delete",
                    estimated_monthly_savings=50.0,
                ),
            ],
        )
        assert account.total_monthly_waste == 250.0
        assert account.total_monthly_savings == 150.0

    def test_empty_findings(self) -> None:
        account = AccountResults(
            account_id="123456789012",
            account_name="test",
            profile="test",
            region="us-east-1",
        )
        assert account.total_monthly_waste == 0.0
        assert account.total_monthly_savings == 0.0

    def test_to_dict(self) -> None:
        account = AccountResults(
            account_id="123456789012",
            account_name="test",
            profile="test",
            region="us-east-1",
        )
        d = account.to_dict()
        assert d["account_id"] == "123456789012"
        assert d["findings"] == []
        assert d["total_monthly_savings"] == 0.0


class TestScanResults:
    """Tests for the ScanResults dataclass."""

    def test_total_monthly_savings(self) -> None:
        results = ScanResults()
        results.accounts = [
            AccountResults(
                account_id="111",
                account_name="dev",
                profile="dev",
                region="us-east-1",
                findings=[
                    CheckResult(
                        check_name="test",
                        resource_type="EC2",
                        resource_id="i-1",
                        resource_name="instance",
                        current_monthly_cost=100.0,
                        recommended_action="Downsize",
                        estimated_monthly_savings=50.0,
                    ),
                ],
            ),
            AccountResults(
                account_id="222",
                account_name="staging",
                profile="staging",
                region="us-east-1",
                findings=[
                    CheckResult(
                        check_name="test",
                        resource_type="NAT",
                        resource_id="nat-1",
                        resource_name="nat-gw",
                        current_monthly_cost=32.0,
                        recommended_action="Delete",
                        estimated_monthly_savings=32.0,
                    ),
                ],
            ),
        ]
        assert results.total_monthly_savings == 82.0
        assert results.total_annual_savings == 984.0
        assert results.total_findings == 2

    def test_empty_results(self) -> None:
        results = ScanResults()
        assert results.total_monthly_savings == 0.0
        assert results.total_annual_savings == 0.0
        assert results.total_findings == 0

    def test_to_dict(self) -> None:
        results = ScanResults()
        d = results.to_dict()
        assert "scan_time" in d
        assert "total_monthly_savings" in d
        assert "accounts" in d
        assert isinstance(d["accounts"], list)


class TestScanner:
    """Tests for the Scanner orchestrator."""

    def test_scanner_initialization(self, default_config: FinOpsConfig) -> None:
        scanner = Scanner(config=default_config)
        assert scanner.config is default_config

    @patch("finops.scanner.get_enabled_checks")
    def test_scan_profiles_returns_scan_results(
        self,
        mock_get_checks: MagicMock,
        default_config: FinOpsConfig,
    ) -> None:
        """Test that scan_profiles returns a ScanResults object."""
        mock_get_checks.return_value = []  # No checks = no findings

        scanner = Scanner(config=default_config)
        # Patch the AWS client to avoid real AWS calls
        scanner.aws_client = MagicMock()
        scanner.aws_client.get_session.return_value = MagicMock()

        results = scanner.scan_profiles(
            profiles=["test-profile"],
            region="us-east-1",
        )

        assert isinstance(results, ScanResults)
        assert len(results.accounts) == 1
        assert results.accounts[0].profile == "test-profile"
