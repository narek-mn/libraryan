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

from . import config, gitutil, runner
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


def _commit(project: Path, what: str) -> int:
    files = _files(project)
    gitutil.git(project, "add", "-A", "--", *files)
    if not gitutil.git(project, "diff", "--cached", "--name-only", "--", *files):
        print(f"libraryan: nothing to commit for {what}")
        return 0
    r = subprocess.run(["git", "commit", "-q", "-m", f"docs(libraryan): {what}", "--", *files], cwd=project,
                       env={**os.environ, "LIBRARYAN": "1"}, capture_output=True, text=True)
    if r.returncode:
        print(f"libraryan: {what} commit failed:\n{r.stderr or r.stdout}", file=sys.stderr)
    return r.returncode


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
    dirty = [p for p in runner._baseline(project) if is_protected(p, cfg)]
    if dirty:
        print("libraryan: commit or stash these documentation changes first:\n  " + "\n  ".join(dirty),
              file=sys.stderr)
        return 1
    claude = shutil.which("claude")
    if not claude and run_setup:
        print("libraryan: `claude` not found on PATH; install Claude Code, or use --no-setup", file=sys.stderr)
        return 1

    _copy(project, source)
    hooks_path = gitutil.git(project, "config", "core.hooksPath", check=False)
    if hooks_path and (project / hooks_path).resolve() != (project / HOOKS_PATH).resolve():  # never chain to self
        cfg["chain_hooks_path"] = hooks_path
    settings = project / ".claude/settings.json"
    if not settings.exists():
        cfg["created_settings"] = True
    cfg.update(default_branch=branch, runner_host=socket.gethostname(), claude_bin=claude or "claude",
               source_path=str(source))
    config.save(project, cfg)
    old = json.loads(settings.read_text()) if settings.exists() else {}
    settings.write_text(json.dumps(merge_settings(old), indent=2) + "\n")
    agents = project / "AGENTS.md"
    text = agents.read_text() if agents.exists() else ""
    if START not in text or END not in text:
        block = (source / "templates/agents-block.md").read_text().strip() + "\n"
        agents.write_text(text.rstrip("\n") + "\n\n" + block if text.strip() else block)
    claude_md = project / "CLAUDE.md"
    text = claude_md.read_text() if claude_md.exists() else ""
    if "@AGENTS.md" not in text.splitlines():
        claude_md.write_text(text.rstrip("\n") + "\n\n@AGENTS.md\n" if text.strip() else "@AGENTS.md\n")
    gitutil.git(project, "config", "core.hooksPath", HOOKS_PATH)
    _crontab(project, f"0 3 * * * cd '{project}' && python3 {MARK} run --reason daily")

    if not run_setup:
        return _commit(project, "install")
    code = runner.run(project, config.load(project), "setup", extra_paths=_files(project))
    if gitutil.git(project, "status", "--porcelain", "--", *_files(project)):
        # setup failed: commit the install anyway so the lock is consistent; setup can be retried on its own
        print("libraryan: setup run failed (see .libraryan/state/reports/latest.md); retry with "
              f"`python3 {MARK} run --reason setup`", file=sys.stderr)
        return _commit(project, "install") or 1
    return code


def upgrade(project: Path, source: Path) -> int:
    project = Path(project)
    _copy(project, Path(source))
    config.save(project, config.load(project))  # adds keys new in DEFAULTS, keeps existing values
    return _commit(project, "upgrade")


def uninstall(project: Path) -> int:
    project = Path(project)
    cfg = config.load(project)
    if cfg["chain_hooks_path"]:
        gitutil.git(project, "config", "core.hooksPath", cfg["chain_hooks_path"])
    else:
        gitutil.git(project, "config", "--unset", "core.hooksPath", check=False)
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
    return _commit(project, "uninstall")
