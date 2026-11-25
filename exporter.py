# exporter_and_tests.py
import os
import json
from datetime import datetime
import jdatetime
from database import DatabaseManager
from utils_and_widgets import add_jalali_months, normalize_digits, strip_bidi_controls


def _get_openpyxl():
    """Deferred lazy import of openpyxl to eliminate startup latency."""
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    return openpyxl, Font, Alignment, PatternFill, Border, Side


def get_next_excel_filename(directory: str, prefix: str = "R") -> str:
    """
    بند ۹: تولید نام فایل بر اساس تاریخ و ساعت شمسی
    مثال: R14050809_115300.xlsx
    """
    date_part = jdatetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = f"{prefix}{date_part}.xlsx"
    return os.path.join(directory, candidate)


def _clean_excel_value(value):
    """Remove directional control characters without changing the logical value."""
    if value is None:
        return ""
    if isinstance(value, str):
        return strip_bidi_controls(value).strip()
    return value


def _rtl_report_title(shop_name: str, title: str) -> str:
    """Return clean report text; Excel applies paragraph direction contextually."""
    clean_shop_name = _clean_excel_value(shop_name)
    clean_title = _clean_excel_value(title)
    return f"{clean_shop_name} — {clean_title}" if clean_shop_name else clean_title


def _format_catalog_specs(specs: dict, category: str, catalog_config: dict) -> str:
    """Use the catalog's @reference rule in inventory exports as in the UI."""
    definitions = catalog_config.get("attributes", {}).get(category or "", [])
    by_name = {
        str(item.get("name") or "").strip(): item
        for item in definitions
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    values = {}
    order = []
    deferred = []
    for raw_name, raw_value in (specs or {}).items():
        name = str(raw_name).strip()
        value = str(raw_value or "").strip()
        if not name or not value:
            continue
        definition = by_name.get(name, {})
        title = str(definition.get("display_name") or definition.get("label") or "").strip()
        if title.startswith("@"):
            reference = title[1:].strip()
            if reference:
                deferred.append((reference, value))
            continue
        if name not in values:
            order.append(name)
            values[name] = value
        else:
            values[name] = f"{values[name]} {value}".strip()
    for reference, value in deferred:
        if reference not in values:
            order.append(reference)
            values[reference] = value
        else:
            values[reference] = f"{values[reference]} {value}".strip()
    rendered = []
    for name in order:
        definition = by_name.get(name, {})
        title = str(definition.get("display_name") or definition.get("label") or name).strip()
        if not title or title.startswith("@"):
            title = name
        rendered.append(f"{title}: {_clean_excel_value(values[name])}")
    return " | ".join(rendered)




def _style_worksheet_professional(ws, title: str, headers: list, data_rows: list):
    """طراحی حرفه‌ای و چشم‌نواز جدول‌های اکسل با راست‌چین کامل، رنگ‌بندی متناوب و عرض خودکار"""
    openpyxl, Font, Alignment, PatternFill, Border, Side = _get_openpyxl()
    ws.views.sheetView[0].rightToLeft = True
    col_count = max(1, len(headers))

    # ردیف ۱: سربرگ اصلی
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=col_count)
    title_cell = ws.cell(1, 1, title)
    title_cell.font = Font(name="Tahoma", size=13, bold=True, color="FFFFFF")
    title_cell.fill = PatternFill("solid", fgColor="1E3A8A")
    title_cell.alignment = Alignment(horizontal="center", vertical="center", readingOrder=2)
    ws.row_dimensions[1].height = 32

    # ردیف ۲: عناوین ستون‌ها
    ws.append([_clean_excel_value(value) for value in headers])
    ws.row_dimensions[2].height = 25
    header_fill = PatternFill("solid", fgColor="1E293B")
    header_font = Font(name="Tahoma", size=10, bold=True, color="FFFFFF")
    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )

    for col_idx in range(1, col_count + 1):
        c = ws.cell(row=2, column=col_idx)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = thin_border

    # درج داده‌ها با رنگ‌بندی زبرا (متناوب)
    even_fill = PatternFill("solid", fgColor="F8FAFC")
    odd_fill = PatternFill("solid", fgColor="FFFFFF")
    body_font = Font(name="Tahoma", size=10, color="0F172A")

    for r_idx, r_vals in enumerate(data_rows, start=3):
        clean_values = [_clean_excel_value(value) for value in r_vals]
        ws.append(clean_values)
        ws.row_dimensions[r_idx].height = 22
        row_fill = even_fill if r_idx % 2 == 0 else odd_fill
        for c_idx in range(1, col_count + 1):
            cell = ws.cell(row=r_idx, column=c_idx)
            cell.font = body_font
            cell.fill = row_fill
            # Contextual reading direction prevents forced RTL on Latin-only cells.
            cell.alignment = Alignment(horizontal="center", vertical="center", readingOrder=0)
            cell.border = thin_border

    # تنظیم هوشمند عرض ستون‌ها
    for col_idx in range(1, col_count + 1):
        max_len = len(str(headers[col_idx - 1]))
        for r_idx in range(3, ws.max_row + 1):
            val_str = str(ws.cell(r_idx, col_idx).value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        col_letter = openpyxl.utils.get_column_letter(col_idx)
        ws.column_dimensions[col_letter].width = min(max(max_len + 5, 13), 42)


INVENTORY_EXPORT_AVAILABLE_COLUMNS = [
    ("code", "کد کالا"),
    ("batch_code", "کد محموله"),
    ("product_name", "نام کالا"),
    ("category", "دسته‌بندی"),
    ("subcategory", "زیرمجموعه"),
    ("brand_model", "برند و مدل"),
    ("description", "توضیحات کالا"),
    ("reorder_point", "حد سفارش مجدد"),
    ("specs", "مشخصات فنی کالا"),
    ("shipment_specs", "مشخصات فنی محموله"),
    ("supplier", "تأمین‌کننده"),
    ("buyer", "مسئول خرید"),
    ("purchase_date", "تاریخ خرید"),
    ("purchase_invoice", "شماره فاکتور خرید"),
    ("purchase_status", "وضعیت تسویه خرید"),
    ("purchase_paid_amount", "مبلغ پرداخت‌شده به تأمین‌کننده"),
    ("serial_numbers", "شماره سریال"),
    ("colors", "رنگ‌ها"),
    ("initial_qty", "تعداد اولیه"),
    ("sold_qty", "تعداد فروخته‌شده"),
    ("returned_qty", "تعداد مرجوعی"),
    ("stock", "موجودی فعلی"),
    ("shipment_notes", "یادداشت محموله"),
    ("warranty_history", "سوابق گارانتی فروش"),
    ("batch_created_at", "زمان ثبت محموله"),
    ("batch_updated_at", "آخرین ویرایش محموله"),
    ("suggested_price", "قیمت فروش (پیشنهادی)"),
    ("purchase_unit_price", "قیمت خرید واحد"),
    ("unit_cost_price", "بهای تمام‌شده واحد"),
    ("extra_cost_total", "هزینه‌های اضافی محموله"),
    ("upgrade_cost_unit", "هزینه ارتقای واحد"),
    ("profit_pct", "درصد سود"),
]


def export_safe_inventory_excel(
    db: DatabaseManager,
    file_path: str,
    shop_name: str = "",
    included_columns=None,
):
    """Export one row per stocked shipment with configurable product/shipment fields."""
    column_definitions = INVENTORY_EXPORT_AVAILABLE_COLUMNS
    labels = dict(column_definitions)
    if included_columns is None:
        selected_columns = [
            "code", "batch_code", "category", "subcategory", "brand_model", "specs",
        ]
    else:
        valid_keys = set(labels)
        selected_columns = list(dict.fromkeys(
            key for key in included_columns if key in valid_keys
        ))
    if not selected_columns:
        raise ValueError("Select at least one inventory export column.")

    headers = [labels[key] for key in selected_columns]
    catalog_config = db.get_product_catalog_config()
    with db.get_connection() as conn:
        rows = conn.execute("""
            WITH warranty_history AS (
                SELECT
                    batch_id,
                    GROUP_CONCAT(DISTINCT TRIM(
                        COALESCE(NULLIF(warranty_company, ''), 'بدون نام شرکت')
                        || CASE WHEN COALESCE(warranty_days, 0) > 0
                                THEN ' - ' || warranty_days || ' روز' ELSE '' END
                        || CASE WHEN COALESCE(warranty_start, '') <> ''
                                THEN ' | از ' || warranty_start ELSE '' END
                        || CASE WHEN COALESCE(warranty_end, '') <> ''
                                THEN ' | تا ' || warranty_end ELSE '' END
                    )) AS warranty_history
                FROM sales
                WHERE COALESCE(TRIM(warranty_company), '') <> ''
                   OR COALESCE(warranty_days, 0) > 0
                   OR COALESCE(warranty_start, '') <> ''
                   OR COALESCE(warranty_end, '') <> ''
                GROUP BY batch_id
            )
            SELECT
                p.code,
                p.name AS product_name,
                p.reorder_point,
                p.category,
                p.sub_category,
                p.brand,
                p.model,
                p.description,
                p.specs_json,
                b.batch_code,
                b.final_specs,
                b.initial_specs,
                b.supplier_name_snapshot,
                b.purchase_date,
                b.invoice_number,
                b.serial_numbers,
                b.colors_json,
                b.initial_qty,
                b.sold_qty,
                b.returned_qty,
                b.suggested_sell_price,
                b.remaining_qty,
                b.settlement_status AS purchase_status,
                b.paid_amount AS purchase_paid_amount,
                b.unit_purchase_price,
                b.unit_cost_price,
                b.extra_cost_total,
                b.upgrade_cost_unit,
                b.profit_pct,
                b.notes AS shipment_notes,
                b.created_at AS batch_created_at,
                b.updated_at AS batch_updated_at,
                COALESCE(wh.warranty_history, '') AS warranty_history,
                COALESCE(sup.name, b.supplier_name_snapshot, '') AS supplier_name,
                COALESCE(emp.name, '') AS buyer_name
            FROM batches b
            JOIN products p ON p.id = b.product_id
            LEFT JOIN suppliers sup ON sup.id = b.supplier_id
            LEFT JOIN employees emp ON emp.id = b.buyer_employee_id
            LEFT JOIN warranty_history wh ON wh.batch_id = b.id
            WHERE p.is_active = 1 AND b.remaining_qty > 0
            ORDER BY b.updated_at DESC, b.id DESC
        """).fetchall()

    data_rows = []
    for row in rows:
        try:
            product_specs = json.loads(row["specs_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            product_specs = {}
        if not isinstance(product_specs, dict):
            product_specs = {}
        product_specs_text = _format_catalog_specs(
            product_specs, row["category"], catalog_config
        )
        shipment_specs = str(row["final_specs"] or row["initial_specs"] or "").strip()
        try:
            shipment_spec_data = json.loads(shipment_specs) if shipment_specs.startswith("{") else None
        except (TypeError, ValueError, json.JSONDecodeError):
            shipment_spec_data = None
        if isinstance(shipment_spec_data, dict):
            shipment_specs = _format_catalog_specs(
                shipment_spec_data, row["category"], catalog_config
            )
        try:
            colors = json.loads(row["colors_json"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            colors = []
        if not isinstance(colors, list):
            colors = [str(colors)] if colors else []

        values = {
            "code": row["code"],
            "batch_code": row["batch_code"],
            "product_name": row["product_name"] or "-",
            "category": row["category"] or "سایر موارد",
            "reorder_point": int(row["reorder_point"] or 0),
            "subcategory": row["sub_category"] or "-",
            "brand_model": (
                f"{row['brand'] or ''} {row['model'] or ''}".strip()
                or row["product_name"]
            ),
            "description": row["description"] or "-",
            "specs": product_specs_text or "-",
            "shipment_specs": shipment_specs or "-",
            "supplier": row["supplier_name"] or "-",
            "buyer": row["buyer_name"] or "-",
            "purchase_date": row["purchase_date"] or "-",
            "purchase_invoice": row["invoice_number"] or "-",
            "serial_numbers": row["serial_numbers"] or "-",
            "colors": "، ".join(str(value) for value in colors) or "-",
            "initial_qty": int(row["initial_qty"] or 0),
            "sold_qty": int(row["sold_qty"] or 0),
            "returned_qty": int(row["returned_qty"] or 0),
            "stock": int(row["remaining_qty"] or 0),
            "purchase_status": row["purchase_status"] or "-",
            "purchase_paid_amount": int(row["purchase_paid_amount"] or 0),
            "purchase_unit_price": int(row["unit_purchase_price"] or 0),
            "unit_cost_price": int(row["unit_cost_price"] or 0),
            "extra_cost_total": int(row["extra_cost_total"] or 0),
            "upgrade_cost_unit": int(row["upgrade_cost_unit"] or 0),
            "profit_pct": float(row["profit_pct"] or 0),
            "shipment_notes": row["shipment_notes"] or "-",
            "warranty_history": (row["warranty_history"] or "").replace(",", "؛ ") or "-",
            "batch_created_at": row["batch_created_at"] or "-",
            "batch_updated_at": row["batch_updated_at"] or "-",
            "suggested_price": int(row["suggested_sell_price"] or 0),
        }
        data_rows.append([values[key] for key in selected_columns])

    openpyxl, Font, Alignment, PatternFill, Border, Side = _get_openpyxl()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "موجودی همکار"
    report_title = _rtl_report_title(shop_name, "خروجی موجودی همکار")
    _style_worksheet_professional(ws, report_title, headers, data_rows)
    wb.save(file_path)


def export_table_to_excel(
    title: str, headers: list, data_rows: list, file_path: str, summary_text: str = "",
    shop_name: str = "",
):
    """خروجی اکسل کامل و استایل‌دهی شده برای گزارش‌های جامع با پالت رنگی حرفه‌ای و هماهنگ"""
    openpyxl, Font, Alignment, PatternFill, Border, Side = _get_openpyxl()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "گزارش جامع"
    ws.views.sheetView[0].rightToLeft = True

    col_count = max(1, len(headers))
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=col_count)
    report_title = _rtl_report_title(shop_name, title)
    title_cell = ws.cell(1, 1, report_title)
    title_cell.font = Font(name="Tahoma", size=13, bold=True, color="FFFFFF")
    title_cell.fill = PatternFill("solid", fgColor="1E3A8A")
    title_cell.alignment = Alignment(horizontal="center", vertical="center", readingOrder=2)
    ws.row_dimensions[1].height = 32

    start_data_row = 3
    if summary_text:
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=col_count)
        sum_cell = ws.cell(2, 1, _clean_excel_value(summary_text))
        sum_cell.font = Font(name="Tahoma", size=10, bold=True, color="1E3A8A")
        sum_cell.fill = PatternFill("solid", fgColor="DBEAFE")
        sum_cell.alignment = Alignment(horizontal="center", vertical="center", readingOrder=2)
        ws.row_dimensions[2].height = 22
        start_data_row = 4

    header_row_idx = start_data_row - 1
    ws.append([_clean_excel_value(value) for value in headers])
    ws.row_dimensions[header_row_idx].height = 25

    header_fill = PatternFill("solid", fgColor="1E293B")
    header_font = Font(name="Tahoma", size=10, bold=True, color="FFFFFF")
    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )

    for c_idx in range(1, col_count + 1):
        cell = ws.cell(header_row_idx, c_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border

    even_fill = PatternFill("solid", fgColor="F8FAFC")
    odd_fill = PatternFill("solid", fgColor="FFFFFF")
    body_font = Font(name="Tahoma", size=10, color="0F172A")

    for r_idx, r_vals in enumerate(data_rows, start=start_data_row):
        clean_values = [_clean_excel_value(value) for value in r_vals]
        ws.append(clean_values)
        ws.row_dimensions[r_idx].height = 22
        row_fill = even_fill if (r_idx - start_data_row) % 2 == 1 else odd_fill
        for c_idx in range(1, col_count + 1):
            cell = ws.cell(row=r_idx, column=c_idx)
            cell.font = body_font
            cell.fill = row_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", readingOrder=0)
            cell.border = thin_border

    for col_idx in range(1, col_count + 1):
        max_len = len(str(headers[col_idx - 1]))
        for r_idx in range(start_data_row, ws.max_row + 1):
            val_str = str(ws.cell(r_idx, col_idx).value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        col_letter = openpyxl.utils.get_column_letter(col_idx)
        ws.column_dimensions[col_letter].width = min(max(max_len + 5, 13), 42)

    wb.save(file_path)
