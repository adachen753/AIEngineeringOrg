import json
import os
import subprocess
import time
from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".aim-data" / "acceptance"
REPO = DATA / "directory-scoped-repo"
API = os.environ.get("AIM_API_URL", "http://127.0.0.1:8765")


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    if not REPO.exists():
        REPO.mkdir()
        (REPO / "tests").mkdir()
        (REPO / "product").mkdir()
        (REPO / "product" / "math_tools.py").write_bytes((ROOT / "acceptance" / "fixture" / "math_tools.py").read_bytes())
        (REPO / "tests" / "test_math_tools.py").write_text("from product.math_tools import add\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
        for command in (["git", "init"], ["git", "add", "."], ["git", "-c", "user.name=Acceptance Fixture", "-c", "user.email=fixture@localhost", "-c", "core.hooksPath=NUL", "commit", "-m", "Initial harmless fixture"]):
            subprocess.run(command, cwd=REPO, check=True, capture_output=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    os.environ["AIM_API_URL"] = API
    app = AppTest.from_file(str(ROOT / "ai_manager" / "ui.py"), default_timeout=30).run()
    values = {"仓库绝对路径": str(REPO), "Base commit": base}
    for widget in app.text_input:
        if widget.label in values:
            widget.set_value(values[widget.label])
    areas = {"Feature / Manager 需求": "Add clamp(value, lower, upper). Return lower or upper outside bounds, preserve in-range values, raise ValueError when lower > upper. Add normal and boundary pytest tests. No ambiguities.",
             "允许修改路径（每行一个）": "product\ntests", "授权测试路径（每行一个）": "tests",
             "验收条件（每行一个）": "In-range values are preserved\nValues outside bounds clamp to nearest bound\nInvalid lower > upper raises ValueError"}
    for widget in app.text_area:
        if widget.label in areas:
            widget.set_value(areas[widget.label])
    for widget in app.checkbox:
        if widget.label.startswith("授权在隔离"):
            widget.check()
    for widget in app.button:
        if widget.label == "提交":
            widget.click()
    app.run()
    if app.exception:
        raise RuntimeError(str(app.exception))
    workflow_id = app.session_state["workflow_id"]
    record = None
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        record = httpx.get(API + "/workflows/" + workflow_id).raise_for_status().json()
        if record["status"] not in {"queued", "running"}:
            break
        time.sleep(1)
    evidence = {"ui_submission": "Streamlit AppTest actual form -> real HTTP backend (not manual browser)", "workflow": record,
                "events": httpx.get(API + f"/workflows/{workflow_id}/events").json(),
                "artifacts": httpx.get(API + f"/workflows/{workflow_id}/artifacts").json()}
    (DATA / "ui-submission-evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    app.run()
    print(json.dumps({"workflow_id": workflow_id, "status": record["status"], "reason": record["reason"], "threads": record["threads"], "evidence": str(DATA / "ui-submission-evidence.json")}, indent=2))


if __name__ == "__main__":
    main()
