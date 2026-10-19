# Libraryan hardening (v0.2) — design update

Status: draft for approval · 2026-10-19 · extends `2026-10-19-libraryan-design.md`

Source: gap analysis against `docs/research/2026-10-19-kb-agent-harness-whitepaper.md` (cited as WP §) and `docs/research/kb-architecture/`. Five changes, chosen by the user from that analysis.

## 1. Intent

Libraryan already follows the research's core rules (single writer, lock outside the model, requests as data, owned-path-only commits, model-free precheck, backoff). The remaining risks are:

- the model alone decides that a deleted doc's facts were kept (WP F6);
- the reviewer is launched and briefed by the agent it reviews (WP §1.4.5, F14);
- the only budget is wall-clock time (WP §6.2, F12);
- nothing records what runs cost or how they ended (WP §5.1);
- drift is found only by the model searching the repo (WP §2.3, §5.5).

## 2. Goals

1. A deleted owned doc is committed only if the runner can mechanically see where its facts went.
2. Every commit is approved by a reviewer the runner starts itself, with a fresh context and no access to the author's transcript.
3. Every model call has a dollar cap, and the project has daily caps on runs, commits and consecutive failures.
4. Every run leaves one machine-readable trace line: outcome, cost, turns, duration.
5. A deterministic audit finds docs-vs-code drift without the model. Its findings become the model's work list, and a nightly run with no findings costs nothing.

## 3. Non-goals

- No change to the lock, the request format, the installer or the KB layout.
- No custom tool layer or MCP server (WP §3). The model keeps Claude Code's file tools; the runner keeps enforcing after the fact.
- No catalog, no authority tiers, no golden eval suite (later, after the pilot).
- No symbol-level code checks in the audit. Paths only.

## 4. Anti-goals

- A deletion blocked forever because the ledger format is too strict for a legitimate cleanup (an empty stub has no facts).
- A reviewer failure mode that approves by default. Missing, unparseable or timed-out review output means **reject**.
- Caps that silently stop Libraryan with nothing in the report.
- Audit noise: findings on paths inside code blocks, URLs, placeholders or globs.

## 5. Design

### 5.1 Deletion ledger (WP §2.1, F6)

The agent's final message gains ledger lines after the headings, before any `Discard:` lines:

```
Moved: <old path> => <new path>
Fact: <deleted path> => <destination path> | <quote from deleted file> | <quote from destination>
Fact: <deleted path> => none | <why it held no still-valid fact>
```

After the model call, the runner computes the **deleted docs**: owned `.md` paths in HEAD that this run removed. Request files are exempt. For each one:

- **Pure move.** Some new path has the identical blob. No ledger line needed.
- **Moved: line.** The new path exists, is owned, and `difflib` similarity with the HEAD content is at least 0.5.
- **Fact lines with a destination.** The destination exists after the run and is owned. Both quotes are at least 15 characters. The first quote, after whitespace normalisation, occurs in `git show HEAD:<deleted>`, and the second occurs in the destination file. At least one valid Fact line is required.
- **Fact … => none.** Accepted mechanically. The line is passed to the reviewer, who must agree.

Any deleted doc without a valid line produces the problem `deletion ledger: <path>: <reason>`. The run then fails like any other check failure: restore, report, backoff. The ledger is copied into the run report and the trace.

### 5.2 Independent reviewer (WP §1.4.5, §2.5, F14)

The agent keeps calling `libraryan-reviewer` as a subagent for self-checking. The runner adds the **final gate**:

1. **When it runs.** After the deterministic checks pass, the ledger is valid and `changed` is non-empty, the runner starts `claude -p --agent libraryan-reviewer` as a separate process.
   - It runs in the same working tree with `LIBRARYAN=1`.
   - It may use only `Read,Glob,Grep,Bash(git diff:*),Bash(git show:*),Bash(git log:*),Bash(git status:*)`.
   - Its model is `reviewer_model` when set, otherwise `model`.
2. **What the prompt contains** (built by the runner, never by the author):
   - the run reason and date;
   - the changed paths;
   - the baseline;
   - during setup, the installer files and the symlink flag;
   - the ledger lines.

   It does **not** contain the author's final message. Ledger lines are labelled as claims to verify.
3. **Verdict.** Approve only when the output, stripped, is exactly `APPROVE`. Any `REJECT:` line, any other text, a non-zero exit, a timeout or a cap hit counts as reject. Reject adds the problem `review: <first reject lines>` and the run fails (restore, report, backoff).
4. **Read-only check.** The runner snapshots owned paths before and after the review. If anything changed, it rejects (`review: reviewer modified files`).
5. **Config.** `independent_review` (default `true`), `reviewer_model` (default `null`), `review_timeout_minutes` (default 15).

The reviewer template changes its input section to "you receive" rather than "Libraryan gives you", so it works for both the subagent call and the runner call.

### 5.3 Cost caps (WP §6.2, F12)

- **Per call.** `--max-budget-usd` on every model call:
  - `max_usd_run` (default 5) for author runs;
  - `max_usd_setup` (default 25) for setup;
  - `max_usd_review` (default 2) for the reviewer.

  A call that hits its cap is a failed call. These defaults are placeholders, to be calibrated from the pilot's traces.
