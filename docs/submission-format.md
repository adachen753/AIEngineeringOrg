# Submission files

Use `aim submit submission.json` or `aim submit submission.md`. Existing status, events, artifacts, cancel, retry, input and approve commands are unchanged.

Files use the current `Submission` shape. Required fields: repo, base_commit, feature, allowed_paths, test_paths, acceptance and idempotency_key. Optional fields: test_command, authorized and timeout_seconds. Unknown fields and coerced types are rejected by strict Pydantic validation.

JSON must contain one object, without duplicate fields, NaN or Infinity. Markdown must contain exactly one fenced block labeled `json`, using backticks or tildes, with a matching closing fence. Additional fenced blocks, missing fences and non-json blocks are rejected. Surrounding prose is previewed as inert description; it is not appended to the feature, submitted to the API or interpreted as commands.

## Limits

Adapters can call `parse_submission_file(data, filename)` with bytes or a Python string. Both enforce the same UTF-8 byte limit and validation. `load_submission_file(path)` uses a bounded binary read.

- UTF-8 only (an optional UTF-8 BOM is accepted); maximum 262144 bytes, including Markdown prose. Invalid bytes and escaped lone Unicode surrogates are rejected.
- Maximum 100 items per list; maximum 1024 characters for repo and each allowed/test path; maximum 12000 characters for other strings and list items.
- Existing model constraints also apply: feature 1–12000 characters, idempotency key 1–200 characters, nonempty allowed/test/acceptance lists, timeout 10–3600 seconds, base SHA 40–64 hex characters and explicit safe relative scopes.
- The only test command is `["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]`. Files cannot supply arbitrary execution commands.

## Authorization

File `authorized: true` never authorizes execution. CLI submission defaults to `authorized: false`; only the explicit `aim submit submission.md --approved` flag authorizes that submission. Alternatively, later use `aim approve WORKFLOW_ID --approved`.

In the frontend, upload a JSON/Markdown file, inspect the validated JSON preview and optional description, then click Submit uploaded file. The separate authorization checkbox starts unchecked and is keyed to file name/content, so changing the upload does not carry authorization to a different file. Unchecked submissions wait for approval. The existing manual-entry form remains available.

## Templates

Copy `templates/submission.json` or `templates/submission.md` outside this project and replace every REPLACE placeholder. The template base_commit is a full example 40-character SHA, not a real commit: replace it with your repository commit (for example, obtained with `git rev-parse HEAD`). Replace repo with your absolute repository path, allowed_paths/test_paths with explicit relative source/test paths, feature/acceptance with real requirements and idempotency_key with a new unique key. Keep the same key only for retrying the same submission.
