# Libraryan guide

Full reference. For the overview and quick start, see the [README](../README.md).

## Contents

- [What init changes](#what-init-changes)
- [Working with it](#working-with-it)
- [Commands](#commands)
- [Upgrade](#upgrade)
- [Configuration](#configuration)
- [Reports](#reports)
- [Audit](#audit)
- [Uninstall](#uninstall)
- [Known limits](#known-limits)

## What init changes

1. Install commit (`docs(libraryan): install`) with:
   - `.libraryan/` (vendored runtime, `config.json`, `requests/`, templates; `state/` is gitignored)
   - `.claude/agents/libraryan.md` and `libraryan-reviewer.md`
   - `.claude/skills/libraryan-request/SKILL.md` (how to file a request)
   - `.claude/settings.json` hooks merged in (PreToolUse guard on Edit/Write, SessionStart hook re-enabling git hooks)
   - an `AGENTS.md` block (between `<!-- libraryan:start/end -->`) and `CLAUDE.md` importing `@AGENTS.md`
2. On this machine only (not committed): `core.hooksPath` set to `.libraryan/hooks` (existing hooks are chained), and a daily 03:00 cron job.
3. First setup run (Claude Code, headless) creates the KB and is committed as a second commit.

Libraryan commits only on the default branch and never pushes.

## Working with it

Owned files (default: all `**/*.md`, `.claude/skills/**`, `.cursor/rules/**`, `.github/copilot-instructions.md`) cannot be edited directly:
the Claude Code hook blocks Edit/Write, and the pre-commit hook rejects commits touching them (deletions pass).
To change docs, add a Markdown file under `.libraryan/requests/` (see the `libraryan-request` skill) and commit it.
After a commit, Libraryan waits `debounce_minutes` for quiet, then runs and commits the doc updates.
A failed run is retried only after the next commit or by `run` (see `reports/latest.md`); the daily health check is skipped when nothing was committed since the last one.
Before any model call, Libraryan runs `libraryan audit` (below). A daily health check with no requests and no new commits ends there at no cost (outcome `audited`) when the audit finds nothing, or only findings the last completed model health run was already shown (kept in `state/last_health_findings.json`); a new finding gets a model run. When the agent verifies a `stale` note is still accurate it bumps the note's `updated` date, so the finding stops recurring.

Docs vs code: if docs contradict the code, Libraryan fixes the docs; suspected code bugs go under "Possible code issues" in the report.
Outdated or junk Markdown is deleted after still-valid facts are moved into the KB (git history keeps everything).

Deletion-ledger rule: a deleted owned doc is accepted only if it is a pure move (identical content now exists at a new owned path) or the run's output says where its facts went, one line per doc:

```
Moved: <old> => <new>
Fact: <deleted> => <dest> | <quote from deleted> | <quote from dest>
Fact: <deleted> => none | <reason>
```

`Moved:` needs a destination owned by Libraryan and at least 50% similar to the original. `Fact:` quotes (15+ characters) are checked against the deleted file in HEAD and the destination. Anything else fails the run and the deletion is restored.

Independent review (`independent_review`, on by default): when a run has changes and its own checks pass, the runner starts a second, read-only `claude -p` run (agent `libraryan-reviewer`, runner-built prompt, no author summary) before committing. This is one extra model call per committing run. It fails closed: only the exact answer `APPROVE` passes; anything else, a timeout, or a reviewer that edits files fails the run. A setup run's review gets `max_usd_review_setup` and `setup_timeout_minutes`. If another agent changes non-owned files during a run, the run fails before the reviewer is called.

A model call that reports `is_error: true` in its JSON output (for example, its budget ran out mid-run) counts as failed even when it exits 0: the author's run fails and its work is not marked processed; a reviewer reporting it rejects.

Daily caps: an automatic run is skipped (outcome `capped`) once the UTC day has `max_runs_per_day` model runs or `max_commits_per_day` commits, or the last `max_consecutive_failures` runs failed or aborted, or the last `max_consecutive_transient_failures` did. Failures caused only by another agent's concurrent edits (non-owned paths changed, or files changed during the review) are traced with `"transient": true`; they do not count toward the first streak (and do not reset it) but do count toward the second, higher one. A capped run keeps the previous `reports/latest.md` (the report that tripped the cap) and appends the cap line to it. `python3 .libraryan/bin/libraryan run` (reason `manual`) and an explicit setup (`init`, `run --reason setup`) ignore the caps. A run that becomes a setup run because `<kb_root>/index.md` is missing (e.g. the first setup failed) is capped like any automatic run. Each model call also gets `--max-budget-usd` (`max_usd_run`, `max_usd_setup`, `max_usd_review`, `max_usd_review_setup`).

## Commands

Run `libraryan <cmd>` inside the project. The vendored `python3 .libraryan/bin/libraryan <cmd>` runs the same commands without the global tool, except `init` (global command only) and `upgrade` (hands off to the global command):

| Command | Does |
|---|---|
| `run [--reason R]` | Run Libraryan now (default reason `manual`) |
| `wait` | Wait out the debounce window, then run |
| `audit` | Deterministic docs-vs-code audit, no model call, always exit 0 (see below) |
| `stats [--days N]` | Per-day runs, model calls, commits, failures and cost from the run trace (default 7 days) |
| `check` | Lint docs and scan for secrets; exit 1 on problems |
| `init [--no-setup]` | Install into this repo (global command only) |
| `upgrade` | Refresh the project's vendored copy, hooks, agents and skill from the installed version, and commit (the vendored bin runs the global `libraryan upgrade`) |
| `uninstall` | Remove hooks, cron, agent files, `.libraryan/` and the AGENTS.md block; commit. The KB stays |

Internal (called by hooks/cron): `precommit`, `postcommit`, `guard`, `ensure-hooks`, `chainpath`.
`libraryan --version` prints the installed version.

## Upgrade

```
pipx upgrade libraryan
libraryan upgrade        # in each project; commits the refreshed vendored copy
```

From a pre-0.2 source-checkout install: `pipx install libraryan`, then run `libraryan upgrade` in the project.
`upgrade` refuses to replace a project installed by a newer version; run `pipx upgrade libraryan` first.

The project's git hooks, Claude Code hooks and cron job use the vendored copy in `.libraryan/`, so teammates do not need the tool installed unless they run commands themselves.

## Configuration

`.libraryan/config.json` (defaults shown):

| Key | Default | Meaning |
|---|---|---|
| `kb_root` | `docs/kb` | Where the knowledge base lives |
| `default_branch` | detected | Only branch Libraryan edits |
| `runner_host` | install host | Only this machine runs Libraryan |
| `claude_bin` / `model` | `claude` / `null` | Claude Code binary and model |
| `debounce_minutes` | `10` | Quiet time after a commit before a run |
| `run_timeout_minutes` | `30` | Kill a run after this long |
| `setup_timeout_minutes` | `120` | Same, for the setup run; applies to the author and the reviewer each (up to 2× in total) |
| `max_usd_run` / `max_usd_setup` / `max_usd_review` | `5` / `25` / `2` | Per-call budget passed to `claude --max-budget-usd` (run, setup, reviewer) |
| `max_usd_review_setup` | `10` | Reviewer budget on a setup run |
| `max_runs_per_day` | `24` | Daily cap on runs that call the model |
| `max_commits_per_day` | `12` | Daily cap on Libraryan commits |
| `max_consecutive_failures` | `3` | Stop automatic runs after this many failed or aborted runs in a row (transient failures excluded) |
| `max_consecutive_transient_failures` | `10` | Same, counting transient failures too |
| `independent_review` | `true` | Run the reviewer before every commit |
| `reviewer_model` | `null` | Model for the reviewer (falls back to `model`) |
| `review_timeout_minutes` | `15` | Kill a reviewer call after this long (setup runs use `setup_timeout_minutes`) |
| `language` | `en` | Language of the docs |
| `owned` / `excluded` | see `config.py` | Globs Libraryan owns / ignores |
| `exempt` | `[]` | Owned-looking paths people may still edit |
| `chain_hooks_path` | detected | Pre-existing hooks dir to chain to |
| `installed_version` | set by init/upgrade | Libraryan version that last wrote the vendored copy |

## Reports

Each run writes `.libraryan/state/reports/<timestamp>.md` and `.libraryan/state/reports/latest.md` (gitignored). Read `latest.md` for what changed, problems, cost, the deletion ledger, and "Possible code issues".

Every run, including skipped ones, also appends a line to `.libraryan/state/runs.jsonl` (this replaces `runs.log`). Outcomes: `noop`, `deferred`, `capped`, `audited`, `nothing_changed`, `committed`, `failed`, `aborted`. `libraryan stats` summarises it.

## Audit

`libraryan audit` checks owned docs against the repo using paths only (no symbols): `broken-link`, `missing-path` (a backticked path that does not exist), and for KB notes `not-indexed`, `unsourced`, `missing-source`, `stale` (source changed after the note's `updated` date) and `duplicate-title`. Findings are leads, not a gate. The runner passes them to the model on runs that happen anyway.

## Uninstall

`libraryan uninstall` (or `python3 .libraryan/bin/libraryan uninstall`). Restores `core.hooksPath`, removes the cron line and commits the removal.

## Known limits

- `LIBRARYAN=1` in the environment bypasses the lock; any process can set it. The upgrade path is a CI check.
- `git commit --no-verify` skips the pre-commit hook and bypasses the lock the same way.
- A non-Claude agent (no guard hook) that edits an owned doc while a run is in progress can have that edit committed as Libraryan's.
- Hooks and cron run `python3` from PATH and need Python >= 3.10 (macOS's `/usr/bin/python3` may be older).
- Cron runs without your shell profile: make sure `claude` works non-interactively from cron (auth stored, not on a PATH that only nvm or your profile sets up).
- A run fails (and is retried on the next trigger) when another agent edits code while Libraryan runs.
- Requests from teammates that arrive by `git pull` wait for your next local commit or the 03:00 run.
- Edits made through Bash are only caught at commit time.
- Claude Code is the only supported runtime.
- Teammates' clones get the lock when Claude Code's SessionStart hook enables the git hooks there, but they do not run Libraryan.
- Windows is unsupported.
