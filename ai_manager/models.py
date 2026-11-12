from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Settings(BaseModel):
    data_dir: Path = Path(".aim-data")
    adapter_url: str = "http://127.0.0.1:8766"

class AgentSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["codex", "copilot"] = "codex"
    model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
    effort: Literal["minimal", "low", "medium", "high", "xhigh", "max", "ultra", "persistent"] | None = None

    @model_validator(mode="after")
    def supported_options(self):
        if self.provider == "copilot" and self.effort is not None:
            raise ValueError("Copilot ACP effort selection is not verified; omit effort")
        return self

class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_models: dict[Literal["manager", "architect", "dev", "test", "reviewer"], AgentSelection] = Field(default_factory=dict)
    repo: str
    base_commit: str = Field(pattern=r"^[0-9a-fA-F]{40,64}$")
    feature: str = Field(min_length=1, max_length=12000)
    allowed_paths: list[str] = Field(min_length=1)
    test_paths: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(min_length=1)
    test_command: list[str] = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    idempotency_key: str = Field(min_length=1, max_length=200)
    authorized: bool = False
    timeout_seconds: int = Field(default=300, ge=10, le=3600)
    workflow_kind: Literal["legacy", "delivery"] = "legacy"
    project_profile: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,80}$")
    max_fix_rounds: int = Field(default=5, ge=0, le=20, strict=True)
    total_timeout_seconds: int = Field(default=7200, ge=60, le=86400, strict=True)
    deploy_authorized: bool = False

    @model_validator(mode="after")
    def workflow_requirements(self):
        if self.workflow_kind == "legacy" and not self.test_paths:
            raise ValueError("Legacy workflow requires test_paths")
        if self.workflow_kind == "delivery" and (not self.project_profile or self.test_paths):
            raise ValueError("Delivery requires project_profile and no unit-test paths")
        return self

    @field_validator("allowed_paths", "test_paths")
    @classmethod
    def safe_scopes(cls, scopes, info):
        for scope in scopes:
            if scope == "." and info.field_name == "allowed_paths":
                continue
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

class FeatureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role_models: dict[Literal["manager", "architect", "dev", "test", "reviewer"], AgentSelection] = Field(default_factory=dict)
    project: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    feature: str = Field(min_length=1, max_length=12000)
    idempotency_key: str = Field(min_length=1, max_length=200)
    authorized: bool = False
    deploy_authorized: bool = False
    max_fix_rounds: int = Field(default=5, ge=0, le=20, strict=True)
    total_timeout_seconds: int = Field(default=7200, ge=60, le=86400, strict=True)


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

STAGES = ["plan", "architect", "dev", "build", "test", "deploy", "e2e", "assess", "verify", "review", "integrate", "integration_verify", "report", "done"]
TERMINAL = {"succeeded", "failed", "blocked", "cancelled", "interrupted"}
TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"queued", "awaiting_input", "succeeded", "failed", "blocked", "cancelled", "interrupted"},
    "awaiting_input": {"queued", "cancelled"},
    "awaiting_approval": {"queued", "cancelled", "blocked"},
    "failed": {"queued", "cancelled"}, "blocked": {"queued", "cancelled"},
    "cancelled": set(), "interrupted": set(), "succeeded": set(),
}
