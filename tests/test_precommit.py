import json
import os
import subprocess

from helpers import install_runtime


def git(repo, *args, env=None, check=True):
    e = {**os.environ, **(env or {})}
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check, env=e)


def commit(repo, *paths, env=None, msg="c"):
    git(repo, "add", "-A", *paths)
    return git(repo, "commit", "-m", msg, env=env, check=False)


def test_precommit_blocks_doc_edit(repo):
    install_runtime(repo)
    (repo / "README.md").write_text("# changed\n")
    r = commit(repo, "README.md")
    assert r.returncode != 0
    assert ".libraryan/requests" in r.stderr and "README.md" in r.stderr


def test_precommit_allows_code(repo):
    install_runtime(repo)
    (repo / "a.py").write_text("x = 1\n")
    assert commit(repo, "a.py").returncode == 0


def test_precommit_allows_request_file(repo):
    install_runtime(repo)
    (repo / ".libraryan/requests").mkdir()
    (repo / ".libraryan/requests/r1.md").write_text("please document the thing\n")
    assert commit(repo, ".libraryan/requests/r1.md").returncode == 0


def test_precommit_allows_libraryan_env(repo):
    install_runtime(repo)
    (repo / "README.md").write_text("# changed\n")
    assert commit(repo, "README.md", env={"LIBRARYAN": "1"}).returncode == 0


def test_precommit_allows_delete_and_pure_rename(repo):
    (repo / "b.md").write_text("# b\n\nsome longer body text for similarity\n")
    (repo / "c.md").write_text("# c\n\nanother longer body text for similarity here\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "docs")
    install_runtime(repo)
    git(repo, "rm", "-q", "b.md")
    git(repo, "mv", "c.md", "d.md")
    r = git(repo, "commit", "-m", "mv", check=False)
    assert r.returncode == 0, r.stderr


def test_precommit_blocks_secret_in_request(repo):
    install_runtime(repo)
    (repo / ".libraryan/requests").mkdir()
    (repo / ".libraryan/requests/r1.md").write_text("key AKIAIOSFODNN7EXAMPLE here\n")
    r = commit(repo, ".libraryan/requests/r1.md")
    assert r.returncode != 0 and "possible secret" in r.stderr


def test_precommit_allows_merge(repo):
    install_runtime(repo)
    git(repo, "checkout", "-q", "-b", "feat")
    (repo / "README.md").write_text("feat\n")
    commit(repo, "README.md", env={"LIBRARYAN": "1"})
    git(repo, "checkout", "-q", "main")
    (repo / "README.md").write_text("main\n")
    commit(repo, "README.md", env={"LIBRARYAN": "1"})
    assert git(repo, "merge", "feat", check=False).returncode != 0
    (repo / "README.md").write_text("resolved\n")
    git(repo, "add", "README.md")
    r = git(repo, "commit", "--no-edit", check=False)
    assert r.returncode == 0, r.stderr


def test_hook_chains_to_existing(repo):
    install_runtime(repo)
    hook = repo / ".git/hooks/pre-commit"
    hook.write_text(f"#!/bin/sh\ntouch {repo}/marker\n")
    hook.chmod(0o755)
    (repo / "a.py").write_text("x = 1\n")
    assert commit(repo, "a.py").returncode == 0
    assert (repo / "marker").exists()


def test_precommit_blocks_quoted_path(repo):
    install_runtime(repo)
    (repo / "docs").mkdir()
    (repo / 'docs/a"b.md').write_text("x\n")
    r = commit(repo, "docs")
    assert r.returncode != 0 and "blocked" in r.stderr


def test_precommit_blocks_rename_into_protected(repo):
    (repo / "scratch").mkdir()
    (repo / "scratch/f.txt").write_text("some longer body text for similarity\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "s")
    install_runtime(repo)
    (repo / "docs").mkdir()
    git(repo, "mv", "scratch/f.txt", "docs/new.md")
    r = git(repo, "commit", "-m", "mv", check=False)
    assert r.returncode != 0 and "docs/new.md" in r.stderr


def test_precommit_scans_staged_not_worktree(repo):
    install_runtime(repo)
    (repo / ".libraryan/requests").mkdir()
    f = repo / ".libraryan/requests/r1.md"
    f.write_text("key AKIAIOSFODNN7EXAMPLE here\n")
    git(repo, "add", str(f))
    f.write_text("clean\n")
    r = git(repo, "commit", "-m", "x", check=False)
    assert r.returncode != 0 and "possible secret" in r.stderr


def test_hook_chains_to_chain_hooks_path(repo):
    install_runtime(repo)
    d = repo / "extra"
    d.mkdir()
    h = d / "pre-commit"
    h.write_text(f"#!/bin/sh\ntouch {repo}/marker2\n")
    h.chmod(0o755)
    cfg = json.loads((repo / ".libraryan/config.json").read_text())
    cfg["chain_hooks_path"] = str(d)
    (repo / ".libraryan/config.json").write_text(json.dumps(cfg))
    (repo / "a.py").write_text("x = 1\n")
    assert commit(repo, "a.py").returncode == 0
    assert (repo / "marker2").exists()


def test_precommit_blocks_commit_all(repo):
    install_runtime(repo)
    (repo / "README.md").write_text("# changed\n")
    r = git(repo, "commit", "-a", "-m", "x", check=False)
    assert r.returncode != 0 and "README.md" in r.stderr
