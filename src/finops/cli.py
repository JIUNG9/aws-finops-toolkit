"""CLI entry point for aws-finops-toolkit.

Provides four main commands:
  - preflight: Analyze a target resource before any cost optimization (9 checks)
  - scan:      Run cost optimization checks against AWS accounts
  - report:    Generate reports from scan results (HTML, CSV, JSON)
  - watch:     Schedule periodic scans with cron-like scheduling
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from finops import __version__
from finops.config import load_config, FinOpsConfig
from finops.scanner import Scanner
from finops.report import ReportGenerator
from finops.preflight import PreflightAnalyzer, Verdict

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="aws-finops-toolkit")
@click.option(
    "--config", "-c",
    type=click.Path(exists=True),
    default=None,
    help="Path to finops.yaml configuration file.",
)
@click.pass_context
def main(ctx: click.Context, config: Optional[str]) -> None:
    """AWS FinOps Toolkit — Find cost optimization opportunities in your AWS accounts."""
    ctx.ensure_object(dict)
    config_path = Path(config) if config else None
    ctx.obj["config"] = load_config(config_path)


@main.command()
@click.option(
    "--target", "-t",
    type=str,
    required=True,
    help="Target resource (instance ID, DB identifier, or service name).",
)
@click.option(
    "--profile", "-p",
    type=str,
    required=True,
    help="AWS profile for the target account.",
)
@click.option(
    "--region", "-r",
    type=str,
    default=None,
    help="AWS region. Defaults to profile default or us-east-1.",
)
@click.option(
    "--apm",
    type=click.Choice(["signoz", "datadog", "prometheus"]),
    default=None,
    help="APM provider for SLO/error budget data.",
)
@click.option(
    "--apm-endpoint",
    type=str,
    default=None,
    help="APM API endpoint URL (e.g., http://signoz.internal:3301).",
)
@click.option(
    "--output", "-o",
    type=click.Path(),
    default=None,
    help="Save pre-flight results to JSON file.",
)
@click.pass_context
def preflight(
    ctx: click.Context,
    target: str,
    profile: str,
    region: str,
    apm: Optional[str],
    apm_endpoint: Optional[str],
    output: Optional[str],
) -> None:
    """Run pre-flight analysis before optimizing a resource.

    Performs 9 checks: traffic, QoS/SLOs, cache dependency, incident history,
    access validation, target mapping, traffic patterns, priority/freeze status,
    and RI/SP coverage.

    Returns a GO / WAIT / STOP verdict with specific findings.

    Examples:

        finops preflight --target pn-sh-rds-prod --profile dodo-dev

        finops preflight -t i-0abc123 -p prod --apm signoz --apm-endpoint http://signoz:3301

        finops preflight -t gateway-server -p dodo-dev -o preflight.json
    """
    config: FinOpsConfig = ctx.obj["config"]
    effective_region = region or "us-east-1"

    console.print(f"\n[bold]AWS FinOps Toolkit[/bold] v{__version__} — Pre-Flight Analysis")
    console.print(
        f"Target: [cyan]{target}[/cyan]  Profile: [cyan]{profile}[/cyan]"
        f"  Region: [cyan]{effective_region}[/cyan]"
    )

    # Show which config sources are active
    pf = config.preflight
    apm_source = apm or pf.apm.get("provider", "cloudwatch")
    svc = pf.get_service(target) or pf.get_service_by_resource(target)
    if svc:
        console.print(f"Service: [cyan]{svc.name}[/cyan] (from service catalog, priority: {svc.priority})")
    console.print(
        f"APM: [cyan]{apm_source}[/cyan]  SLO: p99<{pf.slo.get('p99_latency_ms', 200)}ms,"
        f" {pf.slo.get('availability_pct', 99.9)}% avail\n"
    )

    # TODO: Create boto3 session from profile
    # session = boto3.Session(profile_name=profile, region_name=effective_region)
    session = None  # Scaffold — replace with real session

    analyzer = PreflightAnalyzer(config=config)
    result = analyzer.analyze(
        target=target,
        session=session,
        region=effective_region,
        apm_provider=apm,
        apm_endpoint=apm_endpoint,
    )

    # Display results
    verdict = result.verdict
    if verdict == Verdict.GO:
        verdict_style = "[bold green]GO — SAFE TO PROCEED[/bold green]"
    elif verdict == Verdict.WAIT:
        verdict_style = "[bold yellow]WAIT — RESOLVE WARNINGS FIRST[/bold yellow]"
    else:
        verdict_style = "[bold red]STOP — BLOCKING ISSUES FOUND[/bold red]"

    console.print(f"Verdict: {verdict_style}\n")
    console.print(f"[dim]{result.recommendation}[/dim]\n")

    # Show findings
    for finding in result.findings:
        if finding.severity.value == "blocker":
            icon = "[red]BLOCK[/red]"
        elif finding.severity.value == "warning":
            icon = "[yellow]WARN [/yellow]"
        else:
            icon = "[dim]INFO [/dim]"
        console.print(f"  {icon}  [{finding.check_name}] {finding.message}")

    if not result.findings:
        console.print("  [green]All 9 checks passed — no issues found.[/green]")

    # Save to file if requested
    if output:
        output_path = Path(output)
        output_path.write_text(json.dumps(result.to_dict(), indent=2, default=str))
        console.print(f"\n[green]Results saved to {output_path}[/green]")

    # Always save last preflight
    last_path = Path(".finops-last-preflight.json")
    last_path.write_text(json.dumps(result.to_dict(), indent=2, default=str))


@main.command()
@click.option(
    "--profile", "-p",
    type=str,
    default=None,
    help="AWS profile name to scan.",
)
@click.option(
    "--profiles",
    type=str,
    default=None,
    help="Comma-separated list of AWS profiles to scan.",
)
@click.option(
    "--org",
    is_flag=True,
    default=False,
    help="Scan all accounts in AWS Organizations.",
)
@click.option(
    "--role-name",
    type=str,
    default="FinOpsReadOnly",
    help="IAM role name to assume in member accounts (used with --org).",
)
@click.option(
    "--management-profile",
    type=str,
    default=None,
    help="AWS profile for the Organizations management account.",
)
@click.option(
    "--region", "-r",
    type=str,
    default=None,
    help="AWS region to scan. Defaults to profile default or us-east-1.",
)
@click.option(
    "--checks",
    type=str,
    default=None,
    help="Comma-separated list of checks to run (e.g., ec2_rightsizing,nat_gateway).",
)
@click.option(
    "--output", "-o",
    type=click.Path(),
    default=None,
    help="Save scan results to a JSON file for later reporting.",
)
@click.pass_context
def scan(
    ctx: click.Context,
    profile: Optional[str],
    profiles: Optional[str],
    org: bool,
    role_name: str,
    management_profile: Optional[str],
    region: Optional[str],
    checks: Optional[str],
    output: Optional[str],
) -> None:
    """Run cost optimization checks against your AWS accounts.

    Examples:

        finops scan --profile production

        finops scan --profiles dev,staging,prod --checks ec2_rightsizing,nat_gateway

        finops scan --org --role-name FinOpsReadOnly --management-profile mgmt
    """
    config: FinOpsConfig = ctx.obj["config"]

    # Determine which profiles to scan
    profile_list: list[str] = []
    if profiles:
        profile_list = [p.strip() for p in profiles.split(",")]
    elif profile:
        profile_list = [profile]
    elif config.accounts:
        profile_list = [a["profile"] for a in config.accounts if "profile" in a]

    if not profile_list and not org:
        console.print(
            "[red]Error:[/red] Specify --profile, --profiles, --org, or configure accounts in finops.yaml"
        )
        sys.exit(1)

    # Determine which checks to run
    check_names: Optional[list[str]] = None
    if checks:
        check_names = [c.strip() for c in checks.split(",")]

    # Run the scanner
    scanner = Scanner(config=config)
    console.print(f"\n[bold]AWS FinOps Toolkit[/bold] v{__version__}")
    console.print(f"Scan started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    if org:
        # TODO: Enumerate accounts via AWS Organizations API
        # Use management_profile to call organizations:ListAccounts
        # Then assume role_name in each member account
        console.print("[yellow]Organization scan — discovering accounts...[/yellow]")
        results = scanner.scan_organization(
            management_profile=management_profile or "default",
            role_name=role_name,
            region=region or "us-east-1",
            check_names=check_names,
        )
    else:
        results = scanner.scan_profiles(
            profiles=profile_list,
            region=region or "us-east-1",
            check_names=check_names,
        )

    # Display results in terminal using rich tables
    report_gen = ReportGenerator(config=config)
    report_gen.print_terminal(results)

    # Save results to file if requested
    if output:
        output_path = Path(output)
        output_path.write_text(json.dumps(results.to_dict(), indent=2, default=str))
        console.print(f"\n[green]Results saved to {output_path}[/green]")

    # Always save to .finops-last-scan.json for the report command
    last_scan_path = Path(".finops-last-scan.json")
    last_scan_path.write_text(json.dumps(results.to_dict(), indent=2, default=str))


@main.command()
@click.option(
    "--format", "-f",
    "output_format",
    type=click.Choice(["json", "csv", "html"]),
    default="html",
    help="Report output format.",
)
@click.option(
    "--input", "-i",
    "input_file",
    type=click.Path(exists=True),
    default=None,
    help="Input JSON file from a previous scan. Defaults to last scan.",
)
@click.option(
    "--output", "-o",
    type=click.Path(),
    default=None,
    help="Output file path.",
)
@click.pass_context
def report(
    ctx: click.Context,
    output_format: str,
    input_file: Optional[str],
    output: Optional[str],
) -> None:
    """Generate a report from scan results.

    Examples:

        finops report --format html --output report.html

        finops report --format csv --input scan-results.json --output costs.csv
    """
    config: FinOpsConfig = ctx.obj["config"]

    # Load scan results
    if input_file:
        scan_path = Path(input_file)
    else:
        scan_path = Path(".finops-last-scan.json")
        if not scan_path.exists():
            console.print("[red]Error:[/red] No scan results found. Run 'finops scan' first or specify --input.")
            sys.exit(1)

    with open(scan_path) as f:
        scan_data = json.load(f)

    report_gen = ReportGenerator(config=config)

    # Determine output path
    if output is None:
        ext = {"json": "json", "csv": "csv", "html": "html"}[output_format]
        output = f"finops-report.{ext}"

    output_path = Path(output)

    if output_format == "html":
        report_gen.generate_html(scan_data, output_path)
    elif output_format == "csv":
        report_gen.generate_csv(scan_data, output_path)
    elif output_format == "json":
        report_gen.generate_json(scan_data, output_path)

    console.print(f"[green]Report generated: {output_path}[/green]")


@main.command()
@click.option(
    "--schedule",
    type=str,
    default="0 8 * * 1",
    help="Cron expression for scan schedule. Default: every Monday at 8am.",
)
@click.option(
    "--profile", "-p",
    type=str,
    default=None,
    help="AWS profile name to scan.",
)
@click.option(
    "--format", "-f",
    "output_format",
    type=click.Choice(["json", "csv", "html"]),
    default="html",
    help="Report output format for each scheduled run.",
)
@click.option(
    "--output-dir",
    type=click.Path(),
    default="./finops-reports",
    help="Directory to store periodic reports.",
)
@click.pass_context
def watch(
    ctx: click.Context,
    schedule: str,
    profile: Optional[str],
    output_format: str,
    output_dir: str,
) -> None:
    """Schedule periodic scans with cron-like scheduling.

    Examples:

        finops watch --schedule "0 8 * * 1" --profile production

        finops watch --schedule "0 6 * * *" --profile prod --format html
    """
    # TODO: Implement cron-like scheduling using sched or APScheduler
    # For now, print the intended schedule and exit
    console.print("[bold]Watch mode[/bold]")
    console.print(f"  Schedule: {schedule}")
    console.print(f"  Profile:  {profile or 'default'}")
    console.print(f"  Format:   {output_format}")
    console.print(f"  Output:   {output_dir}/")
    console.print()
    console.print("[yellow]Watch mode is not yet implemented.[/yellow]")
    console.print("Tip: Use 'finops scan' with a system cron job or GitHub Actions schedule instead.")
    console.print("See examples/ci-integration.md for a GitHub Actions workflow.")


@main.command()
@click.option("--port", "-p", type=int, default=None, help="Port to serve on. Default: 8080.")
@click.option("--host", type=str, default=None, help="Host to bind to. Default: 127.0.0.1.")
@click.option("--no-browser", is_flag=True, default=False, help="Don't open browser on start.")
@click.option("--demo", is_flag=True, default=False, help="Start with demo data (no AWS creds needed).")
@click.pass_context
def dashboard(
    ctx: click.Context,
    port: Optional[int],
    host: Optional[str],
    no_browser: bool,
    demo: bool,
) -> None:
    """Launch the web dashboard.

    Examples:

        finops dashboard

        finops dashboard --port 9090 --host 0.0.0.0

        finops dashboard --demo
    """
    try:
        import uvicorn
    except ImportError:
        console.print("[red]Error:[/red] Web dependencies not installed.")
        console.print("Run: pip install aws-finops-toolkit[web]")
        sys.exit(1)

    config: FinOpsConfig = ctx.obj["config"]
    effective_host = host or config.web.host
    effective_port = port or config.web.port

    console.print(f"\n[bold]AWS FinOps Toolkit[/bold] v{__version__} — Dashboard")
    console.print(f"  URL: http://{effective_host}:{effective_port}")
    if demo:
        console.print("  Mode: [yellow]Demo (mock data)[/yellow]")
    console.print()

    if not no_browser:
        import webbrowser
        webbrowser.open(f"http://{effective_host}:{effective_port}")

    # Store config + demo flag for the FastAPI app
    import os
    os.environ["FINOPS_DEMO"] = "1" if demo else "0"

    uvicorn.run(
        "finops.app:create_app",
        factory=True,
        host=effective_host,
        port=effective_port,
        reload=config.web.debug,
    )


if __name__ == "__main__":
    main()
