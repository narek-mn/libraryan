---
description: File a documentation change request for Libraryan
argument-hint: [what should change in the docs]
allowed-tools: Read, Write, Bash(date:*), Bash(git status:*), Bash(git log:*)
---

Libraryan is the only writer of this project's Markdown docs; changes go through request files. If `.libraryan/` does not exist in the repo root, say Libraryan is not installed here and suggest `/libraryan:init`.

1. Read `.claude/skills/libraryan-request/SKILL.md` and follow it exactly (file name, frontmatter, `kind`, `related`, facts not instructions, no secrets).
2. Work out the facts from the user's request ($ARGUMENTS) and the conversation; check them against the code and recent commits. Ask if the change or its `kind` is unclear.
3. Write one file under `.libraryan/requests/`. Do not edit owned docs directly.
4. Show the file and remind the user to commit it with the related work; Libraryan processes it once it reaches the default branch.
