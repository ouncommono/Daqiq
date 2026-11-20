import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

import database as database_module
from database import DatabaseManager
from exporter import export_safe_inventory_excel
from openpyxl import load_workbook


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


def create_employee(manager, name="کاربر آزمون"):
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
    assert manager.generate_next_code("sales", "invoice_number", "INV-", 1001) == "INV-1001"
    assert manager.generate_next_code("service_catalog", "code", "S-", 1001) == "S-1001"


def test_new_schema_tracks_creation_and_update_activity(manager):
    product_id = create_product(manager, "P-ACTIVITY")
    with manager.get_connection() as conn:
        product = conn.execute(
            "SELECT created_at, updated_at FROM products WHERE id=?", (product_id,)
        ).fetchone()
        index_names = {
            row["name"] for row in conn.execute("PRAGMA index_list(products)")
        }
        assert {"idx_products_activity"} <= index_names
        created_at = product["created_at"]
        first_updated_at = product["updated_at"]
        assert created_at
        assert first_updated_at

        conn.execute(
            "UPDATE products SET description=? WHERE id=?",
            ("changed", product_id),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT created_at, updated_at FROM products WHERE id=?", (product_id,)
        ).fetchone()

    assert updated["created_at"] == created_at
    assert updated["updated_at"] > first_updated_at


def test_colleague_inventory_export_honors_selected_columns(manager, tmp_path):
    product_id = create_product(manager, "P-EXPORT")
    create_batch(manager, product_id, code="C-EXPORT", suggested=175)
    output_path = tmp_path / "colleague-inventory.xlsx"

    export_safe_inventory_excel(
        manager,
        str(output_path),
        included_columns=["code", "suggested_price"],
    )

    workbook = load_workbook(output_path, read_only=True)
    worksheet = workbook["موجودی همکار"]
    assert [cell.value for cell in worksheet[2]] == [
        "کد کالا", "قیمت فروش (پیشنهادی)"
    ]
    assert [cell.value for cell in worksheet[3]] == ["P-EXPORT", 175]
    workbook.close()


