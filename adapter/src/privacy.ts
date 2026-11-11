export function redact(text: string): string {
  return text
    .replace(/\b(?:sk|sess)-[A-Za-z0-9_-]{8,}\b/g, '[REDACTED]')
    .replace(/\bBearer\s+[^\s"']+/gi, 'Bearer [REDACTED]')
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, '[REDACTED]')
    .replace(/((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|authorization|cookie)\s*[=:]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)/gi, '$1[REDACTED]')
    .replace(/(https?:\/\/)[^\s/@]+:[^\s/@]+@/gi, '$1[REDACTED]@');
}

export function sanitize(value: unknown): unknown {
  if (typeof value === 'string') return redact(value);
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).filter(([key]) => !/reasoning|analysis|credential/i.test(key)).map(([key, child]) =>
      [key, /^(?:api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|token|password|secret|authorization|cookie)$/i.test(key) ? '[REDACTED]' : sanitize(child)]));
  }
  return value;
}

export function publicEvent(event: any): unknown | null {
  if (event.type?.startsWith('item.')) {
    const item = event.item;
    if (!item || item.type === 'reasoning') return null;
    if (item.type === 'command_execution') {
      return sanitize({ type: event.type, item: { id: item.id, type: item.type, command: item.command, status: item.status, exit_code: item.exit_code } });
    }
    if (item.type === 'file_change') return sanitize({ type: event.type, item });
    if (item.type === 'agent_message') return { type: event.type, item: { id: item.id, type: item.type } };
    if (item.type === 'error') return sanitize({ type: event.type, item: { id: item.id, type: item.type, message: item.message } });
    return { type: event.type, item: { id: item.id, type: item.type, status: item.status } };
  }
  if (event.type === 'thread.started' || event.type === 'turn.started' || event.type === 'turn.completed') return sanitize(event);
  if (event.type === 'error' || event.type === 'turn.failed') return sanitize({ type: event.type, error: event.error ?? event.message });
  return null;
}
