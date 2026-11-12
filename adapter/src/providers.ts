import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { ApiError, capabilities } from './policy.ts';
import { SdkEngine, resolveCodex } from './engine.ts';
import { CopilotConnection, CopilotEngine, resolveCopilot } from './copilot.ts';
import { validateRequest } from './request.ts';
import { publicEvent, redact } from './privacy.ts';

const execute = promisify(execFile);
const root = path.resolve(process.env.AIM_ADAPTER_DATA ?? 'adapter/.runtime', 'model-probes');
const active = new Set<string>();
export const probeBusy = () => active.size > 0;

export async function providers(): Promise<unknown> {
  let codex = false;
  let authenticated = false;
  let copilot = false;
  try {
    const executable = resolveCodex();
    codex = true;
    await execute(executable, ['login', 'status'], { timeout: 5000, windowsHide: true, maxBuffer: 65536 });
    authenticated = true;
  } catch {}
  try { copilot = Boolean(resolveCopilot()); } catch {}
  return { providers: [
    { id: 'codex', installed: codex, authenticated, transport: 'codex-sdk', login_command: 'codex login', execution_ready: false, blocker: capabilities.blocker },
    { id: 'copilot', installed: copilot, authenticated: null, transport: 'copilot-acp', auth_source: process.env.AIM_COPILOT_AUTH_SOURCE === 'github-cli' ? 'github-cli-explicit-opt-in' : 'copilot-cli', login_command: 'copilot login', execution_ready: false, blocker: 'COPILOT_EXECUTION_BOUNDARY_NOT_VERIFIED; tools are denied' },
  ], probe_busy: probeBusy() };
}

export async function catalog(provider: unknown): Promise<unknown> {
  if (provider === 'codex') {
    const cache = path.join(process.env.CODEX_HOME ?? path.join(homedir(), '.codex'), 'models_cache.json');
    if (existsSync(cache)) {
      const body = JSON.parse(readFileSync(cache, 'utf8'));
      const models = (body.models ?? []).map((model: any) => ({ id: model.slug, label: model.display_name ?? model.slug, efforts: (model.supported_reasoning_levels ?? []).map((level: any) => level.effort) })).filter((model: any) => typeof model.id === 'string');
      return { provider, models, source: 'codex-local-cache', verified_access: false };
    }
  }
  if (!['codex', 'copilot'].includes(provider as string)) throw new ApiError(400, 'Unknown provider');
  if (probeBusy()) throw new ApiError(409, 'Wait for the active connection probe');
  mkdirSync(root, { recursive: true });
  const cwd = mkdtempSync(path.join(root, 'catalog-'));
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  const connection = new CopilotConnection(cwd, controller.signal, provider === 'codex' ? { executable: resolveCodex(), args: ['app-server'] } : undefined);
  try {
    if (provider === 'codex') {
      await connection.request('initialize', { clientInfo: { name: 'ai-manager', version: '0.1.0' } });
      connection.child.stdin!.write(JSON.stringify({ jsonrpc: '2.0', method: 'initialized', params: {} }) + '\n');
      const response = await connection.request('model/list', { limit: 100 });
      return { provider, models: (response.data ?? []).map((model: any) => ({ id: model.model ?? model.id, label: model.displayName ?? model.model ?? model.id, efforts: (model.supportedReasoningEfforts ?? []).map((level: any) => level.reasoningEffort) })), source: 'codex-live-app-server', verified_access: false };
    }
    const session = await connection.open(cwd);
    return { provider, models: (session.models?.availableModels ?? []).map((model: any) => ({ id: model.modelId, label: model.name ?? model.modelId, efforts: [] })), source: 'copilot-live-acp', verified_access: false };
  } catch (error: any) { throw new ApiError(503, 'MODEL_CATALOG_UNAVAILABLE: ' + redact(String(error.message)).slice(0, 300) + '; check CLI login and runtime compatibility'); }
  finally { clearTimeout(timeout); connection.close(); }
}

export function getProbe(id: string): any {
  if (!/^[0-9a-f-]{36}$/.test(id)) throw new ApiError(400, 'Invalid probe ID');
  const file = path.join(root, id + '.json');
  if (!existsSync(file)) throw new ApiError(404, 'Unknown probe');
  const record = JSON.parse(readFileSync(file, 'utf8'));
  if (record.status === 'running' && !active.has(id)) record.status = 'interrupted';
  return record;
}

export function startProbe(body: any): unknown {
  if (!body || Object.keys(body).some(key => !['provider', 'model', 'effort', 'approved'].includes(key)) || body.approved !== true) throw new ApiError(400, 'Explicit approval required; only provider/model/effort are accepted');
  if (!body.provider || !body.model) throw new ApiError(400, 'Select provider and an explicit model');
  if (probeBusy()) throw new ApiError(409, 'One probe at a time');
  mkdirSync(root, { recursive: true });
  const id = randomUUID();
  const cwd = mkdtempSync(path.join(root, 'probe-'));
  const request = validateRequest({ run_id: id, thread_id: null, cwd, role: 'manager', timeout_seconds: 90, provider: body.provider, model: body.model, ...(body.effort ? { effort: body.effort } : {}), prompt: 'Fixed AIManager connectivity diagnostic. Do not invoke tools, run commands, read files, or change files. Return only JSON {"connected":true}.', output_schema: { type: 'object', properties: { connected: { type: 'boolean', enum: [true] } }, required: ['connected'], additionalProperties: false } });
  const record: any = { id, provider: body.provider, requested_model: body.model, requested_effort: body.effort ?? null, status: 'running', thread_id: null, started_at: new Date().toISOString(), scope: 'fixed-connectivity-probe-only', execution_ready: false, events: [] };
  const save = () => writeFileSync(path.join(root, id + '.json'), JSON.stringify(record, null, 2));
  active.add(id);
  save();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 90000);
  void (async () => {
    try {
      const engine = body.provider === 'copilot' ? new CopilotEngine() : new SdkEngine(true);
      record.result = await engine.run(request, controller.signal, event => {
        if (event.type === 'thread.started') record.thread_id = event.thread_id;
        if (event.type.startsWith('item.') && !['agent_message', 'reasoning', 'error'].includes(event.item?.type)) { record.unexpected_item_type = event.item?.type; controller.abort(); throw new Error('PROBE_UNEXPECTED_TOOL_EVENT'); }
        const visible = publicEvent(event);
        if (visible && record.events.length < 100) record.events.push(visible);
        save();
      });
      if (!record.thread_id || (record.result as any)?.connected !== true) throw new Error('PROBE_RESULT_NOT_VERIFIED');
      record.status = 'succeeded';
    } catch (error: any) { record.status = 'failed'; record.error = redact(String(error.message)).slice(0, 1000); }
    finally { clearTimeout(timer); active.delete(id); record.finished_at = new Date().toISOString(); save(); }
  })();
  return record;
}
