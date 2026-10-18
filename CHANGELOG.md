# Changelog

Notable changes to this project. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[PEP 440](https://peps.python.org/pep-0440/).

## [Unreleased]

### Fixed

- Every `github.com/junegu` link pointed at a different person's GitHub account. That
  handle exists and returns 200, so nothing looked broken — but the clone command in
  the README and CONTRIBUTING 404'd, the `pyproject.toml` Homepage / Repository /
  Issues URLs that PyPI renders pointed at a stranger, and so did the "GitHub" link
  in the running dashboard's nav bar and in every generated HTML report. All corrected
  to `JIUNG9`.
- Medium handle corrected to `@June-Gu`.
- Tech-stack table claimed Python 3.9+ while `pyproject.toml` requires `>=3.10`.
- Dropped a `junegu@example.com` placeholder from `authors`.

### Added

- `elasticache_scheduling` now queries AWS. Replication-group nodes are reported once per
  group, a prod-tagged member protects the whole group, and a cluster whose tags can't
  be read is skipped instead of being treated as non-prod. The advice no longer says to
  "stop" a cluster (ElastiCache has no stop); it says snapshot, delete, restore.
- `unused_resources` now finds unattached EBS volumes in real AWS. It pages through
  `DescribeVolumes` with a server-side `status=available` filter, prices each volume
  from the existing gp3/gp2/io1 table (io2 uses the io1 rate), and flags it for
  deletion — `high` severity from $50/month up, `medium` below. The other four
  sub-checks in that module (EIPs, old snapshots, idle load balancers, stopped
  instances) are still commented out.
- `tests/test_unused_resources_live.py`: 7 tests that assert on findings. Moto for real
  volumes, attachments and tags; botocore `Stubber` for a two-page `NextToken` walk and
  an aged `CreateTime`, both of which moto can't produce. Suite 77 -> 84.
- CI, license, Python and test-count badges. CI has been green for months with nothing
  in the README to show it.
- `SECURITY.md`, scoped to what actually matters here: credential leakage into logs,
  reports, the SQLite database or LLM prompts; bypassing the error-budget safety gate;
  and template injection via AWS-supplied resource names.
- This changelog.

### Changed

- The EBS finding reports `age_days` (from `CreateTime`), not the `days_unattached` the
  commented-out draft used, and the action text says "created N days ago". AWS doesn't
  expose a detach time, so the draft's wording claimed something the data can't back.
- Test count stated as **70**, which is what `pytest` collects. The README and several
  other documents said 44.

## [0.2.0] — 2026-04-04

The release that turned a CLI into a platform.

### Added

- **Web dashboard** — FastAPI + Jinja2 + HTMX, with Chart.js for cost trends and a
  D3.js service dependency graph.
- **Three more cost checks**, bringing the total to 10: `vpc_waste`,
  `cloudwatch_waste`, `s3_lifecycle`.
- **Safety analyzer** — the five-step gate (traffic analysis, dependency check,
  error-budget gate, AI analysis, confirmation) that has to pass before any
  recommendation is presented as safe to execute.
- **Error-budget tracking** — SLO targets, burn rate, incident timeline.
- **Financial budgets** — budget vs actual with forecasting.
- Alerts, import/export, and an onboarding wizard.
- Pluggable LLM backend (Claude or OpenAI) for recommendations.
- API endpoint tests and a CI workflow.

### Fixed

- All flake8 and mypy findings across the source tree and tests.

### Changed

- Dropped Python 3.9; minimum is now 3.10.

## [0.1.0] — 2026-01-25

Initial release: a CLI that scans AWS accounts for waste.

### Added

- 7 cost checks across EC2, NAT gateways, Spot candidates, unused resources, reserved
  instances, ElastiCache scheduling and RDS rightsizing.
- Multi-account scanning via named AWS profiles.
- Three output formats — rich terminal, HTML and CSV/JSON.
- Tests using `moto`, so the suite runs without touching real AWS.

[Unreleased]: https://github.com/JIUNG9/aws-finops-toolkit/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/JIUNG9/aws-finops-toolkit/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/JIUNG9/aws-finops-toolkit/releases/tag/v0.1.0
