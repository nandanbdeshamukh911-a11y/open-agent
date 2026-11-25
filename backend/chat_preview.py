"""Find standalone pages in saved chat replies and render them offline."""
import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from . import browser_api, store

router = APIRouter(prefix='/api/chats')
DOCUMENT_START = re.compile(r'^\s*(?:<!doctype\s+html\b|<html(?=[\s>]))', re.I)
HTML_FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})[ \t]*html[ \t]*\r?\n', re.I | re.M)
DOCUMENT_END = re.compile(r'</html\s*>', re.I)


def extract_page(content):
    """Open a full document, including one cut short by the model."""
    candidates = []
    for fence in HTML_FENCE.finditer(content):
        marker = fence[1]
        remainder = content[fence.end():]
        closing = re.search(r'^ {0,3}' + marker[0] + '{' + str(len(marker)) + r',}[ \t]*\r?$', remainder, re.M)
        candidates.append(remainder[:closing.start()] if closing else remainder)
    candidates.append(content)
    for source in candidates:
        if not DOCUMENT_START.match(source):
            continue
        ends = list(DOCUMENT_END.finditer(source))
        return (source[:ends[-1].end()].strip(), True) if ends else (source.strip(), False)
    return None


class OpenPreview(BaseModel):
    message_id: int
    viewport: Literal['desktop', 'mobile'] = 'desktop'


def saved_page(chat_id, message_id):
    message = store.query(
        "SELECT content FROM chat_messages WHERE chat_id=? AND id=? AND role='assistant'", (chat_id, message_id), True,
    )
    page = extract_page(message['content']) if message else None
    if page is None:
        raise HTTPException(404, 'This reply does not contain a standalone HTML page.')
    return page


@router.post('/{chat_id}/preview')
def open_preview(chat_id: int, body: OpenPreview):
    source, complete = saved_page(chat_id, body.message_id)
    preview = browser_api.call('browser_project', f'chat-{chat_id}', {
        'document': source.encode('utf-8'), 'viewport': body.viewport,
    })
    return {**preview, 'complete': complete}


@router.get('/{chat_id}/preview/source/{message_id}')
def download_source(chat_id: int, message_id: int):
    source, _ = saved_page(chat_id, message_id)
    return Response(source, media_type='application/octet-stream', headers={
        'Content-Disposition': 'attachment; filename="index.html"',
        'X-Content-Type-Options': 'nosniff',
    })


@router.post('/{chat_id}/preview/point')
def click_preview(chat_id: int, body: browser_api.Point):
    return browser_api.call('point', f'chat-{chat_id}', body.model_dump())


@router.post('/{chat_id}/preview/scroll')
def scroll_preview(chat_id: int, body: browser_api.Scroll):
    return browser_api.call('scroll', f'chat-{chat_id}', body.model_dump())
