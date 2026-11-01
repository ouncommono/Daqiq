import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QTableWidgetItem

import database as database_module
from database import DatabaseManager
from main import MainWindow


@pytest.fixture(scope="session")
def qapp():
    application = QApplication.instance() or QApplication(["accounting-smoke-test"])
    yield application


def test_main_window_builds_with_empty_database(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))

    window = MainWindow(manager, active_employee=None)
    try:
        assert window.tabs.count() == 10
        assert window.tabs.tabText(9).endswith("تنظیمات و پشتیبان‌گیری")
        assert window.lbl_store_name.text().startswith("💻")
        assert "مدیریت فروش" not in window.lbl_store_name.text()
        assert window.lbl_active_user.text().startswith("👤 کاربر:")
        assert window.lbl_live_clock.minimumWidth() >= 250
        assert window.btn_theme.isEnabled()
        assert window.btn_table_width.isEnabled()
        assert window.tbl_batches.columnCount() >= 22
        assert not hasattr(window, "chk_zero_enabled")
        assert window.lbl_live_clock.toolTip()

        table = window.tbl_batches
        column = min(2, table.columnCount() - 1)
        baseline_width = table.columnWidth(column)
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, column, QTableWidgetItem("متن بسیار طولانی برای آزمون اندازه‌گذاری هوشمند ستون"))
        qapp.processEvents()
        window._toggle_table_autosize()
        fitted_width = table.columnWidth(column)
        assert fitted_width > baseline_width
        window._toggle_table_autosize()
        assert table.columnWidth(column) == baseline_width
    finally:
        window.close()
        qapp.processEvents()
