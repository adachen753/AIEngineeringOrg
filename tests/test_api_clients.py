import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from ai_manager.api import create_app
from ai_manager.models import Settings
from ai_manager.store import Store


@pytest.fixture
def api_client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "api-data", adapter_url="http://idle-agent.invalid"))
    with TestClient(app) as client:
        yield client, app
    app.state.store.db.close()


def unauthorized_body(submission):
    return {**submission.model_dump(), "authorized": False}


def test_actual_api_health_idempotency_and_sqlite_restart(tmp_path, submission):
    settings = Settings(data_dir=tmp_path / "api-data", adapter_url="http://idle-agent.invalid")
    app = create_app(settings)
    body = unauthorized_body(submission)
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        first = client.post("/workflows", json=body)
        assert first.status_code == 201
        record = first.json()
        assert record["status"] == "awaiting_approval"
        assert client.post("/workflows", json=body).json() == record
        conflict = client.post("/workflows", json={**body, "feature": "Different input"})
        assert conflict.status_code == 409
        assert client.get("/workflows").json() == [record]
        assert client.get("/workflows/" + record["id"]).json() == record
        assert len(client.get("/workflows/" + record["id"] + "/events").json()) == 1
        assert record["attempts"] == [] and record["worktrees"] == {}
        assert not app.state.worker.done()
    app.state.store.db.close()
    restarted = create_app(settings)
    with TestClient(restarted) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/workflows/" + record["id"]).json() == record
        assert client.post("/workflows", json=body).json() == record
        assert not restarted.state.worker.done()
    restarted.state.store.db.close()


@pytest.mark.parametrize("origin", ["https://evil.example", "http://localhost.evil.example", "null"])
def test_actual_api_rejects_nonlocal_origin_without_persisting(api_client, submission, origin):
    client, app = api_client
    response = client.post("/workflows", json=unauthorized_body(submission), headers={"Origin": origin})
    assert response.status_code == 403
    assert app.state.store.list() == []
    assert client.get("/health").status_code == 200


def test_actual_api_artifact_download_redaction_and_traversal(api_client, submission):
    client, app = api_client
    record = client.post("/workflows", json=unauthorized_body(submission)).json()
    workflow_id = record["id"]
    app.state.store.artifact(workflow_id, "evidence.txt", "password=private-value")
    base = "/workflows/" + workflow_id + "/artifacts/"
    response = client.get(base + "evidence.txt")
    assert response.status_code == 200
    assert "private-value" not in response.text
    assert "[REDACTED]" in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"
    for name in ("..%5Cstate.sqlite3", "C%3Astate.sqlite3", "%2E%2E%2Fstate.sqlite3", "missing.txt"):
        rejected = client.get(base + name)
        assert rejected.status_code in {400, 404}
        assert "SQLite format" not in rejected.text
    assert len(client.get(base.rstrip("/")).json()) == 1
    assert not app.state.worker.done()


@pytest.mark.parametrize("action,payload", [("approve", {"approved": "true"}), ("approve", {}),
                                          ("input", {"text": None}), ("input", {"text": 1})])
def test_actual_api_control_payload_types_fail_without_authorizing(api_client, submission, action, payload):
    client, app = api_client
    record = client.post("/workflows", json=unauthorized_body(submission)).json()
    response = client.post("/workflows/" + record["id"] + "/" + action, json=payload)
    assert response.status_code == 422
    assert app.state.store.get(record["id"]) == record
    assert not app.state.worker.done()


@pytest.mark.parametrize("arguments,path,payload", [
    (["status"], "/workflows", None), (["status", "task-id"], "/workflows/task-id", None),
    (["input", "task-id", "Clarify"], "/workflows/task-id/input", {"text": "Clarify"}),
    (["approve", "task-id", "--approved"], "/workflows/task-id/approve", {"approved": True}),
    (["cancel", "task-id"], "/workflows/task-id/cancel", {}),
])
def test_cli_unit_mock_uses_shared_api_request(monkeypatch, capsys, arguments, path, payload):
    from ai_manager import cli
    mock_request = MagicMock(return_value={"id": "task-id", "status": "awaiting_approval"})
    monkeypatch.setattr(cli, "api_request", mock_request)
    assert cli.main(["--api-url", "http://unit-test.invalid", *arguments]) == 0
    mock_request.assert_called_once_with("http://unit-test.invalid", path, payload)
    assert json.loads(capsys.readouterr().out)["id"] == "task-id"


def test_ui_unit_mock_uses_same_api_function_without_local_engine(monkeypatch):
    from ai_manager import cli, ui
    assert ui.api_request is cli.api_request
    mock_request = MagicMock(return_value=[])
    mock_streamlit = MagicMock()
    mock_streamlit.session_state.submission_key = "ui-key"
    mock_streamlit.form_submit_button.return_value = False
    mock_streamlit.button.return_value = False
    mock_streamlit.checkbox.return_value = False
    mock_streamlit.text_input.side_effect = lambda label, *args, **kwargs: "" if label.startswith("Workflow ID") else (args[0] if args else "")
    mock_streamlit.sidebar.text_input.return_value = "http://unit-test.invalid"
    monkeypatch.setattr(ui, "st", mock_streamlit)
    monkeypatch.setattr(ui, "api_request", mock_request)
    ui.main()
    mock_request.assert_called_once_with("http://unit-test.invalid", "/workflows", None)
