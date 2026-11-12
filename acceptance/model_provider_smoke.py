import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description="Real HTTP/SDK integration smoke; no source changes or product UT")
    parser.add_argument("--node", required=True)
    parser.add_argument("--live", action="store_true", help="Authorize two fixed real model calls; usage may be billed")
    parser.add_argument("--codex-model", required=True)
    parser.add_argument("--copilot-model", default="auto")
    parser.add_argument("--providers", nargs="+", choices=["codex", "copilot"], default=["codex", "copilot"])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    runtime = root / "adapter" / ".runtime"
    runtime.mkdir(exist_ok=True)
    data = Path(tempfile.mkdtemp(prefix="model-http-", dir=runtime))
    adapter_port, api_port = free_port(), free_port()
    while api_port == adapter_port:
        api_port = free_port()
    env = os.environ | {"PORT": str(adapter_port), "AIM_ADAPTER_DATA": str(data / "adapter"), "AIM_DATA_DIR": str(data / "backend"), "AIM_ADAPTER_URL": f"http://127.0.0.1:{adapter_port}"}
    children = []
    logs = []
    evidence = {"kind": "REAL_HTTP_AND_MODEL_CONNECTIVITY", "product_tools_executed": False, "workflow_execution_ready": False, "probes": []}
    try:
        for name, command in [("adapter", [args.node, "adapter/src/server.ts"]), ("backend", [sys.executable, "-m", "uvicorn", "ai_manager.api:app", "--host", "127.0.0.1", "--port", str(api_port)])]:
            log = (data / (name + ".log")).open("w", encoding="utf-8")
            logs.append(log)
            children.append(subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
        with httpx.Client(base_url=f"http://127.0.0.1:{api_port}", timeout=25) as client:
            for attempt in range(60):
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if any(child.poll() is not None for child in children):
                    raise RuntimeError("Service exited; inspect " + str(data))
                time.sleep(0.5)
            else:
                raise RuntimeError("Health timeout")
            response = client.get("/models/providers")
            response.raise_for_status()
            evidence["providers"] = response.json()
            rejected = client.post("/models/probes", json={"provider": "codex", "model": args.codex_model, "approved": False})
            if rejected.status_code != 400:
                raise RuntimeError("Probe approval guard failed")
            for provider, model in [("codex", args.codex_model), ("copilot", args.copilot_model)]:
                if provider not in args.providers:
                    continue
                response = client.post("/models/catalog", json={"provider": provider})
                if response.status_code >= 400:
                    raise RuntimeError(provider + " catalog: " + response.text)
                response.raise_for_status()
                evidence[provider + "_catalog"] = response.json()
                if not args.live:
                    continue
                response = client.post("/models/probes", json={"provider": provider, "model": model, "approved": True})
                response.raise_for_status()
                probe_id = response.json()["id"]
                for attempt in range(110):
                    result = client.get("/models/probes/" + probe_id)
                    result.raise_for_status()
                    record = result.json()
                    if record["status"] != "running":
                        break
                    time.sleep(1)
                evidence["probes"].append(record)
                if record["status"] != "succeeded":
                    raise RuntimeError(provider + " connectivity failed")
            from streamlit.testing.v1 import AppTest
            os.environ["AIM_API_URL"] = str(client.base_url).rstrip("/")
            ui = AppTest.from_file(str(root / "ai_manager" / "ui.py")).run(timeout=20)
            if ui.exception or not any("默认 后端" == widget.label for widget in ui.selectbox):
                raise RuntimeError("UI model panel failed")
            evidence["ui_model_panel"] = "rendered-with-real-backend"
            evidence["status"] = "passed"
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=10)
        for log in logs:
            log.close()
        destination = data / "evidence.json"
        destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        print(destination)


if __name__ == "__main__":
    main()
