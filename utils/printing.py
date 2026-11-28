# utils/printing.py
"""Commercial monochrome (black & white) A5/A4 RTL printing & editable Word (.docx) export for Daqiq."""

from __future__ import annotations

import html
import io
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Mm, Pt, RGBColor
from PySide6.QtCore import QBuffer, QIODevice, QMarginsF, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrintPreviewWidget, QPrinter
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

# Strictly excluded internal financial/technical terms on customer-facing invoices
FORBIDDEN_SALES_INVOICE_TERMS = (
    "بهای تمام‌شده",
    "بهای تمام شده",
    "قیمت خرید",
    "سود واحد",
    "سود کل",
    "سود خالص",
    "سود فروش",
    "درصد سود",
    "قیمت پیشنهادی",
    "هزینه ارتقا",
    "کد محموله",
    "شناسه فاکتور خرید",
    "شناسه فاکتور تأمین‌کننده",
    "کارمزد",
    "unit_cost_price",
    "unit_profit",
    "total_profit",
)

_LRI = "\u2066"
_PDI = "\u2069"

_DATE_TIME_TOKEN_RE = re.compile(
    r"(?<!\u2066)"
    r"("
    r"[0-9۰-۹٠-٩]{2,4}[/\-][0-9۰-۹٠-٩]{1,2}[/\-][0-9۰-۹٠-٩]{1,4}"
    r"(?:\s+[0-9۰-۹٠-٩]{1,2}:[0-9۰-۹٠-٩]{2}(?::[0-9۰-۹٠-٩]{2})?(?:\s*(?:AM|PM|am|pm|ق\.ظ|ب\.ظ))?)?"
    r"|"
    r"[0-9۰-۹٠-٩]{1,2}:[0-9۰-۹٠-٩]{2}(?::[0-9۰-۹٠-٩]{2})?(?:\s*(?:AM|PM|am|pm|ق\.ظ|ب\.ظ))?"
    r")"
    r"(?!\u2069)"
)


def isolate_bidi_dates(text: Any) -> str:
    """Wrap every date, time, or datetime token in LRI..PDI (U+2066..U+2069) so RTL never flips dates."""
    if text is None:
        return ""
    raw = str(text)
    if not raw:
        return raw

    def _wrap(m: re.Match) -> str:
        tok = m.group(1)
        return f"{_LRI}{tok}{_PDI}"

    return _DATE_TIME_TOKEN_RE.sub(_wrap, raw)


def _esc_html_dates(val: Any) -> str:
    """HTML-escape text while isolating every date/time token inside <span dir='ltr'>U+2066...U+2069</span>."""
    raw = "" if val is None else str(val)
    if not raw:
        return ""
    # Strip existing isolates temporarily to emit uniform spans cleanly
    cleaned = raw.replace(_LRI, "").replace(_PDI, "")
    parts: List[str] = []
    pos = 0
    for m in _DATE_TIME_TOKEN_RE.finditer(cleaned):
        if m.start() > pos:
            parts.append(html.escape(cleaned[pos:m.start()], quote=True))
        tok = html.escape(m.group(1), quote=True)
        parts.append(f"<span dir='ltr' style='unicode-bidi:isolate;'>{_LRI}{tok}{_PDI}</span>")
        pos = m.end()
    if pos < len(cleaned):
        parts.append(html.escape(cleaned[pos:], quote=True))
    return "".join(parts)

PAPER_SIZE_MAP = {
    "A5": QPageSize.PageSizeId.A5,
    "A4": QPageSize.PageSizeId.A4,
}

_ASCII_TO_PERSIAN = str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬")
_PERSIAN_TO_ASCII = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٬", "01234567890123456789,")


def to_persian_digits(text: Any) -> str:
    """Convert ASCII digits & commas into clean Persian digits and separator."""
    if text is None:
        return ""
    return str(text).translate(_ASCII_TO_PERSIAN)


def to_ascii_digits(text: Any) -> str:
    """Normalize Persian/Arabic numerals to ASCII digits for parsing."""
    if text is None:
        return ""
    return str(text).translate(_PERSIAN_TO_ASCII)


def _fmt_int_fa(val: Any) -> str:
    if val is None or isinstance(val, bool):
        return "۰"
    if isinstance(val, (int, float)):
        return to_persian_digits(f"{int(round(val)):,}")
    clean = to_ascii_digits(str(val)).replace(",", "").strip()
    if clean.lstrip("-").isdigit():
        return to_persian_digits(f"{int(clean):,}")
    return to_persian_digits(str(val).strip() or "۰")


def _esc(val: Any) -> str:
    return html.escape("" if val is None else str(val), quote=True)


def assert_no_internal_cost_leakage(rendered_text: str) -> None:
    """Verify no internal cost, margin, batch ID, or profit term leaks into customer invoices."""
    lowered = to_ascii_digits(rendered_text).lower()
    for term in FORBIDDEN_SALES_INVOICE_TERMS:
        if term.lower() in lowered:
            raise ValueError(f"Internal financial term leaked into customer invoice: {term}")


@dataclass
class PrintDocumentSpec:
    """Unified structured document representation powering both B&W A5/A4 Print and Editable Word (.docx)."""

    section_key: str
    title: str
    shop_name: str = "فروشگاه دقیق"
    shop_phone: str = ""
    print_time: str = ""
    meta_pairs: List[Tuple[str, str]] = field(default_factory=list)
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    right_align_cols: set[int] = field(default_factory=set)
    col_widths_pct: Optional[List[int]] = None
    summary_pairs: List[Tuple[str, str]] = field(default_factory=list)
    notes: str = ""
    signatures: Optional[Tuple[str, str]] = None
    chart_png_bytes: Optional[bytes] = None
    customer_privacy_strict: bool = False


# ---------------------------------------------------------------------------
# Spec Builders for ALL 12 Store Sections
# ---------------------------------------------------------------------------

def build_sales_invoice_spec(
    records: Sequence[Dict[str, Any]],
    shop_info: Optional[Dict[str, Any]] = None,
) -> PrintDocumentSpec:
    """Customer-only concise Sales Invoice («فاکتور فروش»): zero internal cost, profit, batch, or tech jargon."""
    shop = shop_info or {}
    shop_name = str(shop.get("shop_name") or "فروشگاه دقیق").strip()
    shop_phone = str(shop.get("phone") or "").strip()
    print_time = to_persian_digits(str(shop.get("print_time") or "-").strip())

    first = records[0] if records else {}
    inv_nos = list(dict.fromkeys(str(r.get("invoice_number") or "").strip() for r in records if str(r.get("invoice_number") or "").strip()))
    inv_display = "، ".join(inv_nos) if inv_nos else "-"
    customer = str(first.get("customer_name") or "").strip()
    cust_phone = str(first.get("customer_phone") or "").strip()
    sale_dt = to_persian_digits(str(first.get("sale_datetime") or print_time or "-").strip())

    meta: List[Tuple[str, str]] = [
        ("شماره فاکتور", inv_display),
        ("تاریخ و ساعت", sale_dt),
    ]
    if customer and customer != "-":
        meta.append(("خریدار", customer))
    if cust_phone and cust_phone != "-":
        meta.append(("تلفن خریدار", to_persian_digits(cust_phone)))

    rows: List[List[str]] = []
    grand_total = 0
    grand_discount = 0
    grand_paid = 0
    any_installment = False
    has_warranty = False
    clean_notes: List[str] = []

    for r in records:
        w = str(r.get("warranty_text") or "").strip()
        if w and w not in ("ندارد", "-", "بدون گارانتی"):
            has_warranty = True

    headers = ["ردیف", "شرح کالا"]
    right_cols = {1}
    if has_warranty:
        headers.append("گارانتی")
        widths = [7, 41, 16, 8, 14, 14]
    else:
        widths = [7, 51, 10, 16, 16]
    headers.extend(["تعداد", "فی (تومان)", "مبلغ کل (تومان)"])

    for idx, item in enumerate(records, 1):
        qty = int(item.get("qty") or 0)
        unit_price = int(item.get("actual_unit_price") or 0)
        disc = int(item.get("total_discount") or 0)
        line_total = int(item.get("total_amount") or 0)
        paid = int(item.get("paid_amount") or 0)
        grand_total += line_total
        grand_discount += disc
        grand_paid += paid
        if str(item.get("payment_type") or "").lower() in ("installment", "credit") or (line_total > paid and paid >= 0):
            any_installment = True

        # Concise customer-facing item label (brand + model only, never category/batch/internal codes)
        bm = " ".join(
            v for v in (str(item.get("brand") or "").strip(), str(item.get("model") or "").strip())
            if v
        )
        raw_title = str(item.get("product_title") or item.get("description") or "کالا").strip()
        if not bm and "|" in raw_title:
            raw_title = raw_title.split("|", 1)[1].strip() or raw_title
        title = bm or raw_title
        row = [to_persian_digits(idx), title]
        if has_warranty:
            w = str(item.get("warranty_text") or "").strip()
            row.append(to_persian_digits(w if w and w != "-" else "ندارد"))
        row.extend([_fmt_int_fa(qty), _fmt_int_fa(unit_price), _fmt_int_fa(line_total)])
        rows.append(row)

        n = str(item.get("notes") or "").strip()
        if n and not any(bad in n.lower() for bad in FORBIDDEN_SALES_INVOICE_TERMS):
            clean_notes.append(n)

    summary: List[Tuple[str, str]] = []
    if grand_discount > 0:
        summary.append(("تخفیف کل", f"{_fmt_int_fa(grand_discount)} تومان"))
    summary.append(("جمع کل قابل پرداخت", f"{_fmt_int_fa(grand_total)} تومان"))
    remaining = max(0, grand_total - grand_paid)
    first_item = records[0] if records else {}
    is_chk = (
        str(first_item.get("settlement_subtype") or "").strip() == "تسویه چکی"
        or str(first_item.get("payment_type") or "").strip().lower() == "check"
    )
    chk_due = str(first_item.get("check_due_date") or "").strip()
    if any_installment or remaining > 0:
        summary.append(("مبلغ پرداخت‌شده / پیش‌پرداخت", f"{_fmt_int_fa(grand_paid)} تومان"))
        summary.append(("مانده حساب", f"{_fmt_int_fa(remaining)} تومان"))
    elif is_chk:
        chk_desc = f"تسویه چکی (سررسید: {to_persian_digits(chk_due)})" if chk_due else "تسویه چکی"
        summary.append(("نحوه پرداخت", chk_desc))
    else:
        summary.append(("وضعیت پرداخت", "تسویه‌شده"))

    return PrintDocumentSpec(
        section_key="sales",
        title="فاکتور فروش",
        shop_name=shop_name,
        shop_phone=to_persian_digits(shop_phone),
        print_time=print_time,
        meta_pairs=meta,
        headers=headers,
        rows=rows,
        right_align_cols=right_cols,
        col_widths_pct=widths,
        summary_pairs=summary,
        notes=" | ".join(dict.fromkeys(clean_notes)),
        signatures=("مهر و امضای فروشنده", "امضای خریدار"),
        customer_privacy_strict=True,
    )


