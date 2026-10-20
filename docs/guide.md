# Libraryan guide

Full reference. For the overview and quick start, see the [README](../README.md).

## Contents

- [What init changes](#what-init-changes)
- [Working with it](#working-with-it)
- [Commands](#commands)
- [Upgrade](#upgrade)
- [Configuration](#configuration)
- [Runtimes](#runtimes)
- [Reports](#reports)
- [Audit](#audit)
- [Uninstall](#uninstall)
- [Known limits](#known-limits)

## What init changes

1. Install commit (`docs(libraryan): install`) with:
   - `.libraryan/` (vendored runtime, `config.json`, `requests/`, templates; `state/` is gitignored)
   - `.claude/agents/libraryan.md` and `libraryan-reviewer.md`
   - `.claude/skills/libraryan-request/SKILL.md` (how to file a request)
   - the edit guard in each tool's hook file, merged in: `.claude/settings.json`, `.codex/hooks.json`, `.gemini/settings.json`, `.qwen/settings.json`, `.cursor/hooks.json` and `.opencode/plugins/libraryan.js` (plus a SessionStart hook re-enabling git hooks where the tool has one)
   - an `AGENTS.md` block (between `<!-- libraryan:start/end -->`) and `CLAUDE.md` importing `@AGENTS.md`
2. On this machine only (not committed): `core.hooksPath` set to `.libraryan/hooks` (existing hooks are chained), and a daily 03:00 cron job.
3. First setup run (your agent CLI, headless) creates the KB and is committed as a second commit.

Libraryan commits only on the default branch and never pushes.

## Working with it

Owned files (default: all `**/*.md`, `.claude/skills/**`, `.cursor/rules/**`, `.github/copilot-instructions.md`) cannot be edited directly:
each tool's edit guard blocks direct edits, and the pre-commit hook rejects commits touching them (deletions pass).
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

Independent review (`independent_review`, on by default): when a run has changes and its own checks pass, the runner starts a second, read-only run of the reviewer's tool (`libraryan-reviewer` instructions, runner-built prompt, no author summary) before committing. This is one extra model call per committing run. It fails closed: only the exact answer `APPROVE` passes; anything else, a timeout, or a reviewer that edits files fails the run. A setup run's review gets `max_usd_review_setup` and `setup_timeout_minutes`. Every model session runs in a throwaway git worktree under `.libraryan/state/wt`; only owned-doc changes are copied back. The author's stray code edits are discarded and listed in the report under "Ignored (outside owned paths, discarded)". A teammate's code edits during a run do not fail it; only an owned doc changed in the checkout during the run fails it (a transient failure, retried).

A model call that reports `is_error: true` in its JSON output (for example, its budget ran out mid-run) counts as failed even when it exits 0: the author's run fails and its work is not marked processed; a reviewer reporting it rejects.

Daily caps: an automatic run is skipped (outcome `capped`) once the UTC day has `max_runs_per_day` model runs or `max_commits_per_day` commits, or the last `max_consecutive_failures` runs failed or aborted, or the last `max_consecutive_transient_failures` did. Failures caused only by another agent's concurrent edits (an owned doc changed in the checkout, or files changed during the review) are traced with `"transient": true`; they do not count toward the first streak (and do not reset it) but do count toward the second, higher one. A capped run keeps the previous `reports/latest.md` (the report that tripped the cap) and appends the cap line to it. `python3 .libraryan/bin/libraryan run` (reason `manual`) and an explicit setup (`init`, `run --reason setup`) ignore the caps. A run that becomes a setup run because `<kb_root>/index.md` is missing (e.g. the first setup failed) is capped like any automatic run. Claude Code calls also get `--max-budget-usd` (`max_usd_run`, `max_usd_setup`, `max_usd_review`, `max_usd_review_setup`); other runtimes have no dollar cap (see Turn caps).

## Commands

Run `libraryan <cmd>` inside the project. The vendored `python3 .libraryan/bin/libraryan <cmd>` runs the same commands without the global tool, except `init` (global command only) and `upgrade` (hands off to the global command):

| Command | Does |
|---|---|
| `run [--reason R]` | Run Libraryan now (default reason `manual`) |
| `wait` | Wait out the debounce window, then run |
| `audit` | Deterministic docs-vs-code audit, no model call, always exit 0 (see below) |
| `stats [--days N]` | Per-day runs, model calls, commits, failures and cost from the run trace (default 7 days) |
| `check` | Lint docs and scan for secrets; exit 1 on problems |
| `init [--no-setup] [--runtime NAME]` | Install into this repo (global command only); the agent CLI is detected unless `--runtime` names it |
| `runtime [NAME] [--reviewer]` | Show the agent CLIs in use and found, or switch the writer (or, with `--reviewer`, the reviewer) to NAME |
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

The project's git hooks, tool hooks and cron job use the vendored copy in `.libraryan/`, so teammates do not need the tool installed unless they run commands themselves.

## Configuration

`.libraryan/config.json` (defaults shown):

| Key | Default | Meaning |
|---|---|---|
| `kb_root` | `docs/kb` | Where the knowledge base lives |
| `default_branch` | detected | Only branch Libraryan edits |
| `runner_host` | install host | Only this machine runs Libraryan |
| `runtime` | `claude` | Writer's tool: `claude`, `codex`, `gemini`, `qwen`, `copilot`, `opencode`, `cursor` or `command` |
| `runtime_bin` | `null` | Binary to run instead of the tool's default name (`claude_bin` from 0.2.x is still read as this) |
| `reviewer_runtime` / `reviewer_runtime_bin` | `null` | Reviewer's tool and binary; `null` means the same as the writer |
| `runtime_command` | `null` | Argv list for `runtime: command`, with `{prompt}` and `{instructions_file}` placeholders |
| `model` | `null` | Model for the writer |
| `debounce_minutes` | `10` | Quiet time after a commit before a run |
| `run_timeout_minutes` | `30` | Kill a run after this long |
| `setup_timeout_minutes` | `120` | Same, for the setup run; applies to the author and the reviewer each (up to 2× in total) |
| `max_usd_run` / `max_usd_setup` / `max_usd_review` | `5` / `25` / `2` | Per-call budget passed to `claude --max-budget-usd` (run, setup, reviewer); Claude Code only |
| `max_usd_review_setup` | `10` | Reviewer budget on a setup run |
| `max_turns_run` / `max_turns_setup` / `max_turns_review` | `60` / `200` / `30` | Turn caps, used only by runtimes without a USD cap |
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

## Runtimes

The writer and the reviewer each run on an agent CLI, set by `runtime` and `reviewer_runtime` (see Configuration). `libraryan init` detects an installed one; `libraryan runtime` shows what is in use and what is found, `libraryan runtime NAME` switches the writer and `libraryan runtime NAME --reviewer` the reviewer. Running the reviewer on a different tool from the writer gives a more independent review.

Status: Claude Code is stable. Every other runtime is experimental until a real smoke run (below).

| Runtime | Install | Login |
|---|---|---|
| `claude` | `npm install -g @anthropic-ai/claude-code` | run `claude setup-token` and export `CLAUDE_CODE_OAUTH_TOKEN`, or set `ANTHROPIC_API_KEY` |
| `codex` | `npm install -g @openai/codex` | `codex login --device-auth`, or export `CODEX_API_KEY` |
| `gemini` | `npm install -g @google/gemini-cli` | export `GEMINI_API_KEY` (or `GOOGLE_API_KEY`, or the Vertex AI variables) |
| `qwen` | `npm install -g @qwen-code/qwen-code` | export `OPENAI_API_KEY` (and `OPENAI_BASE_URL`, or another provider's key); Qwen OAuth's free tier has ended |
| `copilot` | `npm install -g @github/copilot` (Node.js 22+) | export `COPILOT_GITHUB_TOKEN` (fine-grained PAT with the "Copilot Requests" permission; classic `ghp_` tokens are unsupported) |
| `opencode` | `npm install -g opencode-ai` | export the provider's key (for example `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) |
| `cursor` | `curl https://cursor.com/install -fsS \| bash` | export `CURSOR_API_KEY` |
| `command` | set `runtime_command` | whatever that tool needs |

Cron has no shell profile: put the key where cron can see it, and check the tool works non-interactively from cron.

**Guards and trust.** The edit guard is installed for every tool, in its own project file (see What init changes). A tool must trust the project before it loads the guard: in Codex, review the project hooks once with `/hooks`; in Gemini and Copilot, trust the folder. If `.cursor/` or `.codex/` is gitignored in your repo, the hook file is never committed, so teammates do not get that guard (the git pre-commit lock still applies). A `pre-push` hook refuses any push while a Libraryan run is active.

**Custom command.** Set `runtime: "command"` and `runtime_command` to an argv list. To start with it, write `runtime_command` into `.libraryan/config.json` and commit that file before `libraryan init --runtime command` (init refuses uncommitted Libraryan files). `{prompt}` is replaced by the prompt and `{instructions_file}` by the path of the instructions. Libraryan treats exit 0 with non-empty output as success. There is no dollar or turn cap; only the run timeout bounds it. Recipes:

```json
{"runtime": "command", "runtime_command": ["aider", "--yes-always", "--no-auto-commits", "--no-dirty-commits", "--message", "{prompt}"]}
{"runtime": "command", "runtime_command": ["amp", "-x", "{prompt}"]}
```

The Amp recipe needs `AMP_API_KEY` set (the token stored by `amp login` is rejected). Pair these recipes with a different reviewer (`libraryan runtime claude --reviewer`, or any other runtime): the reviewer must answer exactly `APPROVE`, and Aider and Amp never do, so with them as reviewer every run fails. Check each recipe with the smoke checklist before relying on it.

**Turn caps.** `max_turns_run`, `max_turns_setup` and `max_turns_review` (defaults 60, 200, 30) apply only to runtimes that have a turn flag but no USD cap (Qwen today). Runtimes with neither are bounded only by the run timeout.

**Cost.** Claude Code reports dollars. OpenCode does when it reports a price. The others show "unknown" in the report and `libraryan stats` (never a guess), and the USD budgets do not apply to them.

**Smoke checklist.** For each runtime you want to rely on, in a throwaway repo:

1. Install and log in, `libraryan init --runtime NAME`, and confirm `libraryan runtime` shows it as found.
2. Run `libraryan run` (the first one is a setup run). Confirm: exit 0 and a `docs(libraryan)` commit; `reports/latest.md` has a sensible summary; cost and turns show as expected ("unknown" is fine).
3. Edit an owned doc with that tool and confirm the guard blocks it (after the trust step above).
4. Make the author touch a code file (or edit one yourself mid-run) and confirm it is listed under "Ignored" and the working tree is untouched.
5. File a request, run again, and confirm the reviewer (the same or another tool) answers `APPROVE` and the doc changes.

When all five pass on a real account, remove the "experimental" label for that runtime in the README and this guide.

## Reports

Each run writes `.libraryan/state/reports/<timestamp>.md` and `.libraryan/state/reports/latest.md` (gitignored). Read `latest.md` for what changed, problems, cost ("unknown" for tools that do not report dollars), the deletion ledger, "Ignored (outside owned paths, discarded)" and "Possible code issues".

Every run, including skipped ones, also appends a line to `.libraryan/state/runs.jsonl` (this replaces `runs.log`). Outcomes: `noop`, `deferred`, `capped`, `audited`, `nothing_changed`, `committed`, `failed`, `aborted`. `libraryan stats` summarises it.

## Audit

`libraryan audit` checks owned docs against the repo using paths only (no symbols): `broken-link`, `missing-path` (a backticked path that does not exist), and for KB notes `not-indexed`, `unsourced`, `missing-source`, `stale` (source changed after the note's `updated` date) and `duplicate-title`. Findings are leads, not a gate. The runner passes them to the model on runs that happen anyway.

## Uninstall

`libraryan uninstall` (or `python3 .libraryan/bin/libraryan uninstall`). Restores `core.hooksPath`, removes the cron line and commits the removal.

## Known limits

- `LIBRARYAN=1` in the environment bypasses the lock; any process can set it. The upgrade path is a CI check.
- `git commit --no-verify` skips the pre-commit hook and bypasses the lock the same way.
- An agent with no guard hook (or a tool that has not trusted the project) that edits an owned doc while a run is in progress makes that run fail (retried later); the edit is not committed as Libraryan's.
- Hooks and cron run `python3` from PATH and need Python >= 3.10 (macOS's `/usr/bin/python3` may be older).
- Cron runs without your shell profile: make sure your agent CLI works non-interactively from cron (auth stored, not on a PATH that only nvm or your profile sets up).
- Requests from teammates that arrive by `git pull` wait for your next local commit or the 03:00 run.
- Edits made through Bash are only caught at commit time.
- Claude Code is the only stable runtime; all others are experimental until a real smoke run.
- Some runtimes cannot restrict shell commands per run: the Qwen author, Cursor with `--force`, OpenCode and a custom command. Files in the repo are protected by the throwaway copy and the owned-paths-only copy-back, and the `pre-push` hook blocks pushes while a run is active; but a runtime with unrestricted shell could still touch files outside the repo or run other commands, so run those only on machines and accounts you trust.
- Cost shows "unknown" for tools that do not report dollars, and the USD budgets do not apply to them.
- Teammates' clones get the lock when their tool's SessionStart hook enables the git hooks there, but they do not run Libraryan.
- Windows is unsupported.
