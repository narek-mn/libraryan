import copy
import json
from pathlib import Path

CONFIG_PATH = ".libraryan/config.json"

DEFAULTS = {
    "version": 1,
    "kb_root": "docs/kb",
    "default_branch": "main",
    "runner_host": "",
    "runtime": "claude",
    "runtime_bin": None,
    "reviewer_runtime": None,
    "reviewer_runtime_bin": None,
    "runtime_command": None,
    "model": None,
    "debounce_minutes": 10,
    "run_timeout_minutes": 30,
    "setup_timeout_minutes": 120,
    "max_usd_run": 5,
    "max_usd_setup": 25,
    "max_usd_review": 2,
    "max_usd_review_setup": 10,
    "max_turns_run": 60,
    "max_turns_setup": 200,
    "max_turns_review": 30,
    "ask_before_commit": True,
    "independent_review": True,
    "reviewer_model": None,
    "review_timeout_minutes": 15,
    "max_runs_per_day": 24,
    "max_commits_per_day": 12,
    "max_consecutive_failures": 3,
    "max_consecutive_transient_failures": 10,
    "language": "en",
    "owned": ["**/*.md", ".claude/skills/**", ".cursor/rules/**", ".github/copilot-instructions.md"],
    "excluded": ["**/node_modules/**", "**/vendor/**", "**/fixtures/**", "**/testdata/**", "**/templates/**", "**/.venv/**"],
    "exempt": [],
    "chain_hooks_path": None,
}


def load(root: Path) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    p = Path(root) / CONFIG_PATH
    if p.exists():
        stored = json.loads(p.read_text())
        old = stored.pop("claude_bin", None)  # 0.2.x name
        cfg.update(stored)
        cfg["runtime_bin"] = cfg["runtime_bin"] or old
    return cfg


def save(root: Path, cfg: dict) -> None:
    p = Path(root) / CONFIG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2) + "\n")
