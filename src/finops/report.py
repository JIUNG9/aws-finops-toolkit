"""Report Generator — Output scan results in multiple formats.

Supports:
  - Terminal output with rich tables (default, shown during scan)
  - JSON export (for CI/CD integration and programmatic access)
  - CSV export (for spreadsheets and data analysis)
  - HTML report (for sharing with management, email reports)
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, BaseLoader
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from finops.config import FinOpsConfig

console = Console()

# Inline HTML template as fallback when the template file isn't found
INLINE_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AWS FinOps Report — {{ scan_time }}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: #f5f7fa; color: #333; line-height: 1.6; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        h1 { font-size: 1.8rem; margin-bottom: 0.5rem; }
        .subtitle { color: #666; margin-bottom: 2rem; }
        .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                   gap: 1rem; margin-bottom: 2rem; }
        .card { background: white; border-radius: 8px; padding: 1.5rem;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .card h3 { font-size: 0.9rem; color: #666; text-transform: uppercase; }
        .card .value { font-size: 2rem; font-weight: 700; color: #1a73e8; }
        .card .value.savings { color: #0d9488; }
        .card .value.waste { color: #dc2626; }
        .section { margin-bottom: 2rem; }
        .section h2 { font-size: 1.3rem; margin-bottom: 1rem; padding-bottom: 0.5rem;
                      border-bottom: 2px solid #e5e7eb; }
        table { width: 100%; border-collapse: collapse; background: white;
                border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        th { background: #f8fafc; text-align: left; padding: 0.75rem 1rem;
             font-size: 0.85rem; color: #666; text-transform: uppercase; border-bottom: 2px solid #e5e7eb; }
        td { padding: 0.75rem 1rem; border-bottom: 1px solid #f0f0f0; }
        tr:hover { background: #f8fafc; }
        .severity-high { color: #dc2626; font-weight: 600; }
        .severity-medium { color: #f59e0b; font-weight: 600; }
        .severity-low { color: #10b981; }
        .footer { text-align: center; color: #999; font-size: 0.85rem; margin-top: 3rem;
                  padding-top: 1rem; border-top: 1px solid #e5e7eb; }
        .chart-placeholder { background: white; border-radius: 8px; padding: 2rem;
                            text-align: center; color: #999; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                            margin-bottom: 2rem; }
    </style>
</head>
<body>
    <div class="container">
        <h1>AWS FinOps Report</h1>
        <p class="subtitle">Scan: {{ scan_time }} | Accounts: {{ accounts|length }}</p>

        <div class="summary">
            <div class="card">
                <h3>Total Findings</h3>
                <div class="value">{{ total_findings }}</div>
            </div>
            <div class="card">
                <h3>Monthly Waste</h3>
                <div class="value waste">${{ "%.2f"|format(total_monthly_savings) }}</div>
            </div>
            <div class="card">
                <h3>Annual Savings</h3>
                <div class="value savings">${{ "%.2f"|format(total_annual_savings) }}</div>
            </div>
        </div>

        <div class="chart-placeholder">
            <!-- Savings by Category — Pie Chart Placeholder -->
            <p>Savings breakdown by check category</p>
            <p style="font-size: 0.8rem; margin-top: 0.5rem;">
                (Integrate Chart.js or D3.js here for interactive visualization)
            </p>
        </div>

        {% for account in accounts %}
        <div class="section">
            <h2>{{ account.account_name }} ({{ account.account_id }}) — {{ account.region }}</h2>

            {% if account.findings %}
            <table>
                <thead>
                    <tr>
                        <th>Resource</th>
                        <th>Type</th>
                        <th>Current Cost/mo</th>
                        <th>Recommended Action</th>
                        <th>Est. Savings/mo</th>
                        <th>Severity</th>
                    </tr>
                </thead>
                <tbody>
                    {% for f in account.findings %}
                    <tr>
                        <td><strong>{{ f.resource_id }}</strong><br><small>{{ f.resource_name }}</small></td>
                        <td>{{ f.resource_type }}</td>
                        <td>${{ "%.2f"|format(f.current_monthly_cost) }}</td>
                        <td>{{ f.recommended_action }}</td>
                        <td><strong>${{ "%.2f"|format(f.estimated_monthly_savings) }}</strong></td>
                        <td class="severity-{{ f.severity }}">{{ f.severity|upper }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <p>No optimization opportunities found.</p>
            {% endif %}

            {% if account.errors %}
            <div style="margin-top: 1rem; padding: 1rem; background: #fef2f2; border-radius: 8px;">
                <strong>Errors:</strong>
                <ul>
                    {% for error in account.errors %}
                    <li>{{ error }}</li>
                    {% endfor %}
                </ul>
            </div>
            {% endif %}
        </div>
        {% endfor %}

        <div class="footer">
            Generated by <strong>aws-finops-toolkit</strong> | {{ scan_time }}
        </div>
    </div>
</body>
</html>"""


