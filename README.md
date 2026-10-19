# Libraryan

Libraryan installs a Claude Code agent as the sole writer of a project's Markdown knowledge base.
Everyone else (people, other agents) files requests; Libraryan updates the docs, checks them, and commits.

## Requirements

Linux or macOS. Python 3.10+, git >= 2.34, Claude Code >= 2.1, cron. [gitleaks](https://github.com/gitleaks/gitleaks) is optional (secret scanning).

## Install

```
git clone <repo> ~/libraryan
cd <your-project>        # a git repo, on its default branch, Claude Code installed
python3 ~/libraryan/libraryan.py init
```

`init` refuses to run on a non-default branch or with uncommitted installer paths or owned docs.
Use `init --no-setup` to install without the first Claude run.

## What init changes

1. Install commit (`docs(libraryan): install`) with:
   - `.libraryan/` (vendored runtime, `config.json`, `requests/`, templates; `state/` is gitignored)
   - `.claude/agents/libraryan.md` and `libraryan-reviewer.md`
   - `.claude/skills/libraryan-request/SKILL.md` (how to file a request)
   - `.claude/settings.json` hooks merged in (PreToolUse guard on Edit/Write, SessionStart hook re-enabling git hooks)
   - an `AGENTS.md` block (between `<!-- libraryan:start/end -->`) and `CLAUDE.md` importing `@AGENTS.md`
2. On this machine only (not committed): `core.hooksPath` set to `.libraryan/hooks` (existing hooks are chained), and a daily 03:00 cron job.
3. First setup run (Claude Code, headless) creates the KB and is committed as a second commit.

Libraryan commits only on the default branch and never pushes.

## Working with it

Owned files (default: all `**/*.md`, `.claude/skills/**`, `.cursor/rules/**`, `.github/copilot-instructions.md`) cannot be edited directly:
the Claude Code hook blocks Edit/Write, and the pre-commit hook rejects commits touching them (deletions pass).
To change docs, add a Markdown file under `.libraryan/requests/` (see the `libraryan-request` skill) and commit it.
After a commit, Libraryan waits `debounce_minutes` for quiet, then runs and commits the doc updates.

Docs vs code: if docs contradict the code, Libraryan fixes the docs; suspected code bugs go under "Possible code issues" in the report.
Outdated or junk Markdown is deleted after still-valid facts are moved into the KB (git history keeps everything).

## Commands

Run via the vendored `python3 .libraryan/bin/libraryan <cmd>` inside the project:

| Command | Does |
|---|---|
| `run [--reason R]` | Run Libraryan now (default reason `manual`) |
| `wait` | Wait out the debounce window, then run |
| `check` | Lint docs and scan for secrets; exit 1 on problems |
| `upgrade` | Re-run the installer from `source_path` (refreshes runtime, hooks, agents, skill) and commit |
| `uninstall` | Remove hooks, cron, agent files, `.libraryan/` and the AGENTS.md block; commit. The KB stays |

Internal (called by hooks/cron): `precommit`, `postcommit`, `guard`, `ensure-hooks`, `chainpath`.
Without a project install, `python3 ~/libraryan/libraryan.py {init,upgrade,uninstall}` does the same from the source checkout.

## Configuration

`.libraryan/config.json` (defaults shown):

| Key | Default | Meaning |
|---|---|---|
| `kb_root` | `docs/kb` | Where the knowledge base lives |
| `default_branch` | detected | Only branch Libraryan edits |
| `runner_host` | install host | Only this machine runs Libraryan |
| `claude_bin` / `model` | `claude` / `null` | Claude Code binary and model |
| `debounce_minutes` | `10` | Quiet time after a commit before a run |
| `run_timeout_minutes` | `30` | Kill a run after this long |
| `language` | `en` | Language of the docs |
| `owned` / `excluded` | see `config.py` | Globs Libraryan owns / ignores |
| `exempt` | `[]` | Owned-looking paths people may still edit |
| `chain_hooks_path` | detected | Pre-existing hooks dir to chain to |

## Reports

Each run writes `.libraryan/state/reports/<timestamp>.md` and `.libraryan/state/reports/latest.md` (gitignored). Read `latest.md` for what changed, problems, and "Possible code issues".

## Uninstall

`python3 .libraryan/bin/libraryan uninstall` (or `libraryan.py uninstall`). Restores `core.hooksPath`, removes the cron line and commits the removal.

## Known limits

- `LIBRARYAN=1` in the environment bypasses the lock; any process can set it. The upgrade path is a CI check.
- Edits made through Bash are only caught at commit time.
- Claude Code is the only supported runtime.
- Teammates' clones get the lock when Claude Code's SessionStart hook enables the git hooks there, but they do not run Libraryan.
- Windows is unsupported.
