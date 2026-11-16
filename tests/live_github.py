"""Opt-in integration test of a public GitHub file import, in disposable local state."""
import os
import sys
import tempfile
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
(root / 'data').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='open-agent-github-', dir=root / 'data') as tmp:
    os.environ['OPEN_AGENT_DATA'] = tmp
    from fastapi.testclient import TestClient
    from backend.main import app
    client = TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Open-Agent':'local'})
    url = 'https://github.com/git/git/blob/master/README.md'
    pending = client.post('/api/skills/import', json={'url': url}).json()
    destination = Path(pending['destination'])
    assert not destination.exists()
    client.post(f"/api/approvals/{pending['approval_id']}/decide", json={'approved':True}).raise_for_status()
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        status = client.get('/api/approvals').json()
        if not any(a['id'] == pending['approval_id'] for a in status): break
        time.sleep(.2)
    from backend import store
    approval = store.query('SELECT * FROM approvals WHERE id=?',(pending['approval_id'],),True)
    print('IMPORT', approval['status'], approval['result'], flush=True)
    assert approval['status'] == 'done'
    skill = client.get('/api/skills').json()[0]
    assert skill['enabled'] == 0 and (destination/'README.md').is_file()
    assert client.get(f"/api/skills/{skill['id']}/inspect").status_code == 200
    removal = client.delete(f"/api/skills/{skill['id']}").json()['approval_id']
    client.post(f'/api/approvals/{removal}/decide',json={'approved':True}).raise_for_status()
    while time.monotonic() < deadline:
        row = store.query('SELECT * FROM approvals WHERE id=?',(removal,),True)
        if row['status'] in ('done','failed'): break
        time.sleep(.2)
    print('REMOVAL', row['status'], row['result'], flush=True)
    assert row['status'] == 'done' and not destination.exists()
