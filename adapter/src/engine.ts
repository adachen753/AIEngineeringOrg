import { Codex } from '@openai/codex-sdk';
import type { Thread, ThreadEvent } from '@openai/codex-sdk';
import { execFileSync } from 'node:child_process';
import { matchesSchema } from './request.ts';
import type { RunRequest } from './request.ts';
import { canonicalDirectory, within } from './policy.ts';
import path from 'node:path';

export function resolveCodex(): string {
  if (process.env.AIM_CODEX_EXE) return process.env.AIM_CODEX_EXE;
  const command = process.platform === 'win32' ? 'where.exe' : 'which';
  const executable = process.platform === 'win32' ? 'codex.exe' : 'codex';
  return execFileSync(command, [executable], { encoding: 'utf8', windowsHide: true }).trim().split(/\r?\n/)[0];
}

export class SdkEngine {
  codex: Codex;
  threads = new Map<string, Thread>();
  constructor(probe = false) {
    this.codex = new Codex({
      env: Object.fromEntries(Object.entries(process.env).filter(([key, value]) => value !== undefined && !['AIM_DESKTOP_BRIDGE_TOKEN', 'AIM_PROJECT_CONFIG', 'AIM_BRIDGE_CONFIG', 'COPILOT_GITHUB_TOKEN', 'GH_TOKEN', 'GITHUB_TOKEN'].includes(key))) as Record<string, string>,
      codexPathOverride: resolveCodex(),
      config: {
        approval_policy: 'never',
        sandbox_workspace_write: { network_access: false, exclude_tmpdir_env_var: true, exclude_slash_tmp: true, writable_roots: [] },
        web_search: 'disabled',
        ...(probe ? { project_doc_max_bytes: 0, developer_instructions: 'Connectivity diagnostic only. Return the requested JSON without calling tools or reading instructions.', features: { shell_tool: false, unified_exec: false, skill_search: false, skill_mcp_dependency_install: false, tool_suggest: false } } : {}),
      },
    });
  }

  async run(request: RunRequest, signal: AbortSignal, onEvent: (event: ThreadEvent) => void): Promise<unknown> {
    const readOnly = request.role === 'manager' || request.role === 'architect' || request.role === 'reviewer' || (request.role === 'test' && !request.allowed_paths?.length && !request.test_paths?.length);
    const roots = (request.role === 'test' ? request.test_paths ?? request.allowed_paths : request.allowed_paths)?.map(directory => canonicalDirectory(path.resolve(request.cwd, directory))) ?? [];
    if (roots.some(directory => !within(request.cwd, directory))) throw new Error('INVALID_SCOPE');
    const options = {
      ...(request.model ? { model: request.model } : {}),
      ...(request.effort ? { modelReasoningEffort: request.effort } : {}),
      workingDirectory: readOnly || !roots.length ? request.cwd : roots[0],
      sandboxMode: readOnly ? 'read-only' as const : 'workspace-write' as const,
      approvalPolicy: 'never' as const,
      networkAccessEnabled: false,
      webSearchMode: 'disabled' as const,
      additionalDirectories: request.role === 'dev' ? roots.slice(1) : [],
      skipGitRepoCheck: true,
    };
    const thread = request.thread_id ? this.threads.get(request.thread_id) ?? this.codex.resumeThread(request.thread_id, options) : this.codex.startThread(options);
    const turn = await thread.runStreamed(request.prompt, { signal, outputSchema: request.output_schema });
    let finalText = '';
    let completed = false;
    for await (const event of turn.events) {
      if (event.type === 'thread.started') this.threads.set(event.thread_id, thread);
      onEvent(event);
      if (event.type === 'item.completed' && event.item.type === 'agent_message') finalText = event.item.text;
      if (event.type === 'turn.completed') completed = true;
      if (event.type === 'turn.failed' || event.type === 'error') throw new Error('SDK_TURN_FAILED');
    }
    if (!completed || signal.aborted) throw new Error('INCOMPLETE_TURN');
    let parsed: unknown;
    try { parsed = JSON.parse(finalText); } catch { throw new Error('INVALID_JSON_RESULT'); }
    if (request.output_schema && !matchesSchema(parsed, request.output_schema)) throw new Error('INVALID_SCHEMA_RESULT');
    return parsed;
  }
}
