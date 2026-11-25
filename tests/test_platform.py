import asyncio
import base64
import io
import json
from pathlib import Path
import subprocess
import threading

from PIL import Image
import pytest
from backend import codemap, integrations, worktrees, checks
from test_agent import app, wait_for


def test_incremental_map_tracks_symbols_and_removals(app,tmp_path):
    p = tmp_path/'src'
    p.mkdir()
    for name,source in {'file.py':'def InvoiceTotal(): pass','view.tsx':'export function InvoiceRow() { return null }'}.items():
        (p/name).write_text(source)
    result = codemap.search(p,'Invoice')
    assert 'InvoiceTotal:1' in result and 'InvoiceRow:1' in result
    (p/'file.py').write_text('def subtotal(): pass')
    (p/'view.tsx').unlink()
    assert 'No matching' in codemap.search(p,'Invoice')


def test_python_lsp_reports_undefined_name(tmp_path):
    (tmp_path/'example.py').write_text('print(missing_name)\n')
    result = asyncio.run(integrations.diagnostics(tmp_path,'example.py'))
    assert 'missing_name' in result and ':1:' in result


def test_image_roundtrip_and_local_model_payload(app,monkeypatch):
    client,agent,store=app
    seen=[]
    def model(messages,**kwargs):
        seen.extend(messages)
        return 'Received the attachment.'
    monkeypatch.setattr(agent,'model_call',model)
    buf=io.BytesIO()
    Image.new('RGB',(4,4)).save(buf,format='PNG')
    image='data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()
    assert client.post('/api/chats',json={'content':'Look','image':'data:image/png;base64,bad'}).status_code==422
    cid=client.post('/api/chats',json={'content':'Look','image':image}).json()['id']
    wait_for(lambda:client.get(f'/api/chats/{cid}').json()['status']=='ready')
    msg=client.get(f'/api/chats/{cid}').json()['messages'][0]
    assert msg['has_image'] and seen[-1]['content'][1]['type']=='image_url'
    response=client.get(f"/api/chats/{cid}/messages/{msg['id']}/image")
    assert Image.open(io.BytesIO(response.content)).size==(4,4)


def test_restore_leaves_original_and_previous_edits_intact(app,tmp_path,monkeypatch):
    client,agent,store=app
    repo=tmp_path/'repo'
    repo.mkdir()
    subprocess.run(['git','init','-q',str(repo)],check=True)
    (repo/'file').write_text('start')
    worktrees.git(repo,'add','file')
    worktrees.git(repo,'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','baseline')
    monkeypatch.setattr(agent,'start',lambda _:None)
    tid=client.post('/api/tasks',json={'project':str(repo),'request':'Edit','isolated':True}).json()['id']
    task=client.get(f'/api/tasks/{tid}').json()
    old=Path(task['project'])
    (old/'file').write_text('changed')
    client.post(f'/api/tasks/{tid}/pause').raise_for_status()
    fresh=Path(client.post(f'/api/tasks/{tid}/restore').json()['project'])
    assert (fresh/'file').read_text()==(repo/'file').read_text()=='start'
    assert (old/'file').read_text()=='changed'


def test_parallel_verifier_runs_in_copy(app,tmp_path,monkeypatch):
    client,agent,store=app
    project=tmp_path/'project'
    project.mkdir()
    (project/'requirements.txt').touch()
    (project/'test_unit.py').write_text("import unittest\nfrom pathlib import Path\nclass Test(unittest.TestCase):\n def test_work(self): Path('marker').touch()")
    monkeypatch.setattr(agent,'start',lambda _:None)
    monkeypatch.setattr(agent,'model_call',lambda *a,**kw:'Reviewed test evidence.')
    tid=client.post('/api/tasks',json={'project':str(project),'request':'Verify'}).json()['id']
    options=client.get(f'/api/tasks/{tid}/checks').json()
    check=next(o for o in options if o['check']=='unittest')
    client.post(f'/api/tasks/{tid}/verify',json=check).raise_for_status()
    wait_for(lambda:store.query("SELECT id FROM events WHERE content='Reviewed test evidence.'"))
    assert not (project/'marker').exists()
    assert 'Exit code: 0' in store.query("SELECT content FROM events WHERE kind='tool'",one=True)['content']


