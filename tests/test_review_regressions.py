import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_manager.git import Worktrees, git, run_tests, snapshot


@pytest.mark.parametrize("metadata_index", [0, 1])
@pytest.mark.parametrize("protected", ["Q:/GraphConnectors/cwzClaude", "q:/GRAPHCONNECTORS/SOURCES/DEV/CWZCLAUDE-SQL"])
def test_git_unit_mock_rejects_protected_metadata_before_mutation(tmp_path, monkeypatch, metadata_index, protected):
    calls = []
    directories = [str(tmp_path / "git-dir"), str(tmp_path / "common-dir")]
    directories[metadata_index] = protected
    def metadata_only(command, **kwargs):
        calls.append(command)
        assert command == ["git", "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir"]
        return SimpleNamespace(returncode=0, stdout="\n".join(directories), stderr="")
    monkeypatch.setattr("ai_manager.git.subprocess.run", metadata_only)
    with pytest.raises(ValueError, match="Protected"):
        git(tmp_path, "add", "--", "authorized-fixture.py")
    assert len(calls) == 1


@pytest.mark.parametrize("addition", [
    "pytestmark = __import__('pytest').mark.skip(reason='fixture bypass')\n",
    "test_acceptance = lambda: None\n",
    "VALUE = 0\n",
    "def helper():\n    return None\n",
    "class AddedTests:\n    pass\n",
])
def test_real_git_rejects_original_ast_plus_module_bypass(repo, tmp_path, addition):
    base = git(repo, "rev-parse", "HEAD")
    trees = Worktrees(tmp_path / "trees")
    cwd = trees.create(repo, "workflow", "test", base)
    target = cwd / "tests" / "test_feature.py"
    original = target.read_text(encoding="utf-8")
    target.write_text(original + "\n" + addition, encoding="utf-8")
    before = snapshot(cwd)
    with pytest.raises(ValueError, match="Only additive test functions"):
        trees.commit(cwd, base, ["tests"], "Rejected fixture bypass", test_scopes=["tests"])
    assert snapshot(cwd) == before
    assert git(cwd, "diff", "--cached", "--name-only") == ""
    assert target.read_text(encoding="utf-8").startswith(original)


@pytest.mark.asyncio
async def test_real_trusted_runner_cannot_be_shadowed_by_repository_pytest(repo, tmp_path):
    (repo / "pytest.py").write_text("raise RuntimeError('repository shadow imported')\n", encoding="utf-8")
    (repo / "tests" / "test_feature.py").write_text(
        "from app.feature import VALUE\ndef test_acceptance():\n    assert VALUE == 2\n", encoding="utf-8")
    git(repo, "add", "--", "pytest.py", "tests/test_feature.py")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@localhost", "commit", "-m", "Authorized runner isolation fixtures")
    cwd = Worktrees(tmp_path / "trees").create(repo, "workflow", "verify", git(repo, "rev-parse", "HEAD"))
    evidence = await run_tests(cwd, 30, {}, "workflow", lambda: False)
    assert evidence["exit_code"] == 1
    assert "repository shadow imported" not in evidence["stdout"]
    assert evidence["test_results"]["cases"] == {"tests/test_feature.py::test_acceptance": "failed"}
    assert evidence["test_results"]["collection_errors"] == []
    command = evidence["command"]
    assert command[:3] == [sys.executable, "-I", "-B"]
    assert Path(command[3]).name == "trusted_runner.py"
    assert not Path(command[3]).resolve().is_relative_to(cwd)
    destination = Path(command[4]).resolve()
    assert not destination.is_relative_to(cwd)
    assert json.loads(destination.read_text(encoding="utf-8")) == evidence["test_results"]
    assert not evidence["polluted"]


