<!-- libraryan:start -->
## Documentation is managed by Libraryan

Libraryan is the only writer of this project's Markdown docs: the knowledge base, READMEs, guides and agent instruction files, this file included. Markdown that belongs to the code (fixtures, templates, generated files, vendored packages) is not Libraryan's. The exact paths are in `.libraryan/config.json` (`owned`, `excluded`, `exempt`).

- Read the docs freely; start with `index.md` in the knowledge base folder (`kb_root` in the config).
- Do not edit owned files. The commit will be rejected.
- Commit rejected for owned files? If you did not edit these files, Libraryan may be mid-run: unstage them (`git restore --staged <file>`) and commit only your own files. Never discard, stash, or use --no-verify on them.
- To change docs, send a request: write a file in `.libraryan/requests/` as described in `.claude/skills/libraryan-request/SKILL.md`, and commit it with your work.

Send a request when you:

- made or changed a decision;
- changed something others rely on (commands, settings, APIs, setup, behaviour);
- found docs wrong or missing;
- hit a non-obvious problem others will hit.

Don't send:

- things the code makes obvious;
- unfinished experiments;
- personal notes or to-dos.

One request per finished task. Libraryan merges duplicates, rejects trivial ones with a reason, and adds to the "Don't send" list when one kind keeps getting rejected.
<!-- libraryan:end -->
