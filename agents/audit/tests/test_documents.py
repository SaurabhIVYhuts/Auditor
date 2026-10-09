"""Tests for the document store placeholder (shared/documents.py)."""
import hashlib
import uuid

import pytest

import shared.documents as documents
from shared.config import settings
from shared.documents import DocumentRejected, read_document, store_document, verify_document

PDF = b"%PDF-1.4 demo invoice content"


@pytest.fixture(autouse=True)
def temp_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))
    return tmp_path


def store(db, tenant=None, filename="invoice.pdf", content_type="application/pdf", data=PDF):
    return store_document(db, tenant or uuid.uuid4(), filename, content_type, data, uploaded_by=uuid.uuid4())


def test_store_and_read_back_same_bytes_and_hash(db_session, temp_storage):
    doc = store(db_session)
    assert doc.sha256 == hashlib.sha256(PDF).hexdigest() and doc.size_bytes == len(PDF)
    assert doc.storage_key == f"{doc.tenant_id}/{doc.id}"
    stored, data = read_document(db_session, doc.tenant_id, doc.id)
    assert stored.id == doc.id and data == PDF
    assert verify_document(db_session, doc.tenant_id, doc.id) is True


def test_too_big_is_refused(db_session, monkeypatch):
    monkeypatch.setattr(settings, "document_max_bytes", 10)
    with pytest.raises(DocumentRejected, match="larger than"):
        store(db_session)


@pytest.mark.parametrize("filename,content_type", [
    ("tool.exe", "application/octet-stream"),        # extension not allowed
    ("invoice.pdf", "image/png"),                    # content type does not match the extension
    ("noextension", "application/pdf"),
])
def test_wrong_type_is_refused(db_session, filename, content_type):
    with pytest.raises(DocumentRejected):
        store(db_session, filename=filename, content_type=content_type)


def test_empty_file_is_refused(db_session):
    with pytest.raises(DocumentRejected, match="empty"):
        store(db_session, data=b"")


def test_path_in_filename_is_dropped(db_session):
    doc = store(db_session, filename="..\\..\\secret/invoice.pdf")
    assert doc.filename == "invoice.pdf"


def test_other_hospital_gets_none(db_session):
    doc = store(db_session)
    assert read_document(db_session, uuid.uuid4(), doc.id) is None
    with pytest.raises(LookupError):
        verify_document(db_session, uuid.uuid4(), doc.id)


def test_tampering_with_the_file_makes_verify_false(db_session, temp_storage):
    doc = store(db_session)
    (temp_storage / doc.storage_key).write_bytes(PDF + b" changed")
    assert verify_document(db_session, doc.tenant_id, doc.id) is False


def test_missing_file_is_not_verified(db_session, temp_storage):
    doc = store(db_session)
    (temp_storage / doc.storage_key).unlink()
    assert verify_document(db_session, doc.tenant_id, doc.id) is False


def test_module_offers_no_update_or_delete():
    public = {name for name in dir(documents) if not name.startswith("_")}
    assert not {n for n in public if n.startswith(("update", "delete", "remove", "replace"))}
