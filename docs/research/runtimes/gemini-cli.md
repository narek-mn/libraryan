# Gemini CLI as a Libraryan runtime

Researched 2026-10-20 against `@google/gemini-cli` **0.64.0** (latest stable, released 2026-10-13), the `--help` output of that build, its bundled source, and the docs in `google-gemini/gemini-cli` at commit `76e4d7c`.

Doc links below use `D/` = `https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/`. The same pages are published at `https://geminicli.com/docs/`.

"Verified in source" means read in the 0.64.0 npm bundle. "Probed" means a local run with no credentials, which fails before any model call.

## 1. Headless invocation

```
gemini -p "<prompt>" -o json --approval-mode auto_edit --skip-trust [-m <model>]
```

- `-p/--prompt <text>` forces headless mode. A bare positional `query` starts the **interactive** UI. Headless mode also kicks in when there is no TTY, but pass `-p` explicitly. Sources: `--help`, [D/cli/headless.md](https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/cli/headless.md).
- **Stdin:** if stdin has data, the `-p` text is appended to it. With `stdin=DEVNULL`, which is what Libraryan uses, only the `-p` text is sent.
- **Exit codes** (verified in source as `Fatal*Error` classes; the docs list only 0/1/42/53):

  | Code | Meaning |
  | --- | --- |
  | 0 | success |
  | 1 | general or API error |
  | 41 | auth (probed: no credentials gives 41) |
  | 42 | input |
  | 44 | sandbox |
  | 52 | config |
  | 53 | turn limit (`model.maxSessionTurns`) |
  | 54 | fatal tool execution error |
  | 55 | **untrusted workspace** |
  | 130 | cancelled (SIGINT) |

- **Timeouts:** there is no wall-clock flag; the caller must enforce one, as Libraryan already does. Related limits:
  - Shell-tool inactivity timeout: `tools.shell.inactivityTimeout`, default 300 s.
  - Hook timeout: default 60000 **ms**.
  - Subagent `timeout_mins`: default 10.

## 2. Machine-readable output

`-o text|json|stream-json`.

**`-o json`** prints one pretty-printed object at the end (verified in source, `JsonFormatter`):

```json
{ "session_id": "...", "response": "<final text>", "stats": { ... }, "error": {"type": "...", "message": "...", "code": 41}, "warnings": ["..."] }
```

- `stats` is the raw session-metrics object:
  - `stats.models.<model>.api.{totalRequests,totalErrors,totalLatencyMs}`
  - `stats.models.<model>.tokens.{input,prompt,candidates,total,cached,thoughts,tool}`
  - `stats.tools.{totalCalls,totalSuccess,totalFail,totalDurationMs,totalDecisions,byName}`
  - `stats.files.{totalLinesAdded,totalLinesRemoved}`
- **No cost in USD, no turn count, no `is_error` flag.** Treat the presence of `error` as the error flag. Exit 0 is possible with `error.type == "INVALID_STREAM"`, so check both the exit code and `error`.
- A run stopped by a hook or a tool still gets exit 0 and JSON on stdout, with the reason added to `warnings`.
- **Gotcha (probed and verified in source):** on fatal errors (auth, turn limit, untrusted workspace, cancellation) the error JSON goes to **stderr**, prefixed `[ERROR] `, and **stdout is empty**. A caller that reads only stdout sees an empty result. Example stderr from a run with no credentials (exit 41):

  ```
  [ERROR] {"session_id": "...", "error": {"type": "Error", "message": "Please set an Auth method in your <home>/.gemini/settings.json or specify one of the following environment variables before running: GEMINI_API_KEY, GOOGLE_GENAI_USE_VERTEXAI, GOOGLE_GENAI_USE_GCA", "code": 41}}
  ```

**`-o stream-json`** writes JSONL events: `init`, `message`, `tool_use`, `tool_result`, `error`, `result`. The final event has this shape (verified in source):

```
{"type":"result","timestamp":"...","status":"success"|"error","error":{...}?,"stats":{"total_tokens","input_tokens","output_tokens","cached","input","duration_ms","tool_calls","models":{...}}}
```

Stream mode also writes fatal errors to stdout as a `result` event, so it is easier to parse than `json` for an unattended caller.

