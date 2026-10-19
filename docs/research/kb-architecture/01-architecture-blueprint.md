---
title: "1. Executive Architecture Blueprint"
reviewed: 2026-10-19
source: https://claude.ai/code/artifact/9511a455-029e-465f-8cca-c7eddd7f7cd1
---

# 1. Executive Architecture Blueprint

A knowledge base that serves humans and agents equally is two things kept in one repository: a **typed catalog** that machines validate and query, and **prose** that explains why. Every fact lives in exactly one of them, every prose page declares its authority and owner in frontmatter, and CI fails when the two drift apart.

The design rests on eight principles. Each is enforced by a file convention or a check, not by goodwill.

| # | Principle | Enforced by |
| --- | --- | --- |
| P1 | **Facts are data, reasons are prose.** Ports, owners, dependencies, endpoints and limits live in schema-validated YAML/JSON. Prose links to them and never restates them. | JSON Schema validation in CI; a lint that flags numbers in prose that duplicate catalog fields |
| P2 | **One root, two hops.** A fixed entry file (`AGENTS.md` + `README.md` + `llms.txt`) routes any reader to the right subsystem in at most two link traversals. | Link-depth check from the root |
| P3 | **Every document declares its authority.** Frontmatter carries `tier`, `status`, `owner`, `reviewed`. Higher tiers win conflicts; lower tiers must cite upward. | Frontmatter schema; tier-citation lint |
| P4 | **Stable identifiers over paths.** Documents and catalog entities have immutable IDs (`svc.billing`, `adr.0042`). Links may use paths, but the ID survives renames. | ID uniqueness check; redirect map |
| P5 | **Self-contained chunks.** Each `##` section stands alone: it names its subject, states its scope, and fits one retrieval chunk (about 200–800 tokens). | Section-size lint; heading lint |
| P6 | **Docs change with code.** Documentation for a component lives beside it or is linked from it by ID; a code change that alters a contract must touch its doc in the same pull request. | Ownership file + path-based CI rule |
| P7 | **Retire, never delete.** Superseded material moves to an archive path that retrieval excludes, keeps its ID, and points forward to its replacement. | Archive status in frontmatter; index generator excludes `status: archived` |
| P8 | **Open formats only.** Markdown (CommonMark), YAML 1.2, JSON, JSON Schema, plain git. Any tool that reads files can consume the KB. | No binary or vendor formats in the KB tree |

**How the parts fit.** A reader (human or agent) enters at the root, reads the routing table, and lands on either a catalog entry (what is true) or a guide (how and why). Catalog entries link to their guides by ID; guides link to catalog entries instead of repeating values. Normative specs and ADRs sit above guides in authority; notes and transcripts sit below and are excluded from default retrieval.

```text
                    ┌──────────────────────────────────┐
                    │ Root router                      │   ≤ 2 hops to any page
                    │ AGENTS.md · README.md · llms.txt │
                    └────────────────┬─────────────────┘
          ┌─────────────────┬────────┴────────┬─────────────────┐
          ▼                 ▼                 ▼                 ▼ (opt-in)
 ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
 │ Tier 1 Catalog  │ │ Tier 2 Decisions│ │ Tier 3 Guides   │ │ Tier 4 Notes    │
 │ What is true    │ │ Why it is so    │ │ How to do it    │ │ What was said   │
 │ YAML/JSON,      │ │ ADRs,           │ │ how-tos,        │ │ notes, drafts   │
 │ validated specs │ │ append-only     │ │ runbooks        │ │ opt-in only     │
 └────────▲────────┘ └─────────────────┘ └──┬───────┬──────┘ └────────┬────────┘
          └──── cites by id, never restates ┘       ┊ retire          ┊ retire
 ┌──────────────────────────────────────────────────▼─────────────────▼────────┐
 │ Archive · kept for history, excluded from index and retrieval               │
 └─────────────────────────────────────────────────────────────────────────────┘
```

Guides point at the catalog instead of copying it, notes are reachable only on request, and retired pages leave every retrieval path while staying in git.

**Who it serves.** The [Diátaxis framework](https://diataxis.fr/) gives the prose four kinds (tutorial, how-to, reference, explanation); this blueprint keeps that split and moves most *reference* material out of prose into the catalog, where agents parse it deterministically.