def build_proforma_invoice_spec(
    records: Sequence[Dict[str, Any]],
    shop_info: Optional[Dict[str, Any]] = None,
) -> PrintDocumentSpec:
    """Customer-only Proforma Invoice («پیش‌فاکتور فروش»): displays ONLY brand + model without cost/profit."""
    shop = shop_info or {}
    shop_name = str(shop.get("shop_name") or "فروشگاه دقیق").strip()
    shop_phone = str(shop.get("phone") or "").strip()
    print_time = to_persian_digits(str(shop.get("print_time") or "-").strip())

    first = records[0] if records else {}
    pf_nos = list(dict.fromkeys(str(r.get("proforma_number") or "").strip() for r in records if str(r.get("proforma_number") or "").strip()))
    pf_display = "، ".join(pf_nos) if pf_nos else "-"
    customer = str(first.get("customer_name") or "").strip()
    cust_phone = str(first.get("customer_phone") or "").strip()
    pf_dt = to_persian_digits(str(first.get("proforma_datetime") or print_time or "-").strip())
    valid_until = to_persian_digits(str(first.get("valid_until") or "").strip())

    meta: List[Tuple[str, str]] = [
        ("شماره پیش‌فاکتور", pf_display),
        ("تاریخ صدور", pf_dt),
    ]
    if valid_until and valid_until != "-":
        meta.append(("تاریخ اعتبار", valid_until))
    if customer and customer != "-":
        meta.append(("خریدار", customer))
    if cust_phone and cust_phone != "-":
        meta.append(("تلفن خریدار", to_persian_digits(cust_phone)))

    headers = ["ردیف", "شرح کالا", "تعداد", "فی (تومان)", "مبلغ کل (تومان)"]
    widths = [8, 48, 10, 16, 18]
    rows: List[List[str]] = []
    grand_total = 0
    clean_notes: List[str] = []
    for idx, item in enumerate(records, 1):
        qty = int(item.get("qty") or 0)
        unit_price = int(item.get("actual_unit_price") or 0)
        line_total = int(item.get("line_total") or (qty * unit_price))
        grand_total += line_total
        bm = " ".join(
            v for v in (str(item.get("brand") or "").strip(), str(item.get("model") or "").strip())
            if v
        )
        raw_title = str(item.get("product_title") or item.get("description") or "کالا").strip()
        if not bm and "|" in raw_title:
            raw_title = raw_title.split("|", 1)[1].strip() or raw_title
        title = bm or raw_title
        rows.append([
            to_persian_digits(idx),
            title,
            _fmt_int_fa(qty),
            _fmt_int_fa(unit_price),
            _fmt_int_fa(line_total),
        ])
        n = str(item.get("notes") or "").strip()
        if n and not any(bad in n.lower() for bad in FORBIDDEN_SALES_INVOICE_TERMS):
            clean_notes.append(n)

    summary = [
        ("تعداد ردیف", to_persian_digits(len(rows))),
        ("جمع کل پیش‌فاکتور", f"{_fmt_int_fa(grand_total)} تومان"),
    ]
    return PrintDocumentSpec(
        section_key="proformas",
        title="پیش‌فاکتور فروش",
        shop_name=shop_name,
        shop_phone=to_persian_digits(shop_phone),
        print_time=print_time,
        meta_pairs=meta,
        headers=headers,
        rows=rows,
        right_align_cols=set(),
        col_widths_pct=widths,
        summary_pairs=summary,
        notes=" | ".join(dict.fromkeys(clean_notes)),
        signatures=("مهر و امضای فروشنده", "تأیید خریدار"),
        customer_privacy_strict=True,
    )


def build_purchase_voucher_spec(
    records: Sequence[Dict[str, Any]],
    shop_info: Optional[Dict[str, Any]] = None,
) -> PrintDocumentSpec:
    """Clean B&W Purchase / Stock-In Receipt («رسید خرید و ثبت محموله»)."""
    shop = shop_info or {}
    shop_name = str(shop.get("shop_name") or "فروشگاه دقیق").strip()
    print_time = to_persian_digits(str(shop.get("print_time") or "-").strip())

    headers = ["ردیف", "شناسه فاکتور خرید", "شناسه فاکتور تأمین‌کننده", "تاریخ و ساعت", "تأمین‌کننده", "کالا", "تعداد", "قیمت خرید واحد", "جمع کل (تومان)"]
    rows: List[List[str]] = []
    grand_total = 0
    grand_paid = 0
    grand_rem = 0
    for idx, rec in enumerate(records, 1):
        tot = int(rec.get("total_bill") or 0)
        paid = int(rec.get("paid_amount") or 0)
        rem = int(rec.get("remaining_bill") if rec.get("remaining_bill") is not None else max(0, tot - paid))
        grand_total += tot
        grand_paid += paid
        grand_rem += rem
        rows.append([
            to_persian_digits(idx),
            str(rec.get("purchase_invoice_code") or rec.get("batch_code") or "-"),
            str(rec.get("invoice_number") or "-"),
            to_persian_digits(rec.get("purchase_date") or "-"),
            str(rec.get("supplier_name") or "-"),
            str(rec.get("product_title") or "-"),
            _fmt_int_fa(rec.get("initial_qty")),
            _fmt_int_fa(rec.get("unit_purchase_price")),
            _fmt_int_fa(tot),
        ])

    summary_pairs = [
        ("جمع کل فاکتورهای خرید", f"{_fmt_int_fa(grand_total)} تومان"),
        ("جمع پرداخت‌شده", f"{_fmt_int_fa(grand_paid)} تومان"),
        ("مانده بدهی به تأمین‌کننده", f"{_fmt_int_fa(grand_rem)} تومان"),
    ]
    chk_notes = [
        f"{str(rec.get('settlement_subtype'))} (سررسید: {to_persian_digits(rec.get('check_due_date') or '-')})"
        for rec in records
        if str(rec.get("settlement_subtype") or "") == "تسویه چکی"
    ]
    if chk_notes:
        summary_pairs.append(("جزئیات تسویه", chk_notes[0]))

    return PrintDocumentSpec(
        section_key="batches",
        title="رسید خرید و ثبت محموله",
        shop_name=shop_name,
        print_time=print_time,
        meta_pairs=[("تعداد اقلام", to_persian_digits(len(records))), ("تاریخ چاپ", print_time)],
        headers=headers,
        rows=rows,
        right_align_cols=set(),
        col_widths_pct=[5, 11, 12, 12, 13, 19, 7, 10, 11],
        summary_pairs=summary_pairs,
        signatures=("امضای انباردار / خریدار", "تأیید مدیریت"),
    )


