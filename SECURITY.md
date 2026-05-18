# Security Policy

## Supported versions

| Version | Status |
|---|---|
| 0.1.x | Supported |
| < 0.1 | Not supported (pre-release; do not use in production) |

## Reporting a vulnerability

If you find a security issue in oak, please report it privately. Do not file a public GitHub issue.

Email: **security@oak.dev** (placeholder - maintainers should update with a real address)

Include:
- A description of the issue
- Steps to reproduce
- Affected versions / packages (oak-workspace, oak-session, oak)
- Your assessment of impact (information disclosure, code execution, denial of service, etc.)
- A suggested fix if you have one

## Disclosure timeline

We aim to:
- Acknowledge receipt within 72 hours
- Provide an initial assessment within 7 days
- Coordinate a patch and disclosure within 90 days of report

If a vulnerability is being actively exploited in the wild, we will accelerate.

## Scope

In scope:
- The `oak-workspace`, `oak-session`, and `oak` packages in this repository
- The first-party reference backends shipped under each package

Out of scope:
- Vulnerabilities in third-party provider SDKs (E2B, Redis, etc.) - report to the upstream
- Vulnerabilities in community-maintained adapter packages - report to that package's maintainer
- Issues affecting the user's own code, system prompts, or domain logic - not oak's surface

## What we will not do

- Run a bug bounty program (until further notice)
- Issue CVEs for issues in unsupported pre-0.1 versions
- Provide patches for unsupported versions

Thank you for helping keep oak users safe.
