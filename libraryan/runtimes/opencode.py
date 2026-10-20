"""OpenCode (researched against opencode-ai 1.19.3; flags and event shapes are pinned to that version, the 2.x rewrite differs):
`opencode run --format json`, NDJSON events with no final result object, so parse() aggregates them.

Permissions come from the OPENCODE_PERMISSION env (last matching rule wins, so "*" is first); headless `ask` is auto-rejected,
so --auto is never used. The writer is the default agent, the reviewer the read-only built-in `plan` agent plus an edit/bash
deny. No agent files are installed for OpenCode, so the instructions are prepended. No turn or USD flag exists on `run`."""
import json
from pathlib import Path

from . import with_instructions

BIN = "opencode"
INSTALL = "npm install -g opencode-ai"
AUTH = "export the provider's key (e.g. ANTHROPIC_API_KEY, OPENAI_API_KEY); detected automatically"
AUTHOR_PERM = {"edit": "allow", "bash": {"*": "allow", "git commit*": "deny", "git push*": "deny"}}
REVIEW_PERM = {"edit": "deny", "bash": {"*": "deny", "git diff*": "allow", "git show*": "allow", "git log*": "allow",
                                        "git status*": "allow"}}


def command(role: str, prompt: str, cfg: dict, limits: dict, instructions: Path) -> tuple[list[str], dict]:
    author = role == "author"
    argv = [cfg["_bin"], "run", "--format", "json", *([] if author else ["--agent", "plan"])]
    if model := (cfg.get("model") if author else cfg.get("reviewer_model") or cfg.get("model")):
        argv += ["-m", model]
    return ([*argv, with_instructions(prompt, instructions)],
            {"OPENCODE_PERMISSION": json.dumps(AUTHOR_PERM if author else REVIEW_PERM),
             "OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_CLAUDE_CODE": "1"})


def parse(out: str, err: str, code: int) -> tuple[str, dict, bool]:
    text, costs, tokens, finishes, failed, reason = "", [], 0, 0, False, None
    for line in out.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        part, t = e.get("part") or {}, e.get("type")
        if t == "step_start":
            text = ""  # the answer is the last step's text
        elif t == "text" and isinstance(part.get("text"), str):
            text += part["text"]
        elif t == "step_finish":
            finishes += 1
            reason = part.get("reason")  # the last step's: anything but "stop" (e.g. "length") left the work unfinished
            if isinstance(c := part.get("cost"), (int, float)) and not isinstance(c, bool):
                costs.append(c)
            tk = part.get("tokens") or {}
            tokens += sum(v for k in ("input", "output") if isinstance(v := tk.get(k), int) and not isinstance(v, bool))
        elif t == "error":
            failed = True
    usage = {"cost_usd": sum(costs) if costs else None, "tokens": tokens or None, "turns": finishes or None, "is_error": failed}
    return text, usage, reason == "stop" and text.strip() != "" and not failed and code == 0
