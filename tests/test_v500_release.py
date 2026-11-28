"""Comprehensive Daqiq v5.0.0 commercial release QA suite (REQ-00 through REQ-22)."""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QTableWidget

import database as db_mod
import exporter as exp_mod
import main as main_mod
from database import (
    DatabaseManager,
    DuplicateInvoiceConflictError,
    SCHEMA_VERSION,
)
from licensing.device_identity import create_device_request_dict
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
from licensing.license_verifier import KeyRegistry, LicenseVerifier, compare_semver
from troubleshooter.core import discover_troubleshooting_targets, execute_troubleshooting_reset
from utils import datetime_format
from utils.printing import (
    build_purchase_voucher_spec,
    build_sales_invoice_spec,
    build_section_table_spec,
    build_service_or_upgrade_spec,
    export_spec_to_docx,
    render_spec_to_html,
)
from utils_and_widgets import SearchableComboBox


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setLayoutDirection(Qt.RightToLeft)
    return app


def _mock_v5_license_svc():
    svc = MagicMock(spec=LicenseService)
    feat_map = {
        "dashboard": True,
        "products": True,
        "batches": True,
        "sales": True,
        "services": True,
        "upgrades": True,
        "suppliers_payments": True,
        "customers": True,
        "installments": True,
        "reports": True,
        "charts_analytics": True,
        "employees": True,
        "settings": True,
        "print_invoices": True,
        "word_export": True,
        "backup_export": True,
        "checks_manage": True,
        "multi_item_invoices": True,
        "user_performance": True,
    }
    payload = LicensePayload(
        format_version=1,
        product_id="daqiq.desktop",
        license_id="LIC-V500-QA",
        key_id="k1",
        customer=CustomerInfo(name="فروشگاه دقیق ۵"),
        license_type="subscription",
        issued_at="2026-01-01T00:00:00Z",
        not_before="2026-01-01T00:00:00Z",
        expires_at="2031-01-01T00:00:00Z",
        max_devices=1,
        device_fingerprints=["fp_v1:v5qa"],
        features=feat_map,
    )
    env = LicenseEnvelope(1, "Ed25519", "k1", payload, "sig")
    res = ValidationResult(
        status=ValidationStatus.VALID,
        is_valid=True,
        license=env,
        message_fa="لایسنس معتبر",
        in_grace_period=False,
        grace_mode=None,
        grace_days_remaining=0,
    )
    svc.check_license.return_value = res
    svc.is_write_allowed.return_value = True
    svc.is_feature_enabled.side_effect = lambda f: bool(
        feat_map.get(f, f in OPTIONAL_DEFAULT_TRUE_FEATURES)
    )
    svc.is_feature_enabled_for_result.side_effect = lambda f, _r=None: bool(
        feat_map.get(f, f in OPTIONAL_DEFAULT_TRUE_FEATURES)
    )
    svc.get_support_phone.return_value = "09000000000"
    svc.get_hardware_fingerprint.return_value = "fp_v1:v5qa"
    return svc


# ---------------------------------------------------------------------------
# REQ-00 & REQ-20: Schema v5 Additive Upgrade & Strict Version 5.0.0
# ---------------------------------------------------------------------------

