"""Run trace: one JSON line per run() loop iteration in .libraryan/state/runs.jsonl."""
import json
import time
from pathlib import Path


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def append(st: Path, record: dict) -> None:
    try:  # the trace is bookkeeping: it must never fail or mask a run
        with open(Path(st) / "runs.jsonl", "a") as f:
            f.write(json.dumps({"ts": _ts(), **record}) + "\n")
    except Exception:
        pass


def read(st: Path, since_ts: str | None = None) -> list[dict]:
    p = Path(st) / "runs.jsonl"
    out = []
    try:
        lines = p.read_text(errors="replace").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            r = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if isinstance(r, dict) and isinstance(r.get("ts"), str) and (since_ts is None or r["ts"] >= since_ts):
            out.append(r)
    return out


def today(st: Path) -> list[dict]:
    d = _ts()[:10]
    return [r for r in read(st) if r["ts"][:10] == d]


def stats(st: Path, days: int = 7) -> str:
    since = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(time.time() - (days - 1) * 86400))
    per: dict[str, list[dict]] = {}
    for r in read(st, since):
        per.setdefault(r["ts"][:10], []).append(r)
    calls = lambda rs: [c for r in rs for c in r.get("calls") or []]
    unknown = lambda rs: sum(c.get("cost_usd") is None for c in calls(rs))
    return "\n".join(
        f"{d} runs={len(rs)} calls={len(calls(rs))} "
        f"commits={sum(r.get('outcome') == 'committed' for r in rs)} "
        f"failures={sum(r.get('outcome') == 'failed' for r in rs)} "
        f"cost=${sum(c.get('cost_usd') or 0 for c in calls(rs)):.2f}" + (f" unknown={unknown(rs)}" if unknown(rs) else "")
        for d, rs in sorted(per.items()))
