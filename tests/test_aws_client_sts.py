"""STS identity tests: account IDs come from STS, never from a placeholder."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError, NoCredentialsError
from moto import mock_aws

from finops.aws_client import AWSClient, AWSClientError
from finops.config import FinOpsConfig
from finops.scanner import Scanner

REGION = "us-east-1"
# moto's default account; any other value proves the ID came from STS and not a constant.
MOTO_ACCOUNT = "123456789012"
TARGET_ACCOUNT = "111122223333"


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


@mock_aws
def test_get_account_id_reads_sts() -> None:
    client = AWSClient()
    assert client.get_account_id(boto3.Session(region_name=REGION)) == MOTO_ACCOUNT


@mock_aws
def test_assume_role_returns_session_for_the_target_account() -> None:
    client = AWSClient()
    session = client.assume_role(None, TARGET_ACCOUNT, "FinOpsReadOnly", REGION)
    assert client.get_account_id(session) == TARGET_ACCOUNT
    assert session.get_credentials().token  # temporary credentials, not the source session's


@mock_aws
def test_assume_role_is_cached() -> None:
    client = AWSClient()
    first = client.assume_role(None, TARGET_ACCOUNT, "FinOpsReadOnly", REGION)
    assert client.assume_role(None, TARGET_ACCOUNT, "FinOpsReadOnly", REGION) is first


def test_assume_role_failure_raises_clear_error() -> None:
    client = AWSClient()
    source = MagicMock()
    source.client.return_value.assume_role.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "nope"}}, "AssumeRole"
    )
    with patch.object(client, "get_session", return_value=source):
        with pytest.raises(AWSClientError, match="FinOpsReadOnly"):
            client.assume_role("mgmt", TARGET_ACCOUNT, "FinOpsReadOnly", REGION)


def test_get_account_id_without_credentials_raises() -> None:
    session = MagicMock()
    session.client.return_value.get_caller_identity.side_effect = NoCredentialsError()
    with pytest.raises(AWSClientError):
        AWSClient().get_account_id(session)


@mock_aws
def test_scan_labels_findings_with_the_real_account_id() -> None:
    scanner = Scanner(config=FinOpsConfig())
    session = boto3.Session(region_name=REGION)
    with patch("finops.scanner.get_enabled_checks", return_value=[]), \
            patch.object(scanner.aws_client, "get_session", return_value=session):
        account = scanner._scan_account(profile="prod", region=REGION)
    assert account.account_id == MOTO_ACCOUNT


def test_scan_profiles_reports_unresolvable_account_instead_of_guessing() -> None:
    scanner = Scanner(config=FinOpsConfig())
    scanner.aws_client = MagicMock()
    scanner.aws_client.get_account_id.side_effect = AWSClientError("no credentials")
    with patch("finops.scanner.get_enabled_checks") as checks:
        results = scanner.scan_profiles(profiles=["broken"], region=REGION)
    checks.assert_not_called()
    account = results.accounts[0]
    assert account.account_id == "unknown"
    assert account.findings == []
    assert "no credentials" in account.errors[0]
