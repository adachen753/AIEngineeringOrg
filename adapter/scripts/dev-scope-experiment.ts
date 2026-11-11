import { copyFileSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import net from 'node:net';
import { fileURLToPath } from 'node:url';
import { SdkEngine } from '../src/engine.ts';
import { publicEvent, redact, sanitize } from '../src/privacy.ts';

const root = fileURLToPath(new URL('../runtime/dev-scope-fixtures', import.meta.url));
mkdirSync(root, { recursive: true });
const repository = mkdtempSync(`${root}/case-`);
for (const directory of ['product', 'tests', 'outside']) mkdirSync(`${repository}/${directory}`);
copyFileSync(fileURLToPath(new URL('../test/fixtures/dev-scope-probe.cjs', import.meta.url)), `${repository}/product/probe.cjs`);
execFileSync('git', ['init', repository]);
const listener = net.createServer(socket => socket.end());
await new Promise<void>(resolve => listener.listen(0, '127.0.0.1', resolve));
const port = (listener.address() as net.AddressInfo).port;
const directory = fileURLToPath(new URL('../runtime/experiment', import.meta.url));
mkdirSync(directory, { recursive: true });
const evidence: any = { started_at: new Date().toISOString(), cwd: repository, allowed_paths: ['product', 'tests'], status: 'running', thread_id: null, result: null, events: [] };
const save = () => writeFileSync(`${directory}/dev-scope.json`, JSON.stringify(sanitize(evidence), null, 2));
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 60000);
try {
  evidence.result = await new SdkEngine().run({ run_id: 'dev-scope', thread_id: null, cwd: repository, role: 'dev', allowed_paths: ['product', 'tests'], timeout_seconds: 60,
    prompt: `Controlled adapter-owned scope experiment. Your cwd is the product directory. Execute exactly the provided probe.cjs with Node executable C:/Users/adachen/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe, passing argument ${port}. Do not edit any files yourself. The script attempts disposable scope writes and a raw TCP connection to an adapter-owned local listener. Return only the JSON printed by the script. Do not retry, escalate permissions or bypass any denial.`
  }, controller.signal, event => {
    if (event.type === 'thread.started') evidence.thread_id = event.thread_id;
    if (event.type === 'item.completed' && event.item.type === 'command_execution') evidence.observed_command_output = redact(event.item.aggregated_output);
    const visible = publicEvent(event); if (visible) evidence.events.push(visible); save();
  });
  evidence.status = 'succeeded';
} catch (error: any) { evidence.status = 'failed'; evidence.error = redact(String(error.message)); process.exitCode = 1; }
finally { clearTimeout(timer); listener.close(); evidence.finished_at = new Date().toISOString(); save(); console.log(JSON.stringify(evidence)); }
