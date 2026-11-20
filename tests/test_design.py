import json
import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from backend import browser, design, tools
from test_agent import app, wait_for

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples' / 'listening-room'
BRIEF = json.loads((EXAMPLE / 'brief.json').read_text(encoding='utf-8'))


def test_example_matches_compiler_and_escapes_copy():
    assert design.render(BRIEF) == (EXAMPLE / 'index.html').read_text(encoding='utf-8')
    assert '&lt;/script&gt;' in design.render({**BRIEF, 'intro':'</script>'})
    with pytest.raises(ValueError, match='palette'):
        design.render({**BRIEF, 'palette':'bad'})


def test_design_task_reviews_exact_html_and_preserves_existing_file(app, tmp_path, monkeypatch):
    client, agent, store = app
    replies = iter([
        {'plan':'Create the programme', 'requirements':['Create the website']},
        {'action':'design_page','args':BRIEF},
        {'action':'clarify','args':{'question':'Choose another file.'}},
    ])
    monkeypatch.setattr(agent, 'model_call', lambda _: json.dumps(next(replies)))
    task = client.post('/api/tasks', json={'request':'Build a website', 'project':str(tmp_path)}).json()['id']
    approval = wait_for(lambda: store.query('SELECT * FROM approvals WHERE task_id=?',(task,), True))
    assert json.loads(approval['args']) == {'path':'index.html', 'content':design.render(BRIEF)}
    target = tmp_path / 'index.html'
    assert not target.exists()
    target.write_text('Concurrent edit', encoding='utf-8')
    client.post(f"/api/approvals/{approval['id']}/decide", json={'approved':True}).raise_for_status()
    wait_for(lambda: store.query('SELECT status FROM tasks WHERE id=?',(task,),True)['status'] == 'blocked')
    assert target.read_text() == 'Concurrent edit'
    assert store.query('SELECT status FROM approvals WHERE id=?',(approval['id'],),True)['status'] == 'failed'


@pytest.mark.skipif(not os.environ.get('OPEN_AGENT_TEST_BROWSER'), reason='Requires installed Chromium')
def test_standalone_preview_verifies_approved_bytes_without_a_server(app, tmp_path, monkeypatch):
    client, agent, store = app
    requirement = 'Build the festival website and verify the phone layout'
    def replies():
        yield {'plan':'Build and inspect', 'requirements':[requirement]}
        yield {'action':'design_page','args':BRIEF}
        yield {'action':'browser_project','args':{'viewport':'mobile'}}
        yield {'action':'browser_layout'}
        yield {'action':'review'}
        event = next(row for row in store.query("SELECT id,content FROM events WHERE kind='tool'")
                     if json.loads(row['content'])['action'] == 'browser_layout')
        evidence = json.loads(event['content'])['result']
        yield {'verdict':'pass','checks':[{'requirement':requirement,'status':'pass','event_id':event['id'],'evidence':evidence}], 'summary':evidence}
        yield {'verdict':'pass','summary':evidence}
    steps = replies()
    monkeypatch.setattr(agent, 'model_call', lambda _: json.dumps(next(steps)))
    task = client.post('/api/tasks', json={'request':requirement, 'project':str(tmp_path)}).json()['id']
    try:
        for action in ('design_page', 'browser_project'):
            approval = wait_for(lambda: store.query("SELECT * FROM approvals WHERE task_id=? AND status='pending'", (task,), True))
            assert approval['action'] == action
            client.post(f"/api/approvals/{approval['id']}/decide", json={'approved':True}).raise_for_status()
        wait_for(lambda: store.query('SELECT status FROM tasks WHERE id=?',(task,),True)['status'] == 'completed')
        assert '390 x 844' in store.query('SELECT final FROM tasks WHERE id=?',(task,),True)['final']
        captured = json.loads(approval['args'])
        (tmp_path / 'index.html').write_text('Changed page')
        with pytest.raises(ValueError, match='changed after approval'):
            agent.task_action('browser_project', captured, {'project':str(tmp_path), 'id':task})
    finally:
        browser.service.call('shutdown')


@pytest.mark.skipif(not os.environ.get('OPEN_AGENT_TEST_BROWSER'), reason='Requires installed Chromium')
def test_programme_in_phone_and_desktop_preview(app, tmp_path):
    target = tmp_path / 'index.html'
    tools.run('design_page', {'path':target.name, 'content':design.render(BRIEF)}, tmp_path)
    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    with ThreadingHTTPServer(('127.0.0.1', 0), handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        url = f'http://127.0.0.1:{server.server_port}/index.html'
        try:
            for viewport, (width, height) in browser.VIEWPORTS.items():
                state = browser.service.call('browser_open', args={'url':url, 'viewport':viewport})
                assert (state['width'], state['height'], state['overflow']) == (width, height, 0)
                assert state['status'] == 200 and not state['diagnostics']
                assert '0px horizontal overflow' in browser.service.call('browser_layout')
                assert BRIEF['headline'] in state['outline']
                item = BRIEF['items'][0]
                state = browser.service.call('browser_click', args={'role':'button', 'name':item['label'] + ' ' + item['title'], 'revision':state['revision']})
                assert item['detail'] in state['outline'] and not state['diagnostics']
            # Measure an actual CSS regression and repair only its declaration.
            original = target.read_text(encoding='utf-8')
            broken = original.replace('.hero { display:grid;', '.hero { min-width:900px; display:grid;')
            target.write_text(broken, encoding='utf-8')
            def measure():
                return browser.service.call('browser_open', args={'url':url,'viewport':'mobile'})['overflow']
            assert measure() > 0
            with pytest.raises(ValueError, match='overflows horizontally'):
                browser.service.call('browser_layout')
            edit = tools.prepare_edit(tmp_path, {'path':'index.html','old_text':'min-width:900px; ', 'new_text':''})
            tools.run('replace_text', edit, tmp_path)
            assert measure() == 0
            assert target.read_text(encoding='utf-8') == original
            catalogue = design.render({**BRIEF, 'layout':'catalogue'}).encode()
            state = browser.service.call('browser_project', args={'document':catalogue, 'viewport':'mobile'})
            for query, expected in [('river', '1 entry'), ('missing term', 'No matching entries.'), ('', '3 entries')]:
                state = browser.service.call('browser_fill', args={'label':'Search entries','value':query,'revision':state['revision']})
                assert expected in state['outline'] and state['overflow'] == 0
        finally:
            browser.service.call('shutdown')
            server.shutdown()
            worker.join()
