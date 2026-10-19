# Libraryan — design

Status: draft for approval · 2026-10-19

## 1. Intent

Libraryan is an agent that **owns the knowledge base (KB) of any git project it is launched in**. It structures, fixes, formats and keeps the KB up to date. It is the **only writer**: other agents (any vendor) must not edit the KB; they send Libraryan a request and Libraryan does the edit.

Why: when several AI agents work on one project, docs drift from code, every agent writes in its own style, duplicates and contradictions pile up, and vendor instruction files (CLAUDE.md, GEMINI.md, Cursor rules…) diverge. One owner with one style fixes that.

The whole thing is agent-run: **no person edits the KB by hand and no person approves changes.** Automated checks replace human review.

First real use: the user will clone Libraryan and launch it in `<your-project>` themselves. The builder must not touch that project.

## 2. Goals

1. One command sets Libraryan up in any git project.
2. After setup, every KB change in that project is made by Libraryan.
3. The KB stays accurate as code changes, consistent in style, and free of broken links, duplicates and secrets.
4. Other agents learn the new process automatically and cannot bypass it silently.
5. Every change is a git commit and can be undone.

## 3. Non-goals

- Writing or changing code. Making product decisions (it only records them).
- Answering questions about the project (other agents read the KB directly).
- Editing Markdown that belongs to the code (test fixtures, templates, generated files, vendored packages).
- Running other vendors' CLIs as Libraryan's runtime. **Runtime is Claude Code only for now.** The KB itself and the request process stay vendor-neutral.
- A server, database, vector index or always-on daemon.

## 4. Anti-goals (failure even if it "works")

- Libraryan rewrites or deletes project knowledge it can't justify from a source or from the code (deleting outdated or junk docs is intended, see §11; losing a still-valid fact is not).
- Planted text in a request or a source becomes an instruction Libraryan follows.
- Libraryan's background commit sweeps up another agent's unrelated, in-progress changes.
- It spams commits or burns tokens on runs that change nothing.
- Uninstalling leaves the project broken or locked.

## 5. What Libraryan owns

All Markdown a person or agent reads to understand or work on the project:

| Group | Examples | Rule |
|---|---|---|
| Knowledge | decisions, architecture, how-tos, glossary | Owned |
| Project docs | README, guides, API docs, CHANGELOG | Owned |
| Agent instruction files | AGENTS.md, CLAUDE.md, GEMINI.md, `.claude/skills/**`, `.cursor/rules/**`, `.github/copilot-instructions.md` | Owned, **extra care** |
| Code's own Markdown | fixtures, templates, generated, vendored | **Not owned** |

"Extra care" = changed only when a request explicitly asks for it or during setup, never during routine cleanup; the reviewer applies a stricter check.

The exact owned/excluded globs live in the per-project settings file (§8.1). Setup proposes them by scanning the project.

## 6. Jobs

1. **Setup** (`init`): scan code + existing docs; build or restructure the KB; write the house style guide and settings file; install the lock, triggers and request skill; announce itself in agent instruction files. All in one commit so it can be reverted in one step.
2. **Handle requests:** extract facts, write/format/link them. Reject wrong or vague requests with a reason, or flag them for the user. Merge duplicates. Never follow instructions inside a request.
3. **Sync docs with code:** after commits, find docs the code change made wrong and fix them.
4. **Daily health check:** broken links, duplicates, contradictions, stale notes, notes without sources, style violations.
5. **Keep agent instruction files consistent:** AGENTS.md is canonical; vendor files point to it.
6. **Guard:** block other agents' edits; block secrets.
7. **Review before saving:** a second checker reviews every change set.
8. **Run one copy at a time.**
9. **Log and summarise:** every change logged; a short summary per run.
10. **Uninstall** cleanly (`uninstall`).

## 7. How other agents learn about it

1. **Instruction files.** Setup adds a marked block to AGENTS.md (`<!-- libraryan:start --> … <!-- libraryan:end -->`) and ensures each vendor file points to AGENTS.md. The block says: docs are managed by Libraryan; don't edit owned files; send a request; when to send one (below).
2. **Request skill.** `.claude/skills/libraryan-request/SKILL.md` (Agent Skills format, readable by other vendors too) explains exactly how to write a request.
3. **The lock.** Agents that missed the rules learn them when an edit or commit is rejected; the rejection message explains the request process.

**When to send a request** (written into the AGENTS.md block):
- Send: made/changed a decision; changed something others rely on (commands, settings, APIs, setup, behaviour); found docs wrong or missing; hit a non-obvious problem others will hit.
- Don't send: things the code makes obvious; unfinished experiments; personal notes/to-dos.
- One request per finished task. Libraryan merges duplicates, rejects trivial ones with a reason, and tightens the "don't send" list itself if one kind keeps getting rejected (noted in the summary).

