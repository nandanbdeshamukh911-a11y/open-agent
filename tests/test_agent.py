import importlib
import json
import time
import threading
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_chat_and_followup_use_plain_text_and_saved_history(app, monkeypatch):
    client, agent, store = app
    prompts = []

    def model(messages, *, structured):
        assert not structured
        prompts.append(messages)
        return 'A local reply.'

    monkeypatch.setattr(agent, 'model_call', model)
    created = client.post('/api/chats', json={'content': 'I prefer concise answers.'})
    assert created.status_code == 201
    chat_id = created.json()['id']
    wait_for(lambda: client.get(f'/api/chats/{chat_id}').json()['status'] == 'ready')
    assert client.post(f'/api/chats/{chat_id}/messages', json={'content': 'What did I just say?'}).status_code == 200
    wait_for(lambda: client.get(f'/api/chats/{chat_id}').json()['status'] == 'ready')
    assert [message['role'] for message in prompts[1]] == ['system', 'user', 'assistant', 'user']
    assert len(client.get(f'/api/chats/{chat_id}').json()['messages']) == 4
    assert client.get('/api/tasks').json() == []
    assert client.get('/api/approvals').json() == []


def test_chat_error_can_retry_without_duplicate_message(app, monkeypatch):
    client, agent, store = app
    replies = iter(['', 'Recovered reply'])
    monkeypatch.setattr(agent, 'model_call', lambda *a, **kw: next(replies))
    chat_id = client.post('/api/chats', json={'content': 'Hello'}).json()['id']
    wait_for(lambda: client.get(f'/api/chats/{chat_id}').json()['status'] == 'failed')
    assert client.post(f'/api/chats/{chat_id}/retry').status_code == 200
    wait_for(lambda: client.get(f'/api/chats/{chat_id}').json()['status'] == 'ready')
    messages = client.get(f'/api/chats/{chat_id}').json()['messages']
    assert [message['content'] for message in messages] == ['Hello', 'Recovered reply']


def test_chat_tools_are_deterministic_without_model(app, monkeypatch):
    client, agent, store = app
    monkeypatch.setattr(agent, 'model_call', lambda *a, **kw: pytest.fail('Tool called the model'))
    reply = client.post('/api/chats', json={'content': '0.1 + 0.2', 'tool': 'calculate'})
    chat_id = reply.json()['id']
    assert client.get(f'/api/chats/{chat_id}').json()['messages'][-1]['content'] == '0.3'
    for expression in ('1/0', '2**200', '__import__("os")'):
        assert client.post('/api/chats', json={'tool':'calculate','content':expression}).status_code == 422
    response = client.post(f'/api/chats/{chat_id}/messages', json={'tool':'json','content':'{"n":1e400,"v":["a,b",{}]}'})
    assert response.status_code == 200
    assert '"n": 1e400' in client.get(f'/api/chats/{chat_id}').json()['messages'][-1]['content']
    assert client.post('/api/chats', json={'tool':'json','content':'{"a":1,"a":2}'}).status_code == 422
    response = client.post(f'/api/chats/{chat_id}/messages', json={'tool':'text_stats','content':"A café\nDon't stop"})
    assert response.status_code == 200
    assert client.get(f'/api/chats/{chat_id}').json()['messages'][-1]['content'].splitlines()[0] == 'Words: 4'


