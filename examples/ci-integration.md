# Example: Run FinOps Scan in GitHub Actions as a Weekly Report

Automate your FinOps review by running aws-finops-toolkit on a schedule and posting results to Slack or saving as an artifact.

## GitHub Actions Workflow

Create `.github/workflows/finops-weekly.yml`:

```yaml
name: Weekly FinOps Scan

on:
  schedule:
    # Every Monday at 8:00 AM UTC
    - cron: '0 8 * * 1'
  workflow_dispatch:  # Allow manual triggering

permissions:
  id-token: write   # For OIDC authentication
  contents: read

jobs:
  finops-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install aws-finops-toolkit
        run: pip install aws-finops-toolkit

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::111111111111:role/GitHubActionsFinOps
          aws-region: us-east-1

      - name: Run FinOps scan
        run: |
          finops scan --profiles dev,staging,production --output scan-results.json

      - name: Generate HTML report
        run: |
          finops report --format html --input scan-results.json --output finops-report.html

      - name: Generate CSV report
        run: |
          finops report --format csv --input scan-results.json --output finops-report.csv

      - name: Upload reports as artifacts
        uses: actions/upload-artifact@v4
        with:
          name: finops-reports-${{ github.run_number }}
          path: |
            finops-report.html
            finops-report.csv
            scan-results.json
          retention-days: 90

      # Optional: Post summary to Slack
      - name: Extract savings summary
        id: summary
        run: |
          SAVINGS=$(python3 -c "
          import json
          data = json.load(open('scan-results.json'))
          monthly = data['total_monthly_savings']
          annual = data['total_annual_savings']
          findings = data['total_findings']
          print(f'Found {findings} optimizations. Monthly savings: \${monthly:,.2f}. Annual savings: \${annual:,.2f}.')
          ")
          echo "text=${SAVINGS}" >> $GITHUB_OUTPUT

      - name: Post to Slack
        if: success()
        uses: slackapi/slack-github-action@v1.25.0
        with:
          payload: |
            {
              "text": "Weekly FinOps Report: ${{ steps.summary.outputs.text }}\n\nFull report: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
            }
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
```

## IAM Role for GitHub Actions

Create an IAM role that GitHub Actions can assume via OIDC:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Federated": "arn:aws:iam::111111111111:oidc-provider/token.actions.githubusercontent.com"
            },
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {
                    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                },
                "StringLike": {
                    "token.actions.githubusercontent.com:sub": "repo:your-org/your-repo:*"
                }
            }
        }
    ]
}
```

Attach the ViewOnlyAccess and CloudWatchReadOnlyAccess managed policies, plus sts:AssumeRole for cross-account access.

## Customizing the Schedule

Common cron schedules:

| Schedule | Cron Expression | Use Case |
|----------|----------------|----------|
| Weekly (Monday 8am) | `0 8 * * 1` | Standard weekly review |
| Daily (6am) | `0 6 * * *` | Active cost reduction projects |
| Bi-weekly (1st and 15th) | `0 8 1,15 * *` | Lighter-touch monitoring |
| Monthly (1st of month) | `0 8 1 * *` | Monthly executive report |

## Tracking Savings Over Time

Save scan results to a persistent store (S3, database) to track trends:

```yaml
      - name: Upload to S3 for trend tracking
        run: |
          DATE=$(date +%Y-%m-%d)
          aws s3 cp scan-results.json s3://my-finops-bucket/scans/${DATE}.json
```

Then build a dashboard from the historical data to show savings progress month-over-month.
