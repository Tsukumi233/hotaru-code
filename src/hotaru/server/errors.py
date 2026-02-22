"""Error handlers for the FastAPI transport layer."""

from __future__ import annotations

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
) -> JSONResponse:
    payload = ErrorResponse(error=ErrorInfo(code=code, message=message, details=details))
    return JSONResponse(payload.model_dump(exclude_none=True), status_code=status_code)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return _error_response(status_code=400, code="bad_request", message=str(exc))

    @app.exception_handler(NotFoundError)
    async def not_found_error_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return _error_response(status_code=404, code="not_found", message=str(exc))

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
        )

    @app.exception_handler(Exception)
    async def exception_handler(request: Request, exc: Exception) -> JSONResponse:
        log.error("v1 route failed", {"error": str(exc)})
        return _error_response(
            status_code=500,
            code="internal_error",
            message="Internal server error",
            details={"error": str(exc)},
        )
