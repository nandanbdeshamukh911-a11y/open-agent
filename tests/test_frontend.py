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
            root = page.locator('html')
            expect(root).to_have_attribute('data-theme', 'dark')
            expect(root).to_have_css('background-color', 'rgb(32, 32, 32)')
            expect(page.locator('.chat-surface')).to_have_css('animation-name', 'none')
            page.get_by_role('button', name='Review code', exact=True).click()
            draft = page.get_by_role('textbox', name='Message', exact=True)
            expect(draft).to_be_focused()
            expect(draft).to_have_value('Review this code and explain what I could improve:\n\n')
            draft.fill('')
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
            page.get_by_role('button', name='System', exact=True).click()
            page.emulate_media(color_scheme='light')
            expect(root).to_have_css('background-color', 'rgb(255, 255, 255)')
            page.emulate_media(color_scheme='dark')
            expect(root).to_have_css('background-color', 'rgb(32, 32, 32)')
            page.reload()
            expect(root).to_have_attribute('data-theme', 'system')
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
    chat = client.post('/api/chats', json={'content':'Make a page','tool':'text_stats'}).json()
    assert 'id' in chat, chat
    chat_id = chat['id']
    from backend import store
    source = ('<!doctype html><html><head><title>Demo page</title></head>'
              '<body><input aria-label="Name"><button onclick="this.textContent=\'Updated\'">Update</button>'
              '<a href="#details">Details</a><div style="height:150vh"></div><h2 id="details">More information</h2>'
              '<a href="https://example.invalid/other">Other site</a>'
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
        outside_requests = []
        def reject_outside(route):
            outside_requests.append(route.request.url)
            route.abort()
        page.route('https://example.invalid/**', reject_outside)
        page.route('http://127.0.0.1:8765/**', serve)
        try:
            page.goto('http://127.0.0.1:8765/')
            page.get_by_role('button', name='Make a page', exact=True).click()
            preview = page.get_by_role('region', name='Website preview')
            frame = preview.locator('iframe[title="Website content"]')
            content = frame.content_frame.frame_locator('iframe[title="Generated page"]')
            name = content.get_by_role('textbox', name='Name')
            expect(preview.get_by_role('heading', name='Demo page')).to_be_visible()
            page.get_by_role('button', name='Hide sidebar').click()
            expect(page.locator('.sidebar')).to_be_hidden()
            page.get_by_role('button', name='Show sidebar').click()
            expect(page.get_by_role('button', name='Hide sidebar')).to_be_focused()
            assert page.locator('.chat-with-preview').evaluate('element => getComputedStyle(element).display')=='grid'
            assert page.get_by_role('navigation').get_by_role('button',name='Browser',exact=True).count()==0
            box = frame.bounding_box()
            assert box['x'] > page.locator('.chat-panel').bounding_box()['x']
            assert client.get(f'/api/chats/{chat_id}/preview/source/{message_id}').text==source
            name.click()
            page.keyboard.type('Saved while resizing')
            name.press('Tab')
            page.keyboard.press('Enter')
            expect(content.get_by_role('button', name='Updated')).to_be_visible()
            frame.hover()
            details = content.get_by_role('heading', name='More information')
            expect(details).not_to_be_in_viewport()
            page.mouse.wheel(0, 1000)
            expect(details).to_be_in_viewport()
            content.get_by_role('link', name='Details', exact=True).click()
            assert details.evaluate('() => location.hash') == '#details'
            expect(preview.locator('summary')).to_contain_text('Page diagnostics')
            preview.get_by_role('button',name='Phone').click()
            expect(frame).to_have_css('width','390px')
            expect(name).to_have_value('Saved while resizing')
            content.get_by_role('link', name='Other site').click()
            expect(preview.get_by_role('link', name='Open example.invalid in a new tab')).to_have_attribute('href','https://example.invalid/other')
            expect(name).to_have_value('Saved while resizing')
            preview.get_by_role('button',name='Reload preview').click()
            expect(name).to_have_value('')
            assert not outside_requests
            page.get_by_role('textbox',name='Message',exact=True).focus()
            assert page.get_by_role('textbox',name='Message',exact=True).evaluate('e => getComputedStyle(e).outlineStyle')=='none'
            preview.get_by_role('button',name='Close preview').click()
            expect(preview).to_have_count(0)
            page.get_by_role('button',name='Preview website').click()
            expect(name).to_be_visible()
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth===innerWidth')
        finally:
            chromium.close()
