"""Automated verification suite for Daqiq v4.9.5 critical hotfixes (Issue #1 & Issue #2)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMessageBox,
    QPushButton,
)

import database as database_module
import main as main_module
from database import DatabaseManager
from licensing.device_identity import create_device_request_dict
from licensing.license_dialog import LicenseDialog, ThemedNoticeDialog
from licensing.license_models import (
    CustomerInfo,
    LicenseEnvelope,
    LicensePayload,
    ValidationResult,
    ValidationStatus,
)


def _make_valid_service(tmp_path: Path):
    fp = "fp_v1:" + "a" * 64
    payload = LicensePayload(
        format_version=1,
        product_id="daqiq.desktop",
        license_id="DAQIQ-TEST-495",
        key_id="k1",
        customer=CustomerInfo(name="فروشگاه تست"),
        license_type="perpetual",
        issued_at="2026-01-01T00:00:00Z",
        not_before="2026-01-01T00:00:00Z",
        expires_at=None,
        max_devices=1,
        device_fingerprints=[fp],
        features={"dashboard": True, "sales": True, "batches": True, "settings": True},
    )
    env = LicenseEnvelope(envelope_version=1, algorithm="ed25519", key_id="k1", payload=payload, signature="sig")
    res = ValidationResult(
        status=ValidationStatus.VALID,
        is_valid=True,
        license=env,
        message_fa="لایسنس معتبر و فعال است.",
    )
    svc = MagicMock()
    svc.get_hardware_fingerprint.return_value = fp
    svc.get_active_key_fingerprints.return_value = [{"display": "abcd-ef01"}]
    svc.check_license.return_value = res
    svc.is_feature_enabled.side_effect = lambda feat: True
    svc.import_license_file.return_value = res
    svc.import_license_token.return_value = res
    svc.export_device_request_file.side_effect = lambda path: Path(path).write_text("{}", encoding="utf-8")
    return svc


# ---------------------------------------------------------------------------
# Issue #2: Full Startup Pipeline (Create New DB / Connect Existing / Crash Net)
# ---------------------------------------------------------------------------

def test_main_startup_create_new_db_with_and_without_taxonomy(tmp_path, monkeypatch, qapp):
    """Verify Create New DB reaches MainWindow.isVisible() both with and without default_taxonomy.json."""
    for has_taxonomy in (False, True):
        run_dir = tmp_path / ("with_tax" if has_taxonomy else "no_tax")
        run_dir.mkdir(parents=True, exist_ok=True)
        cfg_file = run_dir / "app_config.json"
        tax_file = run_dir / "default_taxonomy.json"
        if has_taxonomy:
            tax_file.write_text('{"products": [], "services": []}', encoding="utf-8")

        monkeypatch.setenv("APPDATA", str(run_dir / "appdata"))
        monkeypatch.setenv("LOCALAPPDATA", str(run_dir / "localappdata"))
        monkeypatch.setattr(database_module, "CONFIG_FILE", str(cfg_file))
        monkeypatch.setattr(database_module, "get_default_taxonomy_path", lambda p=tax_file: str(p))

        target_db = run_dir / "store_new.db"
        svc = _make_valid_service(run_dir)

        def _fake_db_exec(dlg_self):
            dlg_self.rb_create.setChecked(True)
            dlg_self.ed_path.setText(str(target_db))
            dlg_self._validate_and_accept()
            return dlg_self.result()

        observed = {}

        def _fake_app_exec():
            win = main_module._ACTIVE_MAIN_WINDOW
            observed["win"] = win
            observed["visible"] = bool(win is not None and win.isVisible())
            observed["quit_on_last"] = qapp.quitOnLastWindowClosed()
            if win is not None:
                win.close()
            return 0

        monkeypatch.setattr(main_module, "LicenseService", lambda *a, **kw: svc)
        monkeypatch.setattr(main_module.DatabaseBootstrapDialog, "exec", _fake_db_exec)
        monkeypatch.setattr(main_module, "load_app_config", lambda c=cfg_file: database_module.load_app_config())
        monkeypatch.setattr(qapp, "exec", _fake_app_exec)

        exit_codes = []
        monkeypatch.setattr(sys, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code)))

        with pytest.raises(SystemExit) as exc_info:
            main_module.main()
        exit_codes.append(exc_info.value.code)

        assert exit_codes == [0]
        assert observed["visible"] is True
        assert observed["quit_on_last"] is True
        assert target_db.is_file()
        assert main_module._ACTIVE_MAIN_WINDOW is None


def test_main_startup_connect_existing_encrypted_and_unencrypted_db(tmp_path, monkeypatch, qapp):
    """Verify Connect Existing DB opens MainWindow cleanly for both plain and password-protected DBs."""
    for encrypted in (False, True):
        run_dir = tmp_path / ("enc" if encrypted else "plain")
        run_dir.mkdir(parents=True, exist_ok=True)
        cfg_file = run_dir / "app_config.json"
        monkeypatch.setenv("APPDATA", str(run_dir / "appdata"))
        monkeypatch.setenv("LOCALAPPDATA", str(run_dir / "localappdata"))
        monkeypatch.setattr(database_module, "CONFIG_FILE", str(cfg_file))

        db_path = run_dir / "existing_store.db"
        mgr = DatabaseManager(str(db_path))
        if encrypted:
            mgr.set_database_password("Secret#495")
        mgr.close()
        if cfg_file.exists():
            cfg_file.unlink()

        svc = _make_valid_service(run_dir)
        wizard_calls = []

        def _fake_db_exec(dlg_self):
            wizard_calls.append(True)
            dlg_self.rb_existing.setChecked(True)
            dlg_self.ed_path.setText(str(db_path))
            dlg_self._validate_and_accept()
            return dlg_self.result()

        observed = {}

        def _fake_app_exec():
            win = main_module._ACTIVE_MAIN_WINDOW
            observed["visible"] = bool(win is not None and win.isVisible())
            observed["quit_on_last"] = qapp.quitOnLastWindowClosed()
            if win is not None:
                win.close()
            return 0

        monkeypatch.setattr(main_module, "LicenseService", lambda *a, **kw: svc)
        monkeypatch.setattr(main_module.DatabaseBootstrapDialog, "exec", _fake_db_exec)
        monkeypatch.setattr(main_module, "_prompt_database_password", lambda *a, **kw: ("Secret#495", True))
        monkeypatch.setattr(qapp, "exec", _fake_app_exec)
        monkeypatch.setattr(sys, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code)))

        with pytest.raises(SystemExit) as exc_info:
            main_module.main()

        assert exc_info.value.code == 0
        assert len(wizard_calls) == 1
        assert observed["visible"] is True
        assert observed["quit_on_last"] is True
        assert main_module._ACTIVE_MAIN_WINDOW is None


def test_crash_logger_and_startup_exception_safety_net(tmp_path, monkeypatch, qapp):
    """Verify unhandled startup errors log to daqiq_crash.log and show Persian error dialog."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localapp"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))

    svc = _make_valid_service(tmp_path)
    shown_dialogs = []

    def _capture_notice(dlg_self):
        shown_dialogs.append((
            dlg_self.windowTitle(),
            dlg_self.lbl_message.text(),
            [b.text() for b in dlg_self.buttons()],
        ))
        return QDialog.Accepted

    monkeypatch.setattr(ThemedNoticeDialog, "exec", _capture_notice)
    monkeypatch.setattr(main_module, "LicenseService", lambda *a, **kw: svc)
    monkeypatch.setattr(main_module, "select_startup_database_path", lambda: str(tmp_path / "shop.db"))
    monkeypatch.setattr(main_module, "MainWindow", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("Simulated boom")))
    monkeypatch.setattr(sys, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code)))

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 1
    assert qapp.quitOnLastWindowClosed() is True
    log_path = Path(main_module.get_crash_log_path())
    assert log_path.is_file()
    log_content = log_path.read_text(encoding="utf-8")
    assert "RuntimeError: Simulated boom" in log_content
    assert len(shown_dialogs) == 1
    title, msg, btns = shown_dialogs[0]
    assert title == "بروز خطای غیرمنتظره"
    assert str(log_path) in msg
    assert btns == ["تأیید"]


