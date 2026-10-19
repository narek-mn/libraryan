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
