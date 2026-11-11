import ast
import asyncio
import os
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from .security import allowed_file, protect, within


def git(cwd: Path, *args):
    protect(cwd.resolve())
    metadata = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir"], cwd=cwd, capture_output=True, text=True, timeout=30)
    if metadata.returncode == 0:
        for directory in metadata.stdout.splitlines():
            protect(Path(directory).resolve())
    result = subprocess.run(["git", "-c", "core.hooksPath=NUL" if os.name == "nt" else "core.hooksPath=/dev/null", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def snapshot(cwd):
    return {"head": git(cwd, "rev-parse", "HEAD"), "status": git(cwd, "status", "--porcelain", "--untracked-files=all", "--ignored")}


class Worktrees:
    def __init__(self, root: Path):
        self.root = root.resolve()
        protect(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, repo: Path, workflow_id, label, commit):
        protect(repo.resolve())
        resolved_commit = git(repo, "rev-parse", "--verify", commit + "^{commit}")
        if git(repo, "ls-tree", "-r", resolved_commit).find("120000 ") >= 0:
            raise ValueError("MVP does not accept repository symlinks")
        directory = within(self.root / workflow_id / label, self.root)
        if directory.exists():
            if snapshot(directory) != {"head": resolved_commit, "status": ""}:
                raise RuntimeError("Existing worktree not clean at expected commit; retained for inspection")
            return directory
        directory.parent.mkdir(parents=True, exist_ok=True)
        git(repo, "worktree", "add", "--detach", str(directory), resolved_commit)
        return directory

    def commit(self, cwd, base, scopes, label, test_scopes=None):
        within(cwd, self.root)
        committed = git(cwd, "diff", "--name-only", base, "HEAD").splitlines()
        working = git(cwd, "diff", "--name-only", "HEAD").splitlines()
        untracked = git(cwd, "ls-files", "--others", "--exclude-standard").splitlines()
        staged = git(cwd, "diff", "--cached", "--name-only").splitlines()
        names = sorted(set(committed + working + untracked + staged))
        if test_scopes and any(Path(name).name in {"conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"} for name in names):
            raise ValueError("Test collection/configuration changes require human review")
        if test_scopes:
            for name in git(cwd, "ls-tree", "-r", "--name-only", base).splitlines():
                if not allowed_file(name, test_scopes):
                    continue
                target = within(cwd / name, cwd)
                if not target.is_file():
                    raise ValueError("Accepted test deletion forbidden: " + name)
                original = git(cwd, "show", base + ":" + name)
                current = target.read_text(encoding="utf-8")
                if original.strip() == current.strip():
                    continue
                if not name.endswith(".py"):
                    raise ValueError("Existing test assets cannot be changed without approval")
                old_tree = ast.parse(original)
                new_tree = ast.parse(current)
                old_nodes = [ast.dump(node, include_attributes=False) for node in old_tree.body]
                new_nodes = [ast.dump(node, include_attributes=False) for node in new_tree.body]
                if any(node not in new_nodes for node in old_nodes):
                    raise ValueError("Existing test assertions/configuration cannot be weakened or changed")
                for node in new_tree.body:
                    if ast.dump(node, include_attributes=False) not in old_nodes:
                        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                            raise ValueError("Only additive test functions allowed in existing test files")
                function_names = [node.name for node in new_tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
                if len(function_names) != len(set(function_names)):
                    raise ValueError("Duplicate test definitions forbidden")
        for name in names:
            if not allowed_file(name, scopes):
                raise ValueError("Unauthorized modification retained: " + name)
            target = within(cwd / name, cwd)
            if target.is_symlink():
                raise ValueError("Symlinks forbidden")
        diff = git(cwd, "diff", base)
        for name in working + untracked + staged:
            git(cwd, "add", "--", name)
        if git(cwd, "diff", "--cached", "--name-only"):
            git(cwd, "-c", "user.name=AI Manager", "-c", "user.email=ai-manager@localhost", "commit", "-m", label)
        return git(cwd, "rev-parse", "HEAD"), diff


async def stop_owned(process):
    if process.returncode is not None:
        return True
    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec("taskkill", "/PID", str(process.pid), "/T", "/F", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await killer.communicate()
    else:
        import signal
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), 10)
        return True
    except asyncio.TimeoutError:
        return False


async def run_tests(cwd, timeout, processes, workflow_id, cancelled, started=None):
    before = snapshot(cwd)
    if before["status"]:
        raise ValueError("Verification directory polluted before execution")
    command = [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    result_path = cwd.parent / ("pytest-" + str(uuid4()) + ".json")
    command = [sys.executable, "-I", "-B", str(Path(__file__).with_name("trusted_runner.py")), str(result_path)]
    environment = {key: value for key, value in os.environ.items() if not any(secret in key.upper() for secret in ("KEY", "TOKEN", "PASSWORD", "SECRET"))}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    process = await asyncio.create_subprocess_exec(*command, cwd=cwd, env=environment, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, start_new_session=os.name != "nt")
    processes[workflow_id] = process
    timed_out = False
    try:
        if started:
            started(process.pid)
        output, _ = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError:
        timed_out = True
        if not await stop_owned(process):
            raise RuntimeError("UNCERTAIN test termination")
        output = b"Test timeout; process tree stopped"
    except asyncio.CancelledError:
        stopped = await asyncio.shield(stop_owned(process))
        if not stopped:
            raise RuntimeError("UNCERTAIN test cancellation; ownership retained")
        raise
    finally:
        if process.returncode is not None:
            processes.pop(workflow_id, None)
    after = snapshot(cwd)
    cases = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {"cases": {}, "collection_errors": ["Missing trusted runner evidence"]}
    return {"command": command, "exit_code": process.returncode, "stdout": output.decode("utf-8", "replace"), "before": before, "after": after,
            "test_results": cases,
            "polluted": before != after, "timed_out": timed_out, "cancelled": cancelled(), "pid": process.pid,
            "python": sys.version, "platform": sys.platform}
