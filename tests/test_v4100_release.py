"""Comprehensive Daqiq v4.10.0 commercial milestone QA suite (REQ-00 through REQ-11)."""

from __future__ import annotations

import ast
import datetime
import json
import os
import sqlite3
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import jdatetime
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from lxml import etree
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPointingDevice
from PySide6.QtWidgets import QApplication, QMessageBox

import database as db_mod
import main as main_mod
from charts import NativeChartWidget
from database import ConcurrencyConflictError, DatabaseManager, SCHEMA_VERSION
from licensing.license_models import (
    CustomerInfo,
    LicenseEnvelope,
    LicensePayload,
    ValidationResult,
    ValidationStatus,
)
from licensing.license_policy import (
    FEATURE_LABELS_FA,
    LicenseService,
    OPTIONAL_DEFAULT_TRUE_FEATURES,
    SUBFEATURE_PARENT_TAB,
)
from licensing.license_store import LicenseStore
from licensing.license_verifier import (
    DOMAIN_PREFIX,
    KeyRegistry,
    LicenseVerifier,
    canonicalize_payload,
    compare_semver,
)
from troubleshooter.core import find_running_daqiq_pids
from troubleshooter.win_ui import (
    BTN_CANCEL,
    BTN_DELETE_DBS,
    BTN_KEEP_DBS,
    BTN_START_RESET,
    compute_centered_button_rects,
)
from utils import datetime_format
from utils.printing import (
    PrintPreviewDialog,
    assert_no_internal_cost_leakage,
    build_purchase_voucher_spec,
    build_sales_invoice_spec,
    build_section_table_spec,
    build_service_or_upgrade_spec,
    export_spec_to_docx,
    render_html_to_pdf,
    render_spec_to_html,
    to_ascii_digits,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setLayoutDirection(Qt.RightToLeft)
    return app


class _FixedHW:
    def __init__(self, fp="fp_v1:v4100_test_fp"):
        self._fp = fp

    def get_fingerprint(self):
        return self._fp

    def get_tiers(self):
        return {"tier1": self._fp}


def _sign_lic(priv: Ed25519PrivateKey, payload: LicensePayload) -> LicenseEnvelope:
    import base64
    raw = DOMAIN_PREFIX + canonicalize_payload(payload.to_dict())
    sig = base64.b64encode(priv.sign(raw)).decode("ascii")
    return LicenseEnvelope(
        envelope_version=1,
        algorithm="Ed25519",
        key_id=payload.key_id,
        payload=payload,
        signature=sig,
    )


def _mock_license_svc(features: dict | None = None, in_grace: bool = False, grace_mode: str = "full"):
    svc = MagicMock(spec=LicenseService)
    feat_map = {
        "dashboard": True, "products": True, "batches": True, "sales": True,
        "services": True, "upgrades": True, "suppliers_payments": True,
        "reports": True, "employees": True, "settings": True,
        "print_invoices": True, "backup_export": True,
        "customers": True, "installments": True,
        "charts_analytics": True, "word_export": True,
    }
    if features:
        feat_map.update(features)
    payload = LicensePayload(
        format_version=1,
        product_id="daqiq.desktop",
        license_id="LIC-V4100-QA",
        key_id="k1",
        customer=CustomerInfo(name="فروشگاه تست"),
        license_type="subscription",
        issued_at="2026-01-01T00:00:00Z",
        not_before="2026-01-01T00:00:00Z",
        expires_at="2030-01-01T00:00:00Z",
        max_devices=1,
        device_fingerprints=["fp_v1:mock"],
        features=feat_map,
    )
    env = LicenseEnvelope(1, "Ed25519", "k1", payload, "sig")
    res = ValidationResult(
        status=ValidationStatus.GRACE_PERIOD if in_grace else ValidationStatus.VALID,
        is_valid=True,
        license=env,
        message_fa="معتبر",
        in_grace_period=in_grace,
        grace_mode=grace_mode if in_grace else None,
        grace_days_remaining=2 if in_grace else 0,
    )
    svc.check_license.return_value = res
    svc.is_write_allowed.return_value = not (in_grace and grace_mode == "readonly")
    svc.is_feature_enabled.side_effect = lambda f: bool(feat_map.get(f, f in OPTIONAL_DEFAULT_TRUE_FEATURES))
    svc.is_feature_enabled_for_result.side_effect = lambda f, _r=None: bool(
        feat_map.get(f, f in OPTIONAL_DEFAULT_TRUE_FEATURES)
    )
    svc.get_support_phone.return_value = "09000000000"
    svc.get_hardware_fingerprint.return_value = "fp_v1:mock"
    return svc


# ---------------------------------------------------------------------------
# REQ-00: SemVer (4.10.0 > 4.9.10), Additive v4.10.0 Upgrade & 50k+ Scalability
# ---------------------------------------------------------------------------

def test_req00_semver_and_additive_upgrade_compatibility(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    assert Path("VERSION").read_text(encoding="utf-8").strip() == "4.10.0"
    assert db_mod.get_live_app_version() == "4.10.0"
    assert main_mod.APP_VERSION == "4.10.0"

    assert compare_semver("4.10.0", "4.9.10") == 1
    assert compare_semver("4.9.10", "4.10.0") == -1
    assert compare_semver("4.10.0", "4.10.0") == 0

    # LicenseVerifier SemVer validation accepts 4.10.0 cleanly for min_app_version="4.9.10"
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes_raw()
    now = datetime.datetime.now(datetime.timezone.utc)
    fp = _FixedHW().get_fingerprint()
    payload = LicensePayload(
        format_version=1,
        product_id="daqiq.desktop",
        license_id="lic-semver",
        key_id="k-sv",
        customer=CustomerInfo(name="Test"),
        license_type="perpetual",
        issued_at=(now - datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        not_before=(now - datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        expires_at=None,
        max_devices=1,
        device_fingerprints=[fp],
        features={"sales": True},
        min_app_version="4.9.10",
        max_app_version="4.10.5",
    )
    env = _sign_lic(priv, payload)
    verifier = LicenseVerifier(key_registry=KeyRegistry({"k-sv": pub}))
    res = verifier.validate_license(env, fp, current_app_version="4.10.0", now_utc=now)
    assert res.is_valid is True

    # Simulate an existing v4.9.10 DB lacking v4.10.0 additive columns/tables
    legacy_db_path = tmp_path / "legacy_484.db"
    db_tmp = DatabaseManager(str(legacy_db_path))
    db_tmp.close()
    raw = sqlite3.connect(str(legacy_db_path))
    raw.execute("DROP TABLE installment_payments")
    raw.execute("DROP TABLE installment_plans")
    # Rebuild minimal customers/sales without tail columns while keeping PRAGMA user_version=484
    raw.execute("CREATE TABLE cust_old (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '', row_version INTEGER NOT NULL DEFAULT 1)")
    raw.execute("INSERT INTO cust_old (name, phone) VALUES ('مشتری قدیمی', '09121112233')")
    raw.execute("DROP TABLE customers")
    raw.execute("ALTER TABLE cust_old RENAME TO customers")
    raw.execute("PRAGMA user_version = 484")
    raw.commit()
    raw.close()

    upgraded = DatabaseManager(str(legacy_db_path))
    with upgraded.get_connection() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 484
        cols_cust = {r["name"] for r in conn.execute("PRAGMA table_info(customers)").fetchall()}
        assert {"national_id", "address", "last_modified_by", "last_modified_at"}.issubset(cols_cust)
        row = conn.execute("SELECT name, phone FROM customers").fetchone()
        assert row["name"] == "مشتری قدیمی"
        idx_names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
        assert {"idx_inst_plans_customer", "idx_inst_pay_due", "idx_sales_customer_id", "idx_customers_name"}.issubset(idx_names)


def test_req00_50000_row_high_load_scalability_benchmark(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db = DatabaseManager(str(tmp_path / "scale_50k.db"))
    db.add_product("P-50K", "", "لپ‌تاپ", "اداری", "LENOVO", "V15", {}, "", 2, 20.0)
    with db.get_connection() as conn:
        pid = conn.execute("SELECT id FROM products WHERE code='P-50K'").fetchone()["id"]
    db.add_batch("C-50K", pid, None, None, "B-1", "1405/01/01 10:00:00", 60000, 10000000, 0, 12000000, 0, "", "", "", "تسویه‌شده")
    cust_ids = [db.add_customer(f"مشتری شماره {i}", phone=f"0912{i:07d}") for i in range(50)]

    with db.get_connection() as conn:
        batch_id = conn.execute("SELECT id FROM batches LIMIT 1").fetchone()["id"]
        rows_to_insert = [
            (
                f"INV-{i:06d}", pid, batch_id, None,
                f"مشتری شماره {i % 50}", f"0912{i % 50:07d}",
                1, 12000000, 12000000, 10000000, 0, 0, 0, 2000000, 2000000,
                12000000, 12000000, "تسویه‌شده",
                f"1405/{(i % 12) + 1:02d}/{(i % 28) + 1:02d} 12:00:00",
                cust_ids[i % 50], "installment" if i % 5 == 0 else "cash",
            )
            for i in range(50000)
        ]
        conn.executemany(
            """
            INSERT INTO sales (
                invoice_number, product_id, batch_id, seller_employee_id,
                customer_name, customer_phone, qty, suggested_unit_price,
                actual_unit_price, unit_cost_price, unit_discount, total_discount,
                price_Markup_unit, unit_profit, total_profit, total_amount, paid_amount,
                settlement_status, sale_datetime, customer_id, payment_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows_to_insert,
        )
        conn.commit()

    t0 = time.perf_counter()
    chart_data = db.get_chart_analytics_data(top_n=10)
    t_chart = time.perf_counter() - t0
    assert chart_data["best_selling"] and chart_data["best_selling"][0]["qty"] == 50000
    assert len(chart_data["time_trend"]) >= 30
    assert t_chart < 2.5, f"50k chart query took too long: {t_chart:.2f}s"

    t1 = time.perf_counter()
    ledgers = db.list_customers_with_ledgers(today_str="1405/06/01")
    t_ledger = time.perf_counter() - t1
    assert len(ledgers) == 50
    assert sum(c["invoice_count"] for c in ledgers) == 50000
    assert t_ledger < 1.5, f"50k customer ledger query took too long: {t_ledger:.2f}s"


# ---------------------------------------------------------------------------
# REQ-01: A5-Default / A4 Toggle B&W Print + Editable RTL Word (.docx) Engine
# ---------------------------------------------------------------------------

def test_req01_all_12_print_specs_a5_default_and_editable_word_docx(tmp_path, qapp):
    # 1. All 12 sections produce valid B&W HTML with Bold B Nazanin + B Titr
    shop = {"shop_name": "فروشگاه دقیق", "shop_phone": "021-88888888", "print_time": "1405/02/15 10:30"}
    sale_spec = build_sales_invoice_spec(
        [{
            "invoice_number": "INV-9001", "sale_datetime": "1405/02/15 10:00",
            "customer_name": "رضا احمدی", "customer_phone": "09123456789",
            "product_title": "لپ‌تاپ ASUS ROG", "qty": 2, "actual_unit_price": 45000000,
            "total_amount": 90000000, "paid_amount": 90000000, "settlement_status": "تسویه‌شده",
            "unit_cost_price": 38000000, "total_profit": 14000000, "profit_pct": 18,
        }],
        shop,
    )
    html_a5 = render_spec_to_html(sale_spec, is_a5=True)
    html_a4 = render_spec_to_html(sale_spec, is_a5=False)
    assert "9pt" in html_a5 and "10pt" in html_a4
    assert "B Nazanin" in html_a5 and "B Titr" in html_a5
    assert_no_internal_cost_leakage(html_a5)
    assert "38,000,000" not in to_ascii_digits(html_a5)

    batch_spec = build_purchase_voucher_spec(
        [{"batch_code": "C-101", "product_title": "کیبورد", "initial_qty": 10, "unit_purchase_price": 500000, "total_bill": 5000000}],
        shop,
    )
    assert "رسید خرید" in render_spec_to_html(batch_spec, is_a5=True)

    srv_spec = build_service_or_upgrade_spec("services", [{"invoice_number": "SRV-1", "service_name": "نصب", "service_fee": 400000, "paid_amount": 400000}], shop)
    upg_spec = build_service_or_upgrade_spec("upgrades", [{"part_desc": "RAM 16G", "added_cost_unit": 2000000}], shop)
    assert "فاکتور خدمات" in render_spec_to_html(srv_spec)
    assert "رسید ارتقای کالا" in render_spec_to_html(upg_spec)

    for sec in ("dashboard_low", "dashboard_employees", "products", "suppliers", "customers", "employees", "service_catalog", "reports", "charts"):
        sec_spec = build_section_table_spec(sec, ["عنوان", "مقدار"], [["آیتم اول", "1000"]], shop_info=shop)
        assert "#000000" in render_spec_to_html(sec_spec, is_a5=True)

    # 2. Dialog defaults to A5 and guards word_export cleanly
    called = []
    dlg = PrintPreviewDialog(lambda is_a5=True: render_spec_to_html(sale_spec, is_a5=is_a5), default_paper="A5", word_export_guard=lambda: called.append(1) or False)
    assert dlg.cb_paper.currentData() == "A5"
    a4_idx = dlg.cb_paper.findData("A4")
    assert a4_idx >= 0
    dlg.cb_paper.setCurrentIndex(a4_idx)
    assert dlg.cb_paper.currentData() == "A4"
    dlg._save_docx()
    assert len(called) == 1
    dlg.close()
    dlg.deleteLater()
    qapp.processEvents()

    # 3. Editable RTL Word (.docx) generation + strict OOXML validation
    chart = NativeChartWidget()
    chart.set_data(title="نمودار تست", chart_type="bar", items=[{"label": "کالای ۱", "value": 1500000}])
    chart_png = chart.render_png_bytes(width=640, height=300, print_bw=True)
    chart_spec = build_section_table_spec("charts", ["کالا", "فروش"], [["کالای ۱", "1,500,000"]], chart_png_bytes=chart_png, shop_info=shop)

    out_docx = tmp_path / "test_export.docx"
    export_spec_to_docx(chart_spec, str(out_docx), paper_size="A5")
    assert out_docx.is_file() and out_docx.stat().st_size > 5000

    with zipfile.ZipFile(out_docx, "r") as zf:
        doc_xml = etree.fromstring(zf.read("word/document.xml"))
        footer_files = [n for n in zf.namelist() if n.startswith("word/footer")]
        assert footer_files, "Expected footer XML with Persian running page numbers"
        footer_xml = etree.fromstring(zf.read(footer_files[0]))
        media_files = [n for n in zf.namelist() if n.startswith("word/media/")]
        assert media_files, "Expected embedded chart PNG inside word/media/"

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    assert doc_xml.xpath(".//w:bidi", namespaces=ns)
    assert doc_xml.xpath(".//w:bidiVisual", namespaces=ns)
    assert doc_xml.xpath(".//w:rtl", namespaces=ns)
    assert doc_xml.xpath(".//w:bCs", namespaces=ns)
    assert doc_xml.xpath(".//w:tblHeader", namespaces=ns)
    assert doc_xml.xpath(".//w:cantSplit", namespaces=ns)
    fonts_cs = doc_xml.xpath(".//w:rFonts/@w:cs", namespaces=ns)
    assert "B Nazanin" in fonts_cs and "B Titr" in fonts_cs
    footer_instr = "".join(footer_xml.xpath(".//w:instrText/text()", namespaces=ns))
    assert "PAGE" in footer_instr and "NUMPAGES" in footer_instr

    # Real multi-page A5 PDF test
    multi_rows = [[f"ردیف کالای تست شماره {i}", str(i * 1000)] for i in range(45)]
    multi_spec = build_section_table_spec("products", ["کالا", "قیمت"], multi_rows, shop_info=shop)
    pdf_out = Path(render_html_to_pdf(render_spec_to_html(multi_spec, is_a5=True), str(tmp_path / "multi_a5.pdf"), paper_size="A5"))
    assert pdf_out.is_file() and pdf_out.read_bytes().startswith(b"%PDF-1.")


# ---------------------------------------------------------------------------
# REQ-02, REQ-03, REQ-04: Layout, RTL Alignment, Persistent Purchase & Sales Forms
# ---------------------------------------------------------------------------

def test_req02_req03_req04_ui_layout_rtl_and_persistent_forms(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db = DatabaseManager(str(tmp_path / "ui_v4100.db"))
    db.add_product("P-101", "", "لوازم جانبی کامپیوتر", "کیبورد", "LOGITECH", "K120", {"نوع اتصال": "با سیم"}, "", 2, 20.0)
    with db.get_connection() as conn:
        prod_id = conn.execute("SELECT id FROM products WHERE code='P-101'").fetchone()["id"]
    db.add_supplier("پخش آواژنگ", "0218888", "تهران")
    svc = _mock_license_svc()
    win = main_mod.MainWindow(db, active_employee=None, license_service=svc)
    try:
        win.resize(1366, 820)
        win.show()
        qapp.processEvents()

        # Tab order & count (12 tabs): مشتری‌ها beside تأمین‌کنندگان; گزارش‌های نموداری beside گزارش‌های جامع
        assert win.tabs.count() == 12
        tab_names = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        idx_sup = next(i for i, t in enumerate(tab_names) if "تأمین‌کنندگان" in t)
        idx_cust = next(i for i, t in enumerate(tab_names) if "مشتری" in t)
        idx_rep = next(i for i, t in enumerate(tab_names) if "گزارش‌های جامع" in t)
        idx_chr = next(i for i, t in enumerate(tab_names) if "گزارش‌های نموداری" in t)
        assert idx_cust == idx_sup + 1
        assert idx_chr == idx_rep + 1

        # Dashboard print button on visual LEFT of expanding search bar under RTL
        for key in ("dashboard_low", "dashboard_employees"):
            btn = win._table_print_buttons[key]
            tbl = win.tbl_dash_low if key == "dashboard_low" else win.tbl_dash_emp
            srch = win._table_search_fields[tbl]
            assert btn.x() < srch.x(), f"Dashboard print button ({btn.x()}) must be visual LEFT of search ({srch.x()})"

        # مدیریت کالا: زیرمجموعه inside gb_prod_form + equal groupbox height
        assert win.gb_prod_form.isAncestorOf(win.cb_prod_sub)
        assert abs(win.gb_prod_form.height() - win.specs_widget.height()) <= 2

        # Settings license button parity
        assert win.btn_settings_license_mgmt.objectName() == "btnSettingsLicense"
        assert win.btn_settings_export_req.objectName() == "btnSettingsLicense"

        # REQ-03: Persistent Purchase Form
        for idx in range(win.cb_batch_prod.count()):
            if (win.cb_batch_prod.itemData(idx) or {}).get("id") == prod_id:
                win.cb_batch_prod.setCurrentIndex(idx)
                break
        win.ed_batch_code.setText("C-7701")
        win.ed_batch_inv.setText("BINV-77")
        win.ed_batch_serial_number.setText("SN-B77")
        win.ed_batch_serial.setText("رنگ مشکی - با گارانتی")
        win.cb_batch_qty.setCurrentText("5")
        win.pr_batch_buy.set_value(1_000_000)
        win.pr_batch_suggest.set_value(1_300_000)
        win.pr_batch_paid.set_value(5_000_000)
        win._save_new_batch()
        assert win.ed_batch_code.text() == ""
        assert win.ed_batch_inv.text() == ""
        assert win._checked_colors(win.btn_batch_colors) == []
        assert win.cb_batch_prod.currentData()["id"] == prod_id
        assert win.pr_batch_buy.get_value() == 1_000_000
        assert win.ed_batch_serial_number.text() == "SN-B77"
        assert win.ed_batch_serial.text() == "رنگ مشکی - با گارانتی"

        # REQ-03: Persistent Sales Form + Silent live remaining_qty & row_version refresh
        for idx in range(win.cb_sale_prod.count()):
            if (win.cb_sale_prod.itemData(idx) or {}).get("id") == prod_id:
                win.cb_sale_prod.setCurrentIndex(idx)
                break
        assert win.cb_sale_batch.count() >= 1
        b_id = win.cb_sale_batch.currentData()["id"]
        rv_before = win.cb_sale_batch.currentData()["row_version"]
        win.ed_sale_inv.setText("INV-8801")
        win.ed_sale_customer.setText("سعید کریمی")
        win.ed_sale_phone.setText("09120001122")
        win.cb_sale_qty.setCurrentText("2")
        win.pr_sale_actual.set_value(1_350_000)
        win.ed_war_company.setText("آواژنگ")
        win.cb_war_months.setCurrentText("1 سال")
        win._save_new_sale()

        # Exception fields reset, persistent fields stay & live stock/row_version updated silently!
        assert win.ed_sale_inv.text() == ""
        assert win._checked_colors(win.btn_sale_colors) == []
        assert win.cb_war_months.currentText() == "بدون گارانتی"
        assert win.dt_war_start.get_date() == ""
        assert win.dt_war_end.get_date() == ""
        assert win.ed_sale_customer.text() == "سعید کریمی"
        assert win.ed_sale_phone.text() == "09120001122"
        assert win.ed_war_company.text() == "آواژنگ"
        live_b = win.cb_sale_batch.currentData()
        assert live_b["id"] == b_id
        assert live_b["remaining_qty"] == 3
        assert live_b["row_version"] > rv_before

        # Rapid Sale #2 succeeds immediately with zero OCC mismatch
        win.ed_sale_inv.setText("INV-8802")
        win.cb_sale_qty.setCurrentText("1")
        win._save_new_sale()
        assert win.cb_sale_batch.currentData()["remaining_qty"] == 2
    finally:
        win.close()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# REQ-05: Customers CRM, Installment Schedule, Rounding, OCC & Delete Cleanup
# ---------------------------------------------------------------------------

def test_req05_customers_and_installment_lifecycle(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db = DatabaseManager(str(tmp_path / "cust_inst.db"))
    db.add_product("P-INS1", "", "لپ‌تاپ", "گیمینگ", "ASUS", "TUF", {}, "", 1, 20.0)
    with db.get_connection() as conn:
        pid = conn.execute("SELECT id FROM products WHERE code='P-INS1'").fetchone()["id"]
    db.add_batch("C-INS1", pid, None, None, "B-1", "1405/01/01 09:00:00", 5, 30000000, 0, 35000000, 0, "", "", "", "تسویه‌شده")
    with db.get_connection() as conn:
        bid = conn.execute("SELECT id FROM batches WHERE batch_code='C-INS1'").fetchone()["id"]

    # Exact remainder on final installment & large 64-bit check
    sched_3 = db.build_installment_schedule(1_000_000, 3, "1405/02/01", interval_days=30, cal_type="jalali")
    assert [s["due_amount"] for s in sched_3] == [333_333, 333_333, 333_334]
    assert sum(s["due_amount"] for s in sched_3) == 1_000_000
    sched_big = db.build_installment_schedule(3_500_000_000, 3, "1405/02/01", interval_days=30, cal_type="jalali")
    assert sum(s["due_amount"] for s in sched_big) == 3_500_000_000

    cid = db.add_customer("علی رضایی", phone="09123334455", national_id="0012345678", address="ونک")
    db.add_sale(
        "INV-INS-1", pid, bid, None, "علی رضایی", 1,
        35_000_000, 35_000_000, 5_000_000, "1405/01/15 14:00:00",
        customer_id=cid, payment_type="installment",
        installment_plan={"down_payment": 5_000_000, "count": 3, "interval_days": 30, "start_due_date": "1405/02/15", "cal_type": "jalali"},
    )

    detail = db.get_customer_sales_and_installments(cid)
    assert len(detail["sales"]) == 1
    assert len(detail["installments"]) == 3
    assert sum(x["due_amount"] for x in detail["installments"]) == 30_000_000

    first_inst = detail["installments"][0]
    db.pay_installment(first_inst["id"], first_inst["due_amount"], "1405/02/15", expected_row_version=first_inst["row_version"])

    # LAN OCC guard prevents stale concurrent double-payment
    with pytest.raises(ConcurrencyConflictError):
        db.pay_installment(first_inst["id"], 1000, "1405/02/16", expected_row_version=first_inst["row_version"])

    # Ledger reflects payment accurately
    ledgers = db.list_customers_with_ledgers(today_str="1405/03/20")
    assert len(ledgers) == 1
    assert ledgers[0]["remaining_debt"] == 20_000_000
    assert ledgers[0]["overdue_count"] == 1  # installment #2 due 1405/03/15 < 1405/03/20

    # Atomic sale deletion cleans up linked installment plans & payments cleanly
    sale_id = detail["sales"][0]["id"]
    db.delete_sale(sale_id)
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM installment_plans").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM installment_payments").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# REQ-06: Native Pure QPainter Interactive Charts
# ---------------------------------------------------------------------------

def test_req06_native_qpainter_charts_all_modes_themes_and_exports(qapp):
    w = NativeChartWidget()
    w.resize(800, 420)
    sample = [
        {"label": "لپ‌تاپ ASUS", "value": 45_000_000, "extra": "3 عدد"},
        {"label": "مانیتور LG", "value": 18_500_000, "extra": "2 عدد"},
        {"label": "کیبورد Logitech", "value": 4_200_000, "extra": "6 عدد"},
    ]
    for ctype in ("bar", "hbar", "line", "donut"):
        for dark in (False, True):
            w.set_dark_theme(dark)
            w.set_data(title=f"نمودار {ctype}", chart_type=ctype, items=sample)
            png = w.render_png_bytes(width=760, height=380, print_bw=False)
            assert png.startswith(b"\x89PNG") and len(png) > 2000

    # Hover interaction never crashes & updates hovered index
    move_ev = QMouseEvent(
        QEvent.MouseMove, QPointF(250.0, 200.0), QPointF(250.0, 200.0),
        Qt.NoButton, Qt.NoButton, Qt.NoModifier, QPointingDevice.primaryPointingDevice(),
    )
    w.mouseMoveEvent(move_ev)
    w.leaveEvent(QEvent(QEvent.Leave))

    # Empty state renders gracefully
    w.set_data(title="نمودار خالی", chart_type="bar", items=[])
    empty_png = w.render_png_bytes(width=640, height=320)
    assert empty_png.startswith(b"\x89PNG")


# ---------------------------------------------------------------------------
# REQ-07, REQ-10: Granular Entitlements, Calendar Migration & Zero-Qt Win32 Troubleshooter
# ---------------------------------------------------------------------------

def test_req07_granular_entitlements_and_calendar_installment_migration(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    # Omitted new keys default True for backward compatibility; explicit False denies
    for key in ("customers", "installments", "charts_analytics", "word_export"):
        assert key in OPTIONAL_DEFAULT_TRUE_FEATURES
        assert key in SUBFEATURE_PARENT_TAB
        assert key in FEATURE_LABELS_FA

    db = DatabaseManager(str(tmp_path / "cal_inst.db"))
    db.add_product("P-CAL1", "", "لپ‌تاپ", "اداری", "HP", "ProBook", {}, "", 1, 20.0)
    with db.get_connection() as conn:
        pid = conn.execute("SELECT id FROM products WHERE code='P-CAL1'").fetchone()["id"]
    db.add_batch("C-CAL1", pid, None, None, "B-1", "1405/01/01 10:00:00", 5, 10000000, 0, 12000000, 0, "", "", "", "تسویه‌شده")
    with db.get_connection() as conn:
        bid = conn.execute("SELECT id FROM batches LIMIT 1").fetchone()["id"]
    # customer sale follows below
    cid = db.add_customer("مشتری تقویم", phone="09129998877")
    db.add_sale(
        "INV-CAL1", pid, bid, None, "مشتری تقویم", 1, 12_000_000, 12_000_000, 2_000_000,
        "1405/01/15 10:00:00", customer_id=cid, payment_type="installment",
        installment_plan={"down_payment": 2_000_000, "count": 2, "interval_days": 30, "start_due_date": "1405/02/15", "cal_type": "jalali"},
    )
    mig = datetime_format.migrate_database_datetime(db, "gregorian", "24h", create_backup=False)
    assert mig["total_updated"] > 0
    with db.get_connection() as conn:
        due_row = conn.execute("SELECT due_date FROM installment_payments ORDER BY installment_no ASC LIMIT 1").fetchone()
        assert due_row["due_date"].startswith("2026-") or due_row["due_date"].startswith("2026/")


def test_req10_zero_qt_win32_rtl_troubleshooter_contract():
    # 1. Pure AST check: ZERO PySide6/PyQt/tkinter/MessageBoxW/daqiq imports inside troubleshooter/*
    forbidden_modules = {"PySide6", "PyQt5", "PyQt6", "shiboken6", "tkinter", "matplotlib"}
    for py_file in Path("troubleshooter").glob("*.py"):
        src = py_file.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_modules
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_modules
        assert "MessageBoxW" not in src, "Troubleshooter must use custom pure-Win32 RTL Persian dialog, never MessageBoxW"

    # 2. Horizontal bottom button centering proof across single, 2-button, and 3-button flows
    for lbls in (
        ["تأیید و بستن"],
        [BTN_START_RESET, BTN_CANCEL],
        [BTN_KEEP_DBS, BTN_DELETE_DBS, BTN_CANCEL],
    ):
        rects = compute_centered_button_rects(560, 240, lbls)
        assert len(rects) == len(lbls)
        left_gap = rects[0]["x"]
        right_gap = 560 - (rects[-1]["x"] + rects[-1]["w"])
        assert abs(left_gap - right_gap) <= 1

    # 3. Running process check never self-matches Troubleshooter
    assert find_running_daqiq_pids(process_lister=lambda: []) == []

    # 4. Run real CLI --self-test & --dry-run
    for flag, marker in (("--self-test", "DAQIQ_TROUBLESHOOTER_SELF_TEST_OK"), ("--dry-run", "DAQIQ_TROUBLESHOOTER_DRY_RUN_OK")):
        proc = subprocess.run([sys.executable, "-m", "troubleshooter.app", flag], capture_output=True, text=True, timeout=30)
        assert proc.returncode == 0, proc.stderr
        assert marker in proc.stdout
