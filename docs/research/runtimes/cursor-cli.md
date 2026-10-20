# Cursor CLI (`agent` / `cursor-agent`) as a Libraryan runtime

Researched 2026-10-20 against build `2026.10.19-6bbf2c4` (linux/arm64 tarball). `--help` was read from the
real binary without logging in, and the shipped JS bundle was grepped to fill gaps in the docs. A claim marked
"bundle" comes from that bundle, not from the docs. Anything else not in the docs is marked UNVERIFIED.

Sources:
- Headless: https://cursor.com/docs/cli/headless
- Output format: https://cursor.com/docs/cli/reference/output-format
- Permissions: https://cursor.com/docs/cli/reference/permissions
- Config: https://cursor.com/docs/cli/reference/configuration
- Hooks: https://cursor.com/docs/agent/hooks
- Third-party (Claude Code) hooks: https://cursor.com/docs/reference/third-party-hooks
- Rules: https://cursor.com/docs/context/rules
- Subagents: https://cursor.com/docs/context/subagents
- Install: https://cursor.com/docs/cli/installation

## 1. Headless invocation

```
agent -p --force --output-format json [--model M] [--mode plan|ask] [--trust] "<prompt>"
```

- `-p, --print` is the non-interactive mode. Per `--help`, print mode "has access to all tools, including write
  and shell". The headless docs add that **without `--force`, changes are only proposed and not applied**
  ("`agent -p "..."  # Won't modify files`"). The writer therefore needs `--force` (alias `--yolo`).
- The prompt is the last positional argument. The docs say nothing about stdin, so treat it as UNVERIFIED and
  pass `stdin=DEVNULL` as today.
- `--trust` trusts the workspace without a prompt. A cron run on a fresh checkout probably needs it, because
  the bundle writes a `.cursor/.workspace-trusted` marker (UNVERIFIED whether print mode prompts).
- `--workspace <path>` sets the root. `--add-dir` adds more roots. `-w/--worktree` runs in an isolated git
  worktree under the user's home directory.
- Exit codes: the docs say only "non-zero" on failure, with no specific values listed.

## 2. Machine-readable output

`--output-format text|json|stream-json`, which works only with `--print`.

The `json` mode prints one object on success:

```
{"type":"result","subtype":"success","is_error":false,"duration_ms":..,"duration_api_ms":..,
 "result":"<final text>","session_id":"..","request_id":".."}
```

- **There is no cost in USD and no turn count.** The bundle also adds an optional `usage` object (token usage)
  when the server returns one. The docs do not mention it (bundle, UNVERIFIED field names).
- **Errors:** `is_error` is always `false` in the emitted object. On failure, "No well-formed JSON object is
  emitted", the error goes to stderr, and the exit code is non-zero. A Libraryan parser must treat "exit
  non-zero OR no JSON" as `is_error`.
- `stream-json` is NDJSON with these events:
  - `system` (subtype `init`: `apiKeySource`, `cwd`, `session_id`, `model`, `permissionMode`)
  - `user`
  - `assistant`
  - `tool_call` (subtype `started`/`completed`, keyed by `readToolCall` / `writeToolCall` / ...)
  - a terminal `result` with the same fields as above

  The stream "may end early without a terminal event" on failure.
- The shape is close to Claude Code's (`type`, `subtype`, `is_error`, `result`, `session_id`), but
  `total_cost_usd` and `num_turns` are missing.

## 3. Instructions, persona, auto-read files

