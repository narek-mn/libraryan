import copy
import subprocess

import pytest

from libraryan import config, ledger, runner

OLD = """# Old notes

The deploy script pushes images to the staging registry
before tagging a release.
"""


@pytest.fixture
def kb(repo):
    (repo / "docs/kb").mkdir(parents=True)
    (repo / "docs/old.md").write_text(OLD)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "old"], cwd=repo, check=True)
    cfg = copy.deepcopy(config.DEFAULTS)
    return repo, cfg, runner._snapshot(repo, cfg)


def delete(repo, cfg, snap, text, writes=None):
    (repo / "docs/old.md").unlink()
    for rel, body in (writes or {}).items():
        (repo / rel).write_text(body)
    return ledger.check(repo, cfg, ["docs/old.md"], snap, runner._snapshot(repo, cfg), ledger.parse(text))


def test_parse_lines():
    p = ledger.parse("SUMMARY\nMoved: `docs/a.md` => `docs/kb/a.md`\n"
                     "Fact: docs/b.md => docs/kb/x.md | quote one here ok | quote two here ok\n"
                     "Fact: `docs/c.md` => none | empty stub\nFact: garbage\nDiscard: docs/kb/y.md\n")
    assert p["moved"] == {"docs/a.md": "docs/kb/a.md"}
    assert p["facts"] == [{"deleted": "docs/b.md", "dest": "docs/kb/x.md", "src_quote": "quote one here ok",
                           "dest_quote": "quote two here ok"}]
    assert p["none"] == {"docs/c.md": "empty stub"}
    assert len(p["lines"]) == 3 and "Fact: garbage" not in p["lines"]


def test_pure_move_needs_no_line(kb):
    repo, cfg, snap = kb
    assert delete(repo, cfg, snap, "", writes={"docs/kb/old.md": OLD}) == []


def test_moved_line_similarity(kb):
    repo, cfg, snap = kb
    edited = OLD.replace("# Old notes", "---\ntitle: Old\n---\n# Old notes")
    assert delete(repo, cfg, snap, "Moved: docs/old.md => docs/kb/old.md", writes={"docs/kb/old.md": edited}) == []


def test_moved_line_dissimilar_rejected(kb):
    repo, cfg, snap = kb
    probs = delete(repo, cfg, snap, "Moved: docs/old.md => docs/kb/old.md", writes={"docs/kb/old.md": "x\n"})
    assert probs and probs[0].startswith("deletion ledger: docs/old.md:")


def test_fact_with_destination_ok(kb):
    repo, cfg, snap = kb
    line = ("Fact: docs/old.md => docs/kb/deploy.md | pushes images to the staging registry | "
            "Images go to the staging registry")
    assert delete(repo, cfg, snap, line, writes={"docs/kb/deploy.md": "Images go to the staging registry first.\n"}) == []


def test_fact_quote_whitespace_normalised(kb):
    repo, cfg, snap = kb
    line = ("Fact: docs/old.md => docs/kb/deploy.md | staging registry before tagging | "
            "Images go to the staging registry")
    assert delete(repo, cfg, snap, line, writes={"docs/kb/deploy.md": "Images go to the\n  staging registry.\n"}) == []


def test_fact_quote_missing_in_source(kb):
    repo, cfg, snap = kb
    line = "Fact: docs/old.md => docs/kb/deploy.md | invented fact never there | Images go to staging"
    probs = delete(repo, cfg, snap, line, writes={"docs/kb/deploy.md": "Images go to staging.\n"})
    assert len(probs) == 1 and probs[0].startswith("deletion ledger: docs/old.md:")


def test_fact_quote_too_short(kb):
    repo, cfg, snap = kb
    line = "Fact: docs/old.md => docs/kb/deploy.md | staging | Images go to staging"
    assert delete(repo, cfg, snap, line, writes={"docs/kb/deploy.md": "Images go to staging.\n"})


def test_fact_dest_not_owned(kb):
    repo, cfg, snap = kb
    cfg["excluded"].append("docs/kb/deploy.md")
    line = ("Fact: docs/old.md => docs/kb/deploy.md | pushes images to the staging registry | "
            "Images go to the staging registry")
    probs = delete(repo, cfg, snap, line, writes={"docs/kb/deploy.md": "Images go to the staging registry.\n"})
    assert len(probs) == 1 and "docs/old.md" in probs[0]


def test_fact_none_accepted(kb):
    repo, cfg, snap = kb
    assert delete(repo, cfg, snap, "Fact: docs/old.md => none | duplicate of README") == []


def test_deleted_without_line(kb):
    repo, cfg, snap = kb
    probs = delete(repo, cfg, snap, "SUMMARY ok")
    assert len(probs) == 1 and probs[0].startswith("deletion ledger: docs/old.md:")


def test_parse_bullets_backticked_lines_and_wrapped_quotes():
    p = ledger.parse("- Fact: docs/a.md => none | empty stub\n* Moved: docs/b.md => docs/kb/b.md\n"
                     "`Fact: docs/c.md => none | empty stub`\n"
                     '+ Fact: docs/d.md => docs/kb/x.md | "quote one here ok" | “quote two here ok”\n'
                     "Fact: docs/e.md => docs/kb/x.md | `quote one here ok` | 'quote two here ok'\n")
    assert p["none"] == {"docs/a.md": "empty stub", "docs/c.md": "empty stub"}
    assert p["moved"] == {"docs/b.md": "docs/kb/b.md"}
    assert [(f["src_quote"], f["dest_quote"]) for f in p["facts"]] == [("quote one here ok", "quote two here ok")] * 2


def test_pure_move_into_discarded_file_fails(kb):
    repo, cfg, snap = kb
    (repo / "docs/kb/old.md").write_text(OLD)
    (repo / "docs/old.md").unlink()
    after = runner._snapshot(repo, cfg)
    (repo / "docs/kb/old.md").unlink()  # the runner's Discard: removal happens after the snapshot
    probs = ledger.check(repo, cfg, ["docs/old.md"], snap, after, ledger.parse(""))
    assert len(probs) == 1 and probs[0].startswith("deletion ledger: docs/old.md:")
