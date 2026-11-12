import asyncio
import os
import httpx
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from ai_manager.engine import Engine
from ai_manager.models import FeatureRequest, Settings, Submission
from ai_manager.models import AgentSelection
from ai_manager.store import Store


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings(
        data_dir=Path(os.environ.get("AIM_DATA_DIR", ".aim-data")),
        adapter_url=os.environ.get("AIM_ADAPTER_URL", "http://127.0.0.1:8766"),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = Store(settings.data_dir)
        app.state.engine = Engine(app.state.store, settings)
        worker = asyncio.create_task(app.state.engine.run_forever())
        app.state.worker = worker
        try:
            yield
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker

    app = FastAPI(title="AI Engineering Manager", lifespan=lifespan)

    @app.middleware("http")
    async def local_mutations(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin is not None:
                try:
                    parsed = urlsplit(origin)
                    local = (
                        parsed.scheme in {"http", "https"}
                        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                        and parsed.username is None and parsed.password is None
                        and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment
                    )
                except ValueError:
                    local = False
                if not local:
                    return JSONResponse(status_code=403, content={"detail": "Non-local Origin rejected"})
        return await call_next(request)

    def invoke(method, *args):
        try:
            return method(*args)
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(404, "Workflow or artifact not found") from exc
        except (ValueError, PermissionError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/health")
    def health():
        if app.state.worker.done():
            raise HTTPException(503, "Workflow worker stopped; inspect backend logs")
        return {"status": "ok"}

    @app.get("/workflows")
    def workflows():
        return invoke(app.state.store.list)

    async def adapter_request(path, payload=None):
        try:
            async with httpx.AsyncClient(base_url=settings.adapter_url, timeout=22) as client:
                response = await client.get(path) if payload is None else await client.post(path, json=payload)
                if response.status_code >= 400:
                    raise HTTPException(response.status_code, response.json())
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, "Model adapter unavailable; inspect adapter logs") from exc

    @app.get("/models/providers")
    async def model_providers():
        return await adapter_request("/providers")

    @app.post("/models/catalog")
    async def model_catalog(selection: AgentSelection):
        return await adapter_request("/model-catalog", {"provider": selection.provider})

    @app.post("/models/probes", status_code=202)
    async def model_probe(payload: dict = Body(...)):
        if set(payload) - {"provider", "model", "effort", "approved"} or payload.get("approved") is not True:
            raise HTTPException(400, "Explicit connection-probe approval required")
        try:
            selection = AgentSelection.model_validate({key: value for key, value in payload.items() if key != "approved"})
        except ValueError as exc:
            raise HTTPException(400, "Invalid provider/model/effort") from exc
        return await adapter_request("/model-probes", selection.model_dump(exclude_none=True) | {"approved": True})

    @app.get("/models/probes/{probe_id}")
    async def model_probe_result(probe_id: str):
        if len(probe_id) != 36 or any(character not in "0123456789abcdef-" for character in probe_id):
            raise HTTPException(400, "Invalid probe ID")
        return await adapter_request("/model-probes/" + probe_id)

    @app.post("/workflows", status_code=201)
    def submit(submission: Submission):
        return invoke(app.state.store.submit, submission)

    @app.post("/features", status_code=201)
    def submit_feature(request: FeatureRequest):
        return invoke(app.state.store.submit_feature, request)

    @app.get("/workflows/{workflow_id}")
    def detail(workflow_id: str):
        return invoke(app.state.store.get, workflow_id)

    @app.get("/workflows/{workflow_id}/events")
    def events(workflow_id: str):
        invoke(app.state.store.get, workflow_id)
        return invoke(app.state.store.events, workflow_id)

    @app.get("/workflows/{workflow_id}/artifacts")
    def artifacts(workflow_id: str):
        invoke(app.state.store.get, workflow_id)
        return invoke(app.state.store.artifacts, workflow_id)

    @app.get("/workflows/{workflow_id}/artifacts/{name}")
    def artifact(workflow_id: str, name: str):
        invoke(app.state.store.get, workflow_id)
        if name in {".", ".."} or any(character in name for character in "/\\:"):
            raise HTTPException(400, "Invalid artifact name")
        path = invoke(app.state.store.artifact_path, workflow_id, name).resolve()
        if not path.is_relative_to(settings.data_dir.resolve()) or not path.is_file():
            raise HTTPException(404, "Artifact not found")
        media_type = "application/json" if path.suffix.lower() == ".json" else "text/plain"
        return FileResponse(path, filename=name, media_type=media_type,
                            headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})

    @app.post("/workflows/{workflow_id}/{action}")
    async def control(workflow_id: str, action: str, payload: dict = Body(default={})):
        if action not in {"cancel", "retry", "input", "approve"}:
            raise HTTPException(404, "Unknown action")
        if action == "approve" and not isinstance(payload.get("approved"), bool):
            raise HTTPException(422, "approved must be an explicit boolean")
        if action == "input" and not isinstance(payload.get("text"), str):
            raise HTTPException(422, "text must be a string")
        if action == "cancel":
            invoke(app.state.store.get, workflow_id)
            try:
                await app.state.engine.cancel(workflow_id)
            except (ValueError, PermissionError) as exc:
                raise HTTPException(409, str(exc)) from exc
            return invoke(app.state.store.get, workflow_id)
        return invoke(app.state.store.control, workflow_id, action, payload)

    return app


app = create_app()