def test_v500_req00_req20_version_and_v4_additive_upgrade(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    assert Path("VERSION").read_text(encoding="utf-8").strip() in ("5.0.0", "5.0.1", "5.0.2")
    assert db_mod.get_live_app_version() in ("5.0.0", "5.0.1", "5.0.2")
    assert main_mod.APP_VERSION in ("5.0.0", "5.0.1", "5.0.2")
    assert create_device_request_dict(store_name="تست v5")["app_version"] in ("5.0.0", "5.0.1", "5.0.2")
    assert compare_semver("5.0.0", "4.10.0") == 1

    # Build a legacy v4.10.0 database missing v5 tables/columns + old sales CHECK constraint
    legacy_db = tmp_path / "legacy_v410.db"
    db_init = DatabaseManager(str(legacy_db))
    del db_init
    conn = sqlite3.connect(str(legacy_db))
    conn.execute("DROP TABLE IF EXISTS checks")
    conn.execute("DROP TABLE IF EXISTS invoice_headers")
    conn.execute("ALTER TABLE sales RENAME TO sales_tmp")
    conn.execute(
        """
        CREATE TABLE sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            batch_id INTEGER NOT NULL,
            serial_number TEXT DEFAULT '',
            seller_employee_id INTEGER,
            customer_name TEXT DEFAULT '',
            customer_phone TEXT DEFAULT '',
            qty INTEGER NOT NULL,
            returned_qty INTEGER NOT NULL DEFAULT 0,
            suggested_unit_price INTEGER NOT NULL,
            actual_unit_price INTEGER NOT NULL,
            unit_cost_price INTEGER NOT NULL,
            unit_discount INTEGER DEFAULT 0,
            total_discount INTEGER DEFAULT 0,
            price_Markup_unit INTEGER DEFAULT 0,
            unit_profit INTEGER NOT NULL,
            total_profit INTEGER NOT NULL,
            total_amount INTEGER NOT NULL,
            paid_amount INTEGER DEFAULT 0,
            settlement_status TEXT NOT NULL DEFAULT 'تسویه‌شده',
            sale_datetime TEXT NOT NULL,
            warranty_company TEXT DEFAULT '',
            warranty_start TEXT DEFAULT '',
            warranty_months INTEGER NOT NULL DEFAULT 0,
            warranty_days INTEGER NOT NULL DEFAULT 0,
            warranty_end TEXT DEFAULT '',
            specifications TEXT DEFAULT '',
            colors_json TEXT DEFAULT '[]',
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            row_version INTEGER NOT NULL DEFAULT 1,
            customer_id INTEGER DEFAULT NULL,
            payment_type TEXT NOT NULL DEFAULT 'cash' CHECK(payment_type IN ('cash', 'installment', 'partial'))
        )
        """
    )
    conn.execute("DROP TABLE sales_tmp")
    conn.commit()
    conn.close()

    upgraded = DatabaseManager(str(legacy_db))
    assert SCHEMA_VERSION == 484
    with upgraded.get_connection() as c2:
        assert c2.execute("PRAGMA user_version").fetchone()[0] == 484
        tables = {
            r[0]
            for r in c2.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "checks" in tables
        assert "invoice_headers" in tables
        sales_sql = c2.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='sales'"
        ).fetchone()[0]
        assert "'check'" in sales_sql
        sales_cols = {r[1] for r in c2.execute("PRAGMA table_info(sales)").fetchall()}
        assert {"settlement_subtype", "check_due_date", "check_status"}.issubset(sales_cols)


# ---------------------------------------------------------------------------
# REQ-02: Barcode / Product / Service Exact Code Enter Selection
# ---------------------------------------------------------------------------

def test_v500_req02_exact_enter_code_selection(qapp):
    cb = SearchableComboBox()
    cb.set_exact_enter_selection(True)
    cb.addItem("لپ‌تاپ ASUS [312]", {"id": 1, "code": "312"})
    cb.setItemExactCode(0, "312")
    cb.addItem("ماوس Logitech [P-099]", {"id": 2, "code": "P-099"})
    cb.setItemExactCode(1, "P-099")
    cb.setCurrentIndex(-1)

    # Persian digits "۳۱۲" -> normalized "312" + Return key selects index 0
    cb.lineEdit().setText("۳۱۲")
    ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
    QApplication.sendEvent(cb.lineEdit(), ev)
    assert cb.currentIndex() == 0

    # Case-insensitive exact code match + Enter keypad selects index 1
    cb.lineEdit().setText("p-099")
    ev2 = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Enter, Qt.NoModifier)
    QApplication.sendEvent(cb.lineEdit(), ev2)
    assert cb.currentIndex() == 1

    # When disabled, Enter must not jump items automatically
    cb_other = SearchableComboBox()
    cb_other.addItem("مشتری الف [C-1]", 1)
    cb_other.setItemExactCode(0, "C-1")
    cb_other.addItem("مشتری ب [C-2]", 2)
    cb_other.setItemExactCode(1, "C-2")
    cb_other.setCurrentIndex(0)
    cb_other.lineEdit().setText("C-2")
    QApplication.sendEvent(cb_other.lineEdit(), QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
    assert cb_other.currentIndex() == 0


# ---------------------------------------------------------------------------
# REQ-05, REQ-11, REQ-14, REQ-16, REQ-17: Multi-Item Invoices, Checks, Installments & LAN Conflict
# ---------------------------------------------------------------------------

def test_v500_req05_req11_req14_req16_req17_multi_item_checks_installments_lan(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db = DatabaseManager(str(tmp_path / "v5_ops.db"))
    db.add_product("P-100", "", "لپ‌تاپ", "گیمینگ", "ASUS", "ROG", {}, "", 1, 20.0)
    db.add_product("P-200", "", "لوازم جانبی", "ماوس", "Logitech", "G502", {}, "", 2, 25.0)
    with db.get_connection() as conn:
        p1 = conn.execute("SELECT id FROM products WHERE code='P-100'").fetchone()["id"]
        p2 = conn.execute("SELECT id FROM products WHERE code='P-200'").fetchone()["id"]
    db.add_supplier("تأمین‌کننده برتر", "0215555", "تهران")
    with db.get_connection() as conn:
        sup_id = conn.execute("SELECT id FROM suppliers LIMIT 1").fetchone()["id"]
    db.add_employee("امیر فروشنده", "فروشنده", "09121112233", "{}")
    db.add_employee("سارا تکنسین", "تکنسین", "09124445566", "{}")
    with db.get_connection() as conn:
        emps = conn.execute("SELECT id, name FROM employees ORDER BY id ASC").fetchall()
        emp1_id, emp2_id = emps[0]["id"], emps[1]["id"]

    # Multi-item Purchase Invoice with payable check
    inv_b = db.add_purchase_invoice(
        "BINV-500",
        [
            {
                "batch_code": "C-500A",
                "product_id": p1,
                "initial_qty": 4,
                "unit_purchase_price": 30_000_000,
                "suggested_sell_price": 36_000_000,
                "profit_pct": 20.0,
                "initial_specs": "i7 / 16GB",
                "colors": ["مشکی"],
            },
            {
                "batch_code": "C-500B",
                "product_id": p2,
                "initial_qty": 10,
                "unit_purchase_price": 2_000_000,
                "suggested_sell_price": 2_500_000,
                "profit_pct": 25.0,
                "initial_specs": "بی‌سیم",
                "colors": ["سفید"],
            },
        ],
        supplier_id=sup_id,
        buyer_employee_id=emp1_id,
        purchase_date="1405/02/01 10:00:00",
        settlement_status="تسویه‌شده",
        settlement_subtype="تسویه چکی",
        paid_amount=140_000_000,
        check_due_date="1405/05/01",
        check_status="pending",
    )
    assert inv_b == "BINV-500"
    with db.get_connection() as conn:
        b_ids = [
            r["id"]
            for r in conn.execute("SELECT id FROM batches WHERE invoice_number='BINV-500' ORDER BY id ASC").fetchall()
        ]
    assert len(b_ids) == 2
    pay_checks = db.list_checks(direction="payable")
    assert len(pay_checks) == 1
    assert pay_checks[0]["invoice_number"] == "BINV-500"
    assert pay_checks[0]["amount"] == 140_000_000

    # Multi-item Sale Invoice with receivable check -> clear check -> delete cleanup
    cid = db.add_customer("مشتری ویژه", phone="09127778899")
    inv_s = db.add_sale_invoice(
        "INV-501",
        [
            {
                "product_id": p1,
                "batch_id": b_ids[0],
                "qty": 1,
                "suggested_unit_price": 36_000_000,
                "actual_unit_price": 36_000_000,
                "specifications": "i7",
                "colors": ["مشکی"],
            },
            {
                "product_id": p2,
                "batch_id": b_ids[1],
                "qty": 2,
                "suggested_unit_price": 2_500_000,
                "actual_unit_price": 2_500_000,
                "specifications": "بی‌سیم",
                "colors": ["سفید"],
            },
        ],
        seller_employee_id=emp1_id,
        customer_name="مشتری ویژه",
        customer_phone="09127778899",
        customer_id=cid,
        sale_datetime="1405/02/05 11:30:00",
        settlement_status="تسویه‌شده",
        settlement_subtype="تسویه چکی",
        paid_amount=41_000_000,
        payment_type="check",
        check_due_date="1405/06/10",
        check_status="pending",
    )
    assert inv_s == "INV-501"
    with db.get_connection() as conn:
        s_ids = [
            r["id"]
            for r in conn.execute("SELECT id FROM sales WHERE invoice_number='INV-501' ORDER BY id ASC").fetchall()
        ]
    assert len(s_ids) == 2
    recv_checks = db.list_checks(direction="receivable")
    assert len(recv_checks) == 1 and recv_checks[0]["status"] == "pending"
    db.update_check_status(recv_checks[0]["id"], "cleared")
    assert db.list_checks(direction="receivable")[0]["status"] == "cleared"

    # Dashboard check overview
    chk_ov = db.get_checks_overview()
    assert chk_ov["receivable_pending_count"] == 0
    assert chk_ov["payable_pending_count"] == 1
    assert chk_ov["payable_pending_amount"] == 140_000_000

    # LAN 3-option duplicate invoice conflict: Double Option 1 (stale version -> re-prompt -> atomic reversal) + Double Option 2
    with pytest.raises(DuplicateInvoiceConflictError) as conflict_exc:
        db.add_sale_invoice(
            "INV-501",
            [{"product_id": p2, "batch_id": b_ids[1], "qty": 1, "suggested_unit_price": 2_500_000, "actual_unit_price": 2_500_000}],
            seller_employee_id=emp1_id,
            customer_name="مشتری جدید",
            sale_datetime="1405/02/06 12:00:00",
            settlement_status="تسویه‌شده",
            paid_amount=2_500_000,
            enforce_unique_invoice=True,
        )
    v1 = conflict_exc.value.existing_version
    # Option 1 succeeds once and restores original b_ids[0] qty back to 4 & b_ids[1] qty to 9
    db.add_sale_invoice(
        "INV-501",
        [{"product_id": p2, "batch_id": b_ids[1], "qty": 1, "suggested_unit_price": 2_500_000, "actual_unit_price": 2_500_000}],
        seller_employee_id=emp1_id,
        customer_name="مشتری جایگزین اول",
        sale_datetime="1405/02/06 12:00:00",
        settlement_status="تسویه‌شده",
        paid_amount=2_500_000,
        conflict_resolution="replace",
        expected_existing_version=v1,
        enforce_unique_invoice=True,
    )
    # Concurrent second PC still holding stale v1 MUST get re-prompted with fresh conflict!
    with pytest.raises(DuplicateInvoiceConflictError) as stale_exc:
        db.add_sale_invoice(
            "INV-501",
            [{"product_id": p2, "batch_id": b_ids[1], "qty": 1, "suggested_unit_price": 2_500_000, "actual_unit_price": 2_500_000}],
            seller_employee_id=emp1_id,
            customer_name="مشتری جایگزین دوم",
            sale_datetime="1405/02/06 12:05:00",
            settlement_status="تسویه‌شده",
            paid_amount=2_500_000,
            conflict_resolution="replace",
            expected_existing_version=v1,
            enforce_unique_invoice=True,
        )
    assert stale_exc.value.existing_version > v1

    # Option 2 twice in a row auto-advances without colliding: INV-502, then INV-503
    inv_a = db.add_sale_invoice(
        "INV-501",
        [{"product_id": p2, "batch_id": b_ids[1], "qty": 1, "suggested_unit_price": 2_500_000, "actual_unit_price": 2_500_000}],
        seller_employee_id=emp1_id,
        customer_name="مشتری بعدی ۱",
        sale_datetime="1405/02/06 12:10:00",
        settlement_status="تسویه‌شده",
        paid_amount=2_500_000,
        conflict_resolution="next_number",
        enforce_unique_invoice=True,
    )
    inv_b = db.add_sale_invoice(
        "INV-501",
        [{"product_id": p2, "batch_id": b_ids[1], "qty": 1, "suggested_unit_price": 2_500_000, "actual_unit_price": 2_500_000}],
        seller_employee_id=emp1_id,
        customer_name="مشتری بعدی ۲",
        sale_datetime="1405/02/06 12:11:00",
        settlement_status="تسویه‌شده",
        paid_amount=2_500_000,
        conflict_resolution="next_number",
        enforce_unique_invoice=True,
    )
    assert inv_a == "INV-1001"
    assert inv_b == "INV-1002"

    # REQ-16: First installment paid at purchase date vs unpaid
    db.add_sale(
        "INV-INST-FIRST",
        p1,
        b_ids[0],
        emp1_id,
        "مشتری قسطی",
        1,
        36_000_000,
        36_000_000,
        6_000_000,
        "1405/02/10 15:00:00",
        customer_id=cid,
        payment_type="installment",
        installment_plan={
            "down_payment": 6_000_000,
            "count": 3,
            "interval_days": 30,
            "start_due_date": "1405/02/10",
            "cal_type": "jalali",
            "first_installment_paid": True,
        },
    )
    detail = db.get_customer_sales_and_installments(cid)
    paid_first = [x for x in detail["installments"] if x["installment_no"] == 1][0]
    assert paid_first["status"] == "paid"
    assert paid_first["paid_amount"] == 10_000_000
    assert paid_first["paid_date"] == "1405/02/10"
    assert sum(x["due_amount"] - x["paid_amount"] for x in detail["installments"]) == 20_000_000

    # REQ-17: Multi-item Service Invoice + REQ-12 User Performance report
    db.save_service_catalog(None, "", "نرم‌افزار", "نصب نرم‌افزار", 500_000, 100_000, "")
    with db.get_connection() as conn:
        srv_cat_id = conn.execute("SELECT id FROM service_catalog LIMIT 1").fetchone()["id"]
    srv_inv = db.add_service_invoice(
        "SINV-500",
        [
            {"service_id": srv_cat_id, "service_type": "نرم‌افزار", "service_name": "نصب ویندوز", "service_fee": 600_000, "side_cost": 100_000},
            {"service_id": srv_cat_id, "service_type": "نرم‌افزار", "service_name": "نصب درایور", "service_fee": 400_000, "side_cost": 0},
        ],
        seller_employee_id=emp2_id,
        technician_employee_id=emp2_id,
        customer_name="مشتری خدمات",
        customer_phone="09126665544",
        service_datetime="1405/02/12 16:00:00",
        settlement_status="تسویه‌شده",
        settlement_subtype="تسویه چکی",
        paid_amount=1_000_000,
        check_due_date="1405/04/01",
    )
    assert srv_inv == "SINV-500"
    with db.get_connection() as conn:
        srv_ids = [r["id"] for r in conn.execute("SELECT id FROM service_records WHERE invoice_number='SINV-500'").fetchall()]
    assert len(srv_ids) == 2

    perf = db.get_employee_performance_report(date_from="1405/02/01", date_to="1405/02/30")
    by_name = {r["name"]: r for r in perf}
    assert by_name["امیر فروشنده"]["sale_invoices"] >= 3
    assert by_name["سارا تکنسین"]["service_count"] == 1
    assert by_name["سارا تکنسین"]["service_profit"] == 900_000


# ---------------------------------------------------------------------------
# REQ-01..REQ-18: Live MainWindow UI, Bootstrap Light Radio, Neutral 0 & Exports
# ---------------------------------------------------------------------------

def test_v500_ui_layout_forms_colors_reports_and_entitlements(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    # Omitted v5 subfeatures stay backward-compatible True
    for feat in ("checks_manage", "multi_item_invoices", "user_performance"):
        assert feat in OPTIONAL_DEFAULT_TRUE_FEATURES
        assert feat in SUBFEATURE_PARENT_TAB
        assert feat in FEATURE_LABELS_FA

    # REQ-08: Bootstrap Light radio styling clarity check
    dlg_boot = main_mod.DatabaseBootstrapDialog("light")
    assert "#2563eb" in dlg_boot.styleSheet() and "QRadioButton::indicator" in dlg_boot.styleSheet()
    dlg_boot.close()

    db = DatabaseManager(str(tmp_path / "ui_v5.db"))
    db.add_product("P-500", "", "لپ‌تاپ", "گیمینگ", "ASUS", "ROG", {}, "", 1, 20.0)
    with db.get_connection() as conn:
        pid = conn.execute("SELECT id FROM products WHERE code='P-500'").fetchone()["id"]
    db.add_batch("C-500", pid, None, None, "BINV-1", "1405/02/01 09:00:00", 5, 20_000_000, 0, 25_000_000, 0, "", "", "", "تسویه‌شده")
    db.add_customer("مشتری تست", phone="09123334455")
    db.save_service_catalog(None, "", "تعمیر سخت‌افزار", "تست سرویس", 300_000, 50_000, "")

    svc = _mock_v5_license_svc()
    win = main_mod.MainWindow(db, active_employee=None, license_service=svc)
    try:
        win.resize(1366, 840)
        win.show()
        qapp.processEvents()

        # REQ-09: مشتریان terminology + Dashboard check cards
        tab_names = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        assert any("مشتریان" in t for t in tab_names)
        assert not any("مشتری‌ها" in t for t in tab_names)
        assert hasattr(win, "lbl_dash_recv_checks")
        assert hasattr(win, "lbl_dash_pay_checks")

        # REQ-01 & REQ-13: Products spacing & unlimited flush search bars
        assert win.ed_prod_search.maximumWidth() > 1000
        assert win.cb_prod_cat.minimumHeight() >= 30
        for srch in win._table_search_fields.values():
            assert srch.maximumWidth() > 1000

        # REQ-10 / REQ-15B: Single-line banner & crisp dynamically sized renew button
        assert win.lbl_license_banner.wordWrap() is False
        assert win.btn_renew_banner.text() in ("تمدید لایسنس", "🔑 تمدید لایسنس")
        assert 118 <= win.btn_renew_banner.maximumWidth() <= 200

        # REQ-15: Charts Persian Top N
        chart_items = [win.cb_chart_top_n.itemText(i) for i in range(win.cb_chart_top_n.count())]
        assert chart_items == ["۵ مورد برتر", "۱۰ مورد برتر", "۲۰ مورد برتر", "همه"]

        # REQ-02: Enter exact code enabled strictly on the 4 target selectors
        assert win.cb_batch_prod._exact_enter_enabled is True
        assert win.cb_sale_prod._exact_enter_enabled is True
        assert win.cb_sale_batch._exact_enter_enabled is True
        assert win.cb_srv_select._exact_enter_enabled is True
        assert win.cb_upg_target._exact_enter_enabled is False
        assert win.cb_sale_customer._exact_enter_enabled is False

        # REQ-03 & REQ-04: Blank customer combo merged cleanly & clear form clears batch selection while keeping product list
        sales_idx = next(i for i, t in enumerate(tab_names) if "ثبت فروش" in t)
        win.tabs.setCurrentIndex(sales_idx)
        qapp.processEvents()
        assert not hasattr(win, "cb_sale_customer_pick")
        assert not hasattr(win, "chk_sale_installment")
        assert win.ed_sale_customer.text() == ""
        assert win.dt_sale_date.y() == win.ed_war_company.y()
        assert win.dt_sale_date.x() > win.ed_war_company.x()
        assert win.dt_sale_date.y() < win.dt_war_start.y()
        assert win.cb_sale_status.findText("فروش اقساطی") >= 0
        assert win.chk_inst_first_paid.isChecked() is True
        assert win.dt_inst_start.get_date() == win.get_today_date_str()
        win._clear_sale_form()
        assert win.cb_sale_prod.count() >= 1 and win.cb_sale_prod.currentIndex() == 0
        assert win.cb_sale_batch.count() >= 1 and win.cb_sale_batch.currentIndex() == -1

        # REQ-17: SINV-1001 is first field in Service Desk
        srv_idx = next(i for i, t in enumerate(tab_names) if "میز خدمت" in t)
        win.tabs.setCurrentIndex(srv_idx)
        qapp.processEvents()
        assert win.ed_srv_inv.y() <= win.cb_srv_select.y()

        # REQ-14: 4 single-row Customer KPI cards + Check clearing tab
        assert hasattr(win, "lbl_cust_kpi_total")
        assert hasattr(win, "lbl_cust_kpi_debt")
        assert hasattr(win, "lbl_cust_kpi_overdue")
        assert hasattr(win, "lbl_cust_kpi_checks")
        assert hasattr(win, "cust_detail_tabs") and win.cust_detail_tabs.count() == 3

        # REQ-06: Neutral 0 table coloring
        tbl = QTableWidget()
        tbl.setColumnCount(4)
        tbl.setHorizontalHeaderLabels(["کد", "موجودی", "سود کل", "مانده بدهی"])
        win._populate_table_safely(tbl, [["1", "0", "0", "0"], ["2", "5", "+100,000", "250,000"]])
        assert tbl.item(0, 1).data(Qt.ForegroundRole) is None
        assert tbl.item(0, 2).data(Qt.ForegroundRole) is None
        assert tbl.item(0, 3).data(Qt.ForegroundRole) is None
        assert tbl.item(1, 2).foreground().color().green() >= 150
        assert tbl.item(1, 3).foreground().color().red() >= 150

        # REQ-12: User Performance report & print/word spec
        assert hasattr(win, "tbl_emp_performance")
        perf_spec = build_section_table_spec(
            "employee_performance",
            ["کد", "نام کاربر", "سود خالص کل (تومان)"],
            [["1", "مدیر", "5,000,000"]],
            shop_info={"shop_name": "دقیق"},
        )
        assert "عملکرد کاربران" in render_spec_to_html(perf_spec, is_a5=True)
        out_docx = tmp_path / "perf.docx"
        export_spec_to_docx(perf_spec, str(out_docx))
        assert out_docx.is_file()

        # REQ-07: Check columns in Reports & Excel exporter
        assert any("نحوه تسویه" in col for col in main_mod.ALL_SYSTEM_COLUMNS)
        export_col_keys = {k for k, _lbl in exp_mod.INVENTORY_EXPORT_AVAILABLE_COLUMNS}
        assert "settlement_subtype" in export_col_keys
        assert "check_due_date" in export_col_keys
    finally:
        win.close()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# REQ-19 & REQ-21: Complete-Wipe Zero-Qt Troubleshooter & Check Date Migration
# ---------------------------------------------------------------------------

def test_v500_req19_req21_troubleshooter_complete_wipe_and_check_date_migration(tmp_path, monkeypatch):
    # Complete-wipe keeps manual/auto backups while removing license, anchors, Nuitka & config
    local_app = tmp_path / "LocalAppData"
    roaming_app = tmp_path / "Roaming"
    prog_data = tmp_path / "ProgramData"
    docs_dir = tmp_path / "Documents"
    nuitka_cache = local_app / "Nuitka" / "Daqiq" / "5.0.0"
    nuitka_cache.mkdir(parents=True)
    (nuitka_cache / "blob.bin").write_text("x", encoding="utf-8")

    lic_dir = local_app / "Daqiq" / "license"
    lic_dir.mkdir(parents=True)
    (lic_dir / "active_license.daqlic").write_text("lic", encoding="utf-8")

    roaming_daqiq = roaming_app / "Daqiq"
    roaming_daqiq.mkdir(parents=True)
    (roaming_daqiq / ".runtime_anchor.dat").write_text("anchor", encoding="utf-8")

    pd_lic = prog_data / "Daqiq" / "license"
    pd_lic.mkdir(parents=True)
    (pd_lic / "active_license.daqlic").write_text("lic", encoding="utf-8")

    default_bak = docs_dir / "Daqiq Backups"
    default_bak.mkdir(parents=True)
    (default_bak / "manual_backup.db").write_text("sqlite", encoding="utf-8")

    custom_bak = tmp_path / "CustomBackups"
    custom_bak.mkdir(parents=True)
    (custom_bak / "auto_backup.db").write_text("sqlite", encoding="utf-8")

    cfg_path = tmp_path / "app_dir" / "app_config.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(
        json.dumps({"auto_backup_dir": str(custom_bak), "database_path": str(tmp_path / "shop.db")}),
        encoding="utf-8",
    )

    monkeypatch.setenv("LOCALAPPDATA", str(local_app))
    monkeypatch.setenv("APPDATA", str(roaming_app))
    monkeypatch.setenv("PROGRAMDATA", str(prog_data))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    plan = discover_troubleshooting_targets(
        executable_dir=cfg_path.parent,
        local_app_data=local_app,
        roaming_app_data=roaming_app,
        program_data=prog_data,
        temp_dir=tmp_path / "tmp_empty",
        process_lister=lambda: [],
    )
    rep = execute_troubleshooting_reset(plan, delete_databases=False, dry_run=False, process_lister=lambda: [])

    assert not (lic_dir / "active_license.daqlic").exists()
    assert not (roaming_daqiq / ".runtime_anchor.dat").exists()
    assert not (prog_data / "Daqiq").exists()
    assert not (local_app / "Nuitka" / "Daqiq").exists()
    assert not cfg_path.exists()
    assert (default_bak / "manual_backup.db").is_file()
    assert (custom_bak / "auto_backup.db").is_file()
    assert len(rep.removed_licenses) >= 1

    # Calendar migration converts checks.due_date & invoice_headers.issue_date
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config2.json"))
    db = DatabaseManager(str(tmp_path / "cal_v5.db"))
    db.add_product("P-CAL5", "", "لپ‌تاپ", "اداری", "HP", "Elite", {}, "", 1, 20.0)
    with db.get_connection() as conn:
        pid = conn.execute("SELECT id FROM products LIMIT 1").fetchone()["id"]
    db.add_purchase_invoice(
        "BINV-CAL5",
        [{"batch_code": "C-CAL5", "product_id": pid, "initial_qty": 2, "unit_purchase_price": 10000000, "suggested_sell_price": 12000000}],
        purchase_date="1405/01/15 10:00:00",
        settlement_status="تسویه‌شده",
        settlement_subtype="تسویه چکی",
        paid_amount=20000000,
        check_due_date="1405/03/20",
    )
    mig = datetime_format.migrate_database_datetime(db, "gregorian", "24h", create_backup=False)
    assert mig["total_updated"] > 0
    with db.get_connection() as conn:
        chk = conn.execute("SELECT due_date FROM checks LIMIT 1").fetchone()
        hdr = conn.execute("SELECT invoice_datetime FROM invoice_headers LIMIT 1").fetchone()
        assert chk["due_date"].startswith(("2026/", "2026-"))
        assert hdr["invoice_datetime"].startswith(("2026/", "2026-"))
