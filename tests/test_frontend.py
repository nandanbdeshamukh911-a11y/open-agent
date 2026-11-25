import io
import os
import threading

import pytest
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from test_agent import app


@pytest.mark.skipif(not os.environ.get('OPEN_AGENT_TEST_BROWSER'), reason='Requires installed Chromium')
def test_chat_composer_and_transcript(app, monkeypatch):
    client, agent, _ = app
    finished = threading.Event()
    model_input = []

    def reply(messages, *, structured):
        model_input.extend(messages)
        finished.wait(timeout=20)
        return ('## Verification\n\nA **formatted** reply.\n\n'
                '| Check | Result |\n| --- | --- |\n| Preview | Pass |\n\n'
                '```python\nprint("verified")\n```')

    monkeypatch.setattr(agent, 'model_call', reply)
    sample = io.BytesIO()
    Image.new('RGB', (16, 16), 'seagreen').save(sample, format='PNG')

    def serve(route):
        request = route.request
        response = client.request(request.method, request.url, content=request.post_data_buffer, headers=request.headers)
        body = response.content
        headers = {'content-type': response.headers.get('content-type', 'application/octet-stream')}
        route.fulfill(status=response.status_code, headers=headers, body=body)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(chromium_sandbox=True)
        page = browser.new_page(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
        page.route('http://127.0.0.1:8765/**', serve)
        try:
            page.goto('http://127.0.0.1:8765/')
            plus = page.get_by_role('button', name='Add attachment')
            plus.focus()
            page.keyboard.press('Enter')
            upload = page.get_by_role('button', name='Upload image')
            expect(upload).to_be_focused()
            page.keyboard.press('Escape')
            expect(plus).to_be_focused()
            expect(upload).to_have_count(0)
            plus.click()
            with page.expect_file_chooser() as picker:
                upload.click()
            picker.value.set_files({'name': 'sample.png', 'mimeType': 'image/png', 'buffer': sample.getvalue()})
            expect(page.get_by_alt_text('Image ready to send')).to_be_visible()
            page.get_by_role('textbox', name='Message', exact=True).fill('Review the attached image.')
            page.get_by_role('button', name='Send message').click()
            expect(page.get_by_alt_text('Attached image', exact=True)).to_be_visible()
            expect(page.get_by_role('status', name='Generating reply')).to_be_visible()
            assert 'Waiting for the local model' not in page.locator('body').inner_text()
            finished.set()
            expect(page.get_by_role('heading', name='Verification')).to_be_visible()
            expect(page.get_by_role('table')).to_be_visible()
            expect(page.locator('.chat-markdown pre code')).to_have_text('print("verified")')
            page.wait_for_function("""() => {
                const thread = document.querySelector('.chat-transcript');
                return thread.scrollHeight - thread.clientHeight - thread.scrollTop < 2;
            }""")
            expect(page.get_by_text('0', exact=True)).to_have_count(0)
            assert any(isinstance(message['content'], list) for message in model_input)
            assert page.evaluate('document.documentElement.scrollWidth === innerWidth')
            page.get_by_role('button', name='Workspace menu').click()
            page.get_by_role('navigation').get_by_role('button', name='Settings').click()
            page.get_by_role('button', name='Dark', exact=True).click()
            page.reload()
            assert page.evaluate('document.documentElement.dataset.theme') == 'dark'
        finally:
            finished.set()
            browser.close()

@pytest.mark.skipif(not os.environ.get('OPEN_AGENT_TEST_BROWSER'), reason='Requires installed Chromium')
def test_generated_html_opens_automatically_beside_chat(app):
    client, _, _ = app
    from backend import browser
    chat = client.post('/api/chats', json={'content':'Make a page','tool':'text_stats'}).json()
    assert 'id' in chat, chat
    chat_id = chat['id']
    from backend import store
    source = ('<!doctype html><html><head><title>Demo page</title></head>'
              '<body style="margin:0"><button style="width:100vw;height:100vh" '
              'onclick="this.textContent=\'Updated\'">Update</button>'
              '<img src="https://example.invalid/pixel.png"></body></html>')
    message_id = store.execute("INSERT INTO chat_messages(chat_id,role,content) VALUES(?,'assistant',?)",
                               (chat_id, '\x60\x60\x60html\n'+source+'\n\x60\x60\x60'))

    def serve(route):
        request = route.request
        response = client.request(request.method, request.url, content=request.post_data_buffer, headers=request.headers)
        headers = {'content-type': response.headers.get('content-type', 'application/octet-stream')}
        route.fulfill(status=response.status_code, headers=headers, body=response.content)

    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch(chromium_sandbox=True)
        page = chromium.new_page(viewport={'width': 1440,'height': 900})
        page.route('http://127.0.0.1:8765/**', serve)
        try:
            page.goto('http://127.0.0.1:8765/')
            page.get_by_role('button', name='Make a page', exact=True).click()
            preview = page.get_by_role('region', name='Website preview')
            image = preview.get_by_alt_text('Rendered website')
            expect(image).to_have_js_property('naturalWidth',1120)
            assert page.locator('.chat-with-preview').evaluate('element => getComputedStyle(element).display')=='grid'
            assert page.get_by_role('navigation').get_by_role('button',name='Browser',exact=True).count()==0
            box = image.bounding_box()
            assert box['x'] > page.locator('.chat-panel').bounding_box()['x']
            assert client.get(f'/api/chats/{chat_id}/preview/source/{message_id}').text==source
            assert 'Content Security Policy' in '\n'.join(browser.service.call('state',f'chat-{chat_id}')['diagnostics'])
            with page.expect_response(lambda response: response.url.endswith('/preview/point')):
                image.click()
            assert 'Updated' in browser.service.call('state',f'chat-{chat_id}')['outline']
            preview.get_by_role('button',name='Phone').click()
            expect(image).to_have_js_property('naturalWidth',390)
            page.get_by_role('textbox',name='Message',exact=True).focus()
            assert page.get_by_role('textbox',name='Message',exact=True).evaluate('e => getComputedStyle(e).outlineStyle')=='none'
            preview.get_by_role('button',name='Close preview').click()
            expect(preview).to_have_count(0)
            page.get_by_role('button',name='Preview website').click()
            expect(image).to_have_js_property('naturalWidth',1120)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth===innerWidth')
        finally:
            chromium.close()
            browser.service.call('shutdown')
