import re
from pathlib import Path

PROTECTED = ("q:/graphconnectors/cwzclaude", "q:/graphconnectors/sources/dev/cwzclaude-sql")

def normalized(path: Path | str) -> str:
    return str(path).replace("\\", "/").rstrip("/").casefold()

def protect(path: Path | str):
    value = normalized(path)
    if any(value == root or value.startswith(root + "/") for root in PROTECTED):
        raise ValueError("Protected user directory")

def within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    protect(resolved)
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Path escapes owned root")
    return resolved

def redact(value: str) -> str:
    value = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "[REDACTED]", value)
    value = re.sub(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s\"']+", r"\1[REDACTED]", value)
    return re.sub(r"(?i)((?:api[_-]?key|password|access[_-]?token)\s*[=:]\s*)[^\s,\"']+", r"\1[REDACTED]", value)

def allowed_file(name: str, scopes: list[str]) -> bool:
    candidate = name.replace("\\", "/")
    if candidate.startswith("/") or ".." in candidate.split("/") or ".git" in candidate.split("/"):
        return False
    return any(candidate == scope.rstrip("/") or candidate.startswith(scope.rstrip("/") + "/") for scope in scopes)
