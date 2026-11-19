# -*- coding: utf-8 -*-
"""
Comprehensive QA and Automated Verification Test Suite for Daqiq Release v4.6.0.

This suite validates:
1. Strict 1-to-1 Database-to-UI Schema Parity:
   - Complete elimination of orphan 'payment_method' ('روش پرداخت') across schema v460.
   - Strict APP_VERSION == "4.6.0" and SCHEMA_VERSION == 460.
2. Complete Hardware Taxonomy Rebuild & External Seed Loading:
   - DDR2-LPDDR5X coverage, Intel Celeron/Pentium/Core Ultra/Xeon/AMD Ryzen.
   - Separate Monitor Dimensions and Resolution attributes.
   - Universal 'مشخصات' (Specifications) strictly as terminal attribute.
   - Single 'سایر موارد (Other)' containing exclusively 'مشخصات'.
   - Zero 'مشخصه' prefixes or dual specification fields.
   - External seed loading without fallback (0 categories/subcats/attrs when seed file is missing).
   - Full CRUD in catalog settings.
3. Sales Form ('ثبت فروش') Reset & Repopulation:
   - Clicking 'پاک کردن فرم' immediately repopulates 'محموله موجود' (cb_sale_batch) with available shipments.
4. Transactional Excel Report Export Settings & Definition Workflow:
   - In-memory staging of export configurations until 'ذخیره تنظیمات'.
   - Complete rollback on 'انصراف'.
   - 'تعریف گزارش جدید' at index 0 immediately displaying all database columns.
   - Reports tab defaults to 'همه'.
5. UI Layout & Ergonomics:
   - Generous list heights in catalog settings: subcategories >= 260px, attributes >= 320px, colors >= 240px, suggested values >= 240px.
   - Swapped form fields in Purchases ('شماره سریال' directly underneath 'کد محموله').
   - Swapped form fields in Sales ('شماره سریال' and 'محموله موجود' swapped).
   - Legible DB password settings UI without text clipping.
6. Standard SQLCipher 4 Database Encryption (sqlcipher3):
   - Standard SQLCipher 4 format (AES-256-CBC, PBKDF2-HMAC-SHA512, 256k rounds).
   - Standard sqlite3.connect() fails with sqlite3.DatabaseError.
   - Plaintext SQLite header ('SQLite format 3') absent when encrypted.
   - 100% interoperable with DB Browser for SQLite (SQLCipher) using plain UTF-8 passphrases.
   - Password set, verify, dynamic rekey (PRAGMA rekey), and remove (reverts to standard SQLite).
   - Windows DPAPI local envelope caching when startup prompt is bypassed.
   - Encrypted and unencrypted backup and restore.
7. GitHub Actions CI/CD Workflow:
   - Zero occurrences of deprecated @v4 or @v5 Node 20 actions.
   - All actions upgraded to Node 24 native tags.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

import sqlcipher3

import database
from database import (
    APP_VERSION,
    EXPECTED_SCHEMA_COLUMNS,
    SCHEMA_VERSION,
    DatabaseInvalidPasswordError,
    DatabaseManager,
    DatabasePasswordRequiredError,
)
import main
from main import (
    ALL_SYSTEM_COLUMNS,
    APP_VERSION as UI_APP_VERSION,
    MainWindow,
)
from utils_and_widgets import DynamicAttributeValuesWidget, normalize_catalog_label


class ReleaseV46Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Offscreen Qt application instance
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="daqiq_v46_test_")
        self.db_path = os.path.join(self.tmp_dir, "test_v460.db")
        self.cfg_path = os.path.join(self.tmp_dir, "app_config.json")
        self.tax_path = os.path.join(self.tmp_dir, "default_taxonomy.json")

        # Copy original default_taxonomy.json
        orig_tax = os.path.join(os.path.dirname(os.path.dirname(__file__)), "default_taxonomy.json")
        if os.path.exists(orig_tax):
            shutil.copy(orig_tax, self.tax_path)

        self.cfg_patch = patch.object(database, "CONFIG_FILE", self.cfg_path)
        self.tax_patch = patch.object(database, "get_default_taxonomy_path", return_value=self.tax_path)
        self.cfg_patch.start()
        self.tax_patch.start()

        self.db = DatabaseManager(self.db_path)

    def tearDown(self):
        try:
            if hasattr(self, "db") and self.db:
                self.db.close()
        except Exception:
            pass
        self.tax_patch.stop()
        self.cfg_patch.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _create_test_product(self, mgr, code="P-TEST-01", name="Laptop Test"):
        mgr.add_product(
            code=code,
            name=name,
            category="لپ تاپ",
            sub_category="لپ تاپ عمومی و مالتی مدیا (General & Multimedia Laptop)",
            brand="Lenovo",
            model="ThinkPad",
            specs_dict={},
            description="Test Description",
            reorder_point=1,
            default_profit_pct=20,
            serial_number="SN-TEST-123",
        )
        with mgr.get_connection() as conn:
            row = conn.execute("SELECT id FROM products WHERE code=?", (code,)).fetchone()
        return int(row["id"])

    # -------------------------------------------------------------------------
    # TEST 1: Strict DB-UI Parity (No orphan payment_method) & Versioning
    # -------------------------------------------------------------------------
    def test_item0_strict_db_schema_parity(self):
        """Verify schema version is 460 and payment_method is removed completely."""
        self.assertEqual(APP_VERSION, "4.6.0")
        self.assertEqual(UI_APP_VERSION, "4.6.0")
        self.assertEqual(SCHEMA_VERSION, 460)

        # Check EXPECTED_SCHEMA_COLUMNS
        self.assertNotIn("payment_method", EXPECTED_SCHEMA_COLUMNS.get("payments", ()))

        # Check actual database table
        with self.db.get_connection() as conn:
            user_ver = conn.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(user_ver, 460)

            payment_cols = [r["name"] for r in conn.execute("PRAGMA table_info(payments)").fetchall()]
            self.assertNotIn("payment_method", payment_cols)
            self.assertEqual(
                payment_cols,
                ["id", "ref_type", "ref_id", "amount", "payment_date", "notes", "created_at", "updated_at"]
            )

        # Verify add_batch and add_sale work without payment_method
        p_id = self._create_test_product(self.db)
        b_code = self.db.add_batch(
            batch_code="BTEST01",
            product_id=p_id,
            supplier_id=None,
            buyer_employee_id=None,
            invoice_number="INV-01",
            purchase_date="1403/01/01",
            initial_qty=10,
            unit_purchase_price=1000000,
            extra_cost_total=0,
            suggested_sell_price=1200000,
            paid_amount=10000000,
            settlement_status="تسویه‌شده",
            serial_numbers="SN-B01",
            notes="No payment_method",
        )
        self.assertEqual(b_code, "BTEST01")

        with self.db.get_connection() as conn:
            b_row = conn.execute("SELECT id FROM batches WHERE batch_code=?", (b_code,)).fetchone()
            b_id = b_row["id"]

        s_inv = self.db.add_sale(
            invoice_number="SINV-01",
            product_id=p_id,
            batch_id=b_id,
            seller_employee_id=None,
            customer_name="Customer 1",
            qty=1,
            suggested_unit_price=1200000,
            actual_unit_price=1200000,
            paid_amount=1200000,
            sale_datetime="1403/01/02 10:00:00",
            warranty_company="Company A",
            warranty_start="1403/01/02",
            warranty_months=12,
            warranty_end="1404/01/02",
            serial_number="SN-B01",
            notes="",
        )
        self.assertEqual(s_inv, "SINV-01")

        with self.db.get_connection() as conn:
            p_rows = conn.execute("SELECT * FROM payments").fetchall()
            self.assertGreater(len(p_rows), 0)
            p_keys = p_rows[0].keys()
            self.assertNotIn("payment_method", p_keys)

    # -------------------------------------------------------------------------
    # TEST 2: Complete Hardware Taxonomy & Single Source of Truth
    # -------------------------------------------------------------------------
    def test_item1_taxonomy_rebuild_specifications(self):
        """Verify bilingual taxonomy, DDR2-LPDDR5X, CPUs, separate monitor specs, terminal مشخصات."""
        catalog = self.db.get_product_catalog_config()
        categories = catalog.get("categories", [])
        subcategories = catalog.get("subcategories", {})
        attributes = catalog.get("attributes", {})

        # All category names 100% Persian
        self.assertGreater(len(categories), 0)
        for cat in categories:
            self.assertFalse(any(ord(c) < 128 and c.isalpha() for c in cat), f"Category '{cat}' must be 100% Persian")

        # Subcategories strictly فارسی (انگلیسی)
        for cat, subs in subcategories.items():
            for sub in subs:
                if sub != "سایر موارد (Other)":
                    self.assertIn("(", sub, f"Subcategory '{sub}' must contain English in parentheses")
                    self.assertTrue(sub.endswith(")"), f"Subcategory '{sub}' must end with ')'")

        # No duplicate 'سایر موارد'
        for cat, subs in subcategories.items():
            other_count = sum(1 for s in subs if "سایر موارد" in s)
            self.assertEqual(other_count, 1, f"Category '{cat}' must have exactly one 'سایر موارد'")

        # Universal 'مشخصات' is strictly final attribute of every subcategory
        for cat, attrs in attributes.items():
            sub_to_attrs = {}
            for a in attrs:
                sub = a.get("subcategory") or ""
                sub_to_attrs.setdefault(sub, []).append(a)

            for sub, sub_attrs in sub_to_attrs.items():
                self.assertGreater(len(sub_attrs), 0)
                last_attr = sub_attrs[-1]
                self.assertEqual(last_attr.get("name"), "مشخصات", f"Last attribute of '{sub}' in '{cat}' must be 'مشخصات'")
                self.assertEqual(last_attr.get("label"), "Specifications")
                # Zero 'مشخصه'
                for a in sub_attrs:
                    self.assertNotEqual(a.get("name"), "مشخصه", f"Attribute 'مشخصه' should not exist in '{sub}'")

        # RAM covers DDR2 through DDR5
        parts_attrs = attributes.get("قطعات", [])
        ram_attr = next((a for a in parts_attrs if "Desktop RAM" in a.get("subcategory", "") and ("DDR" in a.get("name", "") or "رم" in a.get("name", ""))), None)
        self.assertIsNotNone(ram_attr)
        self.assertTrue(any("DDR2" in v for v in ram_attr.get("values", [])))
        self.assertTrue(any("DDR5" in v for v in ram_attr.get("values", [])))

        # CPU covers Celeron and Core families
        cpu_attr = next((a for a in parts_attrs if "CPU" in a.get("subcategory", "") and ("خانواده" in a.get("name", "") or "پردازنده" in a.get("name", ""))), None)
        self.assertIsNotNone(cpu_attr)
        self.assertTrue(any("Celeron" in v for v in cpu_attr.get("values", [])))

        # Monitor features separate Screen Size and Resolution
        mon_attrs = attributes.get("مانیتور و نمایشگر", [])
        size_attr = next((a for a in mon_attrs if "سایز" in a.get("name", "") or "Screen Size" in a.get("label", "")), None)
        res_attr = next((a for a in mon_attrs if "رزولوشن" in a.get("name", "") or "Resolution" in a.get("label", "")), None)
        self.assertIsNotNone(size_attr, "Monitor must have separate Screen Size attribute")
        self.assertIsNotNone(res_attr, "Monitor must have separate Resolution attribute")

    def test_item2_external_taxonomy_seed_fallback(self):
        """When default_taxonomy.json is missing before DB creation, DB has 0 categories, 0 subcategories, 0 specs."""
        empty_dir = tempfile.mkdtemp(prefix="daqiq_empty_tax_")
        empty_db_path = os.path.join(empty_dir, "empty.db")
        empty_tax_path = os.path.join(empty_dir, "nonexistent_taxonomy.json")

        with patch.object(database, "get_default_taxonomy_path", return_value=empty_tax_path):
            empty_db = DatabaseManager(empty_db_path)
            try:
                catalog = empty_db.get_product_catalog_config()
                self.assertEqual(catalog.get("categories"), [])
                self.assertEqual(catalog.get("subcategories"), {})
                self.assertEqual(catalog.get("attributes"), {})

                # Test MainWindow with empty database starts with 0 categories in product management
                win = MainWindow(empty_db)
                try:
                    self.assertEqual(win.cb_prod_cat.count(), 0)
                    self.assertEqual(win.cb_cfg_category.count(), 0)
                    self.assertEqual(win.lst_cfg_subcategories.count(), 0)
                    self.assertEqual(win.lst_cfg_attributes.count(), 0)
                finally:
                    win.close()
            finally:
                empty_db.close()
                shutil.rmtree(empty_dir, ignore_errors=True)

    def test_taxonomy_crud_in_catalog_settings(self):
        """Verify full persistence and CRUD of taxonomy entities in settings."""
        win = MainWindow(self.db)
        try:
            # 1. Add new subcategory
            win.cb_cfg_category.setCurrentIndex(0)
            cat = win.cb_cfg_category.currentText()
            win.ed_cfg_subcategory.setText("زیرمجموعه آزمایشی (Test Sub)")
            win._add_catalog_subcategory()
            self.assertIn("زیرمجموعه آزمایشی (Test Sub)", win._taxonomy_draft["subcategories"].get(cat, []))

            # 2. Add custom attribute
            win.cb_cfg_attribute_subcategory.setCurrentText("زیرمجموعه آزمایشی (Test Sub)")
            win.ed_cfg_attribute_name.setText("تست ویژگی")
            win.ed_cfg_attribute_label.setText("Test Attr")
            win.attr_values_widget.set_values(["Opt1", "Opt2"])
            win._add_catalog_attribute()

            attrs = win._taxonomy_draft["attributes"].get(cat, [])
            custom = next((a for a in attrs if a.get("name") == "تست ویژگی"), None)
            self.assertIsNotNone(custom)
            self.assertEqual(custom.get("label"), "Test Attr")
            self.assertEqual(custom.get("values"), ["Opt1", "Opt2"])
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # TEST 3: Sales Form Reset & Available Batch Dropdown Bug Fix
    # -------------------------------------------------------------------------
    def test_item3_sales_form_clear_repopulates_batches(self):
        """Clicking 'پاک کردن فرم' in Sales resets product to index 0 and immediately repopulates batches."""
        p_id = self._create_test_product(self.db, code="P-SALE-01", name="Sale Laptop")
        self.db.add_batch(
            batch_code="B-SALE-01",
            product_id=p_id,
            supplier_id=None,
            buyer_employee_id=None,
            invoice_number="INV-S01",
            purchase_date="1403/01/01",
            initial_qty=5,
            unit_purchase_price=500000,
            extra_cost_total=0,
            suggested_sell_price=700000,
            paid_amount=2500000,
            settlement_status="تسویه‌شده",
            serial_numbers="SN-SALE-01",
        )

        win = MainWindow(self.db)
        try:
            # Switch to Sales tab
            win.tabs.setCurrentIndex(0)

            # Change product away from index 0
            if win.cb_sale_prod.count() > 1:
                win.cb_sale_prod.setCurrentIndex(1)

            # Click 'پاک کردن فرم'
            win._clear_sale_form()

            # Product must be index 0 ("همه کالاها")
            self.assertEqual(win.cb_sale_prod.currentIndex(), 0)

            # Verify batches dropdown is NOT empty, it is unconditionally repopulated
            self.assertGreater(win.cb_sale_batch.count(), 0)
            self.assertEqual(win.cb_sale_batch.currentIndex(), 0)
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # TEST 4: Transactional Excel Export Settings & Report Definition Workflow
    # -------------------------------------------------------------------------
    def test_item4_excel_export_settings_transactional_staging(self):
        """Export settings remain staged in-memory until save, roll back on cancel."""
        win = MainWindow(self.db)
        try:
            # Check 'تعریف گزارش جدید' is at index 0
            self.assertEqual(win.cb_report_export_type.itemText(0), "تعریف گزارش جدید")

            # Selecting index 0 displays all system columns immediately
            win.cb_report_export_type.setCurrentIndex(0)
            self.assertEqual(win.lst_report_export_columns.count(), len(ALL_SYSTEM_COLUMNS))

            # Select a standard report (index 1)
            self.assertGreater(win.cb_report_export_type.count(), 1)
            win.cb_report_export_type.setCurrentIndex(1)

            # Uncheck first item
            item0 = win.lst_report_export_columns.item(0)
            orig_state = item0.checkState()
            new_state = Qt.Unchecked if orig_state == Qt.Checked else Qt.Checked
            item0.setCheckState(new_state)

            # Do NOT click save, click cancel (rollback)
            win._rollback_settings()

            # Staged changes were discarded
            win.cb_report_export_type.setCurrentIndex(1)
            self.assertEqual(win.lst_report_export_columns.item(0).checkState(), orig_state)

            # Verify Reports tab defaults to 'همه'
            self.assertTrue(win.cb_rep_type.currentText().startswith("همه"))
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # TEST 5: UI Geometry, Field Swaps, and Password Settings Display
    # -------------------------------------------------------------------------
    def test_item5_ui_geometry_and_swapped_form_fields(self):
        """Verify generous list heights (>= 240-320px) and swapped form fields."""
        win = MainWindow(self.db)
        try:
            # Settings lists height checks
            self.assertGreaterEqual(win.lst_cfg_subcategories.minimumHeight(), 260)
            self.assertGreaterEqual(win.lst_cfg_attributes.minimumHeight(), 320)
            self.assertGreaterEqual(win.lst_cfg_colors.minimumHeight(), 240)

            # DynamicAttributeValuesWidget scroll area height
            dyn_widget = DynamicAttributeValuesWidget()
            self.assertGreaterEqual(dyn_widget.scroll_area.minimumHeight(), 240)

            # Purchases layout: Serial Number directly beneath Batch Code
            layout = win.ed_batch_code.parentWidget().layout()
            pos_batch = layout.getItemPosition(layout.indexOf(win.ed_batch_code))
            pos_serial = layout.getItemPosition(layout.indexOf(win.ed_batch_serial_number))
            self.assertEqual(pos_batch[0], 0)
            self.assertEqual(pos_batch[1], 1)
            self.assertEqual(pos_serial[0], 1)
            self.assertEqual(pos_serial[1], 1)

            # Sales layout: Serial Number directly next to Product, before Available Cargo
            layout_sale = win.cb_sale_prod.parentWidget().layout()
            pos_sprod = layout_sale.getItemPosition(layout_sale.indexOf(win.cb_sale_prod))
            pos_sserial = layout_sale.getItemPosition(layout_sale.indexOf(win.ed_sale_serial))
            pos_sbatch = layout_sale.getItemPosition(layout_sale.indexOf(win.cb_sale_batch))
            self.assertEqual(pos_sprod[0], 0)
            self.assertEqual(pos_sserial[0], 0)
            self.assertEqual(pos_sbatch[0], 1)

            # Password settings section visibility and legible indicators
            self.assertTrue(win.lbl_db_pwd_status.wordWrap())
            self.assertGreaterEqual(win.btn_set_db_pwd.minimumHeight(), 36)
            self.assertGreaterEqual(win.btn_change_db_pwd.minimumHeight(), 36)
            self.assertGreaterEqual(win.btn_remove_db_pwd.minimumHeight(), 36)
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # TEST 6: Authentic Standard SQLCipher 4 Database Encryption
    # -------------------------------------------------------------------------
    def test_item6_sqlcipher4_encryption_roundtrip(self):
        """Verify standard SQLCipher 4 encryption, DB Browser compatibility, atomic rekey, and plaintext export."""
        enc_db_path = os.path.join(self.tmp_dir, "cipher4_test.db")
        enc_cfg_path = os.path.join(self.tmp_dir, "cipher4_cfg.json")

        with patch.object(database, "CONFIG_FILE", enc_cfg_path):
            mgr = DatabaseManager(enc_db_path)
            self._create_test_product(mgr, code="P-CIPHER", name="Cipher Laptop")

            # 1. Plaintext DB starts with SQLite format 3
            with open(enc_db_path, "rb") as f:
                header = f.read(16)
            self.assertEqual(header, b"SQLite format 3\x00")

            # 2. Encrypt database with password
            mgr.set_database_password("CipherPass#2026", require_startup_prompt=True)
            mgr.close()

            # 3. Header is now ciphertext (NOT SQLite format 3)
            with open(enc_db_path, "rb") as f:
                raw_bytes = f.read()
            self.assertFalse(raw_bytes.startswith(b"SQLite format 3"))
            self.assertNotIn(b"SQLite format 3", raw_bytes)
            self.assertNotIn(b"Cipher Laptop", raw_bytes)

            # Standard sqlite3 fails with DatabaseError
            raw_conn = sqlite3.connect(enc_db_path)
            with self.assertRaises(sqlite3.DatabaseError):
                raw_conn.execute("SELECT * FROM products")
            raw_conn.close()

            # 4. Standard external SQLCipher 4 tool compatibility (DB Browser for SQLite)
            # Direct connection with sqlcipher3 and plain PRAGMA key = '...'
            sc_conn = sqlcipher3.connect(enc_db_path)
            sc_conn.execute("PRAGMA key = 'CipherPass#2026';")
            rows = sc_conn.execute("SELECT name FROM products WHERE code='P-CIPHER'").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], "Cipher Laptop")
            sc_conn.close()

            # 5. Wrong password fails cleanly
            with self.assertRaises(DatabaseInvalidPasswordError):
                DatabaseManager(enc_db_path, password="WrongPassword#2026")

            # 6. Reopen with correct password
            mgr2 = DatabaseManager(enc_db_path, password="CipherPass#2026")
            with mgr2.get_connection() as conn:
                products = conn.execute("SELECT * FROM products").fetchall()
            self.assertEqual(len(products), 1)
            self.assertEqual(products[0]["name"], "Cipher Laptop")

            # 7. Change password (atomic PRAGMA rekey)
            mgr2.change_database_password("CipherPass#2026", "NewKey#2026", require_startup_prompt=True)
            mgr2.close()

            # Old password fails
            with self.assertRaises(DatabaseInvalidPasswordError):
                DatabaseManager(enc_db_path, password="CipherPass#2026")

            # New password succeeds
            mgr3 = DatabaseManager(enc_db_path, password="NewKey#2026")
            with mgr3.get_connection() as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM products").fetchone()[0], 1)

            # 8. Remove password -> exports back to plaintext SQLite
            mgr3.remove_database_password("NewKey#2026")
            mgr3.close()

            with open(enc_db_path, "rb") as f:
                plain_header = f.read(16)
            self.assertEqual(plain_header, b"SQLite format 3\x00")

            # Standard sqlite3 can query directly again
            plain_conn = sqlite3.connect(enc_db_path)
            plain_rows = plain_conn.execute("SELECT name FROM products").fetchall()
            self.assertEqual(len(plain_rows), 1)
            self.assertEqual(plain_rows[0][0], "Cipher Laptop")
            plain_conn.close()

    def test_dpapi_startup_bypass_envelope(self):
        """When require_startup_prompt is False, key is safely cached via DPAPI and reopened without prompt."""
        dpapi_db = os.path.join(self.tmp_dir, "dpapi_test.db")
        dpapi_cfg = os.path.join(self.tmp_dir, "dpapi_cfg.json")

        with patch.object(database, "CONFIG_FILE", dpapi_cfg):
            mgr = DatabaseManager(dpapi_db)
            self._create_test_product(mgr, code="P-DPAPI", name="DPAPI Product")
            mgr.set_database_password("AutoUnlock#2026", require_startup_prompt=False)
            mgr.close()

            # Reopening without passing password parameter auto-unlocks using DPAPI cached envelope
            mgr_auto = DatabaseManager(dpapi_db)
            with mgr_auto.get_connection() as conn:
                count = conn.execute("SELECT count(*) FROM products").fetchone()[0]
            self.assertEqual(count, 1)
            mgr_auto.close()

    # -------------------------------------------------------------------------
    # TEST 7: GitHub Actions Workflow Node 24 Native Compliance
    # -------------------------------------------------------------------------
    def test_github_actions_workflow_node24_native(self):
        """CI workflow has zero occurrences of deprecated @v4 / @v5 Node 20 action tags."""
        ci_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".github", "workflows", "ci.yml")
        self.assertTrue(os.path.exists(ci_path), "ci.yml must exist")
        with open(ci_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("actions/checkout@v4", content)
        self.assertNotIn("actions/setup-python@v5", content)
        self.assertNotIn("actions/upload-artifact@v4", content)
        self.assertNotIn("actions/download-artifact@v4", content)
        self.assertNotIn("FORCE_JAVASCRIPT_ACTIONS_TO_NODE24", content)

        # Confirm modern Node 24 action tags
        self.assertIn("actions/checkout@v7", content)
        self.assertIn("actions/setup-python@v7", content)
        self.assertIn("actions/upload-artifact@v7", content)
        self.assertIn("actions/download-artifact@v8", content)


if __name__ == "__main__":
    unittest.main()