class ReportGenerator:
    """Generate reports from scan results in various formats."""

    def __init__(self, config: FinOpsConfig) -> None:
        self.config = config

    def print_terminal(self, results: Any) -> None:
        """Print scan results as rich tables to the terminal.

        This is the default output shown after every scan.

        Args:
            results: A ScanResults object from the Scanner.
        """
        for account in results.accounts:
            # Account header
            console.print()
            console.print(Panel(
                f"[bold]Account:[/bold] {account.account_id} ({account.account_name})\n"
                f"[bold]Region:[/bold]  {account.region}",
                title="Scan Results",
            ))

            if not account.findings:
                console.print("  [green]No optimization opportunities found.[/green]\n")
                continue

            # Findings table
            table = Table(show_header=True, header_style="bold")
            table.add_column("Resource", style="cyan", min_width=20)
            table.add_column("Current Cost/mo", justify="right")
            table.add_column("Recommended Action", min_width=30)
            table.add_column("Est. Savings/mo", justify="right", style="green")

            for finding in account.findings:
                resource_label = f"{finding.resource_id}\n{finding.resource_name}"
                table.add_row(
                    resource_label,
                    f"${finding.current_monthly_cost:.2f}",
                    finding.recommended_action,
                    f"${finding.estimated_monthly_savings:.2f}/mo",
                )

            console.print(table)

            # Account summary
            console.print(
                f"\n  [bold]Total Monthly Waste:[/bold]  "
                f"[red]${account.total_monthly_waste:.2f}[/red]"
            )
            console.print(
                f"  [bold]Total Monthly Savings:[/bold] "
                f"[green]${account.total_monthly_savings:.2f}[/green]"
            )

            # Print errors if any
            if account.errors:
                console.print(f"\n  [yellow]Errors ({len(account.errors)}):[/yellow]")
                for error in account.errors:
                    console.print(f"    - {error}")

        # Grand totals
        console.print()
        console.print(Panel(
            f"[bold]Total Findings:[/bold]        {results.total_findings}\n"
            f"[bold]Total Monthly Savings:[/bold]  [green]${results.total_monthly_savings:.2f}[/green]\n"
            f"[bold]Total Annual Savings:[/bold]   [green]${results.total_annual_savings:.2f}[/green]",
            title="Summary",
            border_style="green",
        ))

    def generate_html(self, scan_data: dict[str, Any], output_path: Path) -> None:
        """Generate an HTML report from scan results.

        Uses a Jinja2 template for rendering. Falls back to an inline
        template if the template file is not found.

        Args:
            scan_data: Scan results as a dictionary (from ScanResults.to_dict()).
            output_path: Path to write the HTML file.
        """
        # Try to load the external template
        template_dir = Path(__file__).parent.parent.parent / "templates"
        template_file = template_dir / "report.html.j2"

        if template_file.exists():
            env = Environment(loader=FileSystemLoader(str(template_dir)))
            template = env.get_template("report.html.j2")
        else:
            # Fall back to inline template
            env = Environment(loader=BaseLoader())
            template = env.from_string(INLINE_HTML_TEMPLATE)

        html = template.render(**scan_data)
        output_path.write_text(html)

    def generate_csv(self, scan_data: dict[str, Any], output_path: Path) -> None:
        """Generate a CSV report from scan results.

        Flattens all findings across accounts into a single CSV file.

        Args:
            scan_data: Scan results as a dictionary.
            output_path: Path to write the CSV file.
        """
        fieldnames = [
            "account_id",
            "account_name",
            "region",
            "check_name",
            "resource_type",
            "resource_id",
            "resource_name",
            "current_monthly_cost",
            "recommended_action",
            "estimated_monthly_savings",
            "severity",
        ]

        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for account in scan_data.get("accounts", []):
                for finding in account.get("findings", []):
                    writer.writerow({
                        "account_id": account["account_id"],
                        "account_name": account["account_name"],
                        "region": account["region"],
                        "check_name": finding["check_name"],
                        "resource_type": finding["resource_type"],
                        "resource_id": finding["resource_id"],
                        "resource_name": finding["resource_name"],
                        "current_monthly_cost": finding["current_monthly_cost"],
                        "recommended_action": finding["recommended_action"],
                        "estimated_monthly_savings": finding["estimated_monthly_savings"],
                        "severity": finding["severity"],
                    })

    def generate_json(self, scan_data: dict[str, Any], output_path: Path) -> None:
        """Generate a formatted JSON report from scan results.

        Args:
            scan_data: Scan results as a dictionary.
            output_path: Path to write the JSON file.
        """
        output_path.write_text(json.dumps(scan_data, indent=2, default=str))
