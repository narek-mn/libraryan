"""Which files count as the project's docs."""
from pathlib import Path

from . import gitutil

# Markdown that belongs to code or to other people, never the project's own docs
SKIP_DIRS = {"node_modules", "vendor", "third_party", "fixtures", "testdata", "templates", ".venv", "venv"}


def is_doc(path: str) -> bool:
    """A project doc: Markdown outside code-owned folders and tool folders (`.claude/`, `.agents/`, ...)."""
    dirs = path.split("/")[:-1]
    return (path.endswith(".md") and not SKIP_DIRS.intersection(dirs)
            and not any(d.startswith(".") and d != ".github" for d in dirs))


def tracked(root: Path) -> list[str]:
    """Every file git knows or would add (tracked and untracked, .gitignore respected)."""
    out = gitutil.git(root, "ls-files", "-z", "-co", "--exclude-standard")
    return sorted({p for p in out.split("\0") if p})
