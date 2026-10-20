# Aider as a Libraryan runtime

Researched 2026-10-20 against PyPI `aider-chat` **0.86.2**. `--help` was read from a local venv and behaviour
was checked in the installed source.

Maintenance signal: 0.86.2 (released 2026-02-12) is the only release since August 2025. The last push to the
repo was 2026-05-22.

Sources:
- Options: https://aider.chat/docs/config/options.html
- Scripting: https://aider.chat/docs/scripting.html
- Conventions: https://aider.chat/docs/usage/conventions.html
- Git: https://aider.chat/docs/git.html
- OpenAI-compatible APIs: https://aider.chat/docs/llms/openai-compat.html
- Ollama: https://aider.chat/docs/llms/ollama.html
- Repo: https://github.com/Aider-AI/aider

Aider is **not an agentic tool loop** like the other runtimes. It edits only the files added to the chat,
using a repo map for context, and has no tool permission system, hooks or agents. It fits Libraryan only as a
"writer given an explicit file list" runtime.

## 1. Headless invocation

```
aider --message "<prompt>" --yes-always --no-auto-commits --no-dirty-commits --no-pretty --no-stream \
      --no-check-update --analytics-disable --no-gitignore --no-show-release-notes \
      --file docs/a.md --file docs/b.md --read AGENTS.md
```

- `--message/-m` (or `--message-file/-f`) processes one message, then exits ("disables chat mode").
- There is no stdin prompt mode.
- **Exit codes:** `main()` returns `0` after `--message`, even when the LLM call failed. Startup and config
  errors return `1`. Model or API failures are therefore visible **only in the output text** (verified in
  `aider/main.py`: the `--message` branch returns `None`, which exits 0).

## 2. Machine-readable output

- **No JSON or JSONL output.**
- Cost is a plain-text line printed after each LLM call: `Tokens: N sent, M received. Cost: $X message, $Y session.`
  (`base_coder.py`). Parse it with a regex.
- There is no turn count and no error flag.
- `--llm-history-file` logs raw LLM traffic. `--chat-history-file` (default `.aider.chat.history.md`) keeps a
  Markdown transcript.
- The Python API (`Coder.create(...)`, which exposes `coder.total_cost`) is "not officially supported or
  documented".

## 3. Instructions, persona, auto-read files

- **No named agents, modes per persona, or AGENTS.md support.** A grep of the source finds no AGENTS.md.
- Instructions come in as read-only context files: `--read CONVENTIONS.md`, or `read: [..]` in
  `.aider.conf.yml`.
- Config search order: `.aider.conf.yml` in the git root, then cwd, then home. `.env` is loaded from the git
  root (`--env-file`).
- `--chat-mode/--edit-format`: `code`, `ask` (no edits), `architect`.
- Edit formats: `diff`, `whole`, `udiff`, and others.

## 4. Permissions and sandbox

- **No allow/deny lists and no sandbox.** Scope is controlled by which files are passed:
  - `--file` files are editable.
  - `--read` files are read-only.
  - `.aiderignore` hides files.
  - `--subtree-only` limits the repo map.
- **Catch:** the model can ask to add other files, or create new ones. `--yes-always` auto-confirms "Add file
  to the chat?" prompts.
- **Shell commands are NOT run under `--yes-always`.** The shell prompt uses `explicit_yes_required=True`, and
  `io.confirm_ask` answers `"n"` in that case (`io.py`). `--no-suggest-shell-commands` stops the model from
  suggesting them at all.
- **Git: aider auto-commits by default.** Disable it with `--no-auto-commits` (env `AIDER_AUTO_COMMITS=false`)
  and `--no-dirty-commits` (the latter stops it committing pre-existing dirty files first).
- Aider never pushes.
- **`--git-commit-verify` defaults to False, so aider's own commits use `--no-verify` and bypass git pre-commit
  hooks.** Disable commits entirely rather than relying on hooks.
- `--no-git` turns git integration off completely.
- Read-only options: `--chat-mode ask`, or `--dry-run` (no file writes).

## 5. Budget and limits

- **No budget, max-turns or max-cost flag.**
- Reflection loops (lint and test fix-ups) are capped at a hard-coded `max_reflections = 3`.
- `--timeout` sets the per-API-call timeout.
- `--max-chat-history-tokens` and `--map-tokens` bound context size.

## 6. Hooks

- **None.** There is no pre-edit hook or session-start hook.
- The closest mechanisms:
  - `--lint-cmd` / `--test-cmd` with `--auto-lint` / `--auto-test` run after edits (post-hoc).
  - `--load <file>` runs `/commands` at launch.
- Enforcement must happen outside aider: pass only allowed files with `--file`, then diff and revert the
  owned docs afterwards. Libraryan already snapshots and diffs.

## 7. Subagents, skills, commands

- No subagents and no skills.
- In-chat `/commands` are built in (`/add`, `/read`, `/run`, `/test`, ...).
- `--architect` pairs a main model with `--editor-model`. This is the only multi-model split.

## 8. Models

- Any LiteLLM provider: `--model provider/model`, with `--weak-model` (commit messages, summaries) and
  `--editor-model`.
- OpenAI-compatible endpoints: `--openai-api-base` (`OPENAI_API_BASE`) with `--model openai/<name>`.
- Ollama: `--model ollama_chat/<model>` with `OLLAMA_API_BASE`.
- Unknown models need `.aider.model.settings.yml` / `.aider.model.metadata.json`, or `--no-show-model-warnings`.

## 9. Auth for cron

- Env vars only: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `--api-key provider=KEY`, or any LiteLLM env var.
- These can also be set in `.env` or `.aider.conf.yml`.
- There is no login. OpenRouter OAuth is offered interactively only.

## 10. Install and detection

- Install: `pipx install aider-chat` / `uv tool install aider-chat` / `python -m pip install aider-install && aider-install`.
- Binary is `aider`. Detect with `aider --version`, which prints `aider 0.86.2`.
- The install is heavy: litellm, tree-sitter grammars, numpy and so on.

## 11. Cron gotchas

- **Exit 0 on model failure.** Parse stdout for errors and for the `Cost:` line.
- Default side effects in the repo:
  - adds `.aider*` to `.gitignore` (`--no-gitignore`)
  - writes `.aider.chat.history.md` and `.aider.input.history` to the git root (redirect with
    `--chat-history-file` / `--input-history-file`, ideally outside the repo)
  - checks for updates (`--no-check-update`)
  - may prompt about analytics on first run (`--analytics-disable`)
- Auto-commits, including dirty-tree commits, are on by default and skip pre-commit hooks.
- A first run may try to install extras or open URLs (playwright prompts). `--yes-always` answers them; use
  `--disable-playwright` and `--no-detect-urls`.
- No agentic exploration: the caller must pick the files. A "find what's stale and fix it" prompt works far
  worse than with the other runtimes.
