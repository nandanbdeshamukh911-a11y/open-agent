"""Adapters for configured MCP servers and diagnostics from the Python language server."""
import asyncio
import json
import os
import sys
import re
import httpx

from . import store, tools


def servers():
    row = store.query("SELECT value FROM settings WHERE key='mcp_servers'",one=True)
    return json.loads(row['value']) if row else {}


async def mcp_request(args):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    endpoint = args['url']
    if servers().get(args['server']) != endpoint:
        raise ValueError('Server configuration changed. Request fresh approval.')
    token_name = 'OPEN_AGENT_MCP_TOKEN_' + re.sub(r'[^A-Z0-9_]', '_', args['server'].upper())
    token = os.environ.get(token_name)
    headers = {'Authorization': 'Bearer '+token} if token else {}
    async with asyncio.timeout(45), httpx.AsyncClient(headers=headers, timeout=12, trust_env=False, follow_redirects=False) as client:
        async with streamable_http_client(endpoint, http_client=client) as (reader, writer, _):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                if args.get('tool'):
                    result = await session.call_tool(args['tool'], args.get('arguments',{}))
                    if result.isError: raise ValueError(result.model_dump_json()[:3000])
                    return result.model_dump_json()[:16000]
                listing = await session.list_tools()
                return json.dumps([{'name':tool.name,'description':tool.description,'schema':tool.inputSchema}
                                   for tool in listing.tools],ensure_ascii=False)[:18000]


async def diagnostics(project, relative):
    path = tools.workspace_path(project, relative)
    text = tools.snapshot(path).decode('utf-8-sig')
    proc = await asyncio.create_subprocess_exec(sys.executable,'-I','-m','pylsp',
        stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
    uri = path.as_uri()
    async def send(method, params, request_id=None):
        msg = {'jsonrpc':'2.0','method':method,'params':params}
        if request_id is not None: msg['id'] = request_id
        data = json.dumps(msg).encode()
        proc.stdin.write(f'Content-Length: {len(data)}\r\n\r\n'.encode()+data)
        await proc.stdin.drain()
    async def receive():
        headers = await proc.stdout.readuntil(b'\r\n\r\n')
        length = next(int(h.split(b':',1)[1]) for h in headers.splitlines() if h.lower().startswith(b'content-length:'))
        if not 0 < length <= 4000000: raise ValueError('Invalid LSP response size.')
        return json.loads(await proc.stdout.readexactly(length))
    try:
        async with asyncio.timeout(25):
            await send('initialize',{'processId':os.getpid(),'rootUri':path.parent.as_uri(),'capabilities':{}},1)
            while (await receive()).get('id') != 1: pass
            await send('initialized',{})
            await send('textDocument/didOpen',{'textDocument':{'uri':uri,'languageId':'python','version':1,'text':text}})
            while True:
                msg = await receive()
                params = msg.get('params',{})
                if msg.get('method')=='textDocument/publishDiagnostics' and params.get('uri')==uri:
                    rows = [f"{relative}:{d['range']['start']['line']+1}: {d['message']}" for d in params['diagnostics']]
                    return '\n'.join(rows[:50]) or f'No Python LSP diagnostics in {relative}.'
    finally:
        if proc.returncode is None: proc.kill()
        await proc.wait()
