import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { SdkEngine } from '../src/engine.ts';
import { publicEvent, redact, sanitize } from '../src/privacy.ts';

const directory = fileURLToPath(new URL('../runtime/experiment', import.meta.url));
mkdirSync(directory, { recursive: true });
const phase = process.argv[2] ?? 'start';
const threadId = process.argv[3] ?? null;
let evidence: any = { phase, started_at: new Date().toISOString(), thread_id: threadId, status: 'running', result: null, events: [] };
let destination = path.join(directory, `${phase}.json`);
const engine = new SdkEngine();
const save = () => writeFileSync(destination, JSON.stringify(sanitize(evidence), null, 2));
save();
const prompt = phase === 'start'
  ? 'Read-only SDK connectivity experiment. Do not invoke any tools, read files, write files, or run commands. Remember the conversation marker AIMSDK-ORCHID-731. Return only JSON {"marker":"AIMSDK-ORCHID-731","phase":"start"}.'
  : `Read-only SDK connectivity experiment. Do not invoke tools, read files, write files, or run commands. Return only JSON with keys marker and phase. marker must be the conversation marker from my initial turn; phase must be "${phase}". Do not invent a marker if unavailable.`;
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 120000);
try {
  evidence.result = await engine.run({ run_id: phase, thread_id: threadId, prompt, cwd: directory, role: 'manager', timeout_seconds: 120 }, controller.signal, event => {
    if (event.type === 'thread.started') evidence.thread_id = event.thread_id;
    const visible = publicEvent(event);
    if (visible) evidence.events.push(visible);
    save();
  });
  evidence.status = 'succeeded';
} catch (error: any) {
  evidence.status = 'failed';
  evidence.error = redact(String(error.message));
  process.exitCode = 1;
} finally {
  clearTimeout(timer);
  evidence.finished_at = new Date().toISOString();
  save();
  console.log(JSON.stringify(evidence));
}
if (phase === 'start' && evidence.status === 'succeeded') {
  evidence = { phase: 'continue', started_at: new Date().toISOString(), thread_id: evidence.thread_id, status: 'running', result: null, events: [], same_engine_instance: true };
  destination = path.join(directory, 'continue.json');
  const continued = new AbortController();
  const continuationTimer = setTimeout(() => continued.abort(), 120000);
  try {
    evidence.result = await engine.run({ run_id: 'continue', thread_id: evidence.thread_id, cwd: directory, role: 'manager', timeout_seconds: 120,
      prompt: 'Read-only connectivity experiment. Do not invoke tools, read/write files, or run commands. Return only JSON with marker from my initial turn and phase "continue". Do not invent a marker.'
    }, continued.signal, event => { const visible = publicEvent(event); if (visible) evidence.events.push(visible); save(); });
    evidence.status = 'succeeded';
  } catch { evidence.status = 'failed'; evidence.error = 'Real SDK continuation failed'; process.exitCode = 1; }
  finally { clearTimeout(continuationTimer); evidence.finished_at = new Date().toISOString(); save(); console.log(JSON.stringify(evidence)); }
}
