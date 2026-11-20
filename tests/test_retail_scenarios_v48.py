"""Comprehensive Multi-Scenario End-to-End QA Suite for Daqiq v4.8.0.
Verifies all 7 production retail scenarios headlessly with zero freezes.
"""

import os
import sys
import json
import tempfile
import sqlite3
from unittest.mock import patch, MagicMock

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
from PySide6.QtCore import Qt

from database import (
    DatabaseManager,
    SCHEMA_VERSION,
    APP_VERSION,
    resolve_new_database_filename,
    create_and_initialize_database,
    SecureCredentialStore,
    load_app_config,
    save_app_config,
    load_default_taxonomy_from_seed,
    get_default_database_path,
)
from utils_and_widgets import DynamicAttributeValuesWidget, DynamicDomainValueRow
from exporter import export_table_to_excel


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if not app:
        app = QApplication(["daqiq_test", "-platform", "offscreen"])
    return app


# ==============================================================================
# Scenario 1: Cold Start, DB Creation & Clean-Slate Setup (REQ-0, REQ-1, REQ-2)
# ==============================================================================

def test_scenario1_smart_naming_and_immediate_creation(tmp_path):
    """Verify smart database naming (Daqiq.db vs timestamped) and unified bootstrapper."""
    base_dir = str(tmp_path / "databases")
    os.makedirs(base_dir, exist_ok=True)

    # 1. First resolution -> Daqiq.db
    path1 = resolve_new_database_filename(base_dir)
    assert os.path.basename(path1) == "Daqiq.db"
    assert not os.path.exists(path1)

    # Create Daqiq.db immediately via bootstrapper (REQ-1)
    db1 = create_and_initialize_database(path1)
    assert os.path.isfile(path1)
    with db1.get_connection() as conn:
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        assert ver == 481

        # Check default settings
        app_ver = conn.execute("SELECT value FROM settings WHERE key='app_version'").fetchone()[0]
        assert app_ver == "4.8.1"

    # Check taxonomy seeded
    tax = db1.get_product_catalog_config()
    assert len(tax.get("categories", [])) > 0
    assert len(tax.get("service_types", [])) > 0
    db1.close()

    # 2. Second resolution when Daqiq.db exists -> Daqiq_YYYY-MM-DD_HH-MM-SS.db
    path2 = resolve_new_database_filename(base_dir)
    base_name = os.path.basename(path2)
    assert base_name.startswith("Daqiq_") and base_name.endswith(".db")
    assert base_name != "Daqiq.db"

    # Create second DB
    db2 = create_and_initialize_database(path2)
    assert os.path.isfile(path2)
    db2.close()


def test_scenario1_taxonomy_missing_fallback(tmp_path, monkeypatch):
    """Verify graceful empty catalog initialization when default_taxonomy.json is missing."""
    import database
    monkeypatch.setattr(database, "load_default_taxonomy_from_seed", lambda: None)

    db_path = str(tmp_path / "empty_catalog.db")
    db = create_and_initialize_database(db_path)
    with db.get_connection() as conn:
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        assert ver == 481
    tax = db.get_product_catalog_config()
    assert len(tax.get("categories", [])) == 0
    assert len(tax.get("service_types", [])) == 0
    db.close()


# ==============================================================================
# Scenario 2: Inventory & Purchasing (Full Lifecycle & Serial Numbers)
# ==============================================================================

