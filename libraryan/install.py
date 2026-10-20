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

from . import __version__, config, gitutil, precommit, runner, runtimes
from .paths import is_protected

PKG = Path(__file__).resolve().parent  # the package, with its data in _runtime/ and _templates/
crontab_cmd = "crontab"  # tests patch this to a fake; tests never touch the real user crontab
MARK = ".libraryan/bin/libraryan"
HOOKS_PATH = ".libraryan/hooks"
START, END = "<!-- libraryan:start -->", "<!-- libraryan:end -->"
# a nested repo or submodule has no Libraryan: its hooks must pass, not fail on a missing script
_HOOK = 'p="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}/%s"; [ -f "$p" ] || exit 0; python3 "$p" ' % MARK
GUARD_CMD, ENSURE_CMD = _HOOK + "guard", _HOOK + "ensure-hooks"


def _cc(event: str, matcher: str) -> dict:
    """Claude Code-style hooks: nested `hooks` lists (Claude, Copilot via .claude, Codex, Gemini, Qwen)."""
    return {event: [{"matcher": matcher, "hooks": [{"type": "command", "command": GUARD_CMD}]}],
            "SessionStart": [{"hooks": [{"type": "command", "command": ENSURE_CMD}]}]}


HOOK_FILES = {  # each tool's project hook file -> the hooks we merge into it
    # Bash (Copilot via .claude: bash): only Libraryan runs are checked for shell writes, see cchooks.SHELL_ESCAPE
    ".claude/settings.json": _cc("PreToolUse", "Edit|Write|MultiEdit|NotebookEdit|apply_patch|Bash|bash"),
    ".codex/hooks.json": _cc("PreToolUse", "Edit|Write|apply_patch|Bash"),
    ".gemini/settings.json": _cc("BeforeTool", "write_file|replace"),
    ".qwen/settings.json": _cc("PreToolUse", "write_file|edit|Write|Edit"),
    ".cursor/hooks.json": {"preToolUse": [{"command": GUARD_CMD, "matcher": "Write|Edit|Delete"}],
                           "sessionStart": [{"command": ENSURE_CMD}]},
}
GEMINI_CONTEXT = ["AGENTS.md", "GEMINI.md"]
OPENCODE_PLUGIN = ".opencode/plugins/libraryan.js"
# everything the installer writes; init/upgrade/uninstall commit only files under these
PATHS = [".libraryan", ".claude/agents/libraryan.md", ".claude/agents/libraryan-reviewer.md",
         ".claude/skills/libraryan-request", *HOOK_FILES, OPENCODE_PLUGIN, "AGENTS.md", "CLAUDE.md"]


def _ours(entry: dict) -> bool:
    return any(MARK in h.get("command", "") for h in [entry, *entry.get("hooks", [])])


def merge_hooks(doc: dict, hooks: dict) -> dict:
    d = copy.deepcopy(doc)
    have = d.setdefault("hooks", {})
    for event, entries in hooks.items():
        if not any(_ours(e) for e in have.get(event, [])):
            have.setdefault(event, []).extend(copy.deepcopy(entries))
    return d


def strip_hooks(doc: dict) -> dict:
    d = copy.deepcopy(doc)
    hooks = d.get("hooks", {})
    for event in list(hooks):
        hooks[event] = [e for e in hooks[event] if not _ours(e)]
        if not hooks[event]:
            del hooks[event]
    if "hooks" in d and not hooks:
        del d["hooks"]
    return d


def _read_hook_files(project: Path) -> dict | None:
    """Each existing hook file's JSON (None if absent); prints and returns None if one is invalid."""
    docs = {}
    for rel in HOOK_FILES:
        p = project / rel
        try:
            docs[rel] = json.loads(p.read_text()) if p.exists() else None
            if docs[rel] is not None and not isinstance(docs[rel], dict):
                raise ValueError("not a JSON object")
        except ValueError as e:
            print(f"libraryan: {rel} is not valid ({e}); fix it first", file=sys.stderr)
            return None
    return docs


