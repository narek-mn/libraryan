# Libraryan multi-runtime (v0.3): design

Status: draft for approval · 2026-10-20 · extends `2026-10-19-libraryan-design.md` and `2026-10-19-libraryan-hardening-design.md`

Research: `docs/research/runtimes/` (one file per tool, verified against each tool's `--help`, docs and source, late 2026).

## 1. Intent

Libraryan must be a vendor- and model-agnostic agent. Two things must hold on any AI coding tool:

1. **Libraryan runs on it.** The writer and the independent reviewer can be any supported agent CLI, not only Claude Code.
2. **Teammates on it are stopped early.** An agent in any supported tool is blocked the moment it tries to edit an owned doc, where the tool allows that, and always at commit time by the git hook.

The user's words: "libraryan must run on anything, codex, gemini, claude code, cursor, ... this must be fully vendor and model agnostic". No manual setup: `libraryan init` must pick a working tool by itself.

Why it is feasible without weakening anything: Libraryan's guarantees never came from the model or from Claude Code's permissions. The runner snapshots and diffs the tree, restores non-owned paths, checks lint, secrets and the deletion ledger, runs the independent reviewer, and commits only owned paths. The git pre-commit hook locks every tool. Those parts stay. Two things change: the layer that **starts a model session and reads its result** becomes pluggable, and every model session runs in an **isolated copy of the repo** (§5.0), so a tool with coarse permissions can never leave stray edits in the real checkout.

## 2. Goals

1. **Runtimes.** Built-in adapters for: Claude Code, Codex CLI, Gemini CLI, Qwen Code, GitHub Copilot CLI, Cursor CLI, OpenCode. A generic `command` runtime covers any other tool (Aider, Amp, Goose, Crush, future tools).
2. **Auto-detect.** `init` finds installed runtimes and picks one without asking. `libraryan runtime` shows what is in use and what was found; `libraryan runtime <name>` switches.
3. **Writer and reviewer may differ.** `runtime` and `reviewer_runtime` (default: same). A different vendor for the reviewer makes the review more independent.
4. **Early guard on every tool that supports project hooks.** `init` installs the edit guard for all supported tools, not only the one Libraryan runs on, because teammates may use any of them.
5. **Same safety on every runtime.** Every runtime goes through the same snapshot, checks, ledger, reviewer and commit path. A runtime that fails or prints nothing counts as failed (fail closed).
6. **Honest cost.** USD is recorded when the tool reports it (Claude Code, OpenCode). Otherwise cost is `null`, shown as "unknown", and tokens are recorded when reported. **Decided by the user:** no price table; spending is limited by time, turns and runs per day.

## 3. Non-goals

- Libraryan's own agent loop calling model APIs directly. It would rebuild a coding agent (file tools, sandbox) that every CLI already has; the research and the base design both say don't build a custom tool layer. Model choice comes through the CLIs: Codex, Copilot, Qwen and OpenCode all reach OpenAI-compatible endpoints and local models (Ollama).
- A price table to estimate dollars.
- Built-in Aider support: no JSON output, exits 0 on model failure, auto-commits, and its commits skip git hooks by default. It is reachable through the `command` runtime with documented flags.
- Windows.

## 4. Anti-goals

- A runtime whose failure looks like success. Known traps: Cursor prints no JSON on failure and `is_error` is always false; Gemini `-o json` puts fatal errors on stderr with empty stdout; Aider exits 0 on model errors. Each adapter must define "success" positively (a final result present and no error signal), never as "no error seen".
- A made-up cost.
- A runtime that weakens the gates. No adapter may skip snapshot, checks, ledger, reviewer, or owned-path-only commits.
- Hidden manual steps. Where a tool needs trust or a one-time approval for hooks (Codex per-hook trust, Gemini and Copilot folder trust), Libraryan passes the per-run flag or env for its own runs, and states in `init` output and the guide what a teammate's tool needs. It never silently installs a guard that cannot fire.
- Breaking existing installs. A project installed with 0.2.x keeps running on Claude Code after `upgrade`, with the same behaviour and config.

## 5. Design

### 5.0 Isolated workspace (all runtimes)

Today Claude Code's tool allowlist and the in-run guard keep the author away from code, and non-owned edits are reported, never restored, because they may be a teammate's concurrent work in the same checkout. Codex `workspace-write`, Cursor `--force` and OpenCode cannot express "owned docs only", so that model breaks for them.

New model, the same for every runtime including Claude Code:

1. The runner creates a temporary git worktree at the commit being processed, under `.libraryan/state/` (gitignored), with the runtime files Libraryan needs.
2. The author runs **in the worktree**. The independent reviewer runs in the same worktree, read-only.
3. After checks pass, the runner copies only owned-path changes (adds, edits, deletes, moves) from the worktree into the real checkout and commits them with the existing owned-paths-only commit. Everything else the model did in the worktree is discarded with it.
4. The worktree is removed in all outcomes, including timeout and crash; a leftover one is removed at the next run's start.

Consequences:

- A stray code edit by any model can no longer reach the real checkout, whatever the tool's permissions.
- A teammate editing code in the real checkout during a run no longer fails the run. The `FOREIGN`/transient failure path stays only for owned docs that changed in the real checkout during the run; that run fails and retries as today.
- Snapshot, baseline and restore logic shrinks: the real checkout is touched only in step 3.
- Plain file operations (`rm`, `mv`) become safe for the author, which the neutral instructions need (§5.2).
- Ceiling: a worktree checkout costs time and disk on very large repos. Accepted; a sparse checkout can come later if the pilot shows it matters.

### 5.1 Runtime adapter

One module per runtime under `libraryan/runtimes/`, all with the same small interface. Shape (names left to the builder):

- `detect() -> version | None`: binary on PATH and `--version` works.
- `command(role, prompt, cfg, budget) -> (argv, extra_env)`: role is `author` or `reviewer`. Builds a headless, non-interactive call with:
  - the instructions (§5.2),
  - permissions for the role (§5.3),
  - limits (§5.4),
  - machine-readable output,
  - flags that keep cron runs safe (no auto-update, trust for this run, no background tasks).
- `parse(stdout, stderr, exit_code) -> (text, usage, ok)`: usage has `cost_usd` (or `null`), `tokens` (or `null`), `turns` (or `null`), `is_error`. `ok` is true only when a final result is present and no error signal exists.
- `guard_files()`: project files that install the early edit guard and session-start hook for that tool (§5.5).

`_call_model` keeps owning process groups, timeouts, wall-clock duration and the child environment. It asks the adapter for argv and parsing only.

The `command` runtime is configured in `config.json`:

```json
"runtime": "command",
"runtime_command": ["aider", "--yes-always", "--no-auto-commits", "--no-dirty-commits", "--message", "{prompt}"]
```

`{prompt}` is replaced; `{instructions_file}` is also available. Output is treated as plain text, cost and tokens are `null`, and success is exit code 0 plus non-empty output. The guide documents tested recipes (at least Aider, Amp).

### 5.2 Instructions

The agent instructions (today `.claude/agents/libraryan.md` and `libraryan-reviewer.md`) become runtime-neutral Markdown in `.libraryan/agents/`. Each adapter delivers them the way its tool accepts:

- Claude Code: `--agent` with the `.claude/agents/` files, as today (still installed, also used for the self-review subagent).
- Copilot: `--agent` reads the same `.claude/agents/` files (verified).
- Others: the runner prepends the instructions to the prompt. This always works, needs no tool-specific file, and keeps the instructions in the runner's control.

The instructions become tool-neutral: "delete the file", "move the file", "search the repo", never a specific tool name. The runner already detects deletions and pure moves by content, so the author no longer needs `git rm`/`git mv`. The Claude Code allowlist gains plain `rm`/`mv`, which is safe inside the worktree (§5.0). Each adapter may append a short "tools you have" note for its tool (Claude Code: Glob, Grep, Agent).

The run prompt itself (requests, audit findings, baseline) is unchanged.

The self-review subagent step in the author instructions becomes optional: "if your tool can start a subagent, ask the reviewer; otherwise check your own work against the checklist." The runner's independent reviewer is the gate either way.

### 5.3 Permissions per role

- **Author:** may edit files and run read-only git commands plus `python3 .libraryan/bin/libraryan check|audit`. Must not commit, push, or edit outside the tree.
- **Reviewer:** read-only.

Each adapter maps this to its tool's own controls. The research files list the exact flags. Examples:

- Codex: author `workspace-write`, reviewer `read-only` (the `exec` default); `.git` stays read-only under `workspace-write`, so commits fail.
- Copilot: `--allow-tool`/`--deny-tool`, with `shell(git commit)` and `shell(git push)` denied.
- Cursor: `--force` (without it, `-p` silently makes no edits) for the author, `--mode ask` for the reviewer.

Where a tool cannot express a restriction, the runner's post-run checks still restore anything outside owned paths and refuse the run. Runtime permissions are defence in depth, not the guarantee.

Known traps to handle:

- **Gemini:** plan mode can switch itself to yolo in headless runs, so the reviewer uses a per-run `--policy` file (kept under `.libraryan/`) that denies writes instead. The reviewer's read-only check (snapshot before and after) stays as the backstop.
- **Codex:** `.git` read-only under `workspace-write` is fine now: the author no longer uses git write commands (§5.2).
- **Settings-only controls** (Gemini's `maxSessionTurns`, Qwen's deny rules): Libraryan does **not** write them into the project's `.gemini/` or `.qwen/` settings, because those apply to every teammate's sessions. These tools get the runner timeout, flag-based caps where a flag exists (Qwen `--max-session-turns`), and the worktree isolation.

### 5.4 Limits and cost

- **Per call:**
  - always the runner's wall-clock timeout (exists today);
  - plus the tool's own cap where one exists: Claude `--max-budget-usd`; Qwen `--max-session-turns`/`--max-wall-time`; Gemini `maxSessionTurns`; OpenCode agent `steps`; Copilot `--max-ai-credits`.
- **New config `max_turns_run` / `max_turns_setup` / `max_turns_review`** (defaults 60 / 200 / 30, calibrated from pilot traces), used only by runtimes that support a turn cap **and** have no USD cap. Claude Code keeps its USD caps and gets no new turn cap, so existing installs behave as before.
- **Daily caps** (`max_runs_per_day`, `max_commits_per_day`, failure streaks): unchanged, runtime-independent.
- **Trace and report:**
  - `cost_usd: null` reads "cost unknown";
  - `tokens` is recorded when reported;
  - `libraryan stats` prints known cost plus "N calls with unknown cost".
- **Existing USD config keys** keep working and apply where a runtime supports a USD cap.

### 5.5 Early edit guard on every tool

`cchooks.guard` already understands Claude Code, Copilot (`path`) and `apply_patch` payloads (0.2.2). `init`/`upgrade`/`uninstall` manage one project hook file per tool family:

| Tool | Project file | Blocks with | Notes |
|---|---|---|---|
| Claude Code, Copilot | `.claude/settings.json` (exists) | exit 2 | Copilot reads Claude hooks (verified) |
| Cursor | `.cursor/hooks.json` `preToolUse` | `{"permission":"deny"}` or exit 2 | native file, because Cursor's loading of Claude hooks is unreliable across versions; experimental until smoke-tested |
| Codex | `.codex/hooks.json` | exit 2 | matcher includes `apply_patch` and `Bash`. Codex loads it only after the teammate trusts the project and the hook once (`/hooks`); `init` says so. Libraryan never writes to the user's `~/.codex/config.toml`. Libraryan's own Codex runs don't need it: they are isolated (§5.0) |
| Gemini CLI | `.gemini/settings.json` `hooks.BeforeTool` | exit 2 | also sets `context.fileName` to include `AGENTS.md`; needs folder trust |
| Qwen Code | `.qwen/settings.json` `hooks.PreToolUse` | exit 2 | Claude-compatible payload |
| OpenCode | `.opencode/plugin/libraryan.js` | throw | small plugin that calls the guard |

The guard command uses a path relative to the repo root found via `git rev-parse --show-toplevel`, because `$CLAUDE_PROJECT_DIR` exists only in Claude Code and Qwen. Hook files are merged, never overwritten, with the existing `merge_settings`/`strip_settings` pattern, and are added to the installer's path list.

The `AGENTS.md` block stays the universal instruction to every agent. Tools that read a different file get a pointer: `CLAUDE.md` (exists), `GEMINI.md` via the Gemini setting above, `QWEN.md` if the tool needs it.

### 5.6 Detection and selection

- **`init` picks a runtime:** the first installed one in a fixed preference order: Claude Code, Codex, Gemini, Qwen, Copilot, OpenCode, Cursor. The order follows how reliably each tool behaves headless in the research: clear failure signals, a real read-only mode for the reviewer, and stable flags. Cost reporting is a tiebreaker only; OpenCode (dev branch is a rewrite) and Cursor (silent no-edit and no-JSON failures) come last.
- **`--runtime <name>`** on `init` overrides the choice.
- **`init` refuses with a plain message** when no runtime is found; the message lists how to install one.
- **Auth is not probed with a paid call.** `init` prints the env var or login each tool needs for unattended runs. The first run's report says plainly if auth failed.
- **Upgrade:** existing projects get `runtime: "claude"`. `claude_bin` stays as an alias for `runtime_bin`.

### 5.7 Tests

- No test calls a real model (unchanged rule).
- Each adapter gets a fake binary under `tests/` that prints the output shapes recorded in `docs/research/runtimes/`: success, error, budget or turn cap hit, and the silent-failure traps in §4.
- The runner's existing scenario tests run against at least three adapters (Claude, Codex, one plain-text `command`).
- Guard tests cover each tool's payload shape.
- A manual smoke checklist in the guide (one real run per runtime) is run before release, by whoever has the accounts. Runtimes not smoke-tested are marked "experimental" in the README.

## 6. Constraints

Unchanged: Python 3.10+ stdlib only, Unix only, never touch other projects, the runner is the only committer, never push. Each adapter's flags are pinned to the tool versions in the research files, and `detect()` records the version in the trace so drift can be spotted.

## 7. Decided by the user

- Libraryan must run on any tool and protect against edits from any tool.
- Tools that don't report dollars: limit by time, turns and runs per day; show cost as unknown; no price table.
- The guard bug (Copilot `path`, Codex `apply_patch`) is fixed now, separately, in 0.2.2.

## 8. Builder's calls (flagged)

- Instructions are prepended to the prompt for all tools except Claude Code and Copilot. This is one universal path, instead of a per-tool agent-file format.
- Aider is supported only through the `command` runtime.
- The guard is installed for all supported tools by default. One `.json` or `.js` file per tool family is a small cost, and teammates' tools are unknown at install time.
- Preference order in §5.6.
- Every runtime, including Claude Code, runs in a temporary worktree, and only owned-path changes are copied back (§5.0). This answers "what if a tool with coarse permissions edits code" with one mechanism instead of per-tool rules.
- Neutral instructions with plain `rm`/`mv`; Claude Code's allowlist gains them (§5.2).
- Turn caps only where no USD cap exists; setup gets its own, higher cap (§5.4).
- Cursor gets a native `.cursor/hooks.json` and stays experimental until smoke-tested (§5.5).
- Libraryan never writes to a user's home config (for example Codex project trust). Teammates trust Codex hooks themselves; the git lock covers them until then.
- No Libraryan settings in the project's `.gemini/` or `.qwen/` files (§5.3).
- Default turn caps (60 / 30) are guesses until the pilot.
- Runtimes without a smoke run are released as "experimental".

## 9. Left to the builder

Exact flags and output parsing per tool (from `docs/research/runtimes/`), module layout under `libraryan/runtimes/`, the `libraryan runtime` output format, OpenCode plugin code, and wording of `init` messages.
