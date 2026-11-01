import os
import sqlite3

import pytest

import database as database_module
from database import DatabaseManager


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    return DatabaseManager(str(tmp_path / "shop.db"))


def create_product(manager, code="P-1001"):
    manager.add_product(
        code, "", "قطعات", "لوازم جانبی", "TestBrand", "TestModel",
        {}, "", 2, 20,
    )
    with manager.get_connection() as conn:
        row = conn.execute("SELECT id FROM products WHERE code=?", (code,)).fetchone()
    return int(row["id"])


def create_employee(manager, name="کارمند آزمون"):
    with manager.get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO employees (name, role, permissions) VALUES (?, ?, ?)",
            (name, "فروشنده", "فروش و خدمات"),
        )
        conn.commit()
        return int(cursor.lastrowid)


def create_supplier(manager, name="تأمین‌کننده آزمون"):
    with manager.get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO suppliers (name, phone, address) VALUES (?, ?, ?)",
            (name, "", ""),
        )
        conn.commit()
        return int(cursor.lastrowid)


def create_batch(manager, product_id, *, code="C-1001", supplier_id=None, buyer_id=None,
                 quantity=5, unit_price=100, suggested=150):
    manager.add_batch(
        code, product_id, supplier_id, buyer_id, "PO-TEST", "1405/01/01",
        quantity, unit_price, 0, suggested, 0, "", "مشخصات اولیه", "آزمون",
        "تسویه‌نشده",
    )
    with manager.get_connection() as conn:
        row = conn.execute("SELECT id FROM batches WHERE batch_code=?", (code,)).fetchone()
    return int(row["id"])


def create_sale(manager, product_id, batch_id, employee_id=None, warranty_days=0):
    return manager.add_sale(
        "INV-TEST", product_id, batch_id, employee_id, "مشتری آزمون",
        1, 150, 150, 0, "1405/01/01 12:00:00",
        "گارانتی آزمون" if warranty_days else "",
        "1405/01/01", 0, "1405/01/08" if warranty_days else "",
        "SERIAL-TEST", "", "تسویه‌نشده", warranty_days=warranty_days,
    )


def test_new_database_has_no_seeded_employees_and_codes_are_sequenced(manager):
    with manager.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM employees").fetchone()["n"]
    assert count == 0
    assert manager.generate_next_code("products", "code", "P-", 1001) == "P-1001"
    assert manager.generate_next_code("batches", "batch_code", "C-", 1001) == "C-1001"
    assert manager.generate_next_code("service_catalog", "code", "S-", 1001) == "S-1001"


def test_add_batch_and_sale_persist_warranty_days(manager):
    product_id = create_product(manager)
    batch_id = create_batch(manager, product_id)
    create_sale(manager, product_id, batch_id, warranty_days=7)

    with manager.get_connection() as conn:
        sale = conn.execute(
            "SELECT warranty_months, warranty_days FROM sales WHERE invoice_number='INV-TEST'"
        ).fetchone()
        batch = conn.execute("SELECT remaining_qty, sold_qty FROM batches WHERE id=?", (batch_id,)).fetchone()

    assert sale["warranty_months"] == 0
    assert sale["warranty_days"] == 7
    assert batch["remaining_qty"] == 4
    assert batch["sold_qty"] == 1


def test_supplier_delete_retains_historical_name_and_purchase(manager):
    product_id = create_product(manager)
    supplier_id = create_supplier(manager, "شرکت نمونه")
    batch_id = create_batch(manager, product_id, supplier_id=supplier_id)

    manager.delete_supplier(supplier_id, delete_related_data=False)

    with manager.get_connection() as conn:
        batch = conn.execute(
            "SELECT supplier_id, supplier_name_snapshot FROM batches WHERE id=?", (batch_id,)
        ).fetchone()
        supplier_count = conn.execute(
            "SELECT COUNT(*) AS n FROM suppliers WHERE id=?", (supplier_id,)
        ).fetchone()["n"]

    assert supplier_count == 0
    assert batch["supplier_id"] is None
    assert batch["supplier_name_snapshot"] == "شرکت نمونه"


