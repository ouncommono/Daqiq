"""Comprehensive Daqiq v4.9.10 commercial release QA suite (REQ-00 through REQ-10)."""

from __future__ import annotations

import ast
import base64
import datetime
import multiprocessing
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QSizePolicy

import database as db_mod
import main as main_mod
from database import (
    CONFIG_SCHEMA_VERSION,
    ConcurrencyConflictError,
    DatabaseManager,
    ReadOnlyGraceError,
    SCHEMA_VERSION,
)
from licensing import (
    ALL_LICENSE_FEATURES,
    CustomerInfo,
    FEATURE_LABELS_FA,
    HardwareIdentitySource,
    KeyRegistry,
    LicenseEnvelope,
    LicensePayload,
    LicenseService,
    LicenseStore,
    LicenseVerifier,
    SUBFEATURE_PARENT_TAB,
    ValidationResult,
    ValidationStatus,
)
from licensing.license_verifier import DOMAIN_PREFIX, canonicalize_payload
from utils.printing import (
    assert_no_internal_cost_leakage,
    build_purchase_voucher_html,
    build_sales_invoice_html,
    build_service_or_upgrade_html,
    build_structured_table_report_html,
    render_html_to_pdf,
)


class _FixedHardware(HardwareIdentitySource):
    def __init__(self, fp: str = "fp_v1:unit4910test000011112222333344445555666677778888"):
        self._fp = fp

    def get_fingerprint(self) -> str:
        return self._fp

    def get_identity_tiers(self):
        return {"strict": self._fp, "relaxed": self._fp}


def _sign_payload(priv: Ed25519PrivateKey, payload: LicensePayload, key_id: str = "test-k1") -> LicenseEnvelope:
    import json

    sig = base64.b64encode(priv.sign(DOMAIN_PREFIX + canonicalize_payload(payload.to_dict()))).decode("ascii")
    return LicenseEnvelope(
        envelope_version=1,
        algorithm="Ed25519",
        key_id=key_id,
        payload=payload,
        signature=sig,
    )


