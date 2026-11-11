import asyncio

import httpx
import pytest
from pydantic import ValidationError

from ai_manager.engine import Engine
from ai_manager.git import snapshot
from ai_manager.models import AgentResult, Settings


@pytest.fixture
async def engine(store):
    instance = Engine(store, Settings(data_dir=store.root))
    yield instance
    await instance.client.aclose()


async def mock_http(engine, handler):
    await engine.client.aclose()
    engine.client = httpx.AsyncClient(base_url="http://unit-test.invalid", transport=httpx.MockTransport(handler))


def running_record(store, submission, stage="plan"):
    record = store.submit(submission)
    record.update(status="running", stage=stage)
    store.save(record)
    return record


def agent_result(classification="none"):
    return AgentResult(status="ready", summary="Unit-test mock analysis", acceptance=["Returns the requested value"],
                       questions=[], evidence=["tests/test_feature.py::test_acceptance"], classification=classification,
                       mappings=[{"criterion": "Returns the requested value", "node_ids": ["tests/test_feature.py::test_acceptance"]}])


@pytest.mark.asyncio
@pytest.mark.parametrize("remote_status", ["running", "succeeded", "unreachable"])
async def test_recovery_is_uncertain_interrupted_and_never_replays(engine, store, submission, repo, monkeypatch, remote_status):
    record = running_record(store, submission)
    record["attempts"] = [{"id": "mock-attempt", "role": "manager", "status": "running", "run_id": "mock-run"}]
    record["worktrees"] = {"manager": str(repo)}
    store.save(record)
    requests = []
    def handler(request):
        requests.append((request.method, request.url.path))
        if remote_status == "unreachable":
            raise httpx.ConnectError("Mock offline", request=request)
        return httpx.Response(200, json={"status": remote_status})
    await mock_http(engine, handler)
    async def forbidden_stage(record):
        pytest.fail("Recovery must never replay interrupted work")
    monkeypatch.setattr(engine, "plan", forbidden_stage)
    await engine.recover()
    recovered = store.get(record["id"])
    assert recovered["status"] == "interrupted"
    assert recovered["reason"].startswith("UNCERTAIN")
    assert store.artifact_path(record["id"], "recovery.json").exists()
    await engine.step({"workflow_id": record["id"]})
    with pytest.raises(ValueError):
        store.control(record["id"], "retry")
    assert ("POST", "/runs") not in requests
    if remote_status == "running":
        assert ("POST", "/runs/mock-run/cancel") in requests
    else:
        assert len(requests) == 1
    assert snapshot(repo)["status"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {**agent_result().model_dump(), "status": "success"},
                                      {**agent_result().model_dump(), "extra": True},
                                      {**agent_result().model_dump(), "evidence": "not-a-list"}])
async def test_http_unit_mock_invalid_agent_schema_blocks_without_recorded_result(engine, store, submission, repo, payload):
    record = running_record(store, submission)
    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"status": "running"})
        return httpx.Response(200, json={"status": "succeeded", "result": payload})
    await mock_http(engine, handler)
    with pytest.raises(ValidationError):
        await engine.agent(record, "manager", repo, "Unit-test mock task")
    saved = store.get(record["id"])
    assert "manager" not in saved["results"]
    assert saved["attempts"][-1]["status"] == "succeeded"
    assert len(store.artifacts(record["id"])) == 1


@pytest.mark.asyncio
async def test_schema_error_through_step_blocks_not_replays(engine, store, submission, monkeypatch):
    record = store.submit(submission)
    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"ready": True})
        return httpx.Response(200, json={"status": "succeeded", "result": {}})
    await mock_http(engine, handler)
    await engine.step({"workflow_id": record["id"]})
    assert store.get(record["id"])["status"] == "blocked"
    assert store.get(record["id"])["stage"] == "plan"


