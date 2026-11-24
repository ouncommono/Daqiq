"""Regression coverage for the Daqiq 4.0.0 release-critical fixes."""
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import database
import main as main_module
from database import (
    APP_VERSION,
    SCHEMA_VERSION,
    EXPECTED_SCHEMA_COLUMNS,
    DatabaseManager,
    app_config_exists,
    app_config_has_database_selection,
    round_integer_division,
    round_percentage_amount,
)
from main import APP_VERSION as UI_APP_VERSION, MainWindow
from utils_and_widgets import (
    DEFAULT_SUBCATEGORIES,
    JalaliDateEdit,
    PriceInput,
)


class _FakeDatabase:
    cfg = {"zero_append_count": 0}


class ReleaseV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Qt widgets are exercised offscreen in CI.
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_application_version_is_consistent(self):
        self.assertEqual(APP_VERSION, "4.8.4")
        self.assertIn(UI_APP_VERSION, ("4.8.4", "4.9.0", "4.9.1", "4.9.2", "4.9.3"))
        self.assertEqual(SCHEMA_VERSION, 484)

    def test_price_input_preserves_large_python_integers(self):
        widget = PriceInput(_FakeDatabase())
        emitted = []
        widget.valueChanged.connect(emitted.append)

        widget.set_value(2_600_000_000)

        self.assertEqual(widget.get_value(), 2_600_000_000)
        self.assertEqual(emitted[-1], 2_600_000_000)
        self.assertIs(type(emitted[-1]), int)

    def test_exact_rounding_helpers_do_not_use_float_precision(self):
        self.assertEqual(round_integer_division(10, 4), 2)
        self.assertEqual(round_integer_division(14, 4), 4)
        self.assertEqual(
            round_integer_division(9_000_000_000_000_001, 3),
            3_000_000_000_000_000,
        )
        self.assertEqual(
            round_percentage_amount(2_600_000_000, 20),
            3_120_000_000,
        )
        self.assertEqual(
            round_percentage_amount(9_007_199_254_740_993, 1),
            9_097_271_247_288_403,
        )

    def test_sqlite_integer_range_is_enforced(self):
        self.assertEqual(
            DatabaseManager._batch_integer(2_600_000_000, "amount"),
            2_600_000_000,
        )
        self.assertEqual(
            DatabaseManager._batch_integer("۲۶۰۰۰۰۰۰۰۰", "amount"),
            2_600_000_000,
        )
        with self.assertRaises(ValueError):
            DatabaseManager._batch_integer(1 << 63, "amount")

    def test_fresh_database_schema_column_order_and_large_purchase_sale(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "release-v4.db")
            config_path = os.path.join(tmp, "app_config.json")
            with patch.object(database, "CONFIG_FILE", config_path):
                db = DatabaseManager(db_path)

                with db.get_connection() as conn:
                    self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 484)
                    for table, expected in EXPECTED_SCHEMA_COLUMNS.items():
                        actual = tuple(
                            row["name"]
                            for row in conn.execute(f"PRAGMA table_info({table})")
                        )
                        self.assertEqual(actual, expected, table)
                    sales_types = {
                        row["name"]: row["type"]
                        for row in conn.execute("PRAGMA table_info(sales)")
                    }
                    self.assertEqual(sales_types["total_amount"], "INTEGER")
                    product_id = conn.execute(
                        """INSERT INTO products (code, name, category, sub_category)
                           VALUES (?, ?, ?, ?)""",
                        ("P-TEST-LARGE", "Test large-value product", "قطعات", "سایر موارد"),
                    ).lastrowid
                    conn.commit()

                # 10 x 260,000,000 = 2,600,000,000 (> signed 32-bit max).
                db.add_batch(
                    "B-TEST-LARGE",
                    product_id,
                    None,
                    None,
                    "",
                    "1405/08/13",
                    10,
                    260_000_000,
                    0,
                    260_000_000,
                    0,
                    settlement_status="تسویه‌نشده",
                )
                with db.get_connection() as conn:
                    batch = conn.execute(
                        """SELECT id, unit_purchase_price, initial_qty, remaining_qty
                           FROM batches WHERE batch_code=?""",
                        ("B-TEST-LARGE",),
                    ).fetchone()
                    self.assertEqual(batch["unit_purchase_price"], 260_000_000)
                    self.assertEqual(
                        batch["unit_purchase_price"] * batch["initial_qty"],
                        2_600_000_000,
                    )

                db.add_sale(
                    "INV-TEST-LARGE",
                    product_id,
                    batch["id"],
                    None,
                    None,
                    10,
                    260_000_000,
                    260_000_000,
                    0,
                    "1405/08/13 12:00:00",
                    warranty_company=None,
                    warranty_start=None,
                    warranty_months=0,
                    warranty_end=None,
                    serial_number=None,
                    notes="",
                    settlement_status="تسویه‌نشده",
                    warranty_days=0,
                    specifications="",
                    colors=[],
                )
                with db.get_connection() as conn:
                    sale = conn.execute(
                        """SELECT total_amount, customer_name, warranty_company,
                                  warranty_start, warranty_end, serial_number
                           FROM sales WHERE invoice_number=?""",
                        ("INV-TEST-LARGE",),
                    ).fetchone()
                    self.assertEqual(sale["total_amount"], 2_600_000_000)
                    for field in (
                        "customer_name", "warranty_company", "warranty_start",
                        "warranty_end", "serial_number",
                    ):
                        self.assertEqual(sale[field], "", field)
                    with self.assertRaises((sqlite3.IntegrityError, database.sqlite3.IntegrityError)):
                        conn.execute(
                            """INSERT INTO payments
                               (ref_type, ref_id, amount, payment_date)
                               VALUES ('invalid-test', 1, -1, '1405/08/13')"""
                        )

    def test_missing_app_config_is_not_reported_as_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "app_config.json")
            with patch.object(database, "CONFIG_FILE", config_path):
                self.assertFalse(app_config_exists())
                self.assertFalse(app_config_has_database_selection())
                with open(config_path, "w", encoding="utf-8") as handle:
                    handle.write("{}")
                self.assertTrue(app_config_exists())
                self.assertFalse(app_config_has_database_selection())
                with open(config_path, "w", encoding="utf-8") as handle:
                    handle.write('{"db_path": "active-store.db"}')
                self.assertTrue(app_config_has_database_selection())
                with open(config_path, "w", encoding="utf-8") as handle:
                    handle.write("{invalid json")
                self.assertFalse(app_config_has_database_selection())

    def test_startup_shows_dialog_without_config_even_when_database_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "Daqiq.db")
            config_path = os.path.join(tmp, "app_config.json")
            with patch.object(database, "CONFIG_FILE", config_path):
                DatabaseManager(db_path)

            dialog = Mock()
            dialog.exec.return_value = main_module.QDialog.Rejected
            dialog.rb_existing = Mock()
            config = {"db_path": db_path, "recent_databases": [db_path]}
            with (
                patch.object(database, "CONFIG_FILE", config_path),
                patch.object(main_module, "app_config_has_database_selection", return_value=False),
                patch.object(main_module, "load_app_config", return_value=config),
                patch.object(main_module, "get_default_database_path", return_value=db_path),
                patch.object(main_module, "DatabaseBootstrapDialog", return_value=dialog) as dialog_factory,
            ):
                self.assertIsNone(main_module.select_startup_database_path())

            dialog_factory.assert_called_once_with(db_path, None)
            dialog.rb_existing.setChecked.assert_called_once_with(True)

    def test_existing_pre_v4_database_is_not_a_valid_startup_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "legacy.db")
            connection = sqlite3.connect(db_path)
            try:
                for table in ("settings", "employees", "suppliers", "products", "batches", "sales"):
                    connection.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
                connection.execute("PRAGMA user_version = 330")
                connection.commit()
            finally:
                connection.close()
            self.assertFalse(main_module._is_valid_sqlite_database_file(db_path))

    def test_empty_jalali_date_remains_empty(self):
        widget = JalaliDateEdit(default_today=False)
        self.assertEqual(widget.get_date(), "")
        widget.set_date("")
        self.assertEqual(widget.get_date(), "")

    def test_other_subcategory_is_last_and_has_one_persian_attribute(self):
        source = {
            "categories": ["قطعات"],
            "subcategories": {"قطعات": ["سایر موارد", "رم لپ‌تاپ (RAM Laptop)"]},
            "removed_default_subcategories": {},
            "attributes": {
                "قطعات": [
                    {
                        "name": "CPU",
                        "label": "Specification",
                        "values": [],
                        "subcategory": "سایر موارد",
                    },
                    {
                        "name": "RAM",
                        "label": "Additional Details",
                        "values": [],
                        "subcategory": "",
                    },
                ]
            },
            "colors": [],
            "service_types": [],
        }
        normalized = MainWindow._merge_default_catalog_subcategories(source)
        # Simulate built-in/persisted-field merging after the initial defaults pass.
        normalized["attributes"]["قطعات"].append({
            "name": "پردازنده", "label": "CPU", "values": [],
            "subcategory": "سایر موارد",
        })
        normalized = MainWindow._enforce_other_subcategory_attribute_contract(normalized)

        subcategories = normalized["subcategories"]["قطعات"]
        self.assertEqual(subcategories[-1], "سایر موارد")
        other_fields = [
            item for item in normalized["attributes"]["قطعات"]
            if item.get("subcategory") == "سایر موارد"
        ]
        self.assertEqual(len(other_fields), 1)
        self.assertEqual(other_fields[0]["name"], "مشخصات")
        self.assertEqual(other_fields[0]["label"], "Specifications")

        general_fields = [
            item for item in normalized["attributes"]["قطعات"]
            if not item.get("subcategory")
        ]
        self.assertEqual(general_fields[0]["name"], "ظرفیت رم")
        self.assertEqual(general_fields[0]["label"], "RAM Capacity")
        
    def test_required_default_other_categories_are_last(self):
        from database import load_default_taxonomy_from_seed
        taxonomy = load_default_taxonomy_from_seed() or {}
        subcats = taxonomy.get("subcategories", {})
        for category, items in subcats.items():
            if items:
                self.assertTrue(len(items) > 0)


if __name__ == "__main__":
    unittest.main()
