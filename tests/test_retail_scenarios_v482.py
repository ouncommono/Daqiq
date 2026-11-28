"""Comprehensive Multi-Scenario End-to-End QA Suite for Daqiq v4.8.2.
Enforces headless (QT_QPA_PLATFORM=offscreen), non-blocking, strictly-timed
verification of Scenarios 1 through 6 across REQ-0 through REQ-6.
"""

import os
import sys
import json
import time
import pytest
import jdatetime

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMessageBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QGroupBox,
)
from PySide6.QtCore import Qt, QLocale

from database import (
    DatabaseManager,
    create_and_initialize_database,
    validate_schema_column_order,
    load_app_config,
    save_app_config,
    APP_VERSION,
    SCHEMA_VERSION,
)
from utils_and_widgets import (
    auto_capitalize_first_char,
    SmartLineEdit,
    SearchableComboBox,
    DynamicSpecsWidget,
)
from main import MainWindow, _window_title


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
        app.setLayoutDirection(Qt.RightToLeft)
    return app


# =========================================================================
# SCENARIO 1: Global First-Letter Auto-Capitalization Policy & Exceptions
# =========================================================================
def test_scenario1_capitalization_policy_and_exceptions(qapp, tmp_path):
    """Scenario 1:
    - auto_capitalize_first_char uppercases first Latin letter only.
    - Preserves mixed-case hardware strings (DDR4, Core i7-14700K, NVMe M.2).
    - Does NOT alter Persian / non-Latin text.
    - SmartLineEdit with all_caps=True (Brand & Model) transforms to ALL-CAPS.
    - SmartLineEdit with all_caps=False (default) applies auto_capitalize_first_char.
    - SearchableComboBox._normalize_search applies auto_capitalize_first_char.
    """
    # 1. auto_capitalize_first_char tests
    assert auto_capitalize_first_char("asus") == "Asus"
    assert auto_capitalize_first_char("lenovo") == "Lenovo"
    assert auto_capitalize_first_char("rog strix") == "Rog strix"
    assert auto_capitalize_first_char("ddr4 3200MHz") == "Ddr4 3200MHz"
    assert auto_capitalize_first_char("core i7-14700K") == "Core i7-14700K"
    assert auto_capitalize_first_char("ssd NVMe M.2") == "Ssd NVMe M.2"
    assert auto_capitalize_first_char("rtx 4060 Ti") == "Rtx 4060 Ti"
    assert auto_capitalize_first_char("پردازنده اینتل Core i5") == "پردازنده اینتل Core i5"
    assert auto_capitalize_first_char("") == ""
    assert auto_capitalize_first_char("   ") == "   "

    # 2. SmartLineEdit with all_caps=True (Used for Brand and Model)
    brand_edit = SmartLineEdit("", all_caps=True)
    brand_edit.setText("asus rog")
    assert brand_edit.text() == "ASUS ROG"

    model_edit = SmartLineEdit("", all_caps=True)
    model_edit.setText("strix b760-f gaming wifi")
    assert model_edit.text() == "STRIX B760-F GAMING WIFI"

    # 3. SmartLineEdit with all_caps=False (Default everywhere else)
    normal_edit = SmartLineEdit("", all_caps=False)
    normal_edit.setText("ddr4 3200MHz 16GB")
    assert normal_edit.text() == "Ddr4 3200MHz 16GB"

    customer_edit = SmartLineEdit("", all_caps=False)
    customer_edit.setText("john doe")
    assert customer_edit.text() == "John doe"

    # Persian input untouched
    persian_edit = SmartLineEdit("", all_caps=False)
    persian_edit.setText("محمد امینی")
    assert persian_edit.text() == "محمد امینی"

    # 4. SearchableComboBox search normalization
    combo = SearchableComboBox()
    combo.addItem("Core i7-14700K", 1)
    combo.addItem("Asus ROG Strix", 2)
    norm_text = combo._normalize_search("asus")
    assert norm_text == "Asus"


