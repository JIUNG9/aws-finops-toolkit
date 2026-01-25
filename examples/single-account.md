# Example: Scan a Single AWS Account

## Prerequisites

1. AWS CLI configured with a named profile
2. Profile must have read-only access (ViewOnlyAccess + CloudWatchReadOnlyAccess)

## Setup

```bash
# Verify your profile works
aws sts get-caller-identity --profile my-account

# Install the toolkit
pip install aws-finops-toolkit
```

## Run a Full Scan

```bash
finops scan --profile my-account
```

This runs all 7 checks against your account in the default region.

## Run Specific Checks Only

```bash
# Just EC2 and unused resources
finops scan --profile my-account --checks ec2_rightsizing,unused_resources

# Just NAT Gateway check
finops scan --profile my-account --checks nat_gateway
```

## Specify a Region

```bash
finops scan --profile my-account --region us-west-2
```

## Save Results and Generate a Report

```bash
# Save scan results to JSON
finops scan --profile my-account --output scan-results.json

# Generate an HTML report
finops report --format html --input scan-results.json --output report.html

# Generate a CSV for spreadsheet analysis
finops report --format csv --input scan-results.json --output findings.csv
```

## Use a Custom Configuration

Create `finops.yaml` in your project directory:

```yaml
thresholds:
  ec2_cpu_avg_percent: 15    # More aggressive: flag instances below 15% CPU
  snapshot_age_days: 60      # Flag snapshots older than 60 days
  idle_lb_days: 3            # Flag LBs idle for just 3 days

checks:
  ec2_rightsizing: true
  nat_gateway: true
  spot_candidates: false     # Skip Spot check
  unused_resources: true
  reserved_instances: false  # Skip RI check
  elasticache_scheduling: true
  rds_rightsizing: true
```

```bash
finops scan --profile my-account --config finops.yaml
```

## Minimum IAM Permissions

The following IAM policy provides the minimum permissions needed:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeInstances",
                "ec2:DescribeVolumes",
                "ec2:DescribeAddresses",
                "ec2:DescribeSnapshots",
                "ec2:DescribeNatGateways",
                "ec2:DescribeVpcs",
                "ec2:DescribeReservedInstances",
                "elasticloadbalancing:DescribeLoadBalancers",
                "elasticache:DescribeCacheClusters",
                "elasticache:ListTagsForResource",
                "rds:DescribeDBInstances",
                "rds:ListTagsForResource",
                "autoscaling:DescribeAutoScalingGroups",
                "eks:ListClusters",
                "eks:ListNodegroups",
                "eks:DescribeNodegroup",
                "cloudwatch:GetMetricStatistics",
                "sts:GetCallerIdentity"
            ],
            "Resource": "*"
        }
    ]
}
```
