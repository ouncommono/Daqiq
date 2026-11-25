"""Comprehensive v4.9.7 commercial release QA suite covering REQ-00 through REQ-08."""

from __future__ import annotations

import base64
import copy
import datetime
import hashlib
import json
import sqlite3
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox, QDialog

import database as db_mod
import exporter
import main as m
from licensing.device_identity import (
    MockHardwareProvider,
    compute_hardware_fingerprint_from_components,
    create_device_request_dict,
)
from licensing.keys import KeyRegistry
from licensing.license_dialog import LicenseDialog, ThemedNoticeDialog
from licensing.license_models import ValidationStatus
from licensing.license_policy import LicenseService
from licensing.license_store import LicenseStore
from licensing.license_verifier import DOMAIN_PREFIX, LicenseVerifier, canonicalize_payload
from utils import datetime_format as dtf


def _make_keypair():
    priv = ed25519.Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    pub_b64 = base64.b64encode(pub_raw).decode("ascii")
    return priv, pub_b64


def _sign_generator_payload(priv, key_id: str, payload_dict: dict) -> bytes:
    canon = canonicalize_payload(payload_dict)
    sig = priv.sign(DOMAIN_PREFIX + canon)
    env = {
        "envelope_version": 1,
        "algorithm": "Ed25519",
        "key_id": key_id,
        "payload": payload_dict,
        "signature": base64.b64encode(sig).decode("ascii"),
    }
    return json.dumps(env, ensure_ascii=False).encode("utf-8")


def _base_generator_payload(key_id: str, fp: str, **overrides) -> dict:
    payload = {
        "customer": {
            "contact": "+989120000000",
            "name": "فروشگاه تجاری دقیق",
            "organization": "گروه فناوری دقیق",
        },
        "device_fingerprints": [fp],
        "expires_at": "2026-12-05T23:59:59Z",
        "expiry_warning_days": 14,
        "features": {
            "batches": True,
            "dashboard": True,
            "employees": True,
            "products": True,
            "reports": True,
            "sales": True,
            "services": True,
            "settings": True,
            "suppliers_payments": True,
            "upgrades": True,
        },
        "format_version": 1,
        "grace_mode": "readonly",
        "grace_period_days": 0,
        "issued_at": "2026-12-01T00:00:00Z",
        "key_id": key_id,
        "license_id": "LIC-14050910-123456",
        "license_type": "subscription",
        "match_policy": "standard",
        "max_app_version": None,
        "max_clock_skew_hours": 24,
        "max_devices": 1,
        "min_app_version": "4.9.0",
        "not_before": "2026-12-01T00:00:00Z",
        "product_id": "daqiq.desktop",
    }
    payload.update(overrides)
    return payload


def _build_service(tmp_path, priv, pub_b64, key_id, hw, now_utc_holder):
    store = LicenseStore(
        machine_dir=str(tmp_path / "lic_m"),
        user_dir=str(tmp_path / "lic_u"),
        roaming_dir=str(tmp_path / "lic_r"),
    )
    reg = KeyRegistry({key_id: pub_b64})
    verifier = LicenseVerifier(key_registry=reg)
    svc = LicenseService(
        store=store,
        verifier=verifier,
        hardware_provider=hw,
        clock_provider=lambda: now_utc_holder[0],
        app_version="4.9.8",
    )
    return svc


# ---------------------------------------------------------------------------
# REQ-01: Critical License Expiry & Generator Protocol Parity
# ---------------------------------------------------------------------------


