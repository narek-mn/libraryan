# Libraryan Hardening (v0.2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a run trace, cost caps, a mechanical deletion ledger, a runner-launched independent reviewer and a deterministic docs-vs-code audit to Libraryan.

**Architecture:** Four new stdlib modules (`trace.py`, `ledger.py`, `review.py`, `audit.py`), each a pure-ish unit with its own tests, wired into `runner.run()` in a fixed order: precheck/caps → audit → author call → unstage/diff/Discard → checks → ledger → reviewer → commit → trace. Templates and README change to match.

**Tech Stack:** Python 3.10 stdlib, git, Claude Code CLI (`-p --agent --output-format json --max-budget-usd`), pytest (dev only).

**Spec:** `docs/superpowers/specs/2026-10-19-libraryan-hardening-design.md` (extends `docs/superpowers/specs/2026-10-19-libraryan-design.md`)

## Global Constraints

- Python 3.10 stdlib only in `libraryan/` and `runtime/`; tests use pytest.
- Tests never call the real `claude`, never touch the real crontab, never touch other projects; temp dirs only ones the test created.
- Every new config key has a default in `config.DEFAULTS`: `independent_review: true`, `reviewer_model: null`, `review_timeout_minutes: 15`, `max_usd_run: 5`, `max_usd_setup: 25`, `max_usd_review: 2`, `max_runs_per_day: 24`, `max_commits_per_day: 12`, `max_consecutive_failures: 3`.
- Reviewer verdict fails closed: only output that strips to exactly `APPROVE` approves.
- Trace file `.libraryan/state/runs.jsonl` replaces `.libraryan/state/runs.log`. Outcomes: `noop`, `deferred`, `capped`, `audited`, `nothing_changed`, `committed`, `failed`, `aborted`.
- Ledger line formats (exact): `Moved: <old> => <new>`, `Fact: <deleted> => <dest> | <quote from deleted> | <quote from dest>`, `Fact: <deleted> => none | <reason>`.
- Commit messages end with a blank line then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Ledger quotes copied from Markdown with different line wrapping or extra spaces must still match (whitespace-normalised). → Task 3 `test_fact_quote_whitespace_normalised`.
2. A deleted empty stub (no facts) with `Fact: <path> => none | empty stub` must pass the mechanical check. → Task 3 `test_fact_none_accepted`.
3. Reviewer output with leading/trailing blank lines or a code fence around `APPROVE` — only bare `APPROVE` approves; fenced output rejects (fail closed, documented). → Task 4 `test_verdict_parsing`.
4. Audit false positives: backticked URLs, globs, `<placeholders>`, `~/x`, `$VAR/x`, tokens in fenced code blocks must not produce `missing-path`. → Task 5 `test_missing_path_ignores_non_paths`.
5. A `capped` day must say so in `latest.md` so a user sees why nothing happened. → Task 2 `test_cap_writes_report_line`.

---

## File structure

```
libraryan/trace.py     parse claude JSON output; append/read runs.jsonl; daily counters; stats text
libraryan/ledger.py    parse ledger lines from model output; check deleted docs against them
libraryan/review.py    build reviewer prompt; run reviewer call; parse verdict; read-only check
libraryan/audit.py     deterministic findings over owned docs and KB notes
libraryan/runner.py    (modify) wiring, caps, outcomes, prompt sections, ALLOWED_TOOLS
libraryan/config.py    (modify) new DEFAULTS keys
libraryan/cli.py       (modify) `audit`, `stats` subcommands
templates/agents/libraryan.md            (modify) ledger lines, audit usage, final gate note
templates/agents/libraryan-reviewer.md   (modify) input section generic; ledger verification
tests/fake_claude.py   (modify) JSON output, reviewer mode
tests/test_trace.py, tests/test_ledger.py, tests/test_review.py, tests/test_audit.py (create)
README.md              (modify)
```