def test_targeted_edit_requires_approval_and_refuses_stale_content(app, tmp_path, monkeypatch):
    client, agent, store = app
    target = tmp_path / 'file.txt'
    original = b'first\r\nsecond\r\nthird\r\n'
    target.write_bytes(original)
    from backend import tools
    assert tools.run('read_file', {'path': 'file.txt', 'line_start': 2, 'line_end': 2}, tmp_path) == 'second\n'
    edit = {'path':'file.txt','old_text':'second\n','new_text':'replacement\n'}
    approved = tools.prepare_edit(tmp_path, edit)
    assert approved['old_text'] == 'second\r\n'
    replies = iter([
        {'plan':'Edit the requested line','requirements':['Update second line']},
        {'action':'replace_text','args':edit},
        {'action':'clarify','args':{'question':'File changed. How should I proceed?'}}
    ])
    monkeypatch.setattr(agent, 'model_call', lambda _:json.dumps(next(replies)))
    task_id = client.post('/api/tasks', json={'request':'Update second line','project':str(tmp_path)}).json()['id']
    pending = wait_for(lambda: store.query("SELECT * FROM approvals WHERE task_id=? AND status='pending'", (task_id,), True))
    assert target.read_bytes() == original
    target.write_bytes(original + b'external edit\r\n')
    assert client.post(f"/api/approvals/{pending['id']}/decide", json={'approved':True}).status_code == 200
    wait_for(lambda: store.query('SELECT status FROM tasks WHERE id=?', (task_id,), True)['status'] == 'blocked')
    assert target.read_bytes() == original + b'external edit\r\n'
    assert store.query('SELECT status FROM approvals WHERE id=?', (pending['id'],), True)['status'] == 'failed'
    tools.run('replace_text', tools.prepare_edit(tmp_path, edit), tmp_path)
    assert target.read_bytes() == b'first\r\nreplacement\r\nthird\r\nexternal edit\r\n'


def test_git_tools_inspect_staged_and_unstaged_changes(tmp_path):
    from backend import tools
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    target = tmp_path / 'file.txt'
    target.write_text('staged\n', encoding='utf-8')
    subprocess.run(['git', 'add', '--', 'file.txt'], cwd=tmp_path, check=True)
    target.write_text('unstaged\n', encoding='utf-8')
    assert 'AM file.txt' in tools.run('git_status', {}, tmp_path)
    assert '+staged' in tools.run('git_diff', {'staged':True}, tmp_path)
    assert '+unstaged' in tools.run('git_diff', {'path':'file.txt'}, tmp_path)

@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('OPEN_AGENT_DATA', str(tmp_path / 'data'))
    from backend import store, agent, main
    importlib.reload(store)
    store.init()
    monkeypatch.setattr(main, 'store', store)
    monkeypatch.setattr(agent, 'store', store)
    from backend import tools
    monkeypatch.setattr(tools, 'store', store)
    return TestClient(main.app, base_url='http://127.0.0.1:8765', headers={'X-Open-Agent':'local'}), agent, store

def wait_for(fn):
    deadline = time.time()+5
    while time.time()<deadline:
        value = fn()
        if value: return value
        time.sleep(.02)
    pytest.fail('Timed out waiting for agent state')

def test_approval_repair_and_final_review(app, tmp_path, monkeypatch):
    client, agent, store = app
    project=tmp_path/'project'; project.mkdir()
    replies = iter([
        {'plan':'Write and verify the file','requirements':['File contains correct text']},
        {'action':'write_file','args':{'path':'hello.txt','content':'wrong'},'reason':'initial implementation'},
        {'action':'review','args':{},'reason':'check'},
        {'verdict':'repair','checks':[{'requirement':'File contains correct text','status':'fail','evidence':'wrong'}],'summary':'Needs repair','repair':'Fix text'},
        {'action':'write_file','args':{'path':'hello.txt','content':'correct'},'reason':'fix only the failed requirement'},
        {'action':'read_file','args':{'path':'hello.txt'},'reason':'verify'},
        {'action':'review','args':{},'reason':'check again'},
        {'verdict':'pass','checks':[{'requirement':'File contains correct text','status':'pass','evidence':'correct'}],'summary':'Created and checked hello.txt.'},
        {'verdict':'pass','summary':'Created and checked hello.txt.','repair':''},
    ])
    def respond(_):
        reply = next(replies)
        if reply.get('verdict') == 'pass' and 'checks' in reply:
            reply['checks'][0]['event_id'] = store.query("SELECT id FROM events WHERE kind='tool' ORDER BY id DESC LIMIT 1",one=True)['id']
        return json.dumps(reply)
    monkeypatch.setattr(agent,'model_call',respond)
    tid=client.post('/api/tasks',json={'request':'Create correct file','project':str(project)}).json()['id']
    wait_for(lambda: store.query('SELECT * FROM approvals WHERE task_id=? AND status="pending"',(tid,),True))
    assert not (project/'hello.txt').exists()
    aid=store.query('SELECT * FROM approvals WHERE task_id=? AND status="pending"',(tid,),True)['id']
    assert client.post(f'/api/approvals/{aid}/decide',json={'approved':True}).status_code==200
    wait_for(lambda: store.query('SELECT * FROM approvals WHERE task_id=? AND status="pending" AND id>?',(tid,aid),True))
    assert (project/'hello.txt').read_text()=='wrong'
    second=store.query('SELECT * FROM approvals WHERE task_id=? AND status="pending"',(tid,),True)['id']
    client.post(f'/api/approvals/{second}/decide',json={'approved':True})
    wait_for(lambda: store.query('SELECT status FROM tasks WHERE id=?',(tid,),True)['status']=='completed')
    assert (project/'hello.txt').read_text()=='correct'
    assert store.query('SELECT retries FROM tasks WHERE id=?',(tid,),True)['retries']==1

