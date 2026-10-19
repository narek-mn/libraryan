---
title: "6. Governance & Automation Playbook"
reviewed: 2026-10-19
source: https://claude.ai/code/artifact/9511a455-029e-465f-8cca-c7eddd7f7cd1
---

# 6. Governance & Automation Playbook

Drift is stopped at three gates: a pre-commit hook catches syntax in seconds, CI blocks merges that break schemas, links or authority rules, and a weekly scheduled job flags what time alone made stale. Authority tiers decide which document wins when two disagree.

### 6.1 Authority tiers

| Tier | Kind | Location | Changes by | Wins over | Default retrieval |
| --- | --- | --- | --- | --- | --- |
| 0 | Running code and generated contracts | `src/`, build output | Code review | Everything, for *what the system does* | Yes, via code search |
| 1 | Normative specs and catalog | `kb/specs/`, `kb/catalog/` | PR + owner approval | Tiers 2–4 | Yes |
| 2 | Decisions (ADRs) | `kb/decisions/` | New ADR only; old ones are never edited except `status` | Tiers 3–4, for *why* | Yes |
| 3 | Guides, runbooks, tutorials | `kb/guides/`, co-located READMEs | PR + owner review | Tier 4 | Yes |
| 4 | Notes, transcripts, drafts | `kb/notes/` | Anyone | Nothing | No; opt-in only |
| — | Archive | `kb/archive/` | Move only | Nothing | Never |

Conflict rule, stated once in `AGENTS.md`: the lower-numbered tier wins; within a tier, the later `reviewed` date wins; a tier-3 document that disagrees with its tier-1 `sources` is a bug to file, not an alternative truth. Code (tier 0) beats a spec on *current behaviour*; the spec beats code on *intended behaviour*, and the mismatch is reported.

**Provenance.** Tier-3 docs must list `sources` (schema 4.3 enforces it). A claim an agent might act on cites the tier-1/2 pointer inline; a `quote` field pins the exact supporting sentence so the checker notices when the source changes underneath it. ADRs follow a fixed template ([MADR](https://adr.github.io/madr/) or [Nygard](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)): Context, Decision, Consequences, Status, with `supersedes` / `superseded_by` links.

### 6.2 The validator: checks and where they run

| # | Check | Fails when | Pre-commit | CI | Weekly |
| --- | --- | --- | --- | --- | --- |
| 1 | YAML/JSON syntax + yamllint | Malformed file, truthy ambiguity | Yes | Yes | — |
| 2 | Schema validation | Catalog entity or frontmatter breaks its JSON Schema | Yes | Yes | — |
| 3 | ID integrity | Duplicate id; filename ≠ id; dangling `depends_on`, `about`, `ref` | — | Yes | — |
| 4 | Link check (internal) | Relative path or heading anchor no longer resolves | — | Yes | — |
| 5 | Quote pin | A pointer's `quote` text no longer appears at its target | — | Yes | — |
| 6 | Tier rule | Tier-3 doc lacks `sources`; any doc cites `kb/archive/` or a tier-4 note as authority | — | Yes | — |
| 7 | Index freshness | `index.json` / `llms.txt` differ from a fresh build | — | Yes | — |
| 8 | Co-change rule | A PR changes `kb/specs/*` or `kb/catalog/*` without touching any doc whose `sources`/`about` names it | — | Warn + reviewer ack | — |
| 9 | Markdown lint | Heading skips a level, H4+, missing summary blockquote, oversize H2 | Yes | Yes | — |
| 10 | Staleness | `reviewed` + `review_every_days` is in the past | — | — | Opens an issue for `owner` |
| 11 | External links | Outbound URL returns 4xx/5xx | — | — | Yes |
| 12 | Orphans | Active doc reachable from no index and cited by nothing | — | — | Yes |

Pre-commit runs only fast, local checks so it never gets bypassed for being slow. Every check is also callable as `tools/kb/validate --check <n>` so agents run the same gate before proposing a change.

### 6.3 Wiring it up with open tools

```yaml
# .pre-commit-config.yaml  (pre-commit framework, or call the same commands from a plain git hook)
repos:
  - repo: https://github.com/adrienverge/yamllint
    rev: v1.35.1
    hooks: [{ id: yamllint, files: ^kb/ }]
  - repo: https://github.com/python-jsonschema/check-jsonschema
    rev: 0.29.4
    hooks:
      - id: check-jsonschema
        name: catalog-systems
        files: ^kb/catalog/systems/.*\.yaml$
        args: [--schemafile, kb/schemas/system.schema.json]
      - id: check-jsonschema
        name: catalog-capabilities
        files: ^kb/catalog/capabilities/.*\.yaml$
        args: [--schemafile, kb/schemas/capability.schema.json]
  - repo: https://github.com/DavidAnson/markdownlint-cli2
    rev: v0.14.0
    hooks: [{ id: markdownlint-cli2, files: ^kb/.*\.md$ }]
  - repo: local
    hooks:
      - id: kb-frontmatter
        name: kb frontmatter schema
        entry: tools/kb/validate --check 2 --frontmatter-only
        language: system
        files: ^kb/.*\.md$
```

```yaml
# CI job (any runner): the full gate on every PR
steps:
  - run: pre-commit run --all-files
  - run: tools/kb/validate            # checks 3–8
  - run: tools/kb/build-index && git diff --exit-code kb/index.json llms.txt
```

The `CODEOWNERS` file maps `kb/catalog/systems/svc.billing.yaml` and `kb/guides/billing/` to `team.payments`, so the owner who must review a contract change also owns the prose that explains it.

### 6.4 Lifecycle and archival

A document moves `draft → active → deprecated → archived`; nothing is deleted. Steps to retire a document:

1. Publish the replacement first and give it `supersedes: [<old id>]`.
2. On the old document set `status: deprecated`, `superseded_by: <new id>`, and add a first-line callout: `> **Deprecated:** replaced by [doc.x](...) on 2026-10-19.` Deprecated docs stay in place for one review cycle (for example 30 days) so inbound links get updated; the index marks them and agents are told to follow `superseded_by`.
3. When no active document links to it (check 4 reports inbound links), `git mv` it to `kb/archive/` keeping its relative path, and set `status: archived`.
4. The index builder drops `status: archived` and `kb/archive/**` from `index.json`, `llms.txt` and any embedding pipeline; the archive stays greppable for humans who ask for history.
5. Leave the ID resolvable: `index.json` keeps a `redirects` map `{ old_id: new_id }`, so stale references in tickets or chat logs still land on the current page.

ADRs are the exception: they are never moved. A superseded ADR keeps its file, gets `status: superseded`, and stays in retrieval because the history of a decision is itself the answer to "why".
