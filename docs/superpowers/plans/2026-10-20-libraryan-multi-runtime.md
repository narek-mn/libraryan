# Libraryan multi-runtime (v0.3.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Libraryan's writer and reviewer run on any supported agent CLI. Every model session runs in an isolated git worktree, and an early edit guard is installed for every supported tool.

**Architecture:**
- Part A (Task 1) moves every model session into a detached worktree under `.libraryan/state/wt`. Only owned-path changes are copied back to the real checkout and committed. Part A ships on its own.
- Part B (Tasks 2–10):
  - extracts a small adapter module per tool under `libraryan/runtimes/`;
  - makes the agent instructions tool-neutral;
  - adds the adapters, per-tool guard files, detection and `libraryan runtime`, then docs and the release.

**Tech Stack:** Python 3.10+ stdlib only, git worktrees, pytest with fake binaries (no real model calls).

**Spec:** `docs/superpowers/specs/2026-10-20-libraryan-multi-runtime-design.md`. Research: `docs/research/runtimes/<tool>.md`. Each adapter's exact flags and output shapes come from its research file.

## Global Constraints

- Python 3.10+ stdlib only; Unix only; no new dependencies.
- No test calls a real model; tests never touch the real crontab or any home config.
- The runner is the only committer; never push; commit only owned paths (`docs(libraryan):` prefix).
- Every runtime goes through snapshot → checks → ledger → reviewer → owned-paths-only commit; a runtime counts as successful only when a final result is present **and** no error signal exists (fail closed).
- Cost: `cost_usd` only when the tool reports it, else `null` shown as "unknown"; no price table.
- Libraryan never writes to a user's home config (`~/.codex`, `~/.gemini`, …) and puts no runtime caps in project `.gemini/` or `.qwen/` settings.
- Existing 0.2.x installs keep running on Claude Code after `upgrade`, with the same behaviour; `claude_bin` stays an alias of `runtime_bin`.
- Defaults: `max_turns_run` 60, `max_turns_setup` 200, `max_turns_review` 30; turn caps apply only to runtimes with no USD cap.
- Auto-detect order: claude, codex, gemini, qwen, copilot, opencode, cursor.
- Runtimes other than Claude Code are labelled "experimental" until smoke-tested on a real account.
- Commits: author `narek-mn`, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Before any push: run the maintainer's privacy check.
- Match the codebase style: dense, few comments that explain *why*, `ponytail:` marks known ceilings.

## Review Focus

1. **Gemini-style silent failure.** Exit 1, empty stdout, error on stderr. The run must fail, and the report must quote the stderr line. Test in Task 6.
2. **Cursor-style output that isn't JSON** (or `is_error` that is always false). `parse` must return `ok=False`, never "no error seen = success". Test in Task 7.
3. **Runtime binary gone at run time** (uninstalled after init). The run fails with "could not start", backs off like any failure, and nothing is committed. Test in Task 2.
4. **Stale worktree** left at `.libraryan/state/wt` by a killed run. The next run removes and prunes it, then proceeds. Test in Task 1.
5. **Turn cap hit** (Qwen `--max-session-turns` shape). The run fails, nothing is committed, and the problem names the cap. Test in Task 6.

---

## Part A: isolation

### Task 1: Every model session runs in a temporary worktree

**Files:**
- Modify: `libraryan/runner.py` (`run()` body from the cap check onward; delete `_unstage_new`, the `foreign_now` lambda and `staged_before`/`dirty_before` if unused)
- Modify: `libraryan/review.py` (`MODIFIED` stops being transient; see the ruling below)
- Modify: `tests/fake_claude.py`, `tests/test_runner.py`, `tests/test_review.py`

**Interfaces:**
- Produces:
  - `runner.WORKTREE = ".libraryan/state/wt"`.
  - `runner._worktree(root: Path, head: str) -> Path`: removes any leftover first (`git worktree remove --force`, then `shutil.rmtree(ignore_errors=True)`, then `git worktree prune`), then runs `git worktree add --detach <path> <head>`.
  - `runner._drop_worktree(root: Path, wt: Path) -> None`: the same removal; never raises.
  - `runner._content_hash(root: Path, path: str) -> str | None`: `git hash-object` of the real file (no `-w`), `None` when absent.
- `run()` keeps its signature and return codes.

**Behaviour (the new run body, after the cap check):**
1. `real = _snapshot(root, cfg)`. Then `wt = _worktree(root, work["head"])`. For each `work["requests"]` path, write the real checkout's file bytes into `wt` at that path. This copies staged-but-uncommitted requests, which a HEAD checkout lacks.
2. `base = _snapshot(wt, cfg)`. The author runs with `cwd=wt` (`_call_model(cmd, wt, timeout)` for now; Task 2 changes the signature).
3. Run `git -C wt reset -q` so the author's `git rm`/`git mv` staging becomes plain working-tree changes. Then `after = _snapshot(wt, cfg)`, `diff = _libraryan_changes(base, after)`, and apply `Discard:` in `wt` as today.
   - `changed` = `diff` minus `work["baseline"]` paths (the baseline is computed on the **real** checkout, as today).