`fake_claude.py` changes (Task 1 and Task 4) are shared test infrastructure:
- If argv contains `--output-format json` and `FAKE_CLAUDE_MODE` lacks `nojson`, print one JSON object `{"type":"result","result":<text>,"total_cost_usd":0.01,"num_turns":3,"duration_ms":100,"is_error":false}` instead of plain text.
- If argv contains `--agent libraryan-reviewer`, do no author edits; print `FAKE_REVIEW` env (default `APPROVE`) as the result; mode `review_edits` appends a line to `docs/kb/index.md`; mode `review_fail` exits 1.
- Extra author output lines: env `FAKE_CLAUDE_EXTRA` (text appended to the printed summary, `\n`-separated).

---

### Task 1: Run trace and JSON output

**Files:**
- Create: `libraryan/trace.py`, `tests/test_trace.py`
- Modify: `libraryan/runner.py` (`_call_model`, `_defer`, `run`), `libraryan/cli.py` (add `stats`), `tests/fake_claude.py`, existing tests asserting `runs.log`

**Interfaces:**
- Produces:
  - `trace.parse_output(stdout: str) -> tuple[str, dict]` — `(text, usage)`; usage keys `cost_usd`, `turns`, `duration_ms`, `is_error` (only those present); non-JSON stdout → `(stdout, {})`.
  - `trace.append(st: Path, record: dict) -> None` — adds `ts` (UTC ISO `YYYY-MM-DDTHH:MM:SSZ`) if absent; one JSON line.
  - `trace.read(st: Path, since_ts: str | None = None) -> list[dict]` — skips unparseable lines.
  - `trace.today(st: Path) -> list[dict]` — records whose `ts` date equals today's UTC date.
  - `trace.stats(st: Path, days: int = 7) -> str` — one line per day: `YYYY-MM-DD runs=N calls=N commits=N failures=N cost=$X.XX`.
  - `runner._call_model(cmd, root, timeout) -> tuple[str, list[str], dict]` — now `(text, problems, usage)`; cmd always includes `--output-format json`.
  - Every exit path of one `run()` loop iteration appends exactly one record: keys `reason, head, outcome, calls (list of {role, **usage}), changed, deleted, problems, commit, cap, audit_findings` (missing values `0`/`null`/`[]`).
  - CLI: `libraryan stats [--days N]`.

- [ ] **Step 1: Failing tests** in `tests/test_trace.py`: `test_parse_output_json` (JSON with `result:"hi"`, `total_cost_usd:0.5`, `num_turns:4` → `("hi", {"cost_usd":0.5,"turns":4})` plus duration/is_error when given); `test_parse_output_plain` (`"hello"` → `("hello", {})`); `test_append_and_today` (two records today, one with ts yesterday → `today` returns two); `test_stats_line` (records with outcomes committed/failed and costs → line contains `commits=1 failures=1 cost=$0.60`). In `tests/test_runner.py`: `test_trace_written_for_noop`, `test_trace_written_for_committed_run` (outcome `committed`, `calls[0].role=="author"`, `cost_usd==0.01`, `commit` = HEAD sha), `test_trace_deferred` (replaces runs.log assertions), `test_nojson_output_still_works` (mode `nojson` → run commits, trace call has no cost).
- [ ] **Step 2:** `cd /home/baze/workspace/libraryan && python3 -m pytest tests/test_trace.py tests/test_runner.py -q` → FAIL.
- [ ] **Step 3:** Implement `trace.py`; update `fake_claude.py` (JSON mode); `_call_model` adds `--output-format json` and returns usage; `run()` builds and appends the record on every exit path (incl. the `BaseException` path with outcome `aborted`); remove `runs.log`; add `stats` to cli; report gains `- Cost: $X.XX (N turns)`.
- [ ] **Step 4:** full suite `python3 -m pytest tests -q` → PASS, pristine.
- [ ] **Step 5:** Commit `feat(runner): JSON model output and runs.jsonl trace`.

### Task 2: Cost caps

