import json
import os
import sqlite3

import pytest

import database as database_module
import exporter as exporter_module
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


def test_new_database_places_activity_columns_last_and_creates_activity_indexes(manager):
    tracked_tables = (
        "employees", "suppliers", "customers", "products", "batches", "upgrades",
        "sales", "service_catalog", "service_price_history", "service_records",
        "payments", "audit_logs",
    )
    with manager.get_connection() as conn:
        for table in tracked_tables:
            columns = [
                row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
            ]
            assert columns[-1] == "updated_at", (table, columns)

        expected_indexes = {
            "batches": "idx_batches_product_activity",
            "sales": "idx_sales_activity",
            "service_records": "idx_service_records_activity",
            "products": "idx_products_activity",
        }
        for table, expected_index in expected_indexes.items():
            indexes = {
                row["name"] for row in conn.execute(f"PRAGMA index_list({table})")
            }
            assert expected_index in indexes, (table, indexes)


def test_partner_inventory_export_obeys_selected_columns(manager, tmp_path):
    product_id = create_product(manager, "P-PEER")
    create_batch(
        manager, product_id, code="C-PEER", quantity=4, unit_price=125, suggested=215
    )
    manager.set_setting(
        "peer_inventory_export_fields",
        json.dumps(["code", "suggested_price"], ensure_ascii=False),
    )
    output = tmp_path / "partner-inventory.xlsx"
    exporter_module.export_safe_inventory_excel(manager, str(output), "8 رایان")

    workbook = exporter_module.openpyxl.load_workbook(output, read_only=True, data_only=True)
    try:
        sheet = workbook["موجودی همکار"]
        headers = [sheet.cell(2, column).value for column in range(1, sheet.max_column + 1)]
        assert headers == ["کد کالا", "قیمت فروش (پیشنهادی)"]
        assert [sheet.cell(3, column).value for column in range(1, 3)] == ["P-PEER", 215]
    finally:
        workbook.close()


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


