# Hybrid Human/Agent Knowledge Base Architecture

> Research whitepaper (2026-10-19) on structuring a vendor-agnostic knowledge base for engineers and AI agents:
> typed catalog for facts, Markdown prose for reasons, authority tiers, and CI checks against drift.
> Exported from the shared doc at https://claude.ai/code/artifact/9511a455-029e-465f-8cca-c7eddd7f7cd1; these files are the offline copy.

## Sections

- [1. Executive Architecture Blueprint](01-architecture-blueprint.md): A knowledge base that serves humans and agents equally is two things kept in one repository: a **typed catalog** that machines validate and query, and **prose** that explains why.
- [2. Format Comparison Matrix](02-format-comparison.md): Use **YAML (restricted subset) for hand-edited catalog files, JSON for generated indexes and schemas, Markdown frontmatter for prose metadata**, and TOML only where a toolchain already expects it.
- [3. Canonical Directory & File Topology](03-directory-topology.md): Use a **hybrid layout**: component docs live beside the code they describe, and a central `kb/` holds the catalog, cross-cutting guides, decisions and the archive.
- [4. Universal Schema Specifications](04-schemas.md): Four JSON Schemas (draft 2020-12) cover the whole KB: systems, capabilities, document frontmatter and document pointers.
- [5. Docs-as-Code Writing Guidelines](05-writing-guidelines.md): Write every `##` section so it can be retrieved alone, cited by its heading, and understood without the page around it.
- [6. Governance & Automation Playbook](06-governance-automation.md): Drift is stopped at three gates: a pre-commit hook catches syntax in seconds, CI blocks merges that break schemas, links or authority rules, and a weekly scheduled job flags what time alone made stale.
- [7. Failure Modes & Countermeasures](07-failure-modes.md): Most KB failures are one of two kinds: the same fact stored twice and drifting, or the right fact stored where no reader finds it.
- [Sources](sources.md): Specs, standards and papers cited across the sections, with links.
