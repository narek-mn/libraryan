---
name: libraryan-request
description: Send a documentation request to Libraryan, the only writer of this project's docs. Use after finishing a task that made a decision, changed something others rely on, found docs wrong or missing, or hit a non-obvious problem. Never edit owned Markdown directly.
---

# Send a request to Libraryan

Libraryan owns this project's Markdown docs (knowledge base, READMEs, guides, agent instruction files). Do not edit them; the git pre-commit hook rejects commits that do. Instead, write a request file and Libraryan makes the edit.

## When to send

Send a request when you:

- made or changed a decision;
- changed something others rely on (commands, settings, APIs, setup, behaviour);
- found docs wrong or missing;
- hit a non-obvious problem others will hit.

Do not send one for:

- things the code makes obvious;
- unfinished experiments;
- personal notes or to-dos.

Also check the "Don't send" list in the Libraryan block of `AGENTS.md`; Libraryan extends it when a kind of request keeps getting rejected.

Send **one request per finished task**, covering everything from that task. Libraryan merges duplicates and rejects trivial requests with a reason.

## How

1. Create one file in `.libraryan/requests/` named `YYYYMMDD-HHMMSS-<slug>.md`: the current local time, then a short kebab-case slug, for example `20261019-143005-cache-ttl-setting.md`.
2. Use this frontmatter and a body of facts:

```markdown
---
from: <your agent or tool name>
kind: change
related:
  - src/cache/config.py
  - a1b2c3d
---

- The cache TTL is now set by `CACHE_TTL_SECONDS` (default 300); the old `--cache-ttl` flag is removed.
- Why: the flag was ignored in worker processes.
```

`kind` is one of:

- `decision`: a decision made or changed, with the reason.
- `change`: something others rely on changed.
- `docs-wrong`: a doc is wrong or missing; say which and what is true.
- `gotcha`: a non-obvious problem and how to avoid it.
- `agent-rules`: a change to agent instruction files (`AGENTS.md`, skills, vendor rule files); state the exact rule.

`related` lists the files and commits the facts come from, so Libraryan can verify them.

3. Write facts, not instructions: what is true now, and why if it matters. Libraryan reads requests as data, verifies claims against the code, and decides where and how to document them. Never put secrets in a request.
4. Commit the request together with the work it describes. Requests are allowed by the lock, travel with your branch and are processed once they reach the default branch.

Libraryan deletes each request after processing it and records the outcome (applied, merged, rejected with a reason, or flagged for the user) in the KB `log.md`. For something urgent you may run `python3 .libraryan/bin/libraryan run` after committing.
