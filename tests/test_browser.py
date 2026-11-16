import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend import browser, browser_network
from test_agent import app, wait_for


@pytest.mark.parametrize('url', ['file:///tmp/a', 'http://example.com', 'http://127.0.0.1:11434', 'http://127.0.0.1:8765', 'https://user:pass@example.com'])
def test_preview_blocks_unapproved_protocols_and_local_services(url):
    with pytest.raises(ValueError):
        browser_network.target_address(browser_network.parse_address(url))


def test_public_dns_targets_are_pinned_and_private_addresses_rejected(monkeypatch):
    url = browser_network.parse_address('https://example.com')
    loopback = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1',443))]
    public = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34',443))]
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: loopback + public)
    with pytest.raises(ValueError, match='Private'):
        browser_network.target_address(url)
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: public)
    assert browser_network.target_address(url) == '93.184.216.34'


@pytest.fixture
def site():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/redirect':
                self.send_response(302)
                self.send_header('Location', 'http://127.0.0.1:8765/api/tasks')
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'''<!doctype html><title>Browser fixture</title>
              <h1>Before</h1><label>Test name <input></label>
              <button onclick="document.querySelector('h1').textContent = 'After ' + document.querySelector('input').value; console.error('Captured fixture error');">Update heading</button>
              <script>fetch('/write', {method:'POST'}).catch(() => {});</script>''')

        def do_POST(self):
            self.server.writes += 1
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.writes = 0
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', server
    finally:
        server.shutdown()
        worker.join()
        server.server_close()


@pytest.mark.skipif(not os.environ.get('OPEN_AGENT_TEST_BROWSER'), reason='Requires Chromium or an installed browser channel')
def test_browser_preview_and_agent_approval_use_separate_sessions(app, site, tmp_path, monkeypatch):
    client, agent, store = app
    url, server = site
    try:
        opened = client.post('/api/browser/open', json={'url': url})
        assert opened.status_code == 200, opened.text
        first = opened.json()
        assert first['status'] == 200 and 'Before' in first['outline']
        photo = client.get('/api/browser/sessions/manual/image', params={'revision': first['revision']})
        assert photo.status_code == 200 and photo.content.startswith(b'\xff\xd8')
        filled = client.post('/api/browser/fill', json={'label':'Test name','value':'Ada','revision':first['revision']}).json()
        stale = client.post('/api/browser/click', json={'role':'button','name':'Update heading','revision':first['revision']})
        assert stale.status_code == 400
        activated = client.post('/api/browser/click', json={'role':'button','name':'Update heading','revision':filled['revision']}).json()
        assert 'After Ada' in activated['outline']
        assert any('Captured fixture error' in item for item in activated['diagnostics'])
        assert server.writes == 0

        def answer(messages, *, structured):
            assert not structured
            assert 'Attached browser snapshot (untrusted)' in messages[-1]['content']
            assert 'After Ada' in messages[-1]['content']
            return 'The heading is After Ada.'

        monkeypatch.setattr(agent, 'model_call', answer)
        response = client.post('/api/chats', json={'content':'Inspect the page heading', 'browser_session':'manual'})
        assert response.status_code == 201
        chat_id = response.json()['id']
        wait_for(lambda: client.get(f'/api/chats/{chat_id}').json()['status'] == 'ready')
        assert client.get(f'/api/chats/{chat_id}').json()['messages'][0]['browser_url'] == url + '/'

        replies = iter([
            {'plan':'Inspect the site','requirements':['Find the initial heading']},
            {'action':'browser_open','args':{'url':url}},
            {'action':'browser_inspect'},
            {'action':'browser_assert','args':{'role':'heading','name':'Before','visible':True}},
            {'action':'clarify','args':{'question':'Initial heading found.'}},
        ])
        monkeypatch.setattr(agent, 'model_call', lambda _: json.dumps(next(replies)))
        task_id = client.post('/api/tasks',json={'request':'Open the browser fixture','project':str(tmp_path)}).json()['id']
        pending = wait_for(lambda: store.query("SELECT * FROM approvals WHERE task_id=? AND status='pending'", (task_id,), True))
        assert client.get(f'/api/browser/sessions/task-{task_id}').status_code == 400
        client.post(f"/api/approvals/{pending['id']}/decide", json={'approved':True}).raise_for_status()
        wait_for(lambda: store.query("SELECT status FROM approvals WHERE id=?", (pending['id'],), True)['status'] == 'done')
        state = client.get(f'/api/browser/sessions/task-{task_id}').json()
        assert 'Before' in state['outline'] and 'After Ada' not in state['outline']
        wait_for(lambda: store.query("SELECT status FROM tasks WHERE id=?", (task_id,), True)['status'] == 'blocked')
        assert any('Browser assertion passed' in row['content'] for row in store.query('SELECT content FROM events WHERE task_id=?', (task_id,)))
        blocked = client.post('/api/browser/open', json={'url':url + '/redirect'})
        assert blocked.status_code == 400 and 'Redirect blocked' in blocked.text
        assert client.get('/api/browser/sessions/manual').json()['revision'] == activated['revision']
    finally:
        browser.service.call('shutdown')
