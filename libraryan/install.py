"""Install, upgrade and uninstall Libraryan in a project."""
import copy
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
from pathlib import Path

from . import config, gitutil, precommit, runner
from .paths import is_protected

crontab_cmd = "crontab"  # tests patch this to a fake; tests never touch the real user crontab
MARK = ".libraryan/bin/libraryan"
HOOKS_PATH = ".libraryan/hooks"
START, END = "<!-- libraryan:start -->", "<!-- libraryan:end -->"
SETTINGS = {"hooks": {
    "PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit",
                    "hooks": [{"type": "command", "command": f'python3 "$CLAUDE_PROJECT_DIR"/{MARK} guard'}]}],
    "SessionStart": [{"hooks": [{"type": "command",
                                 "command": f'python3 "$CLAUDE_PROJECT_DIR"/{MARK} ensure-hooks'}]}],
}}
# everything the installer writes; init/upgrade/uninstall commit only files under these
PATHS = [".libraryan", ".claude/agents/libraryan.md", ".claude/agents/libraryan-reviewer.md",
         ".claude/skills/libraryan-request", ".claude/settings.json", "AGENTS.md", "CLAUDE.md"]


def _ours(entry: dict) -> bool:
    return any(MARK in h.get("command", "") for h in entry.get("hooks", []))


def merge_settings(settings: dict) -> dict:
    s = copy.deepcopy(settings)
    hooks = s.setdefault("hooks", {})
    for event, entries in SETTINGS["hooks"].items():
        if not any(_ours(e) for e in hooks.get(event, [])):
            hooks.setdefault(event, []).extend(copy.deepcopy(entries))
    return s


def strip_settings(settings: dict) -> dict:
    s = copy.deepcopy(settings)
    hooks = s.get("hooks", {})
    for event in list(hooks):
        hooks[event] = [e for e in hooks[event] if not _ours(e)]
        if not hooks[event]:
            del hooks[event]
    if "hooks" in s and not hooks:
        del s["hooks"]
    return s


def _crontab(project: Path, line: str | None) -> None:
    """Replace this project's tagged crontab line with `line` (None removes it)."""
    tag = f"# libraryan:{project}"
    try:
        r = subprocess.run([crontab_cmd, "-l"], capture_output=True, text=True)
        if r.returncode and "no crontab" not in r.stderr.lower():  # unreadable: rewriting would wipe it
            raise OSError(r.stderr.strip() or f"crontab -l exited {r.returncode}")
        lines = [l for l in (r.stdout.splitlines() if r.returncode == 0 else []) if not l.endswith(tag)]
        if line:
            lines.append(f"{line} {tag}")
        subprocess.run([crontab_cmd, "-"], input="".join(l + "\n" for l in lines), text=True, check=True,
                       capture_output=True)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"libraryan: could not update crontab ({e}); edit the `{tag}` line by hand", file=sys.stderr)


def _copy(project: Path, source: Path) -> None:
    """Vendored package, runtime and templates: everything upgrade refreshes."""
    lib = project / ".libraryan"
    for name, src in (("libraryan", "libraryan"), ("bin", "runtime/bin"), ("hooks", "runtime/hooks")):
        shutil.rmtree(lib / name, ignore_errors=True)
        shutil.copytree(source / src, lib / name, ignore=shutil.ignore_patterns("__pycache__"))
    for f in [*(lib / "bin").iterdir(), *(lib / "hooks").iterdir()]:
        f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    for src, dest in (("agents/libraryan.md", ".claude/agents/libraryan.md"),
                      ("agents/libraryan-reviewer.md", ".claude/agents/libraryan-reviewer.md"),
                      ("skills/libraryan-request/SKILL.md", ".claude/skills/libraryan-request/SKILL.md"),
                      ("STYLE.md", ".libraryan/templates/STYLE.md"),
                      ("agents-block.md", ".libraryan/templates/agents-block.md")):  # reviewer's reference
        (project / dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / "templates" / src, project / dest)
    (lib / "requests").mkdir(exist_ok=True)
    (lib / "requests/.gitkeep").touch()
    (lib / ".gitignore").write_text("state/\n__pycache__/\n")


