from libraryan import ledger

OLD = "# Old notes\n\nThe deploy script pushes images to the staging registry\nbefore tagging a release.\n"


def test_parse_lines():
    p = ledger.parse("SUMMARY\n- Moved: `docs/a.md` => `docs/b.md`\n"
                     "Fact: docs/b.md => docs/x.md | quote one here ok | quote two here ok\n"
                     "Fact: `docs/c.md` => none | empty stub\nFact: garbage\n")
    assert p["moved"] == {"docs/a.md": "docs/b.md"}
    assert p["facts"] == [{"deleted": "docs/b.md", "dest": "docs/x.md", "src_quote": "quote one here ok",
                           "dest_quote": "quote two here ok"}]
    assert p["none"] == {"docs/c.md": "empty stub"} and len(p["lines"]) == 3


def check(tmp_path, text, files=None):
    for rel, body in (files or {}).items():
        (tmp_path / rel).write_text(body)
    return ledger.check(tmp_path, {"old.md": OLD}, set(), ledger.parse(text))


def test_fact_quotes_must_match_both_sides(tmp_path):
    files = {"new.md": "Deploys push images to the staging registry before tagging a release.\n"}
    ok = "Fact: old.md => new.md | pushes images to the staging registry | push images to the staging registry"
    assert check(tmp_path, ok, files) == {}
    bad = "Fact: old.md => new.md | invented quote that is long | push images to the staging registry"
    assert "quote not found in the deleted file" in check(tmp_path, bad, files)["old.md"]
    short = "Fact: old.md => new.md | images | images"
    assert "at least 15" in check(tmp_path, short, files)["old.md"]
    nodoc = "Fact: old.md => new.txt | pushes images to the staging registry | push images to the staging"
    assert "not a doc that exists" in check(tmp_path, nodoc, {"new.txt": files["new.md"]})["old.md"]


def test_moved_must_keep_most_content(tmp_path):
    assert check(tmp_path, "Moved: old.md => new.md", {"new.md": OLD + "one more line\n"}) == {}
    assert "less than 50%" in check(tmp_path, "Moved: old.md => new.md", {"new.md": "# Other\n"})["old.md"]


def test_none_line_and_pure_move(tmp_path):
    assert check(tmp_path, "Fact: old.md => none | empty stub") == {}
    assert ledger.check(tmp_path, {"old.md": OLD}, {"old.md"}, ledger.parse("")) == {}
    assert check(tmp_path, "") == {"old.md": "the agent did not say where its facts went"}
