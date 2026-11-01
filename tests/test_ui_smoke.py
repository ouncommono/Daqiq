import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QCompleter
from PySide6.QtGui import QFontMetrics

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
        assert window.lbl_store_name.text().strip("\u2067\u2069") == "فروشگاه من"
        assert "مدیریت فروش" not in window.lbl_store_name.text()
        assert window.lbl_active_user.text().startswith("👤 کاربر:")
        assert window.lbl_live_clock.minimumWidth() >= 170
        assert window.top_layout.direction() == window.top_layout.LeftToRight
        assert window.top_right_layout.direction() == window.top_right_layout.RightToLeft
        assert window.btn_theme.isEnabled()
        assert window.btn_table_width.isEnabled()
        assert window.tbl_batches.columnCount() >= 22
        assert not hasattr(window, "chk_zero_enabled")
        assert window.lbl_live_clock.toolTip()

        # Technical keywords remain searchable but never become part of the visible item.
        product_combo = window.cb_sale_prod
        visible_label = "P-X | کیبورد | Acme Model"
        hidden_technical_text = "DDR5 16GB HiddenDescription"
        hidden_index = product_combo.count()
        product_combo.addItem(visible_label, {"id": -99})
        product_combo.setItemSearchText(hidden_index, hidden_technical_text)
        product_combo._search_proxy.set_query("DDR5")
        assert product_combo._search_proxy.rowCount() == 1
        proxy_index = product_combo._search_proxy.index(0, 0)
        assert product_combo._search_proxy.data(proxy_index) == visible_label
        assert "DDR5" not in product_combo.itemText(hidden_index)
        assert product_combo.completer().completionMode() == QCompleter.UnfilteredPopupCompletion
        product_combo._search_proxy.set_query("")

        # Header text must participate in smart sizing even for empty result tables.
        measured_widths = window._measure_table_columns(window.tbl_batches)
        header_item = window.tbl_batches.horizontalHeaderItem(20)
        expected_header_width = (
            QFontMetrics(header_item.font()).horizontalAdvance(header_item.text()) + 28
        )
        assert measured_widths[20] >= expected_header_width

        assert window.dt_batch_date.ed_day.width() >= 42
        assert window.dt_batch_date.ed_month.width() >= 42
        assert window.dt_batch_date.width() < 220

    finally:
        window.close()
        qapp.processEvents()
