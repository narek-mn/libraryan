import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__, audit, cchooks, checks, config, gitutil, install, precommit, runner, runtimes, trace
from .paths import is_protected, is_request

USAGE = """usage: libraryan <command>

  init [--no-setup] [--runtime NAME] [--yes]
                      install into this git repo and run the setup (--no-setup: install only;
                      the agent CLI is picked automatically unless --runtime says which;
                      --yes: do not ask before the install commit)
  status              is a proposal waiting? last run's outcome
  review              show what the waiting proposal would change
  approve             commit the waiting proposal
  reject              discard the waiting proposal
  runtime [NAME] [--reviewer]
                      show the agent CLIs in use and found, or switch to NAME
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

def _confirm(files: list[str]) -> bool:
    print("Libraryan will commit these files:\n  " + "\n  ".join(files))
    if not sys.stdin.isatty():
        print("libraryan: no terminal to ask in; rerun with --yes to install without asking", file=sys.stderr)
        return False
    return input("Commit these? [y/N] ").strip().lower() in ("y", "yes")


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


def _runtime(root: Path, name: str | None, reviewer: bool) -> int:
    if name and not (root / config.CONFIG_PATH).is_file():
        print("libraryan: not installed here; run: libraryan init", file=sys.stderr)
        return 1
    cfg = config.load(root)
    if name and not runner._on_default(root, cfg):
        print(f"libraryan: check out the default branch `{cfg['default_branch']}` first", file=sys.stderr)
        return 1
    if name and install._dirty(root, cfg, docs=False):
        return 1
    if name is None:
        def show(n, b):  # `command` has no binary to probe: show what it runs
            if n == "command":
                return f"command custom command ({(cfg['runtime_command'] or ['runtime_command not set'])[0]})"
            return f"{n} {runtimes.detect(n, b) or 'not found'} ({b or runtimes.get(n).BIN})"
        w, r = cfg["runtime"], cfg["reviewer_runtime"]
        print(f"writer:   {show(w, cfg['runtime_bin'])}")
        print(f"reviewer: {show(r, cfg['reviewer_runtime_bin'])}" if r and r != w else f"reviewer: {w} (same as writer)")
        print("found:    " + (", ".join(f"{n} {v}" for n in runtimes.ORDER if (v := runtimes.detect(n))) or "none"))
        return 0
    try:
        adapter = runtimes.get(name)
    except ValueError as e:
        print(f"libraryan: {e}", file=sys.stderr)
        return 1
    if name == "command":
        if not cfg["runtime_command"]:
            print("libraryan: runtime command needs `runtime_command` in .libraryan/config.json", file=sys.stderr)
            return 1
        path = None
    elif not (path := shutil.which(adapter.BIN)) or not runtimes.detect(name, path):
        print(f"libraryan: {name} not found on PATH; install it first: {adapter.INSTALL}", file=sys.stderr)
        return 1
    key, what = ("reviewer_runtime" if reviewer else "runtime"), f"runtime {name}"
    if reviewer and name == cfg["runtime"]:  # same as the writer: back to "same as writer"
        name = path = None
    cfg[key], cfg[key + "_bin"] = name, path
    old = (root / config.CONFIG_PATH).read_text()
    config.save(root, cfg)
    code = install._commit(root, what, cfg)
    if code:  # _commit may have staged it
        gitutil.git(root, "reset", "-q", "--", config.CONFIG_PATH, check=False)
        (root / config.CONFIG_PATH).write_text(old)
    return code


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
        ap.add_argument("--runtime", help="agent CLI to use: " + ", ".join(runtimes.NAMES))
        ap.add_argument("--yes", action="store_true", help="do not ask before the install commit")
        a = ap.parse_args(argv[1:])
        if not PACKAGED:
            print("libraryan: install the tool first: pipx install libraryan", file=sys.stderr)
            return 1
        return install.init(gitutil.repo_root(Path.cwd()), run_setup=not a.no_setup, runtime=a.runtime,
                            confirm=None if a.yes else _confirm)
    if cmd == "status":
        root = gitutil.repo_root(Path.cwd())
        prop, last = runner.proposal(root), (trace.read(runner._state(root)) or [{}])[-1]
        print(f"Proposal waiting: {len(prop['changed'])} file(s) from the {prop['reason']} run of {prop['at']}; "
              "`libraryan review`, then `libraryan approve` or `libraryan reject`" if prop else "No proposal waiting.")
        print(f"Last run: {last.get('ts', 'never')} {last.get('reason', '')} {last.get('outcome', '')}".rstrip()
              + "; report: .libraryan/state/reports/latest.md")
        return 0
    if cmd == "review":
        print(runner.review_text(gitutil.repo_root(Path.cwd())))
        return 0
    if cmd == "approve":
        root = gitutil.repo_root(Path.cwd())
        return runner.approve(root, config.load(root))
    if cmd == "reject":
        return runner.reject(gitutil.repo_root(Path.cwd()))
    if cmd == "runtime":
        ap = argparse.ArgumentParser(prog="libraryan runtime")
        ap.add_argument("name", nargs="?")
        ap.add_argument("--reviewer", action="store_true", help="switch the reviewer's tool only")
        a = ap.parse_args(argv[1:])
        return _runtime(gitutil.repo_root(Path.cwd()), a.name, a.reviewer)
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
