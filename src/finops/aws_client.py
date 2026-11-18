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
from botocore.exceptions import BotoCoreError, ClientError


# Default boto3 config: retry logic and timeouts
DEFAULT_BOTO_CONFIG = BotoConfig(
    retries={"max_attempts": 3, "mode": "adaptive"},
    connect_timeout=10,
    read_timeout=30,
)


class AWSClientError(RuntimeError):
    """Raised when an STS call fails, so a scan never runs under a guessed identity."""


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

        source_session = self.get_session(profile=source_profile, region=region)
        role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"

        try:
            response = source_session.client("sts", config=DEFAULT_BOTO_CONFIG).assume_role(
                RoleArn=role_arn,
                RoleSessionName=session_name,
            )
        except (BotoCoreError, ClientError) as e:
            raise AWSClientError(f"Could not assume {role_arn} from profile '{source_profile}': {e}") from e

        creds = response["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )
        self._session_cache[cache_key] = session
        return session

    def get_account_id(self, session: Any) -> str:
        """Get the AWS account ID for a session from STS GetCallerIdentity.

        Args:
            session: A boto3.Session.

        Returns:
            The 12-digit AWS account ID.

        Raises:
            AWSClientError: If STS cannot identify the caller (no or expired credentials).
        """
        try:
            identity = session.client("sts", config=DEFAULT_BOTO_CONFIG).get_caller_identity()
        except (BotoCoreError, ClientError) as e:
            raise AWSClientError(f"Could not resolve the AWS account ID: {e}") from e
        return str(identity["Account"])

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

        return accounts
