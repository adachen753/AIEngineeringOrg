# Submission template

Replace every REPLACE placeholder, including repo and relative paths. Replace the example full 40-character SHA with the actual repository base commit SHA. This prose is description only, never commands.

```json
{
  "repo": "C:/REPLACE_WITH_YOUR_REPO",
  "base_commit": "0123456789abcdef0123456789abcdef01234567",
  "feature": "REPLACE: describe the requested feature.",
  "allowed_paths": [
    "REPLACE_WITH_SOURCE_PATH"
  ],
  "test_paths": [
    "REPLACE_WITH_TEST_PATH"
  ],
  "acceptance": [
    "REPLACE: specify a measurable acceptance criterion."
  ],
  "test_command": [
    "python",
    "-m",
    "pytest",
    "-q",
    "-p",
    "no:cacheprovider"
  ],
  "idempotency_key": "REPLACE_WITH_UNIQUE_SUBMISSION_KEY",
  "authorized": false,
  "timeout_seconds": 300
}
```
