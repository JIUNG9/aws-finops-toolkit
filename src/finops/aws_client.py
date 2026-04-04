"""AWS Client Wrapper — Handles authentication, multi-account access, and region management.

Provides a unified interface for:
  - Profile-based authentication (AWS CLI named profiles)
  - Cross-account access via STS AssumeRole
  - Region handling with sensible defaults
  - Session caching to avoid redundant authentication
"""

from __future__ import annotations

from typing import Any, Optional

import boto3
from botocore.config import Config as BotoConfig


# Default boto3 config: retry logic and timeouts
DEFAULT_BOTO_CONFIG = BotoConfig(
    retries={"max_attempts": 3, "mode": "adaptive"},
    connect_timeout=10,
    read_timeout=30,
)


class AWSClient:
    """Wrapper around boto3 for multi-account, multi-region access.

    Caches sessions to avoid creating duplicate connections.

    Usage:
        client = AWSClient()
        session = client.get_session(profile="production", region="us-east-1")
        ec2 = session.client("ec2")
    """

    def __init__(self) -> None:
        """Initialize the AWS client with an empty session cache."""
        self._session_cache: dict[str, Any] = {}

    def get_session(
        self,
        profile: Optional[str] = None,
        region: Optional[str] = None,
    ) -> Any:
        """Get or create a boto3 Session for the given profile and region.

        Sessions are cached by profile name. If the same profile is requested
        multiple times, the cached session is returned.

        Args:
            profile: AWS CLI profile name. None uses the default profile.
            region: AWS region. None uses the profile's default region.

        Returns:
            A boto3.Session configured for the specified profile and region.
        """
        cache_key = f"{profile or 'default'}:{region or 'default'}"

        if cache_key in self._session_cache:
            return self._session_cache[cache_key]

        session_kwargs: dict[str, Any] = {}
        if profile:
            session_kwargs["profile_name"] = profile
        if region:
            session_kwargs["region_name"] = region

        session = boto3.Session(**session_kwargs)
        self._session_cache[cache_key] = session
        return session

    def assume_role(
        self,
        source_profile: str,
        account_id: str,
        role_name: str,
        region: Optional[str] = None,
        session_name: str = "finops-toolkit",
    ) -> Any:
        """Assume a role in another AWS account and return a new session.

        Used for cross-account scanning in AWS Organizations setups.
        The source profile must have permission to assume the target role.

        Args:
            source_profile: AWS profile with permission to assume roles.
            account_id: Target AWS account ID.
            role_name: IAM role name to assume in the target account.
            region: AWS region for the new session.
            session_name: STS session name for CloudTrail auditing.

        Returns:
            A boto3.Session authenticated as the assumed role.
        """
        cache_key = f"assumed:{account_id}:{role_name}:{region or 'default'}"

        if cache_key in self._session_cache:
            return self._session_cache[cache_key]

        # Get a session for the source account
        source_session = self.get_session(profile=source_profile, region=region)

        # TODO: Uncomment for real cross-account access
        # sts_client = source_session.client("sts", config=DEFAULT_BOTO_CONFIG)
        # role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
        # response = sts_client.assume_role(
        #     RoleArn=role_arn,
        #     RoleSessionName=session_name,
        #     DurationSeconds=3600,  # 1 hour
        # )
        #
        # credentials = response["Credentials"]
        #
        # assumed_session = boto3.Session(
        #     aws_access_key_id=credentials["AccessKeyId"],
        #     aws_secret_access_key=credentials["SecretAccessKey"],
        #     aws_session_token=credentials["SessionToken"],
        #     region_name=region,
        # )
        #
        # self._session_cache[cache_key] = assumed_session
        # return assumed_session

        # Placeholder: return source session for development
        return source_session

    def get_account_id(self, session: Any) -> str:
        """Get the AWS account ID for a session.

        Args:
            session: A boto3.Session.

        Returns:
            The 12-digit AWS account ID.
        """
        # TODO: Uncomment for real AWS calls
        # sts = session.client("sts", config=DEFAULT_BOTO_CONFIG)
        # identity = sts.get_caller_identity()
        # return identity["Account"]
        return "000000000000"

    def list_organization_accounts(
        self,
        management_profile: str,
    ) -> list[dict[str, str]]:
        """List all active accounts in an AWS Organization.

        Args:
            management_profile: AWS profile for the management account
                                with organizations:ListAccounts permission.

        Returns:
            List of dicts with 'id', 'name', 'email' for each active account.
        """
        accounts: list[dict[str, str]] = []

        # TODO: Uncomment for real AWS Organizations calls
        # session = self.get_session(profile=management_profile)
        # org_client = session.client("organizations", config=DEFAULT_BOTO_CONFIG)
        #
        # paginator = org_client.get_paginator("list_accounts")
        # for page in paginator.paginate():
        #     for account in page["Accounts"]:
        #         if account["Status"] == "ACTIVE":
        #             accounts.append({
        #                 "id": account["Id"],
        #                 "name": account["Name"],
        #                 "email": account.get("Email", ""),
        #             })

        return accounts
