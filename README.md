# aws-finops-toolkit

**Find $40,000/year in AWS waste in 5 minutes.**

A CLI tool that scans your AWS accounts and tells you exactly where you're wasting money and how to fix it. Built from real-world experience reducing cloud costs by 30% (~$40K/year) across 5 AWS accounts.

---

## Why This Exists

Every AWS account has waste hiding in plain sight: oversized EC2 instances running at 8% CPU, NAT Gateways in dev environments burning $30/day, forgotten EBS volumes, idle load balancers. Finding this manually means clicking through the console for hours. This tool does it in minutes.

## Features

- **EC2 / EKS Right-Sizing** — Find instances running at <20% CPU and recommend downsizing
- **NAT Gateway Cost Detection** — Flag expensive NAT Gateways in non-production environments
- **Spot Instance Candidates** — Identify stateless workloads that could run on Spot (60-70% savings)
- **Unused Resource Detection** — Catch unattached EBS volumes, unused EIPs, old snapshots, idle ALBs
- **Reserved Instance Recommendations** — Calculate RI and Savings Plans ROI for always-on workloads
- **ElastiCache Scheduling** — Detect dev/staging clusters that should be stopped off-hours
- **RDS Right-Sizing** — Find oversized databases and unnecessary Multi-AZ in non-prod
- **Multi-Account Support** — Scan across AWS Organizations or a list of profiles
- **Multiple Output Formats** — Rich terminal tables, JSON, CSV, HTML reports

## Quick Start

```bash
pip install aws-finops-toolkit
```

```bash
# Scan a single account
finops scan --profile my-aws-profile

# Scan specific checks only
finops scan --profile my-aws-profile --checks ec2_rightsizing,nat_gateway

# Scan all accounts in your AWS Organization
finops scan --org --role-name FinOpsReadOnly

# Generate an HTML report
finops report --format html --output report.html
```

## Example Output

```
$ finops scan --profile production

  AWS FinOps Toolkit — Scan Results
  Account: 123456789012 (production)
  Region:  us-east-1
  Scanned: 2026-03-08 14:30 UTC

  ┌─────────────────────────┬──────────────────────┬─────────────────────────────────────┬──────────────┐
  │ Resource                │ Current Cost/mo      │ Recommended Action                  │ Est. Savings │
  ├─────────────────────────┼──────────────────────┼─────────────────────────────────────┼──────────────┤
  │ i-0a1b2c3d (web-prod)   │ $292.00 (m5.2xlarge) │ Downsize to m5.xlarge (avg CPU 12%) │ $146.00/mo   │
  │ i-0e4f5a6b (worker-01)  │ $146.00 (m5.xlarge)  │ Downsize to m5.large (avg CPU 8%)   │ $73.00/mo    │
  │ nat-0abc1234 (dev-vpc)  │ $32.40               │ Replace with NAT Instance (t3.nano) │ $28.00/mo    │
  │ vol-0ff1234a (detached) │ $80.00 (800GB gp3)   │ Delete — unattached for 45 days     │ $80.00/mo    │
  │ eip-01234abc            │ $3.60                │ Release — not associated             │ $3.60/mo     │
  │ snap-0a1b2c (290 days)  │ $12.50               │ Delete — older than 90 days          │ $12.50/mo    │
  │ asg-staging-workers     │ $438.00 (3x m5.xl)   │ Switch to Spot Instances             │ $306.00/mo   │
  │ redis-dev-001           │ $97.20 (r6g.large)   │ Schedule off-hours (stop 8pm-8am)   │ $48.60/mo    │
  │ mydb-staging (Multi-AZ) │ $584.00 (r5.xlarge)  │ Convert to Single-AZ                │ $292.00/mo   │
  └─────────────────────────┴──────────────────────┴─────────────────────────────────────┴──────────────┘

  Total Monthly Waste Found:  $1,685.80
  Total Annual Savings:       $20,229.60

  Detailed report: finops report --format html --output finops-report.html
```

## Supported Checks