def _files(project: Path) -> list[str]:
    """Installer files present now or in HEAD (so deletions count); gitignored state excluded."""
    now = gitutil.git(project, "ls-files", "-z", "-co", "--exclude-standard", "--", *PATHS)
    head = gitutil.git(project, "ls-tree", "-r", "-z", "--name-only", "HEAD", "--", *PATHS, check=False)
    return sorted({p for p in (now + "\0" + head).split("\0") if p})


def _commit(project: Path, what: str, cfg: dict) -> int:
    """Commit only the installer's files. No hooks: existing docs' lint problems are the setup run's job and
    the user's linters must not judge vendored code; secrets are scanned here instead."""
    files = _files(project)
    if not files:  # an empty pathspec would add and commit the whole tree
        return 0
    gitutil.git(project, "add", "-A", "--", *files)
    staged = [c for c in gitutil.staged_changes(project) if c[1] in set(files) and is_protected(c[1], cfg)]
    if not gitutil.git(project, "diff", "--cached", "--name-only", "--", *files):
        print(f"libraryan: nothing to commit for {what}")
        return 0
    problems = precommit._scan_staged(project, staged)
    if problems:
        print(f"libraryan: {what} aborted, possible secrets:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    r = subprocess.run(["git", "commit", "-q", "--no-verify", "-m", f"docs(libraryan): {what}", "--", *files],
                       cwd=project, env={**os.environ, "LIBRARYAN": "1"}, capture_output=True, text=True)
    if r.returncode:
        print(f"libraryan: {what} commit failed:\n{r.stderr or r.stdout}", file=sys.stderr)
    return r.returncode


def _rollback(project: Path) -> None:
    """Undo init's writes. Installer paths were clean before init, so HEAD is their pre-init state."""
    files = _files(project)
    if not files:
        return
    gitutil.git(project, "reset", "-q", "--", *files, check=False)
    in_head = set(gitutil.git(project, "ls-tree", "-r", "-z", "--name-only", "HEAD", "--", *files,
                              check=False).split("\0"))
    for f in files:
        if f in in_head:
            gitutil.git(project, "checkout", "HEAD", "--", f)
        else:
            (project / f).unlink(missing_ok=True)
            try:
                os.removedirs((project / f).parent)  # prune directories left empty
            except OSError:
                pass


def _dirty(project: Path, cfg: dict, docs: bool = True) -> bool:
    """Uncommitted installer paths (e.g. a request still being written) or, with `docs`, owned docs: they
    would be swept into our commit or deleted."""
    dirty = [p for p in runner._baseline(project)
             if (docs and is_protected(p, cfg)) or any(p == x or p.startswith(x + "/") for x in PATHS)]
    if dirty:
        print("libraryan: commit or stash these changes first:\n  " + "\n  ".join(dirty), file=sys.stderr)
    return bool(dirty)


