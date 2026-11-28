"""Comprehensive v4.9.6 forensic stability & unmocked end-to-end startup verification suite."""

from __future__ import annotations

import base64
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PySide6.QtCore import Qt, QTimer, QtMsgType
from PySide6.QtWidgets import QApplication, QDialogButtonBox

import database as database_module
import main as main_module
from licensing.device_identity import MockHardwareProvider
from licensing.keys import KeyRegistry
from licensing.license_models import CustomerInfo, LicenseEnvelope, LicensePayload
from licensing.license_policy import ALL_LICENSE_FEATURES, LicenseService
from licensing.license_store import LicenseStore
from licensing.license_verifier import DOMAIN_PREFIX, LicenseVerifier, canonicalize_payload
from utils import paths as daqiq_paths
from utils_and_widgets import JalaliCalendarDialog, JalaliDateEdit, _resolve_ancestor_calendar


def _build_real_signed_license_service(tmp_path: Path, features: dict | None = None) -> LicenseService:
    priv = Ed25519PrivateKey.generate()
    pub_b64 = base64.b64encode(priv.public_key().public_bytes_raw()).decode("ascii")
    hw = MockHardwareProvider()
    fp = hw.get_fingerprint()
    if features is None:
        features = {k: True for k in ALL_LICENSE_FEATURES}

    payload = LicensePayload(
        format_version=1,
        product_id="daqiq.desktop",
        license_id="DAQIQ-V496-TEST",
        key_id="v496-key",
        customer=CustomerInfo(name="فروشگاه دقیق"),
        license_type="perpetual",
        issued_at="2026-01-01T00:00:00Z",
        not_before="2026-01-01T00:00:00Z",
        expires_at=None,
        max_devices=1,
        device_fingerprints=[fp],
        features=features,
    )
    sig_b64 = base64.b64encode(
        priv.sign(DOMAIN_PREFIX + canonicalize_payload(payload.to_dict()))
    ).decode("ascii")
    env = LicenseEnvelope(
        envelope_version=1,
        algorithm="Ed25519",
        key_id="v496-key",
        payload=payload,
        signature=sig_b64,
    )
    lic_file = tmp_path / "active.daqlic"
    lic_file.write_text(json.dumps(env.to_dict(), ensure_ascii=False), encoding="utf-8")

    store = LicenseStore(
        machine_dir=str(tmp_path / "lic_m"),
        user_dir=str(tmp_path / "lic_u"),
        roaming_dir=str(tmp_path / "lic_r"),
    )
    verifier = LicenseVerifier(key_registry=KeyRegistry({"v496-key": pub_b64}))
    svc = LicenseService(store=store, verifier=verifier, hardware_provider=hw, app_version="4.9.8")
    res = svc.import_license_file(str(lic_file))
    assert res.is_valid, res
    return svc


# ---------------------------------------------------------------------------
# Phase 1 Root Cause: Eliminate JalaliDateEdit Infinite Recursion / C Stack Overflow
# ---------------------------------------------------------------------------

def test_jalali_date_edit_zero_recursion_and_low_recursion_limit(qapp):
    """Prove JalaliDateEdit no longer triggers self-referential _resolve_ancestor_calendar recursion."""
    calls = [0]
    orig_get = JalaliDateEdit.get_calendar_format

    def _counted(self):
        calls[0] += 1
        return orig_get(self)

    JalaliDateEdit.get_calendar_format = _counted
    orig_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(80)
        w = JalaliDateEdit(default_today=True)
        assert w.get_calendar_format() == "jalali"
        assert calls[0] <= 5, f"Unexpected recursive get_calendar_format calls: {calls[0]}"

        class _HostWidget:
            def get_active_calendar(self):
                return "hijri"

        assert _resolve_ancestor_calendar(_HostWidget()) == "hijri"
        assert _resolve_ancestor_calendar(w) == "jalali"
        w.close()
    finally:
        sys.setrecursionlimit(orig_limit)
        JalaliDateEdit.get_calendar_format = orig_get


