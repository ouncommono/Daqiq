# -*- coding: utf-8 -*-
"""
Comprehensive QA and Automated Verification Test Suite for Daqiq Release v4.7.0.

Validates:
1. Regression Recovery & Strict Scope Control:
   - Purchases tab: Row 0 has batch code (0,1), product (0,3), supplier (0,5);
     Row 1 has serial number (1,1), buyer (1,3), invoice (1,5).
     Serial number is directly beneath batch code.
   - Sales tab: _clear_sale_form preserves batch selection at 0 without unselecting
     with -1, and keeps auto-populated prices and warranty.
2. Clean Taxonomy Seeding Architecture:
   - When default_taxonomy.json is missing, new DB initializes with 0 categories,
     0 subcategories, and 0 attributes.
   - When default_taxonomy.json is present, initializes clean deduplicated taxonomy
     where 'مشخصات' is strictly final attribute and 'سایر موارد (Other)' contains
     only 'مشخصات'.
3. Standard SQLCipher 4 Database Encryption:
   - set_database_password encrypts database with standard SQLCipher 4 defaults.
   - Header is not plaintext 'SQLite format 3', standard sqlite3.connect fails.
   - Direct connection via sqlcipher3 with PRAGMA key = '...' succeeds (DB Browser compatible).
   - change_database_password rekeys database atomically.
   - remove_database_password exports to plaintext SQLite format 3.
   - DPAPI envelope caching for seamless startup when password prompt is disabled.
4. UI Geometry:
   - lst_cfg_subcategories minimum height >= 260px.
   - lst_cfg_attributes minimum height >= 320px.
   - lst_cfg_colors minimum height >= 240px.
5. GitHub Actions CI/CD Workflow:
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
    SCHEMA_VERSION,
    DatabaseInvalidPasswordError,
    DatabaseManager,
    DatabasePasswordRequiredError,
)
import main
from main import (
    APP_VERSION as UI_APP_VERSION,
    MainWindow,
)


class ReleaseV47Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="daqiq_v47_test_")
        self.db_path = os.path.join(self.tmp_dir, "test_v470.db")
        self.cfg_path = os.path.join(self.tmp_dir, "app_config.json")
        self.tax_path = os.path.join(self.tmp_dir, "default_taxonomy.json")

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
    # TEST 1: Version and Schema Consistency
    # -------------------------------------------------------------------------
    def test_version_and_schema_version(self):
        """Release v4.7.0 asserts APP_VERSION == '4.7.0' and SCHEMA_VERSION == 470."""
        self.assertEqual(APP_VERSION, "4.7.0")
        self.assertEqual(UI_APP_VERSION, "4.7.0")
        self.assertEqual(SCHEMA_VERSION, 470)
        with self.db.get_connection() as conn:
            user_ver = conn.execute("PRAGMA user_version").fetchone()[0]
            settings = dict(conn.execute("SELECT key, value FROM settings").fetchall())
        self.assertEqual(user_ver, 470)
        self.assertEqual(settings.get("app_version"), "4.7.0")
        self.assertEqual(settings.get("schema_version"), "470")

    # -------------------------------------------------------------------------
    # TEST 2: Regression Recovery - Purchases Layout & Sales Form Reset
    # -------------------------------------------------------------------------
    def test_purchases_layout_and_field_order(self):
        """Purchases tab: row 0 (0,1 batch_code, 0,3 product, 0,5 supplier);
           row 1 (1,1 serial, 1,3 buyer, 1,5 invoice). Serial is under batch_code."""
        win = MainWindow(self.db)
        try:
            layout = win.ed_batch_code.parentWidget().layout()
            pos_batch = layout.getItemPosition(layout.indexOf(win.ed_batch_code))
            pos_prod = layout.getItemPosition(layout.indexOf(win.cb_batch_prod))
            pos_supp = layout.getItemPosition(layout.indexOf(win.cb_batch_supplier))
            pos_serial = layout.getItemPosition(layout.indexOf(win.ed_batch_serial_number))
            pos_buyer = layout.getItemPosition(layout.indexOf(win.cb_batch_buyer))
            pos_inv = layout.getItemPosition(layout.indexOf(win.ed_batch_inv))

            # Row 0: Batch Code (col 1), Product (col 3), Supplier (col 5)
            self.assertEqual((pos_batch[0], pos_batch[1]), (0, 1))
            self.assertEqual((pos_prod[0], pos_prod[1]), (0, 3))
            self.assertEqual((pos_supp[0], pos_supp[1]), (0, 5))

            # Row 1: Serial (col 1), Buyer (col 3), Invoice (col 5)
            self.assertEqual((pos_serial[0], pos_serial[1]), (1, 1))
            self.assertEqual((pos_buyer[0], pos_buyer[1]), (1, 3))
            self.assertEqual((pos_inv[0], pos_inv[1]), (1, 5))

            # Serial number is directly beneath batch code (col 1, row 1 vs row 0)
            self.assertEqual(pos_serial[1], pos_batch[1])
            self.assertEqual(pos_serial[0], pos_batch[0] + 1)
        finally:
            win.close()

    def test_sales_form_clear_preserves_batch_and_autofill(self):
        """_clear_sale_form resets product to 0 and auto-selects batch at 0, preserving prices."""
        p1 = self._create_test_product(self.db, code="P-CLR-1", name="Product 1")
        p2 = self._create_test_product(self.db, code="P-CLR-2", name="Product 2")
        self.db.add_batch("B-01", p1, None, None, "INV01", "1403/01/01", 5, 1000, 0, 1500, 1000)
        self.db.add_batch("B-02", p2, None, None, "INV02", "1403/01/01", 8, 2000, 0, 2500, 2000)

        win = MainWindow(self.db)
        try:
            # Change to second product
            idx2 = -1
            for i in range(win.cb_sale_prod.count()):
                d = win.cb_sale_prod.itemData(i)
                if isinstance(d, dict) and d.get("id") == p2:
                    idx2 = i
                    break
            self.assertGreaterEqual(idx2, 0)
            win.cb_sale_prod.setCurrentIndex(idx2)

            # Trigger clear
            win._clear_sale_form()

            # Product is reset to index 0
            self.assertEqual(win.cb_sale_prod.currentIndex(), 0)
            # Batch dropdown is auto-selected at 0 (NOT -1)
            self.assertEqual(win.cb_sale_batch.currentIndex(), 0)
            # Price fields are populated, not zeroed
            self.assertGreater(win.pr_sale_actual.get_value(), 0)
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # TEST 3: Clean Taxonomy Seeding
    # -------------------------------------------------------------------------
    def test_missing_taxonomy_file_initializes_empty(self):
        """When default_taxonomy.json is missing, new DB has 0 categories, 0 subcategories, 0 attributes."""
        empty_dir = tempfile.mkdtemp(prefix="daqiq_empty_tax_")
        empty_db_path = os.path.join(empty_dir, "empty_tax.db")
        empty_tax_path = os.path.join(empty_dir, "nonexistent_taxonomy.json")

        with patch.object(database, "get_default_taxonomy_path", return_value=empty_tax_path):
            empty_db = DatabaseManager(empty_db_path)
            try:
                catalog = empty_db.get_product_catalog_config()
                self.assertEqual(catalog.get("categories"), [])
                self.assertEqual(catalog.get("subcategories"), {})
                self.assertEqual(catalog.get("attributes"), {})
            finally:
                empty_db.close()
                shutil.rmtree(empty_dir, ignore_errors=True)

    def test_present_taxonomy_seed_integrity_and_deduplication(self):
        """When default_taxonomy.json is present, taxonomy is clean, deduplicated,
           'مشخصات' is strictly final attribute, and 'سایر موارد (Other)' has only 'مشخصات'."""
        catalog = self.db.get_product_catalog_config()
        self.assertGreater(len(catalog.get("categories", [])), 0)

        attributes = catalog.get("attributes", {})
        subcategories = catalog.get("subcategories", {})

        for cat, defs in attributes.items():
            self.assertIsInstance(defs, list)
            # No duplicate attribute names in the same subcategory
            subcat_attr_names = {}
            for item in defs:
                subcat = item.get("subcategory", "")
                name = item.get("name", "")
                subcat_attr_names.setdefault(subcat, []).append(name)

            for subcat, names in subcat_attr_names.items():
                self.assertEqual(len(names), len(set(names)), f"Duplicates found in {cat} -> {subcat}")
                # 'مشخصات' is strictly the last attribute
                if "مشخصات" in names:
                    self.assertEqual(names[-1], "مشخصات", f"'مشخصات' not last in {cat} -> {subcat}")

            # 'سایر موارد (Other)' has only 'مشخصات'
            for subcat, names in subcat_attr_names.items():
                if "سایر موارد" in subcat or "Other" in subcat:
                    self.assertEqual(names, ["مشخصات"], f"Other subcategory has extra attributes in {cat} -> {subcat}")

    # -------------------------------------------------------------------------
    # TEST 4: Standard SQLCipher 4 Encryption Roundtrip & Rekey
    # -------------------------------------------------------------------------
    def test_sqlcipher4_encryption_roundtrip(self):
        """Verify standard SQLCipher 4 encryption:
           - On-disk file does not have 'SQLite format 3' header.
           - sqlite3.connect fails.
           - sqlcipher3 with PRAGMA key opens it cleanly (DB Browser compatibility).
           - change_database_password rekeys atomically.
           - remove_database_password converts back to plaintext SQLite format 3."""
        enc_db_path = os.path.join(self.tmp_dir, "cipher_test.db")
        enc_cfg_path = os.path.join(self.tmp_dir, "cipher_cfg.json")

        with patch.object(database, "CONFIG_FILE", enc_cfg_path):
            mgr = DatabaseManager(enc_db_path)
            self._create_test_product(mgr, code="P-CIPHER", name="Cipher Laptop")

            # Check initial unencrypted state
            with open(enc_db_path, "rb") as f:
                header = f.read(16)
            self.assertEqual(header, b"SQLite format 3\x00")

            # 1. Set password (standard SQLCipher 4)
            mgr.set_database_password("CipherPass#2026", require_startup_prompt=True)
            mgr.close()

            # 2. Assert disk file is encrypted
            with open(enc_db_path, "rb") as f:
                enc_header = f.read(16)
            self.assertNotEqual(enc_header, b"SQLite format 3\x00")

            # 3. Standard sqlite3 fails
            raw_conn = sqlite3.connect(enc_db_path)
            with self.assertRaises(sqlite3.DatabaseError):
                raw_conn.execute("SELECT * FROM products")
            raw_conn.close()

            # 4. Independent sqlcipher3 connection with PRAGMA key succeeds (DB Browser equivalent)
            sc_conn = sqlcipher3.connect(enc_db_path)
            sc_conn.execute("PRAGMA key = 'CipherPass#2026';")
            rows = sc_conn.execute("SELECT name FROM products WHERE code='P-CIPHER'").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], "Cipher Laptop")
            sc_conn.close()

            # 5. Daqiq reopens cleanly with correct password
            mgr2 = DatabaseManager(enc_db_path, password="CipherPass#2026")
            with mgr2.get_connection() as conn:
                products = conn.execute("SELECT * FROM products").fetchall()
            self.assertEqual(len(products), 1)
            self.assertEqual(products[0]["name"], "Cipher Laptop")

            # 6. Change password (rekey)
            mgr2.change_database_password("CipherPass#2026", "NewKey#2026")
            mgr2.close()

            # Old password fails
            with self.assertRaises(DatabaseInvalidPasswordError):
                DatabaseManager(enc_db_path, password="CipherPass#2026")

            # New password succeeds
            mgr3 = DatabaseManager(enc_db_path, password="NewKey#2026")
            with mgr3.get_connection() as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM products").fetchone()[0], 1)

            # 7. Remove password (export back to plaintext SQLite)
            mgr3.remove_database_password("NewKey#2026")
            mgr3.close()

            # Verify it is now standard plaintext SQLite again
            with open(enc_db_path, "rb") as f:
                plain_header = f.read(16)
            self.assertEqual(plain_header, b"SQLite format 3\x00")

            # Standard sqlite3 can query directly
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

            # Reopening without passing password parameter should auto-unlock using DPAPI cached envelope
            mgr_auto = DatabaseManager(dpapi_db)
            with mgr_auto.get_connection() as conn:
                count = conn.execute("SELECT count(*) FROM products").fetchone()[0]
            self.assertEqual(count, 1)
            mgr_auto.close()

    # -------------------------------------------------------------------------
    # TEST 5: UI Geometry in Catalog Settings
    # -------------------------------------------------------------------------
    def test_catalog_settings_widget_geometry(self):
        """In 'تنظیمات مدیریت کالاها', list widgets have minimum heights:
           lst_cfg_subcategories >= 260px, lst_cfg_attributes >= 320px, lst_cfg_colors >= 240px."""
        win = MainWindow(self.db)
        try:
            self.assertGreaterEqual(win.lst_cfg_subcategories.minimumHeight(), 260)
            self.assertGreaterEqual(win.lst_cfg_attributes.minimumHeight(), 320)
            self.assertGreaterEqual(win.lst_cfg_colors.minimumHeight(), 240)
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # TEST 6: GitHub Actions Workflow Node 24 Compliance
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
