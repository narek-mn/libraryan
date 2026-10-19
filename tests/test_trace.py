import json
import time

from libraryan import trace


def test_parse_output_json():
    out = json.dumps({"result": "hi", "total_cost_usd": 0.5, "num_turns": 4})
    assert trace.parse_output(out) == ("hi", {"cost_usd": 0.5, "turns": 4})
    out = json.dumps({"result": "x", "duration_ms": 7, "is_error": False})
    assert trace.parse_output(out) == ("x", {"duration_ms": 7, "is_error": False})


def test_parse_output_plain():
    assert trace.parse_output("hello") == ("hello", {})
    assert trace.parse_output("[1]") == ("[1]", {})


def test_append_and_today(tmp_path):
    trace.append(tmp_path, {"outcome": "noop"})
    trace.append(tmp_path, {"outcome": "committed"})
    trace.append(tmp_path, {"outcome": "old", "ts": "2000-01-01T00:00:00Z"})
    with open(tmp_path / "runs.jsonl", "a") as f:
        f.write("garbage\n")
    assert [r["outcome"] for r in trace.today(tmp_path)] == ["noop", "committed"]
    assert len(trace.read(tmp_path)) == 3
    assert [r["outcome"] for r in trace.read(tmp_path, "2001-01-01T00:00:00Z")] == ["noop", "committed"]


def test_stats_line(tmp_path):
    trace.append(tmp_path, {"outcome": "committed", "calls": [{"role": "author", "cost_usd": 0.5}]})
    trace.append(tmp_path, {"outcome": "failed", "calls": [{"role": "author", "cost_usd": 0.1}]})
    line = trace.stats(tmp_path)
    assert f"{time.strftime('%Y-%m-%d', time.gmtime())} runs=2 calls=2 commits=1 failures=1 cost=$0.60" in line
