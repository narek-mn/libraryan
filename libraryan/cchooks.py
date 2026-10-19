import os
from pathlib import Path

from . import gitutil
from .paths import is_protected
from .precommit import REJECTION

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def guard(payload: dict, root: Path, cfg: dict, env: dict) -> tuple[int, str]:
    # ponytail: pre-commit is the authoritative lock; Bash parsing is best-effort and skipped
    if payload.get("tool_name") not in EDIT_TOOLS or env.get("LIBRARYAN"):
        return 0, ""
    ti = payload.get("tool_input") or {}
    f = ti.get("file_path") or ti.get("notebook_path")
    if not f:
        return 0, ""
    path = Path(os.path.abspath(Path(payload.get("cwd") or root) / f))
    try:
        rel = path.relative_to(os.path.abspath(root)).as_posix()
    except ValueError:
        return 0, ""
    if is_protected(rel, cfg):
        return 2, f"{REJECTION}\n  {rel}"
    return 0, ""


def ensure_hooks(root: Path) -> None:
    if not (root / ".libraryan" / "hooks").is_dir():
        return
    if gitutil.git(root, "config", "core.hooksPath", check=False).strip() != ".libraryan/hooks":
        gitutil.git(root, "config", "core.hooksPath", ".libraryan/hooks")