def build_service_or_upgrade_spec(
    kind: str,
    records: Sequence[Dict[str, Any]],
    shop_info: Optional[Dict[str, Any]] = None,
) -> PrintDocumentSpec:
    """Customer-safe B&W Service Receipt («فاکتور خدمات فنی») or Hardware Upgrade Receipt («رسید ارتقای کالا»)."""
    shop = shop_info or {}
    shop_name = str(shop.get("shop_name") or "فروشگاه دقیق").strip()
    print_time = to_persian_digits(str(shop.get("print_time") or "-").strip())

    if kind == "upgrades":
        headers = ["ردیف", "تاریخ", "شرح کالا / ارتقا", "جزئیات جدید", "تعداد", "مبلغ (تومان)"]
        rows = []
        tot = 0
        for idx, rec in enumerate(records, 1):
            qty = int(rec.get("target_qty") or 1)
            unit_add = int(rec.get("added_cost_unit") or 0)
            line_tot = qty * unit_add
            tot += line_tot
            desc = str(rec.get("part_desc") or "ارتقای سخت‌افزاری").strip()
            rows.append([
                to_persian_digits(idx),
                to_persian_digits(rec.get("upgrade_date") or "-"),
                desc,
                str(rec.get("new_specs") or "-"),
                _fmt_int_fa(qty),
                _fmt_int_fa(line_tot),
            ])
        return PrintDocumentSpec(
            section_key="upgrades",
            title="رسید ارتقای کالا",
            shop_name=shop_name,
            print_time=print_time,
            meta_pairs=[("تعداد اقلام", to_persian_digits(len(records))), ("تاریخ چاپ", print_time)],
            headers=headers,
            rows=rows,
            right_align_cols={2, 3},
            col_widths_pct=[7, 15, 28, 28, 8, 14],
            summary_pairs=[("جمع کل مبلغ ارتقا", f"{_fmt_int_fa(tot)} تومان")],
            signatures=("امضای کارشناس فنی", "امضای مشتری"),
            customer_privacy_strict=True,
        )

    headers = ["ردیف", "شماره فاکتور", "تاریخ", "خدمت انجام‌شده", "وضعیت", "مبلغ (تومان)"]
    rows = []
    tot_fee = 0
    tot_paid = 0
    first = records[0] if records else {}
    cust = str(first.get("customer_name") or "").strip()
    meta = [("تعداد ردیف", to_persian_digits(len(records))), ("تاریخ چاپ", print_time)]
    if cust and cust not in ("-", "مشتری حضوری"):
        meta.insert(0, ("نام مشتری", cust))
    for idx, rec in enumerate(records, 1):
        fee = int(rec.get("service_fee") or 0)
        paid = int(rec.get("paid_amount") or 0)
        tot_fee += fee
        tot_paid += paid
        sname = str(rec.get("service_name") or "-")
        desc = str(rec.get("description") or "").strip()
        service_txt = f"{sname} — {desc}" if desc and desc != "-" else sname
        rows.append([
            to_persian_digits(idx),
            str(rec.get("invoice_number") or "-"),
            to_persian_digits(rec.get("service_datetime") or "-"),
            service_txt,
            str(rec.get("settlement_status") or "تسویه‌شده"),
            _fmt_int_fa(fee),
        ])
    rem = max(0, tot_fee - tot_paid)
    summary = [("جمع کل هزینه خدمات", f"{_fmt_int_fa(tot_fee)} تومان")]
    if rem > 0:
        summary.append(("مبلغ پرداخت‌شده", f"{_fmt_int_fa(tot_paid)} تومان"))
        summary.append(("مانده حساب", f"{_fmt_int_fa(rem)} تومان"))
    elif str(first.get("settlement_subtype") or "").strip() == "تسویه چکی":
        chk_due = str(first.get("check_due_date") or "").strip()
        summary.append(("نحوه پرداخت", f"تسویه چکی (سررسید: {to_persian_digits(chk_due)})" if chk_due else "تسویه چکی"))
    return PrintDocumentSpec(
        section_key="service_records",
        title="فاکتور خدمات و تعمیرات",
        shop_name=shop_name,
        print_time=print_time,
        meta_pairs=meta,
        headers=headers,
        rows=rows,
        right_align_cols={3},
        col_widths_pct=[7, 13, 16, 36, 13, 15],
        summary_pairs=summary,
        signatures=("مهر و امضای مرکز خدمات", "امضای مشتری"),
        customer_privacy_strict=True,
    )