# ---------------------------------------------------------------------------
# Phase 3 Unmocked Startup Flow (Real LicenseService + Real MainWindow + Event Loop)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("with_taxonomy", [False, True])
def test_unmocked_startup_new_db_real_event_loop(tmp_path, monkeypatch, qapp, with_taxonomy):
    """Execute full startup flow with real signed LicenseService and real QTimer event loop."""
    run_dir = tmp_path / ("tax_yes" if with_taxonomy else "tax_no")
    run_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = run_dir / "app_config.json"
    tax_file = run_dir / "default_taxonomy.json"
    if with_taxonomy:
        tax_file.write_text(
            json.dumps({
                "categories": ["لپ‌تاپ"],
                "subcategories": {"لپ‌تاپ": ["اداری"]},
                "attributes": {},
                "colors": ["مشکی"],
                "service_types": ["نرم‌افزاری"],
            }, ensure_ascii=False),
            encoding="utf-8",
        )

    monkeypatch.setenv("LOCALAPPDATA", str(run_dir / "localapp"))
    monkeypatch.setenv("APPDATA", str(run_dir / "appdata"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(cfg_file))
    monkeypatch.setattr(database_module, "get_default_taxonomy_path", lambda p=tax_file: str(p))
    monkeypatch.setattr(main_module, "load_app_config", database_module.load_app_config)
    monkeypatch.setattr(main_module, "save_app_config", database_module.save_app_config)

    svc = _build_real_signed_license_service(run_dir)
    target_db = run_dir / "store_e2e.db"
    observed = {}

    def _fake_db_exec(dlg_self):
        dlg_self.rb_create.setChecked(True)
        dlg_self.ed_path.setText(str(target_db))
        dlg_self.btn_theme_toggle.click()  # Verify theme toggle survives save_app_config
        dlg_self._validate_and_accept()
        return dlg_self.result()

    orig_exec = qapp.exec

    def _driven_exec():
        def _inspect_alive():
            win = main_module._ACTIVE_MAIN_WINDOW
            observed["visible"] = bool(win is not None and win.isVisible())
            observed["quit_on_last"] = qapp.quitOnLastWindowClosed()
            observed["tabs"] = win.tabs.count() if win else -1
            if win is not None:
                observed["cats"] = list(win.catalog_config.get("categories", []))
                win.close()
            qapp.quit()

        QTimer.singleShot(150, _inspect_alive)
        return orig_exec()

    monkeypatch.setattr(main_module, "LicenseService", lambda *a, **kw: svc)
    monkeypatch.setattr(main_module.DatabaseBootstrapDialog, "exec", _fake_db_exec)
    monkeypatch.setattr(qapp, "exec", _driven_exec)
    monkeypatch.setattr(sys, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code)))

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 0
    assert observed["visible"] is True
    assert observed["quit_on_last"] is True
    assert observed["tabs"] == 13
    if with_taxonomy:
        assert "لپ‌تاپ" in observed["cats"]
    else:
        assert observed["cats"] == []
    assert json.loads(cfg_file.read_text(encoding="utf-8"))["theme"] == "dark"


