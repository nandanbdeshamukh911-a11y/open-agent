from typing import Literal
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import browser

router = APIRouter(prefix='/api/browser')


class Navigate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    viewport: Literal['desktop', 'mobile'] = 'desktop'


class Point(BaseModel):
    x: int = Field(ge=0, lt=browser.WIDTH)
    y: int = Field(ge=0, lt=max(height for _, height in browser.VIEWPORTS.values()))
    revision: int = Field(gt=0)


class Fill(BaseModel):
    label: str = Field(min_length=1, max_length=250)
    value: str = Field(max_length=2000)
    revision: int = Field(gt=0)

class Click(BaseModel):
    role: str
    name: str
    revision: int = Field(gt=0)

class Scroll(BaseModel):
    distance: int = Field(ge=-720, le=720)
    revision: int = Field(gt=0)


def call(action, key='manual', args=None):
    if key != 'manual' and not (key.startswith('task-') and key[5:].isascii() and key[5:].isdigit()):
        raise HTTPException(404, 'Unknown browser session.')
    try:
        return browser.service.call(action, key, args)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, 'Browser action failed. Check the URL and target, or open a new session.') from exc


@router.get('/sessions')
def list_sessions():
    return call('list')


@router.post('/open')
def open_page(body: Navigate):
    return call('browser_open', args=body.model_dump())


@router.get('/sessions/{key}')
def get_session(key: str):
    return call('state', key)


@router.get('/sessions/{key}/image')
def screenshot(key: str, revision: int):
    return Response(call('image', key, {'revision': revision}), media_type='image/jpeg',
                    headers={'Cache-Control': 'no-store'})


@router.post('/sessions/{key}/inspect')
def inspect(key: str):
    return call('browser_inspect', key)


@router.delete('/sessions/{key}')
def close(key: str):
    call('close', key)
    return {'ok': True}


@router.post('/point')
def click(body: Point):
    return call('point', args=body.model_dump())


@router.post('/fill')
def fill(body: Fill):
    return call('browser_fill', args=body.model_dump())


@router.post('/click')
def click_control(body: Click):
    try:
        args = browser.prepare_action('browser_click', body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return call('browser_click', args=args)


@router.post('/scroll')
def scroll(body: Scroll):
    return call('scroll', args=body.model_dump())
