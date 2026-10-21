import argparse
import sys
from pathlib import Path

from . import __version__, check, fix, gitutil


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="libraryan", description="Keep a project's Markdown docs true to its code.")
    ap.add_argument("--version", action="version", version=f"libraryan {__version__}")
    sub = ap.add_subparsers(dest="cmd", metavar="command")
    sub.add_parser("check", help="list broken links and paths that no longer exist (free, no AI, changes nothing)")
    f = sub.add_parser("fix", help="let an AI agent fix the docs; changes are left uncommitted for you to review")
    f.add_argument("--since", metavar="REF", help="only docs affected by code changes since REF, e.g. main")
    f.add_argument("--model", help="model for Claude Code, e.g. sonnet")
    f.add_argument("--budget", type=float, default=5.0, metavar="USD", help="stop after this many dollars (default 5)")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 0
    try:
        root = gitutil.repo_root(Path.cwd())
    except Exception:
        print("libraryan: run this inside a git repository", file=sys.stderr)
        return 1
    if a.cmd == "check":
        problems = check.find(root)
        print(check.format(problems) or "No problems found.")
        return 1 if problems else 0
    return fix.run(root, since=a.since, model=a.model, budget=a.budget)


def entry() -> None:
    sys.exit(main(sys.argv[1:]))
