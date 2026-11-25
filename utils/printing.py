# utils/printing.py
"""Monochrome (black & white) A4/A5 RTL invoice and report printing for Daqiq."""

from __future__ import annotations

import html
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence

from PySide6.QtCore import Qt, QMarginsF
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QTextDocument
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

# Forbidden internal terms on customer-facing sales invoices (cost/profit/margin protection)
FORBIDDEN_SALES_INVOICE_TERMS = (
    "بهای تمام‌شده",
    "بهای تمام شده",
    "قیمت خرید",
    "سود واحد",
    "سود کل",
    "سود خالص",
    "درصد سود",
    "قیمت پیشنهادی",
    "unit_cost_price",
    "unit_profit",
    "total_profit",
)

PAPER_SIZE_MAP = {
    "A4": QPageSize.PageSizeId.A4,
    "A5": QPageSize.PageSizeId.A5,
}


def _esc(val: Any) -> str:
    return html.escape("" if val is None else str(val), quote=True)


def _norm_num(val: Any) -> str:
    if val is None:
        return "0"
    if isinstance(val, bool):
        return "0"
    if isinstance(val, (int, float)):
        return f"{int(round(val)):,}"
    text = str(val).strip()
    return text or "0"


def assert_no_internal_cost_leakage(rendered_html: str) -> None:
    """Verify no internal cost, margin, or profit label leaks into customer invoices."""
    lowered = rendered_html.lower()
    for term in FORBIDDEN_SALES_INVOICE_TERMS:
        if term.lower() in lowered:
            raise ValueError(f"Internal financial term leaked into customer invoice: {term}")


def _base_print_css(is_a5: bool = False) -> str:
    font_px = "9.5pt" if is_a5 else "10.5pt"
    head_px = "13pt" if is_a5 else "15pt"
    sub_px = "8.5pt" if is_a5 else "9.5pt"
    cell_pad = "4px 6px" if is_a5 else "6px 8px"
    return f"""
    <style>
      @page {{ margin: 10mm; }}
      body {{
        direction: rtl;
        font-family: 'Tahoma', 'Segoe UI', Arial, sans-serif;
        font-size: {font_px};
        color: #000000;
        background-color: #ffffff;
        margin: 0;
        padding: 4px;
      }}
      .doc-box {{
        border: 1.5px solid #000000;
        padding: 10px 12px;
        margin-bottom: 14px;
        page-break-inside: avoid;
      }}
      .header-table {{
        width: 100%;
        border-collapse: collapse;
        border-bottom: 2px solid #000000;
        margin-bottom: 8px;
      }}
      .header-table td {{
        border: none;
        padding: 3px 4px;
        vertical-align: middle;
      }}
      .shop-name {{
        font-size: {head_px};
        font-weight: bold;
        color: #000000;
      }}
      .doc-title {{
        font-size: {head_px};
        font-weight: bold;
        text-align: center;
        border: 1.5px solid #000000;
        background-color: #efefef;
        padding: 4px 12px;
      }}
      .meta-grid {{
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 8px;
        font-size: {sub_px};
      }}
      .meta-grid td {{
        border: 1px solid #555555;
        padding: 4px 7px;
        background-color: #fafafa;
      }}
      table.items {{
        width: 100%;
        border-collapse: collapse;
        margin-top: 6px;
        margin-bottom: 8px;
      }}
      table.items th {{
        background-color: #e5e5e5;
        color: #000000;
        font-weight: bold;
        border: 1px solid #000000;
        padding: {cell_pad};
        text-align: center;
      }}
      table.items td {{
        border: 1px solid #222222;
        padding: {cell_pad};
        color: #000000;
        text-align: center;
      }}
      table.items tr:nth-child(even) td {{
        background-color: #f8f8f8;
      }}
      td.right, th.right {{ text-align: right; }}
      .summary-table {{
        width: 56%;
        margin-right: auto;
        margin-left: 0;
        border-collapse: collapse;
        margin-top: 6px;
      }}
      .summary-table td {{
        border: 1px solid #000000;
        padding: 4px 8px;
      }}
      .summary-table td.lbl {{
        background-color: #efefef;
        font-weight: bold;
        text-align: right;
      }}
      .summary-table td.val {{
        font-weight: bold;
        text-align: left;
      }}
      .footer-sign {{
        width: 100%;
        border-collapse: collapse;
        margin-top: 14px;
        font-size: {sub_px};
      }}
      .footer-sign td {{
        width: 50%;
        padding: 8px 6px 2px 6px;
        text-align: center;
        border-top: 1px dashed #666666;
      }}
      .muted-note {{
        font-size: {sub_px};
        margin-top: 6px;
        color: #111111;
      }}
    </style>
    """


