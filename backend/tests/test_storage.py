from pathlib import Path
from uuid import uuid4

from app.services.storage import ORIGINAL_FILENAME, LocalDocumentStorage


def test_storage_uses_generated_id_and_fixed_filename(tmp_path):
    storage = LocalDocumentStorage(str(tmp_path))
    document_id = uuid4()
    data = b"%PDF-1.4\ntest"

    stored = storage.save_original(document_id, data)

    expected = tmp_path / str(document_id) / ORIGINAL_FILENAME
    assert stored == str(expected)
    assert expected.is_file()
    assert expected.read_bytes() == data
    assert expected.name == "original.pdf"
    assert str(document_id) in stored
    assert ".." not in stored


def test_storage_does_not_use_original_filename(tmp_path):
    storage = LocalDocumentStorage(str(tmp_path))
    document_id = uuid4()

    stored = storage.save_original(document_id, b"%PDF-1.4\n")

    assert "evil.pdf" not in stored
    assert "../" not in stored
    assert (tmp_path / str(document_id) / "original.pdf").is_file()
    assert list(tmp_path.iterdir()) == [tmp_path / str(document_id)]


def test_storage_delete_removes_directory(tmp_path):
    storage = LocalDocumentStorage(str(tmp_path))
    document_id = uuid4()
    stored = Path(storage.save_original(document_id, b"%PDF-1.4\ntest"))
    assert stored.is_file()

    storage.delete_original(document_id)

    assert not stored.exists()
    assert not stored.parent.exists()
    assert list(tmp_path.iterdir()) == []


def test_storage_delete_missing_directory_is_ok(tmp_path):
    storage = LocalDocumentStorage(str(tmp_path))
    storage.delete_original(uuid4())
    assert list(tmp_path.iterdir()) == []
