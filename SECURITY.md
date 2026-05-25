# Security Hardening

This project runs financial automation, so assume hostile inputs and supply-chain risk.

## What Is Already Added

- GitHub Actions security workflow:
  - Dependency vulnerability scan with pip-audit
  - Static code scan with bandit
  - Secret leak scan with gitleaks
- Dependabot for weekly pip dependency update PRs

## Google Cloud Runtime Hardening

1. Use a dedicated service account with minimum permissions.
2. Do not store API keys in files on VM disks; use Secret Manager.
3. Restrict network ingress to only what is required.
4. Restrict egress where possible to known API hosts.
5. Enable Cloud Logging and alert on suspicious auth/network activity.
6. Keep OS image and base packages patched automatically.
7. If using containers, run non-root and use Artifact Registry vulnerability scanning.
8. Rotate Alpaca/OpenAI credentials on a regular schedule.

## Repo Hygiene

1. Never commit .env or credential files.
2. Review dependency update PRs before merge.
3. Keep branch protection enabled so scans must pass before merge.
4. Treat failed security scans as blockers for production deploys.
