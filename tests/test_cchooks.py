import subprocess

from libraryan import cchooks, config
from tests.helpers import install_runtime


def _payload(path, tool="Write"):
    return {"tool_name": tool, "tool_input": {"file_path": str(path)}}


def test_guard_blocks_protected_write(repo):
    code, msg = cchooks.guard(_payload(repo / "docs" / "a.md"), repo, config.DEFAULTS, {})
    assert code == 2 and ".libraryan/requests" in msg


def test_guard_allows_code_file(repo):
    assert cchooks.guard(_payload(repo / "src" / "a.py"), repo, config.DEFAULTS, {}) == (0, "")


def test_guard_allows_with_env(repo):
    assert cchooks.guard(_payload(repo / "docs" / "a.md"), repo, config.DEFAULTS, {"LIBRARYAN": "1"}) == (0, "")


def test_guard_allows_request_file(repo):
    p = repo / ".libraryan" / "requests" / "r.md"
    assert cchooks.guard(_payload(p), repo, config.DEFAULTS, {}) == (0, "")


def test_guard_allows_outside_root_and_other_tools(repo, tmp_path_factory):
    out = tmp_path_factory.mktemp("o") / "docs" / "a.md"
    assert cchooks.guard(_payload(out), repo, config.DEFAULTS, {})[0] == 0
    assert cchooks.guard(_payload(repo / "docs" / "a.md", "Bash"), repo, config.DEFAULTS, {})[0] == 0


def test_guard_notebook_path(repo):
    p = {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": str(repo / "docs" / "n.md")}}
    assert cchooks.guard(p, repo, config.DEFAULTS, {})[0] == 2


def test_ensure_hooks_sets_path(repo):
    install_runtime(repo)
    subprocess.run(["git", "config", "--unset", "core.hooksPath"], cwd=repo, check=True)
    cchooks.ensure_hooks(repo)
    out = subprocess.run(["git", "config", "core.hooksPath"], cwd=repo, capture_output=True, text=True).stdout
    assert out.strip() == ".libraryan/hooks"


def test_ensure_hooks_noop_without_hooks_dir(repo):
    cchooks.ensure_hooks(repo)
    assert subprocess.run(["git", "config", "core.hooksPath"], cwd=repo, capture_output=True).returncode == 1


def test_guard_confines_libraryan_run(repo, tmp_path_factory):
    env = {"LIBRARYAN": "1"}
    for p in (repo / "src" / "a.py", repo / ".libraryan" / "config.json",
              repo / ".libraryan" / "requests" / "r.md", tmp_path_factory.mktemp("o") / "a.md"):
        assert cchooks.guard(_payload(p), repo, config.DEFAULTS, env)[0] == 2, p
    assert cchooks.guard(_payload(repo / "docs" / "a.md", "Edit"), repo, config.DEFAULTS, env) == (0, "")
    assert cchooks.guard(_payload(repo / "src" / "a.py", "Bash"), repo, config.DEFAULTS, env) == (0, "")


def test_guard_copilot_path_key(repo):
    # Copilot CLI runs .claude/settings.json hooks but keeps its own argument names (`path`, not `file_path`)
    p = {"tool_name": "Write", "tool_input": {"path": str(repo / "docs" / "a.md"), "file_text": "x"}}
    assert cchooks.guard(p, repo, config.DEFAULTS, {})[0] == 2


PATCH = "*** Begin Patch\n*** Update File: src/a.py\n@@\n-x\n+y\n*** {kind} File: {path}\n+hi\n*** End Patch\n"


def test_guard_apply_patch(repo):
    # Codex (and GPT models in Copilot) edit through apply_patch: the targets are only in the patch text
    for kind in ("Add", "Update", "Delete"):
        p = {"tool_name": "apply_patch", "tool_input": {"command": PATCH.format(kind=kind, path="docs/a.md")}, "cwd": str(repo)}
        assert cchooks.guard(p, repo, config.DEFAULTS, {})[0] == 2, kind
    moved = "*** Begin Patch\n*** Update File: src/a.py\n*** Move to: docs/a.md\n@@\n-x\n+y\n*** End Patch\n"
    assert cchooks.guard({"tool_name": "apply_patch", "tool_input": {"command": moved}, "cwd": str(repo)},
                         repo, config.DEFAULTS, {})[0] == 2
    code_only = PATCH.format(kind="Add", path="src/b.py")
    assert cchooks.guard({"tool_name": "apply_patch", "tool_input": {"command": code_only}, "cwd": str(repo)},
                         repo, config.DEFAULTS, {}) == (0, "")


def test_guard_apply_patch_through_shell(repo):
    cmd = "apply_patch <<'EOF'\n" + PATCH.format(kind="Add", path="docs/a.md") + "EOF\n"
    p = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(repo)}
    assert cchooks.guard(p, repo, config.DEFAULTS, {})[0] == 2
