# Qwen Code as a Libraryan runtime

Researched 2026-10-20 against `@qwen-code/qwen-code` **0.25.3**, the `--help` output of that build, its bundled source, and the docs in `QwenLM/qwen-code` at commit `bf118a1`. Qwen Code began as a fork of Gemini CLI. It has since moved toward Claude Code's conventions for output shape, hooks and permission rules.

Doc links below use `D/` = `https://github.com/QwenLM/qwen-code/blob/bf118a12200abe0548c61a54df33350a9d62f8f8/docs/`.

"Verified in source" means read in the 0.25.3 npm bundle. "Probed" means a local run with no credentials, which fails before any model call.

## 1. Headless invocation

```
qwen "<prompt>" -o json --approval-mode auto-edit --max-session-turns N --max-wall-time 20m [-m <model>]
```

- In 0.25.3 the **positional prompt is one-shot (headless) by default**. `-p/--prompt` still works but is marked deprecated in `--help`. Use `-i` for interactive mode.
- **Stdin:** the prompt is appended to whatever is on stdin. `--input-format stream-json` is a bidirectional protocol meant for SDKs.
- Sources: `--help`, [D/users/features/headless.md](https://github.com/QwenLM/qwen-code/blob/bf118a12200abe0548c61a54df33350a9d62f8f8/docs/users/features/headless.md).
- **Exit codes** (verified in source as `Fatal*Error` classes):

  | Code | Meaning |
  | --- | --- |
  | 0 | success |
  | 1 | general error. **Probed: missing auth exits 1**, not 41. |
  | 41 | auth |
  | 42 | input |
  | 44 | sandbox |
  | 52 | config |
  | 53 | turn limit |
  | 54 | fatal tool execution error |
  | 55 | **budget exceeded** (`--max-wall-time` or `--max-tool-calls`). Gemini CLI uses 55 for an untrusted workspace. |
  | 130 | SIGINT |

- **Timeouts:**
  - `--max-wall-time` takes `90`, `30s`, `5m`, `1h` or `1.5h`, and aborts with exit 55.
  - Stream inactivity: `streamIdleTimeoutMs`, default 240000.
  - Hook timeout: default 60 **seconds**.

## 2. Machine-readable output

`-o text|json|stream-json`.

**`-o json`** prints a **JSON array** of messages at the end. The last element is a `result` message, closely modelled on Claude Code's `--output-format json`. Fields of the result message (verified in source, `buildResultMessage`):

```json
{ "type": "result", "subtype": "success" | "error_during_execution" | ...,
  "uuid": "...", "session_id": "...", "is_error": false,
  "duration_ms": 0, "duration_api_ms": 0, "num_turns": 0,
  "result": "<final text>",
  "usage": { "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "total_tokens": 0 },
  "permission_denials": [ { "tool_name": "...", "tool_use_id": "...", "tool_input": {} } ],
  "stats": { ... }, "structured_result": { ... }, "error": { "message": "..." } }
```

- `stats` is optional. `structured_result` appears only with `--json-schema`. `error` appears only when `is_error` is true.
- **No `total_cost_usd`.** The final text, `is_error`, `num_turns`, token usage and `permission_denials` are all present.
- Errors are also written to **stdout** as the array. Probed with no auth (exit 1):

  ```json
  [{"type":"result","subtype":"error_during_execution","is_error":true,"duration_ms":0,"duration_api_ms":0,"num_turns":0,"usage":{"input_tokens":0,"output_tokens":0},"permission_denials":[],"error":{"message":"No auth type is selected. Please configure an auth type (e.g. via settings or `--auth-type`) before running in non-interactive mode."}, "uuid": "...", "session_id": "..."}]
  ```

- Parse with `out[-1]` where `type == "result"`. Libraryan's current `trace.parse_output` expects a single object, not an array.

**`-o stream-json`** writes JSONL in the same message types (`system` `session_start`, `assistant`, `user` `tool_result`, `result`). Add `--include-partial-messages` for token deltas.

**`--json-schema <json|@file>`** forces the final answer into a validated structured output, which comes back in `structured_result`.

## 3. Instructions and persona

- **Per-run system prompt:**
  - `--system-prompt "<text>"` replaces the built-in main prompt.
  - `--append-system-prompt "<text>"` appends to it.
  - The two can be combined.
  - The `QWEN_SYSTEM_MD` environment variable does a file-based replacement, inherited from Gemini CLI.
  - `QWEN.md` and other context files are still appended after `--system-prompt`.
- **No `--agent <name>` flag** for the main session. Named agents are subagents only (section 7). To run "as" a persona, pass the agent file's body through `--system-prompt` or `--append-system-prompt`.
- **Context files read automatically:**
  - `~/.qwen/QWEN.md`.
  - `QWEN.md` in the project root and its parent directories, up to the `.git` root or home.
  - `.qwen/QWEN.local.md`.
  - **`AGENTS.md` too** ("If your repository already has an `AGENTS.md`… Qwen reads that too").
  - `context.fileName` overrides the names.
  - `.qwen/rules/*.md` rules, which can be scoped by path through `paths:` frontmatter. Project rules load only in trusted workspaces.
  - Sources: [D/users/features/memory.md](https://github.com/QwenLM/qwen-code/blob/bf118a12200abe0548c61a54df33350a9d62f8f8/docs/users/features/memory.md), [D/users/features/rules.md](https://github.com/QwenLM/qwen-code/blob/bf118a12200abe0548c61a54df33350a9d62f8f8/docs/users/features/rules.md).
- **`--bare`** skips implicit startup discovery and honours only explicit command-line inputs.

## 4. Permissions and sandbox

**Approval modes:** `--approval-mode plan|default|auto-edit|auto|yolo`, with a **hyphen** (Gemini CLI spells it `auto_edit`). `-y` is the same as yolo.

| Mode | Effect |
| --- | --- |
| `plan` | analysis only |
| `default` | edits and shell need approval |
| `auto-edit` | edits auto-approved, shell needs approval |
| `auto` | an LLM classifier approves "safe" actions |
| `yolo` | everything auto-approved |

- In headless mode, any call that would need approval is **declined** (verified in source: "…that permission was declined (non-interactive mode cannot prompt for confirmation)"). Declined calls are listed in `permission_denials`.
- A permission-rule `ask` also becomes a denial in headless mode.
- Source: [D/users/features/approval-mode.md](https://github.com/QwenLM/qwen-code/blob/bf118a12200abe0548c61a54df33350a9d62f8f8/docs/users/features/approval-mode.md).

**Permission rules** use Claude Code syntax in settings.json:

```json
"permissions": { "allow": [...], "ask": [...], "deny": ["Bash(git commit *)", "Bash(git push *)", "Edit(/docs/**)"] }
```

- Priority is `deny > ask > allow > approval mode`.
- In the scheduler, deny is checked **before** the approval mode (verified in source), so deny rules also hold under `--yolo`.
- Claude Code tool aliases are accepted: `Bash`, `Read`, `Edit`, `Write`, `Grep`, `Glob`, `WebFetch`, `Agent`, `Skill`, with meta-categories.
- Read, Edit and WebFetch rules also apply to equivalent shell commands such as `cat`, `cp` and `curl`.
- A deny rule naming a whole tool (no argument pattern) also removes that tool from the registry.
- The settings are merged across the user, project and system scopes.
- **There is no per-run settings flag.** Options for one run:
  - write the project's `.qwen/settings.json`;
  - point `QWEN_HOME` at a private config directory;
  - use `--exclude-tools <names>`;
  - use `--allowed-tools <names>`.
- Source: [D/users/configuration/settings.md](https://github.com/QwenLM/qwen-code/blob/bf118a12200abe0548c61a54df33350a9d62f8f8/docs/users/configuration/settings.md) "permissions".

**Read-only reviewer recipe:** `--approval-mode plan`, or `default` with `--exclude-tools write_file,edit,run_shell_command`, plus deny rules. Avoid `--safe-mode`: it **turns off permission rules** (along with hooks, skills and context files).

**Sandbox:**

- Whole-CLI sandbox: `-s/--sandbox` with docker, podman or sandbox-exec.
- Linux per-tool execution sandbox: `tools.executionSandbox` with `backend` (bwrap or Landlock), `filesystem` (`workspace-write`) and `network` (`closed`). It must be set in **user or system** settings.
- `--yolo` does **not** turn on a sandbox. The CLI prints a warning to stderr; `QWEN_CODE_SUPPRESS_YOLO_WARNING=1` silences it.
- Source: [D/users/features/sandbox.md](https://github.com/QwenLM/qwen-code/blob/bf118a12200abe0548c61a54df33350a9d62f8f8/docs/users/features/sandbox.md).

**Folder trust:** `security.folderTrust.enabled` defaults to **false**, so every folder counts as trusted. When the feature is on, an untrusted folder ignores project settings and hooks.

## 5. Budget and limits

**Run-level budgets** ([D/users/features/headless.md](https://github.com/QwenLM/qwen-code/blob/bf118a12200abe0548c61a54df33350a9d62f8f8/docs/users/features/headless.md) "Run-level budgets"):

| Flag | Setting | What it limits | Exit |
| --- | --- | --- | --- |
| `--max-session-turns N` | `model.maxSessionTurns` | turns | 53 |
| `--max-wall-time <dur>` | `model.maxWallTimeSeconds` | wall-clock time | 55 |
| `--max-tool-calls N` | `model.maxToolCalls` | top-level tool calls only; tool calls inside subagents are **not** counted | 55 |

- `model.sessionTokenLimit` drops the next send instead of aborting the run.
- `--max-subagent-depth` limits subagent nesting.
- The wall-time and tool-call budgets **do not apply** to `qwen serve` or ACP sessions.
- **No cost or USD budget.**

## 6. Hooks

Hooks use Claude Code's model. Source: [D/users/features/hooks.md](https://github.com/QwenLM/qwen-code/blob/bf118a12200abe0548c61a54df33350a9d62f8f8/docs/users/features/hooks.md).

**Where they are loaded from and how to turn them off:**

- `hooks` in `.qwen/settings.json`. Project hooks require a trusted folder, which is the default.
- `~/.qwen/settings.json`.
- System settings and extensions.
- Agent frontmatter, scoped to that agent.
- `disableAllHooks: true` turns them all off.

**Event names:**

- Tool events: `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PostToolBatch`.
- Prompt events: `UserPromptSubmit`, `UserPromptExpansion`.
- Session events: `SessionStart`, `SessionEnd`, `SessionDelete`.
- Stop and subagent events: `Stop`, `StopFailure`, `SubagentStart`, `SubagentStop`.
- Compaction: `PreCompact`, `PostCompact`.
- Permissions: `PermissionRequest`, `PermissionDenied`.
- Other: `Notification`, `MessageDisplay`, `TodoCreated`, `TodoCompleted`, `InstructionsLoaded`.

**Hook types:** `command`, `http`, `function` (SDK only) and `prompt`.

**Blocking an edit: `PreToolUse`.**

- The matcher is a regex on the tool name, such as `^(write_file|edit)$`. Claude Code aliases like `"Write|Edit"` are also accepted, matched exactly.
- Input on stdin:

  ```
  {session_id, transcript_path, cwd, hook_event_name, timestamp, permission_mode, tool_name, tool_input, tool_use_id, tool_call_id?, agent_id?}
  ```

- To deny:
  - exit 0 with stdout `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"..."}}`;
  - **or** exit **2** with the reason on stderr.
- `"ask"` becomes deny in headless mode.
- `updatedInput` replaces the tool's input.
- Command hooks get the environment variables `QWEN_PROJECT_DIR`, `CLAUDE_PROJECT_DIR` and `GEMINI_PROJECT_DIR`.

**Timeout unit gotcha:** `timeout` is in **seconds**. A value of 1000 or more is read as milliseconds, for backward compatibility.

**SessionStart:**

- The input adds `source` (`startup|resume|clear|compact`), `model` and `agent_type?`.
- Output `hookSpecificOutput.additionalContext` is added to the model context.
- Plain non-JSON stdout is added to the context too.

Libraryan's Claude Code hook script will most likely work unchanged if it reads `tool_name` and `tool_input.file_path`. Qwen's tool names are `write_file`, `edit` and `notebook_edit`, so the matcher must cover them, or use the aliases. UNVERIFIED by a live run.

## 7. Subagents, skills, extensions

**Subagents:**

- Defined in `.qwen/agents/*.md` (project) or `~/.qwen/agents/*.md`, plus extensions.
- Frontmatter: `name`, `description`, `model` (`inherit|fast|<id>|<authType>:<id>`), `approvalMode`, `tools`, `disallowedTools`, `background`, hooks.
- **Top-level named subagents run in the background by default.** Per the design doc, headless runs wait for them (UNVERIFIED by a live run).
- External executors (Claude Code through ACP, Codex) are also available.
- A parent session's permissive mode (for example yolo) overrides a stricter subagent `approvalMode`.
- To keep one agent in charge, use `--exclude-tools agent` or `permissions.deny: ["Agent"]`.
- Sources: [D/users/features/sub-agents.md](https://github.com/QwenLM/qwen-code/blob/bf118a12200abe0548c61a54df33350a9d62f8f8/docs/users/features/sub-agents.md), [D/design/2026-07-16-default-background-subagents.md](https://github.com/QwenLM/qwen-code/blob/bf118a12200abe0548c61a54df33350a9d62f8f8/docs/design/2026-07-16-default-background-subagents.md).

**Skills:**

- `SKILL.md` folders in `.qwen/skills/` or `~/.qwen/skills/`.
- Settings: `skills.enabled`, `skills.disabled`, `skills.defaultDisabled`.
- An "Auto Skill" feature can generate `.qwen/skills/auto-skill-*` folders.
- Source: [D/users/features/skills.md](https://github.com/QwenLM/qwen-code/blob/bf118a12200abe0548c61a54df33350a9d62f8f8/docs/users/features/skills.md).

**Extensions:** commands, agents, skills, hooks, rules, MCP. Source: [D/users/extension/introduction.md](https://github.com/QwenLM/qwen-code/blob/bf118a12200abe0548c61a54df33350a9d62f8f8/docs/users/extension/introduction.md).

## 8. Model choice

Qwen Code works with many providers.

- `--auth-type openai|openai-responses|anthropic|gemini|vertex-ai|qwen-oauth`, with `-m <model>`.
- Command-line overrides: `--openai-api-key` and `--openai-base-url`.
- **OpenAI-compatible:** `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` (or `QWEN_MODEL`). This covers OpenAI, OpenRouter, DashScope/QwenCloud, vLLM, **Ollama** and LM Studio. For local servers, use `openai` with a local `baseUrl`.
- **Anthropic:** `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`.
- **Gemini:** `GEMINI_API_KEY`, `GEMINI_MODEL`.
- **Vertex AI:** also supported.
- `modelProviders` in settings declares named models, each with an `envKey`.
- `--fallback-model` gives up to three fallback models on 429/503/529 errors.
- Sources: [D/users/configuration/auth.md](https://github.com/QwenLM/qwen-code/blob/bf118a12200abe0548c61a54df33350a9d62f8f8/docs/users/configuration/auth.md), [D/users/configuration/model-providers.md](https://github.com/QwenLM/qwen-code/blob/bf118a12200abe0548c61a54df33350a9d62f8f8/docs/users/configuration/model-providers.md).

## 9. Auth for unattended runs

- Use API keys from environment variables, as in section 8, or from the `env` block of `~/.qwen/settings.json` or `.qwen/.env`. Provider-specific keys such as `QWENCLOUD_API_KEY` take effect only when a `modelProviders` entry names them as its `envKey`.
- **Qwen OAuth's free tier ended on 2026-04-15.** It is no longer offered in the auth menu, and `qwen auth` is marked "(removed)".
- Without a selected auth type, a headless run fails immediately (exit 1, error in JSON). Set it in one of three ways:
  - `--auth-type`;
  - `security.auth.selectedType`;
  - having `OPENAI_API_KEY` or a similar key present.
- For flaky providers, `QWEN_CODE_UNATTENDED_RETRY=1` retries 429 and 529 responses **forever**. Pair it with `--max-wall-time`.

## 10. Install and detection

- `npm install -g @qwen-code/qwen-code` (Node 20 or later).
- Binary: `qwen`. Version: `qwen --version` (or `-v`), which prints `0.25.3`.
- Self-update: `qwen update`.
- Config directory: `~/.qwen`. Override it with `QWEN_HOME`; `QWEN_RUNTIME_DIR` moves session and log output.

## 11. Gotchas for cron-driven headless runs

1. **Output is an array:** `-o json` prints a JSON array, not one object. Take the last `type=="result"` element. There is no `total_cost_usd`, so cost must be computed from `usage` and a price table, or dropped.
2. **Exit code collision:** exit 55 means a budget was exceeded in Qwen but an untrusted workspace in Gemini CLI. A shared runtime adapter must not map exit codes across the two tools.
3. **Approval-mode spelling:** Qwen uses `auto-edit`, Gemini CLI uses `auto_edit`. Headless runs decline anything that needs approval, so the reviewer and writer modes must be chosen explicitly.
4. **`--safe-mode` turns off permission rules and hooks.** Never combine it with safety that depends on deny rules.
5. **Hook timeouts are in seconds**, and values of 1000 or more are read as milliseconds. A timeout copied from a millisecond-based configuration can change meaning.
6. **Background state on by default:**
   - Background subagents.
   - **Auto-memory**, background agents that write to `~/.qwen/projects/<project>/memory/` after sessions.
   - Auto Skill, which can create `.qwen/skills/auto-skill-*` in the repo.
   - `agents.crossSessionMessaging`, which makes the session reachable by other local Qwen sessions through a socket.

   For deterministic cron runs:
   - turn off managed auto-memory and auto skills in the settings (`/memory` toggles; `memory.enableManagedAutoMemory`);
   - set `agents.crossSessionMessaging: false`;
   - consider `--chat-recording false`;
   - consider `--exclude-tools agent`.

   The exact settings key for auto skills is UNVERIFIED.
7. **Session files pile up:** each run writes session JSONL under `~/.qwen/projects/<sanitized-cwd>/chats`.
8. **Permissions cannot be set per run with a flag.** Unlike Claude Code's `--allowedTools`, the deny rules have to live in a settings file: the project's `.qwen/settings.json`, or a private `QWEN_HOME`. `--exclude-tools` and `--allowed-tools` are the only command-line controls.
