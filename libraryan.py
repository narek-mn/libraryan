#!/usr/bin/env python3
"""Libraryan source CLI: install, upgrade or uninstall Libraryan in the git repo containing the current directory."""
import argparse
import sys
from pathlib import Path

from libraryan import gitutil, install

SOURCE = Path(__file__).resolve().parent


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="libraryan.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="install into this repo and run setup").add_argument(
        "--no-setup", action="store_true", help="install only; skip the setup run (no model call)")
    sub.add_parser("upgrade", help="refresh the vendored runtime, hooks, agent and skill files")
    sub.add_parser("uninstall", help="remove Libraryan (the knowledge base stays)")
    args = ap.parse_args(argv)
    root = gitutil.repo_root(Path.cwd())
    if args.cmd == "init":
        return install.init(root, SOURCE, run_setup=not args.no_setup)
    if args.cmd == "upgrade":
        return install.upgrade(root, SOURCE)
    return install.uninstall(root)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