4. Stray edits: `strays` = paths dirty in `wt` that are not in `diff`, not requests and not under `STATE`. They are **not** a failure. They go into the report under `## Ignored (outside owned paths, discarded)`.
5. `checks.run_all(wt, …)` and `ledger.check(wt, cfg, deleted, base, after, parsed)`. `deleted`/`in_head` are computed in `wt`; the worktree shares the object store, so blobs resolve.
6. Reviewer: `review.run_review(wt, …, _call_model, _snapshot)`. It snapshots `wt`, so any reviewer edit is caught there.
7. If `not _on_default(root, cfg)` → `deferred`. Nothing in the real checkout was touched, so there is no restore.
8. Copy-back, only when `changed and not problems`:
   - `conflicts = [p for p in changed if _content_hash(root, p) != base.get(p)]`. A non-empty list means problem `f"{FOREIGN}: …"`, which is transient.
   - Otherwise, for each path: write `after[p]` (via `git cat-file blob`) or unlink it in the real checkout. Track `applied`.
   - Then `_commit(root, changed, reason, output)`. On error: `git reset -q -- changed`, then `_restore(root, base, applied)`.
9. On failure: report and trace as today. No restore of the real checkout is needed unless `applied` is non-empty.
   - On `BaseException`: `_restore(root, base, applied)`, then report and trace `aborted` as today, then raise.
   - `_drop_worktree` runs in a `finally` for every outcome.

**Rulings (record in the ledger):**
- A stray code edit by the author is discarded and reported, not failed. Spec §5.0 says "discarded". The old `test_stray_code_edits_fail_run_and_nothing_left_staged` is rewritten.
- A teammate's code edit in the real checkout during a run no longer fails the run. The old `test_foreign_edit_*` tests become owned-doc conflict tests.
- `review.MODIFIED` is no longer transient. In the worktree only the reviewer can edit, so it backs off like any failure.

**Fake changes (`tests/fake_claude.py`):**
- Add `REAL = Path(subprocess.check_output(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], text=True).strip()).parent`.
- State markers (`fake_claude_ran`, `_prompt`, `_argv`, `_env`, `_child`, `fake_review_*`) go under `REAL/.libraryan/state/`.
- Modes that simulate **another agent** act in `REAL`: `commit`, `checkout`, `stage_request`, the new-request half of `race_request`, `review_newdoc`, `review_request` and `review_baseline`.
- Author modes act in cwd (the worktree).
- Add mode `real_doc_edit`: append a line to `REAL/docs/kb/index.md` during the run.

- [ ] **Step 1: Write the new failing tests in `tests/test_runner.py`**

```python
def test_author_runs_in_worktree(repo, monkeypatch):
    cfg = make_kb(repo); add_request(repo); git(repo, "add", "-A")
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "argv,env")
    assert runner.run(repo, cfg, "manual") == 0
    assert "updated by fake claude" in (repo / "docs/kb/index.md").read_text()
    assert not (repo / runner.WORKTREE).exists()
    assert "wt" not in git(repo, "worktree", "list")

def test_stray_code_edit_discarded_and_reported(repo, monkeypatch):
    # app.py/util.py committed by the test first, as the old test did
    ...
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "codeedit")
    assert runner.run(repo, cfg, "manual") == 0
    assert (repo / "app.py").read_text() == "x = 1\n" and (repo / "util.py").exists()
    assert "app.py" in (state(repo) / "reports/latest.md").read_text()
    assert libraryan_commits(repo)

def test_staged_request_seen_and_removed(repo, monkeypatch):
    cfg = make_kb(repo); add_request(repo)
    git(repo, "add", ".libraryan/requests")          # staged, never committed
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "gitrm")
    assert runner.run(repo, cfg, "manual") == 0
    assert not (repo / ".libraryan/requests/20261019-120000-x.md").exists()
    assert ".libraryan/requests/20261019-120000-x.md" not in git(repo, "ls-files")

def test_owned_doc_edited_in_real_checkout_during_run_is_transient(repo, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "real_doc_edit")
    assert runner.run(repo, cfg, "manual") == 1
    t = last_trace(repo); assert t["outcome"] == "failed" and t["transient"]
    assert (repo / "docs/kb/index.md").read_text().endswith("by another agent\n")  # kept, never restored

def test_code_edit_in_real_checkout_during_run_does_not_fail(repo, monkeypatch):
    # FAKE_CLAUDE_MODE="commit": another agent commits src.py during the run
    assert runner.run(repo, cfg, "manual") == 0 and libraryan_commits(repo)

def test_stale_worktree_removed_at_start(repo):
    cfg = make_kb(repo); add_request(repo); git(repo, "add", "-A")
    git(repo, "worktree", "add", "--detach", runner.WORKTREE, "HEAD")
    (repo / runner.WORKTREE / "junk.md").write_text("x\n")
    assert runner.run(repo, cfg, "manual") == 0
    assert not (repo / runner.WORKTREE).exists()

def test_worktree_removed_after_failure_and_interrupt(repo, monkeypatch):
    # FAKE_CLAUDE_MODE="exit1", then a KeyboardInterrupt from a patched _call_model:
    # both leave no WORKTREE dir and no registered worktree
    ...

def test_baseline_doc_never_copied_back(repo, monkeypatch):
    # docs/wip.md dirty in the real checkout before the run; the fake also edits it in the worktree
    # → the real docs/wip.md keeps the user's text, the commit does not contain it
    ...
```

