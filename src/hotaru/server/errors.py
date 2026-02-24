"""Error handlers for the FastAPI transport layer."""

from __future__ import annotations

import traceback

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..app_services.errors import NotFoundError
from ..util.log import Log
from .schemas import ErrorInfo, ErrorResponse

log = Log.create({"service": "server.errors"})


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object] | list[object] | str | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    payload = ErrorResponse(error=ErrorInfo(code=code, message=message, details=details))
    response = JSONResponse(payload.model_dump(exclude_none=True), status_code=status_code)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


def register_error_handlers(app: FastAPI) -> None:
    def request_id(request: Request) -> str | None:
        rid = getattr(request.state, "request_id", None)
        if isinstance(rid, str) and rid:
            return rid
        return None

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return _error_response(
            status_code=400,
            code="bad_request",
            message=str(exc),
            request_id=request_id(request),
        )

    @app.exception_handler(NotFoundError)
    async def not_found_error_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return _error_response(
            status_code=404,
            code="not_found",
            message=str(exc),
            request_id=request_id(request),
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            status_code=422,
            code="validation_error",
            message="Request validation failed",
            details={"errors": exc.errors()},
            request_id=request_id(request),
        )

    @app.exception_handler(Exception)
    async def exception_handler(request: Request, exc: Exception) -> JSONResponse:
        log.error(
            "v1 route failed",
            {
                "request_id": request_id(request),
                "method": request.method,
                "path": request.url.path,
                "query": request.url.query or None,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                ),
            },
        )
        return _error_response(
            status_code=500,
            code="internal_error",
            message="Internal server error",
            details={"error": str(exc)},
            request_id=request_id(request),
        )
