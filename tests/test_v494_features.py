"""Comprehensive v4.9.4 automated verification suite covering REQ-00 through REQ-14."""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QScrollArea

import database as db_mod
from database import DatabaseManager, validate_schema_column_order
import exporter
from licensing.device_identity import (
    MockHardwareProvider,
    NativeWindowsHardwareProvider,
    create_device_request_dict,
)
from licensing.keys import KeyRegistry
from licensing.license_dialog import LicenseDialog
from licensing.license_models import LicensePayload, ValidationStatus
from licensing.license_policy import (
    ALL_LICENSE_FEATURES,
    LicenseService,
    SUBFEATURE_PARENT_TAB,
)
from licensing.license_store import (
    CLOCK_STATE_FILENAME,
    LicenseStore,
    PRIMARY_CLOCK_FILE,
    RUNTIME_ANCHOR_FILE,
)
from licensing.license_verifier import (
    DOMAIN_PREFIX,
    LicenseVerifier,
    STATUS_MESSAGES_FA,
    canonicalize_payload,
)
from tools.build_key_shards import build_shards
from utils import datetime_format as dtf
from utils import paths as daqiq_paths
from utils_and_widgets import JalaliCalendarDialog, JalaliDateEdit, WarrantyLineEdit


def _make_signed_service(tmp_path: Path, features=None, store_name_provider=None, hw_provider=None, license_type="perpetual"):
    priv = ed25519.Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    pub_b64 = base64.b64encode(pub_raw).decode("ascii")
    key_id = "test-v494-key"
    hw = hw_provider or MockHardwareProvider()
    reg = KeyRegistry({key_id: pub_b64})
    store = LicenseStore(
        machine_dir=str(tmp_path / "lic_machine"),
        user_dir=str(tmp_path / "lic_user"),
        roaming_dir=str(tmp_path / "lic_roaming"),
    )
    verifier = LicenseVerifier(key_registry=reg)
    svc = LicenseService(
        store=store,
        verifier=verifier,
        hardware_provider=hw,
        app_version="4.9.4",
        store_name_provider=store_name_provider,
    )

    if features is not None:
        fp = hw.get_fingerprint()
        payload_obj = LicensePayload(
            format_version=1,
            product_id="daqiq.desktop",
            license_id="LIC-V494-TEST",
            key_id=key_id,
            customer=payload_customer if False else __import__("licensing.license_models", fromlist=["CustomerInfo"]).CustomerInfo(name="Test Customer"),
            license_type=license_type,
            issued_at="2026-01-01T00:00:00Z",
            not_before="2026-01-01T00:00:00Z",
            expires_at="2030-01-01T00:00:00Z" if license_type == "subscription" else None,
            device_fingerprints=[fp],
            max_devices=1,
            features=features,
            min_app_version="4.0.0",
            max_clock_skew_hours=1,
        )
        payload_dict = payload_obj.to_dict()
        canon = canonicalize_payload(payload_dict)
        sig_b64 = base64.b64encode(priv.sign(DOMAIN_PREFIX + canon)).decode("ascii")
        envelope = {
            "envelope_version": 1,
            "algorithm": "Ed25519",
            "key_id": key_id,
            "payload": payload_dict,
            "signature": sig_b64,
        }
        lic_file = tmp_path / "test.daqlic"
        lic_file.write_bytes(json.dumps(envelope, ensure_ascii=False).encode("utf-8"))
        res = svc.import_license_file(str(lic_file))
        assert res.is_valid, res.detail
    return svc, priv, pub_b64, key_id, hw


def _launch_main_window(monkeypatch, tmp_path: Path, *, features=None, license_svc=None):
    import main as main_mod

    db_path = tmp_path / "store.db"
    cfg_path = tmp_path / "app_config.json"
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(cfg_path))
    db = DatabaseManager(str(db_path))
    emp_id = db.add_employee("مدیر کل", "مدیر سیستم", "09120000000", "", "دسترسی کامل (مدیر کل)")
    with db.get_connection() as conn:
        emp = dict(conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone())

    if license_svc is None:
        license_svc, *_ = _make_signed_service(
            tmp_path, features=features or {k: True for k in ALL_LICENSE_FEATURES}
        )

    win = main_mod.MainWindow(db, emp, license_service=license_svc)
    return win, db, main_mod


