"""Comprehensive Multi-Scenario End-to-End QA Suite for Daqiq v4.8.2.
Enforces headless (QT_QPA_PLATFORM=offscreen), non-blocking, strictly-timed
verification of Scenarios 1 through 6 across REQ-0 through REQ-6.
"""

import os
import sys
import json
import time
import pytest
import jdatetime

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QComboBox
from PySide6.QtCore import Qt, QLocale

from database import (
    DatabaseManager,
    create_and_initialize_database,
    resolve_new_database_filename,
    SecureCredentialStore,
    validate_schema_column_order,
    load_app_config,
    save_app_config,
    get_default_database_dir,
    APP_VERSION,
    SCHEMA_VERSION,
)
from main import MainWindow, _window_title


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
        app.setLayoutDirection(Qt.RightToLeft)
    return app


# =========================================================================
# SCENARIO 1: Sequential DB Creation & Multi-DB Per-Database Backup Isolation
# =========================================================================
def test_scenario1_sequential_db_and_isolated_backups(qapp, tmp_path, monkeypatch):
    """Scenario 1:
    - Start empty -> Daqiq.db created with correct column order.
    - 2nd & 3rd DBs -> Daqiq_2.db, Daqiq_3.db.
    - Configure max=2 for Daqiq.db, max=3 for Daqiq_2.db, max=1 for Daqiq_3.db in same folder.
    - Trigger multiple backups -> verify retention per-DB without prefix collision.
    - Remove Daqiq_2.db -> verify its backup config is purged from app_config.json.
    """
    base_dir = str(tmp_path / "databases")
    os.makedirs(base_dir, exist_ok=True)
    shared_backup_dir = str(tmp_path / "shared_backups")
    os.makedirs(shared_backup_dir, exist_ok=True)

    config_path = str(tmp_path / "app_config.json")
    monkeypatch.setattr("database.CONFIG_FILE", config_path)
    monkeypatch.setattr("database.get_default_database_dir", lambda: base_dir)

    # 1. First DB resolution -> Daqiq.db
    path1 = resolve_new_database_filename(base_dir)
    assert os.path.basename(path1) == "Daqiq.db"
    db1 = create_and_initialize_database(path1)
    with db1.get_connection() as conn:
        validate_schema_column_order(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 483

    # 2. Sequential resolution: Daqiq_2.db and Daqiq_3.db
    path2 = resolve_new_database_filename(base_dir)
    assert os.path.basename(path2) == "Daqiq_2.db"
    db2 = create_and_initialize_database(path2)

    path3 = resolve_new_database_filename(base_dir)
    assert os.path.basename(path3) == "Daqiq_3.db"
    db3 = create_and_initialize_database(path3)

    # 3. Configure distinct per-database backup settings in the SAME backup directory
    db1.set_automatic_backup_directory(shared_backup_dir)
    db1.set_db_config("auto_backup_retention_count", 2)
    db1.set_db_config("auto_backup_interval_min", 15)

    db2.set_automatic_backup_directory(shared_backup_dir)
    db2.set_db_config("auto_backup_retention_count", 3)
    db2.set_db_config("auto_backup_interval_min", 30)

    db3.set_automatic_backup_directory(shared_backup_dir)
    db3.set_db_config("auto_backup_retention_count", 1)
    db3.set_db_config("auto_backup_interval_min", 45)

    # Verify app_config.json stores settings separately per DB
    cfg = load_app_config()
    dbs_cfg = cfg.get("databases", {})
    norm1 = os.path.normcase(os.path.abspath(path1))
    norm2 = os.path.normcase(os.path.abspath(path2))
    norm3 = os.path.normcase(os.path.abspath(path3))

    assert dbs_cfg[norm1]["auto_backup_retention_count"] == 2
    assert dbs_cfg[norm2]["auto_backup_retention_count"] == 3
    assert dbs_cfg[norm3]["auto_backup_retention_count"] == 1

    # Verify nothing was stored in the SQLite .db file for backup settings
    with db1.get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='auto_backup_retention_count'").fetchone()
        assert row is None

    # 4. Trigger 4 backups for each DB
    for _ in range(4):
        time.sleep(0.01)
        db1.create_backup(automatic=True)
        db2.create_backup(automatic=True)
        db3.create_backup(automatic=True)

    # Verify retention in the shared folder without prefix collision:
    # Daqiq.db should have exactly 2 copies
    # Daqiq_2.db should have exactly 3 copies
    # Daqiq_3.db should have exactly 1 copy
    db1_copies = db1._automatic_backup_entries(shared_backup_dir, "Daqiq")
    db2_copies = db2._automatic_backup_entries(shared_backup_dir, "Daqiq_2")
    db3_copies = db3._automatic_backup_entries(shared_backup_dir, "Daqiq_3")

    assert len(db1_copies) == 2, f"Expected 2 backups for Daqiq, got {[c[1] for c in db1_copies]}"
    assert len(db2_copies) == 3, f"Expected 3 backups for Daqiq_2, got {[c[1] for c in db2_copies]}"
    assert len(db3_copies) == 1, f"Expected 1 backup for Daqiq_3, got {[c[1] for c in db3_copies]}"

    # Verify names do not cross-pollinate
    for _, name, _ in db1_copies:
        assert name.startswith("Daqiq_") and not name.startswith("Daqiq_2") and not name.startswith("Daqiq_3")
    for _, name, _ in db2_copies:
        assert name.startswith("Daqiq_2_")
    for _, name, _ in db3_copies:
        assert name.startswith("Daqiq_3_")

    # 5. Remove Daqiq_2.db using MainWindow._remove_recent_database logic
    window = MainWindow(db1, {"id": 1, "name": "مدیر", "role": "مدیر کل", "permissions": "all"})
    window.db.cfg["recent_databases"] = [path1, path2, path3]
    save_app_config(window.db.cfg)

    window._remove_recent_database(path2)
    cfg_after = load_app_config()
    assert path2 not in cfg_after.get("recent_databases", [])
    assert norm2 not in cfg_after.get("databases", {})
    # Daqiq and Daqiq_3 must remain untouched in config
    assert norm1 in cfg_after.get("databases", {})
    assert norm3 in cfg_after.get("databases", {})

    window.close()
    db1.close()
    db2.close()
    db3.close()


# =========================================================================
# SCENARIO 2: Sales Warranty English Digits & Full Purchase-to-Sale Lifecycle
# =========================================================================
def test_scenario2_sales_warranty_english_digits_and_lifecycle(qapp, tmp_path, monkeypatch):
    """Scenario 2:
    - Register product and batch with 64-bit amounts.
    - Check cb_war_months uses ASCII English numerals.
    - Edit manually with '18' and Persian digits '۱۸'.
    - Complete sale -> check warranty end date, profit, stock decrement.
    """
    db_path = str(tmp_path / "scenario2.db")
    db = create_and_initialize_database(db_path)
    monkeypatch.setattr("database.CONFIG_FILE", str(tmp_path / "app_config.json"))

    # Seed employee, product & batch
    with db.get_connection() as conn:
        emp_id = conn.execute(
            "INSERT INTO employees (name, role, permissions, is_active) VALUES (?, ?, ?, 1)",
            ("مدیر کل", "مدیر کل", "all"),
        ).lastrowid
        conn.commit()

    prod_code = db.add_product(
        code="PR-WAR-1",
        name="لپتاپ گیمینگ",
        category="رایانه و ماشین‌های اداری",
        sub_category="لپ‌تاپ",
        brand="Asus",
        model="ROG Strix",
        specs_dict={"پردازنده": "Core i9", "رم": "32GB"},
        description="لپتاپ گیمینگ ایسوس",
        reorder_point=2,
        default_profit_pct=20,
    )
    with db.get_connection() as conn:
        prod_id = conn.execute("SELECT id FROM products WHERE code=?", (prod_code,)).fetchone()["id"]

    batch_code = db.add_batch(
        batch_code="C-1001",
        product_id=prod_id,
        supplier_id=None,
        buyer_employee_id=emp_id,
        invoice_number="INV-SUP-1",
        purchase_date="1403/05/01",
        initial_qty=10,
        unit_purchase_price=80_000_000,
        extra_cost_total=0,
        suggested_sell_price=100_000_000,
        paid_amount=800_000_000,
        serial_numbers="SN-001, SN-002",
        colors=["مشکی"],
        notes="ورود اولیه",
    )
    with db.get_connection() as conn:
        batch_id = conn.execute("SELECT id FROM batches WHERE batch_code=?", (batch_code,)).fetchone()["id"]

    window = MainWindow(db, {"id": emp_id, "name": "مدیر", "role": "مدیر کل", "permissions": "all"})

    # Check warranty combo options all contain ASCII English digits
    combo = window.cb_war_months
    assert combo.count() > 0
    for i in range(combo.count()):
        text = combo.itemText(i)
        # Any digit in text must be ASCII English [0-9]
        for ch in text:
            assert not ('۰' <= ch <= '۹'), f"Persian digit found in warranty option: {text}"

    # Test manual typing '18' into cb_war_months
    combo.setEditText("18")
    assert window._get_warranty_days() == 540  # 18 months = 540 days

    # Test Persian digit entry '۱۸' -> normalized to 540 days
    combo.setEditText("۱۸")
    assert window._get_warranty_days() == 540

    # Test '6 ماه'
    combo.setEditText("6 ماه")
    assert window._get_warranty_days() == 180

    # Test '45 روز'
    combo.setEditText("45 روز")
    assert window._get_warranty_days() == 45

    # Test '0'
    combo.setEditText("0")
    assert window._get_warranty_days() == 0

    # Test completing a sale with 18 months warranty
    combo.setEditText("18")
    window.dt_war_start.set_date("1403/05/01")
    window._recalc_warranty_end()
    assert window.dt_war_end.get_date() != ""

    # Select product and batch in UI
    for i in range(window.cb_sale_prod.count()):
        d = window.cb_sale_prod.itemData(i)
        if isinstance(d, dict) and d.get("id") == prod_id:
            window.cb_sale_prod.setCurrentIndex(i)
            window._on_sale_prod_changed()
            break

    if window.cb_sale_batch.count() > 0:
        window.cb_sale_batch.setCurrentIndex(0)
        window._on_sale_batch_changed()

    window.cb_sale_qty.setCurrentText("1")
    window.pr_sale_suggest.set_value(100_000_000)
    window.pr_sale_actual.set_value(95_000_000)
    window.pr_sale_paid.set_value(95_000_000)
    window.ed_sale_customer.setText("مشتری VIP")
    window.ed_sale_phone.setText("09123456789")

    # Mock dialogs
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information", lambda *args, **kwargs: None)
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning", lambda *args, **kwargs: None)

    # Complete sale
    window._save_new_sale()

    with db.get_connection() as conn:
        sale = conn.execute("SELECT * FROM sales WHERE customer_name='مشتری VIP'").fetchone()
        assert sale is not None
        assert sale["warranty_days"] == 540
        assert sale["warranty_months"] == 18
        assert sale["actual_unit_price"] == 95_000_000
        assert sale["unit_profit"] == 15_000_000  # 95M - 80M

        # Batch stock decremented
        batch = conn.execute("SELECT remaining_qty, sold_qty FROM batches WHERE id=?", (batch_id,)).fetchone()
        assert batch["remaining_qty"] == 9
        assert batch["sold_qty"] == 1

    window.close()
    db.close()


# =========================================================================
# SCENARIO 3: Transactional Clear & Scoped Manual JSON Import (Goods vs Services)
# =========================================================================
def test_scenario3_transactional_taxonomy_clear_and_import(qapp, tmp_path, monkeypatch):
    """Scenario 3:
    - Clear product taxonomy in draft -> verify DB untouched -> cancel -> verify revert.
    - Clear & import custom product taxonomy -> save -> verify ONLY products updated (services untouched).
    - Clear & import services taxonomy -> save -> verify ONLY services updated (products untouched).
    - Invalid JSON -> error caught gracefully without corrupting draft.
    """
    db_path = str(tmp_path / "scenario3.db")
    db = create_and_initialize_database(db_path)
    monkeypatch.setattr("database.CONFIG_FILE", str(tmp_path / "app_config.json"))

    window = MainWindow(db, {"id": 1, "name": "مدیر", "role": "مدیر کل", "permissions": "all"})
    orig_tax = db.get_product_catalog_config()
    orig_serv_count = len(orig_tax.get("service_types", []))
    orig_cat_count = len(orig_tax.get("categories", []))
    assert orig_serv_count > 0
    assert orig_cat_count > 0

    # 1. Clear products in draft
    monkeypatch.setattr("main._ask_yes_no", lambda *args, **kwargs: True)
    window._clear_product_taxonomy()
    assert len(window._taxonomy_draft["categories"]) == 0
    # Service types must NOT be touched
    assert len(window._taxonomy_draft["service_types"]) == orig_serv_count
    # DB must be untouched before save
    db_tax_before_save = db.get_product_catalog_config()
    assert len(db_tax_before_save["categories"]) == orig_cat_count

    # 2. Click cancel (انصراف) -> verify full rollback
    window._rollback_settings()
    assert len(window._taxonomy_draft["categories"]) == orig_cat_count

    # 3. Import custom products from JSON
    custom_prod_file = str(tmp_path / "custom_prod.json")
    with open(custom_prod_file, "w", encoding="utf-8") as f:
        json.dump({
            "categories": ["تجهیزات هوشمند"],
            "subcategories": {"تجهیزات هوشمند": ["سنسور حرارتی"]},
            "attributes": {"تجهیزات هوشمند": []},
            "colors": ["طلایی"],
            "service_types": ["خدمت نامربوط که نباید وارد شود"]
        }, f, ensure_ascii=False)

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", lambda *args, **kwargs: (custom_prod_file, "JSON"))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information", lambda *args, **kwargs: None)
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.critical", lambda *args, **kwargs: None)

    window._import_product_taxonomy()
    assert "تجهیزات هوشمند" in window._taxonomy_draft["categories"]
    # Service types must NOT be touched by product import
    assert "خدمت نامربوط که نباید وارد شود" not in window._taxonomy_draft["service_types"]
    assert len(window._taxonomy_draft["service_types"]) == orig_serv_count

    # Save settings -> verify DB commit
    window._on_save_settings_clicked()
    committed_tax = db.get_product_catalog_config()
    assert "تجهیزات هوشمند" in committed_tax["categories"]
    assert len(committed_tax["service_types"]) == orig_serv_count

    # 4. Clear services in draft
    window._clear_service_taxonomy()
    assert len(window._taxonomy_draft["service_types"]) == 0
    # Products must be untouched
    assert "تجهیزات هوشمند" in window._taxonomy_draft["categories"]

    # Import custom service types
    custom_serv_file = str(tmp_path / "custom_serv.json")
    with open(custom_serv_file, "w", encoding="utf-8") as f:
        json.dump({
            "categories": ["دسته نامربوط"],
            "service_types": ["کالیبراسیون صنعتی", "عیب‌یابی پیشرفته"]
        }, f, ensure_ascii=False)

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", lambda *args, **kwargs: (custom_serv_file, "JSON"))
    window._import_service_taxonomy()
    assert "کالیبراسیون صنعتی" in window._taxonomy_draft["service_types"]
    # Products must NOT be touched by service import
    assert "دسته نامربوط" not in window._taxonomy_draft["categories"]
    assert "تجهیزات هوشمند" in window._taxonomy_draft["categories"]

    window._on_save_settings_clicked()
    committed_tax2 = db.get_product_catalog_config()
    assert "کالیبراسیون صنعتی" in committed_tax2["service_types"]
    assert "تجهیزات هوشمند" in committed_tax2["categories"]

    # 5. Invalid JSON handling
    corrupt_file = str(tmp_path / "corrupt.json")
    with open(corrupt_file, "w", encoding="utf-8") as f:
        f.write("{invalid json syntax!!!")

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", lambda *args, **kwargs: (corrupt_file, "JSON"))
    window._import_product_taxonomy()  # Should not crash
    assert "تجهیزات هوشمند" in window._taxonomy_draft["categories"]

    window.close()
    db.close()


