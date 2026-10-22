# libraryan

Project rules (stdlib only, never call the real `claude` in tests, commit
style, README and CHANGELOG on behaviour change): @CONTRIBUTING.md

## Check your work before saying it is done

1. `python3 -m pytest tests -q` must pass.
   The two packaging tests skip when the system setuptools is older than 77.
   To run all of them, use a throwaway venv:
   `python3 -m venv /tmp/lv && /tmp/lv/bin/pip install pytest "setuptools>=77"`,
   then `/tmp/lv/bin/python -m pytest tests -q`.
2. CI runs Python 3.10 to 3.13 on Linux and macOS. Do not use syntax or
   standard-library features newer than 3.10.
3. If you changed what a command does, run it from source and read the output:
   `python3 -c 'import sys; from libraryan.cli import entry; sys.argv=["libraryan","check"]; entry()'`
   Test `fix` against a throwaway repo, never this one.
