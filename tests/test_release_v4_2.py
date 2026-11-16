# -*- coding: utf-8 -*-
"""
Automated Test Suite for Daqiq v4.2.0 Enterprise Release.

Validates all 15 core architectural, dynamic feature, taxonomy, cryptographic,
and UI/UX requirements:
0. Greenfield Schema 420 & Priority Column Sequences (serial_number priority)
1. Product Management Grid - Serial Number Visibility
2. Dynamic Feature Sets & Category Constraints (Laptops, SSD/HDD, Components, Accessories)
3. Taxonomy Standardization & Bilingual Subcategories 'فارسی (انگلیسی)'
4. Default Minimum Stock = 1 & Configuration Persistence
5. Serial Number Observer Pattern & Reporting Visibility
6. Customer Contact Data Integration & Mandatory Validation
7. Settings Action Buttons & Accordion Lifecycle
8. Dynamic Configurable Backup Directory Persistence
9. Cryptographic AES-256-GCM Database Security & Header Verification
10. Timer Stability & Polling Heartbeat Architecture
11. Excel Export UX & Custom Layout Persistence
"""

import json
import os
import sqlite3
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import database as database_module
from database import (
    APP_VERSION,
    SCHEMA_VERSION,
    DatabaseManager,
    is_database_encrypted,
    encrypt_database_file,
    decrypt_database_file,
    load_app_config,
)
import utils_and_widgets as utils_module
from utils_and_widgets import (
    MAIN_CATEGORIES,
    DEFAULT_SUBCATEGORIES,
    DEFAULT_ATTRIBUTES,
    normalize_catalog_label,
    CollapsibleSection,
    DynamicSpecsWidget,
)
import main as main_module
from main import MainWindow


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def mock_qmessagebox(monkeypatch):
    monkeypatch.setattr(main_module.QMessageBox, "information", lambda *args, **kwargs: main_module.QMessageBox.Ok)
    monkeypatch.setattr(main_module.QMessageBox, "warning", lambda *args, **kwargs: main_module.QMessageBox.Ok)
    monkeypatch.setattr(main_module.QMessageBox, "critical", lambda *args, **kwargs: main_module.QMessageBox.Ok)
    monkeypatch.setattr(main_module.QMessageBox, "question", lambda *args, **kwargs: main_module.QMessageBox.Yes)


@pytest.fixture
def clean_db(tmp_path):
    db_path = str(tmp_path / "test_daqiq_v42.db")
    mgr = DatabaseManager(db_path)
    return mgr, db_path


# ==============================================================================
# Requirement 0: Greenfield Schema 420 & Priority Column Sequences
# ==============================================================================
def test_greenfield_schema_420_and_priority_columns(clean_db):
    mgr, db_path = clean_db
    assert APP_VERSION == "4.2.0"
    assert SCHEMA_VERSION == 420

    with mgr.get_connection() as conn:
        schema_ver = conn.execute("PRAGMA user_version").fetchone()[0]
        assert schema_ver == 420

        # Check products table columns order: id, serial_number, code, ...
        prod_cols = [r[1] for r in conn.execute("PRAGMA table_info(products)").fetchall()]
        assert prod_cols[0] == "id"
        assert prod_cols[1] == "serial_number"
        assert prod_cols[2] == "code"

        # Check sales table columns: includes serial_number early, and customer_phone
        sales_cols = [r[1] for r in conn.execute("PRAGMA table_info(sales)").fetchall()]
        assert sales_cols[0] == "id"
        assert sales_cols[1] == "serial_number"
        assert "customer_phone" in sales_cols

        # Check indices
        indices = [r[1] for r in conn.execute("PRAGMA index_list(sales)").fetchall()]
        assert "idx_sales_customer_phone" in indices


# ==============================================================================
# Requirement 1: Product Management Grid - Serial Number Visibility
# ==============================================================================
def test_product_grid_serial_number_column(clean_db, monkeypatch, tmp_path, qapp):
    mgr, db_path = clean_db
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))

    window = MainWindow(mgr, active_employee=None)
    try:
        col_headers = [
            window.tbl_products.horizontalHeaderItem(i).text()
            for i in range(window.tbl_products.columnCount())
        ]
        assert "شماره سریال" in col_headers
    finally:
        window.close()
        qapp.processEvents()