## 3. Instructions and persona

- **No `--agent` flag and no per-run system-prompt flag.** The options are:
  - `GEMINI_SYSTEM_MD=<path>` (environment variable) **replaces** the whole built-in system prompt with that file. `=1` means `./.gemini/system.md`. The file can use `${AgentSkills}` and `${SubAgents}` placeholders. A missing file is a hard error. Source: [D/cli/system-prompt.md](https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/cli/system-prompt.md).
  - Put the persona text in the prompt itself.
  - Prefix the prompt with `@<subagent-name>` to push delegation to a custom subagent. The main agent still runs and calls the subagent as a tool. Whether this behaves the same in `-p` mode is UNVERIFIED.
- **Context files read automatically:**
  - `~/.gemini/GEMINI.md`.
  - `GEMINI.md` in the workspace directories and their parent directories.
  - "Just-in-time" `GEMINI.md` files in directories that tools touch.
  - Imports with `@file.md` syntax.
  - Sources: [D/cli/gemini-md.md](https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/cli/gemini-md.md), [D/reference/memport.md](https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/reference/memport.md).
- **AGENTS.md is not read by default** (verified in source: `DEFAULT_CONTEXT_FILENAME = "GEMINI.md"`). To read it, set `"context": {"fileName": ["AGENTS.md", "GEMINI.md"]}` in settings.
- The directory tree is included in the first request by default (`context.includeDirectoryTree`).

## 4. Permissions and sandbox

**Approval modes** (`--approval-mode default|auto_edit|yolo|plan`; `-y` is the same as yolo). Note that the value is spelled `auto_edit`, not `auto-edit`. In headless mode the policy engine's default decision is **deny** (verified in source), and any `ask_user` result also becomes deny. The bundled `write.toml` has an explicit headless deny rule for `replace`, `write_file`, `run_shell_command`, `activate_skill` and `web_fetch`. In practice:

| Mode | Effect in headless mode |
| --- | --- |
| `default` | read-only tools allowed (`read_file`, `glob`, `grep_search`, `list_directory`, …); edits, shell, **skill activation** and `web_fetch` denied |
| `auto_edit` | `write_file` and `replace` allowed (an `allowed-path` safety checker keeps writes inside the workspace), plus `web_fetch`; **shell still denied** |
| `yolo` | everything allowed (default-tier rule at priority 998) |
| `plan` | read-only. **Gotcha:** in headless mode `exit_plan_mode` is auto-approved, and leaving plan mode switches to **YOLO** ([D/cli/plan-mode.md](https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/cli/plan-mode.md) "Non-interactive execution"). Do not use plan mode as a read-only guarantee without also denying `exit_plan_mode`. |

**Policy engine.** Rules are TOML files with:

- `toolName`, `commandPrefix`, `commandRegex`, `argsPattern`, `decision` (`allow|deny|ask_user`), `priority` 0–999
- `modes`, `interactive`, `denyMessage`, `subagent`, `allowRedirection`

The per-run flag `--policy <file|dir>` loads files at the **User tier** and replaces `~/.gemini/policies` for that run (verified in source). User-tier rules outrank all built-in default rules, **including yolo's allow-all**, so this works for both writer and reviewer:

```toml
[[rule]]
commandRegex = "git (commit|push)"
decision = "deny"
priority = 900
denyMessage = "Libraryan commits, not the agent"
```