**Files:**
- Modify: `libraryan/config.py`, `libraryan/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `trace.today(st)`, trace record keys from Task 1.
- Produces:
  - `runner.cap_hit(st: Path, cfg: dict) -> str | None` — returns `"max_runs_per_day"`, `"max_commits_per_day"` or `"max_consecutive_failures"` (first that applies) else `None`. Runs = today's records with a non-empty `calls`; commits = today's `committed`; consecutive failures = trailing records (all days, ignoring `noop`/`deferred`/`capped`/`audited`) with outcome `failed`/`aborted`.
  - `--max-budget-usd` added to author calls: `max_usd_setup` when reason is `setup`, else `max_usd_run` (reviewer cap in Task 4).
  - When `cap_hit` returns a name and reason not in (`manual`, `setup`): no model call; trace outcome `capped` with `cap`; `latest.md` and a timestamped report contain `Daily cap reached: <name>; run \`libraryan run\` to override.`; return 0.

- [ ] **Step 1: Failing tests:** `test_budget_flag_passed` (add fake mode `argv` that writes `sys.argv` as JSON to `.libraryan/state/fake_claude_argv`; assert `--max-budget-usd` followed by `5` for a commit run and `25` for setup); `test_cap_runs_per_day` (pre-write 24 today records with calls → commit-reason run makes no model call, outcome `capped`, cap `max_runs_per_day`); `test_cap_consecutive_failures`; `test_cap_ignored_for_manual`; `test_cap_writes_report_line`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement (config DEFAULTS keys per Global Constraints; cap check right after `find_work` reports work, before snapshot).
- [ ] **Step 4:** full suite → PASS.
- [ ] **Step 5:** Commit `feat(runner): per-call dollar caps and daily run/commit/failure caps`.

### Task 3: Deletion ledger

**Files:**
- Create: `libraryan/ledger.py`, `tests/test_ledger.py`
- Modify: `libraryan/runner.py`, `templates/agents/libraryan.md`, `tests/fake_claude.py` (`FAKE_CLAUDE_EXTRA`, mode `delete_doc` = `git rm -q docs/old.md`)