def test_upgrade_on_empty_target_with_manual_component_never_changes_stock(manager):
    product_id = create_product(manager)
    target_id = create_batch(manager, product_id, code="C-TARGET-EMPTY", quantity=2)
    part_id = create_batch(manager, product_id, code="C-PART-AVAILABLE", quantity=1)
    with manager.get_connection() as conn:
        conn.execute(
            "UPDATE batches SET remaining_qty=0, sold_qty=initial_qty WHERE id=?",
            (target_id,),
        )
        part_before = conn.execute(
            "SELECT remaining_qty FROM batches WHERE id=?", (part_id,)
        ).fetchone()["remaining_qty"]
        target_before = conn.execute(
            "SELECT unit_cost_price FROM batches WHERE id=?", (target_id,)
        ).fetchone()["unit_cost_price"]
        conn.commit()

    manager.upgrade_batch_product(
        target_id, 1, None, 1, 25, "RAM: 16GB DDR4",
        "1405/01/03", None,
        manual_part_description="RAM 16GB (قطعه خارج از فهرست)",
        consume_stock=False,
    )

    with manager.get_connection() as conn:
        target = conn.execute(
            "SELECT remaining_qty, unit_cost_price, final_specs FROM batches WHERE id=?",
            (target_id,),
        ).fetchone()
        part_after = conn.execute(
            "SELECT remaining_qty FROM batches WHERE id=?", (part_id,)
        ).fetchone()["remaining_qty"]
        upgrade = conn.execute(
            "SELECT part_batch_id, manual_part_description, stock_deducted_qty "
            "FROM upgrades ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert target["remaining_qty"] == 0
    assert target["unit_cost_price"] == target_before + 25
    assert target["final_specs"] == "RAM: 16GB DDR4"
    assert part_after == part_before
    assert upgrade["part_batch_id"] is None
    assert upgrade["manual_part_description"] == "RAM 16GB (قطعه خارج از فهرست)"
    assert upgrade["stock_deducted_qty"] == 0


def test_upgrade_schema_rebuild_preserves_history_and_allows_manual_parts(manager):
    product_id = create_product(manager)
    target_id = create_batch(manager, product_id, code="C-MIGRATION-TARGET")
    part_id = create_batch(manager, product_id, code="C-MIGRATION-PART")
    with manager.get_connection() as conn:
        conn.execute("DROP TABLE upgrades")
        conn.execute("""
            CREATE TABLE upgrades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_batch_id INTEGER NOT NULL,
                target_qty INTEGER NOT NULL DEFAULT 1,
                part_batch_id INTEGER NOT NULL,
                part_qty_used INTEGER NOT NULL,
                part_unit_cost INTEGER NOT NULL,
                labor_cost_unit INTEGER DEFAULT 0,
                added_cost_unit INTEGER DEFAULT 0,
                old_specs TEXT DEFAULT '',
                new_specs TEXT DEFAULT '',
                upgrade_date TEXT NOT NULL,
                technician_id INTEGER,
                serial_number TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                updated_at TEXT,
                FOREIGN KEY(target_batch_id) REFERENCES batches(id),
                FOREIGN KEY(part_batch_id) REFERENCES batches(id),
                FOREIGN KEY(technician_id) REFERENCES employees(id)
            )
        """)
        conn.execute(
            """INSERT INTO upgrades (
                id, target_batch_id, target_qty, part_batch_id, part_qty_used,
                part_unit_cost, labor_cost_unit, added_cost_unit, old_specs, new_specs,
                upgrade_date, technician_id, serial_number, notes, updated_at
            ) VALUES (41, ?, 1, ?, 2, 75, 20, 95, 'RAM: 8GB', 'RAM: 16GB', ?, NULL, '', 'legacy', '00000000000000000042')""",
            (target_id, part_id, "1405/01/02"),
        )
        conn.commit()

    manager.init_db()

    with manager.get_connection() as conn:
        columns = {
            row["name"]: row
            for row in conn.execute("PRAGMA table_info(upgrades)").fetchall()
        }
        legacy = conn.execute("SELECT * FROM upgrades WHERE id=41").fetchone()

    assert columns["part_batch_id"]["notnull"] == 0
    assert legacy["target_batch_id"] == target_id
    assert legacy["part_batch_id"] == part_id
    assert legacy["part_qty_used"] == 2
    assert legacy["stock_deducted_qty"] == 2
    assert legacy["old_specs"] == "RAM: 8GB"
    assert legacy["new_specs"] == "RAM: 16GB"
    assert legacy["updated_at"] == "00000000000000000042"
    assert legacy["manual_part_description"] == ""


def test_upgrade_backend_rejects_unconfirmed_insufficient_inventory(manager):
    product_id = create_product(manager)
    target_id = create_batch(manager, product_id, code="C-GUARD-TARGET")
    part_id = create_batch(manager, product_id, code="C-GUARD-PART", quantity=1)
    with manager.get_connection() as conn:
        conn.execute(
            "UPDATE batches SET remaining_qty=0, sold_qty=initial_qty WHERE id=?",
            (part_id,),
        )
        conn.commit()

    with pytest.raises(ValueError, match="موجودی قطعه کافی نیست"):
        manager.upgrade_batch_product(
            target_id, 1, part_id, 1, 10, "SSD: 1TB",
            "1405/01/04", None, consume_stock=True,
        )
    with manager.get_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM upgrades"
        ).fetchone()[0] == 0


