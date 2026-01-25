"""Shared test fixtures with mocked boto3 responses.

Provides reusable fixtures for:
  - Mocked boto3 sessions and clients
  - Sample EC2, RDS, ElastiCache, NAT Gateway responses
  - CloudWatch metric data
  - FinOps configuration objects
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from finops.config import FinOpsConfig, DEFAULT_THRESHOLDS, DEFAULT_CHECKS


@pytest.fixture
def default_config() -> FinOpsConfig:
    """Provide a default FinOps configuration for tests."""
    return FinOpsConfig(
        thresholds=dict(DEFAULT_THRESHOLDS),
        accounts=[],
        checks=dict(DEFAULT_CHECKS),
    )


@pytest.fixture
def mock_session() -> MagicMock:
    """Provide a mocked boto3 Session.

    Usage in tests:
        def test_something(mock_session):
            ec2_client = mock_session.client("ec2")
            ec2_client.describe_instances.return_value = {...}
    """
    session = MagicMock()
    # Track which clients have been created
    clients: dict[str, MagicMock] = {}

    def get_client(service: str, **kwargs: Any) -> MagicMock:
        if service not in clients:
            clients[service] = MagicMock()
        return clients[service]

    session.client = get_client
    return session


@pytest.fixture
def sample_ec2_instances() -> dict[str, Any]:
    """Provide a sample describe_instances response with various instance types."""
    return {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-0a1b2c3d4e5f",
                        "InstanceType": "m5.2xlarge",
                        "State": {"Name": "running"},
                        "Placement": {"AvailabilityZone": "us-east-1a"},
                        "Tags": [
                            {"Key": "Name", "Value": "web-prod-01"},
                            {"Key": "Environment", "Value": "production"},
                        ],
                        "BlockDeviceMappings": [
                            {
                                "DeviceName": "/dev/xvda",
                                "Ebs": {"VolumeId": "vol-root001"},
                            }
                        ],
                    },
                    {
                        "InstanceId": "i-1a2b3c4d5e6f",
                        "InstanceType": "m5.xlarge",
                        "State": {"Name": "running"},
                        "Placement": {"AvailabilityZone": "us-east-1b"},
                        "Tags": [
                            {"Key": "Name", "Value": "worker-staging-01"},
                            {"Key": "Environment", "Value": "staging"},
                        ],
                        "BlockDeviceMappings": [
                            {
                                "DeviceName": "/dev/xvda",
                                "Ebs": {"VolumeId": "vol-root002"},
                            }
                        ],
                    },
                ]
            }
        ]
    }


@pytest.fixture
def sample_cloudwatch_low_cpu() -> dict[str, Any]:
    """Provide CloudWatch response showing low CPU utilization (~8%)."""
    return {
        "Datapoints": [
            {"Average": 7.5, "Timestamp": datetime(2026, 3, 1, tzinfo=timezone.utc)},
            {"Average": 9.2, "Timestamp": datetime(2026, 3, 2, tzinfo=timezone.utc)},
            {"Average": 6.8, "Timestamp": datetime(2026, 3, 3, tzinfo=timezone.utc)},
            {"Average": 8.1, "Timestamp": datetime(2026, 3, 4, tzinfo=timezone.utc)},
            {"Average": 10.3, "Timestamp": datetime(2026, 3, 5, tzinfo=timezone.utc)},
            {"Average": 7.0, "Timestamp": datetime(2026, 3, 6, tzinfo=timezone.utc)},
            {"Average": 8.5, "Timestamp": datetime(2026, 3, 7, tzinfo=timezone.utc)},
        ]
    }


@pytest.fixture
def sample_cloudwatch_high_cpu() -> dict[str, Any]:
    """Provide CloudWatch response showing high CPU utilization (~65%)."""
    return {
        "Datapoints": [
            {"Average": 62.5, "Timestamp": datetime(2026, 3, 1, tzinfo=timezone.utc)},
            {"Average": 70.2, "Timestamp": datetime(2026, 3, 2, tzinfo=timezone.utc)},
            {"Average": 58.8, "Timestamp": datetime(2026, 3, 3, tzinfo=timezone.utc)},
            {"Average": 66.1, "Timestamp": datetime(2026, 3, 4, tzinfo=timezone.utc)},
            {"Average": 68.3, "Timestamp": datetime(2026, 3, 5, tzinfo=timezone.utc)},
        ]
    }


@pytest.fixture
def sample_unattached_volumes() -> dict[str, Any]:
    """Provide a describe_volumes response with unattached volumes."""
    return {
        "Volumes": [
            {
                "VolumeId": "vol-0ff1234abcdef",
                "Size": 100,
                "VolumeType": "gp3",
                "State": "available",
                "CreateTime": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "Tags": [
                    {"Key": "Name", "Value": "old-data-vol"},
                ],
            },
            {
                "VolumeId": "vol-0aa5678ghijkl",
                "Size": 500,
                "VolumeType": "gp2",
                "State": "available",
                "CreateTime": datetime(2025, 11, 15, tzinfo=timezone.utc),
                "Tags": [],
            },
        ]
    }


@pytest.fixture
def sample_nat_gateways() -> dict[str, Any]:
    """Provide a describe_nat_gateways response."""
    return {
        "NatGateways": [
            {
                "NatGatewayId": "nat-0abc1234def",
                "VpcId": "vpc-dev001",
                "State": "available",
                "Tags": [
                    {"Key": "Name", "Value": "nat-dev"},
                    {"Key": "Environment", "Value": "development"},
                ],
            },
            {
                "NatGatewayId": "nat-0xyz5678ghi",
                "VpcId": "vpc-prod001",
                "State": "available",
                "Tags": [
                    {"Key": "Name", "Value": "nat-prod"},
                    {"Key": "Environment", "Value": "production"},
                ],
            },
        ]
    }


@pytest.fixture
def sample_rds_instances() -> dict[str, Any]:
    """Provide a describe_db_instances response."""
    return {
        "DBInstances": [
            {
                "DBInstanceIdentifier": "mydb-staging",
                "DBInstanceClass": "db.r5.xlarge",
                "Engine": "postgres",
                "MultiAZ": True,
                "DBInstanceStatus": "available",
                "DBInstanceArn": "arn:aws:rds:us-east-1:123456789012:db:mydb-staging",
            },
            {
                "DBInstanceIdentifier": "mydb-prod",
                "DBInstanceClass": "db.r5.2xlarge",
                "Engine": "postgres",
                "MultiAZ": True,
                "DBInstanceStatus": "available",
                "DBInstanceArn": "arn:aws:rds:us-east-1:123456789012:db:mydb-prod",
            },
        ]
    }
