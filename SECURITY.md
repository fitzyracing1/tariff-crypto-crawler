# Security Policy

## Reporting
Please report vulnerabilities privately via GitHub Security Advisories
("Report a vulnerability" on the Security tab) rather than a public issue.

## Design guarantees
- Read-only: only HTTP GET. No posting, messaging, sign-ups, or form submission.
- Never contacts CBP/ACE systems (`cbp.gov`, `cbp.dhs.gov` are hard-blocked in `crawler/fetch.py`).
- Workflows use no secrets and least-privilege `permissions:` blocks. The optional X source
  only runs if `X_BEARER_TOKEN` is set locally; CI never sets it.
- CAPTCHAs/bot challenges are treated as a block and never solved or bypassed.