def _write_hook_files(project: Path, docs: dict, cfg: dict) -> None:
    """Refresh our entries in every hook file; record the files we create so uninstall can delete them."""
    created = set(cfg.get("created_files", []))
    for rel, hooks in HOOK_FILES.items():
        old = docs[rel]
        if old is None:
            created.add(rel)
        doc = strip_hooks(old or ({"version": 1} if rel == ".cursor/hooks.json" else {}))  # key order stays stable
        if rel == ".gemini/settings.json" and "fileName" not in doc.get("context", {}):
            doc.setdefault("context", {})["fileName"] = GEMINI_CONTEXT  # Gemini reads only GEMINI.md otherwise
        doc = merge_hooks(doc, hooks)
        (project / rel).parent.mkdir(parents=True, exist_ok=True)
        (project / rel).write_text(json.dumps(doc, indent=2) + "\n")
    cfg["created_files"] = sorted(created)


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
    """Vendored package, runtime and templates: everything upgrade refreshes. `source` is the package dir."""
    lib = project / ".libraryan"
    for name, src in (("libraryan", ""), ("bin", "_runtime/bin"), ("hooks", "_runtime/hooks"),
                      ("policies", "_runtime/policies")):
        if (lib / name).exists():
            shutil.rmtree(lib / name)
        shutil.copytree(source / src, lib / name,
                        ignore=shutil.ignore_patterns("__pycache__", "_runtime", "_templates"))
        for p in [lib / name, *(lib / name).rglob("*")]:  # a read-only package (e.g. Nix) must not block upgrades
            p.chmod(p.stat().st_mode | stat.S_IWUSR)
    for f in [*(lib / "bin").iterdir(), *(lib / "hooks").iterdir()]:
        f.chmod(0o755)  # explicit: a wheel install may not keep the executable bit
    for src, dest in (("agents/libraryan.md", ".claude/agents/libraryan.md"),
                      ("agents/libraryan-reviewer.md", ".claude/agents/libraryan-reviewer.md"),
                      ("skills/libraryan-request/SKILL.md", ".claude/skills/libraryan-request/SKILL.md"),
                      ("STYLE.md", ".libraryan/templates/STYLE.md"),
                      ("agents-block.md", ".libraryan/templates/agents-block.md")):  # reviewer's reference
        (project / dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / "_templates" / src, project / dest)
    (project / OPENCODE_PLUGIN).parent.mkdir(parents=True, exist_ok=True)
    (project / OPENCODE_PLUGIN).write_text((source / "_templates/opencode-plugin.js").read_text()
                                           .replace("__GUARD_CMD__", json.dumps(GUARD_CMD)))
    neutral_agents(project, source)
    (lib / "requests").mkdir(exist_ok=True)
    (lib / "requests/.gitkeep").touch()
    (lib / ".gitignore").write_text("state/\n__pycache__/\n")


def neutral_agents(project: Path, source: Path) -> None:
    """Tool-neutral instructions for non-Claude runtimes: the agent files' bodies without frontmatter."""
    for name in ("libraryan", "libraryan-reviewer"):
        body = (source / "_templates/agents" / f"{name}.md").read_text()
        (project / ".libraryan/agents").mkdir(parents=True, exist_ok=True)
        (project / ".libraryan/agents" / f"{name}.md").write_text(re.sub(r"\A---\n.*?\n---\n\s*", "", body, flags=re.S))


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


def init(project: Path, source: Path = PKG, run_setup: bool = True, runtime: str | None = None,
         confirm=None) -> int:
    """`confirm(files)` asks the user before the install commit (the CLI passes one; None: no question)."""
    project, source = Path(project), Path(source)
    branch = _default_branch(project)
    if not runner._on_default(project, {"default_branch": branch}):
        print(f"libraryan: check out the default branch `{branch}` first", file=sys.stderr)
        return 1
    reinstall = (project / config.CONFIG_PATH).is_file()
    cfg = config.load(project)
    if _dirty(project, cfg):
        return 1
    name = runtime or (cfg["runtime"] if reinstall else None) or runtimes.pick()  # a re-run keeps the chosen tool
    if not name and run_setup:
        print("libraryan: no supported agent CLI found. Install one of:", file=sys.stderr)
        for n in runtimes.ORDER:
            print(f"  {n}: {runtimes.get(n).INSTALL}", file=sys.stderr)
        return 1
    name = name or "claude"  # --no-setup with nothing installed
    try:
        adapter = runtimes.get(name)
    except ValueError as e:
        print(f"libraryan: {e}", file=sys.stderr)
        return 1
    if name == "command" and not cfg["runtime_command"]:
        print("libraryan: --runtime command needs `runtime_command` in .libraryan/config.json", file=sys.stderr)
        return 1
    kept = cfg["runtime_bin"] if reinstall and not runtime and name == cfg["runtime"] else None
    rbin = kept if kept and os.access(kept, os.X_OK) else shutil.which(adapter.BIN) if adapter.BIN else None
    if runtime and run_setup and adapter.BIN and not rbin:
        print(f"libraryan: {name} not found on PATH; install it first: {adapter.INSTALL}", file=sys.stderr)
        return 1
    docs = _read_hook_files(project)
    if docs is None:
        return 1
    agents, claude_md = project / "AGENTS.md", project / "CLAUDE.md"
    linked = ((claude_md.is_symlink() and claude_md.resolve() == agents.resolve())
              or (agents.is_symlink() and agents.resolve() == claude_md.resolve()))

    _copy(project, source)
    hooks_path = gitutil.git(project, "config", "--local", "core.hooksPath", check=False)
    if hooks_path and (project / hooks_path).resolve() != (project / HOOKS_PATH).resolve():  # never chain to self
        cfg["chain_hooks_path"] = hooks_path
    _write_hook_files(project, docs, cfg)
    cfg.update(default_branch=branch, runner_host=socket.gethostname(), runtime=name, runtime_bin=rbin,
               claude_md_symlink=linked, installed_version=__version__)
    config.save(project, cfg)
    text = agents.read_text() if agents.exists() else ""
    if START not in text or END not in text:
        block = (source / "_templates/agents-block.md").read_text().strip() + "\n"
        agents.write_text(text.rstrip("\n") + "\n\n" + block if text.strip() else block)
    text = claude_md.read_text() if claude_md.exists() else ""
    if not linked and "@AGENTS.md" not in text.splitlines():  # through a link AGENTS.md would import itself
        claude_md.write_text(text.rstrip("\n") + "\n\n@AGENTS.md\n" if text.strip() else "@AGENTS.md\n")
    if confirm and not confirm(_files(project)):
        _rollback(project)
        print("libraryan: nothing was installed", file=sys.stderr)
        return 1
    if _commit(project, "install", cfg):
        _rollback(project)
        print("libraryan: install rolled back; nothing was changed", file=sys.stderr)
        return 1
    # enabled only once the install is committed, so a failed install leaves no hooks or cron behind
    gitutil.git(project, "config", "--local", "core.hooksPath", HOOKS_PATH)
    _crontab(project, f"0 3 * * * cd '{project}' && python3 {MARK} run --reason daily")
    print(f"Runtime: {name} {runtimes.detect(name, rbin) or 'not found'}; {adapter.AUTH}")
    print("Teammates' tools: Codex runs the edit guard once the project and the hook are trusted (`/hooks`), "
          "Gemini and Copilot once the folder is trusted; until then the git lock covers every tool.")
    if not run_setup:
        return 0
    cfg = config.load(project)
    print(f"Setup running (can take up to {cfg['setup_timeout_minutes']} minutes); "
          "report: .libraryan/state/reports/latest.md", flush=True)
    code = runner.run(project, cfg, "setup", extra_paths=_files(project))
    if code:
        why = "".join(f"\n  - {p}" for p in runner.problems(project)) or "\n  - (no reason recorded)"
        print(f"libraryan: installed, but the setup run failed:{why}\n"
              f"Check that {name} works and is logged in ({adapter.AUTH}), then retry with "
              f"`python3 {MARK} run --reason setup`. Full report: .libraryan/state/reports/latest.md", file=sys.stderr)
    elif runner.proposal(project):
        print("Setup finished. See what it wants to change with `libraryan review`, "
              "then `libraryan approve` (commit) or `libraryan reject`.")
    return code


