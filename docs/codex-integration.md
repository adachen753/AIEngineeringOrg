# Codex adapter integration

## Concrete production blocker

**Production is fail-closed.** The Windows 0.153.4 SDK sandbox denied out-of-directory writes in actual Test and Dev fixtures, but **raw TCP to localhost succeeded despite requested network disablement**. An agent could therefore contact the unauthenticated local backend and indirectly escape the intended write boundary. No production Manager/Dev/Test request is dispatched, including otherwise-valid directory scopes. This is an observed failure, not merely an untested possibility.

`GET /health` returns HTTP 200 with `ready:false`, `blocked:true`, role statuses, `command_network_enforced:false` and the specific blocker. Backend code must preflight before worktree or workflow side effects. The adapter does not claim a successful application workflow or independent review.

## HTTP API

The server binds only `127.0.0.1`, default 8766. Validated `PORT` supports alternate ports (1–65535). Unexpected Host headers and browser-origin requests are rejected; this is a trusted same-user localhost service, not an authenticated boundary.

- `POST /runs`: `{run_id,thread_id:null|string,prompt,cwd,role:"manager"|"dev"|"test",timeout_seconds,output_schema?,allowed_paths?,test_paths?}`. Existing absolute cwd, path-safe run ID, UUID thread ID and timeout 1–3600 seconds are required. Unknown fields are rejected.
- `GET /runs/{run_id}`: `{run_id,status,thread_id,result,events,error?}` with `running|succeeded|failed|cancelled|interrupted` status and parsed JSON/null result.
- `POST /runs/{run_id}/cancel`: AbortController cancellation request; terminal records remain unchanged. Active cancellation can initially return running while execution drains.
- Blocked POST returns 503 with a persisted failed record, null result and zero SDK dispatch. Identical duplicate IDs return the existing record; changed payloads return 409. There is no hidden retry or safety-bypass setting.

One active run at a time. Thread reuse requires matching role/cwd/scope and a known adapter record. Interrupted threads require operator reconciliation, not replay. Supported output-schema keywords are `type`, `properties`, `required`, boolean `additionalProperties`, `items`, `enum`, `description`; other keywords are rejected. The SDK receives the schema and JSON results are independently checked against this subset; backend business validation remains necessary.

## Installation and launch

Validated: Node 24.22.1, authenticated `codex-cli 0.153.4`, official `@openai/codex-sdk` 0.153.4. Node 24 native TypeScript stripping executes sources; no compiler/typecheck is claimed. `AIM_CODEX_EXE` can override executable discovery from PATH. Existing Codex authentication/session storage is reused; no credentials were copied into the repository.

Unmodified official SDK and CLI npm archives are included in `adapter/vendor/`; `package-lock.json` pins SHA-512 integrity. Their SHA-256 hashes match the official OpenAI release digests:

- SDK: `f2c5687c142d75d351a8ec069010b79322e4816d1684c127637bef9d1a3b557c`.
- CLI launcher: `fd04263c1adfa1d285c6c0ad86a97cab508d3012ee9eab80a99f773cc4b2fb3a`.

Run `npm ci --omit=optional --ignore-scripts` inside `adapter/`; optional platform binaries are omitted because the authenticated installed executable is used. Optional lock entries reference the configured Microsoft public npm mirror. No global npm installation or insecure TLS bypass occurred.

npm was absent from PATH. A local npm 10.9.4 was bootstrapped from the official npm/cli source release under ignored `adapter/.tools/cli-10.9.4`, with its workspace libraries materialized locally. These commands were actually executed, from the absolute application root:

```powershell
Set-Location -LiteralPath 'C:\Users\adachen\OneDrive - Microsoft\PERSONAL\Obsidian\cwz-notes\AI Learning\20261111 - AI manager\src'
Push-Location adapter
node .tools/cli-10.9.4/bin/npm-cli.js ci --omit=optional --ignore-scripts --audit=false --fund=false --cache .tools/npm-cache
Pop-Location
node adapter/src/server.ts
```

