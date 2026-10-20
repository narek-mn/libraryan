# Changelog

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
