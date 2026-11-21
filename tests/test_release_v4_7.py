import os
import sys
import json
import time
import openpyxl
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from database import (
    DatabaseManager,
    sqlite3,
    SCHEMA_VERSION,
    APP_VERSION,
    generate_timestamped_database_filename,
    get_default_taxonomy_path,
    EXPECTED_SCHEMA_COLUMNS,
)
from main import MainWindow, _is_valid_sqlite_database_file
from utils_and_widgets import normalize_catalog_label
from exporter import export_table_to_excel, export_safe_inventory_excel

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["daqiq_test", "-platform", "offscreen"])
    return app

def test_req0_schema_version_and_parity(tmp_path):
    """REQ-0: Clean-slate relational schema v483 and column parity."""
    assert SCHEMA_VERSION == 484
    assert APP_VERSION == "4.8.4"

    db_path = os.path.join(tmp_path, "schema_test.db")
    db = DatabaseManager(db_path)

    with db.get_connection() as conn:
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        assert ver == 484

        # Verify key tables exist with expected physical columns
        for table, expected_cols in EXPECTED_SCHEMA_COLUMNS.items():
            col_info = conn.execute(f"PRAGMA table_info({table})").fetchall()
            assert col_info, f"Table {table} missing"
            actual_cols = tuple(row["name"] for row in col_info)
            assert actual_cols == expected_cols, f"Mismatch in {table}: expected {expected_cols}, got {actual_cols}"

    db.close()

def test_req1_taxonomy_purge_and_deletion_invariant(tmp_path, monkeypatch):
    """REQ-1: Total purge of hardcoded taxonomy in source, seed from JSON, unrestricted deletion."""
    tax_path = get_default_taxonomy_path()
    assert os.path.exists(tax_path)

    # When seed JSON is absent, no categories/subcategories/specs/service_types are seeded
    monkeypatch.setattr("database.get_default_taxonomy_path", lambda: os.path.join(tmp_path, "nonexistent.json"))
    db_empty_path = os.path.join(tmp_path, "empty_seed.db")
    db_empty = DatabaseManager(db_empty_path)
    cfg = db_empty.get_product_catalog_config()
    assert cfg.get("categories") == []
    assert cfg.get("service_types") == []

    # Can manually add and delete down to 0
    cfg["service_types"] = ["سرویس موقت"]
    db_empty.save_product_catalog_config(cfg)
    assert len(db_empty.get_product_catalog_config()["service_types"]) == 1

    cfg["service_types"] = []
    db_empty.save_product_catalog_config(cfg)
    assert len(db_empty.get_product_catalog_config()["service_types"]) == 0
    db_empty.close()

def test_req2_collision_safe_timestamped_naming(tmp_path):
    """REQ-2: Collision-safe timestamped database filenames."""
    name1 = generate_timestamped_database_filename(str(tmp_path), prefix="Daqiq", extension=".db")
    assert "Daqiq_" in name1
    assert name1.endswith(".db")
    assert not os.path.exists(name1)

    # Create file to trigger collision handling
    with open(name1, "w") as f:
        f.write("test")

    name2 = generate_timestamped_database_filename(str(tmp_path), prefix="Daqiq", extension=".db")
    assert name1 != name2
    assert not os.path.exists(name2)

def test_req3_excel_styling_parity(tmp_path):
    """REQ-3: Exact styling parity between comprehensive reports and colleague inventory."""
    db_path = os.path.join(tmp_path, "excel_db.db")
    db = DatabaseManager(db_path)

    f_rep = os.path.join(tmp_path, "rep.xlsx")
    export_table_to_excel("گزارش تست", ["کد", "نام", "قیمت"], [["1", "کالا", "1000"]], f_rep, shop_name="فروشگاه")

    f_inv = os.path.join(tmp_path, "inv.xlsx")
    export_safe_inventory_excel(db, f_inv, shop_name="فروشگاه")

    wb1 = openpyxl.load_workbook(f_rep)
    wb2 = openpyxl.load_workbook(f_inv)

    ws1 = wb1.active
    ws2 = wb2.active

    # Title parity
    assert ws1.row_dimensions[1].height == 32
    assert ws2.row_dimensions[1].height == 32
    assert ws1.cell(1, 1).fill.fgColor.value in ("1E3A8A", "001E3A8A")
    assert ws2.cell(1, 1).fill.fgColor.value in ("1E3A8A", "001E3A8A")

    # Header parity
    assert ws1.row_dimensions[2].height == 25
    assert ws2.row_dimensions[2].height == 25
    assert ws1.cell(2, 1).fill.fgColor.value in ("1E293B", "001E293B")
    assert ws2.cell(2, 1).fill.fgColor.value in ("1E293B", "001E293B")

    # Data row height
    assert ws1.row_dimensions[3].height == 22

    wb1.close()
    wb2.close()
    db.close()