def test_denial_and_path_escape(app, tmp_path, monkeypatch):
    client, agent, store=app
    project=tmp_path/'project'; project.mkdir()
    replies=iter([{'plan':'Edit','requirements':['edit']},{'action':'command','args':{'command':'echo hello'}}])
    monkeypatch.setattr(agent,'model_call',lambda _:json.dumps(next(replies)))
    tid=client.post('/api/tasks',json={'request':'Edit','project':str(project)}).json()['id']
    approval=wait_for(lambda: store.query('SELECT * FROM approvals WHERE task_id=?',(tid,),True))
    client.post(f"/api/approvals/{approval['id']}/decide",json={'approved':False})
    assert store.query('SELECT status FROM tasks WHERE id=?',(tid,),True)['status']=='blocked'
    from backend.tools import workspace_path
    with pytest.raises(ValueError): workspace_path(str(project),'../outside.txt')

def test_restart_and_security(app, tmp_path):
    client, agent, store=app
    tid=store.execute("INSERT INTO tasks(request,project,status) VALUES('x',?,'running')",(str(tmp_path),))
    aid=store.execute("INSERT INTO approvals(task_id,action,args,status) VALUES(?,'command','{}','executing')",(tid,))
    store.init()
    assert store.query('SELECT status FROM tasks WHERE id=?',(tid,),True)['status']=='paused'
    assert store.query('SELECT status FROM approvals WHERE id=?',(aid,),True)['status']=='interrupted'
    assert client.post(f'/api/tasks/{tid}/resume').status_code==409
    assert client.post(f'/api/tasks/{tid}/message',json={'content':'continue'}).status_code==409
    assert client.post(f'/api/approvals/{aid}/acknowledge').status_code==200
    assert TestClient(client.app,base_url='http://evil.example').get('/api/tasks').status_code==403
    assert TestClient(client.app,base_url='http://127.0.0.1:8765').post('/api/memories',json={'content':'x'}).status_code==403

def test_import_validation_and_memory(app):
    client, _, store=app
    assert client.post('/api/skills/import',json={'url':'https://evil.example/a/b'}).status_code==400
    result=client.post('/api/skills/import',json={'url':'https://github.com/example/tool'}).json()
    assert store.query('SELECT status FROM approvals WHERE id=?',(result['approval_id'],),True)['status']=='pending'
    assert not (store.ROOT/'skills'/'example__tool').exists()
    mid=client.post('/api/memories',json={'content':'Prefer Python'}).json()['id']
    assert client.put(f'/api/memories/{mid}',json={'content':'Prefer Rust','enabled':False}).status_code==200
    assert client.get('/api/memories').json()[0]['enabled']==0
    assert client.delete(f'/api/memories/{mid}').status_code==200

def test_personalization_from_user_messages(app):
    client, agent, store = app
    agent.remember_explicit_preferences('I prefer concise explanations. My preferred language is Python. I prefer my password secret.')
    rows = client.get('/api/memories').json()
    assert len(rows) == 2
    assert all(row['source'] == 'user message' for row in rows)
    assert 'I prefer concise explanations' in agent.relevant_memories('Build a dashboard')
    client.put(f"/api/memories/{rows[0]['id']}",json={'content':rows[0]['content'],'enabled':False})
    assert rows[0]['content'] not in agent.relevant_memories('Build a dashboard')
    agent.remember_explicit_preferences('I prefer concise explanations.')
    assert len(client.get('/api/memories').json()) == 2

