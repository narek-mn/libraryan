import os
import sys
from pathlib import Path

from . import checks, config, gitutil, precommit

REJECTION = """Libraryan: this commit touches documentation managed by Libraryan.
Do not edit these files directly. Write a request file in .libraryan/requests/
instead (see .claude/skills/libraryan-request/SKILL.md); Libraryan will update the docs.
Blocked paths / problems:"""


def _precommit() -> int:
    root = gitutil.repo_root(Path.cwd())
    problems = precommit.check_commit(root, config.load(root), dict(os.environ))
    if not problems:
        return 0
    print(REJECTION, file=sys.stderr)
    for p in problems:
        print(f"  {p}", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "precommit":
        return _precommit()
    if cmd == "postcommit":
        return 0  # Task 5 fills this in
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
    print("usage: libraryan <precommit|postcommit|check>", file=sys.stderr)
    return 2
