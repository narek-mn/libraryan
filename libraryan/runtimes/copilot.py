"""GitHub Copilot CLI (researched against @github/copilot 1.0.100): `copilot -p --output-format json`, JSONL events.

`--agent` loads the installed `.claude/agents/libraryan*.md`, so the instructions are never prepended. Permissions are
--allow-tool/--deny-tool patterns (deny wins); every list flag uses `--flag=value` so nothing can swallow the prompt.
No cost in USD (--max-ai-credits is credits, not USD, so unused) and no turn flag. ponytail: shell patterns for the
author are `shell(cmd:*)` forms (documented, only `shell(git commit)` verified); GPT-family models use `apply_patch`,
whose coverage by `write` is UNVERIFIED. --trust-folder is needed or repo agents/hooks silently do not load."""
import json
from pathlib import Path

BIN = "copilot"
INSTALL = "npm install -g @github/copilot  (Node.js 22+)"
AUTH = "export COPILOT_GITHUB_TOKEN (fine-grained PAT with the 'Copilot Requests' permission; classic ghp_ tokens are unsupported)"
AUTHOR_SHELL = ("git log:*", "git diff:*", "git show:*", "git status:*", "git rm:*", "git mv:*",
                "python3 .libraryan/bin/libraryan check:*", "python3 .libraryan/bin/libraryan audit:*")
REVIEW_SHELL = ("git diff:*", "git show:*", "git log:*", "git status:*")


def command(role: str, prompt: str, cfg: dict, limits: dict, instructions: Path) -> tuple[list[str], dict]:
    author = role == "author"
    allow = ["read", *(["write"] if author else [])] + [f"shell({c})" for c in (AUTHOR_SHELL if author else REVIEW_SHELL)]
    deny = ["shell(git commit)", "shell(git push)"] if author else ["write"]
    argv = [cfg["_bin"], "--agent", "libraryan" if author else "libraryan-reviewer", "--output-format", "json",
            "--no-ask-user", "--trust-folder", "--no-auto-update", *(f"--allow-tool={t}" for t in allow),
            *(f"--deny-tool={t}" for t in deny)]
    if model := (cfg.get("model") if author else cfg.get("reviewer_model") or cfg.get("model")):
        argv += ["--model", model]
    return [*argv, "-p", prompt], {"COPILOT_AUTO_UPDATE": "false"}


def parse(out: str, err: str, code: int) -> tuple[str, dict, bool]:
    evs = []
    for line in out.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            evs.append(e)
    text = ""
    for e in evs:
        if e.get("type") == "assistant.message" and isinstance(c := (e.get("data") or {}).get("content"), str):
            text = c
    result = [e for e in evs if e.get("type") == "result"]
    failed = any(e.get("type") == "session.error" for e in evs)
    turns = sum(e.get("type") == "assistant.turn_start" for e in evs)
    usage = {"cost_usd": None, "tokens": None, "turns": turns or None, "is_error": failed}
    ok = bool(result) and result[-1].get("exitCode") == 0 and not failed and text.strip() != "" and code == 0
    return text or (out if not evs else ""), usage, ok
