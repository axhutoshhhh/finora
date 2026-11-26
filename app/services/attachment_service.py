"""Secure local receipt and invoice attachment storage and validation."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from app.database import db_session, ensure_secure_data_dir
from app.repositories import attachments_repo, transactions_repo
from app.utils.errors import ConflictError, NotFoundError, ValidationError
from app.utils.time import utc_now_iso

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024  # 5 MiB per attachment
_STORED_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(?:png|jpg|pdf)$")


def _attachments_dir(db_path: Path | str) -> Path:
    return Path(db_path).parent / "attachments"


def _detect_magic_mime(raw_bytes: bytes) -> tuple[str, str]:
    """Verify actual binary signature regardless of client extension or Content-Type."""
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if raw_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if raw_bytes.startswith(b"%PDF-"):
        return "application/pdf", ".pdf"
    raise ValidationError(
        "Unsupported file format. Only valid PNG, JPEG, or PDF receipts are permitted.",
        code="unsupported_media_type",
        status_code=415,
        field="file",
    )


def _sanitize_original_filename(raw_name: str | None) -> str:
    if not raw_name:
        raise ValidationError("Filename is required.", field="file")
    stripped_slashes = raw_name.replace("\\", "/").split("/")[-1].strip()
    cleaned = "".join(ch for ch in stripped_slashes if ord(ch) >= 32 and ch not in "\x7f")
    if not cleaned or cleaned in {".", ".."} or ".." in cleaned and "/" in raw_name:
        cleaned = "receipt"
    if cleaned in {".", ".."}:
        cleaned = "receipt"
    if len(cleaned) > 160:
        stem, ext = os.path.splitext(cleaned)
        cleaned = f"{stem[:140]}{ext[:20]}"
    return cleaned


def save_attachment(
    db_path: Path | str,
    *,
    transaction_id: int,
    original_filename: str | None,
    raw_bytes: bytes,
) -> dict[str, Any]:
    """Validate, write atomically outside repo/.app, and attach a receipt to a transaction."""
    if not raw_bytes:
        raise ValidationError("Uploaded file is empty.", field="file")
    if len(raw_bytes) > MAX_ATTACHMENT_BYTES:
        raise ValidationError(
            "Attachment exceeds the maximum allowed size of 5 MiB.",
            code="payload_too_large",
            status_code=413,
            field="file",
        )

    mime_type, canonical_ext = _detect_magic_mime(raw_bytes)
    display_name = _sanitize_original_filename(original_filename)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    att_dir = _attachments_dir(db_path)
    ensure_secure_data_dir(att_dir)

    stored_filename = f"{uuid.uuid4().hex}{canonical_ext}"
    tmp_path = att_dir / f".staging_{uuid.uuid4().hex}"
    final_path = att_dir / stored_filename

    try:
        fd = os.open(os.fspath(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            view = memoryview(raw_bytes)
            written = 0
            while written < len(view):
                written += os.write(fd, view[written:])
        finally:
            os.close(fd)
        os.replace(tmp_path, final_path)
        os.chmod(final_path, 0o600)
    except Exception:
        with suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        with suppress(OSError):
            final_path.unlink(missing_ok=True)
        raise

    try:
        with db_session(db_path, immediate=True) as conn:
            tx_rows = transactions_repo.get_transaction_rows_by_id(conn, transaction_id)
            if not tx_rows:
                raise NotFoundError("Transaction not found.", field="transaction_id")
            if tx_rows[0]["deleted_at"] is not None:
                raise ConflictError("Restore deleted transaction before attaching receipts.")

            now = utc_now_iso()
            att_id = attachments_repo.create_attachment(
                conn,
                transaction_id=transaction_id,
                original_filename=display_name,
                stored_filename=stored_filename,
                mime_type=mime_type,
                size_bytes=len(raw_bytes),
                sha256=sha256,
                now=now,
            )
            return {
                "id": att_id,
                "transaction_id": transaction_id,
                "original_filename": display_name,
                "mime_type": mime_type,
                "size_bytes": len(raw_bytes),
                "created_at": now,
            }
    except Exception:
        with suppress(OSError):
            final_path.unlink(missing_ok=True)
        raise


def get_attachment_for_download(
    db_path: Path | str, attachment_id: int
) -> tuple[dict[str, Any], Path]:
    """Validate stored attachment path safely and return (metadata, resolved_path)."""
    with db_session(db_path) as conn:
        row = attachments_repo.get_attachment_by_id(conn, attachment_id)
        if row is None:
            raise NotFoundError("Attachment not found.")
        stored_name = str(row["stored_filename"])
        if not _STORED_NAME_RE.fullmatch(stored_name):
            raise ValidationError("Attachment storage reference is invalid.")

        att_dir = _attachments_dir(db_path).resolve()
        candidate = (att_dir / stored_name).resolve()
        if candidate.parent != att_dir or not candidate.is_file():
            raise NotFoundError("Attachment file is missing on disk.")

        meta = {
            "id": int(row["id"]),
            "transaction_id": int(row["transaction_id"]),
            "original_filename": str(row["original_filename"]),
            "mime_type": str(row["mime_type"]),
            "size_bytes": int(row["size_bytes"]),
            "created_at": str(row["created_at"]),
        }
        return meta, candidate


def delete_attachment(db_path: Path | str, attachment_id: int) -> dict[str, Any]:
    """Remove attachment metadata atomically and unlink local file cleanly."""
    stored_name: str | None = None
    with db_session(db_path, immediate=True) as conn:
        row = attachments_repo.get_attachment_by_id(conn, attachment_id)
        if row is None:
            raise NotFoundError("Attachment not found.")
        stored_name = str(row["stored_filename"])
        attachments_repo.delete_attachment(conn, attachment_id)

    if stored_name and _STORED_NAME_RE.fullmatch(stored_name):
        target = (_attachments_dir(db_path).resolve() / stored_name).resolve()
        if target.parent == _attachments_dir(db_path).resolve():
            target.unlink(missing_ok=True)
    return {"deleted": True, "id": attachment_id}