def test_review_requires_actual_unique_evidence(app, tmp_path):
    _, agent, store = app
    tid = store.execute("INSERT INTO tasks(request,project,status) VALUES('x',?,'running')",(str(tmp_path),))
    store.event(tid,'tool',{'action':'read_file','result':'hello'})
    eid = store.query('SELECT id FROM events WHERE task_id=?',(tid,),True)['id']
    check = {'requirement':'first','status':'pass','event_id':eid,'evidence':'hello'}
    assert agent.passing_review(tid,['first'],[check])
    assert not agent.passing_review(tid,['first','second'],[check,check])
    assert not agent.passing_review(tid,['first'],[{**check,'evidence':'invented'}])
    assert not agent.passing_review(tid,['first'],[{**check,'event_id':999}])
    wrong = [{**check,'event_id':999}]
    assert agent.repair_evidence_references(tid,wrong) and wrong[0]['event_id']==eid
    assert agent.passing_review(tid,['first'],wrong)
    store.event(tid,'tool',{'action':'command','result':'Exit code: 1\nSTDOUT:\nfailed'})
    failed = store.query('SELECT id FROM events WHERE task_id=? ORDER BY id DESC',(tid,),True)['id']
    assert not agent.passing_review(tid,['first'],[{**check,'event_id':failed,'evidence':'failed'}])
    abbreviated = [{**check,'event_id':failed,'evidence':'Exit code: 1\nincorrect paraphrase'}]
    assert agent.repair_evidence_references(tid,abbreviated)
    assert abbreviated[0]['evidence']=='Exit code: 1'
    store.update(tid,request='First run the test to reproduce the failure, then run it again to verify success.')
    assert agent.passing_review(tid,['Run the test'],[{**check,'requirement':'Run the test','event_id':failed,'evidence':'failed'}])
    assert not agent.passing_review(tid,['Run the test again to verify it passes'],[{**check,'requirement':'Run the test again to verify it passes','event_id':failed,'evidence':'failed'}])

def test_cancel_during_model_failure_does_not_overwrite_cancelled(app, tmp_path, monkeypatch):
    client, agent, store = app
    entered, release = threading.Event(), threading.Event()
    def model(_):
        entered.set(); release.wait(5); raise RuntimeError('model failed')
    monkeypatch.setattr(agent,'model_call',model)
    tid = client.post('/api/tasks',json={'request':'test','project':str(tmp_path)}).json()['id']
    assert entered.wait(2)
    assert client.post(f'/api/tasks/{tid}/cancel').status_code == 200
    release.set()
    wait_for(lambda: tid not in agent.workers)
    assert store.query('SELECT status FROM tasks WHERE id=?',(tid,),True)['status'] == 'cancelled'

def test_import_file_and_remove_approval(app, monkeypatch):
    client, agent, store = app
    from backend import tools
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,_): return b'# Example skill\n'
    class Opener:
        def open(self,url,timeout):
            assert url == 'https://raw.githubusercontent.com/test-owner/tool/main/SKILL.md'
            return Response()
    monkeypatch.setattr(tools.urllib.request,'build_opener',lambda *_:Opener())
    result=client.post('/api/skills/import',json={'url':'https://github.com/test-owner/tool/blob/main/SKILL.md'}).json()
    aid=result['approval_id']
    assert not Path(result['destination']).exists()
    client.post(f'/api/approvals/{aid}/decide',json={'approved':True})
    wait_for(lambda: store.query('SELECT status FROM approvals WHERE id=?',(aid,),True)['status']=='done')
    skill=client.get('/api/skills').json()[0]
    assert skill['enabled']==0
    assert '# Example skill' in client.get(f"/api/skills/{skill['id']}/inspect").json()['content']
    assert client.put(f"/api/skills/{skill['id']}",json={'enabled':True}).status_code==200
    assert agent.skill_context()[0]['name'] == 'test-owner__tool'
    removal=client.delete(f"/api/skills/{skill['id']}").json()['approval_id']
    assert Path(result['destination']).exists()
    client.post(f'/api/approvals/{removal}/decide',json={'approved':True})
    wait_for(lambda: store.query('SELECT status FROM approvals WHERE id=?',(removal,),True)['status']=='done')
    assert not Path(result['destination']).exists()

