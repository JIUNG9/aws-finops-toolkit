"""Only AWS is implemented; the registry must not advertise anything else."""

import pytest

import finops.providers.aws.provider  # noqa: F401  (registers "aws")
from finops.providers.base import _PROVIDERS, get_provider


def test_only_aws_is_registered():
    assert sorted(_PROVIDERS) == ["aws"]


@pytest.mark.parametrize("name", ["azure", "gcp"])
def test_unsupported_cloud_is_an_unknown_provider(name):
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider(name)
