---
description: Install the Libraryan CLI (pipx) and set Libraryan up in the current git repo
allowed-tools: Bash(git rev-parse:*), Bash(git status:*), Bash(git symbolic-ref:*), Bash(git branch:*), Bash(python3 --version), Bash(pipx:*), Bash(libraryan:*), Read
---

Set up Libraryan in the current project. This plugin only installs and runs the real `libraryan` CLI; the CLI does the actual install (git hooks, `.claude/` agents, skill and settings, cron). Stop and explain at the first failed check.

1. Prerequisites:
   - `git rev-parse --show-toplevel` succeeds (must be a git repo).
   - The current branch is the default branch (compare `git branch --show-current` with `git symbolic-ref --short refs/remotes/origin/HEAD` if it exists, else expect `main` or `master`). `libraryan init` refuses other branches.
   - `python3 --version` is 3.10 or newer.
   - `pipx --version` works. If not, tell the user how to get it (Debian/Ubuntu: `sudo apt install pipx && pipx ensurepath`; macOS: `brew install pipx && pipx ensurepath`) and stop.
   - Mention that `claude` must be logged in and that cron is used for the daily run.
2. CLI: if `libraryan --version` fails, run `pipx install libraryan`; if that fails, run `pipx install git+https://github.com/narek-mn/libraryan`. If it is installed, run `pipx upgrade libraryan` (ignore failure for a git install). Show `libraryan --version`.
3. Before running, tell the user what `libraryan init` does: it makes an install commit (`.libraryan/`, `.claude/agents`, `.claude/skills/libraryan-request`, `.claude/settings.json` hooks, an `AGENTS.md` block), sets `core.hooksPath` and a daily cron job on this machine, then starts a headless Claude setup run that builds the knowledge base and commits it. The setup run can take a long time (up to `setup_timeout_minutes`, default 120) and spends model budget (`max_usd_setup`, default 25 USD). It never pushes. By default nothing is committed by the setup run itself: it leaves a proposal the user checks with `libraryan review` and commits with `libraryan approve`. Ask for confirmation (this also confirms the install commit), and offer `libraryan init --no-setup` (install only; the first later commit triggers setup).
4. Run `libraryan init --yes` (or with `--no-setup --yes`; the user already confirmed above) from the repo root. Run it in the background and wait for it to finish; if that is not possible, ask the user to run it in a terminal and come back.
5. Summarise: the exit status, `git status --short`, and the key points of `.libraryan/state/reports/latest.md` (what changed, problems, cost, possible code issues). If a proposal is waiting, show `libraryan review` and ask whether to run `libraryan approve` or `libraryan reject`. Remind the user: docs are now edited through requests (`/libraryan:request`), and `/libraryan:status` shows health.