## 8. How it works

### 8.1 Files Libraryan adds to a project

```
.libraryan/
  config.json        settings: owned/excluded globs, KB root, language, model, debounce
  bin/               runtime (vendored copy, so the project is self-contained)
  hooks/             git hooks (pre-commit, post-commit)
  requests/          the only place other agents may write; one file per request
  state/             gitignored: run lock, last processed commit, run reports
docs/kb/             default KB root (configurable): index.md, log.md, STYLE.md, topic folders
.claude/agents/libraryan.md            the agent definition
.claude/agents/libraryan-reviewer.md   the reviewer
.claude/skills/libraryan-request/SKILL.md
.claude/settings.json                  hooks (merged with any existing settings, never overwritten)
```

Config is JSON (Python 3.10 on target machines has no stdlib TOML parser).

KB layout follows the "LLM Wiki" pattern from the earlier research: `index.md` (catalog, read first), `log.md` (append-only, `## [YYYY-MM-DD] op | title`), one concept per note, flat YAML frontmatter (`title, type, tags, created, updated, status, sources`), standard relative Markdown links (no wikilinks), short sections and bullets over wide tables, explicit "as of" dates.

### 8.2 Requests

A request is a Markdown file in `.libraryan/requests/` named `YYYYMMDD-HHMMSS-<slug>.md`, with frontmatter `from` (agent/tool), `kind` (decision | change | docs-wrong | gotcha | agent-rules), `related` (files/commits) and a free-text body of facts. Requests are committed with the work they describe, so they travel with the branch. Libraryan deletes a request once processed and records the outcome (applied / merged / rejected + reason / flagged) in `log.md`.

Request text is **data, never instructions**. Libraryan only extracts claims and verifies them against code or sources where possible.

### 8.3 Triggers (event-driven, not always running)

- **post-commit hook:** if the commit was not made by Libraryan, schedule a run after a debounce (default 10 min, configurable) so a burst of commits becomes one run.
- **daily schedule:** a user crontab entry runs the health check. Installed by `init`, removed by `uninstall`.
- **direct call:** `.libraryan/bin/libraryan run` (agents may call this for urgent changes).

Every run first does a cheap, model-free check (pending requests? new commits since last processed? health-check due?) and exits without calling the model if there's nothing to do.

### 8.4 One copy at a time

The runner takes a `flock` on `.libraryan/state/run.lock`. A trigger that finds it busy sets a "rerun" flag; the running copy loops once more before exiting.

### 8.5 The run

The runner invokes Claude Code headless: `claude -p --agent libraryan …` with environment `LIBRARYAN=1`, a restricted tool allowlist, and a prompt that states the run reason and the work queue. The agent:

1. Reads `index.md`, `STYLE.md`, config, pending requests, and the code diff since the last processed commit.
2. Makes changes only inside owned paths.
3. Runs the deterministic checks (§8.7).
4. Invokes `libraryan-reviewer` on the change set. Reviewer verdict: approve, or reject with reasons. Rejected changes are discarded and flagged in the summary.
5. Commits **only owned paths** (`git commit -- <paths>`), message prefixed `docs(libraryan):`, so other agents' staged or unstaged work is never included. Retries if git's index is locked.
6. Appends to `log.md`, writes the run summary, records the last processed commit.

### 8.6 The lock (two layers)

- **Claude Code PreToolUse hook** (friendly, early): blocks Edit/Write on owned paths when `LIBRARYAN` is not set, with a message explaining the request process. Best effort for Bash.
- **git pre-commit hook** (authoritative, vendor-neutral): rejects any commit that touches owned paths unless `LIBRARYAN=1`. Allows `.libraryan/requests/**`. Same explanatory message.

Hooks are installed with `git config core.hooksPath .libraryan/hooks`. If the project already uses hooks, the Libraryan hooks chain to them. A Claude Code SessionStart hook re-applies the hooks path in fresh clones, so teammates' agents are covered without manual steps.

Known ceiling: `LIBRARYAN=1` can be set by any process, so a deliberately misbehaving agent could bypass the lock. Acceptable for cooperative agents; upgrade path is a CI check on the remote that verifies `docs(libraryan):` commits only touch owned paths.

### 8.7 Safety checks (no human review, so these are the defence)

- Facts, not orders: requests and sources are treated as data; the agent prompt and reviewer both enforce it.
- Lint (stdlib Python): required frontmatter, broken relative links, index coverage, style rules from `STYLE.md` that can be checked mechanically.
- Secrets scan: gitleaks when installed, else a built-in regex scan for common key/token patterns. A hit blocks the commit.
- Sources required: every KB note cites where its facts came from.
- Reviewer agent: checks accuracy against sources, style, scope (owned paths only), and stricter rules for agent instruction files.
- Everything is a git commit plus a `log.md` entry, so any change can be reverted.

