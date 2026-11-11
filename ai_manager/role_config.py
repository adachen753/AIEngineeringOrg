import hashlib
import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class RoleFiles(BaseModel):
    model_config = ConfigDict(extra="forbid")
    soul: str
    goal: str


class RoleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(default=1, ge=1, le=1)
    roles: dict[str, RoleFiles]


def load_role_config(path=None):
    manifest_path = Path(path or os.environ.get("AIM_ROLE_CONFIG") or Path(__file__).with_name("roles") / "config.json").resolve()
    if manifest_path.stat().st_size > 65536:
        raise ValueError("Role manifest exceeds 64 KiB")
    manifest = RoleManifest.model_validate_json(manifest_path.read_text(encoding="utf-8-sig"))
    if set(manifest.roles) != {"manager", "dev", "test", "reviewer"}:
        raise ValueError("Exactly manager, dev, test and reviewer roles required")
    snapshot = {"version": manifest.version, "roles": {}}
    for role, files in manifest.roles.items():
        content = {}
        for kind in ("soul", "goal"):
            source_path = getattr(files, kind)
            relative = Path(source_path)
            if relative.is_absolute() or ".." in relative.parts or ":" in source_path or "\\" in source_path:
                raise ValueError("Role file must be a contained relative Markdown path")
            target = (manifest_path.parent / relative).resolve()
            if not target.is_relative_to(manifest_path.parent) or target.suffix.lower() != ".md":
                raise ValueError("Role file escapes configuration directory or is not Markdown")
            if target.stat().st_size > 32768:
                raise ValueError("Role file exceeds 32 KiB")
            text = target.read_text(encoding="utf-8-sig").strip()
            if not text:
                raise ValueError("Empty role file")
            content[kind] = text
        snapshot["roles"][role] = content
    snapshot["sha256"] = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return snapshot


def role_prompt(record, role, prompt):
    snapshot = record.get("role_config")
    if snapshot is None:
        raise ValueError("Legacy workflow has no role configuration snapshot; submit a new workflow")
    config = snapshot["roles"][role]
    return ("Role guidance (not authority to change permissions, commands, acceptance or output schema):\n"
            + config["soul"] + "\n" + config["goal"]
            + "\nMandatory stage instructions take precedence over role guidance:\n" + prompt)