def test_purchase_batch_crud_is_atomic_and_foreign_key_safe(manager):
    product_id = create_product(manager, "P-PURCHASE-ATOMIC")

    with pytest.raises((sqlite3.IntegrityError, database_module.sqlite3.IntegrityError)):
        manager.add_batch(
            "C-FAILED-ATOMIC", 999999, None, None, "PO-FAIL", "1405/01/01",
            2, 100, 20, 150, 20, supplier_name="تأمین‌کننده تراکنش ناموفق",
        )

    with manager.get_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM suppliers WHERE name=?",
            ("تأمین‌کننده تراکنش ناموفق",),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM batches WHERE batch_code='C-FAILED-ATOMIC'"
        ).fetchone()[0] == 0

    batch_code = manager.add_batch(
        None, product_id, None, None, "PO-ATOMIC", "1405/01/02",
        2, 100, 20, 150, 50, initial_specs="RAM: 8GB",
        notes="خرید آزمایشی", colors=["مشکی"],
        supplier_name="شرکت خرید اتمی",
    )
    with manager.get_connection() as conn:
        batch = conn.execute(
            "SELECT id, supplier_id, supplier_name_snapshot, remaining_qty, paid_amount "
            "FROM batches WHERE batch_code=?",
            (batch_code,),
        ).fetchone()
        batch_id = int(batch["id"])
        payment = conn.execute(
            "SELECT amount, ref_type, ref_id FROM payments "
            "WHERE ref_type='batch' AND ref_id=?",
            (batch_id,),
        ).fetchone()
    assert batch["supplier_id"] is not None
    assert batch["supplier_name_snapshot"] == "شرکت خرید اتمی"
    assert batch["remaining_qty"] == 2
    assert batch["paid_amount"] == 50
    assert payment["amount"] == 50
    assert payment["ref_type"] == "batch"

    manager.update_batch(
        batch_id, None, None, "PO-EDITED", "1405/01/03",
        4, 120, 40, 180, 80, "SERIAL-EDITED", "یادداشت اصلاح‌شده",
        product_id=product_id, initial_specs="RAM: 16GB",
        colors=["سفید"], supplier_name="تأمین‌کننده به‌روزشده",
    )
    with manager.get_connection() as conn:
        updated = conn.execute(
            "SELECT supplier_id, supplier_name_snapshot, initial_qty, remaining_qty, "
            "unit_purchase_price, extra_cost_total, paid_amount, settlement_status, colors_json "
            "FROM batches WHERE id=?",
            (batch_id,),
        ).fetchone()
        supplier = conn.execute(
            "SELECT name FROM suppliers WHERE id=?", (updated["supplier_id"],)
        ).fetchone()
    assert supplier["name"] == "تأمین‌کننده به‌روزشده"
    assert updated["supplier_name_snapshot"] == "تأمین‌کننده به‌روزشده"
    assert updated["initial_qty"] == 4
    assert updated["remaining_qty"] == 4
    assert updated["unit_purchase_price"] == 120
    assert updated["extra_cost_total"] == 40
    assert updated["paid_amount"] == 80
    assert updated["settlement_status"] == "تسویه جزئی"
    assert json.loads(updated["colors_json"]) == ["سفید"]
    with manager.get_connection() as conn:
        payment_amount = conn.execute(
            "SELECT SUM(amount) FROM payments WHERE ref_type='batch' AND ref_id=?",
            (batch_id,),
        ).fetchone()[0]
    assert payment_amount == 80

    create_sale(manager, product_id, batch_id)
    with manager.get_connection() as conn:
        conn.execute(
            "UPDATE batches SET returned_qty=1, remaining_qty=2 WHERE id=?",
            (batch_id,),
        )
        conn.commit()
    with pytest.raises(ValueError, match="مجموع تعداد فروخته‌شده و مرجوعی"):
        manager.update_batch(
            batch_id, None, None, "PO-EDITED", "1405/01/03",
            1, 120, 40, 180, 80, "SERIAL", "note",
        )

    manager.delete_batch(batch_id)
    with manager.get_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM batches WHERE id=?", (batch_id,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM sales WHERE batch_id=?", (batch_id,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM payments WHERE ref_type='batch' AND ref_id=?",
            (batch_id,),
        ).fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_concurrent_automatic_purchase_codes_are_serialized(manager):
    product_id = create_product(manager, "P-PURCHASE-CONCURRENT")

    def register_purchase(index):
        return manager.add_batch(
            None, product_id, None, None, f"PO-{index}", "1405/01/04",
            1, 100, 0, 150, 0,
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        codes = list(executor.map(register_purchase, range(12)))

    assert len(codes) == 12
    assert len(set(codes)) == 12
    with manager.get_connection() as conn:
        persisted = conn.execute(
            "SELECT COUNT(*) FROM batches WHERE product_id=?", (product_id,)
        ).fetchone()[0]
        assert persisted == 12
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


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


def test_v3_schema_initialization_is_idempotent_and_keeps_upgrade_column_order(manager):
    with manager.get_connection() as conn:
        before = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(upgrades)").fetchall()
        ]

    manager.init_db()

    with manager.get_connection() as conn:
        after = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(upgrades)").fetchall()
        ]
        version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert after == before
    assert after == [
        "id", "target_batch_id", "part_batch_id", "technician_id", "target_qty",
        "part_qty_used", "stock_deducted_qty", "part_unit_cost", "labor_cost_unit",
        "added_cost_unit", "upgrade_date", "serial_number", "manual_part_description",
        "old_specs", "new_specs", "notes", "created_at", "updated_at",
    ]
    assert version == 470


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


def test_v3_application_config_records_release_and_preserves_current_preferences(manager):
    manager.cfg["default_profit_pct"] = 35
    manager.cfg["zero_append_count"] = 4
    manager.cfg["default_window_maximized"] = False
    manager.cfg["require_login_password"] = True
    manager._normalize_application_config()

    assert manager.cfg["default_profit_pct"] == 35
    assert manager.cfg["zero_append_count"] == 4
    assert manager.cfg["default_window_maximized"] is False
    assert manager.cfg["require_login_password"] is True
    assert manager.cfg["app_version"] == "4.7.0"
    assert manager.cfg["schema_version"] == 470
    assert manager.cfg["config_schema_version"] == 2