def _wrap_html_doc(body_html: str, title: str, is_a5: bool = False) -> str:
    return (
        "<!DOCTYPE html>"
        "<html lang='fa' dir='rtl'>"
        f"<head><meta charset='utf-8'><title>{_esc(title)}</title>"
        f"{_base_print_css(is_a5=is_a5)}</head>"
        f"<body>{body_html}</body></html>"
    )


def build_sales_invoice_html(
    records: Sequence[Dict[str, Any]],
    shop_info: Optional[Dict[str, Any]] = None,
    *,
    is_a5: bool = False,
) -> str:
    """Build strict customer-only B&W sales invoice HTML (zero internal cost or profit fields)."""
    shop = shop_info or {}
    shop_name = str(shop.get("shop_name") or "فروشگاه دقیق").strip()
    print_time = str(shop.get("print_time") or "").strip()
    support_phone = str(shop.get("phone") or "").strip()

    # Group rows sharing non-empty invoice_number into unified multi-line invoices.
    grouped: List[List[Dict[str, Any]]] = []
    index_by_inv: Dict[str, int] = {}
    for row in records:
        inv_no = str(row.get("invoice_number") or "").strip()
        if inv_no and inv_no in index_by_inv:
            grouped[index_by_inv[inv_no]].append(row)
        else:
            if inv_no:
                index_by_inv[inv_no] = len(grouped)
            grouped.append([row])

    sections: List[str] = []
    for inv_rows in grouped:
        first = inv_rows[0]
        inv_no = _esc(first.get("invoice_number") or "-")
        sale_dt = _esc(first.get("sale_datetime") or print_time or "-")
        customer = _esc(first.get("customer_name") or "مشتری حضوری")
        cust_phone = _esc(first.get("customer_phone") or "-")
        seller = _esc(first.get("seller_name") or "-")

        total_amount_sum = 0
        total_discount_sum = 0
        paid_sum = 0
        statuses: List[str] = []
        item_trs: List[str] = []

        for idx, item in enumerate(inv_rows, 1):
            qty = int(item.get("qty") or 0)
            unit_price = int(item.get("actual_unit_price") or 0)
            disc = int(item.get("total_discount") or 0)
            line_total = int(item.get("total_amount") or 0)
            paid = int(item.get("paid_amount") or 0)
            total_amount_sum += line_total
            total_discount_sum += disc
            paid_sum += paid
            st = str(item.get("settlement_status") or "").strip()
            if st and st not in statuses:
                statuses.append(st)

            desc_parts = [str(item.get("product_title") or item.get("description") or "کالا").strip()]
            specs = str(item.get("specifications") or "").strip()
            colors = str(item.get("colors_display") or "").strip()
            serial = str(item.get("serial_number") or "").strip()
            if specs:
                desc_parts.append(f"مشخصات: {specs}")
            if colors:
                desc_parts.append(f"رنگ: {colors}")
            if serial:
                desc_parts.append(f"سریال: {serial}")
            warranty = str(item.get("warranty_text") or "").strip()

            item_trs.append(
                "<tr>"
                f"<td>{idx}</td>"
                f"<td>{_esc(item.get('product_code') or '-')}</td>"
                f"<td class='right'>{'<br>'.join(_esc(p) for p in desc_parts if p)}</td>"
                f"<td>{qty:,}</td>"
                f"<td>{unit_price:,}</td>"
                f"<td>{disc:,}</td>"
                f"<td>{line_total:,}</td>"
                f"<td>{_esc(warranty or 'ندارد')}</td>"
                "</tr>"
            )

        remaining = max(0, total_amount_sum - paid_sum)
        status_text = " / ".join(statuses) if statuses else ("تسویه‌شده" if remaining == 0 else "بدهکار")

        notes = [str(r.get("notes") or "").strip() for r in inv_rows if str(r.get("notes") or "").strip()]
        notes_html = (
            f"<div class='muted-note'><b>توضیحات:</b> {_esc(' | '.join(dict.fromkeys(notes)))}</div>"
            if notes
            else ""
        )
        phone_html = f"<div>تلفن فروشگاه: {_esc(support_phone)}</div>" if support_phone else ""

        sections.append(
            f"""
            <div class="doc-box">
              <table class="header-table">
                <tr>
                  <td style="width:36%;" class="right"><div class="shop-name">{_esc(shop_name)}</div>{phone_html}</td>
                  <td style="width:28%;"><div class="doc-title">فاکتور فروش</div></td>
                  <td style="width:36%; text-align:left;">
                    <div><b>شماره فاکتور:</b> {inv_no}</div>
                    <div><b>تاریخ و ساعت:</b> {sale_dt}</div>
                  </td>
                </tr>
              </table>
              <table class="meta-grid">
                <tr>
                  <td><b>خریدار:</b> {customer}</td>
                  <td><b>شماره تماس:</b> {cust_phone}</td>
                  <td><b>فروشنده:</b> {seller}</td>
                </tr>
              </table>
              <table class="items">
                <thead>
                  <tr>
                    <th style="width:5%;">ردیف</th>
                    <th style="width:11%;">کد کالا</th>
                    <th class="right" style="width:36%;">شرح کالا و مشخصات فنی</th>
                    <th style="width:7%;">تعداد</th>
                    <th style="width:12%;">فی واحد (تومان)</th>
                    <th style="width:10%;">تخفیف</th>
                    <th style="width:12%;">مبلغ کل (تومان)</th>
                    <th style="width:12%;">گارانتی</th>
                  </tr>
                </thead>
                <tbody>{''.join(item_trs)}</tbody>
              </table>
              <table class="summary-table">
                <tr><td class="lbl">تخفیف کل فاکتور (تومان)</td><td class="val">{total_discount_sum:,}</td></tr>
                <tr><td class="lbl">مبلغ قابل پرداخت (تومان)</td><td class="val">{total_amount_sum:,}</td></tr>
                <tr><td class="lbl">مبلغ پرداخت‌شده (تومان)</td><td class="val">{paid_sum:,}</td></tr>
                <tr><td class="lbl">مانده حساب مشتری (تومان)</td><td class="val">{remaining:,}</td></tr>
                <tr><td class="lbl">وضعیت تسویه</td><td class="val">{_esc(status_text)}</td></tr>
              </table>
              {notes_html}
              <table class="footer-sign">
                <tr><td>مهر و امضای فروشنده</td><td>امضای خریدار / تحویل‌گیرنده</td></tr>
              </table>
            </div>
            """
        )

    rendered = _wrap_html_doc("".join(sections), "فاکتور فروش", is_a5=is_a5)
    assert_no_internal_cost_leakage(rendered)
    return rendered


