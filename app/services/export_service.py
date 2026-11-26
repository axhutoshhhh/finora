"""Formula-injection-safe CSV export and offline PDF financial report generator."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.services import account_service, analytics_service, transaction_service

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: str) -> str:
    """Neutralize spreadsheet formula injection while preserving text readability."""
    if value and value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def export_transactions_csv(db_path: Path | str) -> str:
    """Export active transactions to a formula-safe UTF-8 CSV string."""
    data = transaction_service.list_transactions(db_path, limit=5000, offset=0)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["date", "entry_type", "account", "category", "merchant", "description", "amount_inr"]
    )
    for tx in data["transactions"]:
        amt_str = f"{tx['amount_minor'] // 100}.{tx['amount_minor'] % 100:02d}"
        writer.writerow(
            [
                tx["tx_date"],
                tx["entry_type"],
                sanitize_csv_cell(str(tx.get("account_name") or "")),
                sanitize_csv_cell(str(tx.get("category_name") or "")),
                sanitize_csv_cell(str(tx.get("merchant") or "")),
                sanitize_csv_cell(str(tx.get("description") or "")),
                amt_str,
            ]
        )
    return buf.getvalue()


def _pdf_escape(text: str) -> str:
    ascii_safe = text.replace("\u20b9", "INR ").encode("latin-1", "replace").decode("latin-1")
    return ascii_safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def export_pdf_report(
    db_path: Path | str,
    *,
    preset: str = "current_month",
    start_date: str | None = None,
    end_date: str | None = None,
) -> bytes:
    """Generate a clean, valid, offline PDF 1.4 financial report."""
    rep = analytics_service.get_full_analytics_report(
        db_path, preset=preset, start_date=start_date, end_date=end_date
    )
    accts = account_service.list_accounts(db_path)
    s = rep["summary"]
    lines = [
        f"Finora Financial Report - {rep['period']['label']}",
        "-" * 64,
        f"Income:        {s['income_formatted']}",
        f"Gross Expense: {s['gross_expense_formatted']}",
        f"Refunds:       {s['refund_formatted']}",
        f"Net Expense:   {s['net_expense_formatted']}",
        f"Surplus:       {s['surplus_formatted']}",
        f"Savings Rate:  {s['savings_rate_percent']}%"
        if s["savings_rate_available"]
        else "Savings Rate:  Unavailable",
        "",
        "Category Breakdown:",
    ]
    for c in rep["categories"][:12]:
        lines.append(f"  {c['category_name'][:24]:<24} Net: {c['net_formatted']}")
    lines.append("")
    lines.append("Accounts Summary:")
    for a in accts["accounts"][:10]:
        lines.append(f"  {a['name'][:24]:<24} {a['balance_formatted']}")

    stream_ops = ["BT", "/F1 11 Tf", "50 750 Td", "14 TL"]
    for idx, line in enumerate(lines[:45]):
        escaped = _pdf_escape(line)
        if idx == 0:
            stream_ops.append(f"({escaped}) Tj")
        else:
            stream_ops.append(f"T* ({escaped}) Tj")
    stream_ops.append("ET")
    stream_bytes = "\n".join(stream_ops).encode("latin-1")

    objs: list[bytes] = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n",
        f"4 0 obj\n<< /Length {len(stream_bytes)} >>\nstream\n".encode("latin-1")
        + stream_bytes
        + b"\nendstream\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>\nendobj\n",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objs:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode("latin-1"))
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("latin-1"))
    out.extend(
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "latin-1"
        )
    )
    return bytes(out)
