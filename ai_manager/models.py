from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class Settings(BaseModel):
    data_dir: Path = Path(".aim-data")
    adapter_url: str = "http://127.0.0.1:8766"

class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo: str
    base_commit: str = Field(pattern=r"^[0-9a-fA-F]{40,64}$")
    feature: str = Field(min_length=1, max_length=12000)
    allowed_paths: list[str] = Field(min_length=1)
    test_paths: list[str] = Field(min_length=1)
    acceptance: list[str] = Field(min_length=1)
    test_command: list[str] = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    idempotency_key: str = Field(min_length=1, max_length=200)
    authorized: bool = False
    timeout_seconds: int = Field(default=300, ge=10, le=3600)

    @field_validator("allowed_paths", "test_paths")
    @classmethod
    def safe_scopes(cls, scopes):
        for scope in scopes:
            path = Path(scope)
            if not scope or path.is_absolute() or scope.startswith("/") or ".." in path.parts or ":" in scope or "\\" in scope or scope.startswith("."):
                raise ValueError("Scopes must be explicit relative file/directory paths")
        return scopes

    @field_validator("test_command")
    @classmethod
    def safe_command(cls, command):
        if command != ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]:
            raise ValueError("MVP permits only the fixed pytest runner")
        return command

class AcceptanceMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criterion: str
    node_ids: list[str] = Field(min_length=1)


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ready", "needs_input", "blocked"]
    summary: str
    acceptance: list[str]
    questions: list[str]
    evidence: list[str]
    classification: Literal["none", "product_bug", "test_issue", "data_issue", "environment", "flaky", "unknown"]
    mappings: list[AcceptanceMapping] = []

STAGES = ["plan", "dev", "test", "verify", "review", "integrate", "integration_verify", "report", "done"]
TERMINAL = {"succeeded", "failed", "blocked", "cancelled", "interrupted"}
TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"queued", "awaiting_input", "succeeded", "failed", "blocked", "cancelled", "interrupted"},
    "awaiting_input": {"queued", "cancelled"},
    "awaiting_approval": {"queued", "cancelled", "blocked"},
    "failed": {"queued", "cancelled"}, "blocked": {"queued", "cancelled"},
    "cancelled": set(), "interrupted": set(), "succeeded": set(),
}
