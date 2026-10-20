"""Claude Code: `claude -p --agent …` with the `.claude/agents/` files; JSON output with cost and turns."""
import json
from pathlib import Path

BIN = "claude"
INSTALL = "npm install -g @anthropic-ai/claude-code"
AUTH = "run `claude setup-token` and export CLAUDE_CODE_OAUTH_TOKEN, or set ANTHROPIC_API_KEY"
# no plain rm/mv/mkdir: they reach outside the repository; git rm/mv refuse to
ALLOWED_TOOLS = ("Read,Edit,Write,Glob,Grep,Task,Agent,Bash(git log:*),Bash(git diff:*),Bash(git show:*),"
                 "Bash(git status:*),Bash(git rm:*),Bash(git mv:*),Bash(python3 .libraryan/bin/libraryan check:*),"
                 "Bash(python3 .libraryan/bin/libraryan audit:*)")
REVIEW_TOOLS = "Read,Glob,Grep,Bash(git diff:*),Bash(git show:*),Bash(git log:*),Bash(git status:*)"


def command(role: str, prompt: str, cfg: dict, limits: dict, instructions: Path) -> tuple[list[str], dict]:
    author = role == "author"  # instructions come from --agent (.claude/agents/), not the neutral file
    argv = [cfg["_bin"], "-p", "--agent", "libraryan" if author else "libraryan-reviewer",
            "--permission-mode", "acceptEdits" if author else "default",
            "--allowedTools", ALLOWED_TOOLS if author else REVIEW_TOOLS]
    if model := (cfg.get("model") if author else cfg.get("reviewer_model") or cfg.get("model")):
        argv += ["--model", model]
    # background subagents would make the final JSON report only the last resumed segment's turns and time
    return ([*argv, "--max-budget-usd", str(limits["usd"]), "--output-format", "json", prompt],
            {"CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1"})


def parse(out: str, err: str, code: int) -> tuple[str, dict, bool]:
    try:
        d = json.loads(out)
    except ValueError:
        d = None
    if not isinstance(d, dict):  # fail closed: no final result
        return out, {"cost_usd": None, "tokens": None, "turns": None, "is_error": False}, False
    num = lambda k: d[k] if isinstance(d.get(k), (int, float)) and not isinstance(d[k], bool) else None
    text = d.get("result")
    usage = {"cost_usd": num("total_cost_usd"), "tokens": None, "turns": num("num_turns"),
             "is_error": bool(d.get("is_error"))}
    return text if isinstance(text, str) else "", usage, isinstance(text, str) and not usage["is_error"] and code == 0
