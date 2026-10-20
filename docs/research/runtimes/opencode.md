# OpenCode as a Libraryan runtime

Researched 2026-10-20 against npm `opencode-ai` **1.19.3** (latest dist-tag). `--help` was read from the
installed binary without logging in. The `opencode run` behaviour was read from the tagged source.

Note: the repo moved from `sst/opencode` to `anomalyco/opencode` (GitHub redirects). The `dev` branch is a
rewrite (`packages/cli`, `@opencode/cli` 2.x) whose non-interactive semantics differ from 1.19.3. See
section 11.

Sources:
- CLI: https://opencode.ai/docs/cli/
- Permissions: https://opencode.ai/docs/permissions/
- Agents: https://opencode.ai/docs/agents/
- Rules: https://opencode.ai/docs/rules/
- Plugins: https://opencode.ai/docs/plugins/
- Skills: https://opencode.ai/docs/skills/
- Commands: https://opencode.ai/docs/commands/
- Providers: https://opencode.ai/docs/providers/
- Source of `run` (1.19.3): https://github.com/anomalyco/opencode/blob/v1.19.3/packages/opencode/src/cli/cmd/run.ts
- SDK types: https://github.com/anomalyco/opencode/blob/v1.19.3/packages/sdk/js/src/gen/types.gen.ts

## 1. Headless invocation

```
opencode run --agent libraryan --format json [-m provider/model] [--auto] [--dir PATH] "<prompt>"
```

- The message comes from positional args. The command fails if the message is empty.
- **stdin:** if stdin is not a TTY, it is read in full and merged into the message
  (`process.stdin.isTTY ? undefined : await Bun.stdin.text()`). Keep `stdin=DEVNULL`; a pipe that stays open
  will hang the run.
- Other flags:
  - `--command <name>` runs a custom command.
  - `-f/--file` attaches files.
  - `--variant` sets reasoning effort.
  - `--pure` runs without external plugins. **Don't use `--pure` if Libraryan's guard is a plugin.**
- `run` starts a local opencode server on a random port, unless `--attach <url>` is given.
- Exit codes: `0` on success. `1` on a session or agent error, a bad flag or a missing message. The dev branch
  also uses `130` on interrupt. No other values are documented.

## 2. Machine-readable output

`--format json` prints **NDJSON events**. There is **no single final result object**. Every line has the shape
`{type, timestamp, sessionID, ...}`. Types in 1.19.3:

- `step_start`
- `text` (`part.text`; emitted when the part finishes)
- `reasoning` (only with `--thinking`)
- `tool_use` (`part` with `tool` and `state.status` = `completed`/`error`)
- `step_finish`, whose `part` is a `StepFinishPart`: `reason`, `cost` (number, USD), and
  `tokens {input, output, reasoning, cache {read, write}}`
- `error` (`error` object; also sets exit code 1)

Mapping to Libraryan's fields:

| Libraryan field | How to compute it |
|---|---|
| final text | concatenate the `text` parts of the last step, or all of them |
| `total_cost_usd` | sum `part.cost` over all `step_finish` events |
| tokens | sum `part.tokens` |
| `num_turns` | count `step_finish` events (one per model step) |
| `is_error` | any `error` event, or a non-zero exit |

Whether subagent (`task` tool) steps appear in this stream is UNVERIFIED. The 1.19.3 loop tracks child
sessions for permissions, but it emits only parts of the main session. Their cost may be missing from the
sum. `opencode stats` / `opencode export <sessionID>` can be used to reconcile.

## 3. Instructions, persona, auto-read files

- **Named agent per run:** `--agent <name>`.
- **Agent files:** `.opencode/agents/<name>.md` (project) or `~/.config/opencode/agents/` (global). The
  filename is the agent name. Agents can also live under the `agent` key in `opencode.json`.
- **Agent frontmatter:**
  - `description` (required)
  - `mode` (`primary|subagent|all`)
  - `model`
  - `prompt`
  - `temperature`, `top_p`
  - `steps` (max agentic iterations)
  - `permission` (per-agent overrides)
  - `tools` (deprecated)
  - `hidden`, `disable`, `color`
  - Unknown keys pass through to the provider.
- **Built-in agents:**
  - `build` (default, all tools)
  - `plan` (restricted, read-only-ish)
  - Subagents `general`, `explore` and `scout`
- **Auto-read files:**
  - The project `AGENTS.md`, found by walking up from cwd. **`CLAUDE.md` is used only if there is no
    `AGENTS.md`.**
  - The global `~/.config/opencode/AGENTS.md`, falling back to `~/.claude/CLAUDE.md`.
  - Extra files from `instructions: [paths|globs|urls]` in `opencode.json`.
  - Nested `AGENTS.md` files are not auto-loaded; the docs suggest an `instructions` glob instead.
- **Claude Code compatibility:** `.claude/skills` and `~/.claude/CLAUDE.md` are read by default. Turn this off
  with `OPENCODE_DISABLE_CLAUDE_CODE`, `..._PROMPT` or `..._SKILLS`. **`.claude/agents/` is not documented as
  read**: Libraryan would have to write `.opencode/agents/libraryan.md`.

## 4. Permissions and sandbox

- **Keys:** `read`, `edit` (covers edit, write and patch), `glob`, `grep`, `bash`, `task`, `skill`, `lsp`,
  `question`, `webfetch`, `websearch`, `external_directory`, `doom_loop`.
- **Values:** `allow|ask|deny`, either per key or as an object of glob → action. **The last matching rule
  wins**, so put the `"*"` rule first.
