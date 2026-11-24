"""SQLAlchemy engine and session foundation.

Connection details come from DATABASE_URL. Credentials are never logged.
"""

from collections.abc import Generator

from pgvector.psycopg import register_vector
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "connect")
def _register_pgvector(dbapi_connection, _connection_record) -> None:
    raw_connection = getattr(dbapi_connection, "driver_connection", dbapi_connection)
    register_vector(raw_connection)


@event.listens_for(Session, "before_flush")
def _ensure_workspace_tenancy(session: Session, flush_context, instances) -> None:
    """Ensure tenancy consistency and restrict default workspace assignment.

    In Phase 1.2:
    - Authenticated runtime paths require explicit workspace_id.
    - Silent defaulting to the default workspace is disallowed in production
      and in any session marked with strict_tenancy=True.
    - Preserves the chunk/document workspace consistency invariant.
    """
    if not session.new:
        return

    from app.db.models import Conversation, Document, DocumentChunk

    strict = session.info.get("strict_tenancy", False) or not get_settings().is_test
    allow_default = session.info.get("allow_default_workspace", False)

    with session.no_autoflush:
        default_ws_id = None
        for obj in list(session.new):
            if isinstance(obj, (Document, Conversation)):
                if getattr(obj, "workspace_id", None) is None:
                    if strict and not allow_default:
                        raise ValueError(
                            f"{obj.__class__.__name__} requires an explicit workspace_id. "
                            f"Ambient default workspace fallback is disabled."
                        )
                    if allow_default or (get_settings().is_test and not strict):
                        if default_ws_id is None:
                            from app.core.workspace_context import WorkspaceContextProvider
                            default_ws_id = WorkspaceContextProvider.get_default_workspace_id(session)
                        obj.workspace_id = default_ws_id

            elif isinstance(obj, DocumentChunk):
                doc_ws_id = None
                if obj.document is not None and obj.document.workspace_id is not None:
                    doc_ws_id = obj.document.workspace_id
                elif obj.document_id is not None:
                    doc = session.get(Document, obj.document_id)
                    if doc is not None:
                        doc_ws_id = doc.workspace_id

                if obj.workspace_id is None:
                    if doc_ws_id is not None:
                        obj.workspace_id = doc_ws_id
                    elif allow_default or (get_settings().is_test and not strict):
                        if default_ws_id is None:
                            from app.core.workspace_context import WorkspaceContextProvider
                            default_ws_id = WorkspaceContextProvider.get_default_workspace_id(session)
                        obj.workspace_id = default_ws_id
                    else:
                        raise ValueError("DocumentChunk requires a resolvable workspace_id matching its parent Document.")
                elif doc_ws_id is not None and obj.workspace_id != doc_ws_id:
                    raise ValueError(
                        f"DocumentChunk workspace_id ({obj.workspace_id}) does not match "
                        f"parent Document workspace_id ({doc_ws_id})"
                    )



def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped SQLAlchemy session.

    This dependency does not commit. Document ingestion owns its transaction
    inside DocumentService so a FAILED status can be persisted even when the
    request then raises an error response for the client.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_connection() -> None:
    """Verify PostgreSQL connectivity and that pgvector is available."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            extension = connection.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            ).scalar()
    except SQLAlchemyError:
        logger.exception("Database connection failed")
        raise

    if extension is None:
        logger.warning(
            "Database connected, but the pgvector extension is not enabled. "
            "Run Alembic migrations."
        )
    else:
        logger.info("Database connection successful; pgvector extension is enabled")


def dispose_engine() -> None:
    engine.dispose()
