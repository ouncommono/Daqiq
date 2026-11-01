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

    assert backup_path == str(tmp_path / "AutoBackup_shop.db")
    with sqlite3.connect(backup_path) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM products WHERE id=?", (product_id,)).fetchone()[0] == 1


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
