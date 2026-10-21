import sys
import fcntl
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from helpers import install_runtime
from libraryan import config, runner
from libraryan.runtimes import claude

FAKE = Path(__file__).resolve().parent / "fake_claude.py"
FAKE_RUNTIME = FAKE.with_name("fake_runtime.py")


def git(repo, *args, env=None):
    e = {**os.environ, **(env or {})}
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, env=e).stdout


def make_kb(repo, ignore_state=True, runtime="claude", monkeypatch=None):
    install_runtime(repo)
    if ignore_state:
        (repo / ".libraryan/.gitignore").write_text("state/\n")
    (repo / "docs/kb").mkdir(parents=True)
    (repo / "docs/kb/index.md").write_text("# Index\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "kb", env={"LIBRARYAN": "1"})
    cfg = config.load(repo)
    cfg["runtime_bin"] = str(FAKE)
    if runtime != "claude":  # one shared fake, its output format picked by FAKE_FORMAT
        cfg.update(runtime=runtime, runtime_bin=str(FAKE_RUNTIME))
        monkeypatch.setenv("FAKE_FORMAT", "text" if runtime == "command" else runtime)
        if runtime == "command":
            cfg["runtime_command"] = [sys.executable, str(FAKE_RUNTIME), "{prompt}"]
    cfg["ask_before_commit"] = False  # test-only: these scenarios test the commit path (config.load forces True)
    return cfg


def state(repo):
    return repo / ".libraryan/state"


def add_request(repo):
    (repo / ".libraryan/requests").mkdir(exist_ok=True)
    (repo / ".libraryan/requests/20261019-120000-x.md").write_text("we chose sqlite\n")


def last_trace(repo):
    return [json.loads(l) for l in (state(repo) / "runs.jsonl").read_text().splitlines()][-1]


def libraryan_commits(repo):
    return [l for l in git(repo, "log", "--format=%s").splitlines() if l.startswith("docs(libraryan):")]


def test_run_noop_without_work(repo):
    cfg = make_kb(repo)
    state(repo).mkdir()
    (state(repo) / "last_processed").write_text(git(repo, "rev-parse", "HEAD"))
    (state(repo) / "last_health").write_text(str(time.time()))
    assert runner.run(repo, cfg, "manual") == 0
    assert not (state(repo) / "fake_claude_ran").exists()


@pytest.mark.parametrize("runtime", ["claude", "codex", "command"])
def test_run_commits_changes(repo, runtime, monkeypatch):
    cfg = make_kb(repo, runtime=runtime, monkeypatch=monkeypatch)
    add_request(repo)
    assert runner.run(repo, cfg, "manual") == 0
    assert libraryan_commits(repo) == ["docs(libraryan): manual run"]
    assert "SUMMARY ok" in git(repo, "log", "-1", "--format=%b")
    latest = (state(repo) / "reports/latest.md").read_text()
    assert "docs/kb/index.md" in latest and "SUMMARY ok" in latest
    assert runner.find_work(repo, cfg, "manual")["commits"] == 0  # its own commit is not new work


def test_commit_excludes_unrelated_changes(repo):
    cfg = make_kb(repo)
    (repo / "src").mkdir()
    (repo / "src/app.py").write_text("x = 1\n")
    git(repo, "add", "src/app.py")
    git(repo, "commit", "-m", "app")
    (repo / "src/app.py").write_text("x = 2\n")
    (repo / "src/other.py").write_text("y = 1\n")
    git(repo, "add", "src/other.py")
    assert runner.run(repo, cfg, "manual") == 0
    assert git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["docs/kb/index.md"]
    status = git(repo, "status", "--porcelain").splitlines()
    assert " M src/app.py" in status and "A  src/other.py" in status


def test_run_deferred_off_default_branch(repo):
    cfg = make_kb(repo)
    git(repo, "checkout", "-q", "-b", "feature")
    add_request(repo)
    assert runner.run(repo, cfg, "manual") == 0
    assert last_trace(repo)["outcome"] == "deferred"
    assert not (state(repo) / "fake_claude_ran").exists()


def test_run_deferred_on_detached_head(repo):
    cfg = make_kb(repo)
    git(repo, "checkout", "-q", "--detach")
    assert runner.run(repo, cfg, "manual") == 0
    assert not (state(repo) / "fake_claude_ran").exists()


def test_run_lock_sets_rerun(repo):
    cfg = make_kb(repo)
    state(repo).mkdir()
    with open(state(repo) / "run.lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert runner.run(repo, cfg, "manual") == 0
    assert (state(repo) / "rerun").exists()
    assert not (state(repo) / "fake_claude_ran").exists()


def test_run_reverts_on_lint_failure(repo, monkeypatch):
    cfg = make_kb(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "badnote")
    assert runner.run(repo, cfg, "manual") == 1
    assert libraryan_commits(repo) == []
    assert not (repo / "docs/kb/bad.md").exists()
    assert (repo / "docs/kb/index.md").read_text() == "# Index\n"
    assert "docs/kb/bad.md: missing frontmatter" in (state(repo) / "reports/latest.md").read_text()


def test_postcommit_skips_other_host(repo, monkeypatch):
    cfg = make_kb(repo)
    cfg["runner_host"] = "elsewhere"
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    runner.post_commit(repo, cfg, {})
    assert not (state(repo) / "last_commit_at").exists()


def test_postcommit_spawns_wait(repo, monkeypatch):
    cfg = make_kb(repo)
    cfg["runner_host"] = runner.socket.gethostname()
    calls = []
    monkeypatch.setattr(runner.subprocess, "Popen", lambda cmd, **k: calls.append((cmd, k)))
    monkeypatch.setenv("GIT_INDEX_FILE", "/tmp/dead-index")
    runner.post_commit(repo, cfg, {"LIBRARYAN": "1"})
    assert calls == []
    runner.post_commit(repo, cfg, {})
    assert (state(repo) / "last_commit_at").exists()
    (cmd, kw), = calls
    assert cmd[-1] == "wait" and kw["start_new_session"] and "GIT_INDEX_FILE" not in kw["env"]


def test_wait_debounces(repo, monkeypatch):
    cfg = make_kb(repo)
    clock = [1000.0]
    monkeypatch.setattr(runner, "_now", lambda: clock[0])
    monkeypatch.setattr(runner, "_sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    ran = []
    monkeypatch.setattr(runner, "run", lambda root, cfg, reason: ran.append((clock[0], reason)))
    state(repo).mkdir()
    (state(repo) / "last_commit_at").write_text("900")
    runner.wait(repo, cfg)
    assert ran == [(900 + cfg["debounce_minutes"] * 60, "commit")]


def give_finding(repo):
    """A committed audit finding, so a health run calls the model."""
    (repo / "README.md").write_text("# test\nRun `src/gone.py`.\n")
    git(repo, "commit", "-qam", "readme", env={"LIBRARYAN": "1"})


def test_cli_run_end_to_end(repo):
    cfg = make_kb(repo)
    give_finding(repo)
    config.save(repo, cfg)
    r = subprocess.run([str(repo / ".libraryan/bin/libraryan"), "run", "--reason", "daily"], cwd=repo,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert libraryan_commits(repo) == []  # a stored `ask_before_commit: false` is ignored: a person approves
    r = subprocess.run([str(repo / ".libraryan/bin/libraryan"), "approve"], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert libraryan_commits(repo) == ["docs(libraryan): daily run"]
    assert not list((repo / ".libraryan").rglob("__pycache__"))


def head_files(repo):
    return git(repo, "ls-tree", "-r", "-z", "--name-only", "HEAD").split("\0")


def test_requests_only_deleted_never_swept(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    git(repo, "add", ".libraryan/requests")
    git(repo, "commit", "-m", "request")
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "race_request")
    assert runner.run(repo, cfg, "manual") == 0
    files = head_files(repo)
    assert ".libraryan/requests/20261019-120000-x.md" not in files  # processed request deletion committed
    assert ".libraryan/requests/other-agent.md" not in files
    assert (repo / ".libraryan/requests/other-agent.md").exists()


def test_request_written_during_failed_run_survives(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "race_request,badnote")
    assert runner.run(repo, cfg, "manual") == 1
    assert (repo / ".libraryan/requests/other-agent.md").exists()
    assert (repo / ".libraryan/requests/20261019-120000-x.md").exists()  # restored


def test_state_files_never_committed(repo):
    cfg = make_kb(repo, ignore_state=False)
    assert runner.run(repo, cfg, "manual") == 0
    assert not [f for f in head_files(repo) if f.startswith(".libraryan/state/")]


def test_commit_during_run_is_still_work(repo, monkeypatch):
    cfg = make_kb(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "commit")
    assert runner.run(repo, cfg, "manual") == 0
    assert runner.find_work(repo, cfg, "manual")["commits"] == 1


def test_branch_switch_during_run_defers(repo, monkeypatch):
    cfg = make_kb(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "checkout")
    assert runner.run(repo, cfg, "manual") == 0
    assert libraryan_commits(repo) == []
    assert git(repo, "status", "--porcelain") == ""
    assert last_trace(repo)["outcome"] == "deferred"
    assert not (state(repo) / "fake_review_argv").exists()  # no paid review once the branch moved


def test_model_timeout_fails_run(repo, monkeypatch):
    cfg = make_kb(repo)
    cfg["run_timeout_minutes"] = 0.01
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "sleep")
    assert runner.run(repo, cfg, "manual") == 1
    assert (repo / "docs/kb/index.md").read_text() == "# Index\n"
    assert "timed out" in (state(repo) / "reports/latest.md").read_text()


def test_non_ascii_note_committed(repo, monkeypatch):
    cfg = make_kb(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "unicode")
    assert runner.run(repo, cfg, "manual") == 0
    assert "docs/kb/գիտելիք.md" in head_files(repo)


def commit_request(repo):
    add_request(repo)
    git(repo, "add", ".libraryan/requests")
    git(repo, "commit", "-m", "request")


def test_git_rm_request_deletion_committed(repo, monkeypatch):
    cfg = make_kb(repo)
    commit_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "gitrm")
    assert runner.run(repo, cfg, "manual") == 0
    assert ".libraryan/requests/20261019-120000-x.md" not in head_files(repo)
    assert git(repo, "status", "--porcelain") == ""


def test_git_mv_commits_both_sides(repo, monkeypatch):
    cfg = make_kb(repo)
    (repo / "docs/a.md").write_text("---\ntitle: a\ntype: note\nupdated: 2026-10-19\nsources: [x]\n---\nA\n")
    git(repo, "add", "docs/a.md")
    git(repo, "commit", "-m", "a", env={"LIBRARYAN": "1"})
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "gitmv")
    assert runner.run(repo, cfg, "manual") == 0
    files = head_files(repo)
    assert "docs/kb/a.md" in files and "docs/a.md" not in files
    assert git(repo, "status", "--porcelain") == ""


def test_undone_git_rm_leaves_nothing_staged(repo, monkeypatch):
    cfg = make_kb(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "rm_restore")
    assert runner.run(repo, cfg, "manual") == 0
    assert "README.md" in head_files(repo)
    assert git(repo, "status", "--porcelain", "--", "README.md") == ""


def test_discard_drops_new_file_only(repo, monkeypatch):
    cfg = make_kb(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "discard,discard_existing")
    assert runner.run(repo, cfg, "manual") == 0
    assert not (repo / "docs/kb/x.md").exists()
    assert "docs/kb/x.md" not in head_files(repo)
    assert "updated by fake claude" in git(repo, "show", "HEAD:docs/kb/index.md")  # existing file kept


def test_prompt_lists_baseline_and_leaves_it_alone(repo):
    cfg = make_kb(repo)
    (repo / "src").mkdir()
    (repo / "src/x.py").write_text("x = 1\n")
    assert runner.run(repo, cfg, "manual") == 0
    prompt = (state(repo) / "fake_claude_prompt").read_text()
    assert "Baseline" in prompt and "- src/x.py" in prompt
    assert (repo / "src/x.py").read_text() == "x = 1\n"
    assert "src/x.py" not in head_files(repo)


def test_untracked_request_is_not_work(repo):
    cfg = make_kb(repo)
    add_request(repo)
    assert runner.find_work(repo, cfg, "manual")["requests"] == []
    git(repo, "add", ".libraryan/requests")
    assert runner.find_work(repo, cfg, "manual")["requests"] == [".libraryan/requests/20261019-120000-x.md"]


def test_build_prompt_includes_baseline():
    work = {"requests": [], "since": None, "commits": 0, "health": False, "baseline": ["AGENTS.md"]}
    assert "- AGENTS.md" in runner.build_prompt("setup", work, {})


def test_git_rm_of_staged_request(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    git(repo, "add", ".libraryan/requests")  # staged, never committed
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "gitrm")
    assert runner.run(repo, cfg, "manual") == 0
    assert libraryan_commits(repo) == ["docs(libraryan): manual run"]
    assert git(repo, "status", "--porcelain") == ""


def test_model_env_strips_claude_session_vars(repo, monkeypatch):
    cfg = make_kb(repo)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    monkeypatch.setenv("GIT_INDEX_FILE", "/tmp/dead-index")
    for k in ("CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "env")
    assert runner.run(repo, cfg, "manual") == 0
    keys = (state(repo) / "fake_claude_env").read_text().split()
    assert "LIBRARYAN" in keys
    assert {"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK"} <= set(keys)  # auth/provider settings survive
    assert not [k for k in keys if k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")
                or k.startswith("GIT_") or ("CLAUDE_CODE_" in k and "SESSION" in k)]


def test_owned_doc_conflict_plus_lint_failure_still_backs_off(repo, monkeypatch):
    cfg = make_kb(repo)
    commit_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "real_doc_edit,badnote")
    assert runner.run(repo, cfg, "commit") == 1
    assert (state(repo) / "last_failed").exists()


def test_other_agents_staged_new_request_stays_staged(repo, monkeypatch):
    cfg = make_kb(repo)
    commit_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "stage_request")
    assert runner.run(repo, cfg, "commit") == 0
    assert ".libraryan/requests/other-agent.md" in git(repo, "diff", "--cached", "--name-only")


def _alive(pid):
    """Portable (no /proc): signal 0 probes the pid. A zombie still answers until reaped; reap it if ours."""
    try:
        if os.waitpid(pid, os.WNOHANG)[0] == pid:
            return False
    except ChildProcessError:  # not our child: its new parent (init) reaps it
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # exists, owned by someone else (pid reused)
        return True
    return True


def test_timeout_kills_process_group(repo, monkeypatch):
    cfg = make_kb(repo)
    cfg["run_timeout_minutes"] = 0.02
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "spawn")
    assert runner.run(repo, cfg, "manual") == 1
    pid = int((state(repo) / "fake_claude_child").read_text())
    for _ in range(20):
        if not _alive(pid):
            break
        time.sleep(0.1)
    else:
        os.kill(pid, 9)
        raise AssertionError("model's child survived the timeout")