With ordinary npm installed, use `npm` instead of the local npm entry point. `AIM_ADAPTER_DATA` selects an adapter-owned data directory (default `adapter/runtime`). Ctrl+C requests graceful shutdown. `PORT` selects a validated port (default 8766); the server always binds to `127.0.0.1`. Standalone server PID 43404 on port 8766 was stopped after explicit coordination authorization; its adapter data was preserved. No main-task service was stopped by this adapter task.

## Persistence and privacy

Runs persist using exclusive temporary creation, fsync and atomic rename. Prompts are not stored; canonical request/scope digests provide idempotency and binding. A live owner lock blocks a second instance. After abrupt termination, verify the recorded PID is dead and remove **only the adapter-owned `.exclusive.lock`** before restarting; stale locks are not automatically removed, avoiding a multi-instance acquisition race. Startup then marks previous running records interrupted without replay. Corrupt or escaping records fail startup.

Reasoning events are dropped. Public command events omit stdout/stderr; MCP arguments/results and raw agent-message text are withheld. Structured final results and diagnostic errors are sanitized for credential keys, common API keys, bearer tokens, JWTs and URL credentials. Arbitrary unknown secrets cannot be reliably recognized; do not expose raw SDK sessions or supply sensitive diagnostic fixtures. SDK session storage is separate from adapter persistence.

AbortSignal cancellation is implemented. Timeout/cancel finalization waits for the SDK iterator to drain and never implies rollback. Windows descendant-process termination is not independently proven. A real no-tool cancellation experiment and fake-only lifecycle tests are distinguished in the evidence section below.

## Real SDK evidence (2026-11-11 UTC)

Sanitized, delivery-preserved captures are in `adapter/evidence/`; runtime originals are under ignored `adapter/runtime/experiment/`. No application Git commit was made.

Thread `01a1c97f-5798-7bf2-b471-d2f391d0e084`:

| Phase | Finish UTC | Actual parsed result |
| --- | --- | --- |
| Start | 07:25:35.895 | `{"marker":"AIMSDK-ORCHID-731","phase":"start"}` |
| Same SDK engine/thread-object continuation | 07:25:40.786 | `{"marker":"AIMSDK-ORCHID-731","phase":"continue"}` |
| Fresh Node process/adapter engine, resume saved ID | 07:25:47.724 | `{"marker":"AIMSDK-ORCHID-731","phase":"restart"}` |
| Diagnostic resume | 07:29:26.591 | `{"marker":"AIMSDK-ORCHID-731","phase":"diagnostic"}` |

Continuation and restart prompts did not repeat the remembered marker. Captures contain actual `thread.started`, `turn.started`, `item.completed`, `turn.completed` and token usage. Diagnostic events precisely report enabled under-development `standalone_web_search` and missing metadata for configured `gpt-6.1-sol`; these are non-fatal warnings, not authentication failures. No model was substituted. Reproduce with `node adapter/scripts/experiment.ts start`, then `node adapter/scripts/experiment.ts restart <saved-thread-id>`. Explicit no-tool connectivity experiments do not bypass production HTTP admission or establish sandbox readiness.

### Test directory scope

Thread `01a1c981-5724-73c0-b6a8-5fc6eff94678`, finish 07:27:51.992, actual command exit 0:

```json
{"inside":"write-allowed","product":"EPERM","git_root":"EPERM","parent":"EPERM","product_read":"product fixture; must stay unchanged"}
```

SDK cwd was the fixture's `tests` directory, workspace-write with no additional directories. An independently initialized Git parent root did not become writable. Local inspection also confirmed only the allowed marker was created. An earlier attempt emitted completion but failed after its abort window; only the successfully drained repeat is presented as success. `node adapter/scripts/scope-experiment.ts` creates another adapter-owned fixture for reproduction.

### Dev directories and network: decisive failure