def build_purchase_voucher_html(
    records: Sequence[Dict[str, Any]],
    shop_info: Optional[Dict[str, Any]] = None,
    *,
    is_a5: bool = False,
) -> str:
    """Build monochrome A4/A5 B&W purchase voucher HTML («رسید خرید و ثبت محموله»)."""
    shop = shop_info or {}
    shop_name = str(shop.get("shop_name") or "فروشگاه دقیق").strip()
    print_time = str(shop.get("print_time") or "").strip()

    rows_html: List[str] = []
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
        specs = str(rec.get("specs") or "").strip()
        colors = str(rec.get("colors") or "").strip()
        serials = str(rec.get("serials") or "").strip()
        details = [str(rec.get("product_title") or "-")]
        if specs:
            details.append(f"مشخصات: {specs}")
        if colors:
            details.append(f"رنگ: {colors}")
        if serials:
            details.append(f"سریال: {serials}")

        rows_html.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td>{_esc(rec.get('batch_code') or '-')}</td>"
            f"<td>{_esc(rec.get('invoice_number') or '-')}</td>"
            f"<td>{_esc(rec.get('purchase_date') or '-')}</td>"
            f"<td>{_esc(rec.get('supplier_name') or '-')}</td>"
            f"<td class='right'>{'<br>'.join(_esc(d) for d in details if d)}</td>"
            f"<td>{_norm_num(rec.get('initial_qty'))}</td>"
            f"<td>{_norm_num(rec.get('unit_purchase_price'))}</td>"
            f"<td>{_norm_num(rec.get('extra_cost_total'))}</td>"
            f"<td>{tot:,}</td>"
            f"<td>{paid:,}</td>"
            f"<td>{rem:,}</td>"
            f"<td>{_esc(rec.get('settlement_status') or '-')}</td>"
            "</tr>"
        )

    body = f"""
    <div class="doc-box">
      <table class="header-table">
        <tr>
          <td style="width:35%;" class="right"><div class="shop-name">{_esc(shop_name)}</div></td>
          <td style="width:30%;"><div class="doc-title">رسید خرید و ثبت محموله</div></td>
          <td style="width:35%; text-align:left;">
            <div><b>تعداد ردیف انتخابی:</b> {len(records)}</div>
            <div><b>تاریخ چاپ:</b> {_esc(print_time or '-')}</div>
          </td>
        </tr>
      </table>
      <table class="items">
        <thead>
          <tr>
            <th>ردیف</th>
            <th>کد محموله</th>
            <th>شماره فاکتور</th>
            <th>تاریخ خرید</th>
            <th>تأمین‌کننده</th>
            <th class="right">شرح کالا و مشخصات</th>
            <th>تعداد کل</th>
            <th>قیمت خرید واحد</th>
            <th>هزینه جانبی</th>
            <th>جمع فاکتور</th>
            <th>پرداخت‌شده</th>
            <th>مانده بدهی</th>
            <th>وضعیت</th>
          </tr>
        </thead>
        <tbody>{''.join(rows_html)}</tbody>
      </table>
      <table class="summary-table">
        <tr><td class="lbl">جمع کل فاکتورهای انتخابی (تومان)</td><td class="val">{grand_total:,}</td></tr>
        <tr><td class="lbl">جمع پرداخت‌شده (تومان)</td><td class="val">{grand_paid:,}</td></tr>
        <tr><td class="lbl">جمع مانده بدهی (تومان)</td><td class="val">{grand_rem:,}</td></tr>
      </table>
      <table class="footer-sign">
        <tr><td>امضای انباردار / خریدار</td><td>تأیید مدیریت / تأمین‌کننده</td></tr>
      </table>
    </div>
    """
    return _wrap_html_doc(body, "رسید خرید و ثبت محموله", is_a5=is_a5)


