# GitHub Copilot CLI as a Libraryan runtime

Researched 2026-10-20 against **GitHub Copilot CLI 1.0.100** (npm `@github/copilot`, which pulls in
`@github/copilot-linux-arm64`). Sources: the tool's own `--help` and `copilot help <topic>` (environment, limits,
permissions, providers, billing, config, sandbox), official docs at docs.github.com, and **local runs against a fake
OpenAI-compatible endpoint** (`COPILOT_OFFLINE=true` + `COPILOT_PROVIDER_BASE_URL` pointing at a mock
`/v1/chat/completions` server, with no GitHub login and no real model). "Observed" means seen in those runs. "UNVERIFIED" means not confirmed.

Key docs:
- Hooks reference: https://docs.github.com/en/copilot/reference/hooks-configuration
- Programmatic reference: https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-programmatic-reference
- Run programmatically: https://docs.github.com/en/copilot/how-tos/copilot-cli/automate-copilot-cli/run-cli-programmatically
- Command reference: https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference
- Auth: https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/authenticate-copilot-cli
- Install: https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli
- Repo: https://github.com/github/copilot-cli

## 1. Headless invocation

```
copilot -p "<prompt>" --allow-all-tools --no-ask-user [--trust-folder] [--agent NAME] \
        [--output-format json] [-s] [--usage-output-file FILE] [--model M] [--max-ai-credits N] [-C DIR]
```
- `-p/--prompt <text>` runs non-interactively and exits. A piped stdin prompt also works (docs mention "`-p` or piped standard input").
- `--allow-all-tools` (env `COPILOT_ALLOW_ALL`) is "required for non-interactive mode" (`--help`), unless every tool the
  run needs is pre-approved with `--allow-tool`.
- `--no-ask-user` removes the `ask_user` tool. `-s/--silent` prints only the agent response.
- Exit codes (observed): `0` on success, `1` on a session error (provider unreachable). The JSONL `result` record repeats
  them as `exitCode`. A documented table exists only for `copilot workflow run` (0/1/2/130).
- No wall-clock timeout flag. Observed: on transport failure it retries 5 times and then exits 1 within about 25 s. Keep an
  external timeout anyway.

## 2. Machine-readable output

`--output-format json` prints JSONL (one event per line, each with `type`, `data`, `id`, `timestamp`, `parentId`, and
`ephemeral` on some). Observed sequence for a successful run (ephemeral events left out):
```
{"type":"user.message","data":{"content":"…",…}}
{"type":"assistant.turn_start","data":{"turnId":"0",…}}
{"type":"tool.execution_start","data":{"toolCallId","toolName":"create","arguments":{…}}}
{"type":"tool.execution_complete","data":{"toolCallId","success":false,"error":{"message":"Denied by preToolUse hook: …","code":"denied"}}}
{"type":"assistant.message","data":{"content":"…final text…","toolRequests":[],"model":"…",…}}
{"type":"assistant.turn_end","data":{"turnId":"0"}}
{"type":"result","timestamp":"…","sessionId":"…","exitCode":0,
 "usage":{"premiumRequests":0,"totalApiDurationMs":18,"sessionDurationMs":280,
          "codeChanges":{"linesAdded":0,"linesRemoved":0,"filesModified":[]}}}
```
On failure there's also `{"type":"session.error","data":{"errorType":"query","message":"…"}}`, and `result.exitCode` is 1.
Ephemeral noise includes `session.skills_loaded`, `session.mcp_servers_loaded`, `model.call_start/failure/finished` and
`assistant.turn_retry`.

`--usage-output-file FILE` (observed contents): `totalPremiumRequestCost`, `totalUserRequests`, `totalNanoAiu`,
`aiCreditsStatus`, `totalApiDurationMs`, `sessionStartTime`, `codeChanges{linesAdded,linesRemoved,filesModifiedCount,filesModified}`,
`modelMetrics.<model>.{requests{count,cost}, usage{inputTokens,outputTokens,cacheReadTokens,cacheWriteTokens}, totalNanoAiu}`,
`agentMetrics.<agent>…`, `providerModelMetrics[]`, `currentModel`, `lastCallInputTokens`, `lastCallOutputTokens`.

