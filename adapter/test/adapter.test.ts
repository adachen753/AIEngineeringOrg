import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { ApiError, capabilities, protectedPath } from '../src/policy.ts';
import { digest, matchesSchema, validateRequest } from '../src/request.ts';
import { publicEvent, redact, sanitize } from '../src/privacy.ts';
import { RunStore } from '../src/store.ts';
import { RunService, response } from '../src/service.ts';
import { createServer } from '../src/server.ts';

const root = fileURLToPath(new URL('../runtime/tests', import.meta.url));
mkdirSync(root, { recursive: true });
const threadId = '11111111-1111-7111-8111-111111111111';
const fixture = () => mkdtempSync(path.join(root, 'case-'));
const request = (cwd: string, changes = {}) => ({ run_id: 'run-1', thread_id: null, prompt: 'Return JSON', cwd, role: 'manager', timeout_seconds: 1, ...changes });
const admitted = () => {};

test('request validation, protected paths, schema subset and stable digest', () => {
  const cwd = fixture();
  assert.equal(validateRequest(request(cwd)).cwd, cwd);
  for (const changes of [{ run_id: '../escape' }, { thread_id: 'not-a-uuid' }, { prompt: '' }, { timeout_seconds: 0 }, { role: 'unknown' }, { unknown: true }, { allowed_paths: ['../escape'] }, { output_schema: { type: 'object', $ref: 'https://example.com' } }]) {
    assert.throws(() => validateRequest(request(cwd, changes)), ApiError);
  }
  assert.equal(protectedPath('Q:\\GraphConnectors\\cwzClaude\\notes.md'), true);
  assert.equal(protectedPath('q:/graphconnectors/sources/dev/cwzclaude-sql/draft.sql'), true);
  assert.equal(protectedPath('Q:/GraphConnectors/cwzClaudeOther'), false);
  const schema = { type: 'object', properties: { count: { type: 'integer' } }, required: ['count'], additionalProperties: false };
  assert.equal(matchesSchema({ count: 3 }, schema), true);
  assert.equal(matchesSchema({ count: 3.5 }, schema), false);
  assert.equal(matchesSchema({ count: 3, extra: true }, schema), false);
  assert.equal(digest({ first: 1, second: 2 }), digest({ second: 2, first: 1 }));
});

test('privacy drops reasoning, command stdout, MCP payloads and credential keys', () => {
  assert.equal(publicEvent({ type: 'item.completed', item: { type: 'reasoning', text: 'private reasoning' } }), null);
  assert.equal(JSON.stringify(publicEvent({ type: 'item.completed', item: { id: '1', type: 'command_execution', command: 'echo api_key=sk-secretsecret', aggregated_output: 'private raw stdout' } })).includes('private raw stdout'), false);
  assert.equal(JSON.stringify(publicEvent({ type: 'item.completed', item: { id: '2', type: 'mcp_tool_call', arguments: { password: 'secret' } } })).includes('secret'), false);
  assert.equal(redact('Bearer abcdefghijk api_key=sk-1234567890').includes('abcdefghijk'), false);
  assert.deepEqual(sanitize({ access_token: 'secret', reasoning: 'hidden', input_tokens: 5 }), { access_token: '[REDACTED]', input_tokens: 5 });
});

test('production fails closed before SDK construction; duplicate IDs never redispatch', async () => {
  const cwd = fixture();
  const store = new RunStore(path.join(cwd, 'data'));
  let constructions = 0;
  const service = new RunService(store, () => { constructions++; throw new Error('must not construct SDK'); });
  assert.equal(capabilities.ready, false);
  const submitted = service.submit(request(cwd));
  assert.equal(submitted.code, 503);
  assert.equal(submitted.record.status, 'failed');
  assert.equal(service.submit(request(cwd)).code, 200);
  assert.throws(() => service.submit(request(cwd, { prompt: 'changed' })), /different request/);
  assert.equal(constructions, 0);
  assert.equal(JSON.stringify(response(service.get('run-1'))).includes('fingerprint'), false);
  assert.equal(readFileSync(path.join(cwd, 'data/run-1.json'), 'utf8').includes('Return JSON'), false);
  await service.shutdown();
});