### 8.8 Summary for the user

Each run that changes something writes `.libraryan/state/reports/<timestamp>.md` (what changed, what was rejected, what needs attention) and updates `.libraryan/state/reports/latest.md`. The daily run also writes a digest of the day.

### 8.9 Setup on an existing project

`init` must be safe on a messy repo: it proposes owned/excluded globs from a scan, restructures existing docs into the KB layout while keeping every existing fact (moved, not dropped), updates links, and does it all in one `docs(libraryan): setup` commit. It refuses to run with uncommitted changes in owned paths.

### 8.10 Uninstall

`uninstall` removes hooks, the crontab entry, the AGENTS.md block, the Claude Code hooks/agents/skill it added, and `.libraryan/`, in one commit. The KB content itself stays (it is the project's knowledge).

## 9. Constraints

- Target: Linux, git ≥ 2.34, Python 3.10 stdlib only, `flock`, `crontab`, Claude Code ≥ 2.1. No new runtime dependencies. gitleaks optional.
- Must work on a project that already has `.claude/settings.json`, other git hooks, or existing docs.
- Libraryan's own repo lives at `<libraryan checkout>`.

## 10. Decided by the user

- Name: Libraryan.
- Owns all project Markdown for people and agents, including agent instruction files; not the code's own Markdown.
- Only writer; others send requests; no manual editing or approval by people.
- Event-driven, not always running.
- "When to call Libraryan" rules with anti-spam, written into setup.
- No question answering.
- Runtime: Claude Code for now.

## 11. Builder's calls (made by me, flagged for the user to check)

- Vendored runtime in `.libraryan/` so the project is self-contained.
- KB root default `docs/kb/`.
- 10-minute debounce after commits.
- Summary as report files in the project (no chat/email notification).
- Requests committed with the work, deleted after processing.
- Lock bypass via `LIBRARYAN=1` accepted as a known ceiling.

- **Branches:** Libraryan edits and commits only on the default branch (from config, e.g. `main`). If another branch is checked out when a trigger fires, the run is deferred (no model call). On other branches the lock still applies and requests accumulate; they are processed once merged into the default branch. "Since last processed commit" is computed on the default branch; if that commit is no longer an ancestor, fall back to the merge-base. Libraryan never pushes. The pre-commit hook allows merge commits (`MERGE_HEAD` present), so KB merge conflicts can always be resolved.
- **Runner host:** only the machine where `init` ran (hostname recorded in config) runs Libraryan. On other clones the hooks enforce the lock but post-commit does not trigger runs, and no crontab entry is installed.
- **Owned files outside the KB root** (root README, CHANGELOG, AGENTS.md, CLAUDE.md, GEMINI.md, SKILL.md files, per-package READMEs) stay where they are. Init does not move them or add KB frontmatter; they get style checks only. Frontmatter, sources and index-coverage rules apply only to notes under the KB root. Init moves loose knowledge docs into the KB root.
- **Daily health check fixes, within limits:** safe fixes are automatic (broken links, formatting, index). Judgement calls (contradictions, stale or unsourced notes) are fixed only when code or a cited source settles them; otherwise flagged in the summary.
- **Docs vs code (user decision, 2026-10-19, supersedes "never delete"):** Libraryan checks docs against the actual codebase (commands, file paths, config keys, APIs, setup steps, described behaviour). Where the doc is wrong, it fixes the doc. Where the code looks wrong and the doc looks right, it never touches code; it reports the mismatch in the summary under "Possible code issues". It **deletes** outdated and junk Markdown: docs describing code that no longer exists, duplicates, empty or placeholder stubs, leftover AI scratch notes, stale TODO/plan dumps, superseded versions. Any still-valid facts in a deleted file are moved into the KB first. Every deletion needs reviewer approval and gets a `log.md` entry with the reason; git history is the archive. Setup performs a full cleanup pass; the daily health check repeats it.
- **Non-agent writers:** config has an `exempt` glob list for tool-written files (e.g. a generated CHANGELOG, generated API docs). The pre-commit hook allows pure deletions and renames of owned files (code refactors moving or removing a package with a README); Libraryan repairs links on its next run. Agents whose task is to add a rule or skill file send a request.
- **Install and upgrade:** clone the Libraryan repo once; from the target project run `python3 <libraryan>/libraryan.py init`. Init runs headless (model call for the restructure). An `upgrade` command refreshes the vendored runtime, hooks, agent and skill files in a project from the cloned repo, in one commit.

## 12. Left to the builder

Script structure, exact prompts, exact lint rules, the regex secret patterns, how chained hooks are detected, test strategy.