- [ ] **Step 2: Run the tests and confirm they fail.** `python -m pytest tests/test_runner.py -q -k "worktree or stray or staged_request_seen or real_checkout or baseline_doc_never"` → FAIL.
- [ ] **Step 3: Update `fake_claude.py` as described above.** Then rewrite the old tests whose assertions encode real-checkout semantics, following the rulings: `test_stray_code_edits_fail_run_and_nothing_left_staged`, `test_foreign_edit_only_failure_does_not_back_off`, `test_foreign_edit_plus_lint_failure_still_backs_off`, `test_foreign_edit_skips_review`, `test_reviewer_edit_rejected` (no longer transient), `test_new_doc_during_review_is_reported_not_removed`, `test_baseline_doc_edited_during_review_kept`, and any test reading marker files from `repo/.libraryan/state`.
- [ ] **Step 4: Implement the run body above in `runner.py`.**
- [ ] **Step 5: Run the full suite.** `python -m pytest tests -q` → all pass.
- [ ] **Step 6: Commit.** `git commit -m "feat(runner): run every model session in a temporary worktree; copy back owned paths only"`

---

## Part B: runtimes

### Task 2: Adapter interface and Claude adapter (pure refactor)

**Files:**
- Create: `libraryan/runtimes/__init__.py`, `libraryan/runtimes/claude.py`, `tests/test_runtimes.py`
- Modify: `libraryan/runner.py` (`_call_model`, `ALLOWED_TOOLS` moves to `runtimes/claude.py`, `_report` cost line), `libraryan/review.py` (`REVIEW_TOOLS` moves, `run_review` uses the new `_call_model`), `libraryan/config.py`, `libraryan/trace.py` (`parse_output` moves into `claude.parse`; `stats` adds unknown cost), `libraryan/install.py` (writes `runtime_bin` instead of `claude_bin`), `tests/test_runner.py`, `tests/test_review.py`, `tests/test_trace.py`

**Interfaces (Produces, used by Tasks 3–9):**
- An adapter module exposes:
  - `BIN: str`: the default binary name.
  - `INSTALL: str`: a one-line install hint.
  - `AUTH: str`: a one-line hint for unattended auth.
  - `command(role: str, prompt: str, cfg: dict, limits: dict, instructions: Path) -> tuple[list[str], dict]`: argv plus extra env. `role` is `"author"` or `"reviewer"`. `limits = {"usd": float, "turns": int}`; use the USD cap if the tool has a USD flag, else the turn cap if it has a turn flag, else neither. `instructions` is the neutral instructions file (`.libraryan/agents/libraryan.md` or `libraryan-reviewer.md` under the cwd). The bin is `cfg["_bin"]`, resolved by the runner.
  - `parse(out: str, err: str, code: int) -> tuple[str, dict, bool]`: text, usage and ok. Usage keys: `cost_usd` (float|None), `tokens` (int|None), `turns` (int|None), `is_error` (bool).
- `runtimes/__init__.py`:
  - `NAMES = ("claude", "codex", "gemini", "qwen", "copilot", "opencode", "cursor", "command")`;
  - `ORDER = NAMES[:7]`;
  - `get(name: str) -> ModuleType` (importlib; `ValueError` for an unknown name);
  - `detect(name: str, bin: str | None = None) -> str | None` (`<bin> --version`, timeout 10 s, first line, `None` on any failure);
  - `with_instructions(prompt: str, instructions: Path) -> str` (file text, a blank line, `---`, a blank line, the prompt; prompt alone if the file is missing).
