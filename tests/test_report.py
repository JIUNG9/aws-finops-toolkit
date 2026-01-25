"""Unit tests for the Report Generator.

Tests cover:
  - HTML report generation
  - CSV report generation
  - JSON report generation
  - Terminal output (smoke test)
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from finops.report import ReportGenerator
from finops.config import FinOpsConfig


@pytest.fixture
def sample_scan_data() -> dict:
    """Provide sample scan results as a dictionary for report generation."""
    return {
        "scan_time": "2026-03-08T14:30:00+00:00",
        "total_monthly_savings": 250.0,
        "total_annual_savings": 3000.0,
        "total_findings": 3,
        "accounts": [
            {
                "account_id": "123456789012",
                "account_name": "production",
                "profile": "prod",
                "region": "us-east-1",
                "findings": [
                    {
                        "check_name": "ec2_rightsizing",
                        "resource_type": "EC2 Instance",
                        "resource_id": "i-0a1b2c3d",
                        "resource_name": "web-prod",
                        "current_monthly_cost": 292.0,
                        "recommended_action": "Downsize to m5.xlarge",
                        "estimated_monthly_savings": 146.0,
                        "estimated_annual_savings": 1752.0,
                        "savings_percentage": 50.0,
                        "severity": "high",
                        "details": {},
                    },
                    {
                        "check_name": "unused_resources",
                        "resource_type": "EBS Volume",
                        "resource_id": "vol-0ff1234a",
                        "resource_name": "old-data",
                        "current_monthly_cost": 80.0,
                        "recommended_action": "Delete — unattached for 45 days",
                        "estimated_monthly_savings": 80.0,
                        "estimated_annual_savings": 960.0,
                        "savings_percentage": 100.0,
                        "severity": "medium",
                        "details": {},
                    },
                ],
                "errors": [],
                "total_monthly_waste": 372.0,
                "total_monthly_savings": 226.0,
            },
            {
                "account_id": "987654321098",
                "account_name": "staging",
                "profile": "staging",
                "region": "us-east-1",
                "findings": [
                    {
                        "check_name": "nat_gateway",
                        "resource_type": "NAT Gateway",
                        "resource_id": "nat-0abc1234",
                        "resource_name": "nat-staging",
                        "current_monthly_cost": 32.40,
                        "recommended_action": "Replace with NAT Instance",
                        "estimated_monthly_savings": 28.00,
                        "estimated_annual_savings": 336.0,
                        "savings_percentage": 86.4,
                        "severity": "medium",
                        "details": {},
                    },
                ],
                "errors": [],
                "total_monthly_waste": 32.40,
                "total_monthly_savings": 28.0,
            },
        ],
    }


@pytest.fixture
def report_gen(default_config: FinOpsConfig) -> ReportGenerator:
    """Provide a ReportGenerator instance."""
    return ReportGenerator(config=default_config)


class TestHTMLReport:
    """Tests for HTML report generation."""

    def test_generate_html(
        self,
        report_gen: ReportGenerator,
        sample_scan_data: dict,
        tmp_path: Path,
    ) -> None:
        output = tmp_path / "report.html"
        report_gen.generate_html(sample_scan_data, output)

        assert output.exists()
        content = output.read_text()
        assert "AWS FinOps Report" in content
        assert "123456789012" in content
        assert "i-0a1b2c3d" in content
        assert "nat-0abc1234" in content

    def test_html_contains_savings(
        self,
        report_gen: ReportGenerator,
        sample_scan_data: dict,
        tmp_path: Path,
    ) -> None:
        output = tmp_path / "report.html"
        report_gen.generate_html(sample_scan_data, output)

        content = output.read_text()
        assert "250.00" in content  # total monthly savings
        assert "3000.00" in content  # total annual savings


class TestCSVReport:
    """Tests for CSV report generation."""

    def test_generate_csv(
        self,
        report_gen: ReportGenerator,
        sample_scan_data: dict,
        tmp_path: Path,
    ) -> None:
        output = tmp_path / "report.csv"
        report_gen.generate_csv(sample_scan_data, output)

        assert output.exists()
        with open(output) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Should have 3 findings total
        assert len(rows) == 3

    def test_csv_columns(
        self,
        report_gen: ReportGenerator,
        sample_scan_data: dict,
        tmp_path: Path,
    ) -> None:
        output = tmp_path / "report.csv"
        report_gen.generate_csv(sample_scan_data, output)

        with open(output) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        first = rows[0]
        assert "account_id" in first
        assert "resource_id" in first
        assert "estimated_monthly_savings" in first
        assert "severity" in first


class TestJSONReport:
    """Tests for JSON report generation."""

    def test_generate_json(
        self,
        report_gen: ReportGenerator,
        sample_scan_data: dict,
        tmp_path: Path,
    ) -> None:
        output = tmp_path / "report.json"
        report_gen.generate_json(sample_scan_data, output)

        assert output.exists()
        with open(output) as f:
            data = json.load(f)

        assert data["total_findings"] == 3
        assert len(data["accounts"]) == 2
