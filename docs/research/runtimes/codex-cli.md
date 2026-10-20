# OpenAI Codex CLI as a Libraryan runtime

Researched 2026-10-20 against **codex-cli 0.163.0** (npm `@openai/codex`, linux-arm64).
Sources: the tool's own `--help` / `exec --help`, the official docs (the old
`developers.openai.com/codex/*` URLs now 308-redirect to `learn.chatgpt.com/docs/*`; appending `.md` returns
Markdown), and **local runs against a fake OpenAI-compatible endpoint** (a mock `/v1/responses` server, no login,
no real model). "Observed" means seen in those runs. "UNVERIFIED" means not confirmed from a primary source or a run.

Key docs:
- Non-interactive mode: https://learn.chatgpt.com/docs/non-interactive-mode
- Hooks: https://learn.chatgpt.com/docs/hooks
- Config reference: https://developers.openai.com/codex/config-reference.md
- Advanced config (profiles, trust, project docs): https://developers.openai.com/codex/config-advanced.md
- Permissions profiles: https://learn.chatgpt.com/docs/permissions.md
- Rules (execpolicy): https://learn.chatgpt.com/docs/agent-configuration/rules.md
- AGENTS.md: https://learn.chatgpt.com/docs/agent-configuration/agents-md.md
- Subagents / custom agents: https://learn.chatgpt.com/docs/agent-configuration/subagents.md
- Skills: https://developers.openai.com/codex/skills.md
- Auth: https://developers.openai.com/codex/auth.md
- Install: https://developers.openai.com/codex/cli.md

## 1. Headless invocation

```
codex exec [--json] [-o FILE] [-s read-only|workspace-write|danger-full-access] [-m MODEL] \
           [-C DIR] [-c key=value]... [--ephemeral] [--skip-git-repo-check] "<prompt>"
```
- `exec` (alias `e`) is the non-interactive mode. Note that **`-p` means `--profile`**, not "prompt".
- Prompt: positional argument. If it's omitted or set to `-`, the prompt is read from stdin. If stdin is piped **and** a prompt
  is given, stdin is appended as a `<stdin>` block (`exec --help`).
- Observed: `exec` prints `Reading additional input from stdin...` to stderr even when stdin is `/dev/null`. Always pass
  `stdin=DEVNULL` (the runner already does), or it may wait on an inherited TTY or pipe.
- Progress goes to stderr. With no `--json`, only the final agent message goes to stdout. `-o/--output-last-message FILE` also
  writes it to a file. `--output-schema FILE` forces the final message to fit a JSON Schema.
- Exit codes (observed): `0` on a completed turn; `1` when the turn fails (HTTP 400 from the provider gave
  `turn.failed` and then exit 1). No documented exit-code table.
- **No built-in wall-clock timeout.** Observed: when the provider endpoint refuses connections, Codex loops forever on
  `{"type":"error","message":"Reconnecting... waiting for network ..."}` even with
  `request_max_retries=0`/`stream_max_retries=0`. An external timeout (killing the process group) is mandatory.
  `model_providers.<id>.stream_idle_timeout_ms` (default 300000) only covers idle SSE streams.
- It refuses to run outside a Git repo unless you pass `--skip-git-repo-check`.
- `--ephemeral` skips writing session rollout files. `--ignore-user-config` skips `$CODEX_HOME/config.toml` (auth
  still uses `CODEX_HOME`). `--ignore-rules` skips `.rules` files.

## 2. Machine-readable output

`codex exec --json` prints JSONL on stdout. Observed stream for a successful run:
```
{"type":"thread.started","thread_id":"…"}
{"type":"turn.started"}
{"type":"item.started","item":{"id":"item_1","type":"file_change","changes":[{"path":"<repo>/docs/x.md","kind":"add"}],"status":"in_progress"}}
{"type":"item.completed","item":{"id":"item_1","type":"file_change","changes":[…],"status":"failed"}}
{"type":"item.completed","item":{"id":"item_2","type":"agent_message","text":"…final text…"}}
{"type":"turn.completed","usage":{"input_tokens":200,"cached_input_tokens":20,"cache_write_input_tokens":0,"output_tokens":10,"reasoning_output_tokens":0}}
```
Failure: `{"type":"error","message":"…"}` followed by `{"type":"turn.failed","error":{"message":"…"}}`, then exit 1.
Warnings also appear as `item.completed` with `item.type:"error"` (for example "Model metadata … not found",
"--dangerously-bypass-hook-trust is enabled"). These are **not** fatal, so don't treat every `type:"error"` item as failure.