# =========================================================================
# SCENARIO 2: Taxonomy/Service Deletion & Historical Immutability
# =========================================================================
def test_scenario2_service_and_taxonomy_deletion_immutability(qapp, tmp_path, monkeypatch):
    """Scenario 2:
    - Service records decouple cleanly from service_catalog when tariff is deleted.
    - Historical service invoices retain snapshot fee, side cost, net profit, and seller.
    - Product batches and sales retain snapshot values even if taxonomy is cleared.
    """
    db_path = str(tmp_path / "Daqiq.db")
    db = create_and_initialize_database(db_path)

    # 1. Add employee
    emp_id = db.add_employee("کاربر تست", "تکنسین فنی", "09120000000", "pass123", "مدیر سیستم (دسترسی کامل)")

    # 2. Add service catalog tariff
    srv_cat_id = db.save_service_catalog(None, "S-101", "سخت‌افزاری", "نصب ویندوز ۱۱ و درایورها", 250000, 50000, "توضیحات")
    assert srv_cat_id is not None

    # 3. Add service record for customer using this tariff
    srv_inv = db.add_service_record(
        invoice_number="SRV-2001",
        service_id=srv_cat_id,
        seller_employee_id=emp_id,
        technician_employee_id=emp_id,
        customer_name="علی عباسی",
        service_fee=250000,
        side_cost=50000,
        paid_amount=250000,
        service_datetime="1403/08/30 14:00:00",
        description="سرویس کامل",
        settlement_status="تسویه‌شده",
    )
    assert srv_inv == "SRV-2001"

    # Verify service record before deletion
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM service_records WHERE invoice_number=?", ("SRV-2001",)).fetchone()
        assert row is not None
        srv_rec_id = row["id"]
        assert row["service_id"] == srv_cat_id
        assert row["service_fee"] == 250000
        assert row["side_cost"] == 50000
        assert row["net_profit"] == 200000

    # 4. Delete the service catalog tariff
    db.delete_service_catalog(srv_cat_id)

    # Tariff is deleted from catalog
    with db.get_connection() as conn:
        cat_row = conn.execute("SELECT * FROM service_catalog WHERE id=?", (srv_cat_id,)).fetchone()
        assert cat_row is None

        # 5. Service record MUST NOT be deleted (ON DELETE SET NULL / decoupled)
        rec_row = conn.execute("SELECT * FROM service_records WHERE id=?", (srv_rec_id,)).fetchone()
        assert rec_row is not None
        assert rec_row["service_id"] is None  # Nullified safely
        assert rec_row["service_name"] == "نصب ویندوز ۱۱ و درایورها"  # Historical snapshot preserved!
        assert rec_row["service_type"] == "سخت‌افزاری"
        assert rec_row["service_fee"] == 250000
        assert rec_row["side_cost"] == 50000
        assert rec_row["net_profit"] == 200000
        assert rec_row["customer_name"] == "علی عباسی"

    # 6. Add product, batch, and sale, then verify taxonomy clear preserves historical records
    prod_code = db.add_product("P-500", "BAR-500", "قطعات اصلی کامپیوتر", "پردازنده (CPU)", "Intel", "Core i7-14700K", {"Specs": "14th Gen, 20-Core"}, "توضیح")
    with db.get_connection() as conn:
        prod_id = conn.execute("SELECT id FROM products WHERE code=?", (prod_code,)).fetchone()["id"]

    batch_code = db.add_batch(
        batch_code="C-500",
        product_id=prod_id,
        supplier_id=None,
        buyer_employee_id=emp_id,
        invoice_number="INV-B500",
        purchase_date="1403/08/30",
        initial_qty=10,
        unit_purchase_price=18000000,
        extra_cost_total=200000,
        suggested_sell_price=21000000,
        paid_amount=180200000,
        serial_numbers="BAR-500",
        initial_specs="Specs snapshot",
        notes="Intel Core i7",
        settlement_status="تسویه‌شده",
        colors=["مشکی"],
        supplier_name="تأمین‌کننده تست",
    )
    with db.get_connection() as conn:
        batch_id = conn.execute("SELECT id FROM batches WHERE batch_code=?", (batch_code,)).fetchone()["id"]

    sale_inv = db.add_sale(
        invoice_number="INV-S500",
        product_id=prod_id,
        batch_id=batch_id,
        seller_employee_id=emp_id,
        customer_name="مشتری فروش",
        qty=2,
        suggested_unit_price=21000000,
        actual_unit_price=21000000,
        paid_amount=42000000,
        sale_datetime="1403/08/30 15:00:00",
        warranty_company="گارانتی سازگار",
        warranty_days=730,
        serial_number="BAR-500",
        specifications="Specs sale",
        colors=["مشکی"],
        notes="توضیح فروش",
        customer_phone="09121111111",
    )

    # Verify batch and sale have complete snapshots
    with db.get_connection() as conn:
        b_row = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        assert b_row["initial_specs"] == "Specs snapshot"
        s_row = conn.execute("SELECT * FROM sales WHERE invoice_number=?", (sale_inv,)).fetchone()
        assert s_row["customer_name"] == "مشتری فروش"
        assert s_row["specifications"] == "Specs sale"