- `runner._call_model(role: str, prompt: str, cwd: Path, cfg: dict, reason: str) -> tuple[str, list[str], dict]`:
  - The runtime is `cfg["reviewer_runtime"] or cfg["runtime"]` for the reviewer and `cfg["runtime"]` for the author.
  - The bin: for the reviewer, `cfg["reviewer_runtime_bin"]` when `reviewer_runtime` is set and differs, else `cfg["runtime_bin"]`; then `adapter.BIN` as fallback.
  - The timeout keys are today's; the limits come from `max_usd_*` and `max_turns_*` by role and reason.
  - The env is `_child_env()` merged with the adapter env.
  - Problems:
    - `could not start <bin>: …` when the process can't start;
    - `<runtime> timed out after N min`;
    - when `ok` is false, `<runtime> failed (exit N): <last non-empty stderr line, ≤300 chars>`.
  - Usage gains `runtime` and `duration_ms`.
- `review.run_review(root, cfg, reason, changed, work, ledger_lines, call_model, snapshot)` keeps its signature and calls `call_model("reviewer", prompt, root, cfg, reason)`.
- Config DEFAULTS:
  - add `"runtime": "claude"`, `"runtime_bin": None`, `"reviewer_runtime": None`, `"reviewer_runtime_bin": None`, `"runtime_command": None`, `"max_turns_run": 60`, `"max_turns_setup": 200`, `"max_turns_review": 30`;
  - remove `claude_bin` from DEFAULTS;
  - `load()` maps a stored `claude_bin` to `runtime_bin` when `runtime_bin` is unset, and drops `claude_bin`.
