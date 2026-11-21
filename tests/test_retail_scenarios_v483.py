"""Comprehensive Multi-Scenario End-to-End QA Suite for Daqiq v4.8.3.

Covers:
- Scenario 1: Dynamic taxonomy placeholder hygiene & permanent built-in field retention.
- Scenario 2: User lifecycle audit timestamps (created_at immutable, updated_at on edit only, last_login_at on login without touching others; UI Jalali display with fallback).
- Scenario 3: Brand logo assets, multi-resolution ICO, runtime icon resolution & PyInstaller packaging check.
- Scenario 4: Clean-slate schema v483 & full end-to-end retail store workflow regression.
"""
import os
import sys
import json
import pytest
from PIL import Image

from PySide6.QtWidgets import QApplication, QLineEdit, QComboBox
from PySide6.QtCore import Qt

from database import (
    DatabaseManager,
    APP_VERSION,
    SCHEMA_VERSION,
    EXPECTED_SCHEMA_COLUMNS,
    create_and_initialize_database,
    validate_schema_column_order,
)
from utils_and_widgets import DynamicSpecsWidget, SmartLineEdit, resource_path
from main import MainWindow, LoginDialog, format_iso_to_jalali


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["daqiq_test", "-platform", "offscreen"])
    return app


# =========================================================================
# SCENARIO 1: Dynamic Taxonomy Placeholder Hygiene
# =========================================================================
def test_scenario1_dynamic_taxonomy_placeholder_hygiene(qapp, tmp_path):
    """Verify dynamic taxonomy fields have no placeholders, while permanent fields keep theirs."""
    widget = DynamicSpecsWidget()
    widget.set_category("کالای دیجیتال")
    
    # Custom catalog with dynamic fields (both combo and text)
    custom_fields = [
        {"name": "پردازنده", "values": ["Intel Core i7", "AMD Ryzen 7"]},
        {"name": "ظرفیت حافظه", "values": []},
        {"name": "گارانتی شرکتی", "values": []},
    ]
    widget.apply_custom_catalog(subcategories=["لپ‌تاپ", "تبلت"], custom_fields=custom_fields)

    # 1. Dynamic ComboBox field should not have a hardcoded placeholder text
    combo_widget = widget.fields.get("پردازنده")
    assert combo_widget is not None
    assert isinstance(combo_widget, QComboBox)
    if combo_widget.lineEdit():
        assert not combo_widget.lineEdit().placeholderText(), "Dynamic combo should not have placeholder text"

    # 2. Dynamic SmartLineEdit field should have an empty placeholder
    line_widget = widget.fields.get("ظرفیت حافظه")
    assert line_widget is not None
    assert isinstance(line_widget, QLineEdit)
    assert not line_widget.placeholderText(), "Dynamic text input should not have placeholder text"

    # 3. Dynamic specs dict should be cleanly set and retrieved without placeholder interference
    widget.set_specs_dict({"پردازنده": "Intel Core i7", "ظرفیت حافظه": "16GB", "رنگ": "مشکی"})
    specs = widget.get_specs_dict()
    assert specs.get("پردازنده") == "Intel Core i7"
    assert specs.get("ظرفیت حافظه") == "16GB"
    assert specs.get("رنگ") == "مشکی"

    # 4. Permanent built-in fields in MainWindow retain their clean placeholders
    db_path = str(tmp_path / "Daqiq.db")
    db = create_and_initialize_database(db_path)
    win = MainWindow(db, active_employee=None)
    try:
        assert win.ed_prod_serial.placeholderText() != ""
        assert win.ed_prod_brand.placeholderText() != ""
        assert win.ed_prod_model.placeholderText() != ""
        assert win.ed_sale_customer.placeholderText() != ""
        assert win.ed_sale_phone.placeholderText() != ""
        assert win.ed_sup_name.placeholderText() != ""
    finally:
        win.close()
        db.close()


