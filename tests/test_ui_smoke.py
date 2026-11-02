import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCompleter,
    QSizePolicy,
    QToolButton,
    QScrollBar,
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
        assert window.tabs.tabText(9).endswith("تنظیمات")
        assert window.lbl_app_version.text() == "نسخه برنامه: 1.0.0"
        assert [window.catalog_tabs.tabText(i) for i in range(window.catalog_tabs.count())] == [
            "مدیریت کالاها", "مدیریت خدمات"
        ]
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
        assert "لپ‌تاپ عمومی / مالتی‌مدیا" in [
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
        assert window.cb_rep_preset.currentText() == "بازه انتخابی دستی"
        assert window.sp_bk_interval.minimum() == 1
        assert window.dt_batch_date.ed_day.width() >= 48
        assert window.dt_batch_date.ed_month.width() >= 48
        assert window.dt_batch_date.width() < 250
        assert isinstance(window.tabs.widget(9), SmoothScrollArea)
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
        assert window.cb_sale_prod.count() == 1
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
        assert window.cb_sale_prod.count() == 1
        assert strip_bidi_controls(window.cb_sale_prod.itemText(0)) == (
            "P-2000 | لپ‌تاپ عمومی / مالتی‌مدیا | ASUS G551"
        )
        assert window.cb_sale_batch.count() == 2

        labels = [
            strip_bidi_controls(window.cb_sale_batch.itemText(index))
            for index in range(window.cb_sale_batch.count())
        ]
        assert any("RAM: 8GB" in label for label in labels)
        assert any("RAM: 16GB" in label for label in labels)
        assert all("CPU:" not in label and "SSD:" not in label for label in labels)

        missing_spec_labels = MainWindow._batch_variant_labels([
            {"id": 1, "final_specs": "CPU: Core i7 | RAM: 8GB"},
            {"id": 2, "final_specs": "CPU: Core i7"},
        ])
        assert missing_spec_labels[2] == "RAM: ثبت نشده"

        tooltips = [
            strip_bidi_controls(window.cb_sale_batch.itemData(index, Qt.ToolTipRole))
            for index in range(window.cb_sale_batch.count())
        ]
        assert any("RAM: 8GB" in tooltip for tooltip in tooltips)
        assert any("RAM: 16GB" in tooltip for tooltip in tooltips)
        assert all("CPU: Core i7" not in tooltip and "SSD: 512GB" not in tooltip for tooltip in tooltips)
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
        active_x = [
            button for button in active_widget.findChildren(QToolButton)
            if button.text() == "×"
        ][0]
        assert not active_x.isEnabled()

        other_widget = window.lst_recent_databases.itemWidget(
            window.lst_recent_databases.item(1)
        )
        other_x = [
            button for button in other_widget.findChildren(QToolButton)
            if button.text() == "×"
        ][0]
        assert other_x.isEnabled()
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
            "name": "CPU",
            "label": "پردازنده (CPU)",
            "display_name": "مدل پردازنده",
            "values": ["Core i5", "Core i7"],
            "subcategory": "پردازنده (CPU)",
        }]},
        "colors": [],
    })
    window = MainWindow(manager, active_employee=None)
    try:
        assert "CPU" in window.specs_widget.fields
        field_widget = window.specs_widget.fields["CPU"]
        assert field_widget.toolTip() == "مشخصه سفارشی: CPU"
        field_label = window.specs_widget.form_layout.labelForField(field_widget)
        assert field_label.text() == "CPU:"
        assert window._format_specs_for_display({"CPU": "Core i7"}, "قطعات") == (
            "پردازنده (CPU): Core i7"
        )
        assert window._format_specs_for_tooltip({"CPU": "Core i7"}, "قطعات") == (
            "پردازنده (CPU): Core i7"
        )
        definition = window.catalog_config["attributes"]["قطعات"][0]
        definition["label"] = ""
        assert window._format_specs_for_display({"CPU": "Core i7"}, "قطعات") == (
            "CPU: Core i7"
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
        today = __import__("jdatetime").date.today().strftime("%Y/%m/%d")
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
        assert window.dt_war_start.get_date() == today
        assert window.dt_war_end.get_date() == today
        assert window.cb_sale_qty.currentText() == "1"
        assert not window.cb_sale_qty.isEditable()
        assert window.cb_sale_prod.currentData() is None
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
        assert "TDP" in window.specs_widget.fields
        assert "VRAM" not in window.specs_widget.fields
        assert window.specs_widget.fields["TDP"].count() == 3

        window.specs_widget.cb_sub.setCurrentText("کارت گرافیک (Graphic Card)")
        assert "VRAM" in window.specs_widget.fields
        assert "TDP" not in window.specs_widget.fields
        assert window.specs_widget.fields["VRAM"].count() == 3
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
        attribute_item = window.lst_cfg_attributes.item(0)
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
