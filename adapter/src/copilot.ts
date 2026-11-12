import { spawn, execFileSync } from 'node:child_process';
import { matchesSchema } from './request.ts';
import type { RunRequest } from './request.ts';
import { redact } from './privacy.ts';

export function resolveCopilot(): string {
  if (process.env.AIM_COPILOT_EXE) return process.env.AIM_COPILOT_EXE;
  return execFileSync(process.platform === 'win32' ? 'where.exe' : 'which', [process.platform === 'win32' ? 'copilot.exe' : 'copilot'], { encoding: 'utf8', windowsHide: true }).trim().split(/\r?\n/)[0];
}

export class CopilotConnection {
  child: ReturnType<typeof spawn>;
  pending = new Map<number, { resolve: (value: any) => void; reject: (error: Error) => void }>();
  sequence = 0;
  buffer = '';
  closed = false;
  onUpdate: (params: any) => void = () => {};
  abort: () => void;
  signal: AbortSignal;

  constructor(cwd: string, signal: AbortSignal, launch?: { executable: string; args: string[] }) {
    this.signal = signal;
    if (signal.aborted) throw new Error('COPILOT_ABORTED');
    const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^(AIM_|COPILOT_ALLOW_ALL|COPILOT_YOLO|OPENAI_API_KEY$|CODEX_API_KEY$)/i.test(key)));
    if (process.env.AIM_COPILOT_AUTH_SOURCE === 'github-cli') {
      const host = process.env.AIM_COPILOT_GITHUB_HOST ?? 'github.com';
      const user = process.env.AIM_COPILOT_GITHUB_USER;
      if (!/^[A-Za-z0-9.-]+$/.test(host) || (user && !/^[A-Za-z0-9-]+$/.test(user))) throw new Error('INVALID_GITHUB_ACCOUNT_SELECTION');
      try {
        const token = execFileSync(process.env.AIM_GH_EXE ?? 'gh', ['auth', 'token', '--hostname', host, ...(user ? ['--user', user] : [])], { encoding: 'utf8', timeout: 5000, windowsHide: true, maxBuffer: 65536, stdio: ['ignore', 'pipe', 'pipe'] }).trim();
        if (!/^(?:gh[ou]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)$/.test(token)) throw new Error();
        env.COPILOT_GITHUB_TOKEN = token;
      } catch { throw new Error('GITHUB_CLI_AUTH_UNAVAILABLE: authenticate the explicitly selected GitHub account'); }
    }
    this.child = spawn(launch?.executable ?? resolveCopilot(), launch?.args ?? ['--acp'], { cwd, env, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    this.abort = () => this.close();
    signal.addEventListener('abort', this.abort, { once: true });
    this.child.on('error', () => this.close());
    this.child.on('exit', () => this.close());
    this.child.stdin!.on('error', () => this.close());
    this.child.stderr!.on('data', () => {});
    this.child.stdout!.setEncoding('utf8');
    this.child.stdout!.on('data', (data: string) => {
      this.buffer += data;
      if (this.buffer.length > 1048576) return this.close();
      let end: number;
      while ((end = this.buffer.indexOf('\n')) >= 0) {
        const line = this.buffer.slice(0, end);
        this.buffer = this.buffer.slice(end + 1);
        if (!line.trim()) continue;
        try { this.receive(JSON.parse(line)); } catch { this.close(); }
      }
    });
  }

  receive(message: any): void {
    if (message.method && message.id !== undefined) {
      const reply = message.method === 'session/request_permission'
        ? { result: { outcome: { outcome: 'cancelled' } } }
        : { error: { code: -32601, message: 'Client tools unavailable' } };
      this.child.stdin!.write(JSON.stringify({ jsonrpc: '2.0', id: message.id, ...reply }) + '\n');
    } else if (message.method === 'session/update') {
      this.onUpdate(message.params);
    } else if (message.id !== undefined) {
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error('COPILOT_RPC_ERROR_' + String(message.error.code) + ': ' + redact(String(message.error.message)).slice(0, 500)));
      else pending.resolve(message.result);
    }
  }

  request(method: string, params: any): Promise<any> {
    if (this.closed) return Promise.reject(new Error('COPILOT_CONNECTION_CLOSED'));
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.child.stdin!.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    });
  }

  async open(cwd: string, threadId?: string | null): Promise<any> {
    const initialized = await this.request('initialize', { protocolVersion: 1, clientCapabilities: {} });
    if (threadId && !initialized.agentCapabilities?.loadSession) throw new Error('COPILOT_RESUME_UNSUPPORTED');
    return this.request(threadId ? 'session/load' : 'session/new', { ...(threadId ? { sessionId: threadId } : {}), cwd, mcpServers: [] });
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.signal.removeEventListener('abort', this.abort);
    for (const pending of this.pending.values()) pending.reject(new Error('COPILOT_CONNECTION_CLOSED'));
    this.pending.clear();
    this.child.stdin?.end();
    this.child.kill();
  }
}

export class CopilotEngine {
  async run(request: RunRequest, signal: AbortSignal, onEvent: (event: any) => void): Promise<unknown> {
    const connection = new CopilotConnection(request.cwd, signal);
    let text = '';
    try {
      const session = await connection.open(request.cwd, request.thread_id);
      const sessionId = request.thread_id ?? session.sessionId;
      if (!sessionId) throw new Error('COPILOT_MISSING_SESSION_ID');
      if (request.model) await connection.request('session/set_model', { sessionId, modelId: request.model });
      if (request.effort) throw new Error('COPILOT_ACP_EFFORT_UNSUPPORTED');
      onEvent({ type: 'thread.started', thread_id: sessionId });
      connection.onUpdate = params => {
        const update = params.update;
        if (update?.sessionUpdate === 'agent_message_chunk' && update.content?.type === 'text') {
          text += update.content.text;
          if (text.length > 262144) throw new Error('COPILOT_OUTPUT_LIMIT');
        }
        if (update?.sessionUpdate === 'tool_call') { connection.close(); throw new Error('COPILOT_TOOLS_NOT_AUTHORIZED'); }
      };
      const completed = await connection.request('session/prompt', { sessionId, prompt: [{ type: 'text', text: request.prompt + '\nReturn only a JSON object. No tools are authorized.' + (request.output_schema ? '\nRequired JSON schema: ' + JSON.stringify(request.output_schema) : '') }] });
      if (completed.stopReason !== 'end_turn' || signal.aborted) throw new Error('COPILOT_INCOMPLETE_TURN');
      const result = JSON.parse(text);
      if (request.output_schema && !matchesSchema(result, request.output_schema)) throw new Error('INVALID_SCHEMA_RESULT');
      onEvent({ type: 'turn.completed' });
      return result;
    } finally { connection.close(); }
  }
}
