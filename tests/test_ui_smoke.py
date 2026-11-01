import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QBoxLayout, QCompleter, QSizePolicy
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics

import database as database_module
import main as main_module
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
        assert window.top_bar.layoutDirection() == Qt.LeftToRight
        assert window.top_layout.direction() == QBoxLayout.LeftToRight
        assert window.top_right_layout.direction() == QBoxLayout.LeftToRight
        assert window.top_layout.itemAt(0).layout() == window.top_right_layout
        assert window.top_layout.itemAt(window.top_layout.count() - 1).widget() == window.lbl_store_name
        assert window.top_right_layout.itemAt(0).widget() == window.btn_theme
        assert window.top_right_layout.itemAt(window.top_right_layout.count() - 1).widget() == window.btn_switch_user
        assert window.lbl_active_user.minimumWidth() >= 90
        assert window.lbl_active_user.sizePolicy().horizontalPolicy() == QSizePolicy.Preferred
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



def test_database_refresh_keeps_services_suppliers_and_password_status_visible(
    tmp_path, monkeypatch, qapp
):
    """Regression: SQLite batch rows must not break full UI refreshes."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    monkeypatch.setattr(
        main_module.QMessageBox,
        "information",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        main_module.QMessageBox,
        "critical",
        lambda *args, **kwargs: None,
    )

    manager = DatabaseManager(str(tmp_path / "shop.db"))
    manager.add_product(
        "P-1001",
        "",
        "قطعات",
        "کیبورد",
        "Acme",
        "K100",
        {"حافظه": "DDR5 16GB"},
        "کالای دارای مشخصات فنی برای جست‌وجو",
        2,
        20,
    )
    with manager.get_connection() as conn:
        product_id = conn.execute(
            "SELECT id FROM products WHERE code='P-1001'"
        ).fetchone()["id"]
    manager.add_batch(
        "C-1001",
        product_id,
        None,
        None,
        "PO-1",
        "1405/01/01",
        5,
        100,
        0,
        150,
        0,
        "SERIAL-1",
        "DDR5 16GB",
        "یادداشت محموله",
        "تسویه‌نشده",
    )

    window = MainWindow(manager, active_employee=None)
    try:
        # A real sqlite3.Row batch is loaded during initial startup and refresh.
        assert window.cb_sale_prod.count() == 1
        assert window.cb_sale_batch.count() == 1
        assert "DDR5" not in window.cb_sale_batch.itemText(0)
        window.cb_sale_batch._search_proxy.set_query("DDR5")
        assert window.cb_sale_batch._search_proxy.rowCount() == 1
        window.cb_sale_batch._search_proxy.set_query("")

        # The add-supplier flow calls refresh_all_data() after committing.
        window.ed_sup_name.setText("تأمین‌کننده رگرسیون")
        window._add_supplier()
        with manager.get_connection() as conn:
            supplier_count = conn.execute(
                "SELECT COUNT(*) FROM suppliers WHERE name=?",
                ("تأمین‌کننده رگرسیون",),
            ).fetchone()[0]
        assert supplier_count == 1
        assert window.tbl_suppliers.rowCount() == 1

        # Purchase registration must still complete and refresh with a populated batch table.
        window.cb_batch_qty.setCurrentText("2")
        window.ed_batch_inv.setText("PO-2")
        window.pr_batch_buy.set_value(100)
        window.pr_batch_suggest.set_value(150)
        window._save_new_batch()
        with manager.get_connection() as conn:
            batch_count = conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0]
        assert batch_count == 2

        # Adding a tariff must both persist it and refresh the visible catalog.
        window.ed_srv_name.setText("نصب ویندوز آزمون")
        window.ed_srv_code.clear()
        window.pr_srv_def_fee.set_value(250000)
        window._add_new_service_tariff()
        with manager.get_connection() as conn:
            service = conn.execute(
                "SELECT code, name FROM service_catalog WHERE name=?",
                ("نصب ویندوز آزمون",),
            ).fetchone()
        assert service is not None
        assert service["code"].startswith("S-")
        assert window.tbl_srv_catalog.rowCount() == 1
        assert window.tbl_srv_catalog.item(0, 3).text() == "نصب ویندوز آزمون"

        # The password indicator must reflect the committed password immediately.
        with manager.get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO employees (name, role, phone, permissions, is_active) "
                "VALUES (?, ?, ?, ?, 1)",
                ("کاربر بدون رمز", "فروشنده", "", "فروش و خدمات"),
            )
            employee_id = int(cursor.lastrowid)
            conn.commit()
        window.refresh_all_data()
        window.selected_emp_id = employee_id
        window.ed_emp_name.setText("کاربر بدون رمز")
        window.cb_emp_role.setCurrentText("فروشنده")
        window.ed_emp_phone.clear()
        window.cb_emp_perm.setCurrentText("فروش و خدمات (گزارش محدود به عملکرد خود)")
        window.chk_emp_active.setChecked(True)
        window.ed_emp_old_pass.clear()
        window.ed_emp_pass.setText("New-Password-123")
        window._update_employee()

        with manager.get_connection() as conn:
            stored_password = conn.execute(
                "SELECT password FROM employees WHERE id=?", (employee_id,)
            ).fetchone()["password"]
        assert stored_password
        assert stored_password != "New-Password-123"

        employee_row = next(
            row for row in range(window.tbl_employees.rowCount())
            if window.tbl_employees.item(row, 0).text() == str(employee_id)
        )
        assert window.tbl_employees.item(employee_row, 5).text() == "بله"

        # Reopen with required-password policy enabled, authenticate and build the main UI.
        manager.cfg["require_login_password"] = True
        database_module.save_app_config(manager.cfg)
        reopened_manager = DatabaseManager(str(tmp_path / "shop.db"))
        assert reopened_manager.cfg["require_login_password"] is True

        login = main_module.LoginDialog(reopened_manager)
        try:
            login.ed_pass.setText("New-Password-123")
            login._check_login()
            assert login.logged_employee is not None
            assert login.result() == 1  # QDialog.Accepted

            protected_window = MainWindow(
                reopened_manager, active_employee=login.logged_employee
            )
            try:
                assert protected_window.cb_sale_batch.count() == 2
                assert "کاربر بدون رمز" in protected_window.lbl_active_user.text()
                protected_employee_row = next(
                    row for row in range(protected_window.tbl_employees.rowCount())
                    if protected_window.tbl_employees.item(row, 0).text() == str(employee_id)
                )
                assert protected_window.tbl_employees.item(
                    protected_employee_row, 5
                ).text() == "بله"
            finally:
                protected_window.close()
        finally:
            login.close()
    finally:
        window.close()
        qapp.processEvents()
