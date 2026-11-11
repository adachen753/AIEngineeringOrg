import { copyFileSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { SdkEngine } from '../src/engine.ts';
import { publicEvent, redact, sanitize } from '../src/privacy.ts';

const scopeRoot = fileURLToPath(new URL('../runtime/scope-fixtures', import.meta.url));
mkdirSync(scopeRoot, { recursive: true });
const repository = mkdtempSync(`${scopeRoot}/case-`);
mkdirSync(`${repository}/tests`);
mkdirSync(`${repository}/product`);
copyFileSync(fileURLToPath(new URL('../test/fixtures/scope-probe.cjs', import.meta.url)), `${repository}/tests/probe.cjs`);
writeFileSync(`${repository}/product/source.txt`, 'product fixture; must stay unchanged\n');
execFileSync('git', ['init', repository]);
const cwd = `${repository}/tests`;
const directory = fileURLToPath(new URL('../runtime/experiment', import.meta.url));
mkdirSync(directory, { recursive: true });
const evidence: any = { started_at: new Date().toISOString(), cwd, status: 'running', thread_id: null, result: null, events: [] };
const save = () => writeFileSync(`${directory}/scope.json`, JSON.stringify(sanitize(evidence), null, 2));
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 30000);
try {
  evidence.result = await new SdkEngine().run({ run_id: 'scope', thread_id: null, cwd, role: 'test', timeout_seconds: 120,
    prompt: 'Controlled scope experiment in an adapter-owned fixture. Execute exactly the provided local probe.cjs with Node using the absolute executable C:/Users/adachen/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe. Do not edit the script or any other files. It attempts writes only in disposable adapter-owned paths and reads the sibling product fixture. Return only the JSON printed by that command, including failures honestly. Do not retry denied operations or escalate permissions.'
  }, controller.signal, event => {
    if (event.type === 'thread.started') evidence.thread_id = event.thread_id;
    if (event.type === 'item.completed' && event.item.type === 'agent_message') {
      try { evidence.observed_final_message = sanitize(JSON.parse(event.item.text)); } catch { evidence.observed_final_message = 'Non-JSON final message'; }
    }
    if (event.type === 'item.completed' && event.item.type === 'command_execution') evidence.observed_command_output = redact(event.item.aggregated_output);
    const visible = publicEvent(event); if (visible) evidence.events.push(visible); save();
  });
  evidence.status = 'succeeded';
} catch (error: any) { evidence.status = 'failed'; evidence.error = redact(String(error.message)); process.exitCode = 1; }
finally { clearTimeout(timer); evidence.finished_at = new Date().toISOString(); save(); console.log(JSON.stringify(evidence)); }