@pytest.mark.asyncio
@pytest.mark.parametrize("classification,repair,exit_code,expected", [
    ("product_bug", 0, 1, "dev"), ("test_issue", 0, 1, "test"),
    ("environment", 0, 1, None), ("data_issue", 0, 1, None),
    ("flaky", 0, 1, None), ("unknown", 0, 1, None),
    ("product_bug", 1, 1, None), ("test_issue", 1, 1, None),
    ("product_bug", 0, 2, None), ("test_issue", 0, 2, None),
])
async def test_unit_mock_failure_classification_routes_once(engine, store, submission, repo, monkeypatch, classification, repair, exit_code, expected):
    record = running_record(store, submission, "verify")
    record["repair_count"] = repair
    record["commits"]["candidate"] = submission.base_commit
    record["worktrees"][f"test-{repair}"] = str(repo)
    store.save(record)
    prompts = []
    async def mock_runner(*args):
        return {"exit_code": exit_code, "stdout": "Unit-test simulated assertion or collection failure",
                "polluted": False, "timed_out": False, "cancelled": False,
                "test_results": {"cases": {"tests/test_feature.py::test_acceptance": "failed"} if exit_code == 1 else {},
                                 "collection_errors": [] if exit_code == 1 else ["Mock collection failure"]}}
    async def mock_agent(record, role, cwd, prompt):
        prompts.append(prompt)
        return agent_result(classification)
    monkeypatch.setattr("ai_manager.engine.run_tests", mock_runner)
    monkeypatch.setattr(engine, "agent", mock_agent)
    if expected:
        await engine.verify(record)
        assert record["stage"] == expected
        assert record["repair_count"] == 1
        if expected == "test":
            assert record["commits"]["implementation"] == submission.base_commit
    else:
        with pytest.raises(ValueError):
            await engine.verify(record)
        assert record["repair_count"] == repair
        assert record["stage"] == "verify"
    assert len(prompts) == 1
    assert "READ ONLY" in prompts[0]
    assert snapshot(repo)["status"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["delete", "weaken"])
async def test_unit_mock_agent_cannot_remove_or_weaken_accepted_tests(engine, store, submission, monkeypatch, mutation):
    record = running_record(store, submission, "test")
    record["repair_count"] = 1
    record["commits"]["implementation"] = submission.base_commit
    record["results"]["manager"] = agent_result().model_dump()
    store.save(record)
    async def malicious_mock_agent(record, role, cwd, prompt):
        target = cwd / "tests" / "test_feature.py"
        if mutation == "delete":
            target.unlink()
        else:
            target.write_text("def test_acceptance():\n    pass\n", encoding="utf-8")
        return agent_result("test_issue")
    monkeypatch.setattr(engine, "agent", malicious_mock_agent)
    with pytest.raises(ValueError):
        await engine.test(record)
    assert record["stage"] == "test"
    assert "candidate" not in record["commits"]


@pytest.mark.asyncio
@pytest.mark.parametrize("polluted,timed_out", [(True, False), (False, True)])
async def test_unit_mock_verification_pollution_or_timeout_never_authorizes_repair(engine, store, submission, monkeypatch, polluted, timed_out):
    record = running_record(store, submission, "verify")
    record["commits"]["candidate"] = submission.base_commit
    store.save(record)
    async def mock_runner(*args):
        return {"exit_code": 1, "stdout": "Unit-test simulated unsafe execution",
                "polluted": polluted, "timed_out": timed_out, "cancelled": False}
    async def forbidden_agent(*args):
        pytest.fail("Unsafe verification must not authorize agent repair")
    monkeypatch.setattr("ai_manager.engine.run_tests", mock_runner)
    monkeypatch.setattr(engine, "agent", forbidden_agent)
    with pytest.raises(ValueError, match="pollution or timeout"):
        await engine.verify(record)
    assert record["repair_count"] == 0
    assert record["stage"] == "verify"
    assert store.artifact_path(record["id"], "verification-0.json").exists()


@pytest.mark.asyncio
async def test_unit_mock_failure_analysis_must_remain_read_only(engine, store, submission, repo, monkeypatch):
    record = running_record(store, submission, "verify")
    record["commits"]["candidate"] = submission.base_commit
    record["worktrees"]["test-0"] = str(repo)
    store.save(record)
    async def mock_runner(*args):
        return {"exit_code": 1, "stdout": "Unit-test simulated failure",
                "polluted": False, "timed_out": False, "cancelled": False}
    async def modifying_agent(record, role, cwd, prompt):
        (cwd / "tests" / "test_feature.py").write_text("VALUE = 0\n", encoding="utf-8")
        return agent_result("product_bug")
    monkeypatch.setattr("ai_manager.engine.run_tests", mock_runner)
    monkeypatch.setattr(engine, "agent", modifying_agent)
    with pytest.raises(ValueError, match="analysis modified"):
        await engine.verify(record)
    assert record["repair_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("health", [{"ready": False, "blocker": "scope enforcement unavailable"},
                                    {"capabilities": {"ready": False, "blocker": "scope enforcement unavailable"}}])
