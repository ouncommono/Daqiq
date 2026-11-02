# main.py
import os
import sys
import json
import subprocess
import time
import sqlite3
import copy
import re
from datetime import timedelta
import jdatetime

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QBoxLayout,
    QGridLayout,
    QFormLayout,
    QTabWidget,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QDialogButtonBox,
    QSizePolicy,
    QFileDialog,
    QGroupBox,
    QComboBox,
    QCheckBox,
    QSpinBox,
    QDialog,
    QLineEdit,
    QRadioButton,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QAbstractItemView,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor, QFontMetrics

from database import DatabaseManager, load_app_config, save_app_config, hash_password
from utils_and_widgets import (
    MAIN_CATEGORIES,
    DEFAULT_SUBCATEGORIES,
    DEFAULT_ATTRIBUTES,
    SmartLineEdit,
    PriceInput,
    SearchableComboBox,
    QuantitySelector,
    JalaliDateEdit,
    DynamicSpecsWidget,
    add_jalali_months,
    add_jalali_days,
    normalize_digits,
    SmoothScrollArea,
    SmoothScrollTableWidget,
    SmoothScrollListWidget,
    CollapsibleSection,
    bidi_isolate_text,
    strip_bidi_controls,
)
from exporter import (
    export_safe_inventory_excel,
    export_table_to_excel,
    get_next_excel_filename,
)

PERSIAN_WEEKDAYS = {
    0: "شنبه",
    1: "یکشنبه",
    2: "دوشنبه",
    3: "سه‌شنبه",
    4: "چهارشنبه",
    5: "پنجشنبه",
    6: "جمعه",
}


def _center_message_buttons(dialog):
    """Keep custom confirmation/action buttons centered and right-to-left."""
    dialog.setLayoutDirection(Qt.RightToLeft)
    button_box = dialog.findChild(QDialogButtonBox)
    if button_box is not None:
        button_box.setCenterButtons(True)


def _ask_yes_no(parent, title: str, message: str) -> bool:
    """Persian, centered confirmation dialog with explicit yes/no actions."""
    dialog = QMessageBox(parent)
    dialog.setWindowTitle(title)
    dialog.setText(message)
    dialog.setIcon(QMessageBox.Question)
    dialog.setLayoutDirection(Qt.RightToLeft)
    yes_button = dialog.addButton("بله", QMessageBox.YesRole)
    no_button = dialog.addButton("خیر", QMessageBox.NoRole)
    dialog.setDefaultButton(no_button)
    _center_message_buttons(dialog)
    dialog.exec()
    return dialog.clickedButton() is yes_button


def format_Signed_diff(actual_unit: int, suggested_unit: int, qty: int) -> str:
    """
    بند ۱۳: نمایش تخفیف با علامت (-) و فروش بالاتر از پیشنهادی (تشدید) با علامت (+) در یک ستون واحد
    """
    diff = (int(actual_unit) - int(suggested_unit)) * int(qty)
    if diff < 0:
        return f"-{abs(diff):,}"
    elif diff > 0:
        return f"+{diff:,}"
    return "0"


class LoginDialog(QDialog):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self.logged_employee = None
        self.require_password = bool(self.db.cfg.get("require_login_password", False))
        self.setWindowTitle("ورود با رمز عبور" if self.require_password else "انتخاب کاربر")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setFixedSize(410, 220)

        layout = QFormLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(9)
        self.cb_emp = SearchableComboBox()
        with self.db.get_connection() as conn:
            emps = conn.execute(
                "SELECT * FROM employees WHERE is_active=1 ORDER BY updated_at DESC, id DESC"
            ).fetchall()
            for employee in emps:
                self.cb_emp.addItem(
                    f"{employee['name']} ({employee['role']})", dict(employee)
                )

        self.ed_pass = QLineEdit()
        self.ed_pass.setEchoMode(QLineEdit.Password)
        self.ed_pass.setPlaceholderText("رمز عبور کارمند...")
        self.ed_pass.setClearButtonEnabled(True)

        self.lbl_login_hint = QLabel(
            "کاربر دارای رمز باید رمز خود را وارد کند؛ حساب بدون رمز می‌تواند مستقیم وارد شود."
        )
        self.lbl_login_hint.setWordWrap(True)
        self.lbl_login_hint.setStyleSheet("color: #64748b; font-size: 11px;")

        btn_login = QPushButton("ورود")
        btn_login.setStyleSheet(
            "background-color: #2563eb; color: white; padding: 8px; font-weight: bold;"
        )
        btn_login.clicked.connect(self._check_login)

        layout.addRow("انتخاب کارمند:", self.cb_emp)
        layout.addRow("رمز عبور:", self.ed_pass)
        layout.addRow(self.lbl_login_hint)
        layout.addRow(btn_login)
        if self.require_password:
            self.lbl_login_hint.setText(
                "در حالت اجباری، همه کارکنان فعال باید رمز داشته باشند. حساب بدون رمز تا زمان تعریف رمز قابل ورود نیست."
            )

    def _check_login(self):
        employee = self.cb_emp.currentData()
        if not employee:
            QMessageBox.warning(self, "انتخاب کارمند", "ابتدا یک کارمند را انتخاب کنید.")
            return
        stored_hash = employee.get("password") or ""
        typed_password = normalize_digits(self.ed_pass.text())
        if self.require_password and not stored_hash:
            QMessageBox.warning(
                self,
                "رمز عبور تعریف نشده",
                "ورود این حساب به دلیل فعال بودن اجبار رمز ممکن نیست. مدیر باید ابتدا برای این کارمند رمز تعیین کند.",
            )
            return
        if stored_hash:
            if not typed_password or (
                hash_password(typed_password) != stored_hash and typed_password != stored_hash
            ):
                QMessageBox.warning(self, "خطا", "رمز عبور واردشده صحیح نیست.")
                return
        self.logged_employee = employee
        self.accept()


def _is_valid_sqlite_database_file(path):
    """Validate both SQLite integrity and the minimum accounting schema."""
    if not path or not os.path.isfile(path):
        return False
    conn = None
    try:
        # Opening a verified existing file to inspect schema does not mutate it.
        conn = sqlite3.connect(os.path.abspath(path), timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
        result = conn.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            return False
        table_names = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        required_tables = {
            "settings", "employees", "suppliers", "products", "batches", "sales"
        }
        return required_tables.issubset(table_names)
    except (sqlite3.Error, OSError, ValueError):
        return False
    finally:
        if conn is not None:
            conn.close()


class DatabaseBootstrapDialog(QDialog):
    """First-run wizard for creating a database file or connecting an existing one."""

    def __init__(self, default_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("راه‌اندازی اولیه پایگاه داده")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(560)
        self.selected_path = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)

        title = QLabel("برای شروع، پایگاه دادهٔ فروشگاه را انتخاب کنید")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        detail = QLabel(
            "می‌توانید یک پایگاه دادهٔ جدید بسازید یا فایل پایگاه دادهٔ قبلی خود را به برنامه متصل کنید. "
            "مسیر پیشنهادی قابل ویرایش است."
        )
        detail.setWordWrap(True)
        detail.setStyleSheet("color: #64748b;")
        layout.addWidget(title)
        layout.addWidget(detail)

        self.rb_create = QRadioButton("ایجاد پایگاه دادهٔ جدید در مسیر زیر")
        self.rb_existing = QRadioButton("اتصال به پایگاه دادهٔ موجود")
        self.rb_create.setChecked(True)
        layout.addWidget(self.rb_create)
        layout.addWidget(self.rb_existing)

        path_row = QHBoxLayout()
        self.ed_path = QLineEdit(default_path)
        self.ed_path.setClearButtonEnabled(True)
        self.ed_path.setToolTip("مسیر و نام فایل پایگاه داده با پسوند .db")
        self.btn_browse = QPushButton("انتخاب مسیر…")
        self.btn_browse.clicked.connect(self._browse)
        path_row.addWidget(self.ed_path, 1)
        path_row.addWidget(self.btn_browse)
        layout.addLayout(path_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.button(QDialogButtonBox.Ok).setText("ادامه")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self):
        current = self.ed_path.text().strip()
        if self.rb_existing.isChecked():
            path, _ = QFileDialog.getOpenFileName(
                self, "انتخاب پایگاه دادهٔ موجود", current, "پایگاه داده SQLite (*.db)"
            )
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, "تعیین مسیر پایگاه دادهٔ جدید", current, "پایگاه داده SQLite (*.db)"
            )
        if path:
            self.ed_path.setText(path)

    def _validate_and_accept(self):
        raw_path = self.ed_path.text().strip().strip('"')
        if not raw_path:
            QMessageBox.warning(self, "مسیر لازم است", "مسیر فایل پایگاه داده را مشخص کنید.")
            return
        path = os.path.abspath(os.path.expanduser(raw_path))
        if not path.lower().endswith((".db", ".sqlite", ".sqlite3")):
            path += ".db"

        if self.rb_existing.isChecked():
            if not os.path.isfile(path):
                QMessageBox.warning(
                    self, "فایل پیدا نشد", "فایل پایگاه دادهٔ موجود در این مسیر پیدا نشد."
                )
                return
            if not _is_valid_sqlite_database_file(path):
                QMessageBox.critical(
                    self,
                    "پایگاه دادهٔ نامعتبر",
                    "فایل انتخاب‌شده یا سالم نیست یا ساختار پایگاه دادهٔ حسابداری را ندارد. "
                    "برای ساخت فایل جدید، گزینهٔ ایجاد پایگاه داده را انتخاب کنید.",
                )
                return
        elif os.path.exists(path) and os.path.getsize(path) > 0:
            QMessageBox.warning(
                self, "فایل از قبل وجود دارد",
                "این فایل از قبل وجود دارد. برای استفاده از آن، گزینهٔ «اتصال به پایگاه دادهٔ موجود» را انتخاب کنید."
            )
            return

        self.selected_path = path
        self.accept()


def select_startup_database_path(parent=None):
    """Choose an existing database or show the first-run setup wizard."""
    config = load_app_config()
    configured_value = str(config.get("db_path") or "").strip()
    configured_path = (
        os.path.abspath(os.path.expanduser(configured_value))
        if configured_value else ""
    )
    candidates = ([configured_path] if configured_path else [])
    candidates.extend(
        os.path.abspath(os.path.expanduser(path))
        for path in config.get("recent_databases", [])
        if path
    )

    existing_path = next(
        (
            path for path in dict.fromkeys(candidates)
            if _is_valid_sqlite_database_file(path)
        ),
        None,
    )
    if existing_path:
        config["db_path"] = existing_path
        recent = [
            os.path.abspath(path) for path in config.get("recent_databases", [])
            if path and os.path.abspath(path) != existing_path
        ]
        config["recent_databases"] = [existing_path] + recent
        save_app_config(config)
        return existing_path

    default_path = configured_path or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "shop_database.db"
    )
    if os.path.exists(default_path):
        base_dir = os.path.dirname(default_path) or "."
        stem, extension = os.path.splitext(os.path.basename(default_path))
        extension = extension or ".db"
        suffix = 1
        proposed = os.path.join(base_dir, f"{stem}_new{extension}")
        while os.path.exists(proposed):
            suffix += 1
            proposed = os.path.join(base_dir, f"{stem}_new_{suffix}{extension}")
        default_path = proposed
    dialog = DatabaseBootstrapDialog(default_path, parent)
    if dialog.exec() != QDialog.Accepted or not dialog.selected_path:
        return None

    chosen_path = os.path.abspath(dialog.selected_path)
    config["db_path"] = chosen_path
    recent = [
        os.path.abspath(path) for path in config.get("recent_databases", [])
        if path and os.path.abspath(path) != chosen_path
    ]
    config["recent_databases"] = [chosen_path] + recent
    save_app_config(config)
    return chosen_path


