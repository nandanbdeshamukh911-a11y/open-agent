import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(os.environ.get('OPEN_AGENT_DATA', Path(__file__).resolve().parent.parent / 'data')).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
DB = ROOT / 'agent.db'
lock = threading.RLock()

@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()

def init():
    with lock, connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, request TEXT NOT NULL, project TEXT NOT NULL, status TEXT NOT NULL, phase TEXT NOT NULL DEFAULT 'plan', plan TEXT DEFAULT '', requirements TEXT DEFAULT '[]', final TEXT DEFAULT '', retries INTEGER DEFAULT 0, max_retries INTEGER DEFAULT 3, created TEXT DEFAULT CURRENT_TIMESTAMP, updated TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id), kind TEXT NOT NULL, content TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS approvals(id INTEGER PRIMARY KEY, task_id INTEGER REFERENCES tasks(id), action TEXT NOT NULL, args TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', result TEXT DEFAULT '', created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY, content TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'user', enabled INTEGER NOT NULL DEFAULT 1, updated TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS skills(id INTEGER PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL, path TEXT NOT NULL, version TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS chats(id INTEGER PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ready', error TEXT NOT NULL DEFAULT '', updated TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS chat_messages(id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL);
        ''')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(tasks)').fetchall()}
        if 'draft' not in columns:
            db.execute("ALTER TABLE tasks ADD COLUMN draft TEXT NOT NULL DEFAULT ''")
        message_columns = {row['name'] for row in db.execute('PRAGMA table_info(chat_messages)')}
        if 'browser_context' not in message_columns:
            db.execute('ALTER TABLE chat_messages ADD COLUMN browser_context TEXT')
        for key in ('checkpoint','source_project'):
            if key not in columns: db.execute(f'ALTER TABLE tasks ADD COLUMN {key} TEXT')
        if 'image' not in message_columns: db.execute('ALTER TABLE chat_messages ADD COLUMN image TEXT')
        db.execute('CREATE TABLE IF NOT EXISTS check_rules(project TEXT,args TEXT,PRIMARY KEY(project,args))')
        # An operation interrupted mid-flight cannot safely be replayed automatically.
        db.execute("UPDATE approvals SET status='interrupted', result='The app stopped during this action. Inspect the workspace before retrying.' WHERE status='executing'")
        db.execute("UPDATE tasks SET status='paused' WHERE status='running'")
        db.execute("UPDATE chats SET status='failed',error='The app stopped before the reply finished. Retry when ready.' WHERE status='generating'")

def query(sql, params=(), one=False):
    with lock, connect() as db:
        rows = db.execute(sql, params).fetchall()
        return (dict(rows[0]) if rows else None) if one else [dict(row) for row in rows]

def execute(sql, params=()):
    with lock, connect() as db:
        cur = db.execute(sql, params)
        return cur.lastrowid

def event(task_id, kind, content):
    execute('INSERT INTO events(task_id,kind,content) VALUES(?,?,?)', (task_id,kind,content if isinstance(content,str) else json.dumps(content)))

def update(task_id, **fields):
    fields['updated'] = __import__('datetime').datetime.now().isoformat(timespec='seconds')
    execute('UPDATE tasks SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?', (*fields.values(),task_id))
