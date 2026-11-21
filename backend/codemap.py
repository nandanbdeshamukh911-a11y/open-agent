"""Incremental, project-local source search using Tree-sitter and SQLite FTS5."""
import hashlib
import os
import re
import sqlite3
from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript

from . import store

GRAMMARS = {'.py':tree_sitter_python.language, '.js':tree_sitter_javascript.language,
            '.jsx':tree_sitter_javascript.language, '.ts':tree_sitter_typescript.language_typescript,
            '.tsx':tree_sitter_typescript.language_tsx}
SKIP = {'.git','node_modules','.venv','venv','__pycache__','dist','build','vendor','.next'}
SYMBOLS = {'class_definition','function_definition','function_declaration','class_declaration',
           'method_definition','interface_declaration','type_alias_declaration','variable_declarator'}


def search(project, query):
    terms = re.findall(r'\w+', str(query))[:12]
    if not terms:
        raise ValueError('Enter a symbol or search phrase.')
    root = Path(project).resolve(strict=True)
    directory = store.ROOT / 'indexes'
    directory.mkdir(exist_ok=True)
    db = sqlite3.connect(directory / (hashlib.sha256(os.fsencode(root)).hexdigest()+'.sqlite'), timeout=30)
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS stamps(path TEXT PRIMARY KEY, stamp TEXT)')
            db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS sources USING fts5(path,symbols,body)')
            db.execute('BEGIN IMMEDIATE')
            stamps = dict(db.execute('SELECT path,stamp FROM stamps'))
            parsers = {}
            count = 0
            for folder, dirs, files in os.walk(root):
                parent = Path(folder)
                dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith('.') and
                           (parent/d).resolve()==parent/d and (parent/d).resolve()!=store.ROOT]
                for filename in files:
                    path = parent/filename
                    ext = path.suffix.lower()
                    if ext not in GRAMMARS or path.is_symlink() or not path.is_file(): continue
                    stat = path.stat()
                    if stat.st_size > 500000: continue
                    count += 1
                    if count > 20000: raise ValueError('Choose a smaller project folder (20,000 source file limit).')
                    key = path.relative_to(root).as_posix()
                    stamp = f'{stat.st_mtime_ns}/{stat.st_size}'
                    if stamps.pop(key,None)==stamp: continue
                    raw = path.read_bytes()
                    if ext not in parsers: parsers[ext] = Parser(Language(GRAMMARS[ext]()))
                    stack = [parsers[ext].parse(raw).root_node]
                    names = []
                    while stack:
                        node = stack.pop()
                        name = node.child_by_field_name('name') if node.type in SYMBOLS else None
                        if name: names.append(f'{name.text.decode("utf8","replace")}:{name.start_point.row+1}')
                        stack.extend(reversed(node.named_children))
                    db.execute('DELETE FROM sources WHERE path=?',(key,))
                    db.execute('INSERT INTO sources VALUES(?,?,?)',(key,' '.join(names),raw.decode('utf8','replace')))
                    db.execute('INSERT OR REPLACE INTO stamps VALUES(?,?)',(key,stamp))
            for missing in stamps:
                db.execute('DELETE FROM sources WHERE path=?',(missing,))
                db.execute('DELETE FROM stamps WHERE path=?',(missing,))
            rows = db.execute("SELECT path,symbols,snippet(sources,2,'[',']','…',16) FROM sources WHERE sources MATCH ? ORDER BY bm25(sources,5,10,1) LIMIT 5",
                              (' OR '.join('"'+term+'"*' for term in terms),)).fetchall()
            return '\n'.join(f'{path}\nSymbols: {symbols[:600]}\n{excerpt[:360]}' for path,symbols,excerpt in rows) or 'No matching indexed source files.'
    finally:
        db.close()
