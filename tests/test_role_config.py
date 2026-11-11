import json
import shutil
from pathlib import Path

import pytest

from ai_manager.role_config import load_role_config, role_prompt


def copy_config(tmp_path):
    source = Path(__file__).parents[1] / "ai_manager" / "roles"
    shutil.copytree(source, tmp_path / "roles")
    return tmp_path / "roles" / "config.json"


def test_defaults_and_prompt():
    config = load_role_config()
    assert set(config["roles"]) == {"manager", "dev", "test", "reviewer"}
    assert len(config["sha256"]) == 64
    prompt = role_prompt({"role_config": config}, "dev", "STAGE")
    assert "# Dev Soul" in prompt
    assert prompt.endswith("STAGE")


def test_workflow_snapshot_stable(store, submission, tmp_path, monkeypatch):
    manifest = copy_config(tmp_path)
    monkeypatch.setenv("AIM_ROLE_CONFIG", str(manifest))
    record = store.submit(submission)
    (manifest.parent / "dev" / "soul.md").write_text("Changed principles", encoding="utf-8")
    assert store.submit(submission)["role_config"] == record["role_config"]
    assert load_role_config()["sha256"] != record["role_config"]["sha256"]


@pytest.mark.parametrize("bad_path", ["../outside.md", "C:/outside.md", "dev/soul.json"])
def test_reject_role_paths(tmp_path, bad_path):
    manifest = copy_config(tmp_path)
    body = json.loads(manifest.read_text())
    body["roles"]["dev"]["soul"] = bad_path
    manifest.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError):
        load_role_config(manifest)


def test_missing_role(tmp_path):
    manifest = copy_config(tmp_path)
    body = json.loads(manifest.read_text())
    del body["roles"]["reviewer"]
    manifest.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError):
        load_role_config(manifest)


def test_legacy_workflow_requires_new_submission():
    with pytest.raises(ValueError, match="Legacy workflow"):
        role_prompt({}, "dev", "task")