def record_timeouts(monkeypatch):
    """Timeouts the model calls were given (git calls pass none)."""
    seen = []

    class Rec(subprocess.Popen):
        def communicate(self, input=None, timeout=None):
            if timeout:
                seen.append(timeout)
            return super().communicate(input, timeout)

    monkeypatch.setattr(subprocess, "Popen", Rec)
    return seen


def test_setup_uses_setup_timeout(repo, monkeypatch):
    cfg = make_kb(repo)
    cfg["independent_review"] = False
    seen = record_timeouts(monkeypatch)
    runner.run(repo, cfg, "setup")
    add_request(repo)
    git(repo, "add", ".libraryan/requests")
    runner.run(repo, cfg, "manual")
    assert seen == [cfg["setup_timeout_minutes"] * 60, cfg["run_timeout_minutes"] * 60]
    assert config.DEFAULTS["setup_timeout_minutes"] == 120


def test_interrupt_restores_and_reports(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)

    def half_done(role, prompt, cwd, cfg, reason):
        with open(cwd / "docs/kb/index.md", "a") as f:
            f.write("half\n")
        git(cwd, "rm", "-q", "--", "README.md")
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "_call_model", half_done)
    try:
        runner.run(repo, cfg, "manual")
        raise AssertionError("KeyboardInterrupt swallowed")
    except KeyboardInterrupt:
        pass
    assert git(repo, "status", "--porcelain", "--untracked-files=no") == ""
    assert (repo / "docs/kb/index.md").read_text() == "# Index\n"
    assert "KeyboardInterrupt" in (state(repo) / "reports/latest.md").read_text()
    assert no_worktree(repo)


