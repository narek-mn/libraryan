"""Cursor CLI, EXPERIMENTAL (researched against build 2026.10.19-6bbf2c4): `agent -p --output-format json`.

The writer needs --force (print mode only proposes changes otherwise); the reviewer uses --mode ask, never --force.
Cursor has no --agent flag, so the instructions are prepended. is_error is always false in Cursor's output and is not
trusted: success means exit 0 and JSON with subtype "success" and a non-empty result. No cost, turn or budget exists.
ponytail: .cursor/cli.json deny rules (git commit/push) are not written, so the writer's only guards are the runner's own
checks; --trust is passed because a fresh cron checkout may prompt (whether print mode prompts is UNVERIFIED)."""
import json
from pathlib import Path

from . import with_instructions

BIN = "agent"  # also installed as `cursor-agent`
INSTALL = "curl https://cursor.com/install -fsS | bash"
AUTH = "export CURSOR_API_KEY"


def command(role: str, prompt: str, cfg: dict, limits: dict, instructions: Path) -> tuple[list[str], dict]:
    author = role == "author"
    argv = [cfg["_bin"], "-p", "--output-format", "json", "--trust", *(["--force"] if author else ["--mode", "ask"])]
    if model := (cfg.get("model") if author else cfg.get("reviewer_model") or cfg.get("model")):
        argv += ["--model", model]
    return [*argv, with_instructions(prompt, instructions)], {}


def parse(out: str, err: str, code: int) -> tuple[str, dict, bool]:
    try:
        d = json.loads(out)
    except ValueError:
        d = None
    usage = {"cost_usd": None, "tokens": None, "turns": None, "is_error": False}
    if not isinstance(d, dict):  # failures print no JSON
        return out, usage, False
    text = d.get("result")
    good = d.get("subtype") == "success"
    usage["is_error"] = not good
    return (text if isinstance(text, str) else ""), usage, good and isinstance(text, str) and text.strip() != "" and code == 0