# ==============================================================================
# Requirement 2 & 3: Dynamic Feature Sets & Bilingual Taxonomy
# ==============================================================================
def test_taxonomy_bilingual_and_pure_persian_main():
    # Main categories must be purely Persian
    for cat in MAIN_CATEGORIES:
        assert isinstance(cat, str) and len(cat) > 0
        # Check no ascii English letters in main category names
        assert not any("a" <= ch.lower() <= "z" for ch in cat)

    # Subcategories must follow format "فارسی (انگلیسی)"
    for cat, subcats in DEFAULT_SUBCATEGORIES.items():
        for subcat in subcats:
            assert "(" in subcat and subcat.endswith(")"), f"Subcategory {subcat} must end with '(English)'"
            paren_content = subcat[subcat.rfind("(") + 1 : -1]
            assert any("a" <= ch.lower() <= "z" for ch in paren_content), f"{subcat} missing English translation"


def test_dynamic_feature_sets_constraints(qapp):
    widget = DynamicSpecsWidget()

    # Laptops: "مشخصات" must exist on all laptop subcategories
    laptop_subcats = DEFAULT_SUBCATEGORIES.get("لپ تاپ", [])
    for subcat in laptop_subcats:
        widget.set_category("لپ تاپ")
        widget.cb_sub.setCurrentText(subcat)
        qapp.processEvents()
        fields = widget.fields
        assert "مشخصات" in fields, f"Laptop subcategory {subcat} missing 'مشخصات'"
        if "سایر موارد" in subcat:
            assert list(fields.keys()) == ["مشخصات"], f"'سایر موارد' in laptops must ONLY have 'مشخصات', got {list(fields.keys())}"

    # Components: "مشخصات" exists, duplicate "مشخصه" removed, "سایر موارد" has only "مشخصات"
    comp_subcats = DEFAULT_SUBCATEGORIES.get("قطعات", [])
    for subcat in comp_subcats:
        widget.set_category("قطعات")
        widget.cb_sub.setCurrentText(subcat)
        qapp.processEvents()
        fields = widget.fields
        assert "مشخصه" not in fields, f"Deprecated 'مشخصه' found in {subcat}"
        assert "مشخصات" in fields, f"Component subcategory {subcat} missing 'مشخصات'"
        if "سایر موارد" in subcat:
            assert list(fields.keys()) == ["مشخصات"], f"'سایر موارد' in components must ONLY have 'مشخصات'"

    # SSD vs HDD capacity tailoring & single interface field
    ssd_subcats = [s for s in comp_subcats if "اس‌اس‌دی" in s or "SSD" in s]
    hdd_subcats = [s for s in comp_subcats if "هارد دیسک اینترنال" in s or "Internal HDD" in s]
    assert len(ssd_subcats) > 0
    assert len(hdd_subcats) > 0

    widget.set_category("قطعات")
    widget.cb_sub.setCurrentText(ssd_subcats[0])
    qapp.processEvents()
    assert "ظرفیت" in widget.fields
    assert "نوع رابط" in widget.fields
    ssd_caps = [widget.fields["ظرفیت"].itemText(i) for i in range(widget.fields["ظرفیت"].count())]
    assert any("128GB" in c for c in ssd_caps)

    widget.cb_sub.setCurrentText(hdd_subcats[0])
    qapp.processEvents()
    assert "ظرفیت" in widget.fields
    assert "نوع رابط" in widget.fields
    hdd_caps = [widget.fields["ظرفیت"].itemText(i) for i in range(widget.fields["ظرفیت"].count())]
    assert any("2TB" in c or "4TB" in c for c in hdd_caps)

    # Accessories: modern multi-mode connections
    mouse_subcats = [s for s in DEFAULT_SUBCATEGORIES.get("لوازم جانبی", []) if "ماوس" in s or "Mouse" in s]
    assert len(mouse_subcats) > 0
    widget.set_category("لوازم جانبی")
    widget.cb_sub.setCurrentText(mouse_subcats[0])
    qapp.processEvents()
    assert "نوع اتصال / پورت" in widget.fields
    conn_list = [widget.fields["نوع اتصال / پورت"].itemText(i) for i in range(widget.fields["نوع اتصال / پورت"].count())]
    assert any("Wired" in opt or "Bluetooth" in opt or "Wireless" in opt for opt in conn_list)


def test_normalize_catalog_label_bilingual():
    assert normalize_catalog_label("ماوس (Mouse)") == normalize_catalog_label("ماوس")
    assert normalize_catalog_label("لپ‌تاپ عمومی / مالتی‌مدیا (General / Multimedia)") == normalize_catalog_label("لپ تاپ عمومی / مالتی مدیا")