def build_service_or_upgrade_html(
    kind: str,
    records: Sequence[Dict[str, Any]],
    shop_info: Optional[Dict[str, Any]] = None,
    *,
    is_a5: bool = False,
) -> str:
    """Build B&W customer Service Invoice («فاکتور خدمات فنی») or Upgrade Voucher («رسید ارتقای کالا»)."""
    shop = shop_info or {}
    shop_name = str(shop.get("shop_name") or "فروشگاه دقیق").strip()
    print_time = str(shop.get("print_time") or "").strip()

    if kind == "upgrades":
        doc_title = "رسید ارتقای کالا"
        headers = [
            "ردیف", "تاریخ ارتقا", "کد محموله هدف", "تعداد هدف", "شرح قطعه / ارتقا",
            "هزینه افزوده‌شده واحد", "مسئول / تکنسین", "مشخصات جدید", "توضیحات",
        ]
        trs: List[str] = []
        total_added = 0
        for idx, rec in enumerate(records, 1):
            qty = int(rec.get("target_qty") or 1)
            unit_add = int(rec.get("added_cost_unit") or 0)
            total_added += qty * unit_add
            trs.append(
                "<tr>"
                f"<td>{idx}</td>"
                f"<td>{_esc(rec.get('upgrade_date') or '-')}</td>"
                f"<td>{_esc(rec.get('target_batch_code') or '-')}</td>"
                f"<td>{qty:,}</td>"
                f"<td class='right'>{_esc(rec.get('part_desc') or '-')}</td>"
                f"<td>{unit_add:,}</td>"
                f"<td>{_esc(rec.get('technician_name') or '-')}</td>"
                f"<td class='right'>{_esc(rec.get('new_specs') or '-')}</td>"
                f"<td class='right'>{_esc(rec.get('notes') or '-')}</td>"
                "</tr>"
            )
        summary = (
            f"<table class='summary-table'>"
            f"<tr><td class='lbl'>جمع هزینه ارتقای انتخابی (تومان)</td><td class='val'>{total_added:,}</td></tr>"
            f"</table>"
        )
    else:
        doc_title = "فاکتور خدمات و تعمیرات"
        headers = [
            "ردیف", "شماره فاکتور", "تاریخ و ساعت", "نوع خدمت", "نام خدمت",
            "مشتری", "مسئول خدمت", "تعرفه / مبلغ (تومان)", "پرداخت‌شده", "وضعیت تسویه", "شرح",
        ]
        trs = []
        tot_fee = 0
        tot_paid = 0
        for idx, rec in enumerate(records, 1):
            fee = int(rec.get("service_fee") or 0)
            paid = int(rec.get("paid_amount") or 0)
            tot_fee += fee
            tot_paid += paid
            trs.append(
                "<tr>"
                f"<td>{idx}</td>"
                f"<td>{_esc(rec.get('invoice_number') or '-')}</td>"
                f"<td>{_esc(rec.get('service_datetime') or '-')}</td>"
                f"<td>{_esc(rec.get('service_type') or '-')}</td>"
                f"<td class='right'>{_esc(rec.get('service_name') or '-')}</td>"
                f"<td>{_esc(rec.get('customer_name') or 'مشتری حضوری')}</td>"
                f"<td>{_esc(rec.get('technician_name') or '-')}</td>"
                f"<td>{fee:,}</td>"
                f"<td>{paid:,}</td>"
                f"<td>{_esc(rec.get('settlement_status') or '-')}</td>"
                f"<td class='right'>{_esc(rec.get('description') or '-')}</td>"
                "</tr>"
            )
        summary = (
            f"<table class='summary-table'>"
            f"<tr><td class='lbl'>جمع مبلغ خدمات (تومان)</td><td class='val'>{tot_fee:,}</td></tr>"
            f"<tr><td class='lbl'>جمع دریافتی (تومان)</td><td class='val'>{tot_paid:,}</td></tr>"
            f"<tr><td class='lbl'>مانده حساب (تومان)</td><td class='val'>{max(0, tot_fee - tot_paid):,}</td></tr>"
            f"</table>"
        )

    th_html = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = f"""
    <div class="doc-box">
      <table class="header-table">
        <tr>
          <td style="width:35%;" class="right"><div class="shop-name">{_esc(shop_name)}</div></td>
          <td style="width:30%;"><div class="doc-title">{_esc(doc_title)}</div></td>
          <td style="width:35%; text-align:left;">
            <div><b>تعداد ردیف:</b> {len(records)}</div>
            <div><b>تاریخ چاپ:</b> {_esc(print_time or '-')}</div>
          </td>
        </tr>
      </table>
      <table class="items">
        <thead><tr>{th_html}</tr></thead>
        <tbody>{''.join(trs)}</tbody>
      </table>
      {summary}
      <table class="footer-sign">
        <tr><td>امضای مسئول فنی / فروشگاه</td><td>امضای مشتری</td></tr>
      </table>
    </div>
    """
    return _wrap_html_doc(body, doc_title, is_a5=is_a5)


