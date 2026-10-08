"""Document store: keeps uploaded files and their SHA-256 fingerprint.

Placeholder until the platform Document Service exists; keep the function signatures.
When the platform service is available, replace the bodies of these functions with calls to
it (scan, storage, signed URLs); callers do not change.

Files are written once and never changed: there are deliberately NO update or delete functions.
The stored file name is generated (hospital id + document id), never taken from the upload, so a
file name can not point outside the storage folder. Functions flush, they never commit.
"""
import hashlib
import os
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import CHAR, DateTime, String, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from shared.config import settings
from shared.models import SharedBase

# Allowed file types: extension -> accepted content types.
ALLOWED_TYPES: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"application/pdf"}),
    ".png": frozenset({"image/png"}),
    ".jpg": frozenset({"image/jpeg"}),
    ".jpeg": frozenset({"image/jpeg"}),
    ".xlsx": frozenset({"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}),
    ".csv": frozenset({"text/csv", "application/vnd.ms-excel"}),
    ".txt": frozenset({"text/plain"}),
}


class DocumentRejected(ValueError):
    """The file cannot be stored (empty, too big, or a type that is not allowed)."""


class Document(SharedBase):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    filename: Mapped[str] = mapped_column(String(255))          # original name, for display only
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(CHAR(64))
    storage_key: Mapped[str] = mapped_column(String(200), unique=True)   # "<tenant_id>/<document_id>"
    uploaded_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def _path(storage_key: str) -> Path:
    return Path(settings.document_storage_dir) / storage_key


def scan_hook(data: bytes) -> None:
    """Virus scan by Document Service. No-op in this placeholder."""


def _check(filename: str, content_type: str, data: bytes) -> None:
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_TYPES:
        raise DocumentRejected(
            f"File type {extension or '(none)'} is not allowed. Allowed: {', '.join(sorted(ALLOWED_TYPES))}")
    if content_type not in ALLOWED_TYPES[extension]:
        raise DocumentRejected(f"Content type {content_type!r} does not match a {extension} file")
    if not data:
        raise DocumentRejected("The file is empty")
    if len(data) > settings.document_max_bytes:
        limit_mb = settings.document_max_bytes / (1024 * 1024)
        raise DocumentRejected(f"The file is larger than the {limit_mb:g} MB limit")


def store_document(
    db: Session, tenant_id: uuid.UUID, filename: str, content_type: str, data: bytes,
    uploaded_by: uuid.UUID | None,
) -> Document:
    """Check, scan, fingerprint and store a file once. Raises DocumentRejected for a bad file."""
    filename = os.path.basename(filename.replace("\\", "/"))[:255]   # keep only the name, never a path
    _check(filename, content_type, data)
    scan_hook(data)
    document = Document(id=uuid.uuid4(), tenant_id=tenant_id, filename=filename, content_type=content_type,
                        size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), uploaded_by=uploaded_by)
    document.storage_key = f"{tenant_id}/{document.id}"
    path = _path(document.storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as file:                                   # "x": refuse to overwrite an existing file
        file.write(data)
    db.add(document)
    db.flush()
    return document


def _get(db: Session, tenant_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
    document = db.get(Document, document_id)
    return document if document is not None and document.tenant_id == tenant_id else None


def read_document(db: Session, tenant_id: uuid.UUID, document_id: uuid.UUID) -> tuple[Document, bytes] | None:
    """The document and its bytes, or None if it does not exist for this hospital."""
    document = _get(db, tenant_id, document_id)
    if document is None:
        return None
    return document, _path(document.storage_key).read_bytes()


def verify_document(db: Session, tenant_id: uuid.UUID, document_id: uuid.UUID) -> bool:
    """True if the stored bytes still match the fingerprint taken at upload.

    A missing file also counts as not verified. Raises LookupError if there is no such
    document for this hospital (so "not found" is never confused with "changed").
    """
    document = _get(db, tenant_id, document_id)
    if document is None:
        raise LookupError("Document not found")
    try:
        data = _path(document.storage_key).read_bytes()
    except FileNotFoundError:
        return False
    return hashlib.sha256(data).hexdigest() == document.sha256
