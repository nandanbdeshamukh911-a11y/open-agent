import json
import os
import platform
import shutil
import subprocess
import urllib.parse
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import agent, browser_api, chat, store, tools

store.init()
app = FastAPI(title='Open Agent', docs_url=None, redoc_url=None, openapi_url=None, lifespan=browser_api.lifespan)
app.include_router(chat.router)
app.include_router(browser_api.router)

@app.middleware('http')
async def local_only(request: Request, call_next):
    host = request.headers.get('host','').split(':')[0].lower()
    origin = request.headers.get('origin')
    if host not in ('localhost','127.0.0.1','[::1]'):
        return JSONResponse({'detail':'Local access only'},status_code=403)
    if origin:
        parsed = urllib.parse.urlparse(origin)
        if parsed.scheme != 'http' or parsed.hostname not in ('localhost','127.0.0.1','::1') or parsed.port not in (8765,5173):
            return JSONResponse({'detail':'Origin not allowed'},status_code=403)
    if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('x-open-agent') != 'local':
        return JSONResponse({'detail':'Missing local request header'},status_code=403)
    return await call_next(request)

class NewTask(BaseModel):
    request: str = Field(min_length=1,max_length=20000)
    project: str = Field(min_length=1,max_length=2000)
    max_retries: int = Field(default=3,ge=0,le=10)
class Message(BaseModel):
    content: str = Field(min_length=1,max_length=20000)
class Decision(BaseModel):
    approved: bool
class Memory(BaseModel):
    content: str = Field(min_length=1,max_length=5000)
    enabled: bool = True
class Settings(BaseModel):
    model_url: str
    model_name: str = Field(min_length=1,max_length=200)
class Import(BaseModel):
    url: str
class Toggle(BaseModel):
    enabled: bool

def physical_memory_gib():
    if os.name != 'nt': return None
    try:
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length',ctypes.c_ulong),('load',ctypes.c_ulong),('total',ctypes.c_ulonglong),('available',ctypes.c_ulonglong),('total_page',ctypes.c_ulonglong),('available_page',ctypes.c_ulonglong),('total_virtual',ctypes.c_ulonglong),('available_virtual',ctypes.c_ulonglong),('available_extended',ctypes.c_ulonglong)]
        value = MemoryStatus(); value.length = ctypes.sizeof(value)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
            return round(value.total / (1024**3), 1)
    except (AttributeError,OSError): pass
    return None

@app.get('/api/status')
def status():
    result = {'platform':platform.platform(),'cpu':platform.processor(),'memory_gib':physical_memory_gib(),'ollama_installed':bool(shutil.which('ollama')),'git_installed':bool(shutil.which('git')),'model_url':agent.setting('model_url','http://127.0.0.1:11434/v1'),'model_name':agent.setting('model_name',''),'models':[],'runtime_error':None}
    try:
        import httpx
        url = result['model_url'].rstrip('/') + '/models'
        response = httpx.get(url,timeout=3,trust_env=False); response.raise_for_status()
        result['models'] = [x.get('id','') for x in response.json().get('data',[])]
        if not result['model_name']:
            result['model_name'] = next((x for x in result['models'] if 'gpt-oss' in x.lower()), '')
    except Exception as e: result['runtime_error'] = str(e)
    return result

@app.put('/api/settings')
def settings(body: Settings):
    p = urllib.parse.urlparse(body.model_url)
    if p.scheme != 'http' or p.hostname not in ('localhost','127.0.0.1','::1') or p.username or p.password or p.query or p.fragment:
        raise HTTPException(400,'Use a local HTTP OpenAI-compatible base URL, such as http://127.0.0.1:11434/v1')
    for k,v in body.model_dump().items(): store.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',(k,v))
    return {'ok':True}

@app.get('/api/tasks')
def tasks(): return store.query('SELECT * FROM tasks ORDER BY id DESC LIMIT 100')

