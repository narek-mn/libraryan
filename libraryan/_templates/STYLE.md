# House style

How this knowledge base is written. Libraryan follows it on every change and the reviewer checks it. Items marked (checked) are enforced by `libraryan check`.

## Notes

- One concept per note. Split a note that covers two things; merge two notes about one thing.
- Start with a one- or two-sentence summary, then details.
- Short sections, short sentences, bullets over paragraphs. Bullets or a short list of key/value lines over wide tables.
- State facts, not history. Put dates on anything that may change: "as of 2026-10-19".
- Code names, commands, paths and config keys in backticks.
- Never include secrets: describe where a value is configured, not the value.

## Frontmatter

Every note in the KB folder, except `index.md`, `log.md` and this file, starts on line 1 with a flat YAML block:

```yaml
---
title: Cache TTL
type: reference
tags: [cache, config]
created: 2026-10-19
updated: 2026-10-19
status: current
sources:
  - src/cache/config.py
  - commit a1b2c3d
---
```

- `title`, `type`, `updated`, `sources` are required (checked).
- `type`: `concept`, `decision`, `howto`, `reference` or `gotcha`.
- `status`: `current` or `superseded` (say by which note).
- `sources`: where the facts come from: repo paths, commit shas, external URLs. A note without sources is a defect.
- Dates are `YYYY-MM-DD`. Bump `updated` on every content change.

Docs outside the KB folder (READMEs, CHANGELOG, agent instruction files) get no frontmatter; the rest of this style applies.

## Files and links

- File names are kebab-case: `cache-ttl.md`. Topic folders are kebab-case too.
- Link with standard relative Markdown links to the target file. No wikilinks (double square brackets). No absolute paths (checked: every relative link must resolve).
- Every note is linked from `index.md` (checked).

## index.md

The catalog, read first. Grouped by topic or type; one bullet per note: a relative link to the note followed by a one-line summary.

## log.md

Append-only record of every change. New entries go at the end; earlier entries are never edited. Each entry:

- Heading `## [YYYY-MM-DD] op | title`, where `op` is one of `setup`, `request`, `update`, `fix`, `move`, `delete`.
- A few bullets: what changed, the outcome for requests (applied, merged, rejected, flagged) and the reason when rejected, flagged or deleted.