def build_section_table_spec(
    section_key: str,
    raw_headers: Sequence[str],
    raw_rows: Sequence[Sequence[str]],
    *,
    report_title: str = "",
    summary_text: str = "",
    shop_info: Optional[Dict[str, Any]] = None,
    chart_png_bytes: Optional[bytes] = None,
) -> PrintDocumentSpec:
    """Build tailored specs for the remaining sections:
    dashboard_low, dashboard_employees, products, suppliers, service_catalog,
    employees, customers, reports, and charts."""
    shop = shop_info or {}
    shop_name = str(shop.get("shop_name") or "فروشگاه دقیق").strip()
    print_time = to_persian_digits(str(shop.get("print_time") or "-").strip())
    col_map = {str(h).strip(): i for i, h in enumerate(raw_headers)}

    def _get(row: Sequence[str], *candidates: str, default: str = "-") -> str:
        for c in candidates:
            if c in col_map and col_map[c] < len(row):
                val = str(row[col_map[c]] or "").strip()
                if val:
                    return val
        return default

    def _to_int(val: str) -> int:
        clean = to_ascii_digits(val).replace(",", "").replace("+", "").strip()
        try:
            return int(clean)
        except ValueError:
            return 0

    if section_key == "dashboard_low":
        headers = ["ردیف", "نام کالا", "دسته‌بندی / محموله", "موجودی فعلی", "حداقل موجودی", "کسری"]
        rows = []
        for idx, r in enumerate(raw_rows, 1):
            cur = _to_int(_get(r, "موجودی فعلی", default="0"))
            mn = _to_int(_get(r, "حداقل موجودی", default="0"))
            deficit = max(0, mn - cur)
            rows.append([
                to_persian_digits(idx),
                _get(r, "مشخصات کالا"),
                _get(r, "کد کالا", "محموله"),
                _fmt_int_fa(cur),
                _fmt_int_fa(mn),
                _fmt_int_fa(deficit),
            ])
        return PrintDocumentSpec(
            section_key=section_key,
            title="گزارش هشدار موجودی",
            shop_name=shop_name,
            print_time=print_time,
            meta_pairs=[("تعداد کالاهای نیازمند تأمین", to_persian_digits(len(rows))), ("تاریخ چاپ", print_time)],
            headers=headers,
            rows=rows,
            right_align_cols={1, 2},
            col_widths_pct=[7, 35, 22, 12, 12, 12],
        )

    if section_key == "dashboard_employees":
        headers = ["ردیف", "نام فروشنده", "تعداد فروش", "مبلغ کل فروش (تومان)", "تخفیف", "سود (تومان)"]
        rows = []
        tot_cnt = 0
        tot_sales = 0
        for idx, r in enumerate(raw_rows, 1):
            cnt = _to_int(_get(r, "تعداد فروش", default="0"))
            sal = _to_int(_get(r, "مبلغ کل فروش (تومان)", default="0"))
            tot_cnt += cnt
            tot_sales += sal
            rows.append([
                to_persian_digits(idx),
                _get(r, "نام فروشنده"),
                _fmt_int_fa(cnt),
                _fmt_int_fa(sal),
                to_persian_digits(_get(r, "تخفیف داده شده", default="۰")),
                to_persian_digits(_get(r, "سود حاصل از فروش", default="۰")),
            ])
        return PrintDocumentSpec(
            section_key=section_key,
            title="گزارش عملکرد فروشندگان",
            shop_name=shop_name,
            print_time=print_time,
            meta_pairs=[("تعداد فروشندگان", to_persian_digits(len(rows))), ("تاریخ چاپ", print_time)],
            headers=headers,
            rows=rows,
            right_align_cols={1},
            col_widths_pct=[7, 29, 13, 21, 14, 16],
            summary_pairs=[
                ("مجموع تعداد فروش", f"{_fmt_int_fa(tot_cnt)} عدد"),
                ("جمع کل فروش", f"{_fmt_int_fa(tot_sales)} تومان"),
            ],
        )

    if section_key == "products":
        headers = ["ردیف", "کد کالا", "عنوان کالا", "دسته‌بندی / زیرمجموعه", "موجودی کل", "تعداد فروش", "وضعیت"]
        rows = []
        for idx, r in enumerate(raw_rows, 1):
            brand_model = " ".join(x for x in (_get(r, "برند", default=""), _get(r, "مدل", default="")) if x).strip() or "-"
            cat_sub = " / ".join(x for x in (_get(r, "دسته‌بندی", default=""), _get(r, "زیرمجموعه", default="")) if x).strip(" /") or "-"
            rows.append([
                to_persian_digits(idx),
                _get(r, "کد کالا"),
                brand_model,
                cat_sub,
                to_persian_digits(_get(r, "موجودی کل", default="۰")),
                to_persian_digits(_get(r, "تعداد فروش", default="۰")),
                _get(r, "وضعیت موجودی"),
            ])
        return PrintDocumentSpec(
            section_key=section_key,
            title="فهرست و موجودی کالاها",
            shop_name=shop_name,
            print_time=print_time,
            meta_pairs=[("تعداد کالاها", to_persian_digits(len(rows))), ("تاریخ چاپ", print_time)],
            headers=headers,
            rows=rows,
            right_align_cols={2, 3},
            col_widths_pct=[7, 11, 25, 25, 10, 10, 12],
        )

    if section_key == "suppliers":
        headers = ["ردیف", "نام تأمین‌کننده", "تلفن تماس", "تعداد محموله", "جمع خرید (تومان)", "پرداخت‌شده", "مانده بدهی"]
        rows = []
        tot_debt = 0
        for idx, r in enumerate(raw_rows, 1):
            debt = _to_int(_get(r, "مانده بدهی به تأمین‌کننده (تومان)", default="0"))
            tot_debt += debt
            rows.append([
                to_persian_digits(idx),
                _get(r, "نام تأمین‌کننده"),
                to_persian_digits(_get(r, "تلفن تماس")),
                to_persian_digits(_get(r, "تعداد محموله‌های خرید", default="۰")),
                to_persian_digits(_get(r, "مجموع مبلغ خرید (تومان)", default="۰")),
                to_persian_digits(_get(r, "مجموع پرداخت‌شده (تومان)", default="۰")),
                _fmt_int_fa(debt),
            ])
        return PrintDocumentSpec(
            section_key=section_key,
            title="صورتحساب تأمین‌کنندگان",
            shop_name=shop_name,
            print_time=print_time,
            meta_pairs=[("تعداد تأمین‌کنندگان", to_persian_digits(len(rows))), ("تاریخ چاپ", print_time)],
            headers=headers,
            rows=rows,
            right_align_cols={1},
            col_widths_pct=[7, 25, 14, 11, 15, 14, 14],
            summary_pairs=[("جمع کل مانده بدهی", f"{_fmt_int_fa(tot_debt)} تومان")],
        )

    if section_key == "customers":
        headers = ["ردیف", "نام مشتری", "تلفن", "تعداد خرید", "جمع خرید (تومان)", "پرداخت‌شده", "مانده بدهی", "اقساط معوق"]
        rows = []
        tot_debt = 0
        for idx, r in enumerate(raw_rows, 1):
            debt = _to_int(_get(r, "مانده بدهی (تومان)", "مانده بدهی", default="0"))
            tot_debt += debt
            rows.append([
                to_persian_digits(idx),
                _get(r, "نام مشتری"),
                to_persian_digits(_get(r, "شماره تماس", "تلفن تماس")),
                to_persian_digits(_get(r, "تعداد خرید", default="۰")),
                to_persian_digits(_get(r, "جمع کل خرید (تومان)", "جمع کل خرید", default="۰")),
                to_persian_digits(_get(r, "مجموع پرداختی (تومان)", "مجموع پرداختی", default="۰")),
                _fmt_int_fa(debt),
                to_persian_digits(_get(r, "اقساط سررسید گذشته", default="۰")),
            ])
        return PrintDocumentSpec(
            section_key="customers",
            title="صورتحساب مشتریان و وضعیت اقساط",
            shop_name=shop_name,
            print_time=print_time,
            meta_pairs=[("تعداد مشتریان", to_persian_digits(len(rows))), ("تاریخ چاپ", print_time)],
            headers=headers,
            rows=rows,
            right_align_cols={1},
            col_widths_pct=[6, 22, 13, 9, 15, 14, 12, 9],
            summary_pairs=[("جمع مطالبات مشتریان", f"{_fmt_int_fa(tot_debt)} تومان")],
        )

    if section_key == "employees":
        headers = ["ردیف", "نام کاربر", "نقش / سمت", "تلفن", "سطح دسترسی", "وضعیت", "تاریخ ثبت"]
        rows = []
        for idx, r in enumerate(raw_rows, 1):
            rows.append([
                to_persian_digits(idx),
                _get(r, "نام کاربر", "نام و نام خانوادگی"),
                _get(r, "نقش / سمت", "سمت"),
                to_persian_digits(_get(r, "تلفن تماس")),
                _get(r, "سطح دسترسی"),
                _get(r, "وضعیت فعالیت"),
                to_persian_digits(_get(r, "تاریخ ایجاد")),
            ])
        return PrintDocumentSpec(
            section_key=section_key,
            title="فهرست کاربران و سطوح دسترسی",
            shop_name=shop_name,
            print_time=print_time,
            meta_pairs=[("تعداد کاربران", to_persian_digits(len(rows))), ("تاریخ چاپ", print_time)],
            headers=headers,
            rows=rows,
            right_align_cols={1, 2, 4},
            col_widths_pct=[7, 22, 16, 14, 16, 11, 14],
        )

    if section_key == "service_catalog":
        headers = ["ردیف", "کد خدمت", "نوع خدمت", "عنوان خدمت", "هزینه خدمت (تومان)"]
        rows = []
        for idx, r in enumerate(raw_rows, 1):
            rows.append([
                to_persian_digits(idx),
                _get(r, "کد خدمت"),
                _get(r, "نوع خدمت"),
                _get(r, "عنوان خدمت"),
                to_persian_digits(_get(r, "هزینه خدمت (تومان)", default="۰")),
            ])
        return PrintDocumentSpec(
            section_key=section_key,
            title="تعرفه خدمات فنی",
            shop_name=shop_name,
            print_time=print_time,
            meta_pairs=[("تعداد خدمات", to_persian_digits(len(rows))), ("تاریخ چاپ", print_time)],
            headers=headers,
            rows=rows,
            right_align_cols={2, 3},
            col_widths_pct=[8, 13, 20, 41, 18],
        )

    if section_key == "employee_performance":
        headers = [
            "ردیف", "نام کاربر", "تعداد فروش", "فروش کل (تومان)", "سود فروش",
            "تعداد خدمات", "سود خدمات", "ارتقا", "وصول اقساط", "مجموع سودآوری",
        ]
        rows = []
        tot_rev = 0
        tot_prof = 0
        for idx, r in enumerate(raw_rows, 1):
            rev = _to_int(_get(r, "جمع فروش (تومان)", default="0"))
            prf = _to_int(_get(r, "مجموع سودآوری (تومان)", default="0"))
            tot_rev += rev
            tot_prof += prf
            rows.append([
                to_persian_digits(idx),
                _get(r, "نام کاربر"),
                to_persian_digits(_get(r, "تعداد فاکتور فروش", default="۰")),
                _fmt_int_fa(rev),
                to_persian_digits(_get(r, "سود فروش (تومان)", default="۰")),
                to_persian_digits(_get(r, "تعداد خدمات", default="۰")),
                to_persian_digits(_get(r, "سود خدمات (تومان)", default="۰")),
                to_persian_digits(_get(r, "تعداد ارتقا", default="۰")),
                to_persian_digits(_get(r, "اقساط وصول‌شده (تومان)", default="۰")),
                _fmt_int_fa(prf),
            ])
        return PrintDocumentSpec(
            section_key="employee_performance",
            title=report_title or "گزارش بازه‌ای عملکرد کاربران",
            shop_name=shop_name,
            print_time=print_time,
            meta_pairs=[("تعداد کاربران", to_persian_digits(len(rows))), ("تاریخ چاپ", print_time)],
            headers=headers,
            rows=rows,
            right_align_cols={1},
            col_widths_pct=[5, 16, 7, 13, 12, 7, 11, 6, 11, 12],
            summary_pairs=[
                ("مجموع فروش بازه", f"{_fmt_int_fa(tot_rev)} تومان"),
                ("مجموع سودآوری", f"{_fmt_int_fa(tot_prof)} تومان"),
            ],
        )

    title_fallback = {
        "reports": report_title or "گزارش جامع عملکرد",
        "charts": report_title or "گزارش نموداری و تحلیلی",
    }
    doc_title = str(report_title or title_fallback.get(section_key, "گزارش چاپی")).strip()
    headers = ["ردیف"] + [str(h) for h in raw_headers]
    rows = [[to_persian_digits(idx)] + [to_persian_digits(c) for c in r] for idx, r in enumerate(raw_rows, 1)]
    summary_pairs = [("خلاصه گزارش", to_persian_digits(summary_text))] if summary_text else []
    return PrintDocumentSpec(
        section_key=section_key,
        title=doc_title,
        shop_name=shop_name,
        print_time=print_time,
        meta_pairs=[("تعداد ردیف چاپی", to_persian_digits(len(rows))), ("تاریخ چاپ", print_time)],
        headers=headers,
        rows=rows,
        right_align_cols={1, 2},
        summary_pairs=summary_pairs,
        chart_png_bytes=chart_png_bytes,
    )