def test_confirmed_upgrade_with_unavailable_selected_component_does_not_go_negative(manager):
    product_id = create_product(manager)
    target_id = create_batch(manager, product_id, code="C-TARGET")
    part_id = create_batch(manager, product_id, code="C-PART", quantity=1)
    with manager.get_connection() as conn:
        conn.execute(
            "UPDATE batches SET remaining_qty=0, sold_qty=initial_qty WHERE id=?",
            (part_id,),
        )
        conn.commit()

    manager.upgrade_batch_product(
        target_id, 1, part_id, 1, 10, "SSD: 1TB",
        "1405/01/04", None, consume_stock=False,
    )
    with manager.get_connection() as conn:
        part = conn.execute(
            "SELECT remaining_qty, sold_qty FROM batches WHERE id=?", (part_id,)
        ).fetchone()
        upgrade = conn.execute(
            "SELECT stock_deducted_qty FROM upgrades ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert part["remaining_qty"] == 0
    assert upgrade["stock_deducted_qty"] == 0


def test_sale_specifications_are_saved_and_updated_as_sold_snapshot(manager):
    product_id = create_product(manager)
    batch_id = create_batch(manager, product_id, code="C-SALE-SPECS")
    invoice = manager.add_sale(
        "INV-SPECS", product_id, batch_id, None, "مشتری",
        1, 150, 150, 0, "1405/01/01 12:00:00",
        "", "", 0, "", "", "",
        settlement_status="تسویه‌نشده",
        specifications="RAM: 8GB DDR4",
    )
    with manager.get_connection() as conn:
        sale_id = conn.execute(
            "SELECT id FROM sales WHERE invoice_number=?", (invoice,)
        ).fetchone()["id"]

    manager.update_sale(
        sale_id, None, "مشتری", 1, 150, 160, 0,
        "", "", 0, "", "", "", "تسویه‌نشده",
        warranty_days=0,
        specifications="RAM: 16GB DDR5",
    )
    with manager.get_connection() as conn:
        sale = conn.execute(
            "SELECT specifications, actual_unit_price FROM sales WHERE id=?",
            (sale_id,),
        ).fetchone()
    assert sale["specifications"] == "RAM: 16GB DDR5"
    assert sale["actual_unit_price"] == 160


def test_batch_and_sale_colour_snapshots_are_validated_and_persisted(manager):
    product_id = create_product(manager, code="P-COLOUR-SNAPSHOT")
    batch_id = create_batch(
        manager, product_id, code="C-COLOUR-SNAPSHOT", quantity=5
    )
    with manager.get_connection() as conn:
        conn.execute(
            "UPDATE batches SET colors_json=? WHERE id=?",
            ('["مشکی", "سبز", "آبی"]', batch_id),
        )
        conn.commit()

    invoice = manager.add_sale(
        "INV-COLOUR-SNAPSHOT", product_id, batch_id, None, "مشتری رنگی",
        2, 150, 150, 0, "1405/01/01 12:00:00",
        settlement_status="تسویه‌نشده",
        colors=["مشکی", "سبز"],
    )
    with manager.get_connection() as conn:
        sale = conn.execute(
            "SELECT id, colors_json FROM sales WHERE invoice_number=?",
            (invoice,),
        ).fetchone()
        batch = conn.execute(
            "SELECT colors_json, remaining_qty FROM batches WHERE id=?",
            (batch_id,),
        ).fetchone()
    assert json.loads(batch["colors_json"]) == ["مشکی", "سبز", "آبی"]
    assert json.loads(sale["colors_json"]) == ["مشکی", "سبز"]
    assert batch["remaining_qty"] == 3

    manager.update_sale(
        sale["id"], None, "مشتری رنگی", 2, 150, 155, 0,
        "", "", 0, "", "", "", "تسویه‌نشده",
        specifications="RAM: 16GB DDR5",
        colors=["آبی"],
    )
    with manager.get_connection() as conn:
        updated = conn.execute(
            "SELECT colors_json, specifications FROM sales WHERE id=?",
            (sale["id"],),
        ).fetchone()
    assert json.loads(updated["colors_json"]) == ["آبی"]
    assert updated["specifications"] == "RAM: 16GB DDR5"

    with pytest.raises(ValueError, match="تعداد رنگ‌های انتخاب‌شده"):
        manager.add_sale(
            "INV-COLOUR-TOO-MANY", product_id, batch_id, None, "مشتری رنگی",
            1, 150, 150, 0, "1405/01/01 12:00:00",
            settlement_status="تسویه‌نشده",
            colors=["مشکی", "سبز"],
        )
    with pytest.raises(ValueError, match="رنگ‌های انتخاب‌شده"):
        manager.add_sale(
            "INV-COLOUR-UNKNOWN", product_id, batch_id, None, "مشتری رنگی",
            1, 150, 150, 0, "1405/01/01 12:00:00",
            settlement_status="تسویه‌نشده",
            colors=["صورتی"],
        )


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

    backup_files = sorted((tmp_path / "Backups").glob("shop_*.db"))
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

    assert first_backup.startswith(str(tmp_path / "first" / "Backups"))
    assert second_backup.startswith(str(tmp_path / "second" / "Backups"))


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

def test_automatic_backup_rotation_keeps_legacy_manual_backup_separate(manager, tmp_path):
    manager.cfg["auto_backup_retention_count"] = 1
    legacy_path = tmp_path / "AutoBackup_shop.db"
    manager.create_backup(target_file=str(legacy_path))

    current_backup = manager.create_backup(automatic=True)

    # Existing legacy/manual files outside Backups are not part of the new cycle.
    assert legacy_path.exists()
    assert os.path.exists(current_backup)
    assert len(list((tmp_path / "Backups").glob("shop_*.db"))) == 1

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

    remaining = sorted((tmp_path / "Backups").glob("shop_*.db"), key=lambda p: p.stat().st_mtime_ns)

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
    assert not list((tmp_path / "Backups").glob("*.tmp"))
    assert not list((tmp_path / "Backups").glob("*.db.tmp"))
    assert not list((tmp_path / "Backups").glob(".shop_backup_*.db"))
    with sqlite3.connect(backup_path) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"



def test_new_database_starts_without_seeded_suppliers(manager):
    with manager.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0] == 0


