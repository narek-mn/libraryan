---
title: "4. Universal Schema Specifications"
reviewed: 2026-10-19
source: https://claude.ai/code/artifact/9511a455-029e-465f-8cca-c7eddd7f7cd1
---

# 4. Universal Schema Specifications

Four JSON Schemas (draft 2020-12) cover the whole KB: systems, capabilities, document frontmatter and document pointers. All share one ID pattern, `^[a-z]+\.[a-z0-9-]+$`, so any validator can resolve any reference with a single lookup in `index.json`. Every schema sets `additionalProperties: false`: an unknown key is a typo until proven otherwise.

### 4.1 System definition — `kb/schemas/system.schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "kb/schemas/system.schema.json",
  "title": "System",
  "type": "object",
  "additionalProperties": false,
  "required": ["id", "name", "kind", "owner", "lifecycle", "summary"],
  "properties": {
    "id":        { "type": "string", "pattern": "^(svc|db|queue|lib|ext)\\.[a-z0-9-]+$" },
    "name":      { "type": "string", "maxLength": 80 },
    "kind":      { "enum": ["service", "database", "queue", "library", "external"] },
    "owner":     { "type": "string", "pattern": "^team\\.[a-z0-9-]+$" },
    "lifecycle": { "enum": ["experimental", "production", "deprecated", "retired"] },
    "summary":   { "type": "string", "maxLength": 280, "description": "One sentence; used verbatim in index.json and llms.txt" },
    "depends_on": {
      "type": "array", "uniqueItems": true,
      "items": { "type": "string", "pattern": "^[a-z]+\\.[a-z0-9-]+$" }
    },
    "interfaces": {
      "type": "array",
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["kind", "spec"],
        "properties": {
          "kind": { "enum": ["http", "grpc", "event", "cli", "sql"] },
          "spec": { "type": "string", "description": "Repo-relative path to the normative contract" },
          "port": { "type": "integer", "minimum": 1, "maximum": 65535 }
        }
      }
    },
    "docs":       { "type": "array", "items": { "$ref": "doc-pointer.schema.json" } },
    "deprecated_by": { "type": "string", "pattern": "^[a-z]+\\.[a-z0-9-]+$" }
  },
  "if":   { "properties": { "lifecycle": { "const": "deprecated" } } },
  "then": { "required": ["deprecated_by"] }
}
```

Instance (`kb/catalog/systems/svc.billing.yaml`):

```yaml
id: svc.billing
name: Billing API
kind: service
owner: team.payments
lifecycle: production
summary: Issues invoices and refunds; source of truth for invoice state.
depends_on: [svc.ledger, db.billing-pg]
interfaces:
  - kind: http
    spec: kb/specs/billing.openapi.yaml
    port: 8443
docs:
  - { ref: doc.billing-overview, rel: explanation }
  - { ref: doc.runbook-payment-timeouts, rel: runbook }
```

### 4.2 Agent capability — `kb/schemas/capability.schema.json`

A capability is a tool an agent may call: its contract, side effects and guardrails. Input and output are themselves JSON Schemas, so the same file can be translated into any agent framework's tool definition.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "kb/schemas/capability.schema.json",
  "title": "Capability",
  "type": "object",
  "additionalProperties": false,
  "required": ["id", "summary", "provided_by", "input", "output", "side_effects", "owner"],
  "properties": {
    "id":          { "type": "string", "pattern": "^cap\\.[a-z0-9-]+$" },
    "summary":     { "type": "string", "maxLength": 200, "description": "When to use it, in one sentence an agent can match on" },
    "when_not_to_use": { "type": "string", "maxLength": 200 },
    "provided_by": { "type": "string", "pattern": "^(svc|lib|ext)\\.[a-z0-9-]+$" },
    "invocation": {
      "type": "object", "additionalProperties": false,
      "required": ["kind"],
      "properties": {
        "kind":    { "enum": ["http", "cli", "function"] },
        "target":  { "type": "string", "description": "e.g. 'POST /v1/refunds' or 'tools/refund --invoice <id>'" }
      }
    },
    "input":  { "$ref": "https://json-schema.org/draft/2020-12/schema" },
    "output": { "$ref": "https://json-schema.org/draft/2020-12/schema" },
    "side_effects": { "enum": ["none", "idempotent-write", "non-idempotent-write", "external-notification", "irreversible"] },
    "requires_human_approval": { "type": "boolean", "default": false },
    "preconditions": { "type": "array", "items": { "type": "string" } },
    "errors": {
      "type": "array",
      "items": {
        "type": "object", "additionalProperties": false, "required": ["code", "meaning"],
        "properties": { "code": { "type": "string" }, "meaning": { "type": "string" }, "retry": { "type": "boolean" } }
      }
    },
    "owner": { "type": "string", "pattern": "^team\\.[a-z0-9-]+$" },
    "docs":  { "type": "array", "items": { "$ref": "doc-pointer.schema.json" } }
  },
  "if":   { "properties": { "side_effects": { "const": "irreversible" } } },
  "then": { "required": ["requires_human_approval"], "properties": { "requires_human_approval": { "const": true } } }
}
```

