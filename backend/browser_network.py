"""HTTP transport for isolated browser previews."""

import ipaddress
import socket

import httpx

LOOPBACK = {'localhost': '127.0.0.1', '127.0.0.1': '127.0.0.1', '::1': '::1'}
INTERNAL_PORTS = {5173, 8765, 11434}
RESPONSE_LIMIT = 8 * 1024 * 1024
REDIRECTS = {301, 302, 303, 307, 308}


def parse_address(value):
    if not isinstance(value, str) or not value or len(value) > 2048 or any(ord(c) <= 32 or c == '\\' for c in value):
        raise ValueError('Enter a complete HTTP or HTTPS URL.')
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL as exc:
        raise ValueError('Enter a complete HTTP or HTTPS URL.') from exc
    if url.scheme not in ('http', 'https') or not url.host or url.userinfo:
        raise ValueError('Use an HTTP or HTTPS URL without credentials.')
    return url


def origin(url):
    return url.scheme, url.host, url.port or (443 if url.scheme == 'https' else 80)


def target_address(url, blocked_ports=()):
    _, host, port = origin(url)
    if host in LOOPBACK:
        if port in INTERNAL_PORTS or port in blocked_ports:
            raise ValueError('That port is reserved for Open Agent or its model server.')
        return LOOPBACK[host]
    if url.scheme != 'https' or port != 443:
        raise ValueError('Public previews require HTTPS on port 443.')
    try:
        addresses = {ipaddress.ip_address(row[4][0]) for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise ValueError('Could not resolve the site address.') from exc
    if not addresses or any(not address.is_global or address.is_multicast for address in addresses):
        raise ValueError('Private and reserved network addresses are unavailable. Use an explicit loopback URL for local previews.')
    # Resolve once and connect to the same verified address for the entire session.
    return str(min(addresses, key=lambda address: (address.version, int(address))))


class PreviewNetwork:
    def __init__(self, address, blocked_ports=()):
        self.site = origin(address)
        self.ip = target_address(address, blocked_ports)
        self.client = httpx.Client(trust_env=False, follow_redirects=False, timeout=6)

    def close(self):
        self.client.close()

    def fetch(self, address, method, headers):
        url = parse_address(address)
        if origin(url) != self.site or method not in ('GET', 'HEAD'):
            raise ValueError('Preview requests are limited to GET and HEAD on the selected origin.')
        pinned = url.copy_with(host=self.ip, fragment=None)
        request_headers = {'Host': url.netloc.decode('ascii'), 'Accept-Encoding': 'identity'}
        for name in ('accept', 'accept-language', 'user-agent'):
            if name in headers:
                request_headers[name] = headers[name]
        with self.client.stream(method, pinned, headers=request_headers,
                                extensions={'sni_hostname': url.raw_host.decode('ascii')}) as response:
            response_headers = {}
            for name in ('content-type', 'content-security-policy', 'x-content-type-options', 'cache-control', 'location'):
                if name in response.headers:
                    response_headers[name] = response.headers[name]
            if response.status_code in REDIRECTS:
                raise ValueError('Redirect blocked. Enter the final URL directly.')
            size = 0
            chunks = []
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > RESPONSE_LIMIT:
                    raise ValueError('Preview response exceeded 8 MiB.')
                chunks.append(chunk)
            return response.status_code, response_headers, b''.join(chunks)
