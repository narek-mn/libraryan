---
description: Show Libraryan health for this project (stats, audit, latest report)
allowed-tools: Bash(libraryan stats:*), Bash(libraryan audit:*), Read
---

If `.libraryan/` does not exist in the repo root, say Libraryan is not installed here and suggest `/libraryan:init`.

Otherwise run `libraryan stats` and `libraryan audit` (if `libraryan` is not on PATH, use `python3 .libraryan/bin/libraryan` instead), and read `.libraryan/state/reports/latest.md` if it exists.

Summarise briefly: recent runs, failures and cost; audit findings grouped by kind (they are leads, not errors); the outcome and any problems or "Possible code issues" from the latest report. Suggest a next step only if something needs attention.