def test_v3_config_normalization_preserves_zero_extra_price_count(manager):
    manager.cfg["zero_append_count"] = 0
    manager._normalize_application_config()
    assert manager.cfg["zero_append_count"] == 0
    assert manager.cfg["config_schema_version"] == 2


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


def test_v3_schema_initialization_does_not_delete_employee_records(manager):
    expected = {
        "فروشنده اول", "فروشنده دوم", "کاربر واقعی", "مدیر واقعی",
    }
    with manager.get_connection() as conn:
        for name, role, permission in (
            ("فروشنده اول", "مدیر / فروشنده", "دسترسی کامل"),
            ("فروشنده دوم", "فروشنده", "دسترسی کامل"),
            ("کاربر واقعی", "فروشنده", "فروش و خدمات"),
            ("مدیر واقعی", "مدیر / فروشنده", "دسترسی کامل"),
        ):
            conn.execute(
                "INSERT INTO employees (name, role, permissions) VALUES (?, ?, ?)",
                (name, role, permission),
            )
        conn.commit()

    manager.init_db()

    with manager.get_connection() as conn:
        names = {
            row["name"] for row in conn.execute("SELECT name FROM employees").fetchall()
        }
    assert names == expected


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
    assert config["service_types"] == []



def test_v3_reinitialization_preserves_user_suppliers_and_linked_purchases(manager, tmp_path):
    product_id = create_product(manager, "P-V2-SUPPLIER")
    with manager.get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO suppliers (name, phone, address, notes) VALUES (?, ?, ?, ?)",
            ("تأمین‌کننده بازار", "021-88990011", "تهران", "ورودی کاربر"),
        )
        supplier_id = int(cursor.lastrowid)
        conn.commit()

    manager.add_batch(
        "C-V2-SUPPLIER", product_id, supplier_id, None, "PO-V2", "1405/01/01",
        2, 100, 0, 150, 0, "", "RAM:8GB", "خرید آزمون", "تسویه‌نشده",
    )
    manager.init_db()

    with manager.get_connection() as conn:
        supplier_count = conn.execute(
            "SELECT COUNT(*) FROM suppliers WHERE id=?", (supplier_id,)
        ).fetchone()[0]
        batch = conn.execute(
            "SELECT supplier_id, supplier_name_snapshot FROM batches "
            "WHERE batch_code='C-V2-SUPPLIER'"
        ).fetchone()

    assert supplier_count == 1
    assert batch["supplier_id"] == supplier_id
    assert batch["supplier_name_snapshot"] == "تأمین‌کننده بازار"


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
        "attributes": {"لپ‌تاپ": [{"name": "RAM", "values": [], "subcategory": ""}]},
        "colors": [],
        "service_types": [],
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

def test_service_discount_and_receivable_follow_settlement_status():
    assert database_module.service_financial_breakdown(
        1000, 850, "تسویه‌شده"
    ) == (-150, 0)
    assert database_module.service_financial_breakdown(
        1000, 1150, "تسویه‌شده"
    ) == (150, 0)
    assert database_module.service_financial_breakdown(
        1000, 400, "تسویه جزئی"
    ) == (0, 600)
    assert database_module.service_financial_breakdown(
        1000, 0, "تسویه‌نشده"
    ) == (0, 1000)
    assert database_module.receivable_balance(
        1000, 400, "تسویه‌شده"
    ) == 0
    assert database_module.receivable_balance(
        1000, 400, "تسویه جزئی"
    ) == 600


def test_colleague_inventory_export_defaults_to_product_and_batch_codes(manager, tmp_path):
    product_id = create_product(manager, "P-EXPORT-DEFAULT")
    create_batch(manager, product_id, code="C-EXPORT-DEFAULT")
    output_path = tmp_path / "colleague-default.xlsx"

    export_safe_inventory_excel(manager, str(output_path))

    workbook = load_workbook(output_path, read_only=True)
    worksheet = workbook.active
    headers = [cell.value for cell in worksheet[2]]
    row = [cell.value for cell in worksheet[3]]
    assert headers[:2] == ["کد کالا", "کد محموله"]
    assert "قیمت فروش پیشنهادی" not in headers
    assert "موجودی" not in headers
    assert row[:2] == ["P-EXPORT-DEFAULT", "C-EXPORT-DEFAULT"]
    workbook.close()


