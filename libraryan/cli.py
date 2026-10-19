import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__, audit, cchooks, checks, config, gitutil, install, precommit, runner, trace
from .paths import is_protected, is_request

USAGE = """usage: libraryan <command>

  init [--no-setup]   install into this git repo and run the setup (--no-setup: install only)
  upgrade             refresh the project's vendored copy from this installed version
  uninstall           remove Libraryan (the knowledge base stays)
  run [--reason R]    run now (default reason: manual)
  wait                wait out the debounce window, then run
  check               lint docs and scan for secrets
  audit               docs-vs-code audit (no model call)
  stats [--days N]    per-day runs, commits and cost
  --version           print the version

internal (hooks and cron): precommit, postcommit, guard, ensure-hooks, chainpath"""
PACKAGED = (install.PKG / "_templates").is_dir()  # False in a project's vendored copy

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


def _upgrade() -> int:
    root = gitutil.repo_root(Path.cwd())
    if PACKAGED:
        return install.upgrade(root)
    # vendored copy: the installed tool holds the new version; the env guard stops a vendored bin on PATH looping
    exe = None if os.environ.get("LIBRARYAN_UPGRADING") else shutil.which("libraryan")
    if not exe:
        print("libraryan: install the tool first: pipx install libraryan", file=sys.stderr)
        return 1
    return subprocess.run([exe, "upgrade"], cwd=root, env={**os.environ, "LIBRARYAN_UPGRADING": "1"}).returncode


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if cmd in ("--version", "version"):
        print(f"libraryan {__version__}")
        return 0
    if cmd == "init":
        ap = argparse.ArgumentParser(prog="libraryan init")
        ap.add_argument("--no-setup", action="store_true", help="install only; skip the setup run (no model call)")
        no_setup = ap.parse_args(argv[1:]).no_setup
        if not PACKAGED:
            print("libraryan: install the tool first: pipx install libraryan", file=sys.stderr)
            return 1
        return install.init(gitutil.repo_root(Path.cwd()), run_setup=not no_setup)
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
    if cmd == "upgrade":
        return _upgrade()
    if cmd == "uninstall":
        return install.uninstall(gitutil.repo_root(Path.cwd()))
    print(USAGE, file=sys.stderr)
    return 2


def entry() -> None:
    sys.exit(main(sys.argv[1:]))
