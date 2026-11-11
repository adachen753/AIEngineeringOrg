import { mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { SdkEngine } from '../src/engine.ts';
import { publicEvent, redact, sanitize } from '../src/privacy.ts';

const directory = fileURLToPath(new URL('../runtime/experiment', import.meta.url));
mkdirSync(directory, { recursive: true });
const evidence: any = { started_at: new Date().toISOString(), status: 'running', thread_id: null, result: null, events: [], abort_requested: false };
const save = () => writeFileSync(`${directory}/cancel.json`, JSON.stringify(sanitize(evidence), null, 2));
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 30000);
try {
  evidence.result = await new SdkEngine().run({ run_id: 'cancel', thread_id: null, cwd: directory, role: 'manager', timeout_seconds: 30,
    prompt: 'Read-only SDK cancellation experiment. Do not invoke tools, execute commands, read or write files. Return only JSON {"ok":true}.'
  }, controller.signal, event => {
    if (event.type === 'thread.started') { evidence.thread_id = event.thread_id; evidence.abort_requested = true; controller.abort(); }
    const visible = publicEvent(event); if (visible) evidence.events.push(visible); save();
  });
  evidence.status = 'succeeded-before-abort';
} catch (error: any) { evidence.status = 'aborted'; evidence.error = redact(String(error.message)); evidence.error_code = error.code ?? null; }
finally { clearTimeout(timer); evidence.finished_at = new Date().toISOString(); save(); console.log(JSON.stringify(evidence)); }