Thread `01a1c985-65ae-72f2-87cc-b0eb39099d02`, finish 07:32:18.737, actual command exit 0:

```json
{"product":"write-allowed","tests":"write-allowed","git_root":"EPERM","git_metadata":"EPERM","sibling":"EPERM","raw_loopback_network":"connected"}
```

SDK cwd was `product`; `additionalDirectories` contained only sibling `tests`. Both requested directories were writable; root, `.git` and an unauthorized sibling were denied. The adapter-owned probe used Node `net.createConnection` to an adapter-owned listener on `127.0.0.1:50754`. Its actual stdout matches the structured result above. It connected while `networkAccessEnabled:false`, `sandbox_workspace_write.network_access:false` and `webSearchMode:"disabled"` were set. The fixture script and reproducer are delivered as `adapter/test/fixtures/dev-scope-probe.cjs` and `adapter/scripts/dev-scope-experiment.ts`; the latter uses an ephemeral local port. No real backend API request or network-policy bypass was attempted.

Directory narrowing therefore has partial positive evidence, but cannot safely enable this backend integration under the requested no-network boundary. File allowlists, junction/hard-link escapes and all tool surfaces are additionally unverified. Root-level grants, post-diff checks, environment proxy variables and prompt instructions are not substituted for actual enforcement.

### Actual cancellation

`adapter/evidence/cancel.json`: thread `01a1c987-e47d-7ea3-8812-6bb7d5075018`, 07:34:48.032–07:34:51.322. AbortController was triggered on the actual `thread.started` event. The SDK rejected with code `ABORT_ERR`, message `The operation was aborted`, null result and no tool events. This verifies no-tool SDK abort propagation, not cancellation/rollback of arbitrary command descendants.

## App-server/profile evaluation

Official beta permission profiles support finer filesystem policies. They do not compose with legacy `--sandbox`/`sandbox_workspace_write`; loaded legacy config can also affect selection. The current SDK options are legacy mode. `writable_roots` and `additionalDirectories` add rights, not restrictions on SDK cwd.

The locally generated **0.153.4 experimental App-server schema** confirms `thread/start.permissions` selects a named profile and cannot be combined with `sandbox`; `turn/start.permissions` cannot combine with `sandboxPolicy`; `runtimeWorkspaceRoots` can replace runtime roots. A profile-based App-server is a possible future integration, **not a tested solution to this network failure**. Inference here used the SDK only. Generation command: `codex app-server generate-json-schema --experimental --out adapter/.tools/appserver-schema`.

Profiles govern sandboxed local commands, not every connector/MCP/browser/computer-use or Codex service-network surface. No speculative profile change was used to bypass the observed failure.

## Tests and references

The main implementation task reports an actual startup lifecycle on adapter 8876/backend 8875/UI 8851: start and health checks, stop with all three ports closed, then restart using the same data. Its actual Streamlit AppTest-to-HTTP workflow `d88f143b-ad52-491a-8075-8de4f8db4a81` was blocked at adapter preflight with no thread and no worktree. These application acceptance observations and their captures belong to the main task; they were not independently executed by this adapter task and do not constitute a successful production workflow.

`node --test adapter/test/*.test.ts`: **7 passed, 0 failed**. Coverage includes path/schema validation, privacy, fail-closed production with zero SDK construction, idempotency, thread binding, persistence/restart ambiguity, cancel/timeout/error controls and real localhost HTTP endpoints. Fake engines exist only in explicitly named isolated control tests. Real SDK evidence above is not mocked. No full application workflow, backend test execution, independent review or Service Fabric E2E is claimed.

Official documentation read: [SDK](https://developers.openai.com/codex/sdk), [App-server](https://developers.openai.com/codex/app-server), [Permissions](https://developers.openai.com/codex/permissions), [Advanced configuration](https://developers.openai.com/codex/config-advanced). Packages are from the [official OpenAI 0.153.4 release](https://github.com/openai/codex/releases/tag/rust-v0.153.4).