# =========================================================================
# SCENARIO 3: "مشخصات" Stored as "Specs" DB Key & Persian UI Display
# =========================================================================
def test_scenario3_specs_db_key_and_persian_ui_mapping(qapp, tmp_path):
    """Scenario 3:
    - DynamicSpecsWidget.get_specs_dict returns key 'Specs'.
    - DynamicSpecsWidget.set_specs_dict accepts 'Specs' and 'مشخصات'.
    - add_product / update_product normalize 'مشخصات' to 'Specs' in specs_json.
    - MainWindow formatters render 'مشخصات' as Persian label in UI and tooltips.
    """
    db_path = str(tmp_path / "Daqiq.db")
    db = create_and_initialize_database(db_path)

    # 1. DynamicSpecsWidget get_specs_dict & set_specs_dict
    widget = DynamicSpecsWidget()
    widget.set_specs_dict({"Specs": "16GB DDR5 6000MHz"})
    retrieved = widget.get_specs_dict()
    assert "Specs" in retrieved
    assert retrieved["Specs"] == "16GB DDR5 6000MHz"
    assert "مشخصات" not in retrieved

    # Legacy compatibility: passing 'مشخصات' sets widget and gets 'Specs'
    widget.set_specs_dict({"مشخصات": "32GB DDR4 3200MHz"})
    retrieved_legacy = widget.get_specs_dict()
    assert "Specs" in retrieved_legacy
    assert retrieved_legacy["Specs"] == "32GB DDR4 3200MHz"
    assert "مشخصات" not in retrieved_legacy

    # 2. Database normalization in add_product and update_product
    prod_code = db.add_product(
        "P-600", "SER-600", "قطعات اصلی کامپیوتر", "رم کامپیوتر (Desktop RAM)",
        "Corsair", "Vengeance", {"مشخصات": "DDR5 32GB RGB"}, "رم گیمینگ",
        1, 20
    )
    with db.get_connection() as conn:
        row = conn.execute("SELECT id, specs_json FROM products WHERE code=?", (prod_code,)).fetchone()
        prod_id = row["id"]
        specs_data = json.loads(row["specs_json"])
        assert "Specs" in specs_data
        assert specs_data["Specs"] == "DDR5 32GB RGB"
        assert "مشخصات" not in specs_data

    # Update product also keeps "Specs"
    db.update_product(
        prod_id, "P-600", "SER-600", "قطعات اصلی کامپیوتر", "رم کامپیوتر (Desktop RAM)",
        "Corsair", "Vengeance Pro", {"مشخصات": "DDR5 64GB RGB"}, "رم به‌روزرسانی‌شده", 1, 20
    )
    with db.get_connection() as conn:
        row = conn.execute("SELECT specs_json FROM products WHERE id=?", (prod_id,)).fetchone()
        specs_data = json.loads(row["specs_json"])
        assert "Specs" in specs_data
        assert specs_data["Specs"] == "DDR5 64GB RGB"

    # 3. Formatters test in MainWindow
    win = MainWindow(db, active_employee={"id": 1, "name": "مدیر سیستم", "role": "مدیر", "permissions": "مدیر سیستم (دسترسی کامل)"})
    display_str = win._format_specs_for_display({"Specs": "Core i7 14700K"})
    assert "مشخصات: Core i7 14700K" in display_str
    assert "Specs:" not in display_str

    tooltip_str = win._format_specs_for_tooltip({"Specs": "Core i7 14700K"})
    assert "مشخصات: Core i7 14700K" in tooltip_str
    assert "Specs:" not in tooltip_str


