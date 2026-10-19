---
title: "3. Canonical Directory & File Topology"
reviewed: 2026-10-19
source: https://claude.ai/code/artifact/9511a455-029e-465f-8cca-c7eddd7f7cd1
---

# 3. Canonical Directory & File Topology

Use a **hybrid layout**: component docs live beside the code they describe, and a central `kb/` holds the catalog, cross-cutting guides, decisions and the archive. No path is deeper than four levels below the repository root, and every directory with content has an index file.

```text
repo/
├── AGENTS.md                     # agent entry: routing table, commands, rules (< 150 lines)
├── README.md                     # human entry: what this is, quick start, link to kb/
├── llms.txt                      # flat link map for agents (llmstxt.org format)
├── CODEOWNERS                    # path → owner map (any host's equivalent); drives review
│
├── kb/
│   ├── index.md                  # human routing page (generated sections + curated intro)
│   ├── index.json                # GENERATED: every doc + entity, id → path, tier, status, summary
│   ├── glossary.md               # one term per ## heading; canonical definitions
│   │
│   ├── catalog/                  # LAYER 1: machine-actionable facts (YAML, schema-validated)
│   │   ├── systems/
│   │   │   ├── svc.billing.yaml
│   │   │   └── db.billing-pg.yaml
│   │   ├── capabilities/         # agent tools and their contracts
│   │   │   └── cap.refund-invoice.yaml
│   │   └── teams/
│   │       └── team.payments.yaml
│   │
│   ├── specs/                    # TIER 1: normative contracts (OpenAPI, AsyncAPI, JSON Schema)
│   │   └── billing.openapi.yaml
│   ├── decisions/                # TIER 2: ADRs, append-only, numbered
│   │   ├── 0001-record-architecture-decisions.md
│   │   └── 0042-use-event-sourcing-for-ledger.md
│   ├── guides/                   # TIER 3: LAYER 2 prose, Diátaxis-typed
│   │   ├── billing/
│   │   │   ├── index.md
│   │   │   ├── explanation-overview.md
│   │   │   ├── howto-issue-refund.md
│   │   │   └── runbook-payment-timeouts.md
│   │   └── onboarding/
│   │       └── tutorial-first-deploy.md
│   ├── notes/                    # TIER 4: meeting notes, RFC drafts; excluded from default retrieval
│   │   └── 2026-10-14-billing-sync.md
│   ├── archive/                  # superseded docs, same filenames, excluded from retrieval
│   │   └── guides/billing/howto-manual-refund.md
│   └── schemas/                  # JSON Schemas that validate everything above
│       ├── system.schema.json
│       ├── capability.schema.json
│       ├── doc-frontmatter.schema.json
│       └── doc-pointer.schema.json
│
├── services/
│   └── billing/
│       ├── AGENTS.md             # nearest-file-wins: local commands + invariants only
│       ├── README.md             # 10-line pointer: catalog id, guides, owner
│       └── src/ …
│
└── tools/kb/                     # validators and generators (any language)
    ├── validate                  # schema + frontmatter + links + tiers
    └── build-index               # writes kb/index.json and llms.txt
```

**Co-located vs central.** Put a document beside the code when it changes with that code and only matters to it (local build commands, module invariants). Put it in `kb/` when it spans components, records a decision, or is read by people who never open that code. The component's `README.md` stays a pointer so the two never duplicate.

**Naming rules.**

| Thing | Pattern | Example |
| --- | --- | --- |
| Prose file | `<diataxis-type>-<kebab-subject>.md` | `howto-issue-refund.md` |
| Catalog entity file | `<kind>.<kebab-name>.yaml`, filename = `id` | `svc.billing.yaml` |
| ADR | `<4-digit seq>-<kebab-title>.md`, never renumbered | `0042-use-event-sourcing-for-ledger.md` |
| Dated note | `YYYY-MM-DD-<kebab-topic>.md` | `2026-10-14-billing-sync.md` |
| Directory | lowercase kebab, singular domain noun | `guides/billing/` |

Lowercase ASCII, hyphens, no spaces: these survive every filesystem, URL and shell, and grep for `refund` finds both the filename and the title.

**Depth and links.** Keep `kb/` at most three levels deep (the archive mirrors original paths, so it may add one) (`kb/guides/billing/file.md`). Link with repository-relative paths from the file (`../../catalog/systems/svc.billing.yaml`) so links work in any git host and offline; reference entities by ID in text (`svc.billing`) so a rename breaks one index entry, not fifty links. The link checker (section 6) resolves both.

**Root entry point.** `AGENTS.md` is the agent's first read ([agents.md](https://agents.md/): plain Markdown, root plus nested files, the nearest file takes precedence). Keep it a router, not an encyclopedia:

```markdown
# AGENTS.md

> Payments platform monorepo. Facts live in kb/catalog (YAML); explanations in kb/guides.
> On conflict: kb/specs > kb/decisions > kb/guides > kb/notes. Never cite kb/archive.

## Route by task
| If you need…                      | Read first                         |
|----------------------------------|------------------------------------|
| What a service is, owns, calls   | kb/catalog/systems/<id>.yaml       |
| An API contract                  | kb/specs/<name>.openapi.yaml       |
| Why something is built this way  | kb/decisions/ (grep the id)        |
| How to do a task                 | kb/guides/<domain>/index.md        |
| Every document with summaries    | kb/index.json                      |

## Commands
- Validate KB: `tools/kb/validate`
- Rebuild index: `tools/kb/build-index`

## Rules
- Do not restate catalog values in prose; link the id.
- A change to a spec or catalog entry updates the guides that cite it in the same PR.
```

`llms.txt` ([llmstxt.org](https://llmstxt.org/)) is generated from `index.json`: an H1, a one-paragraph blockquote summary, H2 sections of `[name](path): summary` links, and an `## Optional` section for material an agent can skip when short on context.