def test_cli_check_owned_files_only_non_ascii(repo):
    cfg = make_kb(repo)
    config.save(repo, cfg)
    (repo / "docs/գիտելիք.md").write_text("[x](nope.md)\n")
    (repo / "fixtures").mkdir()
    (repo / "fixtures/f.md").write_text("[y](gone.md)\n")  # excluded: not Libraryan's
    r = subprocess.run([str(repo / ".libraryan/bin/libraryan"), "check"], cwd=repo, capture_output=True,
                       text=True)
    assert r.returncode == 1 and "docs/գիտելիք.md: broken link nope.md" in r.stdout
    assert "fixtures/f.md" not in r.stdout


def test_failed_run_backs_off_until_head_moves(repo, monkeypatch):
    cfg = make_kb(repo)
    commit_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "badnote")
    assert runner.run(repo, cfg, "commit") == 1
    assert (state(repo) / "last_failed").read_text().strip() == git(repo, "rev-parse", "HEAD").strip()
    monkeypatch.delenv("FAKE_CLAUDE_MODE")
    (state(repo) / "fake_claude_ran").unlink()
    for reason in ("commit", "daily", "rerun"):
        assert runner.run(repo, cfg, reason) == 0
    assert not (state(repo) / "fake_claude_ran").exists()  # same HEAD: no paid retry
    assert runner.run(repo, cfg, "manual") == 0
    assert (state(repo) / "fake_claude_ran").exists() and not (state(repo) / "last_failed").exists()


def test_missing_index_promotes_to_setup(repo):
    cfg = make_kb(repo)
    git(repo, "rm", "-q", "docs/kb/index.md")
    git(repo, "commit", "-m", "rm index", env={"LIBRARYAN": "1"})
    assert runner.run(repo, cfg, "commit") == 0
    assert "Reason: setup" in (state(repo) / "fake_claude_prompt").read_text()
    assert libraryan_commits(repo) == ["docs(libraryan): setup run"]


def test_daily_health_skipped_on_idle_repo(repo):
    cfg = make_kb(repo)
    give_finding(repo)
    assert runner.run(repo, cfg, "daily") == 0
    (state(repo) / "fake_claude_ran").unlink()
    assert runner.run(repo, cfg, "daily") == 0
    assert not (state(repo) / "fake_claude_ran").exists()


def test_trace_written_for_noop(repo):
    cfg = make_kb(repo)
    state(repo).mkdir()
    (state(repo) / "last_processed").write_text(git(repo, "rev-parse", "HEAD"))
    (state(repo) / "last_health").write_text(str(time.time()))
    runner.run(repo, cfg, "manual")
    t = last_trace(repo)
    assert t["outcome"] == "noop" and t["calls"] == [] and t["reason"] == "manual"


def test_trace_written_for_committed_run(repo):
    cfg = make_kb(repo)
    add_request(repo)
    runner.run(repo, cfg, "manual")
    t = last_trace(repo)
    assert t["outcome"] == "committed" and t["calls"][0]["role"] == "author"
    assert t["calls"][0]["cost_usd"] == 0.01 and t["commit"] == git(repo, "rev-parse", "HEAD").strip()
    assert t["changed"] >= 1 and t["problems"] == 0 and t["cap"] is None
    assert t["calls"][1]["role"] == "reviewer"
    assert "- Cost: $0.02 (4 turns)" in (state(repo) / "reports/latest.md").read_text()  # author + reviewer
    assert not (state(repo) / "runs.log").exists()


def test_trace_deferred(repo):
    cfg = make_kb(repo)
    git(repo, "checkout", "-q", "-b", "feature")
    add_request(repo)
    runner.run(repo, cfg, "manual")
    assert [last_trace(repo)["outcome"], last_trace(repo)["calls"]] == ["deferred", []]


def test_trace_failed_and_aborted(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "badnote")
    assert runner.run(repo, cfg, "manual") == 1
    t = last_trace(repo)
    assert t["outcome"] == "failed" and t["problems"] >= 1 and t["commit"] is None

    def boom(role, prompt, cwd, cfg, reason):
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "_call_model", boom)
    try:
        runner.run(repo, cfg, "manual")
    except KeyboardInterrupt:
        pass
    assert last_trace(repo)["outcome"] == "aborted"


def test_nojson_output_fails(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "nojson")
    assert runner.run(repo, cfg, "manual") == 1
    assert last_trace(repo)["outcome"] == "failed" and libraryan_commits(repo) == []
    assert "claude failed (exit 0)" in (state(repo) / "reports/latest.md").read_text()


def test_missing_runtime_binary_fails_and_backs_off(repo):
    cfg = make_kb(repo)
    cfg["runtime_bin"] = str(repo / "no-such-claude")
    add_request(repo)
    assert runner.run(repo, cfg, "manual") == 1
    assert "could not start" in (state(repo) / "reports/latest.md").read_text()
    assert (state(repo) / "last_failed").exists() and libraryan_commits(repo) == []


