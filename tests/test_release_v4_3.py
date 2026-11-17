"""Enterprise-grade regression and unit test suite for Daqiq v4.3.0 release requirements."""
import copy
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QLineEdit

import database
from database import (
    APP_VERSION,
    SCHEMA_VERSION,
    EXPECTED_SCHEMA_COLUMNS,
    DatabaseManager,
    is_database_encrypted,
    encrypt_database_bytes,
    decrypt_database_bytes,
    DatabasePasswordRequiredError,
    DatabaseInvalidPasswordError,
)
import main as main_module
from main import (
    MainWindow,
    DatabaseUnlockDialog,
    REPORT_AVAILABLE_COLUMNS,
)
from utils_and_widgets import (
    MAIN_CATEGORIES,
    DEFAULT_SUBCATEGORIES,
    DEFAULT_ATTRIBUTES,
    SSD_CAPACITIES,
    HDD_CAPACITIES,
    SSD_INTERFACES,
    HDD_INTERFACES,
    CONNECTIVITY_OPTIONS,
    BAG_TYPES,
    BAG_SIZES,
    BAG_MATERIALS,
    CollapsibleSection,
)
from exporter import export_table_to_excel, export_safe_inventory_excel


class ReleaseV43Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._patchers = [
            patch.object(main_module.QMessageBox, "information"),
            patch.object(main_module.QMessageBox, "warning"),
            patch.object(main_module.QMessageBox, "critical"),
            patch.object(main_module.QMessageBox, "question", return_value=main_module.QMessageBox.Yes),
            patch.object(main_module, "_ask_yes_no", return_value=True),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()

    def test_greenfield_database_schema_and_version(self):
        """Requirement 0 & 15: Clean greenfield DB initialization with 4.3.0/430 schema."""
        self.assertEqual(APP_VERSION, "4.3.0")
        self.assertEqual(SCHEMA_VERSION, 430)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test_v430.db")
            config_path = os.path.join(tmp, "app_config.json")
            with patch.object(database, "CONFIG_FILE", config_path):
                db = DatabaseManager(db_path)
                with db.get_connection() as conn:
                    # User version matches 430
                    self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 430)

                    # Physical column order: serial_number is 1st domain column after id
                    for table in ("products", "upgrades", "sales"):
                        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
                        self.assertEqual(cols[0], "id")
                        self.assertEqual(cols[1], "serial_number", f"Table {table} must have serial_number as column 1")

                    # In batches, serial_numbers is column 1
                    batch_cols = [r["name"] for r in conn.execute("PRAGMA table_info(batches)")]
                    self.assertEqual(batch_cols[0], "id")
                    self.assertEqual(batch_cols[1], "serial_numbers")

                    # sales has customer_phone
                    sale_cols = [r["name"] for r in conn.execute("PRAGMA table_info(sales)")]
                    self.assertIn("customer_phone", sale_cols)

                    # Search indexes exist
                    indexes = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
                    self.assertIn("idx_products_serial", indexes)
                    self.assertIn("idx_batches_serial", indexes)
                    self.assertIn("idx_sales_serial", indexes)
                    self.assertIn("idx_sales_customer_phone", indexes)

    def test_database_encryption_and_decryption_flow(self):
        """Requirement 13: Full database password encryption using PBKDF2 + AES-256-GCM."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "secure_shop.db")
            config_path = os.path.join(tmp, "app_config.json")
            with patch.object(database, "CONFIG_FILE", config_path):
                db = DatabaseManager(db_path)
                db.add_product("P-SEC-01", "", "قطعات", "رم کامپیوتر (Desktop RAM)", "Kingston", "Fury", {}, "", 5, 20, serial_number="SN-SEC-999")
                db.sync_database()

                self.assertFalse(db.is_encrypted())
                self.assertFalse(is_database_encrypted(db_path))

                # Set password
                db.set_password("EnterprisePassword#2026")
                db.sync_database()

                self.assertTrue(db.is_encrypted())
                self.assertTrue(is_database_encrypted(db_path))

                # Reopening without password must raise DatabasePasswordRequiredError
                with self.assertRaises(DatabasePasswordRequiredError):
                    DatabaseManager(db_path)

                # Reopening with wrong password must raise DatabaseInvalidPasswordError
                with self.assertRaises(DatabaseInvalidPasswordError):
                    DatabaseManager(db_path, password="WrongPassword")

                # Reopening with correct password must succeed
                db_reopened = DatabaseManager(db_path, password="EnterprisePassword#2026")
                with db_reopened.get_connection() as conn:
                    row = conn.execute("SELECT code, serial_number FROM products WHERE code='P-SEC-01'").fetchone()
                    self.assertEqual(row["code"], "P-SEC-01")
                    self.assertEqual(row["serial_number"], "SN-SEC-999")

                # Remove password
                db_reopened.remove_password("EnterprisePassword#2026")
                db_reopened.sync_database()

                self.assertFalse(db_reopened.is_encrypted())
                self.assertFalse(is_database_encrypted(db_path))

                # Clean opening without password now succeeds
                db_unencrypted = DatabaseManager(db_path)
                with db_unencrypted.get_connection() as conn:
                    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
                    self.assertEqual(count, 1)

    def test_bilingual_taxonomy_and_specifications_standards(self):
        """Requirement 2 & 3: 100% Persian main categories, bilingual subcategories, English specs, single-drive capacities."""
        # 1. Main categories are 100% Persian
        for cat in MAIN_CATEGORIES:
            for ch in cat:
                if 'a' <= ch <= 'z' or 'A' <= ch <= 'Z':
                    self.fail(f"Main category '{cat}' contains English characters!")

        # 2. Subcategories follow bilingual format 'فارسی (English)'
        for cat, subs in DEFAULT_SUBCATEGORIES.items():
            for sub in subs:
                self.assertTrue(
                    "(" in sub and ")" in sub,
                    f"Subcategory '{sub}' in '{cat}' does not follow bilingual 'فارسی (English)' format",
                )
            # Last subcategory in every category is 'سایر موارد (Other)'
            self.assertEqual(subs[-1], "سایر موارد (Other)")

        # 3. SSD and HDD capacities have NO dual-drive combos
        for cap in SSD_CAPACITIES:
            self.assertNotIn("+", cap, f"SSD capacity '{cap}' must not contain dual-drive combos")
        for cap in HDD_CAPACITIES:
            self.assertNotIn("+", cap, f"HDD capacity '{cap}' must not contain dual-drive combos")

        # 4. Storage interfaces are tailored specifically
        self.assertIn("M.2 NVMe PCIe 4.0", SSD_INTERFACES)
        self.assertIn("SATA III 3.5-inch", HDD_INTERFACES)

        # 5. Connectivity options include single and multi-mode options
        self.assertIn("Tri-Mode / Multi-Mode (Wired + 2.4GHz + Bluetooth)", CONNECTIVITY_OPTIONS)

        # 6. Backpack attributes are non-electronic
        self.assertIn("Backpack", BAG_TYPES)
        self.assertIn("15.6-inch", BAG_SIZES)
        self.assertIn("Water-Resistant Polyester", BAG_MATERIALS)

        # 7. In DEFAULT_ATTRIBUTES, 'مشخصات' (Specifications) is always the last field
        for cat, attrs in DEFAULT_ATTRIBUTES.items():
            if attrs:
                self.assertEqual(attrs[-1]["name"], "مشخصات")
                self.assertEqual(attrs[-1]["label"], "Specifications")

    def test_min_stock_defaults_to_one_and_is_configurable(self):
        """Requirement 4: Default min stock is 1 across forms and configurable via Settings."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "min_stock.db")
            config_path = os.path.join(tmp, "app_config.json")
            with patch.object(database, "CONFIG_FILE", config_path):
                db = DatabaseManager(db_path)
                window = MainWindow(db, active_employee=None)
                try:
                    # Form spinbox defaults to config value (1)
                    self.assertEqual(window.sp_prod_reorder.value(), 1)
                    self.assertEqual(window.sp_set_default_min_stock.value(), 1)

                    # Change default in settings
                    window.sp_set_default_min_stock.setValue(5)
                    window._save_general_settings()

                    self.assertEqual(db.cfg.get("default_min_stock"), 5)

                    # Product form clear resets to new default
                    window._clear_product_form()
                    self.assertEqual(window.sp_prod_reorder.value(), 5)
                finally:
                    window.close()

    def test_product_management_table_has_serial_number_first(self):
        """Requirement 1: Missing Serial Number in Product Management bottom table is resolved."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "prod_table.db")
            config_path = os.path.join(tmp, "app_config.json")
            with patch.object(database, "CONFIG_FILE", config_path):
                db = DatabaseManager(db_path)
                db.add_product("P-100", "", "قطعات", "رم کامپیوتر (Desktop RAM)", "Corsair", "Vengeance", {}, "", 3, 15, serial_number="SN-ALPHA-001")
                window = MainWindow(db, active_employee=None)
                try:
                    # Check table header
                    header_0 = window.tbl_products.horizontalHeaderItem(0).text()
                    header_1 = window.tbl_products.horizontalHeaderItem(1).text()
                    self.assertEqual(header_0, "شناسه")
                    self.assertEqual(header_1, "شماره سریال")

                    # Check populated data in row 0
                    self.assertEqual(window.tbl_products.rowCount(), 1)
                    self.assertEqual(window.tbl_products.item(0, 1).text(), "SN-ALPHA-001")
                finally:
                    window.close()

    def test_cargo_and_sales_serial_auto_fill_with_reentrancy_guard(self):
        """Requirement 5: Cargo and sales serial auto-fill with re-entrancy guard."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "autofill.db")
            config_path = os.path.join(tmp, "app_config.json")
            with patch.object(database, "CONFIG_FILE", config_path):
                db = DatabaseManager(db_path)
                db.add_product("P-AUTO-1", "", "قطعات", "رم کامپیوتر (Desktop RAM)", "Crucial", "DDR5", {}, "", 1, 20, serial_number="SN-AUTO-1234")
                window = MainWindow(db, active_employee=None)
                try:
                    self.assertFalse(window._syncing_serial)

                    # Trigger product change in batch tab
                    prod_idx = window.cb_batch_prod.findData(1)
                    if prod_idx >= 0:
                        window.cb_batch_prod.setCurrentIndex(prod_idx)
                        self.assertEqual(window.ed_batch_serial.text(), "SN-AUTO-1234")

                    # Verify re-entrancy guard is reset
                    self.assertFalse(window._syncing_serial)
                finally:
                    window.close()

    def test_sales_customer_phone_handling(self):
        """Requirement 6: Customer phone field in sales form, table, reports, and export."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "cust_phone.db")
            config_path = os.path.join(tmp, "app_config.json")
            with patch.object(database, "CONFIG_FILE", config_path):
                db = DatabaseManager(db_path)
                p_code = db.add_product("P-PHONE", "", "قطعات", "رم کامپیوتر (Desktop RAM)", "Adata", "XPG", {}, "", 1, 20, serial_number="SN-PHONE-1")
                with db.get_connection() as conn:
                    p_id = conn.execute("SELECT id FROM products WHERE code=?", (p_code,)).fetchone()["id"]
                b_code = db.add_batch("B-PHONE", p_id, None, None, "INV-01", "1405/01/01", 5, 1000, 0, 1500, 0, serial_numbers="SN-PHONE-1")
                with db.get_connection() as conn:
                    b_id = conn.execute("SELECT id FROM batches WHERE batch_code=?", (b_code,)).fetchone()["id"]

                # Add sale with customer phone
                sale_inv = db.add_sale(
                    "INV-S-01", p_id, b_id, None, "مشتری رضایی",
                    1, 1500, 1500, 0, "1405/01/02 10:00:00",
                    serial_number="SN-PHONE-1",
                    customer_phone="09123456789",
                )

                with db.get_connection() as conn:
                    sale = conn.execute("SELECT customer_name, customer_phone, serial_number FROM sales WHERE invoice_number=?", (sale_inv,)).fetchone()
                    self.assertEqual(sale["customer_name"], "مشتری رضایی")
                    self.assertEqual(sale["customer_phone"], "09123456789")

                # Verify column in REPORT_AVAILABLE_COLUMNS
                self.assertIn("شماره تماس مشتری", REPORT_AVAILABLE_COLUMNS["۱. گزارش کامل تمام فروش‌ها"])

                window = MainWindow(db, active_employee=None)
                try:
                    # Sales table has customer phone column
                    col_names = [window.tbl_sales.horizontalHeaderItem(i).text() for i in range(window.tbl_sales.columnCount())]
                    self.assertIn("شماره تماس مشتری", col_names)
                    self.assertEqual(window.tbl_sales.item(0, col_names.index("شماره تماس مشتری")).text(), "09123456789")
                finally:
                    window.close()

    def test_backup_timer_overflow_protection_and_cleanup(self):
        """Requirement 12: QTimer interval overflow protection (signed 32-bit max: 2,147,483,647 ms)."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "timer.db")
            config_path = os.path.join(tmp, "app_config.json")
            with patch.object(database, "CONFIG_FILE", config_path):
                db = DatabaseManager(db_path)
                window = MainWindow(db, active_employee=None)
                try:
                    # Set huge backup interval (e.g. 100,000,000 minutes)
                    window.sp_bk_interval.setValue(100_000_000)
                    window._restart_backup_timer()

                    # Timer interval must not exceed 2,147,483,647 ms
                    self.assertLessEqual(window.backup_timer.interval(), 2_147_483_647)
                    self.assertTrue(window.backup_timer.isActive())
                finally:
                    window.close()
                    # On close, timers are stopped
                    self.assertFalse(window.backup_timer.isActive())
                    self.assertFalse(window.clock_timer.isActive())

    def test_settings_rollback_discards_and_collapses_all(self):
        """Requirement 10: Cancel button discards changes, collapses all sections, and switches to Dashboard."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "cancel_set.db")
            config_path = os.path.join(tmp, "app_config.json")
            with patch.object(database, "CONFIG_FILE", config_path):
                db = DatabaseManager(db_path)
                window = MainWindow(db, active_employee=None)
                try:
                    # Go to settings tab
                    window.tabs.setCurrentIndex(window._settings_tab_index)

                    # Expand first collapsible section
                    sections = window.findChildren(CollapsibleSection)
                    self.assertGreater(len(sections), 0)
                    sections[0].expand()
                    self.assertTrue(sections[0].is_expanded())

                    # Change profit value
                    original_profit = window.sp_set_profit.value()
                    window.sp_set_profit.setValue(original_profit + 15)

                    # Click cancel
                    window._rollback_settings()

                    # Profit reset
                    self.assertEqual(window.sp_set_profit.value(), original_profit)

                    # Switched to Dashboard (index 0)
                    self.assertEqual(window.tabs.currentIndex(), 0)

                    # All collapsible sections collapsed
                    for s in sections:
                        self.assertFalse(s.is_expanded(), "Section should be collapsed on rollback")
                finally:
                    window.close()

    def test_excel_report_export_custom_reports_and_toggle(self):
        """Requirement 8: Full-row click toggle and custom report profile management."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "report_export.db")
            config_path = os.path.join(tmp, "app_config.json")
            with patch.object(database, "CONFIG_FILE", config_path):
                db = DatabaseManager(db_path)
                window = MainWindow(db, active_employee=None)
                try:
                    # Test item click toggle
                    report_name = window.cb_report_export_type.itemText(0) or "۱. گزارش کامل تمام فروش‌ها"
                    window._load_report_export_columns_ui(report_name)
                    self.assertGreater(window.lst_report_export_columns.count(), 0)
                    item = window.lst_report_export_columns.item(0)
                    initial_state = item.checkState()
                    window._toggle_report_export_col_item(item)
                    self.assertNotEqual(item.checkState(), initial_state)

                    # Test adding custom report profile
                    with patch("PySide6.QtWidgets.QInputDialog.getText", return_value=("گزارش ویژه مالی", True)):
                        window._add_custom_report_profile()

                    self.assertIn("گزارش ویژه مالی", REPORT_AVAILABLE_COLUMNS)
                    items = [window.cb_report_export_type.itemText(i) for i in range(window.cb_report_export_type.count())]
                    self.assertIn("گزارش ویژه مالی", items)

                    # Test renaming custom report profile
                    with patch("PySide6.QtWidgets.QInputDialog.getText", return_value=("گزارش ویژه مدیران", True)):
                        window._rename_custom_report_profile()

                    self.assertIn("گزارش ویژه مدیران", REPORT_AVAILABLE_COLUMNS)
                    self.assertNotIn("گزارش ویژه مالی", REPORT_AVAILABLE_COLUMNS)

                    # Test deleting custom report profile
                    window._delete_custom_report_profile()
                    self.assertNotIn("گزارش ویژه مدیران", REPORT_AVAILABLE_COLUMNS)
                finally:
                    window.close()

    def test_product_management_three_visual_cards_layout(self):
        """Requirement 9: Product Management redesigned with 3 visual cards."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "prod_cards.db")
            config_path = os.path.join(tmp, "app_config.json")
            with patch.object(database, "CONFIG_FILE", config_path):
                db = DatabaseManager(db_path)
                window = MainWindow(db, active_employee=None)
                try:
                    # Verify 3 card group boxes exist
                    self.assertTrue(hasattr(window, "gb_prod_identity"))
                    self.assertTrue(hasattr(window, "gb_prod_specs"))
                    self.assertTrue(hasattr(window, "gb_prod_inventory"))

                    self.assertIn("هویت", window.gb_prod_identity.title())
                    self.assertIn("مشخصات فنی", window.gb_prod_specs.title())
                    self.assertIn("انبارداری", window.gb_prod_inventory.title())

                    # Verify scroll area for dynamic specs
                    self.assertTrue(hasattr(window, "specs_scroll"))
                    self.assertTrue(window.specs_scroll.widgetResizable())
                finally:
                    window.close()


if __name__ == "__main__":
    unittest.main()
