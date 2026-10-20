"""Generic runtime: any agent CLI via `runtime_command`, an argv template with {prompt} and {instructions_file}."""
from pathlib import Path

from . import with_instructions

BIN = ""  # the real binary is runtime_command[0]; command() ignores cfg["_bin"]
INSTALL = ("set runtime_command in .libraryan/config.json, e.g. "
           '["aider", "--yes-always", "--no-auto-commits", "--no-dirty-commits", "--message", "{prompt}"]')
AUTH = "whatever the configured tool needs"


def command(role: str, prompt: str, cfg: dict, limits: dict, instructions: Path) -> tuple[list[str], dict]:
    tpl = cfg.get("runtime_command")
    if not tpl:
        raise ValueError("runtime_command is not set in .libraryan/config.json")
    if not any("{instructions_file}" in a for a in tpl):
        prompt = with_instructions(prompt, instructions)
    # ponytail: no budget flags; only the runner timeout bounds the tool
    return [a.replace("{prompt}", prompt).replace("{instructions_file}", str(instructions)) for a in tpl], {}


def parse(out: str, err: str, code: int) -> tuple[str, dict, bool]:
    return out, {"cost_usd": None, "tokens": None, "turns": None, "is_error": code != 0}, code == 0 and out.strip() != ""
