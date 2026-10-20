# Other agent CLIs worth considering (brief)

Researched 2026-10-20. Each entry gives one short summary per checklist item (1-11). Details are from the
official docs linked under each tool unless marked UNVERIFIED. GitHub star counts are from the GitHub API on
the research date.

## OpenAI Codex CLI (`codex`): the strongest candidate besides Claude Code

https://github.com/openai/codex (about 130k stars)

Sources:
- Non-interactive mode: https://learn.chatgpt.com/docs/non-interactive-mode
- Hooks: https://learn.chatgpt.com/docs/hooks

1. **Headless:** `codex exec "<prompt>"`. `codex exec -` (or omitting the prompt) reads it from stdin. Piped
   stdin plus a prompt means stdin is context.
2. **Output:** `--json` gives JSONL with these events:
   - `thread.started`, `turn.started`, `turn.completed`, `turn.failed`, `item.*`, `error`
   - `turn.completed` carries token usage: input, cached input, output, reasoning
   - **no cost field**

   `-o/--output-last-message <file>` saves the final text. `--output-schema` gives structured output.
3. **Instructions:** reads `AGENTS.md` (UNVERIFIED detail here).
4. **Permissions:** `--sandbox read-only|workspace-write|danger-full-access`. **`exec` defaults to
   `read-only`**, which fits the reviewer. `--full-auto` was removed; use `--sandbox workspace-write` or
   `--approve-for-me`. Execpolicy `.rules` files gate commands; `--ignore-rules` skips them.
5. **Budget:** no flag found. UNVERIFIED.
6. **Hooks:** enabled by default.
   - Config: `~/.codex/hooks.json`, `<repo>/.codex/hooks.json` or `[hooks]` in `config.toml`. Project hooks
     load only when the project layer is trusted.
   - **`PreToolUse`** covers `Bash`, `apply_patch` (also matched as `Edit`/`Write`) and MCP tools. Deny with
     `hookSpecificOutput.permissionDecision: "deny"` or exit 2.
   - `SessionStart` stdout becomes developer context.
   - The format is very close to Claude Code's.
7. **Subagents and skills:** `SubagentStart`/`SubagentStop` events exist. Skills and agent details are
   UNVERIFIED here.
8. **Models:** OpenAI models; providers are configurable in `config.toml`, including OSS and local models
   (UNVERIFIED).
9. **Auth:** `CODEX_API_KEY` for `exec`. The docs warn against exposing it to repository-controlled code.
10. **Install:** `npm i -g @openai/codex`, binary `codex` (UNVERIFIED detail).
11. **Cron gotchas:** non-managed hooks must be reviewed and trusted (`/hooks`) before they run. Check how that
    interacts with headless runs on a new checkout.

## Google Gemini CLI (`gemini`)

https://github.com/google-gemini/gemini-cli (about 107k stars)

Sources:
- Headless: https://geminicli.com/docs/cli/headless/
- Hooks: https://geminicli.com/docs/hooks/

1. **Headless:** `-p/--prompt`, or any non-TTY run.
2. **Output:** `--output-format json` gives `{response, stats, error?}` (`stats` holds tokens and latency, **no
   cost**). Stream JSON has `init`, `message`, `tool_use`, `tool_result`, `error`, `result` events.
   **Exit codes:** `0` OK, `1` error, `42` input error, `53` turn limit exceeded.
3. **Instructions:** reads `GEMINI.md` (UNVERIFIED here).
4. **Permissions:** `--approval-mode` / `--yolo` (values UNVERIFIED here).
5. **Budget:** a turn limit exists (exit code 53). The flag name is UNVERIFIED.
6. **Hooks:** configured in `settings.json` (project `.gemini/settings.json`, user, system `/etc/gemini-cli`).
   - Events: `SessionStart`, `SessionEnd`, `BeforeAgent`, `AfterAgent`, `BeforeModel`, `AfterModel`,
     `BeforeToolSelection`, **`BeforeTool`**, `AfterTool`, `PreCompress`, `Notification`.
   - Block by printing a deny decision with exit 0, or by exit 2 (stderr becomes the reason).
   - Tool matchers are regexes, e.g. `write_.*`.
