"""Exercise the design workflow against the installed Ornith model in an isolated project."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
(ROOT / 'data').mkdir(exist_ok=True)
run = Path(tempfile.mkdtemp(prefix='design-live-', dir=ROOT / 'data'))
os.environ['OPEN_AGENT_DATA'] = str(run / 'state')
project = run / 'website'
project.mkdir()

from fastapi.testclient import TestClient
from backend.main import app

with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Open-Agent':'local'}) as client:
    client.put('/api/settings', json={'model_url':'http://127.0.0.1:11434/v1','model_name':'ornith-1.5:9b'}).raise_for_status()
    request = ('Build a new single-file editorial website for Echo Hall. Use design_page for index.html '
               'with the headline "Sunday listening" and two weekend sessions. Use the forest palette. '
               'Verify the mobile layout using browser_project and browser_layout, then report the result.')
    response = client.post('/api/tasks', json={'project':str(project), 'request':request})
    response.raise_for_status()
    task_id = response.json()['id']
    seen = set()
    deadline = time.monotonic() + 1200
    print('Project:', project, flush=True)
    while time.monotonic() < deadline:
        task = client.get(f'/api/tasks/{task_id}').json()
        for event in task['events']:
            if event['id'] in seen:
                continue
            seen.add(event['id'])
            if event['kind'] == 'tool':
                tool = json.loads(event['content'])
                print(tool['action'], str(tool['result'])[:200], flush=True)
            else:
                print(event['kind'], event['content'][:400], flush=True)
        if task['status'] == 'waiting_approval':
            approval = next((a for a in task['approvals'] if a['status'] == 'pending'), None)
            if approval is None:  # The approved action is still executing.
                time.sleep(.2)
                continue
            args = json.loads(approval['args'])
            allowed = approval['action'] in ('design_page','browser_project') and args.get('path') == 'index.html'
            client.post(f"/api/approvals/{approval['id']}/decide", json={'approved':allowed}).raise_for_status()
        elif task['status'] in ('blocked','completed','paused','cancelled'):
            if task['status'] != 'completed':
                raise SystemExit(f"{task['status']}: {task['final']}")
            output = (project / 'index.html').read_text(encoding='utf-8')
            assert '<h1 id="headline">Sunday listening</h1>' in output and output.count('<details>') == 2
            assert 'Echo Hall' in output and '--ink:#205141' in output
            events = [json.loads(e['content']) for e in task['events'] if e['kind'] == 'tool']
            assert any(e['action'] == 'browser_layout' and '390 x 844: 0px' in e['result'] for e in events)
            break
        time.sleep(1)
    else:
        client.post(f'/api/tasks/{task_id}/cancel').raise_for_status()
        raise SystemExit('Design task exceeded the live test deadline.')