# =========================================================================
# SCENARIO 2: User Lifecycle Audit Timestamps
# =========================================================================
def test_scenario2_user_lifecycle_audit_timestamps(qapp, tmp_path):
    """Verify created_at, updated_at, last_login_at lifecycle and UI formatting."""
    db_path = str(tmp_path / "Daqiq.db")
    db = create_and_initialize_database(db_path)

    # 1. Create User
    emp_id = db.add_employee(
        name="علی رضایی",
        role="فروشنده",
        phone="09121112233",
        password="password123",
        permissions="دسترسی فروش",
    )
    assert emp_id > 0

    with db.get_connection() as conn:
        emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
        assert emp["created_at"] is not None and len(emp["created_at"]) > 0
        initial_created_at = emp["created_at"]
        assert emp["updated_at"] is None or emp["updated_at"] == ""
        assert emp["last_login_at"] is None or emp["last_login_at"] == ""

        # Test view 'users' alias
        user_row = conn.execute("SELECT * FROM users WHERE id=?", (emp_id,)).fetchone()
        assert user_row["name"] == "علی رضایی"
        assert user_row["created_at"] == initial_created_at

    # 2. Simulate User Login
    db.record_employee_login(emp_id, timestamp="2026-11-21 14:00:00")
    with db.get_connection() as conn:
        emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
        assert emp["created_at"] == initial_created_at, "created_at must be immutable on login"
        assert emp["updated_at"] is None or emp["updated_at"] == "", "updated_at must remain NULL on login"
        assert emp["last_login_at"] == "2026-11-21 14:00:00"

    # 3. Update User Profile
    with db.get_connection() as conn:
        conn.execute("UPDATE employees SET role='مدیر فروش' WHERE id=?", (emp_id,))
        conn.commit()

    with db.get_connection() as conn:
        emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
        assert emp["created_at"] == initial_created_at, "created_at must remain immutable on update"
        assert emp["updated_at"] is not None and len(emp["updated_at"]) > 0, "updated_at must be set on profile change"
        first_updated_at = emp["updated_at"]
        assert emp["last_login_at"] == "2026-11-21 14:00:00"

    # 4. Another Login does NOT overwrite updated_at
    db.record_employee_login(emp_id, timestamp="2026-11-21 15:30:00")
    with db.get_connection() as conn:
        emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
        assert emp["created_at"] == initial_created_at
        assert emp["updated_at"] == first_updated_at, "updated_at must NOT change when last_login_at is updated"
        assert emp["last_login_at"] == "2026-11-21 15:30:00"

    # 5. UI Formatting with Persian/Jalali & Em-dash fallback
    assert format_iso_to_jalali(None) == "—"
    assert format_iso_to_jalali("") == "—"
    formatted_ts = format_iso_to_jalali("2026-11-21 15:30:00")
    assert "1405" in formatted_ts
    assert "15:30" in formatted_ts

    # 6. UI Table Verification in MainWindow
    win = MainWindow(db, active_employee={"id": emp_id, "name": "علی رضایی", "role": "مدیر فروش"})
    try:
        tbl = win.tbl_employees
        # Assert column headers
        headers = [tbl.horizontalHeaderItem(i).text() for i in range(tbl.columnCount())]
        assert "تاریخ ایجاد" in headers
        assert "تاریخ ویرایش" in headers
        assert "آخرین ورود" in headers

        # Assert data populated
        win._refresh_employees_table()
        assert tbl.rowCount() >= 1
        created_col = headers.index("تاریخ ایجاد")
        updated_col = headers.index("تاریخ ویرایش")
        login_col = headers.index("آخرین ورود")

        assert tbl.item(0, created_col).text() != "—"
        assert tbl.item(0, updated_col).text() != "—"
        assert tbl.item(0, login_col).text() != "—"
    finally:
        win.close()
        db.close()