**Interfaces:**
- Produces:
  - `ledger.parse(text: str) -> dict` — `{"moved": {old: new}, "facts": [{"deleted", "dest", "src_quote", "dest_quote"}], "none": {deleted: reason}, "lines": [raw ledger lines]}`; tolerates backticks around paths; ignores malformed lines (they simply don't count).
  - `ledger.check(root: Path, cfg: dict, deleted: list[str], snap: dict, after: dict, parsed: dict) -> list[str]` — problems `deletion ledger: <path>: <reason>`. Rules (spec §5.1): pure move if `snap[deleted]` blob equals any `after` blob of a path absent from `snap`; `Moved:` needs new path existing, protected, `difflib.SequenceMatcher(None, old, new).ratio() >= 0.5`; Fact needs dest existing + protected, both quotes ≥ 15 chars after whitespace normalisation (`" ".join(s.split())`), src quote in `git show HEAD:<deleted>` (normalised), dest quote in dest file (normalised); `none` accepted.
  - Runner: `deleted` = paths in `changed` that are in HEAD, `.md`, protected, not requests, and absent from the working tree; check runs after `checks.run_all`, problems append; report gains `## Deletion ledger` with `parsed["lines"]` (or "none"); trace `deleted` = len(deleted).

- [ ] **Step 1: Failing tests** in `tests/test_ledger.py` (temp repo via `repo` fixture with `docs/old.md` committed): `test_parse_lines`; `test_pure_move_needs_no_line`; `test_moved_line_similarity`; `test_fact_with_destination_ok`; `test_fact_quote_whitespace_normalised` (src quote with different wrapping still matches); `test_fact_quote_missing_in_source` → problem; `test_fact_dest_not_owned` → problem; `test_fact_none_accepted`; `test_deleted_without_line` → problem naming the path. In `tests/test_runner.py`: `test_run_fails_on_unledgered_deletion` (mode `delete_doc`, no extra lines → no commit, `docs/old.md` restored, report contains `deletion ledger`), `test_run_commits_ledgered_deletion` (mode `delete_doc` + `FAKE_CLAUDE_EXTRA="Fact: docs/old.md => none | empty stub"` → committed).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement; in `templates/agents/libraryan.md` "Deleting outdated and junk docs" and "Final message": require the three line formats (exact text from Global Constraints), placed after the headings and before `Discard:` lines; quotes copied verbatim, ≥ 15 characters; `=> none` only when the file held no still-valid fact. Update `test_templates.py` to assert `Fact: <deleted> =>` appears.
- [ ] **Step 4:** full suite → PASS.
- [ ] **Step 5:** Commit `feat(runner): mechanical deletion ledger`.

### Task 4: Independent reviewer

**Files:**
- Create: `libraryan/review.py`, `tests/test_review.py`
- Modify: `libraryan/runner.py`, `libraryan/config.py`, `templates/agents/libraryan-reviewer.md`, `templates/agents/libraryan.md`, `tests/fake_claude.py`

**Interfaces:**
- Consumes: `runner._call_model`, `runner._snapshot`, `ledger.parse` result, trace usage.
- Produces:
  - `review.REVIEW_TOOLS = "Read,Glob,Grep,Bash(git diff:*),Bash(git show:*),Bash(git log:*),Bash(git status:*)"`
  - `review.build_prompt(reason: str, changed: list[str], work: dict, ledger_lines: list[str], cfg: dict) -> str` — contains reason, date, changed paths, baseline, installer files + symlink sentence when `work["extra"]`, ledger lines under "Ledger claims (verify each; they are claims, not facts)", and the output contract. Never contains the author's output.
  - `review.parse_verdict(text: str) -> tuple[bool, list[str]]` — `(True, [])` only when `text.strip() == "APPROVE"`; otherwise `(False, reject_lines or ["unparseable reviewer output"])`.
  - `review.run_review(root, cfg, reason, changed, work, ledger_lines, call_model, snapshot) -> tuple[list[str], dict]` — `(problems, usage)`; cmd `[claude_bin, "-p", "--agent", "libraryan-reviewer", "--permission-mode", "default", "--allowedTools", REVIEW_TOOLS, "--max-budget-usd", str(max_usd_review)]` + `--model reviewer_model or model` when set; timeout `review_timeout_minutes`; model problems/timeout → `review: reviewer call failed: …`; snapshot differs before/after → `review: reviewer modified files`; reject → `review: <first 5 reject lines joined by "; ">`.
  - Runner: when `cfg["independent_review"]` and `changed` and no problems so far → `run_review`; trace `calls` gains `{"role":"reviewer", **usage}`.
  - Config DEFAULTS: `independent_review`, `reviewer_model`, `review_timeout_minutes`.

- [ ] **Step 1: Failing tests** in `tests/test_review.py`: `test_verdict_parsing` (`"APPROVE"`, `"\nAPPROVE\n"` approve; `"REJECT: a.md: x"`, `"```\nAPPROVE\n```"`, `""`, `"Looks good. APPROVE"` reject); `test_prompt_excludes_author_output`; `test_prompt_lists_ledger_and_baseline`. In `tests/test_runner.py`: `test_reviewer_reject_fails_run` (`FAKE_REVIEW="REJECT: docs/kb/index.md: wrong"` → no commit, index restored, report has `review:`); `test_reviewer_edit_rejected` (mode `review_edits`); `test_reviewer_failure_rejects` (mode `review_fail`); `test_review_disabled` (`independent_review: false` → commits without reviewer call); `test_reviewer_args` (reviewer argv contains `--agent libraryan-reviewer`, `--max-budget-usd 2`, and the REVIEW_TOOLS string).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement. Reviewer template: input section begins "You receive the run reason…" (works for both callers), adds a "Ledger claims" check: each `Fact` quote pair states the same fact and no valid fact of a deleted file is missing; each `=> none` is true. Agent template "Before you finish": note that after it finishes, the runner runs the same reviewer independently and any reject discards the whole run, so self-review must be thorough.
- [ ] **Step 4:** full suite → PASS.
- [ ] **Step 5:** Commit `feat(runner): independent reviewer as the final gate`.

### Task 5: Deterministic audit

**Files:**
- Create: `libraryan/audit.py`, `tests/test_audit.py`
- Modify: `libraryan/runner.py` (`find_work` health path, `build_prompt`, `ALLOWED_TOOLS`), `libraryan/cli.py` (add `audit`), `templates/agents/libraryan.md`

**Interfaces:**
- Consumes: `checks._links`, `checks.lint` rules, `paths.is_protected`, `runner._ls_files`.
- Produces:
  - `audit.Finding = tuple[str, str, str]` — `(kind, path, detail)`; kinds exactly `broken-link`, `missing-path`, `missing-source`, `stale`, `unsourced`, `not-indexed`, `duplicate-title`.
  - `audit.frontmatter(text: str) -> dict[str, str | list[str]]` — flat keys; `sources`/`tags` as lists from `[a, b]` or `- a` lines.
  - `audit.looks_like_path(token: str) -> bool` — spec §5.5 heuristic; strips `#L12`/`:12` suffix before deciding; extensions set: `.py .js .ts .tsx .jsx .go .rs .java .kt .c .h .cpp .hpp .cs .rb .php .sh .md .json .yaml .yml .toml .ini .cfg .env .sql .proto .txt`.
  - `audit.run(root: Path, cfg: dict) -> list[Finding]` — sorted, deterministic.
  - `audit.format(findings, cap: int = 100) -> str` — `"<kind> <path>: <detail>"` lines, then `"… and N more"` when capped; `"- (none)"` when empty.
  - CLI: `libraryan audit` prints `format(run(...), cap=10**6)`; exit 0 always.
  - Runner: `ALLOWED_TOOLS` gains `Bash(python3 .libraryan/bin/libraryan audit:*)`; when `work["health"]` and no requests and no commits and reason not in (`manual`,`setup`): run audit; empty → write `last_health`/`last_health_head`, trace outcome `audited` (`audit_findings: 0`), return without model; otherwise prompt gains "Audit findings (verify each; fix the doc or flag it):" + `format(findings)` and trace `audit_findings`. Audit also runs (and is listed) for every model run.

- [ ] **Step 1: Failing tests** in `tests/test_audit.py` (repo fixture with `src/app.py`, `docs/kb/index.md`, notes): `test_frontmatter_lists` (flow and block forms); `test_missing_path_found` (`` `src/gone.py` `` → finding); `test_missing_path_ignores_non_paths` (`` `https://x.io/a.py` ``, `` `src/*.py` ``, `` `<file>.py` ``, `` `~/x/y.py` ``, `` `$HOME/a.py` ``, `` `/etc/hosts` ``, and a path inside a fenced block → none); `test_path_with_line_suffix` (`` `src/app.py#L3` `` and `` `src/app.py:3` `` → no finding); `test_stale_source` (note `updated: 2020-01-01`, source `src/app.py` committed later → `stale`); `test_unsourced_and_missing_source`; `test_duplicate_title`; `test_not_indexed_and_broken_link`. In `tests/test_runner.py`: `test_clean_health_run_skips_model` (daily, clean KB → fake not run, outcome `audited`, `last_health_head` written); `test_health_with_findings_calls_model_with_list` (prompt contains `missing-path`); `test_audit_tool_allowed` (`ALLOWED_TOOLS` contains the audit entry).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement; agent template: in Health check and Before you finish, run `python3 .libraryan/bin/libraryan audit`, treat each finding as a lead to verify (fix doc / flag), re-run before finishing.
- [ ] **Step 4:** full suite → PASS.
- [ ] **Step 5:** Commit `feat: deterministic docs-vs-code audit`.

### Task 6: README and base spec

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-10-19-libraryan-design.md` (one line under §8.8 pointing to the hardening design)

- [ ] **Step 1:** README: new config keys table rows (Global Constraints values); commands `audit`, `stats`; reports now include cost and deletion ledger; trace file `runs.jsonl`; caps behaviour and override; independent reviewer (and that it adds one model call per committing run); the deletion-ledger rule in "How it works".
- [ ] **Step 2:** `python3 -m pytest tests -q` → all pass.
- [ ] **Step 3:** Commit `docs: README for v0.2 hardening`.