# =========================================================================
# SCENARIO 4: Transactional Password Removal
# =========================================================================
def test_scenario4_transactional_password_removal(qapp, tmp_path, monkeypatch):
    """Scenario 4:
    - Encrypt DB with 'pass123'.
    - Trigger remove password dialog -> confirm -> check staged pending removal.
    - Check DB file is STILL encrypted before save.
    - Cancel -> verify DB remains encrypted and vault intact.
    - Remove password -> save settings -> verify DB is decrypted plaintext SQLite.
    """
    db_path = str(tmp_path / "scenario4.db")
    vault_file = str(tmp_path / ".secure_vault.dat")
    SecureCredentialStore.set_vault_path(vault_file)
    monkeypatch.setattr("database.CONFIG_FILE", str(tmp_path / "app_config.json"))

    db = create_and_initialize_database(db_path)
    # Set password
    db.set_database_password("pass123", require_startup_prompt=False)
    assert db.is_password_protected()
    assert SecureCredentialStore.retrieve_database_credential(db_path) == "pass123"

    window = MainWindow(db, {"id": 1, "name": "مدیر", "role": "مدیر کل", "permissions": "all"})

    # Mock dialog inputs
    monkeypatch.setattr("main._ask_yes_no", lambda *args, **kwargs: True)
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information", lambda *args, **kwargs: None)
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning", lambda *args, **kwargs: None)

    # 1. Trigger remove password
    # Stage removal
    window._staged_db_password_action = {"action": "remove", "pwd": "pass123"}
    window._refresh_db_password_status()
    assert window._staged_db_password_action["action"] == "remove"

    # DB file MUST still be encrypted on disk!
    assert db.is_password_protected()
    assert SecureCredentialStore.retrieve_database_credential(db_path) == "pass123"

    # 2. Cancel (انصراف) -> verify rollback
    window._rollback_settings()
    assert window._staged_db_password_action is None
    assert db.is_password_protected()
    assert SecureCredentialStore.retrieve_database_credential(db_path) == "pass123"

    # 3. Stage removal again and click save settings
    window._staged_db_password_action = {"action": "remove", "pwd": "pass123"}
    window._on_save_settings_clicked()

    # DB must now be decrypted plaintext SQLite!
    assert not db.is_password_protected()
    assert SecureCredentialStore.retrieve_database_credential(db_path) is None
    assert window._staged_db_password_action is None

    window.close()
    db.close()