def build_structured_table_report_html(
    report_title: str,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    summary_text: str = "",
    shop_info: Optional[Dict[str, Any]] = None,
    is_a5: bool = False,
) -> str:
    """Build monochrome A4/A5 B&W structured report table HTML («گزارش چاپی ...»)."""
    shop = shop_info or {}
    shop_name = str(shop.get("shop_name") or "فروشگاه دقیق").strip()
    print_time = str(shop.get("print_time") or "").strip()

    title = str(report_title or "گزارش چاپی").strip()
    if not title.startswith("گزارش"):
        title = f"گزارش چاپی {title}"

    ths = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    trs: List[str] = []
    for row in rows:
        tds = "".join(f"<td>{_esc(cell)}</td>" for cell in row)
        trs.append(f"<tr>{tds}</tr>")

    summary_html = (
        f"<div class='muted-note' style='border:1px solid #000; padding:6px 8px; background:#f3f3f3;'><b>خلاصه:</b> {_esc(summary_text)}</div>"
        if summary_text
        else ""
    )

    body = f"""
    <div class="doc-box">
      <table class="header-table">
        <tr>
          <td style="width:35%;" class="right"><div class="shop-name">{_esc(shop_name)}</div></td>
          <td style="width:30%;"><div class="doc-title">{_esc(title)}</div></td>
          <td style="width:35%; text-align:left;">
            <div><b>تعداد ردیف چاپی:</b> {len(rows)}</div>
            <div><b>تاریخ چاپ:</b> {_esc(print_time or '-')}</div>
          </td>
        </tr>
      </table>
      <table class="items">
        <thead><tr>{ths}</tr></thead>
        <tbody>{''.join(trs)}</tbody>
      </table>
      {summary_html}
    </div>
    """
    return _wrap_html_doc(body, title, is_a5=is_a5)


