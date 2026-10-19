#!/usr/bin/env python3
"""Stand-in for `claude` in runner tests: edits the KB and prints a summary.

FAKE_CLAUDE_MODE (comma-separated) adds misbehaviour/races for specific tests."""
import json
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
if "stage_request" in modes:  # another agent stages a fresh request during the run
    Path(".libraryan/requests/other-agent.md").write_text("staged\n")
    subprocess.run(["git", "add", ".libraryan/requests/other-agent.md"], check=True)
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
if "codeedit" in modes:  # the agent strays into code
    Path("app.py").write_text("x = 2\n")
    subprocess.run(["git", "rm", "-q", "--", "util.py"], check=True)
if "env" in modes:
    Path(".libraryan/state/fake_claude_env").write_text("\n".join(sorted(os.environ)))
if "spawn" in modes:  # a tool subprocess that outlives a killed parent unless the group is killed
    child = subprocess.Popen(["sleep", "30"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    Path(".libraryan/state/fake_claude_child").write_text(str(child.pid))
    time.sleep(30)
discard = []
if "discard" in modes:  # reviewer rejected a new note
    Path("docs/kb/x.md").write_text("rejected\n")
    discard.append("docs/kb/x.md")
if "discard_existing" in modes:
    discard.append("docs/kb/index.md")
text = "SUMMARY ok\n" + "".join(f"Discard: {p}\n" for p in discard)
if "--output-format" in sys.argv and "nojson" not in modes:
    print(json.dumps({"type": "result", "result": text, "total_cost_usd": 0.01, "num_turns": 3,
                      "duration_ms": 100, "is_error": False}))
else:
    print(text, end="")
