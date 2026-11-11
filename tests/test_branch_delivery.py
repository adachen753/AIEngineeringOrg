import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from ai_manager.engine import Engine
from ai_manager.git import Worktrees, git, snapshot
from ai_manager.models import AgentResult, Settings


@pytest.fixture
async def delivery(store, submission, monkeypatch):
    engine = Engine(store, Settings(data_dir=store.root))
    await engine.client.aclose()
    engine.client = httpx.AsyncClient(base_url="http://fixture.invalid", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"ready": True})))
    record = store.submit(submission)
    record["status"] = "running"
    store.save(record)
    calls = []

    async def agent(record, role, cwd, prompt):
        calls.append((role, git(cwd, "rev-parse", "HEAD")))
        record["tasks"].setdefault(role, {"id": role, "dependencies": []})
        if role == "dev":
            (cwd / "app" / "delivery.py").write_text("VALUE = 2\n", encoding="utf-8")
        if role == "test":
            (cwd / "tests" / "test_delivery.py").write_text(
                "from app.delivery import VALUE\ndef test_delivery():\n    assert VALUE == 2\n", encoding="utf-8")
        result = AgentResult(status="ready", summary="Fixture approval", acceptance=submission.acceptance,
            questions=[], evidence=["tests/test_delivery.py::test_delivery", git(cwd, "rev-parse", "HEAD")], classification="none",
            mappings=[{"criterion": submission.acceptance[0], "node_ids": ["tests/test_delivery.py::test_delivery"]}])
        record["results"][role] = result.model_dump()
        engine.checkpoint(record)
        return result

    monkeypatch.setattr(engine, "agent", agent)
    yield engine, record, calls
    await engine.client.aclose()


async def through_review(engine, record):
    for stage in ("plan", "dev", "test", "verify", "review"):
        record["stage"] = stage
        await getattr(engine, stage)(record)
        engine.checkpoint(record)


@pytest.mark.asyncio
async def test_delivery_reviews_exact_candidate_then_tests_fixed_integration(delivery, repo, store):
    engine, record, calls = delivery
    original = snapshot(repo)
    await through_review(engine, record)
    candidate = record["commits"]["candidate"]
    assert calls[-1] == ("reviewer", candidate)
    assert record["commits"]["reviewed"] == candidate
    assert record["verification"]["before"]["head"] == candidate
    await engine.integrate(record)
    integration = record["branches"]["integration"]["name"]
    assert integration == "codex/integration/" + record["id"]
    assert git(repo, "rev-parse", "refs/heads/" + integration) == candidate
    await engine.integration_verify(record)
    assert record["stage"] == "report"
    assert record["integration_verification"]["before"] == {"head": candidate, "status": ""}
    assert record["integration_verification"]["after"] == {"head": candidate, "status": ""}
    await engine.report(record)
    assert record["status"] == "succeeded"
    assert snapshot(repo) == original
    assert [role for role, commit in calls] == ["manager", "dev", "test", "reviewer", "manager", "manager"]


@pytest.mark.parametrize("kind", ["feature", "integration"])
def test_foreign_branch_never_overwritten_even_at_same_commit(repo, tmp_path, kind):
    trees = Worktrees(tmp_path / "trees")
    branch = "codex/" + kind + "/foreign"
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "branch", branch, head)
    with pytest.raises(RuntimeError):
        trees.advance_branch(repo, branch, head)
    assert git(repo, "rev-parse", "refs/heads/" + branch) == head


@pytest.mark.asyncio
async def test_feature_ref_compare_and_swap_rejects_external_move(delivery, repo):
    engine, record, calls = delivery
    await through_review(engine, record)
    branch = record["branches"]["feature"]
    git(repo, "update-ref", "refs/heads/" + branch["name"], record["commits"]["base"], branch["head"])
    with pytest.raises(RuntimeError):
        engine.advance_feature(record, branch["head"])
    with pytest.raises(ValueError, match="Feature branch changed"):
        await engine.integrate(record)
    assert "integration" not in record["branches"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["blocked", "polluted"])
async def test_reviewer_must_approve_read_only(delivery, monkeypatch, mutation):
    engine, record, calls = delivery
    for stage in ("plan", "dev", "test", "verify"):
        await getattr(engine, stage)(record)
    original = engine.agent

    async def reviewer(record, role, cwd, prompt):
        result = await original(record, role, cwd, prompt)
        if mutation == "blocked":
            result.status = "blocked"
        else:
            (cwd / "app" / "unexpected.py").write_text("VALUE = 0", encoding="utf-8")
        return result

    monkeypatch.setattr(engine, "agent", reviewer)
    with pytest.raises(ValueError, match="reviewer"):
        await engine.review(record)
    assert "reviewed" not in record["commits"]


