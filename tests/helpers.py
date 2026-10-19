import shutil
import subprocess
from pathlib import Path

from libraryan import config

ROOT = Path(__file__).resolve().parent.parent


def install_runtime(repo: Path) -> None:
    dest = repo / ".libraryan"
    shutil.copytree(ROOT / "libraryan", dest / "libraryan",
                    ignore=shutil.ignore_patterns("__pycache__", "_runtime", "_templates"))
    shutil.copytree(ROOT / "libraryan" / "_runtime" / "bin", dest / "bin")
    shutil.copytree(ROOT / "libraryan" / "_runtime" / "hooks", dest / "hooks")
    config.save(repo, config.DEFAULTS)
    subprocess.run(["git", "config", "core.hooksPath", ".libraryan/hooks"], cwd=repo, check=True)