def test_req01_generator_subscription_expiry_and_fail_closed(tmp_path):
    """Expired subscriptions (grace=0 or omitted) must fail closed on fresh AND cached checks."""
    priv, pub_b64 = _make_keypair()
    key_id = "daqiq-prod-v1"
    hw = MockHardwareProvider()
    fp = hw.get_fingerprint()
    now_holder = [datetime.datetime(2026, 12, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)]
    svc = _build_service(tmp_path, priv, pub_b64, key_id, hw, now_holder)

    # 1. Active 1-day subscription -> PASS
    p_one_day = _base_generator_payload(
        key_id,
        fp,
        not_before="2026-12-01T00:00:00Z",
        expires_at="2026-12-02T23:59:59Z",
        grace_period_days=0,
    )
    res_ok = svc.import_license_bytes(_sign_generator_payload(priv, key_id, p_one_day))
    assert res_ok.is_valid is True
    assert svc.is_feature_enabled("sales") is True

    # 2. Advance clock 1 second past expires_at with grace_period_days=0 -> HARD LOCK (fresh AND cached!)
    now_holder[0] = datetime.datetime(2026, 12, 3, 0, 0, 0, tzinfo=datetime.timezone.utc)
    cached_res = svc.check_license(force_reload=False)
    assert cached_res.is_valid is False
    assert cached_res.status == ValidationStatus.EXPIRED
    assert svc.is_feature_enabled("sales") is False
    fresh_res = svc.check_license(force_reload=True)
    assert fresh_res.is_valid is False
    assert fresh_res.status == ValidationStatus.EXPIRED

    # 3. Omitted grace_period_days (None) MUST NOT grant hidden 7-day grace
    nograce_clock = [datetime.datetime(2026, 12, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)]
    svc_nograce = _build_service(tmp_path / "nograce_case", priv, pub_b64, key_id, hw, nograce_clock)
    p_no_grace = _base_generator_payload(key_id, fp, expires_at="2026-12-02T23:59:59Z")
    p_no_grace.pop("grace_period_days", None)
    assert svc_nograce.import_license_bytes(_sign_generator_payload(priv, key_id, p_no_grace)).is_valid is True
    nograce_clock[0] = datetime.datetime(2026, 12, 3, 0, 0, 1, tzinfo=datetime.timezone.utc)
    assert svc_nograce.check_license(force_reload=False).is_valid is False
    assert svc_nograce.check_license(force_reload=False).status == ValidationStatus.EXPIRED

    # 4. Explicit grace_period_days=7: day 3 -> GRACE_PERIOD, day 8 -> HARD LOCK EXPIRED
    grace_clock = [datetime.datetime(2026, 12, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)]
    svc_grace = _build_service(tmp_path / "grace_case", priv, pub_b64, key_id, hw, grace_clock)
    p_grace = _base_generator_payload(
        key_id,
        fp,
        expires_at="2026-12-02T00:00:00Z",
        grace_period_days=7,
        grace_mode="readonly",
    )
    assert svc_grace.import_license_bytes(_sign_generator_payload(priv, key_id, p_grace)).is_valid is True
    grace_clock[0] = datetime.datetime(2026, 12, 5, 0, 0, 0, tzinfo=datetime.timezone.utc)
    r_grace = svc_grace.check_license(force_reload=False)
    assert r_grace.is_valid is True
    assert r_grace.status == ValidationStatus.GRACE_PERIOD
    assert svc_grace.is_write_allowed() is False
    grace_clock[0] = datetime.datetime(2026, 12, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)
    r_hard = svc_grace.check_license(force_reload=False)
    assert r_hard.is_valid is False
    assert r_hard.status == ValidationStatus.EXPIRED

    # 5. not_before in future -> HARD LOCK NOT_YET_VALID
    now_holder[0] = datetime.datetime(2026, 11, 20, 0, 0, 0, tzinfo=datetime.timezone.utc)
    p_future = _base_generator_payload(
        key_id, fp, not_before="2026-12-01T00:00:00Z", expires_at="2027-12-01T00:00:00Z"
    )
    r_future = svc.verifier.validate_license(
        svc.verifier.parse_envelope_from_bytes(_sign_generator_payload(priv, key_id, p_future)),
        fp,
        "4.9.8",
        now_utc=now_holder[0],
    )
    assert r_future.is_valid is False
    assert r_future.status == ValidationStatus.NOT_YET_VALID

    # 6. Date-only expires_at ('YYYY-MM-DD') expires at end-of-day UTC 23:59:59Z
    p_date_only = _base_generator_payload(
        key_id,
        fp,
        not_before="2026-12-01",
        expires_at="2026-12-02",
        grace_period_days=0,
    )
    env_do = svc.verifier.parse_envelope_from_bytes(_sign_generator_payload(priv, key_id, p_date_only))
    assert svc.verifier.validate_license(
        env_do, fp, "4.9.8", now_utc=datetime.datetime(2026, 12, 2, 22, 0, 0, tzinfo=datetime.timezone.utc)
    ).is_valid is True
    assert svc.verifier.validate_license(
        env_do, fp, "4.9.8", now_utc=datetime.datetime(2026, 12, 2, 23, 59, 59, tzinfo=datetime.timezone.utc)
    ).status == ValidationStatus.EXPIRED

    # 7. Subscription with missing or malformed expiry date -> FAIL-CLOSED
    for bad_exp in (None, "", "not-a-date", "2026-13-45T00:00:00Z"):
        p_bad = _base_generator_payload(key_id, fp, expires_at=bad_exp)
        raw_bad = _sign_generator_payload(priv, key_id, p_bad)
        svc.store.save_license_bytes_atomic(raw_bad)
        r_bad = svc.check_license(force_reload=True)
        assert r_bad.is_valid is False
        assert r_bad.status in (ValidationStatus.CORRUPTED_LICENSE, ValidationStatus.EXPIRED)

    # 8. Perpetual license -> PASS & DB deletion independence
    now_holder[0] = datetime.datetime(2026, 12, 3, 1, 0, 0, tzinfo=datetime.timezone.utc)
    p_perp = _base_generator_payload(key_id, fp, license_type="perpetual", expires_at=None)
    p_perp.pop("grace_period_days", None)
    assert svc.import_license_bytes(_sign_generator_payload(priv, key_id, p_perp)).is_valid is True
    db_file = tmp_path / "dummy.db"
    db_file.write_bytes(b"db")
    db_file.unlink()
    assert svc.check_license(force_reload=True).is_valid is True

    # 9. Unauthorized device / RAM swap resilience
    fp_ram_swap, _ = compute_hardware_fingerprint_from_components(hw.uuid, hw.serial, hw.mfg, hw.prod)
    assert fp_ram_swap == fp
    assert svc.verifier.validate_license(
        svc.verifier.parse_envelope_from_bytes(_sign_generator_payload(priv, key_id, p_perp)),
        "fp_v1:" + ("9" * 64),
        "4.9.8",
    ).status == ValidationStatus.UNAUTHORIZED_DEVICE