def test_unknown_cost_reported(repo, monkeypatch):
    from libraryan import trace
    cfg = make_kb(repo)
    add_request(repo)
    monkeypatch.setattr(runner, "_call_model", lambda *a: ("done", [], {"runtime": "x", "cost_usd": None}))
    assert runner.run(repo, cfg, "manual") == 0
    assert "- Cost: unknown" in (state(repo) / "reports/latest.md").read_text()
    assert trace.stats(state(repo)).endswith(" unknown=1")


def test_trace_failure_does_not_break_run(repo):
    cfg = make_kb(repo)
    add_request(repo)
    (state(repo) / "runs.jsonl").mkdir(parents=True)
    assert runner.run(repo, cfg, "manual") == 0
    assert libraryan_commits(repo) == ["docs(libraryan): manual run"]
    assert (state(repo) / "last_processed").exists()


def prewrite(repo, n, **rec):
    st = state(repo)
    st.mkdir(exist_ok=True)
    for _ in range(n):
        runner.trace.append(st, rec)


def test_budget_flag_passed(repo, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "argv")
    cfg = make_kb(repo)
    give_finding(repo)  # an untracked request is no work; a finding makes the health run a model run
    runner.run(repo, cfg, "commit")
    a = json.loads((state(repo) / "fake_claude_argv").read_text())
    assert a[a.index("--max-budget-usd") + 1] == "5" and "--max-budget-usd" not in a[-1]
    (repo / "docs/kb/index.md").unlink()
    git(repo, "commit", "-qam", "rm", env={"LIBRARYAN": "1"})
    runner.run(repo, cfg, "commit")  # no KB: becomes a setup run
    a = json.loads((state(repo) / "fake_claude_argv").read_text())
    assert a[a.index("--max-budget-usd") + 1] == "25"


def test_cap_runs_per_day(repo):
    cfg = make_kb(repo)
    give_finding(repo)  # an untracked request is no work; a finding makes the health run a model run
    prewrite(repo, 24, outcome="committed", calls=[{"role": "author"}])
    assert runner.run(repo, cfg, "commit") == 0
    assert not (state(repo) / "fake_claude_ran").exists()
    t = last_trace(repo)
    assert t["outcome"] == "capped" and t["cap"] == "max_runs_per_day"


def test_cap_consecutive_failures(repo):
    cfg = make_kb(repo)
    give_finding(repo)  # an untracked request is no work; a finding makes the health run a model run
    prewrite(repo, 3, outcome="failed", calls=[])
    prewrite(repo, 1, outcome="noop", calls=[])  # ignored
    assert runner.cap_hit(state(repo), cfg) == "max_consecutive_failures"
    runner.run(repo, cfg, "commit")
    assert last_trace(repo)["cap"] == "max_consecutive_failures"
    prewrite(repo, 1, outcome="committed", calls=[])  # a success resets the streak
    assert runner.cap_hit(state(repo), cfg) is None


def test_cap_commits_per_day(repo):
    cfg = make_kb(repo)
    prewrite(repo, 12, outcome="committed", calls=[])
    assert runner.cap_hit(state(repo), cfg) == "max_commits_per_day"


def test_cap_ignored_for_manual(repo):
    cfg = make_kb(repo)
    add_request(repo)
    prewrite(repo, 24, outcome="committed", calls=[{"role": "author"}])
    runner.run(repo, cfg, "manual")
    assert (state(repo) / "fake_claude_ran").exists() and last_trace(repo)["outcome"] == "committed"


def test_cap_writes_report_line(repo):
    cfg = make_kb(repo)
    give_finding(repo)  # an untracked request is no work; a finding makes the health run a model run
    prewrite(repo, 3, outcome="aborted", calls=[])
    runner.run(repo, cfg, "commit")
    line = "Daily cap reached: max_consecutive_failures; run `python3 .libraryan/bin/libraryan run` to override."
    assert line in (state(repo) / "reports/latest.md").read_text()


def commit_old_doc(repo):
    (repo / "docs/old.md").write_text("# Old\n\nThe deploy script pushes images to staging.\n")
    git(repo, "add", "docs/old.md")
    git(repo, "commit", "-m", "old", env={"LIBRARYAN": "1"})


def test_run_fails_on_unledgered_deletion(repo, monkeypatch):
    cfg = make_kb(repo)
    commit_old_doc(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "delete_doc")
    assert runner.run(repo, cfg, "manual") == 1
    assert libraryan_commits(repo) == [] and (repo / "docs/old.md").exists()
    assert git(repo, "status", "--porcelain", "--", "docs") == ""
    assert "deletion ledger: docs/old.md" in (state(repo) / "reports/latest.md").read_text()
    assert last_trace(repo)["deleted"] == 1


def test_run_commits_ledgered_deletion(repo, monkeypatch):
    cfg = make_kb(repo)
    commit_old_doc(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "delete_doc")
    monkeypatch.setenv("FAKE_CLAUDE_EXTRA", "Fact: docs/old.md => none | empty stub")
    assert runner.run(repo, cfg, "manual") == 0
    assert "docs/old.md" not in head_files(repo)
    latest = (state(repo) / "reports/latest.md").read_text()
    assert "## Deletion ledger\n\nFact: docs/old.md => none | empty stub" in latest
    assert last_trace(repo)["deleted"] == 1


def test_run_fails_on_move_into_discarded_file(repo, monkeypatch):
    cfg = make_kb(repo)
    commit_old_doc(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "move_doc")
    monkeypatch.setenv("FAKE_CLAUDE_EXTRA", "- Discard: `docs/kb/old.md`")
    assert runner.run(repo, cfg, "manual") == 1
    assert libraryan_commits(repo) == [] and "docs/old.md" in head_files(repo)
    assert (repo / "docs/old.md").exists() and not (repo / "docs/kb/old.md").exists()
    assert "deletion ledger: docs/old.md" in (state(repo) / "reports/latest.md").read_text()


@pytest.mark.parametrize("runtime", ["claude", "codex", "command"])
def test_reviewer_reject_fails_run(repo, runtime, monkeypatch):
    cfg = make_kb(repo, runtime=runtime, monkeypatch=monkeypatch)
    add_request(repo)
    monkeypatch.setenv("FAKE_REVIEW", "REJECT: docs/kb/index.md: no")
    monkeypatch.setenv("FAKE_RUNTIME_MODE", "reject")
    assert runner.run(repo, cfg, "manual") == 1
    assert libraryan_commits(repo) == [] and (repo / "docs/kb/index.md").read_text() == "# Index\n"
    assert "review: REJECT: docs/kb/index.md: no" in (state(repo) / "reports/latest.md").read_text()
    assert [c["role"] for c in last_trace(repo)["calls"]] == ["author", "reviewer"]


def test_reviewer_edit_rejected(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "review_edits")
    assert runner.run(repo, cfg, "manual") == 1
    assert libraryan_commits(repo) == [] and (repo / "docs/kb/index.md").read_text() == "# Index\n"
    assert "review: reviewer modified files: docs/kb/index.md" in (state(repo) / "reports/latest.md").read_text()
    assert (state(repo) / "last_failed").exists()  # only the reviewer edits the worktree: not transient


