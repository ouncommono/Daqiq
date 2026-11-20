import os
import openpyxl
import pytest
from PySide6.QtWidgets import QApplication

from database import DatabaseManager
from main import MainWindow
from exporter import export_table_to_excel, export_safe_inventory_excel

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["daqiq_test", "-platform", "offscreen"])
    return app

def test_phase5_excel_styling_parity(tmp_path, monkeypatch):
    db_file = os.path.join(tmp_path, "excel_test.db")
    db = DatabaseManager(db_file)

    # 1. Export via export_table_to_excel (خروجی اکسل از این گزارش)
    f_report = os.path.join(tmp_path, "report.xlsx")
    headers = ["کد", "نام کالا", "قیمت", "موجودی"]
    rows = [
        ["101", "لپ‌تاپ دل", "35000000", "5"],
        ["102", "ماوس بی‌سیم", "450000", "20"],
    ]
    export_table_to_excel("گزارش آزمایشی", headers, rows, f_report, shop_name="فروشگاه دقیق")

    # 2. Export via export_safe_inventory_excel (خروجی موجود همکار)
    f_inventory = os.path.join(tmp_path, "inventory.xlsx")
    export_safe_inventory_excel(db, f_inventory, shop_name="فروشگاه دقیق")

    wb_rep = openpyxl.load_workbook(f_report)
    ws_rep = wb_rep.active

    wb_inv = openpyxl.load_workbook(f_inventory)
    ws_inv = wb_inv.active

    # Check Title row parity
    assert ws_rep.row_dimensions[1].height == 32
    assert ws_inv.row_dimensions[1].height == 32
    assert ws_rep.cell(1, 1).fill.fgColor.rgb == "001E3A8A" or ws_rep.cell(1, 1).fill.fgColor.value == "1E3A8A"
    assert ws_inv.cell(1, 1).fill.fgColor.rgb == "001E3A8A" or ws_inv.cell(1, 1).fill.fgColor.value == "1E3A8A"

    # Check Header row parity
    assert ws_rep.row_dimensions[2].height == 25
    assert ws_inv.row_dimensions[2].height == 25
    assert ws_rep.cell(2, 1).fill.fgColor.value == "1E293B" or ws_rep.cell(2, 1).fill.fgColor.rgb == "001E293B"
    assert ws_inv.cell(2, 1).fill.fgColor.value == "1E293B" or ws_inv.cell(2, 1).fill.fgColor.rgb == "001E293B"
    assert ws_rep.cell(2, 1).font.color.value in ("FFFFFF", "00FFFFFF")
    assert ws_inv.cell(2, 1).font.color.value in ("FFFFFF", "00FFFFFF")

    # Check Data rows parity
    assert ws_rep.row_dimensions[3].height == 22
    assert ws_rep.cell(3, 1).font.color.value in ("0F172A", "000F172A")
    assert ws_rep.cell(3, 1).border.left.style == "thin"
    assert ws_rep.cell(3, 1).border.left.color.value in ("CBD5E1", "00CBD5E1")

    wb_rep.close()
    wb_inv.close()
    db.close()

def test_phase5_ui_compaction_heights(qapp, tmp_path):
    db_file = os.path.join(tmp_path, "compaction_test.db")
    db = DatabaseManager(db_file)
    win = MainWindow(db=db)

    # REQ-4 exact heights check
    # 1. lst_cfg_subcategories: min 174, max 234
    assert win.lst_cfg_subcategories.minimumHeight() == 174
    assert win.lst_cfg_subcategories.maximumHeight() == 234

    # 2. lst_cfg_colors: min 174, max 234
    assert win.lst_cfg_colors.minimumHeight() == 174
    assert win.lst_cfg_colors.maximumHeight() == 234

    # 3. lst_cfg_attributes: min 192, max 252
    assert win.lst_cfg_attributes.minimumHeight() == 192
    assert win.lst_cfg_attributes.maximumHeight() == 252

    # 4. DynamicAttributeValuesWidget.scroll_area: min 160, max 220 (compacted in v4.8.0)
    assert win.attr_values_widget.scroll_area.minimumHeight() == 160
    assert win.attr_values_widget.scroll_area.maximumHeight() == 220

    win.close()
    db.close()
