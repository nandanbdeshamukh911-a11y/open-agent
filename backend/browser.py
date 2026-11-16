"""Own bounded Playwright sessions on one thread, separate from agent workers."""

import os
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from . import store
from .browser_network import PreviewNetwork, parse_address

WIDTH, HEIGHT = 1120, 720
IDLE_SECONDS = 20 * 60
MAX_SESSIONS = 4
CLICK_ROLES = {'button', 'link', 'tab', 'checkbox', 'radio', 'switch', 'menuitem', 'option'}
ASSERT_ROLES = CLICK_ROLES | {'heading', 'textbox', 'status', 'alert', 'main', 'dialog', 'img'}
BROWSER_ACTIONS = {'browser_open', 'browser_click', 'browser_fill'}


class Preview:
    def __init__(self, browser, address, blocked_ports):
        self.context = None
        self.network = PreviewNetwork(address, blocked_ports)
        self.logs = deque(maxlen=20)
        self.result = {}
        self.image = b''
        self.status = None
        self.revision = 0
        self.visited_at = time.monotonic()
        self.remaining = 100
        self.remaining_bytes = 32 * 1024 * 1024
        try:
            self.context = browser.new_context(
                viewport={'width': WIDTH, 'height': HEIGHT}, service_workers='block',
                accept_downloads=False, permissions=[],
            )
            self.context.route('**/*', self.route)
            self.context.route_web_socket('**/*', lambda ws: ws.close())
            self.page = self.context.new_page()
            self.context.on('page', lambda other: other.close() if other != self.page else None)
            self.page.on('dialog', lambda dialog: dialog.dismiss())
            self.page.on('console', lambda message: self.log('Console', message.text) if message.type == 'error' else None)
            self.page.on('pageerror', lambda error: self.log('Page error', str(error)))
            self.page.on('response', self.on_response)
            self.page.set_default_timeout(4000)
            self.page.set_default_navigation_timeout(22000)
            response = self.page.goto(str(address), wait_until='domcontentloaded')
            self.status = response.status if response else None
            self.capture()
        except Exception as exc:
            self.close()
            detail = self.logs[-1] if self.logs else 'Check that the page is reachable and returns HTML.'
            raise ValueError(f'Could not open the preview. {detail}') from exc

    def on_response(self, response):
        if response.request.is_navigation_request() and response.request.frame == self.page.main_frame:
            self.status = response.status

    def log(self, kind, detail):
        self.logs.append(f'{kind}: {detail[:400]}')

    def route(self, route):
        request = route.request
        self.remaining -= 1
        try:
            if self.remaining < 0 or self.remaining_bytes <= 0:
                raise ValueError('Preview request budget exhausted.')
            status, headers, body = self.network.fetch(request.url, request.method, request.headers)
            self.remaining_bytes -= len(body)
            if self.remaining_bytes < 0:
                raise ValueError('Preview response budget exhausted.')
            if status >= 400:
                self.log('HTTP', f'{status} {request.url}')
            route.fulfill(status=status, headers=headers, body=body)
        except Exception as exc:
            self.log('Blocked or failed request', f'{request.url}: {str(exc).splitlines()[0][:150]}')
            route.abort()

    def capture(self):
        self.visited_at = time.monotonic()
        self.revision += 1
        outline = self.page.locator('body').aria_snapshot(timeout=3000)[:12000]
        self.image = self.page.screenshot(type='jpeg', quality=70, timeout=5000)
        self.result = {
            'url': self.page.url, 'title': self.page.title()[:200], 'status': self.status,
            'revision': self.revision, 'outline': outline, 'diagnostics': list(self.logs),
            'width': WIDTH, 'height': HEIGHT,
        }
        return self.result.copy()

    def interact(self, action, args):
        if args.get('revision') != self.revision:
            raise ValueError('The browser preview changed. Inspect it before retrying.')
        self.remaining = 100
        self.remaining_bytes = 32 * 1024 * 1024
        if action == 'browser_click':
            self.page.get_by_role(args['role'], name=args['name'], exact=True).click()
        elif action == 'browser_fill':
            field = self.page.get_by_label(args['label'], exact=True)
            if field.get_attribute('type') in ('file', 'password', 'hidden'):
                raise ValueError('File, password, and hidden inputs are unavailable.')
            field.fill(args['value'])
        elif action == 'point':
            x, y = args['x'], args['y']
            if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
                raise ValueError('Select a point inside the preview.')
            self.page.mouse.click(x, y)
        elif action == 'scroll':
            self.page.evaluate('(distance) => window.scrollBy(0, distance)', args['distance'])
        return self.capture()

    def close(self):
        try:
            if self.context:
                self.context.close()
        finally:
            self.network.close()


