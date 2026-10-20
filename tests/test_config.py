import json

from libraryan import config


def test_claude_bin_alias(tmp_path):
    (tmp_path / ".libraryan").mkdir()
    (tmp_path / config.CONFIG_PATH).write_text(json.dumps({"claude_bin": "/x/claude"}))
    cfg = config.load(tmp_path)
    assert cfg["runtime_bin"] == "/x/claude" and "claude_bin" not in cfg and cfg["runtime"] == "claude"
    (tmp_path / config.CONFIG_PATH).write_text(json.dumps({"claude_bin": "/x/claude", "runtime_bin": "/y/c"}))
    assert config.load(tmp_path)["runtime_bin"] == "/y/c"
