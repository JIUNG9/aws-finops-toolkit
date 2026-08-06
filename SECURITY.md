# Security Policy

## Reporting a vulnerability

**Please don't open a public issue for a security problem.**

Report it privately through GitHub:
[**Report a vulnerability**](https://github.com/JIUNG9/aws-finops-toolkit/security/advisories/new)

That opens an advisory visible only to you and the maintainer — no email address to
track down, and nothing public until there's a fix.

> **Maintainer note:** that link requires *Private vulnerability reporting* to be
> switched on under **Settings → Advanced Security**. It's one checkbox and it's
> free on public repos. Until it's enabled the URL 404s for outside reporters, so
> turn it on before pointing anyone at this policy.

### What helps

- What the issue is, and what an attacker gets out of it
- Steps to reproduce, or a proof of concept
- The affected version or commit
- A suggested fix, if you have one in mind

### What to expect

This is a personally maintained project rather than a funded product, so response is
best-effort: acknowledgement within a few days, and a fix prioritised by severity.
If something is being actively exploited, say so in the first line.

## Supported versions

Only the latest release gets fixes. Earlier versions are not maintained.

## Scope

This tool reads AWS accounts with credentials you supply and serves a local web
dashboard, so the sharp edges are:

- **Credential handling** — anything that writes an access key, session token or
  account identifier into a log line, an HTML report, the SQLite database, or an
  LLM prompt.
- **The safety gate** — a path that lets a recommendation be marked safe to execute
  without passing the error-budget, traffic and dependency checks. The whole premise
  is that nothing gets cut while a service is burning budget; a bypass is a security
  issue, not a feature request.
- **The dashboard** — template injection or XSS via scanned resource names, which
  come from AWS and shouldn't be trusted as markup.
- **LLM prompts** — resource metadata reaching a third-party model when the pluggable
  AI backend is configured, beyond what the docs say is sent.

Out of scope: findings that only apply to `--demo` mode, which serves fixture data
with deliberately fake account IDs.