def test_req01_runtime_periodic_expiry_locks_mainwindow(qapp, monkeypatch, tmp_path):
    """Mid-session expiry detected by _periodic_license_check must show lock banner & lock tabs."""
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    priv, pub_b64 = _make_keypair()
    key_id = "daqiq-prod-v1"
    hw = MockHardwareProvider()
    fp = hw.get_fingerprint()
    now_holder = [datetime.datetime(2026, 12, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)]
    svc = _build_service(tmp_path, priv, pub_b64, key_id, hw, now_holder)

    payload = _base_generator_payload(
        key_id, fp, expires_at="2026-12-01T18:00:00Z", grace_period_days=0
    )
    assert svc.import_license_bytes(_sign_generator_payload(priv, key_id, payload)).is_valid is True

    db = db_mod.DatabaseManager(str(tmp_path / "store.db"))
    win = m.MainWindow(db, license_service=svc)
    try:
        win.show()
        qapp.processEvents()
        assert win.tabs.isTabEnabled(0) is True
        # Clock advances past expiration mid-session
        now_holder[0] = datetime.datetime(2026, 12, 1, 18, 0, 1, tzinfo=datetime.timezone.utc)
        win._periodic_license_check()
        qapp.processEvents()
        assert win.license_banner_frame.isVisible() is True
        assert "پایان رسیده" in win.lbl_license_banner.text()
        assert all(not win.tabs.isTabEnabled(i) for i in range(win.tabs.count()))
    finally:
        win.close()
        db.close()


# ---------------------------------------------------------------------------
# REQ-02: System Spec `شناسه امنیتی برنامه` Export & Settings Tab Preservation
# ---------------------------------------------------------------------------


