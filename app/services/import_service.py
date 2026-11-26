"""Safe, bounded CSV import preview, duplicate detection, and idempotent commit service."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.database import db_session
from app.repositories import accounts_repo, categories_repo, transactions_repo
from app.services import categorization_service
from app.utils.errors import ConflictError, NotFoundError, ValidationError
from app.utils.money import format_inr_minor, parse_inr_to_minor
from app.utils.time import utc_now_iso

MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_CSV_ROWS = 5_000


def _decode_csv_bytes(raw: bytes) -> str:
    if len(raw) > MAX_CSV_BYTES:
        raise ValidationError("CSV file exceeds 2 MiB limit.", field="csv_content")
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValidationError("Unsupported CSV text encoding.", field="csv_content")


def _parse_csv_date(raw: str, date_format: str) -> str:
    s = raw.strip()
    fmts = {
        "YYYY-MM-DD": ["%Y-%m-%d"],
        "DD/MM/YYYY": ["%d/%m/%Y"],
        "DD-MM-YYYY": ["%d-%m-%Y"],
        "auto": ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"],
    }
    for fmt in fmts.get(date_format, ["%Y-%m-%d"]):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date '{s}'")


def preview_csv_import(
    db_path: Path | str,
    *,
    csv_bytes: bytes,
    account_id: int,
    mapping: dict[str, str],
    date_format: str = "auto",
) -> dict[str, Any]:
    """Parse and validate CSV rows without mutating the financial ledger."""
    text = _decode_csv_bytes(csv_bytes)
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValidationError("CSV file has no header row.", field="csv_content")

    date_col = mapping.get("date", "date")
    desc_col = mapping.get("description", "description")
    merch_col = mapping.get("merchant", "merchant")
    amt_col = mapping.get("amount", "amount")
    type_col = mapping.get("entry_type", "entry_type")

    with db_session(db_path) as conn:
        acct = accounts_repo.get_account_by_id(conn, account_id)
        if acct is None or int(acct["is_archived"]) == 1:
            raise NotFoundError("Destination account not found.", field="account_id")
        exp_cats = categories_repo.list_categories(conn, kind="expense")
        inc_cats = categories_repo.list_categories(conn, kind="income")
        default_exp_cat = int(exp_cats[0]["id"])
        default_inc_cat = int(inc_cats[0]["id"])
        existing_sig_rows = conn.execute(
            """
            SELECT t.tx_date, t.entry_type, p.signed_amount_minor, LOWER(TRIM(t.description)) AS desc_l
            FROM transactions t
            JOIN postings p ON p.transaction_id = t.id
            WHERE t.deleted_at IS NULL AND p.account_id = ?;
            """,
            (account_id,),
        ).fetchall()

    existing_exact = {
        (
            str(r["tx_date"]),
            str(r["entry_type"]),
            abs(int(r["signed_amount_minor"])),
            str(r["desc_l"]),
        )
        for r in existing_sig_rows
    }
    existing_possible = {
        (str(r["tx_date"]), abs(int(r["signed_amount_minor"]))) for r in existing_sig_rows
    }

    parsed_rows: list[dict[str, Any]] = []
    valid_count = 0
    dup_count = 0
    invalid_count = 0

    for idx, row in enumerate(reader, start=1):
        if idx > MAX_CSV_ROWS:
            raise ValidationError(f"CSV exceeds maximum {MAX_CSV_ROWS} rows.", field="csv_content")
        if not any((v or "").strip() for v in row.values()):
            continue
        try:
            tx_date = _parse_csv_date(str(row.get(date_col) or ""), date_format)
            raw_amt = str(row.get(amt_col) or "").strip()
            etype_raw = str(row.get(type_col) or "").strip().lower()
            if etype_raw in ("income", "credit", "cr"):
                etype = "income"
            elif etype_raw in ("expense", "debit", "dr", ""):
                etype = "expense"
            else:
                raise ValueError(f"Unsupported entry_type '{etype_raw}'")
            amt_minor = parse_inr_to_minor(raw_amt.lstrip("-"), field="amount")
            desc = str(row.get(desc_col) or "").strip()[:240]
            merch = str(row.get(merch_col) or "").strip()[:120]

            sug = categorization_service.suggest_category(
                db_path, entry_type=etype, merchant=merch, description=desc
            )
            cat_id = (
                sug["category_id"]
                if sug
                else (default_inc_cat if etype == "income" else default_exp_cat)
            )

            sig_exact = (tx_date, etype, amt_minor, desc.lower())
            sig_poss = (tx_date, amt_minor)
            if sig_exact in existing_exact:
                status = "duplicate"
                dup_count += 1
            elif sig_poss in existing_possible:
                status = "possible_duplicate"
                valid_count += 1
            else:
                status = "valid"
                valid_count += 1

            parsed_rows.append(
                {
                    "row_number": idx,
                    "status": status,
                    "tx_date": tx_date,
                    "entry_type": etype,
                    "amount_minor": amt_minor,
                    "amount_formatted": format_inr_minor(amt_minor),
                    "description": desc,
                    "merchant": merch,
                    "category_id": cat_id,
                    "reason": "",
                }
            )
        except Exception as exc:
            invalid_count += 1
            parsed_rows.append(
                {
                    "row_number": idx,
                    "status": "invalid",
                    "reason": str(exc)[:200],
                }
            )

    return {
        "batch_uuid": str(uuid.uuid4()),
        "headers": list(reader.fieldnames),
        "total_rows": len(parsed_rows),
        "valid_count": valid_count,
        "duplicate_count": dup_count,
        "invalid_count": invalid_count,
        "rows": parsed_rows,
    }


def commit_csv_import(
    db_path: Path | str,
    *,
    batch_uuid: str,
    source_filename: str,
    account_id: int,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Atomically commit reviewed valid CSV rows with idempotency protection."""
    now = utc_now_iso()
    with db_session(db_path, immediate=True) as conn:
        existing = conn.execute(
            "SELECT * FROM import_batches WHERE batch_uuid = ?;", (batch_uuid,)
        ).fetchone()
        if existing is not None:
            return {
                "batch_id": int(existing["id"]),
                "batch_uuid": batch_uuid,
                "inserted_count": int(existing["inserted_count"]),
                "skipped_count": int(existing["skipped_count"]),
                "rejected_count": int(existing["rejected_count"]),
                "idempotent_replay": True,
            }

        acct = accounts_repo.get_account_by_id(conn, account_id)
        if acct is None or int(acct["is_archived"]) == 1:
            raise NotFoundError("Destination account not found.", field="account_id")

        inserted = 0
        skipped = 0
        rejected = 0
        batch_row_logs: list[tuple[int, int | None, str, str]] = []

        for item in rows:
            rnum = int(item.get("row_number") or 0)
            st = str(item.get("status") or "")
            if st == "duplicate":
                skipped += 1
                batch_row_logs.append((rnum, None, "skipped_duplicate", "Duplicate skipped"))
                continue
            if st == "invalid":
                rejected += 1
                batch_row_logs.append(
                    (rnum, None, "rejected", str(item.get("reason") or "Invalid")[:240])
                )
                continue
            if st not in ("valid", "possible_duplicate"):
                raise ConflictError("Invalid import row status.")

            etype = str(item["entry_type"])
            amt_minor = int(item["amount_minor"])
            signed = amt_minor if etype == "income" else -amt_minor
            tx_id = transactions_repo.create_multi_posting_transaction(
                conn,
                entry_type=etype,
                tx_date=str(item["tx_date"]),
                description=str(item.get("description") or "")[:240],
                merchant=str(item.get("merchant") or "")[:120],
                payment_method="other",
                is_split=False,
                idempotency_key=f"csv-{batch_uuid}-{rnum}",
                postings=[(account_id, int(item["category_id"]), signed)],
                now=now,
            )
            inserted += 1
            batch_row_logs.append((rnum, tx_id, "inserted", ""))

        cur = conn.execute(
            """
            INSERT INTO import_batches (
                batch_uuid, source_filename, account_id, total_rows,
                inserted_count, skipped_count, rejected_count, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'committed', ?);
            """,
            (
                batch_uuid,
                source_filename[:255],
                account_id,
                len(rows),
                inserted,
                skipped,
                rejected,
                now,
            ),
        )
        batch_id = int(cur.lastrowid)
        for rnum, tx_id, r_status, reason in batch_row_logs:
            conn.execute(
                """
                INSERT INTO import_batch_rows (batch_id, row_number, transaction_id, status, reason)
                VALUES (?, ?, ?, ?, ?);
                """,
                (batch_id, rnum, tx_id, r_status, reason),
            )

    return {
        "batch_id": batch_id,
        "batch_uuid": batch_uuid,
        "inserted_count": inserted,
        "skipped_count": skipped,
        "rejected_count": rejected,
        "idempotent_replay": False,
    }


def list_import_history(db_path: Path | str) -> list[dict[str, Any]]:
    with db_session(db_path) as conn:
        rows = conn.execute("SELECT * FROM import_batches ORDER BY id DESC LIMIT 50;").fetchall()
    return [dict(r) for r in rows]