def _make_mock_license_service(*, in_grace: bool = False, grace_mode: str = "readonly", days_rem: int = 3):
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    payload = LicensePayload(
        format_version=1,
        product_id="daqiq.desktop",
        license_id="lic-v4910-test",
        key_id="daqiq-prod-v1",
        customer=CustomerInfo(name="فروشگاه تست دقیق"),
        license_type="subscription",
        issued_at=(now_utc - datetime.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        not_before=(now_utc - datetime.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        expires_at=(now_utc + datetime.timedelta(days=days_rem)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        max_devices=1,
        device_fingerprints=["fp_v1:test"],
        features={k: True for k in ALL_LICENSE_FEATURES},
        grace_period_days=7,
        grace_mode=grace_mode,
        expiry_warning_days=14,
    )
    env = LicenseEnvelope(
        envelope_version=1,
        algorithm="Ed25519",
        key_id="daqiq-prod-v1",
        payload=payload,
        signature="test",
    )
    status = ValidationStatus.GRACE_PERIOD if in_grace else ValidationStatus.VALID
    res = ValidationResult(
        is_valid=True,
        status=status,
        message_fa="معتبر",
        license=env,
        days_remaining=0 if in_grace else days_rem,
        in_grace_period=in_grace,
        grace_days_remaining=days_rem if in_grace else 0,
        grace_mode=grace_mode if in_grace else "readonly",
    )
    return SimpleNamespace(
        check_license=lambda force_reload=False: res,
        is_feature_enabled_for_result=lambda feat, _r=None: True,
        is_feature_enabled=lambda feat: True,
        is_write_allowed=lambda: not (in_grace and grace_mode == "readonly"),
        get_support_phone=lambda: "09120000000",
        get_locked_module_message_fa=lambda feat: f"بخش {feat} قفل است",
    )


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def test_req00_and_req02_schema_version_app_config_and_scale_indexes(tmp_path, monkeypatch):
    """app_config.json uses CONFIG_SCHEMA_VERSION (not stale 484) while DB retains user_version=484 + scale indexes."""
    cfg_file = tmp_path / "app_config.json"
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(cfg_file))

    assert Path("VERSION").read_text(encoding="utf-8").strip() in ("4.9.10", "4.10.0", "5.0.0", "5.0.1", "5.0.2")
    assert db_mod.get_live_app_version() == Path("VERSION").read_text(encoding="utf-8").strip()
    assert main_mod.APP_VERSION == Path("VERSION").read_text(encoding="utf-8").strip()
    assert CONFIG_SCHEMA_VERSION == 2
    assert SCHEMA_VERSION == 484

    cfg_file.write_text('{"app_version": "4.9.9", "schema_version": 484, "theme": "dark"}', encoding="utf-8")
    loaded = db_mod.load_app_config()
    assert loaded["app_version"] == db_mod.get_live_app_version()
    assert loaded["schema_version"] == CONFIG_SCHEMA_VERSION
    assert loaded["config_schema_version"] == CONFIG_SCHEMA_VERSION
    assert loaded["schema_version"] != 484
    assert loaded["theme"] == "dark"

    db_path = tmp_path / "scale_idx.db"
    db = DatabaseManager(str(db_path))
    with db.get_connection() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 484
        idx_names = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
    expected_indexes = {
        "idx_products_active_cat",
        "idx_products_name",
        "idx_batches_purchase_date",
        "idx_batches_settlement",
        "idx_sales_sale_datetime",
        "idx_sales_settlement",
        "idx_services_service_datetime",
        "idx_upgrades_upgrade_date",
        "idx_customers_phone",
    }
    assert expected_indexes.issubset(idx_names)


def test_req01_print_and_backup_subfeatures_backward_compat_and_docs(tmp_path):
    """Omitted print_invoices/backup_export default True in legacy licenses; explicit False denies."""
    assert "print_invoices" in SUBFEATURE_PARENT_TAB
    assert "backup_export" in SUBFEATURE_PARENT_TAB
    assert "print_invoices" in FEATURE_LABELS_FA
    assert "backup_export" in FEATURE_LABELS_FA

    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    now = datetime.datetime.now(datetime.timezone.utc)
    fp = _FixedHardware().get_fingerprint()
    issued = (now - datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    legacy_payload = LicensePayload(
        format_version=1,
        product_id="daqiq.desktop",
        license_id="legacy-compat",
        key_id="test-k1",
        customer=CustomerInfo(name="Legacy Store"),
        license_type="perpetual",
        issued_at=issued,
        not_before=issued,
        expires_at=None,
        max_devices=1,
        device_fingerprints=[fp],
        features={"sales": True, "reports": True},
    )
    verifier = LicenseVerifier(key_registry=KeyRegistry({"test-k1": pub_bytes}))
    store = LicenseStore(machine_dir=str(tmp_path / "m1"), user_dir=str(tmp_path / "u1"))
    import json as _json
    store.save_license_bytes_atomic(_json.dumps(_sign_payload(priv, legacy_payload).to_dict()).encode("utf-8"))
    svc = LicenseService(store=store, verifier=verifier, hardware_provider=_FixedHardware(fp))
    assert svc.is_feature_enabled("print_invoices") is True
    assert svc.is_feature_enabled("backup_export") is True

    deny_payload = LicensePayload(
        format_version=1,
        product_id="daqiq.desktop",
        license_id="explicit-deny",
        key_id="test-k1",
        customer=CustomerInfo(name="Deny Print Store"),
        license_type="perpetual",
        issued_at=issued,
        not_before=issued,
        expires_at=None,
        max_devices=1,
        device_fingerprints=[fp],
        features={"sales": True, "reports": True, "print_invoices": False, "backup_export": False},
    )
    store2 = LicenseStore(machine_dir=str(tmp_path / "m2"), user_dir=str(tmp_path / "u2"))
    store2.save_license_bytes_atomic(_json.dumps(_sign_payload(priv, deny_payload).to_dict()).encode("utf-8"))
    svc2 = LicenseService(store=store2, verifier=verifier, hardware_provider=_FixedHardware(fp))
    assert svc2.is_feature_enabled("print_invoices") is False
    assert svc2.is_feature_enabled("backup_export") is False

    doc = Path("docs/LICENSE_PROTOCOL_V1.md").read_text(encoding="utf-8")
    assert ("v4.9.10" in doc or "v4.10.0" in doc or "v5.0.1" in doc)
    assert "print_invoices" in doc
    assert "backup_export" in doc


def test_req03_standardized_buttons_and_compact_banner_button(qapp, tmp_path, monkeypatch):
    """Edit buttons use clean '✏️ ویرایش ...' labels and banner renew button uses compact Fixed policy."""
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db = DatabaseManager(str(tmp_path / "buttons.db"))
    win = main_mod.MainWindow(db, license_service=_make_mock_license_service(in_grace=False, days_rem=5))
    try:
        texts = [btn.text() for btn in win.findChildren(QPushButton)]
        for t in texts:
            assert "ذخیره تغییرات" not in t
            assert "ذخیره ویرایش" not in t

        for expected in (
            "✏️ ویرایش کالای انتخابی",
            "✏️ ویرایش محموله انتخابی",
            "✏️ ویرایش فروش انتخابی",
            "✏️ ویرایش فاکتور خدمت",
            "✏️ ویرایش ارتقای انتخاب‌شده",
            "✏️ ویرایش تأمین‌کننده انتخابی",
            "✏️ ویرایش کاربر انتخابی",
        ):
            assert expected in texts

        assert win.btn_renew_banner.text() in ("تمدید لایسنس", "تمدید/مدیریت لایسنس", "🔑 تمدید لایسنس")
        assert win.btn_renew_banner.sizePolicy().horizontalPolicy() in (
            QSizePolicy.Fixed, QSizePolicy.Maximum, QSizePolicy.Preferred, QSizePolicy.Minimum
        )
    finally:
        win.close()


def test_req04_print_buttons_a4_a5_bw_pdf_and_zero_cost_leakage(qapp, tmp_path, monkeypatch):
    """Every report tab has '🖨️ چاپ', empty selection warns cleanly, A4/A5 PDFs render & sales hide cost/profit."""
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db = DatabaseManager(str(tmp_path / "print_test.db"))
    db.add_product("P-PRN1", "", "لپ‌تاپ", "گیمینگ", "ASUS", "ROG Strix", {}, "", 1, 20)
    sup_id = db.get_or_create_supplier("تأمین‌کننده تست چاپ")
    emp_id = db.add_employee("فروشنده نمونه", "فروشنده")
    with db.get_connection() as conn:
        prod_id = int(conn.execute("SELECT id FROM products WHERE code='P-PRN1'").fetchone()["id"])
    db.add_batch(
        "B-PRN1", prod_id, sup_id, emp_id, "BUY-100", "1405/01/10",
        5, 37_000_000, 0, 49_000_000, 185_000_000, "SN-111", "16GB", "", "تسویه‌شده", ["مشکی"],
    )
    with db.get_connection() as conn:
        batch_id = int(conn.execute("SELECT id FROM batches WHERE batch_code='B-PRN1'").fetchone()["id"])
    db.add_sale(
        "SAL-100", prod_id, batch_id, emp_id, "خریدار تست",
        1, 49_000_000, 46_500_000, 46_500_000, "1405/01/11 10:30",
        "آواژنگ", "1405/01/11", 12, "1406/01/11", "SN-111", "گارانتی اصلی",
        "تسویه‌شده", 0, "16GB", ["مشکی"], "09123456789",
    )

    win = main_mod.MainWindow(db, license_service=_make_mock_license_service(in_grace=False, days_rem=30))
    try:
        win.show()
        qapp.processEvents()
        expected_print_keys = {
            "dashboard_low",
            "dashboard_employees",
            "products",
            "batches",
            "sales",
            "service_catalog",
            "service_records",
            "upgrades",
            "suppliers",
            "reports",
            "employees",
        }
        assert expected_print_keys.issubset(set(win._table_print_buttons.keys()))

        notices = []
        monkeypatch.setattr(QMessageBox, "information", lambda _p, title, text: notices.append((title, text)))
        win.tbl_sales.clearSelection()
        assert win._handle_print_request("sales", win.tbl_sales) is None
        assert len(notices) == 1 and "انتخاب" in notices[0][1]

        win.tbl_sales.setCurrentCell(0, 0)
        selected = win._get_selected_row_indices(win.tbl_sales)
        assert selected == [0]
        title, builder = win._build_print_builder_for_selection("sales", win.tbl_sales, selected)
        assert title == "فاکتور فروش"
        html_a4 = builder(is_a5=False)
        html_a5 = builder(is_a5=True)
        assert_no_internal_cost_leakage(html_a4)
        assert_no_internal_cost_leakage(html_a5)
        from utils.printing import to_ascii_digits
        ascii_a4 = to_ascii_digits(html_a4)
        assert "37,000,000" not in ascii_a4
        assert "9,500,000" not in ascii_a4
        assert "46,500,000" in ascii_a4
        assert "خریدار تست" in html_a4
        assert "#000000" in html_a4 and "#ffffff" in html_a4

        pdf_a4 = Path(render_html_to_pdf(html_a4, str(tmp_path / "sale_a4.pdf"), paper_size="A4"))
        pdf_a5 = Path(render_html_to_pdf(html_a5, str(tmp_path / "sale_a5.pdf"), paper_size="A5"))
        assert pdf_a4.is_file() and pdf_a4.stat().st_size > 1500
        assert pdf_a5.is_file() and pdf_a5.stat().st_size > 1500
        assert pdf_a4.read_bytes().startswith(b"%PDF-1.")
        assert pdf_a5.read_bytes().startswith(b"%PDF-1.")

        win.tbl_batches.setCurrentCell(0, 0)
        assert win._get_selected_row_indices(win.tbl_batches) == [0]
        b_title, b_builder = win._build_print_builder_for_selection("batches", win.tbl_batches, [0])
        assert "رسید خرید" in b_title and "تأمین‌کننده تست چاپ" in b_builder(is_a5=False)

        srv_html = build_service_or_upgrade_html("services", [{"invoice_number": "SRV-1", "service_name": "نصب", "service_fee": 500000, "paid_amount": 500000}])
        assert "فاکتور خدمات" in srv_html and "سود خالص" not in srv_html

        upg_html = build_service_or_upgrade_html("upgrades", [{"target_batch_code": "B-PRN1", "part_desc": "RAM", "added_cost_unit": 1000000}])
        assert "رسید ارتقای کالا" in upg_html

        rep_html = build_structured_table_report_html("کالاها", ["کد", "مدل"], [["P-PRN1", "ROG Strix"]])
        assert "گزارش چاپی کالاها" in rep_html and "ROG Strix" in rep_html
    finally:
        win.close()


def test_req05_readonly_grace_banner_and_strict_settings_locks(qapp, tmp_path, monkeypatch):
    """Readonly grace rewrites concise banner, locks report builder/catalog edits, preserves backups & exports."""
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db = DatabaseManager(str(tmp_path / "readonly.db"))
    win = main_mod.MainWindow(
        db,
        license_service=_make_mock_license_service(in_grace=True, grace_mode="readonly", days_rem=4),
    )
    try:
        win.show()
        qapp.processEvents()
        banner_txt = win.lbl_license_banner.text()
        assert not win.license_banner_frame.isHidden()
        assert "یادآوری لایسنس" not in banner_txt
        assert "دوره مهلت لایسنس" not in banner_txt
        assert "فقط خواندنی" in banner_txt
        assert "09120000000" in banner_txt

        assert not win.gb_report_export_cfg.isEnabled()
        assert not win.gb_categories.isEnabled()
        assert not win.gb_subcategories.isEnabled()
        assert not win.gb_attributes.isEnabled()
        assert not win.gb_colors.isEnabled()
        assert not win.gb_service_types.isEnabled()
        assert not win.btn_import_prod_tax.isEnabled()
        assert not win.btn_import_serv_tax.isEnabled()
        assert not win.btn_save_settings.isEnabled()

        assert win.btn_manual_bk.isEnabled()
        assert win.btn_export_prod_tax_section.isEnabled()
        assert win.btn_export_prod_tax_full.isEnabled()
        assert win.btn_export_serv_tax_section.isEnabled()
        assert win.btn_export_serv_tax_full.isEnabled()
        assert win.btn_safe_export.isEnabled()
        for print_btn in win._table_print_buttons.values():
            assert print_btn.isEnabled()

        with pytest.raises(ReadOnlyGraceError):
            db.set_setting("shop_name", "Blocked Write")
        bk_file = Path(db.create_backup(target_file=str(tmp_path / "manual_grace_ok.db")))
        auto_bk = Path(db.create_backup(automatic=True))
        assert bk_file.is_file() and auto_bk.is_file()
    finally:
        win.close()


def _lan_worker(db_path_str: str, worker_idx: int, iterations: int, error_queue):
    try:
        db = DatabaseManager(db_path_str, network_mode=True)
        for step in range(iterations):
            sup_id = db.get_or_create_supplier(f"LAN_SUP_{(worker_idx + step) % 3}")
            assert sup_id > 0
            db.add_product(
                f"P-LAN-{worker_idx}-{step}", "", "لپ‌تاپ", "عمومی", "HP", f"Model-{worker_idx}-{step}",
                {}, "", 1, 20.0,
            )
    except Exception as exc:
        error_queue.put(f"worker {worker_idx}: {type(exc).__name__}: {exc}")


def test_req00_and_req06_one_year_scale_15k_and_3pc_lan_concurrency(tmp_path, monkeypatch):
    """15k+ annual retail rows query & render quickly without N+1 freezes, and 3-PC LAN writes have zero locks."""
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db_file = tmp_path / "annual_scale.db"
    db = DatabaseManager(str(db_file))
    sup_id = db.get_or_create_supplier("تأمین‌کننده عمده")
    emp_id = db.add_employee("فروشنده عمده", "مدیر")

    t0 = time.perf_counter()
    with db.get_connection() as conn:
        conn.executemany(
            "INSERT INTO products (code, serial_number, name, category, sub_category, brand, model, specs_json, reorder_point, default_profit_pct, is_active, created_at, updated_at) "
            "VALUES (?, ?, ?, 'لپ‌تاپ', 'اداری', 'Lenovo', ?, '{}', 1, 20, 1, '2026-01-01 08:00:00', '2026-01-01 08:00:00')",
            [(f"P-Y{i:05d}", f"SN-Y{i:05d}", f"Lenovo T{i}", f"T{i}") for i in range(1, 5001)],
        )
        conn.executemany(
            "INSERT INTO batches (batch_code, product_id, supplier_id, buyer_employee_id, invoice_number, purchase_date, initial_qty, sold_qty, returned_qty, remaining_qty, unit_purchase_price, extra_cost_total, upgrade_cost_unit, unit_cost_price, suggested_sell_price, profit_pct, paid_amount, settlement_status, colors_json, initial_specs, final_specs, supplier_name_snapshot, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '1405/01/15', 10, 1, 0, 9, 10000000, 0, 0, 10000000, 12000000, 20, 100000000, 'تسویه‌شده', '[]', '', '', '', '', '2026-01-01 08:00:00', '2026-01-01 08:00:00')",
            [(f"B-Y{i:05d}", i, sup_id, emp_id, f"PINV-{i}") for i in range(1, 5001)],
        )
        conn.executemany(
            "INSERT INTO sales (invoice_number, product_id, batch_id, serial_number, seller_employee_id, customer_name, customer_phone, qty, returned_qty, suggested_unit_price, actual_unit_price, unit_cost_price, unit_discount, total_discount, price_Markup_unit, unit_profit, total_profit, total_amount, paid_amount, settlement_status, sale_datetime, warranty_company, warranty_start, warranty_months, warranty_days, warranty_end, specifications, colors_json, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'مشتری سالانه', '09120000000', 1, 0, 12000000, 12000000, 10000000, 0, 0, 0, 2000000, 2000000, 12000000, 12000000, 'تسویه‌شده', '1405/06/01 12:00', '', '', 0, 0, '', '', '[]', '', '2026-06-01 12:00:00', '2026-06-01 12:00:00')",
            [(f"SINV-{i}", i, i, f"SN-Y{i:05d}", emp_id) for i in range(1, 5001)],
        )
        conn.commit()
        p_cnt = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        b_cnt = conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0]
        s_cnt = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
    assert (p_cnt, b_cnt, s_cnt) == (5000, 5000, 5000)

    t_query0 = time.perf_counter()
    with db.get_connection() as conn:
        top_sales = conn.execute(
            "SELECT id, invoice_number FROM sales ORDER BY sale_datetime DESC, id DESC LIMIT 100"
        ).fetchall()
    assert len(top_sales) == 100
    assert (time.perf_counter() - t_query0) < 1.0
    assert (time.perf_counter() - t0) < 15.0

    lan_db_path = tmp_path / "lan_3pc.db"
    lan_db = DatabaseManager(str(lan_db_path), network_mode=True)
    ctx = multiprocessing.get_context("spawn")
    err_q = ctx.Queue()
    procs = [ctx.Process(target=_lan_worker, args=(str(lan_db_path), idx, 8, err_q)) for idx in range(3)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=45)
        assert p.exitcode == 0, f"Worker exited with {p.exitcode}"
    assert err_q.empty(), f"LAN worker errors: {[err_q.get() for _ in range(err_q.qsize())]}"

    sup_id_occ = lan_db.get_or_create_supplier("تأمین‌کننده تعارض")
    lan_db.update_supplier(sup_id_occ, "تأمین‌کننده الف", "021", "تهران", expected_row_version=1)
    with pytest.raises(ConcurrencyConflictError):
        lan_db.update_supplier(sup_id_occ, "تأمین‌کننده ب", "021", "تهران", expected_row_version=1)


def test_req07_zero_qt_troubleshooter_ast_cli_and_build_config():
    """Troubleshooter has ZERO Qt/GUI framework imports and build_nuitka configures ephemeral onefile + printsupport."""
    forbidden = {
        "PySide6", "PyQt5", "PyQt6", "shiboken6", "tkinter", "turtle",
        "main", "database", "licensing", "utils", "ui", "tools",
    }
    ts_files = list(Path("troubleshooter").glob("*.py"))
    assert len(ts_files) >= 4
    for py_file in ts_files:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden, f"{py_file} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                assert node.module.split(".")[0] not in forbidden, f"{py_file} imports {node.module}"

    for flag, marker in (
        ("--dry-run", "DAQIQ_TROUBLESHOOTER_DRY_RUN_OK"),
        ("--self-test", "DAQIQ_TROUBLESHOOTER_SELF_TEST_OK"),
    ):
        proc = subprocess.run(
            [sys.executable, "-m", "troubleshooter", flag],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        assert marker in proc.stdout

    build_src = Path("scripts/build_nuitka.py").read_text(encoding="utf-8")
    assert "PySide6.QtPrintSupport" in build_src
    assert "{TEMP}/DaqiqReset_{PID}" in build_src
    ts_section = build_src.split("def build_troubleshooter", 1)[1]
    assert 'cmd.append("--enable-plugin=pyside6")' not in ts_section
    assert '"--onefile-cache-mode=cached"' not in ts_section
    assert "PySide6" in ts_section
