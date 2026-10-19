from libraryan import checks, config

FM = "---\ntitle: T\ntype: note\nupdated: 2026-01-01\nsources: []\n---\n"


def mk(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def lint(root, files):
    return checks.lint(root, config.load(root), files)


def test_lint_missing_frontmatter(tmp_path):
    mk(tmp_path, "docs/kb/a.md", FM.replace("sources: []\n", ""))
    mk(tmp_path, "docs/kb/index.md", "[a](a.md)\n")
    out = lint(tmp_path, ["docs/kb/a.md"])
    assert len(out) == 1 and "sources" in out[0] and out[0].startswith("docs/kb/a.md: ")


def test_lint_broken_link(tmp_path):
    mk(tmp_path, "README.md", "[x](nope.md#top)\n[ok](https://x.io/a.md)\n")
    out = lint(tmp_path, ["README.md", "gone.md"])
    assert len(out) == 1 and "nope.md" in out[0]


def test_lint_link_with_spaces_ok(tmp_path):
    mk(tmp_path, "README.md", "[x](My%20Note.md)\n")
    mk(tmp_path, "My Note.md", "hi\n")
    assert lint(tmp_path, ["README.md"]) == []


def test_lint_index_coverage(tmp_path):
    mk(tmp_path, "docs/kb/a.md", FM)
    mk(tmp_path, "docs/kb/b.md", FM)
    mk(tmp_path, "docs/kb/index.md", "[a](a.md)\n")
    out = lint(tmp_path, ["docs/kb/a.md", "docs/kb/b.md", "docs/kb/index.md"])
    assert len(out) == 1 and out[0].startswith("docs/kb/b.md") and "index" in out[0]


def test_lint_ignores_frontmatter_outside_kb(tmp_path):
    mk(tmp_path, "README.md", "# hi\n")
    assert lint(tmp_path, ["README.md"]) == []


def test_secrets_detects_aws_key(tmp_path):
    mk(tmp_path, "a.txt", "key=AKIAABCDEFGHIJKLMNOP\n")
    out = checks.scan_secrets(tmp_path, ["a.txt"])
    assert len(out) == 1 and out[0].startswith("a.txt:1: ")


def test_secrets_clean_file(tmp_path):
    mk(tmp_path, "a.txt", "nothing here\n")
    assert checks.scan_secrets(tmp_path, ["a.txt", "missing.txt"]) == []


def test_secrets_ignores_hyphenated_slug(tmp_path):
    mk(tmp_path, "a.md", "[x](risk-assessment-for-the-project.md) disk-encryption-configuration\n")
    assert checks.scan_secrets(tmp_path, ["a.md"]) == []
    mk(tmp_path, "b.txt", "k sk-ant-" + "a" * 30 + "\n")
    assert len(checks.scan_secrets(tmp_path, ["b.txt"])) == 1


def _kb_note(root, text):
    mk(root, "docs/kb/index.md", "[a](a.md)\n")
    (root / "docs/kb/a.md").write_bytes(text.encode())
    return lint(root, ["docs/kb/a.md"])


def test_lint_frontmatter_crlf(tmp_path):
    assert _kb_note(tmp_path, FM.replace("\n", "\r\n")) == []


def test_lint_frontmatter_at_eof(tmp_path):
    assert _kb_note(tmp_path, FM.rstrip("\n")) == []


def test_secrets_ignore_placeholders(tmp_path):
    mk(tmp_path, "a.md", 'API_KEY="your_api_key_here"\ntoken: "<your-token>"\npassword = "changeme123"\n'
                         'api_key: "${API_KEY}"\n')
    assert checks.scan_secrets(tmp_path, ["a.md"]) == []


def test_secret_reported_with_line_and_masked(tmp_path):
    mk(tmp_path, "a.md", "intro\n\npassword = \"Tr0ub4dor&3horse\"\n")
    out = checks.scan_secrets(tmp_path, ["a.md"])
    assert len(out) == 1 and out[0].startswith("a.md:3: ") and "Tr0ub4dor&3horse" not in out[0]


def test_lint_ignores_links_in_code(tmp_path):
    mk(tmp_path, "a.md", "```\n[x](nope.md)\n```\nuse `[y](gone.md)` syntax\n[z](missing.md)\n")
    assert lint(tmp_path, ["a.md"]) == ["a.md: broken link missing.md"]
