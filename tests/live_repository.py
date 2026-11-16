"""Opt-in public GitHub repository import test in disposable local state."""
import os
import sys
import tempfile
import time
from pathlib import Path

root=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(root))
(root/'data').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='open-agent-repo-',dir=root/'data') as tmp:
    os.environ['OPEN_AGENT_DATA']=tmp
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend import store
    client=TestClient(app,base_url='http://127.0.0.1:8765',headers={'X-Open-Agent':'local'})
    result=client.post('/api/skills/import',json={'url':'https://github.com/octocat/Hello-World'}).json()
    target=Path(result['destination']); assert not target.exists()
    aid=result['approval_id']; client.post(f'/api/approvals/{aid}/decide',json={'approved':True}).raise_for_status()
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        row=store.query('SELECT * FROM approvals WHERE id=?',(aid,),True)
        if row['status'] in ('done','failed'): break
        time.sleep(.25)
    print('REPOSITORY IMPORT',row['status'],row['result'],flush=True)
    assert row['status']=='done' and target.is_dir()
    skill=client.get('/api/skills').json()[0]
    assert len(skill['version'])==40 and skill['enabled']==0
    inspect=client.get(f"/api/skills/{skill['id']}/inspect").json(); assert inspect['files']
    aid=client.delete(f"/api/skills/{skill['id']}").json()['approval_id']
    client.post(f'/api/approvals/{aid}/decide',json={'approved':True}).raise_for_status()
    while time.monotonic()<deadline:
        row=store.query('SELECT * FROM approvals WHERE id=?',(aid,),True)
        if row['status'] in ('done','failed'): break
        time.sleep(.25)
    print('REMOVAL',row['status'],row['result'],flush=True)
    assert row['status']=='done' and not target.exists()