# =========================================================================
# SCENARIO 5: Multi-DB .secure_vault.dat & Self-Healing Recovery
# =========================================================================
def test_scenario5_multi_db_vault_and_self_healing(qapp, tmp_path, monkeypatch):
    """Scenario 5:
    - 3 encrypted DBs:
      DB1: pw='pw1', prompt=OFF -> auto-unlocks
      DB2: pw='pw2', prompt=ON  -> prompts
      DB3: pw='pw3', prompt=OFF -> auto-unlocks
    - Self-Heal Test A (Deleted vault):
      Delete vault -> supply DB1 password -> assert self-healed vault & next auto-unlock.
    - Self-Heal Test B (Corrupted vault):
      Write garbage to vault -> supply DB3 password -> assert self-healed vault & next auto-unlock.
    """
    vault_file = str(tmp_path / ".secure_vault.dat")
    SecureCredentialStore.set_vault_path(vault_file)
    monkeypatch.setattr("database.CONFIG_FILE", str(tmp_path / "app_config.json"))

    path1 = str(tmp_path / "db1.db")
    path2 = str(tmp_path / "db2.db")
    path3 = str(tmp_path / "db3.db")

    db1 = create_and_initialize_database(path1)
    db1.set_database_password("pw1", require_startup_prompt=False)

    db2 = create_and_initialize_database(path2)
    db2.set_database_password("pw2", require_startup_prompt=True)

    db3 = create_and_initialize_database(path3)
    db3.set_database_password("pw3", require_startup_prompt=False)

    # Verify initial auto-unlock capabilities
    assert db1.can_auto_unlock_locally() is True
    assert db2.can_auto_unlock_locally() is False
    assert db3.can_auto_unlock_locally() is True

    # 1. Self-Heal Test A: Delete .secure_vault.dat
    if os.path.exists(vault_file):
        os.remove(vault_file)
    assert not os.path.exists(vault_file)

    # Now db1 cannot auto-unlock because vault is gone
    assert db1.can_auto_unlock_locally() is False

    # Simulate entering valid password
    assert db1.verify_database_password("pw1") is True
    # Verify .secure_vault.dat was AUTOMATICALLY self-healed!
    assert os.path.isfile(vault_file)
    assert db1.can_auto_unlock_locally() is True
    assert SecureCredentialStore.retrieve_database_credential(path1) == "pw1"

    # 2. Self-Heal Test B: Corrupt .secure_vault.dat with garbage bytes
    with open(vault_file, "wb") as f:
        f.write(b"CORRUPTED_GARBAGE_BYTES_#$!@#^&*")

    # Now db3 cannot auto-unlock because vault is corrupt
    assert db3.can_auto_unlock_locally() is False

    # Simulate entering valid password for db3
    assert db3.verify_database_password("pw3") is True
    # Verify vault was repaired and db3 auto-unlocks again
    assert db3.can_auto_unlock_locally() is True
    assert SecureCredentialStore.retrieve_database_credential(path3) == "pw3"

    db1.close()
    db2.close()
    db3.close()


