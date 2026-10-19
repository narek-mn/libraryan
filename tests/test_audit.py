import os
import subprocess

from libraryan import audit, config

FM = "---\ntitle: {title}\ntype: note\nupdated: {updated}\nsources: [{sources}]\n---\n"


def git(repo, *args, env=None):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env={**os.environ, **(env or {})})


def note(title="A", updated="2099-01-01", sources="src/app.py", body=""):
    return FM.format(title=title, updated=updated, sources=sources) + body


def kb(repo, notes: dict, index=None, commit=True):
    """Repo with src/app.py, docs/kb/index.md linking every note (unless `index` given)."""
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src/app.py").write_text("x = 1\n")
    (repo / "docs/kb").mkdir(parents=True, exist_ok=True)
    for name, text in notes.items():
        (repo / "docs/kb" / name).write_text(text)
    links = "".join(f"- [{n}]({n})\n" for n in notes)
    (repo / "docs/kb/index.md").write_text("# Index\n" + (links if index is None else index))
    if commit:
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "kb", env={"GIT_COMMITTER_DATE": "2026-10-01T12:00:00"})
    return config.load(repo)


def kinds(findings, kind):
    return [f for f in findings if f[0] == kind]


def test_frontmatter_lists():
    fm = audit.frontmatter("---\ntitle: T\nsources: [a, 'b c']\ntags:\n  - x\n  - y\nupdated: 2026-01-01\n---\nbody")
    assert fm == {"title": "T", "sources": ["a", "b c"], "tags": ["x", "y"], "updated": "2026-01-01"}
    assert audit.frontmatter("---\nsources:\n---\n")["sources"] == []
    assert audit.frontmatter("no frontmatter") == {}


def test_clean_kb_has_no_findings(repo):
    cfg = kb(repo, {"a.md": note(body="See `src/app.py`.\n")})
    assert audit.run(repo, cfg) == []


def test_missing_path_found(repo):
    cfg = kb(repo, {"a.md": note(body="Entry is `src/gone.py`.\n")})
    assert audit.run(repo, cfg) == [("missing-path", "docs/kb/a.md", "src/gone.py")]


def test_missing_path_ignores_non_paths(repo):
    body = ("`https://x.io/a.py` `src/*.py` `<file>.py` `~/x/y.py` `$HOME/a.py` `/etc/hosts` `{a}/b.py` `a b.py` `@AGENTS.md`\n"
            "```\nsrc/fenced.py\n`src/fenced2.py`\n```\n")
    cfg = kb(repo, {"a.md": note(body=body)})
    (repo / "README.md").write_text("# t\n`src/app.py` and `app.py` exist\n")
    assert kinds(audit.run(repo, cfg), "missing-path") == []


def test_path_with_line_suffix(repo):
    cfg = kb(repo, {"a.md": note(body="`src/app.py#L3` and `src/app.py:3` and `src/app.py#L3-L9`\n")})
    assert audit.run(repo, cfg) == []
    assert audit.looks_like_path("src/app.py:3") and not audit.looks_like_path("hello")


def test_stale_source(repo):
    cfg = kb(repo, {"a.md": note(updated="2020-01-01")})
    out = audit.run(repo, cfg)
    assert [f[:2] for f in out] == [("stale", "docs/kb/a.md")] and "src/app.py" in out[0][2]


def test_unsourced_and_missing_source(repo):
    cfg = kb(repo, {"a.md": note(sources=""), "b.md": note(title="B", sources="src/gone.py, commit abc123"),
                    "c.md": note(title="C").replace("sources: [src/app.py]\n", "")})
    out = audit.run(repo, cfg)
    assert ("unsourced", "docs/kb/a.md", "no sources") in out
    assert ("unsourced", "docs/kb/c.md", "no sources") in out
    assert ("missing-source", "docs/kb/b.md", "src/gone.py") in out
    assert len(out) == 3


def test_duplicate_title(repo):
    cfg = kb(repo, {"a.md": note(title="Same  Title"), "b.md": note(title="same title")})
    assert audit.run(repo, cfg) == [("duplicate-title", "docs/kb/b.md", "same title as docs/kb/a.md")]


def test_not_indexed_and_broken_link(repo):
    cfg = kb(repo, {"a.md": note(body="[x](gone.md)\n")}, index="")
    assert audit.run(repo, cfg) == [("broken-link", "docs/kb/a.md", "gone.md"),
                                    ("not-indexed", "docs/kb/a.md", "not linked from docs/kb/index.md")]


def test_odd_files_never_raise(repo):
    cfg = kb(repo, {"a.md": "no frontmatter\n"}, commit=False)
    (repo / "docs/kb/bin.md").write_bytes(b"\xff\xfe\x00`src/x.py`\x00")
    (repo / "docs/kb/index.md").unlink()
    (repo / "docs/kb/dir.md").mkdir()
    out = audit.run(repo, cfg)
    assert ("unsourced", "docs/kb/a.md", "no sources") in out and ("missing-path", "docs/kb/bin.md", "src/x.py") in out


def test_format_caps():
    f = [("stale", f"n{i}.md", "x") for i in range(5)]
    assert audit.format([]) == "- (none)"
    assert audit.format(f, cap=2) == "stale n0.md: x\nstale n1.md: x\n… and 3 more"


def test_fresh_install_is_clean(repo):
    from pathlib import Path

    from libraryan import install
    assert install.init(repo, run_setup=False) == 0
    (repo / "docs/kb").mkdir(parents=True)
    (repo / "docs/kb/index.md").write_text("# Index\n")
    (repo / "docs/kb/STYLE.md").write_text((repo / ".libraryan/templates/STYLE.md").read_text())  # setup copies it
    (repo / "docs/kb/log.md").write_text("# Log\n\n## [2026-10-19] delete | old\n- removed `src/gone.py` notes\n")
    assert audit.run(repo, config.load(repo)) == []


def test_doc_relative_source_is_stale_checked(repo):
    cfg = kb(repo, {"a.md": note(updated="2020-01-01", sources="../../src/app.py")})
    assert [f[:2] for f in audit.run(repo, cfg)] == [("stale", "docs/kb/a.md")]


def test_path_outside_repo_is_missing(repo):
    outside = repo.parent / "outside.py"
    outside.write_text("x\n")
    cfg = kb(repo, {"a.md": note(body="`../../../outside.py`\n")})
    assert audit.run(repo, cfg) == [("missing-path", "docs/kb/a.md", "../../../outside.py")]


def test_path_with_symbol_suffix(repo):
    cfg = kb(repo, {"a.md": note(body="`src/app.py:main` and `src/app.py:App.run`\n")})
    assert audit.run(repo, cfg) == []