def test_new_doc_in_checkout_during_review_left_alone(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "review_newdoc")
    assert runner.run(repo, cfg, "manual") == 0
    assert libraryan_commits(repo) == ["docs(libraryan): manual run"]
    assert (repo / "docs/other.md").read_text() == "another agent\n"
    assert "docs/other.md" not in head_files(repo)


def test_request_written_during_review_survives(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "review_request")
    assert runner.run(repo, cfg, "manual") == 0
    assert libraryan_commits(repo) == ["docs(libraryan): manual run"]
    assert (repo / ".libraryan/requests/other-agent.md").read_text() == "during review\n"
    assert ".libraryan/requests/other-agent.md" not in head_files(repo)


def test_baseline_doc_edited_during_review_kept(repo, monkeypatch):
    cfg = make_kb(repo)
    (repo / "docs/wip.md").write_text("wip\n")
    add_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "review_baseline")
    assert runner.run(repo, cfg, "manual") == 0
    assert (repo / "docs/wip.md").read_text() == "wip\nmore wip\n"
    assert "docs/wip.md" not in head_files(repo)


def test_reviewer_failure_rejects(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "review_fail")
    assert runner.run(repo, cfg, "manual") == 1
    assert libraryan_commits(repo) == [] and (repo / "docs/kb/index.md").read_text() == "# Index\n"
    assert "review: reviewer call failed:" in (state(repo) / "reports/latest.md").read_text()
    assert (state(repo) / "last_failed").exists()


def test_review_disabled(repo):
    cfg = make_kb(repo)
    cfg["independent_review"] = False
    add_request(repo)
    assert runner.run(repo, cfg, "manual") == 0
    assert libraryan_commits(repo) == ["docs(libraryan): manual run"]
    assert not (state(repo) / "fake_review_argv").exists()
    assert [c["role"] for c in last_trace(repo)["calls"]] == ["author"]


def test_reviewer_args(repo):
    cfg = make_kb(repo)
    cfg["model"] = "m-author"
    add_request(repo)
    assert runner.run(repo, cfg, "manual") == 0
    a = json.loads((state(repo) / "fake_review_argv").read_text())
    assert a[a.index("--agent") + 1] == "libraryan-reviewer" and a[a.index("--max-budget-usd") + 1] == "2"
    assert a[a.index("--allowedTools") + 1] == claude.REVIEW_TOOLS
    assert a[a.index("--permission-mode") + 1] == "default" and a[a.index("--model") + 1] == "m-author"


def test_commit_failure_backs_off(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    monkeypatch.setattr(runner, "_commit", lambda *a: "git add/commit failed: hook rejected")
    assert runner.run(repo, cfg, "manual") == 1
    assert (state(repo) / "last_failed").read_text().strip() == git(repo, "rev-parse", "HEAD").strip()
    assert "hook rejected" in (state(repo) / "reports/latest.md").read_text()


def test_clean_health_run_skips_model(repo):
    cfg = make_kb(repo)
    state(repo).mkdir()
    (state(repo) / "last_processed").write_text(git(repo, "rev-parse", "HEAD"))
    assert runner.run(repo, cfg, "daily") == 0
    assert not (state(repo) / "fake_claude_ran").exists()
    t = last_trace(repo)
    assert t["outcome"] == "audited" and t["audit_findings"] == 0 and t["calls"] == []
    assert (state(repo) / "last_health_head").read_text().strip() == git(repo, "rev-parse", "HEAD").strip()
    assert (state(repo) / "last_health").exists()


def test_clean_health_run_not_capped(repo):
    cfg = make_kb(repo)
    prewrite(repo, cfg["max_runs_per_day"], outcome="nothing_changed", calls=[{"role": "author"}])
    (state(repo) / "last_processed").write_text(git(repo, "rev-parse", "HEAD"))
    runner.run(repo, cfg, "daily")
    assert last_trace(repo)["outcome"] == "audited"


def test_health_with_findings_calls_model_with_list(repo):
    cfg = make_kb(repo)
    give_finding(repo)
    state(repo).mkdir(exist_ok=True)
    (state(repo) / "last_processed").write_text(git(repo, "rev-parse", "HEAD"))
    assert runner.run(repo, cfg, "daily") == 0
    prompt = (state(repo) / "fake_claude_prompt").read_text()
    assert "Audit findings (verify each; fix the doc or flag it):" in prompt
    assert "missing-path README.md: src/gone.py" in prompt
    assert last_trace(repo)["audit_findings"] == 1


def test_audit_tool_allowed():
    assert "Bash(python3 .libraryan/bin/libraryan audit:*)" in claude.ALLOWED_TOOLS.split(",")


def test_cli_audit(repo):
    make_kb(repo)
    (repo / "README.md").write_text("# test\n`src/gone.py`\n")
    r = subprocess.run([str(repo / ".libraryan/bin/libraryan"), "audit"], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == "missing-path README.md: src/gone.py\n"


def test_missing_last_processed_still_calls_model(repo):
    cfg = make_kb(repo)  # clean KB, but no record of which commits were processed (fresh clone)
    head = git(repo, "rev-parse", "HEAD").strip()
    assert runner.run(repo, cfg, "daily") == 0
    assert (state(repo) / "fake_claude_ran").exists()
    assert (state(repo) / "last_processed").read_text().strip() == head


def test_promoted_setup_is_capped(repo, monkeypatch):
    cfg = make_kb(repo)
    cfg.update(max_runs_per_day=1, max_consecutive_failures=1)
    git(repo, "rm", "-q", "docs/kb/index.md")
    git(repo, "commit", "-m", "rm index", env={"LIBRARYAN": "1"})
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "exit1")
    for i in range(5):
        (repo / f"c{i}.py").write_text("x\n")
        git(repo, "add", f"c{i}.py")
        git(repo, "commit", "-m", f"c{i}")
        runner.run(repo, cfg, "commit")
    recs = [json.loads(l) for l in (state(repo) / "runs.jsonl").read_text().splitlines()]
    assert [r["outcome"] for r in recs] == ["failed"] + ["capped"] * 4
    assert sum(bool(r["calls"]) for r in recs) == 1
    runner.run(repo, cfg, "setup")  # an explicit setup ignores the caps
    assert last_trace(repo)["outcome"] == "failed" and last_trace(repo)["calls"]


def test_setup_review_budget_and_timeout(repo, monkeypatch):
    from libraryan import review
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "argv")
    cfg = make_kb(repo)
    assert config.DEFAULTS["max_usd_review_setup"] == 10
    git(repo, "rm", "-q", "docs/kb/index.md")
    git(repo, "commit", "-m", "rm index", env={"LIBRARYAN": "1"})
    runner.run(repo, cfg, "commit")  # promoted to setup
    a = json.loads((state(repo) / "fake_review_argv").read_text())
    assert a[a.index("--max-budget-usd") + 1] == "10"
    seen = record_timeouts(monkeypatch)
    for reason in ("setup", "commit"):
        review.run_review(repo, cfg, reason, ["a.md"], {"baseline": []}, [], runner._call_model, lambda r, c: {})
    assert seen == [cfg["setup_timeout_minutes"] * 60, cfg["review_timeout_minutes"] * 60]