@pytest.mark.asyncio
async def test_real_trusted_runner_records_pass_skip_fail_and_collection(repo, tmp_path):
    (repo / "tests" / "test_feature.py").write_text(
        "import pytest\ndef test_pass():\n    assert True\n"
        "@pytest.mark.skip(reason='explicit fixture skip')\ndef test_skip():\n    assert False\n"
        "def test_fail():\n    assert False\n", encoding="utf-8")
    git(repo, "add", "--", "tests/test_feature.py")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@localhost", "commit", "-m", "Authorized structured result fixtures")
    cwd = Worktrees(tmp_path / "trees").create(repo, "workflow", "verify", git(repo, "rev-parse", "HEAD"))
    evidence = await run_tests(cwd, 30, {}, "workflow", lambda: False)
    assert evidence["exit_code"] == 1
    results = evidence["test_results"]
    assert results["cases"] == {"tests/test_feature.py::test_pass": "passed",
                                "tests/test_feature.py::test_skip": "skipped",
                                "tests/test_feature.py::test_fail": "failed"}
    assert set(results["collected"]) == set(results["cases"])
    assert results["collection_errors"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("stopped", [True, False])
async def test_runner_unit_mock_cancellation_shields_stop_and_retains_uncertain_ownership(tmp_path, monkeypatch, stopped):
    started = asyncio.Event()
    stopping = asyncio.Event()
    release = asyncio.Event()
    process = SimpleNamespace(returncode=None, pid=12345)
    async def communicate():
        await asyncio.Event().wait()
    process.communicate = communicate
    async def spawn(*args, **kwargs):
        started.set()
        return process
    stops = []
    async def stop_owned_mock(owned):
        stops.append(owned)
        stopping.set()
        await release.wait()
        if stopped:
            owned.returncode = -1
        return stopped
    monkeypatch.setattr("ai_manager.git.snapshot", lambda cwd: {"head": "fixture", "status": ""})
    monkeypatch.setattr("ai_manager.git.asyncio.create_subprocess_exec", spawn)
    monkeypatch.setattr("ai_manager.git.stop_owned", stop_owned_mock)
    processes = {}
    task = asyncio.create_task(run_tests(tmp_path, 30, processes, "workflow", lambda: False))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    await asyncio.wait_for(stopping.wait(), 2)
    assert processes["workflow"] is process
    assert not task.done()
    release.set()
    if stopped:
        with pytest.raises(asyncio.CancelledError):
            await task
        assert "workflow" not in processes
    else:
        with pytest.raises(RuntimeError, match="UNCERTAIN.*ownership retained"):
            await task
        assert processes["workflow"] is process
    assert stops == [process]


@pytest.mark.asyncio
async def test_real_runner_cancellation_stops_owned_process(repo, tmp_path):
    from ai_manager.git import stop_owned
    (repo / "tests" / "test_feature.py").write_text(
        "import time\ndef test_wait():\n    time.sleep(120)\n", encoding="utf-8")
    git(repo, "add", "--", "tests/test_feature.py")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@localhost", "commit", "-m", "Authorized cancellation fixture")
    cwd = Worktrees(tmp_path / "trees").create(repo, "workflow", "verify", git(repo, "rev-parse", "HEAD"))
    processes = {}
    task = asyncio.create_task(run_tests(cwd, 150, processes, "workflow", lambda: False))
    owned = None
    try:
        for _ in range(100):
            if "workflow" in processes:
                owned = processes["workflow"]
                break
            if task.done():
                pytest.fail("Long-running fixture stopped before cancellation")
            await asyncio.sleep(.1)
        assert owned is not None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 20)
        assert owned.returncode is not None
        assert "workflow" not in processes
        assert snapshot(cwd)["status"] == ""
    finally:
        if not task.done():
            task.cancel()
        if owned is not None and owned.returncode is None:
            await stop_owned(owned)
        if not task.done():
            try:
                await task
            except asyncio.CancelledError:
                pass


@pytest.mark.asyncio
async def test_real_trusted_runner_retains_collection_errors(repo, tmp_path):
    (repo / "tests" / "test_collection.py").write_text(
        "raise RuntimeError('authorized fixture collection failure')\n", encoding="utf-8")
    git(repo, "add", "--", "tests/test_collection.py")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@localhost", "commit", "-m", "Authorized collection error fixture")
    cwd = Worktrees(tmp_path / "trees").create(repo, "workflow", "verify", git(repo, "rev-parse", "HEAD"))
    evidence = await run_tests(cwd, 30, {}, "workflow", lambda: False)
    assert evidence["exit_code"] == 2
    assert evidence["test_results"]["cases"] == {}
    assert any("authorized fixture collection failure" in error for error in evidence["test_results"]["collection_errors"])
    assert not evidence["polluted"]


@pytest.mark.parametrize("name", ["conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"])
def test_real_git_rejects_collection_configuration_additions(repo, tmp_path, name):
    base = git(repo, "rev-parse", "HEAD")
    trees = Worktrees(tmp_path / "trees")
    cwd = trees.create(repo, "workflow", "test", base)
    target = cwd / "tests" / name
    target.write_text("", encoding="utf-8")
    before = snapshot(cwd)
    with pytest.raises(ValueError, match="collection/configuration.*human review"):
        trees.commit(cwd, base, ["tests"], "Rejected collection fixture", test_scopes=["tests"])
    assert snapshot(cwd) == before
    assert target.exists()
    assert git(cwd, "diff", "--cached", "--name-only") == ""
