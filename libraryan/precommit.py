from pathlib import Path

from . import checks, gitutil
from .paths import is_protected, is_request


def check_commit(root: Path, cfg: dict, env: dict) -> list[str]:
    if (root / gitutil.git(root, "rev-parse", "--git-path", "MERGE_HEAD")).exists():
        return []
    changes = gitutil.staged_changes(root)
    if env.get("LIBRARYAN") == "1":
        files = [p for _, p, _ in changes if is_protected(p, cfg) or is_request(p)]
        return checks.run_all(root, cfg, files)
    bad = []
    for status, path, old in changes:
        if status in ("D", "R100"):
            continue
        if is_protected(path, cfg):
            bad.append(path)
    problems = [f"blocked: {p}" for p in bad]
    reqs = [p for _, p, _ in changes if is_request(p)]
    return problems + checks.scan_secrets(root, reqs)
