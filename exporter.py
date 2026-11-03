# exporter_and_tests.py
import os
import json
from datetime import datetime
import jdatetime
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from database import DatabaseManager
from utils_and_widgets import add_jalali_months, normalize_digits, strip_bidi_controls


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
        title = str(by_name.get(name, {}).get("label") or "").strip()
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
        title = str(by_name.get(name, {}).get("label") or name).strip()
        if not title or title.startswith("@"):
            title = name
        rendered.append(f"{title}: {_clean_excel_value(values[name])}")
    return " | ".join(rendered)




def _style_worksheet_professional(ws, title: str, headers: list, data_rows: list):
    """طراحی حرفه‌ای و چشم‌نواز جدول‌های اکسل با راست‌چین کامل، رنگ‌بندی متناوب و عرض خودکار"""
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


PEER_INVENTORY_EXPORT_FIELDS = [
    ("code", "کد کالا"),
    ("category", "دسته‌بندی"),
    ("subcategory", "زیرمجموعه"),
    ("brand_model", "برند و مدل"),
    ("specs", "مشخصات فنی"),
    ("quantity", "موجودی فعلی"),
    ("suggested_price", "قیمت فروش (پیشنهادی)"),
    ("description", "توضیحات"),
]

_DEFAULT_PEER_EXPORT_FIELDS = (
    "code", "category", "subcategory", "brand_model", "specs", "quantity"
)


def export_safe_inventory_excel(db: DatabaseManager, file_path: str, shop_name: str = ""):
    """Create a configurable partner-facing stock list without purchase costs or profit data."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "موجودی همکار"

    raw_fields = db.get_setting("peer_inventory_export_fields", "")
    try:
        configured_fields = json.loads(raw_fields) if raw_fields else list(_DEFAULT_PEER_EXPORT_FIELDS)
    except (TypeError, ValueError, json.JSONDecodeError):
        configured_fields = list(_DEFAULT_PEER_EXPORT_FIELDS)
    if not isinstance(configured_fields, list):
        configured_fields = list(_DEFAULT_PEER_EXPORT_FIELDS)

    available = {key: title for key, title in PEER_INVENTORY_EXPORT_FIELDS}
    selected_keys = []
    for key in configured_fields:
        key = str(key)
        if key in available and key not in selected_keys:
            selected_keys.append(key)
    if not selected_keys:
        selected_keys = ["code"]

    headers = [available[key] for key in selected_keys]
    catalog_config = db.get_product_catalog_config()
    with db.get_connection() as conn:
        rows = conn.execute("""
            SELECT p.code, p.name, p.category, p.sub_category, p.brand, p.model,
                   p.specs_json, p.description,
                   COALESCE(SUM(b.remaining_qty), 0) AS total_rem,
                   MAX(b.updated_at) AS last_batch_activity,
                   COALESCE((
                       SELECT b2.suggested_sell_price
                       FROM batches b2
                       WHERE b2.product_id=p.id AND b2.remaining_qty>0
                       ORDER BY b2.updated_at DESC, b2.id DESC
                       LIMIT 1
                   ), 0) AS suggested_price
            FROM products p
            LEFT JOIN batches b ON p.id = b.product_id
            WHERE p.is_active = 1
            GROUP BY p.id
            HAVING total_rem > 0
            ORDER BY COALESCE(last_batch_activity, p.updated_at) DESC,
                     p.updated_at DESC, p.id DESC
        """).fetchall()

    data_rows = []
    for r in rows:
        category = r["category"] or "سایر موارد"
        brand_model = f"{r['brand'] or ''} {r['model'] or ''}".strip() or r["name"]
        try:
            specs_dict = json.loads(r["specs_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            specs_dict = {}
        if not isinstance(specs_dict, dict):
            specs_dict = {}
        specs_text = _format_catalog_specs(specs_dict, category, catalog_config)
        description = str(r["description"] or "").strip()
        if description:
            specs_text = f"{specs_text} - {description}".strip(" -") if specs_text else description

        values = {
            "code": r["code"],
            "category": category,
            "subcategory": r["sub_category"] or "-",
            "brand_model": brand_model,
            "specs": specs_text or "-",
            "quantity": int(r["total_rem"]),
            "suggested_price": int(r["suggested_price"] or 0),
            "description": description or "-",
        }
        data_rows.append([values[key] for key in selected_keys])

    report_title = _rtl_report_title(shop_name, "موجودی همکار")
    _style_worksheet_professional(ws, report_title, headers, data_rows)
    wb.save(file_path)

def export_table_to_excel(
    title: str, headers: list, data_rows: list, file_path: str, summary_text: str = "",
    shop_name: str = "",
):
    """مورد ۱: خروجی اکسل کامل و استایل‌دهی شده برای گزارش‌های جامع"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "گزارش جامع"
    ws.views.sheetView[0].rightToLeft = True

    col_count = max(1, len(headers))
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=col_count)
    report_title = _rtl_report_title(shop_name, title)
    ws.cell(1, 1, report_title).font = Font(name="Tahoma", size=13, bold=True, color="FFFFFF")
    ws.cell(1, 1).fill = PatternFill("solid", fgColor="1E3A8A")
    ws.cell(1, 1).alignment = Alignment(horizontal="center", vertical="center", readingOrder=2)
    ws.row_dimensions[1].height = 28

    start_data_row = 3
    if summary_text:
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=col_count)
        ws.cell(2, 1, _clean_excel_value(summary_text)).font = Font(name="Tahoma", size=10, bold=True, color="1E3A8A")
        ws.cell(2, 1).fill = PatternFill("solid", fgColor="DBEAFE")
        ws.cell(2, 1).alignment = Alignment(horizontal="center", vertical="center", readingOrder=2)
        ws.row_dimensions[2].height = 22
        start_data_row = 4

    ws.append([_clean_excel_value(value) for value in headers])
    header_row_idx = start_data_row - 1
    for c_idx in range(1, col_count + 1):
        cell = ws.cell(header_row_idx, c_idx)
        cell.font = Font(name="Tahoma", size=10, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="334155")
        cell.alignment = Alignment(horizontal="center", vertical="center")

    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )

    for r_vals in data_rows:
        ws.append([_clean_excel_value(value) for value in r_vals])

    signed_columns = {
        index for index, header in enumerate(headers, start=1)
        if "تخفیف" in str(header) or "تشدید" in str(header)
    }
    for row in ws.iter_rows(min_row=start_data_row, max_row=ws.max_row, max_col=col_count):
        for cell in row:
            cell.font = Font(name="Tahoma", size=10)
            if cell.column in signed_columns and str(cell.value or "").startswith(("+", "-")):
                # Keep the sign to the left of the digits in mixed RTL worksheets.
                cell.alignment = Alignment(horizontal="left", vertical="center", readingOrder=1)
            else:
                cell.alignment = Alignment(horizontal="center", vertical="center", readingOrder=0)
            cell.border = thin_border

    for col in range(1, col_count + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 18

    wb.save(file_path)
