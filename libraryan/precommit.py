from pathlib import Path

from . import checks, gitutil
from .paths import glob_match, is_protected, is_request


def _scan_staged(root: Path, changes) -> list[str]:
    out = []
    for status, path, _ in changes:
        if status[0] != "D":
            out += checks.scan_text(gitutil.staged_text(root, path), path)
    return out


def check_commit(root: Path, cfg: dict, env: dict) -> list[str]:
    if (root / gitutil.git(root, "rev-parse", "--git-path", "MERGE_HEAD")).exists():
        return []
    changes = [c for c in gitutil.staged_changes(root) if is_protected(c[1], cfg) or is_request(c[1])]
    if env.get("LIBRARYAN") == "1":
        files = [p for s, p, _ in changes if s[0] != "D"]
        return checks.lint(root, cfg, files) + _scan_staged(root, changes)
    bad = []
    for status, path, old in changes:
        if is_request(path):
            continue
        if status == "D" or (status == "R100" and is_protected(old, cfg) and not glob_match(path, ".libraryan/**")):
            continue
        bad.append(path)
    return [f"blocked: {p}" for p in bad] + _scan_staged(root, [c for c in changes if is_request(c[1])])
