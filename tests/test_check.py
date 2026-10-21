from conftest import git
from libraryan import check
from libraryan.cli import main


def test_clean_repo(repo, capsys):
    assert main(["check"]) == 0
    assert capsys.readouterr().out == "No problems found.\n"


def test_broken_link_and_missing_path(repo, capsys):
    (repo / "docs/guide.md").write_text(
        "# Guide\n\nSee [old](old.md), [setup](setup.md) and [site](https://x.org/a.md).\n"
        "Code is in `src/app.py`; the worker was `src/worker.py:run`.\n")
    assert main(["check"]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "docs/guide.md:3: broken link old.md",
        "docs/guide.md:4: names src/worker.py, which does not exist"]


def test_ignores_code_blocks_placeholders_and_tool_folders(repo):
    (repo / ".gitignore").write_text("build/\n")
    (repo / "docs/guide.md").write_text(
        "```\nsrc/gone.py [x](gone.md)\n```\n"
        "`src/<name>.py` `src/*.py` `~/x/y` `/etc/hosts` `other/thing.py` `build/out.bin` `--flag=a/b`\n"
        "[top](#top) [mail](mailto:a@b.c) <https://x.org>\n")
    (repo / ".claude/skills/x").mkdir(parents=True)
    (repo / ".claude/skills/x/SKILL.md").write_text("[gone](gone.md) `src/gone.py`\n")
    (repo / "node_modules/pkg").mkdir(parents=True)
    (repo / "node_modules/pkg/README.md").write_text("[gone](gone.md)\n")
    assert check.find(repo) == []


def test_links_to_folders_and_images(repo):
    (repo / "docs/img.png").write_bytes(b"x")
    (repo / "docs/guide.md").write_text("![i](img.png) [src](../src/) [no](../nope/) [setup](./setup.md#install)\n")
    assert check.find(repo) == [("docs/guide.md", 1, "broken link ../nope/")]


def test_outside_a_repo(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["check"]) == 1
    assert "inside a git repository" in capsys.readouterr().err


def test_changelog_is_history(repo):
    (repo / "CHANGELOG.md").write_text("## 0.1\n\n- Removed `src/old.py` and [the guide](docs/guide.md).\n")
    assert check.find(repo) == []
