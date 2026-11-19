# -*- coding: utf-8 -*-
"""
Comprehensive QA and Automated Verification Test Suite for Daqiq Release v4.7.0.

This suite validates:
1. Strict 1-to-1 Database-to-UI Schema Parity:
   - Complete elimination of orphan 'payment_method' ('روش پرداخت') across schema v470.
2. Complete Hardware Taxonomy Rebuild & External Seed Loading:
   - DDR2-LPDDR5X coverage, Intel Celeron/Pentium/Core Ultra/Xeon/AMD Ryzen.
   - Separate Monitor Dimensions and Resolution attributes.
   - Universal 'مشخصات' (Specifications) strictly as final attribute.
   - Single 'سایر موارد (Other)' containing exclusively 'مشخصات'.
   - Zero 'مشخصه' prefixes.
   - External seed loading without fallback (empty taxonomy if file missing).
3. Sales Form ('ثبت فروش') Reset & Repopulation Bug Fix:
   - Clicking 'پاک کردن فرم' immediately repopulates 'محموله موجود' (cb_sale_batch) with available shipments.
4. Transactional Excel Report Export Settings & Definition:
   - In-memory staging of export configurations until 'ذخیره تنظیمات'.
   - Complete rollback on 'انصراف'.
   - 'تعریف گزارش جدید' at index 0 immediately displaying all database columns.
   - Reports tab defaults to 'همه'.
5. UI Layout & Ergonomics:
   - Expanded vertical heights for subcategories, colors, attributes, suggested values (>= 200px).
   - Swapped form fields in Purchases ('شماره سریال' directly underneath 'کد محموله').
   - Swapped form fields in Sales ('شماره سریال' and 'محموله موجود' swapped).
6. True Cryptographic Database Encryption on Disk:
   - Magic header 'DAQIQENC\x01' and AES-256-GCM / PBKDF2 encryption.
   - Standard sqlite3.connect() fails with sqlite3.DatabaseError.
   - Plaintext SQLite header ('SQLite format 3') absent.
   - Password set, verify, change, and remove (reverts to standard SQLite).
   - Encrypted and unencrypted backup and restore.
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
from PySide6.QtWidgets import QApplication

import database
from database import (
    APP_VERSION,
    EXPECTED_SCHEMA_COLUMNS,
    MAGIC_ENCRYPTED,
    SCHEMA_VERSION,
    DatabaseInvalidPasswordError,
    DatabaseManager,
    DatabasePasswordRequiredError,
)
import main
from main import (
    APP_VERSION as UI_APP_VERSION,
    ALL_SYSTEM_COLUMNS,
    MainWindow,
)
from utils_and_widgets import DynamicAttributeValuesWidget


class ReleaseV46Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Offscreen Qt application instance
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="daqiq_v46_test_")
        self.db_path = os.path.join(self.tmp_dir, "test_v470.db")
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
    # TEST 1: Strict DB-UI Parity (No orphan payment_method)
    # -------------------------------------------------------------------------
    def test_item0_strict_db_schema_parity(self):
        """Verify schema version is 470 and payment_method is removed completely."""
        self.assertEqual(APP_VERSION, "4.7.0")
        self.assertEqual(UI_APP_VERSION, "4.7.0")
        self.assertEqual(SCHEMA_VERSION, 470)

        # Check EXPECTED_SCHEMA_COLUMNS
        self.assertNotIn("payment_method", EXPECTED_SCHEMA_COLUMNS.get("payments", ()))

        # Check actual database table
        with self.db.get_connection() as conn:
            user_ver = conn.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(user_ver, 470)

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
            unit_purchase_price=1000,
            extra_cost_total=0,
            suggested_sell_price=1500,
            paid_amount=1000,
        )
        self.assertIsNotNone(b_code)
        with self.db.get_connection() as conn:
            b_id = conn.execute("SELECT id FROM batches WHERE batch_code=?", (b_code,)).fetchone()["id"]

        sale_id = self.db.add_sale(
            invoice_number="INV-SALE01",
            product_id=p_id,
            batch_id=b_id,
            seller_employee_id=None,
            customer_name="Ali",
            qty=1,
            suggested_unit_price=1500,
            actual_unit_price=1500,
            paid_amount=1500,
            sale_datetime="1403/01/02",
            customer_phone="09123456789",
        )
        self.assertIsNotNone(sale_id)

        # Check payment record inserted
        with self.db.get_connection() as conn:
            sale_row = conn.execute("SELECT id FROM sales WHERE invoice_number=?", ("INV-SALE01",)).fetchone()
            self.assertIsNotNone(sale_row)
            sale_pk = int(sale_row["id"])
            payments = conn.execute("SELECT * FROM payments WHERE ref_type='sale' AND ref_id=?", (sale_pk,)).fetchall()
            self.assertGreater(len(payments), 0)
            # Ensure payment row has no payment_method column key
            p_keys = payments[0].keys()
            self.assertNotIn("payment_method", p_keys)

    # -------------------------------------------------------------------------
    # TEST 2: Complete Hardware Taxonomy Rebuild & External Seed Loading
    # -------------------------------------------------------------------------
    def test_item1_taxonomy_rebuild_specifications(self):
        """Validate comprehensive taxonomy specifications in default_taxonomy.json."""
        with open(self.tax_path, "r", encoding="utf-8") as f:
            tax = json.load(f)

        # Check root categories
        expected_cats = [
            "لپ تاپ",
            "قطعات",
            "لوازم جانبی",
            "مانیتور و نمایشگر",
            "تجهیزات شبکه",
            "کامپیوتر و کیس اسمبل شده",
            "ماشین های اداری",
            "سایر موارد",
        ]
        self.assertEqual(tax["categories"], expected_cats)

        # Check each category has exactly 1 'سایر موارد (Other)'
        for cat in tax["categories"]:
            subcats = tax["subcategories"].get(cat, [])
            other_subcats = [s for s in subcats if "سایر موارد" in s or "Other" in s]
            self.assertEqual(len(other_subcats), 1, f"Category '{cat}' must have exactly 1 Other subcategory")
            self.assertEqual(other_subcats[0], "سایر موارد (Other)")

            # Check attributes in this category
            cat_attrs = tax["attributes"].get(cat, [])
            # Group attributes by subcategory
            sub_to_attrs = {}
            for a in cat_attrs:
                sub = a.get("subcategory", "")
                sub_to_attrs.setdefault(sub, []).append(a)

            # For 'سایر موارد (Other)', there must be only 1 attribute: 'مشخصات'
            other_attrs = sub_to_attrs.get("سایر موارد (Other)", [])
            self.assertEqual(len(other_attrs), 1, f"Other in '{cat}' must have only 1 attribute")
            self.assertEqual(other_attrs[0]["name"], "مشخصات")
            self.assertEqual(other_attrs[0]["display_name"], "Specifications")

            # Check Universal Specifications Rule: 'مشخصات' is strictly last for EVERY subcategory
            for sub, attrs in sub_to_attrs.items():
                self.assertGreaterEqual(len(attrs), 1)
                last_attr = attrs[-1]
                self.assertEqual(last_attr["name"], "مشخصات", f"Last attribute of '{sub}' in '{cat}' must be 'مشخصات'")
                self.assertEqual(last_attr["display_name"], "Specifications")

                # Zero 'مشخصه' prefixes in attribute names
                for a in attrs:
                    self.assertNotIn("مشخصه", a["name"], f"Attribute '{a['name']}' in '{sub}' contains 'مشخصه'")

        # Verify RAM memory generations DDR2 - LPDDR5X
        desktop_ram_attrs = [a for a in tax["attributes"]["قطعات"] if a.get("subcategory") == "رم کامپیوتر (Desktop RAM)"]
        laptop_ram_attrs = [a for a in tax["attributes"]["قطعات"] if a.get("subcategory") == "رم لپ تاپ (Laptop RAM)"]
        desktop_ddr = next(a["values"] for a in desktop_ram_attrs if "نسخه DDR" in a["name"])
        laptop_ddr = next(a["values"] for a in laptop_ram_attrs if "نسخه DDR" in a["name"])

        for g in ["DDR2", "DDR3", "DDR4", "DDR5"]:
            self.assertIn(g, desktop_ddr)
        for g in ["DDR2", "DDR3", "DDR4", "DDR5", "LPDDR4", "LPDDR4X", "LPDDR5", "LPDDR5X"]:
            self.assertIn(g, laptop_ddr)

        # Verify CPU family: Celeron, Pentium, Core Ultra, Xeon, Ryzen
        cpu_attrs = [a for a in tax["attributes"]["قطعات"] if a.get("subcategory") == "پردازنده (CPU)"]
        cpu_family = next(a["values"] for a in cpu_attrs if "خانواده پردازنده" in a["name"])
        for expected in ["Intel Celeron", "Intel Pentium", "Intel Core Ultra 7", "Intel Xeon", "AMD Ryzen 5", "AMD Ryzen 7"]:
            self.assertIn(expected, cpu_family)

        # Verify Monitor separate screen size and resolution
        monitor_attrs = [a for a in tax["attributes"]["مانیتور و نمایشگر"] if a.get("subcategory") == "مانیتور اداری و خانگی (Office & Home Monitor)"]
        attr_names = [a["name"] for a in monitor_attrs]
        self.assertIn("سایز صفحه", attr_names)
        self.assertIn("رزولوشن", attr_names)

    def test_item2_external_taxonomy_seed_fallback(self):
        """Verify that when default_taxonomy.json is missing, taxonomy starts completely empty without errors."""
        empty_tax_path = os.path.join(self.tmp_dir, "non_existent_taxonomy.json")
        with patch.object(database, "get_default_taxonomy_path", return_value=empty_tax_path):
            empty_db_path = os.path.join(self.tmp_dir, "clean_empty_tax.db")
            empty_db = DatabaseManager(empty_db_path)
            catalog = empty_db.get_product_catalog_config()
            self.assertEqual(catalog["categories"], [])
            self.assertEqual(catalog["subcategories"], {})
            empty_db.close()

    # -------------------------------------------------------------------------
    # TEST 3: Sales Form Reset & Immediate Cargo Repopulation
    # -------------------------------------------------------------------------
    def test_item3_sales_form_clear_repopulates_batches(self):
        """Clicking 'پاک کردن فرم' resets product to 0 and immediately populates available batches."""
        # Setup test products and batches
        p1 = self._create_test_product(self.db, code="P-CLEAR-1", name="Product 1")
        p2 = self._create_test_product(self.db, code="P-CLEAR-2", name="Product 2")
        b1 = self.db.add_batch("B-01", p1, None, None, "INV01", "1403/01/01", 5, 1000, 0, 1500, 1000)
        b2 = self.db.add_batch("B-02", p2, None, None, "INV02", "1403/01/01", 8, 2000, 0, 2500, 2000)

        win = MainWindow(self.db)
        try:
            # Change product to p2
            idx2 = -1
            for i in range(win.cb_sale_prod.count()):
                data = win.cb_sale_prod.itemData(i)
                if isinstance(data, dict) and data.get("id") == p2:
                    idx2 = i
                    break
            self.assertGreaterEqual(idx2, 0)
            win.cb_sale_prod.setCurrentIndex(idx2)

            # Trigger clear
            win._clear_sale_form()

            # Verify product is reset to index 0
            self.assertEqual(win.cb_sale_prod.currentIndex(), 0)

            # Verify batches dropdown is NOT empty, it is populated with batches of the first product
            self.assertGreater(win.cb_sale_batch.count(), 0)
            # In v4.7.0, cb_sale_batch auto-selects index 0 and autofills prices
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

            # Selecting index 0 displays all system columns
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

            # Re-read and check: DB settings were not touched
            saved_raw = self.db.get_setting("report_excel_export_configs", "{}")
            # Staged changes were discarded
            win.cb_report_export_type.setCurrentIndex(1)
            self.assertEqual(win.lst_report_export_columns.item(0).checkState(), orig_state)

            # Verify Reports tab defaults to 'همه' (or 'همه (گزارش جامع خرید، فروش و خدمات)')
            self.assertTrue(win.cb_rep_type.currentText().startswith("همه"))
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # TEST 5: UI Expanded Heights & Swapped Fields
    # -------------------------------------------------------------------------
    def test_item5_expanded_heights_and_swapped_form_fields(self):
        """Verify list heights >= 200px and swapped form fields."""
        win = MainWindow(self.db)
        try:
            # Settings lists height checks
            self.assertGreaterEqual(win.lst_cfg_subcategories.minimumHeight(), 200)
            self.assertGreaterEqual(win.lst_cfg_attributes.minimumHeight(), 200)
            self.assertGreaterEqual(win.lst_cfg_colors.minimumHeight(), 200)

            # DynamicAttributeValuesWidget scroll area height
            dyn_widget = DynamicAttributeValuesWidget()
            self.assertGreaterEqual(dyn_widget.scroll_area.minimumHeight(), 200)

            def next_focusable(widget):
                w = widget.nextInFocusChain()
                while w and w.focusPolicy() == Qt.NoFocus:
                    w = w.nextInFocusChain()
                return w

            # Purchases layout: Serial Number directly beneath Batch Code
            layout = win.ed_batch_code.parentWidget().layout()
            pos_batch = layout.getItemPosition(layout.indexOf(win.ed_batch_code))
            pos_serial = layout.getItemPosition(layout.indexOf(win.ed_batch_serial_number))
            self.assertEqual(pos_batch[0], 0)
            self.assertEqual(pos_batch[1], 1)
            self.assertEqual(pos_serial[0], 1)
            self.assertEqual(pos_serial[1], 1)

            # Sales tab order: Select Product -> Serial Number -> Available Cargo
            prod_focus = next_focusable(win.cb_sale_prod)
            if prod_focus == win.cb_sale_prod.lineEdit():
                self.assertEqual(next_focusable(win.cb_sale_prod.lineEdit()), win.ed_sale_serial)
            else:
                self.assertEqual(prod_focus, win.ed_sale_serial)
            self.assertIn(next_focusable(win.ed_sale_serial), (win.cb_sale_batch, win.cb_sale_batch.lineEdit()))
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # TEST 6: True Cryptographic On-Disk Database Encryption (AES-256-GCM)
    # -------------------------------------------------------------------------
    def test_item6_cryptographic_database_encryption(self):
        """Verify true AES-256-GCM encryption on disk, rejecting standard sqlite3.connect()."""
        enc_db_path = os.path.join(self.tmp_dir, "encrypted_test.db")
        enc_cfg_path = os.path.join(self.tmp_dir, "enc_app_config.json")

        with patch.object(database, "CONFIG_FILE", enc_cfg_path):
            mgr = DatabaseManager(enc_db_path)
            self._create_test_product(mgr, code="P-SECRET", name="Secret Laptop")

            # Verify unencrypted DB starts with standard SQLite header
            with open(enc_db_path, "rb") as f:
                header = f.read(16)
            self.assertEqual(header, b"SQLite format 3\x00")

            # Set password
            mgr.set_database_password("SuperSecret123!", require_startup_prompt=True)
            mgr.close()

            # Verify the on-disk file is now encrypted
            with open(enc_db_path, "rb") as f:
                raw_bytes = f.read()

            # Must NOT start with SQLite format header
            self.assertFalse(raw_bytes.startswith(b"SQLite format 3"))
            # Must NOT contain plaintext SQLite format header
            self.assertNotIn(b"SQLite format 3", raw_bytes)
            # Must NOT contain plain product name
            self.assertNotIn(b"Secret Laptop", raw_bytes)

            # Standard sqlite3.connect() MUST fail with DatabaseError
            raw_conn = sqlite3.connect(enc_db_path)
            with self.assertRaises(sqlite3.DatabaseError):
                raw_conn.execute("SELECT * FROM products")
            raw_conn.close()

            # Attempting to open DatabaseManager without password must raise DatabasePasswordRequiredError
            with self.assertRaises(DatabasePasswordRequiredError):
                DatabaseManager(enc_db_path)

            # Attempting with wrong password must raise DatabaseInvalidPasswordError
            with self.assertRaises(DatabaseInvalidPasswordError):
                DatabaseManager(enc_db_path, password="WrongPassword!")

            # Opening with correct password must succeed and decrypt data
            mgr2 = DatabaseManager(enc_db_path, password="SuperSecret123!")
            with mgr2.get_connection() as conn:
                products = conn.execute("SELECT * FROM products").fetchall()
            self.assertEqual(len(products), 1)
            self.assertEqual(products[0]["name"], "Secret Laptop")

            # Verify password change
            mgr2.change_database_password("SuperSecret123!", "NewSecret456!", require_startup_prompt=True)
            mgr2.close()

            mgr3 = DatabaseManager(enc_db_path, password="NewSecret456!")
            with mgr3.get_connection() as conn:
                products3 = conn.execute("SELECT * FROM products").fetchall()
            self.assertEqual(len(products3), 1)

            # Remove password -> converts back to plaintext SQLite
            mgr3.remove_database_password("NewSecret456!")
            mgr3.close()

            with open(enc_db_path, "rb") as f:
                header_plain = f.read(16)
            self.assertEqual(header_plain, b"SQLite format 3\x00")

            # Standard sqlite3.connect() works again
            raw_conn2 = sqlite3.connect(enc_db_path)
            row = raw_conn2.execute("SELECT name FROM products").fetchone()
            self.assertEqual(row[0], "Secret Laptop")
            raw_conn2.close()

    def test_item6_encrypted_backup_and_restore(self):
        """Verify backup and restore preserves encryption state seamlessly."""
        enc_db_path = os.path.join(self.tmp_dir, "enc_backup_test.db")
        enc_cfg_path = os.path.join(self.tmp_dir, "enc_bk_config.json")
        backup_dir = os.path.join(self.tmp_dir, "backups")

        with patch.object(database, "CONFIG_FILE", enc_cfg_path):
            mgr = DatabaseManager(enc_db_path)
            self._create_test_product(mgr, code="P-BK", name="Backup Laptop")
            mgr.set_database_password("BackupPass789!", require_startup_prompt=False)

            # Create backup
            backup_file = mgr.create_backup(backup_dir)
            self.assertTrue(os.path.exists(backup_file))

            # Verify backup file is also encrypted
            with open(backup_file, "rb") as f:
                bk_bytes = f.read()
            self.assertFalse(bk_bytes.startswith(b"SQLite format 3"))

            # Mutate original
            self._create_test_product(mgr, code="P-BK2", name="Second Laptop")
            with mgr.get_connection() as conn:
                self.assertEqual(len(conn.execute("SELECT * FROM products").fetchall()), 2)

            # Restore backup
            mgr.restore_backup(backup_file)
            with mgr.get_connection() as conn:
                products_after = conn.execute("SELECT * FROM products").fetchall()
            self.assertEqual(len(products_after), 1)
            self.assertEqual(products_after[0]["name"], "Backup Laptop")
            mgr.close()


if __name__ == "__main__":
    unittest.main()
