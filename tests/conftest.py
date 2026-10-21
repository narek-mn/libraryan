import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FAKE = Path(__file__).with_name("fake_claude.py")


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.name", "Test")
    git(r, "config", "user.email", "test@example.com")
    (r / "README.md").write_text("# Demo\n\nRun `src/app.py` to start. See [setup](docs/setup.md).\n")
    (r / "src").mkdir()
    (r / "src/app.py").write_text("print('hi')\n")
    (r / "docs").mkdir()
    (r / "docs/setup.md").write_text("# Setup\n\nInstall with pip. The port is 8080 by default.\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "init")
    monkeypatch.chdir(r)
    return r


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    """A `claude` on PATH that performs `actions` in the worktree and answers like `claude -p --output-format json`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
    (bin_dir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    script = tmp_path / "script.json"

    def set_script(actions=(), result="Changed:\n- none", **extra):
        script.write_text(json.dumps({"actions": list(actions), "result": result, **extra}))
    monkeypatch.setenv("FAKE_CLAUDE_SCRIPT", str(script))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "argv.json"))
    set_script()
    return set_script