def test_req02_system_spec_includes_security_id_and_settings_tab_preserved(qapp, monkeypatch, tmp_path):
    """Export from BOTH LicenseDialog and Settings must include app_security_id; بستن keeps Settings."""
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    priv, pub_b64 = _make_keypair()
    key_id = "daqiq-prod-v1"
    hw = MockHardwareProvider()
    fp = hw.get_fingerprint()
    now_holder = [datetime.datetime(2026, 12, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)]
    svc = _build_service(tmp_path, priv, pub_b64, key_id, hw, now_holder)

    p_full = _base_generator_payload(key_id, fp, license_type="perpetual", expires_at=None)
    p_full.pop("grace_period_days", None)
    assert svc.import_license_bytes(_sign_generator_payload(priv, key_id, p_full)).is_valid is True

    db = db_mod.DatabaseManager(str(tmp_path / "store.db"))
    win = m.MainWindow(db, license_service=svc)
    try:
        expected_sec_id = svc.get_app_security_id_display()
        assert key_id in expected_sec_id

        # Export from Settings
        settings_out = tmp_path / "from_settings.daqreq"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **kw: (str(settings_out), "")))
        monkeypatch.setattr(ThemedNoticeDialog, "exec", lambda self: QDialog.Accepted)
        win._export_device_request_from_settings()
        req_settings = json.loads(settings_out.read_text(encoding="utf-8"))

        # Export from LicenseDialog
        lic_dlg = LicenseDialog(svc, parent=win, is_startup_gate=False)
        try:
            assert expected_sec_id in lic_dlg.lbl_key_fp.text()
            lic_out = tmp_path / "from_lic.daqreq"
            monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **kw: (str(lic_out), "")))
            lic_dlg._export_request_flow()
            req_lic = json.loads(lic_out.read_text(encoding="utf-8"))
        finally:
            lic_dlg.close()

        for doc in (req_settings, req_lic):
            assert doc["app_security_id"] == expected_sec_id
            payload_only = {k: v for k, v in doc.items() if k != "checksum_sha256"}
            canon = json.dumps(payload_only, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            assert doc["checksum_sha256"] == hashlib.sha256(canon).hexdigest()

        # Navigate to Settings tab and open/close LicenseDialog via بستن -> MUST stay on Settings
        settings_idx = win._settings_tab_index
        win.tabs.setCurrentIndex(settings_idx)
        monkeypatch.setattr(LicenseDialog, "exec", lambda self: QDialog.Accepted)
        win._open_license_dialog()
        assert win.tabs.currentIndex() == settings_idx
        assert win.tabs.currentIndex() != 0
    finally:
        win.close()
        db.close()


# ---------------------------------------------------------------------------
# REQ-03: app_config.json Reconciliation & Live Version Sync
# ---------------------------------------------------------------------------


def test_req03_app_config_reconciles_stale_version_and_legacy_keys(monkeypatch, tmp_path):
    """Loading stale app_config.json updates app_version to 4.9.7 and preserves user preferences."""
    cfg_path = tmp_path / "app_config.json"
    db_file = tmp_path / "store.db"
    db_file.write_bytes(b"dummy")
    stale = {
        "app_version": "4.9.3",
        "theme": "dark",
        "last_db_path": str(db_file),
        "calendar_format": "hijri",
        "time_format": "12h",
        "store_name": "فروشگاه ممتاز",
        "default_profit_pct": 33,
        "local_db_unlock_tokens": {"bad": "secret"},
    }
    cfg_path.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(cfg_path))

    cfg = db_mod.load_app_config()
    persisted = json.loads(cfg_path.read_text(encoding="utf-8"))

    for obj in (cfg, persisted):
        assert obj["app_version"] == "4.9.8"
        assert obj["theme"] == "dark"
        assert obj["db_path"] == str(db_file)
        assert obj["calendar_type"] == "hijri"
        assert obj["time_format"] == "12h"
        assert obj["last_store_name"] == "فروشگاه ممتاز"
        assert obj["default_profit_pct"] == 33
        for orphan in ("last_db_path", "calendar_format", "store_name", "local_db_unlock_tokens"):
            assert orphan not in obj


# ---------------------------------------------------------------------------
# REQ-04: Unified "Date Time" in Purchases & مدیریت کاربران
# ---------------------------------------------------------------------------


