# Example: Scan Multiple Accounts via AWS Organizations

## Architecture

```
Management Account (111111111111)
  |
  +-- finops-toolkit assumes FinOpsReadOnly role in each member account
  |
  +-- Dev Account (222222222222)
  +-- Staging Account (333333333333)
  +-- Production Account (444444444444)
```

## Prerequisites

1. AWS Organizations set up with a management account
2. A read-only IAM role deployed to all member accounts
3. Management account profile configured in AWS CLI

## Step 1: Create the IAM Role in Member Accounts

Deploy this IAM role to each member account (via CloudFormation StackSets or Terraform):

```json
{
    "AWSTemplateFormatVersion": "2010-09-09",
    "Description": "FinOps read-only role for aws-finops-toolkit",
    "Parameters": {
        "ManagementAccountId": {
            "Type": "String",
            "Description": "AWS Account ID of the management account"
        }
    },
    "Resources": {
        "FinOpsReadOnlyRole": {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "RoleName": "FinOpsReadOnly",
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {
                                "AWS": { "Fn::Sub": "arn:aws:iam::${ManagementAccountId}:root" }
                            },
                            "Action": "sts:AssumeRole"
                        }
                    ]
                },
                "ManagedPolicyArns": [
                    "arn:aws:iam::aws:policy/ViewOnlyAccess",
                    "arn:aws:iam::aws:policy/CloudWatchReadOnlyAccess"
                ]
            }
        }
    }
}
```

## Step 2: Configure the Management Account Profile

```ini
# ~/.aws/config

[profile mgmt]
region = us-east-1
# Management account credentials (SSO, IAM user, or instance role)
```

## Step 3: Scan via Organizations

```bash
# Scan all member accounts
finops scan --org --management-profile mgmt --role-name FinOpsReadOnly

# Scan with specific checks only
finops scan --org --management-profile mgmt --role-name FinOpsReadOnly --checks ec2_rightsizing,unused_resources

# Save results and generate a report
finops scan --org --management-profile mgmt --role-name FinOpsReadOnly --output org-scan.json
finops report --format html --input org-scan.json --output org-report.html
```

## Alternative: Profile-Based Multi-Account

If you don't use Organizations, configure profiles for each account and list them:

```ini
# ~/.aws/config

[profile dev]
region = us-east-1
role_arn = arn:aws:iam::222222222222:role/FinOpsReadOnly
source_profile = mgmt

[profile staging]
region = us-east-1
role_arn = arn:aws:iam::333333333333:role/FinOpsReadOnly
source_profile = mgmt

[profile production]
region = us-east-1
role_arn = arn:aws:iam::444444444444:role/FinOpsReadOnly
source_profile = mgmt
```

```bash
# Scan all profiles
finops scan --profiles dev,staging,production
```

Or configure them in `finops.yaml`:

```yaml
accounts:
  - profile: dev
    name: Development (222222222222)
  - profile: staging
    name: Staging (333333333333)
  - profile: production
    name: Production (444444444444)

checks:
  ec2_rightsizing: true
  nat_gateway: true
  spot_candidates: true
  unused_resources: true
  reserved_instances: true
  elasticache_scheduling: true
  rds_rightsizing: true
```

```bash
finops scan --config finops.yaml
```

## Output

The report will show findings grouped by account:

```
  Account: 222222222222 (Development)
  Region:  us-east-1
  Findings: 5 | Savings: $340.00/mo

  Account: 333333333333 (Staging)
  Region:  us-east-1
  Findings: 3 | Savings: $180.00/mo

  Account: 444444444444 (Production)
  Region:  us-east-1
  Findings: 8 | Savings: $1,200.00/mo

  Total Annual Savings: $20,640.00
```