| Check | Description | Typical Savings |
|-------|-------------|-----------------|
| `ec2_rightsizing` | Find EC2 instances with avg CPU < 20% over 14 days, recommend smaller type | 30-50% per instance |
| `nat_gateway` | Detect NAT Gateways in dev/staging, flag unused gateways (0 bytes) | $30-45/month per gateway |
| `spot_candidates` | Identify stateless ASGs / EKS node groups suitable for Spot | 60-70% per instance |
| `unused_resources` | Unattached EBS, unused EIPs, old snapshots, idle load balancers, stopped instances | Varies widely |
| `reserved_instances` | Recommend RIs or Savings Plans for 24/7 on-demand production workloads | 30-40% per instance |
| `elasticache_scheduling` | Dev/staging ElastiCache clusters that can be stopped off-hours | ~50% per cluster |
| `rds_rightsizing` | Oversized RDS instances, unnecessary Multi-AZ in non-prod | 30-50% per instance |

## Multi-Account Support

### Via AWS Organizations

```bash
finops scan --org --role-name FinOpsReadOnly --management-profile mgmt
```

The tool assumes a read-only role in each member account. See [examples/multi-account.md](examples/multi-account.md) for IAM role setup.

### Via Profile List

```bash
finops scan --profiles dev,staging,production
```

Or define accounts in `config/default.yaml`:

```yaml
accounts:
  - profile: dev
    name: Development
  - profile: staging
    name: Staging
  - profile: production
    name: Production
```

## Report Output Formats

| Format | Command | Use Case |
|--------|---------|----------|
| Terminal | `finops scan` (default) | Interactive review, quick checks |
| JSON | `finops report --format json` | CI/CD integration, programmatic access |
| CSV | `finops report --format csv` | Import to spreadsheets, data analysis |
| HTML | `finops report --format html` | Share with management, email reports |

## Architecture

```
                         ┌───────────────────┐
                         │   finops scan     │
                         │   (CLI entry)     │
                         └────────┬──────────┘
                                  │
                         ┌────────▼──────────┐
                         │     Scanner       │
                         │  (orchestrator)   │
                         └────────┬──────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
     ┌────────▼───────┐ ┌────────▼───────┐ ┌────────▼───────┐
     │  AWS Account 1 │ │  AWS Account 2 │ │  AWS Account N │
     │  (assume role) │ │  (assume role) │ │  (assume role) │
     └────────┬───────┘ └────────┬───────┘ └────────┬───────┘
              │                   │                   │
              └───────────┬───────┘───────────────────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
   ┌──────▼─────┐ ┌──────▼─────┐ ┌──────▼─────┐
   │ EC2 Right- │ │ NAT Gate-  │ │ Unused     │  ... (all checks)
   │ sizing     │ │ way Check  │ │ Resources  │
   └──────┬─────┘ └──────┬─────┘ └──────┬─────┘
          │               │               │
          └───────────────┼───────────────┘
                          │
                 ┌────────▼──────────┐
                 │   Report Engine   │
                 │ (terminal/json/   │
                 │  csv/html)        │
                 └───────────────────┘
```

## Configuration

Create a `finops.yaml` or use the defaults:

```yaml
thresholds:
  ec2_cpu_avg_percent: 20      # Flag instances below this CPU %
  ec2_lookback_days: 14        # CloudWatch metrics lookback window
  snapshot_age_days: 90        # Flag snapshots older than this
  idle_lb_days: 7              # Flag LBs with 0 connections for this many days
  stopped_instance_days: 7     # Flag stopped instances older than this

accounts: []                   # List of account profiles to scan

checks:
  ec2_rightsizing: true
  nat_gateway: true
  spot_candidates: true
  unused_resources: true
  reserved_instances: true
  elasticache_scheduling: true
  rds_rightsizing: true
```

## Requirements

- Python 3.9+
- boto3 (AWS SDK)
- AWS credentials with read-only access (SecurityAudit policy or equivalent)
- Recommended IAM policy: `ViewOnlyAccess` + `CloudWatchReadOnlyAccess`

## Installation

### From PyPI

```bash
pip install aws-finops-toolkit
```

### From Source

```bash
git clone https://github.com/junegunn/aws-finops-toolkit.git
cd aws-finops-toolkit
pip install -e ".[dev]"
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License. See [LICENSE](LICENSE).

## Author

**June Gu** — Site Reliability Engineer at NAVER Corporation (Placen)

- Previously: Coupang (NYSE: CPNG), Hyundai IT&E, Lotte Shopping
- 5+ years building and optimizing cloud infrastructure on AWS
- This tool is based on real FinOps work across multi-account AWS environments

LinkedIn: [June Gu](https://www.linkedin.com/in/junegu)