| Libraryan need | Copilot field |
|---|---|
| final text | last `assistant.message` → `data.content` (or `-s` plain stdout) |
| cost USD | **not reported**. Billing is in premium requests / AI credits (`result.usage.premiumRequests`, usage-file `totalPremiumRequestCost`, `totalNanoAiu`). With BYOK the observed values were 0 / `"unavailable"`. How real credit values map to USD is UNVERIFIED |
| tokens | usage file `modelMetrics.<m>.usage.*` (observed: correct input/output counts from the mock) |
| turn count | not reported directly. Count `assistant.turn_start` events |
| error flag | `result.exitCode != 0`, `session.error` event, or the process exit code |
| files touched | `result.usage.codeChanges.filesModified` |

## 3. Instructions / persona

- `--agent <name>` picks a custom agent. Observed: it loads **both** `.github/agents/<name>.agent.md` **and**
  `.claude/agents/<name>.md`. Libraryan's existing `libraryan.md` (Claude frontmatter
  `tools: Read, Edit, Write, Glob, Grep, Bash, Agent, Task`) loaded unchanged. Claude tool names were mapped to
  `view, create, edit, glob, grep, bash, task, …`, and the body was injected into the system prompt.
  Docs: "If a custom agent is used, its model definition takes precedence over `--model`."
- No `--system-prompt` flag. Instruction files are auto-read (observed via `copilot instruction list` plus the request body):
  `.github/copilot-instructions.md`, `AGENTS.md`, **`CLAUDE.md`**, `GEMINI.md`. Extra dirs come from
  `COPILOT_CUSTOM_INSTRUCTIONS_DIRS`. Turn them all off with `--no-custom-instructions`.
- Repo config is only trusted when the folder is trusted (see §11).

## 4. Permissions & sandbox

- `--allow-tool` / `--deny-tool` take patterns `shell(cmd:*)`, `shell(git push)`, `write(path)`, `read`, `url(domain)`,
  `memory`, `<mcp-server>(tool)`. **Deny wins over allow, even over `--allow-all-tools`** (`copilot help permissions`).
  The git/gh matching works at the first-level subcommand (`shell(git:*)` matches `git push`).
- `--available-tools` / `--excluded-tools` control what the model even sees.
- Edit without prompts: `--allow-all-tools` (or `--allow-tool='write'` plus specific `shell(...)` patterns).
- Read-only reviewer: `--available-tools` limited to read tools, or `--deny-tool='write'` with a narrow shell allowlist
  (`--allow-tool='shell(git log:*)'` …). The reviewer's agent file `tools:` list also limits it (observed: `tools: ["view"]`
  left only `view, skill, sql`).
- Preventing commit/push (verified): `--deny-tool='shell(git commit)' --deny-tool='shell(git push)'` worked even with
  `--allow-all-tools`. The tool result was `"Permission to run this tool was denied due to the following rules: \`shell(git commit)\`"`.
- Paths: by default file access is limited to the cwd tree plus the temp dir (`--disallow-temp-dir`, `--add-dir`,
  `--allow-all-paths`).
- Optional OS sandbox for shell commands (`--sandbox` / `/sandbox enable`). On Linux it uses bubblewrap ≥0.5 plus slirp4netns,
  util-linux ≥2.35 and iptables (`copilot help sandbox`). Built-in file edits are only "best-effort" sandboxed. It's off by default.

## 5. Budget / limits

- `--max-ai-credits <credits>`: per-session AI-credit cap, **minimum 30**, a *soft* cap (checked after each model response;
  subagents share it) (`copilot help limits`).