async def test_http_unit_mock_capability_preflight_blocks_without_side_effects(engine, store, submission, repo, monkeypatch, health):
    record = store.submit(submission)
    before = snapshot(repo)
    requests = []
    def handler(request):
        requests.append(request.url.path)
        assert request.method == "GET" and request.url.path == "/health"
        return httpx.Response(200, json=health)
    await mock_http(engine, handler)
    def forbidden_worktree(*args):
        pytest.fail("Known capability blocker must not create worktrees")
    monkeypatch.setattr(engine.worktrees, "create", forbidden_worktree)
    await engine.step({"workflow_id": record["id"]})
    saved = store.get(record["id"])
    assert saved["status"] == "blocked"
    assert "scope enforcement" in saved["reason"]
    assert saved["attempts"] == [] and saved["messages"] == []
    assert saved["worktrees"] == {}
    assert requests == ["/health"]
    assert snapshot(repo) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [400, 503, "timeout"])
async def test_http_unit_mock_explicit_rejection_is_known_but_timeout_uncertain(engine, store, submission, response):
    record = store.submit(submission)
    requests = []
    def handler(request):
        requests.append((request.method, request.url.path))
        if request.url.path == "/health":
            return httpx.Response(200, json={"ready": True})
        assert request.method == "POST" and request.url.path == "/runs"
        if response == "timeout":
            raise httpx.ReadTimeout("Mock acknowledgement lost", request=request)
        return httpx.Response(response, json={"error": "Mock explicit rejection"})
    await mock_http(engine, handler)
    await engine.step({"workflow_id": record["id"]})
    saved = store.get(record["id"])
    assert requests == [("GET", "/health"), ("POST", "/runs")]
    assert "manager" not in saved["results"]
    if response == "timeout":
        assert saved["status"] == "interrupted"
        assert saved["reason"].startswith("UNCERTAIN")
        assert saved["attempts"][-1]["status"] == "running"
        with pytest.raises(ValueError):
            store.control(record["id"], "retry")
    else:
        assert saved["status"] == "blocked"
        assert not saved["reason"].startswith("UNCERTAIN")
        assert saved["attempts"][-1]["status"] == "failed"
        assert saved["messages"][-1]["delivery"] == "rejected"


@pytest.mark.asyncio
async def test_user_cancellation_returns_state_without_stopping_worker(engine, store, submission, monkeypatch):
    record = store.submit(submission)
    calls = []
    async def cancel_stage(record):
        calls.append(record["id"])
        store.control(record["id"], "cancel")
        raise asyncio.CancelledError()
    monkeypatch.setattr(engine, "plan", cancel_stage)
    state = {"workflow_id": record["id"]}
    assert await engine.step(state) == state
    assert store.get(record["id"])["status"] == "cancelled"
    assert await engine.step(state) == state
    assert calls == [record["id"]]


@pytest.mark.asyncio
async def test_unexpected_backend_cancellation_is_interrupted(engine, store, submission, monkeypatch):
    record = store.submit(submission)
    async def interrupted_stage(record):
        raise asyncio.CancelledError()
    monkeypatch.setattr(engine, "plan", interrupted_stage)
    with pytest.raises(asyncio.CancelledError):
        await engine.step({"workflow_id": record["id"]})
    saved = store.get(record["id"])
    assert saved["status"] == "interrupted"
    assert saved["reason"].startswith("UNCERTAIN")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["passed", "missing_mapping", "wrong_criterion", "skipped", "failed", "unmapped_skip", "missing_node", "empty_cases", "collection_error"])