def test_mcp_lists_and_invokes_real_http_server(app):
    import socket
    import time
    import uvicorn
    from mcp.server.fastmcp import FastMCP
    client,_,_=app
    server=FastMCP('fixture',stateless_http=True,json_response=True)
    @server.tool()
    def project_name() -> str:
        return 'Fixture project'
    sock=socket.socket()
    sock.bind(('127.0.0.1',0))
    url=f'http://127.0.0.1:{sock.getsockname()[1]}/mcp'
    host=uvicorn.Server(uvicorn.Config(server.streamable_http_app(),log_level='error'))
    worker=threading.Thread(target=host.run,kwargs={'sockets':[sock]},daemon=True)
    worker.start()
    try:
        wait_for(lambda:host.started)
        client.put('/api/engineering',json={'work_model':'','planning_model':'','python_lsp':False,'mcp_servers':{'demo':url}}).raise_for_status()
        args={'server':'demo','url':url}
        assert 'project_name' in asyncio.run(integrations.mcp_request(args))
        assert 'Fixture project' in asyncio.run(integrations.mcp_request({**args,'tool':'project_name'}))
    finally:
        host.should_exit=True
        worker.join(8)
        sock.close()

def test_named_check_permission_reuse_and_revocation(app,tmp_path,monkeypatch):
    client,agent,store=app
    project=tmp_path/'repo'
    project.mkdir()
    (project/'requirements.txt').touch()
    replies=iter([{'action':'run_check','args':{'check':'unittest'}},
                  {'action':'run_check','args':{'check':'unittest'}},
                  {'action':'clarify','args':{'question':'Done'}}])
    routes=[]
    def model(messages,*,model_override=None):
        routes.append(model_override)
        return json.dumps(next(replies))
    monkeypatch.setattr(agent,'model_call',model)
    store.execute("INSERT INTO settings VALUES('work_model','fixture-small')")
    tid=store.execute("INSERT INTO tasks(request,project,status,phase) VALUES(?,?,'paused','work')",('Test',str(project)))
    client.post(f'/api/tasks/{tid}/resume').raise_for_status()
    approval=wait_for(lambda:store.query("SELECT id FROM approvals WHERE status='pending'",one=True))
    client.post(f"/api/approvals/{approval['id']}/decide",json={'approved':True,'remember':True}).raise_for_status()
    wait_for(lambda:store.query('SELECT status FROM tasks WHERE id=?',(tid,),True)['status']=='blocked')
    assert [a['status'] for a in store.query('SELECT status FROM approvals')]==['done','done']
    assert routes==['fixture-small']*3
    rule=client.get('/api/engineering').json()['rules'][0]
    client.delete(f"/api/check-rules/{rule['id']}").raise_for_status()
    assert not client.get('/api/engineering').json()['rules']

def test_typescript_lsp_reports_type_error(tmp_path):
    (tmp_path/'tsconfig.json').write_text('{"compilerOptions":{"strict":true}}')
    (tmp_path/'bad.ts').write_text('const total: number = "hello";\n')
    result=asyncio.run(integrations.diagnostics(tmp_path,'bad.ts'))
    assert 'not assignable' in result


def test_approved_edit_returns_language_diagnostics_to_agent(app, tmp_path, monkeypatch):
    client, agent, store = app
    project = tmp_path / 'project'
    project.mkdir()
    file = project / 'example.py'
    file.write_text('print("ready")\n', encoding='utf-8')
    client.put('/api/engineering', json={
        'work_model': '', 'planning_model': '', 'python_lsp': True, 'mcp_servers': {},
    }).raise_for_status()
    replies = iter([
        {'action': 'replace_text', 'args': {'path': file.name, 'old_text': 'print("ready")', 'new_text': 'print(missing_name)'}},
        {'action': 'clarify', 'args': {'question': 'What should the name be?'}},
    ])
    inputs = []

    def model(messages):
        inputs.extend(message['content'] for message in messages)
        return json.dumps(next(replies))

    monkeypatch.setattr(agent, 'model_call', model)
    tid = store.execute(
        "INSERT INTO tasks(request,project,status,phase) VALUES(?,?,'paused','work')",
        ('Edit the example', str(project)),
    )
    client.post(f'/api/tasks/{tid}/resume').raise_for_status()
    approval = wait_for(lambda: store.query("SELECT id FROM approvals WHERE status='pending'", one=True))
    assert 'ready' in file.read_text(encoding='utf-8')
    client.post(f"/api/approvals/{approval['id']}/decide", json={'approved': True}).raise_for_status()
    wait_for(lambda: store.query('SELECT status FROM tasks WHERE id=?', (tid,), True)['status'] == 'blocked')
    payload = next(json.loads(event['content']) for event in store.query("SELECT content FROM events WHERE kind='tool'")
                   if 'python_lsp' in event['content'])
    assert 'undefined name' in payload['result'].lower()
    assert any(payload['result'] in message for message in inputs)