- Project-level policy files (`.gemini/policies`) **do not work**: the workspace tier is disabled ([issue #18186](https://github.com/google-gemini/gemini-cli/issues/18186)).
- `--admin-policy` loads files at the admin tier.
- The `tools.core`, `tools.allowed` and `tools.exclude` settings still exist, but `--allowed-tools` is deprecated in favour of policies.
- Source: [D/reference/policy-engine.md](https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/reference/policy-engine.md).

**Read-only reviewer recipe:** `--approval-mode default` plus a `--policy` file that allows only what the reviewer needs (for example `activate_skill`, or specific read-only shell commands such as `git diff`). Without it, skills and every shell command are denied.

**Sandbox:** `-s/--sandbox`, or `tools.sandbox` set to docker, podman, lxc, or macOS seatbelt. Network is off by default (`tools.sandboxNetworkAccess`). Source: [D/cli/sandbox.md](https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/cli/sandbox.md).

**Folder trust is on by default in the code** (verified in source: `security.folderTrust.enabled ?? true`; the configuration reference agrees, but `trusted-folders.md` says it is off). In an untrusted folder, headless mode **exits 55** (`FatalUntrustedWorkspaceError`). If the folder is untrusted, the project's `.gemini/settings.json` and `.env` are ignored, so project hooks never run. Always pass `--skip-trust` or set `GEMINI_CLI_TRUST_WORKSPACE=true`. Source: [D/cli/trusted-folders.md](https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/cli/trusted-folders.md).

## 5. Budget and limits

- `model.maxSessionTurns` in settings.json (default -1, meaning unlimited). There is no command-line flag or environment variable for it. Exceeding it exits 53.
- Subagents have per-agent `max_turns` (default 30) and `timeout_mins` (default 10) in their frontmatter.
- **No cost cap, no USD reporting, no token cap, no wall-clock limit.** Budgets would have to come from token counts in `stats` plus a caller-side timeout.

## 6. Hooks

Hooks live in the `hooks` object of settings.json. Sources: [D/hooks/reference.md](https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/hooks/reference.md), [D/hooks/index.md](https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/hooks/index.md).

**Where they are loaded from:**

- Project: `.gemini/settings.json`, only in trusted folders.
- User: `~/.gemini/settings.json`.
- System: `/etc/gemini-cli/settings.json`.
- Extensions: `hooks/hooks.json`.
- Master switch: `hooksConfig.enabled`, default true.

**Event names differ from Claude Code:**

| Gemini event | Notes |
| --- | --- |
| `BeforeTool` / `AfterTool` | |
| `BeforeAgent` / `AfterAgent` | |
| `BeforeModel` / `AfterModel` / `BeforeToolSelection` | |
| `SessionStart` / `SessionEnd` | |
| `Notification` | |
| `PreCompress` | |

**Blocking an edit:** `BeforeTool` with `matcher` (a regex on the tool name), for example `"write_file|replace"`. Gemini's tool names are `write_file` and `replace`, not `Write`/`Edit`.

- Input on stdin:

  ```
  {session_id, transcript_path, cwd, hook_event_name, timestamp, tool_name, tool_input, mcp_context?, original_request_name?}
  ```

- To deny, do either of these:
  - exit 0 with stdout `{"decision":"deny","reason":"..."}`. `"block"` is an alias. The reason goes to the model as a tool error and the turn continues.
  - exit **2** with the reason on stderr.
- `{"continue": false}` kills the whole agent loop.
- `hookSpecificOutput.tool_input` merges new values into the tool's arguments.
- **Stdout must contain only the JSON.**
- Hooks run with environment variables `GEMINI_PROJECT_DIR`, `GEMINI_SESSION_ID` and `GEMINI_CWD`, plus `CLAUDE_PROJECT_DIR` as an alias.
- `timeout` is in **milliseconds** (default 60000).

**SessionStart:** the input adds `source` (`startup|resume|clear`). Its output `hookSpecificOutput.additionalContext` is **prepended to the user prompt** in headless mode. The hook is advisory only: it cannot block startup.

**Project-hook fingerprinting** (verified in source): a project hook seen for the first time, or whose command changed, prints a `WARNING` to stderr, **still runs**, and is then recorded as trusted. This does not block unattended runs.

## 7. Subagents, skills, extensions

**Subagents:**

- Defined in `.gemini/agents/*.md` or `~/.gemini/agents/*.md`.
- Frontmatter: `name`, `description`, `kind`, `tools`, `mcpServers`, `model`, `temperature`, `max_turns`, `timeout_mins`.
- Exposed to the main agent as tools.
- On by default (`experimental.enableAgents`).
- Built-ins: `codebase_investigator`, `cli_help`, `generalist`, `browser`.
- Policy rules can be scoped to a subagent with `subagent = "..."`.
- Source: [D/core/subagents.md](https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/core/subagents.md).

**Skills:**

- `SKILL.md` folders in `.gemini/skills/` or `.agents/skills/` (the `.agents` folder wins within a tier), and at user level in `~/.gemini/skills/` or `~/.agents/skills/`.
- Loaded through the `activate_skill` tool, which is **denied in headless mode unless a policy allows it**.
- Source: [D/cli/skills.md](https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/cli/skills.md).

**Extensions:**

- A `gemini-extension.json` manifest, which can bundle commands, `hooks/hooks.json`, `skills/`, `agents/` and `policies/`.
- `-e` selects which extensions to load.
- Source: [D/extensions/reference.md](https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/extensions/reference.md).

## 8. Model choice

- `-m/--model`, `GEMINI_MODEL`, or `model.name`.
- **Gemini models only**, through the Gemini API, Vertex AI, or Code Assist.
- `GOOGLE_GEMINI_BASE_URL` and `GOOGLE_VERTEX_BASE_URL` override the endpoint, for example to go through a proxy, but the protocol is still Gemini's.
- There is no built-in OpenAI-compatible or Ollama provider. Local Gemma is supported only as a *routing classifier* (`gemini gemma`, experimental), not as the main model.
- Sources: [D/reference/configuration.md](https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/reference/configuration.md) (environment variables), [D/core/local-model-routing.md](https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/core/local-model-routing.md).

## 9. Auth for unattended runs

- **Gemini API key:** `GEMINI_API_KEY` (or `GOOGLE_API_KEY`).
- **Vertex AI:** `GOOGLE_GENAI_USE_VERTEXAI=true` plus `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, and either Application Default Credentials or `GOOGLE_APPLICATION_CREDENTIALS` (a service-account key).
- `.gemini/.env` and `~/.gemini/.env` are loaded automatically; the project file only in trusted folders.
- Cached "Sign in with Google" login is reused in headless mode, per the docs ([D/get-started/authentication.mdx](https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/get-started/authentication.mdx) "Running in headless mode").
- The docs recommend an API key or Vertex AI for headless runs.
- The FAQ warns that driving Gemini CLI's OAuth from third-party tools can violate the terms of service ([D/resources/faq.md](https://github.com/google-gemini/gemini-cli/blob/76e4d7c046c7dab5727787da378b9c06bf0948cf/docs/resources/faq.md)). Use an API key for cron.

## 10. Install and detection

- `npm install -g @google/gemini-cli` (needs Node 20 or later).
- Binary: `gemini`. Version: `gemini --version` (or `-v`), which prints `0.64.0`.
- Config directory: `~/.gemini`. Override it with `GEMINI_CLI_HOME`.

## 11. Gotchas for cron-driven headless runs

1. **Errors go to stderr in `-o json` mode, and stdout is empty.** Capture stderr, or use `-o stream-json`, which writes the error as a `result` event on stdout.
2. **Folder trust is on by default:** without `--skip-trust` or `GEMINI_CLI_TRUST_WORKSPACE=true`, a headless run exits 55. Even when trust does not cause a hard failure, an untrusted folder silently drops the project's settings and hooks.
3. Headless mode **denies by default**:
   - Skills (`activate_skill`) and shell need explicit `--policy` allow rules.
   - `auto_edit` still denies shell.
4. `--approval-mode plan` in headless mode can switch itself to **YOLO** when the model leaves plan mode.
5. **No cost reporting:** `total_cost_usd` and `--max-budget-usd` have no equivalent. The only limits are a settings-only turn limit plus the caller's timeout.
6. **Hook protocol differs from Claude Code:**

   | | Claude Code | Gemini CLI |
   | --- | --- | --- |
   | Pre-tool event | `PreToolUse` | `BeforeTool` |
   | Tool names to match | `Write`/`Edit` | `write_file`/`replace` |
   | Deny output | `permissionDecision` | `decision:"deny"` |
   | Timeout unit | seconds | milliseconds |

   Libraryan's Claude Code hook config cannot be reused as-is. The script can be shared if it maps both input shapes; Gemini sets `CLAUDE_PROJECT_DIR` as an alias.
7. Project-level policy files are ignored. Policies must be passed with `--policy` or put in `~/.gemini/policies`.
8. A timeout enforced by the caller (SIGKILL) leaves no JSON at all, because `-o json` is written once, at the end. Use `stream-json` if partial usage numbers are needed after a kill.
