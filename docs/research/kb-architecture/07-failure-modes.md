---
title: "7. Failure Modes & Countermeasures"
reviewed: 2026-10-19
source: https://claude.ai/code/artifact/9511a455-029e-465f-8cca-c7eddd7f7cd1
---

# 7. Failure Modes & Countermeasures

Most KB failures are one of two kinds: the same fact stored twice and drifting, or the right fact stored where no reader finds it. Each item below names the symptom an agent or engineer sees and the structural fix; tick it once the countermeasure is in place.

### 7.1 Structure

- [ ] **Monolithic context dump** — one giant `ARCHITECTURE.md` or root agent file pasted into every prompt. *Symptom:* agents ignore the middle, token budget gone before work starts. *Fix:* root file is a router under 150 lines (section 3); detail lives in H2-sized sections retrieved on demand.
- [ ] **Deep nesting** — `docs/eng/platform/payments/billing/v2/howto/`. *Symptom:* more than two hops from root, duplicate folders, guessing where new docs go. *Fix:* max three levels under `kb/`; domain folders only; type in the filename prefix, not a folder.
- [ ] **Facts duplicated in prose** — port, timeout or owner written in five guides. *Symptom:* agents cite the stale copy confidently. *Fix:* P1; values live in the catalog, prose links the ID, a lint flags literal values that match catalog fields.
- [ ] **Docs far from code** — a wiki nobody opens during a PR. *Symptom:* contract changes ship without doc updates. *Fix:* docs in the repo, CODEOWNERS on both, co-change rule (check 8).
- [ ] **Circular navigation** — A says "see B", B says "see A", neither answers. *Symptom:* agents loop or give up. *Fix:* links point up a tier or sideways to a sibling; the orphan/cycle report (check 12) lists pages with no outbound content beyond links.

### 7.2 Authority and provenance

- [ ] **Flat authority** — meeting notes and specs retrieved with equal weight. *Symptom:* an agent implements what was floated in a meeting, not what was decided. *Fix:* `tier` in frontmatter, tier-4 excluded from default retrieval, conflict rule in `AGENTS.md`.
- [ ] **Unsourced claims** — "the service retries three times". *Symptom:* no way to verify; drift goes unnoticed. *Fix:* `sources` required on tier 3, `quote` pins on claims that gate behaviour.
- [ ] **Edited history** — ADRs rewritten to match the current design. *Symptom:* the "why" is lost; old reasoning repeats. *Fix:* ADRs append-only, supersede by a new ADR.

### 7.3 Retrieval

- [ ] **Context-free chunks** — sections that open with "It also supports…". *Symptom:* retrieved chunk is unusable alone; wrong citations. *Fix:* 5.2 self-reference rule; chunker prepends `title > H2`.
- [ ] **Generic headings** — "Overview", "Details", "Notes" on every page. *Symptom:* search results indistinguishable; anchors collide. *Fix:* headings name their subject (5.1); lint rejects a denylist of generic headings.
- [ ] **Synonym sprawl** — "payout", "disbursement", "settlement" for one concept. *Symptom:* grep misses half the docs; embeddings conflate distinct concepts. *Fix:* glossary with one canonical term and its listed synonyms.
- [ ] **Knowledge locked in images or PDFs** — architecture only in a PNG. *Symptom:* invisible to grep and to text-only agents. *Fix:* diagram source as text (Mermaid/PlantUML) or an edge list beside the image.
- [ ] **Archive in the retrieval path** — superseded pages still indexed. *Symptom:* agents cite deprecated procedures. *Fix:* 6.4; index builder excludes archived status and path.

### 7.4 Format and automation

- [ ] **YAML implicit typing** — `NO`, `1.10`, `on` silently retyped. *Symptom:* wrong values with valid syntax. *Fix:* yamllint `truthy` rule, quoted strings, JSON Schema types.
- [ ] **Schemas that accept anything** — no `additionalProperties: false`, no `required`. *Symptom:* typoed keys (`owenr`) pass and data silently vanishes. *Fix:* closed schemas (section 4).
- [ ] **Ambiguous hooks and checks** — a hook named `docs` that does five things and fails with "error". *Symptom:* people skip it with `--no-verify`; agents cannot fix what they cannot read. *Fix:* one check per hook id, a numbered check table (6.2), messages that name the file, line, rule and fix.
- [ ] **Slow pre-commit** — network link checks on every commit. *Symptom:* hooks bypassed. *Fix:* only local, sub-second checks pre-commit; network and staleness checks weekly.
- [ ] **Generated files edited by hand** — `index.json` patched directly. *Symptom:* next build reverts the fix. *Fix:* `GENERATED` header line, index-freshness check (7) fails on any diff.
- [ ] **Ownerless pages** — no `owner`, nobody gets the staleness issue. *Symptom:* pages rot silently. *Fix:* `owner` required in schema; owner must exist in `kb/catalog/teams/`.
