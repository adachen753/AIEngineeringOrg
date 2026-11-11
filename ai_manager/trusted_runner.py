import json
import os
import sys
from pathlib import Path

import pytest


class Evidence:
    def __init__(self):
        self.cases = {}
        self.collection_errors = []
        self.collected = []

    def pytest_collection_finish(self, session):
        self.collected = [item.nodeid for item in session.items]

    def pytest_collectreport(self, report):
        if report.failed:
            self.collection_errors.append(str(report.longrepr))

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or report.failed or report.skipped:
            previous = self.cases.get(report.nodeid)
            if previous not in {"failed", "skipped"}:
                self.cases[report.nodeid] = report.outcome


def main():
    destination = Path(sys.argv[1]).resolve()
    repository = Path.cwd().resolve()
    if destination.is_relative_to(repository):
        raise ValueError("Evidence must be outside immutable test repository")
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    sys.path.insert(0, str(repository))
    evidence = Evidence()
    code = pytest.main(["-q", "-p", "no:cacheprovider"], plugins=[evidence])
    destination.write_text(json.dumps({"collected": evidence.collected, "cases": evidence.cases, "collection_errors": evidence.collection_errors, "pytest_version": pytest.__version__}), encoding="utf-8")
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
