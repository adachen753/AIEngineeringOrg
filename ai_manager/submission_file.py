import json
import re
from dataclasses import dataclass
from pathlib import Path

from ai_manager.models import FeatureRequest, Submission

MAX_FILE_BYTES = 256 * 1024
MAX_LIST_ITEMS = 100
MAX_TEXT_LENGTH = 12000
MAX_PATH_LENGTH = 1024


@dataclass(frozen=True)
class SubmissionFile:
    submission: Submission
    description: str = ""
    endpoint: str = "/workflows"

    def payload(self, *, approved: bool = False) -> dict:
        if type(approved) is not bool:
            raise ValueError("Approval must be an explicit boolean")
        return self.submission.model_dump() | {"authorized": approved, "deploy_authorized": False}


@dataclass(frozen=True)
class FeatureFile:
    submission: FeatureRequest
    description: str = ""
    endpoint: str = "/features"

    def payload(self, *, approved: bool = False) -> dict:
        if type(approved) is not bool:
            raise ValueError("Approval must be an explicit boolean")
        return self.submission.model_dump() | {"authorized": approved, "deploy_authorized": False}


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"Duplicate JSON field: {name}")
        result[name] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


def parse_submission_file(data: bytes | str, filename: str) -> SubmissionFile | FeatureFile:
    if isinstance(data, str):
        try:
            data = data.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValueError("Submission file must be valid UTF-8") from exc
    if not isinstance(data, bytes):
        raise ValueError("Submission file must be bytes or text")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"Submission file exceeds {MAX_FILE_BYTES} bytes")
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("Submission file must be valid UTF-8") from exc
    suffix = Path(filename).suffix.lower()
    description = ""
    if suffix == ".md":
        lines = text.splitlines(keepends=True)
        fences = [index for index, line in enumerate(lines)
                  if re.match(r"^ {0,3}(?:\x60{3,}|~{3,})", line)]
        if len(fences) != 2:
            raise ValueError("Markdown requires exactly one fenced json block")
        opening, closing = fences
        match = re.fullmatch(r" {0,3}(\x60{3,}|~{3,})json[ \t]*\r?\n?", lines[opening])
        if not match or not re.fullmatch(
            r" {0,3}" + re.escape(match[1][0]) + "{" + str(len(match[1])) + r",}[ \t]*\r?\n?",
            lines[closing],
        ):
            raise ValueError("Markdown requires exactly one fenced json block")
        description = "".join(lines[:opening] + lines[closing + 1:]).strip()
        text = "".join(lines[opening + 1:closing])
    elif suffix != ".json":
        raise ValueError("Submission file must use .json or .md")
    try:
        body = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except RecursionError as exc:
        raise ValueError("Submission JSON is too deeply nested") from exc
    if not isinstance(body, dict):
        raise ValueError("Submission JSON must be an object")
    for name, value in body.items():
        if isinstance(value, str):
            limit = MAX_PATH_LENGTH if name == "repo" else MAX_TEXT_LENGTH
            if len(value) > limit:
                raise ValueError(f"{name} exceeds {limit} characters")
        elif isinstance(value, list):
            if len(value) > MAX_LIST_ITEMS:
                raise ValueError(f"{name} exceeds {MAX_LIST_ITEMS} items")
            limit = MAX_PATH_LENGTH if name in {"allowed_paths", "test_paths"} else MAX_TEXT_LENGTH
            if any(isinstance(item, str) and len(item) > limit for item in value):
                raise ValueError(f"{name} item exceeds {limit} characters")
    try:
        json.dumps(body, ensure_ascii=False).encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("Submission JSON contains invalid Unicode") from exc
    except RecursionError as exc:
        raise ValueError("Submission JSON is too deeply nested") from exc
    if "project" in body:
        return FeatureFile(submission=FeatureRequest.model_validate(body, strict=True), description=description)
    submission = Submission.model_validate(body, strict=True)
    return SubmissionFile(submission=submission, description=description)


def load_submission_file(path: Path) -> SubmissionFile | FeatureFile:
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    return parse_submission_file(data, path.name)
