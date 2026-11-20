"""CLI surface: the removed `preflight` command stays gone, and old configs still load."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from finops.cli import main
from finops.config import load_config


def test_preflight_command_is_gone() -> None:
    """`finops preflight` returned a GO verdict from no data; it must not come back unnoticed."""
    result = CliRunner().invoke(main, ["preflight", "--target", "i-0abc", "--profile", "acme-dev"])

    assert result.exit_code == 2
    assert "No such command 'preflight'" in result.output


def test_config_with_old_preflight_section_still_loads(tmp_path: Path) -> None:
    """A finops.yaml written for the removed command must not break `scan`."""
    cfg = tmp_path / "finops.yaml"
    cfg.write_text(
        "preflight:\n"
        "  slo:\n"
        "    p99_latency_ms: 100\n"
        "  services:\n"
        "    - name: gateway\n"
        "checks:\n"
        "  nat_gateway: false\n"
    )

    config = load_config(cfg)

    assert config.checks["nat_gateway"] is False
    assert not hasattr(config, "preflight")