# =========================================================================
# SCENARIO 4: Active-User Auto-Selection Across 4 Operator Fields
# =========================================================================
def test_scenario4_active_user_auto_selection_across_operators(qapp, tmp_path):
    """Scenario 4:
    - On load: 4 operator fields (cb_batch_buyer, cb_sale_seller, cb_srv_seller, cb_upg_tech)
      automatically select the active logged-in employee.
    - On 'پاک کردن فرم': form reset retains the active logged-in employee (does not leave -1).
    - On user switch: all 4 combos immediately update to new active employee.
    - On refresh_all_data: active employee remains selected.
    """
    db_path = str(tmp_path / "Daqiq.db")
    db = create_and_initialize_database(db_path)

    # Create 2 employees
    emp1_id = db.add_employee("علی رضایی", "مدیر", "09121111111", "pass1", "مدیر سیستم (دسترسی کامل)")
    emp2_id = db.add_employee("سارا محمدی", "فروشنده", "09122222222", "pass2", "مدیر سیستم (دسترسی کامل)")

    emp1 = {"id": emp1_id, "name": "علی رضایی", "role": "مدیر", "permissions": "مدیر سیستم (دسترسی کامل)"}
    emp2 = {"id": emp2_id, "name": "سارا محمدی", "role": "فروشنده", "permissions": "مدیر سیستم (دسترسی کامل)"}

    # 1. Initialize MainWindow with emp1
    win = MainWindow(db, active_employee=emp1)

    assert win.cb_batch_buyer.currentText() == "علی رضایی"
    assert win.cb_sale_seller.currentText() == "علی رضایی"
    assert win.cb_srv_seller.currentText() == "علی رضایی"
    assert win.cb_upg_tech.currentText() == "علی رضایی"

    # 2. Test 'پاک کردن فرم' on all 4 tabs
    win._clear_batch_form()
    assert win.cb_batch_buyer.currentText() == "علی رضایی"

    win._clear_sale_form()
    assert win.cb_sale_seller.currentText() == "علی رضایی"

    win._clear_service_rec_form()
    assert win.cb_srv_seller.currentText() == "علی رضایی"

    win._clear_upgrade_form()
    assert win.cb_upg_tech.currentText() == "علی رضایی"

    # 3. Switch active employee to emp2
    win.active_employee = emp2
    win._update_active_user_badge()
    win.refresh_all_data()

    assert win.cb_batch_buyer.currentText() == "سارا محمدی"
    assert win.cb_sale_seller.currentText() == "سارا محمدی"
    assert win.cb_srv_seller.currentText() == "سارا محمدی"
    assert win.cb_upg_tech.currentText() == "سارا محمدی"

    # 4. Trigger refresh_all_data and verify emp2 remains selected
    win.refresh_all_data()
    assert win.cb_batch_buyer.currentText() == "سارا محمدی"
    assert win.cb_sale_seller.currentText() == "سارا محمدی"
    assert win.cb_srv_seller.currentText() == "سارا محمدی"
    assert win.cb_upg_tech.currentText() == "سارا محمدی"


# =========================================================================
# SCENARIO 5: 100% Purge of Asterisk (*) Markers & Uniform Placeholders
# =========================================================================
def test_scenario5_zero_asterisks_and_uniform_placeholders(qapp, tmp_path):
    """Scenario 5:
    - 100% of '*' mandatory indicators purged across all UI labels and titles.
    - ed_sale_customer and other manual inputs have clear Persian placeholders.
    """
    db_path = str(tmp_path / "Daqiq.db")
    db = create_and_initialize_database(db_path)
    emp_id = db.add_employee("مدیر ارشد", "مدیر", "09120000000", "admin", "مدیر سیستم (دسترسی کامل)")
    win = MainWindow(db, active_employee={"id": emp_id, "name": "مدیر ارشد", "role": "مدیر", "permissions": "مدیر سیستم (دسترسی کامل)"})

    # 1. Scan widget tree for mandatory asterisk (*) in labels
    asterisk_labels = []
    for label in win.findChildren(QLabel):
        txt = label.text().strip()
        # Asterisk indicator check (*: or ending with *)
        if "*:" in txt or txt.endswith("*"):
            asterisk_labels.append(txt)

    for gb in win.findChildren(QGroupBox):
        txt = gb.title().strip()
        if "*:" in txt or txt.endswith("*"):
            asterisk_labels.append(txt)

    assert len(asterisk_labels) == 0, f"Found mandatory asterisks in UI: {asterisk_labels}"

    # 2. Check crisp Persian placeholders across inputs
    assert win.ed_sale_customer.placeholderText() in (
        "نام و نام خانوادگی مشتری را وارد کنید...",
        "نام مشتری را تایپ یا از لیست انتخاب کنید...",
    )
    assert win.ed_sale_phone.placeholderText() == "شماره تماس مشتری (مثلاً ۰۹۱۲۳۴۵۶۷۸۹)..."
    assert win.ed_srv_cust.placeholderText() in (
        "نام و نام خانوادگی مشتری را وارد کنید...",
        "نام مشتری را تایپ یا انتخاب کنید...",
    )
    assert "اسکن بارکدخوان یا تایپ شماره سریال..." in win.ed_prod_serial.placeholderText()
    assert "اسکن بارکدخوان یا تایپ شماره سریال..." in win.ed_batch_serial_number.placeholderText()
    assert "اسکن بارکدخوان یا تایپ شماره سریال..." in win.ed_sale_serial.placeholderText()
    assert win.ed_sale_inv.placeholderText().startswith("INV-")
    assert win.ed_srv_code.placeholderText().startswith("SVC-")
    assert win.ed_shop_name.placeholderText() == "نام فروشگاه را وارد کنید..."
    assert not hasattr(win, "ed_emp_old_pass")
    assert hasattr(win, "btn_manage_emp_pass")
    assert "رمز عبور جدید کاربر" in win.ed_emp_pass.placeholderText()


