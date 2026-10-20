# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.2.x | Yes |
| < 0.2 | No |

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting: go to the repository's **Security** tab and choose **Report a vulnerability**. Include what you found, how to reproduce it, and the affected version (`libraryan --version`).

You can expect an acknowledgement within a few days. This is a volunteer-maintained project, so fix timing is best effort.

## Scope notes

- The single-writer lock is a guardrail, not a security boundary. As listed under "Known limits" in the README, `LIBRARYAN=1` in the environment and `git commit --no-verify` both bypass it. Reports that only demonstrate these bypasses are expected behaviour.
- Secret scanning with [gitleaks](https://github.com/gitleaks/gitleaks) is optional. Libraryan does not guarantee that secrets are caught.
- Libraryan runs Claude Code on your machine with your credentials; review what you let it commit.
