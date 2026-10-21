"""`libraryan check`: broken links and file paths that no longer exist, in every doc. No AI, no edits."""
import posixpath
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

from .docs import is_doc, tracked

LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
TICK = re.compile(r"`([^`\n]+)`")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
SUFFIX = re.compile(r"(?:#L\d+(?:-L?\d+)?|:\d+(?:-\d+)?|:[A-Za-z_][\w.]*)$")  # file.py#L12, :12, :symbol

HISTORY = ("CHANGELOG", "CHANGES", "HISTORY", "RELEASE")

Problem = tuple[str, int, str]  # (doc, line, what is wrong)


def _code_free(lines: list[str]):
    """(line number, text) outside fenced code blocks, with inline code kept."""
    fence = None
    for n, line in enumerate(lines, 1):
        m = re.match(r"\s*(`{3,}|~{3,})", line)
        if m and (fence is None or m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)):
            fence = None if fence else m.group(1)
            continue
        if fence is None:
            yield n, line


def find(root: Path) -> list[Problem]:
    root = Path(root)
    files = tracked(root)
    known = set(files) | {posixpath.dirname(p) for p in files}
    for p in list(known):  # every parent folder counts as existing
        while p := posixpath.dirname(p):
            known.add(p)
    tops = {p.split("/")[0] for p in files}

    def exists(rel: str) -> bool:
        return rel in known or (root / rel).exists()

    out: list[Problem] = []
    missing: list[Problem] = []
    for doc in filter(is_doc, files):
        if posixpath.basename(doc).upper().startswith(HISTORY):  # history names paths that existed back then
            continue
        try:
            text = (root / doc).read_text(errors="replace")
        except OSError:
            continue
        here = posixpath.dirname(doc)
        for n, line in _code_free(text.splitlines()):
            for raw in LINK.findall(re.sub(r"`[^`\n]*`", "", line)):
                target = unquote(raw.split("#")[0].split("?")[0])
                if not target or SCHEME.match(raw) or raw.startswith(("#", "/", "mailto:")):
                    continue
                rel = posixpath.normpath(posixpath.join(here, target))
                if not rel.startswith("..") and not exists(rel):
                    out.append((doc, n, f"broken link {raw}"))
            for tok in TICK.findall(line):
                t = SUFFIX.sub("", tok.strip()).rstrip("/")
                # only real-looking repo paths: a/b form, top folder exists, no placeholders or globs
                if ("/" not in t or any(c in t for c in " *?<>{}$|=") or SCHEME.match(t)
                        or t.startswith(("~", "/", "-", "@")) or t.split("/")[0] not in tops):
                    continue
                if not any(exists(c) for c in (posixpath.normpath(t), posixpath.normpath(posixpath.join(here, t)))):
                    missing.append((doc, n, t))
    # a path git ignores (build output, local config) is not expected to exist in a checkout
    ignored = set(subprocess.run(["git", "check-ignore", "--no-index", "--stdin"], cwd=root, capture_output=True,
                                 text=True, input="\n".join(t for *_, t in missing)).stdout.splitlines())
    return sorted(out + [(d, n, f"names {t}, which does not exist") for d, n, t in missing if t not in ignored])


def format(problems: list[Problem]) -> str:
    return "\n".join(f"{d}:{n}: {what}" for d, n, what in problems)