def test_service_update_recalculates_net_profit_from_received_amount(manager):
    manager.save_service_catalog(
        None, "S-FIN-TEST", "نرم‌افزاری", "خدمت آزمون", 1000, 100, ""
    )
    with manager.get_connection() as conn:
        service_id = conn.execute(
            "SELECT id FROM service_catalog WHERE code=?", ("S-FIN-TEST",)
        ).fetchone()["id"]

    invoice = manager.add_service_record(
        "", service_id, None, None, "مشتری آزمون", 1000, 100, 850,
        "1405/01/01 10:00:00", "", "تسویه‌شده",
    )
    with manager.get_connection() as conn:
        record = conn.execute(
            "SELECT id, net_profit FROM service_records WHERE invoice_number=?",
            (invoice,),
        ).fetchone()
        assert record["net_profit"] == 750
        record_id = record["id"]

    manager.update_service_record(
        record_id, None, "مشتری آزمون", 1200, 100, 1100, "", "تسویه‌شده"
    )
    with manager.get_connection() as conn:
        record = conn.execute(
            "SELECT net_profit, service_fee, paid_amount, settlement_status "
            "FROM service_records WHERE id=?",
            (record_id,),
        ).fetchone()
    assert record["net_profit"] == 1000
    assert database_module.service_financial_breakdown(
        record["service_fee"], record["paid_amount"], record["settlement_status"]
    ) == (-100, 0)

def test_fresh_schema_has_v3_physical_column_order_and_metadata(manager):
    expected_columns = {
        "employees": [
            "id", "name", "role", "phone", "is_active", "permissions",
            "password", "created_at", "updated_at",
        ],
        "products": [
            "id", "code", "serial_number", "name", "category", "sub_category", "brand", "model",
            "specs_json", "description", "reorder_point", "default_profit_pct",
            "is_active", "created_at", "updated_at",
        ],
        "batches": [
            "id", "batch_code", "product_id", "serial_numbers", "supplier_id", "buyer_employee_id",
            "invoice_number", "purchase_date", "initial_qty", "sold_qty",
            "returned_qty", "remaining_qty", "unit_purchase_price", "extra_cost_total",
            "upgrade_cost_unit", "unit_cost_price", "suggested_sell_price", "profit_pct",
            "paid_amount", "settlement_status", "colors_json",
            "initial_specs", "final_specs", "supplier_name_snapshot", "notes",
            "created_at", "updated_at",
        ],
        "upgrades": [
            "id", "target_batch_id", "part_batch_id", "technician_id", "target_qty",
            "part_qty_used", "stock_deducted_qty", "part_unit_cost", "labor_cost_unit",
            "added_cost_unit", "upgrade_date", "serial_number", "manual_part_description",
            "old_specs", "new_specs", "notes", "created_at", "updated_at",
        ],
        "sales": [
            "id", "invoice_number", "product_id", "batch_id", "serial_number", "seller_employee_id",
            "customer_name", "customer_phone", "qty", "returned_qty", "suggested_unit_price",
            "actual_unit_price", "unit_cost_price", "unit_discount", "total_discount",
            "price_Markup_unit", "unit_profit", "total_profit", "total_amount",
            "paid_amount", "settlement_status", "sale_datetime", "warranty_company",
            "warranty_start", "warranty_months", "warranty_days", "warranty_end",
            "specifications", "colors_json", "notes",
            "created_at", "updated_at",
        ],
        "service_records": [
            "id", "invoice_number", "service_id", "seller_employee_id",
            "technician_employee_id", "service_type", "service_name", "customer_name",
            "historical_tariff", "service_fee", "side_cost", "paid_amount", "net_profit",
            "settlement_status", "service_datetime", "description", "created_at",
            "updated_at",
        ],
    }
    with manager.get_connection() as conn:
        for table_name, expected in expected_columns.items():
            columns = [
                row["name"]
                for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            ]
            assert columns == expected, table_name
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 470
        product_indexes = {
            row["name"] for row in conn.execute("PRAGMA index_list(products)")
        }
        assert "idx_products_taxonomy" in product_indexes
        metadata = dict(conn.execute("SELECT key, value FROM settings").fetchall())
        assert metadata["app_version"] == "4.7.0"
        assert metadata["schema_version"] == "470"