- **Where they live:**
  - `opencode.json` `permission`
  - per-agent `permission` (merged; the agent's rules win)
  - the `OPENCODE_PERMISSION` env var (inline JSON)
  - `OPENCODE_CONFIG_CONTENT` (whole config inline)
- **Defaults:** almost everything is `allow`. `doom_loop` and `external_directory` default to `ask`. `.env`
  reads are `ask`. Non-interactive `run` also adds a deny for `question`, `plan_enter` and `plan_exit`
  (confirmed by `opencode agent list`).
- **Non-interactive "ask" (1.19.3):** an `ask` rule is **auto-rejected** (prints
  `permission requested: ...; auto-rejecting`). `--auto` (aliases `--yolo`, `--dangerously-skip-permissions`)
  replies `once` to every `ask`, but explicit `deny` still wins.
- What this gives Libraryan:
  - **Writer** (`--agent libraryan`):

    ```
    "permission": {
      "edit": {"*": "allow", "<owned glob>": "deny"},
      "bash": {"*": "allow", "git commit*": "deny", "git push*": "deny"}
    }
    ```

  - **Read-only reviewer:** an agent with `edit: deny` and `bash: {"*": "deny", "git diff*": "allow", ...}`,
    or the built-in `plan` agent.
- **No OS-level sandbox.** Permissions are all there is.

## 5. Budget and limits

- **No USD budget or max-turns flag on `run`.** The only cap is the per-agent `steps` (frontmatter or config).
  Without it, "the agent will continue to iterate until the model chooses to stop".
- `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX` caps output tokens per response.
- Cost is reported after the fact (section 2), so a budget must be enforced by watching `step_finish` cost
  in the stream and killing the process group.

## 6. Hooks that can block an edit, and session start

- **Plugins:**
  - Location: `.opencode/plugins/*.{js,ts}` (project) or `~/.config/opencode/plugins/`; npm plugins are
    added via `opencode plugin <module>`.
  - Signature: `export const P = async ({ project, client, $, directory, worktree }) => ({ ...hooks })`.
  - **Blocking:** in `"tool.execute.before": async (input, output) => { ... }`, **throw an Error** to deny.
    The docs' example is `if (input.tool === "read" && output.args.filePath.includes(".env")) throw new
    Error("Do not read .env files")`. For edits, match `input.tool` in `edit|write|patch` (exact tool ids
    UNVERIFIED) and `output.args.filePath`.
  - **Session start:** the `session.created` event. Other events include `session.idle`, `session.error`,
    `permission.asked`, `file.edited`, `tool.execute.after` and `shell.env`.
  - Plugins are JS/TS run by Bun, not shell commands. Libraryan would ship a small `.ts` file instead of
    reusing its Claude Code hook script, or have the plugin shell out to it via `$`.
  - Whether `tool.execute.before` fires for tool calls made inside subagents is UNVERIFIED. Back the plugin
    with a `permission.edit` deny rule, which applies to every agent.
- Claude Code `settings.json` hooks are not read by OpenCode.

## 7. Subagents, skills, commands

- **Subagents:** any agent with `mode: subagent`, invoked by the `task` tool or `@name`. Gate them with
  `permission.task`.
- **Skills:** `<name>/SKILL.md` under `.opencode/skills/`, `.claude/skills/` or `.agents/skills/` (plus the
  global equivalents). Frontmatter fields: `name`, `description`, `license`, `compatibility`, `metadata`
  (`opencode/slash`, `opencode/autoinvoke`).
- **Custom commands:** `.opencode/commands/<name>.md` (frontmatter `description`, `agent`, `model`,
  `subtask`), runnable headless with `opencode run --command <name> <args>`.

## 8. Models

- Format is `-m provider/model`. Providers come from the AI SDK and Models.dev ("75+ LLM providers").
- OpenAI-compatible endpoints use `@ai-sdk/openai-compatible` with `options.baseURL`; endpoints that speak
  `/v1/responses` use `@ai-sdk/openai`.
- **Ollama:** `baseURL: http://localhost:11434/v1`. The docs suggest raising `num_ctx` to 16k-32k for tool
  calling.
- LM Studio and llama.cpp work the same way.
- `--variant` sets reasoning effort.

## 9. Auth for cron

- **Provider env vars are detected automatically.** `opencode providers list` with `ANTHROPIC_API_KEY` set
  shows "Environment: Anthropic ANTHROPIC_API_KEY" with 0 stored credentials (verified locally).
- Config can also use `{env:VAR}` or `{file:path}` in `apiKey`.
- Interactive `opencode providers login` stores credentials in `~/.local/share/opencode/auth.json`.
- No OpenCode account is needed for BYO keys.

## 10. Install and detection

- Install: `npm i -g opencode-ai`. Also available: `curl -fsSL https://opencode.ai/install | bash`, brew,
  and others.
- The binary is `opencode` (a compiled Bun binary pulled in as a platform optional dependency).
- Version: `opencode --version` prints semver, e.g. `1.19.3`.

## 11. Cron gotchas

- **Major rewrite in flight.** On the `dev` branch (2.x), non-interactive `ask` is rejected *with feedback*
  and the model continues, instead of the 1.19.3 behaviour. The JSON event code also moved. Pin the version
  and re-check `run` when upgrading.
- **Auto-update:** set `OPENCODE_DISABLE_AUTOUPDATE=1` (or `"autoupdate": false`).
- **stdin is read when it is not a TTY.** Always use `stdin=DEVNULL`.
- No final result object: Libraryan's parser must aggregate events.
- Session data accumulates in the user data dir (`OPENCODE_DISABLE_PRUNE` exists, so pruning is the
  default).
- `.claude/skills` and `~/.claude/CLAUDE.md` leak in by default. Set `OPENCODE_DISABLE_CLAUDE_CODE=1` for
  deterministic runs.
- `external_directory` defaults to `ask`, which means auto-rejected headless. That is a good default.
