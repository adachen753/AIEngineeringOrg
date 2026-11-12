"""Synthetic integration exercise; not GraphConnectors, SF, UI, SQL or live-agent acceptance."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from ai_manager.engine import Engine
from ai_manager.git import git
from ai_manager.models import FeatureRequest, Settings
from ai_manager.role_config import role_prompt
from ai_manager.store import Store


BUILD = """
from pathlib import Path
import sys
text = Path('app/feature.txt').read_text()
if text == 'ENVIRONMENT':
    print('error MSB3644: SDK not found; synthetic environment failure')
    sys.exit(1)
if text == 'BROKEN':
    print('error CS1002: synthetic compiler failure')
    sys.exit(1)
Path('target').mkdir(exist_ok=True)
Path('target/package.txt').write_text(text)
print('Synthetic build completed')
"""
DRIVER = """
import json, os
from pathlib import Path
job = json.loads(Path(os.environ['AIM_BRIDGE_REQUEST_FILE']).read_text())
if job['stage'] == 'deploy':
    result = {'healthy': True, 'evidence': ['SIMULATED dedicated deployment; no SF touched']}
else:
    passed = Path(job['cwd'], 'target/package.txt').read_text() == 'FIXED'
    result = {'driver': 'computer-use', 'checks': [
        {'id': name, 'passed': passed, 'evidence': ['SIMULATED UI/SQL observation; no real desktop touched']}
        for name in job['checks']], 'acceptance_mapping': [
        {'criterion': criterion, 'check_ids': job['checks']} for criterion in job['acceptance']]}
