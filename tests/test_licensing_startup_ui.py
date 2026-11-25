# tests/test_licensing_startup_ui.py
"""Unit tests proving strict startup gating, pre-DB blocking, and entitlement enforcement."""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from PySide6.QtCore import Qt

import database as database_module
from database import DatabaseManager
from main import MainWindow
from licensing.license_models import (
    CustomerInfo,
    LicensePayload,
    LicenseEnvelope,
    ValidationStatus,
    ValidationResult,
)
from licensing.license_policy import LicenseService, TAB_MODULE_TO_FEATURE
from licensing.license_dialog import LicenseDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
        app.setLayoutDirection(Qt.RightToLeft)
    return app


def make_mock_service(is_valid: bool, features: dict = None, fp: str = "fp_v1:mock"):
    service = MagicMock(spec=LicenseService)
    service.get_hardware_fingerprint.return_value = fp

    if is_valid:
        default_features = {
            "dashboard": True,
            "products": True,
            "batches": True,
            "sales": True,
            "services": True,
            "upgrades": True,
            "suppliers_payments": True,
            "reports": True,
            "employees": True,
            "settings": True,
            "customers": True,
            "installments": True,
            "charts_analytics": True,
            "word_export": True,
        }
        if features:
            default_features.update(features)

        payload = LicensePayload(
            format_version=1,
            product_id="daqiq.desktop",
            license_id="LIC-MOCK-001",
            key_id="mock-key",
            customer=CustomerInfo(name="مشتری آزمایشی"),
            license_type="perpetual",
            issued_at="2026-11-22T00:00:00Z",
            not_before="2026-11-22T00:00:00Z",
            expires_at=None,
            max_devices=1,
            device_fingerprints=[fp],
            features=default_features,
        )
        env = LicenseEnvelope(
            envelope_version=1,
            algorithm="Ed25519",
            key_id="mock-key",
            payload=payload,
            signature="mock-sig",
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
            message_fa="فایل لایسنس یافت نشد.",
        )

    service.check_license.return_value = val_res
    service.is_feature_enabled.side_effect = lambda f: bool(default_features.get(f, False)) if is_valid else False
    return service


def test_startup_gate_blocks_before_database_when_unlicensed():
    """Prove that when license is missing or invalid, DatabaseManager is NEVER instantiated."""
    mock_service = make_mock_service(is_valid=False)
    mock_dlg = MagicMock()
    mock_dlg.exec.return_value = QDialog.Rejected

    with patch("main.LicenseService", return_value=mock_service), \
         patch("main.LicenseDialog", return_value=mock_dlg), \
         patch("main.select_startup_database_path") as mock_select_db, \
         patch("main.DatabaseManager") as mock_db_mgr, \
         patch("sys.exit", side_effect=SystemExit) as mock_exit:

        from main import main
        with pytest.raises(SystemExit):
            main()

        # Database selection and connection MUST NEVER be invoked!
        mock_select_db.assert_not_called()
        mock_db_mgr.assert_not_called()
        mock_exit.assert_called_with(0)


def test_startup_gate_proceeds_into_db_when_license_is_valid():
    """Prove that when license is valid, database selection and MainWindow proceed normally."""
    mock_service = make_mock_service(is_valid=True)

    with patch("main.LicenseService", return_value=mock_service), \
         patch("main.select_startup_database_path", return_value=None) as mock_select_db, \
         patch("sys.exit", side_effect=SystemExit):

        from main import main
        with pytest.raises(SystemExit):
            main()

        # select_startup_database_path was reached!
        mock_select_db.assert_called_once()


def test_tab_entitlements_enforcement(qapp, tmp_path):
    """Verify that disabled features physically disable the corresponding tabs in MainWindow."""
    # License with 'batches' and 'services' disabled
    features = {
        "dashboard": True,
        "products": True,
        "batches": False,  # DISABLED
        "sales": True,
        "services": False, # DISABLED
        "upgrades": True,
        "suppliers_payments": True,
        "reports": True,
        "employees": True,
        "settings": True,
    }
    service = make_mock_service(is_valid=True, features=features)

    db = DatabaseManager(str(tmp_path / "test.db"))
    win = MainWindow(db, active_employee=None, license_service=service)

    # 12 tabs mapping:
    # 0: dashboard, 1: products, 2: batches, 3: sales, 4: services,
    # 5: upgrades, 6: suppliers, 7: customers, 8: reports, 9: charts, 10: employees, 11: settings
    assert win.tabs.count() == 12
    assert win.tabs.isTabEnabled(0) is True  # dashboard
    assert win.tabs.isTabEnabled(1) is True  # products
    assert win.tabs.isTabEnabled(2) is False # batches: DISABLED
    assert win.tabs.isTabEnabled(3) is True  # sales
    assert win.tabs.isTabEnabled(4) is False # services: DISABLED
    assert win.tabs.isTabEnabled(5) is True  # upgrades
    assert win.tabs.isTabEnabled(11) is True  # settings


def test_clicking_disabled_tab_shows_persian_notice(qapp, tmp_path):
    """Verify that clicking a disabled tab triggers the polite Persian explanation."""
    features = {"batches": False}
    service = make_mock_service(is_valid=True, features=features)

    db = DatabaseManager(str(tmp_path / "test.db"))
    win = MainWindow(db, active_employee=None, license_service=service)

    shown = []
    def _fake_exec(msg_self):
        shown.append((msg_self.windowTitle(), msg_self.text(), [b.text() for b in msg_self.buttons()]))
        return QMessageBox.Rejected

    with patch.object(QMessageBox, "exec", _fake_exec):
        # Simulate user clicking tab 2 (batches)
        win._on_tab_bar_clicked(2)
        assert len(shown) == 1
        title, body, btn_texts = shown[0]
        assert "دسترسی لایسنس" in title
        assert "در لایسنس فعال شما مجاز نیست" in body
        assert any("مدیریت لایسنس" in bt for bt in btn_texts)


def test_all_10_tabs_enabled_on_full_license(qapp, tmp_path):
    """Verify full commercial license preserves all 12 production tabs."""
    service = make_mock_service(is_valid=True)
    db = DatabaseManager(str(tmp_path / "test.db"))
    win = MainWindow(db, active_employee=None, license_service=service)

    assert win.tabs.count() == 12
    for i in range(12):
        assert win.tabs.isTabEnabled(i) is True
