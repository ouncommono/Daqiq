"""Comprehensive verification suite for Daqiq v5.0.1 (REQ-00 through REQ-20)."""

from __future__ import annotations

import base64
import datetime
import multiprocessing
import os
import sqlite3
import stat
import time
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from openpyxl import load_workbook
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QScrollArea

import database as db_mod
import main as main_mod
from database import DatabaseManager, ReadOnlyGraceError
from exporter import INVENTORY_EXPORT_AVAILABLE_COLUMNS, export_safe_inventory_excel
from licensing.device_identity import create_device_request_dict
from licensing.license_dialog import LicenseDialog
from licensing.license_models import (
    CustomerInfo,
    LicenseEnvelope,
    LicensePayload,
    ValidationResult,
    ValidationStatus,
)
from licensing.license_policy import (
    ALL_LICENSE_FEATURES,
    FEATURE_LABELS_FA,
    OPTIONAL_DEFAULT_TRUE_FEATURES,
    LicenseService,
    SUBFEATURE_PARENT_TAB,
)
from licensing.license_store import LicenseStore
from licensing.license_verifier import DOMAIN_PREFIX, LicenseVerifier, canonicalize_payload
from troubleshooter.core import discover_troubleshooting_targets, execute_troubleshooting_reset
from utils import datetime_format
from utils.printing import (
    build_proforma_invoice_html,
    build_proforma_invoice_spec,
    build_purchase_voucher_spec,
    build_sales_invoice_html,
    build_sales_invoice_spec,
    export_spec_to_docx,
    render_html_to_pdf,
)


def _proforma_race_worker(db_path: str, pf_id: int, barrier, out_q) -> None:
    db = DatabaseManager(db_path)
    try:
        barrier.wait(timeout=15)
        inv_no = db.convert_proforma_to_sale(pf_id, settlement_status="تسویه‌شده")
        out_q.put(("ok", inv_no))
    except Exception as exc:
        out_q.put(("err", type(exc).__name__, str(exc)))
    finally:
        db.close()


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setLayoutDirection(Qt.RightToLeft)
    return app


