import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import audit, cchooks, checks, config, gitutil, install, precommit, runner, trace
from .paths import is_protected, is_request

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
    if cmd == "stats":
        ap = argparse.ArgumentParser(prog="libraryan stats")
        ap.add_argument("--days", type=int, default=7)
        print(trace.stats(runner._state(gitutil.repo_root(Path.cwd())), ap.parse_args(argv[1:]).days))
        return 0
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
        cfg = config.load(root)
        files = [p for p in runner._ls_files(root, "-co", "--exclude-standard")
                 if is_protected(p, cfg) or is_request(p)]
        problems = checks.run_all(root, cfg, files)
        for p in problems:
            print(p)
        return 1 if problems else 0
    if cmd == "audit":
        try:
            root = gitutil.repo_root(Path.cwd())
            print(audit.format(audit.run(root, config.load(root)), cap=10**6))
        except Exception as e:  # findings are leads, never a gate: exit 0 always
            print(f"libraryan audit failed: {e}", file=sys.stderr)
        return 0
    if cmd == "upgrade":  # run the source checkout's own installer so new install logic applies
        root = gitutil.repo_root(Path.cwd())
        source = config.load(root).get("source_path")
        if not source or not (Path(source) / "libraryan.py").is_file():
            print(f"libraryan: source checkout not found at {source!r} (source_path in config)", file=sys.stderr)
            return 1
        return subprocess.run([sys.executable, str(Path(source) / "libraryan.py"), "upgrade"], cwd=root).returncode
    if cmd == "uninstall":
        return install.uninstall(gitutil.repo_root(Path.cwd()))
    print("usage: libraryan <run|wait|precommit|postcommit|check|audit|stats|guard|ensure-hooks|upgrade|uninstall>",
          file=sys.stderr)
    return 2
