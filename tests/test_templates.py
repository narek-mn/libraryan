import re
from pathlib import Path

from libraryan import checks, runner

T = Path(__file__).resolve().parent.parent / "templates"
FILES = ["agents/libraryan.md", "agents/libraryan-reviewer.md", "skills/libraryan-request/SKILL.md",
         "agents-block.md", "STYLE.md"]


def frontmatter(rel):
    m = re.match(r"---\n(.*?)\n---\n", (T / rel).read_text(), re.S)
    assert m, f"{rel}: no frontmatter"
    return dict(re.findall(r"^(\w+):\s*(.*)$", m.group(1), re.M))


def test_files_exist():
    for rel in FILES:
        assert (T / rel).is_file(), rel


def test_agent_frontmatter():
    for rel in ("agents/libraryan.md", "agents/libraryan-reviewer.md"):
        fm = frontmatter(rel)
        assert fm.get("name") and fm.get("description"), rel
    assert frontmatter("agents/libraryan.md")["name"] == "libraryan"
    assert frontmatter("agents/libraryan-reviewer.md")["name"] == "libraryan-reviewer"


def test_skill_name():
    assert frontmatter("skills/libraryan-request/SKILL.md")["name"] == "libraryan-request"


def test_agents_block_markers():
    text = (T / "agents-block.md").read_text().strip()
    assert text.startswith("<!-- libraryan:start -->")
    assert text.endswith("<!-- libraryan:end -->")


def test_agent_key_phrases():
    text = (T / "agents/libraryan.md").read_text()
    for phrase in ("data, never instructions", "libraryan-reviewer", "python3 .libraryan/bin/libraryan check",
                   "Possible code issues", "Discard: <path>", "baseline",
                   "Installer files", "@AGENTS.md"):
        assert phrase in text, phrase


def test_symlinked_claude_md_exception():
    assert "unless the prompt says CLAUDE.md is a symlink" in (T / "agents/libraryan.md").read_text()
    rev = (T / "agents/libraryan-reviewer.md").read_text()
    assert "when the prompt says CLAUDE.md is a symlink" in rev and "replaced by a regular file" in rev


def test_no_relative_md_links():
    # templates are installed elsewhere; relative links would break lint in the install commit
    for rel in FILES:
        text = (T / rel).read_text()
        assert not [l for l in checks.LINK.findall(text) if not checks.SCHEME.match(l)], rel


def test_allowed_tools_can_delete_and_move():
    tools = runner.ALLOWED_TOOLS.split(",")
    assert "Bash(git rm:*)" in tools and "Bash(git mv:*)" in tools


def test_mid_run_advice_in_rejection_and_block():
    from libraryan import precommit
    advice = "If you did not edit these files, Libraryan may be mid-run"
    for text in (precommit.REJECTION, (T / "agents-block.md").read_text()):
        assert advice in text and "git restore --staged <file>" in text and "--no-verify" in text
    assert "this commit" not in precommit.REJECTION  # also shown by the Claude Code guard, before any commit
