import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCompleter,
    QSizePolicy,
    QPushButton,
    QToolButton,
    QScrollBar,
    QLabel,
    QWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics

import database as database_module
import exporter as exporter_module
import main as main_module
from database import DatabaseManager
from main import MainWindow, SmoothScrollArea
from utils_and_widgets import (
    JalaliCalendarDialog,
    PriceInput,
    _animate_scrollbar,
    bidi_isolate_text,
    strip_bidi_controls,
)


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
        assert window.chk_upg_consume_stock.isChecked()
        assert window.tabs.tabText(9).endswith("تنظیمات")
        assert window.lbl_app_version.text() == "دقیق | نسخه برنامه: 4.8.2"
        assert [window.catalog_tabs.tabText(i) for i in range(window.catalog_tabs.count())] == [
            "مدیریت کالاها",
            "مدیریت خدمات",
            "تنظیمات خروجی موجودی همکار",
            "تنظیمات خروجی اکسل گزارش‌ها",
            "مدیریت سطوح دسترسی",
        ]
        assert len(window.inventory_export_column_checks) == 32
        for key in ("code", "batch_code", "category", "subcategory", "brand_model", "specs"):
            assert window.inventory_export_column_checks[key].isChecked()
        assert not window.inventory_export_column_checks["suggested_price"].isChecked()
        assert not window.inventory_export_column_checks["stock"].isChecked()
        assert not window.inventory_export_column_checks["purchase_unit_price"].isChecked()
        assert not window.inventory_export_column_checks["unit_cost_price"].isChecked()
        assert not window.inventory_export_column_checks["profit_pct"].isChecked()
        assert window.lbl_store_name.text().strip("\u2067\u2069") == "دقیق | فروشگاه من"
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
        assert window.lbl_active_db_path.layoutDirection() == Qt.LeftToRight
        assert window.lbl_active_db_path.alignment() & Qt.AlignLeft
        assert window.lst_cfg_attributes.minimumHeight() >= 140
        attribute_section = window.lst_cfg_attributes.parentWidget()
        assert attribute_section.header.objectName() == "collapsibleSectionHeader"
        assert window.lst_cfg_attributes.isHidden()
        attribute_section.header.click()
        assert not window.lst_cfg_attributes.isHidden()
        attribute_section.header.click()
        assert window.lst_cfg_attributes.isHidden()
        assert window.btn_theme.isEnabled()
        assert window.btn_table_width.isEnabled()
        assert window.tbl_batches.columnCount() >= 22
        assert isinstance(window.tbl_batches, main_module.SmoothScrollTableWidget)

        # Repeated wheel events accumulate against the previous animation target.
        scroll_owner = QWidget()
        scroll_bar = QScrollBar()
        scroll_bar.setRange(0, 1000)
        scroll_bar.setValue(500)
        assert _animate_scrollbar(scroll_owner, scroll_bar, 120)
        first_target = int(scroll_owner._wheel_animation.endValue())
        assert first_target == 380
        assert _animate_scrollbar(scroll_owner, scroll_bar, 120)
        second_target = int(scroll_owner._wheel_animation.endValue())
        assert second_target == 260
        assert not hasattr(window, "chk_zero_enabled")
        assert window.lbl_live_clock.toolTip()
        assert window.lst_cfg_subcategories.count() > 0
        assert "پردازنده (CPU)" in [
            window.lst_cfg_subcategories.item(index).text()
            for index in range(window.lst_cfg_subcategories.count())
        ]
        assert window.ed_search_sales is not None

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

        assert window.dt_rep_from.get_date() == "1400/01/01"
        assert window.cb_rep_preset.currentText() == "همه زمان‌ها"
        assert window.sp_bk_interval.minimum() == 1
        assert window.dt_batch_date.ed_day.width() >= 48
        assert window.dt_batch_date.ed_month.width() >= 48
        assert window.dt_batch_date.width() < 250
        assert window.tabs.widget(9).findChild(SmoothScrollArea) is not None
        assert isinstance(window.lst_cfg_subcategories, main_module.SmoothScrollListWidget)
        assert isinstance(window.lst_cfg_attributes, main_module.SmoothScrollListWidget)
        assert isinstance(window.lst_cfg_colors, main_module.SmoothScrollListWidget)
        assert isinstance(window.lst_recent_databases, main_module.SmoothScrollListWidget)
        assert window.btn_save_settings.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding

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
        assert window.cb_sale_prod.count() == 2
        assert window.cb_sale_prod.itemData(0).get("_all_products") is True
        assert window.cb_sale_prod.itemText(0) == "همه کالاها"
        assert window.cb_sale_batch.count() == 1
        # Purchase picker hides long specs in the row but includes them in its search and hover text.
        assert "DDR5" not in window.cb_batch_prod.itemText(0)
        assert window.cb_batch_prod._search_proxy.rowCount() >= 1
        assert "DDR5" in window.cb_batch_prod.itemData(0, Qt.ToolTipRole)
        window.cb_batch_prod._search_proxy.set_query("DDR5")
        assert window.cb_batch_prod._search_proxy.rowCount() == 1
        window.cb_batch_prod._search_proxy.set_query("")
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
        assert any(
            window.tbl_suppliers.item(row, 1).text() == "تأمین‌کننده رگرسیون"
            for row in range(window.tbl_suppliers.rowCount())
        )

        # Purchase registration must still complete and refresh with a populated batch table.
        window.cb_batch_qty.setCurrentText("2")
        window.ed_batch_inv.setText("PO-2")
        window.pr_batch_buy.set_value(100)
        window.pr_batch_suggest.set_value(150)
        window._save_new_batch()
        with manager.get_connection() as conn:
            batch_count = conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0]
        assert batch_count == 2

        # The same purchase form must update and delete a shipment without
        # leaving supplier, payment, or sale references behind.
        with manager.get_connection() as conn:
            purchase_id = int(conn.execute(
                "SELECT id FROM batches WHERE invoice_number='PO-2'"
            ).fetchone()["id"])
        window.selected_batch_id = purchase_id
        window.ed_batch_inv.setText("PO-2-EDIT")
        window.cb_batch_qty.setCurrentText("3")
        window.pr_batch_buy.set_value(110)
        window.pr_batch_extra.set_value(30)
        window.pr_batch_suggest.set_value(170)
        window.cb_batch_status.setCurrentText("تسویه‌نشده")
        window.pr_batch_paid.set_value(0)
        window.ed_batch_serial.setText("SERIAL-UPDATED")
        window._update_selected_batch()
        with manager.get_connection() as conn:
            edited = conn.execute(
                "SELECT invoice_number, initial_qty, remaining_qty, unit_purchase_price "
                "FROM batches WHERE id=?",
                (purchase_id,),
            ).fetchone()
        assert edited["invoice_number"] == "PO-2-EDIT"
        assert edited["initial_qty"] == 3
        assert edited["remaining_qty"] == 3
        assert edited["unit_purchase_price"] == 110

        monkeypatch.setattr(main_module, "_ask_yes_no", lambda *_args: True)
        window.selected_batch_id = purchase_id
        window._delete_selected_batch()
        with manager.get_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM batches WHERE id=?", (purchase_id,)
            ).fetchone()[0] == 0
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

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
                # A self-scoped user without owned shipments must not see global sale stock.
                assert protected_window.cb_sale_prod.count() == 1
                assert protected_window.cb_sale_batch.count() == 0
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



def test_create_database_action_defaults_to_new_daqiq_filename(
    tmp_path, monkeypatch, qapp
):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "active.db"))
    window = MainWindow(manager, active_employee=None)
    captured = []

    def capture_dialog(*args, **kwargs):
        captured.append(args)
        return "", ""

    monkeypatch.setattr(main_module.QFileDialog, "getSaveFileName", capture_dialog)
    try:
        window._create_and_connect_new_db()
        assert captured
        # REQ-2: Defaults to Daqiq.db if missing, or Daqiq_ timestamped if existing
        assert os.path.basename(captured[0][2]) == "Daqiq.db"
        # When Daqiq.db already exists in directory:
        daqiq_path = os.path.join(os.path.dirname(captured[0][2]), "Daqiq.db")
        with open(daqiq_path, "w") as f:
            f.write("existing")
        captured.clear()
        window._create_and_connect_new_db()
        assert os.path.basename(captured[0][2]).startswith("Daqiq_") and captured[0][2].endswith(".db")
    finally:
        window.close()
        qapp.processEvents()


