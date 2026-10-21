"""Build the wheel offline, install it into a fresh venv and run the `libraryan` command it ships."""
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
        ".git", "build", "dist", "*.egg-info", "__pycache__", ".pytest_cache"))
    subprocess.run([sys.executable, "-m", "pip", "wheel", str(src), "--no-deps", "--no-build-isolation",
                    "-w", str(tmp / "dist")], check=True, capture_output=True)
    return next((tmp / "dist").glob("libraryan-*.whl"))


def test_wheel_contents(wheel):
    with zipfile.ZipFile(wheel) as z:
        names = set(z.namelist())
        eps = next(z.read(n).decode() for n in names if n.endswith(".dist-info/entry_points.txt"))
    for n in ("libraryan/cli.py", "libraryan/check.py", "libraryan/fix.py", "libraryan/instructions.py"):
        assert n in names, n
    assert not any(n.startswith(("tests/", "docs/")) for n in names)
    assert "libraryan = libraryan.cli:entry" in eps


def test_installed_command(wheel, repo, tmp_path_factory):
    v = tmp_path_factory.mktemp("venv") / "v"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(v)], check=True)
    subprocess.run([sys.executable, "-m", "pip", "--python", str(v / "bin/python"), "install", "--no-deps",
                    "--no-index", str(wheel)], check=True, capture_output=True)
    r = subprocess.run([str(v / "bin/libraryan"), "--version"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == f"libraryan {libraryan.__version__}\n"
    r = subprocess.run([str(v / "bin/libraryan"), "check"], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == "No problems found.\n"
