"""Credential-free process/readiness probes; no provider calls or business data."""
import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix='/health', include_in_schema=False)


def probe(status, ready=True):
    return JSONResponse({'status': status}, status_code=200 if ready else 503,
                        headers={'Cache-Control': 'no-store'})


@router.get('/live')
def live():
    return probe('alive')


@router.get('/ready')
def ready(request: Request):
    store = getattr(getattr(request.app.state, 'travel', None), 'store', None)
    if store is None or not store.lock.acquire(timeout=.1):
        return probe('unavailable', False)
    try:
        store.db.execute('SELECT id FROM tasks LIMIT 1').fetchone()
    except sqlite3.Error:
        return probe('unavailable', False)
    finally:
        store.lock.release()
    return probe('ready')
