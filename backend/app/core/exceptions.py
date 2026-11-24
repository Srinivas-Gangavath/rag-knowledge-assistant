"""Global exception handlers.

Responses stay user-friendly. Stack traces, credentials, and internal details
are logged server-side only — never returned to the client.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger
from app.services.ai.errors import AI_PUBLIC_ERROR_DETAIL, AIProviderError
from app.services.chat_errors import ChatServiceError
from app.services.document_errors import DocumentServiceError

logger = get_logger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": str(exc.detail)},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        safe_errors = [
            {
                "field": ".".join(str(part) for part in error.get("loc", [])),
                "message": error.get("msg"),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Request validation failed.",
                "errors": safe_errors,
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_exception_handler(
        request: Request,
        exc: SQLAlchemyError,
    ) -> JSONResponse:
        logger.exception(
            "Database error on %s %s",
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "A database error occurred. Please try again later."},
        )

    @app.exception_handler(AIProviderError)
    async def ai_provider_exception_handler(
        request: Request,
        exc: AIProviderError,
    ) -> JSONResponse:
        logger.exception(
            "AI provider error on %s %s (%s)",
            request.method,
            request.url.path,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=502,
            content={"detail": AI_PUBLIC_ERROR_DETAIL},
        )

    @app.exception_handler(DocumentServiceError)
    async def document_service_exception_handler(
        request: Request,
        exc: DocumentServiceError,
    ) -> JSONResponse:
        logger.warning(
            "Document error on %s %s (%s)",
            request.method,
            request.url.path,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.public_message},
        )

    @app.exception_handler(ChatServiceError)
    async def chat_service_exception_handler(
        request: Request,
        exc: ChatServiceError,
    ) -> JSONResponse:
        logger.warning(
            "Chat error on %s %s (%s)",
            request.method,
            request.url.path,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.public_message},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception(
            "Unhandled error on %s %s",
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected error occurred. Please try again later."},
        )
