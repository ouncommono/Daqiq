import os
import sys
import tempfile
import json
import shutil
import unittest
import sqlite3
import sqlcipher3

# Non-blocking headless mandate
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QMessageBox
import database
from database import (
    DatabaseManager,
    save_app_config,
    load_default_taxonomy_from_seed,
    APP_VERSION,
    SCHEMA_VERSION,
    EXPECTED_SCHEMA_COLUMNS,
)
from main import MainWindow

class TestReleaseV460(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.orig_config_file = database.CONFIG_FILE
        self.orig_get_cfg = database.get_config_file_path
        self.orig_msg_warn = QMessageBox.warning
        self.orig_msg_info = QMessageBox.information
        self.orig_msg_quest = QMessageBox.question

        QMessageBox.warning = lambda *args, **kwargs: QMessageBox.Ok
        QMessageBox.information = lambda *args, **kwargs: QMessageBox.Ok
        QMessageBox.question = lambda *args, **kwargs: QMessageBox.Yes

    def tearDown(self):
        database.CONFIG_FILE = self.orig_config_file
        database.get_config_file_path = self.orig_get_cfg
        QMessageBox.warning = self.orig_msg_warn
        QMessageBox.information = self.orig_msg_info
        QMessageBox.question = self.orig_msg_quest

    # =========================================================================
    # REQ-0: Greenfield Schema & App Parity (Zero Phantom Columns)
    # =========================================================================
    def test_req0_schema_parity_no_phantom_columns(self):
        self.assertEqual(APP_VERSION, "4.8.0")
        self.assertEqual(SCHEMA_VERSION, 480)

        # Verify payment_method phantom column is completely eliminated
        self.assertNotIn("payment_method", EXPECTED_SCHEMA_COLUMNS["payments"])

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "schema_test.db")
            app_cfg = os.path.join(tmpdir, "app_config.json")
            database.CONFIG_FILE = app_cfg
            database.get_config_file_path = lambda: app_cfg
            with open(app_cfg, "w", encoding="utf-8") as f:
                json.dump({"db_path": db_path}, f)

            db = DatabaseManager(db_path)
            with db.get_connection() as conn:
                # Check user_version
                ver = conn.execute("PRAGMA user_version").fetchone()[0]
                self.assertEqual(ver, 480)

                # Check payments columns in database
                cols = [row[1] for row in conn.execute("PRAGMA table_info(payments)").fetchall()]
                self.assertNotIn("payment_method", cols)

    # =========================================================================
    # REQ-2 & REQ-3: Purge of Hardcoded Taxonomy & Deletion Invariant (Gate 2)
    # =========================================================================
    def test_req2_req3_deletion_invariant_when_no_seed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "empty_seed.db")
            app_cfg = os.path.join(tmpdir, "app_config.json")
            database.CONFIG_FILE = app_cfg
            database.get_config_file_path = lambda: app_cfg
            with open(app_cfg, "w", encoding="utf-8") as f:
                json.dump({"db_path": db_path}, f)

            # Ensure default_taxonomy.json does not exist in tmpdir
            tax_path = os.path.join(tmpdir, "default_taxonomy.json")
            if os.path.exists(tax_path):
                os.remove(tax_path)

            db = DatabaseManager(db_path)
            catalog = db.get_product_catalog_config()
            self.assertEqual(catalog.get("categories"), [])
            self.assertEqual(catalog.get("subcategories"), {})
            self.assertEqual(catalog.get("attributes"), {})
            self.assertEqual(catalog.get("colors"), [])

            # UI starts cleanly with zero taxonomy and allows manual definition
            win = MainWindow(db)
            self.assertEqual(win.cb_prod_cat.count(), 0)

            win._load_catalog_customization_form()
            self.assertEqual(win.cb_cfg_category.count(), 0)

            # Manually define category, subcategory, attribute
            win.ed_cfg_category.setText("قطعات رباتیک")
            win._add_catalog_category()
            self.assertIn("قطعات رباتیک", win._taxonomy_draft["categories"])

            win.ed_cfg_subcategory.setText("سروموتور (Servo)")
            win._add_catalog_subcategory()
            self.assertIn("سروموتور (Servo)", win._taxonomy_draft["subcategories"]["قطعات رباتیک"])

            win.ed_cfg_attribute_name.setText("ولتاژ کاری")
            win.ed_cfg_attribute_label.setText("Voltage")
            win._add_catalog_attribute()
            self.assertTrue(any(a["name"] == "ولتاژ کاری" for a in win._taxonomy_draft["attributes"]["قطعات رباتیک"]))

            win.close()

    # =========================================================================
    # REQ-2 & REQ-4: Bilingual Hardware Domain Research & External Taxonomy
    # =========================================================================
    def test_req2_req4_bilingual_hardware_taxonomy_rules(self):
        taxonomy = load_default_taxonomy_from_seed()
        self.assertIsNotNone(taxonomy)

        # 1. Categories: 100% Persian
        import re
        for cat in taxonomy["categories"]:
            self.assertFalse(bool(re.search(r'[A-Za-z]', cat)), f"Category contains English: {cat}")

        # 2. Subcategories: Strictly "Persian (English)", except universal "سایر موارد"
        for cat, subs in taxonomy["subcategories"].items():
            self.assertEqual(len(subs), len(set(subs)), f"Duplicate subcategory in {cat}")
            for sub in subs:
                if sub == "سایر موارد":
                    continue
                self.assertTrue(bool(re.search(r'\([A-Za-z0-9\s,&/+\-.]+\)$', sub)), f"Subcategory not bilingual: {sub}")

        # 3. Attribute names: 100% Persian, display names: 100% English, options: 100% English
        for cat, attrs in taxonomy["attributes"].items():
            for attr in attrs:
                name = attr["name"]
                label = attr["label"]
                values = attr["values"]
                self.assertFalse(bool(re.search(r'[A-Za-z]', name)), f"Attr name contains English: {name}")
                self.assertFalse(bool(re.search(r'[\u0600-\u06FF]', label)), f"Display label contains Persian: {label}")
                for val in values:
                    self.assertFalse(bool(re.search(r'[\u0600-\u06FF]', val)), f"Value contains Persian: {val}")

        # Specific hardware checks: DDR2, Celeron, Screen Size & Resolution separated, NVMe PCIe 3.0-5.0
        pc_attrs = taxonomy["attributes"]["قطعات اصلی کامپیوتر"]
        ram_attr = next(a for a in pc_attrs if a["name"] == "نسل رم" and a.get("subcategory") == "رم کامپیوتر (Desktop RAM)")
        self.assertIn("DDR2", ram_attr["values"])

        cpu_attr = next(a for a in pc_attrs if a["name"] == "سری پردازنده")
        self.assertIn("Celeron", cpu_attr["values"])

        ssd_attr = next(a for a in pc_attrs if a["name"] == "نوع رابط" and a.get("subcategory") == "حافظه اس‌اس‌دی (SSD)")
        self.assertIn("NVMe PCIe 3.0", ssd_attr["values"])
        self.assertIn("NVMe PCIe 4.0", ssd_attr["values"])
        self.assertIn("NVMe PCIe 5.0", ssd_attr["values"])

        mon_attrs = {a["name"]: a for a in taxonomy["attributes"]["مانیتور و نمایشگر"]}
        self.assertIn("ابعاد صفحه نمایش", mon_attrs)
        self.assertIn("رزولوشن", mon_attrs)
        self.assertEqual(mon_attrs["ابعاد صفحه نمایش"]["label"], "Screen Size")
        self.assertEqual(mon_attrs["رزولوشن"]["label"], "Resolution")

    # =========================================================================
    # REQ-8: True Standard SQLCipher AES-256 DB Encryption Lifecycle & Zero Leakage
    # =========================================================================
    def test_req8_sqlcipher_encryption_and_zero_leakage_backup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "enc_lifecycle.db")
            app_cfg = os.path.join(tmpdir, "app_config.json")
            database.CONFIG_FILE = app_cfg
            database.get_config_file_path = lambda: app_cfg
            with open(app_cfg, "w", encoding="utf-8") as f:
                json.dump({"db_path": db_path}, f)

            # 1. Plain DB
            db = DatabaseManager(db_path)
            self.assertFalse(db.is_password_protected())
            with db.get_connection() as conn:
                conn.execute("INSERT INTO settings (key, value) VALUES ('k1', 'v1')")
                conn.commit()

            # 2. Encrypt
            pwd1 = "MasterPass999!"
            db.set_database_password(pwd1, require_startup_prompt=True)
            self.assertTrue(db.is_password_protected())

            # 3. Plain sqlite3 MUST FAIL
            conn_plain = sqlite3.connect(db_path)
            try:
                with self.assertRaises(sqlite3.DatabaseError):
                    conn_plain.execute("SELECT * FROM settings").fetchall()
            finally:
                conn_plain.close()

            # 4. SQLCipher standard connection MUST SUCCEED
            conn_sc = sqlcipher3.connect(db_path)
            try:
                conn_sc.execute(f"PRAGMA key = '{pwd1}'")
                v = conn_sc.execute("SELECT value FROM settings WHERE key='k1'").fetchone()[0]
                self.assertEqual(v, "v1")
            finally:
                conn_sc.close()

            # 5. Encrypted Backup - Zero Leakage
            bk_dir = os.path.join(tmpdir, "backups")
            bk_file = db.create_backup(custom_dir=bk_dir)
            self.assertTrue(os.path.exists(bk_file))

            # Backup cannot be read with plain sqlite3!
            bk_plain = sqlite3.connect(bk_file)
            try:
                with self.assertRaises(sqlite3.DatabaseError):
                    bk_plain.execute("SELECT * FROM settings").fetchall()
            finally:
                bk_plain.close()

            # Backup can be read with SQLCipher + key!
            bk_sc = sqlcipher3.connect(bk_file)
            try:
                bk_sc.execute(f"PRAGMA key = '{pwd1}'")
                bv = bk_sc.execute("SELECT value FROM settings WHERE key='k1'").fetchone()[0]
                self.assertEqual(bv, "v1")
            finally:
                bk_sc.close()

            # 6. Change password (rekey)
            pwd2 = "UpdatedPass777@"
            db.change_database_password(pwd1, pwd2)
            self.assertTrue(db.is_password_protected())

            # 7. Remove password (decrypt)
            db.remove_database_password(pwd2)
            self.assertFalse(db.is_password_protected())
            conn_plain2 = sqlite3.connect(db_path)
            try:
                final_v = conn_plain2.execute("SELECT value FROM settings WHERE key='k1'").fetchone()[0]
                self.assertEqual(final_v, "v1")
            finally:
                conn_plain2.close()

    # =========================================================================
    # REQ-5: Sales Form Reset Dropdown Bug
    # =========================================================================
    def test_req5_sales_form_clear_repopulates_batches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "sales_fix.db")
            app_cfg = os.path.join(tmpdir, "app_config.json")
            database.CONFIG_FILE = app_cfg
            database.get_config_file_path = lambda: app_cfg
            with open(app_cfg, "w", encoding="utf-8") as f:
                json.dump({"db_path": db_path}, f)

            db = DatabaseManager(db_path)
            with db.get_connection() as conn:
                pid = conn.execute("INSERT INTO products (name, code, category, sub_category) VALUES ('کیبورد مکانیکی', 'KB-01', 'تجهیزات جانبی', 'کیبورد (Keyboard)')").lastrowid
                conn.execute("""
                    INSERT INTO batches (batch_code, product_id, purchase_date, initial_qty, sold_qty, remaining_qty, unit_purchase_price, unit_cost_price, suggested_sell_price, colors_json, notes)
                    VALUES ('BAT-KB', ?, '1405/01/01', 10, 0, 10, 500000, 500000, 700000, '[]', '')
                """, (pid,))
                conn.commit()

            win = MainWindow(db)
            self.assertGreaterEqual(win.cb_sale_batch.count(), 1)

            # Clear form
            win._clear_sale_form()

            # cb_sale_batch must not become empty!
            self.assertGreaterEqual(win.cb_sale_batch.count(), 1, "cb_sale_batch must be repopulated after clearing form!")
            win.close()

    # =========================================================================
    # REQ-6: Transactional Excel Staging & Comprehensive Reports Default
    # =========================================================================
    def test_req6_excel_settings_transactional_staging_and_reports_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "excel_fix.db")
            app_cfg = os.path.join(tmpdir, "app_config.json")
            database.CONFIG_FILE = app_cfg
            database.get_config_file_path = lambda: app_cfg
            with open(app_cfg, "w", encoding="utf-8") as f:
                json.dump({"db_path": db_path}, f)

            db = DatabaseManager(db_path)
            win = MainWindow(db)

            # Comprehensive reports default to index 0 ("همه")
            self.assertEqual(win.cb_rep_type.currentIndex(), 0)
            self.assertIn("همه", win.cb_rep_type.currentText())

            # Excel export settings: index 0 is "تعریف گزارش جدید"
            self.assertEqual(win.cb_report_export_type.itemText(0), "تعریف گزارش جدید")
            win.cb_report_export_type.setCurrentIndex(0)
            self.assertGreater(win.lst_report_export_columns.count(), 10)

            # Staging: add custom report in memory
            win.ed_custom_report_name.setText("گزارش تست اعتبارسنجی")
            win._add_custom_report()

            # Verify not saved in DB yet
            saved_in_db = json.loads(db.get_setting("custom_report_definitions", "{}") or "{}")
            self.assertNotIn("گزارش تست اعتبارسنجی", saved_in_db)

            # Explicit save commits to DB
            win._save_report_export_config_ui()
            saved_after = json.loads(db.get_setting("custom_report_definitions", "{}") or "{}")
            self.assertIn("گزارش تست اعتبارسنجی", saved_after)

            win.close()

    # =========================================================================
    # REQ-7 & REQ-10: UI Layout & Inner List Viewport Expansion (6-8 Items)
    # =========================================================================
    def test_req7_req10_ui_layout_and_list_viewport_heights(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "ui_test.db")
            app_cfg = os.path.join(tmpdir, "app_config.json")
            database.CONFIG_FILE = app_cfg
            database.get_config_file_path = lambda: app_cfg
            with open(app_cfg, "w", encoding="utf-8") as f:
                json.dump({"db_path": db_path}, f)

            db = DatabaseManager(db_path)
            win = MainWindow(db)

            # Check minimum heights conform to compacted v4.8.0 standard
            self.assertGreaterEqual(win.lst_cfg_subcategories.minimumHeight(), 174)
            self.assertGreaterEqual(win.lst_cfg_colors.minimumHeight(), 174)
            self.assertGreaterEqual(win.lst_cfg_attributes.minimumHeight(), 192)
            self.assertGreaterEqual(win.attr_values_widget.scroll_area.minimumHeight(), 160)

            win.close()

if __name__ == "__main__":
    unittest.main()
