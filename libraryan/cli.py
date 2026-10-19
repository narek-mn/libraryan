import argparse
import json
import os
import sys
from pathlib import Path

from . import cchooks, checks, config, gitutil, precommit, runner

def _precommit() -> int:
    root = gitutil.repo_root(Path.cwd())
    problems = precommit.check_commit(root, config.load(root), dict(os.environ))
    if not problems:
        return 0
    print(precommit.REJECTION, file=sys.stderr)
    for p in problems:
        print(f"  {p}", file=sys.stderr)
    return 1


def _guard() -> int:
    try:
        payload = json.load(sys.stdin)
        root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or gitutil.repo_root(Path(payload.get("cwd") or ".")))
        code, msg = cchooks.guard(payload, root, config.load(root), dict(os.environ))
    except Exception:  # never crash the user's session
        return 0
    if msg:
        print(msg, file=sys.stderr)
    return code


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "precommit":
        return _precommit()
    if cmd == "guard":
        return _guard()
    if cmd == "ensure-hooks":
        try:
            cchooks.ensure_hooks(gitutil.repo_root(Path.cwd()))
        except Exception:  # never break session start
            pass
        return 0
    if cmd == "postcommit":
        try:
            root = gitutil.repo_root(Path.cwd())
            runner.post_commit(root, config.load(root), dict(os.environ))
        except Exception:  # never fail the user's commit
            pass
        return 0
    if cmd == "run":
        ap = argparse.ArgumentParser(prog="libraryan run")
        ap.add_argument("--reason", default="manual")
        root = gitutil.repo_root(Path.cwd())
        return runner.run(root, config.load(root), ap.parse_args(argv[1:]).reason)
    if cmd == "wait":
        root = gitutil.repo_root(Path.cwd())
        runner.wait(root, config.load(root))
        return 0
    if cmd == "chainpath":
        root = gitutil.repo_root(Path.cwd())
        print(config.load(root)["chain_hooks_path"] or "")
        return 0
    if cmd == "check":
        root = gitutil.repo_root(Path.cwd())
        files = gitutil.git(root, "ls-files", "-co", "--exclude-standard").splitlines()
        problems = checks.run_all(root, config.load(root), files)
        for p in problems:
            print(p)
        return 1 if problems else 0
    print("usage: libraryan <run|wait|precommit|postcommit|check|guard|ensure-hooks>", file=sys.stderr)
    return 2
