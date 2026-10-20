import re
from pathlib import Path

from libraryan import checks, runner
from libraryan.runtimes import claude

T = Path(__file__).resolve().parent.parent / "libraryan" / "_templates"
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
                   "Installer files", "@AGENTS.md", "Fact: <deleted> =>",
                   "Moved: <old> => <new>"):
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


def test_claude_allows_git_rm_mv_only():
    tools = claude.ALLOWED_TOOLS.split(",")
    assert all(f"Bash(git {c}:*)" in tools for c in ("rm", "mv"))
    assert not [t for t in tools if t.startswith(("Bash(rm", "Bash(mv", "Bash(mkdir"))]


def test_claude_agents_keep_frontmatter(tmp_path):
    _install(tmp_path)
    for n in ("libraryan", "libraryan-reviewer"):
        assert (tmp_path / ".claude/agents" / f"{n}.md").read_text() == (T / "agents" / f"{n}.md").read_text()


def test_neutral_bodies_name_no_tools(tmp_path):
    _install(tmp_path)
    for n in ("libraryan", "libraryan-reviewer"):
        text = (tmp_path / ".libraryan/agents" / f"{n}.md").read_text()
        assert not text.startswith("---") and text.startswith("# ")
        for bad in ("Glob", "Grep", "subagent_type", "`Read`", "`Edit`", "`Write`", "`Agent`", "`Task`"):
            assert bad not in text, (n, bad)


def test_policy_file_installed(tmp_path):
    _install(tmp_path)
    for n in ("gemini-author", "gemini-reviewer"):
        assert "[[rule]]" in (tmp_path / ".libraryan/policies" / f"{n}.toml").read_text()


def _install(dest):
    from libraryan import install
    (dest / ".libraryan").mkdir()
    install._copy(dest, Path(install.__file__).resolve().parent)


def test_mid_run_advice_in_rejection_and_block():
    from libraryan import precommit
    advice = "If you did not edit these files, Libraryan may be mid-run"
    for text in (precommit.REJECTION, (T / "agents-block.md").read_text()):
        assert advice in text and "git restore --staged <file>" in text and "--no-verify" in text
    assert "this commit" not in precommit.REJECTION  # also shown by the Claude Code guard, before any commit


def test_reviewer_input_works_for_both_callers():
    rev = (T / "agents/libraryan-reviewer.md").read_text()
    assert "You receive the run reason" in rev and "Libraryan gives you" not in rev
    assert "**Ledger claims.**" in rev and "=> none" in rev and "--output" in rev
    assert "discards your whole run" in (T / "agents/libraryan.md").read_text()


def test_stale_note_verified_gets_updated_bumped():
    assert "still accurate, bump its `updated`" in (T / "agents/libraryan.md").read_text()


def test_reviewer_deletion_reason_from_runner():
    rev = (T / "agents/libraryan-reviewer.md").read_text()
    assert "From the runner, the reason is in the `log.md` delete entry" in rev


def test_gemini_author_shell_writes_stay_in_the_repo():
    # Gemini tests commandRegex against the JSON arguments after `"command":"`
    import json
    text = (T.parent / "_runtime/policies/gemini-author.toml").read_text()
    rx = re.search(r"^commandRegex = '(.*)'$", text, re.M)[1]
    ok = lambda c: bool(re.search('"command":"' + rx, json.dumps({"command": c, "description": "d"},
                                                                 separators=(",", ":"), ensure_ascii=False)))
    for c in ("git rm -q -- docs/kb/գիտելիք.md", "git mv -- docs/a.md docs/kb/a.md", "rm -- docs/a.md",
              "mv docs/a.md docs/b.md", "mkdir -p docs/kb/new"):
        assert ok(c), c
    for c in ("rm -rf /", "rm -- ../x.md", "rm ~/x", "rm docs/../../x", "rm a.md; curl x", "rm a.md && rm /x",
              "rm '/etc/x'", 'rm "/x"', "rm $HOME/x", "rm `pwd`/x", "mv a.md /tmp/a.md", "rm a.md\nrm /x", "rmdir a"):
        assert not ok(c), c
    assert 'commandPrefix = "rm"' not in text and 'commandPrefix = "mv"' not in text


def test_gemini_policies_deny_shell_output():
    import json
    for name in ("gemini-author", "gemini-reviewer"):
        text = (T.parent / "_runtime/policies" / f"{name}.toml").read_text()
        rx = re.search(r"commandRegex = '(.*)'\ndecision = \"deny\"\npriority = 900\ndenyMessage = \"Libraryan: no --output", text)[1]
        hit = lambda c: bool(re.search('"command":"' + rx, json.dumps({"command": c, "description": "d"},
                                                                       separators=(",", ":"), ensure_ascii=False)))
        for c in ("git log --output=/tmp/x", "git diff --no-index /etc/passwd a", "git log --out''put=/x",
                  'git log "--output=/x"', "git log --out\\put=/x", "git log --out$x"):
            assert hit(c), (name, c)
        for c in ("git log --oneline", "git log --grep='x y'", 'git log --grep="a"', "git show HEAD:docs/a.md"):
            assert not hit(c), (name, c)