- **There is no `--agent` flag.** Persona options:
  - (a) Subagent files in `.cursor/agents/`, `.claude/agents/` or `.codex/agents/` (and the same folders under
    the user's home). On a name clash, `.cursor/` wins. They are invoked by `/name ...` in the prompt or
    delegated to automatically. Frontmatter fields: `name`, `description`, `model` (default `inherit`),
    `readonly`, `is_background`. A `tools` field is not documented. Whether `/name` works as the first token
    of a `-p` prompt is UNVERIFIED.
  - (b) Put the persona in the prompt or in rules.
- **Modes:** `--mode plan` ("read-only/planning ... no edits") and `--mode ask` (read-only Q&A). `--plan` is
  short for `--mode plan`.
- **Auto-read files:**
  - `AGENTS.md` at the root and in subdirectories (nested files combine with their parents).
  - `.cursor/rules/*.mdc`. A plain `.md` file in `.cursor/rules` is ignored. Frontmatter fields:
    `description`, `globs`, `alwaysApply`.
  - The bundle also references `CLAUDE.md` and `.cursor/CLOUD.md`. Whether the CLI reads `CLAUDE.md` is
    UNVERIFIED.
- **Third-party config:** with "Include third-party Plugins, Skills, and other configs" on, Cursor also loads
  Claude Code skills, agents and hooks. A forum thread reports this cannot be turned off in the CLI
  (https://forum.cursor.com/t/no-way-to-opt-out-of-third-party-claude-code-codex-config-loading-the-flag-is-hardcoded/166558).

## 4. Permissions and sandbox

- Config files: `<project>/.cursor/cli.json` (only `permissions` is allowed at project level) and the global
  `~/.cursor/cli-config.json`.
- Rule syntax: `{"permissions":{"allow":[...],"deny":[...]}}` with these entries:
  - `Shell(cmd)` matches the first token, with globs and `cmd:args`, for example `Shell(git:push*)`
    (UNVERIFIED exact arg-glob form).
  - `Read(glob)`
  - `Write(glob)`
  - `WebFetch(domain)`
  - `Mcp(server:tool)`
- **Deny beats allow.**
- What this gives Libraryan:
  - **Read-only reviewer:** `--mode plan` or `--mode ask`, without `--force`, plus `deny: ["Write(**)"]` as a
    belt.
  - **Writer:** `--force` plus `deny: ["Write(<owned docs glob>)", "Shell(git:commit*)", "Shell(git:push*)"]`.
- `--force` means "Force allow commands unless explicitly denied". Deny lists still apply under `--force`
  (docs wording; not tested).
- `approvalMode` (global) takes `allowlist | auto-review | unrestricted`. `--auto-review` uses a server-side
  classifier.
- Sandbox: `--sandbox enabled|disabled`, plus global `sandbox.mode`, `sandbox.networkAccess` and
  `sandbox.readBoundary` (`system|workspace`). The bundle ships a `cursorsandbox` binary and
  `.cursor/sandbox.json`. Linux sandbox specifics are UNVERIFIED.
- Git commit and push can be blocked with `Shell(git...)` deny rules or a `beforeShellExecution` hook.

## 5. Budget and limits

There is **no USD budget, max-turns or max-tokens flag** in `--help` or in the config docs. The bundle has a
`maxTurns` field, but nothing exposes it to the user. Limits must come from outside: the wall-clock timeout
Libraryan already applies with `killpg`.

## 6. Hooks that can block an edit, and session start

- Config files: `<project>/.cursor/hooks.json`, `~/.cursor/hooks.json` and enterprise `/etc/cursor/hooks.json`.
  The bundle also reads `~/.claude/settings.json`, `.claude/settings.json` and `.claude/settings.local.json`
  (third-party hooks, with Claude hook names mapped to Cursor's).
- Schema: `{"version":1,"hooks":{"<event>":[{"command":"...","matcher":"<regex>","timeout":30,"failClosed":false}]}}`.
- **Blocking an edit:**
  - Use `preToolUse` (fires "before any tool execution"). Input fields: `tool_name`, `tool_input`,
    `tool_use_id`, `cwd`, `model`, plus the common fields (`conversation_id`, `generation_id`,
    `hook_event_name`, `workspace_roots`, `cursor_version`, `user_email`).
  - Deny by printing `{"permission":"deny","agent_message":"..."}` or by **exiting with code 2**.
  - The bundle's tool names include `Write`, `Delete`, `Read`, `Grep`, `List` and `Fetch`. The docs do not
    explicitly confirm that a `Write` deny blocks the write (UNVERIFIED).
  - Invalid JSON from a permission hook blocks the action. Other failures let the action through unless
    `failClosed: true`.
- `afterFileEdit` fires only after the edit, so it cannot block.
- `beforeShellExecution` (allow/deny/ask) can gate `git commit` and `git push`.
- `beforeReadFile` can deny reads.
- `subagentStart` can deny a subagent.
- **Session start:** `sessionStart` (input `session_id`, `is_background_agent`, `composer_mode`). Also
  available: `sessionEnd`, `stop`, `beforeSubmitPrompt`, `preCompact`.
- CLI coverage: the docs give no per-hook CLI matrix. The bundle contains `preToolUse`, `beforeShellExecution`,
  `beforeReadFile`, `afterFileEdit`, `sessionStart`, `subagentStart` and `stop` handling, and reads
  `.cursor/hooks.json` at start (it logs a warning if the file changed mid-session). Hooks therefore load in
  the CLI, but each event is UNVERIFIED in `-p` mode.
- Gotcha: a forum report says hooks in `.claude/settings.json` were not loaded in some versions
  (https://forum.cursor.com/t/claude-hooks-dont-work/153614). Install a native `.cursor/hooks.json`; don't rely
  on the Claude Code copy.

## 7. Subagents, skills, commands

- Subagents: see section 3.
- Skills: `.cursor/skills/`, with `.claude/skills/` and `.codex/skills/` also referenced in the bundle (`SKILL.md`).
- Commands: `.cursor/commands/`.
- Plugins: `--plugin-dir`, `agent plugin`.
- MCP: `.cursor/mcp.json`, `--approve-mcps`.

## 8. Models

- `--model <id>`, for example `gpt-5`, `sonnet-4-thinking`, or bracket overrides such as
  `'claude-opus-4-8[context=1m,effort=high]'`.
- List models with `--list-models` or `agent models`.
- All models go through Cursor's backend (`--endpoint`, default `api2.cursor.sh`), so there is **no direct
  OpenAI-compatible or Ollama endpoint**.
- `agent bedrock` configures AWS Bedrock usage.
- Usage is billed to the Cursor plan, not per API key.

## 9. Auth for cron

- Set the `CURSOR_API_KEY` env var or pass `--api-key`. The headless docs present this as the way to
  authenticate scripts.
- `agent login` is browser-based (`NO_OPEN_BROWSER` disables opening a browser).
- `agent status` (alias `whoami`) checks auth.
- The bundle also knows `CURSOR_AUTH_TOKEN`, which is undocumented.

## 10. Install and detection

- Install: `curl https://cursor.com/install -fsS | bash`. This installs to `~/.local/bin`, as binaries `agent`
  and `cursor-agent`.
- The tarball ships its own `node`, `rg` and native modules and takes about **550 MB** unpacked.
- Detect with `agent --version`. It prints a date-based build string such as `2026.10.19-6bbf2c4`, not semver.
- Detection should accept either `agent` or `cursor-agent`, and note that `agent` is a very generic binary
  name.

## 11. Cron gotchas

- **Auto-updates by default** ("will try to auto-update by default"). Pin via the `channel` config key or by
  vendoring the tarball (pinning procedure UNVERIFIED).
- No cost in the output, so Libraryan's USD budget reporting is impossible. Record tokens from `usage` if
  present.
- No budget flag. Wall-clock timeout is the only cap.
- A failed run prints no JSON. Rely on the exit code.
- `-p` without `--force` silently makes no edits. A writer run that "succeeds" with no diff may just be a
  missing flag.
- Third-party Claude config (skills, agents, hooks under `.claude/`) can load implicitly. Libraryan's existing
  Claude Code hook may then fire, or fail to parse, under Cursor.
- Hook input includes `user_email`. Don't log hook stdin verbatim.
- Workspace trust prompt: pass `--trust`.