def test_unmocked_startup_existing_v493_schema_and_restricted_license(tmp_path, monkeypatch, qapp):
    """Connect a pre-v4.9.4 (v4.9.3 schema without batches.purchase_time) DB with restricted tabs."""
    run_dir = tmp_path / "v493_compat"
    run_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = run_dir / "app_config.json"

    monkeypatch.setenv("LOCALAPPDATA", str(run_dir / "localapp"))
    monkeypatch.setenv("APPDATA", str(run_dir / "appdata"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(cfg_file))
    monkeypatch.setattr(main_module, "load_app_config", database_module.load_app_config)
    monkeypatch.setattr(main_module, "save_app_config", database_module.save_app_config)

    # Create a v4.9.5 DB and strip batches.purchase_time column to simulate exact v4.9.3 SQLite schema
    db_v493 = run_dir / "legacy_v493.db"
    mgr = database_module.DatabaseManager(str(db_v493))
    mgr.close()
    with sqlite3.connect(str(db_v493)) as raw_conn:
        cols = [
            r[1]
            for r in raw_conn.execute("PRAGMA table_info(batches)").fetchall()
            if r[1] not in ("purchase_time", "row_version", "settlement_subtype", "check_due_date", "check_status", "purchase_invoice_code", "payment_type")
        ]
        cols_csv = ", ".join(cols)
        raw_conn.execute("PRAGMA foreign_keys=OFF")
        raw_conn.execute("ALTER TABLE batches RENAME TO batches_tmp_old")
        raw_conn.execute("""
            CREATE TABLE batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_code TEXT NOT NULL UNIQUE,
                product_id INTEGER NOT NULL,
                serial_numbers TEXT DEFAULT '',
                supplier_id INTEGER,
                buyer_employee_id INTEGER,
                invoice_number TEXT DEFAULT '',
                purchase_date TEXT NOT NULL,
                initial_qty INTEGER NOT NULL,
                sold_qty INTEGER NOT NULL DEFAULT 0,
                returned_qty INTEGER NOT NULL DEFAULT 0,
                remaining_qty INTEGER NOT NULL,
                unit_purchase_price INTEGER NOT NULL,
                extra_cost_total INTEGER NOT NULL DEFAULT 0,
                upgrade_cost_unit INTEGER NOT NULL DEFAULT 0,
                unit_cost_price INTEGER NOT NULL,
                suggested_sell_price INTEGER NOT NULL,
                profit_pct INTEGER NOT NULL,
                paid_amount INTEGER NOT NULL DEFAULT 0,
                settlement_status TEXT NOT NULL DEFAULT 'تسویه‌شده',
                colors_json TEXT DEFAULT '[]',
                initial_specs TEXT DEFAULT '',
                final_specs TEXT DEFAULT '',
                supplier_name_snapshot TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
        """)
        raw_conn.execute(f"INSERT INTO batches ({cols_csv}) SELECT {cols_csv} FROM batches_tmp_old")
        raw_conn.execute("DROP TABLE batches_tmp_old")
        raw_conn.commit()

    # Dashboard & batches disabled in license -> MainWindow must open cleanly on first unlocked tab (products=1)
    restricted_features = {k: True for k in ALL_LICENSE_FEATURES}
    restricted_features["dashboard"] = False
    restricted_features["batches"] = False
    svc = _build_real_signed_license_service(run_dir, features=restricted_features)

    observed = {}

    def _fake_db_exec(dlg_self):
        dlg_self.rb_existing.setChecked(True)
        dlg_self.ed_path.setText(str(db_v493))
        dlg_self._validate_and_accept()
        return dlg_self.result()

    orig_exec = qapp.exec

    def _driven_exec():
        def _inspect_alive():
            win = main_module._ACTIVE_MAIN_WINDOW
            observed["visible"] = bool(win is not None and win.isVisible())
            observed["cur_tab"] = win.tabs.currentIndex() if win else -1
            if win is not None:
                win.close()
            qapp.quit()

        QTimer.singleShot(150, _inspect_alive)
        return orig_exec()

    monkeypatch.setattr(main_module, "LicenseService", lambda *a, **kw: svc)
    monkeypatch.setattr(main_module.DatabaseBootstrapDialog, "exec", _fake_db_exec)
    monkeypatch.setattr(qapp, "exec", _driven_exec)
    monkeypatch.setattr(sys, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code)))

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 0
    assert observed["visible"] is True
    assert observed["cur_tab"] == 1  # products tab unlocked


def test_smoke_launch_db_create_and_existing_modes(tmp_path, monkeypatch, qapp):
    """Verify --smoke-launch-db handler executes DB bootstrap + MainWindow cleanly in create and existing modes."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localapp"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))

    db_path = tmp_path / "smoke_launch.db"
    assert main_module._run_smoke_launch_db(qapp, str(db_path), mode="create") == 0
    assert db_path.is_file()
    assert main_module._run_smoke_launch_db(qapp, str(db_path), mode="existing") == 0


def test_native_and_qt_crash_loggers_write_cleanly(tmp_path, monkeypatch):
    """Verify crash log paths and Qt message logging work cleanly without raising."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localapp"))
    crash_path = Path(main_module.get_crash_log_path())
    fault_path = Path(main_module.get_native_fault_log_path())
    assert crash_path.parent == fault_path.parent
    assert crash_path.name == "daqiq_crash.log"
    assert fault_path.name == "daqiq_native_fault.log"

    # Trigger Qt critical message handler directly
    from PySide6.QtCore import qCritical
    main_module.install_native_fault_and_qt_loggers()
    qCritical("Test Qt critical diagnostic line")
    assert crash_path.is_file()
    assert "Test Qt critical diagnostic line" in crash_path.read_text(encoding="utf-8")


def test_nuitka_parent_pid_lookup_handles_invalid_pid_safely(monkeypatch):
    """Ensure invalid integer NUITKA_ONEFILE_PARENT never returns an integer path."""
    monkeypatch.setenv("NUITKA_ONEFILE_PARENT", "99999999")
    assert daqiq_paths._resolve_nuitka_parent_process_dir() is None
