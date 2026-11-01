# main.py
import os
import sys
import json
import subprocess
from datetime import timedelta
import jdatetime

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFormLayout,
    QTabWidget,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QFileDialog,
    QGroupBox,
    QComboBox,
    QCheckBox,
    QSpinBox,
    QDialog,
    QLineEdit,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor

from database import DatabaseManager, load_app_config, save_app_config, hash_password
from utils_and_widgets import (
    MAIN_CATEGORIES,
    SmartLineEdit,
    PriceInput,
    SearchableComboBox,
    QuantitySelector,
    JalaliDateEdit,
    DynamicSpecsWidget,
    add_jalali_months,
    add_jalali_days,
    normalize_digits,
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
        self.setWindowTitle("ورود به برنامه")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setFixedSize(360, 200)

        layout = QFormLayout(self)
        self.cb_emp = SearchableComboBox()
        with self.db.get_connection() as conn:
            emps = conn.execute(
                "SELECT * FROM employees WHERE is_active=1"
            ).fetchall()
            for e in emps:
                self.cb_emp.addItem(f"{e['name']} ({e['role']})", dict(e))

        self.ed_pass = QLineEdit()
        self.ed_pass.setEchoMode(QLineEdit.Password)
        self.ed_pass.setPlaceholderText("رمز عبور کارمند...")

        btn_login = QPushButton("ورود")
        btn_login.setStyleSheet(
            "background-color: #2563eb; color: white; padding: 8px; font-weight: bold;"
        )
        btn_login.clicked.connect(self._check_login)

        layout.addRow("انتخاب کارمند:", self.cb_emp)
        layout.addRow("رمز عبور:", self.ed_pass)
        layout.addRow(btn_login)

    def _check_login(self):
        emp = self.cb_emp.currentData()
        if not emp:
            return
        saved_hash = emp.get("password") or ""
        typed_raw = normalize_digits(self.ed_pass.text())
        if saved_hash:
            # پشتیبانی از هش SHA-256
            if hash_password(typed_raw) != saved_hash and typed_raw != saved_hash:
                QMessageBox.warning(self, "خطا", "رمز عبور وارد شده صحیح نیست!")
                return
        self.logged_employee = emp
        self.accept()


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
        self.resize(1360, 840)
        self._tables_auto_fit = False

        self._apply_styles()
        self._build_ui()
        self._setup_timers()
        self.refresh_all_data()
        self._apply_employee_permissions()

    def _switch_active_employee(self):
        dlg = LoginDialog(self.db, self)
        if dlg.exec() == QDialog.Accepted and dlg.logged_employee:
            self.active_employee = dlg.logged_employee
            self.lbl_active_user.setText(
                f"👤 کاربر فعال: {self.active_employee['name']} ({self.active_employee['role']})"
            )
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

    def _toggle_theme(self):
        self.db.cfg["theme"] = "dark" if self.db.cfg.get("theme", "light") != "dark" else "light"
        save_app_config(self.db.cfg)
        self._apply_styles()
        self.btn_theme.setText("☀️ تم روشن" if self.db.cfg["theme"] == "dark" else "🌙 تم تیره")

    def _toggle_table_autosize(self):
        self._tables_auto_fit = not self._tables_auto_fit
        for table in self.findChildren(QTableWidget):
            header = table.horizontalHeader()
            if self._tables_auto_fit:
                header.setSectionResizeMode(QHeaderView.ResizeToContents)
            else:
                header.setSectionResizeMode(QHeaderView.Interactive)
                header.setStretchLastSection(True)
        self.btn_table_width.setText(
            "↔️ بازگشت به اندازه ثابت ستون‌ها" if self._tables_auto_fit
            else "↔️ اندازه‌گذاری هوشمند ستون‌ها"
        )

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
            self.btn_switch_user.setEnabled(is_full or is_senior)


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

        # --- نوار بالای برنامه (ساعت زنده + دکمه همگام‌سازی اطلاعات + خروجی موجودی امن) ---
        top_bar = QWidget()
        top_bar.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0f172a, stop:1 #1e3a8a); border-radius: 8px; padding: 6px;"
        )
        top_layout = QHBoxLayout(top_bar)

        shop_name = (self.db.cfg.get("shop_name") or "فروشگاه من").strip()
        title_lbl = QLabel(f"💻 {shop_name} | مدیریت فروش، انبار و حسابداری")
        self.lbl_store_name = title_lbl
        title_lbl.setStyleSheet(
            "color: #ffffff; font-size: 15px; font-weight: bold; background: transparent;"
        )
        title_lbl.setToolTip("سامانه آفلاین مدیریت خرید، فروش، موجودی محموله‌ها و خدمات")

        self.lbl_live_clock = QLabel()
        self.lbl_live_clock.setStyleSheet(
            "color: #38bdf8; font-size: 13px; font-weight: bold; background: rgba(255,255,255,0.08); padding: 5px 12px; border-radius: 6px;"
        )

        # بند ۷: دکمه همگام‌سازی اطلاعات در بالای برنامه
        btn_sync = QPushButton("🔄 همگام‌سازی اطلاعات")
        btn_sync.setToolTip("همگام‌سازی کامل اطلاعات با پایگاه داده و بازخوانی تمامی لیست‌ها")
        btn_sync.setStyleSheet(
            "background-color: #0284c7; color: white; padding: 6px 12px; font-weight: bold; border-radius: 6px;"
        )
        btn_sync.clicked.connect(self._manual_sync_data)

        btn_safe_export = QPushButton("📤 خروجی موجودی امن")
        self.btn_safe_export = btn_safe_export
        btn_safe_export.setObjectName("btnSuccess")
        btn_safe_export.setToolTip(
            "تهیه فایل اکسل از کالاهای موجود در انبار بدون اطلاعات قیمت خرید و سود (مناسب ارسال به همکاران)"
        )
        btn_safe_export.clicked.connect(self._export_safe_inventory)

        # نمایش نام کارمند وارد شده در نوار بالای برنامه + امکان تغییر کاربر
        emp_name = self.active_employee["name"] if self.active_employee else "مدیر سیستم"
        emp_role = self.active_employee["role"] if self.active_employee else "دسترسی کامل"
        self.lbl_active_user = QLabel(f"👤 کاربر فعال: {emp_name} ({emp_role})")
        self.lbl_active_user.setStyleSheet(
            "color: #fde047; font-size: 13px; font-weight: bold; background: rgba(255,255,255,0.12); padding: 5px 12px; border-radius: 6px;"
        )
        btn_switch_user = QPushButton("🔑 تغییر کاربر")
        self.btn_switch_user = btn_switch_user
        btn_switch_user.setStyleSheet("background-color: #475569; color: white; padding: 6px 10px;")
        btn_switch_user.clicked.connect(self._switch_active_employee)
        self.btn_theme = QPushButton("☀️ تم روشن" if self.db.cfg.get("theme") == "dark" else "🌙 تم تیره")
        self.btn_theme.clicked.connect(self._toggle_theme)
        self.btn_table_width = QPushButton("↔️ اندازه‌گذاری هوشمند ستون‌ها")
        self.btn_table_width.setObjectName("btnSecondary")
        self.btn_table_width.clicked.connect(self._toggle_table_autosize)

        top_layout.addWidget(title_lbl)
        top_layout.addStretch()
        top_layout.addWidget(self.lbl_active_user)
        top_layout.addWidget(btn_switch_user)
        top_layout.addWidget(self.lbl_live_clock)
        top_layout.addWidget(btn_sync)
        top_layout.addWidget(btn_safe_export)
        top_layout.addWidget(self.btn_table_width)
        top_layout.addWidget(self.btn_theme)
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
        self._apply_employee_permissions()

    def _manual_sync_data(self):
        try:
            self.db.sync_database()
            self.refresh_all_data()
            QMessageBox.information(
                self,
                "همگام‌سازی اطلاعات",
                "تمامی اطلاعات با پایگاه داده همگام‌سازی و بروزرسانی شدند.",
            )
        except Exception as e:
            QMessageBox.critical(self, "خطا در همگام‌سازی", str(e))

    def _setup_timers(self):
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)

        self.backup_timer = QTimer(self)
        self.backup_timer.timeout.connect(self._run_periodic_backup)
        self._restart_backup_timer()

    def _restart_backup_timer(self):
        cfg = load_app_config()
        if cfg.get("auto_backup_enabled", True):
            mins = max(5, int(cfg.get("auto_backup_interval_min", 60)))
            self.backup_timer.start(mins * 60 * 1000)
        else:
            self.backup_timer.stop()

    def _run_periodic_backup(self):
        try:
            self.db.create_backup(automatic=True)
            if hasattr(self, "lbl_last_backup"):
                self.lbl_last_backup.setText(
                    f"آخرین پشتیبان‌گیری: {self.db.cfg.get('last_backup_time', '')}"
                )
        except Exception:
            pass

    def _update_clock(self):
        now = jdatetime.datetime.now()
        w_day = PERSIAN_WEEKDAYS.get(now.weekday(), "")
        date_str = now.strftime("%Y/%m/%d")
        time_str = now.strftime("%H:%M:%S")
        self.lbl_live_clock.setText(
            f"📅 {w_day}  {date_str}   |   ⏰ ساعت: {time_str}"
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
                export_safe_inventory_excel(self.db, path, (self.db.cfg.get("shop_name") or "").strip())
                QMessageBox.information(
                    self,
                    "ذخیره شد",
                    f"فایل «گزارش موجودی» با موفقیت ذخیره شد:\n{path}",
                )
            except Exception as e:
                QMessageBox.critical(self, "خطا", str(e))

    def _create_table(self, headers):
        tbl = QTableWidget(0, len(headers))
        tbl.setHorizontalHeaderLabels(headers)
        for idx, h_text in enumerate(headers):
            item = tbl.horizontalHeaderItem(idx)
            if item:
                item.setToolTip(h_text)
        tbl.setAlternatingRowColors(True)
        tbl.setSelectionBehavior(QTableWidget.SelectRows)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.setSortingEnabled(True)
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        tbl.horizontalHeader().setStretchLastSection(True)
        return tbl

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
                item = QTableWidgetItem(text_val)
                item.setToolTip(text_val)
                if highlight_col is not None and c_idx == highlight_col:
                    if text_val in ("ناموجود", "کم‌موجود", "تسویه‌نشده") or text_val.startswith("-"):
                        item.setForeground(QColor("#dc2626"))
                    elif text_val.startswith("+"):
                        item.setForeground(QColor("#059669"))
                table.setItem(r_idx, c_idx, item)
        table.setSortingEnabled(True)

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
        l_low.addWidget(self.tbl_dash_low)

        gb_emp = QGroupBox("👥 عملکرد فروشندگان")
        l_emp = QVBoxLayout(gb_emp)
        self.tbl_dash_emp = self._create_table(
            ["نام فروشنده", "تعداد فروش", "مبلغ کل فروش (تومان)", "تخفیف داده شده", "سود حاصل از فروش"]
        )
        l_emp.addWidget(self.tbl_dash_emp)

        split.addWidget(gb_low)
        split.addWidget(gb_emp)
        layout.addLayout(split)

        self.tabs.addTab(tab, "📊 داشبورد")

    def _make_stat_card(self, grid, r, c, title, val, color):
        box = QGroupBox()
        box.setToolTip(title)
        box.setStyleSheet(
            f"QGroupBox {{ border-right: 5px solid {color}; background: white; border-radius: 8px; padding: 8px; }}"
        )
        v = QVBoxLayout(box)
        t = QLabel(title)
        t.setToolTip(title)
        t.setStyleSheet("color: #64748b; font-size: 12px; font-weight: bold;")
        lbl_val = QLabel(val)
        lbl_val.setStyleSheet(
            f"color: {color}; font-size: 18px; font-weight: bold;"
        )
        v.addWidget(t)
        v.addWidget(lbl_val)
        grid.addWidget(box, r, c)
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
        # بند ۱ و ۲: کمبوباکس دسته‌بندی اصلی با قابلیت تایپ دستی برای کالاهای ناشناخته
        self.cb_prod_cat = SearchableComboBox()
        self.cb_prod_cat.addItems(MAIN_CATEGORIES)
        self.cb_prod_cat.setToolTip("دسته‌بندی اصلی را انتخاب کنید یا در صورت جدید بودن، مستقیم تایپ نمایید")

        self.ed_prod_brand = SmartLineEdit("مثلاً ASUS, Lenovo, HP, Logitech...")
        self.ed_prod_model = SmartLineEdit("مدل کالا (مثلاً G102, VivoBook 15...)")
        self.cb_prod_color = SearchableComboBox()
        self.cb_prod_color.addItems(
            ["", "مشکی", "سفید", "نقره‌ای", "خاکستری", "آبی", "قرمز", "طلایی", "سبز", "سایر"]
        )
        self.sp_prod_reorder = QSpinBox()
        self.sp_prod_reorder.setRange(0, 1000)
        self.sp_prod_reorder.setValue(3)
        self.sp_prod_reorder.setToolTip("اگر موجودی کالا به این عدد یا کمتر برسد، در داشبورد هشدار داده می‌شود")

        self.sp_prod_profit = QSpinBox()
        self.sp_prod_profit.setRange(0, 500)
        self.sp_prod_profit.setValue(
            int(float(self.db.get_setting("default_profit_pct", "20")))
        )
        self.sp_prod_profit.setToolTip("درصد سود پیش‌فرض برای محاسبه قیمت فروش پیشنهادی این کالا")
        self.ed_prod_desc = SmartLineEdit("توضیحات تکمیلی کالا...")

        f_layout.addRow("کد کالا (شناسه):", self.ed_prod_code)
        f_layout.addRow("دسته‌بندی اصلی (قابل تایپ) *:", self.cb_prod_cat)
        f_layout.addRow("برند کالا:", self.ed_prod_brand)
        f_layout.addRow("مدل کالا:", self.ed_prod_model)
        f_layout.addRow("رنگ کالا:", self.cb_prod_color)
        f_layout.addRow("حداقل موجودی (هشدار سفارش):", self.sp_prod_reorder)
        f_layout.addRow("درصد سود پیشنهادی (%):", self.sp_prod_profit)
        f_layout.addRow("توضیحات:", self.ed_prod_desc)

        self.specs_widget = DynamicSpecsWidget()
        self.cb_prod_cat.currentTextChanged.connect(self.specs_widget.set_category)

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

        self.tabs.addTab(tab, "📦 مدیریت کالاها")

    def _clear_product_form(self):
        self.selected_product_id = None
        self.ed_prod_code.setText(
            self.db.generate_next_code("products", "code", "P-", 1001)
        )
        self.ed_prod_brand.clear()
        self.ed_prod_model.clear()
        self.cb_prod_color.setCurrentText("")
        self.ed_prod_desc.clear()
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
            with self.db.get_connection() as conn:
                duplicate = conn.execute("SELECT id FROM products WHERE code=?", (code,)).fetchone()
            target_id = None
            if duplicate:
                msg = QMessageBox(self)
                msg.setWindowTitle("کد کالای تکراری")
                msg.setText(f"کد {code} قبلاً ثبت شده است. اطلاعات کالای قبلی جایگزین شود؟")
                btn_replace = msg.addButton("جایگزین کردن", QMessageBox.AcceptRole)
                msg.addButton("انصراف", QMessageBox.RejectRole)
                msg.exec()
                if msg.clickedButton() != btn_replace:
                    return
                target_id = int(duplicate["id"])
            args = (
                code, "", cat, sub, brand, model, specs_dict,
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
        self.specs_widget.set_category(cat_txt)
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
        specs_dict = self.specs_widget.get_specs_dict()
        color_val = self.cb_prod_color.currentText().strip()
        if color_val:
            specs_dict["رنگ"] = color_val
        if not self.selected_product_id:
            QMessageBox.warning(self, "انتخاب کالا", "ابتدا یک کالا را از جدول انتخاب کنید.")
            return
        try:
            self.db.update_product(
                self.selected_product_id,
                self.ed_prod_code.text().strip(),
                "",
                self.cb_prod_cat.currentText().strip() or "سایر موارد",
                self.specs_widget.get_sub_category(),
                self.ed_prod_brand.text().strip(),
                self.ed_prod_model.text().strip(),
                specs_dict,
                self.ed_prod_desc.text().strip(),
                self.sp_prod_reorder.value(),
                self.sp_prod_profit.value(),
            )
            self.refresh_all_data()
            QMessageBox.information(self, "ذخیره شد", "اطلاعات کالا با موفقیت اصلاح شد.")
        except Exception as e:
            QMessageBox.critical(self, "خطا", str(e))

    def _delete_selected_product(self):
        if not self.selected_product_id:
            return
        if (
            QMessageBox.question(self, "تأیید حذف", "آیا از حذف این کالا اطمینان دارید؟")
            == QMessageBox.Yes
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

        self.ed_batch_code = SmartLineEdit("C-1001")
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
        layout.addWidget(self.tbl_batches)

        self.tabs.addTab(tab, "🚚 ثبت خرید و محموله‌ها")

    def _on_batch_prod_changed(self):
        prod = self.cb_batch_prod.currentData()
        if prod:
            specs = json.loads(prod.get("specs_json") or "{}")
            specs_str = " | ".join(f"{k}:{v}" for k, v in specs.items())
            desc = (prod.get("description") or "").strip()
            combined = f"{specs_str} - {desc}".strip(" -") if desc else specs_str
            self.ed_batch_serial.setText(combined)
        self._recalc_batch_suggested()

    def _clear_batch_form(self):
        self.selected_batch_id = None
        self.ed_batch_code.setText(
            self.db.generate_next_code("batches", "batch_code", "C-", 1001)
        )
        self.ed_batch_inv.clear()
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
            else float(self.db.get_setting("default_profit_pct", "20"))
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
            with self.db.get_connection() as conn:
                duplicate = conn.execute("SELECT id FROM batches WHERE batch_code=?", (code,)).fetchone()
            if duplicate:
                msg = QMessageBox(self)
                msg.setWindowTitle("کد محموله تکراری")
                msg.setText(f"کد {code} قبلاً ثبت شده است. اطلاعات محموله قبلی جایگزین شود؟")
                btn_replace = msg.addButton("جایگزین کردن", QMessageBox.AcceptRole)
                msg.addButton("انصراف", QMessageBox.RejectRole)
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
                    code, prod["id"], *batch_values[:10],
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
            QMessageBox.question(
                self, "تأیید حذف", "آیا از حذف این محموله خرید اطمینان دارید؟"
            )
            == QMessageBox.Yes
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

        self.ed_sale_inv = SmartLineEdit("INV-1001")
        self.cb_sale_prod = SearchableComboBox()
        self.cb_sale_prod.setToolTip(
            "می‌توانید نام زیرگروه (مثلاً کیبورد، ماوس، مانیتور)، برند، مدل یا کد کالا را تایپ کنید"
        )
        self.cb_sale_prod.currentIndexChanged.connect(self._on_sale_prod_changed)
        self.cb_sale_batch = SearchableComboBox()
        self.cb_sale_batch.currentIndexChanged.connect(self._on_sale_batch_changed)
        self.cb_sale_seller = SearchableComboBox()
        self.ed_sale_customer = SmartLineEdit("نام مشتری (اختیاری)")
        self.cb_sale_qty = QuantitySelector(100)
        self.cb_sale_qty.qtyChanged.connect(self._recalc_sale_live)

        self.pr_sale_suggest = PriceInput(self.db)
        self.pr_sale_suggest.setReadOnly(True)
        self.pr_sale_suggest.setToolTip("قیمت پیشنهادی از بخش ثبت خرید و محموله‌ها دریافت می‌شود و در فاکتور فروش قابل تغییر نیست.")
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

        grid.addWidget(self.lbl_sale_summary, 5, 0, 1, 6)

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
            ]
        )
        self.tbl_sales.itemSelectionChanged.connect(self._on_sale_row_selected)
        layout.addWidget(self.tbl_sales)

        self.tabs.addTab(tab, "🛒 ثبت فروش")

    def _on_sale_prod_changed(self):
        prod = self.cb_sale_prod.currentData()
        self.cb_sale_batch.clear()
        if not prod:
            return
        with self.db.get_connection() as conn:
            batches = conn.execute(
                """
                SELECT * FROM batches
                WHERE product_id=? AND remaining_qty > 0
                ORDER BY id ASC
            """,
                (prod["id"],),
            ).fetchall()
            for b in batches:
                label = f"{b['batch_code']} | موجودی: {b['remaining_qty']} | خرید: {b['purchase_date']} | پیشنهادی: {b['suggested_sell_price']:,}"
                self.cb_sale_batch.addItem(label, dict(b))

    def _on_sale_batch_changed(self):
        b = self.cb_sale_batch.currentData()
        if not b:
            return
        self.cb_sale_qty.set_max_qty(b["remaining_qty"])
        sug = int(b["suggested_sell_price"])
        self.pr_sale_suggest.set_value(sug)
        self.pr_sale_actual.set_value(sug)
        self._recalc_sale_live()

    def _clear_sale_form(self):
        self.selected_sale_id = None
        self.ed_sale_inv.setText(
            self.db.generate_next_code("sales", "invoice_number", "INV-", 1001)
        )
        self.ed_sale_customer.clear()
        self.cb_sale_qty.setCurrentText("1")
        self.cb_sale_status.setCurrentIndex(0)
        self.ed_war_company.clear()
        self.cb_war_months.setCurrentIndex(0)
        self.ed_sale_serial.clear()
        self.tbl_sales.clearSelection()
        self._on_sale_batch_changed()

    def _on_sale_status_changed(self, st):
        tot = self.pr_sale_actual.get_value() * self.cb_sale_qty.get_qty()
        if st.startswith("تسویه‌شده"):
            self.pr_sale_paid.set_value(tot)
        elif st.startswith("تسویه‌نشده"):
            self.pr_sale_paid.set_value(0)

    def _on_suggest_edited_in_sale(self, val):
        self.pr_sale_actual.set_value(val)
        self._recalc_sale_live()

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
            )
            self.refresh_all_data()
            self.ed_sale_inv.setText(
                self.db.generate_next_code("sales", "invoice_number", "INV-", 1001)
            )
        except Exception as e:
            QMessageBox.critical(self, "خطا در ثبت فروش", str(e))

    def _on_sale_row_selected(self):
        items = self.tbl_sales.selectedItems()
        if not items:
            return
        r = items[0].row()
        self.selected_sale_id = int(self.tbl_sales.item(r, 0).text())
        self.ed_sale_inv.setText(self.tbl_sales.item(r, 1).text())
        self.ed_sale_customer.setText(self.tbl_sales.item(r, 7).text())
        self.cb_sale_qty.setCurrentText(self.tbl_sales.item(r, 8).text())
        self.pr_sale_suggest.set_value(
            int(self.tbl_sales.item(r, 9).text().replace(",", ""))
        )
        self.pr_sale_actual.set_value(
            int(self.tbl_sales.item(r, 10).text().replace(",", ""))
        )
        self.pr_sale_paid.set_value(
            int(self.tbl_sales.item(r, 16).text().replace(",", ""))
        )
        self.cb_sale_status.setCurrentText(self.tbl_sales.item(r, 17).text())
        self.ed_sale_serial.setText(self.tbl_sales.item(r, 19).text())

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
            )
            self.refresh_all_data()
            QMessageBox.information(self, "اصلاح فروش", "ردیف فروش با موفقیت اصلاح شد.")
        except Exception as e:
            QMessageBox.critical(self, "خطا", str(e))

    def _delete_selected_sale(self):
        if not self.selected_sale_id:
            return
        if (
            QMessageBox.question(
                self,
                "حذف فروش",
                "آیا از حذف این فروش و بازگرداندن کالا به موجودی انبار اطمینان دارید؟",
            )
            == QMessageBox.Yes
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
        self.cb_srv_type.addItems(["نرم‌افزاری", "سخت‌افزاری"])
        self.ed_srv_code = SmartLineEdit("S-1001")
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
        f_rec.addRow("کارمند انجام‌دهنده:", self.cb_srv_seller)
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
                "کارمند",
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
        layout.addWidget(self.tbl_services)
        self.tabs.addTab(tab, "🛠️ مدیریت خدمات")
        
    def _clear_service_cat_form(self):
        self.selected_srv_cat_id = None
        self.ed_srv_code.setText(self.db.generate_next_code("service_catalog", "code", "S-", 1001))
        self.ed_srv_name.clear()
        self.pr_srv_def_fee.set_value(0)
        self.pr_srv_def_side.set_value(0)
        self.tbl_srv_catalog.clearSelection()

    def _clear_service_rec_form(self):
        self.selected_srv_rec_id = None
        self.ed_srv_cust.clear()
        self.ed_srv_desc.clear()
        self.cb_srv_status.setCurrentIndex(0)
        self.tbl_services.clearSelection()
        self._on_srv_catalog_picked()

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
        """بند ۴: ثبت خدمت جدید بدون جایگزینی خدمات قبلی (مگر هم‌نام بودن دقیق)"""
        name = self.ed_srv_name.text().strip()
        if not name:
            QMessageBox.warning(self, "خطا", "عنوان خدمت را وارد کنید.")
            return
        code = self.ed_srv_code.text().strip()
        with self.db.get_connection() as conn:
            duplicate = conn.execute("SELECT id FROM service_catalog WHERE code=?", (code,)).fetchone()
        target_id = None
        if duplicate:
            msg = QMessageBox(self)
            msg.setWindowTitle("کد خدمت تکراری")
            msg.setText(f"کد {code} قبلاً ثبت شده است. اطلاعات خدمت قبلی جایگزین شود؟")
            btn_replace = msg.addButton("جایگزین کردن", QMessageBox.AcceptRole)
            msg.addButton("انصراف", QMessageBox.RejectRole)
            msg.exec()
            if msg.clickedButton() != btn_replace:
                return
            target_id = int(duplicate["id"])
        self.db.save_service_catalog(
            target_id, code, self.cb_srv_type.currentText(), name,
            self.pr_srv_def_fee.get_value(), self.pr_srv_def_side.get_value(), "",
        )
        self._clear_service_cat_form()
        self.refresh_all_data()

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
        self.cb_upg_part = SearchableComboBox()
        self.cb_upg_part_qty = QuantitySelector(10)
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
        grid.addWidget(QLabel("انجام‌دهنده:"), 3, 2)
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
                "انجام‌دهنده",
            ]
        )
        self.tbl_upgrades.itemSelectionChanged.connect(self._on_upgrade_selected)
        layout.addWidget(self.tbl_upgrades)
        self.tabs.addTab(tab, "🔧 ارتقای کالا")

    def _on_upg_target_changed(self):
        """مورد ۶: پر شدن خودکار کادر مشخصات جدید با مشخصات قبلی دستگاه جهت ویرایش راحت‌تر"""
        t_id = self.cb_upg_target.currentData()
        if not t_id:
            self.ed_upg_new_specs.clear()
            return
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT b.final_specs, b.initial_specs, p.specs_json
                FROM batches b JOIN products p ON b.product_id = p.id
                WHERE b.id = ?
            """,
                (t_id,),
            ).fetchone()
            if row:
                specs_txt = row["final_specs"] or row["initial_specs"]
                if not specs_txt and row["specs_json"]:
                    d = json.loads(row["specs_json"] or "{}")
                    specs_txt = " | ".join(f"{k}:{v}" for k, v in d.items())
                self.ed_upg_new_specs.setText(specs_txt or "")

    def _save_upgrade(self):
        t_id = self.cb_upg_target.currentData()
        p_id = self.cb_upg_part.currentData()
        if not t_id or not p_id:
            QMessageBox.warning(
                self, "خطا", "محموله کالای هدف و محموله قطعه مصرفی را انتخاب کنید."
            )
            return
        try:
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
            )
            self.refresh_all_data()
            QMessageBox.information(
                self, "ثبت شد", "ارتقای کالا با موفقیت ثبت گردید."
            )
        except Exception as e:
            QMessageBox.critical(self, "خطا در ارتقا", str(e))

    def _clear_upgrade_form(self):
        self.selected_upgrade_id = None
        self.tbl_upgrades.clearSelection()
        self.cb_upg_target.setCurrentIndex(0)
        self.cb_upg_part.setCurrentIndex(0)
        self.cb_upg_target_qty.setCurrentText("1")
        self.cb_upg_part_qty.setCurrentText("1")
        self.pr_upg_labor.set_value(0)
        self.ed_upg_serial.clear()
        self.chk_upg_add_cost.setChecked(False)
        self.dt_upg_date.set_date(jdatetime.date.today().strftime("%Y/%m/%d"))
        self._on_upg_target_changed()

    def _on_upgrade_selected(self):
        items = self.tbl_upgrades.selectedItems()
        if not items:
            return
        row_index = items[0].row()
        self.selected_upgrade_id = int(self.tbl_upgrades.item(row_index, 0).text())
        with self.db.get_connection() as conn:
            upgrade = conn.execute(
                "SELECT * FROM upgrades WHERE id=?", (self.selected_upgrade_id,)
            ).fetchone()
        if not upgrade:
            self._clear_upgrade_form()
            return
        target_index = self.cb_upg_target.findData(int(upgrade["target_batch_id"]))
        part_index = self.cb_upg_part.findData(int(upgrade["part_batch_id"]))
        if target_index >= 0:
            self.cb_upg_target.setCurrentIndex(target_index)
        if part_index >= 0:
            self.cb_upg_part.setCurrentIndex(part_index)
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
            QMessageBox.question(
                self,
                "تأیید برگشت ارتقا",
                "آیا از برگشت این ارتقا، بازگرداندن قطعه به موجودی انبار و بازگشت مشخصات قبلی کالا اطمینان دارید؟",
            )
            == QMessageBox.Yes
        ):
            try:
                self.db.revert_upgrade(upg_id)
                self.refresh_all_data()
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
        layout.addWidget(self.tbl_suppliers)
        self.tabs.addTab(tab, "💳 تأمین‌کنندگان و بدهی‌ها")

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

        self.dt_rep_from = JalaliDateEdit(default_today=False)
        self.dt_rep_from.set_date("1395/01/01")
        self.dt_rep_to = JalaliDateEdit(default_today=True)

        self.cb_rep_emp = SearchableComboBox()
        self.cb_rep_cat = SearchableComboBox()
        self.cb_rep_cat.addItems(["همه دسته‌ها"] + MAIN_CATEGORIES)
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
        self.dt_rep_from.dateChanged.connect(self._update_report_live)
        self.dt_rep_to.dateChanged.connect(self._update_report_live)
        self.cb_rep_emp.currentIndexChanged.connect(self._update_report_live)
        self.cb_rep_cat.currentTextChanged.connect(self._update_report_live)
        self.ed_rep_search.textChanged.connect(self._update_report_live)

        self.tabs.addTab(tab, "📈 گزارش‌های جامع")

    def _on_rep_preset_changed(self):
        preset = self.cb_rep_preset.currentText()
        today_j = jdatetime.date.today()
        today_g = today_j.togregorian()

        if preset == "همه زمان‌ها":
            self.dt_rep_from.set_date("1395/01/01")
            self.dt_rep_to.set_date("1450/12/29")
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
                ]
                s_rows = conn.execute("""
                    SELECT 'فروش کالا' as t_type, s.invoice_number as ref, s.sale_datetime as dt,
                           p.code, p.category, p.sub_category, (p.brand || ' ' || p.model) as title,
                           e.id as emp_id, e.name as emp_name, s.customer_name as party,
                           s.qty, s.actual_unit_price as u_price, s.suggested_unit_price as sug_price,
                           (s.unit_cost_price * s.qty) as cost_total, s.total_amount as amt,
                           s.paid_amount as paid, s.total_profit as prof, s.settlement_status as st
                    FROM sales s
                    JOIN products p ON s.product_id=p.id
                    LEFT JOIN employees e ON s.seller_employee_id=e.id
                """).fetchall()

                b_rows = conn.execute("""
                    SELECT 'خرید محموله' as t_type, b.batch_code as ref, b.purchase_date as dt,
                           p.code, p.category, p.sub_category, (p.brand || ' ' || p.model) as title,
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
                           sr.service_name as title, e.id as emp_id, e.name as emp_name,
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
                ]
                q = conn.execute("""
                    SELECT s.*, p.code, p.category, p.sub_category, p.brand, p.model,
                           b.batch_code, e.name as emp_name
                    FROM sales s
                    JOIN products p ON s.product_id=p.id
                    JOIN batches b ON s.batch_id=b.id
                    LEFT JOIN employees e ON s.seller_employee_id=e.id
                    ORDER BY s.id DESC
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
                    ORDER BY b.id DESC
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
                    ORDER BY p.code ASC
                """).fetchall()
                sum_stock, sum_prof = 0, 0
                for r in q:
                    if cat and cat != "همه دسته‌ها" and r["category"] != cat:
                        continue
                    rem = int(r["rem_qty"])
                    if rep_type.startswith("۸.") and rem > int(r["reorder_point"]):
                        continue
                    specs = json.loads(r["specs_json"] or "{}")
                    specs_str = " | ".join(f"{k}:{v}" for k, v in specs.items())
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
                    "کارمند انجام‌دهنده",
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
                    ORDER BY sr.id DESC
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
            shop_name=(self.db.cfg.get("shop_name") or "").strip(),
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
            ["مدیر / فروشنده", "فروشنده", "مسئول خرید", "تکنسین فنی"]
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
        layout.addWidget(self.tbl_employees)

        self.tabs.addTab(tab, "👤 مدیریت کارمندان")

    def _add_employee(self):
        name = self.ed_emp_name.text().strip()
        if not name:
            QMessageBox.warning(self, "خطا", "نام کارمند را وارد کنید.")
            return
        raw_pass = normalize_digits(self.ed_emp_pass.text().strip())
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

        gb_gen = QGroupBox("تنظیمات قیمت‌گذاری، صفرهای خودکار و پنجره‌ها")
        f_gen = QFormLayout(gb_gen)

        self.sp_set_profit = QSpinBox()
        self.sp_set_profit.setRange(0, 300)
        self.sp_set_profit.setValue(
            int(float(self.db.get_setting("default_profit_pct", "20")))
        )

        self.chk_zero_enabled = QCheckBox(
            "افزودن خودکار صفر به اعداد وارد شده در کادرهای قیمت"
        )
        self.chk_zero_enabled.setChecked(
            self.db.get_setting("zero_append_enabled", "1") == "1"
        )
        self.cb_zero_count = QComboBox()
        self.cb_zero_count.addItem("بدون صفر اضافی (0)", "0")
        self.cb_zero_count.addItem("افزودن ۲ صفر (ضرب در 100)", "2")
        self.cb_zero_count.addItem(
            "افزودن ۳ صفر (مثلاً تایپ 300 -> 300,000 تومان)", "3"
        )
        self.cb_zero_count.addItem("افزودن ۴ صفر (ضرب در 10,000)", "4")
        for zeros in (5, 6, 8, 10, 12):
            self.cb_zero_count.addItem(f"افزودن {zeros} صفر", str(zeros))
        cur_z = self.db.get_setting("zero_append_count", "3")
        idx_z = self.cb_zero_count.findData(cur_z)
        if idx_z >= 0:
            self.cb_zero_count.setCurrentIndex(idx_z)

        self.cb_win_mode = QComboBox()
        self.cb_win_mode.addItem("تمام‌صفحه (Maximized)", "1")
        self.cb_win_mode.addItem("پنجره معمولی (Normal)", "0")
        if self.db.get_setting("default_window_maximized", "1") == "0":
            self.cb_win_mode.setCurrentIndex(1)

        self.chk_req_pass = QCheckBox(
            "درخواست رمز عبور کارمند هنگام شروع برنامه (اختیاری)"
        )
        self.chk_req_pass.setChecked(
            self.db.get_setting("require_login_password", "0") == "1"
        )

        self.ed_shop_name = QLineEdit(self.db.cfg.get("shop_name") or "فروشگاه من")
        self.ed_shop_name.setAlignment(Qt.AlignRight)
        self.ed_shop_name.setLayoutDirection(Qt.RightToLeft)

        f_gen.addRow("درصد سود پیش‌فرض فروشگاه (%):", self.sp_set_profit)
        f_gen.addRow(self.chk_zero_enabled)
        f_gen.addRow("تعداد صفرهای خودکار قیمت:", self.cb_zero_count)
        f_gen.addRow("حالت باز شدن پنجره برنامه:", self.cb_win_mode)
        f_gen.addRow(self.chk_req_pass)
        f_gen.addRow("نام فروشگاه:", self.ed_shop_name)
        layout.addWidget(gb_gen)

        # مورد ۹: مدیریت و اتصال به چند پایگاه داده مختلف + پشتیبان‌گیری
        gb_db = QGroupBox("مدیریت چند پایگاه داده (اتصال، ایجاد دیتابیس جدید و پشتیبان‌گیری)")
        f_db = QFormLayout(gb_db)

        self.cb_multi_db = QComboBox()
        self._refresh_multi_db_combo()
        self.cb_multi_db.currentIndexChanged.connect(self._on_switch_multi_db)

        db_btn_row = QHBoxLayout()
        btn_new_db = QPushButton("➕ ایجاد دیتابیس جدید (مثلاً سال مالی جدید)")
        btn_new_db.clicked.connect(self._create_and_connect_new_db)
        btn_open_existing_db = QPushButton("🔗 اتصال به فایل دیتابیس موجود")
        btn_open_existing_db.setObjectName("btnSecondary")
        btn_open_existing_db.clicked.connect(self._connect_existing_db)
        btn_open_db_dir = QPushButton("📂 باز کردن پوشه دیتابیس فعلی")
        btn_open_db_dir.clicked.connect(self._open_db_folder)
        db_btn_row.addWidget(btn_new_db)
        db_btn_row.addWidget(btn_open_existing_db)
        db_btn_row.addWidget(btn_open_db_dir)

        self.chk_auto_bk = QCheckBox("پشتیبان‌گیری خودکار دوره‌ای فعال باشد")
        self.chk_auto_bk.setChecked(
            self.db.cfg.get("auto_backup_enabled", True)
        )
        self.sp_bk_interval = QSpinBox()
        self.sp_bk_interval.setRange(5, 1440)
        self.sp_bk_interval.setValue(
            int(self.db.cfg.get("auto_backup_interval_min", 60))
        )
        self.sp_bk_interval.setKeyboardTracking(False)
        self.sp_bk_interval.setButtonSymbols(QSpinBox.NoButtons)

        bk_btn_row = QHBoxLayout()
        btn_manual_bk = QPushButton("🛡️ تهیه نسخه پشتیبان دستی")
        btn_manual_bk.setObjectName("btnSuccess")
        btn_manual_bk.clicked.connect(self._do_manual_backup)
        btn_restore_bk = QPushButton("♻️ بازیابی اطلاعات از بکاپ")
        btn_restore_bk.setObjectName("btnDanger")
        btn_restore_bk.clicked.connect(self._do_restore_backup)
        bk_btn_row.addWidget(btn_manual_bk)
        bk_btn_row.addWidget(btn_restore_bk)

        self.lbl_last_backup = QLabel(
            f"آخرین پشتیبان‌گیری: {self.db.cfg.get('last_backup_time', 'ثبت نشده')}"
        )

        f_db.addRow("پایگاه داده فعال (انتخاب از لیست دیتابیس‌ها):", self.cb_multi_db)
        f_db.addRow(db_btn_row)
        f_db.addRow(self.chk_auto_bk)
        f_db.addRow("فاصله زمانی بکاپ خودکار (دقیقه):", self.sp_bk_interval)
        f_db.addRow(bk_btn_row)
        f_db.addRow(self.lbl_last_backup)
        layout.addWidget(gb_db)
        layout.addStretch()
        btn_save_set = QPushButton("💾 ذخیره تنظیمات")
        btn_save_set.clicked.connect(self._save_general_settings)
        layout.addWidget(btn_save_set, 0, Qt.AlignBottom | Qt.AlignRight)

        self.tabs.addTab(tab, "⚙️ تنظیمات و پشتیبان‌گیری")

    def _refresh_multi_db_combo(self):
        self.cb_multi_db.blockSignals(True)
        self.cb_multi_db.clear()
        recents = self.db.cfg.get("recent_databases", [self.db.db_path])
        if self.db.db_path not in recents:
            recents.append(self.db.db_path)
        for p in recents:
            self.cb_multi_db.addItem(p, p)
        idx = self.cb_multi_db.findData(self.db.db_path)
        if idx >= 0:
            self.cb_multi_db.setCurrentIndex(idx)
        self.cb_multi_db.blockSignals(False)

    def _switch_to_database_path(self, target_path: str):
        if not target_path:
            return
        self.db.db_path = target_path
        self.db.cfg["db_path"] = target_path
        recents = self.db.cfg.get("recent_databases", [])
        if target_path not in recents:
            recents.append(target_path)
        self.db.cfg["recent_databases"] = recents
        save_app_config(self.db.cfg)
        self.db.init_db()
        self.setWindowTitle(f"{self.db.cfg.get('shop_name') or 'فروشگاه من'} | سامانه حسابداری و مدیریت فروشگاه")
        self.lbl_store_name.setText(f"💻 {self.db.cfg.get('shop_name') or 'فروشگاه من'} | مدیریت فروش، انبار و حسابداری")
        self._refresh_multi_db_combo()
        self.refresh_all_data()
        QMessageBox.information(
            self, "تغییر پایگاه داده", f"برنامه با موفقیت به پایگاه داده زیر متصل شد:\n{target_path}"
        )

    def _on_switch_multi_db(self):
        path = self.cb_multi_db.currentData()
        if path and path != self.db.db_path:
            self._switch_to_database_path(path)

    def _create_and_connect_new_db(self):
        new_path, _ = QFileDialog.getSaveFileName(
            self, "ایجاد فایل پایگاه داده جدید", "NewShopDatabase.db", "SQLite DB (*.db)"
        )
        if new_path:
            self._switch_to_database_path(new_path)

    def _connect_existing_db(self):
        ext_path, _ = QFileDialog.getOpenFileName(
            self, "انتخاب فایل پایگاه داده موجود", "", "SQLite DB (*.db)"
        )
        if ext_path:
            self._switch_to_database_path(ext_path)

    def _save_general_settings(self):
        self.db.set_setting("default_profit_pct", self.sp_set_profit.value())
        self.db.set_setting(
            "zero_append_enabled", "1" if self.chk_zero_enabled.isChecked() else "0"
        )
        self.db.set_setting("zero_append_count", self.cb_zero_count.currentData())
        self.db.set_setting(
            "default_window_maximized", self.cb_win_mode.currentData()
        )
        self.db.set_setting(
            "require_login_password", "1" if self.chk_req_pass.isChecked() else "0"
        )

        self.db.cfg["shop_name"] = self.ed_shop_name.text().strip() or "فروشگاه من"
        self.db.cfg["auto_backup_enabled"] = self.chk_auto_bk.isChecked()
        self.db.cfg["auto_backup_interval_min"] = self.sp_bk_interval.value()
        save_app_config(self.db.cfg)
        self.setWindowTitle(f"{self.db.cfg['shop_name']} | سامانه حسابداری و مدیریت فروشگاه")
        if hasattr(self, "lbl_store_name"):
            self.lbl_store_name.setText(f"💻 {self.db.cfg['shop_name']} | مدیریت فروش، انبار و حسابداری")
        self._restart_backup_timer()
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
            "Database (*.db)",
        )
        if path:
            import shutil

            shutil.copy2(self.db.db_path, path)
            self.db.create_backup()
            self.lbl_last_backup.setText(
                f"آخرین پشتیبان‌گیری: {self.db.cfg.get('last_backup_time')}"
            )
            QMessageBox.information(
                self, "پشتیبان‌گیری", f"نسخه پشتیبان ذخیره شد:\n{path}"
            )

    def _do_restore_backup(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "انتخاب فایل پشتیبان", "", "Database (*.db)"
        )
        if path:
            if (
                QMessageBox.question(
                    self,
                    "تأیید بازیابی",
                    "آیا از بازیابی اطلاعات مطمئن هستید؟ (از دیتابیس فعلی به طور خودکار بکاپ گرفته می‌شود)",
                )
                == QMessageBox.Yes
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

    def _refresh_combos(self):
        with self.db.get_connection() as conn:
            prods = conn.execute(
                "SELECT * FROM products WHERE is_active=1 ORDER BY code ASC"
            ).fetchall()
            emps = conn.execute(
                "SELECT * FROM employees WHERE is_active=1 ORDER BY id DESC"
            ).fetchall()
            if self._is_scoped_access() and self.active_employee:
                active_id = int(self.active_employee["id"])
                emps = [employee for employee in emps if int(employee["id"]) == active_id]
            sups = conn.execute(
                "SELECT * FROM suppliers ORDER BY id DESC"
            ).fetchall()
            srvs = conn.execute(
                "SELECT * FROM service_catalog WHERE is_active=1 ORDER BY id DESC"
            ).fetchall()
            batches = conn.execute(
                """
                SELECT b.*, p.category, p.sub_category, p.brand, p.model
                FROM batches b
                JOIN products p ON b.product_id=p.id
                WHERE b.remaining_qty > 0
                ORDER BY b.id DESC
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
        for p in prods:
            specs = json.loads(p["specs_json"] or "{}")
            specs_short = " ".join(str(v) for v in specs.values())
            lbl = (
                f"{p['code']} | {p['category']} - {p['sub_category']} | "
                f"{p['brand']} {p['model']} {specs_short}".strip()
            )
            self.cb_batch_prod.addItem(lbl, dict(p))
            if int(p["id"]) in sale_product_ids:
                self.cb_sale_prod.addItem(lbl, dict(p))
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
        for s in sups:
            self.cb_batch_supplier.addItem(s["name"], s["id"])

        self.cb_srv_select.blockSignals(True)
        self.cb_srv_select.clear()
        for s in srvs:
            self.cb_srv_select.addItem(
                f"{s['name']} ({s['service_type']}) - {s['default_fee']:,} تومان",
                dict(s),
            )
        self.cb_srv_select.blockSignals(False)
        if srvs:
            self._on_srv_catalog_picked()

        self.cb_upg_target.clear()
        self.cb_upg_part.clear()
        for b in batches:
            title = f"{b['sub_category']} {b['brand']} {b['model']}".strip()
            lbl = f"{b['batch_code']} | {b['category']} - {title} (موجودی: {b['remaining_qty']})"
            self.cb_upg_target.addItem(lbl, b["id"])
            self.cb_upg_part.addItem(lbl, b["id"])
        self._on_upg_target_changed()

        if not self.selected_product_id:
            self.ed_prod_code.setText(
                self.db.generate_next_code("products", "code", "P-", 1001)
            )
        if not self.selected_batch_id:
            self.ed_batch_code.setText(
                self.db.generate_next_code("batches", "batch_code", "C-", 1001)
            )
        if not self.selected_sale_id:
            self.ed_sale_inv.setText(
                self.db.generate_next_code("sales", "invoice_number", "INV-", 1001)
            )

    def _refresh_products_table(self):
        q = self.ed_prod_search.text().strip().lower()
        with self.db.get_connection() as conn:
            rows = conn.execute("""
                SELECT p.*,
                       COALESCE(SUM(b.remaining_qty), 0) as rem_qty,
                       COALESCE(SUM(b.sold_qty), 0) as sold_qty
                FROM products p
                LEFT JOIN batches b ON p.id = b.product_id
                GROUP BY p.id ORDER BY p.id DESC
            """).fetchall()

        data = []
        for r in rows:
            specs = json.loads(r["specs_json"] or "{}")
            specs_str = " | ".join(f"{k}:{v}" for k, v in specs.items())
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
                ORDER BY b.id DESC
            """).fetchall()
        data = []
        for r in rows:
            tot_bill = (r["unit_purchase_price"] * r["initial_qty"]) + r["extra_cost_total"]
            debt = max(0, tot_bill - r["paid_amount"])
            prod_title = f"{r['category']} - {r['sub_category']} ({r['brand']} {r['model']})".strip()
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
                       b.batch_code, e.name as emp_name
                FROM sales s
                JOIN products p ON s.product_id=p.id
                JOIN batches b ON s.batch_id=b.id
                LEFT JOIN employees e ON s.seller_employee_id=e.id
                ORDER BY s.id DESC
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
                ]
            )
        self._populate_table_safely(self.tbl_sales, data, highlight_col=11)

    def _refresh_upgrades_table(self):
        with self.db.get_connection() as conn:
            rows = conn.execute("""
                SELECT u.*, b1.batch_code as t_code, b2.batch_code as p_code, e.name as tech_name
                FROM upgrades u
                JOIN batches b1 ON u.target_batch_id=b1.id
                JOIN batches b2 ON u.part_batch_id=b2.id
                LEFT JOIN employees e ON u.technician_id=e.id
                ORDER BY u.id DESC
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
                ]
            )
        self._populate_table_safely(self.tbl_upgrades, data)

    def _refresh_services_table(self):
        with self.db.get_connection() as conn:
            cat_rows = conn.execute(
                "SELECT * FROM service_catalog WHERE is_active=1 ORDER BY id DESC"
            ).fetchall()
            rec_rows = conn.execute("""
                SELECT sr.*, e.name as emp_name FROM service_records sr
                LEFT JOIN employees e ON sr.seller_employee_id=e.id
                ORDER BY sr.id DESC
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
                ORDER BY s.id DESC
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
                "SELECT * FROM employees ORDER BY id DESC"
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
        with self.db.get_connection() as conn:
            s_today = conn.execute(
                """
                SELECT COUNT(*) as cnt, COALESCE(SUM(total_amount),0) as amt, COALESCE(SUM(total_profit),0) as prof
                FROM sales WHERE substr(sale_datetime, 1, 10) = ?
            """,
                (today,),
            ).fetchone()
            b_today = conn.execute(
                """
                SELECT COALESCE(SUM(unit_purchase_price*initial_qty + extra_cost_total),0)
                FROM batches WHERE purchase_date = ?
            """,
                (today,),
            ).fetchone()[0]
            srv_today = conn.execute(
                """
                SELECT COALESCE(SUM(net_profit),0) FROM service_records
                WHERE substr(service_datetime, 1, 10) = ?
            """,
                (today,),
            ).fetchone()[0]
            tot_stock = conn.execute(
                "SELECT COALESCE(SUM(remaining_qty),0) FROM batches"
            ).fetchone()[0]
            tot_debt = conn.execute(
                "SELECT COALESCE(SUM((unit_purchase_price*initial_qty + extra_cost_total) - paid_amount),0) FROM batches"
            ).fetchone()[0]

            low_prods = conn.execute("""
                SELECT p.code, p.category, p.sub_category, p.brand, p.model, p.reorder_point,
                       COALESCE(SUM(b.remaining_qty),0) as rem
                FROM products p
                LEFT JOIN batches b ON p.id=b.product_id
                GROUP BY p.id
                HAVING rem <= p.reorder_point
                ORDER BY rem ASC
            """).fetchall()

            emp_perf = conn.execute("""
                SELECT e.name, COUNT(s.id) as cnt, COALESCE(SUM(s.total_amount),0) as amt,
                       COALESCE(SUM(s.total_discount),0) as disc, COALESCE(SUM(s.total_profit),0) as prof
                FROM employees e
                LEFT JOIN sales s ON e.id = s.seller_employee_id
                GROUP BY e.id
                ORDER BY e.id ASC
            """).fetchall()

        scoped_dashboard = self._is_scoped_access() and bool(self.active_employee)
        if scoped_dashboard:
            own_id = int(self.active_employee["id"])
            role = self.active_employee.get("permissions") or ""
            with self.db.get_connection() as conn:
                s_today = conn.execute(
                    """SELECT COUNT(*) AS cnt, COALESCE(SUM(total_amount),0) AS amt,
                       COALESCE(SUM(total_profit),0) AS prof
                       FROM sales WHERE substr(sale_datetime,1,10)=? AND seller_employee_id=?""",
                    (today, own_id),
                ).fetchone()
                b_today = conn.execute(
                    """SELECT COALESCE(SUM(unit_purchase_price*initial_qty+extra_cost_total),0)
                       FROM batches WHERE purchase_date=? AND buyer_employee_id=?""",
                    (today, own_id),
                ).fetchone()[0]
                srv_today = conn.execute(
                    """SELECT COALESCE(SUM(net_profit),0) FROM service_records
                       WHERE substr(service_datetime,1,10)=? AND seller_employee_id=?""",
                    (today, own_id),
                ).fetchone()[0]
                emp_perf = conn.execute(
                    """SELECT e.name, COUNT(s.id) AS cnt, COALESCE(SUM(s.total_amount),0) AS amt,
                       COALESCE(SUM(s.total_discount),0) AS disc, COALESCE(SUM(s.total_profit),0) AS prof
                       FROM employees e LEFT JOIN sales s ON e.id=s.seller_employee_id
                       WHERE e.id=? GROUP BY e.id""",
                    (own_id,),
                ).fetchall()
            if "فروش و خدمات" in role:
                b_today = 0
            if "ثبت خرید و انبارداری" in role:
                s_today = {"cnt": 0, "amt": 0, "prof": 0}
                srv_today = 0
            low_prods = []

        self.lbl_dash_sales_today.setText(f"{int(s_today['amt']):,}")
        self.lbl_dash_profit_today.setText(f"{int(s_today['prof']):,}")
        self.lbl_dash_count_today.setText(str(s_today["cnt"]))
        self.lbl_dash_buy_today.setText(f"{int(b_today):,}")
        self.lbl_dash_total_stock.setText("—" if scoped_dashboard else f"{int(tot_stock):,}")
        self.lbl_dash_low_stock.setText("—" if scoped_dashboard else str(len(low_prods)))
        self.lbl_dash_unpaid_supplier.setText("—" if scoped_dashboard else f"{max(0, int(tot_debt)):,}")
        self.lbl_dash_srv_profit.setText(f"{int(srv_today):,}")

        low_data = []
        for r in low_prods:
            st = "ناموجود" if int(r["rem"]) == 0 else "کم‌موجود"
            title = f"{r['brand']} {r['model']}".strip() or r["sub_category"]
            low_data.append(
                [
                    r["code"],
                    title,
                    r["category"],
                    r["sub_category"],
                    r["rem"],
                    r["reorder_point"],
                    st,
                ]
            )
        self._populate_table_safely(self.tbl_dash_low, low_data, highlight_col=6)

        emp_data = [
            [
                r["name"],
                r["cnt"],
                f"{int(r['amt']):,}",
                f"{int(r['disc']):,}",
                f"{int(r['prof']):,}",
            ]
            for r in emp_perf
        ]
        self._populate_table_safely(self.tbl_dash_emp, emp_data)


def main():
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    font = QFont("Tahoma", 10)
    app.setFont(font)

    db = DatabaseManager()

    active_emp = None
    if db.get_setting("require_login_password", "0") == "1":
        dlg = LoginDialog(db)
        if dlg.exec() != QDialog.Accepted:
            sys.exit(0)
        active_emp = dlg.logged_employee

    win = MainWindow(db, active_emp)
    if db.get_setting("default_window_maximized", "1") == "1":
        win.showMaximized()
    else:
        win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
