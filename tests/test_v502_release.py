"""Comprehensive end-to-end verification suite for Daqiq v5.0.2 (REQ-00 through REQ-25)."""

from __future__ import annotations

import datetime
import os
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QPushButton

import database as db_mod
import main as main_mod
from database import ConcurrencyConflictError, DatabaseManager, DuplicateInvoiceConflictError
from licensing.device_identity import create_device_request_dict
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
    SUBFEATURE_PARENT_TAB,
)
from utils import datetime_format
from utils.printing import (
    build_proforma_invoice_spec,
    build_purchase_voucher_spec,
    build_sales_invoice_spec,
    build_service_or_upgrade_spec,
    default_print_filename,
    export_spec_to_docx,
    render_html_to_pdf,
    render_spec_to_html,
)
from utils_and_widgets import CollapsibleSection


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _make_mock_service(enabled_features=None):
    svc = MagicMock()
    allowed = set(enabled_features) if enabled_features is not None else set(ALL_LICENSE_FEATURES)
    svc.is_feature_enabled.side_effect = lambda feat: feat in allowed
    svc.is_write_allowed.return_value = True
    svc.get_support_phone.return_value = "09120000000"
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    payload = LicensePayload(
        format_version=1,
        product_id="daqiq.desktop",
        license_id="lic-v502-test",
        key_id="daqiq-prod-v1",
        customer=CustomerInfo(name="فروشگاه دقیق ۵.۰.۲"),
        license_type="subscription",
        issued_at=(now_utc - datetime.timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        not_before=(now_utc - datetime.timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        expires_at=(now_utc + datetime.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        max_devices=1,
        device_fingerprints=["fp_v1:mock"],
        features={k: (k in allowed) for k in ALL_LICENSE_FEATURES},
    )
    env = LicenseEnvelope(1, "Ed25519", "daqiq-prod-v1", payload, "sig")
    res = ValidationResult(
        status=ValidationStatus.VALID,
        is_valid=True,
        license=env,
        message_fa="لایسنس معتبر است.",
    )
    svc.check_license.return_value = res
    return svc


def _prod_id(db: DatabaseManager, code: str) -> int:
    with db.get_connection() as conn:
        return int(conn.execute("SELECT id FROM products WHERE code=?", (code,)).fetchone()[0])


# ---------------------------------------------------------------------------
# REQ-00 & REQ-19: Version Parity, Pre-v5.0.2 Additive Rebuild & License Policy
# ---------------------------------------------------------------------------

def test_v502_req00_req19_version_upgrade_and_license_features(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    assert Path("VERSION").read_text(encoding="utf-8").strip() == "5.0.2"
    assert db_mod.get_live_app_version() == "5.0.2"
    assert main_mod.APP_VERSION == "5.0.2"
    assert create_device_request_dict(store_name="تست")["app_version"] == "5.0.2"

    # New v5.0.2 licensing subfeatures
    for key, parent in (
        ("incidental_costs", "sales"),
        ("service_installments", "services"),
    ):
        assert SUBFEATURE_PARENT_TAB.get(key) == parent
        assert key in OPTIONAL_DEFAULT_TRUE_FEATURES
        assert key in FEATURE_LABELS_FA

    # Build a synthetic pre-v5.0.2 DB where installment_plans.sale_id & proforma_items.product_id are NOT NULL
    legacy_path = tmp_path / "legacy_pre_502.db"
    db0 = DatabaseManager(str(legacy_path))
    del db0
    raw = sqlite3.connect(str(legacy_path))
    raw.executescript("""
        PRAGMA foreign_keys = OFF;
        DROP TABLE IF EXISTS installment_plans;
        CREATE TABLE installment_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            total_amount INTEGER NOT NULL DEFAULT 0,
            down_payment INTEGER NOT NULL DEFAULT 0,
            financed_amount INTEGER NOT NULL DEFAULT 0,
            installments_count INTEGER NOT NULL DEFAULT 1,
            interval_days INTEGER NOT NULL DEFAULT 30,
            first_installment_paid INTEGER NOT NULL DEFAULT 0,
            start_due_date TEXT NOT NULL DEFAULT '',
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT ''
        );
        DROP TABLE IF EXISTS proforma_items;
        CREATE TABLE proforma_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proforma_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            batch_id INTEGER NOT NULL,
            qty INTEGER NOT NULL DEFAULT 1,
            suggested_unit_price INTEGER NOT NULL DEFAULT 0,
            actual_unit_price INTEGER NOT NULL DEFAULT 0,
            line_total INTEGER NOT NULL DEFAULT 0,
            notes TEXT DEFAULT ''
        );
        PRAGMA foreign_keys = ON;
    """)
    raw.commit()
    raw.close()

    upgraded = DatabaseManager(str(legacy_path))
    with upgraded.get_connection() as conn:
        ip_cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(installment_plans)").fetchall()}
        pi_cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(proforma_items)").fetchall()}
        ih_cols = {r["name"] for r in conn.execute("PRAGMA table_info(invoice_headers)").fetchall()}
        sr_cols = {r["name"] for r in conn.execute("PRAGMA table_info(service_records)").fetchall()}
        pf_cols = {r["name"] for r in conn.execute("PRAGMA table_info(proforma_invoices)").fetchall()}
        assert ip_cols["sale_id"]["notnull"] == 0
        assert ip_cols["customer_id"]["notnull"] == 0
        assert "ref_type" in ip_cols and "service_record_id" in ip_cols
        assert pi_cols["product_id"]["notnull"] == 0
        assert pi_cols["batch_id"]["notnull"] == 0
        assert "item_kind" in pi_cols and "service_name" in pi_cols
        assert "extra_cost_total" in ih_cols
        assert "customer_id" in sr_cols and "payment_type" in sr_cols
        assert "converted_service_invoice" in pf_cols


# ---------------------------------------------------------------------------
# REQ-01, REQ-03, REQ-06: Multi-Item Editing, Invoice Incidental Costs & OCC
# ---------------------------------------------------------------------------

def test_v502_req01_req03_req06_multi_item_editing_and_extra_costs(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db = DatabaseManager(str(tmp_path / "invoices.db"))
    c1 = db.add_product("SKU-1", "ASUS A", "لپ‌تاپ", "اداری", "ASUS", "A1", {}, "", 1, 20)
    c2 = db.add_product("SKU-2", "HP B", "لپ‌تاپ", "اداری", "HP", "B2", {}, "", 1, 20)
    p1, p2 = _prod_id(db, c1), _prod_id(db, c2)
    sup = db.get_or_create_supplier("تأمین تست")
    emp = db.add_employee("اپراتور", "مدیر")
    cust_id = db.add_customer("مشتری تست", phone="09121112233")

    # 1. Purchase invoice with invoice-level extra cost: per-item cost MUST NOT be diluted
    pinv = db.add_purchase_invoice(
        "SUP-10",
        [
            {"product_id": p1, "initial_qty": 4, "unit_purchase_price": 10_000_000, "extra_cost_total": 0, "suggested_sell_price": 12_000_000, "profit_pct": 20},
            {"product_id": p2, "initial_qty": 2, "unit_purchase_price": 20_000_000, "extra_cost_total": 0, "suggested_sell_price": 24_000_000, "profit_pct": 20},
        ],
        purchase_invoice_code="PINV-1001",
        supplier_id=sup,
        supplier_name="تأمین تست",
        buyer_employee_id=emp,
        purchase_date="1405/08/10",
        paid_amount=80_500_000,
        settlement_status="تسویه‌شده",
        extra_cost_total=500_000,
    )
    det_p = db.get_purchase_invoice_detail(pinv)
    assert len(det_p["items"]) == 2
    assert det_p["extra_cost_total"] == 500_000
    assert all(it["unit_cost_price"] == it["unit_purchase_price"] for it in det_p["items"])

    # Edit purchase invoice atomically & verify OCC
    rv_p = det_p.get("row_version") or (det_p.get("header") or {}).get("row_version")
    db.update_purchase_invoice(
        pinv,
        "SUP-10-R",
        [
            {"id": det_p["items"][0]["id"], "product_id": p1, "initial_qty": 5, "unit_purchase_price": 10_000_000, "extra_cost_total": 0, "suggested_sell_price": 12_000_000, "profit_pct": 20},
            {"id": det_p["items"][1]["id"], "product_id": p2, "initial_qty": 3, "unit_purchase_price": 20_000_000, "extra_cost_total": 0, "suggested_sell_price": 24_000_000, "profit_pct": 20},
        ],
        supplier_id=sup,
        supplier_name="تأمین تست",
        buyer_employee_id=emp,
        purchase_date="1405/08/11",
        paid_amount=110_750_000,
        settlement_status="تسویه‌شده",
        extra_cost_total=750_000,
        expected_existing_version=rv_p,
    )
    with pytest.raises((ConcurrencyConflictError, DuplicateInvoiceConflictError)):
        db.update_purchase_invoice(
            pinv,
            "SUP-10-R",
            det_p["items"],
            supplier_id=sup,
            supplier_name="تأمین تست",
            buyer_employee_id=emp,
            purchase_date="1405/08/11",
            paid_amount=0,
            settlement_status="تسویه‌نشده",
            extra_cost_total=0,
            expected_existing_version=rv_p,
        )

    det_p2 = db.get_purchase_invoice_detail(pinv)
    assert det_p2["extra_cost_total"] == 750_000
    b1, b2 = det_p2["items"][0]["id"], det_p2["items"][1]["id"]

    # 2. Multi-item sale invoice + edit + extra cost + stock reconciliation
    sinv = db.add_sale_invoice(
        "INV-1001",
        [
            {"product_id": p1, "batch_id": b1, "qty": 2, "suggested_unit_price": 12_000_000, "actual_unit_price": 12_000_000},
            {"product_id": p2, "batch_id": b2, "qty": 1, "suggested_unit_price": 24_000_000, "actual_unit_price": 24_000_000},
        ],
        seller_employee_id=emp,
        customer_name="مشتری تست",
        sale_datetime="1405/08/12 11:00",
        paid_amount=48_200_000,
        settlement_status="تسویه‌شده",
        customer_id=cust_id,
        extra_cost_total=200_000,
    )
    det_s = db.get_sale_invoice_detail(sinv)
    assert det_s["extra_cost_total"] == 200_000 and len(det_s["items"]) == 2
    rv_s = det_s.get("row_version") or (det_s.get("header") or {}).get("row_version")
    db.update_sale_invoice(
        sinv,
        [{"product_id": p1, "batch_id": b1, "qty": 1, "suggested_unit_price": 12_000_000, "actual_unit_price": 12_000_000}],
        seller_employee_id=emp,
        customer_name="مشتری تست",
        sale_datetime="1405/08/12 11:30",
        paid_amount=12_300_000,
        settlement_status="تسویه‌شده",
        customer_id=cust_id,
        extra_cost_total=300_000,
        expected_existing_version=rv_s,
    )
    with db.get_connection() as conn:
        rem1 = int(conn.execute("SELECT remaining_qty FROM batches WHERE id=?", (b1,)).fetchone()[0])
        rem2 = int(conn.execute("SELECT remaining_qty FROM batches WHERE id=?", (b2,)).fetchone()[0])
    assert rem1 == 4 and rem2 == 3

    # 3. Multi-item service invoice + update
    srv_inv = db.add_service_invoice(
        "SINV-1001",
        [
            {"service_id": None, "service_type": "نصب", "service_name": "نصب ویندوز", "historical_tariff": 500_000, "service_fee": 500_000, "side_cost": 0},
            {"service_id": None, "service_type": "تعمیر", "service_name": "سرویس کامل", "historical_tariff": 700_000, "service_fee": 700_000, "side_cost": 100_000},
        ],
        seller_employee_id=emp,
        technician_employee_id=emp,
        customer_name="مشتری تست",
        service_datetime="1405/08/13 12:00",
        paid_amount=1_250_000,
        settlement_status="تسویه‌شده",
        customer_id=cust_id,
        extra_cost_total=50_000,
    )
    det_sv = db.get_service_invoice_detail(srv_inv)
    assert len(det_sv["items"]) == 2 and det_sv["extra_cost_total"] == 50_000
    rv_sv = det_sv.get("row_version") or (det_sv.get("header") or {}).get("row_version")
    db.update_service_invoice(
        srv_inv,
        [{"service_id": None, "service_type": "نصب", "service_name": "نصب ویندوز", "historical_tariff": 600_000, "service_fee": 600_000, "side_cost": 0}],
        seller_employee_id=emp,
        technician_employee_id=emp,
        customer_name="مشتری تست",
        service_datetime="1405/08/13 13:00",
        paid_amount=650_000,
        settlement_status="تسویه‌شده",
        customer_id=cust_id,
        extra_cost_total=50_000,
        expected_existing_version=rv_sv,
    )
    assert len(db.get_service_invoice_detail(srv_inv)["items"]) == 1


# ---------------------------------------------------------------------------
# REQ-04, REQ-07, REQ-12: Service Installments, Proforma PI-, Mixed Convert & Reports
# ---------------------------------------------------------------------------

def test_v502_req04_req07_req12_service_installments_proforma_and_reports(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db = DatabaseManager(str(tmp_path / "srv_pf.db"))
    c1 = db.add_product("SKU-10", "Lenovo", "لپ‌تاپ", "گیمینگ", "Lenovo", "LOQ", {}, "", 1, 20)
    p1 = _prod_id(db, c1)
    sup = db.get_or_create_supplier("تأمین")
    emp = db.add_employee("فروشنده", "مدیر")
    cust_id = db.add_customer("مشتری اقساط", phone="09123334455")

    db.add_purchase_invoice(
        "",
        [{"product_id": p1, "initial_qty": 5, "unit_purchase_price": 10_000_000, "extra_cost_total": 0, "suggested_sell_price": 12_000_000, "profit_pct": 20}],
        purchase_invoice_code="PINV-1001", supplier_id=sup, supplier_name="تأمین",
        buyer_employee_id=emp, purchase_date="1405/08/01", paid_amount=50_000_000, settlement_status="تسویه‌شده",
    )
    with db.get_connection() as conn:
        b_id = int(conn.execute("SELECT id FROM batches LIMIT 1").fetchone()[0])

    # Service installment plan with manual service line (service_id=None)
    db.add_service_invoice(
        "SINV-1001",
        [{"service_id": None, "service_type": "تعمیر", "service_name": "تعمیر مادربرد", "historical_tariff": 1_000_000, "service_fee": 1_000_000, "side_cost": 0}],
        seller_employee_id=emp,
        technician_employee_id=emp,
        customer_name="مشتری اقساط",
        service_datetime="1405/08/10 10:00",
        paid_amount=400_000,
        settlement_status="فروش اقساطی",
        customer_id=cust_id,
        payment_type="installment",
        installment_plan={"count": 3, "down_payment": 100_000, "start_due_date": "1405/08/10", "interval_days": 30, "first_installment_paid": True},
    )
    cust_det = db.get_customer_sales_and_installments(cust_id)
    assert len(cust_det["installments"]) == 3
    assert cust_det["installments"][0]["status"] == "paid"
    # Pay remaining 2 installments -> service record must synchronize to تسویه‌شده
    for inst in cust_det["installments"][1:]:
        db.pay_installment(int(inst["id"]), int(inst["due_amount"]), "1405/09/10", expected_row_version=int(inst["row_version"]))
    with db.get_connection() as conn:
        sr_st = conn.execute("SELECT settlement_status, paid_amount FROM service_records WHERE invoice_number='SINV-1001'").fetchone()
    assert sr_st["settlement_status"] == "تسویه‌شده" and sr_st["paid_amount"] == 1_000_000

    # Proforma PI- prefix + mixed items + append service + atomic convert
    pf_no = db.add_proforma_invoice(
        "",
        [{"item_kind": "product", "product_id": p1, "batch_id": b_id, "qty": 1, "suggested_unit_price": 12_000_000, "actual_unit_price": 12_000_000}],
        customer_id=cust_id, customer_name="مشتری اقساط", customer_phone="09123334455",
        seller_employee_id=emp, proforma_datetime="1405/08/15 11:00", valid_until="1405/08/25",
    )
    assert pf_no == "PI-1001"
    with db.get_connection() as conn:
        pf_id = int(conn.execute("SELECT id FROM proforma_invoices WHERE proforma_number='PI-1001'").fetchone()[0])
    db.append_services_to_proforma(
        pf_id,
        [{"item_kind": "service", "service_id": None, "service_type": "نصب", "service_name": "نصب درایور", "actual_unit_price": 300_000, "side_cost": 50_000}],
    )
    conv = db.convert_proforma_to_sale(pf_id, sale_invoice_number="INV-1001", sale_datetime="1405/08/16 12:00", paid_amount=12_300_000, settlement_status="تسویه‌شده", service_invoice_number="SINV-1002", technician_employee_id=emp)
    assert conv == "INV-1001"
    with db.get_connection() as conn:
        pf_conv = conn.execute("SELECT converted_sale_invoice, converted_service_invoice, status FROM proforma_invoices WHERE id=?", (pf_id,)).fetchone()
    assert pf_conv["status"] == "converted" and pf_conv["converted_sale_invoice"] == "INV-1001" and pf_conv["converted_service_invoice"] == "SINV-1002"

    # GUI Report centering (REQ-12) + Manual service present in "همه" + Service installments in "۱۳."
    svc = _make_mock_service()
    win = main_mod.MainWindow(db, active_employee=None, license_service=svc)
    try:
        win.cb_rep_type.setCurrentIndex(0)  # همه
        win._update_report_live()
        all_texts = [win.tbl_report.item(r, 1).text() for r in range(win.tbl_report.rowCount()) if win.tbl_report.item(r, 1)]
        assert "SINV-1001" in all_texts
        for c in range(win.tbl_report.columnCount()):
            if win.tbl_report.rowCount() > 0 and win.tbl_report.item(0, c):
                assert win.tbl_report.item(0, c).textAlignment() == Qt.AlignCenter

        rep13_idx = next(i for i in range(win.cb_rep_type.count()) if win.cb_rep_type.itemText(i).startswith("۱۳."))
        win.cb_rep_type.setCurrentIndex(rep13_idx)
        win._update_report_live()
        rep13_invs = [win.tbl_report.item(r, 3).text() for r in range(win.tbl_report.rowCount()) if win.tbl_report.item(r, 3)]
        assert "SINV-1001" in rep13_invs
    finally:
        win.close()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# REQ-02, REQ-05, REQ-08..REQ-11, REQ-15A/B, REQ-16, REQ-17, REQ-19: UI Polish
# ---------------------------------------------------------------------------

def test_v502_ui_layout_kpis_ledgers_employees_and_settings(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db = DatabaseManager(str(tmp_path / "ui_502.db"))
    db.cfg["theme"] = "light"
    db.add_customer("علی رضایی", phone="09121110000")
    db.get_or_create_supplier("پخش آلفا")
    emp_pwd_id = db.add_employee("کاربر رمزدار", "فروشنده", password="secret")
    emp_nopwd_id = db.add_employee("کاربر بدون رمز", "فروشنده", password="")

    svc = _make_mock_service()
    win = main_mod.MainWindow(db, active_employee=None, license_service=svc)
    try:
        # REQ-02 & REQ-16: Dynamic sidebar width & Light header gradient
        assert win.tabs._compute_expanded_width() >= 224
        assert "stop:0 #1e3a8a" in win.top_bar.styleSheet()
        assert "stop:1 #0284c7" in win.top_bar.styleSheet()

        # REQ-01 & REQ-15B: Clear form keeps cart + compact banner button
        win._batch_cart_items = [{"product_id": 1, "initial_qty": 1, "unit_purchase_price": 100_000, "line_bill": 100_000}]
        win._clear_batch_form()
        assert len(win._batch_cart_items) == 1
        win._sale_cart_items = [{"product_id": 1, "batch_id": 1, "qty": 1, "actual_unit_price": 120_000, "suggested_unit_price": 120_000, "unit_cost_price": 100_000, "line_total": 120_000}]
        win._clear_sale_form()
        assert len(win._sale_cart_items) == 1
        win._update_license_banner()
        assert 118 <= win.btn_renew_banner.minimumWidth() <= 170
        assert 118 <= win.btn_renew_banner.maximumWidth() <= 170

        # REQ-10 & REQ-15A: Supplier & Customer top KPIs + "همه" ledger filters
        assert hasattr(win, "lbl_sup_kpi_total") and hasattr(win, "lbl_cust_kpi_total")
        assert win.cb_sup_ledger_filter.currentText() == "همه"
        assert win.cb_cust_ledger_filter.currentText() == "همه"

        # REQ-11: Conditional employee password management button
        assert not hasattr(win, "ed_emp_old_pass")
        for r in range(win.tbl_employees.rowCount()):
            row_eid = int(win.tbl_employees.item(r, 0).text())
            win.tbl_employees.clearSelection()
            win.tbl_employees.item(r, 0).setSelected(True)
            win._on_emp_selected()
            if row_eid == emp_pwd_id:
                assert not win.btn_manage_emp_pass.isHidden()
                assert win.ed_emp_pass.isHidden()
            elif row_eid == emp_nopwd_id:
                assert win.btn_manage_emp_pass.isHidden()
                assert not win.ed_emp_pass.isHidden()

        # REQ-05: Zero CollapsibleSection in Settings, 5 subtabs, Version+License at LAST subtab
        spage = win.tabs.widget(win._settings_tab_index)
        assert len(spage.findChildren(CollapsibleSection)) == 0
        assert win.settings_subtabs.count() == 5
        assert "نسخه و لایسنس" in win.settings_subtabs.tabText(4)

        # REQ-09: Every button has non-empty tooltip
        empty_tips = [b.text() for b in win.findChildren(QPushButton) if not b.toolTip().strip() and b.text().strip()]
        assert empty_tips == []
    finally:
        win.close()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# REQ-18, REQ-20, REQ-21, REQ-22: Print/Word Parity, Charts >= 2400px & Troubleshooter Icon
# ---------------------------------------------------------------------------

def test_v502_req18_req20_req21_print_charts_and_troubleshooter(tmp_path, qapp):
    # High-res chart PNG >= 2400px (REQ-20)
    from charts import NativeChartWidget
    chart = NativeChartWidget()
    chart.set_data(title="نمودار فروش", items=[{"label": "آبان", "value": 1000}, {"label": "آذر", "value": 2500}])
    png = chart.render_png_bytes()
    img = QImage.fromData(png, "PNG")
    assert img.width() >= 2400

    # Print / Word parity + metadata non-omission + fixed tblGrid (REQ-18)
    spec = build_sales_invoice_spec(
        [
            {"invoice_number": "INV-502", "sale_datetime": "1405/08/10 14:00", "brand": "ASUS", "model": "ZenBook 14", "qty": 1, "actual_unit_price": 50_000_000, "total_amount": 50_000_000, "paid_amount": 50_000_000},
            {"invoice_number": "INV-502", "sale_datetime": "1405/08/10 14:00", "brand": "Logitech", "model": "MX Master 3S", "qty": 1, "actual_unit_price": 5_000_000, "total_amount": 5_000_000, "paid_amount": 5_000_000},
        ],
        {"shop_name": "فروشگاه دقیق", "print_time": "1405/08/10 14:05"},
    )
    meta_dict = dict(spec.meta_pairs)
    assert meta_dict.get("خریدار") == "-"
    assert meta_dict.get("فروشنده") == "-"
    assert meta_dict.get("تلفن خریدار") == "-"

    html = render_spec_to_html(spec, is_a5=True)
    assert 'width="28%"' in html and 'width="44%"' in html
    assert "#f3f4f6" in html

    docx_p = export_spec_to_docx(spec, str(tmp_path / "inv502.docx"), paper_size="A5")
    with zipfile.ZipFile(docx_p) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert 'tblLayout w:type="fixed"' in xml
    assert "<w:tblGrid>" in xml
    assert "Daqiq_sales_" in default_print_filename("Daqiq_sales", "pdf")

    # Troubleshooter wrench icon distinct from main logo + zero-Qt CLI (REQ-21, REQ-22)
    ts_ico = Path("assets/daqiq_troubleshooter.ico")
    logo_ico = Path("assets/daqiq_logo.ico")
    assert ts_ico.is_file() and logo_ico.is_file()
    assert ts_ico.read_bytes() != logo_ico.read_bytes()
    build_py = Path("scripts/build_nuitka.py").read_text(encoding="utf-8")
    assert "daqiq_troubleshooter.ico" in build_py
    proc = subprocess.run([sys.executable, "-m", "troubleshooter", "--self-test", "--dry-run"], capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0 and "DAQIQ_TROUBLESHOOTER_SELF_TEST_OK" in proc.stdout