# ---------------------------------------------------------------------------
# HTML Renderer (B&W Bold 'B Nazanin' + 'B Titr', Repeating thead, cantSplit)
# ---------------------------------------------------------------------------

def render_spec_to_html(spec: PrintDocumentSpec, *, is_a5: bool = True) -> str:
    """Render any PrintDocumentSpec to crisp monochrome RTL HTML optimized for A5/A4 laser printers."""
    body_pt = "9pt" if is_a5 else "10pt"
    title_pt = "12pt" if is_a5 else "14pt"
    meta_pt = "8.2pt" if is_a5 else "9pt"
    cell_pad = "3.5px 5px" if is_a5 else "5px 7px"

    css = f"""
    <style>
      body {{
        direction: rtl;
        font-family: 'B Nazanin', 'BNazanin', 'Nazanin', 'Vazirmatn', 'Tahoma', sans-serif;
        font-size: {body_pt};
        font-weight: 700;
        color: #000000;
        background-color: #ffffff;
        margin: 0;
        padding: 0;
      }}
      .header-box {{
        width: 100%;
        border: 1.5px solid #000000;
        border-collapse: collapse;
        margin-bottom: 6px;
        page-break-inside: avoid;
      }}
      .header-box td {{
        border: none;
        padding: 5px 8px;
        vertical-align: middle;
      }}
      .shop-name {{
        font-family: 'B Titr', 'BTitr', 'Titr', 'B Nazanin', 'Tahoma', sans-serif;
        font-size: {title_pt};
        font-weight: 700;
        color: #000000;
      }}
      .doc-title {{
        font-family: 'B Titr', 'BTitr', 'Titr', 'B Nazanin', 'Tahoma', sans-serif;
        font-size: {title_pt};
        font-weight: 700;
        text-align: center;
        border: 1.5px solid #000000;
        background-color: #efefef;
        padding: 4px 10px;
      }}
      .meta-grid {{
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 6px;
        font-size: {meta_pt};
        page-break-inside: avoid;
      }}
      .meta-grid td {{
        border: 1px solid #222222;
        padding: 3.5px 6px;
        background-color: #fafafa;
      }}
      table.items {{
        width: 100%;
        border-collapse: collapse;
        margin-top: 4px;
        margin-bottom: 6px;
        table-layout: fixed;
      }}
      table.items thead {{ display: table-header-group; }}
      table.items tr {{ page-break-inside: avoid; break-inside: avoid; }}
      table.items th {{
        font-family: 'B Titr', 'BTitr', 'Titr', 'B Nazanin', 'Tahoma', sans-serif;
        background-color: #efefef;
        color: #000000;
        font-weight: 700;
        border: 1px solid #000000;
        padding: {cell_pad};
        text-align: center;
      }}
      table.items td {{
        border: 1px solid #111111;
        padding: {cell_pad};
        color: #000000;
        font-weight: 700;
        text-align: center;
        word-wrap: break-word;
      }}
      table.items tr:nth-child(even) td {{
        background-color: #fafafa;
      }}
      td.right, th.right {{ text-align: right; }}
      .totals-wrap {{
        page-break-inside: avoid;
        break-inside: avoid;
        margin-top: 6px;
      }}
      .summary-table {{
        width: 62%;
        margin-right: auto;
        margin-left: 0;
        border-collapse: collapse;
      }}
      .summary-table td {{
        border: 1px solid #000000;
        padding: 4px 8px;
        font-weight: 700;
      }}
      .summary-table td.lbl {{
        background-color: #efefef;
        text-align: right;
      }}
      .summary-table td.val {{
        text-align: left;
      }}
      .footer-sign {{
        width: 100%;
        border-collapse: collapse;
        margin-top: 14px;
        font-size: {meta_pt};
        page-break-inside: avoid;
      }}
      .footer-sign td {{
        width: 50%;
        padding: 8px 6px 2px 6px;
        text-align: center;
        border-top: 1px dashed #333333;
      }}
      .muted-note {{
        font-size: {meta_pt};
        margin-top: 5px;
        border: 1px solid #444444;
        padding: 4px 7px;
        background-color: #fafafa;
      }}
      .chart-box {{
        text-align: center;
        margin: 6px 0;
        border: 1px solid #000000;
        padding: 4px;
        page-break-inside: avoid;
      }}
    </style>
    """

    phone_html = f"<div>تلفن: {_esc_html_dates(spec.shop_phone)}</div>" if spec.shop_phone else ""
    meta_tds = "".join(f"<td align='center' valign='middle'><b>{_esc(k)}:</b> {_esc_html_dates(v)}</td>" for k, v in spec.meta_pairs)
    meta_html = f"<table width='100%' border='1' cellspacing='0' cellpadding='4' class='meta-grid'><tr>{meta_tds}</tr></table>" if meta_tds else ""

    chart_html = ""
    if spec.chart_png_bytes:
        import base64
        b64 = base64.b64encode(spec.chart_png_bytes).decode("ascii")
        max_w = "420" if is_a5 else "620"
        chart_html = f"<div class='chart-box'><img src='data:image/png;base64,{b64}' width='{max_w}'/></div>"

    ths: List[str] = []
    for idx, h in enumerate(spec.headers):
        w_pct = f"{spec.col_widths_pct[idx]}%" if (spec.col_widths_pct and idx < len(spec.col_widths_pct)) else ""
        w_attr = f" width='{w_pct}'" if w_pct else ""
        w_style = f" style='width:{w_pct};text-align:center;vertical-align:middle;'" if w_pct else " style='text-align:center;vertical-align:middle;'"
        ths.append(f"<th align='center' valign='middle'{w_attr}{w_style}>{_esc_html_dates(h)}</th>")

    trs: List[str] = []
    for row in spec.rows:
        tds = []
        for idx, cell in enumerate(row):
            w_pct = f"{spec.col_widths_pct[idx]}%" if (spec.col_widths_pct and idx < len(spec.col_widths_pct)) else ""
            w_attr = f" width='{w_pct}'" if w_pct else ""
            tds.append(f"<td align='center' valign='middle'{w_attr} style='text-align:center;vertical-align:middle;'>{_esc_html_dates(cell)}</td>")
        trs.append(f"<tr>{''.join(tds)}</tr>")

    table_html = (
        f"<table width='100%' border='1' cellspacing='0' cellpadding='4' class='items'><thead><tr>{''.join(ths)}</tr></thead><tbody>{''.join(trs)}</tbody></table>"
        if spec.headers
        else ""
    )

    summary_rows = "".join(
        f"<tr><td width='48%' align='right' valign='middle' class='lbl'>{_esc(k)}</td><td width='52%' align='left' valign='middle' class='val'>{_esc_html_dates(v)}</td></tr>"
        for k, v in spec.summary_pairs
    )
    summary_html = f"<table width='62%' align='left' border='1' cellspacing='0' cellpadding='4' class='summary-table'>{summary_rows}</table>" if summary_rows else ""
    notes_html = f"<div class='muted-note'><b>توضیحات:</b> {_esc_html_dates(spec.notes)}</div>" if spec.notes else ""
    sign_html = (
        f"<table width='100%' cellspacing='0' cellpadding='6' class='footer-sign'><tr><td width='50%' align='center' valign='middle'>{_esc(spec.signatures[0])}</td><td width='50%' align='center' valign='middle'>{_esc(spec.signatures[1])}</td></tr></table>"
        if spec.signatures
        else ""
    )

    body = f"""
    <table width="100%" cellspacing="0" cellpadding="5" class="header-box">
      <tr>
        <td width="36%" align="right" valign="middle"><div class="shop-name">{_esc_html_dates(spec.shop_name)}</div>{phone_html}</td>
        <td width="32%" align="center" valign="middle"><div class="doc-title">{_esc_html_dates(spec.title)}</div></td>
        <td width="32%" align="left" valign="middle" style="text-align:left;"><div><b>تاریخ چاپ:</b> {_esc_html_dates(spec.print_time or '-')}</div></td>
      </tr>
    </table>
    {meta_html}
    {chart_html}
    {table_html}
    <div class="totals-wrap">
      {summary_html}
      {notes_html}
      {sign_html}
    </div>
    """

    full_html = (
        "<!DOCTYPE html>"
        "<html lang='fa' dir='rtl'>"
        f"<head><meta charset='utf-8'><title>{_esc(spec.title)}</title>{css}</head>"
        f"<body>{body}</body></html>"
    )
    if spec.customer_privacy_strict:
        assert_no_internal_cost_leakage(full_html)
    return full_html


