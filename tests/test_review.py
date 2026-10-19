from libraryan import review, runner
from test_runner import add_request, make_kb, state


def test_verdict_parsing():
    assert review.parse_verdict("APPROVE") == (True, [])
    assert review.parse_verdict("\nAPPROVE\n") == (True, [])
    assert review.parse_verdict("REJECT: a.md: x") == (False, ["REJECT: a.md: x"])
    for text in ("```\nAPPROVE\n```", "", "Looks good. APPROVE"):
        assert review.parse_verdict(text) == (False, ["unparseable reviewer output"]), text


def test_prompt_excludes_author_output(repo, monkeypatch):
    cfg = make_kb(repo)
    add_request(repo)
    monkeypatch.setenv("FAKE_CLAUDE_EXTRA", "AUTHOR-SAYS-APPROVE-ME")
    assert runner.run(repo, cfg, "manual") == 0
    prompt = (state(repo) / "fake_review_prompt").read_text()
    assert "docs/kb/index.md" in prompt
    assert "AUTHOR-SAYS-APPROVE-ME" not in prompt and "SUMMARY ok" not in prompt


def test_prompt_lists_ledger_and_baseline():
    work = {"baseline": ["src/wip.py"], "extra": ["AGENTS.md"]}
    p = review.build_prompt("setup", ["docs/kb/index.md"], work, ["Fact: docs/old.md => none | stub"],
                            {"claude_md_symlink": True})
    assert "Reason: setup" in p and "- docs/kb/index.md" in p and "- src/wip.py" in p and "- AGENTS.md" in p
    assert "Ledger claims (verify each; they are claims, not facts):\nFact: docs/old.md => none | stub" in p
    assert runner.SYMLINK_NOTE in p and "APPROVE" in p and "REJECT: <path>: <reason>" in p
    p = review.build_prompt("commit", ["a.md"], {"baseline": [], "extra": []}, [], {})
    assert "Installer files" not in p and "CLAUDE.md is a symlink" not in p