def test_first_run_database_wizard_validates_new_and_existing_files(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))

    new_path = tmp_path / "first-run" / "store.db"
    create_dialog = main_module.DatabaseBootstrapDialog(str(new_path))
    create_dialog._validate_and_accept()
    assert create_dialog.selected_path == str(new_path)
    assert not new_path.exists()
    create_dialog.close()

    existing_path = tmp_path / "existing.db"
    DatabaseManager(str(existing_path))
    connect_dialog = main_module.DatabaseBootstrapDialog(str(existing_path))
    connect_dialog.rb_existing.setChecked(True)
    connect_dialog._validate_and_accept()
    assert connect_dialog.selected_path == str(existing_path)
    connect_dialog.close()


def test_sale_batch_picker_shows_only_distinguishing_specifications(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    manager.add_product(
        "P-2000", "", "لپ‌تاپ", "لپ‌تاپ عمومی / مالتی‌مدیا",
        "ASUS", "G551", {"CPU": "Core i7", "RAM": "8GB"}, "", 1, 20,
    )
    with manager.get_connection() as conn:
        product_id = conn.execute(
            "SELECT id FROM products WHERE code='P-2000'"
        ).fetchone()["id"]

    manager.add_batch(
        "C-2001", product_id, None, None, "PO-1", "1405/01/01", 2,
        100, 0, 150, 0, "", "CPU: Core i7 | RAM: 8GB | SSD: 512GB",
        "سری اول", "تسویه‌نشده",
    )
    manager.add_batch(
        "C-2002", product_id, None, None, "PO-2", "1405/01/02", 2,
        100, 0, 150, 0, "", "CPU: Core i7 | RAM: 16GB | SSD: 512GB",
        "سری دوم", "تسویه‌نشده",
    )

    window = MainWindow(manager, active_employee=None)
    try:
        assert window.cb_sale_prod.count() == 2
        assert window.cb_sale_prod.itemData(0).get("_all_products") is True
        assert strip_bidi_controls(window.cb_sale_prod.itemText(1)) == (
            "P-2000 | لپ‌تاپ عمومی / مالتی‌مدیا | ASUS G551"
        )
        assert window.cb_sale_batch.count() == 2

        labels = [
            strip_bidi_controls(window.cb_sale_batch.itemText(index))
            for index in range(window.cb_sale_batch.count())
        ]
        assert set(labels) == {
            "C-2001 | رنگ: - | قیمت پیشنهادی: 150 تومان",
            "C-2002 | رنگ: - | قیمت پیشنهادی: 150 تومان",
        }
        assert all("RAM:" not in label and "CPU:" not in label for label in labels)
        assert window.cb_sale_batch.view().layoutDirection() == Qt.RightToLeft

        missing_spec_labels = MainWindow._batch_variant_labels([
            {"id": 1, "final_specs": "CPU: Core i7 | RAM: 8GB"},
            {"id": 2, "final_specs": "CPU: Core i7"},
        ])
        assert missing_spec_labels[2] == "RAM: ثبت نشده"

        raw_tooltips = [
            window.cb_sale_batch.itemData(index, Qt.ToolTipRole)
            for index in range(window.cb_sale_batch.count())
        ]
        assert all('dir="rtl"' in tooltip and 'align="right"' in tooltip for tooltip in raw_tooltips)
        tooltips = [strip_bidi_controls(tooltip) for tooltip in raw_tooltips]
        assert any("RAM: 8GB" in tooltip for tooltip in tooltips)
        assert any("RAM: 16GB" in tooltip for tooltip in tooltips)
        assert all("CPU: Core i7" in tooltip and "SSD: 512GB" in tooltip for tooltip in tooltips)
        assert all("مشخصات اولیه" not in tooltip for tooltip in tooltips)

        window.cb_sale_batch._search_proxy.set_query("SSD: 512GB")
        assert window.cb_sale_batch._search_proxy.rowCount() == 2
        window.cb_sale_batch._search_proxy.set_query("16GB")
        assert window.cb_sale_batch._search_proxy.rowCount() == 1
    finally:
        window.close()
        qapp.processEvents()


def test_settings_are_drafts_until_saved_and_recent_database_x_keeps_the_file(
    tmp_path, monkeypatch, qapp
):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    monkeypatch.setattr(
        main_module.QMessageBox, "information", lambda *args, **kwargs: None
    )
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    manager.cfg["auto_backup_interval_min"] = 60
    manager.cfg["default_profit_pct"] = 20
    database_module.save_app_config(manager.cfg)

    other_path = tmp_path / "other" / "other.db"
    DatabaseManager(str(other_path))
    window = MainWindow(manager, active_employee=None)
    try:
        assert window.sp_bk_interval.value() == 60
        assert window.sp_set_profit.value() == 20

        window.sp_bk_interval.setValue(15)
        window.sp_set_profit.setValue(45)
        window.tabs.setCurrentIndex(0)
        window.tabs.setCurrentIndex(window._settings_tab_index)

        # Leaving Settings and returning must discard unsaved edits.
        assert window.sp_bk_interval.value() == 60
        assert window.sp_set_profit.value() == 20

        manager.cfg["recent_databases"] = [manager.db_path, str(other_path)]
        database_module.save_app_config(manager.cfg)
        window._refresh_multi_db_combo()
        assert window.lst_recent_databases.count() == 2
        active_widget = window.lst_recent_databases.itemWidget(
            window.lst_recent_databases.item(0)
        )
        active_badge = active_widget.findChild(QLabel, "databaseActiveBadge")
        assert active_badge is not None
        assert active_badge.text() == "فعال / متصل"
        assert active_badge.width() >= 96 and active_badge.height() >= 32
        active_x = [
            button for button in active_widget.findChildren(QToolButton)
            if button.text() == "×"
        ][0]
        assert active_x.width() >= 32 and active_x.height() >= 32
        assert not active_x.isEnabled()

        other_widget = window.lst_recent_databases.itemWidget(
            window.lst_recent_databases.item(1)
        )
        other_x = [
            button for button in other_widget.findChildren(QToolButton)
            if button.text() == "×"
        ][0]
        assert other_x.isEnabled()
        assert other_x.width() >= 32 and other_x.height() >= 32
        other_x.click()
        assert window.lst_recent_databases.count() == 1
        assert os.path.isfile(other_path)  # X removes the recent path, not the file.

        window.sp_bk_interval.setValue(25)
        window.sp_set_profit.setValue(35)
        window._save_general_settings()
        assert manager.cfg["auto_backup_interval_min"] == 25
        assert manager.cfg["default_profit_pct"] == 35

        reloaded = DatabaseManager(str(tmp_path / "shop.db"))
        assert reloaded.cfg["auto_backup_interval_min"] == 25
        assert reloaded.cfg["default_profit_pct"] == 35
    finally:
        window.close()
        qapp.processEvents()


def test_jalali_calendar_uses_theme_and_readable_day_cells(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    window = MainWindow(manager, active_employee=None)
    try:
        manager.cfg["theme"] = "dark"
        calendar = JalaliCalendarDialog("1405/01/01", window)
        try:
            assert calendar.width() >= 450
            assert calendar.height() >= 420
            assert calendar.day_buttons[0].width() >= 48
            assert "#263244" in calendar.styleSheet()
        finally:
            calendar.close()
    finally:
        window.close()
        qapp.processEvents()



def test_custom_attribute_name_is_form_label_and_title_is_output_label(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    manager.save_product_catalog_config({
        "categories": ["قطعات"],
        "subcategories": {"قطعات": ["پردازنده (CPU)"]},
        "attributes": {"قطعات": [{
            "name": "پردازنده",
            "label": "CPU",
            "display_name": "مدل پردازنده",
            "values": ["Core i5", "Core i7"],
            "subcategory": "پردازنده (CPU)",
        }]},
        "colors": [],
    })
    window = MainWindow(manager, active_employee=None)
    try:
        assert "پردازنده" in window.specs_widget.fields
        field_widget = window.specs_widget.fields["پردازنده"]
        assert field_widget.toolTip() == "مشخصات فنی: پردازنده"
        field_label = window.specs_widget.form_layout.labelForField(field_widget)
        assert field_label.text() == "پردازنده:"
        assert window._format_specs_for_display({"پردازنده": "Core i7"}, "قطعات") == (
            "CPU: Core i7"
        )
        assert window._format_specs_for_tooltip({"پردازنده": "Core i7"}, "قطعات") == (
            "CPU: Core i7"
        )
        definition = window.catalog_config["attributes"]["قطعات"][0]
        definition["label"] = ""
        assert window._format_specs_for_display({"پردازنده": "Core i7"}, "قطعات") == (
            "پردازنده: Core i7"
        )

        manager.save_product_catalog_config({
            "categories": ["لپ‌تاپ"],
            "subcategories": {"لپ‌تاپ": ["عمومی"]},
            "attributes": {"لپ‌تاپ": [
                {"name": "رم", "label": "RAM", "values": []},
                {"name": "نوع رم", "label": "@رم", "values": []},
            ]},
            "colors": [],
        })
        window.catalog_config = manager.get_product_catalog_config()
        assert window._format_specs_for_display(
            {"نوع رم": "DDR4", "رم": "8GB"}, "لپ‌تاپ"
        ) == "RAM: 8GB DDR4"
        assert exporter_module._format_catalog_specs(
            {"نوع رم": "DDR4", "رم": "8GB"},
            "لپ‌تاپ",
            window.catalog_config,
        ) == "RAM: 8GB DDR4"
    finally:
        window.close()
        qapp.processEvents()


def test_password_requirement_is_confirmed_when_checkbox_is_enabled(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    with manager.get_connection() as conn:
        conn.execute(
            "INSERT INTO employees (name, role, permissions, is_active) VALUES (?, ?, ?, 1)",
            ("کارمند بدون رمز", "فروشنده", "فروش و خدمات"),
        )
        conn.commit()
    window = MainWindow(manager, active_employee=None)
    prompts = []

    def reject(_parent, title, message):
        prompts.append((title, message))
        return False

    try:
        monkeypatch.setattr(main_module, "_ask_yes_no", reject)
        window.chk_req_pass.setChecked(True)
        assert not window.chk_req_pass.isChecked()
        assert prompts and "کارمند بدون رمز" in prompts[0][1]
        assert "اطمینان دارید" in prompts[0][1]

        monkeypatch.setattr(main_module, "_ask_yes_no", lambda *_args: True)
        window.chk_req_pass.setChecked(True)
        assert window.chk_req_pass.isChecked()
        assert not manager.cfg.get("require_login_password", False)

        with manager.get_connection() as conn:
            conn.execute(
                "UPDATE employees SET password=? WHERE name=?",
                ("stored-password-hash", "کارمند بدون رمز"),
            )
            conn.commit()
        def accept_and_capture(_parent, title, message):
            prompts.append((title, message))
            return True

        monkeypatch.setattr(main_module, "_ask_yes_no", accept_and_capture)
        window.chk_req_pass.setChecked(False)
        prompts.clear()
        window.chk_req_pass.setChecked(True)
        assert window.chk_req_pass.isChecked()
        assert prompts and "تمام کارکنان فعال" in prompts[0][1]
        assert "اطمینان دارید" in prompts[0][1]
    finally:
        window.close()
        qapp.processEvents()


def test_catalog_manager_selection_and_service_type_crud(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    window = MainWindow(manager, active_employee=None)
    try:
        subcategory_item = window.lst_cfg_subcategories.item(0)
        window.lst_cfg_subcategories.setCurrentItem(subcategory_item)
        assert window.ed_cfg_subcategory.text() == subcategory_item.text()

        color_item = window.lst_cfg_colors.item(0)
        window.lst_cfg_colors.setCurrentItem(color_item)
        assert window.ed_cfg_color.text() == color_item.text()

        window.ed_cfg_service_type.setText("شبکه")
        window._add_catalog_service_type()
        assert "شبکه" in window._taxonomy_draft["service_types"]
        network_item = next(
            window.lst_cfg_service_types.item(i)
            for i in range(window.lst_cfg_service_types.count())
            if window.lst_cfg_service_types.item(i).text() == "شبکه"
        )
        window.lst_cfg_service_types.setCurrentItem(network_item)
        assert window.ed_cfg_service_type.text() == "شبکه"
        window.ed_cfg_service_type.setText("شبکه و ارتباطات")
        window._rename_catalog_service_type()
        assert "شبکه و ارتباطات" in window._taxonomy_draft["service_types"]
        renamed_item = next(
            window.lst_cfg_service_types.item(i)
            for i in range(window.lst_cfg_service_types.count())
            if window.lst_cfg_service_types.item(i).text() == "شبکه و ارتباطات"
        )
        window.lst_cfg_service_types.setCurrentItem(renamed_item)
        window._delete_catalog_service_type()
        assert "شبکه و ارتباطات" not in window._taxonomy_draft["service_types"]

        manager.save_product_catalog_config(window._taxonomy_draft)
        assert manager.get_product_catalog_config()["service_types"] == (
            window._taxonomy_draft["service_types"]
        )
    finally:
        window.close()
        qapp.processEvents()


def test_database_records_move_to_top_after_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    manager.add_product(
        "P-3001", "", "لپ‌تاپ", "عمومی", "ASUS", "A1", {}, "", 1, 20
    )
    manager.add_product(
        "P-3002", "", "لپ‌تاپ", "عمومی", "HP", "H1", {}, "", 1, 20
    )
    with manager.get_connection() as conn:
        first_id = conn.execute(
            "SELECT id FROM products WHERE code='P-3001'"
        ).fetchone()["id"]
        second_id = conn.execute(
            "SELECT id FROM products WHERE code='P-3002'"
        ).fetchone()["id"]
    with manager.get_connection() as conn:
        before = conn.execute(
            "SELECT updated_at FROM products WHERE id=?", (first_id,)
        ).fetchone()["updated_at"]
        conn.execute("UPDATE products SET model='A1-Pro' WHERE id=?", (first_id,))
        after = conn.execute(
            "SELECT updated_at FROM products WHERE id=?", (first_id,)
        ).fetchone()["updated_at"]
        ordered = conn.execute(
            "SELECT id FROM products ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    assert after > before
    assert [row["id"] for row in ordered] == [first_id, second_id]


def test_settings_sections_start_collapsed(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    window = MainWindow(manager, active_employee=None)
    try:
        from utils_and_widgets import CollapsibleSection
        sections = window.findChildren(CollapsibleSection)
        assert sections
        assert all(not section._expanded for section in sections)
        section = sections[0]
        section.header.click()
        qapp.processEvents()
        assert section._expanded
        assert not section.content.isHidden()
        section.header.click()
        qapp.processEvents()
        assert not section._expanded
        assert section.content.isHidden()
    finally:
        window.close()
        qapp.processEvents()


def test_autogenerated_codes_are_placeholders_on_first_load(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    window = MainWindow(manager, active_employee=None)
    try:
        fields = [
            (window.ed_prod_code, "P-1001"),
            (window.ed_batch_code, "C-1001"),
            (window.ed_sale_inv, "INV-1001"),
            (window.ed_srv_code, "S-1001"),
        ]
        for edit, next_code in fields:
            assert edit.text() == ""
            assert edit.placeholderText() == next_code
    finally:
        window.close()
        qapp.processEvents()


def test_inventory_bound_quantities_are_not_editable(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    window = MainWindow(manager, active_employee=None)
    try:
        assert not window.cb_sale_qty.isEditable()
        assert not window.cb_upg_target_qty.isEditable()
        assert not window.cb_upg_part_qty.isEditable()
        assert window.cb_batch_qty.isEditable()
        assert not window.cb_prod_cat.isEditable()
        assert not window.specs_widget.cb_sub.isEditable()
    finally:
        window.close()
        qapp.processEvents()


def test_calendar_year_range_and_day_picker_are_consistent(qapp):
    calendar = JalaliCalendarDialog("1405/01/15")
    try:
        years = [calendar.cb_year.itemText(i) for i in range(calendar.cb_year.count())]
        assert years[0] == "1400"
        assert years[-1] == "1600"
        assert len(years) == 201
        assert calendar.cb_day.count() == 31

        calendar.cb_month.setCurrentIndex(calendar.cb_month.findData(3))
        assert calendar.cb_day.model().item(30).isEnabled()
        calendar.cb_month.setCurrentIndex(calendar.cb_month.findData(7))
        assert not calendar.cb_day.model().item(30).isEnabled()
    finally:
        calendar.close()


def test_bidi_text_is_kept_in_logical_order_without_invisible_controls():
    mixed = "نوع RAM: 12GB و مدل CPU: Core i7"
    latin_only = "RAPOO 9550L"
    rendered = bidi_isolate_text(mixed)
    assert rendered == mixed
    assert strip_bidi_controls(rendered) == mixed
    assert bidi_isolate_text(latin_only) == latin_only
    assert "9550L RAPOO" not in rendered
    assert all(marker not in rendered for marker in ("\u2066", "\u2069", "\u200e", "\u200f"))


def test_price_input_selects_the_full_amount_on_focus(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    edit = PriceInput(manager)
    try:
        edit.set_value(1234567)
        edit.show()
        edit.setFocus()
        qapp.processEvents()
        assert edit.selectedText() == edit.text()
    finally:
        edit.close()
        qapp.processEvents()


def test_all_remaining_clear_buttons_reset_requested_fields(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    window = MainWindow(manager, active_employee=None)
    try:
        window.pr_batch_buy.set_value(111)
        window.pr_batch_extra.set_value(222)
        window.pr_batch_suggest.set_value(333)
        window.pr_batch_paid.set_value(444)
        window.ed_batch_inv.setText("PO-RESET")
        window._clear_batch_form()
        assert [
            window.pr_batch_buy.get_value(),
            window.pr_batch_extra.get_value(),
            window.pr_batch_suggest.get_value(),
            window.pr_batch_paid.get_value(),
        ] == [0, 0, 0, 0]
        assert window.ed_batch_inv.text() == ""
        assert window.cb_batch_prod.currentIndex() == -1
        assert window.cb_batch_supplier.currentIndex() == -1

        window.pr_srv_def_fee.set_value(555)
        window.pr_srv_def_side.set_value(666)
        window._clear_service_cat_form()
        assert window.pr_srv_def_fee.get_value() == 0
        assert window.pr_srv_def_side.get_value() == 0

        window.pr_srv_fee.set_value(777)
        window.pr_srv_side.set_value(888)
        window.pr_srv_paid.set_value(999)
        window.ed_srv_cust.setText("مشتری آزمایش")
        window._clear_service_rec_form()
        assert [
            window.pr_srv_fee.get_value(),
            window.pr_srv_side.get_value(),
            window.pr_srv_paid.get_value(),
        ] == [0, 0, 0]
        assert window.ed_srv_cust.text() == ""
        assert window.cb_srv_select.currentIndex() == -1
        assert window.cb_srv_seller.currentIndex() == -1

        window.pr_upg_labor.set_value(1234)
        window._clear_upgrade_form()
        assert window.pr_upg_labor.get_value() == 0
    finally:
        window.close()
        qapp.processEvents()


def test_sale_clear_form_resets_values_and_keeps_next_invoice_as_placeholder(
    tmp_path, monkeypatch, qapp
):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    manager.add_product(
        "P-2000", "", "لپ‌تاپ", "لپ‌تاپ عمومی / مالتی‌مدیا",
        "ASUS", "G551", {"RAM": "8GB"}, "", 1, 20,
    )
    with manager.get_connection() as conn:
        product_id = conn.execute(
            "SELECT id FROM products WHERE code='P-2000'"
        ).fetchone()["id"]
    manager.add_batch(
        "C-2000", product_id, None, None, "PO-2000", "1405/01/01", 3,
        100, 0, 150, 0, "", "RAM: 8GB", "", "تسویه‌نشده",
    )

    window = MainWindow(manager, active_employee=None)
    try:
        window.ed_sale_inv.setText("MANUAL-INV")
        window.ed_sale_customer.setText("مشتری آزمایشی")
        window.ed_sale_specs.setText("RAM: 16GB DDR5")
        window.pr_sale_paid.set_value(500)
        window.ed_war_company.setText("Warranty")
        window.ed_sale_serial.setText("SERIAL-1")
        window.dt_war_start.set_date("1404/01/01")
        window.dt_war_end.set_date("1404/02/01")
        window.pr_sale_actual.set_value(999)
        window._clear_sale_form()

        assert window.selected_sale_id is None
        assert window.ed_sale_inv.text() == ""
        assert window.ed_sale_inv.placeholderText() == "INV-1001"
        assert window.ed_sale_customer.text() == ""
        assert window.ed_sale_specs.text() == ""
        assert window.pr_sale_actual.get_value() == 0
        assert window.pr_sale_paid.get_value() == 0
        assert window.ed_war_company.text() == ""
        assert window.ed_sale_serial.text() == ""
        assert window.dt_war_start.get_date() == ""
        assert window.dt_war_end.get_date() == ""
        assert window.cb_sale_qty.currentText() == "1"
        assert not window.cb_sale_qty.isEditable()
        assert window.cb_sale_prod.currentText() == "همه کالاها"
        assert window.cb_sale_prod.currentData().get("_all_products") is True
    finally:
        window.close()
        qapp.processEvents()


def test_sales_all_products_loads_batches_and_saves_the_selected_batch_product(
    tmp_path, monkeypatch, qapp
):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    monkeypatch.setattr(main_module.QMessageBox, "critical", lambda *args, **kwargs: pytest.fail(str(args[2] if len(args) > 2 else args)))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    manager.add_product(
        "P-ALL-1", "", "لوازم جانبی", "کیبورد", "Acme", "K100",
        {"نوع اتصال": "USB"}, "", 1, 20,
    )
    manager.add_product(
        "P-ALL-2", "", "مانیتور", "مانیتور اداری", "View", "V24",
        {"سایز": "24 inch"}, "", 1, 20,
    )
    with manager.get_connection() as conn:
        product_ids = {
            row["code"]: row["id"]
            for row in conn.execute(
                "SELECT id, code FROM products WHERE code IN ('P-ALL-1','P-ALL-2')"
            ).fetchall()
        }
    manager.add_batch(
        "C-ALL-1", product_ids["P-ALL-1"], None, None, "PO-ALL-1", "1405/01/01",
        2, 100, 0, 150, 0, "", "Keyboard USB", "", "تسویه‌نشده",
        colors=["مشکی", "سبز"],
    )
    manager.add_batch(
        "C-ALL-2", product_ids["P-ALL-2"], None, None, "PO-ALL-2", "1405/01/02",
        2, 200, 0, 300, 0, "", "Display 24 inch", "", "تسویه‌نشده",
        colors=["آبی"],
    )

    window = MainWindow(manager, active_employee=None)
    try:
        assert window.cb_sale_prod.currentText() == "همه کالاها"
        assert window.cb_sale_prod.currentData().get("_all_products") is True
        assert window.cb_sale_batch.count() == 2
        batch_index = next(
            index for index in range(window.cb_sale_batch.count())
            if window.cb_sale_batch.itemData(index)["batch_code"] == "C-ALL-2"
        )
        batch_label = window.cb_sale_batch.itemText(batch_index)
        assert strip_bidi_controls(batch_label) == (
            "C-ALL-2 | رنگ: آبی | قیمت پیشنهادی: 300 تومان"
        )
        window.cb_sale_batch.setCurrentIndex(batch_index)
        batch = window.cb_sale_batch.currentData()
        assert batch["product_id"] == product_ids["P-ALL-2"]
        assert window.btn_sale_colors.available_colors() == ["آبی"]
        window.btn_sale_colors.set_colors(
            window.btn_sale_colors.available_colors(), ["آبی"]
        )
        window.cb_sale_qty.setCurrentText("1")
        window.ed_sale_inv.setText("INV-ALL-PRODUCTS")
        window.cb_sale_status.setCurrentText("تسویه‌نشده")
        window.pr_sale_paid.set_value(0)
        window._save_new_sale()

        with manager.get_connection() as conn:
            sale = conn.execute(
                """SELECT product_id, batch_id, colors_json
                   FROM sales WHERE invoice_number='INV-ALL-PRODUCTS'"""
            ).fetchone()
        assert sale is not None
        assert sale["product_id"] == product_ids["P-ALL-2"]
        assert sale["batch_id"] == batch["id"]
        assert json.loads(sale["colors_json"]) == ["آبی"]
    finally:
        window.close()
        qapp.processEvents()


def test_password_policy_cannot_be_enabled_without_any_user(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    window = MainWindow(manager, active_employee=None)
    messages = []
    try:
        monkeypatch.setattr(
            main_module.QMessageBox,
            "information",
            lambda _parent, title, message: messages.append((title, message)),
        )
        monkeypatch.setattr(
            main_module,
            "_ask_yes_no",
            lambda *_args: pytest.fail("Confirmation must not be requested when no user exists"),
        )
        window.chk_req_pass.setChecked(True)
        assert not window.chk_req_pass.isChecked()
        assert messages and "حداقل یک کاربر" in messages[0][1]
    finally:
        window.close()
        qapp.processEvents()


def test_catalog_aliases_are_merged_and_existing_product_specs_are_migrated(
    tmp_path, monkeypatch, qapp
):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    monkeypatch.setattr(main_module.QMessageBox, "information", lambda *args, **kwargs: None)
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    manager.save_product_catalog_config({
        "categories": ["لپ‌تاپ"],
        "subcategories": {"لپ‌تاپ": ["عمومی", "عمومی"]},
        "attributes": {"لپ‌تاپ": [
            {"name": "صفحه‌نمایش", "label": "Display", "values": ["FHD"], "subcategory": ""},
            {"name": "صفحه نمایش", "label": "Display", "values": ["IPS"], "subcategory": ""},
        ]},
        "colors": ["مشکی"],
        "service_types": ["نرم‌افزاری", "سخت‌افزاری"],
    })
    manager.add_product(
        "P-ALIAS", "", "لپ‌تاپ", "عمومی", "Acme", "L1",
        {"صفحه‌نمایش": "FHD", "صفحه نمایش": "IPS"}, "", 1, 20,
    )
    window = MainWindow(manager, active_employee=None)
    try:
        items = window._taxonomy_draft["attributes"]["لپ‌تاپ"]
        assert len([
            item for item in items
            if main_module.normalize_catalog_label(item["name"]) ==
               main_module.normalize_catalog_label("صفحه‌نمایش")
        ]) == 1
        display = next(
            item for item in items
            if main_module.normalize_catalog_label(item["name"]) ==
               main_module.normalize_catalog_label("صفحه‌نمایش")
        )
        assert set(display["values"]) == {"FHD", "IPS"}
        window._save_general_settings()
        with manager.get_connection() as conn:
            product = conn.execute(
                "SELECT specs_json FROM products WHERE code='P-ALIAS'"
            ).fetchone()
        specs = json.loads(product["specs_json"])
        assert "صفحه نمایش" not in specs
        assert specs["صفحه‌نمایش"] == "FHD IPS"
    finally:
        window.close()
        qapp.processEvents()


def test_catalog_settings_recovers_product_subcategories_and_filters_feature_scope(
    tmp_path, monkeypatch, qapp
):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    manager.add_product(
        "P-HIDDEN-SUBCATEGORY", "", "قطعات", "زیرمجموعه ثبت‌شده",
        "Acme", "Part-1", {}, "", 1, 20,
    )
    manager.save_product_catalog_config({
        "categories": ["قطعات"],
        "subcategories": {
            "قطعات": ["پردازنده (CPU)", "کارت گرافیک (Graphic Card)"]
        },
        "attributes": {
            "قطعات": [
                {
                    "name": "فرکانس پردازنده",
                    "label": "CPU Frequency",
                    "values": [],
                    "subcategory": "پردازنده (CPU)",
                },
                {
                    "name": "حافظه گرافیکی",
                    "label": "VRAM",
                    "values": [],
                    "subcategory": "کارت گرافیک (Graphic Card)",
                },
                {
                    "name": "مشخصه مشترک",
                    "label": "Specification",
                    "values": [],
                    "subcategory": "",
                },
            ]
        },
        "colors": [],
    })
    manager.set_setting(
        "subcategory_field_labels",
        json.dumps({"قطعات": "نوع قطعه"}, ensure_ascii=False),
    )

    window = MainWindow(manager, active_employee=None)
    try:
        window.cb_cfg_category.setCurrentText("قطعات")
        subcategory_names = [
            window.lst_cfg_subcategories.item(index).text()
            for index in range(window.lst_cfg_subcategories.count())
        ]
        assert "زیرمجموعه ثبت‌شده" in subcategory_names
        assert "کارت گرافیک (Graphic Card)" in subcategory_names

        assert not hasattr(window, "cb_subcategory_caption_category")
        assert window.ed_subcategory_caption.text() == "نوع قطعه"
        window.ed_subcategory_caption.setText("نوع قطعه جدید")
        window._save_subcategory_caption()
        saved_labels = json.loads(manager.get_setting("subcategory_field_labels", "{}"))
        assert saved_labels["قطعات"] == "نوع قطعه جدید"

        cpu_index = window.cb_cfg_attribute_subcategory.findData("پردازنده (CPU)")
        gpu_index = window.cb_cfg_attribute_subcategory.findData("کارت گرافیک (Graphic Card)")
        assert cpu_index >= 0 and gpu_index >= 0

        window.cb_cfg_attribute_subcategory.setCurrentIndex(cpu_index)
        cpu_features = [
            window.lst_cfg_attributes.item(index).text()
            for index in range(window.lst_cfg_attributes.count())
        ]
        assert any("فرکانس پردازنده" in item for item in cpu_features)
        assert any("مشخصه مشترک" in item for item in cpu_features)
        assert not any("حافظه گرافیکی" in item for item in cpu_features)

        window.cb_cfg_attribute_subcategory.setCurrentIndex(gpu_index)
        gpu_features = [
            window.lst_cfg_attributes.item(index).text()
            for index in range(window.lst_cfg_attributes.count())
        ]
        assert any("حافظه گرافیکی" in item for item in gpu_features)
        assert any("مشخصه مشترک" in item for item in gpu_features)
        assert not any("فرکانس پردازنده" in item for item in gpu_features)

        # Selecting a universal feature while filtered by a subcategory must
        # preserve the selection after the list is rebuilt for its own scope.
        common_index = next(
            index for index in range(window.lst_cfg_attributes.count())
            if "مشخصه مشترک" in window.lst_cfg_attributes.item(index).text()
        )
        window.lst_cfg_attributes.setCurrentRow(common_index)
        assert window.lst_cfg_attributes.currentItem() is not None
        window.ed_cfg_attribute_label.setText("Shared Specification")
        window._update_catalog_attribute()
        assert any(
            item.get("name") == "مشخصه مشترک"
            and item.get("label") == "Shared Specification"
            for item in window._taxonomy_draft["attributes"]["قطعات"]
        )

        recent_rows = window.lst_recent_databases.findChildren(
            QWidget, "databaseRecentRow"
        )
        assert window.lst_recent_databases.objectName() == "recentDatabasesList"
        assert recent_rows
    finally:
        window.close()
        qapp.processEvents()


def test_technical_attributes_follow_selected_subcategory_and_are_editable(
    tmp_path, monkeypatch, qapp
):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    manager.save_product_catalog_config({
        "categories": ["قطعات"],
        "subcategories": {
            "قطعات": ["پردازنده (CPU)", "کارت گرافیک (Graphic Card)"]
        },
        "attributes": {
            "قطعات": [
                {
                    "name": "TDP",
                    "values": ["45W", "65W"],
                    "subcategory": "پردازنده (CPU)",
                },
                {
                    "name": "VRAM",
                    "values": ["4GB", "8GB"],
                    "subcategory": "کارت گرافیک (Graphic Card)",
                },
            ]
        },
        "colors": ["مشکی"],
    })

    window = MainWindow(manager, active_employee=None)
    try:
        assert window.cb_prod_cat.currentText() == "قطعات"
        assert "توان طراحی حرارتی" in window.specs_widget.fields
        assert "حافظه گرافیکی" not in window.specs_widget.fields
        assert window.specs_widget.fields["توان طراحی حرارتی"].count() == 3

        window.specs_widget.cb_sub.setCurrentText("کارت گرافیک (Graphic Card)")
        assert "حافظه گرافیکی" in window.specs_widget.fields
        assert "توان طراحی حرارتی" not in window.specs_widget.fields
        assert window.specs_widget.fields["حافظه گرافیکی"].count() == 3
    finally:
        window.close()
        qapp.processEvents()



def test_taxonomy_attribute_rename_and_pending_category_delete_preserve_product_data(
    tmp_path, monkeypatch, qapp
):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    monkeypatch.setattr(
        main_module.QMessageBox, "information", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        main_module.QMessageBox, "warning", lambda *args, **kwargs: None
    )

    manager = DatabaseManager(str(tmp_path / "shop.db"))
    manager.add_product(
        "P-TAX-1", "", "قطعات", "پردازنده (CPU)",
        "Intel", "i5", {"TDP": "65W", "رنگ": "مشکی"}, "", 1, 20,
    )

    manager.save_product_catalog_config({
        "categories": ["قطعات"],
        "subcategories": {"قطعات": ["پردازنده (CPU)"]},
        "attributes": {
            "قطعات": [
                {
                    "name": "TDP",
                    "values": ["45W", "65W"],
                    "subcategory": "پردازنده (CPU)",
                }
            ]
        },
        "colors": ["مشکی"],
    })

    window = MainWindow(manager, active_employee=None)
    try:
        window.cb_cfg_category.setCurrentText("قطعات")
        attribute_item = next(
            (
                window.lst_cfg_attributes.item(index)
                for index in range(window.lst_cfg_attributes.count())
                if window.lst_cfg_attributes.item(index).text().startswith(
                    "توان طراحی حرارتی"
                )
            ),
            None,
        )
        assert attribute_item is not None
        window.lst_cfg_attributes.setCurrentItem(attribute_item)
        window.ed_cfg_attribute_name.setText("توان مصرفی")
        window._update_catalog_attribute()

        # Renaming the category and deleting it before Save must not bypass the
        # guard for existing records whose category is still stored under the old name.
        window.ed_cfg_category.setText("سخت‌افزار")
        window._rename_catalog_category()
        assert window.cb_cfg_category.currentText() == "سخت‌افزار"
        window._delete_catalog_category()
        assert "سخت‌افزار" in window._taxonomy_draft["categories"]

        window._save_general_settings()
        assert window.cb_rep_cat.findText("سخت‌افزار") >= 0
        with manager.get_connection() as conn:
            product = conn.execute(
                "SELECT category, specs_json FROM products WHERE code='P-TAX-1'"
            ).fetchone()
        specs = __import__("json").loads(product["specs_json"])
        assert product["category"] == "سخت‌افزار"
        assert specs["توان مصرفی"] == "65W"
        assert "TDP" not in specs
    finally:
        window.close()
        qapp.processEvents()


def test_create_database_dialog_does_not_default_to_overwriting_invalid_file(
    tmp_path, monkeypatch, qapp
):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    monkeypatch.setattr(
        main_module.QMessageBox,
        "critical",
        lambda *args, **kwargs: None,
    )

    corrupt = tmp_path / "corrupt.db"
    corrupt.write_text("not a sqlite database", encoding="utf-8")
    valid_path = tmp_path / "valid.db"
    manager = DatabaseManager(str(valid_path))
    del manager
    assert main_module._is_valid_sqlite_database_file(str(valid_path))

    # A different, healthy SQLite file is not automatically an accounting DB.
    unrelated = tmp_path / "unrelated.db"
    with database_module.sqlite3.connect(unrelated) as conn:
        conn.execute("CREATE TABLE unrelated_records (id INTEGER PRIMARY KEY)")

    for selected_path in (corrupt, unrelated):
        dialog = main_module.DatabaseBootstrapDialog(str(selected_path))
        dialog.rb_existing.setChecked(True)
        dialog._validate_and_accept()
        assert dialog.selected_path is None
        dialog.close()


def test_catalog_create_actions_reject_persian_spacing_aliases(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    window = MainWindow(manager, active_employee=None)
    messages = []
    try:
        monkeypatch.setattr(
            main_module.QMessageBox,
            "information",
            lambda _parent, title, message: messages.append((title, message)),
        )

        category_count = len(window._taxonomy_draft["categories"])
        window.ed_cfg_category.setText("لپ تاپ و سیستم های آماده")
        window._add_catalog_category()
        assert len(window._taxonomy_draft["categories"]) == category_count

        window.cb_cfg_category.setCurrentText("لپ‌تاپ و سیستم‌های آماده")
        subcategories = window._taxonomy_draft["subcategories"]["لپ‌تاپ و سیستم‌های آماده"]
        subcategory_count = len(subcategories)
        window.ed_cfg_subcategory.setText("لپ تاپ گیمینگ (Gaming Laptop)")
        window._add_catalog_subcategory()
        assert len(window._taxonomy_draft["subcategories"]["لپ‌تاپ و سیستم‌های آماده"]) == subcategory_count

        colors = window._taxonomy_draft["colors"]
        color_count = len(colors)
        window.ed_cfg_color.setText("نقره ای")
        window._add_catalog_color()
        assert len(window._taxonomy_draft["colors"]) == color_count

        service_types = window._taxonomy_draft["service_types"]
        service_type_count = len(service_types)
        window.ed_cfg_service_type.setText("تعمیرات سخت افزاری")
        window._add_catalog_service_type()
        assert len(window._taxonomy_draft["service_types"]) == service_type_count

        assert len(messages) == 4
        assert "لپ" in messages[0][1]
        assert "لپ" in messages[1][1]
        assert "نقره" in messages[2][1]
        assert "تعمیرات" in messages[3][1] or "سخت" in messages[3][1]
    finally:
        window.close()
        qapp.processEvents()


def test_comprehensive_report_orders_by_last_edit_and_aligns_specification_column(
    tmp_path, monkeypatch, qapp
):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    manager.add_product(
        "P-REPORT", "", "لپ‌تاپ", "لپ‌تاپ عمومی / مالتی‌مدیا",
        "ASUS", "RPT-15", {"ظرفیت رم": "8GB"}, "", 1, 20,
    )
    with manager.get_connection() as conn:
        product_id = conn.execute(
            "SELECT id FROM products WHERE code='P-REPORT'"
        ).fetchone()["id"]
    manager.add_batch(
        "C-REPORT", product_id, None, None, "PO-REPORT", "1405/01/01",
        5, 100, 0, 150, 0, "", "RAM: 8GB DDR4", "",
        "تسویه‌نشده", colors=["مشکی"],
    )
    with manager.get_connection() as conn:
        batch_id = conn.execute(
            "SELECT id FROM batches WHERE batch_code='C-REPORT'"
        ).fetchone()["id"]

    manager.add_sale(
        "INV-REPORT-OLD", product_id, batch_id, None, "مشتری اول",
        1, 150, 150, 0, "1405/01/01 10:00:00",
        settlement_status="تسویه‌نشده",
        specifications="RAM: 8GB DDR4",
        colors=["مشکی"],
    )
    manager.add_sale(
        "INV-REPORT-NEW", product_id, batch_id, None, "مشتری دوم",
        1, 150, 150, 0, "1405/01/02 10:00:00",
        settlement_status="تسویه‌نشده",
        specifications="RAM: 8GB DDR4",
        colors=["مشکی"],
    )
    with manager.get_connection() as conn:
        old_sale_id = conn.execute(
            "SELECT id FROM sales WHERE invoice_number='INV-REPORT-OLD'"
        ).fetchone()["id"]

    # A later edit to an older invoice must promote that row above the newer invoice.
    manager.update_sale(
        old_sale_id, None, "مشتری اول", 1, 150, 151, 0,
        "", "", 0, "", "", "",
        settlement_status="تسویه‌نشده",
        warranty_days=0,
        specifications="RAM: 16GB DDR5",
        colors=["مشکی"],
    )

    window = MainWindow(manager, active_employee=None)
    try:
        window.cb_rep_type.setCurrentIndex(0)
        window._update_report_live()
        headers = [
            window.tbl_report.horizontalHeaderItem(index).text()
            for index in range(window.tbl_report.columnCount())
        ]
        title_index = headers.index("برند و مدل / عنوان")
        specs_index = headers.index("مشخصات فنی")
        assert specs_index == title_index + 1

        visible_invoices = [
            window.tbl_report.item(row, 1).text()
            for row in range(window.tbl_report.rowCount())
            if window.tbl_report.item(row, 1) is not None
        ]
        sale_invoices = [
            value for value in visible_invoices
            if value in {"INV-REPORT-OLD", "INV-REPORT-NEW"}
        ]
        assert sale_invoices == ["INV-REPORT-OLD", "INV-REPORT-NEW"]

        edited_sale_row = next(
            row for row in range(window.tbl_report.rowCount())
            if window.tbl_report.item(row, 1)
            and window.tbl_report.item(row, 1).text() == "INV-REPORT-OLD"
        )
        first_specs = window.tbl_report.item(edited_sale_row, specs_index).text()
        assert first_specs == "RAM: 16GB DDR5"
        signed_column = headers.index("تخفیف (-) / تشدید (+)")
        signed_cell = window.tbl_report.item(edited_sale_row, signed_column)
        assert signed_cell.text().startswith("\u200e+")
    finally:
        window.close()
        qapp.processEvents()


def test_dark_theme_updates_settings_and_read_only_field_contrast(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    window = MainWindow(manager, active_employee=None)
    try:
        window._apply_styles()
        light_css = window.styleSheet()
        assert "QLabel#appVersion" in light_css
        assert "QLabel#activeDbPath" in light_css
        assert "QScrollBar::up-arrow:vertical" in light_css
        assert "QScrollBar::down-arrow:vertical" in light_css

        manager.cfg["theme"] = "dark"
        window._apply_styles()
        dark_css = window.styleSheet()
        assert "#93c5fd" in dark_css
        assert "#29384d" in dark_css
        assert "QLabel#settingsHint" in dark_css
        assert "QLineEdit:read-only" in dark_css
    finally:
        manager.cfg["theme"] = "light"
        window._apply_styles()
        window.close()
        qapp.processEvents()

def test_table_headers_toggle_smart_sort_and_financial_colors(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    window = MainWindow(manager, active_employee=None)
    try:
        table = window._create_table(["کد", "مبلغ", "بدهی", "طلب"])
        window._populate_table_safely(
            table,
            [
                ["S-12", "-100", "50", "-10"],
                ["S-2", "100", "0", "25"],
                ["S-1", "1,200", "40", "800"],
            ],
        )
        assert table.item(0, 1).foreground().color().name() == "#dc2626"
        assert table.item(0, 2).foreground().color().name() == "#dc2626"
        assert table.item(1, 2).foreground().color().name() != "#dc2626"
        assert table.item(1, 3).foreground().color().name() == "#059669"
        assert table.item(2, 3).foreground().color().name() == "#059669"

        table.horizontalHeader().sectionClicked.emit(0)
        assert table.item(0, 0).text() == "S-1"
        table.horizontalHeader().sectionClicked.emit(0)
        assert table.item(0, 0).text() == "S-12"
        table.horizontalHeader().sectionClicked.emit(1)
        assert table.item(0, 1).text() == "-100"
        assert table.item(1, 1).text() == "100"
        assert table.item(2, 1).text() == "1,200"

        # Switching back to a previously sorted column starts a fresh ascending sort.
        table.horizontalHeader().sectionClicked.emit(0)
        assert table.item(0, 0).text() == "S-1"
        table.horizontalHeader().sectionClicked.emit(0)
        assert table.item(0, 0).text() == "S-12"

        assert main_module._smart_table_sort_key("S-2") < main_module._smart_table_sort_key("S-12")
        assert main_module._smart_table_sort_key("۱۴۰۵/۰۱/۰۲") < main_module._smart_table_sort_key("۱۴۰۵/۰۱/۱۲")
        assert main_module._smart_table_sort_key("250 تومان") < main_module._smart_table_sort_key("1,200 تومان")
    finally:
        window.close()
        qapp.processEvents()


def test_backup_numeric_fields_select_their_current_value_on_focus(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    window = MainWindow(manager, active_employee=None)
    try:
        assert isinstance(window.sp_bk_interval, main_module.SelectAllSpinBox)
        assert isinstance(window.sp_bk_retention, main_module.SelectAllSpinBox)
        window.show()
        window.tabs.setCurrentIndex(window._settings_tab_index)
        qapp.processEvents()
        backup_header = next(
            button for button in window.findChildren(QPushButton, "collapsibleSectionHeader")
            if "پایگاه داده و پشتیبان‌گیری" in button.text()
        )
        backup_header.click()
        qapp.processEvents()
        for spin, value in (
            (window.sp_bk_interval, 90),
            (window.sp_bk_retention, 12),
        ):
            spin.setValue(value)
            spin.lineEdit().setFocus(Qt.OtherFocusReason)
            qapp.processEvents()
            assert spin.lineEdit().selectedText() == str(value)
    finally:
        window.close()
        qapp.processEvents()


def test_dashboard_roles_have_granular_metric_and_table_permissions():
    required = {
        "dashboard.metric.sales_today",
        "dashboard.metric.profit_today",
        "dashboard.metric.purchase_today",
        "dashboard.metric.total_stock",
        "dashboard.metric.low_stock_count",
        "dashboard.metric.supplier_debt",
        "dashboard.metric.service_profit_today",
        "dashboard.table.low_stock",
        "dashboard.table.employee_performance",
    }
    assert required.issubset(set(main_module.ALL_PERMISSION_KEYS))
    assert required.issubset(
        set(main_module.ROLE_PERMISSION_PRESETS[
            "سرپرست عملیات (گزارش‌های محدود به عملکرد خود)"
        ])
    )


def test_comprehensive_report_uses_real_service_catalog_code(tmp_path, monkeypatch, qapp):
    import jdatetime

    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    manager.save_service_catalog(
        None, "S-1001", "نرم‌افزاری", "نصب سیستم‌عامل", 1000, 0, ""
    )
    with manager.get_connection() as conn:
        service_id = conn.execute(
            "SELECT id FROM service_catalog WHERE code='S-1001'"
        ).fetchone()["id"]
    window = MainWindow(manager, active_employee=None)
    try:
        today = jdatetime.date.today().strftime("%Y/%m/%d")
        manager.add_service_record(
            "", service_id, None, None, "مشتری آزمون", 1000, 0, 1000,
            f"{today} 12:00:00", "آزمون", "تسویه‌شده",
        )
        window.dt_rep_from.set_date(today)
        window.dt_rep_to.set_date(today)
        window.cb_rep_type.setCurrentIndex(0)
        window._update_report_live()

        headers = [
            window.tbl_report.horizontalHeaderItem(i).text()
            for i in range(window.tbl_report.columnCount())
        ]
        code_column = headers.index("کد کالا / خدمت")
        type_column = headers.index("نوع عملیات")
        visible_codes = [
            window.tbl_report.item(row, code_column).text()
            for row in range(window.tbl_report.rowCount())
            if "خدمات" in window.tbl_report.item(row, type_column).text()
        ]
        assert "S-1001" in visible_codes
        assert "SRV" not in visible_codes
    finally:
        window.close()
        qapp.processEvents()


def test_settings_catalog_synchronizes_builtin_and_saved_product_features(
    tmp_path, monkeypatch, qapp
):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    manager.add_product(
        "P-CATALOG-SYNC", "", "قطعات اصلی کامپیوتر", "رم کامپیوتر (Desktop RAM)",
        "TestBrand", "TestModel",
        {"فرکانس": "3200MHz", "ویژگی ذخیره‌شده": "مقدار آزمایشی"},
        "", 2, 20,
    )
    window = MainWindow(manager, active_employee=None)
    try:
        parts = window._taxonomy_draft["attributes"]["قطعات اصلی کامپیوتر"]
        part_names = {
            (item["name"], item.get("subcategory", ""))
            for item in parts
        }
        assert ("فرکانس", "رم کامپیوتر (Desktop RAM)") in part_names
        assert ("نسل رم", "رم کامپیوتر (Desktop RAM)") in part_names
        assert ("ویژگی ذخیره‌شده", "رم کامپیوتر (Desktop RAM)") in part_names

        monitor_names = {
            item["name"] for item in window._taxonomy_draft["attributes"]["مانیتور و نمایشگر"]
        }
        assert {"ابعاد صفحه نمایش", "نوع پنل", "نرخ تازه‌سازی"} <= monitor_names

        window.cb_cfg_category.setCurrentText("مانیتور و نمایشگر")
        scoped_subcategory = window._taxonomy_draft["subcategories"]["مانیتور و نمایشگر"][0]
        definitions = window._taxonomy_draft["attributes"].setdefault("مانیتور و نمایشگر", [])
        definitions.extend([
            {"name": "ویژگی عمومی آزمون", "label": "", "values": [], "subcategory": ""},
            {
                "name": "ویژگی مختص آزمون", "label": "", "values": [],
                "subcategory": scoped_subcategory,
            },
        ])
        window.cb_cfg_attribute_subcategory.setCurrentIndex(0)
        window._refresh_catalog_attribute_list()
        all_names = {
            window.lst_cfg_attributes.item(i).text().split("  ←")[0].split(" — ")[0].split("  [")[0]
            for i in range(window.lst_cfg_attributes.count())
        }
        assert "ویژگی عمومی آزمون" in all_names
        assert "ویژگی مختص آزمون" in all_names

        scope_index = window.cb_cfg_attribute_subcategory.findData(scoped_subcategory)
        assert scope_index > 0
        window.cb_cfg_attribute_subcategory.setCurrentIndex(scope_index)
        window._refresh_catalog_attribute_list()
        specific_names = {
            window.lst_cfg_attributes.item(i).text().split("  ←")[0].split(" — ")[0].split("  [")[0]
            for i in range(window.lst_cfg_attributes.count())
        }
        assert "ویژگی مختص آزمون" in specific_names
        assert "ویژگی عمومی آزمون" in specific_names  # Global definitions apply to every subcategory.

        window.cb_cfg_attribute_subcategory.setCurrentIndex(0)
        window._refresh_catalog_attribute_list()
        target_index = next(
            index for index, definition in enumerate(definitions)
            if definition["name"] == "ویژگی مختص آزمون"
        )
        target_item = next(
            window.lst_cfg_attributes.item(i)
            for i in range(window.lst_cfg_attributes.count())
            if window.lst_cfg_attributes.item(i).data(Qt.UserRole) == target_index
        )
        window.lst_cfg_attributes.setCurrentItem(target_item)
        assert window.cb_cfg_attribute_subcategory.currentData() == ""

        button_labels = {button.text() for button in window.findChildren(QPushButton)}
        # The subcategory list now exposes separate Add/Rename/Delete actions;
        # the caption helper remains callable but is not a merged action button.
        assert "افزودن/تغییرنام" not in button_labels
        assert "ذخیره عنوان" not in button_labels

        window.ed_subcategory_caption.setText("نوع دستگاه آزمایشی")
        window._add_or_rename_catalog_subcategory()
        saved_labels = json.loads(manager.get_setting("subcategory_field_labels", "{}"))
        assert saved_labels["مانیتور و نمایشگر"] == "نوع دستگاه آزمایشی"
    finally:
        window.close()
        qapp.processEvents()



def test_cold_start_first_shipment_quantity_10_edit_1_to_10_to_2_and_delete(
    tmp_path, monkeypatch, qapp
):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "cold-start-shop.db"))
    errors = []
    monkeypatch.setattr(
        main_module.QMessageBox, "critical",
        lambda _parent, title, message: errors.append((title, message)),
    )
    monkeypatch.setattr(main_module.QMessageBox, "information", lambda *_args: None)
    window = MainWindow(manager, active_employee=None)
    try:
        # Cold-start the complete UI flow: create the product with no prior
        # product or shipment rows, then register its first shipment.
        window.ed_prod_code.setText("P-COLD-START-01")
        window.cb_prod_cat.setCurrentText("قطعات")
        window.specs_widget.set_sub_category("لوازم جانبی")
        window.ed_prod_brand.setText("ColdStart")
        window.ed_prod_model.setText("FirstShipment")
        window._save_new_product()
        with manager.get_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM products WHERE code='P-COLD-START-01'"
            ).fetchone()[0] == 1
        window.refresh_all_data()
        product_index = next(
            index for index in range(window.cb_batch_prod.count())
            if (window.cb_batch_prod.itemData(index) or {}).get("code") == "P-COLD-START-01"
        )
        window.cb_batch_prod.setCurrentIndex(product_index)
        window.ed_batch_code.setText("C-COLD-START-01")
        window.ed_batch_inv.setText("PO-COLD-START-01")
        window.cb_batch_qty.setCurrentText("10")
        window.pr_batch_buy.set_value(100)
        window.pr_batch_extra.set_value(0)
        # Keep the cold-start default settlement mode (fully paid); quantity
        # changes must recalculate the aggregate paid amount without breaking
        # the first shipment insert.
        window.cb_batch_status.setCurrentText("تسویه‌شده")
        window.ed_batch_serial.setText("RAM: 16GB")

        window._save_new_batch()
        assert not errors, errors
        with manager.get_connection() as conn:
            batch = conn.execute(
                "SELECT id, initial_qty, remaining_qty, settlement_status, paid_amount, "
                "serial_numbers, initial_specs, notes "
                "FROM batches WHERE batch_code='C-COLD-START-01'"
            ).fetchone()
        assert batch is not None
        batch_id = int(batch["id"])
        assert (batch["initial_qty"], batch["remaining_qty"]) == (10, 10)
        assert batch["settlement_status"] == "تسویه‌شده"
        assert batch["paid_amount"] == 1000
        assert batch["serial_numbers"] == ""
        assert batch["initial_specs"] == "RAM: 16GB"
        assert batch["notes"] == "RAM: 16GB"

        # Exercise the UI edit handler directly with the selected shipment.
        # The numeric selector is edited as a whole value, never incremented.
        edit_button = next(
            button for button in window.findChildren(QPushButton)
            if button.text().startswith("✏️ ذخیره ویرایش محموله")
        )
        delete_button = next(
            button for button in window.findChildren(QPushButton)
            if button.text().startswith("🗑️ حذف محموله انتخابی")
        )
        window.selected_batch_id = batch_id
        window.cb_batch_qty.setCurrentText("1")
        edit_button.click()
        with manager.get_connection() as conn:
            one = conn.execute(
                "SELECT initial_qty, remaining_qty FROM batches WHERE id=?", (batch_id,)
            ).fetchone()
        assert (one["initial_qty"], one["remaining_qty"]) == (1, 1)

        window.selected_batch_id = batch_id
        window.cb_batch_qty.setCurrentText("10")
        edit_button.click()
        with manager.get_connection() as conn:
            ten = conn.execute(
                "SELECT initial_qty, remaining_qty FROM batches WHERE id=?", (batch_id,)
            ).fetchone()
        assert (ten["initial_qty"], ten["remaining_qty"]) == (10, 10)

        window.selected_batch_id = batch_id
        window.cb_batch_qty.setCurrentText("2")
        edit_button.click()
        with manager.get_connection() as conn:
            two = conn.execute(
                "SELECT initial_qty, remaining_qty FROM batches WHERE id=?", (batch_id,)
            ).fetchone()
        assert (two["initial_qty"], two["remaining_qty"]) == (2, 2)

        monkeypatch.setattr(main_module, "_ask_yes_no", lambda *_args: True)
        window.selected_batch_id = batch_id
        delete_button.click()
        with manager.get_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM batches WHERE id=?", (batch_id,)
            ).fetchone()[0] == 0
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert not errors, errors
    finally:
        window.close()
        qapp.processEvents()


def test_subcategory_settings_restore_three_independent_actions(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(database_module, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    manager = DatabaseManager(str(tmp_path / "three-buttons.db"))
    window = MainWindow(manager, active_employee=None)
    try:
        buttons = {
            button.property("catalogAction"): button
            for button in window.findChildren(QPushButton)
            if button.property("catalogAction")
        }
        add_button = buttons["addSubcategory"]
        rename_button = buttons["renameSubcategory"]
        assert add_button.text() == "افزودن"
        assert rename_button.text() == "تغییر نام"
        assert buttons["deleteSubcategory"].text() == "حذف"
        assert "افزودن/تغییرنام" not in {
            button.text() for button in window.findChildren(QPushButton)
        }

        window.cb_cfg_category.setCurrentText("مانیتور و نمایشگر")
        before = list(window._taxonomy_draft["subcategories"]["مانیتور و نمایشگر"])
        window.ed_cfg_subcategory.setText("زیرمجموعه آزمایش")
        add_button.click()
        assert "زیرمجموعه آزمایش" in window._taxonomy_draft["subcategories"]["مانیتور و نمایشگر"]
        window.lst_cfg_subcategories.setCurrentRow(
            window._taxonomy_draft["subcategories"]["مانیتور و نمایشگر"].index("زیرمجموعه آزمایش")
        )
        window.ed_cfg_subcategory.setText("زیرمجموعه تغییرنام‌یافته")
        rename_button.click()
        assert "زیرمجموعه تغییرنام‌یافته" in window._taxonomy_draft["subcategories"]["مانیتور و نمایشگر"]
        assert "زیرمجموعه آزمایش" not in window._taxonomy_draft["subcategories"]["مانیتور و نمایشگر"]
    finally:
        window.close()
        qapp.processEvents()