def test_employee_delete_without_cascade_keeps_sales_and_batches(manager):
    product_id = create_product(manager)
    employee_id = create_employee(manager)
    batch_id = create_batch(manager, product_id, buyer_id=employee_id)
    create_sale(manager, product_id, batch_id, employee_id=employee_id)

    manager.delete_employee_custom(employee_id, delete_related_data=False)

    with manager.get_connection() as conn:
        batch = conn.execute("SELECT buyer_employee_id FROM batches WHERE id=?", (batch_id,)).fetchone()
        sale = conn.execute("SELECT seller_employee_id FROM sales WHERE invoice_number='INV-TEST'").fetchone()

    assert batch["buyer_employee_id"] is None
    assert sale["seller_employee_id"] is None


def test_employee_delete_with_cascade_removes_owned_history(manager):
    product_id = create_product(manager)
    employee_id = create_employee(manager)
    batch_id = create_batch(manager, product_id, buyer_id=employee_id)
    create_sale(manager, product_id, batch_id, employee_id=employee_id)

    manager.delete_employee_custom(employee_id, delete_related_data=True)

    with manager.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM employees WHERE id=?", (employee_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM batches WHERE id=?", (batch_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM sales WHERE invoice_number='INV-TEST'").fetchone()[0] == 0


def test_upgrade_reversal_restores_component_stock_and_target_cost(manager):
    product_id = create_product(manager)
    target_id = create_batch(manager, product_id, code="C-1001", quantity=2, unit_price=100, suggested=150)
    part_id = create_batch(manager, product_id, code="C-1002", quantity=5, unit_price=20, suggested=30)

    with manager.get_connection() as conn:
        target_before = conn.execute(
            "SELECT unit_cost_price, suggested_sell_price, final_specs FROM batches WHERE id=?",
            (target_id,),
        ).fetchone()
        part_before = conn.execute(
            "SELECT remaining_qty FROM batches WHERE id=?", (part_id,)
        ).fetchone()["remaining_qty"]

    manager.upgrade_batch_product(
        target_id, 1, part_id, 2, 10, "مشخصات ارتقایافته",
        "1405/01/02", None, add_part_cost_to_product=True,
    )

    with manager.get_connection() as conn:
        reduced_stock = conn.execute(
            "SELECT remaining_qty FROM batches WHERE id=?", (part_id,)
        ).fetchone()["remaining_qty"]

    assert reduced_stock == part_before - 2

    with manager.get_connection() as conn:
        upgrade_id = conn.execute("SELECT id FROM upgrades ORDER BY id DESC LIMIT 1").fetchone()["id"]
    manager.revert_upgrade(int(upgrade_id))

    with manager.get_connection() as conn:
        target_after = conn.execute(
            "SELECT unit_cost_price, suggested_sell_price, final_specs FROM batches WHERE id=?",
            (target_id,),
        ).fetchone()
        part_after = conn.execute(
            "SELECT remaining_qty FROM batches WHERE id=?", (part_id,)
        ).fetchone()["remaining_qty"]

    assert part_after == part_before
    assert target_after["unit_cost_price"] == target_before["unit_cost_price"]
    assert target_after["suggested_sell_price"] == target_before["suggested_sell_price"]
    assert target_after["final_specs"] == target_before["final_specs"]


def test_automatic_backup_follows_the_active_database_path(manager, tmp_path):
    product_id = create_product(manager)
    backup_path = manager.create_backup(automatic=True)

    assert os.path.basename(backup_path).startswith("shop_")
    assert backup_path.endswith(".db")
    with sqlite3.connect(backup_path) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM products WHERE id=?", (product_id,)).fetchone()[0] == 1


def test_automatic_backup_rotates_oldest_after_success(manager, tmp_path):
    manager.cfg["auto_backup_retention_count"] = 2
    product_id = create_product(manager)

    first = manager.create_backup(automatic=True)
    second = manager.create_backup(automatic=True)
    third = manager.create_backup(automatic=True)

    backup_files = sorted(tmp_path.glob("shop_*.db"))
    assert len(backup_files) == 2
    assert first not in {str(path) for path in backup_files}
    assert second in {str(path) for path in backup_files}
    assert third in {str(path) for path in backup_files}
    for path in backup_files:
        with sqlite3.connect(path) as conn:
            assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            assert conn.execute("SELECT COUNT(*) FROM products WHERE id=?", (product_id,)).fetchone()[0] == 1


def test_automatic_backup_folder_tracks_each_database_path(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    first_manager = DatabaseManager(str(tmp_path / "first" / "first_shop.db"))
    second_manager = DatabaseManager(str(tmp_path / "second" / "second_shop.db"))

    first_backup = first_manager.create_backup(automatic=True)
    second_backup = second_manager.create_backup(automatic=True)

    assert first_backup.startswith(str(tmp_path / "first"))
    assert second_backup.startswith(str(tmp_path / "second"))


def test_application_settings_migrate_from_database_to_config(manager):
    manager.set_setting("default_profit_pct", "35")
    manager.set_setting("zero_append_count", "4")
    manager.set_setting("zero_append_enabled", "1")
    manager.set_setting("default_window_maximized", "0")
    manager.set_setting("require_login_password", "1")
    manager.cfg["config_schema_version"] = 1

    manager._migrate_legacy_application_settings()

    assert manager.cfg["default_profit_pct"] == 35
    assert manager.cfg["zero_append_count"] == 4
    assert manager.cfg["default_window_maximized"] is False
    assert manager.cfg["require_login_password"] is True
    assert manager.get_setting("default_profit_pct", None) is None
    assert manager.get_setting("zero_append_count", None) is None


def test_zero_count_migration_respects_legacy_disabled_flag(manager):
    manager.set_setting("zero_append_count", "3")
    manager.set_setting("zero_append_enabled", "0")
    manager.cfg["config_schema_version"] = 1

    manager._migrate_legacy_application_settings()

    assert manager.cfg["zero_append_count"] == 0


def test_shop_name_is_stored_per_database(manager):
    manager.set_setting("shop_name", "8 رایان")
    assert manager.get_setting("shop_name") == "8 رایان"
    assert "shop_name" not in manager.cfg


def test_service_code_is_the_tariff_identity(manager):
    manager.save_service_catalog(None, "S-1001", "نصب", "نصب ویندوز", 100, 10, "")
    manager.save_service_catalog(None, "S-1002", "نصب", "نصب ویندوز", 120, 10, "")

    with manager.get_connection() as conn:
        rows = conn.execute(
            "SELECT code, default_fee FROM service_catalog WHERE name='نصب ویندوز' ORDER BY code"
        ).fetchall()

    assert [(row["code"], row["default_fee"]) for row in rows] == [
        ("S-1001", 100), ("S-1002", 120)
    ]


def test_upgrade_migration_removes_only_legacy_sample_employees(manager):
    with manager.get_connection() as conn:
        conn.execute(
            "INSERT INTO employees (name, role, permissions) VALUES (?, ?, ?)",
            ("فروشنده اول", "مدیر / فروشنده", "دسترسی کامل"),
        )
        conn.execute(
            "INSERT INTO employees (name, role, permissions) VALUES (?, ?, ?)",
            ("فروشنده دوم", "فروشنده", "دسترسی کامل"),
        )
        conn.execute(
            "INSERT INTO employees (name, role, permissions) VALUES (?, ?, ?)",
            ("کارمند واقعی", "فروشنده", "فروش و خدمات"),
        )
        conn.execute(
            "INSERT INTO employees (name, role, permissions) VALUES (?, ?, ?)",
            ("مدیر واقعی", "مدیر / فروشنده", "دسترسی کامل"),
        )
        conn.commit()

    manager.init_db()

    with manager.get_connection() as conn:
        names = [
            row["name"] for row in conn.execute(
                "SELECT name FROM employees ORDER BY name"
            ).fetchall()
        ]

    assert set(names) == {"کارمند واقعی", "مدیر واقعی"}
    with manager.get_connection() as conn:
        migrated_role = conn.execute(
            "SELECT role FROM employees WHERE name='مدیر واقعی'"
        ).fetchone()["role"]
    assert migrated_role == "مدیر"


def test_excel_report_title_is_right_to_left_for_digit_prefixed_shop_name(tmp_path):
    from openpyxl import load_workbook
    from exporter import export_table_to_excel

    target = tmp_path / "rtl_report.xlsx"
    export_table_to_excel(
        "گزارش فروش",
        ["عنوان"],
        [["مقدار"]],
        str(target),
        shop_name="8 رایان",
    )

    workbook = load_workbook(target)
    worksheet = workbook.active
    assert worksheet.views.sheetView[0].rightToLeft is True
    assert worksheet["A1"].value == "8 رایان — گزارش فروش"
    assert not any(mark in worksheet["A1"].value for mark in ("\u2066", "\u2067", "\u2068", "\u2069"))
    assert worksheet["A1"].alignment.readingOrder == 2

def test_automatic_backup_rotation_counts_legacy_fixed_backup(manager, tmp_path):
    manager.cfg["auto_backup_retention_count"] = 1
    legacy_path = tmp_path / "AutoBackup_shop.db"
    manager.create_backup(target_file=str(legacy_path))

    current_backup = manager.create_backup(automatic=True)

    assert not legacy_path.exists()
    assert os.path.exists(current_backup)
    assert len(list(tmp_path.glob("shop_*.db"))) == 1

def test_automatic_backup_keeps_exactly_latest_configured_count(manager, tmp_path, monkeypatch):
    class FakeTimestamp:
        def __init__(self, value):
            self.value = value

        def strftime(self, format_string):
            minutes, seconds = divmod(self.value, 60)
            if format_string == "%Y%m%d_%H%M%S":
                return f"14050810_00{minutes:02d}{seconds:02d}"
            if format_string == "%Y/%m/%d %H:%M:%S":
                return f"1405/08/10 00:{minutes:02d}:{seconds:02d}"
            raise AssertionError(f"Unexpected format: {format_string}")

    class FakeJalaliDateTime:
        counter = 0

        @classmethod
        def now(cls):
            cls.counter += 1
            return FakeTimestamp(cls.counter)

    monkeypatch.setattr(database_module.jdatetime, "datetime", FakeJalaliDateTime)
    manager.cfg["auto_backup_retention_count"] = 10
    created = [manager.create_backup(automatic=True) for _ in range(12)]

    remaining = sorted(tmp_path.glob("shop_*.db"), key=lambda p: p.stat().st_mtime_ns)

    assert len(remaining) == 10
    assert {str(path) for path in remaining} == set(created[-10:])
    assert not os.path.exists(created[0])
    assert not os.path.exists(created[1])


def test_last_automatic_backup_timestamp_is_tracked_per_database(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    first = DatabaseManager(str(tmp_path / "first" / "first.db"))
    first_backup = first.create_backup(automatic=True)
    first_timestamp = first.get_last_automatic_backup_timestamp()

    second = DatabaseManager(str(tmp_path / "second" / "second.db"))
    second.create_backup(automatic=True)

    first_reload = DatabaseManager(str(tmp_path / "first" / "first.db"))
    assert first_reload.get_last_automatic_backup_timestamp() >= first_timestamp
    assert os.path.exists(first_backup)
    assert len(first_reload.cfg["auto_backup_last_success_by_db"]) == 2



def test_automatic_backup_uses_db_files_and_removes_staging_file(manager, tmp_path):
    backup_path = manager.create_backup(automatic=True)

    assert backup_path.endswith(".db")
    assert os.path.isfile(backup_path)
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob("*.db.tmp"))
    assert not list(tmp_path.glob(".shop_backup_*.db"))
    with sqlite3.connect(backup_path) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