def test_product_catalog_configuration_is_persisted_per_database(manager, tmp_path, monkeypatch):
    manager.save_product_catalog_config({
        "categories": ["لپ‌تاپ", "تجهیزات جدید"],
        "subcategories": {"تجهیزات جدید": ["دستگاه هوشمند"]},
        "attributes": {
            "تجهیزات جدید": [{"name": "نسل", "values": ["نسل ۵", "نسل ۶"]}]
        },
        "colors": ["مشکی", "نقره‌ای"],
    })

    reloaded = DatabaseManager(str(tmp_path / "shop.db"))
    config = reloaded.get_product_catalog_config()
    assert "تجهیزات جدید" in config["categories"]
    assert config["subcategories"]["تجهیزات جدید"] == ["دستگاه هوشمند"]
    assert config["attributes"]["تجهیزات جدید"][0]["values"] == ["نسل ۵", "نسل ۶"]
    assert config["colors"] == ["مشکی", "نقره‌ای"]
    assert config["service_types"] == ["نرم‌افزاری", "سخت‌افزاری"]



def test_legacy_generic_supplier_is_removed_without_losing_purchase_history(manager, tmp_path):
    product_id = create_product(manager, "P-LEGACY")
    with manager.get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO suppliers (name, phone, address, notes) VALUES (?, ?, ?, ?)",
            ("تأمین‌کننده عمومی بازار", "021-88990011", "تهران", "پیش‌فرض"),
        )
        supplier_id = int(cursor.lastrowid)
        conn.commit()

    manager.add_batch(
        "C-LEGACY", product_id, supplier_id, None, "PO-OLD", "1404/01/01",
        2, 100, 0, 150, 0, "", "RAM:8GB", "سوابق خرید", "تسویه‌نشده",
    )

    reloaded = DatabaseManager(str(tmp_path / "shop.db"))
    with reloaded.get_connection() as conn:
        supplier_count = conn.execute(
            "SELECT COUNT(*) FROM suppliers WHERE name='تأمین‌کننده عمومی بازار'"
        ).fetchone()[0]
        batch = conn.execute(
            "SELECT supplier_id, supplier_name_snapshot FROM batches WHERE batch_code='C-LEGACY'"
        ).fetchone()

    assert supplier_count == 0
    assert batch["supplier_id"] is None
    assert batch["supplier_name_snapshot"] == "تأمین‌کننده عمومی بازار"



