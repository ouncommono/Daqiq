import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

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
        assert window.btn_theme.isEnabled()
        assert window.btn_table_width.isEnabled()
        assert window.tbl_batches.columnCount() >= 22
    finally:
        window.close()
        qapp.processEvents()
