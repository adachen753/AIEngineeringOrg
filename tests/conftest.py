from pathlib import Path

import pytest

from ai_manager.git import git
from ai_manager.models import Submission
from ai_manager.store import Store


@pytest.fixture
def repo(tmp_path):
    directory = tmp_path / "repo"
    directory.mkdir()
    git(directory, "init")
    (directory / "app").mkdir()
    (directory / "tests").mkdir()
    (directory / "app" / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
    (directory / "tests" / "test_feature.py").write_text(
        "from app.feature import VALUE\n\ndef test_acceptance():\n    assert VALUE == 1\n", encoding="utf-8"
    )
    git(directory, "add", "--", "app/feature.py", "tests/test_feature.py")
    git(directory, "-c", "user.name=Fixture", "-c", "user.email=fixture@localhost",
        "commit", "-m", "Authorized test fixtures")
    return directory


@pytest.fixture
def submission(repo):
    return Submission(repo=str(repo), base_commit=git(repo, "rev-parse", "HEAD"),
                      feature="Return the requested value", allowed_paths=["app"],
                      test_paths=["tests"], acceptance=["Returns the requested value"],
                      idempotency_key="fixture-key", authorized=True)


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "data")
    yield instance
    instance.db.close()
