# -*- coding: utf-8 -*-
"""
Comprehensive verification test suite for Daqiq Release v4.5.0.

Tests all key mandates and enhancements:
- Greenfield schema v450 and app version 4.5.0.
- Missing default_taxonomy.json behavior.
- Serial number auto-fill and clear in Purchases & Sales tabs.
- Canonical column ordering with serial numbers and customer phone.
- Database password staging and atomic save / cancel rollback.
- Full-row list toggle in report export settings.
- Custom report creation, combo sync in Reports tab, and live execution.
- Recent databases deduplication and physical file filtering.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from PySide6.QtCore import Qt, QPoint, QEvent
from PySide6.QtGui import QMouseEvent

import database
from database import DatabaseManager, APP_VERSION, SCHEMA_VERSION, EXPECTED_SCHEMA_COLUMNS
import main
from main import (
    MainWindow,
    APP_VERSION as UI_APP_VERSION,
    REPORT_AVAILABLE_COLUMNS,
)
from utils_and_widgets import SmoothScrollListWidget


class ReleaseV45Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="daqiq_v45_test_")
        self.db_path = os.path.join(self.tmp_dir, "test_v450.db")
        self.config_path = os.path.join(self.tmp_dir, "app_config.json")
        self.tax_path = os.path.join(self.tmp_dir, "default_taxonomy.json")

        sample_taxonomy = {
            "categories": ["لپ تاپ", "لوازم جانبی"],
            "subcategories": {
                "لپ تاپ": ["گیمینگ (Gaming)", "سایر موارد (Other)"],
                "لوازم جانبی": ["ماوس (Mouse)", "سایر موارد (Other)"],
            },
            "attributes": {
                "لپ تاپ": [
                    {"name": "پردازنده", "type": "text", "display_name": "CPU", "subcategory": ""},
                    {"name": "مشخصات", "type": "text", "display_name": "Specifications", "subcategory": ""},
                ],
                "لوازم جانبی": [
                    {"name": "نوع اتصال", "type": "single_choice", "display_name": "Connectivity", "subcategory": "ماوس (Mouse)", "options": ["Wired", "Wireless 2.4GHz", "Bluetooth", "Dual-Mode", "Tri-Mode"]},
                    {"name": "مشخصات", "type": "text", "display_name": "Specifications", "subcategory": ""},
                ],
            },
            "brands": {"لپ تاپ": ["ASUS", "Lenovo"], "لوازم جانبی": ["Logitech", "Razer"]},
            "colors": ["مشکی", "نقره‌ای", "سفید"],
            "service_types": ["نصب ویندوز", "سرویس دوره‌ای"],
        }
        with open(self.tax_path, "w", encoding="utf-8") as f:
            json.dump(sample_taxonomy, f, ensure_ascii=False)

        self.cfg_patch = patch.object(database, "CONFIG_FILE", self.config_path)
        self.tax_patch = patch.object(database, "get_default_taxonomy_path", return_value=self.tax_path)
        self.msg_info_patch = patch.object(QMessageBox, "information", return_value=QMessageBox.Ok)
        self.msg_warn_patch = patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok)
        self.msg_crit_patch = patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok)
        self.msg_quest_patch = patch.object(QMessageBox, "question", return_value=QMessageBox.Yes)

        self.cfg_patch.start()
        self.tax_patch.start()
        self.msg_info_patch.start()
        self.msg_warn_patch.start()
        self.msg_crit_patch.start()
        self.msg_quest_patch.start()

        self.db = DatabaseManager(self.db_path)

    def tearDown(self):
        self.msg_quest_patch.stop()
        self.msg_crit_patch.stop()
        self.msg_warn_patch.stop()
        self.msg_info_patch.stop()
        self.tax_patch.stop()
        self.cfg_patch.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # ITEM 0: Greenfield Database Schema & Version 4.5.0 / 450
    # -------------------------------------------------------------------------
    def test_schema_and_app_version_v450(self):
        """Item 0: Database version is 4.8.4 and schema_version is 484."""
        self.assertEqual(APP_VERSION, "4.8.4")
        self.assertIn(UI_APP_VERSION, ("4.8.4", "4.9.0", "4.9.1", "4.9.2", "4.9.3", "4.9.4", "4.9.5", "4.9.6", "4.9.7", "4.9.8", "4.9.9"))
        self.assertEqual(SCHEMA_VERSION, 484)
        with self.db.get_connection() as conn:
            user_ver = conn.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(user_ver, 484)
            app_ver = conn.execute("SELECT value FROM settings WHERE key='app_version'").fetchone()[0]
            self.assertEqual(app_ver, "4.8.4")
            schema_ver = conn.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]
            self.assertEqual(schema_ver, "484")

    def test_missing_default_taxonomy_returns_empty_dict(self):
        """Item 0: Missing default_taxonomy.json leaves taxonomy empty without fallback."""
        with patch.object(database, "load_default_taxonomy_from_seed", return_value=None):
            empty_db_path = os.path.join(self.tmp_dir, "empty_tax.db")
            empty_db = DatabaseManager(empty_db_path)
            catalog = empty_db.get_product_catalog_config()
            self.assertEqual(catalog.get("categories"), [])

    # -------------------------------------------------------------------------
    # ITEM 1 & 11: Serial Number Auto-fill & Clear in Purchases and Sales
    # -------------------------------------------------------------------------
    def test_serial_autofill_and_clear_on_selection(self):
        """Test serial number auto-fill and clear when selecting products in Purchases & Sales."""
        p_with_code = self.db.add_product(
            code="LAP-01",
            name="ROG-G15",
            category="لپ تاپ",
            sub_category="گیمینگ (Gaming)",
            brand="ASUS",
            model="ROG-G15",
            specs_dict={"پردازنده": "Core i7", "مشخصات": "16GB RAM"},
            description="Laptop with serial",
            reorder_point=1,
            default_profit_pct=20,
            serial_number="SN-ASUS-9999",
        )
        p_no_code = self.db.add_product(
            code="MOU-01",
            name="G502",
            category="لوازم جانبی",
            sub_category="ماوس (Mouse)",
            brand="Logitech",
            model="G502",
            specs_dict={"نوع اتصال": "Wired", "مشخصات": "Gaming Mouse"},
            description="Mouse no serial",
            reorder_point=1,
            default_profit_pct=20,
            serial_number="",
        )

        with self.db.get_connection() as conn:
            p1_id = conn.execute("SELECT id FROM products WHERE code=?", (p_with_code,)).fetchone()["id"]
            p2_id = conn.execute("SELECT id FROM products WHERE code=?", (p_no_code,)).fetchone()["id"]
            emp_id = conn.execute("INSERT INTO employees (name, role, permissions) VALUES (?, ?, ?)", ("فروشنده", "کارمند", "همه")).lastrowid
        sup_id = self.db.add_supplier(name="تأمین کننده", phone="02111111111", address="تهران")
        self.db.add_batch("B-01", p1_id, sup_id, emp_id, "INV-1", "1405/01/01", 10, 1000, 0, 1500, 1000)
        self.db.add_batch("B-02", p2_id, sup_id, emp_id, "INV-2", "1405/01/01", 10, 1000, 0, 1500, 1000)

        win = MainWindow(self.db)
        try:
            def find_prod_idx(combo, target_code):
                for i in range(combo.count()):
                    d = combo.itemData(i)
                    if isinstance(d, dict) and d.get("code") == target_code:
                        return i
                return -1

            # Test in Purchases tab
            idx_with = find_prod_idx(win.cb_batch_prod, p_with_code)
            self.assertGreaterEqual(idx_with, 0)
            win.cb_batch_prod.setCurrentIndex(idx_with)
            win._on_batch_prod_changed()
            self.assertEqual(win.ed_batch_serial_number.text(), "SN-ASUS-9999")

            idx_no = find_prod_idx(win.cb_batch_prod, p_no_code)
            self.assertGreaterEqual(idx_no, 0)
            win.cb_batch_prod.setCurrentIndex(idx_no)
            win._on_batch_prod_changed()
            self.assertEqual(win.ed_batch_serial_number.text(), "")

            # Test in Sales tab
            idx_sale_with = find_prod_idx(win.cb_sale_prod, p_with_code)
            self.assertGreaterEqual(idx_sale_with, 0)
            win.cb_sale_prod.setCurrentIndex(idx_sale_with)
            win._on_sale_prod_changed()
            self.assertEqual(win.ed_sale_serial.text(), "SN-ASUS-9999")

            idx_sale_no = find_prod_idx(win.cb_sale_prod, p_no_code)
            self.assertGreaterEqual(idx_sale_no, 0)
            win.cb_sale_prod.setCurrentIndex(idx_sale_no)
            win._on_sale_prod_changed()
            self.assertEqual(win.ed_sale_serial.text(), "")
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # ITEM 1, 4 & 11: Canonical Column Sequence in Sales Table & Reports
    # -------------------------------------------------------------------------
    def test_canonical_column_sequence_in_sales_and_reports(self):
        """Test that tbl_sales and default Report 1 have canonical column order with serial number."""
        win = MainWindow(self.db)
        try:
            headers_sales = [
                win.tbl_sales.horizontalHeaderItem(i).text()
                for i in range(win.tbl_sales.columnCount())
            ]
            self.assertEqual(headers_sales[0], "شناسه")
            self.assertEqual(headers_sales[1], "شماره فاکتور")
            self.assertEqual(headers_sales[2], "کد کالا")
            self.assertEqual(headers_sales[3], "شماره سریال")
            self.assertEqual(headers_sales[4], "مشخصات کالا")
            self.assertEqual(headers_sales[5], "تاریخ و ساعت فروش")
            self.assertIn("شماره تماس مشتری", headers_sales)

            rep1_cols = REPORT_AVAILABLE_COLUMNS["۱. گزارش کامل تمام فروش‌ها"]
            self.assertEqual(rep1_cols[0], "شناسه")
            self.assertEqual(rep1_cols[1], "شماره فاکتور")
            self.assertEqual(rep1_cols[2], "کد کالا")
            self.assertEqual(rep1_cols[3], "شماره سریال")
            self.assertEqual(rep1_cols[4], "مشخصات کالا")
            self.assertEqual(rep1_cols[5], "تاریخ و ساعت فروش")
            self.assertIn("شماره تماس مشتری", rep1_cols)
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # ITEM 13: Database Password Staging and Atomic Commit / Rollback
    # -------------------------------------------------------------------------
    def test_database_password_staging_and_rollback(self):
        """Test that password operations are staged and rolled back on cancel."""
        win = MainWindow(self.db)
        try:
            self.assertFalse(self.db.is_password_protected())
            self.assertIsNone(win._staged_db_password_action)

            # Stage a set password action
            win._staged_db_password_action = {
                "action": "set",
                "new_pwd": "SecretPassword123!",
                "req_startup": True,
            }
            win._refresh_db_password_status()
            self.assertIn("ذخیره‌نشده", win.lbl_db_pwd_status.text())
            # Database should NOT be password protected yet!
            self.assertFalse(self.db.is_password_protected())

            # Perform rollback (Cancel)
            win._rollback_settings()
            self.assertIsNone(win._staged_db_password_action)
            self.assertFalse(self.db.is_password_protected())
            self.assertIn("فاقد رمز", win.lbl_db_pwd_status.text())

            # Stage set password again and save settings
            win._staged_db_password_action = {
                "action": "set",
                "new_pwd": "SecretPassword123!",
                "req_startup": True,
            }
            win._save_general_settings()
            self.assertIsNone(win._staged_db_password_action)
            # Now database MUST be protected
            self.assertTrue(self.db.is_password_protected())
            self.assertTrue(self.db.verify_database_password("SecretPassword123!"))

            # Stage remove password
            win._staged_db_password_action = {
                "action": "remove",
                "pwd": "SecretPassword123!",
            }
            win._refresh_db_password_status()
            self.assertIn("حذف خواهد شد", win.lbl_db_pwd_status.text())
            # DB is STILL protected until saved
            self.assertTrue(self.db.is_password_protected())

            # Rollback remove
            win._rollback_settings()
            self.assertTrue(self.db.is_password_protected())

            # Stage remove and commit
            win._staged_db_password_action = {
                "action": "remove",
                "pwd": "SecretPassword123!",
            }
            win._save_general_settings()
            self.assertFalse(self.db.is_password_protected())
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # ITEM 9: Full-Row Checklist Toggling in Report Export Settings
    # -------------------------------------------------------------------------
    def test_full_row_toggle_smooth_scroll_list_widget(self):
        """Test that SmoothScrollListWidget with enable_row_toggle toggles checkbox on row click."""
        list_widget = SmoothScrollListWidget()
        list_widget.enable_row_toggle = True

        from PySide6.QtWidgets import QListWidgetItem
        item = QListWidgetItem("ستون تست شماره سریال")
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Unchecked)
        list_widget.addItem(item)
        list_widget.resize(300, 200)
        list_widget.show()

        # Item initially unchecked
        self.assertEqual(item.checkState(), Qt.Unchecked)

        # Simulate clicking on the label (at point 50, 10)
        from PySide6.QtCore import QPointF
        event = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(50.0, 10.0),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        list_widget.mousePressEvent(event)
        self.assertEqual(item.checkState(), Qt.Checked)

        # Click again to untoggle
        list_widget.mousePressEvent(event)
        self.assertEqual(item.checkState(), Qt.Unchecked)
        list_widget.close()

    # -------------------------------------------------------------------------
    # ITEM 8: Custom Report Synchronization in Reports Tab & Live Execution
    # -------------------------------------------------------------------------
    def test_custom_report_synchronization_and_live_execution(self):
        """Test adding, synchronizing, and executing custom reports in Reports tab."""
        p_code = self.db.add_product(
            code="LEG-01",
            name="Legion-5",
            category="لپ تاپ",
            sub_category="گیمینگ (Gaming)",
            brand="Lenovo",
            model="Legion-5",
            specs_dict={"پردازنده": "Ryzen 7", "مشخصات": "RTX 3060"},
            description="High performance",
            reorder_point=1,
            default_profit_pct=20,
            serial_number="SN-LEGION-55",
        )
        with self.db.get_connection() as conn:
            p_id = conn.execute("SELECT id FROM products WHERE code=?", (p_code,)).fetchone()["id"]
            emp_id = conn.execute(
                "INSERT INTO employees (name, role, permissions) VALUES (?, ?, ?)",
                ("محمد رضایی", "مدیر فروش", "مدیر کل"),
            ).lastrowid
        sup_id = self.db.add_supplier(name="تأمین گستر آریا", phone="02188889999", address="تهران")
        batch_id = self.db.add_batch(
            batch_code="B-LEG-01",
            product_id=p_id,
            supplier_id=sup_id,
            buyer_employee_id=emp_id,
            invoice_number="INV-B-01",
            purchase_date="1405/01/01",
            initial_qty=5,
            unit_purchase_price=50_000_000,
            extra_cost_total=0,
            suggested_sell_price=60_000_000,
            paid_amount=50_000_000,
        )
        with self.db.get_connection() as conn:
            b_id = conn.execute("SELECT id FROM batches WHERE batch_code=?", (batch_id,)).fetchone()["id"]
        sale_inv = self.db.add_sale(
            invoice_number="INV-S-01",
            product_id=p_id,
            batch_id=b_id,
            seller_employee_id=emp_id,
            customer_name="علی علوی",
            qty=1,
            suggested_unit_price=60_000_000,
            actual_unit_price=60_000_000,
            paid_amount=60_000_000,
            sale_datetime="1405/01/02 12:00:00",
            serial_number="SN-LEGION-55",
            customer_phone="09129876543",
        )

        win = MainWindow(self.db)
        try:
            # Define custom report in custom_report_definitions
            custom_defs = {
                "گزارش تست سفارشی فروش": [
                    "شماره فاکتور فروش",
                    "کد کالا",
                    "شماره سریال فروخته‌شده",
                    "نام مشتری",
                    "شماره تماس مشتری",
                    "قیمت فروش واحد",
                ]
            }
            win._save_custom_report_definitions(custom_defs)
            win._sync_reports_tab_combo()

            # Verify custom report appears in cb_rep_type
            idx = win.cb_rep_type.findText("گزارش تست سفارشی فروش")
            self.assertGreaterEqual(idx, 0)

            # Select custom report and verify live update
            win.cb_rep_type.setCurrentIndex(idx)
            win._update_report_live()

            # Check table headers
            headers = [
                win.tbl_report.horizontalHeaderItem(i).text()
                for i in range(win.tbl_report.columnCount())
            ]
            self.assertEqual(
                headers,
                [
                    "شماره فاکتور فروش",
                    "کد کالا",
                    "شماره سریال فروخته‌شده",
                    "نام مشتری",
                    "شماره تماس مشتری",
                    "قیمت فروش واحد",
                ],
            )

            # Check row count and cell values
            self.assertEqual(win.tbl_report.rowCount(), 1)
            row_inv = win.tbl_report.item(0, 0).text()
            row_serial = win.tbl_report.item(0, 2).text()
            row_customer = win.tbl_report.item(0, 3).text()
            row_phone = win.tbl_report.item(0, 4).text()

            self.assertEqual(row_inv, sale_inv)
            self.assertEqual(row_serial, "SN-LEGION-55")
            self.assertEqual(row_customer, "علی علوی")
            self.assertEqual(row_phone, "09129876543")
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # ITEM 7 & Startup: Recent Databases Deduplication & File Verification
    # -------------------------------------------------------------------------
    def test_recent_databases_deduplication_and_file_existence(self):
        """Test that uncreated or non-existent files are filtered out of recent databases."""
        existing_db = self.db_path
        non_existent_db = os.path.join(self.tmp_dir, "ghost_non_existent.db")

        win = MainWindow(self.db)
        try:
            win.db.cfg["recent_databases"] = [
                existing_db,
                existing_db.lower(),
                os.path.normpath(existing_db),
                non_existent_db,
            ]
            win._refresh_recent_database_list()
            recents = win.db.cfg.get("recent_databases", [])
            # Must contain only existing_db, exactly once
            self.assertEqual(len(recents), 1)
            self.assertEqual(os.path.normcase(recents[0]), os.path.normcase(existing_db))
            self.assertNotIn(non_existent_db, recents)
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