# ---------------------------------------------------------------------------
# REQ-01..05: Offline Licensing, Zero winreg & Multi-Anchor Clock Guard
# ---------------------------------------------------------------------------

def test_zero_winreg_in_licensing_modules():
    """Verify REQ-05 & Trap 2: winreg is completely removed from licensing modules."""
    licensing_dir = Path(__file__).resolve().parent.parent / "licensing"
    for py_file in licensing_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert not re.search(r"\bimport\s+winreg\b|\bfrom\s+winreg\b", content), py_file.name


def test_multi_anchor_clock_guard_rollback_and_recovery(tmp_path):
    """Verify dual HMAC-SHA256 anchors detect clock rollback and recover when clock advances."""
    svc, *_ = _make_signed_service(
        tmp_path,
        features={"sales": True},
        license_type="subscription",
    )
    assert svc.check_license(force_reload=True).is_valid

    now = dt.datetime.now(dt.timezone.utc)
    future_utc = now + dt.timedelta(hours=5)
    # Record legitimate future timestamp into redundant anchors
    svc.store.check_and_update_clock_state(
        device_fingerprint=svc.get_hardware_fingerprint(),
        is_subscription=True,
        now_utc=future_utc,
        tolerance_sec=3600,
    )

    # Current wall clock appears 5h rolled back -> blocked
    res_tamper = svc.check_license(force_reload=True)
    assert not res_tamper.is_valid
    assert res_tamper.status == ValidationStatus.CLOCK_TAMPERED

    # Deleting primary clock anchor alone cannot bypass redundant roaming anchor
    for d in (svc.store.machine_dir, svc.store.user_dir):
        for fname in (PRIMARY_CLOCK_FILE, CLOCK_STATE_FILENAME):
            p = Path(d) / fname
            if p.exists():
                p.unlink()
    assert Path(svc.store.roaming_dir, RUNTIME_ANCHOR_FILE).is_file()
    res_still_tampered = svc.check_license(force_reload=True)
    assert res_still_tampered.status == ValidationStatus.CLOCK_TAMPERED

    # Recover cleanly once system clock reaches/exceeds high-water mark
    svc.clock_provider = lambda: future_utc + dt.timedelta(seconds=30)
    assert svc.check_license(force_reload=True).is_valid


def test_license_independent_from_sqlite_database(tmp_path):
    """Deleting/replacing SQLite DB never invalidates an active commercial license."""
    svc, *_ = _make_signed_service(tmp_path, features={"sales": True})
    db1_path = tmp_path / "db1.db"
    db1 = DatabaseManager(str(db1_path))
    assert svc.check_license(force_reload=True).is_valid
    del db1
    db1_path.unlink(missing_ok=True)
    DatabaseManager(str(tmp_path / "db2.db"))
    assert svc.check_license(force_reload=True).is_valid


# ---------------------------------------------------------------------------
# REQ-06: LicenseDialog Theme Isolation, RTL Status, Bottom Label & Copy
# ---------------------------------------------------------------------------

def test_license_dialog_theme_isolation_and_concise_copy(qapp, tmp_path):
    """Verify Light/Dark palette isolation, SVG logo, no 'تجاری', concise messages, copy label."""
    from PySide6.QtWidgets import QWidget

    dark_host = QWidget()
    dark_host.setStyleSheet("QDialog, QWidget { background-color: #0b1120; color: #f8fafc; }")
    try:
        svc, *_ = _make_signed_service(tmp_path, features=None)
        svg_path = Path(__file__).resolve().parent.parent / "assets" / "daqiq_logo.svg"
        dlg = LicenseDialog(
            service=svc,
            parent=dark_host,
            icon_path=str(svg_path),
            is_dark_theme=False,
            is_startup_gate=False,
        )
        assert "#LicenseDialogRoot" in dlg.styleSheet()
        assert dlg.findChild(QScrollArea) is not None

        # Explicit light palette wins despite dark app QSS
        win_rgb = dlg.palette().color(QPalette.Window).name().lower()
        assert win_rgb == "#f4f7fb"

        all_labels = " ".join(lbl.text() for lbl in dlg.findChildren(QLabel))
        assert "تجاری" not in all_labels
        assert "فایل لایسنس یافت نشد" not in all_labels
        assert "جزئیات:" not in all_labels
        assert "شناسه امنیتی برنامه" in dlg.lbl_key_fp.text()
        from PySide6.QtWidgets import QPushButton
        assert any(b.text() == "بستن" for b in dlg.findChildren(QPushButton))

        assert "فایل لایسنس یافت نشد" not in STATUS_MESSAGES_FA[ValidationStatus.MISSING]

        assert any(
            lbl.pixmap() is not None and not lbl.pixmap().isNull()
            for lbl in dlg.findChildren(QLabel)
        )

        dlg._copy_fingerprint()
        assert "کپی شد" in dlg.btn_copy_fp.text()
        assert dlg._hw_fp_revert_timer.isActive()

        dlg._copy_key_fingerprint(None)
        assert "کپی شد" in dlg.lbl_key_fp.text()
        assert dlg._key_fp_revert_timer.isActive()
        dlg.close()
    finally:
        dark_host.close()


