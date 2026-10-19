---
title: "2. Format Comparison Matrix"
reviewed: 2026-10-19
source: https://claude.ai/code/artifact/9511a455-029e-465f-8cca-c7eddd7f7cd1
---

# 2. Format Comparison Matrix

Use **YAML (restricted subset) for hand-edited catalog files, JSON for generated indexes and schemas, Markdown frontmatter for prose metadata**, and TOML only where a toolchain already expects it. YAML is the most compact to write and read, but only safe when a schema and a strict loader stop its implicit typing.

| Criterion | JSON | YAML 1.2 (restricted) | TOML 1.0 | Markdown + YAML frontmatter |
| --- | --- | --- | --- | --- |
| Size of one sample catalog record (characters) | 360 pretty / 269 minified | 248 | 268 | Record size + prose body |
| Token cost for agents | High when pretty-printed (braces, quotes, indentation); lowest-ambiguity when minified | Lowest for nested data | Low for flat tables; grows with nested arrays of tables | Metadata cheap; body cost is the prose |
| Parser determinism | Highest: one grammar, no implicit types, one spec ([RFC 8259](https://www.rfc-editor.org/rfc/rfc8259)) | Medium: implicit typing (`NO` → false in YAML 1.1 loaders, `1.10` → 1.1, `null`), anchors, multi-docs; deterministic only with quoting rules + a 1.2 core-schema loader | High: explicit types, but nested structures have several valid spellings | Medium: no formal frontmatter spec; delimiter `---` convention only |
| Comments | None | Yes | Yes | Yes (in body and frontmatter) |
| Human readability and diff quality | Fair; trailing-comma and brace noise in diffs | Best for nested lists and maps | Best for flat config | Best for mixed metadata + explanation |
| Schema validation | Native target of JSON Schema | Validate via JSON Schema after load | Validate via JSON Schema after load | Validate frontmatter via JSON Schema; body via linter |
| Maintenance complexity | Low for machines, tedious for humans | Low if linted; high without a linter | Low for shallow data; awkward deeper than 2 levels | Low; one file carries both layers |
| LLM generation reliability | Highest: strict, easy to verify by parsing | High, but indentation errors are silent structure changes | Medium: less common in training data | High |
| Best role in the KB | Generated `index.json`, schemas, API contracts, tool definitions | Hand-edited catalog entities, capability manifests | Tool configs that already use it | Every prose page's metadata header |

Sample record: one service with owner, tier, two dependencies, one interface and one doc link; the same data serialised four ways. Character counts are a rough proxy for tokens; measure with your own tokenizer before optimising further.

**YAML safety rules** (enforced by `yamllint` + schema):

```yaml
# .yamllint.yaml
extends: default
rules:
  truthy: {allowed-values: ["true", "false"], check-keys: true}  # blocks yes/no/on/off
  document-start: disable
  line-length: {max: 120}
  anchors: {forbid-undeclared-aliases: true, forbid-duplicated-anchors: true}
```

- Quote every string that could be read as another type: country codes, versions (`"1.10"`), IDs with leading zeros.
- One document per file; no anchors or merge keys (`<<:`) in catalog files.
- Load with a YAML 1.2 core-schema or "safe" loader, then validate against JSON Schema before anything consumes it.
