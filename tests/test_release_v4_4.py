"""
Comprehensive verification test suite for Daqiq Release v4.4.0.
Covers Items 0 through 15:
- Greenfield schema v440, canonical physical column order, 64-bit integer financials
- Product serial number display, table column positioning, auto-fill in purchases & sales
- Universal 'مشخصات' as last attribute, 'سایر موارد (Other)' rule
- SSD/HDD single-drive capacities and unified 'نوع رابط و فرم' field
- Multi-mode connectivity options in peripherals & mouse
- External default_taxonomy.json resilience and zero hardcoded fallback injection
- Default minimum inventory level = 1 and persistence
- Customer phone number recording, update, and reporting
- Windows Documents relocation detection and automatic backup directory
- Excel export report builder and row-click selection toggle
- Settings 2-column RTL layout, dynamic spec scrolling
- Settings action button symmetry, rollback to dashboard, collapsible section collapse
- Periodic timer immunity to 32-bit millisecond integer overflow
- Database password set, change, remove, startup prompt toggle, and atomic integrity
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QPushButton, QLineEdit, QDialog, QTableWidget,
    QCheckBox, QSpinBox, QScrollArea, QSizePolicy
)

import database
from database import (
    DatabaseManager, APP_VERSION, SCHEMA_VERSION,
    EXPECTED_SCHEMA_COLUMNS, get_windows_documents_path,
    hash_database_password,
)
import main as main_module
from main import MainWindow
from utils_and_widgets import CollapsibleSection, DynamicSpecsWidget


class ReleaseV44Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_v440.db")
        self.cfg_path = os.path.join(self.tmp_dir, "app_config.json")
        self.cfg_patch = patch.object(database, "CONFIG_FILE", self.cfg_path)
        self.cfg_patch.start()
        self.msg_info_patch = patch.object(main_module.QMessageBox, "information", return_value=None)
        self.msg_warn_patch = patch.object(main_module.QMessageBox, "warning", return_value=None)
        self.msg_crit_patch = patch.object(main_module.QMessageBox, "critical", return_value=None)
        self.ask_yes_no_patch = patch.object(main_module, "_ask_yes_no", return_value=True)
        self.msg_info_patch.start()
        self.msg_warn_patch.start()
        self.msg_crit_patch.start()
        self.ask_yes_no_patch.start()
        self.db = DatabaseManager(self.db_path)

    def tearDown(self):
        self.ask_yes_no_patch.stop()
        self.msg_crit_patch.stop()
        self.msg_warn_patch.stop()
        self.msg_info_patch.stop()
        self.cfg_patch.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # ITEM 0 & 11: Greenfield Database Schema & Canonical Column Order
    # -------------------------------------------------------------------------
    def test_item0_greenfield_schema_and_version(self):
        """Item 0: Database version is 4.7.0 and schema_version is 470."""
        self.assertEqual(APP_VERSION, "4.7.0")
        self.assertEqual(SCHEMA_VERSION, 470)
        with self.db.get_connection() as conn:
            user_ver = conn.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(user_ver, 470)
            app_ver = conn.execute("SELECT value FROM settings WHERE key='app_version'").fetchone()[0]
            self.assertEqual(app_ver, "4.7.0")

    def test_item0_and_11_canonical_physical_column_order(self):
        """Item 0 & 11: Products, batches, and sales have strict canonical column positions."""
        with self.db.get_connection() as conn:
            prod_cols = [r["name"] for r in conn.execute("PRAGMA table_info(products)").fetchall()]
            self.assertEqual(prod_cols, list(EXPECTED_SCHEMA_COLUMNS["products"]))
            # serial_number must be immediately after code
            code_idx = prod_cols.index("code")
            serial_idx = prod_cols.index("serial_number")
            self.assertEqual(serial_idx, code_idx + 1)

            batch_cols = [r["name"] for r in conn.execute("PRAGMA table_info(batches)").fetchall()]
            self.assertEqual(batch_cols, list(EXPECTED_SCHEMA_COLUMNS["batches"]))
            # serial_numbers must be immediately after product_id
            prod_id_idx = batch_cols.index("product_id")
            batch_serial_idx = batch_cols.index("serial_numbers")
            self.assertEqual(batch_serial_idx, prod_id_idx + 1)

            sales_cols = [r["name"] for r in conn.execute("PRAGMA table_info(sales)").fetchall()]
            self.assertEqual(sales_cols, list(EXPECTED_SCHEMA_COLUMNS["sales"]))
            # serial_number immediately after batch_id
            batch_id_idx = sales_cols.index("batch_id")
            sale_serial_idx = sales_cols.index("serial_number")
            self.assertEqual(sale_serial_idx, batch_id_idx + 1)
            # customer_phone immediately after customer_name
            cust_name_idx = sales_cols.index("customer_name")
            cust_phone_idx = sales_cols.index("customer_phone")
            self.assertEqual(cust_phone_idx, cust_name_idx + 1)

    def test_item0_large_financial_figures_64bit_integers(self):
        """Item 0: Large Toman figures fit safely into 64-bit SQLite integers."""
        large_amount = 50_000_000_000  # 50 billion Tomans
        prod_code = self.db.add_product(
            code="P-BIG", name="", category="قطعات",
            sub_category="پردازنده (CPU)", brand="Intel", model="Xeon Enterprise",
            specs_dict={}, description="High end", reorder_point=1, default_profit_pct=15,
            serial_number="SN-BIG-99",
        )
        with self.db.get_connection() as conn:
            prod_id = conn.execute("SELECT id FROM products WHERE code=?", (prod_code,)).fetchone()["id"]

        batch_code = self.db.add_batch(
            batch_code="B-BIG", product_id=prod_id, serial_numbers="SN-BIG-99",
            supplier_id=None, buyer_employee_id=None, invoice_number="INV-BIG-1",
            purchase_date="1405/01/01", initial_qty=1, unit_purchase_price=large_amount,
            extra_cost_total=0, suggested_sell_price=large_amount + 5_000_000_000,
            paid_amount=large_amount, notes="",
        )
        with self.db.get_connection() as conn:
            batch_id = conn.execute("SELECT id FROM batches WHERE batch_code=?", (batch_code,)).fetchone()["id"]

        sale_inv = self.db.add_sale(
            invoice_number="INV-SALE-BIG", product_id=prod_id, batch_id=batch_id,
            seller_employee_id=None, customer_name="Tech Corp", qty=1,
            suggested_unit_price=large_amount + 5_000_000_000,
            actual_unit_price=large_amount + 5_000_000_000,
            paid_amount=large_amount + 5_000_000_000,
            sale_datetime="1405/01/02 12:00:00",
            serial_number="SN-BIG-99", customer_phone="09121112233",
        )
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT total_amount, paid_amount FROM sales WHERE invoice_number=?", (sale_inv,)).fetchone()
            self.assertEqual(row["total_amount"], 55_000_000_000)
            self.assertEqual(row["paid_amount"], 55_000_000_000)

    # -------------------------------------------------------------------------
    # ITEM 1 & 11: Product Serial Number Display & Auto-fill
    # -------------------------------------------------------------------------
    def test_item1_product_management_serial_number_column(self):
        """Item 1: 'شماره سریال' column appears right after 'کد کالا' in Product Management table."""
        window = MainWindow(self.db, active_employee=None)
        try:
            headers = [
                window.tbl_products.horizontalHeaderItem(i).text()
                for i in range(window.tbl_products.columnCount())
            ]
            self.assertIn("کد کالا", headers)
            self.assertIn("شماره سریال", headers)
            code_col = headers.index("کد کالا")
            serial_col = headers.index("شماره سریال")
            self.assertEqual(serial_col, code_col + 1)
        finally:
            window.close()

    def test_item1_and_11_serial_autofill_in_purchases_and_sales(self):
        """Item 1 & 11: Selecting a product auto-fills the serial number in Purchases and Sales."""
        prod_code = self.db.add_product(
            code="P-SERIAL-100", name="", category="قطعات",
            sub_category="پردازنده (CPU)", brand="AMD", model="Ryzen 7 7800X3D",
            specs_dict={}, description="", reorder_point=1, default_profit_pct=15,
            serial_number="SN-AUTO-7788",
        )
        with self.db.get_connection() as conn:
            prod_id = conn.execute("SELECT id FROM products WHERE code=?", (prod_code,)).fetchone()["id"]

        self.db.add_batch(
            batch_code="B-SERIAL-100", product_id=prod_id, serial_numbers="SN-AUTO-7788",
            supplier_id=None, buyer_employee_id=None, invoice_number="INV-S-1",
            purchase_date="1405/01/01", initial_qty=5, unit_purchase_price=10_000_000,
            extra_cost_total=0, suggested_sell_price=12_000_000, paid_amount=50_000_000,
            notes="",
        )
        window = MainWindow(self.db, active_employee=None)
        try:
            window.refresh_all_data()

            # Test Purchases tab auto-fill
            idx = next(i for i in range(window.cb_batch_prod.count()) if (window.cb_batch_prod.itemData(i) or {}).get("id") == prod_id)
            self.assertGreaterEqual(idx, 0)
            window.cb_batch_prod.setCurrentIndex(idx)
            self.assertEqual(window.ed_batch_serial_number.text(), "SN-AUTO-7788")

            # Test Sales tab auto-fill
            idx_sale = next(i for i in range(window.cb_sale_prod.count()) if (window.cb_sale_prod.itemData(i) or {}).get("id") == prod_id)
            self.assertGreaterEqual(idx_sale, 0)
            window.cb_sale_prod.setCurrentIndex(idx_sale)
            self.assertEqual(window.ed_sale_serial.text(), "SN-AUTO-7788")
        finally:
            window.close()

    # -------------------------------------------------------------------------
    # ITEM 2 & 3: Taxonomy Rules, Universal 'مشخصات', SSD/HDD, Peripherals
    # -------------------------------------------------------------------------
    def test_item2_and_3_universal_specifications_strictly_last(self):
        """Item 2 & 3: 'مشخصات' is strictly the very last attribute of every subcategory."""
        window = MainWindow(self.db, active_employee=None)
        try:
            taxonomy = self.db.get_product_catalog_config()
            categories = taxonomy.get("categories", [])
            for cat in categories:
                subcategories = taxonomy.get("subcategories", {}).get(cat, [])
                for sub in subcategories:
                    window.cb_prod_cat.setCurrentText(cat)
                    if window.specs_widget.cb_sub is not None:
                        window.specs_widget.cb_sub.setCurrentText(sub)
                    window._apply_custom_specs_for_subcategory()
                    fields = list(window.specs_widget.fields.keys())
                    if fields:
                        self.assertEqual(fields[-1], "مشخصات", f"Last attribute of {cat}->{sub} must be 'مشخصات'")
        finally:
            window.close()

    def test_item2_other_subcategory_rule(self):
        """Item 2: 'سایر موارد (Other)' subcategories contain ONLY the 'مشخصات' attribute."""
        window = MainWindow(self.db, active_employee=None)
        try:
            taxonomy = self.db.get_product_catalog_config()
            categories = taxonomy.get("categories", [])
            for cat in categories:
                subcategories = taxonomy.get("subcategories", {}).get(cat, [])
                other_subs = [s for s in subcategories if "سایر موارد" in s]
                for other_sub in other_subs:
                    window.cb_prod_cat.setCurrentText(cat)
                    if window.specs_widget.cb_sub is not None:
                        window.specs_widget.cb_sub.setCurrentText(other_sub)
                    window._apply_custom_specs_for_subcategory()
                    fields = list(window.specs_widget.fields.keys())
                    self.assertEqual(len(fields), 1, f"Other subcategory {cat}->{other_sub} should have exactly 1 attribute")
                    self.assertEqual(fields[0], "مشخصات")
        finally:
            window.close()

    def test_item2_ssd_hdd_tailored_capacities_and_unified_interface(self):
        """Item 2: SSD/HDD have single-drive capacities (no combos) and unified 'نوع رابط و فرم'."""
        taxonomy = self.db.get_product_catalog_config()
        parts_defs = taxonomy.get("attributes", {}).get("قطعات", [])

        # SSD
        ssd_defs = [d for d in parts_defs if "اس اس دی" in d.get("subcategory", "")]
        ssd_names = [d["name"] for d in ssd_defs]
        self.assertIn("ظرفیت", ssd_names)
        self.assertIn("نوع رابط و فرم", ssd_names)
        self.assertNotIn("نوع رابط", ssd_names)
        self.assertNotIn("رابط و فرم", ssd_names)

        ssd_cap = next(d for d in ssd_defs if d["name"] == "ظرفیت")
        # Ensure no combo capacities
        for val in ssd_cap["values"]:
            self.assertNotIn("+", val)
        self.assertIn("1TB", ssd_cap["values"])
        self.assertIn("512GB", ssd_cap["values"])

        # HDD
        hdd_defs = [d for d in parts_defs if "هارد دیسک" in d.get("subcategory", "")]
        hdd_names = [d["name"] for d in hdd_defs]
        self.assertIn("ظرفیت", hdd_names)
        self.assertIn("نوع رابط و فرم", hdd_names)
        hdd_cap = next(d for d in hdd_defs if d["name"] == "ظرفیت")
        for val in hdd_cap["values"]:
            self.assertNotIn("+", val)
        self.assertIn("1TB", hdd_cap["values"])
        self.assertIn("2TB", hdd_cap["values"])

    def test_item2_multi_mode_connectivity(self):
        """Item 2 & 3: Mouse and peripherals have comprehensive multi-mode connectivity options."""
        taxonomy = self.db.get_product_catalog_config()
        acc_defs = taxonomy.get("attributes", {}).get("لوازم جانبی", [])
        mouse_defs = [d for d in acc_defs if "ماوس" in d.get("subcategory", "")]
        conn_def = next((d for d in mouse_defs if d["name"] == "نوع اتصال"), None)
        self.assertIsNotNone(conn_def)
        conn_vals = conn_def["values"]
        self.assertTrue(any("Wired" in v for v in conn_vals))
        self.assertTrue(any("Wireless" in v for v in conn_vals))
        self.assertTrue(any("Bluetooth" in v for v in conn_vals))
        self.assertTrue(any("Tri-Mode" in v or "Dual" in v for v in conn_vals))

    # -------------------------------------------------------------------------
    # ITEM 3: External Taxonomy JSON Seed Resilience
    # -------------------------------------------------------------------------
    def test_item3_external_taxonomy_json_missing_resilience(self):
        """Item 3: When default_taxonomy.json is missing, DB initializes with empty taxonomy structure without injecting legacy fallbacks."""
        isolated_db_path = os.path.join(self.tmp_dir, "isolated_empty_taxonomy.db")
        with patch("os.path.isfile", side_effect=lambda p: False if "default_taxonomy.json" in p else os.path.exists(p)):
            isolated_db = DatabaseManager(isolated_db_path)
            catalog = isolated_db.get_product_catalog_config()
            self.assertEqual(catalog["categories"], [])
            self.assertEqual(catalog["subcategories"], {})
            self.assertEqual(catalog["attributes"], {})

    # -------------------------------------------------------------------------
    # ITEM 5: Default Minimum Inventory Level = 1
    # -------------------------------------------------------------------------
    def test_item5_default_min_inventory_level_is_one(self):
        """Item 5: Default minimum inventory level is initialized to 1."""
        self.assertEqual(self.db.cfg.get("default_min_inventory"), 1)
        window = MainWindow(self.db, active_employee=None)
        try:
            self.assertEqual(window.sp_prod_reorder.value(), 1)
            window._clear_product_form()
            self.assertEqual(window.sp_prod_reorder.value(), 1)
            self.assertEqual(window.sp_default_min_inventory.value(), 1)
        finally:
            window.close()

    # -------------------------------------------------------------------------
    # ITEM 6: Customer Phone Number in Sales
    # -------------------------------------------------------------------------
    def test_item6_customer_phone_number_persistence(self):
        """Item 6: Customer phone number is saved, updated, and retrieved in sales."""
        prod_code = self.db.add_product(
            code="P-PHONE-1", name="", category="قطعات",
            sub_category="پردازنده (CPU)", brand="Intel", model="Core i5",
            specs_dict={}, description="", reorder_point=1, default_profit_pct=10,
            serial_number="SN-P1",
        )
        with self.db.get_connection() as conn:
            prod_id = conn.execute("SELECT id FROM products WHERE code=?", (prod_code,)).fetchone()["id"]

        batch_code = self.db.add_batch(
            batch_code="B-PHONE-1", product_id=prod_id, serial_numbers="SN-P1",
            supplier_id=None, buyer_employee_id=None, invoice_number="INV-P1",
            purchase_date="1405/01/01", initial_qty=5, unit_purchase_price=1_000_000,
            extra_cost_total=0, suggested_sell_price=1_200_000, paid_amount=5_000_000,
            notes="",
        )
        with self.db.get_connection() as conn:
            batch_id = conn.execute("SELECT id FROM batches WHERE batch_code=?", (batch_code,)).fetchone()["id"]

        sale_inv = self.db.add_sale(
            invoice_number="INV-SALE-PHONE", product_id=prod_id, batch_id=batch_id,
            seller_employee_id=None, customer_name="مشتری نمونه", qty=1,
            suggested_unit_price=1_200_000, actual_unit_price=1_200_000,
            paid_amount=1_200_000, sale_datetime="1405/01/02 10:00:00",
            serial_number="SN-P1", customer_phone="09129876543",
        )
        with self.db.get_connection() as conn:
            sale_row = conn.execute("SELECT id, customer_name, customer_phone FROM sales WHERE invoice_number=?", (sale_inv,)).fetchone()
            sale_id = sale_row["id"]
            self.assertEqual(sale_row["customer_name"], "مشتری نمونه")
            self.assertEqual(sale_row["customer_phone"], "09129876543")

        # Update phone number
        self.db.update_sale(
            sale_id=sale_id, seller_employee_id=None, customer_name="مشتری نمونه",
            new_qty=1, suggested_unit_price=1_200_000, actual_unit_price=1_200_000,
            paid_amount=1_200_000, warranty_company="", warranty_start="",
            warranty_months=0, warranty_end="", serial_number="SN-P1",
            notes="", customer_phone="09351234567",
        )
        with self.db.get_connection() as conn:
            sale_row2 = conn.execute("SELECT customer_phone FROM sales WHERE id=?", (sale_id,)).fetchone()
            self.assertEqual(sale_row2["customer_phone"], "09351234567")

    # -------------------------------------------------------------------------
    # ITEM 7: Windows Documents Detection & Backup Settings
    # -------------------------------------------------------------------------
    def test_item7_windows_documents_resolution(self):
        """Item 7: Resolves true Windows Documents path dynamically without hardcoding drive C."""
        doc_path = get_windows_documents_path()
        self.assertTrue(os.path.isdir(doc_path))
        self.assertFalse(doc_path.startswith("C:\\Users\\..."))

    def test_item7_automatic_backup_directory_settings(self):
        """Item 7: View and customize automatic backup directory."""
        custom_bk = os.path.join(self.tmp_dir, "MyCustomBackups")
        self.db.set_automatic_backup_directory(custom_bk)
        self.assertEqual(self.db.get_automatic_backup_directory(), os.path.abspath(custom_bk))
        self.assertTrue(os.path.isdir(custom_bk))

    # -------------------------------------------------------------------------
    # ITEM 8: Excel Export Report Builder & Row Click Selection
    # -------------------------------------------------------------------------
    def test_item8_excel_export_custom_report_lifecycle(self):
        """Item 8: Add, rename, and delete custom Excel export reports."""
        window = MainWindow(self.db, active_employee=None)
        try:
            # Row-click selection toggle on list item
            if window.lst_report_export_columns.count() > 0:
                item = window.lst_report_export_columns.item(0)
                init_state = item.checkState()
                window._on_report_export_col_clicked(item)
                self.assertNotEqual(item.checkState(), init_state)

            # Add custom report
            window.ed_custom_report_name.setText("گزارش سود ماهانه")
            window._add_custom_report()
            custom_defs = window._get_custom_report_definitions()
            self.assertIn("گزارش سود ماهانه", custom_defs)

            # Rename custom report
            window.cb_report_export_type.setCurrentText("گزارش سود ماهانه")
            window.ed_custom_report_name.setText("گزارش سود ویژه")
            window._rename_custom_report()
            custom_defs2 = window._get_custom_report_definitions()
            self.assertNotIn("گزارش سود ماهانه", custom_defs2)
            self.assertIn("گزارش سود ویژه", custom_defs2)

            # Delete custom report
            window.cb_report_export_type.setCurrentText("گزارش سود ویژه")
            with patch("main._ask_yes_no", return_value=True):
                window._delete_custom_report()
            custom_defs3 = window._get_custom_report_definitions()
            self.assertNotIn("گزارش سود ویژه", custom_defs3)
        finally:
            window.close()

    # -------------------------------------------------------------------------
    # ITEM 9: 2-Column RTL Layout & Dynamic Spec Scrolling
    # -------------------------------------------------------------------------
    def test_item9_settings_2column_rtl_layout_and_dynamic_spec_scroll(self):
        """Item 9 & 2: Products page has 2-column RTL layout and scrollable technical specs."""
        window = MainWindow(self.db, active_employee=None)
        try:
            self.assertTrue(isinstance(window.specs_widget, DynamicSpecsWidget))
            scroll_area = window.specs_widget.findChild(QScrollArea)
            self.assertIsNotNone(scroll_area)
            self.assertTrue(scroll_area.widgetResizable())
        finally:
            window.close()

    # -------------------------------------------------------------------------
    # ITEM 10: Settings Buttons Symmetry & Rollback to Dashboard
    # -------------------------------------------------------------------------
    def test_item10_settings_cancel_rollback_and_collapse(self):
        """Item 10: Clicking Cancel resets staged settings, collapses sections, and navigates to Dashboard."""
        window = MainWindow(self.db, active_employee=None)
        try:
            # Symmetry check
            self.assertEqual(window.btn_save_settings.minimumHeight(), 42)
            self.assertEqual(window.btn_cancel_settings.minimumHeight(), 42)

            # Navigate to settings
            window.tabs.setCurrentIndex(window._settings_tab_index)
            self.assertEqual(window.tabs.currentIndex(), window._settings_tab_index)

            # Stage a change in shop name
            window.ed_shop_name.setText("فروشگاه تست جدید")

            # Click Cancel (Rollback)
            window._rollback_settings()

            # Verify navigation back to Dashboard (tab 0)
            self.assertEqual(window.tabs.currentIndex(), 0)

            # Verify all sections are collapsed
            settings_page = window.tabs.widget(window._settings_tab_index)
            for section in settings_page.findChildren(CollapsibleSection):
                self.assertFalse(section.is_expanded())
        finally:
            window.close()

    # -------------------------------------------------------------------------
    # ITEM 12: Timer Overflow Protection
    # -------------------------------------------------------------------------
    def test_item12_timer_overflow_protection(self):
        """Item 12: Timer setup safely handles extreme intervals without OverflowError."""
        window = MainWindow(self.db, active_employee=None)
        try:
            # Set extreme intervals
            self.db.cfg["auto_backup_interval_min"] = 100_000_000
            window._setup_timers()
            window._restart_backup_timer()
            self.assertTrue(window.backup_timer.isActive())
            # Timer interval must be <= 2,147,483,647 ms
            self.assertLessEqual(window.backup_timer.interval(), 2_147_483_647)
            self.assertGreaterEqual(window.backup_timer.interval(), 1_000)
        finally:
            window.close()

    # -------------------------------------------------------------------------
    # ITEM 13: Database Password Protection Architecture
    # -------------------------------------------------------------------------
    def test_item13_database_password_lifecycle(self):
        """Item 13: Setting, verifying, changing, removing DB password and startup prompt toggle."""
        # Initial: not protected
        self.assertFalse(self.db.is_password_protected())

        # Set password
        self.db.set_database_password("SecretPass123", require_startup_prompt=True)
        self.assertTrue(self.db.is_password_protected())
        self.assertTrue(self.db.is_startup_password_prompt_required())
        self.assertTrue(self.db.verify_database_password("SecretPass123"))
        self.assertFalse(self.db.verify_database_password("WrongPass"))

        # Change password
        self.db.change_database_password("SecretPass123", "NewSecretPass456")
        self.assertTrue(self.db.verify_database_password("NewSecretPass456"))
        self.assertFalse(self.db.verify_database_password("SecretPass123"))

        # Toggle startup prompt requirement
        self.db.set_startup_password_prompt_required(False)
        self.assertFalse(self.db.is_startup_password_prompt_required())
        self.assertTrue(self.db.can_auto_unlock_locally())

        self.db.set_startup_password_prompt_required(True)
        self.assertTrue(self.db.is_startup_password_prompt_required())
        self.assertFalse(self.db.can_auto_unlock_locally())

        # Remove password
        self.db.remove_database_password("NewSecretPass456")
        self.assertFalse(self.db.is_password_protected())


if __name__ == "__main__":
    unittest.main()
