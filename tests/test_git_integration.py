import pytest

from ai_manager.git import Worktrees, git, run_tests, snapshot


def test_real_worktree_uses_fixed_revision_not_dirty_source(repo, tmp_path):
    base = git(repo, "rev-parse", "HEAD")
    (repo / "app" / "feature.py").write_text("VALUE = 2\n", encoding="utf-8")
    git(repo, "add", "--", "app/feature.py")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@localhost", "commit", "-m", "Later authorized fixture")
    (repo / "app" / "feature.py").write_text("VALUE = 3\n", encoding="utf-8")
    (repo / "personal.txt").write_text("Leave untouched", encoding="utf-8")
    before = snapshot(repo)
    trees = Worktrees(tmp_path / "worktrees")
    cwd = trees.create(repo, "workflow", "verify", base)
    assert snapshot(cwd) == {"head": base, "status": ""}
    assert (cwd / "app" / "feature.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert not (cwd / "personal.txt").exists()
    assert snapshot(repo) == before
    assert trees.create(repo, "workflow", "verify", base) == cwd
    (cwd / "pollution.txt").write_text("retained", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not clean"):
        trees.create(repo, "workflow", "verify", base)
    assert (cwd / "pollution.txt").read_text(encoding="utf-8") == "retained"


def test_real_commit_rejects_out_of_scope_without_staging(repo, tmp_path):
    trees = Worktrees(tmp_path / "worktrees")
    base = git(repo, "rev-parse", "HEAD")
    cwd = trees.create(repo, "workflow", "dev", base)
    (cwd / "tests" / "test_feature.py").write_text("changed", encoding="utf-8")
    before = snapshot(cwd)
    with pytest.raises(ValueError, match="Unauthorized"):
        trees.commit(cwd, base, ["app"], "Must not commit")
    assert snapshot(cwd) == before
    assert git(cwd, "diff", "--cached", "--name-only") == ""


@pytest.mark.asyncio
async def test_real_pytest_executes_fixed_clean_revision(repo, tmp_path):
    trees = Worktrees(tmp_path / "worktrees")
    cwd = trees.create(repo, "workflow", "verify", git(repo, "rev-parse", "HEAD"))
    processes = {}
    started_pids = []
    evidence = await run_tests(cwd, 30, processes, "workflow", lambda: False, started_pids.append)
    assert started_pids == [evidence["pid"]]
    assert evidence["exit_code"] == 0
    assert "1 passed" in evidence["stdout"]
    assert evidence["command"][1:3] == ["-I", "-B"]
    assert evidence["test_results"]["cases"] == {"tests/test_feature.py::test_acceptance": "passed"}
    assert evidence["test_results"]["collection_errors"] == []
    assert evidence["before"] == evidence["after"]
    assert not evidence["polluted"] and not evidence["timed_out"]
    assert processes == {}


@pytest.mark.asyncio
async def test_real_pytest_pollution_is_detected(repo, tmp_path):
    test_file = repo / "tests" / "test_feature.py"
    test_file.write_text("from pathlib import Path\ndef test_acceptance():\n    Path('pollution.txt').write_text('retained')\n    assert 1 == 1\n", encoding="utf-8")
    git(repo, "add", "--", "tests/test_feature.py")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@localhost", "commit", "-m", "Authorized pollution fixture")
    cwd = Worktrees(tmp_path / "worktrees").create(repo, "workflow", "verify", git(repo, "rev-parse", "HEAD"))
    evidence = await run_tests(cwd, 30, {}, "workflow", lambda: False)
    assert evidence["exit_code"] == 0
    assert evidence["polluted"]
    assert (cwd / "pollution.txt").exists()


@pytest.mark.asyncio
async def test_dirty_verification_rejected_before_spawn(repo, tmp_path, monkeypatch):
    cwd = Worktrees(tmp_path / "worktrees").create(repo, "workflow", "verify", git(repo, "rev-parse", "HEAD"))
    (cwd / "dirty.txt").write_text("retained", encoding="utf-8")
    async def forbidden_spawn(*args, **kwargs):
        pytest.fail("Polluted worktree must not execute")
    monkeypatch.setattr("ai_manager.git.asyncio.create_subprocess_exec", forbidden_spawn)
    with pytest.raises(ValueError, match="polluted before"):
        await run_tests(cwd, 30, {}, "workflow", lambda: False)


@pytest.mark.parametrize("mutation", ["delete", "weaken", "duplicate", "rename"])
def test_real_commit_preserves_existing_test_ast(repo, tmp_path, mutation):
    base = git(repo, "rev-parse", "HEAD")
    trees = Worktrees(tmp_path / "worktrees")
    cwd = trees.create(repo, "workflow", "test", base)
    target = cwd / "tests" / "test_feature.py"
    original = target.read_text(encoding="utf-8")
    if mutation == "delete":
        target.unlink()
    elif mutation == "weaken":
        target.write_text(original.replace("assert VALUE == 1", "pass"), encoding="utf-8")
    elif mutation == "rename":
        target.write_text(original.replace("test_acceptance", "test_other"), encoding="utf-8")
    else:
        target.write_text(original + "\ndef test_acceptance():\n    pass\n", encoding="utf-8")
    before = snapshot(cwd)
    with pytest.raises(ValueError):
        trees.commit(cwd, base, ["tests"], "Forbidden test change", test_scopes=["tests"])
    assert snapshot(cwd) == before
    assert git(cwd, "diff", "--cached", "--name-only") == ""


def test_real_commit_allows_additive_test_without_changing_original(repo, tmp_path):
    base = git(repo, "rev-parse", "HEAD")
    trees = Worktrees(tmp_path / "worktrees")
    cwd = trees.create(repo, "workflow", "test", base)
    target = cwd / "tests" / "test_feature.py"
    original = target.read_text(encoding="utf-8")
    target.write_text(original + "\ndef test_boundary():\n    assert isinstance(VALUE, int)\n", encoding="utf-8")
    commit, diff = trees.commit(cwd, base, ["tests"], "Authorized additive fixture", test_scopes=["tests"])
    assert commit != base
    assert target.read_text(encoding="utf-8").startswith(original)
    assert "test_boundary" in diff
    assert snapshot(cwd)["status"] == ""
