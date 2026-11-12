import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_manager.models import Submission, TRANSITIONS
from ai_manager.security import allowed_file, protect, redact, within


def test_same_idempotency_returns_existing_record_without_duplicate_event(store, submission):
    first = store.submit(submission)
    second = store.submit(submission)
    assert second == first
    assert len(store.list()) == 1
    assert len(store.events(first["id"])) == 1


@pytest.mark.parametrize("change", [{"feature": "Different"}, {"authorized": False},
                                     {"acceptance": ["Different"]}, {"base_commit": "HEAD"}])
def test_different_input_cannot_reuse_idempotency_key(store, submission, change):
    first = store.submit(submission)
    with pytest.raises(ValueError, match="different input"):
        store.submit(submission.model_copy(update=change))
    assert store.get(first["id"]) == first


@pytest.mark.parametrize("approved,status", [(True, "queued"), (False, "blocked"), (1, "blocked"), ("true", "blocked")])
def test_approval_requires_literal_true(store, submission, approved, status):
    record = store.submit(submission.model_copy(update={"authorized": False}))
    assert record["status"] == "awaiting_approval"
    result = store.control(record["id"], "approve", {"approved": approved})
    assert result["status"] == status
    assert result["submission"]["authorized"] is (approved is True)
    assert len(result["approvals"]) == 2
    if status == "blocked":
        with pytest.raises(ValueError, match="Authorization"):
            store.control(record["id"], "retry")


def test_clarification_requires_nonempty_input_and_resumes(store, submission):
    record = store.submit(submission)
    record["status"] = "running"
    store.save(record)
    record["status"] = "awaiting_input"
    store.save(record)
    for text in ("", "  "):
        with pytest.raises(ValueError, match="Nonempty"):
            store.control(record["id"], "input", {"text": text})
    resumed = store.control(record["id"], "input", {"text": "  Use two  "})
    assert resumed["status"] == "queued"
    assert resumed["submission"]["feature"].endswith("User clarification: Use two")


@pytest.mark.parametrize("terminal", ["failed", "blocked"])
def test_explicit_retry_is_bounded_once(store, submission, terminal):
    record = store.submit(submission)
    record["status"] = "running"
    store.save(record)
    record["status"] = terminal
    store.save(record)
    resumed = store.control(record["id"], "retry")
    assert resumed["retry_count"] == 1
    resumed["status"] = "running"
    store.save(resumed)
    resumed["status"] = terminal
    store.save(resumed)
    with pytest.raises(ValueError, match="retry limit"):
        store.control(record["id"], "retry")


def test_uncertain_failure_cannot_retry(store, submission):
    record = store.submit(submission)
    record["status"] = "running"
    store.save(record)
    record.update(status="blocked", reason="UNCERTAIN execution")
    store.save(record)
    with pytest.raises(ValueError, match="manual reconciliation"):
        store.control(record["id"], "retry")


@pytest.mark.parametrize("source,target", [(source, target) for source in TRANSITIONS for target in TRANSITIONS if source != target])
def test_store_enforces_transition_matrix(store, submission, source, target):
    record = store.submit(submission)
    record["status"] = source
    with store.db:
        store.db.execute("UPDATE workflows SET body=? WHERE id=?", (json.dumps(record), record["id"]))
    record["status"] = target
    if target in TRANSITIONS[source]:
        store.save(record)
        assert store.get(record["id"])["status"] == target
    else:
        with pytest.raises(ValueError, match="Illegal transition"):
            store.save(record)
        assert store.get(record["id"])["status"] == source


@pytest.mark.parametrize("path", ["Q:/GraphConnectors/cwzClaude", "q:/GRAPHCONNECTORS/CWZCLAUDE/note.md",
                                  "Q:\\GraphConnectors\\sources\\dev\\cwzClaude-SQL\\draft.sql"])
def test_protected_paths_are_case_insensitive_read_only_checks(path):
    with pytest.raises(ValueError, match="Protected"):
        protect(path)


