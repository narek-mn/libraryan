#!/usr/bin/env python3
"""Stand-in for `claude` in runner tests: edits the KB and prints a summary.

FAKE_CLAUDE_MODE (comma-separated) adds misbehaviour/races for specific tests."""
import os
import subprocess
import sys
import time
from pathlib import Path

modes = os.environ.get("FAKE_CLAUDE_MODE", "").split(",")
Path(".libraryan/state/fake_claude_ran").write_text("")
Path(".libraryan/state/fake_claude_prompt").write_text(sys.argv[-1])
with open("docs/kb/index.md", "a") as f:
    f.write("- updated by fake claude\n")
if "badnote" in modes:
    Path("docs/kb/bad.md").write_text("no frontmatter here\n")
if "unicode" in modes:
    Path("docs/kb/գիտելիք.md").write_text("---\ntitle: t\ntype: note\nupdated: 2026-10-19\nsources: [x]\n---\nbody\n")
    with open("docs/kb/index.md", "a") as f:
        f.write("- [գիտելիք](գիտելիք.md)\n")
if "race_request" in modes:  # consume pending requests, while another agent writes a new one
    for p in Path(".libraryan/requests").glob("*.md"):
        p.unlink()
    Path(".libraryan/requests/other-agent.md").write_text("in progress\n")
if "commit" in modes:  # another agent commits code during the run
    Path("src.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "src.py"], check=True)
    subprocess.run(["git", "commit", "-qm", "code"], check=True)
if "checkout" in modes:  # another agent switches branch during the run
    subprocess.run(["git", "checkout", "-qb", "feature"], check=True)
if "sleep" in modes:
    time.sleep(5)
if "gitrm" in modes:  # processed request deleted the way the agent does it
    subprocess.run(["git", "rm", "-qf", "--", ".libraryan/requests/20261019-120000-x.md"], check=True)
if "gitmv" in modes:  # loose doc moved into the KB
    subprocess.run(["git", "mv", "docs/a.md", "docs/kb/a.md"], check=True)
    with open("docs/kb/index.md", "a") as f:
        f.write("- [A](a.md)\n")
if "rm_restore" in modes:  # deletion undone after a reviewer rejection
    text = Path("README.md").read_text()
    subprocess.run(["git", "rm", "-q", "--", "README.md"], check=True)
    Path("README.md").write_text(text)
discard = []
if "discard" in modes:  # reviewer rejected a new note
    Path("docs/kb/x.md").write_text("rejected\n")
    discard.append("docs/kb/x.md")
if "discard_existing" in modes:
    discard.append("docs/kb/index.md")
print("SUMMARY ok")
for p in discard:
    print(f"Discard: {p}")
