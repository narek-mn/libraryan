"""`libraryan fix`: an agent fixes the docs in a throwaway copy of the repo; only doc changes come back, uncommitted."""
import itertools
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import check, gitutil, ledger
from .docs import is_doc
from .instructions import INSTRUCTIONS

TOOLS = ("Read,Edit,Write,Glob,Grep,Bash(git log:*),Bash(git diff:*),Bash(git show:*),Bash(git status:*),"
         "Bash(git grep:*),Bash(git ls-files:*),Bash(git rm:*),Bash(git mv:*)")
TIMEOUT_MINUTES = 60


class Progress:
    """A live line on a terminal while the agent works: time so far and docs changed so far. No percentage: the
    agent does not say how much work is left. Silent when stderr is not a terminal."""
    SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, wt: Path):
        self.wt, self.on = wt, sys.stderr.isatty()
        self.stop, self.start, self.docs = threading.Event(), time.monotonic(), 0

    def __enter__(self):
        if self.on:
            threading.Thread(target=self._loop, daemon=True).start()
        return self

    def __exit__(self, kind, *exc):
        if self.on:
            self.stop.set()
            sys.stderr.write(f"\r\033[K{'✗' if kind else '✓'} {self._line()}\n")
            sys.stderr.flush()

    def _line(self) -> str:
        m, s = divmod(int(time.monotonic() - self.start), 60)
        return f"Fixing the docs · {m}:{s:02d} · {self.docs} doc{'s' * (self.docs != 1)} changed so far"

    def _loop(self) -> None:
        for i in itertools.count():
            if i % 10 == 0:
                self.docs = len([p for _, p in _changes(self.wt, stage=False) if is_doc(p)])
            sys.stderr.write(f"\r\033[K{self.SPIN[i % len(self.SPIN)]} {self._line()}")
            sys.stderr.flush()
            if self.stop.wait(1):
                return