@pytest.mark.parametrize("runtime", ["claude", "codex", "command"])
def test_is_error_fails_run(repo, runtime, monkeypatch):
    cfg = make_kb(repo, runtime=runtime, monkeypatch=monkeypatch)
    commit_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "is_error")
    monkeypatch.setenv("FAKE_RUNTIME_MODE", "error")
    assert runner.run(repo, cfg, "commit") == 1
    assert last_trace(repo)["outcome"] == "failed" and libraryan_commits(repo) == []
    assert not (state(repo) / "last_processed").exists() and not (state(repo) / "last_health").exists()
    assert f"{runtime} failed (exit " in (state(repo) / "reports/latest.md").read_text()


def test_reviewer_is_error_rejects(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "review_is_error")
    assert runner.run(repo, cfg, "manual") == 1
    assert libraryan_commits(repo) == []
    assert "review: reviewer call failed:" in (state(repo) / "reports/latest.md").read_text()


def health_run(repo, cfg):
    """A new code commit already processed by a commit run, then the nightly health run."""
    n = len(list(repo.glob("code*.py")))
    (repo / f"code{n}.py").write_text("x\n")
    git(repo, "add", f"code{n}.py")
    git(repo, "commit", "-qm", "code")
    (state(repo) / "last_processed").write_text(git(repo, "rev-parse", "HEAD"))
    (state(repo) / "fake_claude_ran").unlink(missing_ok=True)
    return runner.run(repo, cfg, "daily")


def test_recurring_findings_are_audited(repo):
    cfg = make_kb(repo)
    give_finding(repo)
    state(repo).mkdir(exist_ok=True)
    (state(repo) / "last_processed").write_text(git(repo, "rev-parse", "HEAD"))
    assert runner.run(repo, cfg, "daily") == 0
    assert (state(repo) / "fake_claude_ran").exists()  # first sight: the model verifies them
    assert health_run(repo, cfg) == 0
    assert not (state(repo) / "fake_claude_ran").exists()  # same findings: free
    t = last_trace(repo)
    assert t["outcome"] == "audited" and t["audit_findings"] == 1 and t["calls"] == []
    (repo / "README.md").write_text("# test\nRun `src/gone.py` and `src/new.py`.\n")
    git(repo, "commit", "-qam", "readme", env={"LIBRARYAN": "1"})
    assert health_run(repo, cfg) == 0
    assert (state(repo) / "fake_claude_ran").exists()  # a new finding: model run


def test_failed_health_run_does_not_store_findings(repo, monkeypatch):
    cfg = make_kb(repo)
    give_finding(repo)
    state(repo).mkdir(exist_ok=True)
    (state(repo) / "last_processed").write_text(git(repo, "rev-parse", "HEAD"))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "badnote")
    assert runner.run(repo, cfg, "daily") == 1
    assert not (state(repo) / "last_health_findings.json").exists()


def test_cap_keeps_failure_report(repo, monkeypatch):
    cfg = make_kb(repo)
    cfg["max_consecutive_failures"] = 1
    commit_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "badnote")
    assert runner.run(repo, cfg, "commit") == 1
    failure = (state(repo) / "reports/latest.md").read_text()
    reports = set((state(repo) / "reports").iterdir())
    for i in range(2):
        (repo / f"c{i}.py").write_text("x\n")  # new HEAD, so not backed off
        git(repo, "add", f"c{i}.py")
        git(repo, "commit", "-m", f"c{i}")
        runner.run(repo, cfg, "commit")
    assert last_trace(repo)["outcome"] == "capped"
    latest = (state(repo) / "reports/latest.md").read_text()
    line = "Daily cap reached: max_consecutive_failures; run `python3 .libraryan/bin/libraryan run` to override."
    assert latest.startswith(failure) and latest.count(line) == 1
    new = set((state(repo) / "reports").iterdir()) - reports
    assert new and any(line in p.read_text() for p in new)


def test_owned_doc_conflict_skips_review(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "real_doc_edit")
    assert runner.run(repo, cfg, "manual") == 1
    assert not (state(repo) / "fake_review_argv").exists()
    t = last_trace(repo)
    assert [c["role"] for c in t["calls"]] == ["author"] and t["transient"] is True
    assert (state(repo) / "reports/latest.md").read_text().count(runner.FOREIGN) == 1


def test_transient_failures_not_in_streak(repo):
    cfg = make_kb(repo)
    prewrite(repo, 2, outcome="failed", calls=[])
    prewrite(repo, 5, outcome="failed", calls=[], transient=True)
    assert runner.cap_hit(state(repo), cfg) is None
    prewrite(repo, 1, outcome="failed", calls=[])
    assert runner.cap_hit(state(repo), cfg) == "max_consecutive_failures"


def test_manual_run_not_capped_when_index_missing(repo):
    cfg = make_kb(repo)
    git(repo, "rm", "-q", "docs/kb/index.md")
    git(repo, "commit", "-m", "rm index", env={"LIBRARYAN": "1"})
    prewrite(repo, 24, outcome="committed", calls=[{"role": "author"}])
    runner.run(repo, cfg, "manual")
    assert (state(repo) / "fake_claude_ran").exists() and last_trace(repo)["outcome"] != "capped"


def test_transient_streak_cap(repo):
    cfg = make_kb(repo)
    assert cfg["max_consecutive_transient_failures"] == 10
    prewrite(repo, 9, outcome="failed", calls=[], transient=True)
    assert runner.cap_hit(state(repo), cfg) is None
    prewrite(repo, 1, outcome="aborted", calls=[], transient=True)
    assert runner.cap_hit(state(repo), cfg) == "max_consecutive_transient_failures"
    prewrite(repo, 1, outcome="noop", calls=[])  # skipped, streak stays
    assert runner.cap_hit(state(repo), cfg) == "max_consecutive_transient_failures"
    prewrite(repo, 1, outcome="committed", calls=[])  # a success resets both
    assert runner.cap_hit(state(repo), cfg) is None


def test_transient_failures_count_toward_total_streak(repo):
    cfg = make_kb(repo)
    prewrite(repo, 5, outcome="failed", calls=[], transient=True)
    prewrite(repo, 5, outcome="failed", calls=[])
    assert runner.cap_hit(state(repo), cfg) == "max_consecutive_failures"
    cfg["max_consecutive_failures"] = 99
    assert runner.cap_hit(state(repo), cfg) == "max_consecutive_transient_failures"


def test_reports_in_the_same_second_both_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_now", lambda: 1_800_000_000.0)
    st = runner._state(tmp_path)
    work = {"requests": [], "since": None, "commits": 0, "health": False}
    for out in ("first", "second", "third"):
        runner._report(st, "manual", work, [], [], out)
    archived = sorted(p.name for p in (st / "reports").iterdir() if p.name != "latest.md")
    assert len(archived) == 3
    assert sorted("first" in (st / "reports" / n).read_text() for n in archived) == [False, False, True]
    assert all(n.endswith(".md") for n in archived)


def test_call_model_disables_background_tasks_and_times_the_call(tmp_path):
    # A background subagent makes Claude Code's final JSON report only the last resumed segment
    # (seen: 1 turn / 14 s for a 5-minute run); the runner forbids background tasks and measures time itself.
    script = ("import json, os, time; time.sleep(0.3); "
              "print(json.dumps({'result': os.environ.get('CLAUDE_CODE_DISABLE_BACKGROUND_TASKS', ''), "
              "'duration_ms': 1, 'num_turns': 1}))")
    (tmp_path / "tool").write_text(f"#!/usr/bin/env python3\n{script}\n")
    (tmp_path / "tool").chmod(0o755)
    cfg = {**config.DEFAULTS, "runtime_bin": str(tmp_path / "tool")}
    text, problems, usage = runner._call_model("author", "prompt", tmp_path, cfg, "manual")
    assert (text, problems) == ("1", [])
    assert usage["duration_ms"] >= 300 and usage["runtime"] == "claude"


