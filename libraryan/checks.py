import posixpath
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote

KEYS = ("title", "type", "updated", "sources")
SPECIAL = ("index.md", "log.md", "STYLE.md")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
SECRETS = [re.compile(p) for p in (
    r"(?<![A-Za-z0-9_-])AKIA[0-9A-Z]{16}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"(?<![A-Za-z0-9_-])gh[pousr]_[A-Za-z0-9]{36}",
    r"(?<![A-Za-z0-9_-])github_pat_[A-Za-z0-9_]{20,}",
    r"(?<![A-Za-z0-9_-])sk-(ant-)?[A-Za-z0-9_-]{20,}",
    r"(?<![A-Za-z0-9_-])xox[abprs]-[A-Za-z0-9-]{10,}",
    r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}",
    # values that look like placeholders (`<your-token>`, `${API_KEY}`, `changeme`) are documentation, not secrets
    r"(?i)(password|secret|api[_-]?key|token)\s*[:=]\s*['\"]"
    r"(?![^'\"\s]*(?:[<${]|your|example|change|placeholder|dummy|xxxx))[^'\"\s]{8,}['\"]",
)]


def _links(root: Path, rel: str, text: str) -> list[tuple[str, str]]:
    """(raw link, repo-relative resolved path) for relative .md links."""
    out = []
    text = re.sub(r"`[^`\n]*`", "", re.sub(r"```.*?(?:```|\Z)", "", text, flags=re.S))  # code is not links
    for raw in LINK.findall(text):
        target = unquote(raw.split("#")[0])
        if not target or SCHEME.match(raw) or target.startswith("/") or not target.endswith(".md"):
            continue
        out.append((raw, posixpath.normpath(posixpath.join(posixpath.dirname(rel), target))))
    return out


def lint(root: Path, cfg: dict, files: list[str]) -> list[str]:
    root, kb = Path(root), cfg["kb_root"].strip("/")
    problems = []
    index = root / kb / "index.md"
    indexed = {r for _, r in _links(root, f"{kb}/index.md", index.read_text())} if index.exists() else set()
    for rel in files:
        p = root / rel
        if not rel.endswith(".md") or not p.is_file():
            continue
        text = p.read_text(errors="replace").replace("\r\n", "\n")
        for raw, res in _links(root, rel, text):
            if not (root / res).exists():
                problems.append(f"{rel}: broken link {raw}")
        if rel.startswith(kb + "/") and posixpath.basename(rel) not in SPECIAL:
            m = re.match(r"---\n(.*?\n)?---(?:\n|$)", text, re.S)
            have = set(re.findall(r"^(\w+):", m.group(1) or "", re.M)) if m else set()
            missing = [k for k in KEYS if k not in have]
            if missing:
                problems.append(f"{rel}: missing frontmatter {', '.join(missing)}")
            if rel not in indexed:
                problems.append(f"{rel}: not linked from {kb}/index.md")
    return problems


def scan_text(text: str, label: str) -> list[str]:
    """`label:line: possible secret (abcd…)`: enough to find it, never the whole value."""
    return [f"{label}:{text.count(chr(10), 0, m.start()) + 1}: possible secret ({m.group()[:4]}…)"
            for rx in SECRETS for m in rx.finditer(text)]


def scan_secrets(root: Path, files: list[str]) -> list[str]:
    root, problems = Path(root), []
    gitleaks = shutil.which("gitleaks")
    for rel in files:
        p = root / rel
        if not p.is_file():
            continue
        if gitleaks:
            r = subprocess.run([gitleaks, "detect", "--no-git", "--source", str(p)], capture_output=True)
            if r.returncode:
                problems.append(f"{rel}: possible secret (gitleaks)")
        else:
            problems += scan_text(p.read_text(errors="replace"), rel)
    return problems


def run_all(root: Path, cfg: dict, files: list[str]) -> list[str]:
    return lint(root, cfg, files) + scan_secrets(root, files)
