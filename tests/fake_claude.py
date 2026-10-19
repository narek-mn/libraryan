#!/usr/bin/env python3
"""Stand-in for `claude` in runner tests: edits the KB and prints a summary."""
import os
from pathlib import Path

Path(".libraryan/state/fake_claude_ran").write_text("")
with open("docs/kb/index.md", "a") as f:
    f.write("- updated by fake claude\n")
if os.environ.get("FAKE_CLAUDE_BADNOTE"):
    Path("docs/kb/bad.md").write_text("no frontmatter here\n")
print("SUMMARY ok")