@pytest.mark.asyncio
async def test_changed_candidate_requires_new_exact_commit_review(delivery):
    engine, record, calls = delivery
    await through_review(engine, record)
    record["commits"]["candidate"] = record["commits"]["implementation"]
    with pytest.raises(ValueError, match="fixed-commit independent review"):
        await engine.integrate(record)
    with pytest.raises(ValueError, match="fixed commit"):
        await engine.review(record)


@pytest.mark.asyncio
async def test_existing_integration_branch_blocks_manager_delivery(delivery, repo):
    engine, record, calls = delivery
    await through_review(engine, record)
    branch = "codex/integration/" + record["id"]
    git(repo, "branch", branch, record["commits"]["base"])
    with pytest.raises(RuntimeError):
        await engine.integrate(record)
    assert git(repo, "rev-parse", "refs/heads/" + branch) == record["commits"]["base"]
    assert "integration" not in record["commits"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["wrong_commit", "failure", "pollution", "missing_mapping"])
async def test_integration_verification_failures_never_report(delivery, monkeypatch, fault):
    engine, record, calls = delivery
    await through_review(engine, record)
    await engine.integrate(record)
    commit = record["commits"]["integration"]

    async def runner(*args):
        evidence = {"exit_code": 0, "polluted": False, "timed_out": False, "cancelled": False,
            "before": {"head": commit, "status": ""}, "after": {"head": commit, "status": ""},
            "test_results": {"cases": {"tests/test_delivery.py::test_delivery": "passed"}, "collection_errors": []}}
        if fault == "wrong_commit":
            evidence["after"]["head"] = record["commits"]["base"]
        elif fault == "failure":
            evidence["exit_code"] = 1
        elif fault == "pollution":
            evidence["polluted"] = True
        else:
            evidence["test_results"]["cases"] = {"tests/test_feature.py::test_acceptance": "passed"}
        return evidence

    monkeypatch.setattr("ai_manager.engine.run_tests", runner)
    with pytest.raises(ValueError):
        await engine.integration_verify(record)
    assert record["stage"] == "integration_verify"
    assert record["status"] != "succeeded"


@pytest.mark.asyncio
async def test_integration_ref_moved_after_tests_blocks_report(delivery, repo):
    engine, record, calls = delivery
    await through_review(engine, record)
    await engine.integrate(record)
    await engine.integration_verify(record)
    git(repo, "update-ref", "refs/heads/" + record["branches"]["integration"]["name"], record["commits"]["base"])
    with pytest.raises(ValueError, match="moved before report"):
        await engine.report(record)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["ref", "worktree"])
async def test_report_rechecks_ref_and_worktree_after_agent(delivery, repo, monkeypatch, mutation):
    engine, record, calls = delivery
    await through_review(engine, record)
    await engine.integrate(record)
    await engine.integration_verify(record)
    original = engine.agent

    async def reporting(record, role, cwd, prompt):
        result = await original(record, role, cwd, prompt)
        if mutation == "ref":
            git(repo, "update-ref", "refs/heads/" + record["branches"]["integration"]["name"], record["commits"]["base"])
        else:
            (cwd / "app" / "unexpected.py").write_text("VALUE = 0", encoding="utf-8")
        return result

    monkeypatch.setattr(engine, "agent", reporting)
    with pytest.raises(ValueError, match="during report|modified worktree"):
        await engine.report(record)
    assert record["status"] != "succeeded"


def test_adapter_reviewer_has_no_writes_and_remains_fail_closed(repo):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node runtime unavailable")
    adapter = Path(__file__).resolve().parents[1] / "adapter"
    script = """
        import assert from 'node:assert/strict';
        import {validateRequest} from './src/request.ts';
        import {capabilities, requireEnforcedScope} from './src/policy.ts';
        const cwd = JSON.parse(process.argv[1]);
        const input = {run_id:'review-1',thread_id:null,prompt:'Review',cwd,role:'reviewer',timeout_seconds:10,allowed_paths:[]};
        assert.equal(validateRequest(input).role, 'reviewer');
        assert.throws(() => validateRequest({...input,allowed_paths:['app']}));
        assert.throws(() => validateRequest({...input,test_paths:['tests']}));
        assert.equal(capabilities.roles.reviewer, 'blocked');
        assert.throws(requireEnforcedScope);
    """
    subprocess.run([node, "--input-type=module", "-e", script, json.dumps(str(repo))], cwd=adapter, check=True)
