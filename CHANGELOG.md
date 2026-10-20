# Changelog

## 0.2.1 - 2026-10-20

- Fix: the run trace (`runs.jsonl`) and the run report could show far too few turns and seconds for a model call (seen: 1 turn and 14 s for a 5-minute setup run). Claude Code reported only the last resumed segment when the agent's self-review subagent ran in the background. Libraryan now runs Claude Code with background tasks disabled and measures each call's duration itself. Costs were always correct.
- Upgrade: `pipx upgrade libraryan`, then `libraryan upgrade` in each project.

## 0.2.0 - 2026-10-20

First public release.

- Installable with `pipx install libraryan`; new `libraryan init` and `libraryan --version`.
- `libraryan upgrade` refreshes a project from the installed version and refuses downgrades.
- Run trace (`.libraryan/state/runs.jsonl`) and `libraryan stats`.
- Per-call and daily cost caps.
- Deletion ledger: a deleted doc must show where its facts went.
- Independent reviewer gates every commit (fails closed).
- `libraryan audit`: deterministic docs-vs-code check; quiet daily runs cost nothing.
- Claude Code plugin: `/plugin marketplace add narek-mn/libraryan`, then `/libraryan:init`, `/libraryan:status`, `/libraryan:request`.
- Reproducible demo project (`examples/demo`) and full guide (`docs/guide.md`).

## 0.1.0

- First version: single-writer lock, requests, event-driven runs, setup, uninstall.