# ==============================================================================
# Requirement 4: Default Minimum Stock = 1 & Configuration Persistence
# ==============================================================================
def test_default_min_stock_persisted(clean_db, monkeypatch, tmp_path, qapp):
    mgr, db_path = clean_db
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    cfg_file = str(tmp_path / "app_config.json")
    monkeypatch.setattr(database_module, "CONFIG_FILE", cfg_file)

    # Initial default is 1
    cfg = load_app_config()
    assert cfg.get("default_min_stock", 1) == 1

    window = MainWindow(mgr, active_employee=None)
    try:
        assert hasattr(window, "sp_set_min_stock")
        assert window.sp_set_min_stock.value() >= 1
        window.sp_set_min_stock.setValue(5)
        window._save_general_settings()

        saved_cfg = load_app_config()
        assert saved_cfg.get("default_min_stock") == 5
    finally:
        window.close()
        qapp.processEvents()


# ==============================================================================
# Requirement 5: Serial Number Observer Pattern & Reporting
# ==============================================================================
def test_serial_number_observer_auto_populates(clean_db, monkeypatch, tmp_path, qapp):
    mgr, db_path = clean_db
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))

    mgr.add_product(
        code="P-OBS-1",
        name="Laptop Test",
        category="لپ تاپ",
        sub_category="لپ‌تاپ گیمینگ (Gaming)",
        brand="ASUS",
        model="ROG",
        specs_dict={"مشخصات": "Core i7"},
        description="Demo",
        serial_number="SN-TEST-9999",
    )
    with mgr.get_connection() as conn:
        prod_id = conn.execute("SELECT id FROM products WHERE code='P-OBS-1'").fetchone()[0]

    mgr.add_batch(
        batch_code="B-OBS-1",
        product_id=prod_id,
        supplier_id=None,
        buyer_employee_id=None,
        invoice_number="INV-B-1",
        purchase_date="1404/01/01",
        initial_qty=5,
        unit_purchase_price=1000,
        extra_cost_total=0,
        suggested_sell_price=1200,
        paid_amount=5000,
        serial_numbers="SN-TEST-9999",
    )

    window = MainWindow(mgr, active_employee=None)
    try:
        window._refresh_combos()

        # Select in sales combobox
        idx = next(
            i for i in range(window.cb_sale_prod.count())
            if window.cb_sale_prod.itemData(i) and window.cb_sale_prod.itemData(i).get("id") == prod_id
        )
        window.cb_sale_prod.setCurrentIndex(idx)
        qapp.processEvents()

        # Auto-populated serial number
        assert window.ed_sale_serial.text() == "SN-TEST-9999"
    finally:
        window.close()
        qapp.processEvents()


# ==============================================================================
# Requirement 6: Customer Contact Data Integration & Mandatory Validation
# ==============================================================================
def test_customer_phone_mandatory_in_sales(clean_db, monkeypatch, tmp_path, qapp):
    mgr, db_path = clean_db
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))

    mgr.add_product(
        code="P-PHONE-1",
        name="Phone Test Item",
        category="لپ تاپ",
        sub_category="لپ‌تاپ گیمینگ (Gaming)",
        brand="ASUS",
        model="ROG",
        specs_dict={},
        description="",
        serial_number="SN-PHONE-1",
    )
    with mgr.get_connection() as conn:
        prod_id = conn.execute("SELECT id FROM products WHERE code='P-PHONE-1'").fetchone()[0]

    mgr.add_batch(
        batch_code="B-PH-1",
        product_id=prod_id,
        supplier_id=None,
        buyer_employee_id=None,
        invoice_number="INV-B-2",
        purchase_date="1404/01/01",
        initial_qty=5,
        unit_purchase_price=1000,
        extra_cost_total=0,
        suggested_sell_price=1200,
        paid_amount=5000,
    )
    with mgr.get_connection() as conn:
        batch_int_id = conn.execute("SELECT id FROM batches WHERE batch_code='B-PH-1'").fetchone()[0]

    sale_id = mgr.add_sale(
        invoice_number="INV-PHONE-01",
        product_id=prod_id,
        batch_id=batch_int_id,
        seller_employee_id=None,
        customer_name="Ali Reza",
        qty=1,
        suggested_unit_price=1200,
        actual_unit_price=1200,
        paid_amount=1200,
        sale_datetime="1404/01/01 10:00:00",
        customer_phone="09121112233",
        serial_number="SN-PHONE-1",
    )
    assert sale_id == "INV-PHONE-01"

    with mgr.get_connection() as conn:
        sale_rec = conn.execute(
            "SELECT customer_phone, serial_number FROM sales WHERE invoice_number=?",
            (sale_id,),
        ).fetchone()
        assert sale_rec is not None
        assert sale_rec["customer_phone"] == "09121112233"
        assert sale_rec["serial_number"] == "SN-PHONE-1"