# ---------------------------------------------------------------------------
# REQ-07: Authoritative Outer Executable Dir & Nuitka Cache Bypass
# ---------------------------------------------------------------------------

def test_paths_resolution_ignores_nuitka_cache_and_integer_parent(monkeypatch, tmp_path):
    """Verify Trap 1: NUITKA_ONEFILE_BINARY overrides cached sys.executable and PID env."""
    outer_dir = tmp_path / "PortableStore" / "Daqiq"
    outer_dir.mkdir(parents=True)
    cache_dir = tmp_path / "AppData" / "Local" / "Daqiq" / "4.9.4"
    cache_dir.mkdir(parents=True)

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    monkeypatch.setenv("NUITKA_ONEFILE_PARENT", "54321")  # integer PID must NEVER be treated as path
    monkeypatch.setenv("NUITKA_ONEFILE_BINARY", str(outer_dir / "Daqiq.exe"))
    monkeypatch.setattr(sys, "executable", str(cache_dir / "Daqiq.exe"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    resolved = daqiq_paths.get_executable_dir()
    assert resolved == outer_dir.resolve()
    assert daqiq_paths.get_default_taxonomy_path() == (outer_dir / "default_taxonomy.json").resolve()
    assert daqiq_paths.get_app_config_path() == (outer_dir / "app_config.json").resolve()


def test_print_paths_cli_from_separate_cwd(tmp_path):
    """Verify --print-paths runs cleanly without launching UI/DB and prints resolved paths."""
    repo_root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, str(repo_root / "main.py"), "--print-paths"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert f"EXECUTABLE_DIR={repo_root.resolve()}" in proc.stdout
    assert "APP_CONFIG_PATH=" in proc.stdout
    assert "DEFAULT_TAXONOMY_PATH=" in proc.stdout


# ---------------------------------------------------------------------------
# REQ-08: WarrantyLineEdit Selection, Batch Tooltip Alignment & ZWNJ Label
# ---------------------------------------------------------------------------

def test_warranty_line_edit_mouse_release_selects_digits_only(qapp):
    """Verify Trap 5: mouse press+release selects only numeric part; typing keeps unit intact."""
    edit = WarrantyLineEdit("")
    edit.setText("12 ماه")
    edit.show()
    qapp.processEvents()

    press = QMouseEvent(
        QEvent.MouseButtonPress,
        QPointF(10, 10),
        QPointF(10, 10),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    release = QMouseEvent(
        QEvent.MouseButtonRelease,
        QPointF(10, 10),
        QPointF(10, 10),
        Qt.LeftButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(edit, press)
    QApplication.sendEvent(edit, release)
    qapp.processEvents()
    assert edit.selectedText() == "12"

    edit.insert("18")
    assert edit.text() == "18 ماه"
    edit.close()


def test_sales_batch_tooltip_matches_product_rtl_and_zwnj_label(qapp, monkeypatch, tmp_path):
    """Verify Trap 4: cb_sale_batch tooltips match cb_sale_prod RTL; label has exact ZWNJ."""
    win, db, _ = _launch_main_window(monkeypatch, tmp_path)
    try:
        db.add_product("P-100", "لپ‌تاپ ROG", "قطعات", "لپ‌تاپ", "Asus", "ROG", {}, "")
        with db.get_connection() as conn:
            prod_id = conn.execute("SELECT id FROM products WHERE code='P-100'").fetchone()["id"]
        db.add_batch("B-100", prod_id, None, None, "INV-1", "1405/01/01", 5, 1000, 0, 2000, 0, purchase_time="09:15:00")
        win.refresh_all_data()
        p_idx = next(
            i for i in range(win.cb_sale_prod.count())
            if isinstance(win.cb_sale_prod.itemData(i), dict)
            and win.cb_sale_prod.itemData(i).get("code") == "P-100"
        )
        win.cb_sale_prod.setCurrentIndex(p_idx)
        win._on_sale_prod_changed()

        b_idx = next(
            i for i in range(win.cb_sale_batch.count())
            if isinstance(win.cb_sale_batch.itemData(i), dict)
            and win.cb_sale_batch.itemData(i).get("batch_code") == "B-100"
        )
        tip = win.cb_sale_batch.itemData(b_idx, Qt.ToolTipRole) or ""
        assert "direction:ltr" not in tip
        assert "text-align:left" not in tip
        assert "کد محموله: B-100" in tip

        labels = [lbl.text() for lbl in win.ed_sale_specs.parentWidget().findChildren(QLabel)]
        assert "مشخصات فنی فروخته‌شده:" in labels
    finally:
        win.close()


# ---------------------------------------------------------------------------
# REQ-09: Multi-Origin Calendar Conversion, AM/PM & Chronological Sorting
# ---------------------------------------------------------------------------

def test_mixed_origin_calendar_migration_and_chronological_sorting(tmp_path):
    """Verify Jalali + Hijri mixed DB converts cleanly to Gregorian AM/PM and sorts chronologically."""
    db_path = tmp_path / "mixed.db"
    db = DatabaseManager(str(db_path))
    db.add_product("P-1", "قطعات Intel", "قطعات", "CPU", "Intel", "i5", {}, "")
    with db.get_connection() as conn:
        p_id = conn.execute("SELECT id FROM products WHERE code='P-1'").fetchone()["id"]
    db.add_batch("B-OLD-AM", p_id, None, None, "", "1405/01/15", 1, 100, 0, 150, 0, purchase_time="09:00:00 AM")
    db.add_batch("B-OLD-PM", p_id, None, None, "", "1405/01/15", 1, 100, 0, 150, 0, purchase_time="02:30:00 PM")
    db.add_batch("B-HIJRI", p_id, None, None, "", "1447/10/17", 1, 100, 0, 150, 0, purchase_time="16:45:00")
    db.set_setting("calendar_format", "hijri")
    db.set_setting("time_format", "24h")

    with db.get_connection() as conn:
        conn.execute("CREATE TABLE custom_events (id INTEGER PRIMARY KEY, event_date TEXT)")
        conn.execute("INSERT INTO custom_events (event_date) VALUES ('1405/01/15')")
        conn.commit()

    res = dtf.migrate_database_datetime(db, "gregorian", "12h", create_backup=False)
    assert res["status"] == "success"

    with db.get_connection() as conn:
        rows = {
            r["batch_code"]: r["purchase_date"]
            for r in conn.execute("SELECT batch_code, purchase_date FROM batches").fetchall()
        }
        assert rows["B-OLD-AM"] == "2026/04/04 09:00:00 AM"
        assert rows["B-OLD-PM"] == "2026/04/04 02:30:00 PM"
        assert rows["B-HIJRI"] == "2026/04/05 04:45:00 PM"
        ev = conn.execute("SELECT event_date FROM custom_events WHERE id=1").fetchone()["event_date"]
        assert ev == "2026/04/04"

    res2 = dtf.migrate_database_datetime(db, "gregorian", "12h", create_backup=False)
    assert res2["status"] == "noop"

    samples = ["2026/04/04 02:30:00 PM", "2026/04/04 09:00:00 AM", "2026/04/04 12:15:00 AM"]
    ordered = sorted(samples, key=lambda s: dtf.chronological_sort_key(s))
    assert ordered == ["2026/04/04 12:15:00 AM", "2026/04/04 09:00:00 AM", "2026/04/04 02:30:00 PM"]


def test_hijri_gregorian_date_picker_dialog(qapp):
    """Verify JalaliDateEdit & JalaliCalendarDialog support Hijri and Gregorian pickers cleanly."""
    de_h = JalaliDateEdit(default_today=False, calendar_format="hijri")
    de_h.set_date("1447/10/17")
    dlg_h = JalaliCalendarDialog(de_h.get_date(), de_h, cal_format="hijri")
    assert "قمری" in dlg_h.windowTitle()
    dlg_h.close()

    de_g = JalaliDateEdit(default_today=False, calendar_format="gregorian")
    de_g.set_date("2026/04/05")
    dlg_g = JalaliCalendarDialog(de_g.get_date(), de_g, cal_format="gregorian")
    assert "میلادی" in dlg_g.windowTitle()
    dlg_g.close()


# ---------------------------------------------------------------------------
# REQ-10: Clean .daqreq, SMBIOS Type 4 CPU Model, store_name Sync & Key Config
# ---------------------------------------------------------------------------

def test_clean_daqreq_smbios_type4_and_store_sync(monkeypatch, tmp_path):
    """Verify .daqreq cleanliness, SMBIOS Type 4 CPU model, store_name sync, and key precedence."""
    if sys.platform == "win32":
        cpu = NativeWindowsHardwareProvider().get_cpu_model()
        assert cpu
        smbios_cpu = NativeWindowsHardwareProvider()._query_native_smbios_with_cpu()[4]
        if smbios_cpu:
            assert cpu == smbios_cpu
            assert "Family " not in cpu

    svc, *_ = _make_signed_service(
        tmp_path, features={"sales": True}, store_name_provider=lambda: "فروشگاه دقیق پلاس"
    )
    out_req = tmp_path / "dev.daqreq"
    svc.export_device_request_file(str(out_req))
    req = json.loads(out_req.read_text(encoding="utf-8"))
    assert req["store_name"] == "فروشگاه دقیق پلاس"
    assert "hardware_anchors" not in req
    assert "device_label" not in req

    local_cfg_path = tmp_path / "local.json"
    local_cfg_path.write_text(
        json.dumps({"fp_prefix": "dq_local:", "key_id": "local-k1"}),
        encoding="utf-8",
    )
    out_shards = tmp_path / "_embedded_test.py"
    manifest = Path(__file__).resolve().parent.parent / "licensing" / "trusted_keys.json"
    monkeypatch.setenv("DAQIQ_LICENSE_FP_PREFIX", "dq_env")
    res_shards = build_shards(
        str(out_shards),
        str(manifest),
        local_config_path=str(local_cfg_path),
    )
    assert res_shards.fp_prefix == "dq_env:"
    assert res_shards[0]["key_id"] == "local-k1"
    generated_src = out_shards.read_text(encoding="utf-8")
    assert "_FP_PREFIX = 'dq_env:'" in generated_src


# ---------------------------------------------------------------------------
# REQ-11: Granular Feature Locks, Tab Interception & Startup Auto-Select
# ---------------------------------------------------------------------------

def test_granular_subfeature_locks_and_startup_tab_selection(qapp, monkeypatch, tmp_path):
    """Verify 14 granular subfeatures, Settings locked popup, and startup first unlocked tab."""
    assert len(SUBFEATURE_PARENT_TAB) == 14

    features = {k: True for k in ALL_LICENSE_FEATURES}
    features["dashboard"] = False
    features["products"] = False
    features["manual_backup_restore"] = False

    win, _, _ = _launch_main_window(monkeypatch, tmp_path, features=features)
    try:
        # Startup auto-selects first unlocked tab (batches == index 2) without blocking popups
        assert win.tabs.currentIndex() == 2

        popups = []
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(
            QDialog,
            "exec",
            lambda self: popups.append(self.windowTitle()) or QDialog.Rejected,
        )
        monkeypatch.setattr(
            QMessageBox,
            "exec",
            lambda self: popups.append(self.windowTitle()) or QMessageBox.Rejected,
        )
        assert not win._require_license_feature("products")
        assert popups, "Locked feature must invoke locked-access popup"

        popups.clear()
        win._do_manual_backup()
        assert popups, "Locked manual_backup_restore subfeature must block cleanly"
    finally:
        win.close()


# ---------------------------------------------------------------------------
# REQ-12 & REQ-13: Purchase Reordering + purchase_time, Sales dt_sale_date + Warranty Sync
# ---------------------------------------------------------------------------

def test_purchase_layout_order_and_purchase_time_and_sales_date(qapp, monkeypatch, tmp_path):
    """Verify REQ-12 field order/purchase_time persistence & REQ-13 dt_sale_date row 5 + warranty."""
    legacy_db_path = tmp_path / "legacy_v493.db"
    init_db = DatabaseManager(str(legacy_db_path))
    del init_db
    with sqlite3.connect(str(legacy_db_path)) as raw_conn:
        cols_no_pt = [
            "id", "batch_code", "product_id", "serial_numbers", "supplier_id", "buyer_employee_id",
            "invoice_number", "purchase_date", "initial_qty", "sold_qty", "returned_qty", "remaining_qty",
            "unit_purchase_price", "extra_cost_total", "upgrade_cost_unit", "unit_cost_price",
            "suggested_sell_price", "profit_pct", "paid_amount", "settlement_status", "colors_json",
            "initial_specs", "final_specs", "supplier_name_snapshot", "notes", "created_at", "updated_at",
        ]
        raw_conn.execute(f"CREATE TABLE batches_old AS SELECT {', '.join(cols_no_pt)} FROM batches")
        raw_conn.execute("DROP TABLE batches")
        raw_conn.execute("ALTER TABLE batches_old RENAME TO batches")
        raw_conn.commit()
    upgraded_db = DatabaseManager(str(legacy_db_path))
    with upgraded_db.get_connection() as conn:
        validate_schema_column_order(conn)
        col_names = [r["name"] for r in conn.execute("PRAGMA table_info(batches)").fetchall()]
        assert "purchase_time" not in col_names
        assert "purchase_date" in col_names

    win, db, _ = _launch_main_window(monkeypatch, tmp_path)
    try:
        db.add_product("P-900", "گوشی S24", "قطعات", "موبایل", "Samsung", "S24", {}, "")
        win.refresh_all_data()

        batch_grid = win.dt_batch_date.parentWidget().layout()
        idx_dt = batch_grid.indexOf(win.dt_batch_date)
        idx_colors = batch_grid.indexOf(win.btn_batch_colors)
        idx_qty = batch_grid.indexOf(win.cb_batch_qty)
        assert batch_grid.getItemPosition(idx_dt)[0] == 4
        assert batch_grid.getItemPosition(idx_colors)[0] == 4
        assert batch_grid.getItemPosition(idx_qty)[0] == 2

        headers = [win.tbl_batches.horizontalHeaderItem(c).text() for c in range(win.tbl_batches.columnCount())]
        idx_pdate = headers.index("تاریخ خرید")
        assert "ساعت خرید" not in headers

        exp_keys = [k for k, _ in exporter.INVENTORY_EXPORT_AVAILABLE_COLUMNS]
        assert "purchase_date" in exp_keys
        assert "purchase_time" not in exp_keys

        win.cb_batch_prod.setCurrentIndex(0)
        win.dt_batch_date.set_date("1405/02/10")
        win._save_new_batch()
        assert win.tbl_batches.rowCount() == 1
        assert win.tbl_batches.item(0, idx_pdate).text().startswith("1405/02/10 ")

        sale_grid = win.dt_sale_date.parentWidget().layout()
        r_we, c_we, _, _ = sale_grid.getItemPosition(sale_grid.indexOf(win.dt_war_end))
        r_sd, c_sd, _, _ = sale_grid.getItemPosition(sale_grid.indexOf(win.dt_sale_date))
        r_sc, c_sc, _, _ = sale_grid.getItemPosition(sale_grid.indexOf(win.btn_sale_colors))
        assert r_we == r_sd == r_sc == 5
        assert c_we < c_sd < c_sc

        win.cb_war_months.setCurrentText("1 ماه")
        win.dt_sale_date.set_date("1405/03/01")
        assert win.dt_war_start.get_date() == "1405/03/01"
        assert win.dt_war_end.get_date() == "1405/03/31"  # 30 days in 31-day Khordad

        win.dt_sale_date.set_date("1405/03/15")
        assert win.dt_war_start.get_date() == "1405/03/15"
        assert win.dt_war_end.get_date() == "1405/04/14"  # +30 days from 1405/03/15

        win.cb_sale_prod.setCurrentIndex(0)
        win._on_sale_prod_changed()
        win.dt_sale_date.set_date("1405/03/15")
        win._save_new_sale()
        with db.get_connection() as conn:
            s = conn.execute("SELECT sale_datetime FROM sales ORDER BY id DESC LIMIT 1").fetchone()
            assert s["sale_datetime"].startswith("1405/03/15 ")
    finally:
        win.close()