@app.post('/api/tasks')
def new_task(body: NewTask):
    project = Path(body.project).expanduser().resolve()
    if not project.is_dir(): raise HTTPException(400,'Select an existing project directory.')
    tid = store.execute("INSERT INTO tasks(request,project,status,max_retries) VALUES(?,?,'running',?)",(body.request,str(project),body.max_retries))
    agent.remember_explicit_preferences(body.request)
    store.event(tid,'user',body.request); agent.start(tid)
    return {'id':tid}

@app.get('/api/tasks/{task_id}')
def task(task_id: int):
    row = store.query('SELECT * FROM tasks WHERE id=?',(task_id,),True)
    if not row: raise HTTPException(404,'Task not found')
    row['events'] = store.query('SELECT * FROM events WHERE task_id=? ORDER BY id',(task_id,))
    row['approvals'] = store.query('SELECT * FROM approvals WHERE task_id=? ORDER BY id',(task_id,))
    return row

@app.post('/api/tasks/{task_id}/message')
def task_message(task_id: int, body: Message):
    row = store.query('SELECT * FROM tasks WHERE id=?',(task_id,),True)
    if not row: raise HTTPException(404,'Task not found')
    if row['status'] in ('running','waiting_approval','completed','cancelled'): raise HTTPException(409,'Pause or resolve the task before adding a message.')
    unsettled = store.query("SELECT status FROM approvals WHERE task_id=? AND status IN ('pending','executing','interrupted') LIMIT 1",(task_id,),True)
    if unsettled: raise HTTPException(409,'Resolve or acknowledge the existing approval before resuming with a message.')
    agent.remember_explicit_preferences(body.content)
    store.event(task_id,'user',body.content)
    # Include clarifications in future prompts as evidence, then resume.
    store.update(task_id,status='running',final=''); agent.start(task_id)
    return {'ok':True}

@app.post('/api/tasks/{task_id}/{operation}')
def control(task_id: int, operation: str):
    with store.lock, store.connect() as db:
        row = db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
        if not row: raise HTTPException(404,'Task not found')
        if operation == 'pause' and row['status'] in ('running','waiting_approval'):
            agent.invalidate(task_id)
            db.execute("UPDATE tasks SET status='paused' WHERE id=?",(task_id,))
        elif operation == 'cancel' and row['status'] not in ('completed','cancelled'):
            agent.invalidate(task_id)
            db.execute("UPDATE tasks SET status='cancelled' WHERE id=?",(task_id,))
            db.execute("UPDATE approvals SET status='cancelled' WHERE task_id=? AND status='pending'",(task_id,))
        elif operation == 'resume' and row['status'] in ('paused','blocked'):
            executing = db.execute("SELECT 1 FROM approvals WHERE task_id=? AND status='executing'",(task_id,)).fetchone()
            interrupted = db.execute("SELECT 1 FROM approvals WHERE task_id=? AND status='interrupted'",(task_id,)).fetchone()
            if executing: raise HTTPException(409,'Wait for the approved action to finish before resuming.')
            if interrupted: raise HTTPException(409,'Inspect the interrupted action and acknowledge it before resuming.')
            pending = db.execute("SELECT 1 FROM approvals WHERE task_id=? AND status='pending'",(task_id,)).fetchone()
            db.execute('UPDATE tasks SET status=?,final=? WHERE id=?',('waiting_approval' if pending else 'running','',task_id))
        else: raise HTTPException(409,'Operation is not available in this task state.')
    if operation == 'resume' and not pending: agent.start(task_id)
    return {'ok':True}

@app.get('/api/approvals')
def approvals():
    return store.query("""
        SELECT approvals.*, tasks.project, tasks.status AS task_status
        FROM approvals LEFT JOIN tasks ON tasks.id=approvals.task_id
        WHERE approvals.status IN ('pending','executing','interrupted')
        ORDER BY approvals.id DESC
    """)

@app.post('/api/approvals/{approval_id}/decide')
def decide(approval_id: int, body: Decision):
    try: agent.resolve_approval(approval_id,body.approved)
    except ValueError as e: raise HTTPException(409,str(e))
    return {'ok':True}