- Claude adapter:
  - argv is exactly today's (`-p --agent libraryan|libraryan-reviewer`, permission mode, allowed tools, `--model`/reviewer model, `--max-budget-usd`), plus `--output-format json` before the prompt; `instructions` is ignored.
  - env `{"CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1"}` moves here from `_child_env`.
  - `parse`: JSON object with a string `result` and `is_error` false and exit 0 → ok. Non-JSON output → ok False (ruling: replaces `test_nojson_output_still_works`, per the spec's fail-closed rule).

- [ ] **Step 1: Write failing tests** in `tests/test_runtimes.py`:
  - `test_claude_author_argv` (contains `--agent libraryan`, the allowed-tools string, `--max-budget-usd 5`, `--output-format json`, prompt last);
  - `test_claude_parse_ok`, `test_claude_parse_is_error` (ok False, `is_error` True), `test_claude_parse_not_json` (ok False);
  - `test_detect_missing_binary_is_none`;
  - `test_get_unknown_raises`.

  In `tests/test_runner.py`:
  - `test_missing_runtime_binary_fails_and_backs_off`: `runtime_bin` set to a nonexistent path → `run()==1`, the report contains "could not start", `last_failed` written, no commit.
  - `test_unknown_cost_reported`: a patched `_call_model` returning `cost_usd: None` → the report shows "cost unknown", and `trace.stats` prints `unknown=1`.

  In `tests/test_config.py`: `test_claude_bin_alias`, a stored `claude_bin: "/x/claude"` loads as `runtime_bin == "/x/claude"`.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
  - Point the test helper `make_kb` at `cfg["runtime_bin"] = str(FAKE)`.
  - Update existing tests that patch `_call_model`, or that call `trace.parse_output`, to the new signatures.
- [ ] **Step 4: `python -m pytest tests -q`.** All pass.
- [ ] **Step 5: Commit.** `feat(runtimes): pluggable runtime adapters; Claude Code adapter; unknown cost`

### Task 3: Tool-neutral instructions

**Files:**
- Modify: `libraryan/_templates/agents/libraryan.md`, `libraryan/_templates/agents/libraryan-reviewer.md`, `libraryan/install.py` (`_copy`), `libraryan/runtimes/claude.py` (allowed tools), `libraryan/runner.py` (`build_prompt` line "Before finishing, run the libraryan-reviewer subagent…"), `tests/test_templates.py`, `tests/test_install.py`

**Interfaces:**
- Produces: `_copy` also writes `.libraryan/agents/libraryan.md` and `.libraryan/agents/libraryan-reviewer.md`, which are the template bodies with the YAML frontmatter stripped. `.claude/agents/*.md` keep the frontmatter; one source.
- Consumes: Task 2's `instructions` path (`<cwd>/.libraryan/agents/<agent>.md`).

**Content rules for the bodies:**
- No tool names: Read, Edit, Write, Glob, Grep, Agent, Task, `git rm`, `git mv`. Use "read the file", "search the repo", "delete the file", "move the file".
- Allowed shell commands are read-only git (`log`, `diff`, `show`, `status`), `python3 .libraryan/bin/libraryan check|audit`, and plain `rm`, `mv`, `mkdir -p`.
- Self-review: "If your tool can start a subagent, ask it to review your changes with the reviewer instructions in `.libraryan/agents/libraryan-reviewer.md`; otherwise check your own work against that checklist." Change the `build_prompt` line to match.
- The Claude allowed tools gain `Bash(rm:*)`, `Bash(mv:*)` and `Bash(mkdir:*)` and keep the rest.

- [ ] **Step 1: Failing tests.**
  - `test_neutral_bodies_name_no_tools`: for both installed `.libraryan/agents/*.md` files, none of `Glob`, `Grep`, `git rm`, `git mv`, `subagent_type` appears, and the file does not start with `---`.
  - `test_claude_agents_keep_frontmatter`.
  - `test_claude_allows_plain_rm_mv`.
- [ ] **Step 2: Run; fail.**
- [ ] **Step 3: Rewrite the two template bodies and implement the `_copy` change.** Keep every rule and checklist item; change only the tool wording. The ledger format (`Moved:`, `Fact` lines, `Discard:`) is unchanged.
- [ ] **Step 4: Full suite passes.**
- [ ] **Step 5: Commit.** `feat: tool-neutral agent instructions in .libraryan/agents/`

### Task 4: Codex adapter and a shared fake runtime

**Files:**
- Create: `libraryan/runtimes/codex.py`, `tests/fake_runtime.py`
- Modify: `tests/test_runtimes.py`, `tests/test_runner.py`

**Interfaces:**
- Consumes: the Task 2 adapter interface.
- Produces:
  - `tests/fake_runtime.py`: one fake for every non-Claude runtime.
    - It reads `FAKE_FORMAT` (`codex|gemini|qwen|copilot|opencode|cursor|text`) and `FAKE_RUNTIME_MODE` (`ok|error|reject`).
    - The prompt is the last argv element, or after `-p`/`--prompt` per format.
    - Role: reviewer if `"Libraryan independent review"` is in the prompt.
    - The author appends `- updated by fake runtime\n` to `docs/kb/index.md` in cwd. The reviewer answers `APPROVE`, or `REJECT: docs/kb/index.md: no` with mode `reject`.
    - It prints that format's success or error output, copied from the research file's recorded shapes.
  - `make_kb(repo, runtime="claude")` sets `cfg["runtime"]`, and for non-Claude `runtime_bin` = the fake, plus `FAKE_FORMAT` via `monkeypatch`, or for `text` `runtime_command = [sys.executable, fake, "{prompt}"]` (Task 5).

**Codex specifics:** `docs/research/runtimes/codex-cli.md` §1, 2, 4, 5, 9, 11.
- `exec --json`, plus `--skip-git-repo-check` only if the research says a worktree needs it.
- Author sandbox `workspace-write`, reviewer `read-only`; model from `-m`.
- No USD or turn flag (§5), so limits are unused.
- `parse`:
  - JSONL; text is the last `agent_message` item;
  - tokens are the sum of `turn.completed.usage` input and output;
  - turns are the count of `turn.started`;
  - `cost_usd` None;
  - ok = exit 0, a final message present and no `turn.failed`;
  - `item.type:"error"` items are warnings, not failures (§11).

- [ ] **Step 1: Failing tests.**
  - `test_codex_argv_roles` (author `workspace-write`, reviewer `read-only`, prompt contains the neutral instructions text);
  - `test_codex_parse_ok_counts_tokens`;
  - `test_codex_parse_turn_failed` (ok False);
  - `test_codex_warning_item_is_not_failure`.
  - Parametrize over `["claude", "codex"]`: `test_run_commits_changes`, `test_reviewer_reject_fails_run` and `test_is_error_fails_run` (for codex, "error" mode = the `turn.failed` shape with exit 1).
- [ ] **Step 2: Run; fail.**
- [ ] **Step 3: Implement `codex.py` and `fake_runtime.py`.**
- [ ] **Step 4: Full suite passes.**
- [ ] **Step 5: Commit.** `feat(runtimes): Codex CLI adapter`

### Task 5: Generic `command` runtime

**Files:** Create `libraryan/runtimes/command.py`. Modify `tests/test_runtimes.py` and `tests/test_runner.py` (add `"command"` to the Task 4 parametrization with `FAKE_FORMAT=text`).

**Behaviour:**
- `cfg["runtime_command"]` is a list of strings. In each element, `{prompt}` is replaced by the prompt and `{instructions_file}` by `str(instructions)`.
- The instructions are prepended to the prompt (`with_instructions`) **unless** some element contains `{instructions_file}`.
- A missing or empty `runtime_command` raises `ValueError("runtime_command is not set in .libraryan/config.json")`. `_call_model` turns that into a problem, not a crash.
- `BIN` is `runtime_command[0]` at call time. `parse`: text = stdout; usage all None; `is_error = code != 0`; ok = `code == 0 and out.strip() != ""`.

- [ ] **Step 1: Failing tests.**
  - `test_command_substitutes_prompt_and_instructions_file`;
  - `test_command_prepends_instructions_without_placeholder`;
  - `test_command_empty_output_is_failure`;
  - `test_command_unset_is_a_problem_not_a_crash` (run → 1, report says `runtime_command is not set`).
- [ ] **Step 2: Run; fail.** **Step 3: Implement.** **Step 4: Full suite passes.**
- [ ] **Step 5: Commit.** `feat(runtimes): generic command runtime`

### Task 6: Gemini and Qwen adapters

**Files:**
- Create: `libraryan/runtimes/gemini.py`, `libraryan/runtimes/qwen.py`, `libraryan/_runtime/policies/gemini-author.toml`, `libraryan/_runtime/policies/gemini-reviewer.toml`
- Modify: `libraryan/install.py` (`_copy` also copies `_runtime/policies` to `.libraryan/policies`), `tests/fake_runtime.py`, `tests/test_runtimes.py`

**Gemini** (`gemini-cli.md` §1, 2, 4 policy engine, 5, 9, 11):
- Headless `-p`, `-o json`.
- Trust for this run via env `GEMINI_CLI_TRUST_WORKSPACE=true` (or `--skip-trust`, whichever the research marks verified).
- Author `--approval-mode auto_edit --policy .libraryan/policies/gemini-author.toml`. Headless mode denies shell by default, so this policy allows exactly the Task 3 shell commands (read-only git, `libraryan check|audit`, `rm`, `mv`, `mkdir -p`).
- Reviewer `--approval-mode default --policy .libraryan/policies/gemini-reviewer.toml`, which allows reads and read-only git and denies writes. Never use plan mode (it can switch to yolo).
- No USD or turn flag on the CLI; settings-only caps are not written (Global Constraints).
- `parse`:
  - the JSON `response` is the text, and `stats` tokens are summed;
  - ok = exit 0 and a non-empty `response` and no `error` key;
  - empty stdout + stderr is a failure, and the stderr line reaches the problem via `_call_model`.

**Qwen** (`qwen-code.md`): Claude-like JSON with no cost.
- Author `--approval-mode auto-edit` or the flag the research names; reviewer read-only per the research.
- `--max-session-turns <limits["turns"]>`.
- `parse` like Claude's, but `cost_usd` None; a turn-cap result → ok False with `is_error` True.

- [ ] **Step 1: Failing tests.**
  - `test_gemini_reviewer_uses_policy_not_plan_mode`;
  - `test_gemini_empty_stdout_stderr_error_fails_run` (Review Focus 1: run → 1, the report contains the fake's stderr line);
  - `test_gemini_parse_ok`;
  - `test_qwen_argv_has_turn_cap` (`--max-session-turns 60` for a run, 200 for setup, 30 for review);
  - `test_qwen_turn_cap_hit_fails_run` (Review Focus 5: no commit, the problem mentions the runtime);
  - `test_policy_file_installed`.
- [ ] **Step 2: Run; fail.** **Step 3: Implement.** **Step 4: Full suite passes.**
- [ ] **Step 5: Commit.** `feat(runtimes): Gemini CLI and Qwen Code adapters`

### Task 7: Copilot, OpenCode and Cursor adapters

**Files:** Create `libraryan/runtimes/copilot.py`, `opencode.py` and `cursor.py`. Modify `tests/fake_runtime.py` and `tests/test_runtimes.py`.

**Copilot** (`copilot-cli.md`):
- `--agent libraryan|libraryan-reviewer` reads `.claude/agents`, so `instructions` is not prepended. JSONL output.
- Author `--allow-tool` for write/read/the allowed shell commands, plus `--deny-tool 'shell(git commit)'` and `--deny-tool 'shell(git push)'`. Reviewer: read tools only.
- No turn flag unless the research names one; `--max-ai-credits` is not USD, so it is unused.

**OpenCode** (`opencode.md`):
- `run --format json`, or the research's verified equivalent.
- `cost_usd` = the sum of `step_finish` costs; steps are capped with `limits["turns"]` only if a CLI flag exists, otherwise nothing.
- The reviewer uses a read-only agent or permission per the research.
- Record that flags are pinned to the researched version (a comment with the version).

**Cursor** (`cursor-cli.md`):
- Author `-p --force --output-format json`; reviewer `--mode ask`.
- `parse`: ok only when stdout is JSON with a non-empty `result`, the subtype is success and exit is 0. `is_error` from Cursor is ignored as a success signal.
- Mark experimental in its module docstring.

- [ ] **Step 1: Failing tests.**
  - `test_copilot_denies_commit_and_push`, `test_copilot_uses_agent_file_not_prepend`;
  - `test_opencode_sums_step_costs`;
  - `test_cursor_author_has_force_reviewer_ask`;
  - `test_cursor_non_json_exit0_is_failure` (Review Focus 2);
  - `test_cursor_is_error_false_but_empty_result_fails`.
- [ ] **Step 2: Run; fail.** **Step 3: Implement.** **Step 4: Full suite passes.**
- [ ] **Step 5: Commit.** `feat(runtimes): Copilot, OpenCode and Cursor adapters (experimental)`

### Task 8: Early edit guard for every tool

**Files:** Modify `libraryan/install.py`, `libraryan/cchooks.py`, `tests/test_install.py`, `tests/test_cchooks.py`. Create `libraryan/_templates/opencode-plugin.js`.

**Interfaces / decisions:**
- `install.GUARD_CMD = 'python3 "$(git rev-parse --show-toplevel)/.libraryan/bin/libraryan" guard'` and `install.ENSURE_CMD` (same, `ensure-hooks`). These replace the `$CLAUDE_PROJECT_DIR` form everywhere (Copilot reads `.claude/settings.json` but has no `CLAUDE_PROJECT_DIR`).
- `install.HOOK_FILES: dict[str, dict]` maps each path to the hooks to merge:

| Path | Hooks |
|---|---|
| `.claude/settings.json` | `PreToolUse` matcher `Edit\|Write\|MultiEdit\|NotebookEdit\|apply_patch`, plus `SessionStart` |
| `.codex/hooks.json` | `PreToolUse` matcher `Edit\|Write\|apply_patch\|Bash`, plus `SessionStart` |
| `.gemini/settings.json` | `BeforeTool` matcher `write_file\|replace`, plus `SessionStart`; also `context.fileName = ["AGENTS.md", "GEMINI.md"]`, set only when absent and removed on uninstall only if unchanged |
| `.qwen/settings.json` | `PreToolUse` matcher `write_file\|edit\|Write\|Edit`, plus `SessionStart` |
| `.cursor/hooks.json` | `{"version": 1}`; `preToolUse: [{"command": GUARD_CMD, "matcher": "Write\|Edit\|Delete"}]`, `sessionStart: [{"command": ENSURE_CMD}]` (flat entries, no nested `hooks`) |

- `.opencode/plugins/libraryan.js` (plural `plugins`, per the research) is copied from the template. Its `tool.execute.before`:
  - for `edit|write|patch`, it builds a guard payload with `tool_name` `Write` or `apply_patch`, `tool_input.file_path` or `patch`, and `cwd`;
  - it pipes the payload to the guard command via Bun `$`;
  - when the guard exits 2, it throws `Error(stderr)`.
- `merge_hooks(doc: dict, hooks: dict) -> dict` and `strip_hooks(doc: dict) -> dict` generalise `merge_settings`/`strip_settings`. `_ours` matches `MARK` in an entry's own `command` (Cursor) or in its nested `hooks[].command`. Keep `merge_settings`/`strip_settings` as thin wrappers only if tests import them; otherwise rename.
- init, upgrade and uninstall:
  - init and upgrade write every hook file as `merge_hooks(strip_hooks(old), …)`. Upgrade now refreshes hook files, which replaces the old `$CLAUDE_PROJECT_DIR` entries.
  - Invalid JSON in any existing hook file → init refuses, naming the file.
  - `cfg["created_files"]` lists the hook files init created; a stored `created_settings: true` counts as `.claude/settings.json`.
  - Uninstall strips each file and deletes it when it was created by init and is now empty (`{}` or `{"version": 1}`).
- `PATHS` gains all five new files.
- `cchooks.EDIT_TOOLS` gains `write_file`, `replace`, `edit`, `write`, `patch`, `create` and `Delete`. `_targets` also reads `tool_input.filePath`.
- init prints a "Teammates' tools" note:
  - Codex: trust the project and the hook once with `/hooks`;
  - Gemini and Copilot: trust the folder;
  - the git lock covers every tool until then.

- [ ] **Step 1: Failing tests.**
  - `test_init_writes_every_guard_file`;
  - `test_existing_hook_files_merged_not_overwritten` (a user's own Gemini hook and `context` survive);
  - `test_upgrade_replaces_old_claude_project_dir_hook`;
  - `test_uninstall_removes_created_hook_files_keeps_user_ones`;
  - `test_invalid_codex_hooks_json_refuses_init`;
  - `test_guard_gemini_write_file`, `test_guard_qwen_edit`, `test_guard_cursor_delete`;
  - `test_guard_opencode_filepath`;
  - `test_guard_command_runs_from_subdir`: run `GUARD_CMD` through `sh -c` in a repo subdirectory with a payload targeting `docs/kb/index.md` → exit 2.
- [ ] **Step 2: Run; fail.** **Step 3: Implement.** **Step 4: Full suite passes.**
- [ ] **Step 5: Commit.** `feat(install): early edit guard for Codex, Gemini, Qwen, Cursor and OpenCode`

### Task 9: Detection, `init --runtime`, `libraryan runtime`

**Files:** Modify `libraryan/runtimes/__init__.py`, `libraryan/install.py` (`init`), `libraryan/cli.py` (USAGE and the `runtime` command), `tests/test_install.py`, and create `tests/test_cli_runtime.py`.

**Interfaces:**
- `runtimes.pick() -> str | None`: the first name in `ORDER` whose `detect(name)` is not None.
- `install.init(project, source=PKG, run_setup=True, runtime: str | None = None)`:
  - `runtime or pick()`. When none is found and `run_setup` is set, refuse with `libraryan: no supported agent CLI found. Install one of:` followed by each adapter's `INSTALL`.
  - With `--no-setup` and none found, store `"claude"`.
  - Store `cfg["runtime"]` and `cfg["runtime_bin"] = shutil.which(adapter.BIN)`, an absolute path because cron has a minimal PATH.
  - `--runtime command` with no `runtime_command` in config → refuse with a message naming the key.
  - Print the chosen runtime, its version and its `AUTH` line.
- CLI:
  - `libraryan init [--no-setup] [--runtime NAME]`.
  - `libraryan runtime` prints:
    ```
    writer:   <name> <version or "not found"> (<bin>)
    reviewer: <name> (same as writer) | <name> <version> (<bin>)
    found:    claude 2.1.x, codex 0.x, ...   (or "none")
    ```
  - `libraryan runtime NAME [--reviewer]`:
    - refuses an unknown or undetected name (except `command`, which needs `runtime_command`);
    - sets `runtime`/`runtime_bin`, or `reviewer_runtime`/`reviewer_runtime_bin`;
    - saves, and commits via `install._commit(project, f"runtime {name}", cfg)`.
- The trace records each call's `runtime` (Task 2) plus `runtime_version` from a per-process `functools.lru_cache` around `detect`.

- [ ] **Step 1: Failing tests.** Use fake binaries on a monkeypatched `PATH`, each printing a version.
  - `test_pick_follows_preference_order` (only `gemini` and `cursor` present → `gemini`);
  - `test_init_refuses_without_any_runtime`;
  - `test_init_runtime_flag_overrides`;
  - `test_runtime_command_lists_found`;
  - `test_runtime_switch_commits_config`;
  - `test_runtime_switch_reviewer_only`;
  - `test_upgrade_from_02_keeps_claude` (a config with `claude_bin` and no `runtime` → after upgrade `runtime == "claude"` and `runtime_bin` == the old `claude_bin`; a run uses it);
  - `test_trace_records_runtime_version`.
- [ ] **Step 2: Run; fail.** **Step 3: Implement.** **Step 4: Full suite passes.**
- [ ] **Step 5: Commit.** `feat: auto-detect the runtime; init --runtime; libraryan runtime`

### Task 10: Docs and the 0.3.0 version

**Files:**
- Modify: `README.md`, `docs/guide.md`, `site/index.html`, `CHANGELOG.md`, and the version in `libraryan/__init__.py`, `pyproject.toml`, `plugin/.claude-plugin/plugin.json` and `tests/test_version.py` → `0.3.0`.

**README changes:**
- Requirements row: "Claude Code 2.1+" becomes "one agent CLI: Claude Code, Codex, Gemini, Qwen, Copilot, OpenCode or Cursor (others via a custom command)".
- "Honest limits" and the FAQ answer: drop "runs through Claude Code today / planned"; say non-Claude runtimes are experimental until smoke-tested.
- A short "Runtimes" table with status (Claude Code: stable; others: experimental) and cost reporting (USD / unknown).
- The worktree isolation line goes in the safety table: "It touches my code → it works in a throwaway copy; only owned docs come back".

**Guide changes:**
- A Runtimes section: config keys, `libraryan runtime`, the writer/reviewer split, and the per-tool auth and trust notes.
- `command` recipes for Aider (`aider --yes-always --no-auto-commits --no-dirty-commits --message {prompt}`) and Amp, from `others.md`.
- Turn caps.
- A smoke checklist: one real `libraryan run` per runtime, what to check, and how to drop "experimental".

**CHANGELOG:** a `## 0.3.0` section for the user-visible changes:
- runtimes and auto-detect;
- worktree isolation;
- tool-neutral instructions;
- guard files per tool;
- unknown cost;
- `claude_bin` → `runtime_bin` alias.

- [ ] **Step 1: Make the edits.**
- [ ] **Step 2: Run `python -m pytest tests -q`** (the version and packaging tests).
- [ ] **Step 3: Run `python -m build && twine check --strict dist/*`** (if available; skip quietly otherwise).
- [ ] **Step 4: Run the maintainer's privacy check.**
- [ ] **Step 5: Commit.** `docs: multi-runtime docs; 0.3.0`

Release (merge to `main`, push, tag `v0.3.0`) is **not** a plan step: the controller asks the user first.
