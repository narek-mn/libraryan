"""Run trace: one JSON line per run() loop iteration in .libraryan/state/runs.jsonl."""
import json
import time
from pathlib import Path

_USAGE = {"total_cost_usd": "cost_usd", "num_turns": "turns", "duration_ms": "duration_ms", "is_error": "is_error"}


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_output(stdout: str) -> tuple[str, dict]:
    """(text, usage) from `--output-format json` stdout; anything else is plain text with no usage."""
    try:
        d = json.loads(stdout)
    except ValueError:
        return stdout, {}
    if not isinstance(d, dict) or not isinstance(d.get("result"), str):
        return stdout, {}
    return d["result"], {v: d[k] for k, v in _USAGE.items() if k in d}


def append(st: Path, record: dict) -> None:
    with open(Path(st) / "runs.jsonl", "a") as f:
        f.write(json.dumps({"ts": _ts(), **record}) + "\n")


def read(st: Path, since_ts: str | None = None) -> list[dict]:
    p = Path(st) / "runs.jsonl"
    out = []
    for line in p.read_text().splitlines() if p.exists() else []:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and (since_ts is None or r.get("ts", "") >= since_ts):
            out.append(r)
    return out


def today(st: Path) -> list[dict]:
    d = _ts()[:10]
    return [r for r in read(st) if r.get("ts", "")[:10] == d]


def stats(st: Path, days: int = 7) -> str:
    since = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(time.time() - (days - 1) * 86400))
    per: dict[str, list[dict]] = {}
    for r in read(st, since):
        per.setdefault(r["ts"][:10], []).append(r)
    return "\n".join(
        f"{d} runs={len(rs)} calls={sum(len(r.get('calls') or []) for r in rs)} "
        f"commits={sum(r.get('outcome') == 'committed' for r in rs)} "
        f"failures={sum(r.get('outcome') == 'failed' for r in rs)} "
        f"cost=${sum(c.get('cost_usd') or 0 for r in rs for c in r.get('calls') or []):.2f}"
        for d, rs in sorted(per.items()))
