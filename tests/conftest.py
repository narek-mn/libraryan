import os
import shutil
import subprocess

import pytest


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    (tmp_path / "README.md").write_text("# test\n")
    git("add", "README.md")
    git("commit", "-m", "init")
    return tmp_path


@pytest.fixture(autouse=True)
def fake_crontab(tmp_path_factory, monkeypatch):
    """Every test gets a fake `crontab`; the real user crontab is never touched."""
    from libraryan import install

    d = tmp_path_factory.mktemp("crontab")
    script = d / "crontab"
    script.write_text(f"""#!/bin/sh
f='{d}/table'
if [ "$1" = -l ]; then cat "$f" 2>/dev/null || {{ echo "no crontab for user" >&2; exit 1; }}
else cat > "$f"; fi
""")
    script.chmod(0o755)
    monkeypatch.setattr(install, "crontab_cmd", str(script))
    return d / "table"


BASE_TOOLS = ("git", "sh", "env", "python3", "cat", "dirname", "basename", "mkdir", "rm", "sed", "grep", "head", "tr",
              "sort", "date", "sleep", "uname", "id", "ls", "touch", "chmod")


@pytest.fixture(autouse=True)
def isolated_path(tmp_path_factory, monkeypatch):
    """PATH holds only symlinks to the basics, so no developer's real agent CLI (claude, agent, ...) is ever found."""
    d = tmp_path_factory.mktemp("basebin")
    for t in BASE_TOOLS:
        src = os.path.realpath(shutil.which(t)) if shutil.which(t) else None
        if t == "python3":
            src = os.path.realpath(__import__("sys").executable)
        if src:
            (d / t).symlink_to(src)
    monkeypatch.setenv("PATH", str(d))
    return d
