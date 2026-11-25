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
