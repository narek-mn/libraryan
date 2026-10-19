"""Deterministic docs-vs-code audit: no model, no edits. Paths only, never symbols."""
import posixpath
import re
import subprocess
from pathlib import Path

from . import checks, gitutil
from .paths import is_protected

Finding = tuple[str, str, str]  # (kind, path, detail)
EXTS = set(".py .js .ts .tsx .jsx .go .rs .java .kt .c .h .cpp .hpp .cs .rb .php .sh .md .json .yaml .yml .toml "
           ".ini .cfg .env .sql .proto .txt".split())
MAX_BYTES = 2_000_000  # a huge doc is audited on its head only
FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
TICK = re.compile(r"`([^`\n]+)`")
SUFFIX = re.compile(r"(?:#L\d+(?:-L?\d+)?|:\d+(?:-\d+)?)$")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def frontmatter(text: str) -> dict[str, str | list[str]]:
    m = re.match(r"---\n(.*?\n)?---(?:\n|$)", text.replace("\r\n", "\n"), re.S)
    out: dict = {}
    key = None
    for line in (m.group(1) or "").splitlines() if m else []:
        if km := re.match(r"(\w+):\s*(.*?)\s*$", line):
            key, v = km.group(1), km.group(2)
            out[key] = ([x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
                        if v.startswith("[") and v.endswith("]") else v.strip("'\""))
        elif key and (bm := re.match(r"\s*-\s+(.*?)\s*$", line)):
            out[key] = (out[key] if isinstance(out[key], list) else []) + [bm.group(1).strip("'\"")]
    for k in ("sources", "tags"):
        if isinstance(out.get(k), str):
            out[k] = [out[k]] if out[k] else []
    return out


def looks_like_path(token: str) -> bool:
    t = SUFFIX.sub("", token.strip())
    if (not t or any(c in t for c in " *<>${") or checks.SCHEME.match(t) or "://" in t
            or t.startswith(("~", "/", "@"))):  # @file: a Claude Code import
        return False
    return "/" in t or posixpath.splitext(t)[1] in EXTS


def _read(p: Path) -> str | None:
    try:
        with open(p, "rb") as f:
            return f.read(MAX_BYTES).decode("utf-8", "replace").replace("\r\n", "\n")
    except OSError:
        return None


def run(root: Path, cfg: dict) -> list[Finding]:
    root, kb = Path(root), cfg["kb_root"].strip("/")
    files = sorted(set(p for p in gitutil.git(root, "ls-files", "-z", "-co", "--exclude-standard").split("\0") if p))
    listed = set(files)
    names = {posixpath.basename(p) for p in files}
    dates: dict[str, str] = {}

    def exists(tok: str, rel: str) -> bool:
        t = SUFFIX.sub("", tok.strip()).rstrip("/")
        if "/" not in t:  # bare file name: any file of that name counts
            return t in names or (root / t).exists()
        cands = {posixpath.normpath(t), posixpath.normpath(posixpath.join(posixpath.dirname(rel), t))}
        return any(c in listed or (root / c).exists() for c in cands)

    def last_change(src: str) -> str:
        if src not in dates:  # ponytail: one git log per distinct source; batch if KBs grow to thousands
            r = subprocess.run(["git", "log", "-1", "--format=%cs", "--", src], cwd=root,
                               capture_output=True, text=True)
            dates[src] = r.stdout.strip() if r.returncode == 0 else ""
        return dates[src]

    from .install import PATHS  # here: install imports runner, which imports this module
    # Libraryan's own installed files are not the project's docs (and the agent may not edit them)
    own = tuple(p for p in PATHS if p.startswith(".claude/")) + (".libraryan/",)
    docs = [p for p in files if p.endswith(".md") and is_protected(p, cfg)
            and not any(p == o or p.startswith(o.rstrip("/") + "/") for o in own)]
    index = _read(root / kb / "index.md")
    indexed = {r for _, r in checks._links(root, f"{kb}/index.md", index)} if index else set()
    out: list[Finding] = []
    titles: dict[str, str] = {}
    for rel in docs:
        text = _read(root / rel)
        if text is None:
            continue
        out += [("broken-link", rel, raw) for raw, res in checks._links(root, rel, text) if not (root / res).exists()]
        out += [("missing-path", rel, tok) for tok in TICK.findall(FENCE.sub("", text))
                if looks_like_path(tok) and not exists(tok, rel)]
        if not rel.startswith(kb + "/") or posixpath.basename(rel) in checks.SPECIAL:
            continue
        fm = frontmatter(text)
        if rel not in indexed:
            out.append(("not-indexed", rel, f"not linked from {kb}/index.md"))
        sources = fm.get("sources") or []
        if not sources:
            out.append(("unsourced", rel, "no sources"))
        updated = DATE.match(fm.get("updated") if isinstance(fm.get("updated"), str) else "")
        for src in sources:
            if not looks_like_path(src):
                continue  # `commit <sha>`, URLs, prose
            if not exists(src, rel):
                out.append(("missing-source", rel, src))
            elif updated and (d := last_change(SUFFIX.sub("", src))) > updated.group():
                out.append(("stale", rel, f"{src} changed {d}, note updated {updated.group()}"))
        title = fm.get("title")
        if isinstance(title, str) and title.strip():
            norm = " ".join(title.casefold().split())
            if norm in titles:
                out.append(("duplicate-title", rel, f"same title as {titles[norm]}"))
            else:
                titles[norm] = rel
    return sorted(set(out))


def format(findings: list[Finding], cap: int = 100) -> str:
    lines = [f"{k} {p}: {d}" for k, p, d in findings[:cap]]
    if len(findings) > cap:
        lines.append(f"… and {len(findings) - cap} more")
    return "\n".join(lines) or "- (none)"
