"""Adapters for configured MCP servers and local language diagnostics."""
import asyncio
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import httpx

from . import store, tools

LANGUAGES = {'.py': 'python', '.ts': 'typescript', '.tsx': 'typescriptreact',
             '.js': 'javascript', '.jsx': 'javascriptreact'}


def diagnostic_path(uri):
    parsed = urllib.parse.urlsplit(uri)
    if parsed.scheme != 'file':
        return None
    address = ('//' + parsed.netloc if parsed.netloc else '') + parsed.path
    # VS Code's URI serializer escapes the drive separator. Decode it first so
    # the Windows URL converter recognizes the drive form.
    if os.name == 'nt':
        address = re.sub(r'^/([a-z])%3a(?=/)', r'/\1:', address, flags=re.I)
    return Path(urllib.request.url2pathname(address))


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
    language = LANGUAGES[path.suffix.lower()]
    options = {}
    if language=='python':
        command = [sys.executable,'-I','-m','pylsp']
    else:
        modules = Path(__file__).resolve().parents[1]/'frontend'/'node_modules'
        cli = modules/'typescript-language-server'/'lib'/'cli.mjs'
        if not cli.is_file() or not shutil.which('node'): raise ValueError('Install frontend dependencies and Node to enable TypeScript diagnostics.')
        command = [shutil.which('node'),str(cli),'--stdio']
        options = {'disableAutomaticTypingAcquisition': True,
                   'tsserver': {'path': str(modules/'typescript'/'lib'/'tsserver.js'), 'useSyntaxServer': 'never'}}
    proc = await asyncio.create_subprocess_exec(*command,
        stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
    uri = path.as_uri()
    async def transmit(msg):
        data = json.dumps(msg).encode()
        proc.stdin.write(f'Content-Length: {len(data)}\r\n\r\n'.encode()+data)
        await proc.stdin.drain()
    async def send(method, params, request_id=None):
        msg = {'jsonrpc':'2.0','method':method,'params':params}
        if request_id is not None: msg['id'] = request_id
        await transmit(msg)
    async def receive():
        headers = await proc.stdout.readuntil(b'\r\n\r\n')
        length = next(int(h.split(b':',1)[1]) for h in headers.splitlines() if h.lower().startswith(b'content-length:'))
        if not 0 < length <= 4000000: raise ValueError('Invalid LSP response size.')
        return json.loads(await proc.stdout.readexactly(length))
    diagnostics_result = None
    try:
        async with asyncio.timeout(25):
            await send('initialize',{'processId':os.getpid(),'rootUri':Path(project).resolve().as_uri(),'capabilities':{'textDocument':{'publishDiagnostics':{'relatedInformation':True}}},'initializationOptions':options},1)
            while True:
                msg = await receive()
                if msg.get('id')==1 and 'method' not in msg:
                    if 'error' in msg: raise ValueError(str(msg['error'])[:800])
                    break
            await send('initialized',{})
            await send('textDocument/didOpen',{'textDocument':{'uri':uri,'languageId':language,'version':1,'text':text}})
            async with asyncio.timeout(None) as settle:
                while True:
                    msg = await receive()
                    if 'id' in msg and 'method' in msg:
                        await transmit({'jsonrpc':'2.0','id':msg['id'],'result':None})
                    params = msg.get('params') or {}
                    if msg.get('method') == 'textDocument/publishDiagnostics' and diagnostic_path(params.get('uri','')) == path:
                        diagnostics_result = params['diagnostics']
                        if language == 'python':
                            break
                        # TypeScript may publish syntax results before semantic results.
                        settle.reschedule(asyncio.get_running_loop().time() + 1)
    except TimeoutError as exc:
        if diagnostics_result is None:
            raise ValueError('The language server did not publish diagnostics within 25 seconds.') from exc
    finally:
        if proc.returncode is None:
            try:
                await send('shutdown',None,2)
                async with asyncio.timeout(2):
                    while (await receive()).get('id') != 2: pass
                await send('exit',None)
                await asyncio.wait_for(proc.wait(),2)
            except (OSError,TimeoutError,EOFError,ValueError):
                if proc.returncode is None: proc.kill()
        await proc.wait()
    rows = [f"{relative}:{d['range']['start']['line']+1}: {d['message']}" for d in diagnostics_result]
    return '\n'.join(rows[:50]) or f'No {language} diagnostics reported for {relative} at capture.'