### 4.3 Document frontmatter — `kb/schemas/doc-frontmatter.schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "kb/schemas/doc-frontmatter.schema.json",
  "title": "DocFrontmatter",
  "type": "object",
  "additionalProperties": false,
  "required": ["id", "title", "type", "tier", "status", "owner", "reviewed", "summary"],
  "properties": {
    "id":       { "type": "string", "pattern": "^(doc|adr|spec|note)\\.[a-z0-9-]+$" },
    "title":    { "type": "string", "maxLength": 100 },
    "type":     { "enum": ["tutorial", "howto", "reference", "explanation", "runbook", "adr", "spec", "note"] },
    "tier":     { "type": "integer", "minimum": 1, "maximum": 4, "description": "1 spec, 2 decision, 3 guide, 4 note" },
    "status":   { "enum": ["draft", "active", "deprecated", "superseded", "archived"] },
    "owner":    { "type": "string", "pattern": "^team\\.[a-z0-9-]+$" },
    "reviewed": { "type": "string", "format": "date" },
    "review_every_days": { "type": "integer", "default": 180 },
    "summary":  { "type": "string", "maxLength": 280 },
    "about":    { "type": "array", "items": { "type": "string", "pattern": "^[a-z]+\\.[a-z0-9-]+$" }, "description": "Catalog ids this doc describes" },
    "sources":  { "type": "array", "items": { "$ref": "doc-pointer.schema.json" }, "description": "Higher-tier authorities this doc derives from" },
    "superseded_by": { "type": "string" },
    "supersedes":    { "type": "array", "items": { "type": "string" } }
  },
  "allOf": [
    { "if": { "properties": { "status": { "enum": ["deprecated", "superseded", "archived"] } } }, "then": { "required": ["superseded_by"] } },
    { "if": { "properties": { "tier": { "const": 3 } } }, "then": { "required": ["sources"] } }
  ]
}
```

### 4.4 Document pointer — `kb/schemas/doc-pointer.schema.json`

One shape for every cross-reference, so a single resolver checks them all. `anchor` targets a heading slug; `quote` pins the exact sentence a claim rests on, and the checker fails when that sentence disappears.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "kb/schemas/doc-pointer.schema.json",
  "title": "DocPointer",
  "type": "object",
  "additionalProperties": false,
  "required": ["ref"],
  "properties": {
    "ref":    { "type": "string", "description": "Stable id (doc.x, adr.0042, svc.y) or repo-relative path" },
    "anchor": { "type": "string", "pattern": "^[a-z0-9-]+$" },
    "rel":    { "enum": ["explanation", "howto", "runbook", "spec", "decision", "source", "see-also"] },
    "quote":  { "type": "string", "maxLength": 300 }
  }
}
```

A guide's frontmatter using all four:

```markdown
---
id: doc.runbook-payment-timeouts
title: Runbook — payment provider timeouts
type: runbook
tier: 3
status: active
owner: team.payments
reviewed: 2026-09-30
summary: Diagnose and mitigate 504s from the payment provider on POST /v1/charges.
about: [svc.billing, ext.payment-provider]
sources:
  - { ref: kb/specs/billing.openapi.yaml, anchor: post-v1-charges, rel: spec }
  - { ref: adr.0031, rel: decision, quote: "Retries use exponential backoff capped at 3 attempts." }
---
```
