import fcntl
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
    assert "deferred" in (state(repo) / "runs.log").read_text()
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
    assert "deferred" in (state(repo) / "runs.log").read_text()


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