Path(os.environ['AIM_BRIDGE_RESULT_FILE']).write_text(json.dumps(result))
"""


async def exercise(root, port):
    repo = root / 'repo'
    repo.mkdir()
    git(repo, 'init')
    (repo / 'app').mkdir()
    (repo / 'app/feature.txt').write_text('BASE')
    git(repo, 'add', 'app/feature.txt')
    git(repo, '-c', 'user.name=Smoke', '-c', 'user.email=smoke@localhost', 'commit', '-m', 'Fixture')
    profile = {'enabled': True, 'repo': str(repo), 'allowed_paths': ['app'], 'acceptance': ['Synthetic feature behaves correctly'],
        'build_executable': sys.executable, 'build_arguments': ['-c', BUILD], 'build_output_paths': ['target'],
        'build_timeout_seconds': 30, 'bridge_url': f'http://127.0.0.1:{port}', 'resource_id': 'synthetic-only',
        'deployment_recipe': 'synthetic', 'scenario': 'synthetic', 'checks': ['synthetic-ui', 'synthetic-db']}
    config = root / 'projects.json'
    config.write_text(json.dumps({'version': 1, 'projects': {'smoke': profile}}))
    os.environ['AIM_PROJECT_CONFIG'] = str(config)
    store = Store(root / 'data')
    engine = Engine(store, Settings(data_dir=root / 'data'))
    await engine.client.aclose()
    engine.client = httpx.AsyncClient(base_url='http://adapter.invalid', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={'ready': True})))
    roles = []

    async def fixture_agent(record, role, cwd, prompt):
        role_prompt(record, role, prompt)
        roles.append(role)
        if role == 'dev':
            value = 'BROKEN' if record['repair_count'] == 0 else 'OK' if record['repair_count'] == 1 else 'FIXED'
            if record['submission']['feature'] == 'environment fixture':
                value = 'ENVIRONMENT'
            (cwd / 'app/feature.txt').write_text(value)
        classification = 'none'
        if role == 'test' and record['stage'] == 'assess' and record['delivery_e2e']['status'] == 'failed':
            classification = 'product_bug'
        from ai_manager.models import AgentResult
        result = AgentResult(status='ready', summary='SYNTHETIC role response', acceptance=profile['acceptance'],
            questions=[], evidence=['SYNTHETIC fixture evidence, not live verification'], classification=classification)
        record['results'][role] = result.model_dump()
        engine.checkpoint(record)
        return result

    engine.agent = fixture_agent
    try:
        request = FeatureRequest(project='smoke', feature='Synthetic feature', idempotency_key='smoke',
                                 authorized=True, deploy_authorized=True)
        record = store.submit_feature(request)
        for _ in range(40):
            await engine.graph.ainvoke({'workflow_id': record['id']})
            record = store.get(record['id'])
            if record['status'] != 'queued':
                break
        if record['status'] != 'succeeded' or record['repair_count'] != 2 or set(roles) != {'manager', 'architect', 'dev', 'test'}:
            raise RuntimeError(json.dumps({'status': record['status'], 'reason': record['reason'], 'stage': record['stage'], 'roles': roles}))
        if store.submit_feature(request)['id'] != record['id']:
            raise RuntimeError('Feature idempotency failed')
        limited = store.submit_feature(request.model_copy(update={'idempotency_key': 'zero-repairs', 'max_fix_rounds': 0}))
        for _ in range(8):
            await engine.graph.ainvoke({'workflow_id': limited['id']})
            limited = store.get(limited['id'])
            if limited['status'] != 'queued':
                break
        if limited['status'] != 'blocked' or limited['repair_count'] != 0 or 'repair limit' not in limited['reason']:
            raise RuntimeError('Configured zero repair limit was not enforced: ' + str(limited['reason']))
        environment = store.submit_feature(request.model_copy(update={'idempotency_key': 'environment', 'feature': 'environment fixture'}))
        for _ in range(8):
            await engine.graph.ainvoke({'workflow_id': environment['id']})
            environment = store.get(environment['id'])
            if environment['status'] != 'queued':
                break
        if environment['status'] != 'blocked' or environment['repair_count'] != 0 or 'environment' not in environment['reason']:
            raise RuntimeError('Environment failure incorrectly entered repair loop')
        expired = store.submit_feature(request.model_copy(update={'idempotency_key': 'expired'}))
        expired['delivery_started_at'] = '2000-01-01T00:00:00+00:00'
        store.save(expired)
        await engine.graph.ainvoke({'workflow_id': expired['id']})
        expired = store.get(expired['id'])
        if expired['status'] != 'blocked' or 'time limit' not in expired['reason']:
            raise RuntimeError('Persisted total time limit was not enforced')
        async with httpx.AsyncClient(trust_env=False) as client:
            unauthorized = await client.get(f'http://127.0.0.1:{port}/health')
            if unauthorized.status_code != 403:
                raise RuntimeError('Desktop bridge accepted an unauthenticated caller')
        print(json.dumps({'status': 'passed', 'scope': 'SYNTHETIC integration only; not live Agent/SF/Computer-use/SQL',
            'real_operations': ['Git worktrees/commits', 'build subprocess', 'authenticated HTTP bridge', 'approved driver subprocess'],
            'repair_rounds': record['repair_count'], 'default_max_fix_rounds': request.max_fix_rounds,
            'zero_repair_limit': limited['status'], 'unit_tests_written_or_run_by_delivery': False}))
    finally:
        await engine.client.aclose()
        store.db.close()


def main():
    with tempfile.TemporaryDirectory(prefix='aim-delivery-smoke-') as directory:
        root = Path(directory)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        os.environ['AIM_DESKTOP_BRIDGE_TOKEN'] = 'synthetic-smoke-token-not-a-real-secret-12345'
        bridge_config = root / 'bridge.json'
        bridge_config.write_text(json.dumps({'version': 1, 'enabled': True, 'data_dir': str(root / 'bridge-state'),
            'artifact_root': str(root / 'data/worktrees'), 'resources': {'synthetic-only': {'recipe': 'synthetic',
                'scenario': 'synthetic', 'checks': ['synthetic-ui', 'synthetic-db'],
                'deploy_command': [sys.executable, '-c', DRIVER], 'e2e_command': [sys.executable, '-c', DRIVER]}}}))
        os.environ['AIM_BRIDGE_CONFIG'] = str(bridge_config)
        with (root / 'server.log').open('w') as log:
            process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'ai_manager.desktop_bridge:app',
                '--host', '127.0.0.1', '--port', str(port)], stdout=log, stderr=log,
                creationflags=0x08000000 if os.name == 'nt' else 0)
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError((root / 'server.log').read_text())
                    try:
                        response = httpx.get(f'http://127.0.0.1:{port}/health',
                            headers={'Authorization': 'Bearer ' + os.environ['AIM_DESKTOP_BRIDGE_TOKEN']}, timeout=1)
                        if response.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError('Synthetic desktop bridge startup timed out')
                asyncio.run(exercise(root, port))
            finally:
                process.terminate()
                try:
                    process.wait(10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    main()
