"""Build the wheel offline, install it into a fresh venv and use the `libraryan` command it ships."""
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import libraryan

ROOT = Path(__file__).resolve().parent.parent


def _missing() -> str | None:
    try:
        import setuptools
        import venv  # noqa: F401
    except ImportError as e:
        return str(e)
    if int(setuptools.__version__.split(".")[0]) < 77:
        return f"setuptools {setuptools.__version__} < 77"
    if "--python" not in subprocess.run([sys.executable, "-m", "pip", "--help"], capture_output=True, text=True).stdout:
        return "pip >= 22.3 (--python) not available"
    return None


MISSING = _missing()
pytestmark = pytest.mark.skipif(bool(MISSING), reason=f"cannot build/install a wheel: {MISSING}")


@pytest.fixture(scope="module")
def wheel(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("wheel")
    src = tmp / "src"  # build from a copy so the checkout gets no build/ or egg-info
    shutil.copytree(ROOT, src, ignore=shutil.ignore_patterns(
        ".git", "build", "dist", "*.egg-info", "__pycache__", ".pytest_cache", ".superpowers"))
    subprocess.run([sys.executable, "-m", "pip", "wheel", str(src), "--no-deps", "--no-build-isolation",
                    "-w", str(tmp / "dist")], check=True, capture_output=True)
    return next((tmp / "dist").glob("libraryan-*.whl"))


@pytest.fixture(scope="module")
def venv_bin(wheel, tmp_path_factory):
    v = tmp_path_factory.mktemp("venv") / "v"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(v)], check=True)
    # host pip installs into the venv: works where the venv has no ensurepip (Debian without python3-venv)
    subprocess.run([sys.executable, "-m", "pip", "--python", str(v / "bin/python"), "install", "--no-deps",
                    "--no-index", str(wheel)], check=True, capture_output=True)
    return v / "bin"


def test_wheel_contents(wheel):
    with zipfile.ZipFile(wheel) as z:
        names = set(z.namelist())
        eps = next(z.read(n).decode() for n in names if n.endswith(".dist-info/entry_points.txt"))
    for n in ("libraryan/_runtime/bin/libraryan", "libraryan/_runtime/hooks/pre-commit",
              "libraryan/_runtime/hooks/post-commit", "libraryan/_runtime/policies/gemini-author.toml", "libraryan/_templates/agents/libraryan.md",
              "libraryan/_templates/skills/libraryan-request/SKILL.md", "libraryan/cli.py"):
        assert n in names, n
    assert not any(n.startswith(("tests/", "docs/")) for n in names)
    assert "libraryan = libraryan.cli:entry" in eps


def test_installed_command_version(venv_bin):
    r = subprocess.run([str(venv_bin / "libraryan"), "--version"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == f"libraryan {libraryan.__version__}\n"


def test_installed_command_init(venv_bin, repo, tmp_path_factory):
    fake = tmp_path_factory.mktemp("fakecron")  # first on PATH: the real crontab is never touched
    (fake / "crontab").write_text(f"""#!/bin/sh
if [ "$1" = -l ]; then cat '{fake}/table' 2>/dev/null || {{ echo "no crontab for user" >&2; exit 1; }}
else cat > '{fake}/table'; fi
""")
    (fake / "crontab").chmod(0o755)
    env = {**os.environ, "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run([str(venv_bin / "libraryan"), "init", "--no-setup"], cwd=repo, capture_output=True,
                       text=True, env=env)
    assert r.returncode == 0, r.stderr
    log = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo, capture_output=True, text=True).stdout
    assert log.strip() == "docs(libraryan): install"
    for p in ("bin/libraryan", "hooks/pre-commit", "hooks/post-commit"):
        assert os.access(repo / ".libraryan" / p, os.X_OK), p
    assert not (repo / ".libraryan/libraryan/_templates").exists()
    assert not (repo / ".libraryan/libraryan/_runtime").exists()
    assert f"# libraryan:{repo}" in (fake / "table").read_text()
    r = subprocess.run([str(repo / ".libraryan/bin/libraryan"), "check"], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
