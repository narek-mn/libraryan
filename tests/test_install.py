import json
import os
import subprocess
from pathlib import Path

import pytest

from libraryan import config, install, runner

SRC = Path(__file__).resolve().parent.parent
FAKE = Path(__file__).resolve().parent / "fake_claude.py"
START, END = "<!-- libraryan:start -->", "<!-- libraryan:end -->"


def git(repo, *args, env=None, check=True):
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                       env={**os.environ, **(env or {})})
    if check and r.returncode:
        raise AssertionError(r.stderr)
    return r


def subject(repo):
    return git(repo, "log", "-1", "--format=%s").stdout.strip()


def settings(repo):
    return json.loads((repo / ".claude/settings.json").read_text())


def test_init_installs_and_commits(repo, fake_crontab):
    assert install.init(repo, SRC, run_setup=False) == 0
    for p in (".libraryan/bin/libraryan", ".libraryan/hooks/pre-commit", ".libraryan/libraryan/cli.py",
              ".libraryan/config.json", ".libraryan/requests/.gitkeep", ".libraryan/templates/STYLE.md", ".libraryan/templates/agents-block.md",
              ".claude/agents/libraryan.md", ".claude/agents/libraryan-reviewer.md",
              ".claude/skills/libraryan-request/SKILL.md"):
        assert (repo / p).is_file(), p
    assert os.access(repo / ".libraryan/hooks/pre-commit", os.X_OK)
    assert (repo / ".libraryan/.gitignore").read_text().split() == ["state/", "__pycache__/"]
    assert git(repo, "config", "core.hooksPath").stdout.strip() == ".libraryan/hooks"
    assert subject(repo) == "docs(libraryan): install"
    assert git(repo, "status", "--porcelain").stdout == ""
    agents = (repo / "AGENTS.md").read_text()
    assert START in agents and END in agents
    assert "@AGENTS.md" in (repo / "CLAUDE.md").read_text().splitlines()
    cfg = config.load(repo)
    assert cfg["source_path"] == str(SRC) and cfg["default_branch"] == "main" and cfg["runner_host"]
    assert f"# libraryan:{repo}" in fake_crontab.read_text()


def test_init_is_idempotent(repo, fake_crontab):
    assert install.init(repo, SRC, run_setup=False) == 0
    assert install.init(repo, SRC, run_setup=False) == 0
    s = settings(repo)
    assert len(s["hooks"]["PreToolUse"]) == 1 and len(s["hooks"]["SessionStart"]) == 1
    assert (repo / "AGENTS.md").read_text().count(START) == 1
    assert (repo / "CLAUDE.md").read_text().splitlines().count("@AGENTS.md") == 1
    assert fake_crontab.read_text().count("# libraryan:") == 1


def test_crontab_replaces_tagged_line_keeps_others(repo, fake_crontab):
    fake_crontab.write_text(f"5 * * * * other\n1 1 * * * old # libraryan:{repo}\n")
    install.init(repo, SRC, run_setup=False)
    lines = fake_crontab.read_text().splitlines()
    assert lines[0] == "5 * * * * other"
    assert lines[1] == (f"0 3 * * * cd '{repo}' && python3 .libraryan/bin/libraryan run --reason daily "
                        f"# libraryan:{repo}")
    install.uninstall(repo)
    assert fake_crontab.read_text().splitlines() == ["5 * * * * other"]


def test_settings_merge_preserves_existing(repo):
    mine = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}
    (repo / ".claude").mkdir()
    (repo / ".claude/settings.json").write_text(json.dumps({"model": "x", "hooks": {"PreToolUse": [mine]}}))
    git(repo, "add", ".claude")
    git(repo, "commit", "-m", "settings")
    install.init(repo, SRC, run_setup=False)
    s = settings(repo)
    assert s["model"] == "x" and mine in s["hooks"]["PreToolUse"] and len(s["hooks"]["PreToolUse"]) == 2
    install.uninstall(repo)
    assert settings(repo) == {"model": "x", "hooks": {"PreToolUse": [mine]}}


def test_merge_and_strip_settings_roundtrip():
    s = install.merge_settings({})
    assert install.merge_settings(s) == s
    assert install.strip_settings(s) == {}


def test_uninstall_deletes_settings_only_if_created(repo):
    install.init(repo, SRC, run_setup=False)
    install.uninstall(repo)
    assert not (repo / ".claude/settings.json").exists()


def test_uninstall_keeps_preexisting_empty_settings(repo):
    (repo / ".claude").mkdir()
    (repo / ".claude/settings.json").write_text("{}\n")
    git(repo, "add", ".claude")
    git(repo, "commit", "-m", "settings")
    install.init(repo, SRC, run_setup=False)
    install.uninstall(repo)
    assert settings(repo) == {}