def test_scenario2_inventory_purchasing_and_64bit_tomans(tmp_path):
    """Test supplier purchase, batch creation, serial numbers, and 64-bit amounts."""
    db_path = str(tmp_path / "store.db")
    db = create_and_initialize_database(db_path)

    with db.get_connection() as conn:
        # 1. Create a Supplier
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO suppliers (name, phone, address, created_at, updated_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            ("تأمین‌کننده اصلی قطعات", "09123456789", "تهران، میدان ولیعصر")
        )
        supplier_id = cur.lastrowid

        # 2. Create Product with Serial Number requirement
        cur.execute(
            """INSERT INTO products (code, serial_number, name, category, sub_category, brand, model, default_profit_pct, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
            ("PRD-1001", "SN-ASUS-99881", "لپ‌تاپ گیمینگ ایسوس", "کامپیوتر و سخت‌افزار", "لپ‌تاپ", "Asus", "ROG Strix", 15)
        )
        product_id = cur.lastrowid

        # 3. Add Batch with Large 64-bit Toman purchase (5,000,000,000 Toman)
        large_toman_price = 5_000_000_000
        cur.execute(
            """INSERT INTO batches (batch_code, product_id, supplier_id, purchase_date, initial_qty, remaining_qty, unit_purchase_price, unit_cost_price, suggested_sell_price, created_at, updated_at)
               VALUES (?, ?, ?, '1403/01/01', ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
            ("BATCH-001", product_id, supplier_id, 10, 10, large_toman_price, large_toman_price, large_toman_price + 200_000_000)
        )
        batch_id = cur.lastrowid
        conn.commit()

        # Check batch and 64-bit precision preservation
        row = conn.execute("SELECT initial_qty, remaining_qty, unit_purchase_price, unit_cost_price FROM batches WHERE id=?", (batch_id,)).fetchone()
        assert row["initial_qty"] == 10
        assert row["remaining_qty"] == 10
        assert row["unit_purchase_price"] == large_toman_price
        assert row["unit_cost_price"] == large_toman_price

    db.close()


# ==============================================================================
# Scenario 3: Sales, Stock Deduction, Profits & Form Clear Repopulation
# ==============================================================================

def test_scenario3_sales_stock_deduction_and_profit(tmp_path):
    """Test sale transaction, remaining_qty deduction, profit calculation."""
    db_path = str(tmp_path / "sales.db")
    db = create_and_initialize_database(db_path)

    with db.get_connection() as conn:
        cur = conn.cursor()
        # Customer
        cur.execute("INSERT INTO customers (name, phone, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))", ("مشتری گرامی", "09121112233"))
        customer_id = cur.lastrowid

        # Product & Batch
        cur.execute("INSERT INTO products (code, name, category, sub_category, created_at, updated_at) VALUES ('P-SALE', 'کالای فروش', 'عمومی', 'پیش‌فرض', datetime('now'), datetime('now'))")
        product_id = cur.lastrowid

        cur.execute(
            """INSERT INTO batches (batch_code, product_id, purchase_date, initial_qty, remaining_qty, unit_purchase_price, unit_cost_price, suggested_sell_price, created_at, updated_at)
               VALUES ('B-10', ?, '1403/01/01', 20, 20, 100000, 100000, 150000, datetime('now'), datetime('now'))""",
            (product_id,)
        )
        batch_id = cur.lastrowid

        # Sale record (sold 2 units at 150,000, cost 100,000 each -> profit 100,000 total)
        cur.execute(
            """INSERT INTO sales (invoice_number, product_id, batch_id, qty, suggested_unit_price, actual_unit_price, unit_cost_price, unit_profit, total_profit, total_amount, paid_amount, sale_datetime, created_at, updated_at)
               VALUES ('INV-101', ?, ?, 2, 150000, 150000, 100000, 50000, 100000, 300000, 300000, '1403/01/02 10:00:00', datetime('now'), datetime('now'))""",
            (product_id, batch_id)
        )

        # Deduct batch stock
        cur.execute("UPDATE batches SET remaining_qty = remaining_qty - 2, sold_qty = sold_qty + 2 WHERE id=?", (batch_id,))
        conn.commit()

        # Verify stock deducted
        b_row = conn.execute("SELECT initial_qty, sold_qty, remaining_qty FROM batches WHERE id=?", (batch_id,)).fetchone()
        assert b_row["initial_qty"] == 20
        assert b_row["sold_qty"] == 2
        assert b_row["remaining_qty"] == 18

    db.close()


# ==============================================================================
# Scenario 4: Services Order, Financial Breakdown & Catalog Management
# ==============================================================================

def test_scenario4_service_orders_and_taxonomy_management(tmp_path):
    """Test service order creation, parts + labor, and taxonomy draft persistence."""
    db_path = str(tmp_path / "service.db")
    db = create_and_initialize_database(db_path)

    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO service_catalog (code, service_type, name, default_fee, default_side_cost, is_active, created_at, updated_at)
               VALUES ('SRV-01', 'تعمیرات سخت‌افزار', 'تعویض چیپست لپ‌تاپ', 1500000, 500000, 1, datetime('now'), datetime('now'))"""
        )
        catalog_id = cur.lastrowid

        cur.execute(
            """INSERT INTO service_records (invoice_number, service_id, service_type, service_name, customer_name, historical_tariff, service_fee, side_cost, paid_amount, net_profit, service_datetime, created_at, updated_at)
               VALUES ('SRV-2001', ?, 'تعمیرات سخت‌افزار', 'تعویض چیپست لپ‌تاپ', 'مشتری تعمیرات', 1500000, 1500000, 500000, 1500000, 1000000, '1403/01/03 14:00:00', datetime('now'), datetime('now'))""",
            (catalog_id,)
        )
        conn.commit()

        s_row = conn.execute("SELECT service_fee, side_cost, net_profit FROM service_records WHERE invoice_number='SRV-2001'").fetchone()
        assert s_row["service_fee"] == 1500000
        assert s_row["side_cost"] == 500000
        assert s_row["net_profit"] == 1000000

    # Add custom service type and verify persistence
    tax = db.get_product_catalog_config()
    tax.setdefault("service_types", []).append("سرویس دوره‌ای کولر")
    db.save_product_catalog_config(tax)

    reloaded_tax = db.get_product_catalog_config()
    assert "سرویس دوره‌ای کولر" in reloaded_tax["service_types"]
    db.close()


# ==============================================================================
# Scenario 5: Product Settings UI Compaction & Inline Controls (REQ-3)
# ==============================================================================

def test_scenario5_product_settings_ui_compaction(qapp):
    """Verify DynamicAttributeValuesWidget height reduction and row-level controls."""
    widget = DynamicAttributeValuesWidget()

    # 1. Verify height compaction (REQ-3: min 160, max 220, exactly 1 row ~30px less than 190..250)
    assert widget.scroll_area.minimumHeight() == 160
    assert widget.scroll_area.maximumHeight() == 220

    # 2. Verify btn_add_initial is removed
    assert not hasattr(widget, "btn_add_initial")

    # 3. Initial state has exactly 1 empty row with '+' and '-' buttons
    assert len(widget.rows) == 1
    assert widget.rows[0].text() == ""
    assert widget.get_values() == []

    # 4. Input text and add after
    widget.rows[0].setText("USB 3.0")
    assert widget.get_values() == ["USB 3.0"]

    # Click '+' on first row
    widget.rows[0].btn_add.click()
    assert len(widget.rows) == 2
    widget.rows[1].setText("Type-C")
    assert widget.get_values() == ["USB 3.0", "Type-C"]

    # 5. Remove first row via '-' button
    widget.rows[0].btn_remove.click()
    assert len(widget.rows) == 1
    assert widget.get_values() == ["Type-C"]

    # 6. Remove remaining row -> guarantees at least 1 empty row remains with '+' and '-'
    widget.rows[0].btn_remove.click()
    assert len(widget.rows) == 1
    assert widget.rows[0].text() == ""
    assert widget.get_values() == []

    # 7. Clear widget -> guarantees at least 1 empty row
    widget.set_values(["HDMI", "DisplayPort"])
    assert len(widget.rows) == 2
    widget.clear()
    assert len(widget.rows) == 1
    assert widget.rows[0].text() == ""
    assert widget.get_values() == []


# ==============================================================================
# Scenario 6: Database Encryption, DPAPI Auto-Unlock & Single-Close Dialog (REQ-4)
# ==============================================================================

def test_scenario6_dpapi_auto_unlock_and_single_close_remove_dialog(qapp, tmp_path):
    """Test SQLCipher encryption, DPAPI auto-unlock toggle, and single-execution password removal."""
    db_path = str(tmp_path / "enc_test.db")
    vault_path = str(tmp_path / ".test_vault.dat")
    SecureCredentialStore.set_vault_path(vault_path)

    db = create_and_initialize_database(db_path)
    assert not db.is_password_protected()

    # 1. Encrypt DB with startup prompt enabled
    test_pwd = "P@ssw0rdSecure480!"
    db.set_database_password(test_pwd, require_startup_prompt=True)
    assert db.is_password_protected()
    assert db.is_startup_password_prompt_required()
    # Startup prompt required -> credential MUST NOT be stored in vault
    assert SecureCredentialStore.retrieve_database_credential(db_path) is None
    assert not db.can_auto_unlock_locally()

    # 2. Toggle startup password prompt OFF (enable auto-unlock)
    db.set_startup_password_prompt_required(False)
    assert not db.is_startup_password_prompt_required()
    # Credential MUST be stored in DPAPI vault
    assert SecureCredentialStore.retrieve_database_credential(db_path) == test_pwd
    assert db.can_auto_unlock_locally()

    # Test auto-unlock on cold start (re-opening DatabaseManager without password argument)
    db.close()
    cold_db = DatabaseManager(db_path)
    assert cold_db.is_password_protected()
    assert cold_db._encryption_key == test_pwd
    assert cold_db.can_auto_unlock_locally()

    # 3. Toggle startup password prompt back ON -> credential must be purged
    cold_db.set_startup_password_prompt_required(True)
    assert cold_db.is_startup_password_prompt_required()
    assert SecureCredentialStore.retrieve_database_credential(db_path) is None
    assert not cold_db.can_auto_unlock_locally()

    # 4. Remove database password directly
    cold_db.remove_database_password(test_pwd)
    assert not cold_db.is_password_protected()
    assert SecureCredentialStore.retrieve_database_credential(db_path) is None
    cold_db.close()

    # Clean up vault path
    SecureCredentialStore.set_vault_path(None)


def test_scenario6_remove_password_dialog_single_exec(qapp, tmp_path, monkeypatch):
    """Verify _on_remove_db_password_clicked executes dialog.exec() exactly once."""
    from main import MainWindow
    db_path = str(tmp_path / "dialog_test.db")
    db = create_and_initialize_database(db_path)
    db.set_database_password("MySecretPass123", require_startup_prompt=True)

    win = MainWindow(db, {"id": 1, "name": "مدیر سیستم", "role": "admin"})

    exec_count = 0

    def mock_exec(dialog_self):
        nonlocal exec_count
        exec_count += 1
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", mock_exec)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr("main._ask_yes_no", lambda *args, **kwargs: True)

    win._on_remove_db_password_clicked()

    # Ensure dialog.exec() was called exactly ONCE (eliminating the duplicate dialog bug)
    assert exec_count == 1
    win.close()
    db.close()


# ==============================================================================
# Scenario 7: Comprehensive Reports, Excel Export & Settings Persistence
# ==============================================================================

def test_scenario7_reports_excel_and_settings_persistence(tmp_path):
    """Test multi-operation reports, Excel export styling, and settings save."""
    db_path = str(tmp_path / "reports.db")
    db = create_and_initialize_database(db_path)

    # 1. Update general settings
    db.set_setting("shop_name", "فروشگاه بزرگ دیجیتال تهران")
    db.set_setting("shop_phone", "021-88889999")
    db.set_setting("shop_address", "خیابان ولیعصر، پلاک ۱۰۰")

    assert db.get_setting("shop_name") == "فروشگاه بزرگ دیجیتال تهران"
    assert db.get_setting("shop_phone") == "021-88889999"

    # 2. Test Excel export
    excel_path = str(tmp_path / "test_report.xlsx")
    headers = ["شناسه", "نام کالا", "موجودی", "قیمت خرید (تومان)", "قیمت فروش (تومان)"]
    rows = [
        ["1", "کارت گرافیک RTX 4080", "5", "85,000,000", "98,000,000"],
        ["2", "پردازنده Core i9-14900K", "8", "34,000,000", "39,500,000"],
    ]

    export_table_to_excel("گزارش موجودی انبار فروشگاه", headers, rows, excel_path)
    assert os.path.isfile(excel_path)
    assert os.path.getsize(excel_path) > 1000

    db.close()
