import json
import pytest

from backend import checks, tools
from test_agent import app, wait_for


def test_named_project_check_requires_approval_and_records_real_exit_code(app, tmp_path, monkeypatch):
    client, agent, store = app
    project = tmp_path / 'fixture'
    project.mkdir()
    tests = project / 'test_fixture.py'
    tests.write_text(
        'from pathlib import Path\nimport unittest\n\n'
        'class Example(unittest.TestCase):\n'
        '    def test_example(self):\n'
        '        Path("ran.txt").write_text("executed")\n'
        '        self.assertEqual(1, 2)\n',
        encoding='utf-8',
    )
    (project / 'requirements.txt').touch()
    assert 'unittest' in json.loads(tools.run('project_checks', {}, project))['checks']
    replies = iter([
        {'plan':'Run the check','requirements':['Reproduce the test failure']},
        {'action':'run_check','args':{'check':'unittest','path':'.'}},
        {'action':'clarify','args':{'question':'Failure reproduced.'}},
    ])
    monkeypatch.setattr(agent, 'model_call', lambda _: json.dumps(next(replies)))
    task_id = client.post('/api/tasks',json={'request':'Run the check','project':str(project)}).json()['id']
    pending = wait_for(lambda: store.query("SELECT * FROM approvals WHERE task_id=? AND status='pending'", (task_id,), True))
    assert not (project/'ran.txt').exists()
    assert json.loads(pending['args'])['argv'][1:] == ['-m','unittest','discover','-v']
    client.post(f"/api/approvals/{pending['id']}/decide", json={'approved':True}).raise_for_status()
    wait_for(lambda: store.query('SELECT status FROM tasks WHERE id=?', (task_id,), True)['status'] == 'blocked')
    result = store.query('SELECT result FROM approvals WHERE id=?', (pending['id'],), True)['result']
    assert result.startswith('Exit code: 1\nCheck: unittest')
    assert 'FAILED' in result and (project/'ran.txt').read_text() == 'executed'


def test_npm_lifecycle_changes_invalidate_approval(tmp_path, monkeypatch):
    manifest = tmp_path / 'package.json'
    manifest.write_text(json.dumps({'scripts':{'test':'echo test','pretest':'echo before'}}))
    monkeypatch.setattr(checks.shutil, 'which', lambda _: 'npm')
    approval = {'check':'npm-test', **checks.recipe(tmp_path, 'npm-test')}
    assert approval['scripts']['pretest'] == 'echo before'
    manifest.write_text(json.dumps({'scripts':{'test':'echo test','pretest':'echo changed'}}))
    with pytest.raises(ValueError, match='changed since'):
        checks.run_check(tmp_path, approval)


def test_review_repairs_a_bad_citation_without_repeating_a_tool(app, tmp_path, monkeypatch):
    client, agent, store = app
    task_id = store.execute(
        "INSERT INTO tasks(request, project, status, phase, requirements) VALUES(?,?,'paused','review',?)",
        ('Verify the page', str(tmp_path), json.dumps(['Open the site'])),
    )
    evidence = 'Browser opened http://127.0.0.1:3000/\nHTTP status: 200'
    store.event(task_id, 'tool', {'action':'browser_open','result':evidence})
    event_id = store.query("SELECT id FROM events WHERE task_id=?", (task_id,), True)['id']
    replies = iter([
        {'verdict':'pass','checks':[{'requirement':'Open the site','status':'pass','event_id':event_id,'evidence':'fabricated'}], 'summary':'Opened'},
        {'verdict':'pass','checks':[{'requirement':'Open the site','status':'pass','event_id':event_id,'evidence':evidence.replace('\n','\\n')}], 'summary':'Opened'},
        {'verdict':'pass','summary':'The browser opened the site with HTTP 200.'},
    ])
    monkeypatch.setattr(agent, 'model_call', lambda _: json.dumps(next(replies)))
    client.post(f'/api/tasks/{task_id}/resume').raise_for_status()
    wait_for(lambda: store.query('SELECT status FROM tasks WHERE id=?', (task_id,), True)['status'] == 'completed')
    assert not store.query('SELECT id FROM approvals WHERE task_id=?', (task_id,))