# =========================================================================
# SCENARIO 3: Brand Logo Assets, Multi-Resolution ICO & Packaging Checks
# =========================================================================
def test_scenario3_brand_logo_assets_and_packaging():
    """Verify SVG, 512x512 PNG, multi-resolution ICO, and PyInstaller config."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets_dir = os.path.join(base_dir, "assets")
    svg_path = os.path.join(assets_dir, "daqiq_logo.svg")
    png_path = os.path.join(assets_dir, "daqiq_logo.png")
    ico_path = os.path.join(assets_dir, "daqiq_logo.ico")

    # 1. Assets exist on disk
    assert os.path.isfile(svg_path), f"Missing SVG logo at {svg_path}"
    assert os.path.isfile(png_path), f"Missing PNG logo at {png_path}"
    assert os.path.isfile(ico_path), f"Missing ICO logo at {ico_path}"

    # 2. PNG dimensions
    with Image.open(png_path) as png_img:
        assert png_img.size == (512, 512)
        assert png_img.mode in ("RGBA", "RGB")

    # 3. Multi-resolution ICO frames
    with Image.open(ico_path) as ico_img:
        assert ico_img.format == "ICO"
        sizes = ico_img.info.get("sizes", set())
        expected_resolutions = {(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}
        assert expected_resolutions.issubset(sizes), f"ICO missing required sizes: {expected_resolutions - sizes}"

    # 4. Runtime resource_path resolution
    resolved = resource_path("assets/daqiq_logo.png")
    assert os.path.isabs(resolved)
    assert os.path.exists(resolved)

    # 5. CI Workflow check
    ci_path = os.path.join(base_dir, ".github", "workflows", "ci.yml")
    with open(ci_path, "r", encoding="utf-8") as f:
        ci_content = f.read()
    assert "--icon=assets/daqiq_logo.ico" in ci_content
    assert '--add-data "assets;assets"' in ci_content or "--add-data 'assets;assets'" in ci_content
    assert "4.8.3" in ci_content


# =========================================================================
# SCENARIO 4: Clean-Slate Schema v483 & End-to-End Store Workflow Sweep
# =========================================================================
def test_scenario4_schema_v483_and_store_workflow_sweep(qapp, tmp_path):
    """End-to-end retail store scenario on clean schema v483."""
    assert APP_VERSION == "4.8.3"
    assert SCHEMA_VERSION == 483

    db_path = str(tmp_path / "Daqiq.db")
    db = create_and_initialize_database(db_path)

    # Schema integrity check
    with db.get_connection() as conn:
        validate_schema_column_order(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 483
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        emp_cols = tuple(r["name"] for r in conn.execute("PRAGMA table_info(employees)").fetchall())
        assert emp_cols == EXPECTED_SCHEMA_COLUMNS["employees"]
        assert emp_cols[-1] == "last_login_at"

    # 1. Register User & Supplier
    emp_id = db.add_employee("کاربر تست", "مدیر سیستم", "09120000000", "admin", "دسترسی کامل")
    sup_id = db.add_supplier("تأمین‌کننده آلفا", "02177777777", "تهران")

    # 2. Register Product
    prod_code = db.add_product(
        code="P-TEST-100",
        name="ماوس بی‌سیم گیمینگ",
        category="قطعات جانبی",
        sub_category="ماوس",
        brand="Logitech",
        model="G305",
        specs_dict={"DPI": "12000", "نوع اتصال": "بی‌سیم"},
        description="ماوس گیمینگ",
        reorder_point=2,
    )
    with db.get_connection() as conn:
        prod_id = conn.execute("SELECT id FROM products WHERE code=?", (prod_code,)).fetchone()["id"]
    assert prod_id > 0

    # 3. Purchase Batch
    batch_code = db.add_batch(
        batch_code="C-BATCH-100",
        product_id=prod_id,
        supplier_id=sup_id,
        buyer_employee_id=emp_id,
        invoice_number="INV-BUY-01",
        purchase_date="1405/09/01",
        initial_qty=10,
        unit_purchase_price=1_500_000,
        extra_cost_total=0,
        suggested_sell_price=2_000_000,
        paid_amount=15_000_000,
        supplier_name="تأمین‌کننده آلفا",
    )
    with db.get_connection() as conn:
        batch_id = conn.execute("SELECT id FROM batches WHERE batch_code=?", (batch_code,)).fetchone()["id"]
    assert batch_id > 0

    # 4. Sell Item
    sale_inv = db.add_sale(
        invoice_number="INV-SALE-01",
        product_id=prod_id,
        batch_id=batch_id,
        seller_employee_id=emp_id,
        customer_name="خریدار نمونه",
        customer_phone="09129998877",
        qty=2,
        suggested_unit_price=2_000_000,
        actual_unit_price=2_000_000,
        paid_amount=4_000_000,
        sale_datetime="1405/09/01 10:00:00",
    )
    assert sale_inv == "INV-SALE-01"

    # Verify inventory deduction
    with db.get_connection() as conn:
        batch = conn.execute("SELECT remaining_qty, sold_qty FROM batches WHERE id=?", (batch_id,)).fetchone()
        assert batch["remaining_qty"] == 8
        assert batch["sold_qty"] == 2

    # 5. Service Record
    srv_catalog_id = db.save_service_catalog(
        service_id=None,
        code="S-SRV-100",
        service_type="سخت‌افزاری",
        name="تعمیر و سرویس ماوس",
        default_fee=300_000,
        default_side_cost=0,
        description="تعمیرات",
    )
    srv_rec_inv = db.add_service_record(
        invoice_number="INV-SRV-01",
        service_id=srv_catalog_id,
        seller_employee_id=emp_id,
        technician_employee_id=emp_id,
        customer_name="خریدار نمونه",
        service_fee=300_000,
        side_cost=0,
        paid_amount=300_000,
        service_datetime="1405/09/01 11:00:00",
        description="تعمیرات ماوس",
    )
    assert srv_rec_inv == "INV-SRV-01"

    # 6. Verify Financial & Audit Logs
    with db.get_connection() as conn:
        sales_cnt = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        assert sales_cnt == 1
        audit_cnt = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
        assert audit_cnt >= 2

    db.close()
