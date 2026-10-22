from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from travel.provider import TravelFailure
from travel.schemas import Error, ErrorResponse
from travel.store import Store
from travel.tasks import TaskManager
from travel.auth import AuthService
from travel.map_proxy import MapProxy


@asynccontextmanager
async def lifespan(app):
    default_path = Path(__file__).resolve().parents[1] / "data" / "travel.sqlite3"
    store = Store(Path(os.getenv("TRAVEL_DB_PATH", str(default_path))))
    try:
        app.state.auth=AuthService(store)
        app.state.travel = TaskManager(store, timeout=float(os.getenv("TRAVEL_TASK_TIMEOUT", "180")))
        app.state.map_proxy = MapProxy()
    except Exception:
        store.close()
        raise
    try:
        yield
    finally:
        await app.state.map_proxy.close()
        await app.state.travel.close()
        store.close()


def configure_errors(app):
    @app.exception_handler(TravelFailure)
    async def provider_error(request: Request, error: TravelFailure):
        body = ErrorResponse(error=Error(code=error.code, message=error.message, retryable=error.retryable, retry_after=error.retry_after, time_constraints=error.time_constraints, travel_constraints=error.travel_constraints))
        headers={"WWW-Authenticate":'Bearer realm="TravelAgent"'} if error.status==401 else {}
        if error.code=='login_rate_limited': headers['Retry-After']='300'
        if getattr(error, 'retry_after', None): headers['Retry-After']=str(error.retry_after)
        return JSONResponse(status_code=error.status, content=body.model_dump(),headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        if request.url.path.startswith("/api/v1/travel"):
            messages = [f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in error.errors()]
            return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "；".join(messages), "retryable": False}})
        from fastapi.exception_handlers import request_validation_exception_handler
        return await request_validation_exception_handler(request, error)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception):
        # Sanitized error; no tokens, URLs or raw provider responses exposed.
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "服务执行失败", "retryable": False}})