# Backward-compatible HTML entrypoints used cleanly by legacy callers & tests
def build_sales_invoice_html(
    records: Sequence[Dict[str, Any]],
    shop_info: Optional[Dict[str, Any]] = None,
    *,
    is_a5: bool = True,
) -> str:
    return render_spec_to_html(build_sales_invoice_spec(records, shop_info), is_a5=is_a5)


def build_proforma_invoice_html(
    records: Sequence[Dict[str, Any]],
    shop_info: Optional[Dict[str, Any]] = None,
    *,
    is_a5: bool = True,
) -> str:
    return render_spec_to_html(build_proforma_invoice_spec(records, shop_info), is_a5=is_a5)


def build_purchase_voucher_html(
    records: Sequence[Dict[str, Any]],
    shop_info: Optional[Dict[str, Any]] = None,
    *,
    is_a5: bool = True,
) -> str:
    return render_spec_to_html(build_purchase_voucher_spec(records, shop_info), is_a5=is_a5)


def build_service_or_upgrade_html(
    kind: str,
    records: Sequence[Dict[str, Any]],
    shop_info: Optional[Dict[str, Any]] = None,
    *,
    is_a5: bool = True,
) -> str:
    return render_spec_to_html(build_service_or_upgrade_spec(kind, records, shop_info), is_a5=is_a5)


def build_structured_table_report_html(
    report_title: str,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    summary_text: str = "",
    shop_info: Optional[Dict[str, Any]] = None,
    is_a5: bool = True,
) -> str:
    title = str(report_title or "گزارش چاپی").strip()
    if not title.startswith("گزارش"):
        title = f"گزارش چاپی {title}"
    return render_spec_to_html(
        build_section_table_spec(
            "reports",
            headers,
            rows,
            report_title=title,
            summary_text=summary_text,
            shop_info=shop_info,
        ),
        is_a5=is_a5,
    )


# ---------------------------------------------------------------------------
# Multi-Page Printer / PDF Engine with Running Persian Page Numbers
# ---------------------------------------------------------------------------

def configure_printer(
    printer: QPrinter,
    paper_size: str = "A5",
    orientation: str = "portrait",
) -> None:
    """Configure QPrinter paper size (A5 default / A4), orientation, >= 9mm margins & B&W GrayScale."""
    size_id = PAPER_SIZE_MAP.get(str(paper_size or "A5").strip().upper(), QPageSize.PageSizeId.A5)
    orient = (
        QPageLayout.Orientation.Landscape
        if str(orientation or "").strip().lower() == "landscape"
        else QPageLayout.Orientation.Portrait
    )
    printer.setPageSize(QPageSize(size_id))
    printer.setPageOrientation(orient)
    printer.setPageMargins(QMarginsF(9, 9, 9, 13), QPageLayout.Unit.Millimeter)
    printer.setColorMode(QPrinter.ColorMode.GrayScale)


def render_html_to_printer(html_content: str, printer: QPrinter) -> None:
    """Render HTML cleanly across dynamic pages with running Persian page footers ('صفحه ۱ از ۳')."""
    doc = QTextDocument()
    doc.setDefaultFont(QFont("B Nazanin", 10, QFont.Weight.Bold))
    page_rect = printer.pageRect(QPrinter.Unit.Point)
    body_w = max(120.0, float(page_rect.width()))
    body_h = max(120.0, float(page_rect.height()) - 18.0)
    doc.setPageSize(QSizeF(body_w, body_h))
    doc.setHtml(html_content)

    total_pages = max(1, int(doc.pageCount()))
    painter = QPainter()
    if not painter.begin(printer):
        doc.print_(printer)
        return
    try:
        # Scale QTextDocument logical points cleanly onto physical printer DPI coordinates
        paint_rect = printer.pageLayout().paintRectPixels(printer.resolution())
        scale_x = paint_rect.width() / body_w if body_w > 0 else 1.0
        footer_h_pts = 16.0
        footer_font = QFont("B Nazanin", 8, QFont.Weight.Bold)

        for page_idx in range(total_pages):
            if page_idx > 0:
                printer.newPage()
            painter.save()
            painter.scale(scale_x, scale_x)
            y_offset = page_idx * body_h
            painter.translate(0.0, -y_offset)
            clip = QRectF(0.0, y_offset, body_w, body_h)
            doc.drawContents(painter, clip)
            painter.restore()

            # Running footer in Persian numerals
            painter.save()
            painter.scale(scale_x, scale_x)
            painter.setFont(footer_font)
            painter.setPen(QColor("#000000"))
            footer_rect = QRectF(0.0, body_h + 2.0, body_w, footer_h_pts)
            footer_text = f"صفحه {to_persian_digits(page_idx + 1)} از {to_persian_digits(total_pages)}"
            painter.drawText(footer_rect, Qt.AlignCenter, footer_text)
            painter.restore()
    finally:
        painter.end()


def render_html_to_pdf(
    html_content: str,
    pdf_path: str,
    *,
    paper_size: str = "A5",
    orientation: str = "portrait",
) -> str:
    """Render invoice/report HTML directly to a B&W A5 or A4 PDF via QtPrintSupport."""
    out_path = os.path.abspath(pdf_path)
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(out_path)
    configure_printer(printer, paper_size=paper_size, orientation=orientation)
    render_html_to_printer(html_content, printer)
    return out_path


# ---------------------------------------------------------------------------
# Native Editable Word (.docx) Export with Authentic RTL & Complex-Script XML
# ---------------------------------------------------------------------------

def _set_paragraph_rtl(paragraph) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    bidi = OxmlElement("w:bidi")
    bidi.set(qn("w:val"), "1")
    pPr.append(bidi)


def _format_persian_run(
    run,
    *,
    font_name: str = "B Nazanin",
    size_pt: float = 9.0,
    bold: bool = True,
) -> None:
    run.bold = bold
    run.font.name = font_name
    run.font.size = Pt(size_pt)
    run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    rPr = run._r.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:ascii"), font_name)
    rFonts.set(qn("w:hAnsi"), font_name)
    rFonts.set(qn("w:cs"), font_name)

    rtl = OxmlElement("w:rtl")
    rtl.set(qn("w:val"), "1")
    rPr.append(rtl)
    if bold and rPr.find(qn("w:bCs")) is None:
        bCs = OxmlElement("w:bCs")
        rPr.append(bCs)
    sz_half_pt = str(int(round(size_pt * 2)))
    if rPr.find(qn("w:szCs")) is None:
        szCs = OxmlElement("w:szCs")
        szCs.set(qn("w:val"), sz_half_pt)
        rPr.append(szCs)


def _set_cell_pct_width(cell, pct: float) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    for old in tcPr.findall(qn("w:tcW")):
        tcPr.remove(old)
    tcW = OxmlElement("w:tcW")
    tcW.set(qn("w:w"), str(int(round(max(1.0, pct) * 50))))
    tcW.set(qn("w:type"), "pct")
    tcPr.append(tcW)


def _write_docx_runs_with_date_isolation(
    paragraph,
    text: Any,
    *,
    font_name: str = "B Nazanin",
    size_pt: float = 9.0,
    bold: bool = True,
) -> None:
    """Emit OOXML runs with U+2066..U+2069 and explicit w:rtl='0' on date/time tokens so dates never flip."""
    isolated = isolate_bidi_dates("" if text is None else str(text))
    parts = re.split(r"(\u2066[^\u2069]+\u2069)", isolated)
    for part in parts:
        if not part:
            continue
        is_date_seg = part.startswith(_LRI) and part.endswith(_PDI)
        run = paragraph.add_run(part)
        _format_persian_run(run, font_name=font_name, size_pt=size_pt, bold=bold)
        if is_date_seg:
            rPr = run._r.get_or_add_rPr()
            for old_rtl in rPr.findall(qn("w:rtl")):
                old_rtl.set(qn("w:val"), "0")


def _set_table_rtl_and_borders(table) -> None:
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    tblPr = table._tbl.tblPr
    for old_w in tblPr.findall(qn("w:tblW")):
        tblPr.remove(old_w)
    tblW = OxmlElement("w:tblW")
    tblW.set(qn("w:w"), "5000")
    tblW.set(qn("w:type"), "pct")
    tblPr.append(tblW)
    bidi_vis = OxmlElement("w:bidiVisual")
    tblPr.append(bidi_vis)
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        '<w:top w:val="single" w:sz="6" w:space="0" w:color="000000"/>'
        '<w:bottom w:val="single" w:sz="6" w:space="0" w:color="000000"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="222222"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="222222"/>'
        "</w:tblBorders>"
    )
    tblPr.append(borders)