def _default_branch(project: Path) -> str:
    ref = gitutil.git(project, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
    return ref.split("/", 1)[1] if ref else gitutil.current_branch(project)


def init(project: Path, source: Path, run_setup: bool = True) -> int:
    project, source = Path(project), Path(source)
    branch = _default_branch(project)
    if not runner._on_default(project, {"default_branch": branch}):
        print(f"libraryan: check out the default branch `{branch}` first", file=sys.stderr)
        return 1
    cfg = config.load(project)
    if _dirty(project, cfg):
        return 1
    claude = shutil.which("claude")
    if not claude and run_setup:
        print("libraryan: `claude` not found on PATH; install Claude Code, or use --no-setup", file=sys.stderr)
        return 1
    settings = project / ".claude/settings.json"
    try:
        old = json.loads(settings.read_text()) if settings.exists() else {}
        if not isinstance(old, dict):
            raise ValueError("not a JSON object")
    except ValueError as e:
        print(f"libraryan: .claude/settings.json is not valid ({e}); fix it first", file=sys.stderr)
        return 1
    agents, claude_md = project / "AGENTS.md", project / "CLAUDE.md"
    linked = ((claude_md.is_symlink() and claude_md.resolve() == agents.resolve())
              or (agents.is_symlink() and agents.resolve() == claude_md.resolve()))

    _copy(project, source)
    hooks_path = gitutil.git(project, "config", "--local", "core.hooksPath", check=False)
    if hooks_path and (project / hooks_path).resolve() != (project / HOOKS_PATH).resolve():  # never chain to self
        cfg["chain_hooks_path"] = hooks_path
    if not settings.exists():
        cfg["created_settings"] = True
    cfg.update(default_branch=branch, runner_host=socket.gethostname(), claude_bin=claude or "claude",
               source_path=str(source), claude_md_symlink=linked)
    config.save(project, cfg)
    settings.write_text(json.dumps(merge_settings(old), indent=2) + "\n")
    text = agents.read_text() if agents.exists() else ""
    if START not in text or END not in text:
        block = (source / "templates/agents-block.md").read_text().strip() + "\n"
        agents.write_text(text.rstrip("\n") + "\n\n" + block if text.strip() else block)
    text = claude_md.read_text() if claude_md.exists() else ""
    if not linked and "@AGENTS.md" not in text.splitlines():  # through a link AGENTS.md would import itself
        claude_md.write_text(text.rstrip("\n") + "\n\n@AGENTS.md\n" if text.strip() else "@AGENTS.md\n")
    if _commit(project, "install", cfg):
        _rollback(project)
        print("libraryan: install rolled back; nothing was changed", file=sys.stderr)
        return 1
    # enabled only once the install is committed, so a failed install leaves no hooks or cron behind
    gitutil.git(project, "config", "--local", "core.hooksPath", HOOKS_PATH)
    _crontab(project, f"0 3 * * * cd '{project}' && python3 {MARK} run --reason daily")
    if not run_setup:
        return 0
    code = runner.run(project, config.load(project), "setup", extra_paths=_files(project))
    if code:
        print("libraryan: installed, but the setup run failed (see .libraryan/state/reports/latest.md); retry "
              f"with `python3 {MARK} run --reason setup`", file=sys.stderr)
    return code


def upgrade(project: Path, source: Path) -> int:
    project = Path(project)
    cfg = config.load(project)
    if _dirty(project, cfg):
        return 1
    _copy(project, Path(source))
    config.save(project, cfg)  # adds keys new in DEFAULTS, keeps existing values
    return _commit(project, "upgrade", cfg)


def uninstall(project: Path) -> int:
    project = Path(project)
    cfg = config.load(project)
    if _dirty(project, cfg, docs=False):  # includes untracked requests, which rmtree would destroy
        return 1
    if cfg["chain_hooks_path"]:
        gitutil.git(project, "config", "--local", "core.hooksPath", cfg["chain_hooks_path"])
    else:
        gitutil.git(project, "config", "--local", "--unset", "core.hooksPath", check=False)
    _crontab(project, None)
    agents = project / "AGENTS.md"
    if agents.exists():
        text = re.sub(rf"\n*{re.escape(START)}.*?{re.escape(END)}\n*", "\n\n", agents.read_text(), flags=re.S)
        agents.write_text(text.strip("\n") + "\n" if text.strip() else "")
    settings = project / ".claude/settings.json"
    if settings.exists():
        s = strip_settings(json.loads(settings.read_text()))
        if s == {} and cfg.get("created_settings"):
            settings.unlink()
        else:
            settings.write_text(json.dumps(s, indent=2) + "\n")
    for p in (".claude/agents/libraryan.md", ".claude/agents/libraryan-reviewer.md"):
        (project / p).unlink(missing_ok=True)
    shutil.rmtree(project / ".claude/skills/libraryan-request", ignore_errors=True)
    shutil.rmtree(project / ".libraryan", ignore_errors=True)
    return _commit(project, "uninstall", cfg)