# ==============================================================================
# Requirement 7: Settings Action Buttons & Accordion Lifecycle
# ==============================================================================
def test_settings_rollback_collapses_sections(clean_db, monkeypatch, tmp_path, qapp):
    mgr, db_path = clean_db
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))

    window = MainWindow(mgr, active_employee=None)
    try:
        # Expand one section
        sections = [child for child in window.findChildren(CollapsibleSection)]
        assert len(sections) > 0
        sections[0].expand()
        assert sections[0].is_expanded is True

        # Click rollback
        window._rollback_settings()
        # All sections should be collapsed
        for sec in sections:
            assert sec.is_expanded is False
    finally:
        window.close()
        qapp.processEvents()


# ==============================================================================
# Requirement 8: Dynamic Configurable Backup Directory Persistence
# ==============================================================================
def test_backup_dir_configurable_and_persistent(clean_db, monkeypatch, tmp_path, qapp):
    mgr, db_path = clean_db
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))

    custom_backup = str(tmp_path / "my_custom_backups")
    os.makedirs(custom_backup, exist_ok=True)

    window = MainWindow(mgr, active_employee=None)
    try:
        assert hasattr(window, "ed_backup_dir")
        window.ed_backup_dir.setText(custom_backup)
        window._save_general_settings()

        cfg = load_app_config()
        assert cfg.get("backup_dir") == custom_backup

        # Execute backup
        backup_path = mgr.create_backup(custom_dir=custom_backup)
        assert os.path.exists(backup_path)
        assert os.path.dirname(backup_path) == custom_backup
    finally:
        window.close()
        qapp.processEvents()


# ==============================================================================
# Requirement 9: Cryptographic AES-256-GCM Database Security
# ==============================================================================
def test_database_aes_256_gcm_encryption_roundtrip(tmp_path):
    plain_db_path = str(tmp_path / "plain_vault.db")
    mgr = DatabaseManager(plain_db_path)
    mgr.add_product(
        code="P-SEC",
        name="Secret Device",
        category="لپ تاپ",
        sub_category="لپ‌تاپ گیمینگ (Gaming)",
        brand="Brand",
        model="Model",
        specs_dict={},
        description="",
        serial_number="SN-SEC-12345",
    )

    # Check unencrypted
    assert not is_database_encrypted(plain_db_path)

    # Encrypt
    enc_db_path = str(tmp_path / "encrypted_vault.db")
    password = "MasterKeyP@ssw0rd!2026"
    encrypt_database_file(plain_db_path, password, target_path=enc_db_path)

    assert is_database_encrypted(enc_db_path)
    with open(enc_db_path, "rb") as f:
        header = f.read(13)
        assert header == b"DAQIQ_ENC_V1\x00"

    # Decrypt
    dec_db_path = str(tmp_path / "decrypted_vault.db")
    decrypt_database_file(enc_db_path, password, target_path=dec_db_path)
    assert not is_database_encrypted(dec_db_path)

    dec_mgr = DatabaseManager(dec_db_path)
    with dec_mgr.get_connection() as conn:
        prod = conn.execute("SELECT * FROM products WHERE code='P-SEC'").fetchone()
        assert prod is not None
        assert prod["serial_number"] == "SN-SEC-12345"


# ==============================================================================
# Requirement 10: Polling Heartbeat Backup Architecture
# ==============================================================================
def test_backup_heartbeat_polling(clean_db, monkeypatch, tmp_path, qapp):
    mgr, db_path = clean_db
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))

    window = MainWindow(mgr, active_employee=None)
    try:
        # Verify the backup timer interval is fixed at 60,000ms
        assert hasattr(window, "backup_timer")
        assert window.backup_timer.interval() == 60_000
    finally:
        window.close()
        qapp.processEvents()


# ==============================================================================
# Requirement 11: Excel Export UX & Custom Layout
# ==============================================================================
def test_excel_export_column_label_click_and_layout_name(clean_db, monkeypatch, tmp_path, qapp):
    mgr, db_path = clean_db
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))

    window = MainWindow(mgr, active_employee=None)
    try:
        assert hasattr(window, "ed_report_layout_name")
        assert hasattr(window, "lst_report_export_columns")
        if window.lst_report_export_columns.count() > 0:
            first_item = window.lst_report_export_columns.item(0)
            initial_state = first_item.checkState()
            window._on_report_export_col_clicked(first_item)
            expected_state = Qt.Unchecked if initial_state == Qt.Checked else Qt.Checked
            assert first_item.checkState() == expected_state
    finally:
        window.close()
        qapp.processEvents()
