"""OpenAI Codex CLI (researched against codex-cli 0.163.0): `codex exec --json`, JSONL events, no USD or turn limits."""
import json
from pathlib import Path

from . import with_instructions

BIN = "codex"
INSTALL = "npm install -g @openai/codex"
AUTH = "run `codex login --device-auth`, or export CODEX_API_KEY"


def command(role: str, prompt: str, cfg: dict, limits: dict, instructions: Path) -> tuple[list[str], dict]:
    author = role == "author"
    argv = [cfg["_bin"], "exec", "--json", "-s", "workspace-write" if author else "read-only"]  # runs in a git worktree
    if model := (cfg.get("model") if author else cfg.get("reviewer_model") or cfg.get("model")):
        argv += ["-m", model]
    # ponytail: the prompt is one argv element (~128 KB Linux limit); no budget flags exist, only the runner timeout
    return [*argv, with_instructions(prompt, instructions)], {}


def parse(out: str, err: str, code: int) -> tuple[str, dict, bool]:
    text, tokens, turns, failed = None, None, 0, False
    for line in out.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        t, item = e.get("type"), e.get("item")
        if t == "turn.started":
            turns += 1
        elif t == "turn.failed":
            failed = True
        elif t == "turn.completed" and isinstance(e.get("usage"), dict):
            u = e["usage"]
            tokens = (tokens or 0) + sum(v for k in ("input_tokens", "output_tokens")
                                         if isinstance(v := u.get(k), int) and not isinstance(v, bool))
        elif t == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message" \
                and isinstance(item.get("text"), str):
            text = item["text"]  # item.type "error" is only a warning
    usage = {"cost_usd": None, "tokens": tokens, "turns": turns or None, "is_error": failed}
    return text or "", usage, text is not None and not failed and code == 0
