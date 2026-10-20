# Changelog

## 0.3.0 - 2026-10-20

- Runtimes: the writer and the reviewer now run on Claude Code, Codex, Gemini, Qwen, Copilot, OpenCode or Cursor, or on any CLI through `runtime_command`. `libraryan init` detects an installed one (`--runtime NAME` to choose); `libraryan runtime [NAME] [--reviewer]` shows and switches it. Claude Code is stable; the others are experimental until smoke-tested.
- Worktree isolation: every model session runs in a throwaway git worktree. Only owned docs are copied back; stray code edits are discarded and listed in the report under "Ignored". A teammate's code edits during a run no longer fail it.
- Tool-neutral instructions: the agent and reviewer instructions no longer assume Claude Code. The writer deletes and moves with `git rm`/`git mv`; plain `rm`/`mv` are no longer granted to Claude Code and Copilot, and Gemini's are limited to relative paths inside the repo.
- A model session can never change Libraryan's own files (`.libraryan/`, its agent files and request skill): such changes are discarded and listed under "Ignored", and the reviewer always reads the committed instructions.
- Guard files per tool: the edit guard is installed in `.codex/hooks.json`, `.gemini/settings.json`, `.qwen/settings.json`, `.cursor/hooks.json` and `.opencode/plugins/libraryan.js` as well as `.claude/settings.json` (which Copilot also reads). In a nested repo or submodule without Libraryan the hooks pass. During a Libraryan run the guard (and Gemini's policy) also refuses shell commands with `--output` or `--no-index`, and a Claude agent file that claims a Libraryan agent name is discarded like Libraryan's own files. A `pre-push` hook refuses pushes while a run is active.
- Cost shows "unknown" for tools that do not report dollars; new turn caps `max_turns_run`, `max_turns_setup`, `max_turns_review` for runtimes without a USD cap.
- Config: `claude_bin` is now `runtime_bin` (the old key is still read). New keys `runtime`, `reviewer_runtime`, `reviewer_runtime_bin`, `runtime_command`.
- Upgrade: `pipx upgrade libraryan`, then `libraryan upgrade` in each project.

## 0.2.2 - 2026-10-20

- Fix: the instant edit guard missed edits made from GitHub Copilot CLI (it names the file `path`, not `file_path`) and patch-style edits (`apply_patch`, used by Codex and by GPT models in Copilot). It now blocks them before they happen. The git pre-commit lock was never affected.
- Upgrade: `pipx upgrade libraryan`, then `libraryan upgrade` in each project (refreshes the hook settings).

## 0.2.1 - 2026-10-20

- Fix: the run trace (`runs.jsonl`) and the run report could show far too few turns and seconds for a model call (seen: 1 turn and 14 s for a 5-minute setup run). Claude Code reported only the last resumed segment when the agent's self-review subagent ran in the background. Libraryan now runs Claude Code with background tasks disabled and measures each call's duration itself. Costs were always correct.
- Docs: describe Libraryan as vendor-neutral (plain Markdown, `AGENTS.md`, a git-hook lock that stops any agent); the runner itself uses Claude Code today.
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
