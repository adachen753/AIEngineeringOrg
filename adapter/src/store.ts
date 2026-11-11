import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, readdirSync, realpathSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { canonicalDirectory, protectedPath, within } from './policy.ts';
import { sanitize } from './privacy.ts';

export type RunRecord = {
  run_id: string;
  status: 'running' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted';
  thread_id: string | null;
  result: unknown;
  events: unknown[];
  error?: string;
  fingerprint: string;
  binding: string;
};

export class RunStore {
  directory: string;
  records = new Map<string, RunRecord>();
  lock: number;
  constructor(directory = process.env.AIM_ADAPTER_DATA ?? fileURLToPath(new URL('../runtime', import.meta.url))) {
    const absolute = path.resolve(directory);
    if (protectedPath(absolute)) throw new Error('Protected data directory');
    let ancestor = absolute;
    while (!existsSync(ancestor)) ancestor = path.dirname(ancestor);
    const physicalAncestor = canonicalDirectory(ancestor);
    if (protectedPath(path.resolve(physicalAncestor, path.relative(ancestor, absolute)))) throw new Error('Protected data directory');
    mkdirSync(absolute, { recursive: true, mode: 0o700 });
    this.directory = canonicalDirectory(absolute);
    const lockPath = path.join(this.directory, '.exclusive.lock');
    if (existsSync(lockPath)) {
      const owner = JSON.parse(readFileSync(lockPath, 'utf8'));
      if (!Number.isInteger(owner.pid) || owner.pid <= 0) throw new Error('Invalid owner lock; operator intervention required');
      try { process.kill(owner.pid, 0); throw new Error('Adapter data already owned by a live process'); }
      catch (error: any) {
        if (error.code !== 'ESRCH') throw error;
        throw new Error('Stale adapter owner lock: verify its PID is dead and remove only .exclusive.lock before restarting; do not replay runs');
      }
    }
    this.lock = openSync(lockPath, 'wx', 0o600);
    writeFileSync(this.lock, JSON.stringify({ pid: process.pid }));
    try {
      for (const filename of readdirSync(this.directory)) {
        if (!/^[A-Za-z0-9_-]{1,128}\.json$/.test(filename)) continue;
        const location = path.join(this.directory, filename);
        if (!within(this.directory, realpathSync.native(location))) throw new Error('Run file escapes data directory');
        const record = JSON.parse(readFileSync(location, 'utf8')) as RunRecord;
        if (`${record.run_id}.json` !== filename || !record.fingerprint || !record.binding || !Array.isArray(record.events) || !['running', 'succeeded', 'failed', 'cancelled', 'interrupted'].includes(record.status)) throw new Error('Corrupt run record');
        this.records.set(record.run_id, record);
        if (record.status === 'running') {
          record.status = 'interrupted';
          record.result = null;
          record.error = 'ADAPTER_RESTART: prior delivery may have executed; do not automatically replay';
          this.save(record);
        }
      }
    } catch (error) {
      this.close();
      throw error;
    }
  }

  save(record: RunRecord): void {
    const destination = path.join(this.directory, `${record.run_id}.json`);
    if (!within(this.directory, destination)) throw new Error('Invalid record path');
    const temporary = `${destination}.${randomUUID()}.tmp`;
    const descriptor = openSync(temporary, 'wx', 0o600);
    try {
      writeFileSync(descriptor, JSON.stringify(sanitize(record)));
      fsyncSync(descriptor);
    } finally { closeSync(descriptor); }
    renameSync(temporary, destination);
    this.records.set(record.run_id, record);
  }

  close(): void {
    closeSync(this.lock);
    unlinkSync(path.join(this.directory, '.exclusive.lock'));
  }
}
