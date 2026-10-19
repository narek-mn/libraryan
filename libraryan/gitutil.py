import subprocess
from pathlib import Path


def git(root: Path, *args, check=True, env=None) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=check, env=env)
    return r.stdout.strip()


def repo_root(cwd: Path) -> Path:
    return Path(git(cwd, "rev-parse", "--show-toplevel"))


def current_branch(root: Path) -> str:
    return git(root, "symbolic-ref", "--short", "HEAD")


def head(root: Path) -> str:
    return git(root, "rev-parse", "HEAD")


def staged_changes(root: Path) -> list[tuple[str, str, str | None]]:
    """(status, path, old_path) per staged change; status keeps rename score, e.g. R100."""
    out = git(root, "diff", "--cached", "--name-status", "-M", "-z")
    f = out.split("\0")[:-1] if out else []
    changes, i = [], 0
    while i < len(f):
        if f[i][0] in "RC":
            changes.append((f[i], f[i + 2], f[i + 1]))
            i += 3
        else:
            changes.append((f[i], f[i + 1], None))
            i += 2
    return changes


def staged_text(root: Path, path: str) -> str:
    r = subprocess.run(["git", "show", f":{path}"], cwd=root, capture_output=True)
    return r.stdout.decode(errors="replace")
