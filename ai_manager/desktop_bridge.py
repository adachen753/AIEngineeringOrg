import asyncio
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import portalocker
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .git import stop_owned
from .security import protect, redact, within
from .store import now


class DesktopJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    workflow_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    stage: Literal["deploy", "e2e"]
    resource_id: str
    recipe: str
    scenario: str
    checks: list[str] = Field(min_length=1)
    commit: str = Field(pattern=r"^[0-9a-fA-F]{40,64}$")
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifacts: list[dict] = Field(min_length=1)
    cwd: str
    feature: str = Field(min_length=1, max_length=12000)
    acceptance: list[str] = Field(min_length=1)
    design: dict
    test_plan: dict
    timeout_seconds: int = Field(ge=1, le=86400)


class DesktopBridge:
    def __init__(self, path):
        source = Path(path).resolve()
        protect(source)
        if source.stat().st_size > 65536:
            raise ValueError("Bridge config exceeds 64 KiB")
        config = json.loads(source.read_text(encoding="utf-8-sig"))
        if set(config) != {"version", "enabled", "data_dir", "artifact_root", "resources"} or config["version"] != 1 or config["enabled"] is not True:
            raise ValueError("Operator must enable and verify the desktop bridge configuration")
        self.config = config
        self.root = Path(config["data_dir"]).resolve()
        self.artifact_root = Path(config["artifact_root"]).resolve()
        protect(self.root)
        protect(self.artifact_root)
        if source.is_relative_to(self.artifact_root) or self.root.is_relative_to(self.artifact_root):
            raise ValueError("Bridge configuration/state must be outside build worktrees")
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = portalocker.Lock(str(self.root / "bridge.lock"), timeout=0)
        self.lock.acquire()
        self.active = None
        self.process = None
        self.task = None
        self.records = {}
        for path in self.root.glob("run-*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["status"] == "running":
                record["status"] = "interrupted"
                record["error"] = "Driver state uncertain after restart; inspect before releasing resource"
                self.save(record)
            self.records[record["run_id"]] = record
        owner_path = self.root / "owners.json"
        self.owners = json.loads(owner_path.read_text()) if owner_path.exists() else {}

    def save(self, record):
        path = self.root / ("run-" + record["run_id"] + ".json")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(redact(json.dumps(record)), encoding="utf-8")
        temporary.replace(path)

    def save_owners(self):
        path = self.root / "owners.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.owners), encoding="utf-8")
        temporary.replace(path)

    def public(self, record):
        keys = {"run_id", "stage", "resource_id", "commit", "artifact_sha256", "status", "healthy",
                "evidence", "checks", "acceptance_mapping", "driver", "error", "started_at", "ended_at", "exit_code"}
        return json.loads(redact(json.dumps({key: value for key, value in record.items() if key in keys})))

    def verify_artifacts(self, job):
        cwd = within(Path(job.cwd), self.artifact_root)
        if hashlib.sha256(json.dumps(job.artifacts, sort_keys=True).encode()).hexdigest() != job.artifact_sha256:
            raise ValueError("Artifact manifest digest mismatch")
        for item in job.artifacts:
            if set(item) != {"path", "sha256", "size"}:
                raise ValueError("Invalid artifact manifest entry")
            target = within(cwd / item["path"], cwd)
            if target.stat().st_size != item["size"]:
                raise ValueError("Artifact size changed")
            digest = hashlib.sha256()
            with target.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != item["sha256"]:
                raise ValueError("Deployment artifact changed since build")

    def submit(self, job):
        fingerprint = hashlib.sha256(job.model_dump_json().encode()).hexdigest()
        if job.run_id in self.records:
            record = self.records[job.run_id]
            if record["fingerprint"] != fingerprint:
                raise ValueError("Run ID already used with different input")
            return record
        if self.active:
            raise ValueError("Desktop is busy; no parallel UI/deployment execution")
        resource = self.config["resources"].get(job.resource_id)
        if not resource or resource["recipe"] != job.recipe or resource["scenario"] != job.scenario or resource["checks"] != job.checks:
            raise ValueError("Job does not match operator-approved resource, recipe and scenario")
        owner = self.owners.get(job.resource_id)
        if owner and owner != job.workflow_id:
            raise ValueError("Resource retained by another workflow; manual reconciliation required")
        if any(record["workflow_id"] == job.workflow_id and record["status"] == "interrupted" for record in self.records.values()):
            raise ValueError("Workflow has uncertain desktop execution; automatic replay forbidden")
        command = resource[job.stage + "_command"]
        if not isinstance(command, list) or not command or not all(isinstance(item, str) and item and "\0" not in item for item in command):
            raise ValueError("Operator command must be a nonempty literal argv")
        executable = Path(command[0])
        if not executable.is_absolute() or not executable.is_file() or executable.resolve().is_relative_to(self.artifact_root):
            raise ValueError("Driver executable must be an absolute operator-owned file")
        protect(executable.resolve())
        self.verify_artifacts(job)
        if job.stage == "e2e" and not any(record["workflow_id"] == job.workflow_id and record["stage"] == "deploy" and
            record["commit"] == job.commit and record["artifact_sha256"] == job.artifact_sha256 and record["status"] == "succeeded"
            and record.get("healthy") is True for record in self.records.values()):
            raise ValueError("E2E requires a healthy deployment of these exact artifacts")
        self.owners[job.resource_id] = job.workflow_id
        self.save_owners()
        record = job.model_dump() | {"fingerprint": fingerprint, "status": "running", "started_at": now()}
        self.records[job.run_id] = record
        self.save(record)
        self.active = job.run_id
        self.task = asyncio.create_task(self.execute(job, command, record))
        return record

    async def execute(self, job, command, record):
        directory = within(self.root / job.run_id, self.root)
        directory.mkdir(exist_ok=True)
        request_file = directory / "request.json"
        result_file = directory / "result.json"
        request_file.write_text(job.model_dump_json(), encoding="utf-8")
        env = dict(os.environ)
        env.pop("AIM_DESKTOP_BRIDGE_TOKEN", None)
        env["AIM_BRIDGE_REQUEST_FILE"] = str(request_file)
        env["AIM_BRIDGE_RESULT_FILE"] = str(result_file)
        env["AIM_BRIDGE_EVIDENCE_DIR"] = str(directory)
        kwargs = {"creationflags": 0x08000000} if os.name == "nt" else {"start_new_session": True}
        try:
            self.process = await asyncio.create_subprocess_exec(*command, cwd=directory, env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, **kwargs)
            record["pid"] = self.process.pid
            self.save(record)
            output, _ = await asyncio.wait_for(self.process.communicate(), job.timeout_seconds)
            record["stdout"] = output.decode("utf-8", "replace")[-1048576:]
            record["exit_code"] = self.process.returncode
            if self.process.returncode != 0:
                raise ValueError("Approved driver failed; inspect retained logs")
            if not result_file.is_file() or result_file.stat().st_size > 1048576:
                raise ValueError("Driver must produce bounded JSON evidence, not just exit successfully")
            result = json.loads(result_file.read_text(encoding="utf-8-sig"))
            if job.stage == "deploy":
                if result.get("healthy") is not True or not result.get("evidence"):
                    raise ValueError("Deployment driver did not prove healthy application")
                record.update(healthy=True, evidence=result["evidence"], status="succeeded")
            else:
                checks = result.get("checks")
                if result.get("driver") != "computer-use" or not isinstance(checks, list) or len(checks) != len(job.checks):
                    raise ValueError("E2E requires Computer-use driver and complete check matrix")
                if any(not isinstance(item, dict) for item in checks) or {item.get("id") for item in checks} != set(job.checks):
                    raise ValueError("Driver returned unexpected check IDs")
                if any(type(item.get("passed")) is not bool or not item.get("evidence") for item in checks):
                    raise ValueError("Each check requires a boolean result and actual UI/query evidence")
                mappings = result.get("acceptance_mapping")
                if not isinstance(mappings, list) or len(mappings) != len(job.acceptance) or any(not isinstance(item, dict) for item in mappings):
                    raise ValueError("Driver must map all feature acceptance criteria to executed check IDs")
                if {item.get("criterion") for item in mappings} != set(job.acceptance):
                    raise ValueError("Driver acceptance mapping omitted feature criteria")
                if any(not isinstance(item.get("check_ids"), list) or not item["check_ids"] or any(name not in job.checks for name in item["check_ids"]) for item in mappings):
                    raise ValueError("Driver acceptance mapping contains unknown check IDs")
                record.update(checks=checks, acceptance_mapping=mappings, driver="computer-use", status="succeeded" if all(item["passed"] for item in checks) else "failed")
                if record["status"] == "succeeded":
                    self.owners.pop(job.resource_id, None)
                    self.save_owners()
        except asyncio.CancelledError:
            stopped = self.process is None or await asyncio.shield(stop_owned(self.process))
            record["status"] = "cancelled" if stopped else "interrupted"
        except asyncio.TimeoutError:
            stopped = self.process is None or await stop_owned(self.process)
            record["status"] = "failed" if stopped else "interrupted"
            record["error"] = "Desktop driver timeout; verify deployment state before retry"
        except Exception as error:
            record["status"] = "failed"
            record["error"] = str(error)
        finally:
            record["ended_at"] = now()
            self.save(record)
            self.process = None
            self.active = None

    async def cancel(self, run_id):
        record = self.records[run_id]
        if self.active == run_id and self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            if self.active == run_id and self.process is None:
                record["status"] = "cancelled"
                self.save(record)
                self.active = None
        return record


def create_bridge_app():
    @asynccontextmanager
    async def lifespan(app):
        token = os.environ.get("AIM_DESKTOP_BRIDGE_TOKEN", "")
        if len(token) < 32:
            raise ValueError("AIM_DESKTOP_BRIDGE_TOKEN must contain at least 32 characters")
        app.state.bridge = DesktopBridge(os.environ["AIM_BRIDGE_CONFIG"])
        try:
            yield
        finally:
            bridge = app.state.bridge
            if bridge.active:
                await bridge.cancel(bridge.active)
            bridge.lock.release()

    app = FastAPI(lifespan=lifespan)

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        from fastapi.responses import JSONResponse
        expected = "Bearer " + os.environ.get("AIM_DESKTOP_BRIDGE_TOKEN", "")
        if request.headers.get("origin") or not request.client or request.client.host != "127.0.0.1" or not hmac.compare_digest(request.headers.get("authorization", ""), expected):
            return JSONResponse(status_code=403, content={"detail": "Authenticated non-browser localhost requests only"})
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"protocol": "aim-desktop-v1", "ready": True, "resources": list(app.state.bridge.config["resources"])}

    @app.post("/runs", status_code=202)
    async def submit(job: DesktopJob):
        try:
            return app.state.bridge.public(app.state.bridge.submit(job))
        except (ValueError, KeyError, OSError) as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/runs/{run_id}")
    def get(run_id: str):
        if run_id not in app.state.bridge.records:
            raise HTTPException(404, "Unknown desktop run")
        return app.state.bridge.public(app.state.bridge.records[run_id])

    @app.post("/runs/{run_id}/cancel")
    async def cancel(run_id: str):
        if run_id not in app.state.bridge.records:
            raise HTTPException(404, "Unknown desktop run")
        return app.state.bridge.public(await app.state.bridge.cancel(run_id))

    return app


app = create_bridge_app()
