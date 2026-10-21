"""Deletion ledger: a doc is deleted only when the agent shows, with quotes we can check, where its facts went."""
import difflib
import re
from pathlib import Path

MOVED = re.compile(r"^Moved: `?(.+?)`? => `?(.+?)`?\s*$")
FACT = re.compile(r"^Fact: `?(.+?)`? => `?(.+?)`? \| (.+?)\s*$")
MIN_QUOTE = 15


def _clean(line: str) -> str:
    """A line without a list bullet or wrapping backticks."""
    line = re.sub(r"^[-*+]\s+", "", line.strip())
    return line[1:-1].strip() if len(line) > 1 and line[0] == line[-1] == "`" else line


def _unquote(s: str) -> str:
    return s.strip().strip("\"“”'`").strip()


def _norm(s: str) -> str:
    return " ".join(s.split())


def parse(text: str) -> dict:
    out = {"moved": {}, "facts": [], "none": {}, "lines": []}
    for line in map(_clean, text.splitlines()):
        if m := MOVED.match(line):
            out["moved"][m[1]] = m[2]
        elif m := FACT.match(line):
            parts = [_unquote(s) for s in m[3].split("|", 1)]
            if m[2] == "none":
                out["none"][m[1]] = m[3]
            elif len(parts) == 2:
                out["facts"].append({"deleted": m[1], "dest": m[2], "src_quote": parts[0], "dest_quote": parts[1]})
            else:
                continue
        else:
            continue
        out["lines"].append(line)
    return out


def _read(root: Path, path: str) -> str | None:
    f = Path(root) / path
    return f.read_text(errors="replace") if path.endswith(".md") and f.is_file() else None


def _fact_problem(root: Path, fact: dict, original: str) -> str | None:
    dest = _read(root, fact["dest"])
    if dest is None:
        return f"{fact['dest']} is not a doc that exists"
    src, dst = _norm(fact["src_quote"]), _norm(fact["dest_quote"])
    if len(src) < MIN_QUOTE or len(dst) < MIN_QUOTE:
        return f"quotes must be at least {MIN_QUOTE} characters"
    if src not in _norm(original):
        return f"quote not found in the deleted file: {fact['src_quote']!r}"
    if dst not in _norm(dest):
        return f"quote not found in {fact['dest']}: {fact['dest_quote']!r}"
    return None


def check(root: Path, deleted: dict[str, str], pure_moves: set[str], parsed: dict) -> dict[str, str]:
    """{deleted path: why it must be kept}. `deleted` maps each deleted doc to its old text; `pure_moves` are
    deleted docs whose exact content is now in a new file, which need no ledger line."""
    problems = {}
    for path, original in deleted.items():
        if path in pure_moves or path in parsed["none"]:
            continue
        errors = []
        if new := parsed["moved"].get(path):
            text = _read(root, new)
            if text is None:
                errors.append(f"{new} is not a doc that exists")
            elif difflib.SequenceMatcher(None, original, text).ratio() < 0.5:
                errors.append(f"{new} is less than 50% similar to the deleted file")
            else:
                continue
        facts = [f for f in parsed["facts"] if f["deleted"] == path]
        fact_errors = [e for f in facts if (e := _fact_problem(root, f, original))]
        if len(fact_errors) < len(facts):  # at least one checked Fact line
            continue
        errors += fact_errors
        problems[path] = "; ".join(errors) or "the agent did not say where its facts went"
    return problems
