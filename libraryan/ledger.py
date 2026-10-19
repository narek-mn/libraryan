"""Deletion ledger: where each deleted owned doc's facts went (spec §5.1)."""
import difflib
import re
import subprocess
from pathlib import Path

from .paths import is_protected

MOVED = re.compile(r"^Moved: `?(.+?)`? => `?(.+?)`?\s*$")
FACT = re.compile(r"^Fact: `?(.+?)`? => `?(.+?)`? \| (.+?)\s*$")
MIN_QUOTE = 15


def _norm(s: str) -> str:
    return " ".join(s.split())


def parse(text: str) -> dict:
    out = {"moved": {}, "facts": [], "none": {}, "lines": []}
    for line in text.splitlines():
        line = line.strip()
        if m := MOVED.match(line):
            out["moved"][m[1]] = m[2]
        elif m := FACT.match(line):
            parts = [s.strip() for s in m[3].split("|", 1)]
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
    return f.read_text(errors="replace") if f.is_file() else None


def _head(root: Path, path: str) -> str:
    return subprocess.run(["git", "show", f"HEAD:{path}"], cwd=root, capture_output=True).stdout.decode(
        errors="replace")


def _dest_problem(root: Path, cfg: dict, dest: str) -> str | None:
    if not is_protected(dest, cfg):
        return f"{dest} is not owned by Libraryan"
    if _read(root, dest) is None:
        return f"{dest} does not exist"
    return None


def _fact_problem(root: Path, cfg: dict, fact: dict, original: str) -> str | None:
    if err := _dest_problem(root, cfg, fact["dest"]):
        return err
    src, dst = _norm(fact["src_quote"]), _norm(fact["dest_quote"])
    if len(src) < MIN_QUOTE or len(dst) < MIN_QUOTE:
        return f"quotes must be at least {MIN_QUOTE} characters"
    if src not in _norm(original):
        return f"quote not found in the deleted file: {fact['src_quote']!r}"
    if dst not in _norm(_read(root, fact["dest"])):
        return f"quote not found in {fact['dest']}: {fact['dest_quote']!r}"
    return None


def check(root: Path, cfg: dict, deleted: list[str], snap: dict, after: dict, parsed: dict) -> list[str]:
    # a new request is never committed by Libraryan, so a doc "moved" there would be lost
    new_blobs = {b for p, b in after.items() if b and snap.get(p) is None and is_protected(p, cfg)}
    problems = []
    for path in deleted:
        if snap.get(path) and snap[path] in new_blobs:  # pure move
            continue
        if path in parsed["none"]:
            continue
        original = _head(root, path)
        errors = []
        if new := parsed["moved"].get(path):
            err = _dest_problem(root, cfg, new)
            if not err and difflib.SequenceMatcher(None, original, _read(root, new)).ratio() < 0.5:
                err = f"{new} is less than 50% similar to the deleted file"
            if not err:
                continue
            errors.append(err)
        facts = [f for f in parsed["facts"] if f["deleted"] == path]
        fact_errors = [e for f in facts if (e := _fact_problem(root, cfg, f, original))]
        if len(fact_errors) < len(facts):  # at least one valid Fact line
            continue
        errors += fact_errors
        problems.append(f"deletion ledger: {path}: "
                        + ("; ".join(errors) or "no Moved: or Fact: line says where its facts went"))
    return problems
