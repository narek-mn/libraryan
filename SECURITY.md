# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.4.x | Yes |
| < 0.4 | No |

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting: go to the repository's **Security** tab and choose **Report a vulnerability**. Include what you found, how to reproduce it, and the affected version (`libraryan --version`).

You can expect an acknowledgement within a few days. This is a volunteer-maintained project, so fix timing is best effort.

## Scope notes

- `libraryan fix` runs Claude Code on your machine, with your credentials, in a throwaway git worktree. Only `.md` changes are copied back, and nothing is committed; read the diff before you keep it.
- The agent may only run read-only git commands plus `git rm` and `git mv`, and edits files through Claude Code's own tools.