# ---------------------------------------------------------------------------
# Issue #1a & #1b: Centered License Header & Styled Persian Notice Dialogs
# ---------------------------------------------------------------------------

def test_license_dialog_header_is_geometrically_centered(qapp, tmp_path):
    """Verify header title stays centered between logo and theme toggle in Light/Dark & resized widths."""
    svc = _make_valid_service(tmp_path)
    svg_path = Path(__file__).resolve().parent.parent / "assets" / "daqiq_logo.svg"
    dlg = LicenseDialog(service=svc, icon_path=str(svg_path), is_dark_theme=False, is_startup_gate=True)
    dlg.show()
    qapp.processEvents()

    for label in ("light_default", "dark_default", "dark_wide"):
        if label == "dark_default":
            dlg.btn_theme_toggle.click()
            qapp.processEvents()
        elif label == "dark_wide":
            dlg.resize(980, 720)
            qapp.processEvents()

        header_rect = dlg.header_frame.geometry()
        title_rect = dlg.title_lbl.geometry()
        sub_rect = dlg.sub_lbl.geometry()
        icon_rect = dlg.icon_lbl.geometry()
        toggle_rect = dlg.btn_theme_toggle.geometry()

        header_mid = header_rect.width() / 2.0
        assert abs(title_rect.center().x() - header_mid) <= 3.0, f"{label}: title off-center"
        assert abs(sub_rect.center().x() - header_mid) <= 3.0, f"{label}: subtitle off-center"
        assert dlg.header_grid.columnMinimumWidth(0) == dlg.header_grid.columnMinimumWidth(2)
        assert not title_rect.intersects(icon_rect)
        assert not title_rect.intersects(toggle_rect)

    dlg.close()


