import shutil
from pathlib import Path
from uuid import UUID

from app.core.logging import get_logger
from app.services.document_errors import StorageError

logger = get_logger(__name__)

ORIGINAL_FILENAME = "original.pdf"


class LocalDocumentStorage:
    """Store originals as storage/documents/<document-id>/original.pdf."""

    def __init__(self, root: str) -> None:
        self._root = Path(root)

    def save_original(self, document_id: UUID, data: bytes) -> str:
        directory = self._safe_document_directory(document_id)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            destination = directory / ORIGINAL_FILENAME
            destination.write_bytes(data)
        except OSError as exc:
            logger.error("Document storage failed (%s)", type(exc).__name__)
            raise StorageError() from exc

        logger.info("Stored original PDF for document_id=%s", document_id)
        return str(destination)

    def _safe_document_directory(self, document_id: UUID) -> Path:
        base = self._root.resolve()
        directory = (base / str(document_id)).resolve()
        if base not in directory.parents:
            logger.error("Rejected document storage path outside the storage root")
            raise StorageError()
        return directory

    def delete_original(self, document_id: UUID) -> None:
        directory = self._safe_document_directory(document_id)
        if not directory.exists():
            return
        try:
            shutil.rmtree(directory)
        except OSError as exc:
            logger.error("Document storage delete failed (%s)", type(exc).__name__)
            raise StorageError() from exc
        logger.info("Removed stored original for document_id=%s", document_id)
