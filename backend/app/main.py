"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.db.database import check_connection, dispose_engine

setup_logging()
logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logger.info("Application starting (env=%s)", settings.app_env)
    if not settings.is_test:
        check_connection()
        if settings.bootstrap_admin_email and settings.bootstrap_admin_password:
            from app.core.bootstrap import bootstrap_default_admin
            from app.db.database import SessionLocal
            with SessionLocal() as session:
                bootstrap_default_admin(session)
    yield
    logger.info("Application shutting down")
    dispose_engine()


app = FastAPI(
    title="RAG Knowledge Assistant",
    description=(
        "API for the RAG Knowledge Assistant. Upload PDFs, retrieve relevant "
        "passages, and ask grounded questions with authentication and workspace tenancy."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Workspace-Id", "X-Request-Id", "X-Trace-Id"],
    expose_headers=["X-Request-Id", "X-Trace-Id"],
)


@app.middleware("http")
async def tracing_headers_middleware(request, call_next):
    from app.core.request_context import extract_request_context

    ctx = extract_request_context(request)
    request.state.request_id = ctx.request_id
    request.state.trace_id = ctx.trace_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = ctx.request_id
    response.headers["X-Trace-Id"] = ctx.trace_id
    return response


register_exception_handlers(app)
app.include_router(api_v1_router, prefix="/api/v1")