def _changes(root: Path, stage: bool = True) -> list[tuple[str, str]]:
    """(A/M/D, path) against HEAD, renames split into a delete and an add."""
    if stage:
        gitutil.git(root, "add", "-A")
        out = gitutil.git(root, "diff", "--cached", "--name-status", "--no-renames", "-z", "HEAD")
        parts = out.split("\0")
        return [(parts[i][0], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]
    out = subprocess.run(["git", "status", "--porcelain", "-z", "--untracked-files=all"], cwd=root,
                         capture_output=True, text=True).stdout  # not stripped: the first status may start with a space
    return [("?", e[3:]) for e in out.split("\0") if len(e) > 3]


def prompt(since: str | None, changed: list[str], problems: list) -> str:
    if since:
        scope = (f"Scope: only docs affected by the code changes in `{since}...HEAD`. Start from "
                 f"`git diff {since}...HEAD`. Changed files:\n" + "\n".join(f"- {p}" for p in changed[:300])
                 + (f"\n- … and {len(changed) - 300} more" if len(changed) > 300 else ""))
    else:
        scope = "Scope: every doc in the repository."
    found = check.format(problems[:200]) or "none"
    return (f"Fix this project's docs. Date: {time.strftime('%Y-%m-%d')}.\n\n{scope}\n\n"
            f"`libraryan check` found:\n{found}\n\nFollow your instructions; end with the final message they describe.")


def _run_agent(cmd: list[str], wt: Path) -> tuple[str, str | None, float | None]:
    """(final message, error or None, cost in USD)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] = "1"  # the JSON result must cover the whole session
    p = subprocess.Popen(cmd, cwd=wt, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, env=env, start_new_session=True)
    try:
        with Progress(wt):
            out, err = p.communicate(timeout=TIMEOUT_MINUTES * 60)
    except BaseException as e:  # timeout or Ctrl-C: stop the agent and everything it started
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.communicate()
        if isinstance(e, subprocess.TimeoutExpired):
            return "", f"stopped after {TIMEOUT_MINUTES} minutes", None
        raise
    try:
        d = json.loads(out)
    except ValueError:
        d = None
    if not isinstance(d, dict):
        tail = next((l.strip() for l in reversed((err + "\n" + out).splitlines()) if l.strip()), "")
        return "", f"claude failed (exit {p.returncode})" + (f": {tail[:300]}" if tail else ""), None
    cost = d.get("total_cost_usd") if isinstance(d.get("total_cost_usd"), (int, float)) else None
    text = d.get("result") if isinstance(d.get("result"), str) else ""
    if d.get("is_error") or p.returncode:
        why = d.get("subtype") or text.strip().splitlines()[-1:] or [f"exit {p.returncode}"]
        return text, f"the agent stopped early ({why if isinstance(why, str) else why[0]})", cost
    return text, None, cost


def run(root: Path, since: str | None = None, model: str | None = None, budget: float = 5.0) -> int:
    root = Path(root)
    claude = shutil.which("claude")
    if not claude:
        print("libraryan: Claude Code is not installed: npm install -g @anthropic-ai/claude-code", file=sys.stderr)
        return 1
    if not gitutil.git(root, "rev-parse", "--verify", "-q", "HEAD", check=False):
        print("libraryan: this repository has no commits yet", file=sys.stderr)
        return 1
    dirty = [p for _, p in _changes(root, stage=False) if is_doc(p)]
    if dirty:  # their edits would be overwritten
        print("libraryan: commit or stash your doc changes first:\n  " + "\n  ".join(dirty), file=sys.stderr)
        return 1
    changed = []
    if since:
        if not gitutil.git(root, "rev-parse", "--verify", "-q", f"{since}^{{commit}}", check=False):
            print(f"libraryan: {since} is not a commit or branch", file=sys.stderr)
            return 1
        changed = [p for p in gitutil.git(root, "diff", "--name-only", "-z", f"{since}...HEAD").split("\0") if p]
        if not changed:
            print(f"Nothing changed since {since}.")
            return 0
    cmd = [claude, "-p", "--append-system-prompt", INSTRUCTIONS, "--permission-mode", "acceptEdits",
           "--allowedTools", TOOLS, "--max-budget-usd", f"{budget:g}", "--output-format", "json",
           *(["--model", model] if model else []), prompt(since, changed, check.find(root))]
    wt = Path(tempfile.mkdtemp(prefix="libraryan-"))
    try:
        gitutil.git(root, "worktree", "add", "-q", "--detach", str(wt), "HEAD")
        text, error, cost = _run_agent(cmd, wt)
        result = _apply(root, wt, text)
    finally:
        gitutil.git(root, "worktree", "remove", "--force", str(wt), check=False)
        shutil.rmtree(wt, ignore_errors=True)
        gitutil.git(root, "worktree", "prune", check=False)
    report(text, error, cost, budget, *result)
    return 1 if error and not result[0] else 0


def _apply(root: Path, wt: Path, text: str) -> tuple[list[tuple[str, str]], dict[str, str], list[str]]:
    """Copy the agent's doc changes into the user's checkout. Returns (applied, kept deletions, ignored)."""
    changes = _changes(wt)
    docs = [(s, p) for s, p in changes if is_doc(p)]
    ignored = [p for _, p in changes if not is_doc(p)]
    deleted = {p: gitutil.git(wt, "show", f"HEAD:{p}", check=False) for s, p in docs if s == "D"}
    blob = lambda rev_path: gitutil.git(wt, "rev-parse", "-q", "--verify", rev_path, check=False)
    new = {blob(f":{p}") for s, p in docs if s == "A"}
    pure_moves = {p for p in deleted if blob(f"HEAD:{p}") in new}
    kept = ledger.check(wt, deleted, pure_moves, ledger.parse(text))
    applied = []
    for s, p in docs:
        if p in kept:
            continue
        dest = root / p
        if s == "D":
            dest.unlink(missing_ok=True)
            try:
                os.removedirs(dest.parent)  # prune folders left empty
            except OSError:
                pass
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(wt / p, dest)
        applied.append((s, p))
    return applied, kept, ignored


def report(text: str, error: str | None, cost: float | None, budget: float, applied, kept, ignored) -> None:
    body = "\n".join(l for l in text.strip().splitlines()
                     if not ledger.MOVED.match(ledger._clean(l)) and not ledger.FACT.match(ledger._clean(l)))
    if body:
        print(body.rstrip() + "\n")
    if error:
        print(f"libraryan: {error}", file=sys.stderr)
        if "budget" in error:
            print(f"libraryan: run again with a higher limit, e.g. --budget {budget * 3:g}", file=sys.stderr)
    for p, why in kept.items():
        print(f"Kept {p}: the agent deleted it but {why}.")
    if ignored:
        print(f"Ignored {len(ignored)} change(s) outside the docs: " + ", ".join(ignored[:10]))
    spent = f" Cost: ${cost:.2f}." if cost is not None else ""
    if not applied:
        print("No doc changes." + spent)
        return
    word = {"A": "new", "M": "changed", "D": "deleted"}
    print(f"Libraryan changed {len(applied)} doc(s). Nothing is committed.{spent}")
    for s, p in applied:
        print(f"  {word.get(s, 'changed'):8} {p}")
    old = [p for s, p in applied if s != "A"]
    added = [p for s, p in applied if s == "A"]
    undo = " && ".join(c for c in (old and "git restore -- " + shlex.join(old),
                                    added and "rm -- " + shlex.join(added)) if c)
    print(f"\nReview: git diff  (new files: git status)\nKeep:   commit them as usual\nUndo:   {undo}")