test('isolated fake engine tests success, binding, persistence and explicit resume', async () => {
  const cwd = fixture();
  const directory = path.join(cwd, 'data');
  const store = new RunStore(directory);
  const engine = { async run(input: any, signal: AbortSignal, emit: (event: any) => void) {
    emit({ type: 'thread.started', thread_id: input.thread_id ?? threadId });
    emit({ type: 'item.completed', item: { type: 'reasoning', text: 'hidden' } });
    return { ok: true, api_key: 'secret' };
  } };
  const service = new RunService(store, () => engine, admitted);
  assert.equal(service.submit(request(cwd)).code, 202);
  await service.active?.done;
  assert.equal(service.get('run-1').status, 'succeeded');
  assert.deepEqual(service.get('run-1').result, { ok: true, api_key: '[REDACTED]' });
  assert.throws(() => service.submit(request(cwd, { run_id: 'mismatch', thread_id: threadId, role: 'dev' })), /mismatch/);
  await service.shutdown();
  const restored = new RunService(new RunStore(directory), () => engine, admitted);
  assert.equal(restored.get('run-1').thread_id, threadId);
  restored.submit(request(cwd, { run_id: 'run-2', thread_id: threadId }));
  await restored.active?.done;
  assert.equal(restored.get('run-2').status, 'succeeded');
  await restored.shutdown();
});

test('fake-only cancel, timeout, one-run limit and errors', async () => {
  const cwd = fixture();
  const waiting = { run(input: any, signal: AbortSignal) { return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true })); } };
  const service = new RunService(new RunStore(path.join(cwd, 'data')), () => waiting, admitted);
  service.submit(request(cwd));
  assert.throws(() => service.submit(request(cwd, { run_id: 'other' })), /One run/);
  const cancelled = service.active!.done;
  service.cancel('run-1');
  await cancelled;
  assert.equal(service.get('run-1').status, 'cancelled');
  service.submit(request(cwd, { run_id: 'timeout' }));
  await service.active?.done;
  assert.equal(service.get('timeout').error, 'TIMEOUT');
  service.engineFactory = () => ({ async run() { throw new Error('credential error sk-privateprivate'); } });
  service.submit(request(cwd, { run_id: 'error' }));
  await service.active?.done;
  assert.equal(service.get('error').error, 'SDK_EXECUTION_FAILED: details withheld');
  await service.shutdown();
});

test('restart marks ambiguous running delivery interrupted and prohibits replay', async () => {
  const cwd = fixture();
  const directory = path.join(cwd, 'data');
  const store = new RunStore(directory);
  const input = validateRequest(request(cwd));
  store.save({ run_id: 'run-1', thread_id: threadId, status: 'running', result: null, events: [], fingerprint: digest(input), binding: digest({ cwd, role: 'manager', allowed_paths: [], test_paths: [] }) });
  assert.throws(() => new RunStore(directory), /live process/);
  store.close();
  const service = new RunService(new RunStore(directory));
  assert.equal(service.get('run-1').status, 'interrupted');
  assert.equal(service.submit(request(cwd)).record.status, 'interrupted');
  assert.throws(() => service.submit(request(cwd, { run_id: 'retry', thread_id: threadId })), /reconciliation/);
  await service.shutdown();
});

test('real localhost HTTP health, blocked POST, GET, cancel and browser protection', async () => {
  const cwd = fixture();
  const service = new RunService(new RunStore(path.join(cwd, 'data')));
  const server = createServer(service);
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address() as any;
  const base = `http://127.0.0.1:${address.port}`;
  try {
    const health = await (await fetch(`${base}/health`)).json();
    assert.equal(health.ready, false);
    const posted = await fetch(`${base}/runs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request(cwd)) });
    assert.equal(posted.status, 503);
    assert.equal((await posted.json()).status, 'failed');
    assert.equal((await fetch(`${base}/runs/run-1`)).status, 200);
    assert.equal((await fetch(`${base}/runs/run-1/cancel`, { method: 'POST' })).status, 200);
    assert.equal((await fetch(`${base}/health`, { headers: { Origin: 'https://example.com' } })).status, 403);
    assert.equal((await fetch(`${base}/runs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{invalid' })).status, 400);
    assert.equal((await fetch(`${base}/runs/unknown`)).status, 404);
  } finally {
    await new Promise<void>(resolve => server.close(() => resolve()));
    await service.shutdown();
  }
});