def _shade_cell(cell, hex_fill: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_fill}"/>')
    tcPr.append(shd)


def _add_page_number_field(run) -> None:
    fld1 = OxmlElement("w:fldChar")
    fld1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld2 = OxmlElement("w:fldChar")
    fld2.set(qn("w:fldCharType"), "separate")
    fld3 = OxmlElement("w:fldChar")
    fld3.set(qn("w:fldCharType"), "end")
    run._r.append(fld1)
    run._r.append(instr)
    run._r.append(fld2)
    run._r.append(fld3)


def _add_numpages_field(run) -> None:
    fld1 = OxmlElement("w:fldChar")
    fld1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " NUMPAGES "
    fld2 = OxmlElement("w:fldChar")
    fld2.set(qn("w:fldCharType"), "separate")
    fld3 = OxmlElement("w:fldChar")
    fld3.set(qn("w:fldCharType"), "end")
    run._r.append(fld1)
    run._r.append(instr)
    run._r.append(fld2)
    run._r.append(fld3)


def export_spec_to_docx(
    spec: PrintDocumentSpec,
    docx_path: str,
    *,
    paper_size: str = "A5",
    orientation: str = "portrait",
) -> str:
    """Export any PrintDocumentSpec to a fully editable Word (.docx) with true RTL & B Nazanin/B Titr XML."""
    if spec.customer_privacy_strict:
        probe_blob = " ".join([spec.title, *spec.headers, *(c for r in spec.rows for c in r), spec.notes])
        assert_no_internal_cost_leakage(probe_blob)

    is_a5 = str(paper_size or "A5").strip().upper() == "A5"
    is_land = str(orientation or "").strip().lower() == "landscape"
    body_pt = 9.0 if is_a5 else 10.0
    head_pt = 12.0 if is_a5 else 14.0

    doc = Document()
    sec = doc.sections[0]
    w_mm, h_mm = (148, 210) if is_a5 else (210, 297)
    if is_land:
        w_mm, h_mm = h_mm, w_mm
    sec.page_width = Mm(w_mm)
    sec.page_height = Mm(h_mm)
    sec.top_margin = Mm(9)
    sec.bottom_margin = Mm(11)
    sec.right_margin = Mm(9)
    sec.left_margin = Mm(9)

    # Header band (logical RTL column order with <w:bidiVisual/>: 0=right shop, 1=center title, 2=left date)
    hdr_tbl = doc.add_table(rows=1, cols=3)
    _set_table_rtl_and_borders(hdr_tbl)
    c0, c1, c2 = hdr_tbl.rows[0].cells
    _set_cell_pct_width(c0, 36.0)
    _set_cell_pct_width(c1, 32.0)
    _set_cell_pct_width(c2, 32.0)
    c0.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    c1.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    c2.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p0 = c0.paragraphs[0]
    _set_paragraph_rtl(p0)
    p0.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _write_docx_runs_with_date_isolation(p0, spec.shop_name, font_name="B Titr", size_pt=head_pt, bold=True)
    if spec.shop_phone:
        p0_sub = c0.add_paragraph()
        _set_paragraph_rtl(p0_sub)
        p0_sub.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _write_docx_runs_with_date_isolation(p0_sub, f"تلفن: {spec.shop_phone}", font_name="B Nazanin", size_pt=body_pt - 0.5, bold=True)

    _shade_cell(c1, "EFEFEF")
    p1 = c1.paragraphs[0]
    _set_paragraph_rtl(p1)
    p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _write_docx_runs_with_date_isolation(p1, spec.title, font_name="B Titr", size_pt=head_pt, bold=True)

    p2 = c2.paragraphs[0]
    _set_paragraph_rtl(p2)
    p2.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _write_docx_runs_with_date_isolation(p2, f"تاریخ چاپ: {spec.print_time or '-'}", font_name="B Nazanin", size_pt=body_pt - 0.5, bold=True)

    # Metadata strip
    if spec.meta_pairs:
        m_tbl = doc.add_table(rows=1, cols=len(spec.meta_pairs))
        _set_table_rtl_and_borders(m_tbl)
        meta_pct = 100.0 / max(1, len(spec.meta_pairs))
        for idx, (mk, mv) in enumerate(spec.meta_pairs):
            cell = m_tbl.rows[0].cells[idx]
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            _set_cell_pct_width(cell, meta_pct)
            _shade_cell(cell, "FAFAFA")
            p = cell.paragraphs[0]
            _set_paragraph_rtl(p)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _write_docx_runs_with_date_isolation(p, f"{mk}: {mv}", font_name="B Nazanin", size_pt=body_pt - 0.5, bold=True)

    # Chart snapshot if present
    if spec.chart_png_bytes:
        cp = doc.add_paragraph()
        _set_paragraph_rtl(cp)
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cp.add_run().add_picture(io.BytesIO(spec.chart_png_bytes), width=Mm(max(90, w_mm - 26)))

    # Data table with w:tblHeader (repeating header across pages), w:cantSplit, centered cells & col_widths_pct
    if spec.headers:
        tbl = doc.add_table(rows=1 + len(spec.rows), cols=len(spec.headers))
        _set_table_rtl_and_borders(tbl)
        usable_w_mm = max(80.0, float(w_mm) - 18.0)
        equal_pct = 100.0 / max(1, len(spec.headers))
        hdr_row = tbl.rows[0]
        hdr_trPr = hdr_row._tr.get_or_add_trPr()
        hdr_trPr.append(OxmlElement("w:tblHeader"))
        hdr_trPr.append(OxmlElement("w:cantSplit"))

        for c_idx, h_text in enumerate(spec.headers):
            cell = hdr_row.cells[c_idx]
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            pct = float(spec.col_widths_pct[c_idx]) if (spec.col_widths_pct and c_idx < len(spec.col_widths_pct)) else equal_pct
            _set_cell_pct_width(cell, pct)
            cell.width = Mm(usable_w_mm * pct / 100.0)
            _shade_cell(cell, "EFEFEF")
            p = cell.paragraphs[0]
            _set_paragraph_rtl(p)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _write_docx_runs_with_date_isolation(p, str(h_text), font_name="B Titr", size_pt=body_pt, bold=True)

        for r_idx, row_vals in enumerate(spec.rows, 1):
            row_obj = tbl.rows[r_idx]
            row_trPr = row_obj._tr.get_or_add_trPr()
            row_trPr.append(OxmlElement("w:cantSplit"))
            for c_idx, val in enumerate(row_vals):
                if c_idx >= len(spec.headers):
                    continue
                cell = row_obj.cells[c_idx]
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                pct = float(spec.col_widths_pct[c_idx]) if (spec.col_widths_pct and c_idx < len(spec.col_widths_pct)) else equal_pct
                _set_cell_pct_width(cell, pct)
                cell.width = Mm(usable_w_mm * pct / 100.0)
                if r_idx % 2 == 0:
                    _shade_cell(cell, "FAFAFA")
                p = cell.paragraphs[0]
                _set_paragraph_rtl(p)
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                _write_docx_runs_with_date_isolation(p, str(val), font_name="B Nazanin", size_pt=body_pt, bold=True)

    # Summary block
    if spec.summary_pairs:
        sp_p = doc.add_paragraph()
        sp_p.paragraph_format.space_before = Pt(4)
        sp_p.paragraph_format.space_after = Pt(2)
        s_tbl = doc.add_table(rows=len(spec.summary_pairs), cols=2)
        _set_table_rtl_and_borders(s_tbl)
        for idx, (sk, sv) in enumerate(spec.summary_pairs):
            row_trPr = s_tbl.rows[idx]._tr.get_or_add_trPr()
            row_trPr.append(OxmlElement("w:cantSplit"))
            lc, vc = s_tbl.rows[idx].cells[0], s_tbl.rows[idx].cells[1]
            lc.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            vc.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            _set_cell_pct_width(lc, 45.0)
            _set_cell_pct_width(vc, 55.0)
            _shade_cell(lc, "EFEFEF")
            lp = lc.paragraphs[0]
            _set_paragraph_rtl(lp)
            lp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            _write_docx_runs_with_date_isolation(lp, sk, font_name="B Nazanin", size_pt=body_pt, bold=True)
            vp = vc.paragraphs[0]
            _set_paragraph_rtl(vp)
            vp.alignment = WD_ALIGN_PARAGRAPH.LEFT
            _write_docx_runs_with_date_isolation(vp, sv, font_name="B Nazanin", size_pt=body_pt, bold=True)

    if spec.notes:
        np = doc.add_paragraph()
        _set_paragraph_rtl(np)
        np.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _write_docx_runs_with_date_isolation(np, f"توضیحات: {spec.notes}", font_name="B Nazanin", size_pt=body_pt - 0.5, bold=True)

    if spec.signatures:
        sig_p = doc.add_paragraph()
        sig_p.paragraph_format.space_before = Pt(8)
        sig_tbl = doc.add_table(rows=1, cols=2)
        _set_table_rtl_and_borders(sig_tbl)
        sig_tbl.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        for idx, s_lbl in enumerate(spec.signatures):
            p = sig_tbl.rows[0].cells[idx].paragraphs[0]
            _set_paragraph_rtl(p)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _format_persian_run(p.add_run(f"{s_lbl}\n\n"), font_name="B Nazanin", size_pt=body_pt, bold=True)

    # Word page number footer
    ftr = sec.footer
    fp = ftr.paragraphs[0]
    _set_paragraph_rtl(fp)
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _format_persian_run(fp.add_run("صفحه "), font_name="B Nazanin", size_pt=8.5, bold=True)
    r_pg = fp.add_run()
    _format_persian_run(r_pg, font_name="B Nazanin", size_pt=8.5, bold=True)
    _add_page_number_field(r_pg)
    _format_persian_run(fp.add_run(" از "), font_name="B Nazanin", size_pt=8.5, bold=True)
    r_num = fp.add_run()
    _format_persian_run(r_num, font_name="B Nazanin", size_pt=8.5, bold=True)
    _add_numpages_field(r_num)

    out_path = os.path.abspath(docx_path)
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    doc.save(out_path)
    return out_path


