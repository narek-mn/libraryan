import os
import re
from pathlib import Path

from . import gitutil
from .paths import glob_match, is_protected
from .precommit import REJECTION

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"}
PATCH_TARGET = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$", re.M)


def _targets(payload: dict) -> list[str]:
    """Paths a tool call would write. Claude Code: file_path/notebook_path; Copilot CLI: path;
    Codex and GPT models in Copilot: apply_patch text, sometimes run through the shell."""
    ti = payload.get("tool_input") or {}
    tool = payload.get("tool_name")
    text = ti.get("command") or ti.get("patch") or ti.get("input") or ""
    patched = PATCH_TARGET.findall(text) if isinstance(text, str) and "*** Begin Patch" in text else []
    if tool not in EDIT_TOOLS:
        return patched  # ponytail: other shell writes are left to the pre-commit hook, the authoritative lock
    return [f for f in (ti.get("file_path"), ti.get("notebook_path"), ti.get("path")) if isinstance(f, str) and f] + patched


def guard(payload: dict, root: Path, cfg: dict, env: dict) -> tuple[int, str]:
    for f in _targets(payload):
        code, msg = _check(Path(os.path.abspath(Path(payload.get("cwd") or root) / f)), root, cfg, env)
        if code:
            return code, msg
    return 0, ""


def _check(path: Path, root: Path, cfg: dict, env: dict) -> tuple[int, str]:
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