def test_protection_matches_directory_boundary_only():
    protect("Q:/GraphConnectors/cwzClaude-other/note.md")


@pytest.mark.parametrize("name", ["../escape", "nested/escape", "nested\\escape", ".secret", "C:/escape", "/escape"])
def test_artifact_names_cannot_traverse(store, submission, name):
    record = store.submit(submission)
    with pytest.raises(ValueError):
        store.artifact(record["id"], name, "content")
    assert store.artifacts(record["id"]) == []


def test_artifacts_and_events_redact_secrets(store, submission):
    record = store.submit(submission)
    text = "sk-abcdefghijk Authorization: Bearer bearer-secret password=private api_key=private access_token=private"
    metadata = store.artifact(record["id"], "evidence.txt", text)
    content = store.artifact_path(record["id"], "evidence.txt").read_text(encoding="utf-8")
    assert "private" not in content and "bearer-secret" not in content and "sk-abcdefghijk" not in content
    assert metadata["sha256"] == hashlib.sha256(content.encode()).hexdigest()
    assert metadata["bytes"] == len(content.encode())
    store.event(record["id"], "secret", {"text": text})
    assert "private" not in json.dumps(store.events(record["id"]))
    with pytest.raises(KeyError):
        store.artifact_path(record["id"], "missing.txt")


def test_within_rejects_escape(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        within(tmp_path / "owned" / ".." / "outside", tmp_path / "owned")


@pytest.mark.parametrize("name,expected", [("app/feature.py", True), ("application/file.py", False),
                                          ("app/../secret", False), ("app/.git/config", False), ("/app/file", False)])
def test_allowed_scopes_have_path_boundaries(name, expected):
    assert allowed_file(name, ["app"]) is expected


@pytest.mark.parametrize("scope", ["../app", "/app", "C:/app", "app\\file", ".git"])
def test_submission_rejects_unsafe_scopes(submission, scope):
    with pytest.raises(ValidationError):
        Submission.model_validate({**submission.model_dump(), "allowed_paths": [scope]})


def test_repository_scope_is_allowed_only_for_dev(submission):
    data = {**submission.model_dump(), "allowed_paths": ["."]}
    assert Submission.model_validate(data).allowed_paths == ["."]
    with pytest.raises(ValidationError):
        Submission.model_validate({**data, "test_paths": ["."]})


@pytest.mark.parametrize("name,expected", [
    ("README.md", True), ("new/component.cs", True), (".github/config.yml", True),
    ("../escape", False), ("src/../escape", False), ("/escape", False),
    ("C:/escape", False), ("Q:escape", False), (".git/config", False),
    ("nested/.GIT/config", False), ("", False),
])
def test_repository_scope_preserves_path_guards(name, expected):
    assert allowed_file(name, ["."]) is expected



def test_stored_workflow_redacts_secrets_but_idempotency_compares_original_input(store, submission):
    secret_submission = submission.model_copy(update={"feature": "Use password=first-private sk-abcdefghijk"})
    record = store.submit(secret_submission)
    assert "first-private" not in json.dumps(record)
    assert store.submit(secret_submission) == record
    with pytest.raises(ValueError, match="different input"):
        store.submit(secret_submission.model_copy(update={"feature": "Use password=second-private sk-abcdefghijk"}))
    record["status"] = "running"
    record["reason"] = "Authorization: Bearer bearer-private"
    store.save(record)
    saved = store.get(record["id"])
    assert "bearer-private" not in saved["reason"]
    raw = store.db.execute("SELECT body FROM workflows WHERE id=?", (record["id"],)).fetchone()[0]
    assert "first-private" not in raw and "bearer-private" not in raw and "sk-abcdefghijk" not in raw


@pytest.mark.parametrize("action", ["approve", "input", "retry"])
def test_controls_reject_wrong_state_without_mutating_record(store, submission, action):
    record = store.submit(submission)
    with pytest.raises(ValueError, match="Action not allowed"):
        store.control(record["id"], action, {"approved": True, "text": "clarification"})
    assert store.get(record["id"]) == record