7. **Subagents and skills:** not checked.
8. **Models:** Gemini models.
9. **Auth:** `GEMINI_API_KEY` (UNVERIFIED here).
10. **Install:** not checked.
11. **Cron gotcha:** the docs say that on 2026-06-18 Gemini CLI was **replaced by "Antigravity CLI" for the
    unpaid tier and Google One users**, and that it is not optimized for the newest Gemini model. Its future
    as a free cron runtime is uncertain.

## Amp (`amp`, Sourcegraph)

Sources:
- Manual: https://ampcode.com/manual
- Execute mode: https://ampcode.com/docs/cli/execute-mode
- Streaming JSON: https://ampcode.com/docs/cli/streaming-json

1. **Headless:** `amp -x "<prompt>"` (or `--execute`). It turns on automatically when stdout is redirected.
   Non-interactive threads start in Standard mode.
2. **Output:** `--stream-json` "tries to be compatible with Claude Code's format". The final `result` has
   `is_error`, `result` (or `error`), `num_turns`, `duration_ms`, optional `usage`, and **no cost**.
   `system` error subtypes include `error_max_turns`. **This is the closest drop-in for Libraryan's current
   parser.**
3. **Instructions:** has an AGENTS.md page in the docs; not checked.
4. **Permissions:** `amp.permissions` settings and `--dangerously-allow-all` are UNVERIFIED (not on the pages
   read).
5. **Budget:** none found.
6. **Hooks:** plugins with lifecycle events exist (`--plugin-ready-timeout`). Whether they can block a tool is
   UNVERIFIED.
7. **Subagents and skills:** a skills page exists; not checked.
8. **Models:** Amp routes models itself (multi-model); BYO choice is limited.
9. **Auth:** `AMP_API_KEY`. The CLI rejects the short-lived token stored by `amp login`.
10. **Install:** not checked.
11. **Cron gotchas:** none recorded beyond the above.

## Goose (`goose`, now at aaif-goose)

https://github.com/aaif-goose/goose (about 55k stars)

Source: https://goose-docs.ai/docs/guides/running-tasks

1. **Headless:** `goose run -t "<text>"`, or `-i file` / `-i -` (stdin). Also `--recipe recipe.yaml`, and
   `--no-session` (no session file).
2. **Output:** `--output-format json|stream-json` gives session metadata, results, tool outputs and errors.
   Tokens and cost are not documented.
