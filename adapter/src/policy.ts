import { realpathSync, statSync } from 'node:fs';
import path from 'node:path';

export const capabilities = Object.freeze({
  ready: false,
  blocked: true,
  status: 'blocked',
  sdk_version: '0.153.4',
  transport: 'typescript-sdk',
  start_thread: true,
  resume_thread: true,
  stream_events: true,
  abort_signal: true,
  requested_approvals: 'never',
  requested_network: 'disabled',
  command_network_enforced: false,
  directory_write_boundary_probe: 'passed-for-test-and-dev-fixtures',
  strict_write_scopes: false,
  roles: { manager: 'blocked', dev: 'blocked', test: 'blocked' },
  blocker: 'NETWORK_SANDBOX_NOT_ENFORCED: real Windows SDK Dev probe connected over raw TCP to an adapter-owned localhost listener despite networkAccessEnabled=false and sandbox_workspace_write.network_access=false. Test/Dev directory writes were bounded in fixtures, but localhost backend access can bypass those boundaries. All production dispatch remains fail-closed.',
});

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function protectedPath(candidate: string): boolean {
  const normalized = candidate.replaceAll('\\', '/').toLowerCase();
  return normalized === 'q:/graphconnectors/cwzclaude' || normalized.startsWith('q:/graphconnectors/cwzclaude/') ||
    normalized === 'q:/graphconnectors/sources/dev/cwzclaude-sql' || normalized.startsWith('q:/graphconnectors/sources/dev/cwzclaude-sql/');
}

export function canonicalDirectory(candidate: unknown): string {
  if (typeof candidate !== 'string' || !path.isAbsolute(candidate) || candidate.includes('\0')) {
    throw new ApiError(400, 'cwd must be an absolute existing directory');
  }
  if (protectedPath(candidate)) throw new ApiError(403, 'Protected directory');
  try {
    const resolved = realpathSync.native(candidate);
    if (protectedPath(resolved)) throw new ApiError(403, 'Protected directory');
    if (!statSync(resolved).isDirectory()) throw new Error();
    return resolved;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(400, 'cwd must be an absolute existing directory');
  }
}

export function within(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
}

export function requireEnforcedScope(): void {
  throw new ApiError(503, capabilities.blocker);
}
