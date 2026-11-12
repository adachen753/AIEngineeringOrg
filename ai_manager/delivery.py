import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from .git import git, snapshot, stop_owned
from .security import allowed_file, within
from .store import now


ENVIRONMENT_ERRORS = re.compile(r"MSB3644|MSB4236|NETSDK1045|MSB8020|NU1301|NU1101|access (?:is )?denied|certificate|SDK.*not found|permission denied", re.I)
CODE_ERRORS = re.compile(r"\berror\s+(?:CS|SA|CA|IDE)\d+\b", re.I)


def bridge_headers():
    token = os.environ.get("AIM_DESKTOP_BRIDGE_TOKEN", "")
    if len(token) < 32:
        raise ValueError("Configure a desktop bridge token of at least 32 characters outside task files")
    return {"Authorization": "Bearer " + token}


def build_summary(evidence):
    return {key: value for key, value in evidence.items() if key not in {"stdout", "artifacts"}}


class DeliveryWorkflow:
    def __init__(self, engine):
        self.engine = engine

    async def reconcile(self, record):
        confirmed = True
        if not any(item["status"] == "running" and item.get("external_run_id") for item in record["attempts"]):
            return True
        async with httpx.AsyncClient(base_url=record["project_config"]["bridge_url"], headers=bridge_headers(), timeout=10, trust_env=False) as client:
            for attempt in record["attempts"]:
                if attempt["status"] != "running" or not attempt.get("external_run_id"):
                    continue
                try:
                    path = "/runs/" + attempt["external_run_id"]
                    response = await client.post(path + "/cancel")
                    response.raise_for_status()
                    response = await client.get(path)
                    response.raise_for_status()
                    status = response.json().get("status")
                    if status not in {"succeeded", "failed", "cancelled"}:
                        confirmed = False
                    else:
                        attempt["status"] = status
                        attempt["ended_at"] = now()
                except Exception:
                    confirmed = False
        return confirmed

    def remaining(self, record):
        started = datetime.fromisoformat(record["delivery_started_at"])
        remaining = record["submission"]["total_timeout_seconds"] - (datetime.now(timezone.utc) - started).total_seconds()
        if remaining <= 0:
            raise ValueError("Delivery total time limit reached; no further repair or deployment")
        return remaining

    async def step(self, record):
        record.setdefault("delivery_started_at", now())
        self.engine.checkpoint(record)
        stages = {"plan", "architect", "dev", "build", "test", "deploy", "e2e", "assess", "report"}
        if record["stage"] not in stages:
            raise ValueError("Unknown delivery stage")
        timeout = self.remaining(record)
        try:
            await asyncio.wait_for(getattr(self, record["stage"])(record), timeout)
        except asyncio.TimeoutError:
            stopped = await self.engine.cancel(record["id"])
            stopped["reason"] = "Delivery total time limit reached; " + (stopped.get("reason") or "execution stopped")
            self.engine.store.save(stopped, "delivery_deadline_reached")

    def cwd(self, record, label, commit):
        directory = self.engine.worktrees.create(Path(record["submission"]["repo"]), record["id"], label, commit)
        record["worktrees"][label] = str(directory)
        self.engine.checkpoint(record)
        return directory

    async def read_only(self, record, role, cwd, prompt):
        before = snapshot(cwd)
        result = await self.engine.agent(record, role, cwd,
            "READ ONLY. Do not edit files, commit, build, deploy, execute tests or write unit tests. " + prompt)
        if snapshot(cwd) != before:
            raise ValueError("Read-only role changed worktree")
        if result.status == "needs_input":
            record["status"] = "awaiting_input"
            record["reason"] = "\n".join(result.questions) or result.summary
            return None
        if result.status != "ready":
            raise ValueError(role + " blocked: " + result.summary)
        return result

    async def plan(self, record):
        response = await self.engine.client.get("/health")
        response.raise_for_status()
        health = response.json()
        if health.get("ready") is not True:
            raise ValueError("Codex adapter blocked: " + str(health.get("blocker", "verified execution boundary unavailable")))
        profile = record["project_config"]
        if not record["submission"]["deploy_authorized"]:
            raise ValueError("Explicit local deployment/E2E authorization required; file upload cannot grant it")
        async with httpx.AsyncClient(base_url=profile["bridge_url"], headers=bridge_headers(), timeout=10, trust_env=False) as client:
            capability = await client.get("/health")
            capability.raise_for_status()
            bridge = capability.json()
            if bridge.get("protocol") != "aim-desktop-v1" or bridge.get("ready") is not True or profile["resource_id"] not in bridge.get("resources", []):
                raise ValueError("Approved desktop/deployment bridge is not ready for the configured resource")
        base = git(Path(profile["repo"]), "rev-parse", "--verify", record["submission"]["base_commit"] + "^{commit}")
        branch = "codex/feature/" + record["id"]
        existing = record.get("branches", {}).get("feature")
        if existing and existing["head"] != base:
            raise ValueError("Feature branch already advanced; plan cannot be replayed")
        self.engine.worktrees.advance_branch(Path(profile["repo"]), branch, base, existing["head"] if existing else None)
        record.setdefault("branches", {})["feature"] = {"name": branch, "head": base}
        cwd = self.cwd(record, "delivery-manager", base)
        result = await self.read_only(record, "manager", cwd,
            "Plan this feature for Manager -> one Architect -> Dev -> Build/Fix -> Tester deployment/E2E. "
            "No unit tests and no independent Reviewer in this mode. Preserve every supplied acceptance condition. "
            "Clarify material ambiguity, otherwise return ready with classification none. Input: " + json.dumps(record["submission"]))
        if result is None:
            return
        if not set(record["submission"]["acceptance"]).issubset(result.acceptance):
            raise ValueError("Manager narrowed acceptance")
        record["stage"] = "architect"

    async def architect(self, record):
        cwd = self.cwd(record, "delivery-architect", record["commits"]["base"])
        result = await self.read_only(record, "architect", cwd,
            "Produce ONE comprehensive actionable design: existing call chain and source evidence, system/backend boundaries, "
            "API/data compatibility, security/ACL/credentials, reliability/cancellation/retries, minimum file changes, build target, "
            "deployment impact, E2E acceptance and rollback. Self-check the design; do not claim independent design review. "
            "Do not invent environment capability or expand authorization. Manager plan and feature: " +
            json.dumps({"plan": record["results"]["manager"], "feature": record["submission"]["feature"], "profile": record["project_config"]}))
        if result is not None:
            if not result.evidence or result.classification != "none":
                raise ValueError("Architect must provide sourced design without unresolved blocking classification")
            self.engine.store.artifact(record["id"], "design.json", result.model_dump())
            record["stage"] = "dev"

    async def dev(self, record):
        base = record["commits"].get("candidate", record["commits"]["base"])
        label = "delivery-dev-" + str(record["repair_count"])
        cwd = self.cwd(record, label, base)
        result = await self.engine.agent(record, "dev", cwd,
            "Implement the approved feature/design or repair the attached evidenced product/build failure. "
            "DO NOT write, modify, or run unit tests. Do not build, deploy, commit, push, change git configuration or weaken checks. "
            "Only edit authorized source scopes. Backend runs the fixed build. Perform source self-check; no Reviewer stage exists. " +
            json.dumps({"feature": record["submission"]["feature"], "plan": record["results"]["manager"],
                        "design": record["results"]["architect"], "issues": record.get("delivery_issues", [])[-1:],
                        "allowed_paths": record["submission"]["allowed_paths"]}))
        if result.status != "ready" or result.classification != "none":
            raise ValueError("Dev blocked: " + result.summary)
        names = set(git(cwd, "diff", "--name-only", base).splitlines()
                    + git(cwd, "ls-files", "--others", "--exclude-standard").splitlines())
        for name in names:
            parts = Path(name).parts
            if any(part.casefold() in {"test", "tests"} for part in parts) or re.search(r"(?:Tests?\.cs|(?:^|/)test_[^/]+\.py|\.(?:test|spec)\.)", name, re.I):
                raise ValueError("Unit-test changes are disabled in delivery mode: " + name)
        commit, diff = self.engine.worktrees.commit(cwd, base, record["submission"]["allowed_paths"], "Implement feature without unit tests")
        if record["repair_count"] and commit == base:
            raise ValueError("Repair produced no source change")
        record["commits"]["candidate"] = commit
        self.engine.advance_feature(record, commit)
        for message in record["messages"]:
            if message.get("type") == "repair" and message.get("delivery") == "pending":
                message["delivery"] = "completed"
        self.engine.store.artifact(record["id"], label + ".diff", diff)
        record.pop("delivery_build", None)
        record.pop("delivery_e2e", None)
        record["stage"] = "build"

    def repair(self, record, source, evidence, summary):
        issue = {"id": str(uuid4()), "source": source, "receiver": "dev", "commit": record["commits"]["candidate"],
                 "summary": summary, "evidence": evidence, "created_at": now(), "round": record["repair_count"] + 1}
        record.setdefault("delivery_issues", []).append(issue)
        record["messages"].append({"id": issue["id"], "sender": source, "receiver": "dev", "type": "repair",
                                   "code_version": issue["commit"], "content": issue, "delivery": "pending"})
        self.engine.store.artifact(record["id"], "issue-" + issue["id"] + ".json", issue)
        self.engine.checkpoint(record)
        if record["repair_count"] >= record["submission"]["max_fix_rounds"]:
            raise ValueError("Configured repair limit reached; latest issue retained")
        self.remaining(record)
        record["repair_count"] += 1
        record["stage"] = "dev"

    async def build(self, record):
        profile = record["project_config"]
        commit = record["commits"]["candidate"]
        cwd = self.cwd(record, "delivery-build-" + str(record["repair_count"]), commit)
        command = [profile["build_executable"], *profile["build_arguments"]]
        attempt = {"id": str(uuid4()), "role": "executor", "stage": "build", "status": "running", "started_at": now()}
        record["attempts"].append(attempt)
        self.engine.checkpoint(record)
        timeout = min(profile["build_timeout_seconds"], self.remaining(record))
        env = dict(os.environ)
        for key in ("AIM_DESKTOP_BRIDGE_TOKEN", "AIM_PROJECT_CONFIG", "AIM_BRIDGE_CONFIG"):
            env.pop(key, None)
        kwargs = {"creationflags": 0x08000000} if os.name == "nt" else {"start_new_session": True}
        process = await asyncio.create_subprocess_exec(*command, cwd=cwd, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.STDOUT, env=env, **kwargs)
        self.engine.processes[record["id"]] = process
        attempt["pid"] = process.pid
        timed_out = False
        try:
            self.engine.checkpoint(record)
            output, _ = await asyncio.wait_for(process.communicate(), timeout)
        except asyncio.TimeoutError:
            timed_out = True
            if not await stop_owned(process):
                raise RuntimeError("UNCERTAIN build termination")
            output = b"Build timeout; owned process tree stopped"
        except asyncio.CancelledError:
            if not await asyncio.shield(stop_owned(process)):
                raise RuntimeError("UNCERTAIN build cancellation")
            attempt["status"] = "cancelled"
            current = self.engine.store.get(record["id"])
            for saved_attempt in current["attempts"]:
                if saved_attempt["id"] == attempt["id"]:
                    saved_attempt["status"] = "cancelled"
                    saved_attempt["ended_at"] = now()
            self.engine.store.save(current)
            raise
        finally:
            if process.returncode is not None:
                self.engine.processes.pop(record["id"], None)
        attempt["status"] = "succeeded" if process.returncode == 0 and not timed_out else "failed"
        attempt["ended_at"] = now()
        log = output.decode("utf-8", "replace")
        evidence = {"commit": commit, "cwd": str(cwd), "command": command, "exit_code": process.returncode,
                    "stdout": log, "timed_out": timed_out, "started_at": attempt["started_at"], "ended_at": attempt["ended_at"]}
        self.engine.store.artifact(record["id"], "build-" + str(record["repair_count"]) + ".json", evidence)
        self.engine.checkpoint(record)
        if git(cwd, "rev-parse", "HEAD") != commit or git(cwd, "diff", "HEAD", "--name-only"):
            raise ValueError("Build changed tracked source; execution retained for investigation")
        generated = git(cwd, "ls-files", "--others", "--exclude-standard").splitlines()
        if any(not allowed_file(name, profile["build_output_paths"]) for name in generated):
            raise ValueError("Build generated files outside approved output scopes")
        if timed_out or ENVIRONMENT_ERRORS.search(log):
            raise ValueError("Build environment/timeout blocked; no automatic code repair")
        if process.returncode == 0 and CODE_ERRORS.search(log):
            raise ValueError("Build log reports errors despite zero exit code; success rejected")
        if process.returncode != 0:
            if not CODE_ERRORS.search(log):
                raise ValueError("Unclassified build failure; no blind repair")
            feedback = {key: value for key, value in evidence.items() if key != "stdout"}
            feedback["error_excerpt"] = "\n".join(line for line in log.splitlines() if CODE_ERRORS.search(line))[:16000]
            feedback["artifact"] = "build-" + str(record["repair_count"]) + ".json"
            self.repair(record, "build", feedback, "Fix concrete compiler/analyzer errors in the retained build log")
            return
        manifest = []
        for scope in profile["build_output_paths"]:
            path = within(cwd / scope, cwd)
            files = [path] if path.is_file() else sorted(path.rglob("*")) if path.is_dir() else []
            for target in files:
                self.remaining(record)
                if target.is_file():
                    within(target, cwd)
                    digest = hashlib.sha256()
                    with target.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            self.remaining(record)
                            digest.update(chunk)
                    manifest.append({"path": target.relative_to(cwd).as_posix(), "sha256": digest.hexdigest(), "size": target.stat().st_size})
        if not manifest:
            raise ValueError("Build succeeded but no approved deployment artifacts were produced")
        evidence["artifacts"] = manifest
        evidence["artifact_sha256"] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        record["delivery_build"] = evidence
        self.engine.store.artifact(record["id"], "build-" + str(record["repair_count"]) + ".json", evidence)
        branch = "codex/integration/" + record["id"]
        old = record["branches"].get("integration")
        self.engine.worktrees.advance_branch(Path(profile["repo"]), branch, commit, old["head"] if old else None)
        record["branches"]["integration"] = {"name": branch, "head": commit}
        record["commits"]["integration"] = commit
        record["stage"] = "test"

    async def test(self, record):
        cwd = self.cwd(record, "delivery-tester-" + str(record["repair_count"]), record["commits"]["candidate"])
        result = await self.read_only(record, "test", cwd,
            "Plan deployment/E2E verification, NOT unit tests. Use only the approved recipe, scenario and exact check IDs. "
            "Specify expected observations, UI/SSMS evidence, failure triage and rollback risks. Do not execute deployment yourself. " +
            json.dumps({"feature": record["submission"]["feature"], "design": record["results"]["architect"],
                        "acceptance": record["results"]["manager"]["acceptance"],
                        "profile": record["project_config"], "build": build_summary(record["delivery_build"])}))
        if result is not None:
            if not result.evidence or result.classification != "none":
                raise ValueError("Tester plan missing evidence or blocked")
            record["stage"] = "deploy"

    async def bridge(self, record, stage):
        profile = record["project_config"]
        build = record["delivery_build"]
        if build["commit"] != record["commits"]["integration"]:
            raise ValueError("Stale build cannot be deployed or verified")
        job = {"run_id": str(uuid4()), "workflow_id": record["id"], "stage": stage,
               "resource_id": profile["resource_id"], "recipe": profile["deployment_recipe"],
               "scenario": profile["scenario"], "checks": profile["checks"], "commit": build["commit"],
               "artifact_sha256": build["artifact_sha256"], "artifacts": build["artifacts"], "cwd": build["cwd"],
               "feature": record["submission"]["feature"], "acceptance": record["results"]["manager"]["acceptance"],
               "design": record["results"]["architect"], "test_plan": record["results"]["test"],
               "timeout_seconds": int(self.remaining(record))}
        attempt = {"id": str(uuid4()), "role": "desktop_bridge", "stage": stage, "status": "running",
                   "external_run_id": job["run_id"], "started_at": now()}
        record["attempts"].append(attempt)
        self.engine.checkpoint(record)
        async with httpx.AsyncClient(base_url=profile["bridge_url"], headers=bridge_headers(), timeout=15, trust_env=False) as client:
            try:
                response = await client.post("/runs", json=job)
                response.raise_for_status()
                while True:
                    if self.engine.store.get(record["id"])["cancel_requested"]:
                        raise asyncio.CancelledError()
                    self.remaining(record)
                    response = await client.get("/runs/" + job["run_id"])
                    response.raise_for_status()
                    result = response.json()
                    if any(result.get(key) != job[key] for key in ("run_id", "stage", "resource_id", "commit", "artifact_sha256")):
                        raise ValueError("Desktop bridge returned mismatched execution identity")
                    if result.get("status") != "running":
                        break
                    await asyncio.sleep(.5)
            except (Exception, asyncio.CancelledError) as error:
                try:
                    await asyncio.shield(client.post("/runs/" + job["run_id"] + "/cancel"))
                except Exception:
                    pass
                if isinstance(error, asyncio.CancelledError):
                    raise
                raise RuntimeError("UNCERTAIN desktop execution; inspect recorded run before retry")
        if result.get("status") not in {"succeeded", "failed", "cancelled"}:
            raise RuntimeError("UNCERTAIN desktop completion")
        attempt["status"] = result["status"]
        attempt["ended_at"] = now()
        self.engine.store.artifact(record["id"], stage + "-" + str(record["repair_count"]) + ".json", result)
        return result

    async def deploy(self, record):
        if not record["submission"]["deploy_authorized"]:
            raise ValueError("Local deployment authorization missing")
        result = await self.bridge(record, "deploy")
        if result["status"] != "succeeded" or result.get("healthy") is not True or not result.get("evidence"):
            raise ValueError("Deployment failed/unhealthy; no automatic infrastructure cleanup or repair")
        record["delivery_deployment"] = result
        record["stage"] = "e2e"

    async def e2e(self, record):
        result = await self.bridge(record, "e2e")
        checks = result.get("checks")
        expected = record["project_config"]["checks"]
        if not isinstance(checks, list) or len(checks) != len(expected):
            raise ValueError("E2E requires a complete check matrix, not a summary claim")
        if any(not isinstance(item, dict) for item in checks) or {item.get("id") for item in checks} != set(expected):
            raise ValueError("E2E check IDs do not match approved scenario")
        if any(type(item.get("passed")) is not bool or not item.get("evidence") for item in checks):
            raise ValueError("Each E2E check requires boolean outcome and screenshot/query evidence")
        if result["status"] == "succeeded" and not all(item["passed"] for item in checks):
            raise ValueError("E2E success contradicts failed checks")
        mappings = result.get("acceptance_mapping", [])
        criteria = record["results"]["manager"]["acceptance"]
        if not isinstance(mappings, list) or len(mappings) != len(criteria) or any(not isinstance(item, dict) for item in mappings):
            raise ValueError("E2E must map every feature acceptance criterion to executed checks")
        if {item.get("criterion") for item in mappings} != set(criteria):
            raise ValueError("E2E acceptance mapping does not match Manager acceptance")
        if any(not isinstance(item.get("check_ids"), list) or not item["check_ids"] or any(name not in expected for name in item["check_ids"]) for item in mappings):
            raise ValueError("Acceptance mapping references missing E2E checks")
        record["delivery_e2e"] = result
        record["stage"] = "assess"

    async def assess(self, record):
        cwd = Path(record["worktrees"]["delivery-tester-" + str(record["repair_count"])] )
        result = await self.read_only(record, "test", cwd,
            "Assess actual deployment/E2E evidence read-only. Distinguish product_bug/environment/data_issue/flaky/unknown. "
            "A product bug requires failing approved checks plus concrete source root cause and reproducible evidence. "
            "Do not claim build or E2E success without the supplied evidence; no unit tests. " +
            json.dumps({"execution": record["delivery_e2e"], "deployment": record["delivery_deployment"],
                        "design": record["results"]["architect"], "feature": record["submission"]["feature"]}))
        if result is None:
            return
        execution = record["delivery_e2e"]
        passed = execution["status"] == "succeeded" and all(item["passed"] for item in execution["checks"])
        if passed:
            if result.classification != "none":
                raise ValueError("Tester found unresolved failure despite passing checks")
            record["stage"] = "report"
        elif result.classification == "product_bug" and result.evidence and any(not item["passed"] for item in execution["checks"]):
            self.repair(record, "test", {"execution": execution, "analysis": result.model_dump()}, result.summary)
        else:
            raise ValueError("E2E blocked without code repair: " + result.classification + "; " + result.summary)

    async def report(self, record):
        commit = record["commits"]["candidate"]
        required_acceptance = list(record["results"]["manager"]["acceptance"])
        branch = record["branches"]["integration"]
        if git(Path(record["submission"]["repo"]), "rev-parse", "refs/heads/" + branch["name"]) != commit:
            raise ValueError("Integration branch moved before delivery")
        if any(record[key]["commit"] != commit for key in ("delivery_build", "delivery_deployment", "delivery_e2e")):
            raise ValueError("Evidence must describe the delivered integration commit")
        if record["delivery_build"]["exit_code"] != 0 or record["delivery_deployment"]["status"] != "succeeded" or record["delivery_e2e"]["status"] != "succeeded":
            raise ValueError("Successful build, deployment and E2E required before delivery")
        cwd = Path(record["worktrees"]["delivery-manager"])
        summary = await self.read_only(record, "manager", cwd,
            "Summarize the delivered feature using actual supplied build/deploy/E2E evidence. "
            "State explicitly: UT not written/not run, independent code review not performed, no push/main merge. "
            "Map every acceptance condition, identify limits and rollback advice. " + json.dumps({
                "feature": record["submission"]["feature"], "acceptance": required_acceptance,
                "build": build_summary(record["delivery_build"]), "deployment": record["delivery_deployment"],
                "e2e": record["delivery_e2e"], "tester": record["results"]["test"], "branches": record["branches"]}))
        if summary is None:
            return
        if not set(required_acceptance).issubset(summary.acceptance):
            raise ValueError("Delivery summary omitted acceptance conditions")
        report = {"workflow_id": record["id"], "commit": commit, "branches": record["branches"],
                  "summary": summary.model_dump(), "build": record["delivery_build"],
                  "deployment": record["delivery_deployment"], "e2e": record["delivery_e2e"],
                  "repair_count": record["repair_count"], "max_fix_rounds": record["submission"]["max_fix_rounds"],
                  "unit_tests": "NOT_WRITTEN_NOT_RUN", "independent_review": "NOT_PERFORMED",
                  "limitations": ["No automatic push, main merge, cleanup or production deployment"]}
        self.engine.store.artifact(record["id"], "report.json", report)
        record["status"] = "succeeded"
        record["stage"] = "done"
