import { createHash } from 'node:crypto';
import path from 'node:path';
import { ApiError, canonicalDirectory, protectedPath, within } from './policy.ts';

export type RunRequest = {
  run_id: string;
  thread_id: string | null;
  prompt: string;
  cwd: string;
  role: 'manager' | 'dev' | 'test';
  timeout_seconds: number;
  output_schema?: Record<string, unknown>;
  allowed_paths?: string[];
  test_paths?: string[];
};

export const runIdPattern = /^[A-Za-z0-9_-]{1,128}$/;
const threadIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function validateRequest(input: any): RunRequest {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new ApiError(400, 'Expected JSON object');
  const keys = ['run_id', 'thread_id', 'prompt', 'cwd', 'role', 'timeout_seconds', 'output_schema', 'allowed_paths', 'test_paths'];
  if (Object.keys(input).some(key => !keys.includes(key))) throw new ApiError(400, 'Unknown request field');
  if (typeof input.run_id !== 'string' || !runIdPattern.test(input.run_id)) throw new ApiError(400, 'Invalid run_id');
  if (input.thread_id !== null && (typeof input.thread_id !== 'string' || !threadIdPattern.test(input.thread_id))) throw new ApiError(400, 'Invalid thread_id');
  if (typeof input.prompt !== 'string' || !input.prompt.trim() || input.prompt.length > 100000) throw new ApiError(400, 'Invalid prompt');
  if (!['manager', 'dev', 'test'].includes(input.role)) throw new ApiError(400, 'Invalid role');
  if (!Number.isFinite(input.timeout_seconds) || input.timeout_seconds < 1 || input.timeout_seconds > 3600) throw new ApiError(400, 'timeout_seconds must be 1..3600');
  const cwd = canonicalDirectory(input.cwd);
  for (const key of ['allowed_paths', 'test_paths']) {
    if (input[key] === undefined) continue;
    if (!Array.isArray(input[key]) || input[key].length > 128 || input[key].some((entry: unknown) => typeof entry !== 'string' || !entry || /[\0*?]/.test(entry))) throw new ApiError(400, `Invalid ${key}`);
    for (const entry of input[key]) {
      const resolved = path.resolve(cwd, entry);
      if (!within(cwd, resolved) || protectedPath(resolved)) throw new ApiError(403, 'Write scope must remain inside cwd');
    }
  }
  if (input.role === 'manager' && (input.allowed_paths?.length || input.test_paths?.length)) throw new ApiError(400, 'Manager has no writable paths');
  if (input.output_schema !== undefined) validateSchema(input.output_schema);
  return { ...input, cwd };
}

const schemaKeys = new Set(['type', 'properties', 'required', 'additionalProperties', 'items', 'enum', 'description']);

export function validateSchema(schema: any, depth = 0): void {
  if (depth > 20 || !schema || typeof schema !== 'object' || Array.isArray(schema) || Object.keys(schema).some(key => !schemaKeys.has(key))) throw new ApiError(400, 'Unsupported output_schema; only type/properties/required/additionalProperties/items/enum/description supported');
  const types = Array.isArray(schema.type) ? schema.type : [schema.type];
  if (!types.length || types.some((type: string) => !['object', 'array', 'string', 'number', 'integer', 'boolean', 'null'].includes(type))) throw new ApiError(400, 'Schema requires supported type');
  if (schema.description !== undefined && typeof schema.description !== 'string') throw new ApiError(400, 'Invalid schema description');
  if (schema.enum !== undefined && (!Array.isArray(schema.enum) || !schema.enum.length)) throw new ApiError(400, 'Invalid enum');
  if (schema.additionalProperties !== undefined && typeof schema.additionalProperties !== 'boolean') throw new ApiError(400, 'additionalProperties must be boolean');
  if (schema.properties !== undefined) {
    if (!schema.properties || typeof schema.properties !== 'object' || Array.isArray(schema.properties)) throw new ApiError(400, 'Invalid properties');
    for (const child of Object.values(schema.properties)) validateSchema(child, depth + 1);
  }
  if (schema.required !== undefined && (!Array.isArray(schema.required) || schema.required.some((key: unknown) => typeof key !== 'string' || !Object.hasOwn(schema.properties ?? {}, key as string)))) throw new ApiError(400, 'Invalid required properties');
  if (schema.items !== undefined) validateSchema(schema.items, depth + 1);
}

export function matchesSchema(value: any, schema: any): boolean {
  const actual = value === null ? 'null' : Array.isArray(value) ? 'array' : typeof value;
  const types = Array.isArray(schema.type) ? schema.type : [schema.type];
  if (!types.some((type: string) => type === actual || (type === 'integer' && typeof value === 'number' && Number.isInteger(value)))) return false;
  if (schema.enum && !schema.enum.some((entry: unknown) => JSON.stringify(entry) === JSON.stringify(value))) return false;
  if (actual === 'object') {
    if ((schema.required ?? []).some((key: string) => !Object.hasOwn(value, key))) return false;
    if (schema.additionalProperties === false && Object.keys(value).some(key => !Object.hasOwn(schema.properties ?? {}, key))) return false;
    for (const [key, child] of Object.entries(schema.properties ?? {})) if (Object.hasOwn(value, key) && !matchesSchema(value[key], child)) return false;
  }
  if (actual === 'array' && schema.items && !value.every((child: unknown) => matchesSchema(child, schema.items))) return false;
  return true;
}

function stable(value: any): any {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])]));
  return value;
}

export function digest(value: unknown): string {
  return createHash('sha256').update(JSON.stringify(stable(value))).digest('hex');
}
