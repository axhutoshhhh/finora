"""Complete workspace backup (.zip + manifest + SHA-256) and safe staged restoration."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from app.utils.errors import ValidationError
from app.utils.time import utc_now_iso

BACKUP_FORMAT_VERSION = 1
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def create_workspace_backup(
    data_dir: Path, db_path: Path, *, dest_zip: Path | None = None
) -> dict[str, Any]:
    """Create a coherent SQLite + attachments ZIP backup with SHA-256 manifest."""
    backups_dir = data_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(backups_dir, 0o700)
    target_zip = dest_zip or (backups_dir / f"finora-backup-{utc_now_iso().replace(':', '-')}.zip")

    with tempfile.TemporaryDirectory() as td:
        tmp_db = Path(td) / "finance.sqlite3"
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(tmp_db)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

        files_manifest: dict[str, str] = {"finance.sqlite3": _sha256_file(tmp_db)}
        att_dir = data_dir / "attachments"
        att_files: list[tuple[Path, str]] = []
        if att_dir.exists():
            for f in sorted(att_dir.iterdir()):
                if f.is_file():
                    rel = f"attachments/{f.name}"
                    files_manifest[rel] = _sha256_file(f)
                    att_files.append((f, rel))

        manifest = {
            "format_version": BACKUP_FORMAT_VERSION,
            "created_at": utc_now_iso(),
            "files": files_manifest,
        }
        tmp_zip = Path(td) / "backup.zip"
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
            zf.write(tmp_db, "finance.sqlite3")
            for f, rel in att_files:
                zf.write(f, rel)
        shutil.move(str(tmp_zip), str(target_zip))
        os.chmod(target_zip, 0o600)

    return {"backup_path": str(target_zip), "file_count": len(files_manifest)}


def restore_workspace_backup(data_dir: Path, db_path: Path, backup_zip: Path) -> dict[str, Any]:
    """Validate archive safety, manifest checksums, and SQLite integrity, then atomically restore."""
    if not backup_zip.exists() or not backup_zip.is_file():
        raise ValidationError("Backup file not found.", field="backup_path")

    with zipfile.ZipFile(backup_zip, "r") as zf:
        infos = zf.infolist()
        total_uncompressed = 0
        seen_names: set[str] = set()
        for info in infos:
            name = info.filename
            if name in seen_names:
                raise ValidationError("Duplicate entry in backup archive.")
            seen_names.add(name)
            if name.startswith("/") or name.startswith("\\") or ".." in Path(name).parts:
                raise ValidationError("Unsafe path in backup archive.")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValidationError("Symlinks are not permitted in backup archives.")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise ValidationError("Backup archive exceeds maximum safe extracted size.")

        if "manifest.json" not in seen_names or "finance.sqlite3" not in seen_names:
            raise ValidationError("Backup archive is missing required manifest or database.")

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        if int(manifest.get("format_version") or 0) > BACKUP_FORMAT_VERSION:
            raise ValidationError("Unsupported future backup format version.")
        expected_files: dict[str, str] = manifest.get("files") or {}

        with tempfile.TemporaryDirectory() as td:
            stage = Path(td) / "stage"
            stage.mkdir(parents=True, exist_ok=True)
            for rel, expected_hash in expected_files.items():
                if rel not in seen_names:
                    raise ValidationError(f"Missing expected file in backup: {rel}")
                out_path = stage / rel
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(zf.read(rel))
                if _sha256_file(out_path) != expected_hash:
                    raise ValidationError(f"Checksum mismatch for {rel}.")

            staged_db = stage / "finance.sqlite3"
            chk = sqlite3.connect(staged_db)
            try:
                res = chk.execute("PRAGMA integrity_check;").fetchone()
                if not res or res[0] != "ok":
                    raise ValidationError("Restored database failed integrity check.")
            finally:
                chk.close()

            # Safety backup of current workspace before replacement
            if db_path.exists():
                create_workspace_backup(data_dir, db_path)

            shutil.copy2(staged_db, db_path)
            os.chmod(db_path, 0o600)
            att_stage = stage / "attachments"
            att_target = data_dir / "attachments"
            att_target.mkdir(parents=True, exist_ok=True)
            if att_stage.exists():
                for f in att_stage.iterdir():
                    if f.is_file():
                        dest = att_target / f.name
                        shutil.copy2(f, dest)
                        os.chmod(dest, 0o600)

    return {"restored": True, "file_count": len(expected_files)}
