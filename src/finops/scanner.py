"""Main scanner that orchestrates all checks and collects results.

The Scanner is the core orchestrator. It:
  1. Resolves which AWS accounts to scan (profiles or Organizations)
  2. Creates authenticated boto3 sessions for each account
  3. Runs enabled checks against each account/region
  4. Collects and aggregates all findings into a ScanResults object
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from rich.console import Console

from finops.aws_client import AWSClient
from finops.checks import get_enabled_checks
from finops.checks.base import CheckResult
from finops.config import FinOpsConfig

console = Console()


@dataclass
class AccountResults:
    """Results for a single AWS account."""

    account_id: str
    account_name: str
    profile: str
    region: str
    findings: list[CheckResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total_monthly_waste(self) -> float:
        """Sum of current monthly cost for all flagged resources."""
        return sum(f.current_monthly_cost for f in self.findings)

    @property
    def total_monthly_savings(self) -> float:
        """Sum of estimated monthly savings across all findings."""
        return sum(f.estimated_monthly_savings for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON export."""
        return {
            "account_id": self.account_id,
            "account_name": self.account_name,
            "profile": self.profile,
            "region": self.region,
            "findings": [f.to_dict() for f in self.findings],
            "errors": self.errors,
            "total_monthly_waste": self.total_monthly_waste,
            "total_monthly_savings": self.total_monthly_savings,
        }


@dataclass
class ScanResults:
    """Aggregated results across all scanned accounts."""

    scan_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    accounts: list[AccountResults] = field(default_factory=list)

    @property
    def total_monthly_savings(self) -> float:
        """Total estimated monthly savings across all accounts."""
        return sum(a.total_monthly_savings for a in self.accounts)

    @property
    def total_annual_savings(self) -> float:
        """Total estimated annual savings."""
        return self.total_monthly_savings * 12

    @property
    def total_findings(self) -> int:
        """Total number of findings across all accounts."""
        return sum(len(a.findings) for a in self.accounts)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON export."""
        return {
            "scan_time": self.scan_time,
            "total_monthly_savings": self.total_monthly_savings,
            "total_annual_savings": self.total_annual_savings,
            "total_findings": self.total_findings,
            "accounts": [a.to_dict() for a in self.accounts],
        }


class Scanner:
    """Orchestrates cost optimization checks across AWS accounts.

    Usage:
        scanner = Scanner(config=config)
        results = scanner.scan_profiles(profiles=["prod"], region="us-east-1")
    """

    def __init__(self, config: FinOpsConfig) -> None:
        self.config = config
        self.aws_client = AWSClient()

    def scan_profiles(
        self,
        profiles: list[str],
        region: str = "us-east-1",
        check_names: Optional[list[str]] = None,
    ) -> ScanResults:
        """Scan one or more AWS profiles.

        Args:
            profiles: List of AWS CLI profile names to scan.
            region: AWS region to scan.
            check_names: Optional list of specific check names to run.
                         If None, runs all enabled checks from config.

        Returns:
            ScanResults with findings from all profiles.
        """
        results = ScanResults()

        for profile in profiles:
            console.print(f"[bold]Scanning profile:[/bold] {profile} ({region})")
            account_results = self._scan_account(
                profile=profile,
                region=region,
                check_names=check_names,
            )
            results.accounts.append(account_results)

        return results

    def scan_organization(
        self,
        management_profile: str,
        role_name: str,
        region: str = "us-east-1",
        check_names: Optional[list[str]] = None,
    ) -> ScanResults:
        """Scan all accounts in an AWS Organization.

        Args:
            management_profile: AWS profile for the management account.
            role_name: IAM role name to assume in each member account.
            region: AWS region to scan.
            check_names: Optional list of specific check names to run.

        Returns:
            ScanResults with findings from all member accounts.
        """
        results = ScanResults()

        # TODO: Use management_profile to call organizations:ListAccounts
        # For each account, assume role_name and run checks
        #
        # session = self.aws_client.get_session(profile=management_profile)
        # org_client = session.client("organizations")
        # paginator = org_client.get_paginator("list_accounts")
        # for page in paginator.paginate():
        #     for account in page["Accounts"]:
        #         if account["Status"] != "ACTIVE":
        #             continue
        #         account_id = account["Id"]
        #         account_name = account["Name"]
        #         assumed_session = self.aws_client.assume_role(
        #             source_profile=management_profile,
        #             account_id=account_id,
        #             role_name=role_name,
        #         )
        #         account_results = self._scan_with_session(
        #             session=assumed_session,
        #             account_id=account_id,
        #             account_name=account_name,
        #             region=region,
        #             check_names=check_names,
        #         )
        #         results.accounts.append(account_results)

        console.print("[yellow]Organization scan not yet implemented. Use --profiles instead.[/yellow]")
        return results

    def _scan_account(
        self,
        profile: str,
        region: str,
        check_names: Optional[list[str]] = None,
    ) -> AccountResults:
        """Scan a single AWS account using a named profile.

        Creates a boto3 session, resolves the account ID, then runs
        each enabled check and collects findings.
        """
        # Create boto3 session for this profile
        session = self.aws_client.get_session(profile=profile, region=region)

        # Resolve the AWS account ID from STS
        # TODO: Uncomment when running against real AWS
        # sts = session.client("sts")
        # identity = sts.get_caller_identity()
        # account_id = identity["Account"]
        account_id = "000000000000"  # Placeholder for development
        account_name = profile  # Use profile name as account name for now

        return self._scan_with_session(
            session=session,
            account_id=account_id,
            account_name=account_name,
            profile=profile,
            region=region,
            check_names=check_names,
        )

    def _scan_with_session(
        self,
        session: Any,
        account_id: str,
        account_name: str,
        region: str,
        profile: str = "",
        check_names: Optional[list[str]] = None,
    ) -> AccountResults:
        """Run all enabled checks using an authenticated session.

        Args:
            session: An authenticated boto3 Session.
            account_id: The AWS account ID being scanned.
            account_name: A human-readable name for the account.
            region: The AWS region to scan.
            profile: The AWS profile name (for result labeling).
            check_names: Optional filter for which checks to run.

        Returns:
            AccountResults containing all findings and any errors.
        """
        account_results = AccountResults(
            account_id=account_id,
            account_name=account_name,
            profile=profile,
            region=region,
        )

        # Get the checks to run (filtered by check_names and config)
        checks = get_enabled_checks(self.config, check_names)

        for check in checks:
            console.print(f"  Running check: [cyan]{check.name}[/cyan] — {check.description}")
            try:
                findings = check.run(session=session, region=region)
                account_results.findings.extend(findings)
                if findings:
                    console.print(f"    Found [yellow]{len(findings)}[/yellow] optimization(s)")
                else:
                    console.print("    [green]No issues found[/green]")
            except Exception as e:
                error_msg = f"Check '{check.name}' failed: {str(e)}"
                account_results.errors.append(error_msg)
                console.print(f"    [red]Error: {e}[/red]")

        return account_results