def configure_printer(
    printer: QPrinter,
    paper_size: str = "A4",
    orientation: str = "portrait",
) -> None:
    """Configure QPrinter paper size (A4/A5), orientation, and monochrome B&W color mode."""
    size_id = PAPER_SIZE_MAP.get(str(paper_size or "A4").strip().upper(), QPageSize.PageSizeId.A4)
    orient = (
        QPageLayout.Orientation.Landscape
        if str(orientation or "").strip().lower() == "landscape"
        else QPageLayout.Orientation.Portrait
    )
    printer.setPageSize(QPageSize(size_id))
    printer.setPageOrientation(orient)
    printer.setPageMargins(QMarginsF(8, 8, 8, 8), QPageLayout.Unit.Millimeter)
    printer.setColorMode(QPrinter.ColorMode.GrayScale)


def render_html_to_printer(html_content: str, printer: QPrinter) -> None:
    """Render HTML onto the supplied QPrinter cleanly via QTextDocument."""
    doc = QTextDocument()
    doc.setDefaultFont(QFont("Tahoma", 10))
    doc.setPageSize(printer.pageRect(QPrinter.Unit.Point).size())
    doc.setHtml(html_content)
    doc.print_(printer)


def render_html_to_pdf(
    html_content: str,
    pdf_path: str,
    *,
    paper_size: str = "A4",
    orientation: str = "portrait",
) -> str:
    """Render invoice/report HTML directly to a B&W A4 or A5 PDF via QtPrintSupport."""
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


class PrintPreviewDialog(QDialog):
    """Commercial monochrome B&W RTL print preview dialog with A4/A5 switch, PDF export & Print."""

    def __init__(
        self,
        html_or_builder,
        *,
        title: str = "پیش‌نمایش چاپ",
        default_paper: str = "A4",
        parent=None,
    ):
        super().__init__(parent)
        self._html_or_builder = html_or_builder
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle(title)
        self.resize(940, 720)

        self.printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        configure_printer(self.printer, paper_size=default_paper, orientation="portrait")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        toolbar.addWidget(QLabel("اندازه کاغذ:"))
        self.cb_paper = QComboBox()
        self.cb_paper.addItem("A4 (۲۱۰ × ۲۹۷ میلی‌متر)", "A4")
        self.cb_paper.addItem("A5 (۱۴۸ × ۲۱۰ میلی‌متر)", "A5")
        if str(default_paper).upper() == "A5":
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

        btn_save_pdf = QPushButton("📄 ذخیره PDF")
        btn_save_pdf.clicked.connect(self._save_pdf)
        btn_print = QPushButton("🖨️ چاپ نهایی")
        btn_print.setObjectName("btnSuccess")
        btn_print.clicked.connect(self._print_document)
        btn_close = QPushButton("بستن")
        btn_close.clicked.connect(self.reject)

        toolbar.addWidget(btn_save_pdf)
        toolbar.addWidget(btn_print)
        toolbar.addWidget(btn_close)
        root.addLayout(toolbar)

        self.preview = QPrintPreviewWidget(self.printer, self)
        self.preview.paintRequested.connect(self._on_paint_requested)
        root.addWidget(self.preview, 1)

    def current_html(self) -> str:
        is_a5 = str(self.cb_paper.currentData() or "A4").upper() == "A5"
        if callable(self._html_or_builder):
            return self._html_or_builder(is_a5=is_a5)
        return str(self._html_or_builder)

    def _on_paint_requested(self, printer: QPrinter) -> None:
        render_html_to_printer(self.current_html(), printer)

    def _apply_page_settings(self) -> None:
        paper = str(self.cb_paper.currentData() or "A4")
        orient = str(self.cb_orientation.currentData() or "portrait")
        configure_printer(self.printer, paper_size=paper, orientation=orient)
        self.preview.updatePreview()

    def _save_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "ذخیره فایل PDF", "Daqiq_Print.pdf", "PDF Files (*.pdf)"
        )
        if not path:
            return
        try:
            paper = str(self.cb_paper.currentData() or "A4")
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