class BrowserService:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='open-agent-browser')
        self.pending = threading.BoundedSemaphore(8)
        self.sessions = {}
        self.playwright = None
        self.browser = None

    def call(self, action, key='manual', args=None):
        if not self.pending.acquire(blocking=False):
            raise ValueError('The browser is busy. Try again shortly.')
        try:
            return self.executor.submit(self.execute, action, key, args or {}).result()
        finally:
            self.pending.release()

    def launch(self):
        if self.browser and self.browser.is_connected():
            return
        from playwright.sync_api import sync_playwright
        if self.playwright:
            self.playwright.stop()
        self.sessions.clear()
        self.playwright = sync_playwright().start()
        channel = os.environ.get('OPEN_AGENT_BROWSER_CHANNEL')
        try:
            self.browser = self.playwright.chromium.launch(
                channel=channel, headless=True, chromium_sandbox=True, timeout=15000,
                args=['--host-resolver-rules=MAP * ~NOTFOUND', '--no-proxy-server',
                      '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'],
            )
        except Exception as exc:
            self.playwright.stop()
            self.playwright = None
            raise ValueError('Could not launch Chromium. Run python -m playwright install chromium, or configure an installed browser channel.') from exc

    def execute(self, action, key, args):
        if action == 'shutdown':
            for preview in self.sessions.values():
                preview.close()
            self.sessions.clear()
            if self.playwright:
                self.playwright.stop()
            self.playwright = self.browser = None
            return None
        now = time.monotonic()
        for expired in [name for name, preview in self.sessions.items() if now - preview.visited_at > IDLE_SECONDS]:
            self.sessions.pop(expired).close()
        if action == 'list':
            return [{'id': name, **{field: preview.result[field] for field in ('url', 'title')}} for name, preview in self.sessions.items()]
        if action == 'browser_open':
            address = parse_address(args['url'])
            model = store.query("SELECT value FROM settings WHERE key='model_url'", one=True)
            blocked_ports = set()
            if model:
                try:
                    blocked_ports.add(urlsplit(model['value']).port or 80)
                except ValueError:
                    pass
            if key not in self.sessions and len(self.sessions) >= MAX_SESSIONS:
                raise ValueError('Close an existing browser session before opening another.')
            self.launch()
            preview = Preview(self.browser, address, blocked_ports)
            # A revision from a closed page must never authorize the replacement page.
            preview.revision = time.monotonic_ns() // 1_000
            preview.result['revision'] = preview.revision
            previous = self.sessions.get(key)
            self.sessions[key] = preview
            if previous:
                previous.close()
            return preview.result.copy()
        preview = self.sessions.get(key)
        if not preview:
            raise ValueError('No active browser session. Open a URL first.')
        preview.visited_at = now
        if action == 'state':
            return preview.result.copy()
        if action == 'image':
            if args['revision'] != preview.revision:
                raise ValueError('This screenshot was replaced by a newer preview.')
            return preview.image
        if action == 'browser_inspect':
            return preview.capture()
        if action == 'browser_assert':
            role, name = accessible_target(args, ASSERT_ROLES)
            expected = args.get('visible', True)
            if type(expected) is not bool:
                raise ValueError('visible must be a boolean.')
            matches = preview.page.get_by_role(role, name=name, exact=True).all()
            if len(matches) > 1:
                raise ValueError(f'The assertion target is ambiguous: {role} {name!r}.')
            visible = bool(matches and matches[0].is_visible())
            expectation = 'visible' if expected else 'hidden'
            if visible != expected:
                raise ValueError(f'Browser assertion failed: expected {role} {name!r} to be {expectation}.')
            return f'Browser assertion passed: {role} {name!r} is {expectation}.'
        if action == 'close':
            self.sessions.pop(key).close()
            return None
        return preview.interact(action, args)


service = BrowserService()


def accessible_target(args, roles):
    role, name = args.get('role'), args.get('name')
    if not isinstance(role, str) or role not in roles or not isinstance(name, str) or not name.strip() or len(name) > 250:
        raise ValueError('Choose an exact accessible role and name from the browser snapshot.')
    return role, name


def prepare_action(action, args):
    if action == 'browser_open':
        return {'url': str(parse_address(args.get('url')))}
    revision = args.get('revision')
    if isinstance(revision, str) and revision.isascii() and revision.isdecimal() and len(revision) <= 16:
        revision = int(revision)
    if type(revision) is not int or not 0 < revision <= 9_007_199_254_740_991:
        raise ValueError('Use the numeric revision from the current browser snapshot.')
    if action == 'browser_click':
        role, name = accessible_target(args, CLICK_ROLES)
        return {'role':role, 'name':name, 'revision':revision}
    label, value = args.get('label'), args.get('value')
    if not isinstance(label, str) or not label.strip() or len(label) > 250 or not isinstance(value, str) or len(value) > 2000:
        raise ValueError('Choose an exact field label and enter up to 2,000 characters.')
    return {'label':label, 'value':value, 'revision':revision}
