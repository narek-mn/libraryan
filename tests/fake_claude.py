"""Stand-in for `claude -p --output-format json`: runs the scripted file actions in its cwd, then prints a result."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

s = json.loads(Path(os.environ["FAKE_CLAUDE_SCRIPT"]).read_text())
Path(os.environ["FAKE_CLAUDE_LOG"]).write_text(json.dumps(sys.argv[1:]))
for a in s["actions"]:
    if a[0] == "write":
        Path(a[1]).parent.mkdir(parents=True, exist_ok=True)
        Path(a[1]).write_text(a[2])
    elif a[0] == "git":
        subprocess.run(["git", *a[1:]], check=True, capture_output=True)
    elif a[0] == "sleep":
        time.sleep(a[1])
if s.get("crash"):
    print("boom: not logged in", file=sys.stderr)
    sys.exit(1)
print(json.dumps({"type": "result", "subtype": s.get("subtype", "success"), "is_error": s.get("is_error", False),
                  "result": s["result"], "total_cost_usd": 0.42, "num_turns": 3}))
sys.exit(s.get("exit", 0))