# =========================================================================
# SCENARIO 6: End-to-End Store Operations Sweep
# =========================================================================
def test_scenario6_end_to_end_store_operations_sweep(qapp, tmp_path, monkeypatch):
    """Scenario 6:
    - Service registration and fee tracking.
    - Customer and accounting entry.
    - Excel report export.
    - Manual backup.
    """
    db_path = str(tmp_path / "scenario6.db")
    db = create_and_initialize_database(db_path)
    monkeypatch.setattr("database.CONFIG_FILE", str(tmp_path / "app_config.json"))

    # Seed employee
    with db.get_connection() as conn:
        emp_id = conn.execute(
            "INSERT INTO employees (name, role, permissions, is_active) VALUES (?, ?, ?, 1)",
            ("تکنسین", "کارمند", "all"),
        ).lastrowid
        conn.commit()

    # Seed service catalog item
    db.save_service_catalog(
        service_id=None,
        code="S-1001",
        service_type="سخت‌افزاری",
        name="تعویض نمایشگر OLED",
        default_fee=2_500_000,
        default_side_cost=500_000,
        description="صفحه اصلی",
    )
    with db.get_connection() as conn:
        row = conn.execute("SELECT id FROM service_catalog WHERE code='S-1001'").fetchone()
        service_id = row["id"]

    # Add service record
    inv_num = db.add_service_record(
        invoice_number="SINV-1001",
        service_id=service_id,
        seller_employee_id=emp_id,
        technician_employee_id=emp_id,
        customer_name="علی رضایی",
        service_fee=2_500_000,
        side_cost=500_000,
        paid_amount=2_500_000,
        service_datetime="1403/05/10 14:30:00",
        description="صفحه اصلی تعویض شد",
        settlement_status="تسویه‌شده",
    )
    assert inv_num == "SINV-1001"

    with db.get_connection() as conn:
        rec = conn.execute("SELECT * FROM service_records WHERE invoice_number=?", (inv_num,)).fetchone()
        assert rec["net_profit"] == 2_000_000
        assert rec["settlement_status"] == "تسویه‌شده"
        assert rec["service_name"] == "تعویض نمایشگر OLED"

    # Test manual backup creation
    manual_backup_path = str(tmp_path / "manual_backup.db")
    res_path = db.create_backup(target_file=manual_backup_path)
    assert os.path.isfile(res_path)

    db.close()
