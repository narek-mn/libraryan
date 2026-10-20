import os
import shutil
import subprocess
from pathlib import Path

from libraryan import config, install

ROOT = Path(__file__).resolve().parent.parent


def install_runtime(repo: Path) -> None:
    dest = repo / ".libraryan"
    shutil.copytree(ROOT / "libraryan", dest / "libraryan",
                    ignore=shutil.ignore_patterns("__pycache__", "_runtime", "_templates"))
    shutil.copytree(ROOT / "libraryan" / "_runtime" / "bin", dest / "bin")
    shutil.copytree(ROOT / "libraryan" / "_runtime" / "hooks", dest / "hooks")
    install.neutral_agents(repo, ROOT / "libraryan")  # so with_instructions really prepends them in runner tests
    config.save(repo, config.DEFAULTS)
    subprocess.run(["git", "config", "core.hooksPath", ".libraryan/hooks"], cwd=repo, check=True)


def fake_tools(monkeypatch, tmp: Path, *names: str) -> None:
    """Put fake agent binaries (each prints a version) in front of the isolated PATH from conftest."""
    d = tmp.parent / (tmp.name + "-fakebin")
    d.mkdir(exist_ok=True)
    for n in names:
        (d / n).write_text(f"#!/bin/sh\necho '{n} 1.2.3'\n")
        (d / n).chmod(0o755)
    base = os.environ["PATH"].split(os.pathsep)[-1]  # conftest's dir; calling twice must not stack fake dirs
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{base}")
