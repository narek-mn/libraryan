# Libraryan Claude Code plugin

A thin front door to the [Libraryan](https://github.com/narek-mn/libraryan) CLI. It does not ship the agent or hooks itself; `/libraryan:init` installs the real CLI with pipx and runs `libraryan init`, which installs them into your project.

## Install

```
/plugin marketplace add narek-mn/libraryan
/plugin install libraryan@libraryan
```

## Commands

| Command | Does |
|---|---|
| `/libraryan:init` | Checks prerequisites (git repo on default branch, Python 3.10+, pipx), installs or upgrades the CLI, runs `libraryan init` after confirmation, and summarises the setup report |
| `/libraryan:status` | Runs `libraryan stats` and `libraryan audit` and summarises them with the latest report |
| `/libraryan:request [what]` | Files a doc change request under `.libraryan/requests/` following the project's `libraryan-request` skill |

See the main [README](../README.md) for requirements, configuration and limits.
