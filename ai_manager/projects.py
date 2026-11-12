import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .git import git
from .models import FeatureRequest, Submission
from .security import allowed_file, protect


class ProjectProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = False
    repo: str
    allowed_paths: list[str] = Field(min_length=1)
    acceptance: list[str] = Field(min_length=1)
    build_executable: str
    build_arguments: list[str] = Field(min_length=1)
    build_output_paths: list[str] = Field(min_length=1)
    build_timeout_seconds: int = Field(default=1800, ge=10, le=14400)
    bridge_url: str
    resource_id: str = Field(min_length=1, max_length=200)
    deployment_recipe: str = Field(min_length=1, max_length=200)
    scenario: str = Field(min_length=1, max_length=200)
    checks: list[str] = Field(min_length=1, max_length=100)

    @field_validator("allowed_paths", "build_output_paths")
    @classmethod
    def paths(cls, values):
        Submission.safe_scopes(values)
        for value in values:
            if any(part.casefold().startswith("cwz") for part in Path(value).parts):
                raise ValueError("Personal cwz paths cannot be project execution scopes")
        return values

    @field_validator("bridge_url")
    @classmethod
    def local_bridge(cls, value):
        url = urlsplit(value)
        if url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port or url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment:
            raise ValueError("Desktop bridge must be an explicit 127.0.0.1 HTTP port")
        return value.rstrip("/")


def load_project(name):
    configured = os.environ.get("AIM_PROJECT_CONFIG")
    if not configured:
        raise ValueError("Configure AIM_PROJECT_CONFIG with an operator-approved project profile first")
    source = Path(configured).resolve()
    protect(source)
    if source.stat().st_size > 65536:
        raise ValueError("Project config exceeds 64 KiB")
    body = json.loads(source.read_text(encoding="utf-8-sig"))
    if set(body) != {"version", "projects"} or body["version"] != 1:
        raise ValueError("Project config requires version=1 and projects")
    if not isinstance(body["projects"], dict) or name not in body["projects"]:
        raise ValueError("Unknown configured project: " + name)
    profile = ProjectProfile.model_validate(body["projects"][name])
    if not profile.enabled:
        raise ValueError("Project profile is disabled pending operator verification")
    repo = Path(profile.repo).resolve()
    protect(repo)
    if source.is_relative_to(repo):
        raise ValueError("Execution profile must live outside the target repository")
    executable = Path(profile.build_executable)
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError("Build executable must be an existing absolute operator-selected executable")
    protect(executable.resolve())
    if executable.resolve().is_relative_to(repo):
        raise ValueError("Build executable must not be modifiable by the target repository")
    if any("{" in value or "}" in value or "\0" in value for value in profile.build_arguments):
        raise ValueError("Build arguments must be literal argv, not templates or shell commands")
    profile.repo = str(repo)
    snapshot = profile.model_dump()
    snapshot["sha256"] = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    return snapshot


def validate_project_submission(submission, profile):
    if str(Path(submission.repo).resolve()) != profile["repo"]:
        raise ValueError("Submission repo does not match approved project")
    if submission.acceptance != profile["acceptance"]:
        raise ValueError("Delivery acceptance must match the approved project profile")
    if any(not allowed_file(path, profile["allowed_paths"]) for path in submission.allowed_paths):
        raise ValueError("Submission exceeds approved project paths")


def feature_submission(request: FeatureRequest):
    profile = load_project(request.project)
    return Submission(
        role_models=request.role_models,
        repo=profile["repo"], base_commit=git(Path(profile["repo"]), "rev-parse", "HEAD"),
        feature=request.feature, allowed_paths=profile["allowed_paths"], acceptance=profile["acceptance"],
        workflow_kind="delivery", project_profile=request.project,
        idempotency_key=request.idempotency_key, authorized=request.authorized,
        deploy_authorized=request.deploy_authorized, max_fix_rounds=request.max_fix_rounds,
        total_timeout_seconds=request.total_timeout_seconds,
    )