| Libraryan need | Codex field |
|---|---|
| final text | last `item.completed` with `item.type=="agent_message"` → `item.text` (or `-o FILE`) |
| cost USD | **not reported** (docs: only token counts). You'd compute it from tokens × your own price table |
| tokens | `turn.completed.usage.{input_tokens, cached_input_tokens, cache_write_input_tokens, output_tokens, reasoning_output_tokens}` |
| turn count | not reported. Count `turn.started` events (one `exec` = one turn) or count `item.*` tool items |
| error flag | `turn.failed` event and/or a non-zero exit code |
| files touched | `item.type=="file_change"` → `changes[].path`, `kind`, `status` |

Other item types (docs): `command_execution` (`command`, `status`), `reasoning`, `mcp_tool_call`, `web_search`, plan updates.

## 3. Instructions / persona

- There is **no `--agent` or `--system-prompt` flag for the main session.** Options:
  - `-c developer_instructions="…"`: "Additional developer instructions injected into the session" (config reference).
  - `-c model_instructions_file="path"`: *replaces* the built-in instructions (config reference: "Replacement for
    built-in instructions instead of `AGENTS.md`").
  - Profiles: `-p NAME` layers `$CODEX_HOME/NAME.config.toml` on top of the base config (`--help`).
- Auto-read project files: `AGENTS.override.md`, then `AGENTS.md`, then any `project_doc_fallback_filenames`, one per directory,
  from the Git root down to the cwd, plus global `$CODEX_HOME/AGENTS.md`. Capped by `project_doc_max_bytes` (32 KiB default).
  It does **not** read `CLAUDE.md` unless you add it to `project_doc_fallback_filenames`.
- Custom agents: `.codex/agents/*.toml` (project) or `~/.codex/agents/*.toml` (user). Required keys: `name`, `description`,
  `developer_instructions`. Optional: `model`, `model_reasoning_effort`, feature toggles (`features.shell_tool`, …).
  These are **subagents only**: they can't override `sandbox_mode`, `approval_policy`, `model_provider`, or `mcp_servers`.
  Nothing documents selecting one as the main agent of `codex exec` (UNVERIFIED / appears unsupported).
- Project `.codex/config.toml`, hooks, and rules load **only when the project is trusted**:
  `[projects."<abs path>"] trust_level = "trusted"` in the *user* `~/.codex/config.toml` (config-advanced, config-reference).

## 4. Permissions & sandbox

- Sandbox (`-s/--sandbox`, config `sandbox_mode`): `read-only` (the **default for `exec`**), `workspace-write`, or
  `danger-full-access`. Docs: "By default, `codex exec` runs in a read-only sandbox". `--full-auto` "is no longer supported".
- Approvals: `-a/--ask-for-approval on-request|never` (`untrusted` was retired). Observed: in `exec`, hook payloads
  report `permission_mode:"bypassPermissions"`, so nothing prompts headless. `--approve-for-me` sends approval
  requests to an automatic reviewer.
- Edit without prompts: `codex exec -s workspace-write …`.
- Read-only reviewer: `codex exec -s read-only …` (the default). Observed: under read-only the model isn't even offered the
  `apply_patch` tool.
- Command allowlist: **no per-tool allowlist like Claude's `--allowedTools`.** Instead:
  - `.rules` files (Starlark `prefix_rule(pattern=[…], decision="allow"|"prompt"|"forbidden")`) under `rules/` next to
    any config layer (`~/.codex/rules/default.rules`, `<repo>/.codex/rules/` if trusted). They govern commands run
    **outside the sandbox / escalations**. `forbidden` blocks without prompting. Marked "experimental".
  - Filesystem permission profiles: `default_permissions = "name"` plus `[permissions.name.filesystem] "<path>" =
    "read"|"write"|"deny"`, with globs allowed. Path-level `deny`/`read` can keep owned docs read-only at the OS sandbox
    level (permissions.md).
  - Custom agents can turn off `features.shell_tool`.
- Preventing git commit/push: under `workspace-write`, `.git`, `.agents`, `.codex` and `.aws` at the workspace root stay
  **read-only** (permissions.md: extending `:workspace` "keeps the workspace root's `.git` … read-only"). So `git commit`
  fails inside the sandbox. Add a `prefix_rule(pattern=["git", ["commit","push"]], decision="forbidden")` so the model
  can't escalate past it. Network is off by default in `workspace-write` (`sandbox_workspace_write.network_access`).
- Observed anomaly (this host only): sandboxed `apply_patch` writes failed with "Failed to write file" under both
  `workspace-write` and `danger-full-access` while a shell redirect worked. Likely a nested-sandbox artefact of the
  test machine. Not a general conclusion.

## 5. Budget / limits

- **No max-USD, max-turns or max-tokens flag** in `exec --help`.
- `features.rollout_budget.enabled` + `features.rollout_budget.limit_tokens`: token budget tracking, "under development
  and off by default" (config reference). Treat it as unusable for now.
- `model_auto_compact_token_limit` (compaction threshold, not a cap). `tool_output_token_limit`.
- `agents.max_concurrent_threads_per_session` caps parallel subagents.
- Libraryan would have to enforce budget itself: wall-clock timeout plus token totals from `turn.completed`.

## 6. Hooks

- Locations: `~/.codex/hooks.json` or `[hooks]` in `~/.codex/config.toml`; project `<repo>/.codex/hooks.json` or
  `.codex/config.toml` (**only if the project is trusted**); plugins; managed `requirements.toml`.
- Format is Claude-Code-like: `{"hooks":{"PreToolUse":[{"matcher":"Edit|Write","hooks":[{"type":"command","command":"…","timeout":30}]}]}}`.
  Events: `SessionStart`, `SessionEnd`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`, `PostCompact`,
  `UserPromptSubmit`, `SubagentStart`, `SubagentStop`, `Stop`, `Interrupt`. Default timeout 600 s.
- **Per-hook trust:** non-managed hooks must be reviewed and trusted (by hash) in the TUI (`/hooks`) before they run.
  Observed: with no trust, the project hook silently did **not** run (neither SessionStart nor PreToolUse).
  Headless or cron needs `--dangerously-bypass-hook-trust` (per invocation) or managed hooks.
- Codex does **not** read `.claude/settings.json` hooks (observed: a Claude-format hook there never fired).
- PreToolUse input (observed):
  `{"session_id","turn_id","transcript_path","cwd","hook_event_name":"PreToolUse","model","permission_mode","tool_name","tool_input","tool_use_id"}`.
- **File edits don't carry a `file_path`.** Observed:
  - Native edit tool: `tool_name:"apply_patch"`, `tool_input:{"command":"*** Begin Patch\n*** Add File: docs/x.md\n+hi\n*** End Patch\n"}`.
    The matcher `Edit|Write` **does** match it (verified). A guard has to parse the `*** Add File:`, `*** Update File:`,
    `*** Delete File:` and `*** Move to:` lines to get target paths. Paths are relative to cwd.
  - When the model has no native `apply_patch` (for example a custom-provider model missing from Codex's catalog), edits happen
    through the shell: `tool_name:"Bash"`, `tool_input.command:"apply_patch <<'EOF' …"` or any `echo > file`.
    `Edit|Write` does **not** match these, so a guard must also match `Bash` and inspect the command string. That's best-effort.
- Deny: exit code `2` with the reason on stderr (verified: the tool output became "Command blocked by PreToolUse hook: <stderr>"),
  or stdout JSON `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"…"}}`.
  `ask` isn't supported for PreToolUse.
- SessionStart: matcher on `source` (`startup|resume|clear|compact|fork`). Plain stdout (verified) or
  `hookSpecificOutput.additionalContext` is injected as developer context.
- Hosted tools (web search) aren't covered by PreToolUse.

## 7. Subagents / skills

- Subagents are on by default (`agents.enabled`). They're spawned when the prompt, AGENTS.md or a skill asks for it. Built-ins are `default`, `worker`
  and `explorer`. Custom ones come from `.codex/agents/*.toml` (see §3). They inherit the parent's sandbox and permissions, so a
  read-only reviewer subagent **can't be made stricter than its parent** via the agent file (sandbox is not overridable).
  The independent reviewer should be a separate `codex exec -s read-only` process.
- Skills: a directory with `SKILL.md` (frontmatter `name`, `description`). Discovered in `.agents/skills` (cwd up to repo
  root), `$HOME/.agents/skills`, admin and system locations. **Not `.claude/skills`**, so Libraryan's skill would need a
  copy or symlink under `.agents/skills/`.

## 8. Model choice

- `-m/--model`. `--oss` with `--local-provider lmstudio|ollama` (`oss_provider` config).
- Any provider: `model_provider = "<id>"` + `[model_providers.<id>] base_url, env_key, wire_api ("responses"),
  http_headers, query_params, request_max_retries, stream_idle_timeout_ms, auth.command` (config reference). Built-in
  `amazon-bedrock` provider. Observed working against a local OpenAI-compatible `/v1/responses` endpoint with no login.
- Models not in Codex's catalog get "fallback metadata" (a warning) and may lose tools such as native `apply_patch` (observed).

## 9. Auth for unattended runs

- `CODEX_API_KEY=<key> codex exec …` (docs recommend scoping it to the single invocation, not job-wide). Or
  `printenv OPENAI_API_KEY | codex login --with-api-key` to persist it.
- ChatGPT login: cached in `~/.codex/auth.json` (or the OS keyring, per `cli_auth_credentials_store = file|keyring|auto|ephemeral`).
  `exec` reuses saved auth and refreshes tokens automatically, so a logged-in session works from cron as long as the cron user
  shares `CODEX_HOME`. Headless login: `codex login --device-auth`.
- With a custom provider, no OpenAI login is needed (observed).

## 10. Install & detection

- `npm install -g @openai/codex` (package `engines.node >=16`), `brew install --cask codex`, or the standalone installer
  `curl -fsSL https://chatgpt.com/codex/install.sh | sh` (macOS/Linux), or `install.ps1` (Windows).
- Binary `codex`. `codex --version` → `codex-cli 0.163.0`. `codex doctor` diagnoses install, config and auth.
- When `HOME`/`CODEX_HOME` is under `/tmp`, it prints `WARNING: proceeding, even though we could not create PATH aliases …`
  on every invocation (harmless).

## 11. Gotchas for cron-driven headless runs

- Infinite reconnect loop when the endpoint is unreachable (see §1), so always run under a hard timeout and process-group kill.
- `-p` is `--profile`. The prompt is positional.
- Project hooks, config and rules are ignored unless the project is trusted in the **user** config, and hooks additionally need
  per-hash trust or `--dangerously-bypass-hook-trust`. A changed hook script hash means it gets skipped silently.
- The `exec` default sandbox is read-only, so the writer must pass `-s workspace-write`.
- `.git` is read-only in `workspace-write`, which is good for "no commits" but also blocks `git mv`/`git rm` (Libraryan's writer
  allowlist uses them; they'd need escalation or must move to Libraryan's own commit step).
- Child-process env markers (observed): `CODEX_CI`, `CODEX_SESSION_ID`, `CODEX_THREAD_ID`, `CODEX_TOOL_CALL_ID`,
  `CODEX_HOME`, `CODEX_VERSION`, `CODEX_MANAGED_BY_NPM`. Use them to detect a nested Codex session.
- The root `codex` command mentions a "shared local app-server daemon" (`--no-daemon`). `exec --help` doesn't list it. After `codex exec`
  runs, no lingering `codex` process was observed.
- Warnings arrive as `item.type:"error"` JSONL items. Only `turn.failed` or a non-zero exit means failure.
