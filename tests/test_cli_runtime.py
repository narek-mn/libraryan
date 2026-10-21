import json
import os
import subprocess
from pathlib import Path

from helpers import fake_tools
from libraryan import cli, config, install, runner, runtimes
from test_runner import FAKE, add_request, git, last_trace, make_kb

SRC = Path(install.__file__).resolve().parent


def test_pick_follows_preference_order(monkeypatch, tmp_path):
    fake_tools(monkeypatch, tmp_path, "agent", "gemini")  # cursor's binary is `agent`
    assert runtimes.pick() == "gemini"


def test_init_refuses_without_any_runtime(repo, monkeypatch, tmp_path, capsys):
    fake_tools(monkeypatch, tmp_path)
    assert install.init(repo, SRC) == 1
    err = capsys.readouterr().err
    assert "no supported agent CLI found. Install one of:" in err and runtimes.get("codex").INSTALL in err
    assert not (repo / ".libraryan").exists()


def test_init_picks_and_runtime_flag_overrides(repo, monkeypatch, tmp_path, capsys):
    fake_tools(monkeypatch, tmp_path, "codex", "gemini")
    assert install.init(repo, SRC, run_setup=False) == 0
    cfg = config.load(repo)
    assert cfg["runtime"] == "codex" and cfg["runtime_bin"] == str(tmp_path.parent / (tmp_path.name + "-fakebin") / "codex")
    out = capsys.readouterr().out
    assert "codex codex 1.2.3" in out and runtimes.get("codex").AUTH in out
    assert install.init(repo, SRC, run_setup=False, runtime="gemini") == 0
    cfg = config.load(repo)
    assert cfg["runtime"] == "gemini" and cfg["runtime_bin"] == str(tmp_path.parent / (tmp_path.name + "-fakebin") / "gemini")


def test_init_runtime_command_needs_config(repo, monkeypatch, tmp_path, capsys):
    fake_tools(monkeypatch, tmp_path)
    assert install.init(repo, SRC, run_setup=False, runtime="command") == 1
    assert "runtime_command" in capsys.readouterr().err


def installed(repo, monkeypatch, tmp_path, *tools):
    fake_tools(monkeypatch, tmp_path, *tools)
    assert install.init(repo, SRC, run_setup=False, runtime="claude") == 0
    monkeypatch.chdir(repo)


def test_runtime_command_lists_found(repo, monkeypatch, tmp_path, capsys):
    installed(repo, monkeypatch, tmp_path, "claude", "qwen")
    capsys.readouterr()
    assert cli.main(["runtime"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"writer:   claude claude 1.2.3 ({tmp_path.parent}/{tmp_path.name}-fakebin/claude)",
        "reviewer: claude (same as writer)",
        "found:    claude claude 1.2.3, qwen qwen 1.2.3"]


def test_runtime_switch_commits_config(repo, monkeypatch, tmp_path, capsys):
    installed(repo, monkeypatch, tmp_path, "claude", "codex")
    assert cli.main(["runtime", "codex", "--yes"]) == 0
    cfg = config.load(repo)
    assert cfg["runtime"] == "codex" and cfg["runtime_bin"] == str(tmp_path.parent / (tmp_path.name + "-fakebin") / "codex")
    assert git(repo, "log", "-1", "--format=%s").strip() == "docs(libraryan): runtime codex"
    assert git(repo, "status", "--porcelain") == ""
    capsys.readouterr()
    assert cli.main(["runtime", "gemini", "--yes"]) == 1
    assert "gemini not found on PATH; install it first: " + runtimes.get("gemini").INSTALL in capsys.readouterr().err
    assert cli.main(["runtime", "bogus", "--yes"]) == 1 and cli.main(["runtime", "command", "--yes"]) == 1


def test_runtime_switch_reviewer_only(repo, monkeypatch, tmp_path):
    installed(repo, monkeypatch, tmp_path, "claude", "codex")
    assert cli.main(["runtime", "codex", "--reviewer", "--yes"]) == 0
    cfg = config.load(repo)
    assert (cfg["runtime"], cfg["reviewer_runtime"]) == ("claude", "codex")
    assert cfg["reviewer_runtime_bin"] == str(tmp_path.parent / (tmp_path.name + "-fakebin") / "codex")
    assert cli.main(["runtime", "claude", "--reviewer", "--yes"]) == 0  # same as the writer: cleared
    cfg = config.load(repo)
    assert cfg["reviewer_runtime"] is None and cfg["reviewer_runtime_bin"] is None


def test_upgrade_from_02_keeps_claude(repo):
    make_kb(repo)
    raw = json.loads((repo / config.CONFIG_PATH).read_text())
    for k in ("runtime", "runtime_bin"):
        raw.pop(k, None)
    (repo / config.CONFIG_PATH).write_text(json.dumps({**raw, "claude_bin": str(FAKE), "installed_version": "0.2.0"}))
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "old install", env={"LIBRARYAN": "1"})
    assert install.upgrade(repo, SRC) == 0
    cfg = config.load(repo)
    assert cfg["runtime"] == "claude" and cfg["runtime_bin"] == str(FAKE)
    add_request(repo)
    runner._runtime_version.cache_clear()
    runner.run(repo, cfg, "manual")
    assert (repo / ".libraryan/state/fake_claude_ran").exists()