3. **Instructions:** `.goosehints` and AGENTS.md are UNVERIFIED.
4. **Permissions:** `GOOSE_MODE` (auto/approve/smart_approve/chat) is UNVERIFIED here.
5. **Budget:** `--max-turns` and `--max-tool-repetitions` per the man page (https://www.mankier.com/1/goose-run).
6. **Hooks:** none found. UNVERIFIED.
7. **Subagents and skills:** recipes are the reuse mechanism.
8. **Models:** many providers, set with `--provider`/`--model` (overriding env), including Ollama.
9. **Auth:** provider env vars (names UNVERIFIED).
10. **Install:** not checked.
11. **Cron gotchas:** none recorded.

## Kiro CLI (`kiro-cli`, AWS)

Source: https://kiro.dev/docs/cli/headless/

1. **Headless:** `kiro-cli chat --no-interactive "<prompt>"`, or piped stdin.
2. **Output:** `--output-format stream-json` gives JSONL (V2/V3 only). **Exit codes:** `3` = a required MCP
   server failed (`--require-mcp-startup`), `4` = the `--agent` was not found.
3. **Instructions:** custom agents via `--agent <name>` or `chat.defaultAgent`. Steering files and AGENTS.md
   are UNVERIFIED.
4. **Permissions:** `--trust-all-tools`, or `--trust-tools read_file,grep_search` (V3).
5. **Budget:** none found.
6. **Hooks:** V3 headless loads hooks from the agent and workspace. **`PreToolUse` can deny, and a deny is
   final even under the trust flags.**
7. **Subagents and skills:** not checked.
8. **Models:** AWS-hosted models.
9. **Auth:** `KIRO_API_KEY`, limited to some subscription tiers and possibly needing admin enablement.
10. **Install:** not checked.
11. **Cron gotchas:** none recorded.

## Crush (`crush`, Charm)

https://github.com/charmbracelet/crush (about 29k stars). License FSL-1.1-MIT, which is not OSI open source.

Sources:
- README: https://github.com/charmbracelet/crush/blob/main/README.md
- Hooks: https://github.com/charmbracelet/crush/blob/main/docs/hooks/README.md

`crush run --help` was read locally on v0.98.1.

1. **Headless:** `crush run "<prompt>"`, or prompt/context from stdin. Flags: `-q` (no spinner), `-m`,
   `--reasoning-effort`, `-c/--cwd`, `-s/--session`, `-C/--continue`.
2. **Output:** **no JSON output flag in `run --help`.**
3. **Instructions:** `AGENTS.md` (project), `~/.config/AGENTS.md`, `~/.config/crush/CRUSH.md`.
4. **Permissions:** `--yolo` skips prompts. The `permissions` allow list is in `crush.json`.
5. **Budget:** none found.
6. **Hooks:** **exactly one event, `PreToolUse`**, in `crush.json` / `.crush.json` (project or global). The
   matcher is a regex on the tool name. **Exit 2 blocks the call**; other failures are non-blocking warnings.
   When hooks conflict, the first deny wins.
7. **Skills:** `SKILL.md` folders.
8. **Models:** env-var providers (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, ...), custom
   OpenAI- or Anthropic-compatible endpoints, and local Ollama, LM Studio or llama.cpp discovery.
9. **Auth:** the provider env vars above.
10. **Install:** npm `@charmland/crush`.
11. **Cron gotchas:** with no JSON output, Libraryan could not read cost or errors from a run.

## GitHub Copilot CLI (`copilot`)

https://github.com/github/copilot-cli (about 11k stars)

Source: https://docs.github.com/en/copilot/how-tos/copilot-cli/automate-copilot-cli/run-cli-programmatically

1. **Headless:** `copilot -p "<prompt>"`. Piped input is ignored with `-p`. `-s` suppresses metadata.
   `--no-ask-user`.
2. **Output:** JSON output is not on this page. UNVERIFIED.
3. **Instructions:** custom agents and AGENTS.md are not on this page. UNVERIFIED.
4. **Permissions:** `--allow-tool=[...]`, `--allow-url=[...]`, `--allow-all-tools`. `--deny-tool` is
   UNVERIFIED here.
5. **Budget:** not on this page.
6. **Hooks:** not on this page. UNVERIFIED.
7. **Subagents and skills:** not checked.
8. **Models:** `--model`.
9. **Auth:** `COPILOT_GITHUB_TOKEN` (a PAT) in CI.
10. **Install:** not checked.
11. **Cron gotchas:** needs a Copilot subscription.

## Qwen Code (`qwen`)

https://github.com/QwenLM/qwen-code (about 29k stars). A fork of Gemini CLI, so its headless, JSON and hooks
model is likely similar. Not researched further (UNVERIFIED).

## Takeaways for a vendor-agnostic Libraryan

- **Cost in USD** is reported only by Claude Code and OpenCode (`step_finish.cost`), and by Aider as text.
  Every other tool gives tokens at best. Libraryan's USD budget needs either a token-to-price table or "tokens"
  as the budget unit.
- **A blocking pre-edit hook** exists in Codex (`PreToolUse`), Gemini CLI (`BeforeTool`), Cursor
  (`preToolUse`), Kiro (`PreToolUse`), Crush (`PreToolUse`, bash/exit-2 style) and OpenCode (a JS plugin
  `tool.execute.before`). Aider and Goose have none. Path-level declarative deny rules (no hook needed) are documented for Cursor
  (`Write(glob)`) and OpenCode (`permission.edit`); for the others, use the hook.
