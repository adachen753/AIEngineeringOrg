import http from 'node:http';
import { pathToFileURL } from 'node:url';
import { ApiError, capabilities } from './policy.ts';
import { RunStore } from './store.ts';
import { RunService, response } from './service.ts';

export function createServer(service: RunService): http.Server {
  return http.createServer(async (request, reply) => {
    const send = (code: number, body: unknown) => {
      reply.writeHead(code, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
      reply.end(JSON.stringify(body));
    };
    try {
      const expected = `127.0.0.1:${reply.socket?.localPort}`;
      if (request.headers.host !== expected || request.headers.origin !== undefined || request.headers['sec-fetch-site'] === 'cross-site') throw new ApiError(403, 'Only same-host non-browser localhost requests permitted');
      const location = new URL(request.url ?? '/', `http://${expected}`);
      if (location.search) throw new ApiError(400, 'Query parameters unsupported');
      if (request.method === 'GET' && location.pathname === '/health') return send(200, capabilities);
      const match = /^\/runs\/([A-Za-z0-9_-]{1,128})(\/cancel)?$/.exec(location.pathname);
      if (match) {
        if (request.method === 'GET' && !match[2]) return send(200, response(service.get(match[1])));
        if (request.method === 'POST' && match[2]) return send(200, response(service.cancel(match[1])));
      }
      if (request.method !== 'POST' || location.pathname !== '/runs') throw new ApiError(404, 'Unknown endpoint');
      if (!/^application\/json(?:\s*;.*)?$/i.test(request.headers['content-type'] ?? '')) throw new ApiError(415, 'Content-Type application/json required');
      const chunks: Buffer[] = [];
      let size = 0;
      for await (const chunk of request) { size += chunk.length; if (size > 1048576) throw new ApiError(413, 'Request too large'); chunks.push(chunk); }
      let body: unknown;
      try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { throw new ApiError(400, 'Invalid JSON'); }
      const submitted = service.submit(body);
      return send(submitted.code, response(submitted.record));
    } catch (error) { send(error instanceof ApiError ? error.status : 500, { error: error instanceof ApiError ? error.message : 'Internal adapter error (details withheld)' }); }
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const service = new RunService(new RunStore());
  const server = createServer(service);
  server.requestTimeout = 15000;
  server.headersTimeout = 10000;
  const port = Number(process.env.PORT ?? '8766');
  if (!Number.isInteger(port) || port < 1 || port > 65535) { service.store.close(); throw new Error('PORT must be an integer in 1..65535'); }
  server.listen(port, '127.0.0.1', () => console.log(`Codex adapter listening at http://127.0.0.1:${port}; strict write scopes BLOCKED`));
  let stopping = false;
  const stop = async () => { if (stopping) return; stopping = true; server.close(); await service.shutdown(); server.closeAllConnections(); };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
  server.on('error', async () => { await service.shutdown(); process.exitCode = 1; });
}
