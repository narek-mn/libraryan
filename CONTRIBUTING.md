# Contributing to Libraryan

Thanks for helping out! Libraryan is small on purpose: two commands. Please keep it that way.

## Dev setup

```
git clone https://github.com/narek-mn/libraryan
cd libraryan
python3 -m venv .venv
. .venv/bin/activate
pip install -e . pytest build
```

Run the tests:

```
python3 -m pytest -q
```

## Project layout

- `libraryan/check.py` - `libraryan check`: broken links and missing paths, no AI.
- `libraryan/fix.py` - `libraryan fix`: runs Claude Code in a throwaway worktree and copies doc changes back.
- `libraryan/instructions.py` - what the agent is told.
- `libraryan/ledger.py` - checks that deleted docs' facts went somewhere.
- `tests/` - the test suite. `tests/fake_claude.py` stands in for Claude Code.

## Rules

- Python 3.10+, standard library only. No new dependencies.
- Unix only (Linux and macOS). Claude Code is the only supported agent.
- Tests must never call the real `claude`. Stub it.
- Keep commits small and focused. Use conventional-style messages: `feat: ...`, `fix: ...`, `docs: ...`, `build: ...`.
- If behaviour changes, update `README.md` and add a `CHANGELOG.md` entry.

## Proposing a change

For anything bigger than a small fix, open an issue first so we can agree on the approach. Then open a pull request against `main` with tests, and fill in the PR checklist.

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md). For security problems, see [SECURITY.md](SECURITY.md) instead of opening a public issue.