def _resolve_startup_employee(db, parent=None):
    """Select a user at startup whenever there are multiple accounts or any account requires a password."""
    with db.get_connection() as conn:
        employees = conn.execute(
            "SELECT * FROM employees WHERE is_active=1 ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    if not employees:
        return None, True

    require_password = bool(db.cfg.get("require_login_password", False))
    has_password_account = any(bool(employee["password"]) for employee in employees)
    must_show_dialog = require_password or len(employees) > 1 or has_password_account
    if not must_show_dialog:
        return dict(employees[0]), True

    dialog = LoginDialog(db, parent)
    if dialog.exec() != QDialog.Accepted or not dialog.logged_employee:
        return None, False
    return dialog.logged_employee, True



class MainWindow(QMainWindow):
    def __init__(self, db: DatabaseManager, active_employee=None):
        super().__init__()
        self.db = db
        self.active_employee = active_employee
        self.setWindowTitle("نرم‌افزار حسابداری، انبارداری و مدیریت فروشگاه کامپیوتر")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.resize(1180, 740)
        self.setMinimumSize(860, 540)
        self._tables_auto_fit = False
        self._table_default_widths = {}
        self._table_default_stretch = {}
        self._table_search_fields = {}
        self._dashboard_card_styles = []
        self.catalog_config = self.db.get_product_catalog_config()

        self._apply_styles()
        self._build_ui()
        self.tabs.currentChanged.connect(self._on_main_tab_changed)
        self._setup_timers()
        self.refresh_all_data()
        self._apply_employee_permissions()

    def _switch_active_employee(self):
        with self.db.get_connection() as conn:
            active_count = conn.execute(
                "SELECT COUNT(*) FROM employees WHERE is_active=1"
            ).fetchone()[0]
        if not active_count:
            QMessageBox.information(
                self, "کاربری ثبت نشده", "برای این پایگاه داده هنوز کارمند فعالی ثبت نشده است."
            )
            return
        dialog = LoginDialog(self.db, self)
        if dialog.exec() == QDialog.Accepted and dialog.logged_employee:
            self.active_employee = dialog.logged_employee
            self._update_active_user_badge()
            self._apply_employee_permissions()
            self.refresh_all_data()

    def _is_scoped_access(self):
        """Restricted roles may see only their own operational transactions."""
        if not self.active_employee:
            return False
        permission = self.active_employee.get("permissions") or ""
        return any(role in permission for role in (
            "سرپرست عملیات", "سرپرست", "فروش و خدمات", "ثبت خرید و انبارداری"
        ))

    def _is_full_admin(self):
        if not self.active_employee:
            return True
        permission = self.active_employee.get("permissions") or ""
        return "دسترسی کامل" in permission or permission == "all"

    def _update_active_user_badge(self):
        employee_name = self.active_employee["name"] if self.active_employee else "مدیر سیستم"
        employee_role = self.active_employee["role"] if self.active_employee else "دسترسی کامل"
        self.lbl_active_user.setText(f"👤 کاربر: {employee_name}")
        self.lbl_active_user.setToolTip(
            f"کاربر فعال: {employee_name}\nنقش و سطح شغلی: {employee_role}"
        )

    def _refresh_visual_layout(self):
        """Recalculate Qt layouts immediately after global style or column-size changes."""
        root = self.centralWidget()
        if root is not None:
            for widget in [root, *root.findChildren(QWidget)]:
                layout = widget.layout()
                if layout is not None:
                    layout.invalidate()
                    layout.activate()
                widget.updateGeometry()
        self.updateGeometry()
        self.update()
        QApplication.processEvents()

    def _measure_table_columns(self, table):
        """Measure every visible header and every cell, then return content-fit widths."""
        header = table.horizontalHeader()
        widths = []
        for column in range(table.columnCount()):
            header_item = table.horizontalHeaderItem(column)
            header_text = header_item.text() if header_item else ""
            header_font = header_item.font() if header_item else header.font()
            max_width = QFontMetrics(header_font).horizontalAdvance(header_text)

            for row in range(table.rowCount()):
                item = table.item(row, column)
                if item is not None:
                    metrics = QFontMetrics(item.font() if item.font().family() else table.font())
                    for line in item.text().splitlines() or [""]:
                        max_width = max(max_width, metrics.horizontalAdvance(line))
                    if not item.icon().isNull():
                        max_width += item.iconSize().width() + 6

                cell_widget = table.cellWidget(row, column)
                if cell_widget is not None:
                    max_width = max(max_width, cell_widget.sizeHint().width())

            widths.append(max(42, max_width + 28))
        return widths

    def _apply_content_fit_to_table(self, table):
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setResizeContentsPrecision(-1)
        header.setSectionResizeMode(QHeaderView.Interactive)
        for column, width in enumerate(self._measure_table_columns(table)):
            table.setColumnWidth(column, width)

    def _reapply_auto_table_widths(self):
        for table in self.findChildren(QTableWidget):
            self._apply_content_fit_to_table(table)
        self._refresh_visual_layout()

    def _toggle_theme(self):
        self.db.cfg["theme"] = "dark" if self.db.cfg.get("theme", "light") != "dark" else "light"
        save_app_config(self.db.cfg)
        self.setUpdatesEnabled(False)
        try:
            self._apply_styles()
            self.btn_theme.setText(
                "☀️ تم روشن" if self.db.cfg["theme"] == "dark" else "🌙 تم تیره"
            )
        finally:
            self.setUpdatesEnabled(True)
        self._refresh_dashboard_card_styles()
        self._refresh_visual_layout()

    def _toggle_table_autosize(self):
        enable_auto_fit = not self._tables_auto_fit
        for table in self.findChildren(QTableWidget):
            header = table.horizontalHeader()
            table_key = id(table)
            if enable_auto_fit:
                if table_key not in self._table_default_widths:
                    self._table_default_widths[table_key] = [
                        table.columnWidth(column) for column in range(table.columnCount())
                    ]
                    self._table_default_stretch[table_key] = header.stretchLastSection()
                self._apply_content_fit_to_table(table)
            else:
                header.setSectionResizeMode(QHeaderView.Interactive)
                widths = self._table_default_widths.get(table_key, [])
                for column in range(table.columnCount()):
                    width = (
                        widths[column] if column < len(widths)
                        else header.sectionSizeHint(column)
                    )
                    table.setColumnWidth(column, width)
                header.setStretchLastSection(
                    self._table_default_stretch.get(table_key, True)
                )
        self._tables_auto_fit = enable_auto_fit
        self.btn_table_width.setText(
            "↔️ بازگشت به اندازه ثابت ستون‌ها" if self._tables_auto_fit
            else "↔️ اندازه‌گذاری هوشمند ستون‌ها"
        )
        self._refresh_visual_layout()

    def _apply_employee_permissions(self):
        """Role-based tab access and data-scope setup."""
        permission = (
            self.active_employee.get("permissions")
            if self.active_employee else "دسترسی کامل"
        ) or ""
        is_full = "دسترسی کامل" in permission or permission == "all"
        is_senior = "مدیر ارشد" in permission
        is_sales = "فروش و خدمات" in permission
        is_warehouse = "ثبت خرید و انبارداری" in permission
        is_scoped = self._is_scoped_access()

        for index in range(self.tabs.count()):
            self.tabs.setTabEnabled(index, True)
        if not is_full:
            self.tabs.setTabEnabled(8, False)
        if is_sales:
            for index in (2, 6, 9):
                self.tabs.setTabEnabled(index, False)
        elif is_warehouse:
            for index in (3, 4, 9):
                self.tabs.setTabEnabled(index, False)
        elif is_scoped:
            # Operations supervisor: own transactions only, without supplier-wide and system settings.
            self.tabs.setTabEnabled(6, False)
            self.tabs.setTabEnabled(9, False)

        for button in self.findChildren(QPushButton):
            if button.objectName() == "btnDanger":
                button.setEnabled(is_full)

        if hasattr(self, "cb_rep_emp"):
            self.cb_rep_emp.setEnabled(not is_scoped)
            if is_scoped and self.active_employee:
                own_index = self.cb_rep_emp.findData(int(self.active_employee["id"]))
                if own_index >= 0:
                    self.cb_rep_emp.setCurrentIndex(own_index)
        if hasattr(self, "btn_safe_export"):
            self.btn_safe_export.setEnabled(not is_scoped)
        if hasattr(self, "btn_switch_user"):
            # تغییر کاربر بخشی از جریان دسترسی است و برای همه نقش‌ها در دسترس می‌ماند.
            self.btn_switch_user.setEnabled(1)


    def _apply_styles(self):
        dark = self.db.cfg.get("theme", "light") == "dark"
        bg = "#202938" if dark else "#f8fafc"
        panel = "#2b3648" if dark else "#ffffff"
        text = "#e5eaf2" if dark else "#0f172a"
        muted = "#aab6c8" if dark else "#64748b"
        input_bg = "#354257" if dark else "#ffffff"
        alternate = "#273346" if dark else "#f1f5f9"
        border = "#46556c" if dark else "#cbd5e1"
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                font-family: 'Segoe UI', 'Tahoma', sans-serif; font-size: 13px;
                background-color: {bg}; color: {text};
            }}
            QGroupBox {{ font-weight: bold; border: 1px solid {border}; border-radius: 8px;
                margin-top: 10px; padding-top: 12px; background-color: {panel}; }}
            QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top right;
                padding: 0 8px; color: {muted}; }}
            QLineEdit, QComboBox, QSpinBox {{ border: 1px solid {border}; border-radius: 5px;
                padding: 5px 8px; background-color: {input_bg}; min-height: 24px; }}
            QLineEdit:focus, QComboBox:focus {{ border: 1.5px solid #3b82f6; }}
            QPushButton {{ background-color: #2563eb; color: #ffffff; border: none;
                border-radius: 6px; padding: 7px 14px; font-weight: bold; }}
            QPushButton:hover {{ background-color: #1d4ed8; }}
            QPushButton#btnDanger {{ background-color: #dc2626; }}
            QPushButton#btnDanger:hover {{ background-color: #b91c1c; }}
            QPushButton#btnSuccess {{ background-color: #059669; }}
            QPushButton#btnSuccess:hover {{ background-color: #047857; }}
            QPushButton#btnSecondary {{ background-color: #475569; }}
            QTableWidget {{ background-color: {panel}; alternate-background-color: {alternate};
                gridline-color: {border}; border: 1px solid {border}; border-radius: 6px; }}
            QHeaderView::section {{ background-color: #334155; color: #ffffff; font-weight: bold;
                padding: 7px; border: none; }}
            QTabWidget::pane {{ border: 1px solid {border}; background: {bg}; }}
            QTabBar::tab {{ background: {alternate}; color: {text}; padding: 9px 14px;
                font-weight: bold; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-left: 2px; }}
            QTabBar::tab:selected {{ background: #2563eb; color: #ffffff; }}
            QCheckBox {{ font-weight: bold; color: {text}; spacing: 8px; padding: 6px 12px; }}
            QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 4px;
                border: 2px solid #64748b; background-color: {input_bg}; }}
            QCheckBox::indicator:checked {{ background-color: #2563eb; border: 2px solid #1e40af; }}
            QScrollBar:vertical {{ width: 18px; margin: 2px; background: {alternate}; border-radius: 8px; }}
            QScrollBar::handle:vertical {{ min-height: 36px; background: #718096; border-radius: 8px; }}
            QScrollBar:horizontal {{ height: 18px; margin: 2px; background: {alternate}; border-radius: 8px; }}
            QScrollBar::handle:horizontal {{ min-width: 36px; background: #718096; border-radius: 8px; }}
        """)


    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 8, 10, 8)

        # جهت نوار به‌صورت صریح LTR است: ابزارها در لبه چپ و نام فروشگاه در لبه راست.
        # این تنظیم مستقل از RTL بودن محتوای اصلی برنامه است.
        top_bar = QWidget()
        self.top_bar = top_bar
        top_bar.setLayoutDirection(Qt.LeftToRight)
        top_bar.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0f172a, stop:1 #1e3a8a); border-radius: 8px; padding: 5px;"
        )
        top_layout = QHBoxLayout(top_bar)
        self.top_layout = top_layout
        top_layout.setDirection(QBoxLayout.LeftToRight)
        top_layout.setContentsMargins(8, 5, 8, 5)
        top_layout.setSpacing(8)

        shop_name = (self.db.get_setting("shop_name", "فروشگاه من") or "فروشگاه من").strip()
        title_lbl = QLabel(f"\u2067{shop_name}\u2069")
        self.lbl_store_name = title_lbl
        title_lbl.setStyleSheet(
            "color: #ffffff; font-size: 15px; font-weight: bold; background: transparent;"
        )
        title_lbl.setToolTip(f"نام فروشگاه: {shop_name}")
        title_lbl.setLayoutDirection(Qt.RightToLeft)
        title_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title_lbl.setMinimumWidth(0)
        title_lbl.setMaximumWidth(280)
        title_lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        title_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.lbl_live_clock = QLabel()
        self.lbl_live_clock.setStyleSheet(
            "color: #38bdf8; font-size: 12px; font-weight: bold; background: rgba(255,255,255,0.08); padding: 4px 8px; border-radius: 6px;"
        )
        self.lbl_live_clock.setAlignment(Qt.AlignCenter)
        self.lbl_live_clock.setMinimumWidth(170)
        self.lbl_live_clock.setMaximumWidth(270)
        self.lbl_live_clock.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.lbl_live_clock.setToolTip("تاریخ و ساعت جاری")

        btn_safe_export = QPushButton("📤 خروجی موجودی امن")
        self.btn_safe_export = btn_safe_export
        btn_safe_export.setObjectName("btnSuccess")
        btn_safe_export.setToolTip(
            "تهیه فایل اکسل از کالاهای موجود در انبار بدون اطلاعات قیمت خرید و سود (مناسب ارسال به همکاران)"
        )
        btn_safe_export.clicked.connect(self._export_safe_inventory)
        btn_safe_export.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.lbl_active_user = QLabel()
        self.lbl_active_user.setStyleSheet(
            "color: #fde047; font-size: 12px; font-weight: bold; background: rgba(255,255,255,0.12); padding: 4px 8px; border-radius: 6px;"
        )
        self.lbl_active_user.setMinimumWidth(90)
        self.lbl_active_user.setMaximumWidth(190)
        self.lbl_active_user.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._update_active_user_badge()

        btn_switch_user = QPushButton("🔑 تغییر کاربر")
        self.btn_switch_user = btn_switch_user
        self.btn_switch_user.setToolTip("تغییر کاربر فعال؛ برای همه سطوح دسترسی")
        btn_switch_user.setStyleSheet("background-color: #475569; color: white; padding: 6px 8px;")
        btn_switch_user.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        btn_switch_user.clicked.connect(self._switch_active_employee)

        self.btn_theme = QPushButton("☀️ تم روشن" if self.db.cfg.get("theme") == "dark" else "🌙 تم تیره")
        self.btn_theme.clicked.connect(self._toggle_theme)
        self.btn_theme.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.btn_table_width = QPushButton("↔️ اندازه‌گذاری هوشمند ستون‌ها")
        self.btn_table_width.setObjectName("btnSecondary")
        self.btn_table_width.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.btn_table_width.clicked.connect(self._toggle_table_autosize)

        top_right_layout = QHBoxLayout()
        self.top_right_layout = top_right_layout
        top_right_layout.setDirection(QBoxLayout.LeftToRight)
        top_right_layout.setSpacing(6)
        # ترتیب فیزیکی از چپ به راست: تم، ابزارها، ساعت، نام کاربر، تغییر کاربر.
        top_right_layout.addWidget(self.btn_theme)
        top_right_layout.addWidget(self.btn_table_width)
        top_right_layout.addWidget(btn_safe_export)
        top_right_layout.addWidget(self.lbl_live_clock, 1)
        top_right_layout.addWidget(self.lbl_active_user)
        top_right_layout.addWidget(btn_switch_user)

        # گروه کنترل‌ها در چپ قرار می‌گیرد و نام فروشگاه در انتهای راست نوار است.
        top_layout.addLayout(top_right_layout, 0)
        top_layout.addStretch(1)
        top_layout.addWidget(title_lbl, 0)
        main_layout.addWidget(top_bar)

        # --- تب‌های برنامه با ترتیب جدید (بند ۵: تب ارتقای لپ‌تاپ بلافاصله بعد از مدیریت خدمات) ---
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self._init_tab_dashboard()
        self._init_tab_products()
        self._init_tab_batches()
        self._init_tab_sales()
        self._init_tab_services()
        self._init_tab_upgrades()  # بند ۵: بلافاصله بعد از تب مدیریت خدمات
        self._init_tab_suppliers_payments()
        self._init_tab_reports()
        self._init_tab_employees()
        self._init_tab_settings()

        self._update_clock()
        self._update_active_user_badge()
        self._apply_employee_permissions()

    def _refresh_dashboard_card_styles(self):
        dark = self.db.cfg.get("theme", "light") == "dark"
        panel = "#2b3648" if dark else "#ffffff"
        title_color = "#cbd5e1" if dark else "#64748b"
        for box, title_label, value_label, accent in getattr(
            self, "_dashboard_card_styles", []
        ):
            box.setStyleSheet(
                f"QGroupBox {{ border-right: 5px solid {accent}; "
                f"background: {panel}; border-radius: 8px; padding: 8px; }}"
            )
            title_label.setStyleSheet(
                f"color: {title_color}; background: transparent; "
                "font-size: 12px; font-weight: bold;"
            )
            value_label.setStyleSheet(
                f"color: {accent}; background: transparent; "
                "font-size: 18px; font-weight: bold;"
            )

    def _setup_timers(self):
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)

        self.backup_timer = QTimer(self)
        self.backup_timer.timeout.connect(self._run_periodic_backup)
        self._restart_backup_timer()

    def _restart_backup_timer(self):
        cfg = self.db.cfg
        if not cfg.get("auto_backup_enabled", True):
            self.backup_timer.stop()
            return

        try:
            interval_minutes = int(cfg.get("auto_backup_interval_min", 60))
        except (TypeError, ValueError):
            interval_minutes = 60
        interval_seconds = max(1, min(1440, interval_minutes)) * 60
        last_success = self.db.get_last_automatic_backup_timestamp()
        if last_success > 0:
            delay_seconds = max(1, interval_seconds - (time.time() - last_success))
        else:
            delay_seconds = interval_seconds
        self.backup_timer.setSingleShot(True)
        self.backup_timer.start(max(1000, int(delay_seconds * 1000)))

    def _run_periodic_backup(self):
        try:
            saved_path = self.db.create_backup(automatic=True)
            if hasattr(self, "lbl_last_backup"):
                warning = self.db.cfg.get("last_backup_warning", "")
                self.lbl_last_backup.setText(
                    f"آخرین پشتیبان‌گیری خودکار: {self.db.cfg.get('last_backup_time', '')}"
                    + (f"\n{warning}" if warning else "")
                )
                self.lbl_last_backup.setToolTip(
                    f"مسیر نسخه جدید: {saved_path}" + (f"\n{warning}" if warning else "")
                )
        except Exception as exc:
            if hasattr(self, "lbl_last_backup"):
                self.lbl_last_backup.setText("خطا در پشتیبان‌گیری خودکار؛ تلاش مجدد انجام می‌شود.")
                self.lbl_last_backup.setToolTip(str(exc))
            self.backup_timer.start(60 * 1000)
            return
        self._restart_backup_timer()

    def _update_clock(self):
        now = jdatetime.datetime.now()
        w_day = PERSIAN_WEEKDAYS.get(now.weekday(), "")
        date_str = now.strftime("%Y/%m/%d")
        time_str = now.strftime("%H:%M:%S")
        self.lbl_live_clock.setText(
            f"📅 {date_str}  |  ⏰ {time_str}"
        )
        self.lbl_live_clock.setToolTip(
            f"تاریخ شمسی: {w_day} {date_str}\nساعت محلی: {time_str}"
        )

    def _export_safe_inventory(self):
        default_file = get_next_excel_filename(os.path.expanduser("~"), "R")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "ذخیره گزارش موجودی (فقط کالاهای موجود و بدون اطلاعات محرمانه)",
            default_file,
            "Excel Files (*.xlsx)",
        )
        if path:
            try:
                export_safe_inventory_excel(self.db, path, (self.db.get_setting("shop_name", "فروشگاه من") or "فروشگاه من").strip())
                QMessageBox.information(
                    self,
                    "ذخیره شد",
                    f"فایل «گزارش موجودی» با موفقیت ذخیره شد:\n{path}",
                )
            except Exception as e:
                QMessageBox.critical(self, "خطا", str(e))

    def _create_table(self, headers):
        tbl = SmoothScrollTableWidget(0, len(headers))
        tbl.setHorizontalHeaderLabels(headers)
        for idx, h_text in enumerate(headers):
            item = tbl.horizontalHeaderItem(idx)
            if item:
                item.setToolTip(h_text)
        tbl.setAlternatingRowColors(True)
        tbl.setSelectionBehavior(QTableWidget.SelectRows)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.setSortingEnabled(False)
        tbl.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        tbl.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        tbl.verticalScrollBar().setSingleStep(18)
        tbl.horizontalScrollBar().setSingleStep(18)
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        tbl.horizontalHeader().setStretchLastSection(True)
        return tbl

    def _add_scrollable_tab(self, tab: QWidget, title: str):
        """Wrap each page in a scroll area so compact windows never crush form controls."""
        tab.setMinimumWidth(940)
        scroll = SmoothScrollArea()
        scroll.setWidget(tab)
        return self.tabs.addTab(scroll, title)

    def _add_table_search(self, parent_layout, table, key, placeholder):
        """Keep the existing search position while reserving stable space for action buttons."""
        search = SmartLineEdit(placeholder)
        search.setMinimumHeight(34)
        search.setMinimumWidth(180)
        search.setMaximumWidth(240)
        search.setFixedWidth(220)
        search.setToolTip("جست‌وجو در تمام ستون‌های جدول")
        search.setClearButtonEnabled(True)
        search.textChanged.connect(
            lambda query, target=table: self._filter_table_rows(target, query)
        )
        parent_layout.addWidget(search, 0)
        self._table_search_fields[table] = search
        setattr(self, f"ed_search_{key}", search)
        return search

    def _set_generated_code_placeholder(self, edit, table, column, prefix, start_num=1001):
        """Show the next code as a hint; keep the actual field empty for DB allocation."""
        edit.clear()
        edit.setPlaceholderText(
            self.db.generate_next_code(table, column, prefix, start_num)
        )

    def _format_specs_for_display(self, specs, category=""):
        definitions = self.catalog_config.get("attributes", {}).get(category or "", [])
        display_names = {
            item.get("name"): (item.get("display_name") or item.get("label") or item.get("name"))
            for item in definitions
            if isinstance(item, dict) and item.get("name")
        }
        rendered = {}
        order = []
        definitions_by_name = {
            str(item.get("name") or "").strip(): item
            for item in definitions if isinstance(item, dict) and item.get("name")
        }
        for key, value in (specs or {}).items():
            value = str(value).strip()
            if not value:
                continue
            definition = definitions_by_name.get(str(key), {})
            title = str(definition.get("label") or key).strip()
            if title.startswith("@"):
                reference = title[1:].strip()
                if not reference:
                    continue
                if reference not in rendered:
                    rendered[reference] = value
                    order.append(reference)
                else:
                    rendered[reference] = f"{rendered[reference]} {value}".strip()
                continue
            if key not in rendered:
                order.append(key)
            rendered[key] = f"{rendered.get(key, '')} {value}".strip()
        pieces = []
        for key in order:
            definition = definitions_by_name.get(str(key), {})
            title = str(definition.get("label") or key).strip()
            if title.startswith("@"):
                title = str(key)
            pieces.append(f"{title}: {rendered[key]}")
        return " | ".join(pieces)

    def _format_specs_for_tooltip(self, specs, category=""):
        definitions = self.catalog_config.get("attributes", {}).get(category or "", [])
        display_names = {
            item.get("name"): (item.get("display_name") or item.get("label") or item.get("name"))
            for item in definitions
            if isinstance(item, dict) and item.get("name")
        }
        rendered = self._format_specs_for_display(specs, category)
        return rendered.replace(" | ", "\n")

    def _filter_table_rows(self, table, query):
        query = normalize_digits(str(query or "")).strip().casefold()
        for row in range(table.rowCount()):
            if not query:
                table.setRowHidden(row, False)
                continue
            values = []
            for column in range(table.columnCount()):
                item = table.item(row, column)
                if item:
                    values.append(strip_bidi_controls(item.text()))
                    values.append(strip_bidi_controls(item.toolTip()))
            haystack = normalize_digits(" ".join(values)).casefold()
            table.setRowHidden(row, query not in haystack)

    def _on_main_tab_changed(self, index):
        if index == getattr(self, "_settings_tab_index", -1):
            # Unsaved edits are drafts only; entering Settings always reloads persisted values.
            self._load_general_settings_form()

    def _populate_table_safely(self, table: QTableWidget, rows_data: list, highlight_col=None):
        """
        بند ۱۰ و ۱۱: پر کردن امن جداول با غیرفعال کردن موقت SortingEnabled
        (رفع کامل باگ خالی افتادن سطرهای جدول در داشبورد، کارمندان و سایر تب‌ها)
        و افزودن Tooltip روی تک‌تک سلول‌ها برای خوانایی در صفحات کوچک.
        """
        table.setSortingEnabled(False)
        table.clearContents()
        table.setRowCount(len(rows_data))
        for r_idx, row_values in enumerate(rows_data):
            for c_idx, val in enumerate(row_values):
                text_val = "" if val is None else str(val)
                display_text = strip_bidi_controls(text_val)
                item = QTableWidgetItem(display_text)
                item.setToolTip(display_text)
                if highlight_col is not None and c_idx == highlight_col:
                    if text_val in ("ناموجود", "کم‌موجود", "تسویه‌نشده") or text_val.startswith("-"):
                        item.setForeground(QColor("#dc2626"))
                    elif text_val.startswith("+"):
                        item.setForeground(QColor("#059669"))
                table.setItem(r_idx, c_idx, item)
        # Input rows are already sorted by activity timestamps in SQL; keep this
        # order stable instead of allowing the primary-key column to re-sort rows.
        table.setSortingEnabled(False)
        search = self._table_search_fields.get(table)
        if search is not None:
            self._filter_table_rows(table, search.text())

    # =========================================================================
    # ۱. تب داشبورد
    # =========================================================================
    def _init_tab_dashboard(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        cards_layout = QGridLayout()
        self.lbl_dash_sales_today = self._make_stat_card(
            cards_layout, 0, 0, "فروش امروز (تومان)", "0", "#1d4ed8"
        )
        self.lbl_dash_profit_today = self._make_stat_card(
            cards_layout, 0, 1, "سود فروش امروز (تومان)", "0", "#047857"
        )
        self.lbl_dash_count_today = self._make_stat_card(
            cards_layout, 0, 2, "تعداد فروش امروز", "0", "#7c3aed"
        )
        self.lbl_dash_buy_today = self._make_stat_card(
            cards_layout, 0, 3, "خرید امروز (تومان)", "0", "#b45309"
        )
        self.lbl_dash_total_stock = self._make_stat_card(
            cards_layout, 1, 0, "کل موجودی انبار (عدد)", "0", "#0f766e"
        )
        self.lbl_dash_low_stock = self._make_stat_card(
            cards_layout, 1, 1, "کالاهای کم‌موجود", "0", "#dc2626"
        )
        self.lbl_dash_unpaid_supplier = self._make_stat_card(
            cards_layout, 1, 2, "بدهی به تأمین‌کنندگان", "0", "#be123c"
        )
        self.lbl_dash_srv_profit = self._make_stat_card(
            cards_layout, 1, 3, "سود خدمات امروز", "0", "#4338ca"
        )
        layout.addLayout(cards_layout)

        split = QHBoxLayout()
        gb_low = QGroupBox("⚠️ هشدار موجودی (کالاهای نیازمند خرید مجدد)")
        l_low = QVBoxLayout(gb_low)
        self.tbl_dash_low = self._create_table(
            ["کد کالا", "مشخصات کالا", "دسته‌بندی", "زیرمجموعه", "موجودی فعلی", "حداقل موجودی", "وضعیت"]
        )
        self._add_table_search(
            l_low, self.tbl_dash_low, "dashboard_low",
            "🔍 جست‌وجو در هشدارهای موجودی..."
        )
        l_low.addWidget(self.tbl_dash_low)

        gb_emp = QGroupBox("👥 عملکرد فروشندگان")
        l_emp = QVBoxLayout(gb_emp)
        self.tbl_dash_emp = self._create_table(
            ["نام فروشنده", "تعداد فروش", "مبلغ کل فروش (تومان)", "تخفیف داده شده", "سود حاصل از فروش"]
        )
        self._add_table_search(
            l_emp, self.tbl_dash_emp, "dashboard_employees",
            "🔍 جست‌وجو در عملکرد کارکنان..."
        )
        l_emp.addWidget(self.tbl_dash_emp)

        split.addWidget(gb_low)
        split.addWidget(gb_emp)
        layout.addLayout(split)

        self._add_scrollable_tab(tab, "📊 داشبورد")

    def _make_stat_card(self, grid, r, c, title, val, color):
        box = QGroupBox()
        box.setToolTip(title)
        dark = self.db.cfg.get("theme", "light") == "dark"
        panel = "#2b3648" if dark else "#ffffff"
        title_color = "#cbd5e1" if dark else "#64748b"
        box.setStyleSheet(
            f"QGroupBox {{ border-right: 5px solid {color}; background: {panel}; "
            "border-radius: 8px; padding: 8px; }"
        )
        v = QVBoxLayout(box)
        t = QLabel(title)
        t.setToolTip(title)
        t.setStyleSheet(
            f"color: {title_color}; background: transparent; "
            "font-size: 12px; font-weight: bold;"
        )
        lbl_val = QLabel(val)
        lbl_val.setStyleSheet(
            f"color: {color}; background: transparent; "
            "font-size: 18px; font-weight: bold;"
        )
        v.addWidget(t)
        v.addWidget(lbl_val)
        grid.addWidget(box, r, c)
        self._dashboard_card_styles.append((box, t, lbl_val, color))
        self._refresh_dashboard_card_styles()
        return lbl_val

    # =========================================================================
    # ۲. تب مدیریت کالاها (بند ۱، ۲، ۳)
    # =========================================================================
    def _init_tab_products(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.selected_product_id = None

        top_split = QHBoxLayout()
        gb_form = QGroupBox("تعریف و ویرایش کالا (بدون نیاز به نام محصول؛ شناسایی با دسته‌بندی، زیرمجموعه، برند و مدل)")
        f_layout = QFormLayout(gb_form)

        self.ed_prod_code = SmartLineEdit("P-1001")
        self.ed_prod_code.setToolTip("در صورت خالی بودن، کد بعدی به‌صورت خودکار تخصیص می‌یابد.")
        self.cb_prod_cat = SearchableComboBox()
        self.cb_prod_cat.setEditable(0)
        product_categories = self.catalog_config.get("categories") or list(MAIN_CATEGORIES)
        self.cb_prod_cat.addItems(list(dict.fromkeys(product_categories)))
        self.cb_prod_cat.setToolTip("دسته‌بندی اصلی را از فهرست انتخاب کنید.")

        self.ed_prod_brand = SmartLineEdit("مثلاً ASUS, Lenovo, HP, Logitech...")
        self.ed_prod_model = SmartLineEdit("مدل کالا (مثلاً G102, VivoBook 15...)")
        self.cb_prod_color = SearchableComboBox()
        configured_colors = self.catalog_config.get("colors") or [
            "مشکی", "سفید", "نقره‌ای", "خاکستری", "آبی",
            "قرمز", "طلایی", "سبز", "سایر",
        ]
        self.cb_prod_color.addItems([""] + configured_colors)
        self.sp_prod_reorder = QSpinBox()
        self.sp_prod_reorder.setRange(0, 1000)
        self.sp_prod_reorder.setValue(3)
        self.sp_prod_reorder.setToolTip("اگر موجودی کالا به این عدد یا کمتر برسد، در داشبورد هشدار داده می‌شود")

        self.sp_prod_profit = QSpinBox()
        self.sp_prod_profit.setRange(0, 500)
        self.sp_prod_profit.setValue(
            int(float(self.db.cfg.get("default_profit_pct", 20)))
        )
        self.sp_prod_profit.setToolTip("درصد سود پیش‌فرض برای محاسبه قیمت فروش پیشنهادی این کالا")
        self.ed_prod_desc = SmartLineEdit("توضیحات تکمیلی کالا...")

        f_layout.addRow("کد کالا (شناسه):", self.ed_prod_code)
        f_layout.addRow("دسته‌بندی اصلی *:", self.cb_prod_cat)
        f_layout.addRow("برند کالا:", self.ed_prod_brand)
        f_layout.addRow("مدل کالا:", self.ed_prod_model)
        f_layout.addRow("رنگ کالا:", self.cb_prod_color)
        f_layout.addRow("حداقل موجودی (هشدار سفارش):", self.sp_prod_reorder)
        f_layout.addRow("درصد سود پیشنهادی (%):", self.sp_prod_profit)
        f_layout.addRow("توضیحات:", self.ed_prod_desc)

        self.specs_widget = DynamicSpecsWidget()
        self.cb_prod_cat.currentTextChanged.connect(self._configure_product_specs)
        self._configure_product_specs(self.cb_prod_cat.currentText())

        top_split.addWidget(gb_form, 3)
        top_split.addWidget(self.specs_widget, 3)
        layout.addLayout(top_split)

        btn_row = QHBoxLayout()
        btn_clear = QPushButton("پاک کردن فرم")
        btn_clear.setObjectName("btnSecondary")
        btn_clear.clicked.connect(self._clear_product_form)
        btn_add = QPushButton("➕ افزودن کالای جدید")
        btn_add.clicked.connect(self._save_new_product)
        btn_edit = QPushButton("✏️ ذخیره تغییرات کالای انتخابی")
        btn_edit.setObjectName("btnSuccess")
        btn_edit.clicked.connect(self._update_selected_product)
        btn_del = QPushButton("🗑️ حذف کالای انتخابی")
        btn_del.setObjectName("btnDanger")
        btn_del.clicked.connect(self._delete_selected_product)
        self.ed_prod_search = SmartLineEdit("🔍 جست‌وجوی کد کالا، دسته‌بندی، زیرگروه (مثلاً کیبورد)، برند یا مدل...")
        self.ed_prod_search.textChanged.connect(self._refresh_products_table)

        btn_row.addWidget(btn_clear)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_edit)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        btn_row.addWidget(self.ed_prod_search)
        layout.addLayout(btn_row)

        self.tbl_products = self._create_table(
            [
                "شناسه",
                "کد کالا",
                "دسته‌بندی",
                "زیرمجموعه",
                "برند",
                "مدل",
                "مشخصات فنی",
                "موجودی کل",
                "تعداد فروش",
                "حداقل موجودی",
                "درصد سود (%)",
                "وضعیت موجودی",
                "توضیحات",
            ]
        )
        self.tbl_products.itemSelectionChanged.connect(self._on_product_row_selected)
        layout.addWidget(self.tbl_products)

        self._add_scrollable_tab(tab, "📦 مدیریت کالاها")

    def _clear_product_form(self):
        self.selected_product_id = None
        self._set_generated_code_placeholder(self.ed_prod_code, "products", "code", "P-")
        self.cb_prod_cat.setCurrentIndex(0)
        self._configure_product_specs(self.cb_prod_cat.currentText())
        self.ed_prod_brand.clear()
        self.ed_prod_model.clear()
        self.cb_prod_color.setCurrentIndex(0)
        self.sp_prod_reorder.setValue(3)
        self.sp_prod_profit.setValue(int(float(self.db.cfg.get("default_profit_pct", 20))))
        self.ed_prod_desc.clear()
        if self.specs_widget.cb_sub is not None:
            self.specs_widget.cb_sub.setCurrentIndex(0)
        for widget in self.specs_widget.fields.values():
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(0)
            elif isinstance(widget, QLineEdit):
                widget.clear()
        self.tbl_products.clearSelection()

    def _save_new_product(self):
        cat = self.cb_prod_cat.currentText().strip() or "سایر موارد"
        sub = self.specs_widget.get_sub_category()
        brand = self.ed_prod_brand.text().strip()
        model = self.ed_prod_model.text().strip()
        specs_dict = self.specs_widget.get_specs_dict()
        color_val = self.cb_prod_color.currentText().strip()
        if color_val:
            specs_dict["رنگ"] = color_val
        if not brand and not model and sub == "سایر موارد":
            QMessageBox.warning(
                self,
                "نقص اطلاعات",
                "لطفاً حداقل یکی از موارد «زیرمجموعه»، «برند» یا «مدل» را وارد کنید.",
            )
            return
        try:
            code = self.ed_prod_code.text().strip()
            duplicate = None
            if code:
                with self.db.get_connection() as conn:
                    duplicate = conn.execute(
                        "SELECT id FROM products WHERE code=?", (code,)
                    ).fetchone()
            target_id = None
            if duplicate:
                msg = QMessageBox(self)
                msg.setWindowTitle("کد کالای تکراری")
                msg.setText(f"کد {code} قبلاً ثبت شده است. اطلاعات کالای قبلی جایگزین شود؟")
                btn_replace = msg.addButton("جایگزین کردن", QMessageBox.AcceptRole)
                msg.addButton("انصراف", QMessageBox.RejectRole)
                _center_message_buttons(msg)
                msg.exec()
                if msg.clickedButton() != btn_replace:
                    return
                target_id = int(duplicate["id"])
            args = (
                code or None, "", cat, sub, brand, model, specs_dict,
                self.ed_prod_desc.text().strip(),
                self.sp_prod_reorder.value(), self.sp_prod_profit.value(),
            )
            if target_id:
                self.db.update_product(target_id, *args)
            else:
                self.db.add_product(*args)
            self.refresh_all_data()
            self._clear_product_form()
        except Exception as e:
            QMessageBox.critical(self, "خطا در ثبت کالا", str(e))

    def _on_product_row_selected(self):
        items = self.tbl_products.selectedItems()
        if not items:
            return
        row = items[0].row()
        self.selected_product_id = int(self.tbl_products.item(row, 0).text())
        self.ed_prod_code.setText(self.tbl_products.item(row, 1).text())
        cat_txt = self.tbl_products.item(row, 2).text()
        sub_txt = self.tbl_products.item(row, 3).text()
        self.cb_prod_cat.setCurrentText(cat_txt)
        self._configure_product_specs(cat_txt)
        self.specs_widget.set_sub_category(sub_txt)
        self.ed_prod_brand.setText(self.tbl_products.item(row, 4).text())
        self.ed_prod_model.setText(self.tbl_products.item(row, 5).text())
        self.sp_prod_reorder.setValue(int(self.tbl_products.item(row, 9).text()))
        self.sp_prod_profit.setValue(int(float(self.tbl_products.item(row, 10).text())))
        self.ed_prod_desc.setText(self.tbl_products.item(row, 12).text())

        with self.db.get_connection() as conn:
            r = conn.execute(
                "SELECT specs_json FROM products WHERE id=?", (self.selected_product_id,)
            ).fetchone()
            if r and r["specs_json"]:
                sp_data = json.loads(r["specs_json"])
                self.cb_prod_color.setCurrentText(sp_data.get("رنگ", ""))
                self.specs_widget.set_specs_dict(sp_data)

    def _update_selected_product(self):
        specs = self.specs_widget.get_specs_dict()
        color = self.cb_prod_color.currentText().strip()
        if color:
            specs["رنگ"] = color
        if not self.selected_product_id:
            QMessageBox.warning(self, "انتخاب کالا", "ابتدا کالای موردنظر را از جدول انتخاب کنید.")
            return
        try:
            code = self.ed_prod_code.text().strip()
            with self.db.get_connection() as conn:
                duplicate = conn.execute(
                    "SELECT id FROM products WHERE code=? AND id<>?",
                    (code, self.selected_product_id),
                ).fetchone()
            target_id = self.selected_product_id
            if duplicate:
                msg = QMessageBox(self)
                msg.setWindowTitle("کد کالای تکراری")
                msg.setText(f"کد {code} قبلاً برای کالای دیگری ثبت شده است. اطلاعات همان کالا جایگزین شود؟")
                replace_btn = msg.addButton("جایگزین کردن", QMessageBox.AcceptRole)
                msg.addButton("انصراف", QMessageBox.RejectRole)
                _center_message_buttons(msg)
                msg.exec()
                if msg.clickedButton() != replace_btn:
                    return
                target_id = int(duplicate["id"])
            self.db.update_product(
                target_id, code, "",
                self.cb_prod_cat.currentText().strip() or "سایر موارد",
                self.specs_widget.get_sub_category(),
                self.ed_prod_brand.text().strip(), self.ed_prod_model.text().strip(),
                specs, self.ed_prod_desc.text().strip(),
                self.sp_prod_reorder.value(), self.sp_prod_profit.value(),
            )
            self.selected_product_id = target_id
            self.refresh_all_data()
            QMessageBox.information(self, "ذخیره شد", "اطلاعات کالا با موفقیت اصلاح شد.")
        except Exception as exc:
            QMessageBox.critical(self, "خطا در ویرایش کالا", str(exc))


    def _delete_selected_product(self):
        if not self.selected_product_id:
            return
        if (
            _ask_yes_no(self, "تأیید حذف", "آیا از حذف این کالا اطمینان دارید؟")
            is True
        ):
            try:
                self.db.delete_product(self.selected_product_id)
                self.refresh_all_data()
                self._clear_product_form()
            except Exception as e:
                QMessageBox.critical(self, "خطا در حذف", str(e))

    # =========================================================================
    # ۳. تب ثبت خرید و محموله‌ها (شامل انتخاب وضعیت تسویه - بند ۱۲)
    # =========================================================================
    def _init_tab_batches(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.selected_batch_id = None

        gb = QGroupBox("ثبت خرید کالا از تأمین‌کننده (ایجاد محموله جدید)")
        grid = QGridLayout(gb)
        grid.setContentsMargins(12, 16, 12, 10)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(7)
        for column in (1, 3, 5):
            grid.setColumnStretch(column, 1)
        for column in (0, 2, 4):
            grid.setColumnStretch(column, 0)

        self.ed_batch_code = SmartLineEdit("C-1001")
        self.ed_batch_code.setToolTip("در صورت خالی بودن، کد محموله بعدی خودکار تخصیص می‌یابد.")
        self.cb_batch_prod = SearchableComboBox()
        self.cb_batch_prod.setToolTip("نام دسته‌بندی، زیرگروه (مثلاً کیبورد)، برند، مدل یا کد کالا را تایپ کنید")
        self.cb_batch_prod.currentIndexChanged.connect(self._on_batch_prod_changed)
        self.cb_batch_supplier = SearchableComboBox()
        self.cb_batch_buyer = SearchableComboBox()
        self.ed_batch_inv = SmartLineEdit("شماره فاکتور خرید")
        self.dt_batch_date = JalaliDateEdit(default_today=True)
        self.cb_batch_qty = QuantitySelector(500)
        self.pr_batch_buy = PriceInput(self.db)
        self.pr_batch_extra = PriceInput(self.db)
        self.pr_batch_suggest = PriceInput(self.db)
        self.pr_batch_paid = PriceInput(self.db)

        # بند ۱۲: گزینه انتخاب وضعیت تسویه
        self.cb_batch_status = QComboBox()
        self.cb_batch_status.addItems(["تسویه‌شده", "تسویه‌نشده", "تسویه جزئی"])
        self.cb_batch_status.currentTextChanged.connect(self._on_batch_status_changed)

        self.ed_batch_serial = SmartLineEdit("مشخصات فنی یا توضیحات خرید...")

        self.pr_batch_buy.valueChanged.connect(self._recalc_batch_suggested)
        self.pr_batch_extra.valueChanged.connect(self._recalc_batch_suggested)
        self.cb_batch_qty.qtyChanged.connect(self._recalc_batch_suggested)

        grid.addWidget(QLabel("کد محموله:"), 0, 0)
        grid.addWidget(self.ed_batch_code, 0, 1)
        grid.addWidget(QLabel("انتخاب کالا *:"), 0, 2)
        grid.addWidget(self.cb_batch_prod, 0, 3)
        grid.addWidget(QLabel("تأمین‌کننده:"), 0, 4)
        grid.addWidget(self.cb_batch_supplier, 0, 5)

        grid.addWidget(QLabel("مسئول خرید:"), 1, 0)
        grid.addWidget(self.cb_batch_buyer, 1, 1)
        grid.addWidget(QLabel("شماره فاکتور:"), 1, 2)
        grid.addWidget(self.ed_batch_inv, 1, 3)
        grid.addWidget(QLabel("تاریخ خرید:"), 1, 4)
        grid.addWidget(self.dt_batch_date, 1, 5)

        grid.addWidget(QLabel("تعداد خرید *:"), 2, 0)
        grid.addWidget(self.cb_batch_qty, 2, 1)
        grid.addWidget(QLabel("قیمت خرید واحد (تومان):"), 2, 2)
        grid.addWidget(self.pr_batch_buy, 2, 3)
        grid.addWidget(QLabel("هزینه جانبی کل (تومان):"), 2, 4)
        grid.addWidget(self.pr_batch_extra, 2, 5)

        grid.addWidget(QLabel("قیمت فروش پیشنهادی:"), 3, 0)
        grid.addWidget(self.pr_batch_suggest, 3, 1)
        grid.addWidget(QLabel("وضعیت تسویه:"), 3, 2)
        grid.addWidget(self.cb_batch_status, 3, 3)
        grid.addWidget(QLabel("مبلغ پرداخت‌شده:"), 3, 4)
        grid.addWidget(self.pr_batch_paid, 3, 5)

        grid.addWidget(QLabel("مشخصات فنی / توضیحات:"), 4, 0)
        grid.addWidget(self.ed_batch_serial, 4, 1, 1, 5)

        layout.addWidget(gb)

        btn_row = QHBoxLayout()
        btn_clear = QPushButton("پاک کردن فرم")
        btn_clear.setObjectName("btnSecondary")
        btn_clear.clicked.connect(self._clear_batch_form)
        btn_add = QPushButton("➕ ثبت خرید (محموله جدید)")
        btn_add.clicked.connect(self._save_new_batch)
        btn_edit = QPushButton("✏️ ذخیره ویرایش محموله انتخابی")
        btn_edit.setObjectName("btnSuccess")
        btn_edit.clicked.connect(self._update_selected_batch)
        btn_del = QPushButton("🗑️ حذف محموله انتخابی")
        btn_del.setObjectName("btnDanger")
        btn_del.clicked.connect(self._delete_selected_batch)
        btn_row.addWidget(btn_clear)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_edit)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.tbl_batches = self._create_table(
            [
                "شناسه",
                "کد محموله",
                "کد کالا",
                "مشخصات کالا",
                "تأمین‌کننده",
                "مسئول خرید",
                "شماره فاکتور",
                "تاریخ خرید",
                "تعداد خرید",
                "تعداد فروش",
                "موجودی فعلی",
                "قیمت خرید واحد",
                "هزینه جانبی کل",
                "هزینه ارتقا واحد",
                "بهای تمام‌شده واحد",
                "قیمت فروش پیشنهادی",
                "درصد سود (%)",
                "وضعیت تسویه",
                "پرداخت‌شده",
                "مانده بدهی",
                "مشخصات فنی / توضیحات",
                "بهای کل محموله (تومان)",
            ]
        )
        self.tbl_batches.itemSelectionChanged.connect(self._on_batch_row_selected)
        self._add_table_search(btn_row, self.tbl_batches, "batches", "🔍 جست‌وجو در خریدها و محموله‌ها...")
        layout.addWidget(self.tbl_batches)

        self._add_scrollable_tab(tab, "🚚 ثبت خرید و محموله‌ها")

    def _on_batch_prod_changed(self):
        prod = self.cb_batch_prod.currentData()
        if prod:
            specs = json.loads(prod.get("specs_json") or "{}")
            specs_str = self._format_specs_for_display(specs, prod.get("category"))
            desc = (prod.get("description") or "").strip()
            combined = f"{specs_str} - {desc}".strip(" -") if desc else specs_str
            self.ed_batch_serial.setText(combined)
        self._recalc_batch_suggested()

    def _clear_batch_form(self):
        self.selected_batch_id = None
        self._set_generated_code_placeholder(self.ed_batch_code, "batches", "batch_code", "C-")
        self.cb_batch_prod.setCurrentIndex(-1)
        self.cb_batch_supplier.setCurrentIndex(-1)
        self.cb_batch_buyer.setCurrentIndex(0)
        self.ed_batch_inv.clear()
        self.dt_batch_date.set_date(jdatetime.date.today().strftime("%Y/%m/%d"))
        self.cb_batch_qty.setCurrentText("1")
        self.pr_batch_buy.set_value(0)
        self.pr_batch_extra.set_value(0)
        self.pr_batch_suggest.set_value(0)
        self.pr_batch_paid.set_value(0)
        self.cb_batch_status.setCurrentIndex(0)
        self.ed_batch_serial.clear()
        self.tbl_batches.clearSelection()

    def _on_batch_status_changed(self, st):
        tot = (self.pr_batch_buy.get_value() * self.cb_batch_qty.get_qty()) + self.pr_batch_extra.get_value()
        if st.startswith("تسویه‌شده"):
            self.pr_batch_paid.set_value(tot)
        elif st.startswith("تسویه‌نشده"):
            self.pr_batch_paid.set_value(0)

    def _recalc_batch_suggested(self):
        buy_u = self.pr_batch_buy.get_value()
        extra_t = self.pr_batch_extra.get_value()
        qty = self.cb_batch_qty.get_qty()
        cost_u = buy_u + (round(extra_t / qty) if qty > 0 else 0)
        prod_data = self.cb_batch_prod.currentData()
        pct = (
            float(prod_data["default_profit_pct"])
            if prod_data
            else float(self.db.cfg.get("default_profit_pct", 20))
        )
        suggested = round(cost_u * (1 + (pct / 100.0)))
        self.pr_batch_suggest.set_value(suggested)
        st = self.cb_batch_status.currentText()
        if st.startswith("تسویه‌شده"):
            self.pr_batch_paid.set_value((buy_u * qty) + extra_t)
        elif st.startswith("تسویه‌نشده"):
            self.pr_batch_paid.set_value(0)

    def _save_new_batch(self):
        prod = self.cb_batch_prod.currentData()
        if not prod:
            QMessageBox.warning(self, "خطا", "لطفاً یک کالا انتخاب کنید.")
            return
        try:
            # تعریف sup_id: اگر تأمین‌کننده جدید تایپ شده باشد خودکار ساخته می‌شود، وگرنه از لیست انتخاب می‌شود
            sup_id = self.db.get_or_create_supplier(
                self.cb_batch_supplier.currentText()
            )
            if not sup_id:
                sup_id = self.cb_batch_supplier.currentData()

            custom_specs_or_notes = self.ed_batch_serial.text().strip()
            code = self.ed_batch_code.text().strip()
            batch_values = (
                sup_id, self.cb_batch_buyer.currentData(), self.ed_batch_inv.text().strip(),
                self.dt_batch_date.get_date(), self.cb_batch_qty.get_qty(),
                self.pr_batch_buy.get_value(), self.pr_batch_extra.get_value(),
                self.pr_batch_suggest.get_value(), self.pr_batch_paid.get_value(),
                "", custom_specs_or_notes, self.cb_batch_status.currentText(),
            )
            duplicate = None
            if code:
                with self.db.get_connection() as conn:
                    duplicate = conn.execute(
                        "SELECT id FROM batches WHERE batch_code=?", (code,)
                    ).fetchone()
            if duplicate:
                msg = QMessageBox(self)
                msg.setWindowTitle("کد محموله تکراری")
                msg.setText(f"کد {code} قبلاً ثبت شده است. اطلاعات محموله قبلی جایگزین شود؟")
                btn_replace = msg.addButton("جایگزین کردن", QMessageBox.AcceptRole)
                msg.addButton("انصراف", QMessageBox.RejectRole)
                _center_message_buttons(msg)
                msg.exec()
                if msg.clickedButton() != btn_replace:
                    return
                self.db.update_batch(
                    int(duplicate["id"]), *batch_values,
                    product_id=prod["id"], initial_specs=custom_specs_or_notes,
                    batch_code=code,
                )
            else:
                self.db.add_batch(
                    code or None, prod["id"], *batch_values[:10],
                    custom_specs_or_notes, batch_values[10], batch_values[11],
                )
            self.refresh_all_data()
            self._clear_batch_form()
        except Exception as e:
            QMessageBox.critical(self, "خطا در ثبت خرید", str(e))

    def _on_batch_row_selected(self):
        items = self.tbl_batches.selectedItems()
        if not items:
            return
        r = items[0].row()
        self.selected_batch_id = int(self.tbl_batches.item(r, 0).text())
        self.ed_batch_code.setText(self.tbl_batches.item(r, 1).text())
        self.ed_batch_inv.setText(self.tbl_batches.item(r, 6).text())
        self.dt_batch_date.set_date(self.tbl_batches.item(r, 7).text())
        self.cb_batch_qty.setCurrentText(self.tbl_batches.item(r, 8).text())
        self.pr_batch_buy.set_value(
            int(self.tbl_batches.item(r, 11).text().replace(",", ""))
        )
        self.pr_batch_extra.set_value(
            int(self.tbl_batches.item(r, 12).text().replace(",", ""))
        )
        self.pr_batch_suggest.set_value(
            int(self.tbl_batches.item(r, 15).text().replace(",", ""))
        )
        self.cb_batch_status.setCurrentText(self.tbl_batches.item(r, 17).text())
        self.pr_batch_paid.set_value(
            int(self.tbl_batches.item(r, 18).text().replace(",", ""))
        )
        self.ed_batch_serial.setText(self.tbl_batches.item(r, 20).text())

    def _update_selected_batch(self):
        if not self.selected_batch_id:
            return
        try:
            sup_id = self.db.get_or_create_supplier(
                self.cb_batch_supplier.currentText()
            )
            if not sup_id:
                sup_id = self.cb_batch_supplier.currentData()

            custom_specs_or_notes = self.ed_batch_serial.text().strip()
            self.db.update_batch(
                self.selected_batch_id,
                sup_id,
                self.cb_batch_buyer.currentData(),
                self.ed_batch_inv.text().strip(),
                self.dt_batch_date.get_date(),
                self.cb_batch_qty.get_qty(),
                self.pr_batch_buy.get_value(),
                self.pr_batch_extra.get_value(),
                self.pr_batch_suggest.get_value(),
                self.pr_batch_paid.get_value(),
                custom_specs_or_notes,
                custom_specs_or_notes,
                self.cb_batch_status.currentText(),
            )
            self.refresh_all_data()
            QMessageBox.information(
                self, "ذخیره شد", "محموله خرید با موفقیت اصلاح شد."
            )
        except Exception as e:
            QMessageBox.critical(self, "خطا", str(e))

    def _delete_selected_batch(self):
        if not self.selected_batch_id:
            return
        if (
            _ask_yes_no(
                self, "تأیید حذف", "آیا از حذف این محموله خرید اطمینان دارید؟"
            )
            is True
        ):
            try:
                self.db.delete_batch(self.selected_batch_id)
                self.refresh_all_data()
            except Exception as e:
                QMessageBox.critical(self, "خطا", str(e))

    # =========================================================================
    # ۴. تب ثبت فروش (شامل جست‌وجوی زیرگروه، وضعیت تسویه و تک‌ستونی شدن تخفیف/تشدید)
    # =========================================================================
    def _init_tab_sales(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.selected_sale_id = None

        gb = QGroupBox("ثبت فروش کالا (جست‌وجوی سریع بر اساس دسته‌بندی، زیرگروه، برند، مدل یا کد کالا)")
        grid = QGridLayout(gb)
        grid.setContentsMargins(12, 16, 12, 10)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(7)
        for column in (1, 3, 5):
            grid.setColumnStretch(column, 1)
        for column in (0, 2, 4):
            grid.setColumnStretch(column, 0)

        self.ed_sale_inv = SmartLineEdit("")
        self.ed_sale_inv.setToolTip("در صورت خالی بودن، شماره فاکتور بعدی خودکار تخصیص می‌یابد.")
        self.cb_sale_prod = SearchableComboBox()
        self.cb_sale_prod.setToolTip(
            "می‌توانید نام زیرگروه (مثلاً کیبورد، ماوس، مانیتور)، برند، مدل یا کد کالا را تایپ کنید"
        )
        self.cb_sale_prod.currentIndexChanged.connect(self._on_sale_prod_changed)
        self.cb_sale_batch = SearchableComboBox()
        self.cb_sale_batch.currentIndexChanged.connect(self._on_sale_batch_changed)
        self.cb_sale_seller = SearchableComboBox()
        self.ed_sale_customer = SmartLineEdit("نام مشتری (اختیاری)")
        self.ed_sale_specs = SmartLineEdit("مشخصات دقیق کالای فروخته‌شده؛ قابل ویرایش...")
        self.ed_sale_specs.setLayoutDirection(Qt.LeftToRight)
        self.ed_sale_specs.setToolTip("این مشخصات در زمان فروش ثبت و در گزارش‌های آینده حفظ می‌شود.")
        self.cb_sale_qty = QuantitySelector(100)
        self.cb_sale_qty.setEditable(0)
        self.cb_sale_qty.qtyChanged.connect(self._recalc_sale_live)

        self.pr_sale_suggest = PriceInput(self.db)
        self.pr_sale_suggest.setReadOnly(True)
        self.pr_sale_suggest.setStyleSheet(
            "background-color: #e2e8f0; color: #475569; font-weight: bold;"
        )
        self.pr_sale_suggest.setToolTip(
            "قیمت پیشنهادی از بخش ثبت خرید و محموله‌ها دریافت می‌شود و در فاکتور فروش قابل تغییر نیست."
        )
        self.pr_sale_actual = PriceInput(self.db)
        self.pr_sale_paid = PriceInput(self.db)

        # بند ۱۲: کنترل وضعیت تسویه فاکتور فروش
        self.cb_sale_status = QComboBox()
        self.cb_sale_status.addItems(["تسویه‌شده", "تسویه‌نشده", "تسویه جزئی"])
        self.cb_sale_status.currentTextChanged.connect(self._on_sale_status_changed)

        self.pr_sale_actual.valueChanged.connect(self._recalc_sale_live)

        self.lbl_sale_summary = QLabel("تخفیف/تشدید: 0 تومان | سود فروش: 0 تومان")
        self.lbl_sale_summary.setStyleSheet(
            "font-weight: bold; color: #047857; background: #ecfdf5; padding: 6px; border-radius: 5px;"
        )

        self.ed_war_company = SmartLineEdit("شرکت گارانتی‌کننده")
        self.dt_war_start = JalaliDateEdit(default_today=True)
        self.cb_war_months = QComboBox()
        warranty_options = [
            ("بدون گارانتی", 0), ("۲ روز", 2), ("۱ هفته", 7), ("۲ هفته", 14),
            ("۱ ماه", 30), ("۲ ماه", 60), ("۳ ماه", 90), ("۶ ماه", 180),
            ("۱ سال", 365), ("۱۸ ماه", 540), ("۲ سال", 730), ("۳ سال", 1095),
        ]
        for label, days in warranty_options:
            self.cb_war_months.addItem(label, days)
        self.dt_war_end = JalaliDateEdit(default_today=True)
        self.ed_sale_serial = SmartLineEdit("شماره سریال دستگاه")

        self.dt_war_start.dateChanged.connect(self._recalc_warranty_end)
        self.cb_war_months.currentIndexChanged.connect(self._recalc_warranty_end)

        grid.addWidget(QLabel("شماره فاکتور:"), 0, 0)
        grid.addWidget(self.ed_sale_inv, 0, 1)
        grid.addWidget(QLabel("انتخاب کالا *:"), 0, 2)
        grid.addWidget(self.cb_sale_prod, 0, 3)
        grid.addWidget(QLabel("محموله موجود *:"), 0, 4)
        grid.addWidget(self.cb_sale_batch, 0, 5)

        grid.addWidget(QLabel("فروشنده *:"), 1, 0)
        grid.addWidget(self.cb_sale_seller, 1, 1)
        grid.addWidget(QLabel("تعداد فروش *:"), 1, 2)
        grid.addWidget(self.cb_sale_qty, 1, 3)
        grid.addWidget(QLabel("قیمت پیشنهادی واحد:"), 1, 4)
        grid.addWidget(self.pr_sale_suggest, 1, 5)

        grid.addWidget(QLabel("قیمت فروش واحد:"), 2, 0)
        grid.addWidget(self.pr_sale_actual, 2, 1)
        grid.addWidget(QLabel("وضعیت تسویه:"), 2, 2)
        grid.addWidget(self.cb_sale_status, 2, 3)
        grid.addWidget(QLabel("مبلغ دریافتی:"), 2, 4)
        grid.addWidget(self.pr_sale_paid, 2, 5)

        grid.addWidget(QLabel("نام مشتری:"), 3, 0)
        grid.addWidget(self.ed_sale_customer, 3, 1)
        grid.addWidget(QLabel("شرکت گارانتی:"), 3, 2)
        grid.addWidget(self.ed_war_company, 3, 3)
        grid.addWidget(QLabel("شروع گارانتی:"), 3, 4)
        grid.addWidget(self.dt_war_start, 3, 5)

        grid.addWidget(QLabel("مدت گارانتی:"), 4, 0)
        grid.addWidget(self.cb_war_months, 4, 1)
        grid.addWidget(QLabel("انقضای گارانتی:"), 4, 2)
        grid.addWidget(self.dt_war_end, 4, 3)
        grid.addWidget(QLabel("سریال کالا:"), 4, 4)
        grid.addWidget(self.ed_sale_serial, 4, 5)

        grid.addWidget(QLabel("مشخصات فنی کالای فروخته‌شده:"), 5, 0)
        grid.addWidget(self.ed_sale_specs, 5, 1, 1, 5)
        grid.addWidget(self.lbl_sale_summary, 6, 0, 1, 6)

        layout.addWidget(gb)

        btn_row = QHBoxLayout()
        btn_clear = QPushButton("پاک کردن فرم")
        btn_clear.setObjectName("btnSecondary")
        btn_clear.clicked.connect(self._clear_sale_form)
        btn_add = QPushButton("✅ ثبت فروش")
        btn_add.clicked.connect(self._save_new_sale)
        btn_edit = QPushButton("✏️ ذخیره ویرایش فروش انتخابی")
        btn_edit.setObjectName("btnSuccess")
        btn_edit.clicked.connect(self._update_selected_sale)
        btn_del = QPushButton("🗑️ حذف فروش (برگشت کالا به انبار)")
        btn_del.setObjectName("btnDanger")
        btn_del.clicked.connect(self._delete_selected_sale)
        btn_row.addWidget(btn_clear)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_edit)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # بند ۱۳: ادغام تخفیف و تشدید در یک ستون با علامت - و +
        self.tbl_sales = self._create_table(
            [
                "شناسه",
                "شماره فاکتور",
                "تاریخ و ساعت فروش",
                "کد کالا",
                "مشخصات کالا",
                "کد محموله",
                "فروشنده",
                "مشتری",
                "تعداد",
                "قیمت پیشنهادی واحد",
                "قیمت فروش واحد",
                "تخفیف (-) / تشدید (+)",
                "بهای تمام‌شده واحد",
                "سود هر واحد",
                "سود کل",
                "مبلغ کل فاکتور",
                "مبلغ دریافتی",
                "وضعیت تسویه",
                "گارانتی و انقضا",
                "شماره سریال",
                "مشخصات فنی فروخته‌شده",
            ]
        )
        self.tbl_sales.itemSelectionChanged.connect(self._on_sale_row_selected)
        self._add_table_search(btn_row, self.tbl_sales, "sales", "🔍 جست‌وجو در فاکتورها و فروش‌ها...")
        layout.addWidget(self.tbl_sales)

        self._add_scrollable_tab(tab, "🛒 ثبت فروش")

    @staticmethod
    def _parse_batch_specifications(raw_text):
        """Parse key/value technical specifications for comparing batch variants."""
        parsed = {}
        plain_tokens = []
        for segment in re.split(r"[|؛;\n]+", str(raw_text or "")):
            segment = segment.strip(" ,،-")
            if not segment:
                continue
            separator = ":" if ":" in segment else ("=" if "=" in segment else None)
            if separator:
                key, value = segment.split(separator, 1)
                key, value = key.strip(), value.strip()
                if key and value:
                    parsed[key] = value
                    continue
            plain_tokens.extend(
                token.strip() for token in re.split(r"[,،]+", segment) if token.strip()
            )
        return parsed, plain_tokens

    @classmethod
    def _batch_variant_labels(cls, batches):
        """Return only the technical details that distinguish each batch of one product."""
        parsed_rows = []
        token_rows = []
        for batch in batches:
            raw = batch.get("final_specs") or batch.get("initial_specs") or ""
            parsed, tokens = cls._parse_batch_specifications(raw)
            parsed_rows.append(parsed)
            token_rows.append(tokens)

        all_keys = list(dict.fromkeys(
            key for specification in parsed_rows for key in specification
        ))
        varying_keys = [
            key for key in all_keys
            if len({specification.get(key) for specification in parsed_rows}) > 1
        ]

        labels = {}
        for index, batch in enumerate(batches):
            pieces = []
            current = parsed_rows[index]
            for key in varying_keys:
                value = current.get(key) or "ثبت نشده"
                pieces.append(f"{key}: {value}")

            if not varying_keys:
                shared_tokens = (
                    set.intersection(*(set(tokens) for tokens in token_rows))
                    if token_rows and all(token_rows) else set()
                )
                unique_tokens = list(dict.fromkeys(
                    token for token in token_rows[index] if token not in shared_tokens
                ))
                pieces.extend(unique_tokens)

            labels[int(batch["id"])] = "، ".join(pieces) if pieces else "بدون تفاوت ثبت‌شده"
        return labels

    @staticmethod
    def _format_product_picker_label(product, *, include_specs=False):
        category = str(product.get("category") or "سایر موارد").strip()
        subcategory = str(product.get("sub_category") or "").strip()
        brand_model = " ".join(
            part for part in (
                str(product.get("brand") or "").strip(),
                str(product.get("model") or "").strip(),
            ) if part
        )
        main_title = subcategory if subcategory and subcategory not in ("عمومی", "سایر موارد") else category
        parts = [str(product.get("code") or "").strip(), main_title]
        if brand_model:
            parts.append(brand_model)
        if include_specs:
            try:
                specs = json.loads(product.get("specs_json") or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                specs = {}
            if isinstance(specs, dict):
                short_specs = "، ".join(
                    str(value).strip() for value in specs.values() if str(value).strip()
                )
                if short_specs:
                    parts.append(short_specs)
        return " | ".join(part for part in parts if part)

    def _on_sale_prod_changed(self):
        """Load batches and display only the technical differences between variants."""
        product = self.cb_sale_prod.currentData()
        self.cb_sale_batch.clear()
        if not product:
            return

        product_data = dict(product)
        try:
            product_specs = json.loads(product_data.get("specs_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            product_specs = {}
        if not isinstance(product_specs, dict):
            product_specs = {}

        with self.db.get_connection() as conn:
            batch_rows = conn.execute(
                """
                SELECT * FROM batches
                WHERE product_id=? AND remaining_qty > 0
                ORDER BY updated_at DESC, id DESC
                """,
                (product_data["id"],),
            ).fetchall()

        batches = [dict(row) for row in batch_rows]
        variant_labels = self._batch_variant_labels(batches)
        searchable_batch_fields = (
            "batch_code", "initial_specs", "final_specs", "serial_numbers",
            "notes", "supplier_name_snapshot", "invoice_number", "purchase_date",
        )
        product_search_text = " ".join(
            [*(str(value) for value in product_specs.values()),
             str(product_data.get("description") or "")]
        )

        for batch in batches:
            variant = variant_labels.get(int(batch["id"]), "")
            visible_parts = [
                str(batch["batch_code"]),
                f"موجودی: {int(batch['remaining_qty'])}",
            ]
            if variant and variant != "بدون تفاوت ثبت‌شده":
                visible_parts.append(f"تفاوت: {variant}")
            else:
                visible_parts.append(
                    f"قیمت پیشنهادی: {int(batch['suggested_sell_price']):,} تومان"
                )
            label = " | ".join(visible_parts)

            search_text = " ".join(
                str(batch.get(key) or "") for key in searchable_batch_fields
            )
            search_text = f"{search_text} {product_search_text}".strip()
            if variant and variant != "بدون تفاوت ثبت‌شده":
                variant_text = variant.replace("، ", "\n")
                detail_text = f"تفاوت مشخصات نهایی:\n{variant_text}"
            else:
                detail_text = (
                    f"قیمت پیشنهادی: {int(batch['suggested_sell_price']):,} تومان"
                )
            full_tooltip = (
                f"کد محموله: {batch['batch_code']}\n"
                f"موجودی: {batch['remaining_qty']}\n"
                f"{detail_text}"
            )
            index = self.cb_sale_batch.count()
            self.cb_sale_batch.addItem(bidi_isolate_text(label), batch)
            self.cb_sale_batch.setItemSearchText(index, search_text)
            self.cb_sale_batch.setItemData(
                index, bidi_isolate_text(full_tooltip), Qt.ToolTipRole
            )

    def _on_sale_batch_changed(self):
        b = self.cb_sale_batch.currentData()
        if not b:
            self.cb_sale_qty.set_max_qty(1)
            self.pr_sale_suggest.set_value(0)
            self.pr_sale_actual.set_value(0)
            self.pr_sale_paid.set_value(0)
            self.ed_sale_specs.clear()
            self._recalc_sale_live()
            return
        self.cb_sale_qty.set_max_qty(b["remaining_qty"])
        self.ed_sale_specs.setText(
            str(b.get("final_specs") or b.get("initial_specs") or "")
        )
        sug = int(b["suggested_sell_price"])
        self.pr_sale_suggest.set_value(sug)
        self.pr_sale_actual.set_value(sug)
        self._recalc_sale_live()

    def _clear_sale_form(self):
        self.selected_sale_id = None
        self._set_generated_code_placeholder(self.ed_sale_inv, "sales", "invoice_number", "INV-")
        self.cb_sale_prod.setCurrentIndex(-1)
        self.cb_sale_seller.setCurrentIndex(-1)
        self.ed_sale_customer.clear()
        self.ed_sale_specs.clear()
        self.pr_sale_actual.set_value(0)
        self.pr_sale_paid.set_value(0)
        self.cb_sale_status.setCurrentIndex(0)
        self.ed_war_company.clear()
        self.cb_war_months.setCurrentIndex(0)
        today = jdatetime.date.today().strftime("%Y/%m/%d")
        self.dt_war_start.set_date(today)
        self.dt_war_end.set_date(today)
        self.ed_sale_serial.clear()
        self.tbl_sales.clearSelection()
        self.cb_sale_qty.setCurrentText("1")
        self._on_sale_batch_changed()
        self.pr_sale_actual.set_value(0)
        self.pr_sale_paid.set_value(0)
        self.ed_sale_specs.clear()
        self._recalc_sale_live()

    def _on_sale_status_changed(self, st):
        tot = self.pr_sale_actual.get_value() * self.cb_sale_qty.get_qty()
        if st.startswith("تسویه‌شده"):
            self.pr_sale_paid.set_value(tot)
        elif st.startswith("تسویه‌نشده"):
            self.pr_sale_paid.set_value(0)

    def _recalc_sale_live(self):
        b = self.cb_sale_batch.currentData()
        cost_u = int(b["unit_cost_price"]) if b else 0
        sug_u = self.pr_sale_suggest.get_value()
        act_u = self.pr_sale_actual.get_value()
        qty = self.cb_sale_qty.get_qty()

        total_bill = act_u * qty
        if self.cb_sale_status.currentText() == "تسویه‌شده":
            self.pr_sale_paid.set_value(total_bill)
        elif self.cb_sale_status.currentText() == "تسویه‌نشده":
            self.pr_sale_paid.set_value(0)

        profit_total = (act_u - cost_u) * qty
        signed_diff = format_Signed_diff(act_u, sug_u, qty)

        self.lbl_sale_summary.setText(
            f"تخفیف (-) / تشدید (+): {signed_diff} تومان   |   مبلغ کل فاکتور: {total_bill:,} تومان   |   سود فروش: {profit_total:,} تومان"
        )

    def _recalc_warranty_end(self):
        m = self.cb_war_months.currentData() or 0
        if m > 0:
            self.dt_war_end.set_date(add_jalali_days(self.dt_war_start.get_date(), m))
        else:
            self.dt_war_end.set_date(self.dt_war_start.get_date())

    def _save_new_sale(self):
        prod = self.cb_sale_prod.currentData()
        batch = self.cb_sale_batch.currentData()
        if not prod or not batch:
            QMessageBox.warning(
                self, "خطا", "کالا و محموله دارای موجودی را انتخاب کنید."
            )
            return
        now_dt = (
            f"{jdatetime.date.today().strftime('%Y/%m/%d')} "
            f"{jdatetime.datetime.now().strftime('%H:%M:%S')}"
        )
        try:
            self.db.add_sale(
                self.ed_sale_inv.text().strip(),
                prod["id"],
                batch["id"],
                self.cb_sale_seller.currentData(),
                self.ed_sale_customer.text().strip(),
                self.cb_sale_qty.get_qty(),
                self.pr_sale_suggest.get_value(),
                self.pr_sale_actual.get_value(),
                self.pr_sale_paid.get_value(),
                now_dt,
                self.ed_war_company.text().strip(),
                self.dt_war_start.get_date(),
                0,
                self.dt_war_end.get_date(),
                self.ed_sale_serial.text().strip(),
                "",
                self.cb_sale_status.currentText(),
                warranty_days=self.cb_war_months.currentData() or 0,
                specifications=self.ed_sale_specs.text().strip(),
            )
            self.refresh_all_data()
            self._set_generated_code_placeholder(
                self.ed_sale_inv, "sales", "invoice_number", "INV-"
            )
        except Exception as e:
            QMessageBox.critical(self, "خطا در ثبت فروش", str(e))

    def _get_batch_sale_specs(self, batch_id):
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT final_specs, initial_specs FROM batches WHERE id=?",
                (batch_id,),
            ).fetchone()
        return (row["final_specs"] or row["initial_specs"] or "") if row else ""

    def _on_sale_row_selected(self):
        selected = self.tbl_sales.selectedItems()
        if not selected:
            return
        row_index = selected[0].row()
        self.selected_sale_id = int(self.tbl_sales.item(row_index, 0).text())
        self.ed_sale_inv.setText(self.tbl_sales.item(row_index, 1).text())
        self.ed_sale_customer.setText(self.tbl_sales.item(row_index, 7).text())
        self.cb_sale_qty.setCurrentText(self.tbl_sales.item(row_index, 8).text())
        self.pr_sale_suggest.set_value(
            int(self.tbl_sales.item(row_index, 9).text().replace(",", ""))
        )
        self.pr_sale_actual.set_value(
            int(self.tbl_sales.item(row_index, 10).text().replace(",", ""))
        )
        self.pr_sale_paid.set_value(
            int(self.tbl_sales.item(row_index, 16).text().replace(",", ""))
        )
        self.cb_sale_status.setCurrentText(self.tbl_sales.item(row_index, 17).text())
        self.ed_sale_serial.setText(self.tbl_sales.item(row_index, 19).text())
        with self.db.get_connection() as conn:
            sale_specs = conn.execute(
                "SELECT specifications, batch_id FROM sales WHERE id=?",
                (self.selected_sale_id,),
            ).fetchone()
            if sale_specs:
                selected_specs = (
                    sale_specs["specifications"]
                    or self._get_batch_sale_specs(sale_specs["batch_id"])
                )
                self.ed_sale_specs.setText(selected_specs)

        with self.db.get_connection() as conn:
            sale = conn.execute(
                """SELECT warranty_company, warranty_start, warranty_months,
                   warranty_days, warranty_end FROM sales WHERE id=?""",
                (self.selected_sale_id,),
            ).fetchone()
        if sale:
            self.ed_war_company.setText(sale["warranty_company"] or "")
            self.dt_war_start.set_date(sale["warranty_start"] or jdatetime.date.today().strftime("%Y/%m/%d"))
            self.dt_war_end.set_date(sale["warranty_end"] or sale["warranty_start"] or "")
            duration_days = int(sale["warranty_days"] or (int(sale["warranty_months"] or 0) * 30))
            if duration_days:
                index = self.cb_war_months.findData(duration_days)
                if index < 0:
                    choices = [
                        (abs(int(self.cb_war_months.itemData(i)) - duration_days), i)
                        for i in range(1, self.cb_war_months.count())
                        if self.cb_war_months.itemData(i) is not None
                    ]
                    if choices:
                        index = min(choices)[1]
                if index >= 0:
                    self.cb_war_months.setCurrentIndex(index)
            else:
                self.cb_war_months.setCurrentIndex(0)


    def _update_selected_sale(self):
        if not self.selected_sale_id:
            return
        try:
            self.db.update_sale(
                self.selected_sale_id,
                self.cb_sale_seller.currentData(),
                self.ed_sale_customer.text().strip(),
                self.cb_sale_qty.get_qty(),
                self.pr_sale_suggest.get_value(),
                self.pr_sale_actual.get_value(),
                self.pr_sale_paid.get_value(),
                self.ed_war_company.text().strip(),
                self.dt_war_start.get_date(),
                0,
                self.dt_war_end.get_date(),
                self.ed_sale_serial.text().strip(),
                "",
                self.cb_sale_status.currentText(),
                warranty_days=self.cb_war_months.currentData() or 0,
                specifications=self.ed_sale_specs.text().strip(),
            )
            self.refresh_all_data()
            QMessageBox.information(self, "اصلاح فروش", "ردیف فروش با موفقیت اصلاح شد.")
        except Exception as e:
            QMessageBox.critical(self, "خطا", str(e))

    def _delete_selected_sale(self):
        if not self.selected_sale_id:
            return
        if (
            _ask_yes_no(
                self,
                "حذف فروش",
                "آیا از حذف این فروش و بازگرداندن کالا به موجودی انبار اطمینان دارید؟",
            )
            is True
        ):
            self.db.delete_sale(self.selected_sale_id)
            self.refresh_all_data()

    # =========================================================================
    # ۵. تب مدیریت خدمات (بند ۴ و ۱۲)
    # =========================================================================
    def _init_tab_services(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.selected_srv_cat_id = None
        self.selected_srv_rec_id = None

        top_h = QHBoxLayout()
        # الف) تعریف، ویرایش و حذف لیست خدمات (بند ۴)
        gb_cat = QGroupBox("تعریف و مدیریت فهرست خدمات")
        v_cat = QVBoxLayout(gb_cat)
        f_cat = QFormLayout()
        self.cb_srv_type = QComboBox()
        self.cb_srv_type.addItems(
            self.catalog_config.get("service_types") or ["نرم‌افزاری", "سخت‌افزاری"]
        )
        self.ed_srv_code = SmartLineEdit("")
        self.ed_srv_code.setToolTip("در صورت خالی بودن، کد خدمت بعدی خودکار تخصیص می‌یابد.")
        self.ed_srv_name = SmartLineEdit("عنوان خدمت (مثلاً نصب ویندوز، نصب آنتی‌ویروس...)")
        self.pr_srv_def_fee = PriceInput(self.db)
        self.pr_srv_def_side = PriceInput(self.db)

        f_cat.addRow("نوع خدمت:", self.cb_srv_type)
        f_cat.addRow("کد خدمت:", self.ed_srv_code)
        f_cat.addRow("عنوان خدمت *:", self.ed_srv_name)
        f_cat.addRow("هزینه خدمت (تومان):", self.pr_srv_def_fee)
        f_cat.addRow("هزینه جانبی پیش‌فرض:", self.pr_srv_def_side)
        v_cat.addLayout(f_cat)

        cat_btns = QHBoxLayout()
        btn_clr_cat = QPushButton("پاک کردن فرم")
        btn_clr_cat.setObjectName("btnSecondary")
        btn_clr_cat.clicked.connect(self._clear_service_cat_form)
        btn_add_cat = QPushButton("➕ افزودن خدمت جدید")
        btn_add_cat.clicked.connect(self._add_new_service_tariff)
        btn_edit_cat = QPushButton("✏️ ویرایش خدمت انتخابی")
        btn_edit_cat.setObjectName("btnSuccess")
        btn_edit_cat.clicked.connect(self._edit_selected_service_tariff)
        btn_del_cat = QPushButton("🗑️ حذف از لیست")
        btn_del_cat.setObjectName("btnDanger")
        btn_del_cat.clicked.connect(self._delete_selected_service_tariff)
        cat_btns.addWidget(btn_clr_cat)
        cat_btns.addWidget(btn_add_cat)
        cat_btns.addWidget(btn_edit_cat)
        cat_btns.addWidget(btn_del_cat)
        v_cat.addLayout(cat_btns)

        self.tbl_srv_catalog = self._create_table(
            ["شناسه", "کد خدمت", "نوع خدمت", "عنوان خدمت", "هزینه خدمت (تومان)", "هزینه جانبی پیش‌فرض"]
        )
        self.tbl_srv_catalog.setMaximumHeight(160)
        self.tbl_srv_catalog.itemSelectionChanged.connect(self._on_srv_catalog_table_selected)
        self._add_table_search(cat_btns, self.tbl_srv_catalog, "service_catalog", "🔍 جست‌وجو در فهرست تعرفه‌های خدمات...")
        v_cat.addWidget(self.tbl_srv_catalog)

        # ب) ثبت انجام خدمت برای مشتری
        gb_rec = QGroupBox("ثبت فاکتور خدمات برای مشتری")
        f_rec = QFormLayout(gb_rec)
        self.cb_srv_select = SearchableComboBox()
        self.cb_srv_select.currentIndexChanged.connect(self._on_srv_catalog_picked)
        self.cb_srv_seller = SearchableComboBox()
        self.ed_srv_cust = SmartLineEdit("نام مشتری (اختیاری)")
        self.pr_srv_fee = PriceInput(self.db)
        self.pr_srv_fee.setReadOnly(True)
        self.pr_srv_fee.setStyleSheet("background-color: #e2e8f0; color: #475569; font-weight: bold;")
        self.pr_srv_fee.setToolTip("این مبلغ از فهرست خدمات خوانده می‌شود. برای اعمال تخفیف یا تشدید، «مبلغ دریافتی» را تغییر دهید.")
        self.pr_srv_side = PriceInput(self.db)
        self.cb_srv_status = QComboBox()
        self.cb_srv_status.addItems(["تسویه‌شده", "تسویه‌نشده", "تسویه جزئی"])
        self.cb_srv_status.currentTextChanged.connect(self._on_srv_status_changed)
        self.pr_srv_paid = PriceInput(self.db)
        self.ed_srv_desc = SmartLineEdit("توضیحات خدمات انجام شده...")
        
        # نمایش زنده تخفیف/تشدید و سود خالص خدمت
        self.lbl_srv_diff_summary = QLabel("تخفیف (-) / تشدید (+): 0 تومان | سود خالص: 0 تومان")
        self.lbl_srv_diff_summary.setStyleSheet(
            "font-weight: bold; color: #047857; background: #ecfdf5; padding: 5px; border-radius: 5px;"
        )

        self.pr_srv_paid.valueChanged.connect(self._recalc_srv_live_summary)
        self.pr_srv_side.valueChanged.connect(self._recalc_srv_live_summary)

        btn_rec_row = QHBoxLayout()
        btn_clr_srv = QPushButton("پاک کردن فرم")
        btn_clr_srv.setObjectName("btnSecondary")
        btn_clr_srv.clicked.connect(self._clear_service_rec_form)
        btn_add_srv = QPushButton("✅ ثبت فاکتور خدمات")
        btn_add_srv.clicked.connect(self._save_new_service_record)
        btn_edit_srv = QPushButton("✏️ ذخیره ویرایش فاکتور")
        btn_edit_srv.setObjectName("btnSuccess")
        btn_edit_srv.clicked.connect(self._update_selected_service_record)
        btn_del_srv = QPushButton("🗑️ حذف فاکتور خدمت")
        btn_del_srv.setObjectName("btnDanger")
        btn_del_srv.clicked.connect(self._delete_selected_service_record)
        btn_rec_row.addWidget(btn_clr_srv)
        btn_rec_row.addWidget(btn_add_srv)
        btn_rec_row.addWidget(btn_edit_srv)
        btn_rec_row.addWidget(btn_del_srv)

        f_rec.addRow("انتخاب خدمت *:", self.cb_srv_select)
        f_rec.addRow("مسئول خدمت:", self.cb_srv_seller)
        f_rec.addRow("نام مشتری:", self.ed_srv_cust)
        f_rec.addRow("هزینه خدمت (تومان):", self.pr_srv_fee)
        f_rec.addRow("هزینه‌های جانبی (تومان):", self.pr_srv_side)
        f_rec.addRow("وضعیت تسویه:", self.cb_srv_status)
        f_rec.addRow("مبلغ دریافتی (تومان):", self.pr_srv_paid)
        f_rec.addRow("شرح خدمات:", self.ed_srv_desc)
        f_rec.addRow(self.lbl_srv_diff_summary)
        f_rec.addRow(btn_rec_row)

        top_h.addWidget(gb_cat, 3)
        top_h.addWidget(gb_rec, 3)
        layout.addLayout(top_h)

        # بند ۴: حذف ستون «تعرفه تاریخی زمان ثبت» از نمایش جدول و اکتفا به «هزینه خدمت»
        self.tbl_services = self._create_table(
            [
                "شناسه",
                "شماره فاکتور",
                "تاریخ و ساعت",
                "نوع خدمت",
                "نام خدمت",
                "مسئول خدمت",
                "مشتری",
                "هزینه خدمت (تومان)",
                "تخفیف (-) / تشدید (+)",
                "هزینه‌های جانبی (تومان)",
                "سود خالص خدمت (تومان)",
                "مبلغ دریافتی",
                "وضعیت تسویه",
                "شرح خدمات",
            ]
        )
        self.tbl_services.itemSelectionChanged.connect(self._on_srv_rec_selected)
        self._add_table_search(btn_rec_row, self.tbl_services, "service_records", "🔍 جست‌وجو در فاکتورهای خدمات...")
        layout.addWidget(self.tbl_services)
        self._add_scrollable_tab(tab, "🛠️ میز خدمت")
        
    def _clear_service_cat_form(self):
        self.selected_srv_cat_id = None
        self._set_generated_code_placeholder(self.ed_srv_code, "service_catalog", "code", "S-")
        self.cb_srv_type.setCurrentIndex(0)
        self.ed_srv_name.clear()
        self.pr_srv_def_fee.set_value(0)
        self.pr_srv_def_side.set_value(0)
        self.tbl_srv_catalog.clearSelection()

    def _clear_service_rec_form(self):
        self.selected_srv_rec_id = None
        self.cb_srv_select.setCurrentIndex(-1)
        self.cb_srv_seller.setCurrentIndex(-1)
        self.ed_srv_cust.clear()
        self.ed_srv_desc.clear()
        self.cb_srv_status.setCurrentIndex(0)
        self.pr_srv_fee.set_value(0)
        self.pr_srv_side.set_value(0)
        self.pr_srv_paid.set_value(0)
        self.tbl_services.clearSelection()
        self._recalc_srv_live_summary()

    def _recalc_srv_live_summary(self):
        base_fee = self.pr_srv_fee.get_value()
        paid_val = self.pr_srv_paid.get_value()
        side = self.pr_srv_side.get_value()
        diff_str = format_Signed_diff(paid_val, base_fee, 1)
        net = paid_val - side
        self.lbl_srv_diff_summary.setText(
            f"تخفیف (-) / تشدید (+): {diff_str} تومان   |   سود خالص خدمت: {net:,} تومان"
        )

    def _on_srv_status_changed(self, st):
        if st.startswith("تسویه‌شده"):
            self.pr_srv_paid.set_value(self.pr_srv_fee.get_value())
        elif st.startswith("تسویه‌نشده"):
            self.pr_srv_paid.set_value(0)

    def _add_new_service_tariff(self):
        """Register a new tariff, explicitly handling duplicate codes and surfacing failures."""
        name = self.ed_srv_name.text().strip()
        if not name:
            QMessageBox.warning(self, "خطا", "عنوان خدمت را وارد کنید.")
            return

        try:
            code = self.ed_srv_code.text().strip()
            duplicate = None
            if code:
                with self.db.get_connection() as conn:
                    duplicate = conn.execute(
                        "SELECT id FROM service_catalog WHERE code=?", (code,)
                    ).fetchone()

            target_id = None
            if duplicate:
                msg = QMessageBox(self)
                msg.setWindowTitle("کد خدمت تکراری")
                msg.setText(
                    f"کد {code} قبلاً ثبت شده است. اطلاعات خدمت قبلی جایگزین شود؟"
                )
                btn_replace = msg.addButton("جایگزین کردن", QMessageBox.AcceptRole)
                msg.addButton("انصراف", QMessageBox.RejectRole)
                _center_message_buttons(msg)
                msg.exec()
                if msg.clickedButton() != btn_replace:
                    return
                target_id = int(duplicate["id"])

            self.db.save_service_catalog(
                target_id,
                code,
                self.cb_srv_type.currentText(),
                name,
                self.pr_srv_def_fee.get_value(),
                self.pr_srv_def_side.get_value(),
                "",
            )
            self._clear_service_cat_form()
            self.refresh_all_data()
            QMessageBox.information(
                self, "ثبت شد", "خدمت جدید با موفقیت به فهرست خدمات افزوده شد."
            )
        except Exception as exc:
            QMessageBox.critical(self, "خطا در ثبت خدمت", str(exc))

    def _edit_selected_service_tariff(self):
        if not self.selected_srv_cat_id:
            QMessageBox.warning(self, "انتخاب خدمت", "ابتدا یک خدمت را از جدول فهرست خدمات انتخاب کنید.")
            return
        self.db.save_service_catalog(
            self.selected_srv_cat_id,
            self.ed_srv_code.text().strip(),
            self.cb_srv_type.currentText(),
            self.ed_srv_name.text().strip(),
            self.pr_srv_def_fee.get_value(),
            self.pr_srv_def_side.get_value(),
            "",
        )
        self.refresh_all_data()
        QMessageBox.information(self, "ویرایش شد", "تعرفه خدمت بروزرسانی شد (سوابق قبلی تغییر نکردند).")

    def _delete_selected_service_tariff(self):
        if not self.selected_srv_cat_id:
            return
        try:
            self.db.delete_service_catalog(self.selected_srv_cat_id)
            self.selected_srv_cat_id = None
            self.ed_srv_name.clear()
            self.refresh_all_data()
        except Exception as e:
            QMessageBox.warning(self, "خطا در حذف", str(e))

    def _on_srv_catalog_table_selected(self):
        items = self.tbl_srv_catalog.selectedItems()
        if not items:
            return
        r = items[0].row()
        self.selected_srv_cat_id = int(self.tbl_srv_catalog.item(r, 0).text())
        self.ed_srv_code.setText(self.tbl_srv_catalog.item(r, 1).text())
        self.cb_srv_type.setCurrentText(self.tbl_srv_catalog.item(r, 2).text())
        self.ed_srv_name.setText(self.tbl_srv_catalog.item(r, 3).text())
        self.pr_srv_def_fee.set_value(
            int(self.tbl_srv_catalog.item(r, 4).text().replace(",", ""))
        )
        self.pr_srv_def_side.set_value(
            int(self.tbl_srv_catalog.item(r, 5).text().replace(",", ""))
        )

    def _on_srv_catalog_picked(self):
        d = self.cb_srv_select.currentData()
        if not d:
            return
        self.pr_srv_fee.set_value(d["default_fee"])
        self.pr_srv_side.set_value(d["default_side_cost"])
        if self.cb_srv_status.currentText() == "تسویه‌شده":
            self.pr_srv_paid.set_value(d["default_fee"])

    def _save_new_service_record(self):
        d = self.cb_srv_select.currentData()
        if not d:
            QMessageBox.warning(self, "خطا", "ابتدا یک خدمت از لیست انتخاب کنید.")
            return
        now_dt = (
            f"{jdatetime.date.today().strftime('%Y/%m/%d')} "
            f"{jdatetime.datetime.now().strftime('%H:%M:%S')}"
        )
        self.db.add_service_record(
            "",
            d["id"],
            self.cb_srv_seller.currentData(),
            self.cb_srv_seller.currentData(),
            self.ed_srv_cust.text().strip(),
            self.pr_srv_fee.get_value(),
            self.pr_srv_side.get_value(),
            self.pr_srv_paid.get_value(),
            now_dt,
            self.ed_srv_desc.text().strip(),
            self.cb_srv_status.currentText(),
        )
        self.refresh_all_data()

    def _on_srv_rec_selected(self):
        items = self.tbl_services.selectedItems()
        if not items:
            return
        r = items[0].row()
        self.selected_srv_rec_id = int(self.tbl_services.item(r, 0).text())
        self.ed_srv_cust.setText(self.tbl_services.item(r, 6).text())
        self.pr_srv_fee.set_value(
            int(self.tbl_services.item(r, 7).text().replace(",", ""))
        )
        self.pr_srv_side.set_value(
            int(self.tbl_services.item(r, 9).text().replace(",", ""))
        )
        self.pr_srv_paid.set_value(
            int(self.tbl_services.item(r, 11).text().replace(",", ""))
        )
        self.cb_srv_status.setCurrentText(self.tbl_services.item(r, 12).text())
        self.ed_srv_desc.setText(self.tbl_services.item(r, 13).text())

    def _update_selected_service_record(self):
        if not self.selected_srv_rec_id:
            return
        self.db.update_service_record(
            self.selected_srv_rec_id,
            self.cb_srv_seller.currentData(),
            self.ed_srv_cust.text().strip(),
            self.pr_srv_fee.get_value(),
            self.pr_srv_side.get_value(),
            self.pr_srv_paid.get_value(),
            self.ed_srv_desc.text().strip(),
            self.cb_srv_status.currentText(),
        )
        self.refresh_all_data()

    def _delete_selected_service_record(self):
        if not self.selected_srv_rec_id:
            return
        self.db.delete_service_record(self.selected_srv_rec_id)
        self.refresh_all_data()

    # =========================================================================
    # ۶. تب ارتقای لپ‌تاپ (بند ۵: قرار گرفته بلافاصله بعد از تب مدیریت خدمات)
    # =========================================================================
    def _init_tab_upgrades(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        gb = QGroupBox("ثبت ارتقای کالا (کسر خودکار قطعه مصرفی از انبار و ویرایش مشخصات فنی کالا)")
        grid = QGridLayout(gb)

        self.selected_upgrade_id = None
        self.cb_upg_target = SearchableComboBox()
        self.cb_upg_target.currentIndexChanged.connect(self._on_upg_target_changed)
        self.cb_upg_target_qty = QuantitySelector(50)
        self.cb_upg_target_qty.setEditable(0)
        self.cb_upg_part = SearchableComboBox()
        self.cb_upg_part.setEditable(True)
        self.cb_upg_part.setInsertPolicy(QComboBox.NoInsert)
        self.cb_upg_part.setToolTip("قطعه را از موجودی انتخاب کنید یا شرح قطعه را دستی وارد کنید.")
        self.cb_upg_part_qty = QuantitySelector(10)
        self.cb_upg_part_qty.setEditable(0)
        self.cb_upg_part.currentIndexChanged.connect(self._on_upg_part_changed)
        self.cb_upg_part.currentTextChanged.connect(self._on_upg_part_changed)
        self.cb_upg_target_qty.qtyChanged.connect(self._on_upg_part_changed)
        self.pr_upg_labor = PriceInput(self.db)
        self.ed_upg_new_specs = SmartLineEdit("مشخصات فنی کالا پس از ارتقا...")
        self.dt_upg_date = JalaliDateEdit(default_today=True)
        self.cb_upg_tech = SearchableComboBox()
        self.ed_upg_serial = SmartLineEdit("شماره سریال کالا")

        # مورد ۶: پیش‌فرض اضافه نشدن هزینه قطعه به قیمت کل محصول ارتقا یافته، مگر با فعال کردن تیک
        self.chk_upg_add_cost = QCheckBox(
            "افزودن هزینه قطعه مصرفی به بهای تمام‌شده و قیمت پیشنهادی کالای ارتقایافته"
        )
        self.chk_upg_add_cost.setChecked(False)

        grid.addWidget(QLabel("محموله کالای هدف *:"), 0, 0)
        grid.addWidget(self.cb_upg_target, 0, 1)
        grid.addWidget(QLabel("تعداد کالای هدف:"), 0, 2)
        grid.addWidget(self.cb_upg_target_qty, 0, 3)

        grid.addWidget(QLabel("قطعه مصرفی از انبار *:"), 1, 0)
        grid.addWidget(self.cb_upg_part, 1, 1)
        grid.addWidget(QLabel("تعداد قطعه در هر کالا:"), 1, 2)
        grid.addWidget(self.cb_upg_part_qty, 1, 3)

        grid.addWidget(QLabel("اجرت ارتقا هر واحد:"), 2, 0)
        grid.addWidget(self.pr_upg_labor, 2, 1)
        grid.addWidget(QLabel("مشخصات جدید دستگاه *:"), 2, 2)
        grid.addWidget(self.ed_upg_new_specs, 2, 3)

        grid.addWidget(QLabel("تاریخ ارتقا:"), 3, 0)
        grid.addWidget(self.dt_upg_date, 3, 1)
        grid.addWidget(QLabel("مسئول ارتقا:"), 3, 2)
        grid.addWidget(self.cb_upg_tech, 3, 3)

        grid.addWidget(self.chk_upg_add_cost, 4, 0, 1, 4)

        upg_btn_row = QHBoxLayout()
        btn_clear_upg = QPushButton("پاک کردن فرم")
        btn_clear_upg.setObjectName("btnSecondary")
        btn_clear_upg.clicked.connect(self._clear_upgrade_form)
        btn_upg = QPushButton("🔧 ثبت ارتقای جدید")
        btn_upg.clicked.connect(self._save_upgrade)
        btn_edit_upg = QPushButton("✏️ ذخیره ویرایش ارتقای انتخاب‌شده")
        btn_edit_upg.setObjectName("btnSuccess")
        btn_edit_upg.clicked.connect(self._save_upgrade)
        btn_revert_upg = QPushButton("🗑️ حذف ارتقا و بازگردانی موجودی")
        btn_revert_upg.setObjectName("btnDanger")
        btn_revert_upg.clicked.connect(self._revert_selected_upgrade)
        upg_btn_row.addWidget(btn_clear_upg)
        upg_btn_row.addWidget(btn_upg)
        upg_btn_row.addWidget(btn_edit_upg)
        upg_btn_row.addWidget(btn_revert_upg)
        upg_btn_row.addStretch()
        grid.addLayout(upg_btn_row, 5, 0, 1, 4)

        layout.addWidget(gb)

        self.tbl_upgrades = self._create_table(
            [
                "شناسه",
                "کد محموله کالا",
                "تعداد کالا",
                "کد محموله قطعه مصرفی",
                "تعداد کل قطعه مصرفی",
                "بهای واحد قطعه",
                "اجرت واحد",
                "مشخصات قبلی",
                "مشخصات جدید",
                "تاریخ ارتقا",
                "مسئول ارتقا",
                "دسته‌بندی کالای هدف",
                "برند کالای هدف",
                "مدل کالای هدف",
                "تأمین‌کننده کالای هدف",
                "قطعه مصرفی",
                "برند قطعه",
                "مدل قطعه",
                "تأمین‌کننده قطعه",
                "وضعیت کسر موجودی",
            ]
        )
        self.tbl_upgrades.itemSelectionChanged.connect(self._on_upgrade_selected)
        self._add_table_search(upg_btn_row, self.tbl_upgrades, "upgrades", "🔍 جست‌وجو در سوابق ارتقا...")
        layout.addWidget(self.tbl_upgrades)
        self._add_scrollable_tab(tab, "🔧 ارتقای کالا")

    def _on_upg_target_changed(self):
        """مورد ۶: پر شدن خودکار کادر مشخصات جدید با مشخصات قبلی دستگاه جهت ویرایش راحت‌تر"""
        t_id = self.cb_upg_target.currentData()
        if not t_id:
            self.ed_upg_new_specs.clear()
            self.cb_upg_target_qty.set_max_qty(1)
            self._on_upg_part_changed()
            return
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT b.remaining_qty, b.final_specs, b.initial_specs,
                       p.specs_json, p.category
                FROM batches b JOIN products p ON b.product_id = p.id
                WHERE b.id = ?
            """,
                (t_id,),
            ).fetchone()
            if row:
                self.cb_upg_target_qty.set_max_qty(row["remaining_qty"])
                specs_txt = row["final_specs"] or row["initial_specs"] or ""
                if not specs_txt and row["specs_json"]:
                    specs_dict = json.loads(row["specs_json"] or "{}")
                    specs_txt = self._format_specs_for_display(specs_dict, row["category"])
                self.ed_upg_new_specs.setText(specs_txt or "")
                self._on_upg_part_changed()

    def _on_upg_part_changed(self, *_):
        part_id = self.cb_upg_part.currentData()
        target_qty = self.cb_upg_target_qty.get_qty()
        if not part_id:
            self.cb_upg_part_qty.set_max_qty(50)
            self.cb_upg_part_qty.setEnabled(True)
            return
        with self.db.get_connection() as conn:
            part = conn.execute(
                "SELECT remaining_qty FROM batches WHERE id=?", (part_id,)
            ).fetchone()
        available = int(part["remaining_qty"]) if part else 0
        max_per_target = available // max(1, target_qty)
        self.cb_upg_part_qty.set_max_qty(max(1, max_per_target))
        self.cb_upg_part_qty.setEnabled(True)

    def _save_upgrade(self):
        t_id = self.cb_upg_target.currentData()
        p_id = self.cb_upg_part.currentData()
        part_text = self.cb_upg_part.currentText().strip()
        combo_index = self.cb_upg_part.currentIndex()
        is_real_batch = (
            combo_index >= 0
            and combo_index < self.cb_upg_part.count()
            and self.cb_upg_part.itemText(combo_index) == part_text
            and self.cb_upg_part.currentData() is not None
        )
        p_id = self.cb_upg_part.currentData() if is_real_batch else None
        if not t_id or (p_id is None and not part_text):
            QMessageBox.warning(
                self, "اطلاعات ارتقا", "محموله کالای هدف و قطعه مصرفی (انتخابی یا شرح دستی) را مشخص کنید."
            )
            return
        if p_id is not None and int(t_id) == int(p_id):
            QMessageBox.warning(self, "انتخاب نامعتبر", "محموله هدف و قطعه مصرفی باید متفاوت باشند.")
            return
        try:
            was_edit = self.selected_upgrade_id is not None
            consume_stock = False
            warning_messages = []
            with self.db.get_connection() as conn:
                target_row = conn.execute(
                    "SELECT remaining_qty, batch_code FROM batches WHERE id=?", (t_id,)
                ).fetchone()
                part_row = conn.execute(
                    "SELECT remaining_qty, batch_code FROM batches WHERE id=?", (p_id,)
                ).fetchone() if p_id is not None else None
            requested_targets = self.cb_upg_target_qty.get_qty()
            if target_row and int(target_row["remaining_qty"]) < requested_targets:
                warning_messages.append(
                    f"موجودی کالای هدف «{target_row['batch_code']}» کافی نیست "
                    f"(موجودی: {target_row['remaining_qty']})."
                )
            requested_parts = requested_targets * self.cb_upg_part_qty.get_qty()
            if p_id is not None and part_row:
                if int(part_row["remaining_qty"]) >= requested_parts:
                    consume_stock = True
                else:
                    warning_messages.append(
                        f"موجودی قطعه «{part_row['batch_code']}» کافی نیست "
                        f"(موجودی: {part_row['remaining_qty']}، مقدار درخواستی: {requested_parts}). "
                        "با تأیید شما ارتقا بدون کسر موجودی انجام می‌شود."
                    )
            else:
                warning_messages.append(
                    "قطعه به‌صورت دستی ثبت می‌شود و موجودی انبار تغییر نخواهد کرد."
                )
            if warning_messages and not _ask_yes_no(
                self, "هشدار موجودی و تأیید ارتقا",
                "\n".join(warning_messages) + "\n\nآیا با ثبت ارتقا بدون کسر موجودی ادامه می‌دهید؟"
            ):
                return
            self.db.upgrade_batch_product(
                t_id,
                self.cb_upg_target_qty.get_qty(),
                p_id,
                self.cb_upg_part_qty.get_qty(),
                self.pr_upg_labor.get_value(),
                self.ed_upg_new_specs.text().strip(),
                self.dt_upg_date.get_date(),
                self.cb_upg_tech.currentData(),
                self.ed_upg_serial.text().strip(),
                "",
                add_part_cost_to_product=self.chk_upg_add_cost.isChecked(),
                upgrade_id=self.selected_upgrade_id,
                manual_part_description=part_text if p_id is None else "",
                consume_stock=consume_stock,
            )
            self.refresh_all_data()
            self._clear_upgrade_form()
            QMessageBox.information(
                self, "ارتقای کالا",
                "اطلاعات ارتقا با موفقیت اصلاح شد." if was_edit else "ارتقای کالا با موفقیت ثبت شد."
            )
        except Exception as exc:
            QMessageBox.critical(self, "خطا در ارتقا", str(exc))

    def _clear_upgrade_form(self):
        self.selected_upgrade_id = None
        self.tbl_upgrades.clearSelection()
        self.cb_upg_target.setCurrentIndex(-1)
        self.cb_upg_part.setCurrentIndex(-1)
        self.cb_upg_part.setEditText("")
        self.cb_upg_tech.setCurrentIndex(-1)
        self.cb_upg_target_qty.setCurrentText("1")
        self.cb_upg_part_qty.setCurrentText("1")
        self.cb_upg_part_qty.setEnabled(0)
        self.pr_upg_labor.set_value(0)
        self.ed_upg_new_specs.clear()
        self.ed_upg_serial.clear()
        self.chk_upg_add_cost.setChecked(False)
        self.dt_upg_date.set_date(jdatetime.date.today().strftime("%Y/%m/%d"))
        self._on_upg_target_changed()

    def _on_upgrade_selected(self):
        selected = self.tbl_upgrades.selectedItems()
        if not selected:
            return
        row_index = selected[0].row()
        self.selected_upgrade_id = int(self.tbl_upgrades.item(row_index, 0).text())
        with self.db.get_connection() as conn:
            upgrade = conn.execute(
                "SELECT * FROM upgrades WHERE id=?", (self.selected_upgrade_id,)
            ).fetchone()
            related_batches = conn.execute(
                """SELECT b.*, p.category, p.sub_category, p.brand, p.model
                   FROM batches b JOIN products p ON p.id=b.product_id
                   WHERE b.id=? OR (? IS NOT NULL AND b.id=?)""",
                (upgrade["target_batch_id"], upgrade["part_batch_id"], upgrade["part_batch_id"]),
            ).fetchall() if upgrade else []
        if not upgrade:
            self._clear_upgrade_form()
            return

        # Keep exhausted historical batches selectable: editing reverses their old consumption first.
        for batch in related_batches:
            batch_id = int(batch["id"])
            product_title = self._format_product_picker_label(dict(batch))
            label = f"{batch['batch_code']} | {product_title} | موجودی: {batch['remaining_qty']}"
            tooltip = (
                f"{label}\nمشخصات اولیه: {batch['initial_specs'] or '-'}\n"
                f"مشخصات نهایی: {batch['final_specs'] or '-'}\n"
                f"شماره سریال: {batch['serial_numbers'] or '-'}"
            )
            searchable = (
                f"{label} {batch['initial_specs'] or ''} {batch['final_specs'] or ''} "
                f"{batch['serial_numbers'] or ''}"
            ).strip()
            for combo in (self.cb_upg_target, self.cb_upg_part):
                if combo.findData(batch_id) < 0:
                    item_index = combo.count()
                    combo.addItem(label, batch_id)
                    combo.setItemSearchText(item_index, searchable)
                    combo.setItemData(item_index, bidi_isolate_text(tooltip), Qt.ToolTipRole)

        target_index = self.cb_upg_target.findData(int(upgrade["target_batch_id"]))
        part_index = self.cb_upg_part.findData(int(upgrade["part_batch_id"]))
        if target_index >= 0:
            self.cb_upg_target.setCurrentIndex(target_index)
        if part_index >= 0:
            self.cb_upg_part.setCurrentIndex(part_index)
        else:
            self.cb_upg_part.setCurrentIndex(-1)
            self.cb_upg_part.setEditText(upgrade["manual_part_description"] or "")

        target_qty = max(1, int(upgrade["target_qty"]))
        per_unit = max(1, int(upgrade["part_qty_used"]) // target_qty)
        self.cb_upg_target_qty.setCurrentText(str(target_qty))
        self.cb_upg_part_qty.set_max_qty(max(10, per_unit))
        self.cb_upg_part_qty.setCurrentText(str(per_unit))
        self.pr_upg_labor.set_value(int(upgrade["labor_cost_unit"]))
        self.ed_upg_new_specs.setText(upgrade["new_specs"] or "")
        self.dt_upg_date.set_date(upgrade["upgrade_date"])
        self.ed_upg_serial.setText(upgrade["serial_number"] or "")
        self.chk_upg_add_cost.setChecked(
            int(upgrade["added_cost_unit"] or 0) > int(upgrade["labor_cost_unit"] or 0)
        )


    def _revert_selected_upgrade(self):
        items = self.tbl_upgrades.selectedItems()
        if not items:
            QMessageBox.warning(
                self, "انتخاب رکورد", "ابتدا یک ردیف ارتقا را از جدول پایین انتخاب کنید."
            )
            return
        upg_id = int(self.tbl_upgrades.item(items[0].row(), 0).text())
        if (
            _ask_yes_no(
                self,
                "تأیید برگشت ارتقا",
                "آیا از برگشت این ارتقا، بازگرداندن قطعه به موجودی انبار و بازگشت مشخصات قبلی کالا اطمینان دارید؟",
            )
            is True
        ):
            try:
                self.db.revert_upgrade(upg_id)
                self.refresh_all_data()
                self._clear_upgrade_form()
                QMessageBox.information(
                    self, "برگشت ارتقا", "ارتقای کالا به حالت قبل بازگردانده شد و قطعه به انبار برگشت."
                )
            except Exception as e:
                QMessageBox.critical(self, "خطا", str(e))


    # =========================================================================
    # ۷. تب تأمین‌کنندگان و بدهی‌ها (بند ۶: افزودن امکان اصلاح و حذف)
    # =========================================================================
    def _init_tab_suppliers_payments(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.selected_supplier_id = None

        gb_sup = QGroupBox("ثبت، ویرایش و حذف تأمین‌کنندگان (عمده‌فروشان)")
        v_sup = QVBoxLayout(gb_sup)
        h_sup = QHBoxLayout()
        self.ed_sup_name = SmartLineEdit("نام تأمین‌کننده / شرکت...")
        self.ed_sup_phone = SmartLineEdit("تلفن تماس...")
        self.ed_sup_addr = SmartLineEdit("آدرس یا توضیحات...")
        h_sup.addWidget(QLabel("نام تأمین‌کننده *:"))
        h_sup.addWidget(self.ed_sup_name)
        h_sup.addWidget(QLabel("تلفن:"))
        h_sup.addWidget(self.ed_sup_phone)
        h_sup.addWidget(QLabel("آدرس / توضیحات:"))
        h_sup.addWidget(self.ed_sup_addr)
        v_sup.addLayout(h_sup)

        btn_sup_row = QHBoxLayout()
        btn_add_sup = QPushButton("➕ افزودن تأمین‌کننده")
        btn_add_sup.clicked.connect(self._add_supplier)
        btn_edit_sup = QPushButton("✏️ ذخیره ویرایش تأمین‌کننده انتخابی")
        btn_edit_sup.setObjectName("btnSuccess")
        btn_edit_sup.clicked.connect(self._update_supplier)
        btn_del_sup = QPushButton("🗑️ حذف تأمین‌کننده انتخابی")
        btn_del_sup.setObjectName("btnDanger")
        btn_del_sup.clicked.connect(self._delete_supplier)
        btn_sup_row.addWidget(btn_add_sup)
        btn_sup_row.addWidget(btn_edit_sup)
        btn_sup_row.addWidget(btn_del_sup)
        btn_sup_row.addStretch()
        v_sup.addLayout(btn_sup_row)
        layout.addWidget(gb_sup)

        self.tbl_suppliers = self._create_table(
            [
                "شناسه",
                "نام تأمین‌کننده",
                "تلفن تماس",
                "آدرس / توضیحات",
                "تعداد محموله‌های خرید",
                "مجموع مبلغ خرید (تومان)",
                "مجموع پرداخت‌شده (تومان)",
                "مانده بدهی به تأمین‌کننده (تومان)",
            ]
        )
        self.tbl_suppliers.itemSelectionChanged.connect(self._on_supplier_selected)
        self._add_table_search(btn_sup_row, self.tbl_suppliers, "suppliers", "🔍 جست‌وجو در تأمین‌کنندگان...")
        layout.addWidget(self.tbl_suppliers)
        self._add_scrollable_tab(tab, "💳 تأمین‌کنندگان و بدهی‌ها")

    def _add_supplier(self):
        name = self.ed_sup_name.text().strip()
        if not name:
            QMessageBox.warning(self, "خطا", "نام تأمین‌کننده را وارد کنید.")
            return
        try:
            self.db.add_supplier(
                name,
                self.ed_sup_phone.text().strip(),
                self.ed_sup_addr.text().strip(),
                "",
            )
            self.ed_sup_name.clear()
            self.ed_sup_phone.clear()
            self.ed_sup_addr.clear()
            self.selected_supplier_id = None
            self.refresh_all_data()
        except Exception as e:
            QMessageBox.critical(self, "خطا در ثبت تأمین‌کننده", str(e))

    def _on_supplier_selected(self):
        items = self.tbl_suppliers.selectedItems()
        if not items:
            return
        r = items[0].row()
        self.selected_supplier_id = int(self.tbl_suppliers.item(r, 0).text())
        self.ed_sup_name.setText(self.tbl_suppliers.item(r, 1).text())
        phone = self.tbl_suppliers.item(r, 2).text()
        addr = self.tbl_suppliers.item(r, 3).text()
        self.ed_sup_phone.setText("" if phone == "-" else phone)
        self.ed_sup_addr.setText("" if addr == "-" else addr)

    def _update_supplier(self):
        if not self.selected_supplier_id:
            QMessageBox.warning(
                self, "انتخاب تأمین‌کننده", "ابتدا یک تأمین‌کننده را از جدول انتخاب کنید."
            )
            return
        name = self.ed_sup_name.text().strip()
        if not name:
            QMessageBox.warning(self, "خطا", "نام تأمین‌کننده نمی‌تواند خالی باشد.")
            return
        try:
            self.db.update_supplier(
                self.selected_supplier_id,
                name,
                self.ed_sup_phone.text().strip(),
                self.ed_sup_addr.text().strip(),
                "",
            )
            self.refresh_all_data()
            QMessageBox.information(
                self, "ذخیره شد", "اطلاعات تأمین‌کننده با موفقیت اصلاح شد."
            )
        except Exception as e:
            QMessageBox.critical(self, "خطا در ویرایش", str(e))

    def _delete_supplier(self):
        if not self.selected_supplier_id:
            QMessageBox.warning(
                self, "انتخاب تأمین‌کننده", "ابتدا یک تأمین‌کننده را از جدول انتخاب کنید."
            )
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("حذف تأمین‌کننده")
        msg.setText(
            "نحوه حذف را انتخاب کنید. در حالت حفظ سوابق، نام تأمین‌کننده در اطلاعات خریدهای گذشته باقی می‌ماند."
        )
        btn_cancel = msg.addButton("انصراف", QMessageBox.RejectRole)
        msg.addButton("حذف تأمین‌کننده بدون حذف داده‌های مربوط به آن", QMessageBox.AcceptRole)
        btn_delete_all = msg.addButton("حذف تأمین‌کننده و داده‌های مربوط به آن", QMessageBox.DestructiveRole)
        _center_message_buttons(msg)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == btn_cancel or clicked is None:
            return
        try:
            self.db.delete_supplier(
                self.selected_supplier_id,
                delete_related_data=(clicked == btn_delete_all),
            )
            self.selected_supplier_id = None
            self.ed_sup_name.clear()
            self.ed_sup_phone.clear()
            self.ed_sup_addr.clear()
            self.refresh_all_data()
        except Exception as e:
            QMessageBox.warning(self, "خطا در حذف", str(e))

    # =========================================================================
    # ۸. تب گزارش‌های جامع (بند ۳، ۹، ۱۰، ۱۳: ستون‌های کامل + نام‌گذاری خودکار RYYYYMMDD_N)
    # =========================================================================
    def _init_tab_reports(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        gb_flt = QGroupBox(
            "فیلترهای هوشمند گزارش (با تغییر هر فیلتر، جدول گزارش بلافاصله بروزرسانی می‌شود)"
        )
        grid = QGridLayout(gb_flt)

        self.cb_rep_type = QComboBox()
        self.cb_rep_type.addItems(
            [
                "همه (گزارش جامع خرید، فروش و خدمات)",
                "۱. گزارش کامل تمام فروش‌ها",
                "۲. گزارش کامل تمام خریدها (محموله‌ها)",
                "۳. گزارش موجودی فعلی کالاها",
                "۴. گزارش موجودی و سود به تفکیک محموله",
                "۵. گزارش سود تجمعی هر کالا",
                "۶. گزارش سود و عملکرد هر محموله",
                "۷. گزارش جامع عملکرد هر کارمند / فروشنده",
                "۸. گزارش کالاهای کم‌موجود (نیازمند خرید)",
                "۹. گزارش بدهی به تأمین‌کنندگان",
                "۱۰. گزارش فاکتورهای تسویه‌نشده (طلب و بدهی)",
                "۱۱. گزارش تخفیف‌ها و تشدیدهای فروش",
                "۱۲. گزارش کامل خدمات انجام‌شده",
            ]
        )
        if self._is_scoped_access():
            permission = self.active_employee.get("permissions") or ""
            if "ثبت خرید و انبارداری" in permission:
                allowed_reports = [
                    "۲. گزارش کامل تمام خریدها (محموله‌ها)",
                    "۷. گزارش جامع عملکرد هر کارمند / فروشنده",
                ]
            elif "سرپرست عملیات" in permission:
                allowed_reports = [
                    "۱. گزارش کامل تمام فروش‌ها",
                    "۲. گزارش کامل تمام خریدها (محموله‌ها)",
                    "۱۲. گزارش کامل خدمات انجام‌شده",
                ]
            else:
                allowed_reports = [
                    "۱. گزارش کامل تمام فروش‌ها",
                    "۱۲. گزارش کامل خدمات انجام‌شده",
                ]
            self.cb_rep_type.clear()
            self.cb_rep_type.addItems(allowed_reports)

        self.cb_rep_preset = QComboBox()
        self.cb_rep_preset.addItems(
            [
                "همه زمان‌ها",
                "امروز",
                "دیروز",
                "هفته گذشته",
                "یک ماه گذشته",
                "سال گذشته",
                "بازه انتخابی دستی",
            ]
        )
        self.cb_rep_preset.setCurrentText("همه زمان‌ها")

        self.dt_rep_from = JalaliDateEdit(default_today=False)
        self.dt_rep_from.set_date("1405/01/01")
        self.dt_rep_to = JalaliDateEdit(default_today=True)

        self.cb_rep_emp = SearchableComboBox()
        self.cb_rep_cat = SearchableComboBox()
        report_categories = (
            self.catalog_config.get("categories") or list(MAIN_CATEGORIES)
        )
        self.cb_rep_cat.addItems(["همه دسته‌ها"] + report_categories)
        self.ed_rep_search = SmartLineEdit(
            "جست‌وجوی کد کالا، دسته‌بندی، زیرگروه (مثلاً کیبورد)، برند، مدل، فاکتور..."
        )

        btn_exp_excel = QPushButton("📥 خروجی اکسل از این گزارش")
        btn_exp_excel.setObjectName("btnSuccess")
        btn_exp_excel.setToolTip(
            "ذخیره گزارش فعلی با تمامی ستون‌ها در فایل اکسل با نام‌گذاری خودکار روزانه"
        )
        btn_exp_excel.clicked.connect(self._export_current_report)

        grid.addWidget(QLabel("نوع گزارش:"), 0, 0)
        grid.addWidget(self.cb_rep_type, 0, 1)
        grid.addWidget(QLabel("بازه زمانی:"), 0, 2)
        grid.addWidget(self.cb_rep_preset, 0, 3)
        grid.addWidget(QLabel("از تاریخ:"), 0, 4)
        grid.addWidget(self.dt_rep_from, 0, 5)
        grid.addWidget(QLabel("تا تاریخ:"), 0, 6)
        grid.addWidget(self.dt_rep_to, 0, 7)

        grid.addWidget(QLabel("کارمند:"), 1, 0)
        grid.addWidget(self.cb_rep_emp, 1, 1)
        grid.addWidget(QLabel("دسته‌بندی:"), 1, 2)
        grid.addWidget(self.cb_rep_cat, 1, 3)
        grid.addWidget(QLabel("جست‌وجو:"), 1, 4)
        grid.addWidget(self.ed_rep_search, 1, 5, 1, 2)
        grid.addWidget(btn_exp_excel, 1, 7)

        layout.addWidget(gb_flt)

        self.lbl_rep_totals = QLabel("خلاصه مالی گزارش:")
        self.lbl_rep_totals.setStyleSheet(
            "font-weight: bold; font-size: 14px; color: #1e3a8a; background: #dbeafe; padding: 8px; border-radius: 6px;"
        )
        layout.addWidget(self.lbl_rep_totals)

        self.tbl_report = self._create_table(["ستون ۱"])
        layout.addWidget(self.tbl_report)

        self.cb_rep_type.currentIndexChanged.connect(self._update_report_live)
        self.cb_rep_preset.currentIndexChanged.connect(self._on_rep_preset_changed)
        self._on_rep_preset_changed()
        self.dt_rep_from.dateChanged.connect(self._update_report_live)
        self.dt_rep_to.dateChanged.connect(self._update_report_live)
        self.cb_rep_emp.currentIndexChanged.connect(self._update_report_live)
        self.cb_rep_cat.currentTextChanged.connect(self._update_report_live)
        self.ed_rep_search.textChanged.connect(self._update_report_live)

        self._add_scrollable_tab(tab, "📈 گزارش‌های جامع")

    def _on_rep_preset_changed(self):
        preset = self.cb_rep_preset.currentText()
        today_j = jdatetime.date.today()
        today_g = today_j.togregorian()

        if preset == "همه زمان‌ها":
            self.dt_rep_from.set_date("1400/01/01")
            self.dt_rep_to.set_date("1600/12/29")
        elif preset == "امروز":
            s = today_j.strftime("%Y/%m/%d")
            self.dt_rep_from.set_date(s)
            self.dt_rep_to.set_date(s)
        elif preset == "دیروز":
            y_j = jdatetime.date.fromgregorian(date=today_g - timedelta(days=1))
            s = y_j.strftime("%Y/%m/%d")
            self.dt_rep_from.set_date(s)
            self.dt_rep_to.set_date(s)
        elif preset == "هفته گذشته":
            w_j = jdatetime.date.fromgregorian(date=today_g - timedelta(days=7))
            self.dt_rep_from.set_date(w_j.strftime("%Y/%m/%d"))
            self.dt_rep_to.set_date(today_j.strftime("%Y/%m/%d"))
        elif preset == "یک ماه گذشته":
            m_j = jdatetime.date.fromgregorian(date=today_g - timedelta(days=30))
            self.dt_rep_from.set_date(m_j.strftime("%Y/%m/%d"))
            self.dt_rep_to.set_date(today_j.strftime("%Y/%m/%d"))
        elif preset == "سال گذشته":
            yr_j = jdatetime.date.fromgregorian(date=today_g - timedelta(days=365))
            self.dt_rep_from.set_date(yr_j.strftime("%Y/%m/%d"))
            self.dt_rep_to.set_date(today_j.strftime("%Y/%m/%d"))

        self._update_report_live()

    def _update_report_live(self):
        rep_type = self.cb_rep_type.currentText()
        d_from = self.dt_rep_from.get_date()
        d_to = self.dt_rep_to.get_date()
        emp_id = self.cb_rep_emp.currentData()
        if self._is_scoped_access() and self.active_employee:
            emp_id = int(self.active_employee["id"])
        cat = self.cb_rep_cat.currentText().strip()
        q_txt = self.ed_rep_search.text().strip().lower()

        headers = []
        rows_data = []
        summary_text = ""

        with self.db.get_connection() as conn:
            # ۰. گزارش جامع همه تراکنش‌ها با کامل‌ترین ستون‌ها (بند ۹)
            if rep_type.startswith("همه"):
                headers = [
                    "نوع عملیات",
                    "شماره فاکتور / محموله",
                    "تاریخ و ساعت",
                    "کد کالا / خدمت",
                    "دسته‌بندی",
                    "زیرمجموعه",
                    "برند و مدل / عنوان",
                    "کارمند ثبت‌کننده",
                    "مشتری / تأمین‌کننده",
                    "تعداد",
                    "مبلغ واحد (تومان)",
                    "تخفیف (-) / تشدید (+)",
                    "بهای تمام‌شده / هزینه جانبی",
                    "مبلغ کل (تومان)",
                    "پرداخت‌شده (تومان)",
                    "مانده حساب (تومان)",
                    "سود خالص (تومان)",
                    "وضعیت تسویه",
                    "مشخصات فنی",
                ]
                s_rows = conn.execute("""
                    SELECT 'فروش کالا' as t_type, s.invoice_number as ref, s.sale_datetime as dt,
                           p.code, p.category, p.sub_category, (p.brand || ' ' || p.model) as title,
                           COALESCE(NULLIF(s.specifications,''), NULLIF(b.final_specs,''), NULLIF(b.initial_specs,''), '') as specs,
                           e.id as emp_id, e.name as emp_name, s.customer_name as party,
                           s.qty, s.actual_unit_price as u_price, s.suggested_unit_price as sug_price,
                           (s.unit_cost_price * s.qty) as cost_total, s.total_amount as amt,
                           s.paid_amount as paid, s.total_profit as prof, s.settlement_status as st
                    FROM sales s
                    JOIN products p ON s.product_id=p.id
                    LEFT JOIN batches b ON s.batch_id=b.id
                    LEFT JOIN employees e ON s.seller_employee_id=e.id
                """).fetchall()

                b_rows = conn.execute("""
                    SELECT 'خرید محموله' as t_type, b.batch_code as ref, b.purchase_date as dt,
                           p.code, p.category, p.sub_category, (p.brand || ' ' || p.model) as title,
                           COALESCE(NULLIF(b.final_specs,''), NULLIF(b.initial_specs,''), '') as specs,
                           e.id as emp_id, e.name as emp_name, COALESCE(sup.name,b.supplier_name_snapshot) as party,
                           b.initial_qty as qty, b.unit_purchase_price as u_price, b.unit_purchase_price as sug_price,
                           b.extra_cost_total as cost_total,
                           (b.unit_purchase_price * b.initial_qty + b.extra_cost_total) as amt,
                           b.paid_amount as paid, 0 as prof, b.settlement_status as st
                    FROM batches b
                    JOIN products p ON b.product_id=p.id
                    LEFT JOIN employees e ON b.buyer_employee_id=e.id
                    LEFT JOIN suppliers sup ON b.supplier_id=sup.id
                """).fetchall()

                srv_rows = conn.execute("""
                    SELECT 'خدمات' as t_type, sr.invoice_number as ref, sr.service_datetime as dt,
                           'SRV' as code, 'خدمات' as category, sr.service_type as sub_category,
                           sr.service_name as title, '' as specs, e.id as emp_id, e.name as emp_name,
                           sr.customer_name as party, 1 as qty, sr.service_fee as u_price,
                           sr.service_fee as sug_price, sr.side_cost as cost_total,
                           sr.service_fee as amt, sr.paid_amount as paid,
                           sr.net_profit as prof, sr.settlement_status as st
                    FROM service_records sr
                    LEFT JOIN employees e ON sr.seller_employee_id=e.id
                """).fetchall()

                total_income = 0
                total_buy = 0
                total_profit = 0
                for r in list(s_rows) + list(b_rows) + list(srv_rows):
                    d_only = (r["dt"] or "")[:10]
                    if not (d_from <= d_only <= d_to):
                        continue
                    if emp_id and r["emp_id"] != emp_id:
                        continue
                    if cat and cat != "همه دسته‌ها" and r["category"] != cat:
                        continue
                    search_pool = f"{r['t_type']} {r['ref']} {r['code']} {r['category']} {r['sub_category']} {r['title']} {r['emp_name']} {r['party']}".lower()
                    if q_txt and q_txt not in search_pool:
                        continue

                    amt = int(r["amt"])
                    paid = int(r["paid"])
                    rem_balance = max(0, amt - paid)
                    prof = int(r["prof"])
                    diff_str = (
                        format_Signed_diff(r["u_price"], r["sug_price"], r["qty"])
                        if r["t_type"] == "فروش کالا"
                        else "0"
                    )

                    if r["t_type"] == "خرید محموله":
                        total_buy += amt
                    else:
                        total_income += amt
                        total_profit += prof

                    rows_data.append(
                        [
                            r["t_type"],
                            r["ref"],
                            r["dt"],
                            r["code"],
                            r["category"],
                            r["sub_category"] or "-",
                            r["title"].strip() or r["sub_category"],
                            r["specs"] or "-",
                            r["emp_name"] or "-",
                            r["party"] or "-",
                            r["qty"],
                            f"{int(r['u_price']):,}",
                            diff_str,
                            f"{int(r['cost_total']):,}",
                            f"{amt:,}",
                            f"{paid:,}",
                            f"{rem_balance:,}",
                            f"{prof:,}",
                            r["st"],
                        ]
                    )
                rows_data.sort(key=lambda row: str(row[2] or ""), reverse=True)
                summary_text = (
                    f"مجموع فروش و خدمات: {total_income:,} تومان   |   "
                    f"مجموع خریدها: {total_buy:,} تومان   |   "
                    f"سود خالص کل: {total_profit:,} تومان"
                )

            # ۱ و ۱۱. گزارش کامل تمام فروش‌ها / تخفیف‌ها و تشدیدها
            elif rep_type.startswith("۱.") or rep_type.startswith("۱۱."):
                headers = [
                    "شماره فاکتور",
                    "تاریخ و ساعت فروش",
                    "کد کالا",
                    "دسته‌بندی",
                    "زیرمجموعه",
                    "برند و مدل",
                    "کد محموله",
                    "فروشنده",
                    "مشتری",
                    "تعداد",
                    "قیمت پیشنهادی واحد",
                    "قیمت فروش واحد",
                    "تخفیف (-) / تشدید (+)",
                    "بهای تمام‌شده واحد",
                    "سود هر واحد",
                    "سود کل ردیف",
                    "مبلغ کل فاکتور",
                    "مبلغ دریافتی",
                    "مانده طلب",
                    "وضعیت تسویه",
                    "شرکت گارانتی",
                    "انقضای گارانتی",
                    "شماره سریال",
                    "مشخصات فنی",
                ]
                q = conn.execute("""
                    SELECT s.*, p.code, p.category, p.sub_category, p.brand, p.model,
                           b.batch_code, b.final_specs, b.initial_specs, e.name as emp_name
                    FROM sales s
                    JOIN products p ON s.product_id=p.id
                    JOIN batches b ON s.batch_id=b.id
                    LEFT JOIN employees e ON s.seller_employee_id=e.id
                    ORDER BY s.updated_at DESC, s.id DESC
                """).fetchall()
                sum_sale, sum_prof, sum_disc = 0, 0, 0
                for r in q:
                    dt = r["sale_datetime"][:10]
                    if not (d_from <= dt <= d_to):
                        continue
                    if emp_id and r["seller_employee_id"] != emp_id:
                        continue
                    if cat and cat != "همه دسته‌ها" and r["category"] != cat:
                        continue
                    diff_val = (int(r["actual_unit_price"]) - int(r["suggested_unit_price"])) * int(r["qty"])
                    if rep_type.startswith("۱۱.") and diff_val == 0:
                        continue
                    search_pool = f"{r['invoice_number']} {r['code']} {r['category']} {r['sub_category']} {r['brand']} {r['model']} {r['batch_code']} {r['customer_name']} {r['serial_number']}".lower()
                    if q_txt and q_txt not in search_pool:
                        continue

                    sum_sale += int(r["total_amount"])
                    sum_prof += int(r["total_profit"])
                    sum_disc += int(r["total_discount"])
                    rem_pay = max(0, int(r["total_amount"]) - int(r["paid_amount"]))
                    signed_str = format_Signed_diff(
                        r["actual_unit_price"], r["suggested_unit_price"], r["qty"]
                    )
                    rows_data.append(
                        [
                            r["invoice_number"],
                            r["sale_datetime"],
                            r["code"],
                            r["category"],
                            r["sub_category"],
                            f"{r['brand']} {r['model']}".strip() or r["sub_category"],
                            r["batch_code"],
                            r["emp_name"],
                            r["customer_name"] or "-",
                            r["qty"],
                            f"{r['suggested_unit_price']:,}",
                            f"{r['actual_unit_price']:,}",
                            signed_str,
                            f"{r['unit_cost_price']:,}",
                            f"{r['unit_profit']:,}",
                            f"{r['total_profit']:,}",
                            f"{r['total_amount']:,}",
                            f"{r['paid_amount']:,}",
                            f"{rem_pay:,}",
                            r["settlement_status"],
                            r["warranty_company"] or "-",
                            r["warranty_end"] or "-",
                            r["serial_number"] or "-",
                            r["specifications"] or r["final_specs"] or r["initial_specs"] or "-",
                        ]
                    )
                summary_text = (
                    f"تعداد ردیف فروش: {len(rows_data)}   |   "
                    f"مجموع فروش: {sum_sale:,} تومان   |   "
                    f"مجموع تخفیف‌ها: {sum_disc:,} تومان   |   "
                    f"سود کل فروش: {sum_prof:,} تومان"
                )

            # ۲، ۴، ۶، ۹. گزارش کامل خریدها و محموله‌ها
            elif (
                rep_type.startswith("۲.")
                or rep_type.startswith("۴.")
                or rep_type.startswith("۶.")
                or rep_type.startswith("۹.")
            ):
                headers = [
                    "کد محموله",
                    "شماره فاکتور خرید",
                    "تاریخ خرید",
                    "کد کالا",
                    "دسته‌بندی",
                    "زیرمجموعه",
                    "برند و مدل",
                    "تأمین‌کننده",
                    "مسئول خرید",
                    "تعداد اولیه",
                    "تعداد فروش‌رفته",
                    "موجودی باقی‌مانده",
                    "قیمت خرید واحد",
                    "هزینه جانبی کل",
                    "هزینه ارتقا واحد",
                    "بهای تمام‌شده واحد",
                    "قیمت فروش پیشنهادی",
                    "درصد سود (%)",
                    "مبلغ کل خرید",
                    "پرداخت‌شده",
                    "مانده بدهی",
                    "سود تحقق‌یافته محموله",
                    "وضعیت تسویه",
                    "مشخصات / توضیحات",
                ]
                q = conn.execute("""
                    SELECT b.*, p.code, p.category, p.sub_category, p.brand, p.model,
                           COALESCE(sup.name,b.supplier_name_snapshot) as sup_name, e.name as emp_name,
                           COALESCE((SELECT SUM(total_profit) FROM sales s WHERE s.batch_id=b.id), 0) as batch_profit
                    FROM batches b
                    JOIN products p ON b.product_id=p.id
                    LEFT JOIN suppliers sup ON b.supplier_id=sup.id
                    LEFT JOIN employees e ON b.buyer_employee_id=e.id
                    ORDER BY b.updated_at DESC, b.id DESC
                """).fetchall()
                sum_buy, sum_debt, sum_b_prof = 0, 0, 0
                for r in q:
                    if not (d_from <= r["purchase_date"] <= d_to):
                        continue
                    if emp_id and r["buyer_employee_id"] != emp_id:
                        continue
                    if cat and cat != "همه دسته‌ها" and r["category"] != cat:
                        continue
                    search_pool = f"{r['batch_code']} {r['invoice_number']} {r['code']} {r['category']} {r['sub_category']} {r['brand']} {r['model']} {r['sup_name']}".lower()
                    if q_txt and q_txt not in search_pool:
                        continue

                    total_buy = (r["unit_purchase_price"] * r["initial_qty"]) + r["extra_cost_total"]
                    debt = max(0, total_buy - r["paid_amount"])
                    if rep_type.startswith("۹.") and debt == 0:
                        continue
                    sum_buy += total_buy
                    sum_debt += debt
                    sum_b_prof += int(r["batch_profit"])
                    rows_data.append(
                        [
                            r["batch_code"],
                            r["invoice_number"] or "-",
                            r["purchase_date"],
                            r["code"],
                            r["category"],
                            r["sub_category"],
                            f"{r['brand']} {r['model']}".strip() or r["sub_category"],
                            r["sup_name"] or "-",
                            r["emp_name"] or "-",
                            r["initial_qty"],
                            r["sold_qty"],
                            r["remaining_qty"],
                            f"{r['unit_purchase_price']:,}",
                            f"{r['extra_cost_total']:,}",
                            f"{r['upgrade_cost_unit']:,}",
                            f"{r['unit_cost_price']:,}",
                            f"{r['suggested_sell_price']:,}",
                            r["profit_pct"],
                            f"{total_buy:,}",
                            f"{r['paid_amount']:,}",
                            f"{debt:,}",
                            f"{int(r['batch_profit']):,}",
                            r["settlement_status"],
                            f"{r['final_specs']} {r['serial_numbers']}".strip() or "-",
                        ]
                    )
                summary_text = (
                    f"کل مبلغ خرید محموله‌ها: {sum_buy:,} تومان   |   "
                    f"سود تحقق‌یافته: {sum_b_prof:,} تومان   |   "
                    f"مانده بدهی به تأمین‌کنندگان: {sum_debt:,} تومان"
                )

            # ۳، ۵، ۸. گزارش موجودی و سود به تفکیک کالا
            elif (
                rep_type.startswith("۳.")
                or rep_type.startswith("۵.")
                or rep_type.startswith("۸.")
            ):
                headers = [
                    "کد کالا",
                    "دسته‌بندی",
                    "زیرمجموعه",
                    "برند",
                    "مدل",
                    "مشخصات فنی",
                    "تعداد کل خریداری‌شده",
                    "تعداد کل فروخته‌شده",
                    "موجودی فعلی انبار",
                    "حداقل موجودی (نقطه سفارش)",
                    "مجموع مبلغ فروش کالا",
                    "سود تجمعی کالا (تومان)",
                    "وضعیت موجودی",
                ]
                q = conn.execute("""
                    SELECT p.*,
                           COALESCE((SELECT SUM(initial_qty) FROM batches b WHERE b.product_id=p.id), 0) as init_qty,
                           COALESCE((SELECT SUM(remaining_qty) FROM batches b WHERE b.product_id=p.id), 0) as rem_qty,
                           COALESCE((SELECT SUM(sold_qty) FROM batches b WHERE b.product_id=p.id), 0) as s_qty,
                           COALESCE((SELECT SUM(total_amount) FROM sales s WHERE s.product_id=p.id), 0) as prod_rev,
                           COALESCE((SELECT SUM(total_profit) FROM sales s WHERE s.product_id=p.id), 0) as prod_prof
                    FROM products p
                    ORDER BY p.updated_at DESC, p.id DESC
                """).fetchall()
                sum_stock, sum_prof = 0, 0
                for r in q:
                    if cat and cat != "همه دسته‌ها" and r["category"] != cat:
                        continue
                    rem = int(r["rem_qty"])
                    if rep_type.startswith("۸.") and rem > int(r["reorder_point"]):
                        continue
                    specs = json.loads(r["specs_json"] or "{}")
                    specs_str = self._format_specs_for_display(specs, r["category"])
                    search_pool = f"{r['code']} {r['category']} {r['sub_category']} {r['brand']} {r['model']} {specs_str}".lower()
                    if q_txt and q_txt not in search_pool:
                        continue

                    sum_stock += rem
                    sum_prof += int(r["prod_prof"])
                    st = (
                        "ناموجود"
                        if rem <= 0
                        else ("کم‌موجود" if rem <= r["reorder_point"] else "موجود")
                    )
                    rows_data.append(
                        [
                            r["code"],
                            r["category"],
                            r["sub_category"],
                            r["brand"] or "-",
                            r["model"] or "-",
                            specs_str or "-",
                            r["init_qty"],
                            r["s_qty"],
                            rem,
                            r["reorder_point"],
                            f"{int(r['prod_rev']):,}",
                            f"{int(r['prod_prof']):,}",
                            st,
                        ]
                    )
                summary_text = (
                    f"تعداد کالاها: {len(rows_data)}   |   "
                    f"مجموع موجودی فیزیکی: {sum_stock:,} عدد   |   "
                    f"سود تجمعی کالاها: {sum_prof:,} تومان"
                )

            # ۷. گزارش جامع عملکرد هر کارمند
            elif rep_type.startswith("۷."):
                headers = [
                    "نام کارمند",
                    "نقش سازمانی",
                    "تعداد محموله خریداری‌شده",
                    "مبلغ کل خرید ثبت‌شده",
                    "تعداد فاکتور فروش",
                    "تعداد اقلام فروخته‌شده",
                    "مبلغ کل فروش (تومان)",
                    "تخفیف داده‌شده (تومان)",
                    "سود حاصل از فروش کالا",
                    "تعداد خدمات انجام‌شده",
                    "سود خالص خدمات",
                    "مجموع سود ایجادی کارمند",
                ]
                emps = conn.execute("SELECT * FROM employees").fetchall()
                for e in emps:
                    if emp_id and e["id"] != emp_id:
                        continue
                    b_stat = conn.execute(
                        """
                        SELECT COUNT(*) as cnt,
                               COALESCE(SUM(unit_purchase_price*initial_qty + extra_cost_total), 0) as amt
                        FROM batches WHERE buyer_employee_id=? AND purchase_date BETWEEN ? AND ?
                    """,
                        (e["id"], d_from, d_to),
                    ).fetchone()
                    s_stat = conn.execute(
                        """
                        SELECT COUNT(*) as cnt, COALESCE(SUM(qty),0) as items_cnt,
                               COALESCE(SUM(total_amount),0) as amt,
                               COALESCE(SUM(total_discount),0) as disc,
                               COALESCE(SUM(total_profit),0) as prof
                        FROM sales WHERE seller_employee_id=? AND substr(sale_datetime,1,10) BETWEEN ? AND ?
                    """,
                        (e["id"], d_from, d_to),
                    ).fetchone()
                    srv_stat = conn.execute(
                        """
                        SELECT COUNT(*) as cnt, COALESCE(SUM(net_profit),0) as prof
                        FROM service_records WHERE seller_employee_id=? AND substr(service_datetime,1,10) BETWEEN ? AND ?
                    """,
                        (e["id"], d_from, d_to),
                    ).fetchone()
                    tot_emp_prof = int(s_stat["prof"]) + int(srv_stat["prof"])
                    rows_data.append(
                        [
                            e["name"],
                            e["role"],
                            b_stat["cnt"],
                            f"{int(b_stat['amt']):,}",
                            s_stat["cnt"],
                            s_stat["items_cnt"],
                            f"{int(s_stat['amt']):,}",
                            f"{int(s_stat['disc']):,}",
                            f"{int(s_stat['prof']):,}",
                            srv_stat["cnt"],
                            f"{int(srv_stat['prof']):,}",
                            f"{tot_emp_prof:,}",
                        ]
                    )
                summary_text = "گزارش جامع عملکرد خرید، فروش و خدمات کارکنان در بازه زمانی انتخابی"

            # ۱۰. گزارش فاکتورهای تسویه‌نشده
            elif rep_type.startswith("۱۰."):
                headers = [
                    "نوع فاکتور",
                    "شماره فاکتور / محموله",
                    "تاریخ",
                    "طرف حساب (مشتری / تأمین‌کننده)",
                    "کارمند مسئول",
                    "شرح کالا / خدمت",
                    "مبلغ کل (تومان)",
                    "مبلغ پرداخت‌شده (تومان)",
                    "مانده تسویه‌نشده (تومان)",
                    "وضعیت تسویه",
                ]
                sum_receivable, sum_payable = 0, 0
                for r in conn.execute("""
                    SELECT s.*, p.sub_category, p.brand, p.model, e.name as emp_name
                    FROM sales s JOIN products p ON s.product_id=p.id LEFT JOIN employees e ON s.seller_employee_id=e.id
                    WHERE s.settlement_status != 'تسویه‌شده'
                """).fetchall():
                    rem_amt = max(0, r["total_amount"] - r["paid_amount"])
                    sum_receivable += rem_amt
                    rows_data.append(
                        [
                            "فروش کالا (طلب از مشتری)",
                            r["invoice_number"],
                            r["sale_datetime"],
                            r["customer_name"] or "مشتری",
                            r["emp_name"],
                            f"{r['sub_category']} {r['brand']} {r['model']}".strip(),
                            f"{r['total_amount']:,}",
                            f"{r['paid_amount']:,}",
                            f"{rem_amt:,}",
                            r["settlement_status"],
                        ]
                    )
                for r in conn.execute("""
                    SELECT b.*, p.sub_category, p.brand, p.model, COALESCE(sup.name,b.supplier_name_snapshot) as sup_name, e.name as emp_name
                    FROM batches b JOIN products p ON b.product_id=p.id
                    LEFT JOIN suppliers sup ON b.supplier_id=sup.id LEFT JOIN employees e ON b.buyer_employee_id=e.id
                    WHERE b.settlement_status != 'تسویه‌شده'
                """).fetchall():
                    tot = (r["unit_purchase_price"] * r["initial_qty"]) + r["extra_cost_total"]
                    rem_amt = max(0, tot - r["paid_amount"])
                    sum_payable += rem_amt
                    rows_data.append(
                        [
                            "خرید محموله (بدهی به تأمین‌کننده)",
                            r["batch_code"],
                            r["purchase_date"],
                            r["sup_name"] or "تأمین‌کننده",
                            r["emp_name"] or "-",
                            f"{r['sub_category']} {r['brand']} {r['model']}".strip(),
                            f"{tot:,}",
                            f"{r['paid_amount']:,}",
                            f"{rem_amt:,}",
                            r["settlement_status"],
                        ]
                    )
                for r in conn.execute("""
                    SELECT sr.*, e.name as emp_name FROM service_records sr
                    LEFT JOIN employees e ON sr.seller_employee_id=e.id
                    WHERE sr.settlement_status != 'تسویه‌شده'
                """).fetchall():
                    rem_amt = max(0, r["service_fee"] - r["paid_amount"])
                    sum_receivable += rem_amt
                    rows_data.append(
                        [
                            "فاکتور خدمات (طلب از مشتری)",
                            r["invoice_number"],
                            r["service_datetime"],
                            r["customer_name"] or "مشتری",
                            r["emp_name"],
                            r["service_name"],
                            f"{r['service_fee']:,}",
                            f"{r['paid_amount']:,}",
                            f"{rem_amt:,}",
                            r["settlement_status"],
                        ]
                    )
                summary_text = (
                    f"مجموع طلب از مشتریان: {sum_receivable:,} تومان   |   "
                    f"مجموع بدهی به تأمین‌کنندگان: {sum_payable:,} تومان"
                )

            # ۱۲. گزارش کامل خدمات انجام‌شده
            elif rep_type.startswith("۱۲."):
                headers = [
                    "شماره فاکتور",
                    "تاریخ و ساعت",
                    "نوع خدمت",
                    "نام خدمت",
                    "مسئول خدمت",
                    "نام مشتری",
                    "هزینه خدمت (تومان)",
                    "هزینه‌های جانبی (تومان)",
                    "سود خالص خدمت (تومان)",
                    "مبلغ دریافتی (تومان)",
                    "مانده طلب",
                    "وضعیت تسویه",
                    "شرح خدمات",
                ]
                q = conn.execute("""
                    SELECT sr.*, e.name as emp_name FROM service_records sr
                    LEFT JOIN employees e ON sr.seller_employee_id=e.id
                    ORDER BY sr.updated_at DESC, sr.id DESC
                """).fetchall()
                sum_fee, sum_side, sum_net = 0, 0, 0
                for r in q:
                    dt = r["service_datetime"][:10]
                    if not (d_from <= dt <= d_to):
                        continue
                    if emp_id and r["seller_employee_id"] != emp_id:
                        continue
                    if q_txt and q_txt not in f"{r['invoice_number']} {r['service_name']} {r['customer_name']} {r['description']}".lower():
                        continue
                    sum_fee += int(r["service_fee"])
                    sum_side += int(r["side_cost"])
                    sum_net += int(r["net_profit"])
                    rem_srv = max(0, int(r["service_fee"]) - int(r["paid_amount"]))
                    rows_data.append(
                        [
                            r["invoice_number"],
                            r["service_datetime"],
                            r["service_type"],
                            r["service_name"],
                            r["emp_name"],
                            r["customer_name"] or "-",
                            f"{r['service_fee']:,}",
                            f"{r['side_cost']:,}",
                            f"{r['net_profit']:,}",
                            f"{r['paid_amount']:,}",
                            f"{rem_srv:,}",
                            r["settlement_status"],
                            r["description"] or "-",
                        ]
                    )
                summary_text = (
                    f"کل هزینه خدمات: {sum_fee:,} تومان   |   "
                    f"کل هزینه‌های جانبی: {sum_side:,} تومان   |   "
                    f"سود خالص خدمات: {sum_net:,} تومان"
                )

        if rows_data:
            date_columns = [
                index for index, header in enumerate(headers)
                if "تاریخ" in str(header) or "زمان" in str(header)
            ]
            if date_columns:
                date_column = date_columns[0]
                rows_data.sort(
                    key=lambda row: str(row[date_column] or ""), reverse=True
                )
        self.tbl_report.setSortingEnabled(False)
        self.tbl_report.clear()
        self.tbl_report.setColumnCount(len(headers))
        self.tbl_report.setHorizontalHeaderLabels(headers)
        for idx, h_text in enumerate(headers):
            h_item = self.tbl_report.horizontalHeaderItem(idx)
            if h_item:
                h_item.setToolTip(h_text)
        self._populate_table_safely(self.tbl_report, rows_data)
        self.lbl_rep_totals.setText(summary_text)

    def _export_current_report(self):
        # بند ۹: نام‌گذاری خودکار فایل بر اساس تاریخ روز (مثلاً R14050809_115300.xlsx)
        default_path = get_next_excel_filename(os.path.expanduser("~"), "R")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "ذخیره گزارش جامع در فایل اکسل",
            default_path,
            "Excel Files (*.xlsx)",
        )
        if not path:
            return
        headers = [
            self.tbl_report.horizontalHeaderItem(i).text()
            for i in range(self.tbl_report.columnCount())
        ]
        rows = []
        for r in range(self.tbl_report.rowCount()):
            rows.append(
                [
                    self.tbl_report.item(r, c).text()
                    if self.tbl_report.item(r, c)
                    else ""
                    for c in range(self.tbl_report.columnCount())
                ]
            )
        export_table_to_excel(
            self.cb_rep_type.currentText(),
            headers,
            rows,
            path,
            summary_text=self.lbl_rep_totals.text(),
            shop_name=(self.db.get_setting("shop_name", "فروشگاه من") or "فروشگاه من").strip(),
        )
        QMessageBox.information(
            self, "خروجی اکسل", f"فایل گزارش با موفقیت ذخیره شد:\n{path}"
        )

    # =========================================================================
    # ۹. تب مدیریت کارمندان (بند ۲ و ۱۱: رفع کامل باگ نمایش جدول کارمندان)
    # =========================================================================
    def _init_tab_employees(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.selected_emp_id = None

        gb = QGroupBox("مدیریت کارمندان، نقش‌ها، سطوح دسترسی و رمز ورود")
        grid = QGridLayout(gb)

        self.ed_emp_name = SmartLineEdit("نام و نام خانوادگی کارمند...")
        self.cb_emp_role = QComboBox()
        self.cb_emp_role.addItems(
            ["مدیر", "فروشنده", "مسئول خرید", "تکنسین فنی"]
        )
        self.ed_emp_phone = SmartLineEdit("شماره تماس...")
        self.ed_emp_old_pass = QLineEdit()
        self.ed_emp_old_pass.setEchoMode(QLineEdit.Password)
        self.ed_emp_old_pass.setPlaceholderText("فقط هنگام تغییر رمز وارد شود...")
        self.ed_emp_pass = QLineEdit()
        self.ed_emp_pass.setEchoMode(QLineEdit.Password)
        self.ed_emp_pass.setPlaceholderText("رمز عبور جدید...")
        self.cb_emp_perm = QComboBox()
        self.cb_emp_perm.addItems(
            [
                "دسترسی کامل (مدیر کل)",
                "مدیر ارشد (بدون مدیریت کارکنان)",
                "سرپرست عملیات (گزارش‌های محدود به عملکرد خود)",
                "فروش و خدمات (گزارش محدود به عملکرد خود)",
                "ثبت خرید و انبارداری (گزارش محدود به خریدهای خود)",
            ]
        )
        self.chk_emp_active = QCheckBox("کارمند فعال است")
        self.chk_emp_active.setChecked(True)

        grid.addWidget(QLabel("نام کارمند *:"), 0, 0)
        grid.addWidget(self.ed_emp_name, 0, 1)
        grid.addWidget(QLabel("نقش:"), 0, 2)
        grid.addWidget(self.cb_emp_role, 0, 3)
        grid.addWidget(QLabel("تلفن:"), 0, 4)
        grid.addWidget(self.ed_emp_phone, 0, 5)

        grid.addWidget(QLabel("رمز عبور فعلی:"), 1, 0)
        grid.addWidget(self.ed_emp_old_pass, 1, 1)
        grid.addWidget(QLabel("رمز عبور جدید:"), 1, 2)
        grid.addWidget(self.ed_emp_pass, 1, 3)
        grid.addWidget(QLabel("سطح دسترسی:"), 1, 4)
        grid.addWidget(self.cb_emp_perm, 1, 5)
        grid.addWidget(self.chk_emp_active, 2, 0, 1, 2)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("➕ افزودن کارمند جدید")
        btn_add.clicked.connect(self._add_employee)
        btn_edit = QPushButton("✏️ ذخیره ویرایش کارمند انتخابی")
        btn_edit.setObjectName("btnSuccess")
        btn_edit.clicked.connect(self._update_employee)
        btn_del = QPushButton("🗑️ حذف کارمند")
        btn_del.setObjectName("btnDanger")
        btn_del.clicked.connect(self._delete_employee)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_edit)
        btn_row.addWidget(btn_del)
        btn_remove_pass = QPushButton("🔒 حذف رمز عبور")
        btn_remove_pass.setObjectName("btnSecondary")
        btn_remove_pass.clicked.connect(self._remove_employee_password)
        btn_row.addWidget(btn_remove_pass)
        btn_row.addStretch()
        grid.addLayout(btn_row, 3, 0, 1, 6)

        layout.addWidget(gb)

        self.tbl_employees = self._create_table(
            [
                "شناسه",
                "نام کارمند",
                "نقش",
                "تلفن تماس",
                "سطح دسترسی",
                "دارای رمز عبور",
                "وضعیت فعالیت",
            ]
        )
        self.tbl_employees.itemSelectionChanged.connect(self._on_emp_selected)
        self._add_table_search(btn_row, self.tbl_employees, "employees", "🔍 جست‌وجو در کارکنان...")
        layout.addWidget(self.tbl_employees)

        self._add_scrollable_tab(tab, "👤 مدیریت کارمندان")

    def _add_employee(self):
        name = self.ed_emp_name.text().strip()
        if not name:
            QMessageBox.warning(self, "خطا", "نام کارمند را وارد کنید.")
            return
        raw_pass = normalize_digits(self.ed_emp_pass.text().strip())
        if self.db.cfg.get("require_login_password", False) and self.chk_emp_active.isChecked() and not raw_pass:
            QMessageBox.warning(
                self, "رمز عبور لازم است",
                "تا زمانی که اجبار رمز عبور فعال است، کارمند فعال باید هنگام ثبت رمز تعیین کند."
            )
            return
        hashed = hash_password(raw_pass) if raw_pass else ""
        try:
            with self.db.get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO employees (name, role, phone, password, permissions, is_active)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        name,
                        self.cb_emp_role.currentText(),
                        self.ed_emp_phone.text().strip(),
                        hashed,
                        self.cb_emp_perm.currentText(),
                        1 if self.chk_emp_active.isChecked() else 0,
                    ),
                )
                conn.commit()
            self.ed_emp_name.clear()
            self.ed_emp_phone.clear()
            self.ed_emp_pass.clear()
            self.refresh_all_data()
        except Exception as e:
            QMessageBox.critical(self, "خطا در ثبت کارمند", str(e))

    def _on_emp_selected(self):
        items = self.tbl_employees.selectedItems()
        if not items:
            return
        r = items[0].row()
        self.selected_emp_id = int(self.tbl_employees.item(r, 0).text())
        with self.db.get_connection() as conn:
            emp = conn.execute(
                "SELECT * FROM employees WHERE id=?", (self.selected_emp_id,)
            ).fetchone()
            if emp:
                self.ed_emp_name.setText(emp["name"])
                self.cb_emp_role.setCurrentText(emp["role"])
                self.ed_emp_phone.setText(emp["phone"] or "")
                # مورد ۵: رمز عبور هرگز در فیلد بازخوانی و نمایش داده نمی‌شود
                self.ed_emp_pass.clear()
                self.cb_emp_perm.setCurrentText(emp["permissions"] or "")
                self.chk_emp_active.setChecked(emp["is_active"] == 1)

    def _update_employee(self):
        if not self.selected_emp_id:
            return
        old_raw = normalize_digits(self.ed_emp_old_pass.text().strip())
        new_raw = normalize_digits(self.ed_emp_pass.text().strip())

        with self.db.get_connection() as conn:
            emp = conn.execute(
                "SELECT password FROM employees WHERE id=?", (self.selected_emp_id,)
            ).fetchone()
            if not emp:
                return
            saved_hash = emp["password"] or ""
            if (
                self.db.cfg.get("require_login_password", False)
                and self.chk_emp_active.isChecked()
                and not saved_hash
                and not new_raw
            ):
                QMessageBox.warning(
                    self, "رمز عبور لازم است",
                    "این کارمند فعال باید پیش از ذخیره اطلاعات، رمز عبور دریافت کند."
                )
                return

            # مورد ۴: اگر کاربر قصد تغییر رمز (یا ثبت رمز جدید برای کارمند دارای رمز) را دارد، رمز فعلی الزامی است
            if new_raw:
                if saved_hash:
                    if not old_raw:
                        QMessageBox.warning(
                            self,
                            "نیاز به رمز فعلی",
                            "برای تغییر رمز عبور، لطفاً ابتدا «رمز عبور فعلی» این کارمند را وارد کنید.",
                        )
                        return
                    if hash_password(old_raw) != saved_hash and old_raw != saved_hash:
                        QMessageBox.critical(
                            self, "خطا", "رمز عبور فعلی وارد شده نادرست است!"
                        )
                        return

                conn.execute(
                    """
                    UPDATE employees SET name=?, role=?, phone=?, password=?, permissions=?, is_active=?
                    WHERE id=?
                """,
                    (
                        self.ed_emp_name.text().strip(),
                        self.cb_emp_role.currentText(),
                        self.ed_emp_phone.text().strip(),
                        hash_password(new_raw),
                        self.cb_emp_perm.currentText(),
                        1 if self.chk_emp_active.isChecked() else 0,
                        self.selected_emp_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE employees SET name=?, role=?, phone=?, permissions=?, is_active=?
                    WHERE id=?
                """,
                    (
                        self.ed_emp_name.text().strip(),
                        self.cb_emp_role.currentText(),
                        self.ed_emp_phone.text().strip(),
                        self.cb_emp_perm.currentText(),
                        1 if self.chk_emp_active.isChecked() else 0,
                        self.selected_emp_id,
                    ),
                )
            conn.commit()
        self.ed_emp_old_pass.clear()
        self.ed_emp_pass.clear()
        self.refresh_all_data()
        QMessageBox.information(self, "ذخیره شد", "اطلاعات کارمند بروزرسانی شد.")

    def _remove_employee_password(self):
        if not self.selected_emp_id:
            QMessageBox.warning(self, "انتخاب کارمند", "ابتدا کارمند موردنظر را انتخاب کنید.")
            return
        current_password = normalize_digits(self.ed_emp_old_pass.text().strip())
        if not current_password:
            QMessageBox.warning(self, "رمز فعلی لازم است", "برای حذف رمز، وارد کردن رمز فعلی الزامی است.")
            return
        with self.db.get_connection() as conn:
            employee = conn.execute(
                "SELECT password FROM employees WHERE id=?", (self.selected_emp_id,)
            ).fetchone()
            if not employee or not employee["password"]:
                QMessageBox.information(self, "بدون رمز", "برای این کارمند رمزی ثبت نشده است.")
                return
            stored = employee["password"]
            if hash_password(current_password) != stored and current_password != stored:
                QMessageBox.warning(self, "رمز نادرست", "رمز فعلی واردشده صحیح نیست.")
                return
            conn.execute("UPDATE employees SET password='' WHERE id=?", (self.selected_emp_id,))
            conn.commit()
        self.ed_emp_old_pass.clear()
        self.ed_emp_pass.clear()
        self.refresh_all_data()
        QMessageBox.information(self, "رمز حذف شد", "رمز عبور پس از تأیید رمز فعلی حذف شد.")

    def _delete_employee(self):
        """مورد ۳: پنجره سه‌گزینه‌ای حذف کارمند"""
        if not self.selected_emp_id:
            QMessageBox.warning(self, "انتخاب کارمند", "ابتدا یک کارمند را از جدول انتخاب کنید.")
            return

        if self.active_employee and int(self.active_employee.get("id", -1)) == int(self.selected_emp_id):
            QMessageBox.warning(
                self, "کارمند فعال",
                "حساب کاربری فعال را نمی‌توان از همان نشست حذف کرد. ابتدا با حساب مدیریتی دیگری وارد شوید."
            )
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("حذف کارمند")
        msg.setText(
            "چگونه می‌خواهید این کارمند را حذف کنید؟\n"
            "(می‌توانید فقط نام کارمند را حذف کنید تا سوابق مالی و فاکتورها حفظ شوند، یا تمام داده‌های مرتبط با او را نیز حذف نمایید)"
        )
        btn_cancel = msg.addButton("انصراف", QMessageBox.RejectRole)
        btn_keep_data = msg.addButton(
            "حذف کارمند بدون حذف داده‌های مربوط به آن", QMessageBox.AcceptRole
        )
        btn_del_data = msg.addButton(
            "حذف کارمند و داده‌های مربوط به آن", QMessageBox.DestructiveRole
        )
        _center_message_buttons(msg)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == btn_cancel or clicked is None:
            return

        delete_all = clicked == btn_del_data
        try:
            self.db.delete_employee_custom(self.selected_emp_id, delete_related_data=delete_all)
            self.selected_emp_id = None
            self.ed_emp_name.clear()
            self.ed_emp_phone.clear()
            self.ed_emp_old_pass.clear()
            self.ed_emp_pass.clear()
            self.refresh_all_data()
            QMessageBox.information(self, "حذف شد", "عملیات حذف کارمند با موفقیت انجام شد.")
        except Exception as e:
            QMessageBox.critical(self, "خطا در حذف", str(e))

    # =========================================================================
    # ۱۰. تب تنظیمات و پشتیبان‌گیری
    # =========================================================================
    def _init_tab_settings(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignTop)

        gb_security = QGroupBox("امنیت و ورود کاربران")
        security_layout = QVBoxLayout(gb_security)
        self.chk_req_pass = QCheckBox(
            "اجبار ورود با رمز عبور برای تمام کارکنان فعال"
        )
        self.chk_req_pass.toggled.connect(self._confirm_password_policy_change)
        self.chk_req_pass.setToolTip(
            "در حالت فعال، تمام کارکنان فعال باید رمز داشته باشند و برای ورود آن را وارد کنند."
        )
        security_hint = QLabel(
            "پیش از فعال‌سازی، برای تمام کارکنان فعال رمز عبور تعیین کنید."
        )
        security_hint.setWordWrap(True)
        security_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        security_layout.addWidget(self.chk_req_pass)
        security_layout.addWidget(security_hint)
        gb_security.setTitle("")
        layout.addWidget(CollapsibleSection("امنیت و ورود کاربران", gb_security))

        gb_gen = QGroupBox("تنظیمات عمومی فروش و نمایش")
        f_gen = QFormLayout(gb_gen)
        f_gen.setContentsMargins(12, 12, 12, 10)
        f_gen.setHorizontalSpacing(14)
        f_gen.setVerticalSpacing(8)

        self.lbl_app_version = QLabel("نسخه برنامه: 1.0.0")
        self.lbl_app_version.setAlignment(Qt.AlignCenter)
        self.lbl_app_version.setStyleSheet("font-size: 13px; font-weight: 700; color: #1e3a8a; padding: 6px;")
        layout.addWidget(self.lbl_app_version)

        self.sp_set_profit = QSpinBox()
        self.sp_set_profit.setRange(0, 300)
        self.cb_zero_count = QComboBox()
        self.cb_zero_count.addItem("بدون صفر اضافی (۰)", "0")
        self.cb_zero_count.addItem("افزودن ۱ صفر (×۱۰)", "1")
        self.cb_zero_count.addItem("افزودن ۲ صفر (×۱۰۰)", "2")
        self.cb_zero_count.addItem("افزودن ۳ صفر (×۱٬۰۰۰)", "3")
        self.cb_zero_count.addItem("افزودن ۴ صفر (×۱۰٬۰۰۰)", "4")
        for zeros in (5, 6, 7, 8, 9, 10, 11, 12):
            self.cb_zero_count.addItem(
                f"افزودن {zeros} صفر (×{10 ** zeros:,})", str(zeros)
            )

        self.cb_win_mode = QComboBox()
        self.cb_win_mode.addItem("تمام‌صفحه", "1")
        self.cb_win_mode.addItem("پنجره معمولی", "0")
        self.ed_shop_name = QLineEdit()
        self.ed_shop_name.setAlignment(Qt.AlignRight)
        self.ed_shop_name.setLayoutDirection(Qt.RightToLeft)

        f_gen.addRow("درصد سود پیش‌فرض فروشگاه (%):", self.sp_set_profit)
        f_gen.addRow("تعداد صفرهای اضافی قیمت:", self.cb_zero_count)
        f_gen.addRow("حالت باز شدن پنجره:", self.cb_win_mode)
        f_gen.addRow("نام فروشگاه:", self.ed_shop_name)
        gb_gen.setTitle("")
        layout.addWidget(CollapsibleSection("تنظیمات عمومی فروش و نمایش", gb_gen))

        # Per-database product taxonomy and catalog customization.
        gb_catalog = QGroupBox("مدیریت دسته‌بندی‌ها، زیرمجموعه‌ها، مشخصات فنی و رنگ‌ها")
        catalog_grid = QGridLayout(gb_catalog)
        catalog_grid.setHorizontalSpacing(10)
        catalog_grid.setVerticalSpacing(8)

        gb_categories = QGroupBox("دسته‌بندی‌های اصلی")
        categories_layout = QVBoxLayout(gb_categories)
        self.cb_cfg_category = QComboBox()
        self.ed_cfg_category = QLineEdit()
        self.ed_cfg_category.setPlaceholderText("نام دسته‌بندی جدید یا نام جایگزین...")
        cat_btn_row = QHBoxLayout()
        btn_add_category = QPushButton("افزودن")
        btn_add_category.clicked.connect(self._add_catalog_category)
        btn_rename_category = QPushButton("تغییر نام")
        btn_rename_category.setObjectName("btnSecondary")
        btn_rename_category.clicked.connect(self._rename_catalog_category)
        btn_delete_category = QPushButton("حذف")
        btn_delete_category.setObjectName("btnDanger")
        btn_delete_category.clicked.connect(self._delete_catalog_category)
        cat_btn_row.addWidget(btn_add_category)
        cat_btn_row.addWidget(btn_rename_category)
        cat_btn_row.addWidget(btn_delete_category)
        categories_layout.addWidget(self.cb_cfg_category)
        categories_layout.addWidget(self.ed_cfg_category)
        categories_layout.addLayout(cat_btn_row)

        gb_subcategories = QGroupBox("زیرمجموعه‌های دستهٔ انتخاب‌شده")
        sub_layout = QVBoxLayout(gb_subcategories)
        self.lst_cfg_subcategories = SmoothScrollListWidget()
        self.lst_cfg_subcategories.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.lst_cfg_subcategories.verticalScrollBar().setSingleStep(18)
        self.lst_cfg_subcategories.setMaximumHeight(125)
        self.ed_cfg_subcategory = QLineEdit()
        self.ed_cfg_subcategory.setPlaceholderText("عنوان زیرمجموعه...")
        sub_btn_row = QHBoxLayout()
        btn_add_sub = QPushButton("افزودن")
        btn_add_sub.clicked.connect(self._add_catalog_subcategory)
        btn_rename_sub = QPushButton("تغییر نام")
        btn_rename_sub.setObjectName("btnSecondary")
        btn_rename_sub.clicked.connect(self._rename_catalog_subcategory)
        btn_delete_sub = QPushButton("حذف")
        btn_delete_sub.setObjectName("btnDanger")
        btn_delete_sub.clicked.connect(self._delete_catalog_subcategory)
        sub_btn_row.addWidget(btn_add_sub)
        sub_btn_row.addWidget(btn_rename_sub)
        sub_btn_row.addWidget(btn_delete_sub)
        sub_layout.addWidget(self.lst_cfg_subcategories)
        sub_layout.addWidget(self.ed_cfg_subcategory)
        sub_layout.addLayout(sub_btn_row)

        gb_attributes = QGroupBox("مشخصات فنی سفارشی")
        attr_layout = QVBoxLayout(gb_attributes)
        self.lst_cfg_attributes = SmoothScrollListWidget()
        self.lst_cfg_attributes.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.lst_cfg_attributes.verticalScrollBar().setSingleStep(18)
        self.lst_cfg_attributes.setMaximumHeight(125)
        self.ed_cfg_attribute_name = QLineEdit()
        self.ed_cfg_attribute_name.setPlaceholderText("نام ویژگی؛ مثلاً نوع پنل")
        self.ed_cfg_attribute_label = QLineEdit()
        self.ed_cfg_attribute_label.setPlaceholderText("عنوان مستقل در فرم ثبت؛ اختیاری")
        self.ed_cfg_attribute_display = QLineEdit()
        self.ed_cfg_attribute_display.setPlaceholderText("عنوان مستقل در جدول؛ اختیاری")
        self.ed_cfg_attribute_values = QLineEdit()
        self.ed_cfg_attribute_values.setPlaceholderText("مقادیر پیشنهادی با جداکنندهٔ ویرگول")
        self.cb_cfg_attribute_subcategory = QComboBox()
        self.cb_cfg_attribute_subcategory.addItem("همهٔ زیرمجموعه‌ها", "")
        attr_layout.addWidget(QLabel("محدودهٔ زیرمجموعه:"))
        attr_layout.addWidget(self.cb_cfg_attribute_subcategory)
        self.lst_cfg_attributes.currentItemChanged.connect(
            self._on_catalog_attribute_selected
        )
        attr_btn_row = QHBoxLayout()
        btn_add_attr = QPushButton("افزودن ویژگی")
        btn_add_attr.clicked.connect(self._add_catalog_attribute)
        btn_update_attr = QPushButton("ویرایش")
        btn_update_attr.setObjectName("btnSecondary")
        btn_update_attr.clicked.connect(self._update_catalog_attribute)
        btn_delete_attr = QPushButton("حذف ویژگی")
        btn_delete_attr.setObjectName("btnDanger")
        btn_delete_attr.clicked.connect(self._delete_catalog_attribute)
        attr_btn_row.addWidget(btn_add_attr)
        attr_btn_row.addWidget(btn_update_attr)
        attr_btn_row.addWidget(btn_delete_attr)
        attr_layout.addWidget(self.lst_cfg_attributes)
        attr_layout.addWidget(self.ed_cfg_attribute_name)
        attr_layout.addWidget(self.ed_cfg_attribute_label)
        attr_layout.addWidget(self.ed_cfg_attribute_display)
        attr_layout.addWidget(self.ed_cfg_attribute_values)
        attr_layout.addLayout(attr_btn_row)

        gb_colors = QGroupBox("رنگ‌های قابل انتخاب کالا")
        colors_layout = QVBoxLayout(gb_colors)
        self.lst_cfg_colors = SmoothScrollListWidget()
        self.lst_cfg_colors.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.lst_cfg_colors.verticalScrollBar().setSingleStep(18)
        self.lst_cfg_colors.setMaximumHeight(125)
        self.ed_cfg_color = QLineEdit()
        self.ed_cfg_color.setPlaceholderText("نام رنگ جدید...")
        color_btn_row = QHBoxLayout()
        btn_add_color = QPushButton("افزودن رنگ")
        btn_add_color.clicked.connect(self._add_catalog_color)
        btn_rename_color = QPushButton("تغییر نام")
        btn_rename_color.setObjectName("btnSecondary")
        btn_rename_color.clicked.connect(self._rename_catalog_color)
        btn_delete_color = QPushButton("حذف رنگ")
        btn_delete_color.setObjectName("btnDanger")
        btn_delete_color.clicked.connect(self._delete_catalog_color)
        color_btn_row.addWidget(btn_add_color)
        color_btn_row.addWidget(btn_rename_color)
        color_btn_row.addWidget(btn_delete_color)
        colors_layout.addWidget(self.lst_cfg_colors)
        colors_layout.addWidget(self.ed_cfg_color)
        colors_layout.addLayout(color_btn_row)

        gb_categories.setTitle("")
        catalog_grid.addWidget(CollapsibleSection("دسته‌بندی‌های اصلی", gb_categories), 0, 0)
        gb_subcategories.setTitle("")
        catalog_grid.addWidget(CollapsibleSection("زیرمجموعه‌ها", gb_subcategories), 0, 1)
        gb_attributes.setTitle("")
        catalog_grid.addWidget(CollapsibleSection("مشخصات فنی سفارشی", gb_attributes), 1, 0)
        gb_colors.setTitle("")
        catalog_grid.addWidget(CollapsibleSection("رنگ‌های قابل انتخاب", gb_colors), 1, 1)
        self.cb_cfg_category.currentTextChanged.connect(
            self._refresh_catalog_management_lists
        )
        gb_catalog.setTitle("")
        layout.addWidget(CollapsibleSection("مدیریت دسته‌بندی‌ها و مشخصات کالا", gb_catalog))

        gb_db = QGroupBox("پایگاه دادهٔ فعال و پشتیبان‌گیری خودکار")
        f_db = QFormLayout(gb_db)
        f_db.setContentsMargins(12, 12, 12, 10)
        f_db.setHorizontalSpacing(14)
        f_db.setVerticalSpacing(8)

        self.lbl_active_db_path = QLabel()
        self.lbl_active_db_path.setWordWrap(True)
        self.lbl_active_db_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_active_db_path.setFrameShape(QLabel.StyledPanel)
        self.lbl_active_db_path.setFrameShadow(QLabel.Sunken)
        self.lbl_active_db_path.setMargin(8)
        self.lbl_active_db_path.setStyleSheet("background: palette(base); border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px;")
        self.lst_recent_databases = SmoothScrollListWidget()
        self.lst_recent_databases.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.lst_recent_databases.verticalScrollBar().setSingleStep(18)
        self.lst_recent_databases.setMaximumHeight(190)
        self.lst_recent_databases.setToolTip(
            "برای اتصال از دکمهٔ «اتصال» استفاده کنید؛ علامت × فقط مسیر را از فهرست حذف می‌کند و فایل را پاک نمی‌کند."
        )

        db_btn_row = QHBoxLayout()
        btn_new_db = QPushButton("ایجاد پایگاه داده")
        btn_new_db.clicked.connect(self._create_and_connect_new_db)
        btn_open_existing_db = QPushButton("اتصال به پایگاه دادهٔ موجود")
        btn_open_existing_db.setObjectName("btnSecondary")
        btn_open_existing_db.clicked.connect(self._connect_existing_db)
        btn_open_db_dir = QPushButton("باز کردن پوشه")
        btn_open_db_dir.clicked.connect(self._open_db_folder)
        db_btn_row.addWidget(btn_new_db)
        db_btn_row.addWidget(btn_open_existing_db)
        db_btn_row.addWidget(btn_open_db_dir)

        self.chk_auto_bk = QCheckBox("پشتیبان‌گیری خودکار دوره‌ای فعال باشد")
        self.sp_bk_interval = QSpinBox()
        self.sp_bk_interval.setRange(1, 1440)
        self.sp_bk_interval.setSuffix(" دقیقه")
        self.sp_bk_interval.setKeyboardTracking(False)
        self.sp_bk_interval.setButtonSymbols(QSpinBox.NoButtons)

        self.sp_bk_retention = QSpinBox()
        self.sp_bk_retention.setRange(1, 100)
        self.sp_bk_retention.setSuffix(" نسخه")
        self.sp_bk_retention.setKeyboardTracking(False)
        self.sp_bk_retention.setButtonSymbols(QSpinBox.NoButtons)
        self.sp_bk_retention.setToolTip(
            "نسخهٔ جدید ابتدا در پوشهٔ Backups ساخته و بررسی می‌شود؛ سپس نسخه‌های قدیمی‌تر از سقف تعیین‌شده حذف می‌شوند."
        )

        bk_btn_row = QHBoxLayout()
        btn_manual_bk = QPushButton("پشتیبان‌گیری دستی")
        btn_manual_bk.setObjectName("btnSuccess")
        btn_manual_bk.clicked.connect(self._do_manual_backup)
        btn_restore_bk = QPushButton("بازیابی پشتیبان")
        btn_restore_bk.setObjectName("btnDanger")
        btn_restore_bk.clicked.connect(self._do_restore_backup)
        bk_btn_row.addWidget(btn_manual_bk)
        bk_btn_row.addWidget(btn_restore_bk)

        self.lbl_last_backup = QLabel()
        self.lbl_last_backup.setWordWrap(True)
        self.lbl_last_backup.setStyleSheet("color: #64748b;")

        f_db.addRow("مسیر پایگاه دادهٔ فعال:", self.lbl_active_db_path)
        f_db.addRow("فهرست پایگاه‌های داده:", self.lst_recent_databases)
        f_db.addRow(db_btn_row)
        f_db.addRow(self.chk_auto_bk)
        f_db.addRow("فاصلهٔ پشتیبان‌گیری خودکار:", self.sp_bk_interval)
        f_db.addRow("حداکثر نسخه‌های پشتیبان خودکار:", self.sp_bk_retention)
        f_db.addRow(bk_btn_row)
        f_db.addRow(self.lbl_last_backup)
        gb_db.setTitle("")
        layout.addWidget(CollapsibleSection("پایگاه داده و پشتیبان‌گیری", gb_db))

        btn_save_set = QPushButton("💾 ذخیره تنظیمات")
        self.btn_save_settings = btn_save_set
        btn_save_set.setMinimumHeight(42)
        btn_save_set.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_save_set.clicked.connect(self._save_general_settings)
        layout.addWidget(btn_save_set)

        self._settings_tab_index = self._add_scrollable_tab(
            tab, "⚙️ تنظیمات"
        )
        self._load_general_settings_form()

    def _load_general_settings_form(self):
        cfg = self.db.cfg
        self.chk_req_pass.setChecked(bool(cfg.get("require_login_password", False)))
        self.sp_set_profit.setValue(int(float(cfg.get("default_profit_pct", 20))))

        zero_count = str(cfg.get("zero_append_count", 3))
        zero_index = self.cb_zero_count.findData(zero_count)
        self.cb_zero_count.setCurrentIndex(zero_index if zero_index >= 0 else 0)
        self.cb_win_mode.setCurrentIndex(
            0 if bool(cfg.get("default_window_maximized", True)) else 1
        )
        self.ed_shop_name.setText(
            self.db.get_setting("shop_name", "فروشگاه من") or "فروشگاه من"
        )
        self.chk_auto_bk.setChecked(bool(cfg.get("auto_backup_enabled", True)))
        try:
            backup_interval = int(cfg.get("auto_backup_interval_min", 60))
        except (TypeError, ValueError):
            backup_interval = 60
        self.sp_bk_interval.setValue(max(1, min(1440, backup_interval)))
        self.sp_bk_retention.setValue(
            max(1, min(100, int(cfg.get("auto_backup_retention_count", 10))))
        )
        last_backup = cfg.get("last_backup_time", "ثبت نشده")
        warning = cfg.get("last_backup_warning", "")
        self.lbl_last_backup.setText(
            f"آخرین پشتیبان‌گیری: {last_backup}" + (f"\n{warning}" if warning else "")
        )
        self.lbl_last_backup.setToolTip(
            warning or f"مسیر نسخه‌های خودکار: {self.db.get_automatic_backup_directory()}"
        )
        self.lbl_active_db_path.setText(self.db.db_path)
        self._refresh_multi_db_combo()
        self._load_catalog_customization_form()

    def _load_catalog_customization_form(self):
        stored = self.db.get_product_catalog_config()
        defaults = {
            "categories": list(MAIN_CATEGORIES),
            "subcategories": copy.deepcopy(DEFAULT_SUBCATEGORIES),
            "attributes": copy.deepcopy(DEFAULT_ATTRIBUTES),
            "colors": [
                "مشکی", "سفید", "نقره‌ای", "خاکستری", "آبی",
                "قرمز", "طلایی", "سبز", "بنفش", "صورتی", "سایر",
            ],
        }
        has_saved_catalog = bool(self.db.get_setting("product_catalog_config", ""))
        self._taxonomy_draft = (
            copy.deepcopy(stored)
            if has_saved_catalog
            else copy.deepcopy(defaults)
        )
        self._pending_category_renames = []
        self._pending_subcategory_renames = []
        self._pending_attribute_renames = []
        self._pending_color_renames = []

        self.cb_cfg_category.blockSignals(True)
        self.cb_cfg_category.clear()
        self.cb_cfg_category.addItems(self._taxonomy_draft["categories"])
        self.cb_cfg_category.blockSignals(False)
        if self.cb_cfg_category.count():
            self.cb_cfg_category.setCurrentIndex(0)
        self._refresh_catalog_management_lists()

    def _refresh_catalog_management_lists(self, *_):
        if not hasattr(self, "_taxonomy_draft"):
            return
        category = self.cb_cfg_category.currentText().strip()
        self.lst_cfg_subcategories.clear()
        subcategories = self._taxonomy_draft["subcategories"].get(category, [])
        for value in subcategories:
            self.lst_cfg_subcategories.addItem(value)

        current_scope = self.cb_cfg_attribute_subcategory.currentData() or ""
        self.cb_cfg_attribute_subcategory.blockSignals(True)
        self.cb_cfg_attribute_subcategory.clear()
        self.cb_cfg_attribute_subcategory.addItem("همهٔ زیرمجموعه‌ها", "")
        for value in subcategories:
            self.cb_cfg_attribute_subcategory.addItem(value, value)
        scope_index = self.cb_cfg_attribute_subcategory.findData(current_scope)
        self.cb_cfg_attribute_subcategory.setCurrentIndex(
            scope_index if scope_index >= 0 else 0
        )
        self.cb_cfg_attribute_subcategory.blockSignals(False)

        self.lst_cfg_attributes.clear()
        for definition_index, item in enumerate(
            self._taxonomy_draft["attributes"].get(category, [])
        ):
            values = "، ".join(item.get("values", []))
            scope = item.get("subcategory") or "همهٔ زیرمجموعه‌ها"
            display_name = item.get("display_name") or item["name"]
            label = display_name + (f" — {values}" if values else "") + f"  [{scope}]"
            entry = QListWidgetItem(label)
            entry.setData(Qt.UserRole, definition_index)
            self.lst_cfg_attributes.addItem(entry)
        self.lst_cfg_colors.clear()
        for color in self._taxonomy_draft["colors"]:
            self.lst_cfg_colors.addItem(color)

    def _add_catalog_category(self):
        name = self.ed_cfg_category.text().strip()
        if not name:
            return
        categories = self._taxonomy_draft["categories"]
        if name in categories:
            QMessageBox.information(self, "دسته‌بندی موجود است", "این دسته‌بندی قبلاً ثبت شده است.")
            return
        categories.append(name)
        self.cb_cfg_category.addItem(name)
        self.cb_cfg_category.setCurrentText(name)
        self.ed_cfg_category.clear()

    def _rename_catalog_category(self):
        old = self.cb_cfg_category.currentText().strip()
        new = self.ed_cfg_category.text().strip()
        if not old or not new or old == new:
            return
        if new in self._taxonomy_draft["categories"]:
            QMessageBox.warning(self, "نام تکراری", "دسته‌بندی دیگری با این نام وجود دارد.")
            return
        index = self._taxonomy_draft["categories"].index(old)
        self._taxonomy_draft["categories"][index] = new
        if old in self._taxonomy_draft["subcategories"]:
            self._taxonomy_draft["subcategories"][new] = self._taxonomy_draft["subcategories"].pop(old)
        if old in self._taxonomy_draft["attributes"]:
            self._taxonomy_draft["attributes"][new] = self._taxonomy_draft["attributes"].pop(old)
        self._pending_category_renames.append((old, new))
        self._pending_subcategory_renames = [
            (new if category == old else category, old_sub, new_sub)
            for category, old_sub, new_sub in self._pending_subcategory_renames
        ]
        self._pending_attribute_renames = [
            (new if category == old else category, old_name, new_name, old_scope, new_scope)
            for category, old_name, new_name, old_scope, new_scope
            in self._pending_attribute_renames
        ]
        self.cb_cfg_category.setItemText(self.cb_cfg_category.currentIndex(), new)
        self.ed_cfg_category.clear()
        self._refresh_catalog_management_lists()

    def _delete_catalog_category(self):
        category = self.cb_cfg_category.currentText().strip()
        if not category or len(self._taxonomy_draft["categories"]) <= 1:
            return
        source_categories = {category}
        current_category = category
        for old_category, new_category in reversed(self._pending_category_renames):
            if current_category == new_category:
                source_categories.add(old_category)
                current_category = old_category
        category_marks = ",".join("?" for _ in source_categories)
        with self.db.get_connection() as conn:
            used = conn.execute(
                f"SELECT COUNT(*) FROM products WHERE category IN ({category_marks})",
                tuple(source_categories),
            ).fetchone()[0]
        if used:
            QMessageBox.warning(
                self, "دسته‌بندی در حال استفاده است",
                "برای حفظ سوابق کالاها، این دسته‌بندی حذف نمی‌شود. در صورت نیاز نام آن را تغییر دهید."
            )
            return
        self._taxonomy_draft["categories"].remove(category)
        self._taxonomy_draft["subcategories"].pop(category, None)
        self._taxonomy_draft["attributes"].pop(category, None)
        self.cb_cfg_category.removeItem(self.cb_cfg_category.currentIndex())
        self._refresh_catalog_management_lists()

    def _add_catalog_subcategory(self):
        category = self.cb_cfg_category.currentText().strip()
        name = self.ed_cfg_subcategory.text().strip()
        if not category or not name:
            return
        values = self._taxonomy_draft["subcategories"].setdefault(category, [])
        if name not in values:
            values.append(name)
        self.ed_cfg_subcategory.clear()
        self._refresh_catalog_management_lists()

    def _rename_catalog_subcategory(self):
        category = self.cb_cfg_category.currentText().strip()
        item = self.lst_cfg_subcategories.currentItem()
        new = self.ed_cfg_subcategory.text().strip()
        if not item or not new:
            return
        old = item.text()
        if old == new:
            return
        values = self._taxonomy_draft["subcategories"].setdefault(category, [])
        if new in values:
            QMessageBox.warning(self, "نام تکراری", "این زیرمجموعه قبلاً وجود دارد.")
            return
        values[values.index(old)] = new
        self._pending_subcategory_renames.append((category, old, new))
        self._pending_attribute_renames = [
            (
                pending_category,
                old_name,
                new_name,
                new if old_scope == old else old_scope,
                new if new_scope == old else new_scope,
            )
            for pending_category, old_name, new_name, old_scope, new_scope
            in self._pending_attribute_renames
        ]
        for definition in self._taxonomy_draft["attributes"].get(category, []):
            if (definition.get("subcategory") or "") == old:
                definition["subcategory"] = new
        self.ed_cfg_subcategory.clear()
        self._refresh_catalog_management_lists()

    def _delete_catalog_subcategory(self):
        category = self.cb_cfg_category.currentText().strip()
        item = self.lst_cfg_subcategories.currentItem()
        if not item:
            return
        name = item.text()
        source_categories = {category}
        current_category = category
        for old_category, new_category in reversed(self._pending_category_renames):
            if current_category == new_category:
                source_categories.add(old_category)
                current_category = old_category

        source_subcategories = {name}
        current_subcategory = name
        for pending_category, old_subcategory, new_subcategory in reversed(
            self._pending_subcategory_renames
        ):
            if pending_category in source_categories and current_subcategory == new_subcategory:
                source_subcategories.add(old_subcategory)
                current_subcategory = old_subcategory

        predicates = []
        parameters = []
        for source_category in source_categories:
            for source_subcategory in source_subcategories:
                predicates.append("(category=? AND sub_category=?)")
                parameters.extend((source_category, source_subcategory))
        with self.db.get_connection() as conn:
            used = conn.execute(
                "SELECT COUNT(*) FROM products WHERE " + " OR ".join(predicates),
                tuple(parameters),
            ).fetchone()[0]
        if used:
            QMessageBox.warning(
                self, "زیرمجموعه در حال استفاده است",
                "برای حفظ سوابق کالاها، این زیرمجموعه حذف نمی‌شود. ابتدا کالاهای مرتبط را اصلاح کنید."
            )
            return
        linked_attributes = [
            definition for definition in self._taxonomy_draft["attributes"].get(category, [])
            if (definition.get("subcategory") or "") == name
        ]
        if linked_attributes:
            QMessageBox.warning(
                self, "زیرمجموعه دارای ویژگی است",
                "ابتدا ویژگی‌های فنی متصل به این زیرمجموعه را حذف یا به زیرمجموعهٔ دیگری منتقل کنید."
            )
            return
        values = self._taxonomy_draft["subcategories"].get(category, [])
        if name in values:
            values.remove(name)
        self._refresh_catalog_management_lists()

    def _add_catalog_attribute(self):
        category = self.cb_cfg_category.currentText().strip()
        name = self.ed_cfg_attribute_name.text().strip()
        if not category or not name:
            QMessageBox.warning(self, "نام ویژگی لازم است", "نام مشخصهٔ فنی را وارد کنید.")
            return
        definitions = self._taxonomy_draft["attributes"].setdefault(category, [])
        selected_scope = self.cb_cfg_attribute_subcategory.currentData() or ""
        if any(
            item["name"] == name
            and (item.get("subcategory", "") or "") == selected_scope
            for item in definitions
        ):
            QMessageBox.warning(
                self, "ویژگی تکراری",
                "این مشخصه قبلاً برای همین زیرمجموعه ثبت شده است."
            )
            return
        values = [
            value.strip() for value in self.ed_cfg_attribute_values.text().replace("،", ",").split(",")
            if value.strip()
        ]
        definitions.append({
            "name": name,
            "label": self.ed_cfg_attribute_label.text().strip(),
            "display_name": self.ed_cfg_attribute_display.text().strip(),
            "values": list(dict.fromkeys(values)),
            "subcategory": selected_scope,
        })
        self.ed_cfg_attribute_name.clear()
        self.ed_cfg_attribute_label.clear()
        self.ed_cfg_attribute_display.clear()
        self.ed_cfg_attribute_values.clear()
        self._refresh_catalog_management_lists()

    def _on_catalog_attribute_selected(self, current, _previous=None):
        if not current:
            return
        category = self.cb_cfg_category.currentText().strip()
        definition_index = current.data(Qt.UserRole)
        definitions = self._taxonomy_draft["attributes"].get(category, [])
        definition = (
            definitions[definition_index]
            if isinstance(definition_index, int) and 0 <= definition_index < len(definitions)
            else None
        )
        if definition:
            self.ed_cfg_attribute_name.setText(definition["name"])
            self.ed_cfg_attribute_label.setText(definition.get("label", ""))
            self.ed_cfg_attribute_display.setText(definition.get("display_name", ""))
            self.ed_cfg_attribute_values.setText(", ".join(definition.get("values", [])))
            scope_index = self.cb_cfg_attribute_subcategory.findData(
                definition.get("subcategory", "") or ""
            )
            self.cb_cfg_attribute_subcategory.setCurrentIndex(
                scope_index if scope_index >= 0 else 0
            )

    def _update_catalog_attribute(self):
        category = self.cb_cfg_category.currentText().strip()
        selected = self.lst_cfg_attributes.currentItem()
        if not selected:
            QMessageBox.information(
                self, "انتخاب ویژگی", "ابتدا ویژگی موردنظر را از فهرست انتخاب کنید."
            )
            return

        definition_index = selected.data(Qt.UserRole)
        definitions = self._taxonomy_draft["attributes"].get(category, [])
        if not isinstance(definition_index, int) or not 0 <= definition_index < len(definitions):
            return

        current = definitions[definition_index]
        old_name = current.get("name", "")
        old_scope = current.get("subcategory", "") or ""
        new_name = self.ed_cfg_attribute_name.text().strip() or old_name
        new_scope = self.cb_cfg_attribute_subcategory.currentData() or ""
        if new_name != old_name and any(
            index != definition_index
            and item.get("name") == new_name
            and (item.get("subcategory", "") or "") == new_scope
            for index, item in enumerate(definitions)
        ):
            QMessageBox.warning(
                self, "نام تکراری",
                "ویژگی دیگری با همین نام برای این زیرمجموعه وجود دارد."
            )
            return

        raw_values = self.ed_cfg_attribute_values.text().replace("،", ",")
        values = [
            value.strip() for value in raw_values.split(",") if value.strip()
        ]
        if new_name != old_name:
            self._pending_attribute_renames.append(
                (category, old_name, new_name, old_scope, new_scope)
            )
        current["name"] = new_name
        current["label"] = self.ed_cfg_attribute_label.text().strip()
        current["display_name"] = self.ed_cfg_attribute_display.text().strip()
        current["values"] = list(dict.fromkeys(values))
        current["subcategory"] = new_scope
        self._refresh_catalog_management_lists()

    def _delete_catalog_attribute(self):
        category = self.cb_cfg_category.currentText().strip()
        item = self.lst_cfg_attributes.currentItem()
        if not item:
            return
        definition_index = item.data(Qt.UserRole)
        definitions = self._taxonomy_draft["attributes"].get(category, [])
        if isinstance(definition_index, int) and 0 <= definition_index < len(definitions):
            removed = definitions.pop(definition_index)
            removed_name = removed.get("name", "")
            self._pending_attribute_renames = [
                pending for pending in self._pending_attribute_renames
                if not (pending[0] == category and pending[2] == removed_name)
            ]
        self._refresh_catalog_management_lists()

    def _add_catalog_color(self):
        color = self.ed_cfg_color.text().strip()
        if color and color not in self._taxonomy_draft["colors"]:
            self._taxonomy_draft["colors"].append(color)
            self.ed_cfg_color.clear()
            self._refresh_catalog_management_lists()

    def _rename_catalog_color(self):
        item = self.lst_cfg_colors.currentItem()
        new_name = self.ed_cfg_color.text().strip()
        if not item or not new_name:
            return
        old_name = item.text()
        if new_name != old_name and new_name in self._taxonomy_draft["colors"]:
            QMessageBox.warning(self, "نام تکراری", "این رنگ قبلاً وجود دارد.")
            return
        index = self._taxonomy_draft["colors"].index(old_name)
        self._taxonomy_draft["colors"][index] = new_name
        self._pending_color_renames.append((old_name, new_name))
        self.ed_cfg_color.clear()
        self._refresh_catalog_management_lists()

    def _delete_catalog_color(self):
        item = self.lst_cfg_colors.currentItem()
        if item:
            color = item.text()
            self._taxonomy_draft["colors"] = [
                value for value in self._taxonomy_draft["colors"] if value != color
            ]
            self._refresh_catalog_management_lists()

    def _apply_product_catalog_config(self):
        self.catalog_config = self.db.get_product_catalog_config()
        categories = self.catalog_config.get("categories") or list(MAIN_CATEGORIES)
        categories = list(dict.fromkeys(categories))
        colors = self.catalog_config.get("colors", [
            "مشکی", "سفید", "نقره‌ای", "خاکستری", "آبی",
            "قرمز", "طلایی", "سبز", "سایر",
        ])
        current_category = self.cb_prod_cat.currentText() if hasattr(self, "cb_prod_cat") else ""
        if hasattr(self, "cb_prod_cat"):
            self.cb_prod_cat.blockSignals(True)
            self.cb_prod_cat.clear()
            self.cb_prod_cat.addItems(categories)
            if current_category:
                self.cb_prod_cat.setCurrentText(current_category)
            self.cb_prod_cat.blockSignals(False)
        if hasattr(self, "cb_prod_color"):
            current_color = self.cb_prod_color.currentText()
            self.cb_prod_color.blockSignals(True)
            self.cb_prod_color.clear()
            self.cb_prod_color.addItem("")
            self.cb_prod_color.addItems(colors)
            self.cb_prod_color.setCurrentText(current_color)
            self.cb_prod_color.blockSignals(False)
        if hasattr(self, "cb_rep_cat"):
            current_report_category = self.cb_rep_cat.currentText()
            self.cb_rep_cat.blockSignals(True)
            self.cb_rep_cat.clear()
            self.cb_rep_cat.addItem("همه دسته‌ها")
            self.cb_rep_cat.addItems(categories)
            report_index = self.cb_rep_cat.findText(current_report_category)
            self.cb_rep_cat.setCurrentIndex(report_index if report_index >= 0 else 0)
            self.cb_rep_cat.blockSignals(False)
        if hasattr(self, "specs_widget"):
            self._configure_product_specs(self.cb_prod_cat.currentText())

    def _configure_product_specs(self, category):
        if not hasattr(self, "specs_widget"):
            return
        category = (category or "").strip()
        # The widget invokes this callback after category-specific built-in controls
        # have been rebuilt; a parent currentIndexChanged slot can run too early.
        self.specs_widget.set_custom_field_callback(
            self._apply_custom_specs_for_subcategory
        )
        self.specs_widget.set_category(category)
        if hasattr(self, "catalog_config"):
            self.specs_widget.apply_custom_catalog(
                self.catalog_config.get("subcategories", {}).get(category),
                [],
            )
            self._apply_custom_specs_for_subcategory()

    def _apply_custom_specs_for_subcategory(self, *_):
        if not hasattr(self, "specs_widget") or self.specs_widget.cb_sub is None:
            return
        category = (self.cb_prod_cat.currentText() or "").strip()
        # SearchableComboBox normalizes Latin text to uppercase when reading its
        # Python-level currentText(). Match scopes case-insensitively so stored labels
        # such as "Graphic Card" remain compatible with the visible "GRAPHIC CARD".
        subcategory = QComboBox.currentText(self.specs_widget.cb_sub).strip()
        definitions = self.catalog_config.get("attributes", {}).get(category, [])
        applicable = [
            item for item in definitions
            if not str(item.get("subcategory") or "").strip()
            or str(item.get("subcategory") or "").strip().casefold() == subcategory.casefold()
        ]
        self.specs_widget.apply_custom_catalog(None, applicable)

    def _refresh_multi_db_combo(self):
        self._refresh_recent_database_list()

    def _refresh_recent_database_list(self):
        self.lst_recent_databases.clear()
        recents = self.db.cfg.get("recent_databases", [])
        active_path = os.path.abspath(self.db.db_path)
        ordered = []
        for path in [active_path] + list(reversed(recents)):
            if not path:
                continue
            normalized = os.path.abspath(path)
            if normalized not in ordered:
                ordered.append(normalized)
        self.db.cfg["recent_databases"] = ordered

        for database_path in ordered:
            row_item = QListWidgetItem()
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(5, 3, 5, 3)
            row_layout.setSpacing(6)

            is_active = os.path.normcase(database_path) == os.path.normcase(active_path)
            database_label = QLabel(os.path.basename(database_path))
            database_label.setToolTip(database_path)
            database_label.setMinimumWidth(100)
            database_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            if is_active:
                database_label.setStyleSheet("font-weight: bold; color: #059669;")

            btn_connect = QPushButton("فعال" if is_active else "اتصال")
            btn_connect.setEnabled(not is_active)
            btn_connect.setMaximumWidth(72)
            btn_connect.clicked.connect(
                lambda checked=False, target=database_path: self._switch_to_database_path(target)
            )

            btn_remove = QToolButton()
            btn_remove.setText("×")
            btn_remove.setToolTip("حذف مسیر از فهرست؛ فایل پایگاه داده پاک نمی‌شود")
            btn_remove.setFixedSize(28, 28)
            btn_remove.setEnabled(not is_active)
            btn_remove.setStyleSheet(
                "QToolButton { color: #dc2626; font-size: 18px; font-weight: bold; "
                "border-radius: 5px; background: transparent; }"
                "QToolButton:hover { background: rgba(220,38,38,0.12); }"
            )
            btn_remove.clicked.connect(
                lambda checked=False, target=database_path: self._remove_recent_database(target)
            )

            row_layout.addWidget(database_label, 1)
            row_layout.addWidget(btn_connect)
            row_layout.addWidget(btn_remove)
            row_item.setSizeHint(row_widget.sizeHint())
            self.lst_recent_databases.addItem(row_item)
            self.lst_recent_databases.setItemWidget(row_item, row_widget)

        save_app_config(self.db.cfg)

    def _remove_recent_database(self, database_path):
        active = os.path.normcase(os.path.abspath(self.db.db_path))
        target = os.path.normcase(os.path.abspath(database_path))
        if target == active:
            QMessageBox.information(
                self, "پایگاه دادهٔ فعال",
                "پایگاه دادهٔ فعال را نمی‌توان از فهرست حذف کرد."
            )
            return
        self.db.cfg["recent_databases"] = [
            path for path in self.db.cfg.get("recent_databases", [])
            if os.path.normcase(os.path.abspath(path)) != target
        ]
        save_app_config(self.db.cfg)
        self._refresh_recent_database_list()


    def _switch_to_database_path(self, target_path: str, *, create_if_missing=False):
        if not target_path:
            return
        target_path = os.path.abspath(os.path.expanduser(target_path))
        if os.path.normcase(os.path.abspath(self.db.db_path)) == os.path.normcase(target_path):
            return

        if os.path.isfile(target_path):
            if not _is_valid_sqlite_database_file(target_path):
                QMessageBox.warning(
                    self, "پایگاه داده نامعتبر",
                    "فایل انتخاب‌شده یک پایگاه دادهٔ سالم SQLite نیست."
                )
                return
            if create_if_missing:
                QMessageBox.warning(
                    self, "فایل از قبل وجود دارد",
                    "برای ایجاد پایگاه دادهٔ جدید، مسیر دیگری انتخاب کنید یا از گزینهٔ اتصال استفاده کنید."
                )
                return
        elif not create_if_missing:
            QMessageBox.warning(
                self, "فایل پیدا نشد",
                "فایل پایگاه دادهٔ انتخاب‌شده پیدا نشد؛ این مسیر از فهرست به‌صورت فایل جدید ساخته نمی‌شود."
            )
            return

        previous_path = self.db.db_path
        previous_config = copy.deepcopy(self.db.cfg)
        previous_employee = self.active_employee

        try:
            os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
            self.db.db_path = target_path
            self.db.cfg["db_path"] = target_path
            self.db.cfg["backup_dir"] = os.path.dirname(target_path) or "."
            recents = [
                os.path.abspath(path) for path in self.db.cfg.get("recent_databases", [])
                if path and os.path.normcase(os.path.abspath(path)) != os.path.normcase(target_path)
            ]
            self.db.cfg["recent_databases"] = [target_path] + recents
            self.db.init_db()
            self.db._migrate_legacy_application_settings()
        except Exception as exc:
            self.db.db_path = previous_path
            self.db.cfg = previous_config
            QMessageBox.critical(self, "خطا در اتصال", f"اتصال به پایگاه داده انجام نشد.\n{exc}")
            self._refresh_multi_db_combo()
            return

        selected_employee, accepted = _resolve_startup_employee(self.db, self)
        if not accepted:
            self.db.db_path = previous_path
            self.db.cfg = previous_config
            self.active_employee = previous_employee
            self._refresh_multi_db_combo()
            self._restart_backup_timer()
            return

        self.active_employee = selected_employee
        save_app_config(self.db.cfg)
        shop_name = (self.db.get_setting("shop_name", "فروشگاه من") or "فروشگاه من").strip()
        self.setWindowTitle(f"{shop_name} | سامانه حسابداری و مدیریت فروشگاه")
        self.lbl_store_name.setText(f"\u2067{shop_name}\u2069")
        self.lbl_store_name.setToolTip(f"نام فروشگاه: {shop_name}")

        self.catalog_config = self.db.get_product_catalog_config()
        self._apply_product_catalog_config()
        self._refresh_multi_db_combo()
        self._restart_backup_timer()
        self.refresh_all_data()
        self._load_general_settings_form()
        QMessageBox.information(
            self, "تغییر پایگاه داده",
            f"برنامه به پایگاه دادهٔ زیر متصل شد:\n{target_path}"
        )

    def _create_and_connect_new_db(self):
        default_path = os.path.join(
            os.path.dirname(os.path.abspath(self.db.db_path)), "NewShopDatabase.db"
        )
        new_path, _ = QFileDialog.getSaveFileName(
            self, "ایجاد فایل پایگاه دادهٔ جدید", default_path,
            "پایگاه داده SQLite (*.db)"
        )
        if new_path:
            self._switch_to_database_path(new_path, create_if_missing=True)

    def _connect_existing_db(self):
        ext_path, _ = QFileDialog.getOpenFileName(
            self, "انتخاب فایل پایگاه دادهٔ موجود", "",
            "پایگاه داده SQLite (*.db *.sqlite *.sqlite3)"
        )
        if ext_path:
            self._switch_to_database_path(ext_path)

    def _save_general_settings(self):
        requested_password_policy = self.chk_req_pass.isChecked()
        current_password_policy = bool(self.db.cfg.get("require_login_password", False))
        effective_password_policy = requested_password_policy

        if requested_password_policy:
            with self.db.get_connection() as conn:
                missing_passwords = conn.execute(
                    """SELECT name FROM employees
                       WHERE is_active=1 AND (password IS NULL OR TRIM(password)='')"""
                ).fetchall()
            if missing_passwords:
                names = "، ".join(row["name"] for row in missing_passwords[:6])
                suffix = " و ..." if len(missing_passwords) > 6 else ""
                QMessageBox.warning(
                    self,
                    "رمز عبور همه کارکنان لازم است",
                    "اجبار رمز عبور فعال می‌شود؛ کارکنان زیر تا زمان تعیین رمز عبور نمی‌توانند وارد برنامه شوند:\n"
                    + names + suffix,
                )
                # Enabling is permitted; users without a password are blocked at login
                # and asked to contact an administrator until a password is created.
                effective_password_policy = requested_password_policy

        try:
            # Apply taxonomy edits and persist the new configuration atomically.
            # Existing product rows are renamed only after the explicit Save action.
            with self.db.get_connection() as conn:
                for old_category, new_category in self._pending_category_renames:
                    conn.execute(
                        "UPDATE products SET category=? WHERE category=?",
                        (new_category, old_category),
                    )
                for category, old_subcategory, new_subcategory in self._pending_subcategory_renames:
                    conn.execute(
                        "UPDATE products SET sub_category=? WHERE category=? AND sub_category=?",
                        (new_subcategory, category, old_subcategory),
                    )

                for category, old_name, new_name, old_scope, _new_scope in self._pending_attribute_renames:
                    if not old_name or not new_name or old_name == new_name:
                        continue
                    if old_scope:
                        attribute_rows = conn.execute(
                            "SELECT id, specs_json FROM products WHERE category=? AND sub_category=?",
                            (category, old_scope),
                        ).fetchall()
                    else:
                        attribute_rows = conn.execute(
                            "SELECT id, specs_json FROM products WHERE category=?",
                            (category,),
                        ).fetchall()
                    for product_row in attribute_rows:
                        try:
                            specs = json.loads(product_row["specs_json"] or "{}")
                        except (TypeError, ValueError, json.JSONDecodeError):
                            continue
                        if not isinstance(specs, dict) or old_name not in specs:
                            continue
                        if new_name not in specs:
                            specs[new_name] = specs[old_name]
                        del specs[old_name]
                        conn.execute(
                            "UPDATE products SET specs_json=? WHERE id=?",
                            (json.dumps(specs, ensure_ascii=False), product_row["id"]),
                        )

                if self._pending_color_renames:
                    product_rows = conn.execute(
                        "SELECT id, specs_json FROM products"
                    ).fetchall()
                    for product_row in product_rows:
                        try:
                            specs = json.loads(product_row["specs_json"] or "{}")
                        except (TypeError, ValueError, json.JSONDecodeError):
                            continue
                        if not isinstance(specs, dict):
                            continue
                        changed = False
                        for old_color, new_color in self._pending_color_renames:
                            if specs.get("رنگ") == old_color:
                                specs["رنگ"] = new_color
                                changed = True
                        if changed:
                            conn.execute(
                                "UPDATE products SET specs_json=? WHERE id=?",
                                (json.dumps(specs, ensure_ascii=False), product_row["id"]),
                            )
                self.db.save_product_catalog_config(self._taxonomy_draft, conn=conn)
                conn.commit()

            self.db.cfg["default_profit_pct"] = self.sp_set_profit.value()
            self.db.cfg["zero_append_count"] = int(self.cb_zero_count.currentData())
            self.db.cfg["default_window_maximized"] = self.cb_win_mode.currentData() == "1"
            self.db.cfg["require_login_password"] = effective_password_policy

            shop_name = self.ed_shop_name.text().strip() or "فروشگاه من"
            self.db.set_setting("shop_name", shop_name)
            self.db.cfg["auto_backup_enabled"] = self.chk_auto_bk.isChecked()
            self.db.cfg["auto_backup_interval_min"] = self.sp_bk_interval.value()
            self.db.cfg["auto_backup_retention_count"] = self.sp_bk_retention.value()
            self.db.cfg["backup_dir"] = os.path.dirname(os.path.abspath(self.db.db_path)) or "."
            save_app_config(self.db.cfg)
        except Exception as exc:
            QMessageBox.critical(self, "خطا در ذخیره تنظیمات", str(exc))
            return

        self.setWindowTitle(f"{shop_name} | سامانه حسابداری و مدیریت فروشگاه")
        if hasattr(self, "lbl_store_name"):
            self.lbl_store_name.setText(f"\u2067{shop_name}\u2069")
            self.lbl_store_name.setToolTip(f"نام فروشگاه: {shop_name}")

        self._apply_product_catalog_config()
        self.refresh_all_data()
        self._refresh_multi_db_combo()
        self._restart_backup_timer()
        self._refresh_visual_layout()
        self._load_general_settings_form()
        QMessageBox.information(
            self, "ذخیره تنظیمات", "تنظیمات با موفقیت ذخیره شدند."
        )

    def _open_db_folder(self):
        folder = os.path.dirname(os.path.abspath(self.db.db_path))
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            subprocess.Popen(["xdg-open", folder])

    def _do_manual_backup(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "ذخیره فایل پشتیبان",
            f"Backup_{jdatetime.date.today().strftime('%Y%m%d')}.db",
            "پایگاه داده SQLite (*.db)",
        )
        if not path:
            return
        try:
            saved_path = self.db.create_backup(target_file=path)
            self.lbl_last_backup.setText(
                f"آخرین پشتیبان‌گیری: {self.db.cfg.get('last_backup_time')}"
            )
            QMessageBox.information(
                self, "پشتیبان‌گیری", f"نسخه پشتیبان به‌صورت امن ذخیره شد:\n{saved_path}"
            )
        except Exception as exc:
            QMessageBox.critical(self, "خطا در پشتیبان‌گیری", str(exc))


    def _do_restore_backup(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "انتخاب فایل پشتیبان", "", "پایگاه داده SQLite (*.db)"
        )
        if path:
            if (
                _ask_yes_no(
                    self,
                    "تأیید بازیابی",
                    "آیا از بازیابی اطلاعات مطمئن هستید؟ (از پایگاه دادهٔ فعلی به‌صورت خودکار نسخهٔ پشتیبان تهیه می‌شود)",
                )
                is True
            ):
                self.db.restore_backup(path)
                self.refresh_all_data()
                QMessageBox.information(
                    self, "بازیابی موفق", "اطلاعات با موفقیت بازیابی شدند."
                )

    # =========================================================================
    # متدهای بازخوانی و پر کردن امن جداول (رفع کامل باگ بند ۱۱)
    # =========================================================================
    def refresh_all_data(self):
        self._refresh_combos()
        self._refresh_products_table()
        self._refresh_batches_table()
        self._refresh_sales_table()
        self._refresh_upgrades_table()
        self._refresh_services_table()
        self._refresh_suppliers_table()
        self._refresh_employees_table()
        self._refresh_dashboard()
        self._update_report_live()
        self._apply_employee_permissions()
        if self._tables_auto_fit:
            self._reapply_auto_table_widths()

    def _refresh_combos(self):
        with self.db.get_connection() as conn:
            prods = conn.execute(
                "SELECT * FROM products WHERE is_active=1 ORDER BY updated_at DESC, id DESC"
            ).fetchall()
            emps = conn.execute(
                "SELECT * FROM employees WHERE is_active=1 ORDER BY updated_at DESC, id DESC"
            ).fetchall()
            if self._is_scoped_access() and self.active_employee:
                active_id = int(self.active_employee["id"])
                emps = [employee for employee in emps if int(employee["id"]) == active_id]
            if self._is_scoped_access() and self.active_employee:
                sups = conn.execute(
                    """SELECT DISTINCT s.* FROM suppliers s
                       JOIN batches b ON b.supplier_id=s.id
                       WHERE b.buyer_employee_id=? ORDER BY s.updated_at DESC, s.id DESC""",
                    (int(self.active_employee["id"]),),
                ).fetchall()
            else:
                sups = conn.execute(
                    "SELECT * FROM suppliers ORDER BY updated_at DESC, id DESC"
                ).fetchall()
            srvs = conn.execute(
                "SELECT * FROM service_catalog WHERE is_active=1 ORDER BY updated_at DESC, id DESC"
            ).fetchall()
            batches = conn.execute(
                """
                SELECT b.*, p.code AS p_code, p.category, p.sub_category, p.brand, p.model
                FROM batches b
                JOIN products p ON b.product_id=p.id
                ORDER BY b.updated_at DESC, b.id DESC
            """
            ).fetchall()
            sale_product_ids = {
                row["product_id"] for row in conn.execute(
                    "SELECT DISTINCT product_id FROM batches WHERE remaining_qty > 0"
                ).fetchall()
            }

        # بند ۳: قرار دادن دسته‌بندی و زیرگروه در متن آیتم‌های کمبوباکس کالا برای جست‌وجوی مستقیم (مثلاً تایپ «کیبورد»)
        self.cb_batch_prod.blockSignals(True)
        self.cb_sale_prod.blockSignals(True)
        self.cb_batch_prod.clear()
        self.cb_sale_prod.clear()
        for product_row in prods:
            product = dict(product_row)
            try:
                specs = json.loads(product.get("specs_json") or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                specs = {}
            if not isinstance(specs, dict):
                specs = {}
            specs_short = self._format_specs_for_display(specs, product.get("category"))
            product_description = str(product.get("description") or "")
            visible_label = bidi_isolate_text(self._format_product_picker_label(product))
            product_hover = (
                f"کد کالا: {product.get('code') or '-'}\n"
                f"دسته‌بندی اصلی: {product.get('category') or '-'}\n"
                f"زیرمجموعه: {product.get('sub_category') or '-'}\n"
                f"برند: {product.get('brand') or '-'}\n"
                f"مدل: {product.get('model') or '-'}\n"
                f"مشخصات نهایی:\n{self._format_specs_for_tooltip(specs, product.get('category')) or '-'}\n"
                f"توضیحات: {product_description or '-'}"
            )
            batch_index = self.cb_batch_prod.count()
            self.cb_batch_prod.addItem(visible_label, product)
            self.cb_batch_prod.setItemSearchText(
                batch_index,
                f"{product['category']} {product['sub_category']} {product['code']} "
                f"{product['brand']} {product['model']} {specs_short} {product_description}",
            )
            self.cb_batch_prod.setItemData(
                batch_index, bidi_isolate_text(product_hover), Qt.ToolTipRole
            )

            if int(product["id"]) in sale_product_ids:
                sale_label = bidi_isolate_text(self._format_product_picker_label(product))
                sale_index = self.cb_sale_prod.count()
                self.cb_sale_prod.addItem(sale_label, product)
                self.cb_sale_prod.setItemSearchText(
                    sale_index,
                    f"{product['category']} {product['sub_category']} {product['code']} "
                    f"{product['brand']} {product['model']} {specs_short} {product_description}",
                )
                self.cb_sale_prod.setItemData(
                    sale_index, bidi_isolate_text(product_hover), Qt.ToolTipRole
                )
        self.cb_batch_prod.blockSignals(False)
        self.cb_sale_prod.blockSignals(False)
        self._on_sale_prod_changed()

        for cb in (
            self.cb_batch_buyer,
            self.cb_sale_seller,
            self.cb_upg_tech,
            self.cb_srv_seller,
        ):
            cb.clear()
            for e in emps:
                cb.addItem(e["name"], e["id"])

        self.cb_rep_emp.blockSignals(True)
        self.cb_rep_emp.clear()
        self.cb_rep_emp.addItem("همه کارکنان", None)
        for e in emps:
            self.cb_rep_emp.addItem(e["name"], e["id"])
        self.cb_rep_emp.blockSignals(False)

        self.cb_batch_supplier.clear()
        for supplier_row in sups:
            supplier = dict(supplier_row)
            index = self.cb_batch_supplier.count()
            self.cb_batch_supplier.addItem(supplier["name"], supplier["id"])
            supplier_details = " | ".join(
                value for value in (
                    supplier.get("phone") or "",
                    supplier.get("address") or "",
                    supplier.get("notes") or "",
                ) if value
            )
            self.cb_batch_supplier.setItemData(
                index,
                f"{supplier['name']}\n{supplier_details}".strip(),
                Qt.ToolTipRole,
            )

        self.cb_srv_select.blockSignals(True)
        self.cb_srv_select.clear()
        for service_row in srvs:
            service = dict(service_row)
            label = (
                f"{service['name']} | {service['service_type']} | "
                f"{service['default_fee']:,} تومان"
            )
            index = self.cb_srv_select.count()
            self.cb_srv_select.addItem(bidi_isolate_text(label), service)
            self.cb_srv_select.setItemSearchText(
                index,
                f"{service['code']} {service['name']} {service['service_type']} "
                f"{service.get('description') or ''}",
            )
            self.cb_srv_select.setItemData(
                index,
                f"{label}\nکد خدمت: {service['code']}\nشرح: {service.get('description') or '-'}",
                Qt.ToolTipRole,
            )
        self.cb_srv_select.blockSignals(False)
        if srvs:
            self._on_srv_catalog_picked()

        self.cb_upg_target.clear()
        self.cb_upg_part.clear()
        for batch_row in batches:
            batch = dict(batch_row)
            product_title = self._format_product_picker_label(batch)
            label = (
                f"{batch['batch_code']} | {product_title} | "
                f"موجودی: {batch['remaining_qty']}"
            )
            searchable = (
                f"{label} {batch.get('initial_specs') or ''} "
                f"{batch.get('final_specs') or ''} {batch.get('serial_numbers') or ''}"
            ).strip()
            final_specs_dict, _tokens = self._parse_batch_specifications(
                batch.get("final_specs") or batch.get("initial_specs") or ""
            )
            final_specs_text = self._format_specs_for_display(
                final_specs_dict, batch.get("category")
            )
            tooltip = (
                f"کد محموله: {batch['batch_code']}\n"
                f"کد کالا: {batch.get('p_code') or '-'}\n"
                f"دسته‌بندی اصلی: {batch.get('category') or '-'}\n"
                f"زیرمجموعه: {batch.get('sub_category') or '-'}\n"
                f"برند: {batch.get('brand') or '-'}\n"
                f"مدل: {batch.get('model') or '-'}\n"
                f"موجودی: {batch['remaining_qty']}\n"
                f"قیمت پیشنهادی: {int(batch['suggested_sell_price']):,} تومان\n"
                f"مشخصات نهایی:\n{self._format_specs_for_tooltip(final_specs_dict, batch.get('category')) or final_specs_text or '-'}\n"
                f"شماره سریال: {batch.get('serial_numbers') or '-'}"
            )
            for combo in (self.cb_upg_target, self.cb_upg_part):
                item_index = combo.count()
                combo.addItem(bidi_isolate_text(label), batch["id"])
                combo.setItemSearchText(item_index, searchable)
                combo.setItemData(item_index, bidi_isolate_text(tooltip), Qt.ToolTipRole)
        self._on_upg_target_changed()

        if not self.selected_product_id and not self.ed_prod_code.text().strip():
            self.ed_prod_code.setPlaceholderText(self.db.generate_next_code("products", "code", "P-", 1001))
        if not self.selected_batch_id and not self.ed_batch_code.text().strip():
            self.ed_batch_code.setPlaceholderText(self.db.generate_next_code("batches", "batch_code", "C-", 1001))
        if not self.selected_sale_id and not self.ed_sale_inv.text().strip():
            self.ed_sale_inv.setPlaceholderText(self.db.generate_next_code("sales", "invoice_number", "INV-", 1001))
        if not self.selected_srv_cat_id and not self.ed_srv_code.text().strip():
            self.ed_srv_code.setPlaceholderText(self.db.generate_next_code("service_catalog", "code", "S-", 1001))

    def _refresh_products_table(self):
        q = self.ed_prod_search.text().strip().lower()
        with self.db.get_connection() as conn:
            rows = conn.execute("""
                SELECT p.*,
                       COALESCE(SUM(b.remaining_qty), 0) as rem_qty,
                       COALESCE(SUM(b.sold_qty), 0) as sold_qty
                FROM products p
                LEFT JOIN batches b ON p.id = b.product_id
                GROUP BY p.id ORDER BY p.updated_at DESC, p.id DESC
            """).fetchall()

        data = []
        for r in rows:
            specs = json.loads(r["specs_json"] or "{}")
            specs_str = self._format_specs_for_display(specs, r["category"])
            search_pool = f"{r['code']} {r['category']} {r['sub_category']} {r['brand']} {r['model']} {specs_str} {r['description']}".lower()
            if q and q not in search_pool:
                continue
            rem = int(r["rem_qty"])
            st = (
                "ناموجود"
                if rem <= 0
                else ("کم‌موجود" if rem <= r["reorder_point"] else "موجود")
            )
            data.append(
                [
                    r["id"],
                    r["code"],
                    r["category"],
                    r["sub_category"],
                    r["brand"],
                    r["model"],
                    specs_str,
                    rem,
                    r["sold_qty"],
                    r["reorder_point"],
                    r["default_profit_pct"],
                    st,
                    r["description"],
                ]
            )
        self._populate_table_safely(self.tbl_products, data, highlight_col=11)

    def _refresh_batches_table(self):
        with self.db.get_connection() as conn:
            rows = conn.execute("""
                SELECT b.*, p.code as p_code, p.category, p.sub_category, p.brand, p.model,
                       COALESCE(sup.name,b.supplier_name_snapshot) as sup_name, e.name as emp_name
                FROM batches b
                JOIN products p ON b.product_id=p.id
                LEFT JOIN suppliers sup ON b.supplier_id=sup.id
                LEFT JOIN employees e ON b.buyer_employee_id=e.id
                ORDER BY b.updated_at DESC, b.id DESC
            """).fetchall()
        data = []
        for r in rows:
            tot_bill = (r["unit_purchase_price"] * r["initial_qty"]) + r["extra_cost_total"]
            debt = max(0, tot_bill - r["paid_amount"])
            prod_title = self._format_product_picker_label(dict(r))
            data.append(
                [
                    r["id"],
                    r["batch_code"],
                    r["p_code"],
                    prod_title,
                    r["sup_name"] or "-",
                    r["emp_name"] or "-",
                    r["invoice_number"],
                    r["purchase_date"],
                    r["initial_qty"],
                    r["sold_qty"],
                    r["remaining_qty"],
                    f"{r['unit_purchase_price']:,}",
                    f"{r['extra_cost_total']:,}",
                    f"{r['upgrade_cost_unit']:,}",
                    f"{r['unit_cost_price']:,}",
                    f"{r['suggested_sell_price']:,}",
                    r["profit_pct"],
                    r["settlement_status"],
                    f"{r['paid_amount']:,}",
                    f"{debt:,}",
                    f"{r['final_specs']} {r['serial_numbers']}".strip(),
                    f"{tot_bill:,}",
                ]
            )
        self._populate_table_safely(self.tbl_batches, data, highlight_col=17)

    def _refresh_sales_table(self):
        with self.db.get_connection() as conn:
            rows = conn.execute("""
                SELECT s.*, p.code as p_code, p.category, p.sub_category, p.brand, p.model,
                       b.batch_code, b.final_specs, b.initial_specs, e.name as emp_name
                FROM sales s
                JOIN products p ON s.product_id=p.id
                JOIN batches b ON s.batch_id=b.id
                LEFT JOIN employees e ON s.seller_employee_id=e.id
                ORDER BY s.updated_at DESC, s.id DESC
            """).fetchall()
        data = []
        for r in rows:
            war_str = (
                f"{r['warranty_company']} ({r['warranty_end']})"
                if r["warranty_company"] or r["warranty_months"] or r["warranty_days"]
                else "-"
            )
            prod_title = f"{r['sub_category']} {r['brand']} {r['model']}".strip()
            signed_diff = format_Signed_diff(
                r["actual_unit_price"], r["suggested_unit_price"], r["qty"]
            )
            data.append(
                [
                    r["id"],
                    r["invoice_number"],
                    r["sale_datetime"],
                    r["p_code"],
                    prod_title,
                    r["batch_code"],
                    r["emp_name"],
                    r["customer_name"] or "-",
                    r["qty"],
                    f"{r['suggested_unit_price']:,}",
                    f"{r['actual_unit_price']:,}",
                    signed_diff,
                    f"{r['unit_cost_price']:,}",
                    f"{r['unit_profit']:,}",
                    f"{r['total_profit']:,}",
                    f"{r['total_amount']:,}",
                    f"{r['paid_amount']:,}",
                    r["settlement_status"],
                    war_str,
                    r["serial_number"] or "-",
                    r["specifications"] or r["final_specs"] or r["initial_specs"] or "-",
                ]
            )
        self._populate_table_safely(self.tbl_sales, data, highlight_col=11)

    def _refresh_upgrades_table(self):
        with self.db.get_connection() as conn:
            rows = conn.execute("""
                SELECT u.*,
                       b1.batch_code AS t_code,
                       b2.batch_code AS p_code,
                       p1.category AS target_category,
                       p1.brand AS target_brand,
                       p1.model AS target_model,
                       COALESCE(sup1.name, b1.supplier_name_snapshot) AS target_supplier,
                       p2.sub_category AS part_subcategory,
                       p2.brand AS part_brand,
                       p2.model AS part_model,
                       COALESCE(sup2.name, b2.supplier_name_snapshot) AS part_supplier,
                       e.name AS tech_name
                FROM upgrades u
                JOIN batches b1 ON u.target_batch_id=b1.id
                JOIN products p1 ON b1.product_id=p1.id
                LEFT JOIN batches b2 ON u.part_batch_id=b2.id
                LEFT JOIN products p2 ON b2.product_id=p2.id
                LEFT JOIN suppliers sup1 ON b1.supplier_id=sup1.id
                LEFT JOIN suppliers sup2 ON b2.supplier_id=sup2.id
                LEFT JOIN employees e ON u.technician_id=e.id
                ORDER BY u.updated_at DESC, u.id DESC
            """).fetchall()
        data = []
        for r in rows:
            data.append(
                [
                    r["id"],
                    r["t_code"],
                    r["target_qty"],
                    r["p_code"],
                    r["part_qty_used"],
                    f"{r['part_unit_cost']:,}",
                    f"{r['labor_cost_unit']:,}",
                    r["old_specs"],
                    r["new_specs"],
                    r["upgrade_date"],
                    r["tech_name"] or "-",
                    r["target_category"] or "-",
                    r["target_brand"] or "-",
                    r["target_model"] or "-",
                    r["target_supplier"] or "-",
                    r["p_code"] or r["manual_part_description"] or r["part_subcategory"] or "-",
                    r["part_brand"] or "-",
                    r["part_model"] or "-",
                    r["part_supplier"] or "-",
                    "کسر شد" if int(r["stock_deducted_qty"] or 0) > 0 else "بدون کسر موجودی",
                ]
            )
        self._populate_table_safely(self.tbl_upgrades, data)

    def _refresh_services_table(self):
        with self.db.get_connection() as conn:
            cat_rows = conn.execute(
                "SELECT * FROM service_catalog WHERE is_active=1 ORDER BY updated_at DESC, id DESC"
            ).fetchall()
            rec_rows = conn.execute("""
                SELECT sr.*, e.name as emp_name FROM service_records sr
                LEFT JOIN employees e ON sr.seller_employee_id=e.id
                ORDER BY sr.updated_at DESC, sr.id DESC
            """).fetchall()

        cat_data = [
            [
                r["id"],
                r["code"],
                r["service_type"],
                r["name"],
                f"{r['default_fee']:,}",
                f"{r['default_side_cost']:,}",
            ]
            for r in cat_rows
        ]
        self._populate_table_safely(self.tbl_srv_catalog, cat_data)

        rec_data = [
            [
                r["id"],
                r["invoice_number"],
                r["service_datetime"],
                r["service_type"],
                r["service_name"],
                r["emp_name"],
                r["customer_name"] or "-",
                f"{r['service_fee']:,}",
                format_Signed_diff(r["paid_amount"], r["service_fee"], 1),
                f"{r['side_cost']:,}",
                f"{r['net_profit']:,}",
                f"{r['paid_amount']:,}",
                r["settlement_status"],
                r["description"],
            ]
            for r in rec_rows
        ]
        self._populate_table_safely(self.tbl_services, rec_data, highlight_col=8)

    def _refresh_suppliers_table(self):
        with self.db.get_connection() as conn:
            rows = conn.execute("""
                SELECT s.*,
                       COUNT(b.id) as b_cnt,
                       COALESCE(SUM(b.unit_purchase_price*b.initial_qty + b.extra_cost_total), 0) as tot_buy,
                       COALESCE(SUM(b.paid_amount), 0) as tot_paid
                FROM suppliers s
                LEFT JOIN batches b ON s.id = b.supplier_id
                GROUP BY s.id
                ORDER BY s.updated_at DESC, s.id DESC
            """).fetchall()
        data = []
        for r in rows:
            debt = max(0, int(r["tot_buy"]) - int(r["tot_paid"]))
            data.append(
                [
                    r["id"],
                    r["name"],
                    r["phone"] or "-",
                    r["address"] or "-",
                    r["b_cnt"],
                    f"{int(r['tot_buy']):,}",
                    f"{int(r['tot_paid']):,}",
                    f"{debt:,}",
                ]
            )
        self._populate_table_safely(self.tbl_suppliers, data)

    def _refresh_employees_table(self):
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM employees ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        data = [
            [
                r["id"],
                r["name"],
                r["role"],
                r["phone"] or "-",
                r["permissions"],
                "بله" if r["password"] else "خیر",
                "فعال" if r["is_active"] else "غیرفعال",
            ]
            for r in rows
        ]
        self._populate_table_safely(self.tbl_employees, data)

    def _refresh_dashboard(self):
        today = jdatetime.date.today().strftime("%Y/%m/%d")
        scoped = self._is_scoped_access() and bool(self.active_employee)
        permissions = (self.active_employee.get("permissions") or "") if scoped else ""
        own_id = int(self.active_employee["id"]) if scoped else None
        sales_role = "فروش و خدمات" in permissions
        warehouse_role = "ثبت خرید و انبارداری" in permissions

        with self.db.get_connection() as conn:
            if scoped:
                # Restricted accounts receive aggregates for their own employee ID only.
                if warehouse_role:
                    sales_today = {"cnt": 0, "amt": 0, "prof": 0}
                    service_profit_today = 0
                else:
                    sales_today = conn.execute(
                        """SELECT COUNT(*) AS cnt, COALESCE(SUM(total_amount),0) AS amt,
                           COALESCE(SUM(total_profit),0) AS prof
                           FROM sales
                           WHERE substr(sale_datetime,1,10)=? AND seller_employee_id=?""",
                        (today, own_id),
                    ).fetchone()
                    service_profit_today = conn.execute(
                        """SELECT COALESCE(SUM(net_profit),0)
                           FROM service_records
                           WHERE substr(service_datetime,1,10)=?
                           AND (seller_employee_id=? OR technician_employee_id=?)""",
                        (today, own_id, own_id),
                    ).fetchone()[0]

                purchase_today = 0 if sales_role else conn.execute(
                    """SELECT COALESCE(SUM(unit_purchase_price*initial_qty+extra_cost_total),0)
                       FROM batches WHERE purchase_date=? AND buyer_employee_id=?""",
                    (today, own_id),
                ).fetchone()[0]

                employee_performance = conn.execute(
                    """SELECT e.name, COUNT(s.id) AS cnt,
                       COALESCE(SUM(s.total_amount),0) AS amt,
                       COALESCE(SUM(s.total_discount),0) AS disc,
                       COALESCE(SUM(s.total_profit),0) AS prof
                       FROM employees e LEFT JOIN sales s ON e.id=s.seller_employee_id
                       WHERE e.id=? GROUP BY e.id""",
                    (own_id,),
                ).fetchall()

                # Do not even query global stock, low-stock, or supplier-debt figures.
                low_products = []
                total_stock = None
                supplier_debt = None
            else:
                sales_today = conn.execute(
                    """SELECT COUNT(*) AS cnt, COALESCE(SUM(total_amount),0) AS amt,
                       COALESCE(SUM(total_profit),0) AS prof
                       FROM sales WHERE substr(sale_datetime,1,10)=?""",
                    (today,),
                ).fetchone()
                purchase_today = conn.execute(
                    """SELECT COALESCE(SUM(unit_purchase_price*initial_qty+extra_cost_total),0)
                       FROM batches WHERE purchase_date=?""",
                    (today,),
                ).fetchone()[0]
                service_profit_today = conn.execute(
                    """SELECT COALESCE(SUM(net_profit),0) FROM service_records
                       WHERE substr(service_datetime,1,10)=?""",
                    (today,),
                ).fetchone()[0]
                total_stock = conn.execute(
                    "SELECT COALESCE(SUM(remaining_qty),0) FROM batches"
                ).fetchone()[0]
                supplier_debt = conn.execute(
                    """SELECT COALESCE(SUM((unit_purchase_price*initial_qty+extra_cost_total)-paid_amount),0)
                       FROM batches"""
                ).fetchone()[0]
                low_products = conn.execute(
                    """SELECT p.code,p.category,p.sub_category,p.brand,p.model,p.reorder_point,
                       COALESCE(SUM(b.remaining_qty),0) AS rem
                       FROM products p LEFT JOIN batches b ON p.id=b.product_id
                       GROUP BY p.id HAVING rem<=p.reorder_point ORDER BY p.updated_at DESC, p.id DESC"""
                ).fetchall()
                employee_performance = conn.execute(
                    """SELECT e.name, COUNT(s.id) AS cnt,
                       COALESCE(SUM(s.total_amount),0) AS amt,
                       COALESCE(SUM(s.total_discount),0) AS disc,
                       COALESCE(SUM(s.total_profit),0) AS prof
                       FROM employees e LEFT JOIN sales s ON e.id=s.seller_employee_id
                       GROUP BY e.id ORDER BY e.updated_at DESC, e.id DESC"""
                ).fetchall()

        if scoped and warehouse_role:
            sales_today = {"cnt": 0, "amt": 0, "prof": 0}
            service_profit_today = 0

        self.lbl_dash_sales_today.setText(f"{int(sales_today['amt']):,}")
        self.lbl_dash_profit_today.setText(f"{int(sales_today['prof']):,}")
        self.lbl_dash_count_today.setText(str(sales_today["cnt"]))
        self.lbl_dash_buy_today.setText(f"{int(purchase_today):,}")
        self.lbl_dash_srv_profit.setText(f"{int(service_profit_today):,}")

        if scoped:
            self.lbl_dash_total_stock.setText("—")
            self.lbl_dash_low_stock.setText("—")
            self.lbl_dash_unpaid_supplier.setText("—")
        else:
            self.lbl_dash_total_stock.setText(f"{int(total_stock):,}")
            self.lbl_dash_low_stock.setText(str(len(low_products)))
            self.lbl_dash_unpaid_supplier.setText(f"{max(0, int(supplier_debt)):,}")

        low_data = []
        for row in low_products:
            status = "ناموجود" if int(row["rem"]) == 0 else "کم‌موجود"
            title = f"{row['brand']} {row['model']}".strip() or row["sub_category"]
            low_data.append([
                row["code"], title, row["category"], row["sub_category"],
                row["rem"], row["reorder_point"], status,
            ])
        self._populate_table_safely(self.tbl_dash_low, low_data, highlight_col=6)

        employee_data = [[
            row["name"], row["cnt"], f"{int(row['amt']):,}",
            f"{int(row['disc']):,}", f"{int(row['prof']):,}",
        ] for row in employee_performance]
        self._populate_table_safely(self.tbl_dash_emp, employee_data)




def main():
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    font = QFont("Tahoma", 10)
    app.setFont(font)

    selected_db_path = select_startup_database_path()
    if not selected_db_path:
        sys.exit(0)
    db = DatabaseManager(selected_db_path)

    active_emp = None
    active_emp, accepted = _resolve_startup_employee(db)
    if not accepted:
        sys.exit(0)

    win = MainWindow(db, active_emp)
    if bool(db.cfg.get("default_window_maximized", True)):
        win.showMaximized()
    else:
        win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