- `--max-autopilot-continues <count>` (default 5) only applies in autopilot mode.
- **No max-USD, max-turns or max-tokens flag.** `COPILOT_PROVIDER_MAX_PROMPT_TOKENS` / `_MAX_OUTPUT_TOKENS` are per-call
  limits for BYOK, not budgets.

## 6. Hooks

- Sources (all run): policy `/etc/github-copilot/policy.d/*.json`; repo `.github/hooks/*.json`; user `~/.copilot/hooks/*.json`
  (or `$COPILOT_HOME/hooks/`); an inline `hooks` key in `.github/copilot/settings(.local).json` / `~/.copilot/settings.json`;
  **and the repo's `.claude/settings.json` / `.claude/settings.local.json`** (hooks reference). Plugins too.
- Native format: `{"version":1,"hooks":{"preToolUse":[{"type":"command","bash":"…","timeoutSec":30}],"sessionStart":[…]}}`.
  Events: `sessionStart, sessionEnd, userPromptSubmitted, preToolUse, postToolUse, postToolUseFailure, permissionRequest,
  agentStop, subagentStart, subagentStop, errorOccurred, preCompact, notification`. Each has a PascalCase alias.
- PreToolUse input:
  - native (observed): `{"sessionId","timestamp","cwd","toolName":"create","toolArgs":{"path":"<abs>","file_text":"…"}}`
  - Claude-compatible, from `.claude/settings.json` with `matcher:"Edit|Write|MultiEdit"` (observed):
    `{"hook_event_name":"PreToolUse","session_id","timestamp","cwd","tool_name":"Write","tool_input":{"path":"<abs>","file_text":"…"}}`.
    `create` maps to `Write` and `edit` maps to `Edit`.
  - **`tool_input` keeps Copilot's argument names (`path`, `file_text`, `old_str`, `new_str`), not Claude's `file_path`/`content`.**
    A guard that reads only `tool_input.file_path` (like Libraryan's current `cchooks.py`) gets nothing and **fails open** under Copilot.
- Deny (verified): exit code `2`. The tool result is `"Denied by preToolUse hook: hook exited with code 2"`, and the write didn't
  happen even with `--allow-all-tools`. You can also print JSON `{"permissionDecision":"deny","permissionDecisionReason":"…"}`
  (with `modifiedArgs` to rewrite). Per docs, a crash or other non-zero exit also denies. **A timeout (default 30 s) lets the call
  through** (fail-open).
- sessionStart (verified): input `{"sessionId","timestamp","cwd","source":"new|startup|resume","initialPrompt"}`. Output
  `{"additionalContext":"…"}` was injected into the model request. `prompt`-type entries don't run in `-p` mode.
- Tool set depends on the model (observed). Claude-family model IDs get `create` / `edit`. GPT-family IDs get a freeform
  `apply_patch` custom tool and no `create`/`edit`. Hook `tool_name` and `tool_input` for `apply_patch` are **UNVERIFIED**.
  It's probably a patch text with no path field, so a guard must parse it.

## 7. Subagents / skills

- Built-in `task` tool with `agent_type` enum `explore, task, general-purpose, code-review, research, security-review`
  (observed in the tool schema), plus `read_agent/list_agents/write_agent` and `--fleet` for parallel orchestration.
  Spawning a *custom* agent by name as a subagent is UNVERIFIED (the observed `agent_type` is a fixed enum). The independent
  reviewer should stay a separate `copilot -p --agent libraryan-reviewer` process.
- `subagents.agents.<name>` config sets per-subagent model and effort.
- Skills (`SKILL.md`) are discovered from `.github/skills/`, `.agents/skills/` **and `.claude/skills/`** (project), and
  `~/.copilot/skills/`, `~/.agents/skills/` (user) (`copilot skill --help`). Observed: Libraryan-style
  `.claude/skills/<name>/SKILL.md` was listed and offered.

## 8. Model choice

- `--model` / `COPILOT_MODEL` picks from Copilot's catalog (Claude, GPT, Gemini, Grok and others; `copilot help config`) or `auto`.
- BYOK (`copilot help providers`): `COPILOT_PROVIDER_BASE_URL` + `COPILOT_PROVIDER_TYPE=openai|azure|anthropic` +
  `COPILOT_PROVIDER_API_KEY` (or `_BEARER_TOKEN`, `_API_KEY_COMMAND`), `COPILOT_PROVIDER_WIRE_API=completions|responses`,
  `COPILOT_PROVIDER_MODEL_ID` / `_WIRE_MODEL`, `COPILOT_PROVIDER_HEADERS`. "openai" covers Ollama, vLLM and Foundry Local.
  `COPILOT_OFFLINE=true` skips GitHub auth, telemetry and auto-update. Observed working with no GitHub login.

## 9. Auth for unattended runs

- Precedence: `COPILOT_GITHUB_TOKEN` > `GH_TOKEN` > `GITHUB_TOKEN` > keychain OAuth (`copilot login`) > `gh auth token`.
- For cron, use a **fine-grained PAT** (`github_pat_`, user-owned) with the **"Copilot Requests"** account permission. Classic `ghp_`
  tokens are **not supported**. An active Copilot subscription is required, and org policy can disable the CLI.
- A logged-in OAuth session lives in the OS keychain (`copilot-cli` service; Linux libsecret). On headless Linux without
  libsecret it offers plaintext `~/.copilot/config.json`. Under cron the keychain may be locked or unreachable, so prefer the env token
  (UNVERIFIED whether the keychain works from cron).
- BYOK + `COPILOT_OFFLINE=true` needs no GitHub auth at all.

## 10. Install & detection

- `npm install -g @github/copilot` (docs: **Node.js 22+**), `brew install --cask copilot-cli`,
  `winget install GitHub.Copilot`, `curl -fsSL https://gh.io/copilot-install | bash`, or release binaries. Windows needs PowerShell 6+.
- Binary `copilot`. `copilot --version` prints **two lines** (`GitHub Copilot CLI 1.0.100.` / `Run 'copilot update' …`),
  so parse only the first. `copilot version` also exists.

## 11. Gotchas for cron-driven headless runs

- **Repo hooks, agents and skills need folder trust.** Observed: without `--trust-folder`, `.github/hooks/*.json` silently did
  not run and the guarded write **succeeded**. Fixes: `--trust-folder` (one session), `COPILOT_ALLOW_ALL=true` (exactly
  `"true"` also trusts the cwd), or `trustedFolders` in `~/.copilot/settings.json`. Libraryan must pass one of these, or its guard is off.
- Hook timeout allows the tool call (fail-open). Keep guard hooks fast.
- `.claude/settings.json` hooks are honoured. That's convenient, but Libraryan's hook must accept both `file_path` and `path`
  (and the snake/camel payload variants) before it relies on that.
- Auto-update downloads in the background unless `CI` is set, `COPILOT_AUTO_UPDATE=false`, or `--no-auto-update`. Pin it for
  reproducible cron runs.
- Memory (`memory` setting) is on in interactive mode but off in `-p` unless `--enable-memory` is set. `includeCoAuthoredBy` (default true)
  makes the agent add co-author trailers if it commits.
- Child-process env markers (observed): `COPILOT_CLI`, `COPILOT_AGENT_SESSION_ID`, `COPILOT_CLI_BINARY_VERSION`, `COPILOT_MODEL`.
  `COPILOT_PROVIDER_*` was not passed through to child shells. `--secret-env-vars` redacts others.
- Telemetry: `--disable-client-telemetry`. Logs go to `~/.copilot/logs/` (`--log-dir`).
- Built-in GitHub MCP server is on by default (`--disable-builtin-mcps` turns it off) and could act on GitHub (issues, PRs) with the run's token.