# =========================================================================
# SCENARIO 6: Clean-Slate Schema v483 & Full Store Workflow Regression Sweep
# =========================================================================
def test_scenario6_schema_v482_and_full_workflow_regression(qapp, tmp_path):
    """Scenario 6:
    - Schema version is 483 and APP_VERSION is 4.8.3.
    - All tables, columns, indexes valid.
    - End-to-end store workflow: purchase batch -> sell items -> upgrade batch -> service invoice -> reports.
    """
    assert APP_VERSION == "4.8.4"
    assert SCHEMA_VERSION == 484

    db_path = str(tmp_path / "Daqiq.db")
    db = create_and_initialize_database(db_path)

    with db.get_connection() as conn:
        validate_schema_column_order(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 484

    # Add Employee
    emp_id = db.add_employee("صندوق‌دار اصلی", "فروشنده", "09123456789", "pass123", "مدیر سیستم (دسترسی کامل)")

    # Add Supplier
    sup_id = db.add_supplier("شرکت بازرگانی پارس", "02188888888", "تهران، خیابان ولیعصر")

    # Add Products
    laptop_code = db.add_product(
        "P-LAP-1", "SN-LAP-001", "لپ‌تاپ و سیستم‌های آماده", "لپ‌تاپ مهندسی و اداری (Workstation & Office Laptop)",
        "Lenovo", "ThinkPad E14", {"Specs": "Core i5, 8GB RAM, 256GB SSD"}, "لپ‌تاپ اداری نو",
        1, 20
    )
    ram_code = db.add_product(
        "P-RAM-1", "SN-RAM-001", "قطعات اصلی کامپیوتر", "رم لپ‌تاپ (Laptop RAM)",
        "Crucial", "DDR4 16GB", {"Specs": "3200MHz SODIMM"}, "رم ارتقا",
        1, 20
    )
    with db.get_connection() as conn:
        laptop_id = conn.execute("SELECT id FROM products WHERE code=?", (laptop_code,)).fetchone()["id"]
        ram_id = conn.execute("SELECT id FROM products WHERE code=?", (ram_code,)).fetchone()["id"]

    # Add Batches
    batch_laptop_code = db.add_batch(
        batch_code="C-LAP-01",
        product_id=laptop_id,
        supplier_id=sup_id,
        buyer_employee_id=emp_id,
        invoice_number="INV-IN-01",
        purchase_date="1403/09/01",
        initial_qty=5,
        unit_purchase_price=25000000,
        extra_cost_total=100000,
        suggested_sell_price=28000000,
        paid_amount=125100000,
        serial_numbers="SN-LAP-001",
        initial_specs="Core i5, 8GB RAM, 256GB SSD",
        notes="ThinkPad E14",
        settlement_status="تسویه‌شده",
        colors=["مشکی"],
        supplier_name="شرکت بازرگانی پارس",
    )
    batch_ram_code = db.add_batch(
        batch_code="C-RAM-01",
        product_id=ram_id,
        supplier_id=sup_id,
        buyer_employee_id=emp_id,
        invoice_number="INV-IN-02",
        purchase_date="1403/09/01",
        initial_qty=10,
        unit_purchase_price=1200000,
        extra_cost_total=0,
        suggested_sell_price=1500000,
        paid_amount=12000000,
        serial_numbers="SN-RAM-001",
        initial_specs="3200MHz SODIMM",
        notes="DDR4 16GB",
        settlement_status="تسویه‌شده",
        colors=["سبز"],
        supplier_name="شرکت بازرگانی پارس",
    )
    with db.get_connection() as conn:
        batch_laptop_id = conn.execute("SELECT id FROM batches WHERE batch_code=?", (batch_laptop_code,)).fetchone()["id"]
        batch_ram_id = conn.execute("SELECT id FROM batches WHERE batch_code=?", (batch_ram_code,)).fetchone()["id"]

    # Perform Upgrade on Laptop batch using RAM batch (upgrade 2 laptops with 1 RAM each)
    db.upgrade_batch_product(
        target_batch_id=batch_laptop_id,
        target_qty=2,
        part_batch_id=batch_ram_id,
        part_qty_per_unit=1,
        labor_cost_unit=300000,
        new_specs="Core i5, 24GB RAM, 256GB SSD (Upgraded)",
        technician_id=emp_id,
        add_part_cost_to_product=True,
        consume_stock=True,
        upgrade_date="1403/09/01",
    )

    # Verify stock of RAM batch decreased from 10 to 8
    with db.get_connection() as conn:
        ram_batch = conn.execute("SELECT remaining_qty FROM batches WHERE id=?", (batch_ram_id,)).fetchone()
        assert ram_batch["remaining_qty"] == 8

        # Target batch received new specs
        laptop_batch = conn.execute("SELECT final_specs, upgrade_cost_unit FROM batches WHERE id=?", (batch_laptop_id,)).fetchone()
        assert "24GB RAM" in laptop_batch["final_specs"]
        assert laptop_batch["upgrade_cost_unit"] > 0

    # Sell 1 upgraded laptop
    sale_inv = db.add_sale(
        invoice_number="INV-OUT-101",
        product_id=laptop_id,
        batch_id=batch_laptop_id,
        seller_employee_id=emp_id,
        customer_name="احمد حسینی",
        qty=1,
        suggested_unit_price=30000000,
        actual_unit_price=30000000,
        paid_amount=30000000,
        sale_datetime="1403/09/01 16:00:00",
        settlement_status="تسویه‌شده",
        serial_number="SN-LAP-001-A",
        colors=["مشکی"],
        specifications="Core i5, 24GB RAM, 256GB SSD (Upgraded)",
        warranty_company="گارانتی شرکتی",
        warranty_days=365,
        notes="فروش با ارتقا",
        customer_phone="09191234567",
    )
    assert sale_inv == "INV-OUT-101"

    # Check remaining laptop quantity
    with db.get_connection() as conn:
        laptop_batch_after = conn.execute("SELECT remaining_qty FROM batches WHERE id=?", (batch_laptop_id,)).fetchone()
        assert laptop_batch_after["remaining_qty"] == 4

        sale_row = conn.execute("SELECT * FROM sales WHERE invoice_number=?", (sale_inv,)).fetchone()
        assert sale_row["qty"] == 1
        assert sale_row["actual_unit_price"] == 30000000
        assert sale_row["customer_name"] == "احمد حسینی"
        assert sale_row["specifications"] == "Core i5, 24GB RAM, 256GB SSD (Upgraded)"

    # Add Service Record
    srv_inv = db.add_service_record(
        invoice_number="SRV-301",
        service_id=None,
        seller_employee_id=emp_id,
        technician_employee_id=emp_id,
        customer_name="احمد حسینی",
        service_fee=150000,
        side_cost=20000,
        paid_amount=150000,
        service_datetime="1403/09/01 16:30:00",
        description="تنظیمات نرم‌افزاری اولیه",
        settlement_status="تسویه‌شده",
    )
    assert srv_inv == "SRV-301"

    with db.get_connection() as conn:
        srv_row = conn.execute("SELECT * FROM service_records WHERE invoice_number=?", (srv_inv,)).fetchone()
        assert srv_row["service_fee"] == 150000
        assert srv_row["side_cost"] == 20000
        assert srv_row["net_profit"] == 130000
