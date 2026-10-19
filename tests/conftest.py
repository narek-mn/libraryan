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