def test_req4_ui_compaction_heights(qapp, tmp_path):
    """REQ-4: 1-item height compaction on 4 list viewports."""
    db_path = os.path.join(tmp_path, "compaction.db")
    db = DatabaseManager(db_path)
    win = MainWindow(db=db)

    assert win.lst_cfg_subcategories.minimumHeight() == 174
    assert win.lst_cfg_subcategories.maximumHeight() == 234

    assert win.lst_cfg_colors.minimumHeight() == 174
    assert win.lst_cfg_colors.maximumHeight() == 234

    assert win.lst_cfg_attributes.minimumHeight() == 192
    assert win.lst_cfg_attributes.maximumHeight() == 252

    assert win.attr_values_widget.scroll_area.minimumHeight() == 160
    assert win.attr_values_widget.scroll_area.maximumHeight() == 220

    win.close()
    db.close()

def test_req5_encryption_reconnect_fast_save_zero_leakage(qapp, tmp_path, monkeypatch):
    """REQ-5: Encryption lifecycle, reconnect fix, fast settings save, zero token leakage."""
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    db_path = os.path.join(tmp_path, "enc_vault.db")
    db = DatabaseManager(db_path)

    # 1. Set password '12345'
    db.set_database_password("12345")
    assert db.is_password_protected()
    db.close()

    # 2. Reconnect integrity check
    assert _is_valid_sqlite_database_file(db_path) == True

    # 3. Interoperability with standard SQLCipher '12345'
    c = sqlite3.connect(db_path)
    try:
        c.execute("PRAGMA key = '12345'")
        assert c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        c.close()

    # 4. Zero plaintext token leakage
    with open(db.cfg.get("config_file", "app_config.json"), "r", encoding="utf-8") as f:
        cfg_disk = json.load(f)
    assert "local_db_unlock_tokens" not in cfg_disk
    for k, v in cfg_disk.items():
        assert "12345" not in str(v)

    # 5. Fast save & UI check
    db_open = DatabaseManager(db_path, password="12345")
    win = MainWindow(db=db_open)
    assert win.lbl_db_pwd_status.wordWrap() == False

    t0 = time.perf_counter()
    win._save_general_settings()
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0, f"Settings save exceeded 5.0s: {elapsed:.2f}s"

    win.close()
    db_open.close()

def test_req6_taxonomy_hardware_and_sayer_mowared_ux(qapp, tmp_path):
    """REQ-6: Hardware domain coverage, 'سایر موارد' strictly last, editable cb_sub and single spec."""
    tax_path = get_default_taxonomy_path()
    with open(tax_path, "r", encoding="utf-8") as f:
        tax = json.load(f)

    # Categories check
    assert tax["categories"][-1] == "سایر موارد"
    for cat, subs in tax["subcategories"].items():
        assert subs[-1] == "سایر موارد"

    # Services check
    assert len(tax["service_types"]) >= 2
    assert any("سخت‌افزاری" in s for s in tax["service_types"])

    # RAM and CPU checks
    pc_attrs = {a["name"]: a for a in tax["attributes"]["قطعات اصلی کامپیوتر"]}
    ram_caps = next(a["values"] for a in tax["attributes"]["قطعات اصلی کامپیوتر"] if a["subcategory"] == "رم کامپیوتر (Desktop RAM)" and a["name"] == "ظرفیت")
    for cap in ["1GB", "6GB", "12GB", "128GB"]:
        assert cap in ram_caps

    cpus = next(a["values"] for a in tax["attributes"]["قطعات اصلی کامپیوتر"] if a["subcategory"] == "پردازنده (CPU)" and a["name"] == "سری پردازنده")
    for cpu in ["Celeron", "Pentium", "Core i7", "Xeon", "Threadripper"]:
        assert any(cpu in c for c in cpus)

    # UX Check in Window
    db_path = os.path.join(tmp_path, "ux_tax.db")
    db = DatabaseManager(db_path)
    win = MainWindow(db=db)

    # Select 'سایر موارد' category
    sayer_idx = -1
    for i in range(win.cb_prod_cat.count()):
        if normalize_catalog_label(win.cb_prod_cat.itemText(i)) == normalize_catalog_label("سایر موارد"):
            sayer_idx = i
            break
    assert sayer_idx >= 0
    win.cb_prod_cat.setCurrentIndex(sayer_idx)

    # cb_sub is editable
    assert win.specs_widget.cb_sub.isEditable() == True
    win.specs_widget.set_sub_category("تجهیزات خاص")
    assert win.specs_widget.get_sub_category() == "تجهیزات خاص"

    # Only 'مشخصات' shown
    fields = list(win.specs_widget.fields.keys())
    assert len(fields) == 1
    assert normalize_catalog_label(fields[0]) == normalize_catalog_label("مشخصات")

    win.close()
    db.close()
