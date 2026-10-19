import fcntl
import json
import os
import subprocess
import time
from pathlib import Path

from helpers import install_runtime
from libraryan import config, runner

FAKE = Path(__file__).resolve().parent / "fake_claude.py"


def git(repo, *args, env=None):
    e = {**os.environ, **(env or {})}
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, env=e).stdout


def make_kb(repo, ignore_state=True):
    install_runtime(repo)
    if ignore_state:
        (repo / ".libraryan/.gitignore").write_text("state/\n")
    (repo / "docs/kb").mkdir(parents=True)
    (repo / "docs/kb/index.md").write_text("# Index\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "kb", env={"LIBRARYAN": "1"})
    cfg = config.load(repo)
    cfg["claude_bin"] = str(FAKE)
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


def test_run_commits_changes(repo):
    cfg = make_kb(repo)
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


def test_cli_run_end_to_end(repo):
    cfg = make_kb(repo)
    config.save(repo, cfg)
    r = subprocess.run([str(repo / ".libraryan/bin/libraryan"), "run", "--reason", "daily"], cwd=repo,
                       capture_output=True, text=True)
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


def test_stray_code_edits_fail_run_and_nothing_left_staged(repo, monkeypatch):
    cfg = make_kb(repo)
    (repo / "app.py").write_text("x = 1\n")
    (repo / "util.py").write_text("y = 1\n")
    git(repo, "add", "app.py", "util.py")
    git(repo, "commit", "-m", "code")
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "codeedit")
    assert runner.run(repo, cfg, "manual") == 1
    assert libraryan_commits(repo) == []
    assert git(repo, "diff", "--cached", "--name-only") == ""  # util.py deletion not left staged
    assert (repo / "docs/kb/index.md").read_text() == "# Index\n"
    assert (repo / "app.py").read_text() == "x = 2\n"  # foreign paths are reported, not restored
    report = (state(repo) / "reports/latest.md").read_text()
    assert "non-owned paths changed" in report and "app.py" in report and "util.py" in report


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


def test_foreign_edit_only_failure_does_not_back_off(repo, monkeypatch):
    cfg = make_kb(repo)
    (repo / "util.py").write_text("y = 1\n")
    git(repo, "add", "util.py")
    git(repo, "commit", "-m", "code")
    commit_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "codeedit")
    assert runner.run(repo, cfg, "commit") == 1
    assert not (state(repo) / "last_failed").exists()
    assert runner.find_work(repo, cfg, "commit")["requests"]  # next trigger retries at the same HEAD


def test_foreign_edit_plus_lint_failure_still_backs_off(repo, monkeypatch):
    cfg = make_kb(repo)
    (repo / "util.py").write_text("y = 1\n")
    git(repo, "add", "util.py")
    git(repo, "commit", "-m", "code")
    commit_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "codeedit,badnote")
    assert runner.run(repo, cfg, "commit") == 1
    assert (state(repo) / "last_failed").exists()


def test_other_agents_staged_new_request_stays_staged(repo, monkeypatch):
    cfg = make_kb(repo)
    commit_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "stage_request")
    assert runner.run(repo, cfg, "commit") == 0
    assert ".libraryan/requests/other-agent.md" in git(repo, "diff", "--cached", "--name-only")


def _alive(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0] != "Z"
    except FileNotFoundError:
        return False


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


def test_setup_uses_setup_timeout(repo, monkeypatch):
    cfg = make_kb(repo)
    seen = []
    monkeypatch.setattr(runner, "_call_model", lambda cmd, root, timeout: seen.append(timeout) or ("", [], {}))
    runner.run(repo, cfg, "setup")
    add_request(repo)
    git(repo, "add", ".libraryan/requests")
    runner.run(repo, cfg, "manual")
    assert seen == [cfg["setup_timeout_minutes"] * 60, cfg["run_timeout_minutes"] * 60]
    assert config.DEFAULTS["setup_timeout_minutes"] == 120


def test_interrupt_restores_and_reports(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)

    def half_done(cmd, root, timeout):
        with open(repo / "docs/kb/index.md", "a") as f:
            f.write("half\n")
        git(repo, "rm", "-q", "--", "README.md")
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
    (repo / "docs/kb").mkdir(parents=True)  # fake claude writes into it
    assert runner.run(repo, cfg, "commit") == 0
    assert "Reason: setup" in (state(repo) / "fake_claude_prompt").read_text()
    assert libraryan_commits(repo) == ["docs(libraryan): setup run"]


def test_daily_health_skipped_on_idle_repo(repo):
    cfg = make_kb(repo)
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
    assert "- Cost: $0.01 (3 turns)" in (state(repo) / "reports/latest.md").read_text()
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

    def boom(cmd, root, timeout):
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "_call_model", boom)
    try:
        runner.run(repo, cfg, "manual")
    except KeyboardInterrupt:
        pass
    assert last_trace(repo)["outcome"] == "aborted"


def test_nojson_output_still_works(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "nojson")
    assert runner.run(repo, cfg, "manual") == 0
    t = last_trace(repo)
    assert t["outcome"] == "committed" and "cost_usd" not in t["calls"][0]
    assert "SUMMARY ok" in git(repo, "log", "-1", "--format=%b")


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
    add_request(repo)
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
    add_request(repo)
    prewrite(repo, 24, outcome="committed", calls=[{"role": "author"}])
    assert runner.run(repo, cfg, "commit") == 0
    assert not (state(repo) / "fake_claude_ran").exists()
    t = last_trace(repo)
    assert t["outcome"] == "capped" and t["cap"] == "max_runs_per_day"


def test_cap_consecutive_failures(repo):
    cfg = make_kb(repo)
    add_request(repo)
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
    add_request(repo)
    prewrite(repo, 3, outcome="aborted", calls=[])
    runner.run(repo, cfg, "commit")
    line = "Daily cap reached: max_consecutive_failures; run `libraryan run` to override."
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