def test_pause_resume_does_not_accept_stale_model_response(app, tmp_path, monkeypatch):
    client, agent, store = app
    entered, release = threading.Event(), threading.Event()
    calls = []
    def model(_):
        calls.append(1)
        if len(calls)==1:
            entered.set(); release.wait(5)
            return json.dumps({'plan':'stale','requirements':['stale']})
        return json.dumps({'plan':'fresh','requirements':['fresh']}) if len(calls)==2 else json.dumps({'action':'clarify','args':{'question':'test'}})
    monkeypatch.setattr(agent,'model_call',model)
    tid=client.post('/api/tasks',json={'request':'test','project':str(tmp_path)}).json()['id']
    assert entered.wait(2)
    assert client.post(f'/api/tasks/{tid}/pause').status_code==200
    assert client.post(f'/api/tasks/{tid}/resume').status_code==200
    release.set()
    wait_for(lambda: store.query('SELECT status FROM tasks WHERE id=?',(tid,),True)['status']=='blocked')
    assert store.query('SELECT plan FROM tasks WHERE id=?',(tid,),True)['plan']=='fresh'

def test_malformed_json_is_retried_then_stops(app, tmp_path, monkeypatch):
    client, agent, store=app
    calls=[]
    def model(_): calls.append(1); return 'not JSON'
    monkeypatch.setattr(agent,'model_call',model)
    tid=client.post('/api/tasks',json={'request':'test','project':str(tmp_path)}).json()['id']
    wait_for(lambda: store.query('SELECT status FROM tasks WHERE id=?',(tid,),True)['status']=='blocked')
    assert len(calls)==3
    assert len(store.query("SELECT id FROM events WHERE task_id=? AND kind='format_error'",(tid,)))==3

def test_failed_repository_clone_can_be_retried(app, monkeypatch):
    _, _, store=app
    from backend import tools
    class Result:
        returncode=1
        stderr='simulated failure'
    def clone(args,**_):
        Path(args[-1]).mkdir()
        (Path(args[-1])/'partial').write_text('partial')
        return Result()
    monkeypatch.setattr(tools.subprocess,'run',clone)
    with pytest.raises(ValueError,match='Clone failed'):
        tools.download_skill('https://github.com/example/repository')
    assert not tools.github_destination('https://github.com/example/repository').exists()
    assert not list((store.ROOT/'skills').iterdir())

def test_database_connection_closes_after_use(app):
    _, _, store=app
    store.query('SELECT 1')
    original=store.DB
    moved=original.with_name('moved.db')
    original.rename(moved)
    moved.rename(original)

def test_native_model_tool_call_still_requires_approval(app, tmp_path, monkeypatch):
    client, agent, store=app
    store.execute("INSERT INTO settings(key,value) VALUES('model_name','test-model')")
    class Response:
        status_code=200
        def raise_for_status(self): pass
        def json(self):
            return {'choices':[{'finish_reason':'tool_calls','message':{'content':None,'tool_calls':[{'function':{'name':'write_file','arguments':'{"path":"hello.txt","content":"hello"}'}}]}}]}
    monkeypatch.setattr(agent.httpx,'post',lambda *a,**kw:Response())
    result=json.loads(agent.model_call([]))
    assert result['action']=='write_file' and result['args']['path']=='hello.txt'
    assert not (tmp_path/'hello.txt').exists()
    class CommentaryResponse(Response):
        def json(self):
            return {'choices':[{'finish_reason':'tool_calls','message':{'content':None,'tool_calls':[{'function':{'name':'commentary','arguments':'{"action":"command","command":"echo hello"}'}}]}}]}
    monkeypatch.setattr(agent.httpx,'post',lambda *a,**kw:CommentaryResponse())
    assert json.loads(agent.model_call([]))['args']=={'command':'echo hello'}

