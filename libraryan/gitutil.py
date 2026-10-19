import subprocess
from pathlib import Path


def git(root: Path, *args, check=True, env=None) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=check, env=env)
    return r.stdout.strip()


def repo_root(cwd: Path) -> Path:
    return Path(git(cwd, "rev-parse", "--show-toplevel"))


def current_branch(root: Path) -> str:
    return git(root, "rev-parse", "--abbrev-ref", "HEAD")


def head(root: Path) -> str:
    return git(root, "rev-parse", "HEAD")


def staged_changes(root: Path) -> list[tuple[str, str, str | None]]:
    """(status, path, old_path) per staged change; status keeps rename score, e.g. R100."""
    out = git(root, "-c", "core.quotepath=off", "diff", "--cached", "--name-status", "-M")
    changes = []
    for line in out.splitlines():
        parts = line.split("\t")
        if parts[0][0] in "RC":
            changes.append((parts[0], parts[2], parts[1]))
        else:
            changes.append((parts[0], parts[1], None))
    return changes
