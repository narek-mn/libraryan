"""Runtime adapters: one module per agent CLI, each with BIN, INSTALL, AUTH, command() and parse()."""
import importlib
import subprocess
from pathlib import Path
from types import ModuleType

NAMES = ("claude", "codex", "gemini", "qwen", "copilot", "opencode", "cursor", "command")
ORDER = NAMES[:7]  # auto-detect order


def get(name: str) -> ModuleType:
    if name not in NAMES:
        raise ValueError(f"unknown runtime {name!r}; one of: {', '.join(NAMES)}")
    return importlib.import_module(f"{__name__}.{name}")


def detect(name: str, bin: str | None = None) -> str | None:
    """First line of `<bin> --version`, None if the tool is missing or broken."""
    try:
        p = subprocess.run([bin or get(name).BIN, "--version"], capture_output=True, text=True, timeout=10,
                           stdin=subprocess.DEVNULL)
        return (p.stdout.strip().splitlines() or [None])[0] if p.returncode == 0 else None
    except Exception:
        return None


def pick() -> str | None:
    return next((n for n in ORDER if detect(n)), None)


def with_instructions(prompt: str, instructions: Path) -> str:
    """For tools with no agent-file flag: the instructions go in front of the prompt."""
    try:
        return f"{Path(instructions).read_text().rstrip()}\n\n---\n\n{prompt}"
    except OSError:
        return prompt
