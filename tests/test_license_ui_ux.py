# tests/test_license_ui_ux.py
"""Automated tests for LicenseDialog and DatabaseBootstrapDialog Phase 2 UI/UX overhaul."""

import os
import pytest
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from licensing.license_dialog import LicenseDialog
from licensing.license_policy import LicenseService
from licensing.license_models import ValidationResult, ValidationStatus, LicenseEnvelope, LicensePayload, CustomerInfo
from main import DatabaseBootstrapDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
        app.setLayoutDirection(Qt.RightToLeft)
    return app


def _create_mock_service(is_valid: bool = True):
    service = MagicMock(spec=LicenseService)
    service.get_hardware_fingerprint.return_value = "fp_v1:0123456789abcdef"
    service.get_active_key_fingerprints.return_value = [{"key_id": "test-key", "fingerprint": "1234-5678-90ab", "display": "test-key · 1234-5678-90ab"}]
    if is_valid:
        payload = LicensePayload(
            format_version=1,
            product_id="daqiq.desktop",
            license_id="LIC-TEST-001",
            key_id="test-key",
            customer=CustomerInfo(name="کاربر تست"),
            license_type="perpetual",
            issued_at="2026-11-24T00:00:00Z",
            not_before="2026-11-24T00:00:00Z",
            expires_at=None,
            max_devices=1,
            device_fingerprints=["fp_v1:0123456789abcdef"],
            features={"dashboard": True, "settings": True},
        )
        env = LicenseEnvelope(
            envelope_version=1,
            algorithm="Ed25519",
            key_id="test-key",
            payload=payload,
            signature="test-sig",
        )
        val_res = ValidationResult(
            status=ValidationStatus.VALID,
            is_valid=True,
            license=env,
            message_fa="معتبر",
        )
    else:
        val_res = ValidationResult(
            status=ValidationStatus.MISSING,
            is_valid=False,
            license=None,
            message_fa="لایسنس یافت نشد",
        )
    service.check_license.return_value = val_res
    return service


def test_license_dialog_scroll_area_and_theme_toggle(qapp):
    """Verify LicenseDialog includes scroll area, theme toggle, and no 'تجاری'."""
    service = _create_mock_service(is_valid=True)
    dlg = LicenseDialog(service, is_dark_theme=False, is_startup_gate=True)

    # 1. No 'تجاری' in texts
    assert "تجاری" not in dlg.title_lbl.text()
    assert "تجاری" not in dlg.sub_lbl.text()

    # 2. Scroll area exists and is resizable
    assert hasattr(dlg, "scroll_area")
    assert dlg.scroll_area.widgetResizable() is True

    # 3. Theme toggle
    assert dlg.is_dark_theme is False
    assert "تاریک" in dlg.btn_theme_toggle.text()
    dlg.btn_theme_toggle.click()
    assert dlg.is_dark_theme is True
    assert "روشن" in dlg.btn_theme_toggle.text()


def test_license_dialog_footer_mode_startup_vs_in_app(qapp):
    """Verify startup gate shows enter/exit buttons while in-app shows close button."""
    service = _create_mock_service(is_valid=True)

    # Startup gate
    dlg_startup = LicenseDialog(service, is_startup_gate=True)
    assert not dlg_startup.btn_enter.isHidden()
    assert not dlg_startup.btn_exit.isHidden()
    assert dlg_startup.btn_close.isHidden()

    # In-app
    dlg_inapp = LicenseDialog(service, is_startup_gate=False)
    assert dlg_inapp.btn_enter.isHidden()
    assert dlg_inapp.btn_exit.isHidden()
    assert not dlg_inapp.btn_close.isHidden()


def test_license_dialog_key_fp_click_to_copy(qapp):
    """Verify clicking Key FP copies string to clipboard."""
    service = _create_mock_service(is_valid=True)
    dlg = LicenseDialog(service, is_startup_gate=False)

    assert "1234-5678-90ab" in dlg._current_key_fp_text
    dlg._copy_key_fingerprint()
    clipboard_text = qapp.clipboard().text()
    assert "1234-5678-90ab" in clipboard_text


def test_database_bootstrap_dialog_theme_toggle(qapp, tmp_path):
    """Verify DatabaseBootstrapDialog has theme toggle and toggles mode."""
    db_file = str(tmp_path / "test.db")
    dlg = DatabaseBootstrapDialog(db_file, is_dark_theme=False)

    assert hasattr(dlg, "btn_theme_toggle")
    assert dlg.is_dark_theme is False
    dlg.btn_theme_toggle.click()
    assert dlg.is_dark_theme is True
