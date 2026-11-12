import { ApiError, requireEnforcedScope } from './policy.ts';
import { digest, validateRequest } from './request.ts';
import type { RunRequest } from './request.ts';
import { publicEvent, sanitize } from './privacy.ts';
import { SdkEngine } from './engine.ts';
import { CopilotEngine } from './copilot.ts';
import { RunStore } from './store.ts';
import type { RunRecord } from './store.ts';

type Engine = { run(request: RunRequest, signal: AbortSignal, onEvent: (event: any) => void): Promise<unknown> };
type Active = { record: RunRecord; controller: AbortController; reason?: 'cancel' | 'timeout' | 'shutdown'; done: Promise<void> };

export function response(record: RunRecord): any {
  return sanitize({ run_id: record.run_id, status: record.status, thread_id: record.thread_id, result: record.result, events: record.events, ...(record.error ? { error: record.error } : {}) });
}

export class RunService {
  store: RunStore;
  engineFactory: (request: RunRequest) => Engine;
  admission: (request?: RunRequest) => void;
  active?: Active;
  constructor(store: RunStore, engineFactory: (request: RunRequest) => Engine = request => request.provider === 'copilot' ? new CopilotEngine() : new SdkEngine(), admission = requireEnforcedScope) {
    this.store = store;
    this.engineFactory = engineFactory;
    this.admission = admission;
  }

  get(id: string): RunRecord {
    const record = this.store.records.get(id);
    if (!record) throw new ApiError(404, 'Unknown run_id');
    return record;
  }

  submit(input: unknown): { code: number; record: RunRecord } {
    const request = validateRequest(input);
    const fingerprint = digest(request);
    const existing = this.store.records.get(request.run_id);
    if (existing) {
      if (existing.fingerprint !== fingerprint) throw new ApiError(409, 'run_id already used for a different request');
      return { code: 200, record: existing };
    }
    if (this.active) throw new ApiError(409, 'One run at a time');
    const binding = digest({ cwd: request.cwd, role: request.role, allowed_paths: request.allowed_paths ?? [], test_paths: request.test_paths ?? [], ...(request.provider || request.model || request.effort ? { provider: request.provider ?? 'codex', model: request.model ?? null, effort: request.effort ?? null } : {}) });
    if (request.thread_id) {
      const history = [...this.store.records.values()].filter(record => record.thread_id === request.thread_id);
      if (!history.length || history.some(record => record.binding !== binding)) throw new ApiError(409, 'Unknown thread or role/cwd/write-scope mismatch');
      if (history.some(record => record.status === 'interrupted')) throw new ApiError(409, 'Ambiguous interrupted thread requires operator reconciliation, not automatic replay');
    }
    const record: RunRecord = { run_id: request.run_id, thread_id: request.thread_id, status: 'running', result: null, events: [], fingerprint, binding };
    try { this.admission(request); } catch (error) {
      record.status = 'failed';
      record.error = error instanceof ApiError ? error.message : 'SCOPE_ADMISSION_FAILED';
      this.store.save(record);
      return { code: 503, record };
    }
    this.store.save(record);
    const active: Active = { record, controller: new AbortController(), done: Promise.resolve() };
    this.active = active;
    active.done = this.execute(request, active);
    return { code: 202, record };
  }

  private async execute(request: RunRequest, active: Active): Promise<void> {
    const timer = setTimeout(() => { active.reason ??= 'timeout'; active.controller.abort(); }, request.timeout_seconds * 1000);
    try {
      const result = await this.engineFactory(request).run(request, active.controller.signal, event => {
        if (event.type === 'thread.started') {
          if (active.record.thread_id && active.record.thread_id !== event.thread_id) throw new Error('THREAD_ID_MISMATCH');
          active.record.thread_id = event.thread_id;
        }
        const visible = publicEvent(event);
        if (visible) {
          if (active.record.events.length >= 10000) throw new Error('EVENT_LIMIT');
          active.record.events.push(visible);
        }
        this.store.save(active.record);
      });
      if (!active.reason) { active.record.result = sanitize(result); active.record.status = 'succeeded'; }
    } catch (error: any) {
      active.record.status = 'failed';
      active.record.error = ['INVALID_JSON_RESULT', 'INVALID_SCHEMA_RESULT', 'SDK_TURN_FAILED', 'INCOMPLETE_TURN', 'THREAD_ID_MISMATCH', 'EVENT_LIMIT'].includes(error.message) ? error.message : 'SDK_EXECUTION_FAILED: details withheld';
    } finally {
      clearTimeout(timer);
      if (active.reason) {
        active.record.result = null;
        active.record.status = active.reason === 'cancel' ? 'cancelled' : active.reason === 'shutdown' ? 'interrupted' : 'failed';
        active.record.error = active.reason === 'timeout' ? 'TIMEOUT' : active.reason === 'shutdown' ? 'ADAPTER_SHUTDOWN: delivery ambiguous' : 'CANCELLED: abort requested; descendant process termination is not independently verified';
      }
      try { this.store.save(active.record); } finally { this.active = undefined; }
    }
  }

  cancel(id: string): RunRecord {
    const record = this.get(id);
    if (record.status === 'running' && this.active?.record.run_id === id) { this.active.reason ??= 'cancel'; this.active.controller.abort(); }
    return record;
  }

  async shutdown(): Promise<void> {
    if (this.active) { this.active.reason ??= 'shutdown'; this.active.controller.abort(); await this.active.done; }
    this.store.close();
  }
}
