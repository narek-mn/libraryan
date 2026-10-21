import json
import os

import pytest

from conftest import git
from libraryan import fix
from libraryan.cli import main

SETUP_OLD = "Install with pip. The port is 8080 by default."


def status(repo):
    return git(repo, "status", "--porcelain")


def argv(tmp_path):
    return json.loads((tmp_path / "argv.json").read_text())


def test_doc_edit_comes_back_uncommitted(repo, fake_claude, tmp_path, capsys):
    head = git(repo, "rev-parse", "HEAD")
    fake_claude([["write", "docs/setup.md", "# Setup\n\nInstall with pip. The port is 9090 by default.\n"]],
                result="Changed:\n- docs/setup.md: port was wrong")
    assert main(["fix"]) == 0
    assert "9090" in (repo / "docs/setup.md").read_text()
    assert git(repo, "rev-parse", "HEAD") == head and status(repo) == " M docs/setup.md\n"
    out = capsys.readouterr().out
    assert "port was wrong" in out and "changed  docs/setup.md" in out and "Nothing is committed" in out
    assert "Undo:   git restore -- docs/setup.md" in out and "Cost: $0.42" in out
    assert git(repo, "worktree", "list").count("\n") == 1  # the throwaway copy is gone


def test_agent_gets_instructions_tools_budget_and_findings(repo, fake_claude, tmp_path):
    (repo / "docs/a.md").write_text("[x](gone.md)\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "a")
    assert main(["fix", "--budget", "2", "--model", "sonnet"]) == 0
    a = argv(tmp_path)
    assert a[0] == "-p" and "You fix this project's Markdown docs" in a[a.index("--append-system-prompt") + 1]
    assert a[a.index("--max-budget-usd") + 1] == "2" and a[a.index("--model") + 1] == "sonnet"
    assert "Bash(git rm:*)" in a[a.index("--allowedTools") + 1] and "Bash(git commit" not in " ".join(a)
    assert "Scope: every doc" in a[-1] and "docs/a.md:1: broken link gone.md" in a[-1]


def test_non_doc_changes_are_dropped(repo, fake_claude, capsys):
    fake_claude([["write", "src/app.py", "print('hacked')\n"], ["write", ".claude/x.md", "x\n"],
                 ["write", "docs/new.md", "# New\n"]])
    assert main(["fix"]) == 0
    assert (repo / "src/app.py").read_text() == "print('hi')\n" and not (repo / ".claude").exists()
    assert status(repo) == "?? docs/new.md\n"
    out = capsys.readouterr().out
    assert "Ignored 2 change(s) outside the docs" in out and "rm -- docs/new.md" in out


def test_deletion_needs_a_ledger_line(repo, fake_claude, capsys):
    fake_claude([["git", "rm", "-q", "docs/setup.md"], ["write", "README.md", "# Demo\n"]])
    assert main(["fix"]) == 0
    assert (repo / "docs/setup.md").read_text().strip().endswith(SETUP_OLD)  # kept
    assert "Kept docs/setup.md: the agent deleted it but the agent did not say where its facts went" \
        in capsys.readouterr().out
    assert status(repo) == " M README.md\n"


def test_deletion_with_checked_fact_is_applied(repo, fake_claude):
    readme = "# Demo\n\nRun `src/app.py` to start. The port is 8080 by default.\n"
    fake_claude([["git", "rm", "-q", "docs/setup.md"], ["write", "README.md", readme]],
                result="Deleted:\n- docs/setup.md\nFact: docs/setup.md => README.md | The port is 8080 by default. "
                       "| The port is 8080 by default.")
    assert main(["fix"]) == 0
    assert not (repo / "docs").exists()  # emptied folder pruned
    assert status(repo) == " M README.md\n D docs/setup.md\n"


def test_pure_move_needs_no_line(repo, fake_claude):
    fake_claude([["git", "mv", "docs/setup.md", "docs/install.md"]])
    assert main(["fix"]) == 0
    assert (repo / "docs/install.md").exists() and not (repo / "docs/setup.md").exists()


def test_refuses_uncommitted_doc_changes(repo, fake_claude, capsys):
    (repo / "docs/setup.md").write_text("mine\n")
    assert main(["fix"]) == 1
    assert "commit or stash your doc changes first" in capsys.readouterr().err
    assert (repo / "docs/setup.md").read_text() == "mine\n"


def test_code_changes_of_the_user_are_untouched(repo, fake_claude):
    (repo / "src/app.py").write_text("print('wip')\n")
    fake_claude([["write", "docs/setup.md", "# Setup\n"]])
    assert main(["fix"]) == 0
    assert (repo / "src/app.py").read_text() == "print('wip')\n"


def test_since_scopes_to_changed_files(repo, fake_claude, tmp_path, capsys):
    git(repo, "switch", "-qc", "feature")
    assert main(["fix", "--since", "main"]) == 0
    assert "Nothing changed since main." in capsys.readouterr().out
    (repo / "src/app.py").write_text("print('v2')\n")
    git(repo, "commit", "-qam", "v2")
    assert main(["fix", "--since", "main"]) == 0
    assert "Scope: only docs affected" in argv(tmp_path)[-1] and "- src/app.py" in argv(tmp_path)[-1]
    assert main(["fix", "--since", "nope"]) == 1
    assert "nope is not a commit or branch" in capsys.readouterr().err


def test_agent_failure_reports_why(repo, fake_claude, capsys):
    fake_claude(crash=True)
    assert main(["fix"]) == 1
    assert "claude failed (exit 1): boom: not logged in" in capsys.readouterr().err


def test_budget_stop_keeps_work_done_so_far(repo, fake_claude, capsys):
    fake_claude([["write", "docs/setup.md", "# Setup\n\nfixed\n"]], is_error=True, subtype="error_max_budget_usd",
                result="")
    assert main(["fix", "--budget", "1"]) == 0
    err = capsys.readouterr().err
    assert "stopped early (error_max_budget_usd)" in err and "--budget 3" in err
    assert status(repo) == " M docs/setup.md\n"


def test_timeout_stops_the_agent(repo, fake_claude, monkeypatch, capsys):
    monkeypatch.setattr(fix, "TIMEOUT_MINUTES", 0.02)
    fake_claude([["sleep", 30]])
    assert main(["fix"]) == 1
    assert "stopped after" in capsys.readouterr().err


def test_without_claude(repo, monkeypatch, capsys):
    monkeypatch.setattr(fix.shutil, "which", lambda name: None)
    assert main(["fix"]) == 1
    assert "Claude Code is not installed" in capsys.readouterr().err


def test_progress_line_on_a_terminal(repo, fake_claude, monkeypatch, capsys):
    monkeypatch.setattr(fix.sys.stderr, "isatty", lambda: True)
    fake_claude([["write", "docs/setup.md", "x\n"]])
    assert main(["fix"]) == 0
    err = capsys.readouterr().err
    assert "Fixing the docs · 0:0" in err and "✓ Fixing the docs" in err and "%" not in err