def no_worktree(repo):
    return not (repo / runner.WORKTREE).exists() and "/wt" not in git(repo, "worktree", "list")


def test_author_runs_in_worktree(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    git(repo, "add", "-A")
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "argv,env")
    assert runner.run(repo, cfg, "manual") == 0
    assert "updated by fake claude" in (repo / "docs/kb/index.md").read_text()
    assert (state(repo) / "fake_claude_cwd").read_text().endswith(runner.WORKTREE)
    assert no_worktree(repo)


def test_stray_code_edit_discarded_and_reported(repo, monkeypatch):
    cfg = make_kb(repo)
    (repo / "app.py").write_text("x = 1\n")
    (repo / "util.py").write_text("y = 1\n")
    git(repo, "add", "app.py", "util.py")
    git(repo, "commit", "-m", "code")
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "codeedit")
    assert runner.run(repo, cfg, "manual") == 0
    assert (repo / "app.py").read_text() == "x = 1\n" and (repo / "util.py").exists()
    assert git(repo, "status", "--porcelain") == ""
    report = (state(repo) / "reports/latest.md").read_text()
    assert "## Ignored (outside owned paths, discarded)\n- app.py\n- util.py" in report
    assert libraryan_commits(repo) and git(repo, "show", "--name-only", "--format=", "HEAD").split() == [
        "docs/kb/index.md"]


def test_staged_request_seen_and_removed(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    git(repo, "add", ".libraryan/requests")  # staged, never committed
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "gitrm")
    assert runner.run(repo, cfg, "manual") == 0
    assert not (repo / ".libraryan/requests/20261019-120000-x.md").exists()
    assert ".libraryan/requests/20261019-120000-x.md" not in git(repo, "ls-files")
    assert ".libraryan/requests/20261019-120000-x.md" in (state(repo) / "fake_claude_prompt").read_text()


def test_owned_doc_edited_in_real_checkout_during_run_is_transient(repo, monkeypatch):
    cfg = make_kb(repo)
    commit_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "real_doc_edit")
    assert runner.run(repo, cfg, "commit") == 1
    t = last_trace(repo)
    assert t["outcome"] == "failed" and t["transient"] and libraryan_commits(repo) == []
    assert (repo / "docs/kb/index.md").read_text() == "# Index\n- by another agent\n"  # kept, never restored
    assert not (state(repo) / "last_failed").exists()
    assert runner.find_work(repo, cfg, "commit")["requests"]  # next trigger retries at the same HEAD


def test_code_edit_in_real_checkout_during_run_does_not_fail(repo, monkeypatch):
    cfg = make_kb(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "commit")  # another agent commits src.py during the run
    assert runner.run(repo, cfg, "manual") == 0 and libraryan_commits(repo)


def test_stale_worktree_removed_at_start(repo):
    cfg = make_kb(repo)
    add_request(repo)
    git(repo, "add", "-A")
    git(repo, "worktree", "add", "--detach", runner.WORKTREE, "HEAD")
    (repo / runner.WORKTREE / "junk.md").write_text("x\n")
    assert runner.run(repo, cfg, "manual") == 0
    assert "junk.md" not in head_files(repo) and no_worktree(repo)


def test_worktree_removed_after_failure_and_interrupt(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "exit1")
    assert runner.run(repo, cfg, "manual") == 1
    assert no_worktree(repo)

    def boom(role, prompt, cwd, cfg, reason):
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "_call_model", boom)
    try:
        runner.run(repo, cfg, "manual")
        raise AssertionError("KeyboardInterrupt swallowed")
    except KeyboardInterrupt:
        pass
    assert no_worktree(repo)


def test_baseline_doc_never_copied_back(repo, monkeypatch):
    cfg = make_kb(repo)
    (repo / "docs/wip.md").write_text("wip\n")
    git(repo, "add", "docs/wip.md")
    git(repo, "commit", "-m", "wip", env={"LIBRARYAN": "1"})
    (repo / "docs/wip.md").write_text("user's wip\n")
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "edit_wip")
    assert runner.run(repo, cfg, "manual") == 0
    assert (repo / "docs/wip.md").read_text() == "user's wip\n"
    assert git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["docs/kb/index.md"]


def test_command_unset_is_a_problem_not_a_crash(repo):
    cfg = make_kb(repo)
    commit_request(repo)
    cfg["runtime"], cfg["runtime_command"] = "command", None
    assert runner.run(repo, cfg, "commit") == 1
    assert "runtime_command is not set" in (state(repo) / "reports/latest.md").read_text()


@pytest.mark.parametrize("runtime", ["gemini", "qwen", "copilot", "opencode", "cursor"])
def test_other_runtimes_run_commits(repo, runtime, monkeypatch):
    cfg = make_kb(repo, runtime=runtime, monkeypatch=monkeypatch)
    add_request(repo)
    assert runner.run(repo, cfg, "manual") == 0
    assert libraryan_commits(repo) == ["docs(libraryan): manual run"]


def test_gemini_empty_stdout_stderr_error_fails_run(repo, monkeypatch):
    cfg = make_kb(repo, runtime="gemini", monkeypatch=monkeypatch)
    commit_request(repo)
    monkeypatch.setenv("FAKE_RUNTIME_MODE", "error")
    assert runner.run(repo, cfg, "commit") == 1
    assert libraryan_commits(repo) == []
    assert "gemini failed (exit 1): fake runtime failed" in (state(repo) / "reports/latest.md").read_text()


def test_qwen_turn_cap_hit_fails_run(repo, monkeypatch):
    cfg = make_kb(repo, runtime="qwen", monkeypatch=monkeypatch)
    commit_request(repo)
    monkeypatch.setenv("FAKE_RUNTIME_MODE", "turn_cap")
    assert runner.run(repo, cfg, "commit") == 1
    assert last_trace(repo)["outcome"] == "failed" and libraryan_commits(repo) == []
    assert "qwen failed (exit 53)" in (state(repo) / "reports/latest.md").read_text()