@app.post('/api/approvals/{approval_id}/acknowledge')
def acknowledge(approval_id: int):
    with store.lock, store.connect() as db:
        row = db.execute("SELECT * FROM approvals WHERE id=? AND status='interrupted'",(approval_id,)).fetchone()
        if not row: raise HTTPException(409,'Action is not interrupted.')
        db.execute("UPDATE approvals SET status='acknowledged' WHERE id=?",(approval_id,))
    if row['task_id']: store.event(row['task_id'],'interrupted_action','User acknowledged an interrupted action after inspecting the workspace; outcome is unknown.')
    return {'ok':True}

@app.get('/api/memories')
def memories(): return store.query('SELECT * FROM memories ORDER BY updated DESC,id DESC')

@app.post('/api/memories')
def add_memory(body: Memory):
    return {'id':store.execute('INSERT INTO memories(content,enabled) VALUES(?,?)',(body.content,int(body.enabled)))}

@app.put('/api/memories/{memory_id}')
def edit_memory(memory_id: int, body: Memory):
    store.execute('UPDATE memories SET content=?,enabled=?,updated=CURRENT_TIMESTAMP WHERE id=?',(body.content,int(body.enabled),memory_id)); return {'ok':True}

@app.delete('/api/memories/{memory_id}')
def delete_memory(memory_id: int):
    store.execute('DELETE FROM memories WHERE id=?',(memory_id,)); return {'ok':True}

@app.get('/api/skills')
def skills(): return store.query('SELECT * FROM skills ORDER BY id DESC')

@app.get('/api/project-tools')
def project_tools():
    return tools.PROJECT_CATALOG

@app.get('/api/skills/{skill_id}/inspect')
def inspect_skill(skill_id: int):
    row = store.query('SELECT * FROM skills WHERE id=?',(skill_id,),True)
    if not row: raise HTTPException(404,'Tool not found')
    root = Path(row['path']).resolve()
    if not root.is_dir(): raise HTTPException(404,'Tool directory not found')
    files = [str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and '.git' not in p.relative_to(root).parts and p.resolve().is_relative_to(root)][:200]
    entry = root / 'SKILL.md'
    content = entry.read_text(encoding='utf-8',errors='replace')[:30000] if entry.is_file() and entry.resolve().is_relative_to(root) else 'No root SKILL.md. Inspect other files on disk before using this tool.'
    return {'files':files,'content':content}

@app.post('/api/skills/import')
def import_skill(body: Import):
    try: owner, repo, _ = tools.parse_github(body.url)
    except ValueError as e: raise HTTPException(400,str(e))
    dest = str(tools.github_destination(body.url))
    aid = store.execute("INSERT INTO approvals(action,args) VALUES('download_skill',?)",(json.dumps({'url':body.url,'destination':dest}),))
    return {'approval_id':aid,'destination':dest}

@app.put('/api/skills/{skill_id}')
def toggle_skill(skill_id: int, body: Toggle):
    store.execute('UPDATE skills SET enabled=? WHERE id=?',(int(body.enabled),skill_id)); return {'ok':True}

@app.delete('/api/skills/{skill_id}')
def delete_skill(skill_id: int):
    row = store.query('SELECT * FROM skills WHERE id=?',(skill_id,),True)
    if not row: raise HTTPException(404,'Tool not found')
    aid = store.execute("INSERT INTO approvals(action,args) VALUES('remove_skill',?)",(json.dumps({'skill_id':skill_id,'path':row['path']}),))
    return {'approval_id':aid}

dist = Path(__file__).resolve().parent.parent / 'frontend' / 'dist'
if (dist / 'assets').exists(): app.mount('/assets',StaticFiles(directory=dist/'assets'),name='assets')
@app.get('/')
def index():
    if not (dist/'index.html').exists(): return JSONResponse({'detail':'Build the frontend first; see README.md.'},status_code=503)
    return FileResponse(dist/'index.html')