def test_v3_schema_creates_normalized_access_scope_tables(manager):
    with manager.get_connection() as conn:
        tables = {
            row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {
            "access_level_data_scopes",
            "access_level_scope_levels",
            "access_level_scope_users",
        }.issubset(tables)
        scope_columns = [
            row["name"] for row in conn.execute(
                "PRAGMA table_info(access_level_data_scopes)"
            ).fetchall()
        ]
        assert scope_columns == ["access_level_name", "mode"]
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 470


def test_v3_rejects_pre_v3_database_without_attempting_migration(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    legacy_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(legacy_path)
    try:
        conn.execute("CREATE TABLE legacy_records (id INTEGER PRIMARY KEY, value TEXT)")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="نسخه 4.7.0"):
        DatabaseManager(str(legacy_path))


def test_first_upgrade_rollback_restores_product_base_specifications(manager):
    product_id = create_product(manager, "P-BASE-SPECS")
    target_id = create_batch(manager, product_id, code="C-BASE-SPECS")
    base_specs = "CPU: Core i5 | RAM: 8GB"
    with manager.get_connection() as conn:
        conn.execute(
            "UPDATE batches SET initial_specs=?, final_specs='' WHERE id=?",
            (base_specs, target_id),
        )
        conn.commit()

    manager.upgrade_batch_product(
        target_id, 1, None, 1, 0, "CPU: Core i7 | RAM: 16GB",
        "1405/01/10", None, consume_stock=False,
        manual_part_description="قطعه دستی",
    )
    with manager.get_connection() as conn:
        upgrade_id = conn.execute(
            "SELECT id FROM upgrades WHERE target_batch_id=?", (target_id,)
        ).fetchone()["id"]

    manager.revert_upgrade(int(upgrade_id))
    with manager.get_connection() as conn:
        restored = conn.execute(
            "SELECT final_specs FROM batches WHERE id=?", (target_id,)
        ).fetchone()["final_specs"]
    assert restored == base_specs


def test_bulk_inventory_quantities_are_atomic_for_create_edit_and_delete(manager):
    product_id = create_product(manager, "P-BULK-QTY")
    batch_id = create_batch(manager, product_id, code="C-BULK-QTY", quantity=1)
    created_batch_id = create_batch(
        manager, product_id, code="C-BULK-CREATE", quantity=10
    )
    with manager.get_connection() as conn:
        created = conn.execute(
            "SELECT initial_qty, remaining_qty FROM batches WHERE id=?",
            (created_batch_id,),
        ).fetchone()
    assert (created["initial_qty"], created["remaining_qty"]) == (10, 10)

    manager.update_batch(
        batch_id, None, None, "PO-BULK", "1405/01/01",
        10, 100, 0, 150, 0, "", "bulk quantity",
    )
    manager.update_batch(
        batch_id, None, None, "PO-BULK", "1405/01/01",
        50, 100, 0, 150, 0, "", "bulk quantity",
    )
    with manager.get_connection() as conn:
        batch = conn.execute(
            "SELECT initial_qty, sold_qty, remaining_qty FROM batches WHERE id=?",
            (batch_id,),
        ).fetchone()
    assert (batch["initial_qty"], batch["sold_qty"], batch["remaining_qty"]) == (50, 0, 50)

    manager.add_sale(
        "INV-BULK-QTY", product_id, batch_id, None, "مشتری آزمون",
        10, 150, 150, 0, "1405/01/02 12:00:00",
        settlement_status="تسویه‌نشده",
    )
    with manager.get_connection() as conn:
        sale_id = int(conn.execute(
            "SELECT id FROM sales WHERE invoice_number='INV-BULK-QTY'"
        ).fetchone()["id"])
        stock_after_create = conn.execute(
            "SELECT sold_qty, remaining_qty FROM batches WHERE id=?", (batch_id,)
        ).fetchone()
    assert (stock_after_create["sold_qty"], stock_after_create["remaining_qty"]) == (10, 40)

    manager.update_sale(
        sale_id, None, "مشتری آزمون", 25, 150, 150, 0,
        "", "", 0, "", "", "", "تسویه‌نشده",
    )
    with manager.get_connection() as conn:
        stock_after_increase = conn.execute(
            "SELECT sold_qty, remaining_qty FROM batches WHERE id=?", (batch_id,)
        ).fetchone()
    assert (stock_after_increase["sold_qty"], stock_after_increase["remaining_qty"]) == (25, 25)

    manager.update_sale(
        sale_id, None, "مشتری آزمون", 5, 150, 150, 0,
        "", "", 0, "", "", "", "تسویه‌نشده",
    )
    with manager.get_connection() as conn:
        stock_after_decrease = conn.execute(
            "SELECT sold_qty, remaining_qty FROM batches WHERE id=?", (batch_id,)
        ).fetchone()
    assert (stock_after_decrease["sold_qty"], stock_after_decrease["remaining_qty"]) == (5, 45)

    manager.delete_sale(sale_id)
    with manager.get_connection() as conn:
        stock_after_delete = conn.execute(
            "SELECT sold_qty, remaining_qty FROM batches WHERE id=?", (batch_id,)
        ).fetchone()
    assert (stock_after_delete["sold_qty"], stock_after_delete["remaining_qty"]) == (0, 50)

    manager.delete_product(product_id)
    with manager.get_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM products WHERE id=?", (product_id,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM batches WHERE id IN (?, ?)",
            (batch_id, created_batch_id),
        ).fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert manager._batch_integer("۱۰", "تعداد", minimum=1) == 10
    assert manager._batch_integer("۵۰", "تعداد", minimum=1) == 50


