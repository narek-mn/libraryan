import time

from libraryan import trace


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
    assert line == f"{time.strftime('%Y-%m-%d', time.gmtime())} runs=2 calls=2 commits=1 failures=1 cost=$0.60"
    trace.append(tmp_path, {"outcome": "failed", "calls": [{"role": "author", "cost_usd": None}, {"role": "reviewer"}]})
    assert trace.stats(tmp_path).endswith("calls=4 commits=1 failures=2 cost=$0.60 unknown=2")


def test_read_survives_bad_bytes_and_partial_line(tmp_path):
    (tmp_path / "runs.jsonl").write_bytes(b'{"ts": "t", "outcome": "a"}\n\xff\xfe\n{"ts": "t", "outcome": "b"}\n{"outco')
    assert [r["outcome"] for r in trace.read(tmp_path)] == ["a", "b"]


def test_append_never_raises(tmp_path):
    (tmp_path / "runs.jsonl").mkdir()
    trace.append(tmp_path, {"outcome": "x"})
    trace.append(tmp_path / "missing", {"outcome": "x"})


def test_corrupt_lines_ignored(tmp_path):
    trace.append(tmp_path, {"outcome": "committed"})
    with open(tmp_path / "runs.jsonl", "a") as f:
        f.write('{"ts": 5}\n{}\n' + "[" * 100000 + "\n")
    assert [r["outcome"] for r in trace.today(tmp_path)] == ["committed"]
    assert len(trace.read(tmp_path, "2001-01-01T00:00:00Z")) == 1
    trace.stats(tmp_path)