def machinery_kb(repo, monkeypatch):
    cfg = make_kb(repo, runtime="command", monkeypatch=monkeypatch)
    (repo / ".claude/agents").mkdir(parents=True)
    (repo / ".claude/agents/libraryan-reviewer.md").write_text("# real reviewer\n")
    (repo / ".gitignore").write_text(".claude/settings.local.json\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "agents", env={"LIBRARYAN": "1"})
    commit_request(repo)
    monkeypatch.setenv("FAKE_RUNTIME_MODE", "machinery")
    return cfg


MACHINERY = [".claude/agents/libraryan-reviewer.md", ".libraryan/agents/libraryan-reviewer.md",
             ".libraryan/config.json", ".libraryan/hooks/pre-commit"]
IGNORED = [".claude/agents/libraryan-reviewer.md", ".claude/agents/x.md", *MACHINERY[1:]]


def test_author_cannot_commit_libraryan_machinery(repo, monkeypatch):
    cfg = machinery_kb(repo, monkeypatch)
    before = {p: (repo / p).read_bytes() for p in MACHINERY}
    assert runner.run(repo, cfg, "commit") == 0
    assert git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["docs/kb/index.md"]
    assert {p: (repo / p).read_bytes() for p in MACHINERY} == before
    assert git(repo, "status", "--porcelain", "--untracked-files=no") == ""
    report = (state(repo) / "reports/latest.md").read_text()
    assert "## Ignored (outside owned paths, discarded)\n" + "".join(f"- {p}\n" for p in IGNORED) in report
    assert ".claude/agents/x.md" not in git(repo, "ls-files") and not (repo / ".claude/agents/x.md").exists()


def test_reviewer_sees_head_instructions(repo, monkeypatch):
    cfg = machinery_kb(repo, monkeypatch)
    seen, call = [], runner._call_model

    def spy(role, prompt, cwd, cfg, reason):
        if role == "reviewer":
            seen.append({p: (cwd / p).read_bytes() for p in MACHINERY})
            assert not (cwd / ".claude/settings.local.json").exists() and not (cwd / ".claude/agents/x.md").exists()
        return call(role, prompt, cwd, cfg, reason)

    monkeypatch.setattr(runner, "_call_model", spy)
    assert runner.run(repo, cfg, "commit") == 0
    assert seen == [{p: git(repo, "show", f"HEAD~1:{p}").encode() for p in MACHINERY}]
    prompt = (state(repo) / "fake_review_prompt").read_text()
    head_text = git(repo, "show", "HEAD:.libraryan/agents/libraryan-reviewer.md").rstrip()
    assert prompt.startswith(head_text) and "TAMPERED" not in prompt


def test_author_branch_checkout_in_worktree_never_moves_the_branch(repo, monkeypatch):
    cfg = make_kb(repo)
    commit_request(repo)
    git(repo, "branch", "x", "HEAD~1")
    tip = git(repo, "rev-parse", "x")

    def switch(role, prompt, cwd, cfg, reason):
        if role == "author":
            git(cwd, "checkout", "-q", "x")
            with open(cwd / "docs/kb/index.md", "a") as f:
                f.write("- note\n")
        return "APPROVE" if role == "reviewer" else "SUMMARY ok\n", [], {}

    monkeypatch.setattr(runner, "_call_model", switch)
    assert runner.run(repo, cfg, "commit") == 0
    assert git(repo, "rev-parse", "x") == tip and libraryan_commits(repo)


def test_interrupt_during_commit_leaves_nothing_staged(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)

    def half_commit(root, paths, reason, output):
        git(root, "add", "-A", "--", *paths)
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "_commit", half_commit)
    with pytest.raises(KeyboardInterrupt):
        runner.run(repo, cfg, "manual")
    assert git(repo, "diff", "--cached", "--name-only") == ""
    assert (repo / "docs/kb/index.md").read_text() == "# Index\n"


def test_ignored_list_capped_in_report(tmp_path):
    work = {"requests": [], "since": None, "commits": 0, "health": False}
    (tmp_path / "reports").mkdir()
    runner._report(tmp_path, "manual", work, [], [], "", ignored=[f"src/f{i}.py" for i in range(250)])
    text = (tmp_path / "reports/latest.md").read_text()
    assert "- src/f199.py\n- 50 more in src/" in text and "f200" not in text


def test_ask_mode_proposes_then_approve_commits(repo, capsys, monkeypatch):
    cfg = {**make_kb(repo), "ask_before_commit": True}
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "gitrm")  # also deletes the processed request
    add_request(repo)
    git(repo, "add", "-A")
    before = libraryan_commits(repo)
    assert runner.run(repo, cfg, "manual") == 0
    assert libraryan_commits(repo) == before and (repo / "docs/kb/index.md").read_text() == "# Index\n"
    assert (repo / ".libraryan/requests/20261019-120000-x.md").exists()
    assert "--- deleted: .libraryan/requests/20261019-120000-x.md" in runner.review_text(repo)
    assert "libraryan approve" in (state(repo) / "reports/latest.md").read_text()
    assert last_trace(repo)["outcome"] == "proposed"
    assert "+- updated by fake claude" in runner.review_text(repo)
    (state(repo) / "fake_claude_ran").unlink()
    assert runner.run(repo, cfg, "manual") == 0  # waiting: no new paid run
    assert not (state(repo) / "fake_claude_ran").exists() and last_trace(repo)["outcome"] == "pending"
    assert "libraryan review" in capsys.readouterr().err
    assert runner.approve(repo, cfg) == 0
    assert libraryan_commits(repo) == ["docs(libraryan): manual run", *before]
    assert "updated by fake claude" in (repo / "docs/kb/index.md").read_text()
    assert not (repo / ".libraryan/requests/20261019-120000-x.md").exists()
    assert runner.proposal(repo) is None and git(repo, "status", "--porcelain") == ""
    assert (state(repo) / "last_processed").exists()


def test_unreadable_proposal_can_be_rejected(repo):
    make_kb(repo)
    (repo / runner.PROPOSAL / "files").mkdir(parents=True)  # e.g. a hand-damaged proposal: no proposal.json
    assert runner.reject(repo) == 0 and not (repo / runner.PROPOSAL).exists()


def test_reject_discards_proposal(repo):
    cfg = {**make_kb(repo), "ask_before_commit": True}
    add_request(repo)
    git(repo, "add", "-A")
    runner.run(repo, cfg, "manual")
    assert not (state(repo) / "last_processed").exists()  # processed only once approved
    assert runner.reject(repo) == 0
    assert runner.proposal(repo) is None and (repo / "docs/kb/index.md").read_text() == "# Index\n"
    assert not (state(repo) / "last_processed").exists()
    assert runner.review_text(repo) == "No proposal waiting." and runner.approve(repo, cfg) == 1


def test_approve_refuses_when_file_changed_since(repo):
    cfg = {**make_kb(repo), "ask_before_commit": True}
    add_request(repo)
    git(repo, "add", "-A")
    runner.run(repo, cfg, "manual")
    (repo / "docs/kb/index.md").write_text("# Index\nmine\n")
    assert runner.approve(repo, cfg) == 1
    assert (repo / "docs/kb/index.md").read_text() == "# Index\nmine\n" and runner.proposal(repo)


def test_tool_error_message_reaches_the_problem(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "is_error")
    monkeypatch.setenv("FAKE_CLAUDE_EXTRA", "Invalid API key")
    assert runner.run(repo, cfg, "manual") == 1
    assert any("claude failed" in p and "SUMMARY ok" in p for p in runner.problems(repo))


def test_progress_line_on_a_terminal(repo, monkeypatch, capsys):
    cfg = make_kb(repo)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    assert runner.run(repo, cfg, "manual") == 0
    err = capsys.readouterr().err
    assert "Writing the docs · 0:0" in err and "✓ Writing the docs" in err and "changed so far" in err
    assert "%" not in err


def test_no_progress_line_without_a_terminal(repo, capsys):
    assert runner.run(repo, make_kb(repo), "manual") == 0
    assert "Writing the docs" not in capsys.readouterr().err
