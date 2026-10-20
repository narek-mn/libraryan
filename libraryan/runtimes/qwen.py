"""Qwen Code (researched against @qwen-code/qwen-code 0.25.3): `qwen -o json`, a Claude-like result with no cost.

Permissions cannot be set per run (rules live in settings files, which Libraryan must not write), so only
--approval-mode and --allowed/--exclude-tools are used. ponytail: the author gets run_shell_command unrestricted
(tool-name syntax only is verified; argument patterns like `run_shell_command(git log)` are UNVERIFIED)."""
import json
from pathlib import Path

from . import with_instructions

BIN = "qwen"
INSTALL = "npm install -g @qwen-code/qwen-code"
AUTH = "export OPENAI_API_KEY (and OPENAI_BASE_URL, or another provider's key); Qwen OAuth's free tier has ended"


def command(role: str, prompt: str, cfg: dict, limits: dict, instructions: Path) -> tuple[list[str], dict]:
    author = role == "author"
    argv = [cfg["_bin"], "-o", "json", "--max-session-turns", str(limits["turns"])]
    argv += ["--approval-mode", "auto-edit", "--allowed-tools", "run_shell_command"] if author else \
            ["--approval-mode", "default", "--exclude-tools", "write_file,edit,run_shell_command"]
    if model := (cfg.get("model") if author else cfg.get("reviewer_model") or cfg.get("model")):
        argv += ["-m", model]
    return [*argv, "-p", with_instructions(prompt, instructions)], {}  # explicit -p (deprecated but works): a positional prompt after the variadic tool lists could be read as a tool name


def parse(out: str, err: str, code: int) -> tuple[str, dict, bool]:
    try:
        d = json.loads(out)
    except ValueError:
        d = None
    if isinstance(d, list):  # the array of messages ends with the result
        d = next((m for m in reversed(d) if isinstance(m, dict) and m.get("type") == "result"), None)
    if not isinstance(d, dict):  # fail closed: no final result
        return out, {"cost_usd": None, "tokens": None, "turns": None, "is_error": False}, False
    num = lambda v: v if isinstance(v, int) and not isinstance(v, bool) else None
    u = d.get("usage") if isinstance(d.get("usage"), dict) else {}
    tokens = num(u.get("total_tokens")) or (None if num(u.get("input_tokens")) is None else
                                            u["input_tokens"] + (num(u.get("output_tokens")) or 0))
    text = d.get("result")
    usage = {"cost_usd": None, "tokens": tokens, "turns": num(d.get("num_turns")), "is_error": bool(d.get("is_error"))}
    return text if isinstance(text, str) else "", usage, isinstance(text, str) and not usage["is_error"] and code == 0