- **Daily caps.** Read from today's trace lines (§5.4) before any model call:
  - `max_runs_per_day` (default 24): runs that called the model;
  - `max_commits_per_day` (default 12);
  - `max_consecutive_failures` (default 3): trailing failed or aborted runs, not counting transient ones (another agent's concurrent edit);
  - `max_consecutive_transient_failures` (default 10): trailing failed or aborted runs, transient or not.
- **When a cap is hit**, any run other than a manual run or an explicit setup (`init`, `run --reason setup`) stops before the model is called. A setup that was promoted because index.md is missing counts as automatic, so it is capped. It writes a trace line with outcome `capped` and the cap's name, and appends to the report the line "Daily cap reached: …; run `python3 .libraryan/bin/libraryan run` to override".
- **Manual runs and explicit setup** ignore the daily caps but not the per-call caps.

### 5.4 Run trace (WP §5.1)

- **Model output format.** Every model call uses `--output-format json`. The runner parses the JSON. The model's text is the `result` field. `usage` collects `total_cost_usd`, `num_turns`, `duration_ms` and `is_error` where present. If stdout is not JSON, the raw stdout is the text and usage is empty, so a format change degrades and never crashes.
- **One trace line per `run()` loop iteration**, appended to `.libraryan/state/runs.jsonl`:

```json
{"ts": "2026-10-19T03:00:12Z", "reason": "daily", "head": "a1b2c3d", "outcome": "committed",
 "calls": [{"role": "author", "cost_usd": 0.84, "turns": 23, "duration_ms": 412000, "is_error": false},
           {"role": "reviewer", "cost_usd": 0.12, "turns": 6, "duration_ms": 61000, "is_error": false}],
 "changed": 4, "deleted": 1, "problems": 0, "commit": "d4e5f6a", "cap": null, "audit_findings": 3}
```

- **Outcomes:** `noop` (precheck found nothing), `deferred` (not on the default branch), `capped`, `audited` (health run whose audit found nothing, no model call), `nothing_changed`, `committed`, `failed`, `aborted`. `runs.jsonl` replaces `runs.log`.
- **Report.** The run report gains a `## Cost` line and the deletion ledger.
- **New command `libraryan stats [--days N]`** (default 7) prints, per day: runs, model calls, commits, failures and total cost.

### 5.5 Deterministic audit (WP §2.3, §5.5)

New command `libraryan audit` (also callable by the agent). It prints findings, one per line, as `<kind> <path>: <detail>`. It never calls the model and never edits anything.

| Kind | Rule |
|---|---|
| `broken-link` | Relative `.md` link in an owned doc that doesn't resolve (existing lint rule, over all owned docs) |
| `missing-path` | A backticked token in an owned doc, outside fenced code blocks, that looks like a repo path but doesn't exist in `git ls-files` or the working tree. It looks like a path if it contains `/` or ends in a known code/config extension, has no spaces, no `*`, `<`, `>`, `$` or `{`, is not a URL, and is not `~`-relative; an optional `#L12` or `:12` suffix is stripped. Absolute paths are skipped. |
| `missing-source` | A KB note's `sources` entry that looks like a repo path and doesn't exist |
| `stale` | A KB note whose repo-path `sources` have a commit date (`git log -1 --format=%cs`) later than the note's `updated` |
| `unsourced` | A KB note with no or empty `sources` |
| `not-indexed` | A KB note not linked from `index.md` (existing lint rule) |
| `duplicate-title` | Two KB notes with the same normalised `title` |

Frontmatter `sources` is read with a minimal stdlib parser: a flow list `[a, b]` or block `- a` lines. Entries such as `commit <sha>` or URLs are not paths.

How the runner uses it:

- **Health due.** The runner runs the audit first. With no findings, no requests and no new commits, it records the health run as done (`last_health`, `last_health_head`) and writes trace outcome `audited` with **no model call**.
- **Any model run.** The prompt gains an "Audit findings (verify each; fix the doc or flag it)" section, capped at 100 lines with a count of the rest.
- **Agent tools.** `Bash(python3 .libraryan/bin/libraryan audit:*)` is added to the agent's allowed tools, and its instructions say to re-run the audit before finishing.

## 6. Constraints

Unchanged from the base design: Python 3.10 stdlib only, Claude Code ≥ 2.1, Unix, never touch other projects, tests never call the real `claude`. Every new config key has a default, so existing installs keep working after `upgrade`.

## 7. Decided by the user

- Build items 1–5 of the research gap analysis.
- Keep deleting junk docs (no archive folder). The ledger is the safety net.
- No human checkpoint. The independent reviewer replaces it.

## 8. Builder's calls (flagged)

- Ledger as final-message lines, not a file, because the agent's guard blocks writes under `.libraryan/`.
- Quotes rather than a claim-by-claim inventory. This is mechanical evidence that the destination exists and the text was carried, and the reviewer judges completeness.
- A reviewer reject fails the whole run. There is no partial commit, because dropping single paths would break links and the index.
- The in-run self-review subagent stays: it lets the author fix problems before the final gate. This costs one extra review call per run.
- Default dollar caps are guesses until the pilot's traces exist.
- Audit is paths-only (no code symbols), to keep false positives low.
- Whether `--max-budget-usd` makes `claude` exit non-zero, or exit 0 with partial work, is unverified. Both paths are handled, because checks and the reviewer still gate a partial run.

## 9. Left to the builder

Exact prompt wording, the path-heuristic details beyond §5.5, the `stats` output layout, and module boundaries within the plan's files.
