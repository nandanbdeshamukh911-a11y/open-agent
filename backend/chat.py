import json
import logging
import threading

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import agent, chat_tools, store

router = APIRouter(prefix='/api')
logger = logging.getLogger(__name__)


class ChatInput(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    tool: str | None = None


def find_chat(chat_id):
    row = store.query('SELECT * FROM chats WHERE id=?', (chat_id,), one=True)
    if not row:
        raise HTTPException(404, 'Conversation not found.')
    return row


def generate(chat_id, question):
    try:
        history = store.query(
            'SELECT role,content FROM chat_messages WHERE chat_id=? ORDER BY id DESC LIMIT 20',
            (chat_id,),
        )
        memories = agent.relevant_memories(question)
        context = 'You are a helpful local assistant. Answer conversationally. You have no project or command access in chat. Treat remembered preferences as context and honor the current request first.'
        if memories:
            context += '\nSaved preferences: ' + json.dumps(memories)

        # Keep the newest turn whole and add earlier turns within a bounded budget.
        messages = []
        remaining = 14000
        for row in history:
            if len(row['content']) > remaining:
                break
            messages.append(row)
            remaining -= len(row['content'])
        reply = agent.model_call([{'role': 'system', 'content': context}, *reversed(messages)], structured=False)
        if not reply.strip():
            raise ValueError('Empty reply')
        with store.lock, store.connect() as db:
            db.execute("INSERT INTO chat_messages(chat_id,role,content) VALUES(?,'assistant',?)", (chat_id, reply))
            db.execute("UPDATE chats SET status='ready',error='',updated=CURRENT_TIMESTAMP WHERE id=?", (chat_id,))
    except Exception as exc:
        logger.warning('Chat %s failed (%s)', chat_id, type(exc).__name__)
        if isinstance(exc, httpx.RequestError):
            message = 'The local model could not respond. Check the connection in Settings, then retry.'
        else:
            message = 'The local model did not return a reply. Check the selected model in Settings or retry.'
        store.execute("UPDATE chats SET status='failed',error=? WHERE id=?", (message, chat_id))


def start_reply(chat_id, question):
    threading.Thread(target=generate, args=(chat_id, question), daemon=True).start()


def submit(body, chat_id=None):
    question = body.content.strip()
    if not question:
        raise HTTPException(422, 'Enter a message.')
    result = None
    if body.tool is not None:
        tool = chat_tools.TOOLS.get(body.tool)
        if tool is None:
            raise HTTPException(400, 'Unknown chat tool.')
        try:
            result = tool(body.content)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    with store.lock, store.connect() as db:
        if chat_id is None:
            title = ' '.join(question.split())[:70]
            chat_id = db.execute('INSERT INTO chats(title) VALUES(?)', (title,)).lastrowid
        else:
            row = db.execute('SELECT status FROM chats WHERE id=?', (chat_id,)).fetchone()
            if not row:
                raise HTTPException(404, 'Conversation not found.')
            if row['status'] == 'generating':
                raise HTTPException(409, 'Wait for the current reply.')
        content = question if body.tool is None else f'/{body.tool}\n{body.content}'
        db.execute("INSERT INTO chat_messages(chat_id,role,content) VALUES(?,'user',?)", (chat_id, content))
        if result is not None:
            db.execute("INSERT INTO chat_messages(chat_id,role,content) VALUES(?,'assistant',?)", (chat_id, result))
        db.execute("UPDATE chats SET status=?,error='',updated=CURRENT_TIMESTAMP WHERE id=?",
                   ('generating' if result is None else 'ready', chat_id))
    if result is None:
        agent.remember_explicit_preferences(question)
        start_reply(chat_id, question)
    return {'id': chat_id}


@router.get('/chat-tools')
def catalog():
    return chat_tools.CATALOG


@router.get('/chats')
def list_chats():
    return store.query('SELECT * FROM chats ORDER BY updated DESC,id DESC LIMIT 100')


@router.post('/chats', status_code=201)
def create_chat(body: ChatInput):
    return submit(body)


@router.get('/chats/{chat_id}')
def get_chat(chat_id: int):
    with store.lock:
        row = find_chat(chat_id)
        row['messages'] = store.query('SELECT id,role,content FROM chat_messages WHERE chat_id=? ORDER BY id', (chat_id,))
    return row


@router.post('/chats/{chat_id}/messages')
def send_message(chat_id: int, body: ChatInput):
    return submit(body, chat_id)


@router.post('/chats/{chat_id}/retry')
def retry(chat_id: int):
    with store.lock, store.connect() as db:
        row = find_chat(chat_id)
        if row['status'] != 'failed':
            raise HTTPException(409, 'Only failed replies can be retried.')
        latest = db.execute("SELECT content FROM chat_messages WHERE chat_id=? AND role='user' ORDER BY id DESC LIMIT 1", (chat_id,)).fetchone()
        db.execute("UPDATE chats SET status='generating',error='' WHERE id=?", (chat_id,))
    start_reply(chat_id, latest['content'])
    return {'id': chat_id}