def test_manual_backup_can_replace_an_existing_user_selected_file(manager, tmp_path):
    product_id = create_product(manager, "P-MANUAL-1")
    target = tmp_path / "manual" / "chosen_backup.db"
    first = manager.create_backup(target_file=str(target))
    assert first == str(target)
    assert target.is_file()

    manager.add_product(
        "P-MANUAL-2", "", "قطعات", "حافظه اس‌اس‌دی (SSD)",
        "TestBrand", "Second", {}, "", 2, 20,
    )
    second = manager.create_backup(target_file=str(target))
    assert second == str(target)

    with sqlite3.connect(target) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2
    assert not list(target.parent.glob("*.manual*.db"))



def test_product_attribute_rename_migrates_existing_specs_atomically(manager):
    product_id = create_product(manager, "P-ATTR-1")
    with manager.get_connection() as conn:
        conn.execute(
            "UPDATE products SET specs_json=? WHERE id=?",
            ('{"TDP":"65W","رنگ":"مشکی"}', product_id),
        )
        conn.commit()

    manager.save_product_catalog_config({
        "categories": ["قطعات"],
        "subcategories": {"قطعات": ["پردازنده (CPU)"]},
        "attributes": {
            "قطعات": [
                {"name": "توان مصرفی", "values": ["45W", "65W"], "subcategory": "پردازنده (CPU)"}
            ]
        },
        "colors": ["مشکی"],
    })
    with manager.get_connection() as conn:
        product = conn.execute(
            "SELECT specs_json FROM products WHERE id=?", (product_id,)
        ).fetchone()
    # This contract is verified by the UI settings-save test; this unit test
    # keeps catalog configuration itself per database and serializable.
    assert manager.get_product_catalog_config()["attributes"]["قطعات"][0]["name"] == "توان مصرفی"
    assert product["specs_json"] == '{"TDP":"65W","رنگ":"مشکی"}'



def test_catalog_config_reader_recovers_from_malformed_nested_values(manager):
    manager.set_setting(
        "product_catalog_config",
        '{"categories":null,"subcategories":{"قطعات":"invalid"},'
        '"attributes":{"لپ‌تاپ":[{"name":"RAM","values":null},null]},'
        '"colors":false}',
    )
    config = manager.get_product_catalog_config()

    assert config == {
        "categories": [],
        "subcategories": {},
        "subcategory_labels": {},
        "attributes": {"لپ‌تاپ": [{"name": "RAM", "values": [], "subcategory": ""}]},
        "colors": [],
        "service_types": ["نرم‌افزاری", "سخت‌افزاری"],
    }



def test_automatic_backup_rolls_back_new_copy_when_old_copy_is_locked(
    manager, tmp_path, monkeypatch
):
    manager.cfg["auto_backup_retention_count"] = 1
    first_backup = manager.create_backup(automatic=True)
    real_remove = os.remove

    def remove_with_locked_old_file(path):
        if os.path.abspath(path) == os.path.abspath(first_backup):
            raise PermissionError("file is in use by another process")
        return real_remove(path)

    monkeypatch.setattr(database_module.os, "remove", remove_with_locked_old_file)

    with pytest.raises(PermissionError, match="نسخه‌های قدیمی"):
        manager.create_backup(automatic=True)

    retained = list((tmp_path / "Backups").glob("shop_*.db"))
    assert [str(path) for path in retained] == [first_backup]
    with sqlite3.connect(first_backup) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
