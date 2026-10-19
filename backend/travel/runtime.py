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


@asynccontextmanager
async def lifespan(app):
    default_path = Path(__file__).resolve().parents[1] / "data" / "travel.sqlite3"
    store = Store(Path(os.getenv("TRAVEL_DB_PATH", str(default_path))))
    app.state.travel = TaskManager(store, timeout=float(os.getenv("TRAVEL_TASK_TIMEOUT", "180")))
    try:
        yield
    finally:
        await app.state.travel.close()
        store.close()


def configure_errors(app):
    @app.exception_handler(TravelFailure)
    async def provider_error(request: Request, error: TravelFailure):
        body = ErrorResponse(error=Error(code=error.code, message=error.message, retryable=error.retryable))
        return JSONResponse(status_code=error.status, content=body.model_dump())

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