# ---------------------------------------------------------------------------
# Print Preview Dialog (A5 Default + A4 Toggle + Editable Word .docx Export)
# ---------------------------------------------------------------------------

class PrintPreviewDialog(QDialog):
    """Commercial monochrome B&W RTL print preview dialog defaulting to A5 with A4 toggle, PDF & Word export."""

    def __init__(
        self,
        spec_or_builder,
        *,
        title: str = "پیش‌نمایش چاپ",
        default_paper: str = "A5",
        word_export_guard: Optional[Callable[[], bool]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._spec_or_builder = spec_or_builder
        self._word_export_guard = word_export_guard
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle(title)
        self.resize(960, 740)

        is_offscreen = str(os.environ.get("QT_QPA_PLATFORM") or "").strip().lower() == "offscreen"
        self.printer = QPrinter(
            QPrinter.PrinterMode.ScreenResolution if is_offscreen else QPrinter.PrinterMode.HighResolution
        )
        configure_printer(self.printer, paper_size=default_paper, orientation="portrait")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        toolbar.addWidget(QLabel("اندازه کاغذ:"))
        self.cb_paper = QComboBox()
        self.cb_paper.addItem("A5 (۱۴۸ × ۲۱۰ میلی‌متر)", "A5")
        self.cb_paper.addItem("A4 (۲۱۰ × ۲۹۷ میلی‌متر)", "A4")
        if str(default_paper or "A5").upper() == "A4":
            self.cb_paper.setCurrentIndex(1)
        self.cb_paper.currentIndexChanged.connect(self._apply_page_settings)
        toolbar.addWidget(self.cb_paper)

        toolbar.addWidget(QLabel("جهت صفحه:"))
        self.cb_orientation = QComboBox()
        self.cb_orientation.addItem("عمودی", "portrait")
        self.cb_orientation.addItem("افقی", "landscape")
        self.cb_orientation.currentIndexChanged.connect(self._apply_page_settings)
        toolbar.addWidget(self.cb_orientation)

        btn_zoom_out = QPushButton("− کوچکنمایی")
        btn_zoom_out.clicked.connect(lambda: self.preview.zoomOut())
        btn_zoom_in = QPushButton("+ بزرگنمایی")
        btn_zoom_in.clicked.connect(lambda: self.preview.zoomIn())
        btn_fit = QPushButton("تناسب با عرض")
        btn_fit.clicked.connect(lambda: self.preview.fitToWidth())

        toolbar.addWidget(btn_zoom_out)
        toolbar.addWidget(btn_zoom_in)
        toolbar.addWidget(btn_fit)
        toolbar.addStretch(1)

        self.btn_save_docx = QPushButton("📝 خروجی Word (.docx)")
        self.btn_save_docx.clicked.connect(self._save_docx)
        self.btn_save_pdf = QPushButton("📄 ذخیره PDF")
        self.btn_save_pdf.clicked.connect(self._save_pdf)
        self.btn_print = QPushButton("🖨️ چاپ نهایی")
        self.btn_print.setObjectName("btnSuccess")
        self.btn_print.clicked.connect(self._print_document)
        btn_close = QPushButton("بستن")
        btn_close.clicked.connect(self.reject)

        toolbar.addWidget(self.btn_save_docx)
        toolbar.addWidget(self.btn_save_pdf)
        toolbar.addWidget(self.btn_print)
        toolbar.addWidget(btn_close)
        root.addLayout(toolbar)

        self.preview = QPrintPreviewWidget(self.printer, self)
        self.preview.paintRequested.connect(self._on_paint_requested)
        root.addWidget(self.preview, 1)

    def current_spec(self) -> Optional[PrintDocumentSpec]:
        attached = getattr(self._spec_or_builder, "spec", None)
        if isinstance(attached, PrintDocumentSpec):
            return attached
        val = self._spec_or_builder() if callable(self._spec_or_builder) else self._spec_or_builder
        if isinstance(val, PrintDocumentSpec):
            return val
        return None

    def current_html(self) -> str:
        is_a5 = str(self.cb_paper.currentData() or "A5").upper() == "A5"
        if isinstance(self._spec_or_builder, PrintDocumentSpec):
            return render_spec_to_html(self._spec_or_builder, is_a5=is_a5)
        if callable(self._spec_or_builder):
            try:
                res = self._spec_or_builder(is_a5=is_a5)
            except TypeError:
                res = self._spec_or_builder()
            if isinstance(res, PrintDocumentSpec):
                return render_spec_to_html(res, is_a5=is_a5)
            return str(res)
        return str(self._spec_or_builder)

    def _on_paint_requested(self, printer: QPrinter) -> None:
        render_html_to_printer(self.current_html(), printer)

    def _apply_page_settings(self) -> None:
        paper = str(self.cb_paper.currentData() or "A5")
        orient = str(self.cb_orientation.currentData() or "portrait")
        configure_printer(self.printer, paper_size=paper, orientation=orient)
        self.preview.updatePreview()

    def _save_docx(self) -> None:
        if callable(self._word_export_guard) and not self._word_export_guard():
            return
        spec = self.current_spec()
        if spec is None:
            QMessageBox.warning(self, "خروجی Word", "قالب داده‌های این سند برای تبدیل به Word آماده نیست.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "ذخیره فایل قابل ویرایش Word", "Daqiq_Document.docx", "Word Document (*.docx)"
        )
        if not path:
            return
        try:
            paper = str(self.cb_paper.currentData() or "A5")
            orient = str(self.cb_orientation.currentData() or "portrait")
            saved = export_spec_to_docx(spec, path, paper_size=paper, orientation=orient)
            QMessageBox.information(self, "خروجی Word", f"فایل قابل ویرایش Word با موفقیت ذخیره شد:\n{saved}")
        except Exception as exc:
            QMessageBox.critical(self, "خطا در ذخیره Word", str(exc))

    def _save_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "ذخیره فایل PDF", "Daqiq_Print.pdf", "PDF Files (*.pdf)"
        )
        if not path:
            return
        try:
            paper = str(self.cb_paper.currentData() or "A5")
            orient = str(self.cb_orientation.currentData() or "portrait")
            render_html_to_pdf(
                self.current_html(), path, paper_size=paper, orientation=orient
            )
            QMessageBox.information(self, "ذخیره PDF", f"فایل PDF با موفقیت ذخیره شد:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "خطا در ذخیره PDF", str(exc))

    def _print_document(self) -> None:
        dlg = QPrintDialog(self.printer, self)
        dlg.setWindowTitle("انتخاب چاپگر")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            render_html_to_printer(self.current_html(), self.printer)
            self.accept()

    def _release_preview_widgets(self) -> None:
        preview = getattr(self, "preview", None)
        if preview is not None:
            try:
                preview.setParent(None)
                preview.deleteLater()
            except RuntimeError:
                pass
            self.preview = None

    def closeEvent(self, event) -> None:
        self._release_preview_widgets()
        super().closeEvent(event)

    def done(self, result: int) -> None:
        self._release_preview_widgets()
        super().done(result)
