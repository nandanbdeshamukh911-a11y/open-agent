"""Opt-in, isolated smoke test using the real local model. Never approves shell commands."""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
(ROOT / 'data').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='open-agent-live-', dir=ROOT / 'data') as tmp:
    base = Path(tmp)
    os.environ['OPEN_AGENT_DATA'] = str(base / 'state')
    project = base / 'project'
    project.mkdir()
    from fastapi.testclient import TestClient
    from backend.main import app
    client = TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Open-Agent': 'local'})
    request = ('Create hello.txt containing exactly the text Hello from Open Agent. '
               'Read the file back to verify it. Do not run terminal commands or download anything.')
    response = client.post('/api/tasks', json={'request': request, 'project': str(project)})
    response.raise_for_status()
    task_id = response.json()['id']
    seen = set()
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        task = client.get(f'/api/tasks/{task_id}').json()
        for event in task['events']:
            if event['id'] not in seen:
                print(event['kind'], event['content'][:1500], flush=True)
                seen.add(event['id'])
        if task['status'] == 'waiting_approval':
            approval = next(a for a in task['approvals'] if a['status'] == 'pending')
            import json
            args = json.loads(approval['args'])
            safe = (approval['action'] == 'write_file' and args.get('path') == 'hello.txt'
                    and args.get('content') == 'Hello from Open Agent')
            print('APPROVAL', approval['action'], args, 'accepted' if safe else 'rejected', flush=True)
            client.post(f"/api/approvals/{approval['id']}/decide", json={'approved': safe}).raise_for_status()
        elif task['status'] in ('completed', 'blocked', 'cancelled', 'paused'):
            print('FINAL', task['status'], task['final'], flush=True)
            actual = (project / 'hello.txt').read_text(encoding='utf-8') if (project / 'hello.txt').exists() else None
            print('FILE', repr(actual), flush=True)
            if task['status'] != 'completed' or actual != 'Hello from Open Agent':
                raise SystemExit(1)
            break
        time.sleep(2)
    else:
        raise SystemExit('Timed out waiting for the local model task.')
    from backend import agent
    while task_id in agent.workers:
        time.sleep(.05)
