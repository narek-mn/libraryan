"""Gemini CLI (researched against @google/gemini-cli 0.64.0): `gemini -p -o json`, policy files instead of tool flags.

Trust comes from GEMINI_CLI_TRUST_WORKSPACE (the untrusted-folder exit 55 otherwise). Plan mode is never used: headless
`exit_plan_mode` is auto-approved and switches to yolo. No USD, turn or token flag exists (maxSessionTurns is settings-only)."""
import json
from pathlib import Path

from . import with_instructions

BIN = "gemini"
INSTALL = "npm install -g @google/gemini-cli"
AUTH = "export GEMINI_API_KEY (or GOOGLE_API_KEY, or the Vertex AI variables)"


def command(role: str, prompt: str, cfg: dict, limits: dict, instructions: Path) -> tuple[list[str], dict]:
    author = role == "author"  # relative policy path: the runner starts the tool in a worktree with the committed .libraryan/
    argv = [cfg["_bin"], "-o", "json", "--approval-mode", "auto_edit" if author else "default",
            "--policy", f".libraryan/policies/gemini-{'author' if author else 'reviewer'}.toml"]
    if model := (cfg.get("model") if author else cfg.get("reviewer_model") or cfg.get("model")):
        argv += ["-m", model]
    return [*argv, "-p", with_instructions(prompt, instructions)], {"GEMINI_CLI_TRUST_WORKSPACE": "true"}


def parse(out: str, err: str, code: int) -> tuple[str, dict, bool]:
    try:
        d = json.loads(out)
    except ValueError:
        d = None
    if not isinstance(d, dict):  # fatal errors print `[ERROR] {...}` to stderr and leave stdout empty
        return out, {"cost_usd": None, "tokens": None, "turns": None, "is_error": False}, False
    models = (d.get("stats") or {}).get("models")
    totals = [t for m in models.values() if isinstance(m, dict) and isinstance(t := (m.get("tokens") or {}).get("total"), int)
              and not isinstance(t, bool)] if isinstance(models, dict) else []
    tokens = sum(totals) if totals else None
    text = d.get("response")
    failed = "error" in d
    usage = {"cost_usd": None, "tokens": tokens, "turns": None, "is_error": failed}
    return (text if isinstance(text, str) else ""), usage, isinstance(text, str) and text.strip() != "" and not failed and code == 0
