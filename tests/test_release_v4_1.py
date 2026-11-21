"""Enterprise-grade regression and unit test suite for Daqiq v4.1.0 release requirements."""
import copy
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import database
from database import APP_VERSION, SCHEMA_VERSION, EXPECTED_SCHEMA_COLUMNS, DatabaseManager
import main as main_module
from main import (
    MainWindow,
    CatalogSettingsState,
    SettingsSnapshot,
    REPORT_AVAILABLE_COLUMNS,
)
from utils_and_widgets import DynamicAttributeValuesWidget, DynamicDomainValueRow
from exporter import export_table_to_excel


class ReleaseV41Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_greenfield_database_schema_and_version(self):
        """Requirement 0 & 6: Verify clean greenfield DB initialization with 4.1.0/410 schema."""
        self.assertEqual(APP_VERSION, "4.8.4")
        self.assertEqual(SCHEMA_VERSION, 484)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test_v410.db")
            config_path = os.path.join(tmp, "app_config.json")
            with patch.object(database, "CONFIG_FILE", config_path):
                db = DatabaseManager(db_path)
                with db.get_connection() as conn:
                    # User version matches 483
                    self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 484)
                    
                    # Columns match contract
                    prod_cols = tuple(r["name"] for r in conn.execute("PRAGMA table_info(products)"))
                    self.assertEqual(prod_cols, EXPECTED_SCHEMA_COLUMNS["products"])
                    self.assertIn("serial_number", prod_cols)
                    
                    # Search indexes exist
                    indexes = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
                    self.assertIn("idx_products_serial", indexes)
                    self.assertIn("idx_batches_serial", indexes)
                    self.assertIn("idx_batches_code", indexes)
                    self.assertIn("idx_sales_serial", indexes)

    def test_database_serial_number_lookup(self):
        """Requirement 0 & 5: Test indexed serial and barcode lookup in database."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test_lookup.db")
            config_path = os.path.join(tmp, "app_config.json")
            with patch.object(database, "CONFIG_FILE", config_path):
                db = DatabaseManager(db_path)
                # Add product with serial
                db.add_product(
                    "P-101", "لپ‌تاپ گیمینگ", "رایانه و اداری", "لپ‌تاپ", "Asus", "ROG",
                    {}, "", 1, 20, serial_number="SN-PROD-999"
                )
                with db.get_connection() as conn:
                    p_id = conn.execute("SELECT id FROM products WHERE code='P-101'").fetchone()["id"]
                # Add batch with cargo serial
                b_id = db.add_batch(
                    "C-BATCH-555", p_id, None, None, "", "1405/01/01",
                    5, 50_000_000, 0, 60_000_000, 0,
                    serial_numbers="SN-CARGO-12345\nSN-CARGO-67890"
                )

                # Lookup by product serial
                res1 = db.lookup_by_serial_or_barcode("SN-PROD-999")
                self.assertIsNotNone(res1["product"])
                self.assertEqual(res1["product"]["id"], p_id)

                # Lookup by cargo serial
                res2 = db.lookup_by_serial_or_barcode("SN-CARGO-12345")
                self.assertIsNotNone(res2["product"])
                self.assertEqual(res2["product"]["id"], p_id)
                self.assertIsNotNone(res2["matched_batch"])
                self.assertEqual(res2["matched_batch"]["batch_code"], "C-BATCH-555")

                # Lookup by batch code
                res3 = db.lookup_by_serial_or_barcode("C-BATCH-555")
                self.assertIsNotNone(res3["product"])
                self.assertEqual(res3["product"]["id"], p_id)
                self.assertIsNotNone(res3["matched_batch"])

    def test_dynamic_attribute_values_widget_atomic_add_remove(self):
        """Requirement 2: Dynamic subcategory domain list component with atomic add/remove."""
        widget = DynamicAttributeValuesWidget()
        self.assertEqual(widget.get_values(), [])

        # Set values
        widget.set_values(["HDMI", "Type-C", "DisplayPort"])
        self.assertEqual(widget.get_values(), ["HDMI", "Type-C", "DisplayPort"])
        self.assertEqual(len(widget.rows), 3)

        # Atomic Add row
        widget.add_row("USB 3.2")
        self.assertEqual(widget.get_values(), ["HDMI", "Type-C", "DisplayPort", "USB 3.2"])
        self.assertEqual(len(widget.rows), 4)

        # Atomic Remove row via row's '-' button
        second_row = widget.rows[1] # "Type-C"
        second_row.btn_remove.click()
        self.assertEqual(widget.get_values(), ["HDMI", "DisplayPort", "USB 3.2"])
        self.assertEqual(len(widget.rows), 3)

        # Clear
        widget.clear()
        self.assertEqual(widget.get_values(), [])
        self.assertEqual(len(widget.rows), 1)

    def test_decoupled_catalog_settings_state_preservation(self):
        """Requirement 1: Decoupled UI state preservation across tab switches."""
        state = CatalogSettingsState()
        mock_win = Mock()
        mock_win.ed_cfg_category = Mock()
        mock_win.ed_cfg_category.text.return_value = "گوشی همراه جدید"
        mock_win.ed_cfg_subcategory = Mock()
        mock_win.ed_cfg_subcategory.text.return_value = "پرچمدار"
        mock_win.ed_cfg_attribute_name = Mock()
        mock_win.ed_cfg_attribute_name.text.return_value = "نرخ نوسازی"
        mock_win.ed_cfg_attribute_label = Mock()
        mock_win.ed_cfg_attribute_label.text.return_value = "Refresh Rate"
        mock_win.attr_values_widget = Mock()
        mock_win.attr_values_widget.get_values.return_value = ["120Hz", "144Hz"]
        mock_win.ed_cfg_color = Mock()
        mock_win.ed_cfg_color.text.return_value = "تیتانیوم طبیعی"

        # Capture from window
        state.capture_from_window(mock_win)
        self.assertEqual(state.category_new_name, "گوشی همراه جدید")
        self.assertEqual(state.subcategory_name, "پرچمدار")
        self.assertEqual(state.attribute_name, "نرخ نوسازی")
        self.assertEqual(state.attribute_label, "Refresh Rate")
        self.assertEqual(state.attribute_values, ["120Hz", "144Hz"])
        self.assertEqual(state.color_name, "تیتانیوم طبیعی")

        # Now simulate restore onto clean fields
        target_win = Mock()
        target_win.ed_cfg_category = Mock()
        target_win.ed_cfg_subcategory = Mock()
        target_win.ed_cfg_attribute_name = Mock()
        target_win.ed_cfg_attribute_label = Mock()
        target_win.attr_values_widget = Mock()
        target_win.ed_cfg_color = Mock()

        state.restore_to_window(target_win)
        target_win.ed_cfg_category.setText.assert_called_once_with("گوشی همراه جدید")
        target_win.ed_cfg_subcategory.setText.assert_called_once_with("پرچمدار")
        target_win.ed_cfg_attribute_name.setText.assert_called_once_with("نرخ نوسازی")
        target_win.ed_cfg_attribute_label.setText.assert_called_once_with("Refresh Rate")
        target_win.attr_values_widget.set_values.assert_called_once_with(["120Hz", "144Hz"])
        target_win.ed_cfg_color.setText.assert_called_once_with("تیتانیوم طبیعی")

    def test_settings_snapshot_memento_rollback(self):
        """Requirement 4: SettingsSnapshot Memento pattern deep-copy rollback."""
        mock_win = Mock()
        mock_win.db = Mock()
        mock_win.db.cfg = {"default_profit_pct": 20, "shop_name": "فروشگاه من"}
        mock_win._taxonomy_draft = {"categories": ["قطعات"]}
        mock_win._pending_attribute_renames = []
        mock_win.db.get_setting.return_value = "فروشگاه من"
        mock_win.ed_cfg_category = Mock()
        mock_win.ed_cfg_category.text.return_value = "دسته‌بندی اولیه"
        mock_win.ed_cfg_subcategory = Mock()
        mock_win.ed_cfg_subcategory.text.return_value = "زیرمجموعه اولیه"
        mock_win.ed_cfg_attribute_name = Mock()
        mock_win.ed_cfg_attribute_name.text.return_value = "ویژگی اولیه"
        mock_win.ed_cfg_attribute_label = Mock()
        mock_win.ed_cfg_attribute_label.text.return_value = "Label"
        mock_win.attr_values_widget = Mock()
        mock_win.attr_values_widget.get_values.return_value = ["Val1"]
        mock_win.ed_cfg_color = Mock()
        mock_win.ed_cfg_color.text.return_value = "آبی"

        # Create snapshot
        snapshot = SettingsSnapshot(mock_win)

        # Mutate window state
        mock_win.db.cfg["default_profit_pct"] = 50
        mock_win._taxonomy_draft["categories"] = ["تغییر یافته"]

        # Restore from snapshot
        snapshot.restore(mock_win)
        self.assertEqual(mock_win.db.cfg["default_profit_pct"], 20)
        self.assertEqual(mock_win._taxonomy_draft["categories"], ["قطعات"])

    def test_openpyxl_excel_export_custom_columns(self):
        """Requirement 3: Dynamic Excel export engine generates styled workbook."""
        with tempfile.TemporaryDirectory() as tmp:
            out_file = os.path.join(tmp, "test_report.xlsx")
            headers = ["کد کالا", "نام کالا", "سود"]
            rows = [
                ["P-101", "لپ‌تاپ", "1,500,000"],
                ["P-102", "موس", "50,000"],
            ]
            export_table_to_excel(
                "گزارش فروش و سود کالاها",
                headers,
                rows,
                out_file,
                summary_text="مجموع سود: 1,550,000",
                shop_name="فروشگاه دقیق آزمون",
            )
            self.assertTrue(os.path.exists(out_file))
            self.assertGreater(os.path.getsize(out_file), 1000)


if __name__ == "__main__":
    unittest.main()
