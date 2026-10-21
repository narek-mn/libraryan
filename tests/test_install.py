import json
import os
import subprocess
from pathlib import Path

import pytest

from helpers import fake_tools
from libraryan import __version__, config, install, runner

SRC = Path(install.__file__).resolve().parent  # the package dir: package data lives in it
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
              ".claude/agents/libraryan.md", ".claude/agents/libraryan-reviewer.md", ".libraryan/agents/libraryan.md", ".libraryan/agents/libraryan-reviewer.md",
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
    assert not (repo / ".libraryan/libraryan/_runtime").exists()
    assert not (repo / ".libraryan/libraryan/_templates").exists()
    cfg = config.load(repo)
    assert "source_path" not in cfg and cfg["default_branch"] == "main" and cfg["runner_host"]
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


def test_merge_and_strip_hooks_roundtrip():
    for hooks in install.HOOK_FILES.values():
        s = install.merge_hooks({}, hooks)
        assert install.merge_hooks(s, hooks) == s
        assert install.strip_hooks(s) == {}


def test_init_writes_every_guard_file(repo):
    assert install.init(repo, SRC, run_setup=False) == 0
    load = lambda p: json.loads((repo / p).read_text())
    assert load(".claude/settings.json")["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == install.GUARD_CMD
    codex = load(".codex/hooks.json")["hooks"]
    assert codex["PreToolUse"][0]["matcher"] == "Edit|Write|apply_patch|Bash"
    assert codex["SessionStart"][0]["hooks"][0]["command"] == install.ENSURE_CMD
    gemini = load(".gemini/settings.json")
    assert gemini["hooks"]["BeforeTool"][0]["matcher"] == "write_file|replace" and "SessionStart" in gemini["hooks"]
    assert gemini["context"]["fileName"] == ["AGENTS.md", "GEMINI.md"]
    assert load(".qwen/settings.json")["hooks"]["PreToolUse"][0]["matcher"] == "write_file|edit|Write|Edit"
    assert load(".cursor/hooks.json") == {"version": 1, "hooks": {
        "preToolUse": [{"command": install.GUARD_CMD, "matcher": "Write|Edit|Delete"}],
        "sessionStart": [{"command": install.ENSURE_CMD}]}}
    js = (repo / ".opencode/plugins/libraryan.js").read_text()
    assert install.MARK in js and all(f'"{t}"' in js for t in ("edit", "write", "patch"))
    assert json.dumps(install.GUARD_CMD) in js
    assert sorted(config.load(repo)["created_files"]) == sorted(install.HOOK_FILES)
    assert git(repo, "status", "--porcelain").stdout == ""


def test_existing_hook_files_merged_not_overwritten(repo):
    mine = {"matcher": "run_shell_command", "hooks": [{"type": "command", "command": "echo mine"}]}
    user = {"context": {"fileName": "CONTEXT.md"}, "hooks": {"BeforeTool": [mine]}}
    (repo / ".gemini").mkdir()
    (repo / ".gemini/settings.json").write_text(json.dumps(user))
    git(repo, "add", ".gemini")
    git(repo, "commit", "-m", "gemini")
    assert install.init(repo, SRC, run_setup=False) == 0
    s = json.loads((repo / ".gemini/settings.json").read_text())
    assert s["context"] == {"fileName": "CONTEXT.md"} and s["hooks"]["BeforeTool"][0] == mine
    assert len(s["hooks"]["BeforeTool"]) == 2
    assert ".gemini/settings.json" not in config.load(repo)["created_files"]
    install.uninstall(repo)
    assert json.loads((repo / ".gemini/settings.json").read_text()) == user


def test_upgrade_replaces_old_claude_project_dir_hook(repo):
    install.init(repo, SRC, run_setup=False)
    old = {"hooks": {
        "PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit|apply_patch", "hooks": [
            {"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR"/.libraryan/bin/libraryan guard'}]}],
        "SessionStart": [{"hooks": [
            {"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR"/.libraryan/bin/libraryan ensure-hooks'}]}]}}
    (repo / ".claude/settings.json").write_text(json.dumps(old))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "old hooks", env={"LIBRARYAN": "1"})
    assert install.upgrade(repo, SRC) == 0
    s = settings(repo)
    assert s == install.merge_hooks({}, install.HOOK_FILES[".claude/settings.json"])
    assert git(repo, "status", "--porcelain").stdout == ""


def test_uninstall_removes_created_hook_files_keeps_user_ones(repo):
    (repo / ".cursor").mkdir()
    (repo / ".cursor/hooks.json").write_text('{"version": 1}\n')
    git(repo, "add", ".cursor")
    git(repo, "commit", "-m", "cursor")
    install.init(repo, SRC, run_setup=False)
    assert install.uninstall(repo) == 0
    for p in (".claude/settings.json", ".codex/hooks.json", ".gemini/settings.json", ".qwen/settings.json",
              ".opencode/plugins/libraryan.js"):
        assert not (repo / p).exists(), p
    assert json.loads((repo / ".cursor/hooks.json").read_text()) == {"version": 1}
    assert git(repo, "status", "--porcelain").stdout == ""


def test_invalid_codex_hooks_json_refuses_init(repo, capsys):
    (repo / ".codex").mkdir()
    (repo / ".codex/hooks.json").write_text("{not json")
    git(repo, "add", ".codex")
    git(repo, "commit", "-m", "codex")
    assert install.init(repo, SRC, run_setup=False) == 1
    assert ".codex/hooks.json" in capsys.readouterr().err
    assert git(repo, "status", "--porcelain", "--ignored").stdout == ""


def test_init_prints_teammates_note(repo, capsys):
    install.init(repo, SRC, run_setup=False)
    out = capsys.readouterr().out
    assert "Teammates' tools" in out and "/hooks" in out


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


def test_init_without_claude_needs_no_setup(repo, monkeypatch, tmp_path):
    fake_tools(monkeypatch, tmp_path)
    assert install.init(repo, SRC) != 0
    assert not (repo / ".libraryan").exists()
    assert install.init(repo, SRC, run_setup=False) == 0
    assert config.load(repo)["runtime_bin"] is None


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
    assert (repo / ".libraryan/libraryan/cli.py").read_text() == (SRC / "cli.py").read_text()
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


def test_init_with_setup_runs_runner_with_installer_files(repo, monkeypatch, capsys):
    (repo / "docs/kb").mkdir(parents=True)
    (repo / "docs/kb/index.md").write_text("# Index\n")
    (repo / "src.py").write_text("x = 1\n")  # someone else's work in progress
    git(repo, "add", "docs")
    git(repo, "commit", "-m", "kb")
    monkeypatch.setattr(install.shutil, "which", lambda name: str(FAKE) if name == "claude" else None)
    assert install.init(repo, SRC, runtime="claude") == 0
    assert "libraryan approve" in capsys.readouterr().out  # the setup run asks first
    assert runner.approve(repo, config.load(repo)) == 0
    assert git(repo, "log", "-2", "--format=%s").stdout.split("\n")[:2] == [
        "docs(libraryan): setup run", "docs(libraryan): install"]
    installed = git(repo, "show", "--name-only", "--format=", "HEAD~1").stdout.split()
    assert "AGENTS.md" in installed and ".libraryan/config.json" in installed and "src.py" not in installed
    assert git(repo, "show", "--name-only", "--format=", "HEAD").stdout.split() == ["docs/kb/index.md"]
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
    assert "you may edit the Markdown ones only" in p and "you may edit them," not in p


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
    cfg = {**config.load(repo), "runtime_bin": str(FAKE)}
    assert runner.run(repo, cfg, "manual") == 0
    assert subject(repo) == "kb"  # the only change was to a baseline path: nothing committed
    assert "other agent wip" in (repo / "docs/kb/index.md").read_text()


def test_cli_version(capsys):
    from libraryan import cli
    assert cli.main(["--version"]) == 0 and cli.main(["version"]) == 0
    assert capsys.readouterr().out == f"libraryan {__version__}\n" * 2


def test_cli_usage_lists_user_commands(capsys):
    from libraryan import cli
    assert cli.main([]) == 2
    err = capsys.readouterr().err
    for c in ("init", "upgrade", "uninstall", "run", "check", "audit", "stats", "--version"):
        assert c in err, c


def test_cli_init_no_setup(repo, monkeypatch):
    from libraryan import cli
    monkeypatch.chdir(repo)
    assert cli.main(["init", "--no-setup"]) == 1  # no terminal to ask in
    assert cli.main(["init", "--no-setup", "--yes"]) == 0
    assert subject(repo) == "docs(libraryan): install"
    assert cli.main(["upgrade"]) == 0  # nothing changed: no commit
    assert subject(repo) == "docs(libraryan): install"
    assert cli.main(["uninstall"]) == 1  # no terminal to ask in
    assert subject(repo) == "docs(libraryan): install" and (repo / ".libraryan").exists()
    assert cli.main(["uninstall", "--yes"]) == 0
    assert subject(repo) == "docs(libraryan): uninstall"


def only_path(tmp, *tools):
    """A PATH with just these tools, so a real global `libraryan` can never be found."""
    import shutil
    d = tmp / "pathbin"
    d.mkdir(exist_ok=True)
    for t in tools:
        (d / t).symlink_to(shutil.which(t))
    return {**os.environ, "PATH": str(d)}


def test_vendored_cli_uninstall(repo):
    install.init(repo, SRC, run_setup=False)
    from libraryan import cli
    old = Path.cwd()
    os.chdir(repo)
    try:
        assert cli.main(["uninstall", "--yes"]) == 0
    finally:
        os.chdir(old)
    assert not (repo / ".libraryan").exists()


def test_vendored_cli_upgrade_runs_global_command(repo, tmp_path_factory):
    install.init(repo, SRC, run_setup=False)
    (repo / ".libraryan/libraryan/gone.py").write_text("# removed upstream\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "stale", env={"LIBRARYAN": "1"})
    tmp = tmp_path_factory.mktemp("global")
    env = only_path(tmp, "git", "python3")
    (tmp / "pathbin/libraryan").write_text(  # stands in for the pipx-installed command
        f"#!/bin/sh\nexec python3 -c 'import sys; sys.path.insert(0, \"{SRC.parent}\"); "
        "from libraryan.cli import entry; entry()' \"$@\"\n")
    (tmp / "pathbin/libraryan").chmod(0o755)
    r = subprocess.run(["python3", ".libraryan/bin/libraryan", "upgrade", "--yes"], cwd=repo, capture_output=True,
                       text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert subject(repo) == "docs(libraryan): upgrade"
    assert not (repo / ".libraryan/libraryan/gone.py").exists()


def test_vendored_cli_upgrade_without_global_command(repo, tmp_path_factory):
    install.init(repo, SRC, run_setup=False)
    head = git(repo, "rev-parse", "HEAD").stdout
    env = only_path(tmp_path_factory.mktemp("noglobal"), "git", "python3")
    r = subprocess.run(["python3", ".libraryan/bin/libraryan", "upgrade"], cwd=repo, capture_output=True,
                       text=True, env=env)
    assert r.returncode == 1
    assert "libraryan: install the tool first: pipx install libraryan" in r.stderr
    assert git(repo, "rev-parse", "HEAD").stdout == head


def test_init_refuses_dirty_settings(repo):
    (repo / ".claude").mkdir()
    (repo / ".claude/settings.json").write_text("{}\n")
    assert install.init(repo, SRC, run_setup=False) != 0
    assert not (repo / ".libraryan").exists()


def test_upgrade_refuses_pending_untracked_request(repo):
    install.init(repo, SRC, run_setup=False)
    head = git(repo, "rev-parse", "HEAD").stdout
    (repo / ".libraryan/requests/20261019-120000-x.md").write_text("in progress\n")
    assert install.upgrade(repo, SRC) != 0
    assert git(repo, "rev-parse", "HEAD").stdout == head


def test_init_with_broken_link_in_existing_agents_md(repo):
    (repo / "AGENTS.md").write_text("# Rules\n\nSee [old](missing.md).\n")
    git(repo, "add", "AGENTS.md")
    git(repo, "commit", "-m", "agents")
    assert install.init(repo, SRC, run_setup=False) == 0
    assert subject(repo) == "docs(libraryan): install"


def test_init_rolls_back_on_commit_failure(repo, monkeypatch, fake_crontab):
    (repo / "AGENTS.md").write_text("# Rules\n")
    git(repo, "add", "AGENTS.md")
    git(repo, "commit", "-m", "agents")
    head = git(repo, "rev-parse", "HEAD").stdout
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for v in ("EMAIL", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(v, raising=False)
    git(repo, "config", "--unset", "user.email")
    git(repo, "config", "user.useConfigOnly", "true")  # commit fails: no identity
    assert install.init(repo, SRC, run_setup=False) == 1
    assert git(repo, "rev-parse", "HEAD").stdout == head
    assert git(repo, "config", "core.hooksPath", check=False).stdout == ""
    assert not fake_crontab.exists()
    assert git(repo, "status", "--porcelain", "--ignored").stdout == ""
    assert (repo / "AGENTS.md").read_text() == "# Rules\n"
    assert not (repo / ".libraryan").exists() and not (repo / ".claude").exists()
    git(repo, "config", "user.email", "test@example.com")
    assert install.init(repo, SRC, run_setup=False) == 0


def test_init_aborts_on_secret_in_installer_file(repo):
    (repo / "CLAUDE.md").write_text("token = 'abcdefghijklmnop'\n")
    git(repo, "add", "CLAUDE.md")
    git(repo, "commit", "-m", "claude")
    assert install.init(repo, SRC, run_setup=False) == 1
    assert git(repo, "status", "--porcelain").stdout == ""


def test_init_malformed_settings_writes_nothing(repo):
    (repo / ".claude").mkdir()
    (repo / ".claude/settings.json").write_text("{not json")
    git(repo, "add", ".claude")
    git(repo, "commit", "-m", "settings")
    assert install.init(repo, SRC, run_setup=False) == 1
    assert git(repo, "status", "--porcelain", "--ignored").stdout == ""


@pytest.mark.parametrize("link,target", [("CLAUDE.md", "AGENTS.md"), ("AGENTS.md", "CLAUDE.md")])
def test_init_claude_md_symlink(repo, link, target):
    (repo / target).write_text("# Rules\n")
    (repo / link).symlink_to(target)
    git(repo, "add", "AGENTS.md", "CLAUDE.md")
    git(repo, "commit", "-m", "agents")
    assert install.init(repo, SRC, run_setup=False) == 0
    assert (repo / link).is_symlink()
    text = (repo / target).read_text()
    assert "@AGENTS.md" not in text and START in text
    assert config.load(repo)["claude_md_symlink"] is True
    work = {"requests": [], "since": None, "commits": 0, "health": True, "baseline": [], "extra": ["AGENTS.md"]}
    p = runner.build_prompt("setup", work, config.load(repo))
    assert "symlink" in p and "the `@AGENTS.md` line in CLAUDE.md exactly" not in p
    assert "the `@AGENTS.md` line in CLAUDE.md exactly" in runner.build_prompt("setup", work, {})


def test_init_setup_failure_prints_retry_hint(repo, monkeypatch, capsys):
    monkeypatch.setattr(install.shutil, "which", lambda name: "/nonexistent/claude" if name == "claude" else None)
    assert install.init(repo, SRC, runtime="claude") == 1
    assert subject(repo) == "docs(libraryan): install"
    err = capsys.readouterr().err
    assert "run --reason setup" in err and "could not start /nonexistent/claude" in err


def test_cli_init_asks_before_the_install_commit(repo, monkeypatch, capsys):
    from libraryan import cli
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda _: "n")
    head = subject(repo)
    assert cli.main(["init", "--no-setup", "--runtime", "claude"]) == 1
    assert subject(repo) == head and not (repo / ".libraryan").exists()
    assert ".libraryan/config.json" in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda _: "y")
    assert cli.main(["init", "--no-setup", "--runtime", "claude"]) == 0
    assert subject(repo) == "docs(libraryan): install"


def test_uninstall_refuses_dirty_targets(repo):
    install.init(repo, SRC, run_setup=False)
    (repo / "CLAUDE.md").write_text("@AGENTS.md\nmy edit\n")
    assert install.uninstall(repo) == 1
    assert (repo / ".libraryan").exists() and "my edit" in (repo / "CLAUDE.md").read_text()


def test_uninstall_refuses_untracked_requests(repo, capsys):
    install.init(repo, SRC, run_setup=False)
    (repo / ".libraryan/requests/20261019-120000-x.md").write_text("in progress\n")
    assert install.uninstall(repo) == 1
    assert ".libraryan/requests/20261019-120000-x.md" in capsys.readouterr().err
    assert (repo / ".libraryan/requests/20261019-120000-x.md").exists()


def test_crontab_left_alone_when_unreadable(repo, tmp_path_factory, monkeypatch):
    d = tmp_path_factory.mktemp("badcron")
    (d / "table").write_text("5 * * * * keep me\n")
    script = d / "crontab"
    script.write_text(f"""#!/bin/sh
if [ "$1" = -l ]; then echo "crontab: permission denied" >&2; exit 1; fi
cat > '{d}/table'
""")
    script.chmod(0o755)
    monkeypatch.setattr(install, "crontab_cmd", str(script))
    assert install.init(repo, SRC, run_setup=False) == 0
    assert (d / "table").read_text() == "5 * * * * keep me\n"


def test_commit_with_no_installer_files_commits_nothing(repo):
    (repo / "src.py").write_text("x = 1\n")
    git(repo, "add", "src.py")
    head = git(repo, "rev-parse", "HEAD").stdout
    assert install._commit(repo, "install", config.load(repo)) == 0
    assert git(repo, "rev-parse", "HEAD").stdout == head
    assert git(repo, "status", "--porcelain").stdout.strip() == "A  src.py"


def test_global_hooks_path_ignored(repo, tmp_path, monkeypatch):
    g = tmp_path / "gitconfig"
    g.write_text("[core]\n\thooksPath = /global/hooks\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(g))
    install.init(repo, SRC, run_setup=False)
    assert config.load(repo)["chain_hooks_path"] is None
    install.uninstall(repo)
    assert git(repo, "config", "--local", "core.hooksPath", check=False).stdout == ""


def test_init_announces_setup(repo, monkeypatch, capsys):
    monkeypatch.setattr(install.shutil, "which", lambda name: "/nonexistent/claude" if name == "claude" else None)
    install.init(repo, SRC, runtime="claude")
    assert ("Setup running (can take up to 120 minutes); report: .libraryan/state/reports/latest.md"
            in capsys.readouterr().out)


def test_upgrade_refuses_without_install(repo, capsys):
    head = git(repo, "rev-parse", "HEAD").stdout
    assert install.upgrade(repo) == 1
    assert "libraryan: not installed here; run: libraryan init" in capsys.readouterr().err
    assert not (repo / ".libraryan").exists() and not (repo / ".claude").exists()
    assert git(repo, "rev-parse", "HEAD").stdout == head


def test_upgrade_drops_source_path(repo):
    install.init(repo, SRC, run_setup=False)
    cfg = json.loads((repo / ".libraryan/config.json").read_text())
    cfg["source_path"] = "/old/checkout"
    (repo / ".libraryan/config.json").write_text(json.dumps(cfg))
    git(repo, "commit", "-qam", "old install", env={"LIBRARYAN": "1"})
    assert install.upgrade(repo) == 0
    assert "source_path" not in json.loads((repo / ".libraryan/config.json").read_text())


def test_init_and_upgrade_record_version(repo):
    install.init(repo, SRC, run_setup=False)
    assert config.load(repo)["installed_version"] == __version__
    cfg = json.loads((repo / ".libraryan/config.json").read_text())
    cfg["installed_version"] = "0.1.0"
    (repo / ".libraryan/config.json").write_text(json.dumps(cfg))
    git(repo, "commit", "-qam", "older", env={"LIBRARYAN": "1"})
    assert install.upgrade(repo) == 0
    assert config.load(repo)["installed_version"] == __version__


def test_upgrade_refuses_downgrade(repo, capsys):
    install.init(repo, SRC, run_setup=False)
    cfg = json.loads((repo / ".libraryan/config.json").read_text())
    cfg["installed_version"] = "99.0.0"
    (repo / ".libraryan/config.json").write_text(json.dumps(cfg))
    git(repo, "commit", "-qam", "newer", env={"LIBRARYAN": "1"})
    head = git(repo, "rev-parse", "HEAD").stdout
    assert install.upgrade(repo) == 1
    assert "pipx upgrade libraryan" in capsys.readouterr().err
    assert git(repo, "rev-parse", "HEAD").stdout == head


def test_upgrade_from_read_only_package(repo, tmp_path_factory):
    import shutil
    import stat
    ro = tmp_path_factory.mktemp("ro") / "libraryan"
    shutil.copytree(SRC, ro, ignore=shutil.ignore_patterns("__pycache__"))
    paths = [ro, *ro.rglob("*")]
    for p in paths:
        p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    try:
        assert install.init(repo, ro, run_setup=False) == 0
        (repo / ".libraryan/libraryan/gone.py").write_text("# stale\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "stale", env={"LIBRARYAN": "1"})
        assert install.upgrade(repo, ro) == 0
        assert not (repo / ".libraryan/libraryan/gone.py").exists()
    finally:
        for p in paths:
            p.chmod(p.stat().st_mode | stat.S_IWUSR)


def test_uninstall_with_invalid_hook_file_changes_nothing(repo, fake_crontab):
    install.init(repo, SRC, run_setup=False)
    (repo / ".gemini/settings.json").write_text("{not json")
    git(repo, "commit", "-qam", "broken", env={"LIBRARYAN": "1"})
    cron = fake_crontab.read_text()
    assert install.uninstall(repo) == 1
    assert git(repo, "config", "core.hooksPath").stdout.strip() == install.HOOKS_PATH
    assert fake_crontab.read_text() == cron and START in (repo / "AGENTS.md").read_text()
    assert (repo / ".libraryan").is_dir() and git(repo, "status", "--porcelain").stdout == ""


def stale_install(repo):
    install.init(repo, SRC, run_setup=False)
    (repo / ".libraryan/libraryan/gone.py").write_text("# removed upstream\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "stale", env={"LIBRARYAN": "1"})


def test_upgrade_asks_and_no_changes_nothing(repo, capsys):
    stale_install(repo)
    head, asked = git(repo, "rev-parse", "HEAD").stdout, []
    assert install.upgrade(repo, SRC, confirm=lambda files: asked.append(files) or False) == 1
    assert asked == [[".libraryan/libraryan/gone.py"]]
    assert git(repo, "rev-parse", "HEAD").stdout == head and git(repo, "status", "--porcelain").stdout == ""
    assert "upgrade cancelled" in capsys.readouterr().err
    assert install.upgrade(repo, SRC, confirm=lambda files: True) == 0
    assert subject(repo) == "docs(libraryan): upgrade"


def test_uninstall_asks_first_and_no_changes_nothing(repo, fake_crontab):
    install.init(repo, SRC, run_setup=False)
    head, hooks = git(repo, "rev-parse", "HEAD").stdout, git(repo, "config", "core.hooksPath").stdout
    asked = []
    assert install.uninstall(repo, confirm=lambda files: asked.append(files) or False) == 1
    assert ".libraryan/config.json" in asked[0]
    assert git(repo, "rev-parse", "HEAD").stdout == head and git(repo, "status", "--porcelain").stdout == ""
    assert git(repo, "config", "core.hooksPath").stdout == hooks and (repo / ".libraryan").exists()