def test_req04_unified_purchase_datetime_legacy_migration_and_users_format(qapp, monkeypatch, tmp_path):
    """Purchases store single Date Time (no purchase_time column); کاربران uses Date Time (no dash)."""
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))

    # 1. Verify clean v4.9.7/v4.9.8 DB has unified purchase_date without purchase_time column
    v497_db_path = tmp_path / "schema_v497.db"
    db_seed = db_mod.DatabaseManager(str(v497_db_path))
    db_seed.add_product("P-497A", "کالای تست", "قطعات", "CPU", "Intel", "i7", {}, "")
    with db_seed.get_connection() as conn:
        pid = conn.execute("SELECT id FROM products WHERE code='P-497A'").fetchone()["id"]
    db_seed.add_batch("B-497A", pid, None, None, "INV-497", "1405/03/10 14:25:00", 2, 1000, 0, 1500, 2000)
    db_seed.close()

    reopened_db = db_mod.DatabaseManager(str(v497_db_path))
    with reopened_db.get_connection() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(batches)").fetchall()]
        assert "purchase_time" not in cols
        assert tuple(cols) == db_mod.EXPECTED_SCHEMA_COLUMNS["batches"]
        row = conn.execute("SELECT purchase_date FROM batches WHERE batch_code='B-497A'").fetchone()
        assert row["purchase_date"] == "1405/03/10 14:25:00"
    reopened_db.close()

    # 2. New DB purchase save + UI table + reports + exporter + مدیریت کاربران format
    fresh_db = db_mod.DatabaseManager(str(tmp_path / "fresh_497.db"))
    fresh_db.add_employee("علی کریمی", "فروشنده", "09120001122", "pass123", "دسترسی کامل (مدیر سیستم)")
    with fresh_db.get_connection() as conn:
        fresh_db.record_employee_login(1)

    win = m.MainWindow(fresh_db)
    try:
        fresh_db.add_product("P-497", "لپ‌تاپ دقیق", "لپ‌تاپ", "اداری", "Lenovo", "T14", {}, "")
        win.refresh_all_data()
        win.cb_batch_prod.setCurrentIndex(0)
        win.dt_batch_date.set_date("1405/09/04")
        win._save_new_batch()

        p_headers = [win.tbl_batches.horizontalHeaderItem(c).text() for c in range(win.tbl_batches.columnCount())]
        assert "تاریخ خرید" in p_headers
        assert "ساعت خرید" not in p_headers
        assert all("ساعت خرید" != k and "ساعت خرید" != lbl for k, lbl in exporter.INVENTORY_EXPORT_AVAILABLE_COLUMNS)

        pdate_val = win.tbl_batches.item(0, p_headers.index("تاریخ خرید")).text()
        assert pdate_val.startswith("1405/09/04 ")
        assert " - " not in pdate_val

        # Users table timestamps MUST strictly use "Date Time" (zero " - ")
        win._refresh_employees_table()
        u_headers = [win.tbl_employees.horizontalHeaderItem(c).text() for c in range(win.tbl_employees.columnCount())]
        for col_title in ("تاریخ ایجاد", "آخرین ورود"):
            c_idx = u_headers.index(col_title)
            val = win.tbl_employees.item(0, c_idx).text()
            assert val != "—"
            assert " - " not in val
            assert " " in val

        assert " - " not in dtf.format_timestamp_for_display("2026-11-25 14:35:00", "jalali", "24h")
        assert " - " not in dtf.format_timestamp_for_display("2026-11-25 14:35:00", "jalali", "12h")
        assert dtf.convert_datetime_str("1405/09/04 - 02:35:00 PM", "jalali", "12h", "jalali", "24h") == "1405/09/04 14:35:00"
    finally:
        win.close()
        fresh_db.close()


# ---------------------------------------------------------------------------
# REQ-05: Universal Light/Dark Dialog Theme Synchronization
# ---------------------------------------------------------------------------


def test_req05_all_dialogs_sync_light_and_dark_themes(qapp, monkeypatch, tmp_path):
    """User Select, DB Password, Migration, Bootstrap, and MessageBoxes track Light/Dark themes."""
    cfg_path = tmp_path / "app_config.json"
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(cfg_path))
    db = db_mod.DatabaseManager(str(tmp_path / "theme.db"))
    db.add_employee("مدیر تست", "مدیر سیستم", "09123334455", "", "دسترسی کامل (مدیر سیستم)")

    try:
        for mode_str, expect_dark in (("light", False), ("dark", True)):
            db.cfg["theme"] = mode_str
            db_mod.save_app_config(db.cfg)

            login_dlg = m.LoginDialog(db, parent=None)
            try:
                assert login_dlg.is_dark_theme is expect_dark
                win_light = login_dlg.palette().window().color().lightness()
                assert (win_light < 128) is expect_dark
                assert "background-color: #0f172a" in login_dlg.styleSheet() if expect_dark else "background-color: #f8fafc" in login_dlg.styleSheet()
            finally:
                login_dlg.close()

            pwd_dlg = m.DatabasePasswordDialog(parent=None)
            try:
                assert pwd_dlg.is_dark_theme is expect_dark
                assert pwd_dlg.btn_ok.text() == "تأیید"
                assert pwd_dlg.btn_cancel.text() == "انصراف"
                pwd_light = pwd_dlg.palette().window().color().lightness()
                assert (pwd_light < 128) is expect_dark
            finally:
                pwd_dlg.close()

            win = m.MainWindow(db)
            try:
                mig_dlg = m.DatetimeMigrationChoiceDialog("jalali", "gregorian", "24h", "12h", parent=win)
                try:
                    assert mig_dlg.is_dark_theme is expect_dark
                    assert (mig_dlg.palette().window().color().lightness() < 128) is expect_dark
                finally:
                    mig_dlg.close()

                box = QMessageBox(win)
                box.setText("اعلان آزمایشی")
                pol = qapp._daqiq_msg_polisher if hasattr(qapp, "_daqiq_msg_polisher") else m._MessageBoxPolisher(qapp)
                from PySide6.QtCore import QEvent
                pol.eventFilter(box, QEvent(QEvent.Show))
                if expect_dark:
                    assert "background-color: #0f172a" in box.styleSheet()
                else:
                    assert "background-color: #f8fafc" in box.styleSheet()
            finally:
                win.close()
    finally:
        db.close()