def test_init_refuses_dirty_docs(repo):
    (repo / "README.md").write_text("# dirty\n")
    assert install.init(repo, SRC, run_setup=False) != 0
    assert not (repo / ".libraryan").exists()


def test_init_refuses_off_default_branch(repo):
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    git(repo, "checkout", "-qb", "feature")
    assert install.init(repo, SRC, run_setup=False) != 0
    assert not (repo / ".libraryan").exists()


def test_init_without_claude_needs_no_setup(repo, monkeypatch):
    monkeypatch.setattr(install.shutil, "which", lambda name: None)
    assert install.init(repo, SRC) != 0
    assert not (repo / ".libraryan").exists()
    assert install.init(repo, SRC, run_setup=False) == 0
    assert config.load(repo)["claude_bin"] == "claude"


def test_init_then_doc_edit_blocked(repo):
    install.init(repo, SRC, run_setup=False)
    (repo / "README.md").write_text("# edited\n")
    git(repo, "add", "README.md")
    r = git(repo, "commit", "-m", "edit", check=False, env={"LIBRARYAN": ""})
    assert r.returncode != 0 and "Libraryan" in r.stderr


def test_uninstall_restores(repo):
    install.init(repo, SRC, run_setup=False)
    assert install.uninstall(repo) == 0
    assert not (repo / ".libraryan").exists()
    assert not (repo / ".claude/agents/libraryan.md").exists()
    assert not (repo / ".claude/skills/libraryan-request").exists()
    assert git(repo, "config", "core.hooksPath", check=False).stdout.strip() == ""
    assert START not in (repo / "AGENTS.md").read_text()
    assert subject(repo) == "docs(libraryan): uninstall"
    assert git(repo, "status", "--porcelain").stdout == ""
    (repo / "README.md").write_text("# edited\n")
    git(repo, "commit", "-am", "edit")


def test_agents_md_block_inserted_and_removed_keeping_rest(repo):
    (repo / "AGENTS.md").write_text("# Rules\n\n- be nice\n")
    git(repo, "add", "AGENTS.md")
    git(repo, "commit", "-m", "agents")
    install.init(repo, SRC, run_setup=False)
    text = (repo / "AGENTS.md").read_text()
    assert text.startswith("# Rules\n\n- be nice\n") and START in text
    install.uninstall(repo)
    assert (repo / "AGENTS.md").read_text() == "# Rules\n\n- be nice\n"


def test_upgrade_keeps_existing_block_and_adds_new_defaults(repo, monkeypatch):
    install.init(repo, SRC, run_setup=False)
    agents = (repo / "AGENTS.md").read_text().replace("- personal notes or to-dos.",
                                                       "- personal notes or to-dos.\n- typo fixes.")
    (repo / "AGENTS.md").write_text(agents)
    with open(repo / ".libraryan/libraryan/cli.py", "a") as f:
        f.write("# stale\n")
    (repo / ".libraryan/libraryan/gone.py").write_text("# removed upstream\n")
    cfg = json.loads((repo / ".libraryan/config.json").read_text())
    del cfg["debounce_minutes"]
    cfg["kb_root"] = "kb"
    (repo / ".libraryan/config.json").write_text(json.dumps(cfg))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "tweak", env={"LIBRARYAN": "1"})
    assert install.upgrade(repo, SRC) == 0
    assert subject(repo) == "docs(libraryan): upgrade"
    assert (repo / "AGENTS.md").read_text() == agents
    assert (repo / ".libraryan/libraryan/cli.py").read_text() == (SRC / "libraryan/cli.py").read_text()
    assert not (repo / ".libraryan/libraryan/gone.py").exists()
    cfg = config.load(repo)
    assert cfg["kb_root"] == "kb"
    assert json.loads((repo / ".libraryan/config.json").read_text())["debounce_minutes"] == 10
    assert git(repo, "status", "--porcelain").stdout == ""


def test_init_ignores_own_hooks_path_and_chains_foreign(repo):
    git(repo, "config", "core.hooksPath", ".libraryan/hooks")
    install.init(repo, SRC, run_setup=False)
    assert config.load(repo)["chain_hooks_path"] is None


def test_uninstall_restores_chained_hooks_path(repo):
    git(repo, "config", "core.hooksPath", ".githooks")
    install.init(repo, SRC, run_setup=False)
    assert config.load(repo)["chain_hooks_path"] == ".githooks"
    install.uninstall(repo)
    assert git(repo, "config", "core.hooksPath").stdout.strip() == ".githooks"


