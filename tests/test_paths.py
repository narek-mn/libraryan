from libraryan import config
from libraryan.paths import glob_match, is_protected, is_request

D = config.DEFAULTS


def test_glob_match():
    assert glob_match("README.md", "**/*.md")
    assert glob_match("a/b/c.md", "**/*.md")
    assert not glob_match("a/b.txt", "**/*.md")
    assert glob_match("x/node_modules/y/z.md", "**/node_modules/**")
    assert glob_match("a.md", "?.md")
    assert not glob_match("a/b.md", "*.md")
    assert not glob_match("ab.md", "?.md")


def test_is_protected():
    assert is_protected("docs/kb/x.md", D)
    assert not is_protected("src/fixtures/a.md", D)
    assert not is_protected(".libraryan/requests/r.md", D)
    assert is_protected(".libraryan/config.json", D)
    assert not is_protected("src/main.py", D)
    assert is_protected(".claude/skills/foo/SKILL.md", D)


def test_exempt():
    cfg = {**D, "exempt": ["CHANGELOG.md"]}
    assert not is_protected("CHANGELOG.md", cfg)
    assert is_protected("CHANGELOG.md", D)


def test_is_request():
    assert is_request(".libraryan/requests/r.md")
    assert not is_request("docs/kb/x.md")


def test_config_load_save(tmp_path):
    assert config.load(tmp_path) == D
    cfg = {**D, "model": "opus", "exempt": ["X.md"]}
    config.save(tmp_path, cfg)
    assert config.load(tmp_path) == cfg
    assert (tmp_path / ".libraryan/config.json").read_text().endswith("}\n")


def test_repo_fixture(repo):
    assert (repo / "README.md").exists()
