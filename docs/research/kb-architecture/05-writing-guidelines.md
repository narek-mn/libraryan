---
title: "5. Docs-as-Code Writing Guidelines"
reviewed: 2026-10-19
source: https://claude.ai/code/artifact/9511a455-029e-465f-8cca-c7eddd7f7cd1
---

# 5. Docs-as-Code Writing Guidelines

Write every `##` section so it can be retrieved alone, cited by its heading, and understood without the page around it. The same rules that make a chunk precise for an agent make a page skimmable for a new engineer.

### 5.1 Page skeleton

```markdown
---
(frontmatter per 4.3)
---
# Runbook — payment provider timeouts

> **Summary:** 504s on POST /v1/charges mean the provider exceeded 10 s. Check provider status,
> then shed load with the circuit breaker. Applies to svc.billing only.

## When this applies            ← scope and symptoms, with exact error strings
## Diagnose payment timeouts     ← steps, commands in fenced blocks
## Mitigate payment timeouts
## Why retries are capped        ← links adr.0031, does not restate it
## Related                       ← doc pointers only
```

- **One H1** = the title, matching `title` in frontmatter.
- **A summary blockquote** of 1–3 sentences directly under it. Indexers and agents read this first; it is also what `index.json` quotes.
- **H2 = chunk boundary.** H3 only to split an H2 that runs long; never H4 or deeper.
- **Headings are specific and searchable:** "Diagnose payment timeouts", not "Diagnosis". A heading read alone in a search result must name its subject.

### 5.2 Chunking rules

| Rule | Target | Why |
| --- | --- | --- |
| Section size | 150–600 words (about 200–800 tokens) per H2 | Fits one retrieval chunk; long enough to hold a complete answer |
| Page size | Under about 2,500 words; split by task beyond that | A whole page still fits a modest context budget alongside code |
| Self-reference | First sentence of each H2 restates the subject ("Payment timeouts are…") | A chunk retrieved alone has no page title; pronouns like "it" lose their referent |
| Chunker | Split on H2, then H3, never mid code block or mid table; prepend `title > H2` path to each chunk | Deterministic boundaries make retrieval reproducible and citations stable |
| Overlap | None needed when sections are self-contained; else about 10% | Overlap papers over sections that were not written to stand alone |
| Key facts placement | State the answer in the first two sentences of a section | Models attend less reliably to the middle of long contexts ([Liu et al., 2023](https://arxiv.org/abs/2307.03172)) |

### 5.3 Lexical and semantic findability

- **Use canonical terms from `glossary.md` exactly**, and list synonyms once in the glossary entry ("also: payout, disbursement"). Grep and BM25 match the canonical term; embeddings pick up the synonyms.
- **Quote exact identifiers in backticks:** error codes (`PAY_TIMEOUT`), env vars, CLI flags, endpoint paths. Lexical search finds them; embeddings blur them.
- **Name catalog IDs in text** (`svc.billing`). They are unique tokens that grep, BM25 and the link checker all resolve.
- **No content in images alone.** A diagram carries a text equivalent: a Mermaid/PlantUML source block or a list of its edges.

### 5.4 Tables, code and callouts

- **Tables:** one entity per row, units in headers (`Timeout (s)`), no merged cells, no empty cells (write `none`). Keep under about 8 columns; wider tables become a YAML list.
- **Code blocks:** always fenced with a language tag; one runnable unit per block; show output in a separate block labelled `text`. Mark placeholders as `<invoice-id>`, never as a realistic-looking value.
- **Callouts:** a bold label at line start inside a blockquote, from a closed set: `**Warning:**`, `**Note:**`, `**Deprecated:**`, `**Requires approval:**`. Plain text survives every renderer and is greppable; avoid renderer-specific admonition syntax.
- **Lists:** numbered for ordered steps, one action per step, the expected result after it.

### 5.5 Style rules

- Active voice, present tense, sentences under 25 words.
- **Declarative over narrative:** "The ledger is append-only", not "We decided at some point that…".
- **Normative words per [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119):** MUST, SHOULD, MAY in tier-1 and tier-2 docs only; guides use plain imperatives.
- **No relative time** ("recently", "the new service"). Use dates and IDs.
- **No restated catalog values.** Write "listens on the port in `svc.billing`", or render the value from the catalog at build time.
- **Every claim that a reader might act on carries a source pointer**, inline as `[adr.0031](../../decisions/0031-...md)` or in frontmatter `sources`.