def test_upgrade_can_apply_specs_without_consuming_available_part_stock(manager):
    product_id = create_product(manager)
    target_id = create_batch(manager, product_id, code="C-NO-CONSUME-TARGET", quantity=2)
    part_id = create_batch(manager, product_id, code="C-NO-CONSUME-PART", quantity=4)
    with manager.get_connection() as conn:
        part_before = conn.execute(
            "SELECT remaining_qty, sold_qty FROM batches WHERE id=?", (part_id,)
        ).fetchone()

    manager.upgrade_batch_product(
        target_id, 1, part_id, 2, 25, "RAM: 16GB DDR5",
        "1405/01/03", None, consume_stock=False,
    )

    with manager.get_connection() as conn:
        part_after = conn.execute(
            "SELECT remaining_qty, sold_qty FROM batches WHERE id=?", (part_id,)
        ).fetchone()
        upgrade = conn.execute(
            "SELECT id, stock_deducted_qty FROM upgrades ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert part_after["remaining_qty"] == part_before["remaining_qty"]
    assert part_after["sold_qty"] == part_before["sold_qty"]
    assert upgrade["stock_deducted_qty"] == 0

    manager.revert_upgrade(int(upgrade["id"]))
    with manager.get_connection() as conn:
        part_reverted = conn.execute(
            "SELECT remaining_qty, sold_qty FROM batches WHERE id=?", (part_id,)
        ).fetchone()
    assert part_reverted["remaining_qty"] == part_before["remaining_qty"]
    assert part_reverted["sold_qty"] == part_before["sold_qty"]



def test_v330_greenfield_schema_contracts_and_stock_balance_constraints(manager):
    """Lock down every fresh-install column layout and the core stock invariants."""
    expected_columns = {
        "settings": ["key", "value"],
        "employees": [
            "id", "name", "role", "phone", "is_active", "permissions",
            "password", "created_at", "updated_at",
        ],
        "access_level_data_scopes": ["access_level_name", "mode"],
        "access_level_scope_levels": [
            "access_level_name", "selected_access_level_name",
        ],
        "access_level_scope_users": ["access_level_name", "employee_id"],
        "suppliers": [
            "id", "name", "phone", "address", "notes", "created_at", "updated_at",
        ],
        "customers": [
            "id", "name", "phone", "notes", "created_at", "updated_at",
        ],
        "products": [
            "id", "code", "serial_number", "name", "category", "sub_category", "brand", "model",
            "specs_json", "description", "reorder_point", "default_profit_pct",
            "is_active", "created_at", "updated_at",
        ],
        "batches": [
            "id", "batch_code", "product_id", "serial_numbers", "supplier_id", "buyer_employee_id",
            "invoice_number", "purchase_date", "initial_qty", "sold_qty",
            "returned_qty", "remaining_qty", "unit_purchase_price", "extra_cost_total",
            "upgrade_cost_unit", "unit_cost_price", "suggested_sell_price", "profit_pct",
            "paid_amount", "settlement_status", "colors_json",
            "initial_specs", "final_specs", "supplier_name_snapshot", "notes",
            "created_at", "updated_at",
        ],
        "upgrades": [
            "id", "target_batch_id", "part_batch_id", "technician_id", "target_qty",
            "part_qty_used", "stock_deducted_qty", "part_unit_cost", "labor_cost_unit",
            "added_cost_unit", "upgrade_date", "serial_number", "manual_part_description",
            "old_specs", "new_specs", "notes", "created_at", "updated_at",
        ],
        "sales": [
            "id", "invoice_number", "product_id", "batch_id", "serial_number", "seller_employee_id",
            "customer_name", "customer_phone", "qty", "returned_qty", "suggested_unit_price",
            "actual_unit_price", "unit_cost_price", "unit_discount", "total_discount",
            "price_Markup_unit", "unit_profit", "total_profit", "total_amount",
            "paid_amount", "settlement_status", "sale_datetime", "warranty_company",
            "warranty_start", "warranty_months", "warranty_days", "warranty_end",
            "specifications", "colors_json", "notes",
            "created_at", "updated_at",
        ],
        "service_catalog": [
            "id", "code", "service_type", "name", "default_fee", "default_side_cost",
            "description", "is_active", "created_at", "updated_at",
        ],
        "service_price_history": [
            "id", "service_id", "change_date", "old_fee", "new_fee",
            "created_at", "updated_at",
        ],
        "service_records": [
            "id", "invoice_number", "service_id", "seller_employee_id",
            "technician_employee_id", "service_type", "service_name", "customer_name",
            "historical_tariff", "service_fee", "side_cost", "paid_amount", "net_profit",
            "settlement_status", "service_datetime", "description", "created_at",
            "updated_at",
        ],
        "payments": [
            "id", "ref_type", "ref_id", "amount", "payment_date",
            "notes", "created_at", "updated_at",
        ],
        "audit_logs": [
            "id", "action_time", "action_type", "details", "created_at", "updated_at",
        ],
    }

    product_id = create_product(manager, "P-SCHEMA-CONTRACT")
    batch_id = create_batch(
        manager, product_id, code="C-SCHEMA-CONTRACT", quantity=10
    )
    with manager.get_connection() as conn:
        for table_name, expected in expected_columns.items():
            actual = [
                row["name"]
                for row in conn.execute(
                    f"PRAGMA table_info({table_name})"
                ).fetchall()
            ]
            assert actual == expected, table_name

        # Natural/composite-key lookup tables do not need a duplicate rowid B-tree.
        for table_name in (
            "settings", "access_level_data_scopes",
            "access_level_scope_levels", "access_level_scope_users",
        ):
            ddl = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()["sql"]
            assert "WITHOUT ROWID" in ddl.upper(), table_name

        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 470

        # A stock row cannot represent a quantity that disagrees with its
        # initial, sold and supplier-returned aggregates.
        with pytest.raises((sqlite3.IntegrityError, database_module.sqlite3.IntegrityError)):
            conn.execute(
                "UPDATE batches SET remaining_qty=remaining_qty-1 WHERE id=?",
                (batch_id,),
            )

    # Supported application writes remain valid for direct multi-unit edits.
    manager.update_batch(
        batch_id, None, None, "PO-SCHEMA", "1405/01/01",
        2, 100, 0, 150, 0, "", "schema quantity edit",
    )
    with manager.get_connection() as conn:
        row = conn.execute(
            "SELECT initial_qty, sold_qty, returned_qty, remaining_qty "
            "FROM batches WHERE id=?",
            (batch_id,),
        ).fetchone()
    assert tuple(row) == (2, 0, 0, 2)