def _version(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split("."))
    except (AttributeError, ValueError):  # missing or non-numeric: never block on it
        return ()


def upgrade(project: Path, source: Path = PKG) -> int:
    project = Path(project)
    if not (project / config.CONFIG_PATH).is_file():
        print("libraryan: not installed here; run: libraryan init", file=sys.stderr)
        return 1
    cfg = config.load(project)
    have = cfg.get("installed_version")
    if _version(have) > _version(__version__):
        print(f"libraryan: this project has Libraryan {have}, newer than {__version__}; "
              "run `pipx upgrade libraryan` first", file=sys.stderr)
        return 1
    if _dirty(project, cfg):
        return 1
    docs = _read_hook_files(project)
    if docs is None:
        return 1
    _copy(project, Path(source))
    _write_hook_files(project, docs, cfg)
    cfg.pop("source_path", None)  # pre-0.2 key: an absolute path on someone's machine
    cfg["installed_version"] = __version__
    config.save(project, cfg)  # adds keys new in DEFAULTS, keeps existing values
    return _commit(project, "upgrade", cfg)


def uninstall(project: Path) -> int:
    project = Path(project)
    cfg = config.load(project)
    if _dirty(project, cfg, docs=False):  # includes untracked requests, which rmtree would destroy
        return 1
    docs = _read_hook_files(project)
    if docs is None:  # before anything changes, so uninstall never stops halfway
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
    created = set(cfg.get("created_files", [])) | ({".claude/settings.json"} if cfg.get("created_settings") else set())
    for rel in HOOK_FILES:
        p = project / rel
        if docs[rel] is None:
            continue
        doc = strip_hooks(docs[rel])
        # ponytail: a user's own identical context.fileName goes too; record ours in cfg if that ever matters
        if rel == ".gemini/settings.json" and doc.get("context", {}).get("fileName") == GEMINI_CONTEXT:
            del doc["context"]["fileName"]
            if not doc["context"]:
                del doc["context"]
        if rel in created and doc in ({}, {"version": 1}):
            p.unlink()
        else:
            p.write_text(json.dumps(doc, indent=2) + "\n")
    for p in (".claude/agents/libraryan.md", ".claude/agents/libraryan-reviewer.md", OPENCODE_PLUGIN):
        (project / p).unlink(missing_ok=True)
    shutil.rmtree(project / ".claude/skills/libraryan-request", ignore_errors=True)
    shutil.rmtree(project / ".libraryan", ignore_errors=True)
    return _commit(project, "uninstall", cfg)
