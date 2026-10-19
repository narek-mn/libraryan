import os
from pathlib import Path

from . import gitutil
from .paths import glob_match, is_protected
from .precommit import REJECTION

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def guard(payload: dict, root: Path, cfg: dict, env: dict) -> tuple[int, str]:
    # ponytail: pre-commit is the authoritative lock; Bash parsing is best-effort and skipped
    if payload.get("tool_name") not in EDIT_TOOLS:
        return 0, ""
    ti = payload.get("tool_input") or {}
    f = ti.get("file_path") or ti.get("notebook_path")
    if not f:
        return 0, ""
    path = Path(os.path.abspath(Path(payload.get("cwd") or root) / f))
    try:
        rel = path.relative_to(os.path.abspath(root)).as_posix()
    except ValueError:
        rel = None
    if env.get("LIBRARYAN"):  # a Libraryan run: only the docs it owns, never code, its own files or outside paths
        if rel is None or not is_protected(rel, cfg) or glob_match(rel, ".libraryan/**"):
            return 2, f"Libraryan run: edit only documentation Libraryan owns, not {rel or path}"
        return 0, ""
    if rel is not None and is_protected(rel, cfg):
        return 2, f"{REJECTION}\n  {rel}"
    return 0, ""


def ensure_hooks(root: Path) -> None:
    if not (root / ".libraryan" / "hooks").is_dir():
        return
    if gitutil.git(root, "config", "core.hooksPath", check=False).strip() != ".libraryan/hooks":
        gitutil.git(root, "config", "core.hooksPath", ".libraryan/hooks")
