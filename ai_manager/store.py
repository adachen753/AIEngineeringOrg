import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import Submission, TRANSITIONS
from .role_config import load_role_config
from .security import protect, redact, within


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, data_dir: Path):
        protect(data_dir)
        self.root = data_dir.resolve()
        protect(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "state.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS workflows(id TEXT PRIMARY KEY, idem TEXT UNIQUE, fingerprint TEXT, body TEXT);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, workflow TEXT, body TEXT);
            CREATE TABLE IF NOT EXISTS artifacts(workflow TEXT, name TEXT, body TEXT, PRIMARY KEY(workflow,name));
        """)
        self.db.commit()

    def get(self, workflow_id):
        with self.lock:
            row = self.db.execute("SELECT body FROM workflows WHERE id=?", (workflow_id,)).fetchone()
            if not row:
                raise KeyError(workflow_id)
            return json.loads(row["body"])

    def list(self):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT body FROM workflows ORDER BY rowid DESC")]

    def _event(self, workflow_id, kind, data):
        body = {"id": str(uuid4()), "time": now(), "type": kind, "data": data}
        self.db.execute("INSERT INTO events(workflow,body) VALUES (?,?)", (workflow_id, redact(json.dumps(body))))

    def event(self, workflow_id, kind, data):
        with self.lock, self.db:
            self._event(workflow_id, kind, data)

    def events(self, workflow_id):
        self.get(workflow_id)
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT body FROM events WHERE workflow=? ORDER BY seq", (workflow_id,))]

    def submit(self, submission: Submission):
        protect(submission.repo)
        repo = Path(submission.repo).resolve()
        protect(repo)
        if not (repo / ".git").exists():
            raise ValueError("Target must be a dedicated Git repository")
        body = submission.model_dump()
        body["repo"] = str(repo)
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        with self.lock, self.db:
            existing = self.db.execute("SELECT id,fingerprint FROM workflows WHERE idem=?", (submission.idempotency_key,)).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise ValueError("Idempotency key already used for different input")
                return self.get(existing["id"])
            workflow_id = str(uuid4())
            role_config = load_role_config()
            record = {"id": workflow_id, "status": "queued" if submission.authorized else "awaiting_approval", "stage": "plan", "submission": body,
                      "threads": {}, "tasks": {}, "attempts": [], "messages": [], "approvals": [{"approved": submission.authorized, "time": now()}],
                      "commits": {"base": submission.base_commit}, "worktrees": {}, "results": {}, "repair_count": 0, "retry_count": 0,
                      "cancel_requested": False, "reason": None, "created_at": now(), "updated_at": now(), "role_config": role_config}
            record = json.loads(redact(json.dumps(record)))
            self.db.execute("INSERT INTO workflows VALUES (?,?,?,?)", (workflow_id, submission.idempotency_key, fingerprint, json.dumps(record)))
            self._event(workflow_id, "submitted", {"status": record["status"]})
            return record

    def save(self, record, kind="checkpoint"):
        with self.lock, self.db:
            previous = self.get(record["id"])
            if previous["status"] != record["status"] and record["status"] not in TRANSITIONS[previous["status"]]:
                raise ValueError(f"Illegal transition {previous['status']} -> {record['status']}")
            record["updated_at"] = now()
            self.db.execute("UPDATE workflows SET body=? WHERE id=?", (redact(json.dumps(record)), record["id"]))
            self._event(record["id"], kind, {"status": record["status"], "stage": record["stage"], "reason": record["reason"]})

    def control(self, workflow_id, action, payload=None):
        payload = payload or {}
        with self.lock:
            record = self.get(workflow_id)
            if action == "approve" and record["status"] == "awaiting_approval":
                approved = payload.get("approved", False) is True
                record["approvals"].append({"approved": approved, "time": now()})
                record["submission"]["authorized"] = approved
                record["status"] = "queued" if approved else "blocked"
                record["reason"] = None if approved else "Authorization denied"
            elif action == "input" and record["status"] == "awaiting_input":
                text = payload.get("text", "").strip()
                if not text:
                    raise ValueError("Nonempty input required")
                record["submission"]["feature"] += "\nUser clarification: " + text
                record["status"] = "queued"
                record["reason"] = None
            elif action == "retry" and record["status"] in {"failed", "blocked"}:
                if not record["submission"]["authorized"]:
                    raise ValueError("Authorization required")
                if record["retry_count"] >= 1:
                    raise ValueError("Explicit retry limit reached")
                if record["reason"] and record["reason"].startswith("UNCERTAIN"):
                    raise ValueError("Uncertain execution requires manual reconciliation")
                record["retry_count"] += 1
                record["status"] = "queued"
                record["reason"] = None
            elif action == "cancel" and record["status"] not in {"succeeded", "cancelled", "interrupted"}:
                record["cancel_requested"] = True
                record["status"] = "cancelled"
            else:
                raise ValueError("Action not allowed in current state")
            self.save(record, action)
            return record

    def artifact(self, workflow_id, name, content):
        if Path(name).name != name or name.startswith("."):
            raise ValueError("Invalid artifact name")
        directory = within(self.root / "artifacts" / workflow_id, self.root)
        directory.mkdir(parents=True, exist_ok=True)
        target = within(directory / name, directory)
        text = redact(content if isinstance(content, str) else json.dumps(content, indent=2))
        target.write_text(text, encoding="utf-8")
        metadata = {"name": name, "sha256": hashlib.sha256(text.encode()).hexdigest(), "bytes": len(text.encode()), "time": now()}
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO artifacts VALUES (?,?,?)", (workflow_id, name, json.dumps(metadata)))
        return metadata

    def artifacts(self, workflow_id):
        self.get(workflow_id)
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT body FROM artifacts WHERE workflow=?", (workflow_id,))]

    def artifact_path(self, workflow_id, name):
        if not any(item["name"] == name for item in self.artifacts(workflow_id)):
            raise KeyError(name)
        return within(self.root / "artifacts" / workflow_id / name, self.root / "artifacts" / workflow_id)