def _make_mock_service(
    *,
    is_valid: bool = True,
    in_grace: bool = False,
    grace_mode: str = "full",
    features: dict | None = None,
):
    feat_map = {k: True for k in ALL_LICENSE_FEATURES}
    if features:
        feat_map.update(features)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    payload = LicensePayload(
        format_version=1,
        product_id="daqiq.desktop",
        license_id="lic-v501-test",
        key_id="daqiq-prod-v1",
        customer=CustomerInfo(name="فروشگاه دقیق ۵.۰.۱"),
        license_type="subscription",
        issued_at=(now_utc - datetime.timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        not_before=(now_utc - datetime.timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        expires_at=(now_utc + datetime.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        max_devices=1,
        device_fingerprints=["fp_v1:mock"],
        features=feat_map,
    )
    env = LicenseEnvelope(1, "Ed25519", "daqiq-prod-v1", payload, "sig")
    status = ValidationStatus.GRACE_PERIOD if in_grace else ValidationStatus.VALID
    res = ValidationResult(
        status=status,
        is_valid=is_valid,
        license=env,
        message_fa="معتبر",
        in_grace_period=in_grace,
        grace_mode=grace_mode if in_grace else None,
        grace_days_remaining=4 if in_grace else 0,
    )
    svc = MagicMock(spec=LicenseService)
    svc.check_license.return_value = res
    svc.is_write_allowed.return_value = not (in_grace and grace_mode == "readonly")
    svc.is_feature_enabled.side_effect = lambda f: bool(feat_map.get(f, f in OPTIONAL_DEFAULT_TRUE_FEATURES))
    svc.is_feature_enabled_for_result.side_effect = lambda f, _r=None: bool(
        feat_map.get(f, f in OPTIONAL_DEFAULT_TRUE_FEATURES)
    )
    svc.get_support_phone.return_value = "09000000000"
    svc.get_hardware_fingerprint.return_value = "fp_v1:mock"
    svc.get_hardware_tiers.return_value = {"strict": "fp_v1:mock"}
    svc.get_locked_module_message_fa.side_effect = lambda feat: f"ماژول {feat} در لایسنس شما فعال نیست."
    svc.export_device_request_file.return_value = str(Path.cwd() / "test.daqreq")
    return svc


def _prod_id(db: DatabaseManager, code: str) -> int:
    with db.get_connection() as conn:
        return int(conn.execute("SELECT id FROM products WHERE code=?", (code,)).fetchone()[0])


# ---------------------------------------------------------------------------
# REQ-00 & REQ-04: Schema, Standardized Prefixes & Purchase PINV Grouping
# ---------------------------------------------------------------------------

def test_v501_req00_req04_schema_prefixes_and_purchase_grouping(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db = DatabaseManager(str(tmp_path / "req00.db"))

    with db.get_connection() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for req_tbl in (
            "proforma_invoices",
            "proforma_items",
            "supplier_installment_plans",
            "supplier_installment_payments",
        ):
            assert req_tbl in tables
        batch_cols = {r[1] for r in conn.execute("PRAGMA table_info(batches)").fetchall()}
        assert "purchase_invoice_code" in batch_cols
        assert "payment_type" in batch_cols

    assert db.generate_next_code("products", "code", "SKU-", 1001) == "SKU-1001"
    assert db.generate_next_code("batches", "purchase_invoice_code", "PINV-", 1001) == "PINV-1001"
    assert db.generate_next_code("service_catalog", "code", "SVC-", 1001) == "SVC-1001"
    assert db.generate_next_code("proforma_invoices", "proforma_number", "PI-", 1001) == "PI-1001"
    assert db.generate_next_code("sales", "invoice_number", "INV-", 1001) == "INV-1001"

    c1 = db.add_product("SKU-1001", "ASUS VivoBook 15", "لپ‌تاپ", "لپ‌تاپ اداری", "ASUS", "VivoBook 15", {}, "", 1, 20)
    c2 = db.add_product("SKU-1002", "HP ProBook", "لپ‌تاپ", "لپ‌تاپ اداری", "HP", "ProBook 450", {}, "", 1, 20)
    p1, p2 = _prod_id(db, c1), _prod_id(db, c2)
    sup_id = db.get_or_create_supplier("تأمین‌کننده دقیق")
    emp_id = db.add_employee("کاربر خرید", "مسئول خرید")

    # Multi-item purchase grouped by PINV-1001 with blank optional supplier invoice
    pinv_no = db.add_purchase_invoice(
        "",
        [
            {
                "product_id": p1,
                "initial_qty": 2,
                "unit_purchase_price": 10_000_000,
                "extra_cost_total": 0,
                "suggested_sell_price": 12_000_000,
                "profit_pct": 20,
            },
            {
                "product_id": p2,
                "initial_qty": 3,
                "unit_purchase_price": 8_000_000,
                "extra_cost_total": 0,
                "suggested_sell_price": 9_600_000,
                "profit_pct": 20,
            },
        ],
        purchase_invoice_code="",
        supplier_id=sup_id,
        supplier_name="تأمین‌کننده دقیق",
        buyer_employee_id=emp_id,
        purchase_date="1405/08/10",
        paid_amount=44_000_000,
        settlement_status="تسویه‌شده",
    )
    assert pinv_no == "PINV-1001"
    with db.get_connection() as conn:
        rows = conn.execute("SELECT batch_code, purchase_invoice_code, invoice_number FROM batches WHERE purchase_invoice_code='PINV-1001'").fetchall()
        assert len(rows) == 2
        assert all((r["invoice_number"] or "") == "" for r in rows)


# ---------------------------------------------------------------------------
# REQ-01, REQ-02, REQ-03: Sidebar, Layout Heights, Warranty Order, Service Subtabs, No دریافتنی
# ---------------------------------------------------------------------------

def test_v501_req01_req02_req03_sidebar_layout_warranty_and_services(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db = DatabaseManager(str(tmp_path / "ui_layout.db"))
    # Lock dashboard to prove startup opens on first unlocked tab (products=1)
    svc = _make_mock_service(features={"dashboard": False})
    win = main_mod.MainWindow(db, active_employee=None, license_service=svc)
    try:
        win.resize(1380, 860)
        win.show()
        qapp.processEvents()

        # REQ-02: Right hover sidebar & startup first unlocked tab
        assert win.tabs.currentIndex() == 1
        assert win.tabs.COLLAPSED_WIDTH == 56
        assert win.tabs.EXPANDED_WIDTH == 224
        assert win.tabs._leave_timer.interval() == 120
        assert win.tabs._sidebar_frame.width() <= 64
        win.tabs._sidebar_frame.enterEvent(QEnterEvent(QPointF(10, 10), QPointF(10, 10), QPointF(10, 10)))
        assert win.tabs._expanded is True
        win.tabs._sidebar_frame.leaveEvent(QEvent(QEvent.Leave))
        assert win.tabs._leave_timer.isActive() is True

        # REQ-01: Cart height bounds & bottom table >= 290px & outer QScrollArea
        for cart in (win.tbl_batch_cart, win.tbl_sale_cart, win.tbl_pf_cart, win.tbl_srv_cart):
            assert cart.minimumHeight() >= 140
            assert cart.maximumHeight() <= 285
        for tbl in (win.tbl_products, win.tbl_batches, win.tbl_sales, win.tbl_proformas, win.tbl_services, win.tbl_upgrades, win.tbl_report):
            assert tbl.minimumHeight() >= 290
        for i in range(win.tabs.count()):
            if i != win._settings_tab_index:
                assert isinstance(win.tabs.widget(i), QScrollArea)
                assert win.tabs.widget(i).widgetResizable() is True

        # Sales warranty order under RTL: شروع -> مدت -> انقضا
        sales_idx = next(i for i in range(win.tabs.count()) if "ثبت فروش" in win.tabs.tabText(i))
        win.tabs.setCurrentIndex(sales_idx)
        qapp.processEvents()
        assert win.dt_war_start.x() > win.cb_war_months.x() > win.dt_war_end.x()

        # REQ-03: Services 2 clean sub-tabs & contextual delete labels
        assert win.services_subtabs.count() == 2
        srv_btn_texts = [b.text() for b in win.services_subtabs.findChildren(QPushButton)]
        assert "🗑️ حذف فاکتور خدمت انتخابی" in srv_btn_texts
        assert "🗑️ حذف خدمت انتخابی" in srv_btn_texts

        # REQ-03: Zero "دریافتنی" anywhere in live UI widgets or table headers
        for lbl in win.findChildren(QLabel):
            assert "دریافتنی" not in lbl.text(), lbl.text()
        for btn in win.findChildren(QPushButton):
            assert "دریافتنی" not in btn.text(), btn.text()
        for i in range(win.tabs.count()):
            assert "دریافتنی" not in win.tabs.tabText(i)
    finally:
        win.close()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# REQ-05 & REQ-15: Atomic Multi-Row Batch Deletes & ReadOnly Grace
# ---------------------------------------------------------------------------

def test_v501_req05_atomic_batch_delete_and_readonly(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db = DatabaseManager(str(tmp_path / "batch_del.db"))
    c1 = db.add_product("SKU-1001", "P1", "لپ‌تاپ", "اداری", "Dell", "Vostro", {}, "", 1, 20)
    c2 = db.add_product("SKU-1002", "P2", "لپ‌تاپ", "اداری", "HP", "250", {}, "", 1, 20)
    p1, p2 = _prod_id(db, c1), _prod_id(db, c2)
    sup = db.get_or_create_supplier("تأمین")
    emp = db.add_employee("ادمین", "مدیر")

    db.add_batch("PINV-1001", p1, sup, emp, "", "1405/08/10", 5, 1000, 0, 1200, 20, 5000, "تسویه‌شده", "", "[]", "", "")
    db.add_batch("PINV-1002", p2, sup, emp, "", "1405/08/10", 5, 1000, 0, 1200, 20, 5000, "تسویه‌شده", "", "[]", "", "")
    with db.get_connection() as conn:
        b_ids = [r[0] for r in conn.execute("SELECT id FROM batches ORDER BY id").fetchall()]
        assert len(b_ids) == 2

    # Atomic validation guard: invalid row in batch leaves real batch untouched
    with pytest.raises(ValueError):
        db.delete_batches_batch([b_ids[0], -99])
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 2

    db.delete_batches_batch(b_ids)
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 0

    db.delete_products_batch([p1, p2])
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0

    # Readonly blocks proforma add/convert & batch delete
    db.set_read_only_mode(True, "فقط خواندنی")
    with pytest.raises(ReadOnlyGraceError):
        db.delete_batches_batch([1])
    with pytest.raises(ReadOnlyGraceError):
        db.add_proforma_invoice("PI-1001", [{"product_id": 1, "batch_id": 1, "qty": 1, "suggested_unit_price": 100, "actual_unit_price": 100}])


# ---------------------------------------------------------------------------
# REQ-06: Purchase Installments + Supplier Ledger + Nested Sub-Tabs
# ---------------------------------------------------------------------------

def test_v501_req06_purchase_installments_and_subtabs(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db = DatabaseManager(str(tmp_path / "sup_inst.db"))
    c1 = db.add_product("SKU-1001", "ASUS", "لپ‌تاپ", "گیمینگ", "ASUS", "TUF F15", {}, "", 1, 20)
    p1 = _prod_id(db, c1)
    sup = db.get_or_create_supplier("پخش مرکزی")
    emp = db.add_employee("خریدار ۱", "مسئول خرید")

    db.add_purchase_invoice(
        "SUP-99",
        [{
            "product_id": p1,
            "initial_qty": 1,
            "unit_purchase_price": 10_000_001,
            "extra_cost_total": 0,
            "suggested_sell_price": 12_000_000,
            "profit_pct": 20,
        }],
        purchase_invoice_code="PINV-1001",
        supplier_id=sup,
        supplier_name="پخش مرکزی",
        buyer_employee_id=emp,
        purchase_date="1405/08/10",
        paid_amount=1_000_001,
        settlement_status="خرید اقساطی",
        payment_type="installment",
        installment_plan={
            "count": 3,
            "down_payment": 1_000_001,
            "start_due_date": "1405/08/10",
            "interval_days": 30,
            "first_installment_paid": True,
        },
    )
    det = db.get_supplier_purchases_and_installments(sup)
    assert len(det["installments"]) == 3
    assert sum(int(i["due_amount"]) for i in det["installments"]) == 9_000_000
    assert det["installments"][0]["status"] == "paid"

    inst2 = det["installments"][1]
    db.pay_supplier_installment(int(inst2["id"]), int(inst2["due_amount"]), "1405/09/10", expected_row_version=int(inst2["row_version"]))
    det2 = db.get_supplier_purchases_and_installments(sup)
    assert det2["installments"][1]["status"] == "paid"

    # Sub-tabs in MainWindow
    svc = _make_mock_service()
    win = main_mod.MainWindow(db, active_employee=None, license_service=svc)
    try:
        assert win.supplier_detail_tabs.count() >= 3
        assert win.customers_subtabs.count() == 2
        assert win.employees_subtabs.count() == 2
        assert win.settings_subtabs.count() == 5
        assert win.chk_batch_inst_first_paid.isChecked() is True
    finally:
        win.close()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# REQ-07, REQ-08, REQ-09, REQ-10, REQ-11, REQ-14, REQ-15: Polish, Dialogs & Columns
# ---------------------------------------------------------------------------

def test_v501_req07_req08_req09_req10_req11_req14_req15_ui_polish(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db = DatabaseManager(str(tmp_path / "polish.db"))

    # REQ-10: Bootstrap Dialog Light & Dark styling & natural Persian
    dlg_boot_light = main_mod.DatabaseBootstrapDialog(str(tmp_path / "boot.db"), is_dark_theme=False)
    assert "#2563eb" in dlg_boot_light.styleSheet()
    assert "پایگاه داده" in dlg_boot_light.windowTitle()
    dlg_boot_light.close()
    dlg_boot_dark = main_mod.DatabaseBootstrapDialog(str(tmp_path / "boot.db"), is_dark_theme=True)
    assert "#0b1220" in dlg_boot_dark.styleSheet()
    dlg_boot_dark.close()

    # REQ-11: LicenseDialog RTL step hints
    svc = _make_mock_service(in_grace=True, grace_mode="full")
    lic_dlg = LicenseDialog(svc, parent=None, is_dark_theme=False, is_startup_gate=True)
    for hint_lbl in lic_dlg.findChildren(QLabel):
        t = hint_lbl.text()
        if "گام ۱" in t or "گام ۲" in t:
            assert 'dir="rtl"' in t
            assert 'align="right"' in t
            assert hint_lbl.layoutDirection() == Qt.RightToLeft
    lic_dlg.close()

    win = main_mod.MainWindow(db, active_employee=None, license_service=svc)
    try:
        # REQ-08: شناسه فاکتور تأمین‌کننده directly after کد کالا in Purchases & Sales + Excel Exporter
        b_headers = [win.tbl_batches.horizontalHeaderItem(c).text() for c in range(win.tbl_batches.columnCount())]
        s_headers = [win.tbl_sales.horizontalHeaderItem(c).text() for c in range(win.tbl_sales.columnCount())]
        assert b_headers[b_headers.index("کد کالا") + 1] == "شناسه فاکتور تأمین‌کننده"
        assert s_headers[s_headers.index("کد کالا") + 1] == "شناسه فاکتور تأمین‌کننده"
        assert dict(INVENTORY_EXPORT_AVAILABLE_COLUMNS)["batch_code"] == "شناسه فاکتور خرید"
        assert dict(INVENTORY_EXPORT_AVAILABLE_COLUMNS)["purchase_invoice"] == "شناسه فاکتور تأمین‌کننده"

        # REQ-09: Cursors, hover QSS, theme label حالت تاریک, autosize labels & tooltips
        assert ":hover" in win.styleSheet()
        assert win.btn_theme.text() in ("🌙 حالت تاریک", "☀️ حالت روشن")
        assert "تیره" not in win.btn_theme.text()
        assert win.btn_table_width.text() in ("↔️ تنظیم عرض ستون‌ها", "↔️ عرض پیش‌فرض ستون‌ها")
        assert len(win.btn_table_width.toolTip()) >= 15
        assert win.btn_theme.cursor().shape() == Qt.PointingHandCursor

        # REQ-15: Banner compact button & new subfeature registrations
        assert win.lbl_license_banner.wordWrap() is False
        assert win.btn_renew_banner.minimumWidth() >= 118
        assert "proforma_invoices" in SUBFEATURE_PARENT_TAB
        assert "supplier_installments" in SUBFEATURE_PARENT_TAB
        assert "proforma_invoices" in OPTIONAL_DEFAULT_TRUE_FEATURES
        assert "supplier_installments" in OPTIONAL_DEFAULT_TRUE_FEATURES
        assert "proforma_invoices" in FEATURE_LABELS_FA
    finally:
        win.close()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# REQ-12 & REQ-16: Proforma Lifecycle & 3-Process LAN Race
# ---------------------------------------------------------------------------

def test_v501_req12_req16_proforma_lifecycle_and_lan_race(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db_file = tmp_path / "proforma_race.db"
    db = DatabaseManager(str(db_file))
    c1 = db.add_product("SKU-1001", "Laptop", "لپ‌تاپ", "گیمینگ", "MSI", "Katana 15", {}, "", 1, 20)
    p1 = _prod_id(db, c1)
    sup = db.get_or_create_supplier("تأمین پیش‌فاکتور")
    emp = db.add_employee("فروشنده", "فروشنده")
    db.add_purchase_invoice(
        "EXT-10",
        [{"product_id": p1, "initial_qty": 5, "unit_purchase_price": 20_000_000, "extra_cost_total": 0, "suggested_sell_price": 24_000_000, "profit_pct": 20}],
        purchase_invoice_code="PINV-1001",
        supplier_id=sup,
        supplier_name="تأمین پیش‌فاکتور",
        buyer_employee_id=emp,
        purchase_date="1405/08/10",
        paid_amount=100_000_000,
        settlement_status="تسویه‌شده",
    )
    with db.get_connection() as conn:
        b_id = int(conn.execute("SELECT id FROM batches LIMIT 1").fetchone()[0])

    pf_no = db.add_proforma_invoice(
        "",
        [{"product_id": p1, "batch_id": b_id, "qty": 2, "suggested_unit_price": 24_000_000, "actual_unit_price": 23_500_000}],
        customer_name="مشتری پیش‌فاکتور",
        customer_phone="09120001122",
        seller_employee_id=emp,
        proforma_datetime="1405/08/10 10:00",
        valid_until="1405/08/20",
    )
    assert pf_no == "PI-1001"

    # Stock MUST remain 5 while Proforma is open
    with db.get_connection() as conn:
        assert int(conn.execute("SELECT remaining_qty FROM batches WHERE id=?", (b_id,)).fetchone()[0]) == 5
        pf_id = int(conn.execute("SELECT id FROM proforma_invoices WHERE proforma_number='PI-1001'").fetchone()[0])
    db.close()

    # 3-Process concurrent atomic conversion race on same open Proforma
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(3)
    out_q = ctx.Queue()
    procs = [ctx.Process(target=_proforma_race_worker, args=(str(db_file), pf_id, barrier, out_q)) for _ in range(3)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
    results = [out_q.get(timeout=5) for _ in range(3)]
    wins = [r for r in results if r[0] == "ok"]
    losses = [r for r in results if r[0] == "err"]
    assert len(wins) == 1, results
    assert len(losses) == 2, results

    db2 = DatabaseManager(str(db_file))
    with db2.get_connection() as conn:
        assert int(conn.execute("SELECT remaining_qty FROM batches WHERE id=?", (b_id,)).fetchone()[0]) == 3
        row_pf = conn.execute("SELECT status, converted_sale_invoice FROM proforma_invoices WHERE id=?", (pf_id,)).fetchone()
        assert row_pf["status"] == "converted"
        assert row_pf["converted_sale_invoice"] == wins[0][1]
    db2.close()


# ---------------------------------------------------------------------------
# REQ-13: Print HTML4, PDF, Word DOCX (<w:bidiVisual/> + Non-Flipped Dates + Brand+Model Only)
# ---------------------------------------------------------------------------

def test_v501_req13_print_pdf_docx_rtl_dates_and_brand_model(tmp_path, qapp):
    sale_records = [{
        "invoice_number": "INV-1001",
        "brand": "ASUS",
        "model": "ROG Strix G16",
        "product_title": "لپ‌تاپ | ASUS ROG Strix G16",
        "qty": 1,
        "actual_unit_price": 45_000_000,
        "total_amount": 45_000_000,
        "paid_amount": 45_000_000,
        "sale_datetime": "1405/11/23 14:35",
        "customer_name": "خریدار محترم",
        "customer_phone": "09123456789",
    }]
    spec_s = build_sales_invoice_spec(sale_records, {"shop_name": "فروشگاه دقیق", "print_time": "1405/11/23 14:40"})
    assert spec_s.rows[0][1] == "ASUS ROG Strix G16"
    assert "لپ‌تاپ" not in spec_s.rows[0][1]

    html_out = build_sales_invoice_html(sale_records, {"shop_name": "فروشگاه دقیق", "print_time": "1405/11/23 14:40"}, is_a5=True)
    assert "display: flex" not in html_out.lower()
    assert "display: grid" not in html_out.lower()
    assert "<table width='100%'" in html_out or '<table width="100%"' in html_out
    assert "<span dir='ltr' style='unicode-bidi:isolate;'>\u2066" in html_out
    assert "۱۴۰۵/۱۱/۲۳ ۱۴:۳۵" in html_out

    pdf_path = tmp_path / "sale_a5.pdf"
    render_html_to_pdf(html_out, str(pdf_path), paper_size="A5")
    assert pdf_path.read_bytes().startswith(b"%PDF-")

    docx_path = tmp_path / "sale_a5.docx"
    export_spec_to_docx(spec_s, str(docx_path), paper_size="A5")
    with zipfile.ZipFile(docx_path, "r") as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
    assert "<w:bidiVisual/>" in doc_xml
    assert "<w:tblHeader/>" in doc_xml
    assert "<w:cantSplit/>" in doc_xml
    assert '<w:rtl w:val="0"/>' in doc_xml
    assert "\u2066۱۴۰۵/۱۱/۲۳ ۱۴:۳۵\u2069" in doc_xml
    assert "w:tcW" in doc_xml

    pf_html = build_proforma_invoice_html([{
        "proforma_number": "PI-1001",
        "proforma_datetime": "1405/11/23 15:00",
        "valid_until": "1405/11/30",
        "brand": "Lenovo",
        "model": "ThinkPad T14",
        "qty": 2,
        "actual_unit_price": 30_000_000,
    }], {"shop_name": "فروشگاه دقیق", "print_time": "1405/11/23 15:05"})
    assert "پیش‌فاکتور فروش" in pf_html
    assert "ThinkPad T14" in pf_html

    spec_p = build_purchase_voucher_spec([{
        "purchase_invoice_code": "PINV-1001",
        "invoice_number": "SUP-88",
        "purchase_date": "1405/11/23",
        "supplier_name": "پخش دقیق",
        "product_title": "HP Victus",
        "initial_qty": 3,
        "unit_purchase_price": 20_000_000,
        "total_bill": 60_000_000,
        "paid_amount": 60_000_000,
    }])
    assert "شناسه فاکتور تأمین‌کننده" in spec_p.headers


# ---------------------------------------------------------------------------
# REQ-17: Troubleshooter Bottom-Up Empty Folder Removal & Backup Preservation
# ---------------------------------------------------------------------------

def test_v501_req17_troubleshooter_empty_folder_removal(tmp_path, monkeypatch):
    exe_dir = tmp_path / "DaqiqApp"
    local_app = tmp_path / "LocalAppData"
    roaming_app = tmp_path / "RoamingAppData"
    prog_data = tmp_path / "ProgramData"
    for d in (exe_dir, local_app, roaming_app, prog_data):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("LOCALAPPDATA", str(local_app))
    monkeypatch.setenv("APPDATA", str(roaming_app))
    monkeypatch.setenv("ProgramData", str(prog_data))
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(roaming_app / "Daqiq" / "app_config.json"))

    # Seed Daqiq directories & read-only files + protected backup directory
    (roaming_app / "Daqiq" / "cache").mkdir(parents=True, exist_ok=True)
    ro_file = roaming_app / "Daqiq" / "cache" / "ui.cache"
    ro_file.write_text("stale", encoding="utf-8")
    os.chmod(ro_file, stat.S_IREAD)

    cfg = roaming_app / "Daqiq" / "app_config.json"
    cfg.write_text('{"active_database_path": ""}', encoding="utf-8")
    (local_app / "Daqiq" / "license").mkdir(parents=True, exist_ok=True)
    lic_f = local_app / "Daqiq" / "license" / "license.daqlic"
    lic_f.write_text("x", encoding="utf-8")
    os.chmod(lic_f, stat.S_IREAD)

    bk_dir = exe_dir / "Backups"
    bk_dir.mkdir(parents=True, exist_ok=True)
    bk_file = bk_dir / "Daqiq_backup_14050810.db"
    bk_file.write_text("SQLITE-BACKUP-DATA", encoding="utf-8")

    plan = discover_troubleshooting_targets(
        executable_dir=exe_dir,
        local_app_data=local_app,
        roaming_app_data=roaming_app,
        program_data=prog_data,
        process_lister=lambda: [],
    )
    res = execute_troubleshooting_reset(plan, delete_databases=False, dry_run=False, process_lister=lambda: [])
    assert not res.aborted_reason
    assert not (local_app / "Daqiq").exists()
    assert not (roaming_app / "Daqiq").exists()
    assert bk_file.exists() and bk_file.read_text(encoding="utf-8") == "SQLITE-BACKUP-DATA"


# ---------------------------------------------------------------------------
# REQ-18, REQ-19, REQ-20: Version Parity, Calendar Migration & Indexed Scale
# ---------------------------------------------------------------------------

def test_v501_req18_req19_req20_version_calendar_scale_and_ci(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    assert Path("VERSION").read_text(encoding="utf-8").strip() in ("5.0.1", "5.0.2")
    assert db_mod.get_live_app_version() in ("5.0.1", "5.0.2")
    assert main_mod.APP_VERSION in ("5.0.1", "5.0.2")
    assert create_device_request_dict(store_name="دقیق")["app_version"] in ("5.0.1", "5.0.2")

    ci_txt = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "actions/checkout@v7" in ci_txt
    assert "actions/setup-python@v7" in ci_txt
    assert "actions/upload-artifact@v7" in ci_txt
    assert "actions/download-artifact@v8" in ci_txt

    db = DatabaseManager(str(tmp_path / "cal_scale.db"))
    c1 = db.add_product("SKU-1001", "ASUS", "لپ‌تاپ", "اداری", "ASUS", "X515", {}, "", 1, 20)
    p1 = _prod_id(db, c1)
    sup = db.get_or_create_supplier("تأمین")
    emp = db.add_employee("کاربر", "فروشنده")
    db.add_purchase_invoice(
        "",
        [{"product_id": p1, "initial_qty": 200, "unit_purchase_price": 1000, "extra_cost_total": 0, "suggested_sell_price": 1200, "profit_pct": 20}],
        purchase_invoice_code="PINV-1001",
        supplier_id=sup,
        supplier_name="تأمین",
        buyer_employee_id=emp,
        purchase_date="1405/08/10",
        paid_amount=10000,
        settlement_status="خرید اقساطی",
        payment_type="installment",
        installment_plan={"count": 2, "down_payment": 10000, "start_due_date": "1405/08/10", "interval_days": 30},
    )
    with db.get_connection() as conn:
        b_id = int(conn.execute("SELECT id FROM batches LIMIT 1").fetchone()[0])
    db.add_proforma_invoice(
        "PI-1001",
        [{"product_id": p1, "batch_id": b_id, "qty": 1, "suggested_unit_price": 1200, "actual_unit_price": 1200}],
        customer_name="مشتری",
        proforma_datetime="1405/08/10 12:30",
        valid_until="1405/08/20",
    )

    with db.get_connection() as conn:
        discovered = datetime_format.discover_datetime_columns(conn)
        assert "proforma_datetime" in discovered.get("proforma_invoices", {}).get("datetime_cols", ())
        assert "valid_until" in discovered.get("proforma_invoices", {}).get("date_cols", ())
        assert "due_date" in discovered.get("supplier_installment_payments", {}).get("date_cols", ())

    datetime_format.migrate_database_datetime(db, "gregorian", "24h", create_backup=False)
    with db.get_connection() as conn:
        pf_row = conn.execute("SELECT proforma_datetime, valid_until FROM proforma_invoices WHERE proforma_number='PI-1001'").fetchone()
        assert pf_row["proforma_datetime"].startswith("2026/11/")
        assert pf_row["valid_until"].startswith("2026/11/")

    # 10k indexed scale query benchmark
    with db.get_connection() as conn:
        conn.executemany(
            "INSERT INTO products (code, name, category, sub_category, brand, model, is_active, created_at, updated_at) "
            "VALUES (?, ?, 'لپ‌تاپ', 'اداری', 'Brand', 'Model', 1, '1405/08/10', '1405/08/10')",
            [(f"SKU-B{i}", f"Prod {i}") for i in range(10_000)],
        )
        conn.commit()
        t0 = time.perf_counter()
        cnt = conn.execute("SELECT COUNT(*) FROM products WHERE is_active=1 AND category='لپ‌تاپ'").fetchone()[0]
        dt_ms = (time.perf_counter() - t0) * 1000.0
        assert cnt >= 10_001
        assert dt_ms < 250.0