def test_license_dialog_uses_styled_persian_notices_in_light_and_dark(qapp, tmp_path, monkeypatch):
    """Verify all LicenseDialog popups use ThemedNoticeDialog with Persian buttons and zero English labels."""
    svc = _make_valid_service(tmp_path)
    bad_res = ValidationResult(
        status=ValidationStatus.INVALID_SIGNATURE,
        is_valid=False,
        license=None,
        message_fa="فایل لایسنس نامعتبر است.",
    )
    captured = []

    def _capture_exec(notice_self):
        bg_hex = notice_self.palette().color(QPalette.Window).name().lower()
        btn_texts = [b.text() for b in notice_self.buttons()]
        captured.append({
            "dark": notice_self.is_dark_theme,
            "title": notice_self.windowTitle(),
            "message": notice_self.lbl_message.text(),
            "buttons": btn_texts,
            "qss": notice_self.styleSheet(),
            "bg_hex": bg_hex,
        })
        return QDialog.Accepted

    monkeypatch.setattr(ThemedNoticeDialog, "exec", _capture_exec)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **kw: (str(tmp_path / "req.daqreq"), "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **kw: (str(tmp_path / "lic.daqlic"), "")))

    for is_dark in (False, True):
        captured.clear()
        dlg = LicenseDialog(service=svc, is_dark_theme=is_dark, is_startup_gate=False)

        # 1. Export .daqreq success
        dlg._export_request_flow()
        # 2. Import valid license
        dlg._import_license_file_flow()
        # 3. Import invalid token
        svc.import_license_token.return_value = bad_res
        dlg.txt_token.setPlainText("INVALID-TOKEN")
        dlg._apply_token_flow()
        # 4. Remove license confirmation + completion
        dlg._remove_license_flow()

        assert len(captured) == 5
        for item in captured:
            assert item["dark"] is is_dark
            assert item["bg_hex"] == ("#0b1220" if is_dark else "#f4f7fb")
            assert "#DaqiqNoticeDialogRoot" in item["qss"]
            assert "background-color: #0284c7" in item["qss"]
            assert "border: 1px solid" in item["qss"]
            for bt in item["buttons"]:
                assert bt in ("تأیید", "بله", "خیر")
                assert bt not in ("OK", "Cancel", "Yes", "No")

        assert captured[3]["buttons"] == ["بله", "خیر"]
        assert "background-color: #dc2626" in captured[3]["qss"]
        dlg.close()


def test_messagebox_polisher_translates_ampersand_buttons_and_styles(qapp):
    """Verify _MessageBoxPolisher translates startup QMessageBox &OK/&Yes/&No to Persian."""
    polisher = main_module._MessageBoxPolisher(qapp)
    box = QMessageBox(QMessageBox.Warning, "خطا", "رمز عبور صحیح نیست.", QMessageBox.Yes | QMessageBox.No)
    for btn in box.buttons():
        if btn.text() in ("Yes", "No"):
            btn.setText("&" + btn.text())
    polisher.eventFilter(box, QEvent(QEvent.Show))
    texts = [b.text() for b in box.buttons()]
    assert "بله" in texts
    assert "خیر" in texts
    assert "QMessageBox QPushButton" in box.styleSheet()
    box.close()


def test_version_bumped_consistently_to_495():
    """Verify VERSION, main.APP_VERSION, and device request default app_version stay consistent."""
    root = Path(__file__).resolve().parent.parent
    ver = (root / "VERSION").read_text(encoding="utf-8").strip()
    assert ver == "4.9.9"
    assert main_module.APP_VERSION == ver
    req = create_device_request_dict(store_name="تست")
    assert req["app_version"] == ver
