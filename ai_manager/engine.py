import asyncio
import json
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

import httpx
import portalocker
from langgraph.graph import END, START, StateGraph

from .git import Worktrees, git, run_tests, snapshot, stop_owned
from .models import AgentResult, Settings
from .store import Store, now


class GraphState(TypedDict):
    workflow_id: str


def sdk_schema():
    schema = AgentResult.model_json_schema()
    def simplify(value):
        if isinstance(value, list):
            return [simplify(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            return simplify(schema["$defs"][value["$ref"].split("/")[-1]])
        result = {}
        for key, item in value.items():
            if key == "properties":
                result[key] = {name: simplify(child) for name, child in item.items()}
            elif key in {"type", "required", "additionalProperties", "items", "enum", "description"}:
                result[key] = simplify(item)
        return result
    return simplify(schema)


class Engine:
    def __init__(self, store: Store, settings: Settings):
        self.store = store
        self.settings = settings
        self.worktrees = Worktrees(store.root / "worktrees")
        self.processes = {}
        self.client = httpx.AsyncClient(base_url=settings.adapter_url, timeout=20)
        graph = StateGraph(GraphState)
        graph.add_node("stage", self.step)
        graph.add_edge(START, "stage")
        graph.add_edge("stage", END)
        self.graph = graph.compile()

    async def cancel(self, workflow_id):
        record = self.store.get(workflow_id)
        if record["status"] == "succeeded":
            raise ValueError("Completed workflows cannot be cancelled")
        if record["status"] == "cancelled":
            return record
        record["cancel_requested"] = True
        self.store.save(record, "cancel_requested")
        uncertain = False
        resolved_attempts = {}
        for attempt in record["attempts"]:
            if attempt["status"] == "running" and attempt.get("run_id"):
                try:
                    response = await self.client.post(f"/runs/{attempt['run_id']}/cancel")
                    response.raise_for_status()
                    for _ in range(50):
                        result = (await self.client.get(f"/runs/{attempt['run_id']}")).json()
                        if result.get("status") != "running":
                            uncertain = result.get("status") not in {"cancelled", "failed", "succeeded"}
                            if not uncertain:
                                resolved_attempts[attempt["id"]] = result["status"]
                            break
                        await asyncio.sleep(.2)
                    else:
                        uncertain = True
                except Exception:
                    uncertain = True
        process = self.processes.get(workflow_id)
        if process:
            stopped = await stop_owned(process)
            uncertain = not stopped or uncertain
            if stopped:
                for attempt in record["attempts"]:
                    if attempt["role"] == "executor" and attempt["status"] == "running":
                        resolved_attempts[attempt["id"]] = "cancelled"
        record = self.store.get(workflow_id)
        for attempt in record["attempts"]:
            if attempt["id"] in resolved_attempts:
                attempt["status"] = resolved_attempts[attempt["id"]]
                attempt["ended_at"] = now()
        self.store.save(record, "cancellation_reconciliation")
        if record["status"] in {"succeeded", "cancelled", "interrupted"}:
            return record
        record["status"] = "interrupted" if uncertain and record["status"] == "running" else "cancelled"
        record["reason"] = "UNCERTAIN cancellation; manual reconciliation required" if uncertain else "Cancellation confirmed; no further scheduling"
        self.store.save(record, "cancelled")
        return record

    async def recover(self):
        for record in self.store.list():
            unresolved = [attempt for attempt in record["attempts"] if attempt["status"] == "running"]
            if record["status"] != "running" and not unresolved:
                continue
            evidence = {"stage": record["stage"], "attempts": [], "worktrees": {}}
            for label, directory in record["worktrees"].items():
                try:
                    evidence["worktrees"][label] = snapshot(Path(directory))
                except Exception as error:
                    evidence["worktrees"][label] = str(error)
            for attempt in record["attempts"]:
                if attempt["status"] == "running" and attempt.get("run_id"):
                    try:
                        result = (await self.client.get(f"/runs/{attempt['run_id']}")).json()
                        evidence["attempts"].append(result)
                        if result.get("status") == "running":
                            await self.client.post(f"/runs/{attempt['run_id']}/cancel")
                            result = (await self.client.get(f"/runs/{attempt['run_id']}")).json()
                        if result.get("status") in {"succeeded", "failed", "cancelled"}:
                            attempt["status"] = result["status"]
                            attempt["ended_at"] = now()
                    except Exception as error:
                        evidence["attempts"].append({"error": str(error)})
            self.store.artifact(record["id"], "recovery.json", evidence)
            if record["status"] == "running":
                record["status"] = "interrupted"
            record["reason"] = "UNCERTAIN stage interrupted by backend restart; evidence retained, automatic replay forbidden"
            self.store.save(record, "recovered_interrupted")

    async def run_forever(self):
        with portalocker.Lock(str(self.store.root / "worker.lock"), timeout=0):
            await self.recover()
            try:
                while True:
                    if any(attempt["status"] == "running" for record in self.store.list() for attempt in record["attempts"]):
                        await asyncio.sleep(.3)
                        continue
                    queued = [record for record in self.store.list() if record["status"] == "queued"]
                    if queued:
                        await self.graph.ainvoke({"workflow_id": queued[-1]["id"]})
                    else:
                        await asyncio.sleep(.3)
            finally:
                await self.client.aclose()

    def checkpoint(self, record):
        current = self.store.get(record["id"])
        if current["cancel_requested"] or current["status"] in {"cancelled", "interrupted"}:
            raise asyncio.CancelledError("Workflow stopped")
        self.store.save(record)

    async def agent(self, record, role, cwd, prompt):
        prompt += "\nBackend repository root: " + str(cwd) + ". All allowed relative paths and pytest node IDs are relative to this repository root, even if the sandbox command cwd is a narrower authorized subdirectory."
        run_id = str(uuid4())
        task_id = record["tasks"].setdefault(role, {"id": str(uuid4()), "dependencies": []})["id"]
        attempt = {"id": str(uuid4()), "task_id": task_id, "role": role, "stage": record["stage"], "run_id": run_id, "status": "running", "started_at": now()}
        record["attempts"].append(attempt)
        message = {"id": str(uuid4()), "workflow_id": record["id"], "task_id": task_id, "attempt_id": attempt["id"], "sender": "backend", "receiver": role,
                   "type": "task", "code_version": git(cwd, "rev-parse", "HEAD"), "content": prompt, "delivery": "pending", "idempotency_key": run_id}
        record["messages"].append(message)
        self.checkpoint(record)
        request = {"run_id": run_id, "thread_id": record["threads"].get(role), "prompt": prompt, "cwd": str(cwd), "role": role,
                   "timeout_seconds": record["submission"]["timeout_seconds"], "output_schema": sdk_schema(),
                   "allowed_paths": [] if role == "manager" else record["submission"]["test_paths"] if role == "test" else record["submission"]["allowed_paths"]}
        response = await self.client.post("/runs", json=request)
        if response.status_code >= 400:
            attempt["status"] = "failed"
            attempt["ended_at"] = now()
            message["delivery"] = "rejected"
            self.checkpoint(record)
        response.raise_for_status()
        message["delivery"] = "acknowledged"
        self.checkpoint(record)
        cursor = 0
        deadline = asyncio.get_running_loop().time() + record["submission"]["timeout_seconds"] + 20
        while True:
            current = self.store.get(record["id"])
            if current["cancel_requested"]:
                raise asyncio.CancelledError("Workflow cancellation requested")
            result_response = await self.client.get(f"/runs/{run_id}")
            result_response.raise_for_status()
            result = result_response.json()
            if result.get("thread_id"):
                record["threads"][role] = result["thread_id"]
            events = result.get("events", [])
            for event in events[cursor:]:
                self.store.event(record["id"], "agent_event", {"role": role, "run_id": run_id, "event": event})
            cursor = len(events)
            self.checkpoint(record)
            if result["status"] != "running":
                break
            if asyncio.get_running_loop().time() > deadline:
                await self.client.post(f"/runs/{run_id}/cancel")
                raise RuntimeError("UNCERTAIN adapter timeout; verify termination before retry")
            await asyncio.sleep(.3)
        self.store.artifact(record["id"], f"agent-{run_id}.json", result)
        attempt["ended_at"] = now()
        attempt["status"] = result["status"]
        message["delivery"] = "completed" if result["status"] == "succeeded" else "failed"
        self.checkpoint(record)
        if result["status"] != "succeeded":
            raise ValueError("Adapter execution failed: " + str(result.get("error", result["status"])))
        output = result.get("result")
        if isinstance(output, str):
            output = json.loads(output)
        validated = AgentResult.model_validate(output)
        record["results"][role] = validated.model_dump()
        self.checkpoint(record)
        return validated

    async def step(self, state):
        record = self.store.get(state["workflow_id"])
        if record["status"] != "queued":
            return state
        record["status"] = "running"
        self.store.save(record, "stage_started")
        try:
            if not record["submission"]["authorized"]:
                raise ValueError("Explicit repository authorization missing")
            await getattr(self, record["stage"])(record)
            if record["status"] == "running":
                record["status"] = "queued"
            self.checkpoint(record)
        except asyncio.CancelledError:
            current = self.store.get(record["id"])
            if current["cancel_requested"]:
                return state
            if not current["cancel_requested"]:
                for attempt in current["attempts"]:
                    if attempt["role"] == "executor" and attempt["status"] == "running" and current["id"] not in self.processes:
                        attempt["status"] = "cancelled"
                        attempt["ended_at"] = now()
                current["status"] = "interrupted"
                current["reason"] = "UNCERTAIN backend stopped during stage"
                self.store.save(current)
            raise
        except Exception as error:
            current = self.store.get(record["id"])
            if current["status"] != "running":
                return state
            running = any(attempt["status"] == "running" for attempt in current["attempts"])
            current["reason"] = ("UNCERTAIN execution: " if running else "") + str(error)
            current["status"] = "interrupted" if running else "blocked"
            self.store.save(current, "stage_error")
        return state

    async def plan(self, record):
        health = await self.client.get("/health")
        health.raise_for_status()
        capability = health.json()
        if capability.get("ready") is False or capability.get("capabilities", {}).get("ready") is False:
            raise ValueError("Codex adapter blocked: " + str(capability.get("blocker", capability.get("capabilities", {}).get("blocker", "scope enforcement unavailable"))))
        repo = Path(record["submission"]["repo"])
        base = git(repo, "rev-parse", "--verify", record["submission"]["base_commit"] + "^{commit}")
        record["commits"]["base"] = base
        cwd = self.worktrees.create(repo, record["id"], "manager", base)
        record["worktrees"]["manager"] = str(cwd)
        self.checkpoint(record)
        result = await self.agent(record, "manager", cwd,
            "You are Engineering Manager. Read repository read-only. Clarify critical ambiguities; otherwise create implementation and acceptance plan. "
            "Return schema JSON only; preserve ALL provided acceptance conditions, use classification none, evidence concrete expected test cases. No commands that mutate files. Input: " + json.dumps(record["submission"]))
        if result.status == "needs_input":
            record["status"] = "awaiting_input"
            record["reason"] = "\n".join(result.questions)
            return
        if result.status != "ready" or not all(item in result.acceptance for item in record["submission"]["acceptance"]):
            raise ValueError("Manager blocked or narrowed acceptance")
        record["stage"] = "dev"
        record["tasks"]["dev"] = {"id": str(uuid4()), "dependencies": [record["tasks"]["manager"]["id"]]}

    async def dev(self, record):
        repair = record["repair_count"]
        base = record["commits"].get("candidate", record["commits"]["base"]) if repair else record["commits"]["base"]
        label = f"dev-{repair}-retry-{record['retry_count']}"
        cwd = self.worktrees.create(Path(record["submission"]["repo"]), record["id"], label, base)
        record["worktrees"][label] = str(cwd)
        record["worktrees"][f"dev-{repair}"] = str(cwd)
        self.checkpoint(record)
        result = await self.agent(record, "dev", cwd,
            "Implement feature AND meaningful normal/boundary unit tests. Do not commit, change git config, remove tests, weaken assertions, or run unrelated commands. "
            "Only modify authorized relative scopes: " + json.dumps(record["submission"]["allowed_paths"]) +
            ". Preserve accepted tests. Return schema JSON with classification none. Feature/plan: " + json.dumps(record["results"]["manager"]) +
            "\nFeature: " + record["submission"]["feature"] + "\nRepair evidence: " + json.dumps(record.get("verification", {})))
        if result.status != "ready":
            raise ValueError("Dev blocked: " + result.summary)
        commit, diff = self.worktrees.commit(cwd, base, record["submission"]["allowed_paths"], "Implement authorized feature" if not repair else "Repair evidenced product bug", record["submission"]["test_paths"])
        record["commits"]["implementation"] = commit
        self.store.artifact(record["id"], f"dev-{repair}.diff", diff)
        record["stage"] = "test"
        record["tasks"].setdefault("test", {"id": str(uuid4()), "dependencies": [record["tasks"]["dev"]["id"]]})

    async def test(self, record):
        repair = record["repair_count"]
        base = record["commits"]["implementation"]
        label = f"test-{repair}-retry-{record['retry_count']}"
        cwd = self.worktrees.create(Path(record["submission"]["repo"]), record["id"], label, base)
        record["worktrees"][label] = str(cwd)
        record["worktrees"][f"test-{repair}"] = str(cwd)
        self.checkpoint(record)
        result = await self.agent(record, "test", cwd,
            "Independently design acceptance verification and add meaningful normal/boundary pytest tests if missing. Do not modify product code, delete tests, weaken assertions, commit or run tests (backend runs tests). "
            "Modify only scopes " + json.dumps(record["submission"]["test_paths"]) + ". Return schema JSON with mappings for EVERY acceptance criterion, each mapping has criterion exactly matching acceptance text and node_ids of actual pytest tests (relative file::test_function). Evidence also explains normal/boundary coverage. " + json.dumps(record["results"]["manager"]))
        if result.status != "ready" or not result.evidence:
            raise ValueError("Independent Test planning blocked or missing evidence mapping")
        commit, diff = self.worktrees.commit(cwd, base, record["submission"]["test_paths"], "Add independent acceptance tests", record["submission"]["test_paths"])
        changed = git(cwd, "diff", "--name-only", record["commits"]["base"], commit).splitlines()
        from .security import allowed_file
        if not any(allowed_file(name, record["submission"]["test_paths"]) for name in changed):
            raise ValueError("Feature requires real new or changed tests")
        record["commits"]["candidate"] = commit
        self.store.artifact(record["id"], f"test-{repair}.diff", diff)
        self.store.artifact(record["id"], f"candidate-{repair}.diff", git(cwd, "diff", record["commits"]["base"], commit))
        record["stage"] = "verify"

    async def verify(self, record):
        repair = record["repair_count"]
        label = f"verify-{repair}-retry-{record['retry_count']}"
        cwd = self.worktrees.create(Path(record["submission"]["repo"]), record["id"], label, record["commits"]["candidate"])
        record["worktrees"][label] = str(cwd)
        record["worktrees"][f"verify-{repair}"] = str(cwd)
        record["commits"]["verification"] = record["commits"]["candidate"]
        attempt = {"id": str(uuid4()), "role": "executor", "stage": "verify", "status": "running", "started_at": now()}
        record["attempts"].append(attempt)
        self.checkpoint(record)
        def process_started(pid):
            attempt["pid"] = pid
            self.checkpoint(record)
        evidence = await run_tests(cwd, record["submission"]["timeout_seconds"], self.processes, record["id"], lambda: self.store.get(record["id"])["cancel_requested"], process_started)
        evidence["started_at"] = attempt["started_at"]
        evidence["ended_at"] = now()
        record["verification"] = evidence
        attempt["status"] = "succeeded" if evidence["exit_code"] == 0 else "failed"
        attempt["ended_at"] = now()
        self.store.artifact(record["id"], f"verification-{repair}.json", evidence)
        self.checkpoint(record)
        if evidence["cancelled"]:
            raise asyncio.CancelledError()
        if evidence["polluted"] or evidence["timed_out"]:
            raise ValueError("Verification pollution or timeout; retained evidence")
        if evidence["exit_code"] == 0:
            mappings = record["results"]["test"].get("mappings", [])
            criteria = record["results"]["manager"]["acceptance"]
            if {item["criterion"] for item in mappings} != set(criteria):
                raise ValueError("Every acceptance condition needs a structured test mapping")
            executed = evidence.get("test_results", {})
            if executed.get("collection_errors") or not executed.get("cases"):
                raise ValueError("Trusted pytest execution evidence missing or invalid")
            if any(outcome != "passed" for outcome in executed["cases"].values()):
                raise ValueError("Skipped or nonpassing tests cannot satisfy MVP verification")
            for mapping in mappings:
                if not mapping["node_ids"] or any(executed["cases"].get(node_id) != "passed" for node_id in mapping["node_ids"]):
                    raise ValueError("Acceptance test not executed and passed: " + mapping["criterion"])
            record["stage"] = "report"
            return
        test_cwd = Path(record["worktrees"][f"test-{repair}"])
        before = snapshot(test_cwd)
        analysis = await self.agent(record, "test", test_cwd,
            "READ ONLY failure analysis. Do not modify any files. Classify product_bug/test_issue/data_issue/environment/flaky/unknown. "
            "Product bug requires concrete assertion failure and product-code root cause; collection/import failures are environment/unknown. Cite verification artifact and failing test in evidence. " + json.dumps(evidence))
        if snapshot(test_cwd) != before:
            raise ValueError("Failure analysis modified files")
        if repair >= 1 or not analysis.evidence or analysis.classification not in {"product_bug", "test_issue"}:
            raise ValueError("Failure blocked: " + analysis.classification + "; " + analysis.summary)
        if evidence["exit_code"] != 1:
            raise ValueError("Non-assertion pytest failure cannot authorize product repair")
        record["repair_count"] += 1
        record["stage"] = "dev" if analysis.classification == "product_bug" else "test"
        if analysis.classification == "test_issue":
            record["commits"]["implementation"] = record["commits"]["candidate"]

    async def report(self, record):
        cwd = Path(record["worktrees"]["manager"])
        required_acceptance = list(record["results"]["manager"]["acceptance"])
        result = await self.agent(record, "manager", cwd,
            "Summarize verified results using supplied immutable execution evidence. Do not claim independent Reviewer or E2E. "
            "Preserve every acceptance condition. Return schema JSON, evidence mapping acceptance -> independent test reference -> actual overall command/exit. Clearly distinguish per-case mapping claims from executed evidence. " +
            json.dumps({"acceptance": record["results"]["manager"]["acceptance"], "tests": record["results"]["test"], "verification": record["verification"], "commits": record["commits"]}))
        if result.status != "ready" or not all(criterion in result.acceptance for criterion in required_acceptance):
            raise ValueError("Manager report blocked")
        report = {"workflow_id": record["id"], "threads": record["threads"], "commits": record["commits"], "manager_summary": result.model_dump(),
                  "acceptance_mapping": record["results"]["test"]["mappings"], "execution": record["verification"],
                  "limitations": ["No independent code Reviewer", "No E2E/Service Fabric", "Per-case acceptance mapping is agent-provided; backend proves suite command result", "Base-commit red test not yet executed"]}
        self.store.artifact(record["id"], "report.json", report)
        record["stage"] = "done"
        record["status"] = "succeeded"