def test_install_commit_leaves_other_dirty_files(repo):
    (repo / "src.py").write_text("x = 1\n")
    install.init(repo, SRC, run_setup=False)
    assert "src.py" not in git(repo, "show", "--name-only", "--format=", "HEAD").stdout
    assert git(repo, "status", "--porcelain").stdout.strip() == "?? src.py"


def test_init_with_setup_runs_runner_with_installer_files(repo, monkeypatch):
    (repo / "docs/kb").mkdir(parents=True)
    (repo / "docs/kb/index.md").write_text("# Index\n")
    (repo / "src.py").write_text("x = 1\n")  # someone else's work in progress
    git(repo, "add", "docs")
    git(repo, "commit", "-m", "kb")
    monkeypatch.setattr(install.shutil, "which", lambda name: str(FAKE) if name == "claude" else None)
    assert install.init(repo, SRC) == 0
    assert subject(repo) == "docs(libraryan): setup run"
    committed = git(repo, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert "AGENTS.md" in committed and ".libraryan/config.json" in committed and "docs/kb/index.md" in committed
    assert "src.py" not in committed
    prompt = (repo / ".libraryan/state/fake_claude_prompt").read_text()
    installer = prompt.split("Installer files")[1].split("Baseline")[0]
    baseline = prompt.split("Baseline")[1]
    assert "- AGENTS.md" in installer and "- CLAUDE.md" in installer
    assert "- AGENTS.md" not in baseline and "- src.py" in baseline
    assert git(repo, "status", "--porcelain").stdout.strip() == "?? src.py"


def test_build_prompt_lists_installer_files():
    work = {"requests": [], "since": None, "commits": 0, "health": True, "baseline": [], "extra": ["AGENTS.md"]}
    p = runner.build_prompt("setup", work, {})
    assert "Installer files (written by setup" in p and "- AGENTS.md" in p


def test_build_prompt_caps_baseline():
    base = [f"a/{i}.py" for i in range(250)] + [f"b/{i}.py" for i in range(30)] + ["top.txt"]
    work = {"requests": [], "since": None, "commits": 0, "health": False, "baseline": sorted(base)}
    p = runner.build_prompt("manual", work, {})
    listed = [l for l in p.splitlines() if l.startswith("- a/") or l.startswith("- b/") or l == "- top.txt"]
    assert len(listed) == 200
    assert "- 50 more in a/" in p and "- 30 more in b/" in p and "- 1 more in (root)" in p


def test_runner_never_commits_baseline_paths(repo, monkeypatch):
    from helpers import install_runtime
    install_runtime(repo)
    (repo / ".libraryan/.gitignore").write_text("state/\n")
    (repo / "docs/kb").mkdir(parents=True)
    (repo / "docs/kb/index.md").write_text("# Index\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "kb", env={"LIBRARYAN": "1"})
    (repo / "docs/kb/index.md").write_text("# Index\n- other agent wip\n")  # baseline, fake claude edits it
    cfg = {**config.load(repo), "claude_bin": str(FAKE)}
    assert runner.run(repo, cfg, "manual") == 0
    assert subject(repo) == "kb"  # the only change was to a baseline path: nothing committed
    assert "other agent wip" in (repo / "docs/kb/index.md").read_text()


def test_source_cli_usage(repo):
    r = subprocess.run(["python3", str(SRC / "libraryan.py"), "--help"], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0 and "init" in r.stdout and "uninstall" in r.stdout


def test_source_cli_init_no_setup(repo, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("libraryan_main", SRC / "libraryan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.chdir(repo)
    assert mod.main(["init", "--no-setup"]) == 0
    assert subject(repo) == "docs(libraryan): install"
    assert mod.main(["uninstall"]) == 0
    assert subject(repo) == "docs(libraryan): uninstall"


def test_vendored_cli_uninstall(repo):
    install.init(repo, SRC, run_setup=False)
    from libraryan import cli
    old = Path.cwd()
    os.chdir(repo)
    try:
        assert cli.main(["uninstall"]) == 0
    finally:
        os.chdir(old)
    assert not (repo / ".libraryan").exists()


def test_vendored_cli_upgrade_uses_source(repo):
    install.init(repo, SRC, run_setup=False)
    (repo / ".libraryan/libraryan/gone.py").write_text("# removed upstream\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "stale", env={"LIBRARYAN": "1"})
    r = subprocess.run(["python3", ".libraryan/bin/libraryan", "upgrade"], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert subject(repo) == "docs(libraryan): upgrade"
    assert not (repo / ".libraryan/libraryan/gone.py").exists()
