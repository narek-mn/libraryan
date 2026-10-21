<p align="center">
  <img src="https://raw.githubusercontent.com/narek-mn/libraryan/main/docs/assets/banner.png" alt="Libraryan: keep your Markdown docs true to your code" width="100%">
</p>

<p align="center">
  <a href="https://github.com/narek-mn/libraryan/actions/workflows/test.yml"><img src="https://github.com/narek-mn/libraryan/actions/workflows/test.yml/badge.svg" alt="tests"></a>
  <a href="https://pypi.org/project/libraryan/"><img src="https://img.shields.io/pypi/v/libraryan?color=3fb950" alt="PyPI"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776ab" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/dependencies-0-3fb950" alt="zero dependencies">
  <a href="https://github.com/narek-mn/libraryan/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT"></a>
</p>

Docs drift. A flag gets renamed, a file moves, a default changes, and the README keeps saying the old thing. AI agents make it worse: they write a lot of Markdown and rarely go back to fix it.

Libraryan finds and fixes that drift, when you ask, and never commits anything:

- **`libraryan check`** lists broken links and file paths that no longer exist. Free, no AI, changes nothing. Good in CI.
- **`libraryan fix`** lets an AI agent read your code and fix the docs that are wrong. The changes land in your folder uncommitted, so you read them with `git diff` and keep what you like.

It installs nothing into your project: no hooks, no config files, no background jobs.

## Quick start

```bash
pipx install libraryan
cd your-project
libraryan check                  # free: what is broken?
libraryan fix                    # AI: fix the docs (needs Claude Code)
git diff                         # read the changes, then commit or undo
```

Working on a branch? Fix only the docs your changes affect:

```bash
libraryan fix --since main
```

## What `fix` does

On a small test project with a README that had drifted from its code:

```
$ libraryan fix
Changed
- README.md: the default port was given as 8000, but src/server.py uses 9000.
- README.md: it described a --verbose flag that doesn't exist. The real option is --log-level.
- README.md: it pointed to src/config.py, which doesn't exist. Removed.
- README.md: it linked to docs/deploy.md, which doesn't exist. Removed the link.
Deleted
- docs/notes-old.md: an old scratch note. Its one true fact is already in docs/setup.md.

Libraryan changed 2 doc(s). Nothing is committed. Cost: $0.19.
  changed  README.md
  deleted  docs/notes-old.md

Review: git diff  (new files: git status)
Keep:   commit them as usual
Undo:   git restore -- README.md docs/notes-old.md
```

That run took 22 seconds. The agent:

- **checks docs against the code**: commands, flags, paths, config keys, defaults, setup steps. It fixes what the code proves wrong.
- **fixes broken links** and references to files that are gone.
- **removes junk docs**: empty stubs, duplicates, old scratch notes. Before deleting one, it must quote where each fact went. Libraryan checks those quotes, and puts back any deletion that fails.
- **reports, never touches, code**: if the code looks wrong and the doc looks right, it tells you.
- leaves correct text alone. It does not restyle or reorganise.

## Why you can trust it

| Worry | What happens |
|---|---|
| It commits or pushes something | It never runs `git commit`, `add` or `push`. You decide what to keep. |
| It changes my code | It works in a throwaway copy of your repo. Only `.md` changes come back; anything else is dropped and listed. |
| It deletes a fact | A deletion stays only if the agent quotes where each fact went, and the quotes match both files. |
| It overwrites my edits | `fix` refuses to start while you have uncommitted doc changes. |
| It costs too much | Each run stops at a dollar limit (`--budget`, default $5) and after 60 minutes. The cost is printed at the end. |
| It follows instructions hidden in a file | Docs and code are treated as data, never as instructions. |

## Commands

| Command | Does |
|---|---|
| `libraryan check` | List broken links and missing paths. Exit code 1 if any. |
| `libraryan fix` | Fix the docs with an AI agent; leave the changes uncommitted |
| `libraryan fix --since REF` | Only docs affected by code changes since `REF` |
| `libraryan fix --budget 10` | Raise the dollar limit (default 5) |
| `libraryan fix --model sonnet` | Pick the Claude model |

What counts as a doc: every `.md` file git tracks, except in `node_modules`, `vendor`, `third_party`, `fixtures`, `testdata`, `templates`, `venv` and folders that start with a dot (other than `.github`). `check` skips changelogs (they record history) and paths your `.gitignore` covers, so build output is not reported as missing.

## Use `check` in CI

```yaml
- run: pipx install libraryan && libraryan check
```

## Requirements

- Linux or macOS, Python 3.10+, git.
- For `fix`: [Claude Code](https://docs.anthropic.com/en/docs/claude-code), logged in. You pay for your own usage.

## Upgrading from 0.3

0.3 installed itself into each project (hooks, a scheduled job, `.libraryan/`). 0.4 drops all of that. In each project that has it, before you upgrade, run:

```bash
python3 .libraryan/bin/libraryan uninstall
```

Then `pipx upgrade libraryan`. Your docs stay as they are.

## Contributing

Issues and PRs are welcome; see [CONTRIBUTING.md](https://github.com/narek-mn/libraryan/blob/main/CONTRIBUTING.md). Report security issues privately ([SECURITY.md](https://github.com/narek-mn/libraryan/blob/main/SECURITY.md)).

<sub>MIT © narek-mn · [Changelog](https://github.com/narek-mn/libraryan/blob/main/CHANGELOG.md)</sub>
