import re
from functools import lru_cache


@lru_cache(maxsize=None)
def _regex(pattern: str):
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def glob_match(path: str, pattern: str) -> bool:
    return _regex(pattern).match(path) is not None


def is_request(path: str) -> bool:
    return glob_match(path, ".libraryan/requests/**")


def is_protected(path: str, cfg: dict) -> bool:
    if is_request(path):
        return False
    if glob_match(path, ".libraryan/**"):
        return True
    if any(glob_match(path, p) for p in cfg["excluded"] + cfg["exempt"]):
        return False
    return any(glob_match(path, p) for p in cfg["owned"])


MACHINERY = (".libraryan/**", ".claude/agents/libraryan.md", ".claude/agents/libraryan-reviewer.md",
             ".claude/skills/libraryan-request/**")


def is_machinery(path: str) -> bool:
    """Libraryan's own files (config, hooks, instructions): never changed by a model session. Requests are not."""
    return not is_request(path) and any(glob_match(path, p) for p in MACHINERY)