async def test_unit_mock_success_requires_every_acceptance_mapped_to_passed_nodeids(engine, store, submission, monkeypatch, case):
    record = running_record(store, submission, "verify")
    record["commits"]["candidate"] = submission.base_commit
    manager = agent_result().model_dump()
    tests = agent_result().model_dump()
    node_id = "tests/test_feature.py::test_acceptance"
    results = {"collected": [node_id], "cases": {node_id: "passed"}, "collection_errors": []}
    if case == "missing_mapping":
        tests["mappings"] = []
    elif case == "wrong_criterion":
        tests["mappings"][0]["criterion"] = "Different acceptance"
    elif case in {"skipped", "failed"}:
        results["cases"][node_id] = case
    elif case == "unmapped_skip":
        results["cases"]["tests/test_feature.py::test_unmapped"] = "skipped"
    elif case == "missing_node":
        tests["mappings"][0]["node_ids"] = ["tests/test_feature.py::not_executed"]
    elif case == "empty_cases":
        results["cases"] = {}
    elif case == "collection_error":
        results["collection_errors"] = ["Mock collection failure"]
    record["results"].update(manager=manager, test=tests)
    store.save(record)
    async def mock_runner(*args):
        args[-1](12345)
        assert store.get(record["id"])["attempts"][-1]["pid"] == 12345
        return {"exit_code": 0, "stdout": "Unit-test mocked suite exit zero",
                "polluted": False, "timed_out": False, "cancelled": False, "test_results": results,
                "before": {"head": submission.base_commit, "status": ""}, "after": {"head": submission.base_commit, "status": ""}}
    monkeypatch.setattr("ai_manager.engine.run_tests", mock_runner)
    if case == "passed":
        await engine.verify(record)
        assert record["stage"] == "review"
        assert record["status"] == "running"
    else:
        with pytest.raises(ValueError):
            await engine.verify(record)
        assert record["stage"] == "verify"
        assert record["status"] != "succeeded"
    assert record["repair_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("remote_status", ["running", "succeeded"])
async def test_http_unit_mock_worker_blocks_until_interrupted_attempt_reconciled(engine, store, submission, monkeypatch, remote_status):
    interrupted = running_record(store, submission)
    interrupted["attempts"] = [{"id": "old-attempt", "role": "manager", "status": "running", "run_id": "old-run"}]
    interrupted["status"] = "interrupted"
    store.save(interrupted)
    queued = store.submit(submission.model_copy(update={"idempotency_key": "second-key"}))
    scheduled = asyncio.Event()
    calls = []
    def handler(request):
        return httpx.Response(200, json={"status": remote_status})
    await mock_http(engine, handler)
    async def mock_graph(state):
        calls.append(state)
        store.control(state["workflow_id"], "cancel")
        scheduled.set()
    monkeypatch.setattr(engine.graph, "ainvoke", mock_graph)
    worker = asyncio.create_task(engine.run_forever())
    try:
        for _ in range(100):
            if any(event["type"] == "recovered_interrupted" for event in store.events(interrupted["id"])):
                break
            await asyncio.sleep(.02)
        else:
            pytest.fail("Recovery did not finish")
        recovered = store.get(interrupted["id"])
        assert recovered["status"] == "interrupted"
        if remote_status == "running":
            await asyncio.sleep(.4)
            assert calls == []
            assert recovered["attempts"][0]["status"] == "running"
            assert store.get(queued["id"])["status"] == "queued"
        else:
            await asyncio.wait_for(scheduled.wait(), 2)
            assert recovered["attempts"][0]["status"] == "succeeded"
            assert calls == [{"workflow_id": queued["id"]}]
    finally:
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker


@pytest.mark.asyncio
async def test_unit_mock_explicit_retry_uses_new_worktree_and_retains_old_pollution(engine, store, submission, repo, monkeypatch):
    record = running_record(store, submission, "dev")
    branch = "codex/feature/" + record["id"]
    engine.worktrees.advance_branch(repo, branch, submission.base_commit)
    record["branches"] = {"feature": {"name": branch, "head": submission.base_commit}}
    record["results"]["manager"] = agent_result().model_dump()
    record["tasks"]["dev"] = {"id": "dev-task", "dependencies": []}
    store.save(record)
    visited = []
    async def mock_agent(record, role, cwd, prompt):
        visited.append(cwd)
        (cwd / "app" / "feature.py").write_text("VALUE = 2\n", encoding="utf-8")
        if len(visited) == 1:
            return agent_result().model_copy(update={"status": "blocked"})
        return agent_result()
    monkeypatch.setattr(engine, "agent", mock_agent)
    with pytest.raises(ValueError, match="Dev blocked"):
        await engine.dev(record)
    old = visited[0]
    record.update(status="blocked", reason="Known agent rejection")
    store.save(record)
    retried = store.control(record["id"], "retry")
    retried["status"] = "running"
    store.save(retried)
    await engine.dev(retried)
    new = visited[1]
    assert new != old
    assert old.name == "dev-0-retry-0" and new.name == "dev-0-retry-1"
    assert (old / "app" / "feature.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert snapshot(old)["status"]
    assert snapshot(new)["status"] == ""
    assert retried["stage"] == "test"
    assert retried["retry_count"] == 1