def test_final_review_can_request_focused_repair(app, tmp_path, monkeypatch):
    client, agent, store=app
    tid=store.execute("INSERT INTO tasks(request,project,status,phase,draft) VALUES(?,?,'paused','final_review','draft')",('fix the bug',str(tmp_path)))
    replies=iter([{'verdict':'repair','summary':'Test evidence is missing','repair':'Run the relevant test'}, {'action':'clarify','args':{'question':'Need test details'}}])
    monkeypatch.setattr(agent,'model_call',lambda _:json.dumps(next(replies)))
    assert client.post(f'/api/tasks/{tid}/resume').status_code==200
    wait_for(lambda: store.query('SELECT status FROM tasks WHERE id=?',(tid,),True)['status']=='blocked')
    task=store.query('SELECT * FROM tasks WHERE id=?',(tid,),True)
    assert task['phase']=='work' and task['retries']==1
    assert 'Run the relevant test' in store.query("SELECT content FROM events WHERE task_id=? AND kind='repair_requested'",(tid,),True)['content']

def test_final_draft_survives_restart(app, tmp_path):
    _, _, store=app
    tid=store.execute("INSERT INTO tasks(request,project,status,phase,draft) VALUES(?,?,'running','final_review','unpublished draft')",('x',str(tmp_path)))
    store.init()
    row=store.query('SELECT * FROM tasks WHERE id=?',(tid,),True)
    assert row['status']=='paused' and row['draft']=='unpublished draft'

def test_action_audit_provides_evidence_of_no_download(app, tmp_path):
    _, agent, store=app
    tid=store.execute("INSERT INTO tasks(request,project,status) VALUES('no downloads',?,'running')",(str(tmp_path),))
    agent.record_action_audit(tid)
    event=store.query("SELECT id,content FROM events WHERE task_id=? AND kind='tool'",(tid,),True)
    assert 'Recorded download attempts: 0' in json.loads(event['content'])['result']
    check={'requirement':'No downloads','status':'pass','event_id':event['id'],'evidence':'Recorded download attempts: 0'}
    assert agent.passing_review(tid,['No downloads'],[check])
    requirement='Do not execute any terminal commands or download any external resources.'
    checks=[]
    assert agent.add_missing_negative_checks(tid,[requirement],checks)
    assert agent.passing_review(tid,[requirement],checks)
    assert not agent.add_missing_negative_checks(tid,['Do not delete files or download resources'],[])

def test_agent_requested_github_download_shows_destination_before_approval(app, tmp_path, monkeypatch):
    client, agent, store=app
    replies=iter([{'plan':'Import skill','requirements':['Import the requested skill']},
                  {'action':'download_skill','args':{'url':'https://github.com/example/tool'}}])
    monkeypatch.setattr(agent,'model_call',lambda _:json.dumps(next(replies)))
    tid=client.post('/api/tasks',json={'request':'Download this skill','project':str(tmp_path)}).json()['id']
    pending=wait_for(lambda: store.query("SELECT * FROM approvals WHERE task_id=? AND status='pending'",(tid,),True))
    args=json.loads(pending['args'])
    assert args['url']=='https://github.com/example/tool' and args['destination']==str(store.ROOT/'skills'/'example__tool')
    assert not Path(args['destination']).exists()
    client.post(f"/api/approvals/{pending['id']}/decide",json={'approved':False})
    assert not Path(args['destination']).exists()

def test_identical_edits_do_not_request_approval_or_repeat_forever(app, tmp_path, monkeypatch):
    client, agent, store=app
    target=tmp_path/'hello.txt'; target.write_text('same',encoding='utf-8')
    replies=iter([{'plan':'Verify file','requirements':['File is correct']}] +
                 [{'action':'write_file','args':{'path':'hello.txt','content':'same'}}]*2 +
                 [{'verdict':'blocked','checks':[{'requirement':'File is correct','status':'unverified'}],'summary':'Needs user input'}])
    monkeypatch.setattr(agent,'model_call',lambda _:json.dumps(next(replies)))
    tid=client.post('/api/tasks',json={'request':'Verify file','project':str(tmp_path)}).json()['id']
    wait_for(lambda: store.query('SELECT status FROM tasks WHERE id=?',(tid,),True)['status']=='blocked')
    assert store.query('SELECT * FROM approvals WHERE task_id=?',(tid,)) == []
    assert target.read_text(encoding='utf-8')=='same'
    assert store.query("SELECT * FROM events WHERE task_id=? AND kind='controller'",(tid,),True)
    assert 'same' in store.query("SELECT content FROM events WHERE task_id=? AND kind='tool' AND content LIKE '%read_file%'",(tid,),True)['content']