def test_trace_records_runtime_version(repo):
    cfg = make_kb(repo)
    add_request(repo)
    runner.run(repo, cfg, "manual")
    assert [c["runtime_version"] for c in last_trace(repo)["calls"]] == ["9.9.9 (Fake)"] * 2


def test_runtime_switch_refuses_when_not_installed(repo, monkeypatch, tmp_path, capsys):
    fake_tools(monkeypatch, tmp_path, "codex")
    monkeypatch.chdir(repo)
    assert cli.main(["runtime", "codex", "--yes"]) == 1
    assert "not installed here; run: libraryan init" in capsys.readouterr().err


def test_runtime_switch_refuses_dirty_tree(repo, monkeypatch, tmp_path, capsys):
    installed(repo, monkeypatch, tmp_path, "claude", "codex")
    (repo / ".libraryan/requests").mkdir(exist_ok=True)
    (repo / ".libraryan/requests/x.md").write_text("pending\n")
    before = (repo / config.CONFIG_PATH).read_text()
    assert cli.main(["runtime", "codex", "--yes"]) == 1
    assert "commit or stash" in capsys.readouterr().err
    assert (repo / config.CONFIG_PATH).read_text() == before


def test_reinit_keeps_chosen_runtime(repo, monkeypatch, tmp_path):
    fake_tools(monkeypatch, tmp_path, "codex", "gemini")
    assert install.init(repo, SRC, run_setup=False, runtime="gemini") == 0
    assert install.init(repo, SRC, run_setup=False) == 0  # codex would win auto-detection
    cfg = config.load(repo)
    assert cfg["runtime"] == "gemini" and cfg["runtime_bin"].endswith("-fakebin/gemini")


def test_init_refuses_explicit_runtime_not_installed(repo, monkeypatch, tmp_path, capsys):
    fake_tools(monkeypatch, tmp_path, "codex")
    assert install.init(repo, SRC, runtime="gemini") == 1
    assert "gemini not found on PATH; install it first" in capsys.readouterr().err
    assert not (repo / ".libraryan").exists()


def test_runtime_shows_custom_command(repo, monkeypatch, tmp_path, capsys):
    installed(repo, monkeypatch, tmp_path, "claude")
    cfg = config.load(repo)
    cfg.update(runtime="command", runtime_command=["aider", "--message", "{prompt}"])
    config.save(repo, cfg)
    capsys.readouterr()
    assert cli.main(["runtime"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "writer:   command custom command (aider)"


def test_failed_runtime_switch_leaves_nothing_staged(repo, monkeypatch, tmp_path):
    installed(repo, monkeypatch, tmp_path, "claude", "codex")

    def fail(root, what, cfg):
        git(root, "add", "-A", "--", config.CONFIG_PATH)
        return 1

    monkeypatch.setattr(install, "_commit", fail)
    assert cli.main(["runtime", "codex", "--yes"]) == 1
    assert git(repo, "status", "--porcelain") == "" and config.load(repo)["runtime"] == "claude"


def test_runtime_switch_asks_and_no_changes_nothing(repo, monkeypatch, tmp_path, capsys):
    installed(repo, monkeypatch, tmp_path, "claude", "codex")
    head, before = git(repo, "rev-parse", "HEAD"), (repo / config.CONFIG_PATH).read_text()
    assert cli.main(["runtime", "codex"]) == 1  # no terminal to ask in
    monkeypatch.setattr(cli, "_confirm", lambda files: files == [config.CONFIG_PATH] and False)
    assert cli.main(["runtime", "codex"]) == 1
    assert git(repo, "rev-parse", "HEAD") == head and (repo / config.CONFIG_PATH).read_text() == before
    assert git(repo, "status", "--porcelain") == ""
    assert "runtime codex cancelled" in capsys.readouterr().err
