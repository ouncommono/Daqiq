# main.py
import os
import sys

if __name__ == "__main__" and "--print-paths" in sys.argv[1:]:
    from utils.paths import format_resolved_paths_report
    try:
        print(format_resolved_paths_report(), flush=True)
    except OSError:
        pass
    sys.exit(0)

import json
import subprocess
import time
import sqlite3
import copy
import re
from datetime import date, timedelta
from typing import Optional
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
    QScrollArea,
    QFrame,
)
from PySide6.QtCore import Qt, QTimer, QObject, QEvent, QLocale, QCoreApplication
from PySide6.QtGui import QFont, QColor, QFontMetrics, QIcon

from database import (
    DatabaseManager, load_app_config, save_app_config, hash_password,
    receivable_balance, service_financial_breakdown,
    app_config_has_database_selection, get_default_database_path,
    generate_timestamped_database_filename, resolve_new_database_filename,
    create_and_initialize_database, SecureCredentialStore,
    SCHEMA_VERSION, round_integer_division, round_percentage_amount,
    ReadOnlyGraceError, ConcurrencyConflictError, InsufficientStockError,
)
from utils_and_widgets import (
    normalize_catalog_label,
    SmartLineEdit,
    WarrantyLineEdit,
    PriceInput,
    SearchableComboBox,
    QuantitySelector,
    JalaliDateEdit,
    DynamicSpecsWidget,
    DynamicAttributeValuesWidget,
    add_jalali_months,
    add_jalali_days,
    normalize_digits,
    SmoothScrollArea,
    SmoothScrollTableWidget,
    SmoothScrollListWidget,
    CollapsibleSection,
    bidi_isolate_text,
    strip_bidi_controls,
    mixed_bidi_tooltip,
    resource_path,
    resolve_active_dark_theme,
    build_theme_palette,
    apply_dialog_theme,
)
from exporter import (
    export_safe_inventory_excel,
    export_table_to_excel,
    get_next_excel_filename,
    INVENTORY_EXPORT_AVAILABLE_COLUMNS,
)
from utils.printing import (
    PrintPreviewDialog,
    build_purchase_voucher_html,
    build_sales_invoice_html,
    build_service_or_upgrade_html,
    build_structured_table_report_html,
)
import datetime_format
from datetime_format import (
    CALENDAR_JALALI,
    CALENDAR_HIJRI,
    CALENDAR_GREGORIAN,
    TIME_FORMAT_24H,
    TIME_FORMAT_12H,
    CALENDAR_NAMES_FA,
    TIME_FORMAT_NAMES_FA,
    migrate_database_datetime,
)

from utils.paths import (
    format_resolved_paths_report,
    get_executable_dir,
)


def _load_app_version() -> str:
    for candidate in (
        resource_path("VERSION"),
        os.path.join(str(get_executable_dir()), "VERSION"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION"),
    ):
        if candidate and os.path.isfile(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    ver = f.read().strip()
                    if ver:
                        return ver
            except Exception:
                pass
    return "4.9.10"

APP_VERSION = _load_app_version()

# In Nuitka standalone/onefile binaries, ensure sys.frozen is set for external resource resolution
if "__compiled__" in globals() or hasattr(sys, "__compiled__"):
    sys.frozen = True

from licensing import (
    LicenseService,
    LicenseDialog,
    ThemedNoticeDialog,
    ValidationResult,
    ValidationStatus,
)
from licensing.license_policy import (
    TAB_MODULE_TO_FEATURE,
    FEATURE_LABELS_FA,
    get_feature_label_fa,
    get_grace_mode_label_fa,
)

# Semantic theme tokens for WCAG AA+ accessible dashboard top report cards
DASHBOARD_CARD_TOKENS = {
    "light": {
        "surface": "#FFFFFF",
        "border": "#E2E8F0",
        "title": "#334155",  # Contrast 8.54:1 on #FFFFFF (WCAG AAA)
        "roles": {
            "primary": {"accent": "#2563EB", "val": "#1D4ED8"},   # val: 5.61:1 on #FFFFFF
            "success": {"accent": "#059669", "val": "#047857"},   # val: 5.48:1 on #FFFFFF
            "info":    {"accent": "#7C3AED", "val": "#6D28D9"},   # val: 7.23:1 on #FFFFFF
            "warning": {"accent": "#D97706", "val": "#B45309"},   # val: 5.02:1 on #FFFFFF
            "neutral": {"accent": "#0D9488", "val": "#0F766E"},   # val: 5.16:1 on #FFFFFF
            "danger":  {"accent": "#DC2626", "val": "#B91C1C"},   # val: 6.09:1 on #FFFFFF
            "rose":    {"accent": "#E11D48", "val": "#BE123C"},   # val: 5.92:1 on #FFFFFF
            "accent":  {"accent": "#4F46E5", "val": "#4338CA"},   # val: 7.37:1 on #FFFFFF
        },
    },
    "dark": {
        "surface": "#1E293B",
        "border": "#334155",
        "title": "#CBD5E1",  # Contrast 9.59:1 on #1E293B (WCAG AAA)
        "roles": {
            "primary": {"accent": "#3B82F6", "val": "#60A5FA"},   # val: 6.44:1 on #1E293B
            "success": {"accent": "#10B981", "val": "#34D399"},   # val: 8.38:1 on #1E293B
            "info":    {"accent": "#A855F7", "val": "#C084FC"},   # val: 6.64:1 on #1E293B
            "warning": {"accent": "#F59E0B", "val": "#FBBF24"},   # val: 8.79:1 on #1E293B
            "neutral": {"accent": "#14B8A6", "val": "#2DD4BF"},   # val: 8.16:1 on #1E293B
            "danger":  {"accent": "#EF4444", "val": "#F87171"},   # val: 5.37:1 on #1E293B
            "rose":    {"accent": "#F43F5E", "val": "#FB7185"},   # val: 5.56:1 on #1E293B
            "accent":  {"accent": "#6366F1", "val": "#818CF8"},   # val: 5.86:1 on #1E293B
        },
    },
}

LEGACY_COLOR_TO_ROLE = {
    "#1d4ed8": "primary",
    "#047857": "success",
    "#7c3aed": "info",
    "#b45309": "warning",
    "#0f766e": "neutral",
    "#dc2626": "danger",
    "#be123c": "rose",
    "#4338ca": "accent",
}


def format_iso_to_jalali(dt_str, cal_type: str = "jalali", time_fmt: str = "24h") -> str:
    """Format an ISO or localized timestamp using the active calendar and time format."""
    return datetime_format.format_timestamp_for_display(
        dt_str,
        cal_type=cal_type,
        time_fmt=time_fmt,
    )


REPORT_AVAILABLE_COLUMNS = {
    "همه (گزارش جامع خرید، فروش و خدمات)": [
        "نوع عملیات", "شماره فاکتور / محموله", "تاریخ و ساعت", "کد کالا / خدمت",
        "دسته‌بندی", "زیرمجموعه", "برند و مدل / عنوان", "مشخصات فنی",
        "کاربر ثبت‌کننده", "مشتری / تأمین‌کننده", "تعداد", "مبلغ واحد (تومان)",
        "تخفیف (-) / تشدید (+)", "بهای تمام‌شده / هزینه جانبی", "مبلغ کل (تومان)",
        "پرداخت‌شده (تومان)", "مانده حساب (تومان)", "سود خالص (تومان)", "وضعیت تسویه",
    ],
    "۱. گزارش کامل تمام فروش‌ها": [
        "شناسه", "شماره فاکتور", "کد کالا", "شماره سریال", "مشخصات کالا", "تاریخ و ساعت فروش",
        "کد محموله", "فروشنده", "نام مشتری", "شماره تماس مشتری", "تعداد", "قیمت پیشنهادی واحد",
        "قیمت فروش واحد", "بهای تمام‌شده واحد", "تخفیف (-) / تشدید (+)",
        "سود واحد", "سود کل", "مبلغ کل فاکتور", "دریافتی", "مانده حساب",
        "وضعیت تسویه", "گارانتی", "رنگ‌ها", "مشخصات فنی", "توضیحات",
    ],
    "۱۱. گزارش تخفیف‌ها و تشدیدهای فروش": [
        "شماره فاکتور", "تاریخ فروش", "کد کالا", "عنوان کالا", "فروشنده",
        "مشتری", "تعداد", "قیمت پیشنهادی واحد", "قیمت فروش واحد", "تخفیف واحد",
        "تخفیف کل", "تشدید واحد", "تشدید کل", "تخفیف (-) / تشدید (+) کل",
        "درصد اثر بر قیمت (%)",
    ],
    "۱۲. گزارش کامل خدمات انجام‌شده": [
        "شناسه", "شماره قبض", "تاریخ و ساعت", "کد خدمت", "نوع خدمت",
        "عنوان خدمت", "ثبت‌کننده / پذیرش", "کارشناس / تکنسین", "مشتری",
        "تعرفه مرجع", "اجرت دریافتی", "هزینه جانبی", "دریافتی", "مانده طلب",
        "وضعیت تسویه", "سود خالص خدمت", "شرح خدمت",
    ],
    "۲. گزارش کامل تمام خریدها (محموله‌ها)": [
        "شناسه", "کد محموله", "کد کالا", "شماره سریال", "مشخصات کالا", "تأمین‌کننده",
        "مسئول خرید", "شماره فاکتور", "تاریخ خرید", "تعداد خرید", "تعداد فروش",
        "موجودی فعلی", "قیمت خرید واحد", "هزینه جانبی کل", "هزینه ارتقا واحد",
        "بهای تمام‌شده واحد", "قیمت فروش پیشنهادی", "درصد سود (%)", "وضعیت تسویه",
        "پرداخت‌شده", "مانده بدهی", "مشخصات فنی / توضیحات", "بهای کل محموله (تومان)",
        "رنگ‌های محموله",
    ],
    "۹. گزارش بدهی به تأمین‌کنندگان": [
        "شناسه محموله", "کد محموله", "کد کالا", "مشخصات کالا", "تأمین‌کننده",
        "شماره فاکتور خرید", "تاریخ خرید", "بهای کل محموله (تومان)",
        "مبلغ پرداخت‌شده (تومان)", "مانده بدهی (تومان)", "وضعیت تسویه",
    ],
    "۳. گزارش موجودی فعلی کالاها": [
        "شناسه", "کد کالا", "شماره سریال", "دسته‌بندی", "زیرمجموعه", "برند", "مدل",
        "مشخصات فنی", "موجودی کل", "تعداد فروش", "حداقل موجودی",
        "درصد سود (%)", "وضعیت موجودی", "توضیحات",
    ],
    "۴. گزارش موجودی و سود به تفکیک محموله": [
        "کد محموله", "کد کالا", "مشخصات کالا", "تأمین‌کننده", "تعداد خرید",
        "تعداد فروش", "موجودی فعلی", "بهای تمام‌شده واحد", "قیمت فروش پیشنهادی",
        "درصد سود (%)", "ارزش ریالی موجودی (تومان)", "سود محقق‌شده (تومان)",
    ],
    "۵. گزارش سود تجمعی هر کالا": [
        "کد کالا", "دسته‌بندی", "زیرمجموعه", "برند و مدل", "کل تعداد خریداری‌شده",
        "کل تعداد فروخته‌شده", "موجودی فعلی", "میانگین بهای تمام‌شده",
        "میانگین قیمت فروش", "کل درآمد فروش (تومان)", "سود ناخالص تجمعی (تومان)",
    ],
    "۶. گزارش سود و عملکرد هر محموله": [
        "کد محموله", "کد کالا", "مشخصات کالا", "تأمین‌کننده", "تعداد اولیه",
        "تعداد فروخته‌شده", "موجودی باقی‌مانده", "کل بهای تمام‌شده محموله",
        "کل درآمد حاصل از فروش", "سود محقق‌شده فعلی", "سود بالقوه موجودی باقی‌مانده",
        "کل سود پیش‌بینی‌شده محموله", "درصد بازدهی سرمایه (%)",
    ],
    "۸. گزارش کالاهای کم‌موجود (نیازمند خرید)": [
        "کد کالا", "دسته‌بندی", "زیرمجموعه", "برند و مدل", "موجودی فعلی",
        "حداقل موجودی (حد سفارش)", "کسری موجودی", "وضعیت",
    ],
    "۷. گزارش جامع عملکرد هر کاربر / فروشنده": [
        "شناسه کاربر", "نام کاربر / همکار", "نقش سازمانی", "تعداد فاکتورهای فروش",
        "تعداد اقلام فروخته‌شده", "مبلغ کل فروش (تومان)", "سود حاصل از فروش (تومان)",
        "تعداد خدمات ثبت‌شده", "درآمد خدمات (تومان)", "سود خالص خدمات (تومان)",
        "مجموع سودآوری برای فروشگاه (تومان)",
    ],
    "۱۰. گزارش فاکتورهای تسویه‌نشده (طلب و بدهی)": [
        "نوع فاکتور", "شماره فاکتور / محموله", "تاریخ", "طرف حساب (مشتری / تأمین‌کننده)",
        "مسئول / کاربر", "مبلغ کل (تومان)", "پرداخت‌شده / دریافتی (تومان)",
        "مانده طلب / بدهی (تومان)", "وضعیت تسویه",
    ],
}

ALL_SYSTEM_COLUMNS = [
    # کالاها
    "کد کالا", "شماره سریال", "دسته‌بندی", "زیرمجموعه", "برند", "مدل", "مشخصات فنی",
    "موجودی کل", "تعداد فروش", "حداقل موجودی", "درصد سود (%)", "وضعیت موجودی", "توضیحات",
    # محموله‌ها / خرید
    "کد محموله", "تأمین‌کننده", "مسئول خرید", "شماره فاکتور خرید", "تاریخ خرید", "تعداد خرید",
    "تعداد فروش محموله", "موجودی فعلی محموله", "قیمت خرید واحد", "هزینه جانبی کل", "هزینه ارتقا واحد",
    "بهای تمام‌شده واحد", "قیمت فروش پیشنهادی", "درصد سود (%) محموله", "وضعیت تسویه خرید",
    "پرداخت‌شده خرید", "مانده بدهی خرید", "مشخصات فنی محموله", "بهای کل محموله (تومان)", "رنگ‌های محموله",
    # فروش
    "شماره فاکتور فروش", "تاریخ و ساعت فروش", "فروشنده", "نام مشتری", "شماره تماس مشتری",
    "تعداد فروش", "قیمت پیشنهادی واحد فروش", "قیمت فروش واحد", "تخفیف (-) / تشدید (+)",
    "بهای تمام‌شده واحد فروش", "سود هر واحد", "سود کل فروش", "مبلغ کل فاکتور", "دریافتی فروش",
    "وضعیت تسویه فروش", "گارانتی و انقضا", "شماره سریال فروخته‌شده", "مشخصات فنی فروخته‌شده",
    "رنگ‌های فروخته‌شده",
    # خدمات
    "شماره قبض خدمت", "تاریخ و ساعت خدمت", "کد خدمت", "نوع خدمت", "عنوان خدمت",
    "ثبت‌کننده / پذیرش", "کارشناس / تکنسین", "تعرفه مرجع", "اجرت دریافتی", "هزینه جانبی خدمت",
    "دریافتی خدمت", "مانده طلب خدمت", "وضعیت تسویه خدمت", "سود خالص خدمت", "شرح خدمت",
]


class CatalogSettingsState:
    """Decoupled UI state buffer for Item Settings tab to survive tab navigation lifecycles."""

    def __init__(self):
        self.category_new_name = ""
        self.subcategory_name = ""
        self.attribute_name = ""
        self.attribute_label = ""
        self.attribute_values = []
        self.color_name = ""

    def capture_from_window(self, win):
        if hasattr(win, "ed_cfg_category") and win.ed_cfg_category is not None:
            self.category_new_name = win.ed_cfg_category.text()
        if hasattr(win, "ed_cfg_subcategory") and win.ed_cfg_subcategory is not None:
            self.subcategory_name = win.ed_cfg_subcategory.text()
        if hasattr(win, "ed_cfg_attribute_name") and win.ed_cfg_attribute_name is not None:
            self.attribute_name = win.ed_cfg_attribute_name.text()
        if hasattr(win, "ed_cfg_attribute_label") and win.ed_cfg_attribute_label is not None:
            self.attribute_label = win.ed_cfg_attribute_label.text()
        if hasattr(win, "attr_values_widget") and win.attr_values_widget is not None:
            self.attribute_values = win.attr_values_widget.get_values()
        if hasattr(win, "ed_cfg_color") and win.ed_cfg_color is not None:
            self.color_name = win.ed_cfg_color.text()

    def restore_to_window(self, win):
        if hasattr(win, "ed_cfg_category") and win.ed_cfg_category is not None:
            if self.category_new_name:
                win.ed_cfg_category.setText(self.category_new_name)
        if hasattr(win, "ed_cfg_subcategory") and win.ed_cfg_subcategory is not None:
            if self.subcategory_name:
                win.ed_cfg_subcategory.setText(self.subcategory_name)
        if hasattr(win, "ed_cfg_attribute_name") and win.ed_cfg_attribute_name is not None:
            if self.attribute_name:
                win.ed_cfg_attribute_name.setText(self.attribute_name)
        if hasattr(win, "ed_cfg_attribute_label") and win.ed_cfg_attribute_label is not None:
            if self.attribute_label:
                win.ed_cfg_attribute_label.setText(self.attribute_label)
        if hasattr(win, "attr_values_widget") and win.attr_values_widget is not None:
            if self.attribute_values:
                win.attr_values_widget.set_values(self.attribute_values)
        if hasattr(win, "ed_cfg_color") and win.ed_cfg_color is not None:
            if self.color_name:
                win.ed_cfg_color.setText(self.color_name)


class SettingsSnapshot:
    """Memento pattern deep-copy buffer for Settings rollback (انصراف)."""

    def __init__(self, win):
        self.cfg = copy.deepcopy(win.db.cfg)
        self.taxonomy_draft = copy.deepcopy(getattr(win, "_taxonomy_draft", {}))
        self.pending_attribute_renames = list(getattr(win, "_pending_attribute_renames", []))
        self.shop_name = win.db.get_setting("shop_name", "فروشگاه من")
        self.colleague_export_cols = win.db.get_setting("colleague_inventory_export_columns", "[]")
        self.report_export_configs = win.db.get_setting("report_excel_export_configs", "{}")
        self.category_text = win.ed_cfg_category.text() if hasattr(win, "ed_cfg_category") else ""
        self.subcategory_text = win.ed_cfg_subcategory.text() if hasattr(win, "ed_cfg_subcategory") else ""
        self.attribute_name_text = win.ed_cfg_attribute_name.text() if hasattr(win, "ed_cfg_attribute_name") else ""
        self.attribute_label_text = win.ed_cfg_attribute_label.text() if hasattr(win, "ed_cfg_attribute_label") else ""
        self.attribute_values = win.attr_values_widget.get_values() if hasattr(win, "attr_values_widget") else []
        self.color_text = win.ed_cfg_color.text() if hasattr(win, "ed_cfg_color") else ""
        self.staged_db_password_action = copy.deepcopy(getattr(win, "_staged_db_password_action", None))
        self.staged_db_startup_prompt = getattr(win, "_staged_db_startup_prompt", None)
        cal = win.cb_calendar_format.currentData() if hasattr(win, "cb_calendar_format") else "jalali"
        self.calendar_format = cal if isinstance(cal, str) else "jalali"
        tf = win.cb_time_format.currentData() if hasattr(win, "cb_time_format") else "24h"
        self.time_format = tf if isinstance(tf, str) else "24h"
        self.inventory_export_items = []
        if hasattr(win, "lst_inventory_export_columns"):
            try:
                cnt = win.lst_inventory_export_columns.count()
                if isinstance(cnt, int):
                    for i in range(cnt):
                        it = win.lst_inventory_export_columns.item(i)
                        if it is not None:
                            self.inventory_export_items.append((it.data(Qt.UserRole), it.text(), it.checkState() == Qt.Checked))
            except Exception:
                pass

    def restore(self, win):
        win.db.cfg = copy.deepcopy(self.cfg)
        win._pending_attribute_renames = list(self.pending_attribute_renames)
        win._staged_db_password_action = copy.deepcopy(self.staged_db_password_action)
        win._staged_db_startup_prompt = self.staged_db_startup_prompt
        win._refresh_db_password_status()
        win._load_general_settings_form()
        win._taxonomy_draft = copy.deepcopy(self.taxonomy_draft)
        win._refresh_catalog_draft_ui()
        if hasattr(win, "cb_calendar_format") and hasattr(self, "calendar_format"):
            idx = win.cb_calendar_format.findData(self.calendar_format)
            if isinstance(idx, int) and idx >= 0:
                win.cb_calendar_format.setCurrentIndex(idx)
        if hasattr(win, "cb_time_format") and hasattr(self, "time_format"):
            idx = win.cb_time_format.findData(self.time_format)
            if isinstance(idx, int) and idx >= 0:
                win.cb_time_format.setCurrentIndex(idx)
        if hasattr(win, "lst_inventory_export_columns") and hasattr(self, "inventory_export_items") and self.inventory_export_items:
            win._populate_inventory_export_columns_ui(self.inventory_export_items)
        if hasattr(win, "ed_cfg_category"):
            win.ed_cfg_category.setText(self.category_text)
        if hasattr(win, "ed_cfg_subcategory"):
            win.ed_cfg_subcategory.setText(self.subcategory_text)
        if hasattr(win, "ed_cfg_attribute_name"):
            win.ed_cfg_attribute_name.setText(self.attribute_name_text)
        if hasattr(win, "ed_cfg_attribute_label"):
            win.ed_cfg_attribute_label.setText(self.attribute_label_text)
        if hasattr(win, "attr_values_widget"):
            win.attr_values_widget.set_values(self.attribute_values)
        if hasattr(win, "ed_cfg_color"):
            win.ed_cfg_color.setText(self.color_text)
        if hasattr(win, "_catalog_settings_state"):
            win._catalog_settings_state.capture_from_window(win)

DEFAULT_ACCESS_LEVELS = [
    {"name": "دسترسی کامل (مدیر کل)", "policy": "دسترسی کامل (مدیر کل)"},
    {"name": "مدیر ارشد (بدون مدیریت کارکنان)", "policy": "مدیر ارشد (بدون مدیریت کارکنان)"},
    {"name": "سرپرست عملیات (گزارش‌های محدود به عملکرد خود)", "policy": "سرپرست عملیات (گزارش‌های محدود به عملکرد خود)"},
    {"name": "فروش و خدمات (گزارش محدود به عملکرد خود)", "policy": "فروش و خدمات (گزارش محدود به عملکرد خود)"},
    {"name": "ثبت خرید و انبارداری (گزارش محدود به خریدهای خود)", "policy": "ثبت خرید و انبارداری (گزارش محدود به خریدهای خود)"},
]

DASHBOARD_PERMISSION_ACTIONS = [
    ("metric.sales_today", "فروش امروز"),
    ("metric.profit_today", "سود فروش امروز"),
    ("metric.sales_count_today", "تعداد فروش امروز"),
    ("metric.purchase_today", "خرید امروز"),
    ("metric.total_stock", "کل موجودی انبار"),
    ("metric.low_stock_count", "تعداد کالاهای کم‌موجود"),
    ("metric.supplier_debt", "بدهی تأمین‌کنندگان"),
    ("metric.service_profit_today", "سود خدمات امروز"),
    ("table.low_stock", "جدول هشدار موجودی"),
    ("table.employee_performance", "جدول عملکرد فروشندگان"),
]

PERMISSION_GROUPS = [
    (
        "داشبورد", "dashboard",
        [("view", "مشاهده")] + DASHBOARD_PERMISSION_ACTIONS,
    ),
    ("مدیریت کالاها", "products", [
        ("view", "مشاهده"), ("create", "ثبت"), ("edit", "ویرایش"), ("delete", "حذف"),
    ]),
    ("ثبت خرید و محموله‌ها", "batches", [
        ("view", "مشاهده"), ("create", "ثبت"), ("edit", "ویرایش"), ("delete", "حذف"),
    ]),
    ("ثبت فروش", "sales", [
        ("view", "مشاهده"), ("create", "ثبت"), ("edit", "ویرایش"), ("delete", "حذف"),
    ]),
    ("میز خدمت", "services", [
        ("view", "مشاهده"), ("create", "ثبت"), ("edit", "ویرایش"), ("delete", "حذف"),
    ]),
    ("ارتقای کالا", "upgrades", [
        ("view", "مشاهده"), ("create", "ثبت"), ("edit", "ویرایش"), ("delete", "حذف"),
    ]),
    ("تأمین‌کنندگان و پرداخت‌ها", "suppliers", [
        ("view", "مشاهده"), ("create", "ثبت"), ("edit", "ویرایش"), ("delete", "حذف"),
    ]),
    ("گزارش‌های جامع", "reports", [
        ("view", "مشاهده"), ("export", "خروجی اکسل"),
    ]),
    ("مدیریت کاربران", "employees", [
        ("view", "مشاهده"), ("create", "افزودن"), ("edit", "ویرایش"),
        ("delete", "حذف"), ("manage_access", "مدیریت سطوح دسترسی"),
    ]),
    ("تنظیمات", "settings", [
        ("view", "مشاهده"), ("edit", "ویرایش تنظیمات"),
        ("manage_database", "مدیریت پایگاه داده و پشتیبان"),
        ("manage_access", "مدیریت مجوزها"),
    ]),
    ("خروجی موجودی همکار", "inventory_export", [("export", "تهیه خروجی")]),
]
ALL_PERMISSION_KEYS = tuple(
    f"{module}.{action}"
    for _title, module, actions in PERMISSION_GROUPS
    for action, _label in actions
)
ROLE_PERMISSION_PRESETS = {
    "دسترسی کامل (مدیر کل)": list(ALL_PERMISSION_KEYS),
    "مدیر ارشد (بدون مدیریت کارکنان)": [
        key for key in ALL_PERMISSION_KEYS
        if not key.startswith("employees.")
    ],
    "سرپرست عملیات (گزارش‌های محدود به عملکرد خود)": [
        "dashboard.view",
        "dashboard.metric.sales_today", "dashboard.metric.profit_today",
        "dashboard.metric.sales_count_today", "dashboard.metric.purchase_today",
        "dashboard.metric.total_stock", "dashboard.metric.low_stock_count",
        "dashboard.metric.supplier_debt", "dashboard.metric.service_profit_today",
        "dashboard.table.low_stock", "dashboard.table.employee_performance",
        "products.view", "batches.view", "sales.view",
        "services.view", "upgrades.view", "reports.view",
    ],
    "فروش و خدمات (گزارش محدود به عملکرد خود)": [
        "dashboard.view",
        "dashboard.metric.sales_today", "dashboard.metric.profit_today",
        "dashboard.metric.sales_count_today", "dashboard.metric.service_profit_today",
        "dashboard.table.employee_performance",
        "sales.view", "sales.create", "sales.edit",
        "services.view", "services.create", "services.edit", "reports.view",
    ],
    "ثبت خرید و انبارداری (گزارش محدود به خریدهای خود)": [
        "dashboard.view",
        "dashboard.metric.purchase_today", "dashboard.metric.total_stock",
        "dashboard.metric.low_stock_count", "dashboard.metric.supplier_debt",
        "dashboard.table.low_stock",
        "products.view", "batches.view", "batches.create",
        "batches.edit", "suppliers.view", "reports.view",
    ],
}

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


class _MessageBoxPolisher(QObject):
    """Translate standard Qt message-box buttons, center them, and synchronize Light/Dark theming."""

    _BUTTON_LABELS = {
        "OK": "تأیید", "Ok": "تأیید", "Cancel": "انصراف",
        "Yes": "بله", "No": "خیر", "Save": "ذخیره",
        "Discard": "نادیده گرفتن", "Close": "بستن", "Abort": "توقف",
        "Retry": "تلاش مجدد", "Ignore": "نادیده گرفتن", "Apply": "اعمال",
        "Reset": "بازنشانی",
    }

    _SELF_STYLED_OBJECTS = {"LicenseDialogRoot", "DaqiqNoticeDialogRoot", "JalaliCalendarDialog"}

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Show:
            return False
        try:
            if isinstance(watched, QDialog):
                watched.setLayoutDirection(Qt.RightToLeft)
                button_box = watched.findChild(QDialogButtonBox)
                if button_box is not None:
                    button_box.setCenterButtons(True)
                    for button in button_box.buttons():
                        raw_label = (button.text() or "").replace("&", "").strip()
                        translated = self._BUTTON_LABELS.get(raw_label)
                        if translated:
                            button.setText(translated)
                        button.setLayoutDirection(Qt.RightToLeft)
                obj_name = watched.objectName() or ""
                if obj_name not in self._SELF_STYLED_OBJECTS and not watched.styleSheet():
                    is_dark = resolve_active_dark_theme(parent=watched.parentWidget() or watched)
                    if isinstance(watched, QMessageBox):
                        watched.setPalette(build_theme_palette(is_dark))
                        if is_dark:
                            qss = (
                                "QMessageBox { background-color: #0f172a; color: #f8fafc; }"
                                "QMessageBox QLabel { color: #f8fafc; background: transparent; }"
                                "QMessageBox QPushButton { background-color: #0284c7; color: #ffffff; "
                                "border: 1px solid #38bdf8; border-radius: 6px; padding: 6px 16px; "
                                "min-width: 84px; font-weight: bold; }"
                                "QMessageBox QPushButton:hover { background-color: #0369a1; }"
                            )
                        else:
                            qss = (
                                "QMessageBox { background-color: #f8fafc; color: #0f172a; }"
                                "QMessageBox QLabel { color: #0f172a; background: transparent; }"
                                "QMessageBox QPushButton { background-color: #0284c7; color: #ffffff; "
                                "border: 1px solid #0369a1; border-radius: 6px; padding: 6px 16px; "
                                "min-width: 84px; font-weight: bold; }"
                                "QMessageBox QPushButton:hover { background-color: #0369a1; }"
                            )
                        watched.setStyleSheet(qss)
                    else:
                        apply_dialog_theme(watched, is_dark=is_dark)
        except RuntimeError:
            pass
        return False


_ACTIVE_MAIN_WINDOW = None
_CRASH_HOOK_ACTIVE = False
_IN_CRASH_HANDLER = False
_NATIVE_FAULT_LOG_HANDLE = None
_QT_MSG_HANDLER_ACTIVE = False
_PREV_QT_MSG_HANDLER = None


def _get_log_dir() -> str:
    local_app = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app:
        log_dir = os.path.join(local_app, "Daqiq", "logs")
    else:
        log_dir = os.path.join(os.path.expanduser("~"), ".daqiq", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        log_dir = os.path.dirname(os.path.abspath(__file__))
    return log_dir


def get_crash_log_path() -> str:
    """Return persistent path for crash tracebacks under %LOCALAPPDATA%\\Daqiq\\logs."""
    return os.path.join(_get_log_dir(), "daqiq_crash.log")


def get_native_fault_log_path() -> str:
    """Return persistent path for native C/faulthandler crash dumps under %LOCALAPPDATA%\\Daqiq\\logs."""
    return os.path.join(_get_log_dir(), "daqiq_native_fault.log")


def install_native_fault_and_qt_loggers() -> None:
    """Enable native faulthandler and Qt critical/fatal message logging safely."""
    global _NATIVE_FAULT_LOG_HANDLE, _QT_MSG_HANDLER_ACTIVE, _PREV_QT_MSG_HANDLER
    if "PYTEST_CURRENT_TEST" not in os.environ and _NATIVE_FAULT_LOG_HANDLE is None:
        try:
            import faulthandler

            fault_path = get_native_fault_log_path()
            _NATIVE_FAULT_LOG_HANDLE = open(fault_path, "a", encoding="utf-8", buffering=1)
            faulthandler.enable(file=_NATIVE_FAULT_LOG_HANDLE, all_threads=True)
        except Exception:
            _NATIVE_FAULT_LOG_HANDLE = None

    if not _QT_MSG_HANDLER_ACTIVE:
        try:
            from PySide6.QtCore import QtMsgType, qInstallMessageHandler

            def _qt_message_handler(msg_type, context, message):
                try:
                    if msg_type in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
                        import datetime as _dt

                        severity = "FATAL" if msg_type == QtMsgType.QtFatalMsg else "CRITICAL"
                        loc = f"{getattr(context, 'file', '')}:{getattr(context, 'line', 0)}"
                        line = (
                            f"[{_dt.datetime.now(_dt.timezone.utc).isoformat()}] "
                            f"Qt {severity} ({loc}): {message}\n"
                        )
                        with open(get_crash_log_path(), "a", encoding="utf-8") as f:
                            f.write(line)
                except Exception:
                    pass
                if _PREV_QT_MSG_HANDLER is not None:
                    try:
                        _PREV_QT_MSG_HANDLER(msg_type, context, message)
                    except Exception:
                        pass

            _PREV_QT_MSG_HANDLER = qInstallMessageHandler(_qt_message_handler)
            _QT_MSG_HANDLER_ACTIVE = True
        except Exception:
            pass


def write_crash_log(exc_type, exc_value, exc_tb, context: str = "unhandled") -> str:
    """Write a full timestamped traceback to disk and return the log file path."""
    import datetime as _dt
    import platform
    import traceback

    log_path = get_crash_log_path()
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    entry = (
        "============================================================\n"
        f"Timestamp (UTC): {_dt.datetime.now(_dt.timezone.utc).isoformat()}\n"
        f"Daqiq Version: {APP_VERSION}\n"
        f"Context: {context}\n"
        f"Platform: {platform.platform()} | Python {platform.python_version()}\n"
        f"Executable: {sys.executable}\n"
        "Traceback:\n"
        f"{tb_text}\n"
    )
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)
    except OSError:
        pass
    return log_path


def _show_fatal_crash_dialog(log_path: str, exc_value: BaseException) -> None:
    """Display a localized Persian error dialog so console-less Windows builds never vanish silently."""
    try:
        is_dark = False
        try:
            cfg = load_app_config()
            is_dark = str(cfg.get("theme", "")).lower() == "dark"
        except Exception:
            pass
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv[:1] if sys.argv else ["Daqiq"])
            app.setLayoutDirection(Qt.RightToLeft)
        msg = (
            "متأسفانه خطای غیرمنتظره‌ای هنگام راه‌اندازی یا اجرای برنامه رخ داد.\n"
            f"گزارش کامل خطا در فایل زیر ذخیره شد:\n{log_path}\n\n"
            "لطفاً این گزارش را برای پشتیبانی ارسال فرمایید."
        )
        dlg = ThemedNoticeDialog(
            parent=None,
            title="بروز خطای غیرمنتظره",
            message=msg,
            kind="error",
            is_dark_theme=is_dark,
            buttons="ok",
            details=f"{type(exc_value).__name__}: {exc_value}",
        )
        dlg.exec()
    except Exception:
        pass


def handle_unhandled_exception(exc_type, exc_value, exc_tb, context: str = "sys.excepthook", show_dialog: bool = True) -> str:
    """Log unhandled exceptions cleanly and present Persian crash dialog."""
    global _IN_CRASH_HANDLER
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        return ""
    log_path = write_crash_log(exc_type, exc_value, exc_tb, context=context)
    if show_dialog and not _IN_CRASH_HANDLER:
        _IN_CRASH_HANDLER = True
        try:
            _show_fatal_crash_dialog(log_path, exc_value)
        finally:
            _IN_CRASH_HANDLER = False
    return log_path


def install_global_exception_hooks() -> None:
    """Install sys.excepthook and threading.excepthook once per process."""
    global _CRASH_HOOK_ACTIVE
    if _CRASH_HOOK_ACTIVE:
        return
    _CRASH_HOOK_ACTIVE = True

    def _sys_hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        handle_unhandled_exception(exc_type, exc_value, exc_tb, context="sys.excepthook", show_dialog=True)

    def _thread_hook(args):
        handle_unhandled_exception(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            context=f"threading.excepthook({getattr(args.thread, 'name', 'worker')})",
            show_dialog=False,
        )

    sys.excepthook = _sys_hook
    import threading
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_hook


def _window_title(shop_name: str) -> str:
    """Keep the Daqiq brand before the store name in the desktop title."""
    clean_name = (shop_name or "فروشگاه من").strip()
    return f"\u202bدقیق | {clean_name}\u202c"


class ColorSelectionButton(QPushButton):
    """Modal colour chooser with a full-width checkbox click target."""

    def __init__(self, parent=None):
        super().__init__("انتخاب رنگ", parent)
        self._colors = []
        self._selected = []
        self.setToolTip("برای انتخاب یا تغییر رنگ‌های این مورد کلیک کنید.")
        self.clicked.connect(self._open_color_dialog)

    def set_colors(self, colors, selected=None):
        previous = self._selected if selected is None else selected
        self._colors = list(dict.fromkeys(
            str(value).strip() for value in (colors or [])
            if value is not None and str(value).strip()
        ))
        available = set(self._colors)
        selected_values = list(dict.fromkeys(
            str(value).strip() for value in (previous or [])
            if value is not None and str(value).strip()
            and str(value).strip() in available
        ))
        self._selected = selected_values
        self._refresh_label()

    def selected_colors(self):
        return list(self._selected)

    def available_colors(self):
        """Return the options shown by the modal colour selector."""
        return list(self._colors)

    def _refresh_label(self):
        count = len(self._selected)
        self.setText(f"انتخاب رنگ ({count})" if count else "انتخاب رنگ")

    def _open_color_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("انتخاب رنگ")
        dialog.setLayoutDirection(Qt.RightToLeft)
        dialog.setMinimumSize(320, 360)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("رنگ‌های موردنظر را انتخاب کنید:"))
        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(True)
        content = QWidget()
        colors_layout = QVBoxLayout(content)
        colors_layout.setContentsMargins(8, 8, 8, 8)
        colors_layout.setSpacing(5)
        selected = set(self._selected)
        checkboxes = []
        for color in self._colors:
            checkbox = QCheckBox(color, content)
            checkbox.setLayoutDirection(Qt.RightToLeft)
            checkbox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            checkbox.setChecked(color in selected)
            checkbox.setMinimumHeight(30)
            checkboxes.append((color, checkbox))
            colors_layout.addWidget(checkbox)
        colors_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        buttons = QHBoxLayout()
        accept_button = QPushButton("تأیید")
        accept_button.setObjectName("btnSuccess")
        cancel_button = QPushButton("انصراف")
        cancel_button.setObjectName("btnSecondary")
        accept_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)
        buttons.addStretch(1)
        buttons.addWidget(accept_button)
        buttons.addWidget(cancel_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        apply_dialog_theme(dialog, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self._selected = [
                color for color, checkbox in checkboxes if checkbox.isChecked()
            ]
            self._refresh_label()


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
    """Format a signed price difference as discount (-) or surcharge (+)."""
    diff = (int(actual_unit) - int(suggested_unit)) * int(qty)
    if diff < 0:
        return f"-{abs(diff):,}"
    if diff > 0:
        return f"+{diff:,}"
    return "0"


def _report_sort_key(rows_data, headers, mode):
    """Build a stable sort key from report metadata and visible column names."""
    def find_column(candidates):
        for candidate in candidates:
            if candidate in headers:
                return headers.index(candidate) + 1  # index 0 is hidden activity time
        return None

    def numeric(value):
        clean = normalize_digits(str(value or "")).replace(",", "").replace("٬", "")
        clean = clean.replace("تومان", "").strip()
        try:
            return float(clean)
        except (TypeError, ValueError):
            return 0.0

    def _chrono_key(val):
        parsed = datetime_format.chronological_sort_key(val)
        return parsed if parsed is not None else (1, 0, 0, 0, 0)

    if mode in ("activity_desc", "activity_asc"):
        return lambda row: _chrono_key(row[0])
    if mode.startswith("transaction_"):
        date_idx = find_column((
            "تاریخ و ساعت", "تاریخ و ساعت فروش", "تاریخ خرید", "تاریخ",
        ))
        time_idx = find_column(("ساعت خرید",))
        if date_idx is not None and time_idx is not None:
            return lambda row: _chrono_key(f"{row[date_idx] or ''} {row[time_idx] or ''}".strip())
        return lambda row: _chrono_key(row[date_idx]) if date_idx is not None else _chrono_key(row[0])
    if mode.startswith("amount_"):
        index = find_column((
            "مبلغ کل (تومان)", "مبلغ کل فاکتور", "مبلغ دریافتی (تومان)",
            "هزینه خدمت (تومان)", "مجموع مبلغ فروش کالا", "قیمت فروش واحد",
        ))
        return lambda row: numeric(row[index]) if index is not None else 0.0
    if mode == "settlement_asc":
        index = find_column(("وضعیت تسویه",))
        return lambda row: str(row[index] or "") if index is not None else ""
    if mode == "category_asc":
        index = find_column(("دسته‌بندی",))
        return lambda row: str(row[index] or "") if index is not None else ""
    if mode == "user_asc":
        index = find_column(("کاربر ثبت‌کننده", "فروشنده", "مسئول خدمت", "مسئول خرید", "نام کاربر"))
        return lambda row: str(row[index] or "") if index is not None else ""
    return lambda row: str(row[0] or "")


def _smart_table_sort_key(value):
    """Build a locale-aware, chronological sort key for dates, times, numbers, codes and text."""
    raw = strip_bidi_controls(str(value or "")).strip()
    if not raw:
        return (3, "")

    chrono = datetime_format.chronological_sort_key(raw)
    if chrono is not None:
        return chrono

    clean = normalize_digits(raw).replace("٬", ",").replace("٫", ".")
    clean = clean.replace("\\u200e", "").replace("\\u200f", "").strip()

    numeric = clean.replace(",", "").replace("تومان", "").replace("ریال", "")
    numeric = numeric.replace("%", "").replace(" ", "")
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", numeric):
        try:
            return (1, float(numeric))
        except (TypeError, ValueError, OverflowError):
            pass

    parts = re.split(r"(\d+)", clean.casefold())
    natural = tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in parts if part
    )
    return (2, natural)


def _financial_number(value):
    """Parse a formatted Persian/English financial value without guessing text."""
    clean = normalize_digits(strip_bidi_controls(str(value or ""))).strip()
    if not clean:
        return None
    negative_parentheses = clean.startswith("(") and clean.endswith(")")
    clean = clean.strip("()").replace(",", "").replace("٬", "").replace("٫", ".")
    for token in ("تومان", "ریال", "%", " ", "\\u200e", "\\u200f"):
        clean = clean.replace(token, "")
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", clean):
        return None
    try:
        number = float(clean)
    except (TypeError, ValueError, OverflowError):
        return None
    return -abs(number) if negative_parentheses else number


class _SmartSortTableItem(QTableWidgetItem):
    """QTableWidgetItem that compares parsed values rather than rendered strings."""

    def __lt__(self, other):
        left = self.data(Qt.UserRole)
        right = other.data(Qt.UserRole)
        if left is None:
            left = _smart_table_sort_key(self.text())
        if right is None:
            right = _smart_table_sort_key(other.text())
        return left < right


class SelectAllSpinBox(QSpinBox):
    """Select the numeric editor contents whenever a user focuses or clicks it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lineEdit().installEventFilter(self)

    def _select_all_contents(self):
        editor = self.lineEdit()
        if editor is None:
            return
        text = editor.text()
        start = len(self.prefix())
        end = max(start, len(text) - len(self.suffix()))
        editor.setSelection(start, end - start)

    def eventFilter(self, watched, event):
        editor = self.lineEdit()
        if watched is editor and event.type() in (
            QEvent.FocusIn, QEvent.MouseButtonRelease,
        ):
            QTimer.singleShot(0, editor.selectAll)
        return super().eventFilter(watched, event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        QTimer.singleShot(0, self._select_all_contents)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        QTimer.singleShot(0, self._select_all_contents)


class LoginDialog(QDialog):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self.logged_employee = None
        self.require_password = bool(self.db.cfg.get("require_login_password", False))
        self.setWindowTitle("ورود با رمز عبور" if self.require_password else "انتخاب کاربر")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(430, 240)
        icon_path = resource_path("assets/daqiq_logo.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        layout = QFormLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        self.cb_emp = SearchableComboBox()
        with self.db.get_connection() as conn:
            emps = conn.execute(
                "SELECT id, name, role, phone, is_active, permissions, password, created_at, updated_at FROM employees WHERE is_active=1 ORDER BY updated_at DESC, id DESC"
            ).fetchall()
            for employee in emps:
                self.cb_emp.addItem(
                    f"{employee['name']} ({employee['role']})", dict(employee)
                )

        self.ed_pass = QLineEdit()
        self.ed_pass.setEchoMode(QLineEdit.Password)
        self.ed_pass.setPlaceholderText("رمز عبور کاربر...")
        self.ed_pass.setClearButtonEnabled(True)

        self.chk_show_pass = QCheckBox("نمایش رمز عبور")
        self.chk_show_pass.toggled.connect(
            lambda checked: self.ed_pass.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        )

        self.lbl_login_hint = QLabel(
            "کاربر دارای رمز باید رمز خود را وارد کند؛ حساب بدون رمز می‌تواند مستقیم وارد شود."
        )
        self.lbl_login_hint.setWordWrap(True)
        self.lbl_login_hint.setObjectName("settingsHint")

        btn_login = QPushButton("ورود")
        btn_login.setObjectName("btnSuccess")
        btn_login.setDefault(True)
        btn_login.clicked.connect(self._check_login)
        self.btn_login = btn_login

        layout.addRow("انتخاب کاربر:", self.cb_emp)
        layout.addRow("رمز عبور:", self.ed_pass)
        layout.addRow("", self.chk_show_pass)
        layout.addRow(self.lbl_login_hint)
        layout.addRow(btn_login)
        if self.require_password:
            self.lbl_login_hint.setText(
                "در حالت اجباری، همه کارکنان فعال باید رمز داشته باشند. حساب بدون رمز تا زمان تعریف رمز قابل ورود نیست."
            )
        self.is_dark_theme = apply_dialog_theme(self, db=self.db, parent=parent)

    def _check_login(self):
        employee = self.cb_emp.currentData()
        if not employee:
            QMessageBox.warning(self, "انتخاب کاربر", "ابتدا یک کاربر را انتخاب کنید.")
            return
        stored_hash = employee.get("password") or ""
        typed_password = normalize_digits(self.ed_pass.text())
        if self.require_password and not stored_hash:
            QMessageBox.warning(
                self,
                "رمز عبور تعریف نشده",
                "ورود این حساب به دلیل فعال بودن اجبار رمز ممکن نیست. مدیر باید ابتدا برای این کاربر رمز تعیین کند.",
            )
            return
        if stored_hash:
            if not typed_password or (
                hash_password(typed_password) != stored_hash and typed_password != stored_hash
            ):
                QMessageBox.warning(self, "خطا", "رمز عبور واردشده صحیح نیست.")
                return
        self.logged_employee = employee
        try:
            self.db.record_employee_login(employee["id"])
        except Exception:
            pass
        self.accept()


def _is_valid_sqlite_database_file(path):
    """Validate both SQLite integrity and the minimum accounting schema."""
    if not path or not os.path.isfile(path):
        return False
    if os.path.getsize(path) == 0:
        return False
    if DatabaseManager.is_database_file_encrypted(path):
        return True
    conn = None
    try:
        # Opening a verified existing file to inspect schema does not mutate it.
        conn = sqlite3.connect(os.path.abspath(path), timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
        result = conn.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            return False
        schema_version = conn.execute("PRAGMA user_version").fetchone()
        if not schema_version or int(schema_version[0]) != SCHEMA_VERSION:
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


class DatabasePasswordDialog(QDialog):
    """Theme-synchronized Persian RTL database password dialog replacing raw QInputDialog."""

    def __init__(self, parent=None, prompt_text: str = "رمز عبور پایگاه داده را وارد کنید:", is_dark: Optional[bool] = None):
        super().__init__(parent)
        self.setWindowTitle("ورود به پایگاه داده")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(420)
        icon_path = resource_path("assets/daqiq_logo.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        self.lbl_prompt = QLabel(prompt_text)
        self.lbl_prompt.setWordWrap(True)
        layout.addWidget(self.lbl_prompt)

        self.ed_password = QLineEdit()
        self.ed_password.setEchoMode(QLineEdit.Password)
        self.ed_password.setPlaceholderText("رمز عبور پایگاه داده...")
        self.ed_password.setClearButtonEnabled(True)
        layout.addWidget(self.ed_password)

        self.chk_show_password = QCheckBox("نمایش رمز عبور")
        self.chk_show_password.toggled.connect(
            lambda checked: self.ed_password.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        )
        layout.addWidget(self.chk_show_password)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        self.btn_ok = QPushButton("تأیید")
        self.btn_ok.setDefault(True)
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_ok)

        self.btn_cancel = QPushButton("انصراف")
        self.btn_cancel.setObjectName("btnSecondary")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.is_dark_theme = apply_dialog_theme(self, is_dark=is_dark, parent=parent)


def _prompt_database_password(parent=None, prompt_text="رمز عبور پایگاه داده را وارد کنید:") -> tuple:
    """Display a themed Persian RTL password dialog with 'تأیید' and 'انصراف' buttons."""
    dlg = DatabasePasswordDialog(parent=parent, prompt_text=prompt_text)
    ok = dlg.exec() == QDialog.Accepted
    return (dlg.ed_password.text() if ok else ""), ok


class DatetimeMigrationChoiceDialog(QDialog):
    """3-button dialog when calendar or time format changes."""
    MIGRATE_ALL = 1
    APPLY_NEW_ONLY = 2
    CANCEL = 0

    def __init__(self, from_cal, to_cal, from_time, to_time, parent=None):
        super().__init__(parent)
        self.choice = self.CANCEL
        self.setWindowTitle("تغییر قالب تقویم و ساعت")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setFixedSize(520, 260)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        from_cal_name = CALENDAR_NAMES_FA.get(from_cal, from_cal)
        to_cal_name = CALENDAR_NAMES_FA.get(to_cal, to_cal)
        from_time_name = TIME_FORMAT_NAMES_FA.get(from_time, from_time)
        to_time_name = TIME_FORMAT_NAMES_FA.get(to_time, to_time)

        msg = (
            f"قالب تقویم یا ساعت پایگاه داده تغییر کرده است:\n"
            f"• تقویم: از «{from_cal_name}» به «{to_cal_name}»\n"
            f"• ساعت: از «{from_time_name}» به «{to_time_name}»\n\n"
            f"لطفاً نحوه اعمال این تغییر را مشخص نمایید:"
        )
        lbl = QLabel(msg)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-size: 10pt; line-height: 1.6;")
        layout.addWidget(lbl)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_migrate_all = QPushButton("تغییر تاریخ و ساعت تمامی اطلاعات قبلی")
        btn_migrate_all.setStyleSheet("background-color: #0284c7; color: white; font-weight: bold; padding: 8px 10px; border-radius: 6px;")
        btn_migrate_all.clicked.connect(self._choose_all)

        btn_new_only = QPushButton("اعمال فقط برای جدید")
        btn_new_only.setStyleSheet("background-color: #059669; color: white; font-weight: bold; padding: 8px 10px; border-radius: 6px;")
        btn_new_only.clicked.connect(self._choose_new)

        btn_cancel = QPushButton("انصراف")
        btn_cancel.setStyleSheet("background-color: #6b7280; color: white; font-weight: bold; padding: 8px 10px; border-radius: 6px;")
        btn_cancel.clicked.connect(self._choose_cancel)

        btn_layout.addWidget(btn_migrate_all)
        btn_layout.addWidget(btn_new_only)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)
        self.is_dark_theme = apply_dialog_theme(self, parent=parent)
        btn_migrate_all.setStyleSheet("background-color: #0284c7; color: white; font-weight: bold; padding: 8px 10px; border-radius: 6px;")
        btn_new_only.setStyleSheet("background-color: #059669; color: white; font-weight: bold; padding: 8px 10px; border-radius: 6px;")
        btn_cancel.setStyleSheet("background-color: #6b7280; color: white; font-weight: bold; padding: 8px 10px; border-radius: 6px;")

    def _choose_all(self):
        self.choice = self.MIGRATE_ALL
        self.accept()

    def _choose_new(self):
        self.choice = self.APPLY_NEW_ONLY
        self.accept()

    def _choose_cancel(self):
        self.choice = self.CANCEL
        self.reject()


class _InventoryColumnChecksProxy:
    """Compatibility adapter for tests/code accessing win.inventory_export_column_checks[key].isChecked()"""
    def __init__(self, win):
        self._win = win

    class _ItemProxy:
        def __init__(self, is_checked_fn, set_checked_fn):
            self._is_checked_fn = is_checked_fn
            self._set_checked_fn = set_checked_fn

        def isChecked(self):
            return self._is_checked_fn()

        def setChecked(self, val):
            self._set_checked_fn(val)

    def __getitem__(self, key):
        def _get():
            lst = getattr(self._win, "lst_inventory_export_columns", None)
            if not lst:
                return False
            for i in range(lst.count()):
                it = lst.item(i)
                if it.data(Qt.UserRole) == key:
                    return it.checkState() == Qt.Checked
            return False

        def _set(val):
            lst = getattr(self._win, "lst_inventory_export_columns", None)
            if not lst:
                return
            for i in range(lst.count()):
                it = lst.item(i)
                if it.data(Qt.UserRole) == key:
                    it.setCheckState(Qt.Checked if val else Qt.Unchecked)
                    break

        return self._ItemProxy(_get, _set)

    def __len__(self):
        lst = getattr(self._win, "lst_inventory_export_columns", None)
        return lst.count() if lst is not None else 0

    def __iter__(self):
        lst = getattr(self._win, "lst_inventory_export_columns", None)
        if lst:
            for i in range(lst.count()):
                it = lst.item(i)
                yield it.data(Qt.UserRole)

    def keys(self):
        return list(self)

    def values(self):
        return [self[k] for k in self]

    def items(self):
        lst = getattr(self._win, "lst_inventory_export_columns", None)
        res = []
        if lst:
            for i in range(lst.count()):
                it = lst.item(i)
                k = it.data(Qt.UserRole)
                res.append((k, self[k]))
        return res

    def __contains__(self, key):
        lst = getattr(self._win, "lst_inventory_export_columns", None)
        if not lst:
            return False
        for i in range(lst.count()):
            if lst.item(i).data(Qt.UserRole) == key:
                return True
        return False


class DatabaseBootstrapDialog(QDialog):
    """First-run wizard for creating a database file or connecting an existing one."""

    def __init__(self, default_path, parent=None, is_dark_theme: bool = False):
        super().__init__(parent)
        self.setWindowTitle("راه‌اندازی اولیه پایگاه داده")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(580)
        self.selected_path = None
        self.is_dark_theme = is_dark_theme

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        title = QLabel("برای شروع، پایگاه دادهٔ فروشگاه را انتخاب کنید")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        header_row.addWidget(title, 1)

        self.btn_theme_toggle = QPushButton()
        self.btn_theme_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_theme_toggle.clicked.connect(self._toggle_theme)
        header_row.addWidget(self.btn_theme_toggle)
        layout.addLayout(header_row)

        detail = QLabel(
            "می‌توانید یک پایگاه دادهٔ جدید بسازید یا فایل پایگاه دادهٔ قبلی خود را به برنامه متصل کنید. "
            "مسیر پیشنهادی قابل ویرایش است."
        )
        detail.setWordWrap(True)
        detail.setObjectName("settingsHint")
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
        buttons.setCenterButtons(True)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._apply_theme()

    def _toggle_theme(self):
        self.is_dark_theme = not self.is_dark_theme
        try:
            cfg = load_app_config()
            cfg["theme"] = "dark" if self.is_dark_theme else "light"
            save_app_config(cfg)
        except Exception:
            pass
        self._apply_theme()

    def _apply_theme(self):
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setPalette(build_theme_palette(self.is_dark_theme))
        if self.is_dark_theme:
            self.setStyleSheet(
                "QDialog { background-color: #0f172a; color: #f8fafc; } "
                "QLabel { color: #f1f5f9; background: transparent; } "
                "QRadioButton { color: #f1f5f9; font-size: 11px; background: transparent; } "
                "QLineEdit { background-color: #1e293b; color: #f8fafc; border: 1px solid #475569; padding: 6px; border-radius: 4px; } "
                "QPushButton { background-color: #334155; color: #f8fafc; border: 1px solid #64748b; padding: 6px 12px; border-radius: 4px; } "
            )
            self.btn_theme_toggle.setText("☀️ حالت روشن")
            self.btn_theme_toggle.setStyleSheet(
                "background-color: #334155; color: #f8fafc; border: 1px solid #64748b; border-radius: 6px; padding: 4px 10px; font-weight: bold;"
            )
        else:
            self.setStyleSheet(
                "QDialog { background-color: #f8fafc; color: #0f172a; } "
                "QLabel { color: #0f172a; background: transparent; } "
                "QRadioButton { color: #0f172a; font-size: 11px; background: transparent; } "
                "QLineEdit { background-color: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; padding: 6px; border-radius: 4px; } "
                "QPushButton { background-color: #f1f5f9; color: #0f172a; border: 1px solid #cbd5e1; padding: 6px 12px; border-radius: 4px; } "
            )
            self.btn_theme_toggle.setText("🌙 حالت تاریک")
            self.btn_theme_toggle.setStyleSheet(
                "background-color: #f1f5f9; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 6px; padding: 4px 10px; font-weight: bold;"
            )
        st = self.style()
        if st is not None:
            for w in [self] + self.findChildren(QWidget):
                try:
                    st.unpolish(w)
                    st.polish(w)
                    w.update()
                except Exception:
                    pass

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
                    "فایل انتخاب‌شده سالم نیست یا با ساختار نسخه 4.1.0 سازگار نیست. "
                    "مهاجرت خودکار پشتیبانی نمی‌شود؛ برای شروع، یک پایگاه دادهٔ نسخه 4.1.0 بسازید.",
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
    """Auto-connect only when an explicit app_config.json already exists."""
    has_explicit_config = app_config_has_database_selection()
    config = load_app_config()
    configured_value = str(config.get("db_path") or "").strip()
    configured_path = (
        os.path.abspath(os.path.expanduser(configured_value))
        if configured_value else ""
    )

    # Without the user-created configuration file, even a valid database in the
    # default Documents folder must be offered through the initial setup dialog.
    if has_explicit_config:
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

    default_path = configured_path or resolve_new_database_filename()
    if os.path.isfile(default_path) and not _is_valid_sqlite_database_file(default_path):
        base_dir = os.path.dirname(default_path) or os.path.dirname(get_default_database_path())
        if os.path.isfile(base_dir):
            base_dir = os.path.dirname(base_dir)
        default_path = resolve_new_database_filename(base_dir)

    is_dark = (config.get("theme", "light") == "dark")
    if is_dark:
        dialog = DatabaseBootstrapDialog(default_path, parent, is_dark_theme=True)
    else:
        dialog = DatabaseBootstrapDialog(default_path, parent)
    if _is_valid_sqlite_database_file(default_path):
        dialog.rb_existing.setChecked(True)
    if dialog.exec() != QDialog.Accepted or not dialog.selected_path:
        return None

    chosen_path = os.path.abspath(dialog.selected_path)
    if dialog.rb_create.isChecked() or not os.path.isfile(chosen_path):
        created_db = create_and_initialize_database(chosen_path)
        try:
            created_db.close()
        except Exception:
            pass
    # Reload app_config so any Light/Dark toggle performed inside DatabaseBootstrapDialog is preserved.
    config = load_app_config()
    config["db_path"] = chosen_path
    recent = [
        os.path.abspath(path) for path in config.get("recent_databases", [])
        if path and os.path.normcase(os.path.abspath(path)) != os.path.normcase(chosen_path)
        and os.path.isfile(path)
    ]
    config["recent_databases"] = [chosen_path] + recent
    save_app_config(config)
    return chosen_path


def _resolve_startup_employee(db, parent=None):
    """Select a user at startup whenever there are multiple accounts or any account requires a password."""
    with db.get_connection() as conn:
        employees = conn.execute(
            "SELECT id, name, role, phone, is_active, permissions, password, created_at, updated_at FROM employees WHERE is_active=1 ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    if not employees:
        return None, True

    require_password = bool(db.cfg.get("require_login_password", False))
    has_password_account = any(bool(employee["password"]) for employee in employees)
    must_show_dialog = require_password or len(employees) > 1 or has_password_account
    if not must_show_dialog:
        emp = dict(employees[0])
        try:
            db.record_employee_login(emp["id"])
        except Exception:
            pass
        return emp, True

    dialog = LoginDialog(db, parent)
    if dialog.exec() != QDialog.Accepted or not dialog.logged_employee:
        return None, False
    return dialog.logged_employee, True



class MainWindow(QMainWindow):
    def __init__(
        self,
        db: DatabaseManager,
        active_employee=None,
        license_service: Optional[LicenseService] = None,
    ):
        super().__init__()
        self.db = db
        self.active_employee = active_employee
        if license_service is not None:
            self.license_service = license_service
        elif "PYTEST_CURRENT_TEST" in os.environ:
            self.license_service = None
        else:
            self.license_service = LicenseService(app_version=APP_VERSION)
        if self.license_service is not None and getattr(self.license_service, "store_name_provider", None) is None:
            self.license_service.store_name_provider = lambda: (
                (self.db.get_setting("shop_name", "") or "").strip()
                if getattr(self, "db", None) is not None else ""
            )
        if self.active_employee and isinstance(self.active_employee, dict) and self.active_employee.get("id"):
            try:
                self.db.record_employee_login(self.active_employee["id"])
            except Exception:
                pass
        icon_path = resource_path("assets/daqiq_logo.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        initial_shop_name = (self.db.get_setting("shop_name", "فروشگاه من") or "فروشگاه من").strip()
        self.setWindowTitle(_window_title(initial_shop_name))
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
        self._table_print_buttons = {}
        self._dashboard_card_styles = []
        self.catalog_config = self._effective_product_catalog_config()
        self._catalog_settings_state = CatalogSettingsState()
        self._settings_snapshot = None
        self._staged_db_password_action = None
        self._staged_db_startup_prompt = None

        self._apply_styles()
        self._build_ui()
        self._install_tab_lock_filter()
        self._apply_global_rtl_alignment()
        app = QApplication.instance()
        if (
            app is not None
            and not getattr(app, "_daqiq_msg_polisher", None)
            and not getattr(app, "_accounting_message_box_polisher", None)
        ):
            polisher = _MessageBoxPolisher(app)
            app.installEventFilter(polisher)
            app._accounting_message_box_polisher = polisher
        self.tabs.currentChanged.connect(self._on_main_tab_changed)
        self._setup_timers()
        self.refresh_all_data()
        self._sync_date_widgets_calendar()
        self._apply_employee_permissions(select_first_unlocked=True)
        self._sync_all_default_operators()

    def _select_default_operator(self, combo: QComboBox):
        if combo is None or not hasattr(self, "active_employee") or not self.active_employee:
            return
        active_id = self.active_employee.get("id")
        active_name = (self.active_employee.get("name") or "").strip()
        if active_id is not None:
            idx = combo.findData(active_id)
            if idx != -1:
                combo.setCurrentIndex(idx)
                return
        if active_name:
            idx = combo.findText(active_name)
            if idx != -1:
                combo.setCurrentIndex(idx)
                return

    def _sync_all_default_operators(self):
        for cb in (
            getattr(self, "cb_batch_buyer", None),
            getattr(self, "cb_sale_seller", None),
            getattr(self, "cb_srv_seller", None),
            getattr(self, "cb_upg_tech", None),
        ):
            if cb is not None:
                self._select_default_operator(cb)

    def closeEvent(self, event):
        try:
            if hasattr(self, "backup_timer") and self.backup_timer.isActive():
                self.backup_timer.stop()
            if hasattr(self, "clock_timer") and self.clock_timer.isActive():
                self.clock_timer.stop()
            if hasattr(self, "_license_timer") and self._license_timer.isActive():
                self._license_timer.stop()
            if hasattr(self, "db") and self.db:
                with self.db.get_connection() as conn:
                    conn.commit()
                    try:
                        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    except Exception:
                        pass
        except Exception:
            pass
        super().closeEvent(event)

    def _apply_global_rtl_alignment(self):
        """Use compact right-anchored captions throughout the RTL interface."""
        for group_box in self.findChildren(QGroupBox):
            group_box.setAlignment(Qt.AlignRight)
        for label in self.findChildren(QLabel):
            if label.text().strip() == "/" or label.objectName() == "appVersion":
                continue
            if label.objectName() == "activeDbPath":
                label.setLayoutDirection(Qt.LeftToRight)
                label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            else:
                label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                label.setLayoutDirection(Qt.RightToLeft)
            if label.objectName() not in {
                "reportSummary", "saleSummary", "settingsHint", "activeDbPath",
                "activeUser",
            }:
                label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

    def get_active_calendar(self) -> str:
        return self.db.get_setting("calendar_format", "jalali") or "jalali"

    def get_active_time_format(self) -> str:
        return self.db.get_setting("time_format", "24h") or "24h"

    def get_today_date_str(self) -> str:
        return datetime_format.get_today_date(self.get_active_calendar())

    def get_now_time_str(self) -> str:
        return datetime_format.get_now_time(self.get_active_time_format())

    def get_now_datetime_str(self) -> str:
        return datetime_format.get_now_datetime(self.get_active_calendar(), self.get_active_time_format())

    def _sync_date_widgets_calendar(self):
        cal = self.get_active_calendar()
        for attr in (
            "dt_batch_date",
            "dt_sale_date",
            "dt_war_start",
            "dt_war_end",
            "dt_upg_date",
            "dt_rep_from",
            "dt_rep_to",
        ):
            widget = getattr(self, attr, None)
            if widget is not None and hasattr(widget, "set_calendar_format"):
                widget.set_calendar_format(cal, convert_existing=False)

    def _switch_active_employee(self):
        with self.db.get_connection() as conn:
            active_count = conn.execute(
                "SELECT COUNT(*) FROM employees WHERE is_active=1"
            ).fetchone()[0]
        if not active_count:
            QMessageBox.information(
                self, "کاربری ثبت نشده", "برای این پایگاه داده هنوز کاربر فعالی ثبت نشده است."
            )
            return
        dialog = LoginDialog(self.db, self)
        if dialog.exec() == QDialog.Accepted and dialog.logged_employee:
            self.active_employee = dialog.logged_employee
            self._update_active_user_badge()
            self._apply_employee_permissions()
            self.refresh_all_data()
            self._sync_all_default_operators()

    @staticmethod
    def _default_access_scope(policy):
        policy = str(policy or "")
        mode = "all" if "دسترسی کامل" in policy or "مدیر ارشد" in policy else "self"
        return {"mode": mode, "access_levels": [], "user_ids": []}

    def _load_access_scope(self, name, policy="", fallback=None):
        fallback = fallback if isinstance(fallback, dict) else {}
        default_scope = self._default_access_scope(policy)
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT mode FROM access_level_data_scopes WHERE access_level_name=?",
                (name,),
            ).fetchone()
            if row:
                mode = row["mode"]
                role_names = [
                    item["selected_access_level_name"]
                    for item in conn.execute(
                        "SELECT selected_access_level_name FROM access_level_scope_levels "
                        "WHERE access_level_name=? ORDER BY selected_access_level_name",
                        (name,),
                    ).fetchall()
                ]
                user_ids = [
                    int(item["employee_id"])
                    for item in conn.execute(
                        "SELECT employee_id FROM access_level_scope_users "
                        "WHERE access_level_name=? ORDER BY employee_id",
                        (name,),
                    ).fetchall()
                ]
            else:
                mode = fallback.get("mode", default_scope["mode"])
                role_names = fallback.get("access_levels", [])
                user_ids = fallback.get("user_ids", [])
        if mode not in {"all", "self", "access_levels", "users"}:
            mode = default_scope["mode"]
        return {
            "mode": mode,
            "access_levels": list(dict.fromkeys(
                str(value).strip() for value in role_names
                if value is not None and str(value).strip()
            )),
            "user_ids": list(dict.fromkeys(
                int(value) for value in user_ids
                if str(value).strip().lstrip("-").isdigit() and int(value) > 0
            )),
        }

    def _get_access_levels(self):
        raw = self.db.get_setting("access_levels", "")
        try:
            saved = json.loads(raw) if raw else None
        except (TypeError, ValueError, json.JSONDecodeError):
            saved = None
        if not isinstance(saved, list):
            saved = copy.deepcopy(DEFAULT_ACCESS_LEVELS)
        allowed_policies = {item["policy"] for item in DEFAULT_ACCESS_LEVELS}
        result, seen = [], set()
        for item in saved:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            policy = str(item.get("policy") or "").strip()
            key = normalize_catalog_label(name)
            if not name or policy not in allowed_policies or not key or key in seen:
                continue
            raw_permissions = item.get("permissions")
            permissions = (
                [p for p in raw_permissions if p in ALL_PERMISSION_KEYS]
                if isinstance(raw_permissions, list)
                else list(ROLE_PERMISSION_PRESETS.get(policy, []))
            )
            result.append({
                "name": name,
                "policy": policy,
                "permissions": list(dict.fromkeys(permissions)),
                "data_scope": self._load_access_scope(
                    name, policy, item.get("data_scope")
                ),
            })
            seen.add(key)
        if result:
            return result
        return [
            {
                **copy.deepcopy(level),
                "permissions": list(ROLE_PERMISSION_PRESETS.get(level["policy"], [])),
                "data_scope": self._load_access_scope(level["name"], level["policy"]),
            }
            for level in DEFAULT_ACCESS_LEVELS
        ]

    def _visible_employee_ids(self):
        if not self.active_employee:
            return None
        access_name = str(self.active_employee.get("permissions") or "").strip()
        level = next(
            (item for item in self._get_access_levels() if item["name"] == access_name),
            None,
        )
        if level is None:
            return None if self._is_full_admin() else {int(self.active_employee["id"])}
        scope = level.get("data_scope") or self._default_access_scope(level["policy"])
        mode = scope.get("mode", "self")
        if mode == "all":
            return None
        if mode == "self":
            return {int(self.active_employee["id"])}
        if mode == "users":
            return {int(value) for value in scope.get("user_ids", [])}
        names = list(dict.fromkeys(scope.get("access_levels", [])))
        if not names:
            return set()
        marks = ",".join("?" for _ in names)
        with self.db.get_connection() as conn:
            rows = conn.execute(
                f"SELECT id FROM employees WHERE permissions IN ({marks})", tuple(names)
            ).fetchall()
        return {int(row["id"]) for row in rows}

    def _employee_scope_filter(self, *columns):
        employee_ids = self._visible_employee_ids()
        if employee_ids is None:
            return None, ()
        if not employee_ids:
            return "0=1", ()
        ids = tuple(sorted(employee_ids))
        marks = ",".join("?" for _ in ids)
        return "(" + " OR ".join(f"{column} IN ({marks})" for column in columns) + ")", ids * len(columns)

    def _execute_scoped_query(self, conn, query, *columns, parameters=()):
        """Add an employee-visibility predicate to the outer SELECT statement."""
        predicate, scope_params = self._employee_scope_filter(*columns)
        if predicate is None:
            return conn.execute(query, parameters)

        upper = query.upper()
        cuts = [
            upper.find(marker)
            for marker in (" GROUP BY ", " ORDER BY ", " LIMIT ")
        ]
        cuts = [position for position in cuts if position >= 0]
        cut = min(cuts) if cuts else len(query)
        head, tail = query[:cut], query[cut:]

        # Ignore WHERE keywords in nested SELECT expressions.
        depth = 0
        quote = None
        where_position = None
        index = 0
        while index < len(head):
            char = head[index]
            if quote:
                if char == quote:
                    if index + 1 < len(head) and head[index + 1] == quote:
                        index += 1
                    else:
                        quote = None
            elif char in ("'", '"', "`"):
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif depth == 0 and head[index:index + 6].upper() == " WHERE":
                where_position = index
                break
            index += 1

        if where_position is None:
            scoped_head = head.rstrip() + " WHERE " + predicate
        else:
            prefix = head[:where_position]
            existing_conditions = head[where_position + 6:].strip()
            scoped_head = (
                prefix + " WHERE (" + existing_conditions + ") AND " + predicate
            )

        return conn.execute(
            scoped_head + tail,
            tuple(parameters) + tuple(scope_params),
        )

    def _permission_policy(self, permission_name):
        for level in self._get_access_levels():
            if level["name"] == permission_name:
                return level["policy"]
        return permission_name or ""

    def _permission_grants(self, permission_name=None):
        """Return the explicitly assigned capability keys for an access level."""
        target = permission_name
        if target is None and self.active_employee:
            target = self.active_employee.get("permissions")
        for level in self._get_access_levels():
            if level["name"] == target:
                return set(level.get("permissions") or [])
        for level in self._get_access_levels():
            if level["policy"] == target:
                return set(level.get("permissions") or [])
        if str(target or "").strip() in ("all", "دسترسی کامل"):
            return set(ALL_PERMISSION_KEYS)
        return set()

    def _refresh_employee_permission_combo(self):
        if not hasattr(self, "cb_emp_perm"):
            return
        current = self.cb_emp_perm.currentText()
        self.cb_emp_perm.blockSignals(True)
        self.cb_emp_perm.clear()
        for level in self._get_access_levels():
            self.cb_emp_perm.addItem(level["name"], level["name"])
        index = self.cb_emp_perm.findText(current)
        self.cb_emp_perm.setCurrentIndex(index if index >= 0 else 0)
        self.cb_emp_perm.blockSignals(False)

    def _refresh_access_level_settings_combo(self):
        if not hasattr(self, "cb_cfg_access_level"):
            return
        current = self.cb_cfg_access_level.currentData()
        self.cb_cfg_access_level.blockSignals(True)
        self.cb_cfg_access_level.clear()
        for level in self._get_access_levels():
            self.cb_cfg_access_level.addItem(level["name"], level["name"])
        index = self.cb_cfg_access_level.findData(current)
        self.cb_cfg_access_level.setCurrentIndex(
            index if index >= 0 else (0 if self.cb_cfg_access_level.count() else -1)
        )
        self.cb_cfg_access_level.blockSignals(False)
        self._on_access_level_selected()

    def _persist_access_levels(self, levels):
        normalized = []
        for source in levels:
            level = dict(source)
            level["data_scope"] = level.get("data_scope") or self._default_access_scope(
                level.get("policy")
            )
            normalized.append(level)

        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                ("access_levels", json.dumps(normalized, ensure_ascii=False)),
            )
            role_names = [level["name"] for level in normalized]
            employee_ids = {
                int(row["id"]) for row in conn.execute("SELECT id FROM employees").fetchall()
            }
            for level in normalized:
                scope = level["data_scope"]
                mode = scope.get("mode", "self")
                if mode not in {"all", "self", "access_levels", "users"}:
                    mode = self._default_access_scope(level.get("policy"))["mode"]
                conn.execute(
                    "INSERT OR REPLACE INTO access_level_data_scopes(access_level_name, mode) "
                    "VALUES (?, ?)",
                    (level["name"], mode),
                )
                conn.execute(
                    "DELETE FROM access_level_scope_levels WHERE access_level_name=?",
                    (level["name"],),
                )
                conn.execute(
                    "DELETE FROM access_level_scope_users WHERE access_level_name=?",
                    (level["name"],),
                )
                conn.executemany(
                    "INSERT OR IGNORE INTO access_level_scope_levels "
                    "(access_level_name, selected_access_level_name) VALUES (?, ?)",
                    [
                        (level["name"], name)
                        for name in scope.get("access_levels", [])
                        if name != level["name"]
                    ],
                )
                conn.executemany(
                    "INSERT OR IGNORE INTO access_level_scope_users "
                    "(access_level_name, employee_id) VALUES (?, ?)",
                    [
                        (level["name"], int(user_id))
                        for user_id in scope.get("user_ids", [])
                        if int(user_id) in employee_ids
                    ],
                )
            if role_names:
                marks = ",".join("?" for _ in role_names)
                conn.execute(
                    f"DELETE FROM access_level_data_scopes "
                    f"WHERE access_level_name NOT IN ({marks})",
                    tuple(role_names),
                )
            else:
                conn.execute("DELETE FROM access_level_data_scopes")
            conn.commit()

        self._refresh_access_level_settings_combo()
        self._refresh_employee_permission_combo()
        if hasattr(self, "tbl_employees"):
            self._refresh_employees_table()
        self._apply_employee_permissions()

    def _on_access_level_selected(self, *_):
        if not hasattr(self, "ed_cfg_access_level"):
            return
        name = self.cb_cfg_access_level.currentData()
        level = next((item for item in self._get_access_levels() if item["name"] == name), None)
        self.ed_cfg_access_level.setText(level["name"] if level else "")
        if not level:
            return
        index = self.cb_cfg_access_policy.findData(level["policy"])
        self.cb_cfg_access_policy.blockSignals(True)
        self.cb_cfg_access_policy.setCurrentIndex(index if index >= 0 else 0)
        self.cb_cfg_access_policy.blockSignals(False)
        grants = set(level.get("permissions") or [])
        for key, checkbox in self.access_permission_checks.items():
            checkbox.setChecked(key in grants)
        scope = level.get("data_scope") or self._default_access_scope(level["policy"])
        index = self.cb_cfg_data_scope_mode.findData(scope["mode"])
        self.cb_cfg_data_scope_mode.setCurrentIndex(index if index >= 0 else 0)
        self._refresh_access_scope_choices(level["name"], scope)

    def _on_permission_preset_changed(self, *_):
        policy = self.cb_cfg_access_policy.currentData()
        grants = set(ROLE_PERMISSION_PRESETS.get(policy, []))
        for key, checkbox in self.access_permission_checks.items():
            checkbox.setChecked(key in grants)

    def _refresh_access_scope_choices(self, current_level_name, scope):
        checked_levels = set(scope.get("access_levels", []))
        self.lst_cfg_scope_levels.clear()
        for level in self._get_access_levels():
            if level["name"] == current_level_name:
                continue
            item = QListWidgetItem(level["name"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if level["name"] in checked_levels else Qt.Unchecked
            )
            self.lst_cfg_scope_levels.addItem(item)

        checked_users = {int(value) for value in scope.get("user_ids", [])}
        self.lst_cfg_scope_users.clear()
        with self.db.get_connection() as conn:
            employees = conn.execute(
                "SELECT id, name, role, permissions FROM employees ORDER BY name COLLATE NOCASE, id"
            ).fetchall()
        for employee in employees:
            employee_id = int(employee["id"])
            item = QListWidgetItem(
                f"{employee['name']} — {employee['role']} ({employee['permissions']})"
            )
            item.setData(Qt.UserRole, employee_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if employee_id in checked_users else Qt.Unchecked
            )
            self.lst_cfg_scope_users.addItem(item)
        self._on_data_scope_mode_changed()

    def _on_data_scope_mode_changed(self, *_):
        mode = self.cb_cfg_data_scope_mode.currentData()
        self.scope_levels_container.setVisible(mode == "access_levels")
        self.scope_users_container.setVisible(mode == "users")

    def _collect_access_scope(self):
        return {
            "mode": self.cb_cfg_data_scope_mode.currentData() or "self",
            "access_levels": [
                self.lst_cfg_scope_levels.item(i).text()
                for i in range(self.lst_cfg_scope_levels.count())
                if self.lst_cfg_scope_levels.item(i).checkState() == Qt.Checked
            ],
            "user_ids": [
                int(self.lst_cfg_scope_users.item(i).data(Qt.UserRole))
                for i in range(self.lst_cfg_scope_users.count())
                if self.lst_cfg_scope_users.item(i).checkState() == Qt.Checked
            ],
        }

    def _collect_access_permissions(self):
        return [
            key for key, checkbox in self.access_permission_checks.items()
            if checkbox.isChecked()
        ]

    def _add_access_level(self):
        name = self.ed_cfg_access_level.text().strip()
        policy = self.cb_cfg_access_policy.currentData()
        levels = self._get_access_levels()
        if not name:
            QMessageBox.warning(self, "نام سطح دسترسی", "نام سطح دسترسی را وارد کنید.")
            return
        if any(normalize_catalog_label(item["name"]) == normalize_catalog_label(name) for item in levels):
            QMessageBox.warning(self, "نام تکراری", "این سطح دسترسی از قبل ثبت شده است.")
            return
        levels.append({
            "name": name,
            "policy": policy,
            "permissions": self._collect_access_permissions(),
            "data_scope": self._collect_access_scope(),
        })
        self._persist_access_levels(levels)
        self.ed_cfg_access_level.clear()

    def _update_access_level(self):
        old_name = self.cb_cfg_access_level.currentData()
        new_name = self.ed_cfg_access_level.text().strip()
        new_policy = self.cb_cfg_access_policy.currentData()
        if not old_name or not new_name:
            return
        levels = self._get_access_levels()
        if any(
            item["name"] != old_name
            and normalize_catalog_label(item["name"]) == normalize_catalog_label(new_name)
            for item in levels
        ):
            QMessageBox.warning(self, "نام تکراری", "این سطح دسترسی از قبل ثبت شده است.")
            return
        with self.db.get_connection() as conn:
            assigned = conn.execute(
                "SELECT COUNT(*) FROM employees WHERE permissions=?", (old_name,)
            ).fetchone()[0]
        if assigned and not _ask_yes_no(
            self, "ویرایش سطح دسترسی",
            f"این سطح دسترسی به {assigned} کاربر اختصاص داده شده است. تغییر آن برای همهٔ این کاربران اعمال شود؟",
        ):
            return
        for item in levels:
            if item["name"] == old_name:
                item.update({
                    "name": new_name,
                    "policy": new_policy,
                    "permissions": self._collect_access_permissions(),
                    "data_scope": self._collect_access_scope(),
                })
                break
        for item in levels:
            scope = item.get("data_scope") or {}
            scope["access_levels"] = [
                new_name if value == old_name else value
                for value in scope.get("access_levels", [])
            ]
            item["data_scope"] = scope
        if assigned:
            with self.db.get_connection() as conn:
                conn.execute(
                    "UPDATE employees SET permissions=? WHERE permissions=?",
                    (new_name, old_name),
                )
                conn.commit()
        if self.active_employee and self.active_employee.get("permissions") == old_name:
            self.active_employee["permissions"] = new_name
        self._persist_access_levels(levels)

    def _delete_access_level(self):
        old_name = self.cb_cfg_access_level.currentData()
        if not old_name:
            return
        levels = self._get_access_levels()
        if len(levels) <= 1:
            QMessageBox.warning(self, "آخرین سطح دسترسی", "حداقل یک سطح دسترسی باید باقی بماند.")
            return
        fallback = next(
            (item["name"] for item in levels
             if item["policy"] == "فروش و خدمات (گزارش محدود به عملکرد خود)" and item["name"] != old_name),
            None,
        )
        if fallback is None:
            fallback = next(item["name"] for item in levels if item["name"] != old_name)
        with self.db.get_connection() as conn:
            assigned = conn.execute(
                "SELECT COUNT(*) FROM employees WHERE permissions=?", (old_name,)
            ).fetchone()[0]
        message = (
            f"این سطح دسترسی به {assigned} کاربر اختصاص داده شده است. "
            f"پس از حذف، دسترسی آن کاربران به «{fallback}» تغییر می‌کند. ادامه می‌دهید؟"
            if assigned else "این سطح دسترسی حذف شود؟"
        )
        if not _ask_yes_no(self, "حذف سطح دسترسی", message):
            return
        if assigned:
            with self.db.get_connection() as conn:
                conn.execute(
                    "UPDATE employees SET permissions=? WHERE permissions=?",
                    (fallback, old_name),
                )
                conn.commit()
        if self.active_employee and self.active_employee.get("permissions") == old_name:
            self.active_employee["permissions"] = fallback
        remaining = [item for item in levels if item["name"] != old_name]
        for item in remaining:
            scope = item.get("data_scope") or {}
            scope["access_levels"] = [
                fallback if value == old_name else value
                for value in scope.get("access_levels", [])
            ]
            item["data_scope"] = scope
        self._persist_access_levels(remaining)

    def _is_scoped_access(self):
        """Whether the active user's record visibility is narrower than global."""
        return self._visible_employee_ids() is not None

    def _is_full_admin(self):
        if not self.active_employee:
            return True
        permission = self._permission_policy(
            self.active_employee.get("permissions") or ""
        )
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
                "☀️ حالت روشن" if self.db.cfg["theme"] == "dark" else "🌙 حالت تیره"
            )
            self._update_license_banner()
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

    _TAB_MODULES = (
        "dashboard", "products", "batches", "sales", "services",
        "upgrades", "suppliers", "reports", "employees", "settings",
    )

    def _is_license_feature_enabled(self, feature_id: str) -> bool:
        if getattr(self, "license_service", None) is None:
            return True
        return bool(self.license_service.is_feature_enabled(feature_id))

    def _show_license_locked_dialog(self, feature_id_or_name: str):
        """Show the uniform polite Persian locked-access dialog with a shortcut to License Management."""
        section_label = get_feature_label_fa(feature_id_or_name)
        svc = getattr(self, "license_service", None)
        support_phone = ""
        if svc is not None and hasattr(svc, "get_support_phone"):
            try:
                support_phone = str(svc.get_support_phone() or "").strip()
            except Exception:
                support_phone = ""
        msg = QMessageBox(self)
        msg.setWindowTitle("دسترسی لایسنس")
        msg.setIcon(QMessageBox.Information)
        msg.setLayoutDirection(Qt.RightToLeft)
        body = (
            f"بخش «{section_label}» در لایسنس فعال شما مجاز نیست.\n"
            "برای تهیه یا فعال‌سازی لایسنس این بخش، از پنجره مدیریت لایسنس اقدام فرمایید."
        )
        if support_phone:
            body += f"\nشماره تماس پشتیبانی: {support_phone}"
        msg.setText(body)
        btn_lic = msg.addButton("مدیریت لایسنس 🔑", QMessageBox.ActionRole)
        msg.addButton("بستن", QMessageBox.AcceptRole)
        _center_message_buttons(msg)
        msg.exec()
        if msg.clickedButton() is btn_lic:
            self._open_license_dialog()

    def _require_license_feature(self, feature_id: str) -> bool:
        if self._is_license_feature_enabled(feature_id):
            return True
        self._show_license_locked_dialog(feature_id)
        return False

    def _require_license_write_allowed(self) -> bool:
        lic_svc = getattr(self, "license_service", None)
        if lic_svc is None or not hasattr(lic_svc, "is_write_allowed") or lic_svc.is_write_allowed():
            return True
        QMessageBox.warning(
            self,
            "حالت فقط خواندنی",
            "لایسنس در وضعیت فقط خواندنی قرار دارد و ایجاد یا تغییر تنظیمات و داده‌ها مجاز نیست.\n"
            "امکان مشاهده گزارش‌ها، چاپ، پشتیبان‌گیری و خروجی اکسل همچنان فعال است.",
        )
        return False

    def _install_tab_lock_filter(self):
        """Intercept clicks on license-locked tabs cleanly without switching or flashing content."""
        if not hasattr(self, "tabs") or self.tabs is None:
            return
        tab_bar = self.tabs.tabBar()
        if tab_bar is None or getattr(self, "_tab_lock_filter", None) is not None:
            return

        win = self

        class _TabLockFilter(QObject):
            def eventFilter(self, watched, event):
                if watched is tab_bar and event.type() in (
                    QEvent.MouseButtonPress, QEvent.MouseButtonDblClick
                ):
                    pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                    idx = tab_bar.tabAt(pos)
                    if 0 <= idx < len(win._TAB_MODULES):
                        module = win._TAB_MODULES[idx]
                        lic_feature = TAB_MODULE_TO_FEATURE.get(module, module)
                        if not win._is_license_feature_enabled(lic_feature):
                            if event.type() == QEvent.MouseButtonPress:
                                win._show_license_locked_dialog(lic_feature)
                            return True
                return False

        self._tab_lock_filter = _TabLockFilter(tab_bar)
        tab_bar.installEventFilter(self._tab_lock_filter)

    def _select_first_unlocked_tab(self, force_first: bool = False):
        """Land on the first unlocked tab automatically without spamming popups."""
        if not hasattr(self, "tabs") or self.tabs is None:
            return
        cur = self.tabs.currentIndex()
        if not force_first and 0 <= cur < len(self._TAB_MODULES):
            cur_mod = self._TAB_MODULES[cur]
            cur_feat = TAB_MODULE_TO_FEATURE.get(cur_mod, cur_mod)
            if self.tabs.isTabEnabled(cur) and self._is_license_feature_enabled(cur_feat):
                return
        for idx, module in enumerate(self._TAB_MODULES):
            lic_feat = TAB_MODULE_TO_FEATURE.get(module, module)
            if self.tabs.isTabEnabled(idx) and self._is_license_feature_enabled(lic_feat):
                self.tabs.blockSignals(True)
                self.tabs.setCurrentIndex(idx)
                self.tabs.blockSignals(False)
                return

    def _apply_employee_permissions(self, select_first_unlocked: bool = False):
        """Enforce per-module view and per-action grants selected in the RBAC editor."""
        grants = self._permission_grants()
        if not self.active_employee:
            grants = set(ALL_PERMISSION_KEYS)

        tab_modules = self._TAB_MODULES
        is_scoped = self._is_scoped_access()
        lic_svc = getattr(self, "license_service", None)
        has_fast_eval = callable(getattr(type(lic_svc), "is_feature_enabled_for_result", None)) if lic_svc is not None else False
        lic_res = lic_svc.check_license() if has_fast_eval else None
        write_allowed = bool(lic_svc.is_write_allowed()) if lic_svc is not None and hasattr(lic_svc, "is_write_allowed") else True
        if hasattr(self, "db") and self.db is not None and hasattr(self.db, "set_read_only_mode"):
            readonly_reason = ""
            if not write_allowed:
                support_phone = lic_svc.get_support_phone() if hasattr(lic_svc, "get_support_phone") else ""
                readonly_reason = (
                    "لایسنس در دوره مهلت فقط خواندنی قرار دارد؛ امکان مشاهده گزارش‌ها، پشتیبان‌گیری و خروجی اکسل فعال است "
                    "اما ثبت یا ویرایش داده‌های جدید تا تمدید لایسنس مجاز نیست."
                )
                if support_phone:
                    readonly_reason += f"\nشماره تماس پشتیبانی: {support_phone}"
            self.db.set_read_only_mode(not write_allowed, readonly_reason)
        self.tabs.blockSignals(True)
        try:
            for index, module in enumerate(tab_modules):
                emp_allowed = f"{module}.view" in grants
                lic_feature = TAB_MODULE_TO_FEATURE.get(module, module)
                if lic_svc is None:
                    lic_allowed = True
                elif has_fast_eval:
                    lic_allowed = bool(lic_svc.is_feature_enabled_for_result(lic_feature, lic_res))
                else:
                    lic_allowed = self._is_license_feature_enabled(lic_feature)
                allowed = emp_allowed and lic_allowed
                # Keep tab enabled only when both RBAC and license allow it;
                # _TabLockFilter intercepts clicks even when disabled by license.
                self.tabs.setTabEnabled(index, allowed)
                page_widget = self.tabs.widget(index)
                if page_widget is not None:
                    page_widget.setEnabled(allowed)
                if not lic_allowed:
                    self.tabs.setTabToolTip(index, "این بخش در لایسنس فعال شما مجاز نیست.")
                else:
                    self.tabs.setTabToolTip(index, "")
        finally:
            self.tabs.blockSignals(False)

        if select_first_unlocked:
            self._select_first_unlocked_tab(force_first=True)
        elif hasattr(self, "tabs") and self.tabs is not None:
            cur = self.tabs.currentIndex()
            if not (0 <= cur < len(tab_modules) and self.tabs.isTabEnabled(cur)):
                self._select_first_unlocked_tab(force_first=False)

        for permission_key, widget in getattr(
            self, "_dashboard_permission_widgets", {}
        ).items():
            widget.setVisible(
                "dashboard.view" in grants and permission_key in grants
            )

        for button in self.findChildren(QPushButton):
            page_index = -1
            for index in range(self.tabs.count()):
                page = self.tabs.widget(index)
                if page is not None and page.isAncestorOf(button):
                    page_index = index
                    break
            if page_index < 0:
                continue
            module = tab_modules[page_index]
            label = button.text().strip()
            if button.objectName() == "btnDanger" or any(
                token in label for token in ("حذف", "🗑")
            ):
                action = "delete"
            elif any(token in label for token in ("افزودن", "ثبت", "➕", "✅")):
                action = "create"
            elif any(token in label for token in ("ویرایش", "ذخیره تغییرات", "ذخیره ویرایش")):
                action = "edit"
            elif any(token in label for token in ("خروجی", "📥", "📤")):
                action = "export"
            elif "چاپ" in label or "🖨" in label:
                action = "print"
            else:
                action = None
            if action == "print":
                button.setEnabled(
                    f"{module}.view" in grants and self._is_license_feature_enabled("print_invoices")
                )
                continue
            if module == "settings":
                if button in (
                    getattr(self, "btn_manual_bk", None),
                    getattr(self, "btn_open_db_dir", None),
                    getattr(self, "btn_export_prod_tax_section", None),
                    getattr(self, "btn_export_prod_tax_full", None),
                    getattr(self, "btn_export_serv_tax_section", None),
                    getattr(self, "btn_export_serv_tax_full", None),
                ):
                    if button is getattr(self, "btn_manual_bk", None):
                        button.setEnabled("settings.manage_database" in grants)
                    elif action == "export":
                        button.setEnabled("settings.view" in grants)
                    else:
                        button.setEnabled("settings.manage_database" in grants)
                    continue
                if hasattr(self, "gb_access_levels") and self.gb_access_levels.isAncestorOf(button):
                    required_permission = "settings.manage_access"
                elif hasattr(self, "gb_db") and self.gb_db.isAncestorOf(button):
                    required_permission = "settings.manage_database"
                else:
                    required_permission = "settings.edit"
                enabled = required_permission in grants
                if not write_allowed and action != "export":
                    enabled = False
                button.setEnabled(enabled)
            elif action:
                enabled = f"{module}.{action}" in grants
                if not write_allowed and action in ("create", "edit", "delete"):
                    enabled = False
                button.setEnabled(enabled)

        if hasattr(self, "cb_rep_emp"):
            self.cb_rep_emp.setEnabled(not is_scoped)
            if is_scoped:
                self.cb_rep_emp.setCurrentIndex(0)
        if hasattr(self, "btn_safe_export"):
            self.btn_safe_export.setEnabled(
                not is_scoped and "inventory_export.export" in grants
            )
        if hasattr(self, "cb_rep_sort"):
            self.cb_rep_sort.setEnabled("reports.view" in grants)
        if hasattr(self, "cb_cfg_access_level"):
            access_enabled = (
                "settings.manage_access" in grants
                and "settings.view" in grants
            )
            for widget in (
                self.cb_cfg_access_level, self.ed_cfg_access_level,
                self.cb_cfg_access_policy, self.cb_cfg_data_scope_mode,
                self.lst_cfg_scope_levels, self.lst_cfg_scope_users,
            ):
                widget.setEnabled(access_enabled)
            for checkbox in self.access_permission_checks.values():
                checkbox.setEnabled(access_enabled)
        if hasattr(self, "gb_access_levels"):
            self.gb_access_levels.setEnabled(
                write_allowed and "settings.manage_access" in grants and "settings.view" in grants
            )
        if hasattr(self, "gb_db"):
            self.gb_db.setEnabled(
                "settings.manage_database" in grants and "settings.view" in grants
            )
            for db_mut_btn in (
                getattr(self, "btn_new_db", None),
                getattr(self, "btn_open_existing_db", None),
                getattr(self, "btn_restore_bk", None),
            ):
                if db_mut_btn is not None:
                    db_mut_btn.setEnabled(write_allowed and "settings.manage_database" in grants)
            if hasattr(self, "btn_manual_bk") and self.btn_manual_bk is not None:
                self.btn_manual_bk.setEnabled("settings.manage_database" in grants)
        if hasattr(self, "gb_inventory_export"):
            self.gb_inventory_export.setEnabled(
                write_allowed and "settings.edit" in grants and "settings.view" in grants
            )
        can_edit_settings = write_allowed and "settings.edit" in grants and "settings.view" in grants
        if hasattr(self, "gb_report_export_cfg"):
            self.gb_report_export_cfg.setEnabled(can_edit_settings)
        for cat_widget in (
            getattr(self, "gb_categories", None),
            getattr(self, "gb_subcategories", None),
            getattr(self, "gb_attributes", None),
            getattr(self, "gb_colors", None),
            getattr(self, "gb_service_types", None),
            getattr(self, "btn_clear_prod_tax", None),
            getattr(self, "btn_import_prod_tax", None),
            getattr(self, "btn_clear_serv_tax", None),
            getattr(self, "btn_import_serv_tax", None),
        ):
            if cat_widget is not None:
                cat_widget.setEnabled(can_edit_settings)
        if hasattr(self, "gb_gen"):
            self.gb_gen.setEnabled(can_edit_settings)
        if hasattr(self, "gb_security"):
            self.gb_security.setEnabled(
                write_allowed and ("settings.edit" in grants or "settings.manage_access" in grants) and "settings.view" in grants
            )
        for export_btn in (
            getattr(self, "btn_export_prod_tax_section", None),
            getattr(self, "btn_export_prod_tax_full", None),
            getattr(self, "btn_export_serv_tax_section", None),
            getattr(self, "btn_export_serv_tax_full", None),
        ):
            if export_btn is not None:
                export_btn.setEnabled("settings.view" in grants)
        if hasattr(self, "pr_sale_actual"):
            self.pr_sale_actual.setReadOnly(
                (not write_allowed) or (not self._is_license_feature_enabled("price_edit"))
            )
        if hasattr(self, "btn_switch_user"):
            self.btn_switch_user.setEnabled(True)


    def _apply_styles(self):
        dark = self.db.cfg.get("theme", "light") == "dark"
        bg = "#111827" if dark else "#f8fafc"
        panel = "#1f2937" if dark else "#ffffff"
        text = "#f1f5f9" if dark else "#0f172a"
        muted = "#cbd5e1" if dark else "#475569"
        input_bg = "#263449" if dark else "#ffffff"
        alternate = "#29384d" if dark else "#f1f5f9"
        border = "#52627a" if dark else "#cbd5e1"
        hover = "#3b4b63" if dark else "#e2e8f0"
        accent = "#3b82f6"
        version_color = "#93c5fd" if dark else "#1d4ed8"
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                font-family: 'Segoe UI', 'Tahoma', sans-serif; font-size: 13px;
                background-color: {bg}; color: {text};
            }}
            QGroupBox {{ font-weight: bold; border: 1px solid {border}; border-radius: 8px;
                margin-top: 10px; padding-top: 12px; background-color: {panel}; }}
            QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top right;
                padding: 0 8px; color: {muted}; }}
            QLineEdit, QComboBox, QSpinBox, QDateEdit {{
                border: 1px solid {border}; border-radius: 5px;
                padding: 5px 8px; background-color: {input_bg}; color: {text}; min-height: 24px;
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
                border: 1.5px solid {accent};
            }}
            QLineEdit:read-only {{
                background-color: {alternate}; color: {muted};
                border-color: {border};
            }}
            QLabel#settingsHint {{ color: {muted}; font-size: 11px; }}
            QLabel#reportSummary {{
                color: {text}; background: {alternate};
                border: 1px solid {border}; border-radius: 6px;
                padding: 8px; font-size: 14px; font-weight: 700;
            }}
            QLabel#saleSummary {{
                color: {"#bbf7d0" if dark else "#065f46"};
                background: {"#123b30" if dark else "#ecfdf5"};
                border: 1px solid {"#276749" if dark else "#a7f3d0"};
                border-radius: 6px; padding: 6px; font-weight: 700;
            }}
            QComboBox QAbstractItemView {{
                background: {input_bg}; color: {text}; border: 1px solid {border};
                selection-background-color: #2563eb; selection-color: #ffffff;
                outline: none; padding: 3px;
            }}
            QComboBox QAbstractItemView::item {{ padding: 5px 8px; }}
            QComboBox QAbstractItemView::item:hover {{ background: {hover}; color: {text}; }}
            QListWidget {{
                background: {input_bg}; color: {text}; border: 1px solid {border};
                border-radius: 7px; padding: 4px; outline: none;
            }}
            QListWidget::item {{ padding: 5px 7px; border-radius: 4px; }}
            QListWidget::item:hover {{ background: {hover}; color: {text}; }}
            QListWidget::item:selected {{ background: #2563eb; color: #ffffff; }}
            QListWidget#recentDatabasesList::item {{
                padding: 0px; border: none; background: transparent;
            }}
            QListWidget#recentDatabasesList::item:hover,
            QListWidget#recentDatabasesList::item:selected {{
                background: transparent; color: {text}; border: none;
            }}
            QWidget#databaseRecentRow {{
                background: {panel}; border: 1px solid {border};
                border-radius: 9px;
            }}
            QWidget#databaseRecentRow:hover {{
                background: {alternate}; border: 1px solid {accent};
            }}
            QPushButton {{ background-color: #2563eb; color: #ffffff; border: none;
                border-radius: 6px; padding: 7px 14px; font-weight: bold; }}
            QPushButton:hover {{ background-color: #1d4ed8; }}
            QPushButton#btnDanger {{ background-color: #dc2626; }}
            QPushButton#btnDanger:hover {{ background-color: #b91c1c; }}
            QPushButton#btnSuccess {{ background-color: #059669; }}
            QPushButton#btnSuccess:hover {{ background-color: #047857; }}
            QPushButton#btnSecondary {{ background-color: #475569; }}
            QPushButton#collapsibleSectionHeader {{
                background: {panel}; color: {text}; border: 1px solid {border};
                border-radius: 7px; text-align: center; font-weight: 700;
            }}
            QPushButton#collapsibleSectionHeader:hover {{ background: {hover}; border-color: {accent}; }}
            QTableWidget {{ background-color: {panel}; color: {text};
                alternate-background-color: {alternate}; gridline-color: {border};
                border: 1px solid {border}; border-radius: 6px; }}
            QTableWidget::item:hover {{ background: {hover}; color: {text}; }}
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
            QLabel#appVersion {{
                color: {version_color}; background: {alternate}; border: 1px solid {border};
                border-radius: 6px; font-size: 13px; font-weight: 700; padding: 6px;
            }}
            QLabel#activeDbPath {{
                background: {input_bg}; color: {text}; border: 1px solid {border};
                border-radius: 6px; padding: 8px;
            }}
            QScrollBar:vertical {{ width: 14px; margin: 0px; background: {alternate}; border-radius: 7px; }}
            QScrollBar::handle:vertical {{ min-height: 36px; background: #718096; border-radius: 7px; }}
            QScrollBar:horizontal {{ height: 14px; margin: 0px; background: {alternate}; border-radius: 7px; }}
            QScrollBar::handle:horizontal {{ min-width: 36px; background: #718096; border-radius: 7px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                width: 0px; height: 0px; border: none; background: transparent;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px; height: 0px; border: none; background: transparent;
            }}
            QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical,
            QScrollBar::left-arrow:horizontal, QScrollBar::right-arrow:horizontal {{
                width: 0px; height: 0px; image: none; border: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: transparent;
            }}
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
        title_lbl = QLabel(bidi_isolate_text(f"دقیق | {shop_name}"))
        self.lbl_store_name = title_lbl
        title_lbl.setStyleSheet(
            "color: #ffffff; font-size: 15px; font-weight: bold; "
            "background: rgba(255,255,255,0.14); border: 1px solid rgba(255,255,255,0.22); "
            "border-radius: 7px; padding: 5px 10px;"
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

        btn_safe_export = QPushButton("📤 خروجی موجودی همکار")
        self.btn_safe_export = btn_safe_export
        btn_safe_export.setObjectName("btnSuccess")
        btn_safe_export.setToolTip(
            "تهیه فایل اکسل از کالاهای موجود در انبار بدون اطلاعات قیمت خرید و سود (مناسب ارسال به همکاران)"
        )
        btn_safe_export.clicked.connect(self._export_safe_inventory)
        btn_safe_export.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.lbl_active_user = QLabel()
        self.lbl_active_user.setObjectName("activeUser")
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

        self.btn_theme = QPushButton("☀️ حالت روشن" if self.db.cfg.get("theme") == "dark" else "🌙 حالت تیره")
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

        # نوار هشدار وضعیت لایسنس
        self.license_banner_frame = QFrame()
        self.license_banner_frame.setObjectName("licenseBannerFrame")
        self.license_banner_frame.setVisible(False)
        banner_layout = QHBoxLayout(self.license_banner_frame)
        banner_layout.setContentsMargins(10, 5, 10, 5)
        banner_layout.setSpacing(10)
        self.lbl_license_banner = QLabel()
        self.lbl_license_banner.setObjectName("licenseBannerLabel")
        self.lbl_license_banner.setWordWrap(True)
        self.lbl_license_banner.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.btn_renew_banner = QPushButton("تمدید/مدیریت لایسنس")
        self.btn_renew_banner.setObjectName("licenseBannerButton")
        self.btn_renew_banner.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_renew_banner.setMinimumWidth(140)
        self.btn_renew_banner.clicked.connect(self._open_license_dialog)
        banner_layout.addWidget(self.lbl_license_banner, 1)
        banner_layout.addWidget(self.btn_renew_banner, 0)
        main_layout.addWidget(self.license_banner_frame)

        # --- تب‌های برنامه با ترتیب جدید (بند ۵: تب ارتقای لپ‌تاپ بلافاصله بعد از مدیریت خدمات) ---
        self.tabs = QTabWidget()
        self.tabs.tabBarClicked.connect(self._on_tab_bar_clicked)
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
        self._update_license_banner()

        # بررسی دوره‌ای پس‌زمینه (هر ۶۰ ثانیه برای لایسنس و هر ۴ ثانیه برای همگام‌سازی شبکه بدون مزاحمت برای فرم‌های در حال ویرایش)
        self._license_timer = QTimer(self)
        self._license_timer.timeout.connect(self._periodic_license_check)
        self._license_timer.start(60000)

        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._poll_external_database_changes)
        self._sync_timer.start(4000)

    def _has_unsaved_active_form_edits(self) -> bool:
        """Return True if the user currently has a record open for editing or unsaved form input."""
        if any(
            getattr(self, attr, None) is not None
            for attr in (
                "selected_product_id",
                "selected_batch_id",
                "selected_sale_id",
                "selected_srv_rec_id",
                "selected_upgrade_id",
                "selected_supplier_id",
            )
        ):
            return True
        for attr in ("ed_prod_brand", "ed_prod_model", "ed_batch_inv", "ed_sale_customer"):
            w = getattr(self, attr, None)
            if w is not None and w.isModified():
                return True
        return False

    def _poll_external_database_changes(self):
        """Lightweight PRAGMA data_version polling for multi-PC LAN synchronization."""
        if not getattr(self, "db", None) or not hasattr(self.db, "poll_external_data_version"):
            return
        try:
            _ver, changed = self.db.poll_external_data_version()
        except Exception:
            return
        if not changed:
            return
        if self._has_unsaved_active_form_edits():
            if hasattr(self, "statusBar") and self.statusBar() is not None:
                self.statusBar().showMessage("🔄 تغییرات جدیدی از شبکه دریافت شد (فرم فعلی بدون تغییر ماند).", 4000)
            return
        self.refresh_all_data()

    def _update_license_banner(self, res: Optional[ValidationResult] = None):
        if not getattr(self, "license_service", None):
            if hasattr(self, "license_banner_frame"):
                self.license_banner_frame.setVisible(False)
            return
        if res is None:
            res = self.license_service.check_license()

        is_dark = bool(hasattr(self, "db") and self.db and self.db.cfg.get("theme", "light") == "dark")
        support_phone = ""
        if hasattr(self.license_service, "get_support_phone"):
            try:
                support_phone = str(self.license_service.get_support_phone() or "").strip()
            except Exception:
                support_phone = ""

        def _style_banner(tone: str):
            if is_dark:
                palettes = {
                    "danger": ("#3b1219", "#ef4444", "#fecaca", "#dc2626", "#b91c1c"),
                    "warning": ("#3b280b", "#f59e0b", "#fde68a", "#d97706", "#b45309"),
                    "info": ("#1e293b", "#60a5fa", "#bfdbfe", "#2563eb", "#1d4ed8"),
                }
            else:
                palettes = {
                    "danger": ("#fef2f2", "#ef4444", "#991b1b", "#dc2626", "#b91c1c"),
                    "warning": ("#fffbeb", "#f59e0b", "#92400e", "#d97706", "#b45309"),
                    "info": ("#eff6ff", "#3b82f6", "#1e3a8a", "#2563eb", "#1d4ed8"),
                }
            bg, border, fg, btn_bg, btn_hover = palettes[tone]
            self.license_banner_frame.setStyleSheet(
                f"QFrame#licenseBannerFrame {{ background-color: {bg}; border: 1.5px solid {border}; border-radius: 8px; padding: 6px 12px; }}"
            )
            self.lbl_license_banner.setStyleSheet(
                f"color: {fg}; font-weight: bold; font-size: 12px; background: transparent;"
            )
            if hasattr(self, "btn_renew_banner") and self.btn_renew_banner is not None:
                self.btn_renew_banner.setStyleSheet(
                    f"QPushButton {{ background-color: {btn_bg}; color: #ffffff; font-weight: bold; "
                    f"padding: 5px 12px; border-radius: 6px; border: none; }} "
                    f"QPushButton:hover {{ background-color: {btn_hover}; }}"
                )

        if not res or not res.is_valid or not res.license:
            if hasattr(self, "license_banner_frame"):
                if res is not None and not res.is_valid:
                    _style_banner("danger")
                    msg = res.message_fa or "اعتبار لایسنس به پایان رسیده است؛ دسترسی به بخش‌ها محدود شد."
                    if support_phone:
                        msg += f" • پشتیبانی: {support_phone}"
                    self.lbl_license_banner.setText(f"⛔ {msg}")
                    self.license_banner_frame.setVisible(True)
                else:
                    self.license_banner_frame.setVisible(False)
            return

        payload = res.license.payload
        phone_part = f" • پشتیبانی: {support_phone}" if support_phone else ""
        if res.in_grace_period:
            _style_banner("danger" if res.grace_mode == "readonly" else "warning")
            mode_fa = get_grace_mode_label_fa(res.grace_mode)
            rem_days = (
                f"{res.grace_days_remaining} روز باقیمانده"
                if res.grace_days_remaining is not None
                else "فعال"
            )
            mode_note = (
                "مشاهده، چاپ، پشتیبان‌گیری و خروجی اکسل فعال است."
                if res.grace_mode == "readonly"
                else "پیش از اتمام مهلت برای تمدید اقدام کنید."
            )
            self.lbl_license_banner.setText(
                f"⚠️ اعتبار لایسنس به پایان رسیده است ({rem_days} • حالت {mode_fa}): {mode_note}{phone_part}"
            )
            self.license_banner_frame.setVisible(True)
        elif res.days_remaining is not None and res.days_remaining <= (payload.expiry_warning_days or 14):
            _style_banner("warning")
            self.lbl_license_banner.setText(
                f"⚠️ تنها {res.days_remaining} روز تا پایان اعتبار لایسنس باقی مانده است؛ لطفاً برای تمدید اقدام کنید.{phone_part}"
            )
            self.license_banner_frame.setVisible(True)
        elif res.is_trial:
            _style_banner("info")
            rem_str = f" ({res.days_remaining} روز باقیمانده)" if res.days_remaining is not None else ""
            self.lbl_license_banner.setText(f"🔷 نسخه آزمایشی دقیق فعال است{rem_str}.")
            self.license_banner_frame.setVisible(True)
        else:
            self.license_banner_frame.setVisible(False)

    def _periodic_license_check(self):
        if not getattr(self, "license_service", None):
            return
        res = self.license_service.check_license()
        self._update_license_banner(res)
        self._apply_employee_permissions()

    def _export_device_request_from_settings(self):
        if not getattr(self, "license_service", None):
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "دریافت فایل مشخصات سیستم",
            "Daqiq_Hardware_Request.daqreq",
            "Daqiq Request (*.daqreq);;JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        dark = self.db.cfg.get("theme", "light") == "dark" if hasattr(self, "db") and self.db else False
        try:
            self.license_service.export_device_request_file(path)
            ThemedNoticeDialog(
                parent=self,
                title="ذخیره موفق",
                message=f"فایل مشخصات سیستم با موفقیت ذخیره شد:\n{path}\n\nلطفاً این فایل را برای پشتیبانی ارسال فرمایید.",
                kind="success",
                is_dark_theme=dark,
            ).exec()
        except Exception as e:
            ThemedNoticeDialog(
                parent=self,
                title="خطا در ذخیره فایل",
                message=f"امکان ذخیره فایل مشخصات سیستم وجود ندارد:\n{e}",
                kind="error",
                is_dark_theme=dark,
            ).exec()

    def _refresh_dashboard_card_styles(self):
        dark = self.db.cfg.get("theme", "light") == "dark"
        theme_key = "dark" if dark else "light"
        theme_tokens = DASHBOARD_CARD_TOKENS.get(theme_key, DASHBOARD_CARD_TOKENS["light"])
        surface = theme_tokens["surface"]
        border_color = theme_tokens["border"]
        title_color = theme_tokens["title"]
        roles_dict = theme_tokens["roles"]

        for box, title_label, value_label, role_or_color in getattr(
            self, "_dashboard_card_styles", []
        ):
            role = LEGACY_COLOR_TO_ROLE.get(str(role_or_color).lower(), str(role_or_color))
            card_token = roles_dict.get(role, roles_dict["primary"])
            accent = card_token["accent"]
            val_color = card_token["val"]

            box.setStyleSheet(
                f"QGroupBox {{ border: 1px solid {border_color}; border-right: 5px solid {accent}; "
                f"background: {surface}; border-radius: 8px; padding: 8px; }}"
            )
            title_label.setStyleSheet(
                f"color: {title_color}; background: transparent; "
                "font-size: 12px; font-weight: bold;"
            )
            value_label.setStyleSheet(
                f"color: {val_color}; background: transparent; "
                "font-size: 18px; font-weight: bold;"
            )

    def _setup_timers(self):
        try:
            self.clock_timer = QTimer(self)
            self.clock_timer.timeout.connect(self._update_clock)
            self.clock_timer.start(1000)

            self.backup_timer = QTimer(self)
            self.backup_timer.timeout.connect(self._run_periodic_backup)
            self._restart_backup_timer()
        except Exception:
            pass

    def _restart_backup_timer(self):
        try:
            if not self.db.get_db_config("auto_backup_enabled", True):
                self.backup_timer.stop()
                return

            try:
                interval_minutes = int(self.db.get_db_config("auto_backup_interval_min", 60))
            except (TypeError, ValueError):
                interval_minutes = 60
            interval_seconds = max(1, min(1440, interval_minutes)) * 60
            last_success = float(self.db.get_last_automatic_backup_timestamp() or 0)
            if last_success > 1e11:
                last_success = last_success / 1000.0
            now_ts = time.time()
            if 0 < last_success <= now_ts:
                elapsed = now_ts - last_success
                delay_seconds = max(1.0, interval_seconds - elapsed)
            else:
                delay_seconds = float(interval_seconds)

            msec = int(delay_seconds * 1000)
            # Clamp strictly to safe 32-bit positive signed integer range [1_000, 2_147_483_647]
            msec = max(1_000, min(2_147_483_647, msec))
            self.backup_timer.setSingleShot(True)
            self.backup_timer.start(msec)
        except (OverflowError, ValueError, OSError, TypeError):
            try:
                self.backup_timer.setSingleShot(True)
                self.backup_timer.start(60 * 1000)
            except Exception:
                pass

    def _run_periodic_backup(self):
        if not self._is_license_feature_enabled("auto_backup"):
            return
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
        cal = self.get_active_calendar()
        tf = self.get_active_time_format()
        today_g = date.today()
        # Python date.weekday(): Mon=0 .. Sun=6 -> Saturday=0 .. Friday=6
        w_day = PERSIAN_WEEKDAYS.get((today_g.weekday() + 2) % 7, "")
        date_str = datetime_format.get_today_date(cal)
        time_str = datetime_format.get_now_time(tf)
        cal_title = CALENDAR_NAMES_FA.get(cal, "شمسی")
        self.lbl_live_clock.setText(
            f"📅 {date_str}  |  ⏰ \u200e{time_str}"
        )
        self.lbl_live_clock.setToolTip(
            f"تاریخ {cal_title}: {w_day} {date_str}\nساعت محلی: \u200e{time_str}"
        )

    def _export_safe_inventory(self):
        if not self._require_license_feature("partner_export"):
            return
        default_file = get_next_excel_filename(os.path.expanduser("~"), "R")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "ذخیره خروجی موجودی همکار",
            default_file,
            "Excel Files (*.xlsx)",
        )
        if path:
            try:
                selected_columns = self._get_selected_inventory_export_columns()
                if not selected_columns:
                    QMessageBox.warning(
                        self, "خروجی موجودی همکار",
                        "برای تهیهٔ فایل، دست‌کم یک ستون را در تنظیمات خروجی فعال کنید.",
                    )
                    return
                export_safe_inventory_excel(
                    self.db,
                    path,
                    (self.db.get_setting("shop_name", "فروشگاه من") or "فروشگاه من").strip(),
                    included_columns=selected_columns,
                )
                QMessageBox.information(
                    self,
                    "ذخیره شد",
                    f"فایل «خروجی موجودی همکار» با موفقیت ذخیره شد:\n{path}",
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
        tbl.setSelectionMode(QAbstractItemView.ExtendedSelection)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.setSortingEnabled(False)
        tbl.horizontalHeader().setSectionsClickable(True)
        tbl.horizontalHeader().setSortIndicatorShown(True)
        tbl._last_sorted_column = None
        tbl._last_sort_order = None
        tbl.horizontalHeader().sectionClicked.connect(
            lambda column, table=tbl: self._sort_table_by_header(table, column)
        )
        tbl.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        tbl.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        tbl.verticalScrollBar().setSingleStep(18)
        tbl.horizontalScrollBar().setSingleStep(18)
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        tbl.horizontalHeader().setStretchLastSection(True)
        return tbl

    def _sort_table_by_header(self, table: QTableWidget, column: int):
        """Toggle ascending/descending sorting for the clicked table column."""
        if table is None or column < 0 or column >= table.columnCount():
            return
        is_same_column = getattr(table, "_last_sorted_column", None) == column
        last_order = getattr(table, "_last_sort_order", None)
        next_order = (
            Qt.DescendingOrder
            if is_same_column and last_order == Qt.AscendingOrder
            else Qt.AscendingOrder
        )
        table._last_sorted_column = column
        table._last_sort_order = next_order
        table.horizontalHeader().setSortIndicator(column, next_order)
        table.sortItems(column, next_order)

    def _add_scrollable_tab(self, tab: QWidget, title: str):
        """Wrap each page in a scroll area so compact windows never crush form controls."""
        tab.setMinimumWidth(940)
        scroll = SmoothScrollArea()
        scroll.setWidget(tab)
        return self.tabs.addTab(scroll, title)

    def _create_table_print_button(self, table, key: str) -> QPushButton:
        btn_print = QPushButton("🖨️ چاپ")
        btn_print.setObjectName("btnSecondary")
        btn_print.setMinimumHeight(34)
        btn_print.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        btn_print.setToolTip("پیش‌نمایش و چاپ سیاه‌وسفید A4 / A5 ردیف‌های انتخاب‌شده")
        btn_print.clicked.connect(
            lambda _checked=False, print_key=key, target_table=table: self._handle_print_request(
                print_key, target_table
            )
        )
        self._table_print_buttons[key] = btn_print
        return btn_print

    @staticmethod
    def _get_selected_row_indices(table: QTableWidget) -> list[int]:
        if table is None:
            return []
        rows = []
        sel_model = table.selectionModel()
        if sel_model is not None:
            rows = sorted({idx.row() for idx in sel_model.selectedRows() if not table.isRowHidden(idx.row())})
        if not rows:
            rows = sorted({item.row() for item in table.selectedItems() if not table.isRowHidden(item.row())})
        return rows

    def _build_print_builder_for_selection(self, key: str, table: QTableWidget, selected_rows: list[int]):
        headers = [
            (table.horizontalHeaderItem(c).text() if table.horizontalHeaderItem(c) else f"ستون {c + 1}")
            for c in range(table.columnCount())
        ]
        matrix = [
            [
                strip_bidi_controls(table.item(r, c).text()) if table.item(r, c) else ""
                for c in range(table.columnCount())
            ]
            for r in selected_rows
        ]
        shop_info = {
            "shop_name": (self.db.get_setting("shop_name", "فروشگاه دقیق") or "فروشگاه دقیق").strip(),
            "print_time": self.get_now_datetime_str(),
        }

        effective_kind = key
        rep_title = ""
        rep_summary = ""
        if key == "reports" and hasattr(self, "cb_rep_type"):
            rep_title = self.cb_rep_type.currentText().strip()
            rep_summary = strip_bidi_controls(self.lbl_rep_totals.text()) if hasattr(self, "lbl_rep_totals") else ""
            if rep_title.startswith("۱."):
                effective_kind = "sales"
            elif rep_title.startswith("۲."):
                effective_kind = "batches"
            elif rep_title.startswith("۱۱."):
                effective_kind = "upgrades"
            elif rep_title.startswith("۱۲."):
                effective_kind = "service_records"

        if effective_kind == "sales":
            records = []
            if key == "sales":
                sale_ids = []
                for row_vals in matrix:
                    try:
                        sale_ids.append(int(row_vals[0]))
                    except (TypeError, ValueError, IndexError):
                        pass
                if sale_ids:
                    placeholders = ",".join("?" for _ in sale_ids)
                    with self.db.get_connection() as conn:
                        db_rows = conn.execute(
                            f"""
                            SELECT s.*, p.code AS p_code, p.category, p.sub_category, p.brand, p.model,
                                   e.name AS emp_name
                            FROM sales s
                            JOIN products p ON s.product_id = p.id
                            LEFT JOIN employees e ON s.seller_employee_id = e.id
                            WHERE s.id IN ({placeholders})
                            ORDER BY s.id ASC
                            """,
                            sale_ids,
                        ).fetchall()
                    for r in db_rows:
                        prod_prefix = str(r["sub_category"] or r["category"] or "").strip()
                        bm = " ".join(v for v in (str(r["brand"] or "").strip(), str(r["model"] or "").strip()) if v)
                        title = " | ".join(v for v in (prod_prefix, bm) if v) or r["p_code"]
                        war = (
                            f"{r['warranty_company']} ({r['warranty_end']})".strip(" ()")
                            if (r["warranty_company"] or r["warranty_end"])
                            else "ندارد"
                        )
                        records.append({
                            "invoice_number": r["invoice_number"],
                            "product_code": r["p_code"],
                            "product_title": title,
                            "specifications": r["specifications"] or "",
                            "colors_display": "، ".join(self._decode_colors(r["colors_json"])),
                            "serial_number": r["serial_number"] or "",
                            "qty": r["qty"],
                            "actual_unit_price": r["actual_unit_price"],
                            "total_discount": r["total_discount"],
                            "total_amount": r["total_amount"],
                            "paid_amount": r["paid_amount"],
                            "settlement_status": r["settlement_status"],
                            "sale_datetime": r["sale_datetime"],
                            "warranty_text": war,
                            "customer_name": r["customer_name"] or "",
                            "customer_phone": r["customer_phone"] or "",
                            "seller_name": r["emp_name"] or "",
                            "notes": r["notes"] or "",
                        })
            if not records:
                # Fallback from table columns, explicitly stripped of cost/profit fields
                col_idx = {h: i for i, h in enumerate(headers)}
                def _pick(row_vals, names, default=""):
                    for nm in names:
                        if nm in col_idx and col_idx[nm] < len(row_vals):
                            return row_vals[col_idx[nm]]
                    return default
                def _to_int(val):
                    try:
                        return int(str(val or "0").replace(",", "").strip() or 0)
                    except (TypeError, ValueError):
                        return 0
                for row_vals in matrix:
                    records.append({
                        "invoice_number": _pick(row_vals, ("شماره فاکتور", "شماره فاکتور فروش")),
                        "product_code": _pick(row_vals, ("کد کالا",)),
                        "product_title": _pick(row_vals, ("نام و مشخصات کالا", "کالا / مدل")),
                        "specifications": _pick(row_vals, ("مشخصات فنی فروخته‌شده",)),
                        "colors_display": _pick(row_vals, ("رنگ‌های فروخته‌شده",)),
                        "serial_number": _pick(row_vals, ("شماره سریال", "شماره سریال فروخته‌شده")),
                        "qty": _to_int(_pick(row_vals, ("تعداد", "تعداد فروش"), "1")),
                        "actual_unit_price": _to_int(_pick(row_vals, ("قیمت فروش واحد",))),
                        "total_discount": 0,
                        "total_amount": _to_int(_pick(row_vals, ("مبلغ کل فاکتور",))),
                        "paid_amount": _to_int(_pick(row_vals, ("مبلغ دریافتی", "دریافتی فروش"))),
                        "settlement_status": _pick(row_vals, ("وضعیت تسویه", "وضعیت تسویه فروش")),
                        "sale_datetime": _pick(row_vals, ("تاریخ و ساعت", "تاریخ و ساعت فروش")),
                        "warranty_text": _pick(row_vals, ("گارانتی و انقضا",), "ندارد"),
                        "customer_name": _pick(row_vals, ("خریدار", "نام مشتری")),
                        "customer_phone": _pick(row_vals, ("شماره تماس مشتری",)),
                        "seller_name": _pick(row_vals, ("فروشنده",)),
                        "notes": "",
                    })
            return "فاکتور فروش", (lambda is_a5=False, recs=records, info=shop_info: build_sales_invoice_html(recs, info, is_a5=is_a5))

        if effective_kind == "batches":
            records = []
            if key == "batches":
                batch_ids = []
                for row_vals in matrix:
                    try:
                        batch_ids.append(int(row_vals[0]))
                    except (TypeError, ValueError, IndexError):
                        pass
                if batch_ids:
                    placeholders = ",".join("?" for _ in batch_ids)
                    with self.db.get_connection() as conn:
                        db_rows = conn.execute(
                            f"""
                            SELECT b.*, p.code AS p_code, p.category, p.sub_category, p.brand, p.model,
                                   s.name AS sup_name
                            FROM batches b
                            JOIN products p ON b.product_id = p.id
                            LEFT JOIN suppliers s ON b.supplier_id = s.id
                            WHERE b.id IN ({placeholders})
                            ORDER BY b.id ASC
                            """,
                            batch_ids,
                        ).fetchall()
                    for r in db_rows:
                        tot_bill = r["unit_purchase_price"] * r["initial_qty"] + r["extra_cost_total"]
                        debt = receivable_balance(tot_bill, r["paid_amount"], r["settlement_status"])
                        records.append({
                            "batch_code": r["batch_code"],
                            "invoice_number": r["invoice_number"],
                            "purchase_date": r["purchase_date"],
                            "supplier_name": r["sup_name"] or r["supplier_name_snapshot"] or "-",
                            "product_title": self._format_product_picker_label(dict(r)),
                            "specs": r["final_specs"] or r["initial_specs"] or "",
                            "colors": "، ".join(self._decode_colors(r["colors_json"])),
                            "serials": r["serial_numbers"] or "",
                            "initial_qty": r["initial_qty"],
                            "unit_purchase_price": r["unit_purchase_price"],
                            "extra_cost_total": r["extra_cost_total"],
                            "total_bill": tot_bill,
                            "paid_amount": r["paid_amount"],
                            "remaining_bill": debt,
                            "settlement_status": r["settlement_status"],
                        })
            if not records:
                col_idx = {h: i for i, h in enumerate(headers)}
                def _pick_b(row_vals, names, default=""):
                    for nm in names:
                        if nm in col_idx and col_idx[nm] < len(row_vals):
                            return row_vals[col_idx[nm]]
                    return default
                def _to_int_b(val):
                    try:
                        return int(str(val or "0").replace(",", "").strip() or 0)
                    except (TypeError, ValueError):
                        return 0
                for row_vals in matrix:
                    records.append({
                        "batch_code": _pick_b(row_vals, ("کد محموله",)),
                        "invoice_number": _pick_b(row_vals, ("شماره فاکتور", "شماره فاکتور خرید")),
                        "purchase_date": _pick_b(row_vals, ("تاریخ خرید",)),
                        "supplier_name": _pick_b(row_vals, ("تأمین‌کننده",)),
                        "product_title": _pick_b(row_vals, ("کالا و مدل", "کالا / مدل")),
                        "specs": _pick_b(row_vals, ("مشخصات فنی / توضیحات", "مشخصات فنی محموله")),
                        "colors": _pick_b(row_vals, ("رنگ‌های محموله",)),
                        "serials": _pick_b(row_vals, ("شماره سریال‌ها",)),
                        "initial_qty": _to_int_b(_pick_b(row_vals, ("تعداد خرید", "تعداد اولیه"), "0")),
                        "unit_purchase_price": _to_int_b(_pick_b(row_vals, ("قیمت خرید واحد",))),
                        "extra_cost_total": _to_int_b(_pick_b(row_vals, ("هزینه جانبی محموله",))),
                        "total_bill": _to_int_b(_pick_b(row_vals, ("بهای کل محموله (تومان)",))),
                        "paid_amount": _to_int_b(_pick_b(row_vals, ("پرداخت‌شده", "پرداخت‌شده خرید"))),
                        "remaining_bill": _to_int_b(_pick_b(row_vals, ("مانده بدهی", "مانده بدهی خرید"))),
                        "settlement_status": _pick_b(row_vals, ("وضعیت تسویه", "وضعیت تسویه خرید")),
                    })
            return "رسید خرید و ثبت محموله", (lambda is_a5=False, recs=records, info=shop_info: build_purchase_voucher_html(recs, info, is_a5=is_a5))

        if effective_kind in ("service_records", "upgrades"):
            col_idx = {h: i for i, h in enumerate(headers)}
            def _pick_s(row_vals, names, default=""):
                for nm in names:
                    if nm in col_idx and col_idx[nm] < len(row_vals):
                        return row_vals[col_idx[nm]]
                return default
            def _to_int_s(val):
                try:
                    return int(str(val or "0").replace(",", "").strip() or 0)
                except (TypeError, ValueError):
                    return 0
            records = []
            if effective_kind == "upgrades":
                for row_vals in matrix:
                    records.append({
                        "upgrade_date": _pick_s(row_vals, ("تاریخ ارتقا",)),
                        "target_batch_code": _pick_s(row_vals, ("کد محموله هدف", "محموله هدف")),
                        "target_qty": _to_int_s(_pick_s(row_vals, ("تعداد هدف",), "1")) or 1,
                        "part_desc": _pick_s(row_vals, ("قطعه مصرفی", "محموله/شرح قطعه", "شرح قطعه")),
                        "added_cost_unit": _to_int_s(_pick_s(row_vals, ("هزینه اضافه‌شده به هر واحد", "اجرت ارتقا"))),
                        "technician_name": _pick_s(row_vals, ("مسئول / تکنسین", "تکنسین / کاربر")),
                        "new_specs": _pick_s(row_vals, ("مشخصات جدید",)),
                        "notes": _pick_s(row_vals, ("توضیحات",)),
                    })
                return "رسید ارتقای کالا", (lambda is_a5=False, recs=records, info=shop_info: build_service_or_upgrade_html("upgrades", recs, info, is_a5=is_a5))
            for row_vals in matrix:
                records.append({
                    "invoice_number": _pick_s(row_vals, ("شماره فاکتور",)),
                    "service_datetime": _pick_s(row_vals, ("تاریخ و ساعت",)),
                    "service_type": _pick_s(row_vals, ("نوع خدمت",)),
                    "service_name": _pick_s(row_vals, ("نام خدمت",)),
                    "customer_name": _pick_s(row_vals, ("مشتری", "نام مشتری")),
                    "technician_name": _pick_s(row_vals, ("مسئول خدمت",)),
                    "service_fee": _to_int_s(_pick_s(row_vals, ("هزینه خدمت (تومان)",))),
                    "paid_amount": _to_int_s(_pick_s(row_vals, ("مبلغ دریافتی",))),
                    "settlement_status": _pick_s(row_vals, ("وضعیت تسویه",)),
                    "description": _pick_s(row_vals, ("شرح خدمات", "توضیحات")),
                })
            return "فاکتور خدمات و تعمیرات", (lambda is_a5=False, recs=records, info=shop_info: build_service_or_upgrade_html("services", recs, info, is_a5=is_a5))

        title_map = {
            "products": "گزارش چاپی کالاها",
            "suppliers": "گزارش چاپی تأمین‌کنندگان",
            "employees": "گزارش چاپی کاربران",
            "service_catalog": "گزارش چاپی تعرفه خدمات",
            "dashboard_low": "گزارش چاپی هشدار موجودی",
            "dashboard_employees": "گزارش چاپی عملکرد فروشندگان",
        }
        report_title = (
            f"گزارش چاپی {rep_title}" if rep_title and not rep_title.startswith("گزارش چاپی")
            else title_map.get(key, "گزارش چاپی")
        )
        return report_title, (
            lambda is_a5=False, t=report_title, h=headers, m=matrix, s=rep_summary, info=shop_info:
            build_structured_table_report_html(t, h, m, summary_text=s, shop_info=info, is_a5=is_a5)
        )

    def _handle_print_request(self, key: str, table: QTableWidget):
        if not self._require_license_feature("print_invoices"):
            return None
        selected_rows = self._get_selected_row_indices(table)
        if not selected_rows:
            QMessageBox.information(
                self, "چاپ", "لطفاً حداقل یک ردیف را از جدول انتخاب کنید."
            )
            return None
        title, builder = self._build_print_builder_for_selection(key, table, selected_rows)
        dlg = PrintPreviewDialog(builder, title=f"پیش‌نمایش چاپ — {title}", parent=self)
        self._last_print_preview_dialog = dlg
        dlg.exec()
        return dlg

    def _add_table_search(self, parent_layout, table, key, placeholder):
        """Keep the existing search position while adding print action & scalable search debounce."""
        search = SmartLineEdit(placeholder)
        search.setMinimumHeight(34)
        search.setMinimumWidth(72)
        search.setMaximumWidth(210)
        search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        search.setToolTip("جست‌وجو در تمام ستون‌های جدول")
        search.setClearButtonEnabled(True)

        debounce_timer = QTimer(search)
        debounce_timer.setSingleShot(True)
        debounce_timer.setInterval(150)
        debounce_timer.timeout.connect(
            lambda target=table, field=search: self._filter_table_rows(target, field.text())
        )

        def _on_search_changed(query, target=table, timer=debounce_timer):
            if target.rowCount() > 500:
                timer.start()
            else:
                timer.stop()
                self._filter_table_rows(target, query)

        search.textChanged.connect(_on_search_changed)
        btn_print = self._create_table_print_button(table, key)
        if isinstance(parent_layout, QVBoxLayout):
            search_row = QHBoxLayout()
            search_row.setSpacing(6)
            search_row.addWidget(search, 1)
            search_row.addWidget(btn_print, 0)
            parent_layout.addLayout(search_row)
        else:
            parent_layout.addWidget(search, 1)
            parent_layout.addWidget(btn_print, 0)
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
        """Render specification values in logical order, supporting @parent titles."""
        definitions = self.catalog_config.get("attributes", {}).get(category or "", [])
        definitions_by_name = {
            str(item.get("name") or "").strip(): item
            for item in definitions
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }

        rendered = {}
        order = []
        deferred_children = []
        for raw_key, raw_value in (specs or {}).items():
            key = str(raw_key).strip()
            value = str(raw_value or "").strip()
            if not key or not value:
                continue
            definition = definitions_by_name.get(key, {})
            title = str(
                definition.get("display_name") or definition.get("label") or ""
            ).strip()
            if title.startswith("@"):
                reference = title[1:].strip()
                if reference:
                    deferred_children.append((reference, value))
                continue
            if key not in rendered:
                order.append(key)
                rendered[key] = value
            else:
                rendered[key] = f"{rendered[key]} {value}".strip()

        # Process child attributes after their parent values so the combined text
        # is stable even when JSON property order differs.
        for reference, child_value in deferred_children:
            if reference not in rendered:
                rendered[reference] = child_value
                order.append(reference)
            else:
                rendered[reference] = f"{rendered[reference]} {child_value}".strip()

        pieces = []
        for key in order:
            definition = definitions_by_name.get(key, {})
            title = str(definition.get("label") or key).strip()
            if key in ("Specs", "specs") or title in ("Specs", "specs"):
                title = "مشخصات"
            elif title.startswith("@") or not title:
                title = key
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
        unique_lines = []
        seen = set()
        for line in rendered.replace(" | ", "\n").splitlines():
            clean_line = line.strip()
            key = normalize_catalog_label(clean_line)
            if clean_line and key and key not in seen:
                seen.add(key)
                unique_lines.append(clean_line)
        return "\n".join(unique_lines)

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

    def _on_tab_bar_clicked(self, index: int):
        if 0 <= index < len(self._TAB_MODULES):
            module = self._TAB_MODULES[index]
            lic_feature = TAB_MODULE_TO_FEATURE.get(module, module)
            if not self._is_license_feature_enabled(lic_feature):
                self._show_license_locked_dialog(lic_feature)

    def _open_license_dialog(self):
        icon_path = resource_path("assets/daqiq_logo.svg")
        if not os.path.exists(icon_path):
            icon_path = resource_path("assets/daqiq_logo.png")
        service = getattr(self, "license_service", None) or LicenseService(app_version=APP_VERSION)
        dark = self.db.cfg.get("theme", "light") == "dark" if hasattr(self, "db") and self.db else False
        dlg = LicenseDialog(service, parent=self, icon_path=icon_path, is_dark_theme=dark, is_startup_gate=False)
        dlg.exec()
        if hasattr(self, "db") and self.db:
            new_theme = "dark" if dlg.is_dark_theme else "light"
            if self.db.cfg.get("theme", "light") != new_theme:
                self.db.cfg["theme"] = new_theme
                save_app_config(self.db.cfg)
                self._apply_styles()
                self._refresh_dashboard_card_styles()
                if hasattr(self, "btn_theme"):
                    self.btn_theme.setText("☀️ حالت روشن" if new_theme == "dark" else "🌙 حالت تیره")
        self._update_license_banner()
        self._apply_employee_permissions(select_first_unlocked=False)

    def _on_main_tab_changed(self, index):
        if 0 <= index < len(self._TAB_MODULES):
            module = self._TAB_MODULES[index]
            lic_feature = TAB_MODULE_TO_FEATURE.get(module, module)
            if not self._is_license_feature_enabled(lic_feature):
                self._select_first_unlocked_tab()
                self._show_license_locked_dialog(lic_feature)
                return
        if index == getattr(self, "_settings_tab_index", -1):
            if getattr(self, "_settings_snapshot", None) is None:
                self._settings_snapshot = SettingsSnapshot(self)
            self._load_general_settings_form()
            if hasattr(self, "_catalog_settings_state") and self._catalog_settings_state is not None:
                self._catalog_settings_state.restore_to_window(self)
        else:
            if hasattr(self, "_catalog_settings_state") and self._catalog_settings_state is not None:
                self._catalog_settings_state.capture_from_window(self)
        for cb in (
            getattr(self, "cb_batch_buyer", None),
            getattr(self, "cb_sale_seller", None),
            getattr(self, "cb_srv_seller", None),
            getattr(self, "cb_upg_tech", None),
        ):
            if cb is not None and cb.currentIndex() == -1:
                self._select_default_operator(cb)

    def _on_catalog_subtab_changed(self, index):
        if hasattr(self, "_catalog_settings_state") and self._catalog_settings_state is not None:
            if index == 0:
                self._catalog_settings_state.restore_to_window(self)
            else:
                self._catalog_settings_state.capture_from_window(self)

    def _rollback_settings(self):
        """Rollback all settings to initial snapshot (Memento pattern), collapse sections, and navigate to Dashboard."""
        self._staged_db_password_action = None
        self._staged_db_startup_prompt = None
        self._refresh_db_password_status()
        if hasattr(self, "_settings_snapshot") and self._settings_snapshot is not None:
            self._settings_snapshot.restore(self)
            self._settings_snapshot = None
        else:
            self._load_general_settings_form()
            self._catalog_settings_state = CatalogSettingsState()
        if hasattr(self, "_settings_tab_index"):
            settings_page = self.tabs.widget(self._settings_tab_index)
            if settings_page:
                for section in settings_page.findChildren(CollapsibleSection):
                    try:
                        section.collapse()
                    except Exception:
                        pass
        self.tabs.setCurrentIndex(0)

    def _populate_table_safely(self, table: QTableWidget, rows_data: list, highlight_col=None):
        """
        بند ۱۰ و ۱۱: پر کردن امن جداول با غیرفعال کردن موقت SortingEnabled و UpdatesEnabled
        (رفع کامل باگ خالی افتادن سطرهای جدول در داشبورد، کاربران و سایر تب‌ها)
        و افزودن Tooltip روی تک‌تک سلول‌ها برای خوانایی در صفحات کوچک.
        """
        table.setSortingEnabled(False)
        table.setUpdatesEnabled(False)
        try:
            table.clearContents()
            table.setRowCount(len(rows_data))
            col_count = max(table.columnCount(), len(rows_data[0]) if rows_data else 0)
            col_meta = []
            for c_idx in range(col_count):
                header_item = table.horizontalHeaderItem(c_idx)
                header_text = header_item.text() if header_item else ""
                col_meta.append((
                    ("تخفیف" in header_text or "تشدید" in header_text),
                    "بدهی" in header_text,
                    ("طلب" in header_text or "مطالبات" in header_text),
                    (
                        "مانده حساب" in header_text
                        or "مانده تسویه‌نشده" in header_text
                        or "مانده تسویه نشده" in header_text
                    ),
                ))

            red_brush = QColor("#dc2626")
            green_brush = QColor("#059669")
            for r_idx, row_values in enumerate(rows_data):
                row_kind = str(row_values[0] if row_values else "")
                is_payable_row = ("بدهی" in row_kind or "خرید محموله" in row_kind)
                is_receivable_row = ("طلب" in row_kind or "فروش کالا" in row_kind or "فاکتور خدمات" in row_kind)
                for c_idx, val in enumerate(row_values):
                    text_val = "" if val is None else str(val)
                    display_text = strip_bidi_controls(text_val)
                    is_sign_col, debt_column, receivable_column, mixed_balance_column = col_meta[c_idx]
                    signed_value = is_sign_col and text_val.startswith(("+", "-"))
                    if signed_value:
                        display_text = "\u200e" + display_text
                    item = _SmartSortTableItem(display_text)
                    item.setData(Qt.UserRole, _smart_table_sort_key(text_val))
                    item.setToolTip(display_text)
                    if signed_value:
                        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

                    financial_value = _financial_number(text_val)
                    row_is_payable = mixed_balance_column and is_payable_row
                    row_is_receivable = mixed_balance_column and is_receivable_row
                    if financial_value is not None and financial_value < 0:
                        item.setForeground(red_brush)
                    elif (debt_column or row_is_payable) and financial_value is not None and financial_value > 0:
                        item.setForeground(red_brush)
                    elif (receivable_column or row_is_receivable) and financial_value is not None and financial_value > 0:
                        item.setForeground(green_brush)
                    elif highlight_col is not None and c_idx == highlight_col:
                        if text_val in ("ناموجود", "کم‌موجود", "تسویه‌نشده"):
                            item.setForeground(red_brush)
                        elif text_val.startswith("+"):
                            item.setForeground(green_brush)
                    table.setItem(r_idx, c_idx, item)
            table.setSortingEnabled(False)
            search = self._table_search_fields.get(table)
            if search is not None:
                self._filter_table_rows(table, search.text())
        finally:
            table.setUpdatesEnabled(True)

    # =========================================================================
    # ۱. تب داشبورد
    # =========================================================================
    def _init_tab_dashboard(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        cards_layout = QGridLayout()
        self.lbl_dash_sales_today = self._make_stat_card(
            cards_layout, 0, 0, "فروش امروز (تومان)", "0", "primary"
        )
        self.lbl_dash_profit_today = self._make_stat_card(
            cards_layout, 0, 1, "سود فروش امروز (تومان)", "0", "success"
        )
        self.lbl_dash_count_today = self._make_stat_card(
            cards_layout, 0, 2, "تعداد فروش امروز", "0", "info"
        )
        self.lbl_dash_buy_today = self._make_stat_card(
            cards_layout, 0, 3, "خرید امروز (تومان)", "0", "warning"
        )
        self.lbl_dash_total_stock = self._make_stat_card(
            cards_layout, 1, 0, "کل موجودی انبار (عدد)", "0", "neutral"
        )
        self.lbl_dash_low_stock = self._make_stat_card(
            cards_layout, 1, 1, "کالاهای کم‌موجود", "0", "danger"
        )
        self.lbl_dash_unpaid_supplier = self._make_stat_card(
            cards_layout, 1, 2, "بدهی به تأمین‌کنندگان", "0", "rose"
        )
        self.lbl_dash_srv_profit = self._make_stat_card(
            cards_layout, 1, 3, "سود خدمات امروز", "0", "accent"
        )
        layout.addLayout(cards_layout)

        split = QHBoxLayout()
        gb_low = QGroupBox("⚠️ هشدار موجودی (کالاهای نیازمند خرید مجدد)")
        l_low = QVBoxLayout(gb_low)
        self.tbl_dash_low = self._create_table(
            ["کد کالا", "محموله", "مشخصات کالا", "مشخصات فنی", "موجودی فعلی", "حداقل موجودی", "وضعیت"]
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
        self._dashboard_permission_widgets = {
            "dashboard.metric.sales_today": self.lbl_dash_sales_today.parentWidget(),
            "dashboard.metric.profit_today": self.lbl_dash_profit_today.parentWidget(),
            "dashboard.metric.sales_count_today": self.lbl_dash_count_today.parentWidget(),
            "dashboard.metric.purchase_today": self.lbl_dash_buy_today.parentWidget(),
            "dashboard.metric.total_stock": self.lbl_dash_total_stock.parentWidget(),
            "dashboard.metric.low_stock_count": self.lbl_dash_low_stock.parentWidget(),
            "dashboard.metric.supplier_debt": self.lbl_dash_unpaid_supplier.parentWidget(),
            "dashboard.metric.service_profit_today": self.lbl_dash_srv_profit.parentWidget(),
        }
        self._add_table_search(
            l_emp, self.tbl_dash_emp, "dashboard_employees",
            "🔍 جست‌وجو در عملکرد کارکنان..."
        )
        l_emp.addWidget(self.tbl_dash_emp)
        self._dashboard_permission_widgets["dashboard.table.low_stock"] = gb_low
        self._dashboard_permission_widgets["dashboard.table.employee_performance"] = gb_emp

        split.addWidget(gb_low)
        split.addWidget(gb_emp)
        layout.addLayout(split)

        self._add_scrollable_tab(tab, "📊 داشبورد")

    def _make_stat_card(self, grid, r, c, title, val, color):
        box = QGroupBox()
        box.setToolTip(title)
        v = QVBoxLayout(box)
        t = QLabel(title)
        t.setToolTip(title)
        lbl_val = QLabel(val)
        v.addWidget(t)
        v.addWidget(lbl_val)
        grid.addWidget(box, r, c)
        role = LEGACY_COLOR_TO_ROLE.get(str(color).lower(), str(color))
        self._dashboard_card_styles.append((box, t, lbl_val, role))
        self._refresh_dashboard_card_styles()
        return lbl_val

    # =========================================================================
    # ۲. تب مدیریت کالاها (بند ۱، ۲، ۳)
    # =========================================================================
    def _init_tab_products(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.selected_product_id = None
        self._selected_product_row_version = None

        top_split = QHBoxLayout()
        gb_form = QGroupBox("تعریف و ویرایش کالا (بدون نیاز به نام محصول؛ شناسایی با دسته‌بندی، زیرمجموعه، برند و مدل)")
        f_layout = QFormLayout(gb_form)

        self.ed_prod_code = SmartLineEdit("P-1001")
        self.ed_prod_code.setToolTip("در صورت خالی بودن، کد بعدی به‌صورت خودکار تخصیص می‌یابد.")
        self.ed_prod_serial = SmartLineEdit("")
        self.ed_prod_serial.setPlaceholderText("اسکن بارکدخوان یا تایپ شماره سریال...")
        self.ed_prod_serial.setToolTip("شماره سریال یا بارکد کالا را وارد کنید یا با بارکدخوان اسکن نمایید.")
        self.cb_prod_cat = SearchableComboBox()
        self.cb_prod_cat.setEditable(0)
        product_categories = list(self.catalog_config.get("categories") or [])
        self.cb_prod_cat.addItems(list(dict.fromkeys(product_categories)))
        self.cb_prod_cat.setToolTip("دسته‌بندی اصلی را از فهرست انتخاب کنید.")

        self.ed_prod_brand = SmartLineEdit("", all_caps=True)
        self.ed_prod_brand.setPlaceholderText("مثلاً ASUS, Lenovo, HP, Logitech...")
        self.ed_prod_model = SmartLineEdit("", all_caps=True)
        self.ed_prod_model.setPlaceholderText("مدل کالا (مثلاً G102, VivoBook 15...)")
        self.sp_prod_reorder = QSpinBox()
        self.sp_prod_reorder.setRange(0, 1000)
        self.sp_prod_reorder.setValue(int(self.db.cfg.get("default_min_inventory", 1)))
        self.sp_prod_reorder.setToolTip("اگر موجودی کالا به این عدد یا کمتر برسد، در داشبورد هشدار داده می‌شود")

        self.sp_prod_profit = QSpinBox()
        self.sp_prod_profit.setRange(0, 500)
        self.sp_prod_profit.setValue(
            int(float(self.db.cfg.get("default_profit_pct", 20)))
        )
        self.sp_prod_profit.setToolTip("درصد سود پیش‌فرض برای محاسبه قیمت فروش پیشنهادی این کالا")
        self.ed_prod_desc = SmartLineEdit("")
        self.ed_prod_desc.setPlaceholderText("توضیحات تکمیلی کالا...")

        f_layout.addRow("کد کالا (شناسه):", self.ed_prod_code)
        f_layout.addRow("شماره سریال / بارکد:", self.ed_prod_serial)
        f_layout.addRow("دسته‌بندی اصلی:", self.cb_prod_cat)
        f_layout.addRow("برند کالا:", self.ed_prod_brand)
        f_layout.addRow("مدل کالا:", self.ed_prod_model)
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
        btn_edit = QPushButton("✏️ ویرایش کالای انتخابی")
        btn_edit.setObjectName("btnSuccess")
        btn_edit.clicked.connect(self._update_selected_product)
        btn_del = QPushButton("🗑️ حذف کالای انتخابی")
        btn_del.setObjectName("btnDanger")
        btn_del.clicked.connect(self._delete_selected_product)
        self.ed_prod_search = SmartLineEdit("🔍 جست‌وجوی کد کالا، دسته‌بندی، زیرگروه (مثلاً کیبورد)، برند یا مدل...")
        self._prod_search_timer = QTimer(self.ed_prod_search)
        self._prod_search_timer.setSingleShot(True)
        self._prod_search_timer.setInterval(150)
        self._prod_search_timer.timeout.connect(self._refresh_products_table)

        def _on_prod_search_changed(_text):
            if hasattr(self, "tbl_products") and self.tbl_products.rowCount() > 500:
                self._prod_search_timer.start()
            else:
                self._prod_search_timer.stop()
                self._refresh_products_table()

        self.ed_prod_search.textChanged.connect(_on_prod_search_changed)

        self.tbl_products = self._create_table(
            [
                "شناسه",
                "کد کالا",
                "شماره سریال",
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
        btn_row.addWidget(btn_clear)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_edit)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        btn_row.addWidget(self.ed_prod_search)
        btn_row.addWidget(self._create_table_print_button(self.tbl_products, "products"), 0)
        layout.addLayout(btn_row)

        self.tbl_products.itemSelectionChanged.connect(self._on_product_row_selected)
        layout.addWidget(self.tbl_products)

        self._add_scrollable_tab(tab, "📦 مدیریت کالاها")

    def _clear_product_form(self):
        self.selected_product_id = None
        self._selected_product_row_version = None
        self._set_generated_code_placeholder(self.ed_prod_code, "products", "code", "P-")
        self.ed_prod_serial.clear()
        self.cb_prod_cat.setCurrentIndex(0)
        self._configure_product_specs(self.cb_prod_cat.currentText())
        self.ed_prod_brand.clear()
        self.ed_prod_model.clear()
        self.sp_prod_reorder.setValue(int(self.db.cfg.get("default_min_inventory", 1)))
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
        serial_number = self.ed_prod_serial.text().strip()
        specs_dict = self.specs_widget.get_specs_dict()
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
                self.db.update_product(target_id, *args, serial_number=serial_number)
            else:
                self.db.add_product(*args, serial_number=serial_number)
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
        serial_txt = self.tbl_products.item(row, 2).text()
        self.ed_prod_serial.setText(serial_txt)
        cat_txt = self.tbl_products.item(row, 3).text()
        sub_txt = self.tbl_products.item(row, 4).text()
        if cat_txt and self.cb_prod_cat.findText(cat_txt) == -1:
            self.cb_prod_cat.addItem(cat_txt)
        self.cb_prod_cat.setCurrentText(cat_txt)
        self._configure_product_specs(cat_txt)
        self.specs_widget.set_sub_category(sub_txt)
        self.ed_prod_brand.setText(self.tbl_products.item(row, 5).text())
        self.ed_prod_model.setText(self.tbl_products.item(row, 6).text())
        self.sp_prod_reorder.setValue(int(self.tbl_products.item(row, 10).text()))
        self.sp_prod_profit.setValue(int(float(self.tbl_products.item(row, 11).text())))
        self.ed_prod_desc.setText(self.tbl_products.item(row, 13).text())

        with self.db.get_connection() as conn:
            r = conn.execute(
                "SELECT specs_json, serial_number, row_version FROM products WHERE id=?", (self.selected_product_id,)
            ).fetchone()
            if r:
                self._selected_product_row_version = int(r["row_version"]) if "row_version" in r.keys() else 1
                self.ed_prod_serial.setText(r["serial_number"] or "")
                if r["specs_json"]:
                    sp_data = json.loads(r["specs_json"])
                    sp_data.pop("رنگ", None)
                    self.specs_widget.set_specs_dict(sp_data)

    def _ask_concurrency_resolution(self, title: str, conflict: ConcurrencyConflictError, summary_lines: list = None) -> str:
        """Present a clear Persian modal choice when optimistic concurrency detects a concurrent edit."""
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setIcon(QMessageBox.Warning)
        msg.setLayoutDirection(Qt.RightToLeft)
        details = conflict.message_fa
        if summary_lines:
            details += "\n\n" + "\n".join(summary_lines)
        details += "\n\nآیا می‌خواهید اطلاعات جدید را بارگذاری کنید یا تغییرات فعلی خود را روی نسخه جدید اعمال کنید؟"
        msg.setText(details)
        btn_reload = msg.addButton("🔄 بارگذاری اطلاعات جدید", QMessageBox.AcceptRole)
        btn_overwrite = msg.addButton("✍️ اعمال تغییرات من روی نسخه جدید", QMessageBox.DestructiveRole)
        msg.addButton("انصراف", QMessageBox.RejectRole)
        _center_message_buttons(msg)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked is btn_reload:
            return "reload"
        if clicked is btn_overwrite:
            return "overwrite"
        return "cancel"

    def _update_selected_product(self):
        specs = self.specs_widget.get_specs_dict()
        if not self.selected_product_id:
            QMessageBox.warning(self, "انتخاب کالا", "ابتدا کالای موردنظر را از جدول انتخاب کنید.")
            return
        try:
            code = self.ed_prod_code.text().strip()
            serial_number = self.ed_prod_serial.text().strip()
            with self.db.get_connection() as conn:
                duplicate = conn.execute(
                    "SELECT id FROM products WHERE code=? AND id<>?",
                    (code, self.selected_product_id),
                ).fetchone()
            target_id = self.selected_product_id
            expected_rv = getattr(self, "_selected_product_row_version", None)
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
                expected_rv = None
            cat_val = self.cb_prod_cat.currentText().strip() or "سایر موارد"
            sub_val = self.specs_widget.get_sub_category()
            brand_val = self.ed_prod_brand.text().strip()
            model_val = self.ed_prod_model.text().strip()
            desc_val = self.ed_prod_desc.text().strip()
            reorder_val = self.sp_prod_reorder.value()
            profit_val = self.sp_prod_profit.value()
            try:
                self.db.update_product(
                    target_id, code, "", cat_val, sub_val, brand_val, model_val,
                    specs, desc_val, reorder_val, profit_val,
                    serial_number=serial_number,
                    expected_row_version=expected_rv,
                )
            except ConcurrencyConflictError as conflict:
                live = conflict.live_row
                choice = self._ask_concurrency_resolution(
                    "تعارض ویرایش هم‌زمان کالا",
                    conflict,
                    [f"کد زنده: {live.get('code', '')} | عنوان زنده: {live.get('name', '')}"],
                )
                if choice == "reload":
                    self.refresh_all_data()
                    return
                if choice == "overwrite":
                    self.db.update_product(
                        target_id, code, "", cat_val, sub_val, brand_val, model_val,
                        specs, desc_val, reorder_val, profit_val,
                        serial_number=serial_number,
                        expected_row_version=conflict.actual_version,
                    )
                else:
                    return
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
        self._selected_batch_row_version = None

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
        self.ed_batch_serial_number = SmartLineEdit("")
        self.ed_batch_serial_number.setPlaceholderText("اسکن بارکدخوان یا تایپ شماره سریال...")
        self.ed_batch_serial_number.setToolTip("ورود دستی شماره سریال یا اسکن خودکار با بارکدخوان (Keyboard Wedge)")
        self.ed_batch_serial_number.returnPressed.connect(self._on_batch_serial_scanned)
        self.cb_batch_supplier = SearchableComboBox()
        self.cb_batch_supplier.setEditable(False)
        self.cb_batch_buyer = SearchableComboBox()
        self.cb_batch_buyer.setEditable(False)
        self.ed_batch_inv = SmartLineEdit("")
        self.ed_batch_inv.setPlaceholderText("شماره فاکتور خرید...")
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
        self.btn_batch_colors = ColorSelectionButton()
        self.btn_batch_colors.setToolTip("رنگ یا رنگ‌های موجود در همین محموله را انتخاب کنید.")
        self._populate_color_checklist(
            self.btn_batch_colors,
            self.catalog_config.get("colors") or [],
            selected=[],
        )

        self.pr_batch_buy.valueChanged.connect(self._recalc_batch_suggested)
        self.pr_batch_extra.valueChanged.connect(self._recalc_batch_suggested)
        self.cb_batch_qty.qtyChanged.connect(self._recalc_batch_suggested)

        grid.addWidget(QLabel("کد محموله:"), 0, 0)
        grid.addWidget(self.ed_batch_code, 0, 1)
        grid.addWidget(QLabel("انتخاب کالا:"), 0, 2)
        grid.addWidget(self.cb_batch_prod, 0, 3)
        grid.addWidget(QLabel("شماره سریال / بارکد:"), 0, 4)
        grid.addWidget(self.ed_batch_serial_number, 0, 5)

        grid.addWidget(QLabel("تأمین‌کننده:"), 1, 0)
        grid.addWidget(self.cb_batch_supplier, 1, 1)
        grid.addWidget(QLabel("مسئول خرید:"), 1, 2)
        grid.addWidget(self.cb_batch_buyer, 1, 3)
        grid.addWidget(QLabel("شماره فاکتور:"), 1, 4)
        grid.addWidget(self.ed_batch_inv, 1, 5)

        grid.addWidget(QLabel("تعداد خرید:"), 2, 0)
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

        grid.addWidget(QLabel("تاریخ خرید:"), 4, 0)
        grid.addWidget(self.dt_batch_date, 4, 1)
        grid.addWidget(QLabel("رنگ‌های این محموله:"), 4, 2)
        grid.addWidget(self.btn_batch_colors, 4, 3, 1, 3)

        grid.addWidget(QLabel("مشخصات فنی / توضیحات:"), 5, 0)
        grid.addWidget(self.ed_batch_serial, 5, 1, 1, 5)

        layout.addWidget(gb)

        btn_row = QHBoxLayout()
        btn_clear = QPushButton("پاک کردن فرم")
        btn_clear.setObjectName("btnSecondary")
        btn_clear.clicked.connect(self._clear_batch_form)
        btn_add = QPushButton("➕ ثبت خرید (محموله جدید)")
        btn_add.clicked.connect(self._save_new_batch)
        btn_edit = QPushButton("✏️ ویرایش محموله انتخابی")
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
                "شماره سریال",
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
                "رنگ‌های محموله",
            ]
        )
        self.tbl_batches.itemSelectionChanged.connect(self._on_batch_row_selected)
        self._add_table_search(btn_row, self.tbl_batches, "batches", "🔍 جست‌وجو در خریدها و محموله‌ها...")
        layout.addWidget(self.tbl_batches)

        self._add_scrollable_tab(tab, "🚚 ثبت خرید و محموله‌ها")

    @staticmethod
    def _decode_colors(raw):
        if raw is None:
            return []
        try:
            values = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, (list, tuple, set)):
            return []
        return list(dict.fromkeys(
            str(value).strip() for value in values
            if value is not None and str(value).strip()
        ))

    def _checked_colors(self, widget):
        if hasattr(widget, "selected_colors"):
            return widget.selected_colors()
        return [
            widget.item(index).text()
            for index in range(widget.count())
            if widget.item(index).checkState() == Qt.Checked
        ]

    def _populate_color_checklist(self, widget, colors, selected=None):
        if widget is None:
            return
        if hasattr(widget, "set_colors"):
            widget.set_colors(colors, selected)
            return
        if selected is None:
            selected = self._checked_colors(widget)
        selected_keys = {normalize_catalog_label(value) for value in (selected or [])}
        values = list(dict.fromkeys(
            str(value).strip() for value in (colors or [])
            if value is not None and str(value).strip()
        ))
        known = {normalize_catalog_label(value) for value in values}
        selected_keys.intersection_update(known)
        widget.blockSignals(True)
        widget.clear()
        widget.setSelectionMode(QAbstractItemView.NoSelection)
        for color in values:
            item = QListWidgetItem(color)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if normalize_catalog_label(color) in selected_keys
                else Qt.Unchecked
            )
            widget.addItem(item)
        widget.blockSignals(False)

    def _on_batch_prod_changed(self):
        prod = self.cb_batch_prod.currentData()
        if prod:
            specs = json.loads(prod.get("specs_json") or "{}")
            specs_str = self._format_specs_for_display(specs, prod.get("category"))
            desc = (prod.get("description") or "").strip()
            combined = f"{specs_str} - {desc}".strip(" -") if desc else specs_str
            self.ed_batch_serial.setText(combined)
            prod_serial = prod.get("serial_number")
            if not prod_serial and prod.get("id"):
                try:
                    with self.db.get_connection() as conn:
                        p_row = conn.execute("SELECT serial_number FROM products WHERE id=?", (prod["id"],)).fetchone()
                        if p_row:
                            prod_serial = p_row["serial_number"]
                except Exception:
                    pass
            if prod_serial:
                self.ed_batch_serial_number.setText(str(prod_serial))
            else:
                self.ed_batch_serial_number.clear()
        self._recalc_batch_suggested()

    def _on_batch_serial_scanned(self):
        """Hardware barcode scanner (Keyboard Wedge) and manual Enter event handler for purchase batch entry."""
        if not self._require_license_feature("barcode_scanner"):
            return
        serial = self.ed_batch_serial_number.text().strip()
        if not serial:
            return
        result = self.db.lookup_by_serial_or_barcode(serial)
        product = result.get("product")
        if product:
            target_prod_id = int(product["id"])
            for index in range(self.cb_batch_prod.count()):
                data = self.cb_batch_prod.itemData(index)
                if data and int(data.get("id", -1)) == target_prod_id:
                    self.cb_batch_prod.setCurrentIndex(index)
                    # Automatically cascades and fills all dependent fields via _on_batch_prod_changed
                    break

    def _clear_batch_form(self):
        self.selected_batch_id = None
        self._selected_batch_row_version = None
        self._set_generated_code_placeholder(self.ed_batch_code, "batches", "batch_code", "C-")
        self.ed_batch_serial_number.clear()
        self.cb_batch_prod.setCurrentIndex(-1)
        self.cb_batch_prod.clearEditText()
        self.cb_batch_supplier.setCurrentIndex(-1)
        self.cb_batch_supplier.clearEditText()
        self.cb_batch_buyer.setCurrentIndex(-1)
        self.cb_batch_buyer.clearEditText()
        self._select_default_operator(self.cb_batch_buyer)
        self.ed_batch_inv.clear()
        self.ed_batch_serial.clear()
        self.dt_batch_date.set_date(self.get_today_date_str())
        self.cb_batch_qty.setCurrentText("1")
        self.pr_batch_buy.set_value(0)
        self.pr_batch_extra.set_value(0)
        self.pr_batch_suggest.set_value(0)
        self.pr_batch_paid.set_value(0)
        self.cb_batch_status.setCurrentIndex(0)
        self._populate_color_checklist(
            self.btn_batch_colors,
            self.catalog_config.get("colors") or [],
            selected=[],
        )
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
        cost_u = buy_u + (round_integer_division(extra_t, qty) if qty > 0 else 0)
        prod_data = self.cb_batch_prod.currentData()
        pct = (
            float(prod_data["default_profit_pct"])
            if prod_data
            else float(self.db.cfg.get("default_profit_pct", 20))
        )
        suggested = round_percentage_amount(cost_u, pct)
        self.pr_batch_suggest.set_value(suggested)
        st = self.cb_batch_status.currentText()
        if st.startswith("تسویه‌شده"):
            self.pr_batch_paid.set_value((buy_u * qty) + extra_t)
        elif st.startswith("تسویه‌نشده"):
            self.pr_batch_paid.set_value(0)

    def _save_new_batch(self):
        product = self.cb_batch_prod.currentData()
        if not product:
            QMessageBox.warning(self, "خطا", "لطفاً یک کالا انتخاب کنید.")
            return

        try:
            supplier_id = self.cb_batch_supplier.currentData()
            supplier_name = (
                "" if supplier_id is not None
                else self.cb_batch_supplier.currentText().strip()
            )
            specifications = self.ed_batch_serial.text().strip()
            batch_serial = self.ed_batch_serial_number.text().strip()
            batch_code = self.ed_batch_code.text().strip()
            batch_values = (
                supplier_id,
                self.cb_batch_buyer.currentData(),
                self.ed_batch_inv.text().strip(),
                self.dt_batch_date.get_date(),
                self.cb_batch_qty.get_qty(),
                self.pr_batch_buy.get_value(),
                self.pr_batch_extra.get_value(),
                self.pr_batch_suggest.get_value(),
                self.pr_batch_paid.get_value(),
                batch_serial,
                specifications,
                self.cb_batch_status.currentText(),
            )

            duplicate = None
            if batch_code:
                with self.db.get_connection() as conn:
                    duplicate = conn.execute(
                        "SELECT id FROM batches WHERE batch_code=?",
                        (batch_code,),
                    ).fetchone()

            if duplicate:
                message = QMessageBox(self)
                message.setWindowTitle("کد محموله تکراری")
                message.setText(
                    f"کد {batch_code} قبلاً ثبت شده است. "
                    "اطلاعات محموله قبلی جایگزین شود؟"
                )
                replace_button = message.addButton(
                    "جایگزین کردن", QMessageBox.AcceptRole
                )
                message.addButton("انصراف", QMessageBox.RejectRole)
                _center_message_buttons(message)
                message.exec()
                if message.clickedButton() != replace_button:
                    return

                self.db.update_batch(
                    int(duplicate["id"]),
                    *batch_values,
                    product_id=product["id"],
                    initial_specs=specifications,
                    batch_code=batch_code,
                    colors=self._checked_colors(self.btn_batch_colors),
                    supplier_name=supplier_name or None,
                )
            else:
                # add_batch has an additional initial_specs argument compared
                # with update_batch. Keep this explicit mapping rather than
                # forwarding the edit payload with a different function arity.
                purchase_date_only = self.dt_batch_date.get_date()
                purchase_dt = f"{purchase_date_only} {self.get_now_time_str()}".strip() if purchase_date_only else self.get_now_datetime_str()
                self.db.add_batch(
                    batch_code,
                    product["id"],
                    *batch_values[:3],
                    purchase_dt,
                    *batch_values[4:10],
                    specifications,
                    specifications,
                    batch_values[11],
                    colors=self._checked_colors(self.btn_batch_colors),
                    supplier_name=supplier_name or None,
                )

            self.refresh_all_data()
            self._clear_batch_form()
        except (ValueError, sqlite3.IntegrityError, sqlite3.OperationalError) as exc:
            QMessageBox.critical(self, "خطا در ثبت خرید", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "خطا در ثبت خرید", str(exc))

    def _on_batch_row_selected(self):
        items = self.tbl_batches.selectedItems()
        if not items:
            return
        r = items[0].row()
        self.selected_batch_id = int(self.tbl_batches.item(r, 0).text())
        self.ed_batch_code.setText(self.tbl_batches.item(r, 1).text())
        self.ed_batch_inv.setText(self.tbl_batches.item(r, 7).text())
        raw_purchase_dt = self.tbl_batches.item(r, 8).text().strip()
        self.dt_batch_date.set_date(raw_purchase_dt.split(" ", 1)[0] if raw_purchase_dt else "")
        self.cb_batch_qty.setCurrentText(self.tbl_batches.item(r, 9).text())
        self.pr_batch_buy.set_value(
            int(self.tbl_batches.item(r, 12).text().replace(",", ""))
        )
        self.pr_batch_extra.set_value(
            int(self.tbl_batches.item(r, 13).text().replace(",", ""))
        )
        self.pr_batch_suggest.set_value(
            int(self.tbl_batches.item(r, 16).text().replace(",", ""))
        )
        self.cb_batch_status.setCurrentText(self.tbl_batches.item(r, 18).text())
        self.pr_batch_paid.set_value(
            int(self.tbl_batches.item(r, 19).text().replace(",", ""))
        )
        batch_serial_text = self.tbl_batches.item(r, 21).text()
        with self.db.get_connection() as conn:
            batch_state = conn.execute(
                """SELECT b.colors_json, b.supplier_id, b.buyer_employee_id, b.serial_numbers,
                          b.product_id, b.row_version, p.code, p.name, p.category, p.sub_category,
                          p.brand, p.model, p.specs_json, p.description
                   FROM batches b JOIN products p ON p.id=b.product_id
                   WHERE b.id=?""",
                (self.selected_batch_id,),
            ).fetchone()
        if batch_state:
            self._selected_batch_row_version = (
                int(batch_state["row_version"]) if "row_version" in batch_state.keys() else 1
            )
            self.ed_batch_serial_number.setText(batch_state["serial_numbers"] or "")
            product_index = next(
                (
                    index for index in range(self.cb_batch_prod.count())
                    if isinstance(self.cb_batch_prod.itemData(index), dict)
                    and int(self.cb_batch_prod.itemData(index).get("id", 0))
                    == int(batch_state["product_id"])
                ),
                -1,
            )
            if product_index < 0:
                product_data = {
                    "id": int(batch_state["product_id"]), "code": batch_state["code"],
                    "name": batch_state["name"], "category": batch_state["category"],
                    "sub_category": batch_state["sub_category"], "brand": batch_state["brand"],
                    "model": batch_state["model"], "specs_json": batch_state["specs_json"],
                    "description": batch_state["description"],
                }
                product_index = self.cb_batch_prod.count()
                self.cb_batch_prod.addItem(
                    bidi_isolate_text(self._format_product_picker_label(product_data)),
                    product_data,
                )
            self.cb_batch_prod.blockSignals(True)
            self.cb_batch_prod.setCurrentIndex(product_index)
            self.cb_batch_prod.blockSignals(False)
            self.ed_batch_serial.setText(batch_serial_text)
            supplier_index = self.cb_batch_supplier.findData(batch_state["supplier_id"])
            buyer_index = self.cb_batch_buyer.findData(batch_state["buyer_employee_id"])
            self.cb_batch_supplier.setCurrentIndex(
                supplier_index if supplier_index >= 0 else -1
            )
            self.cb_batch_buyer.setCurrentIndex(
                buyer_index if buyer_index >= 0 else -1
            )
        self._populate_color_checklist(
            self.btn_batch_colors,
            self.catalog_config.get("colors") or [],
            self._decode_colors(batch_state["colors_json"]) if batch_state else [],
        )

    def _update_selected_batch(self):
        if not self.selected_batch_id:
            return
        try:
            supplier_id = self.cb_batch_supplier.currentData()
            supplier_name = (
                "" if supplier_id is not None
                else self.cb_batch_supplier.currentText().strip()
            )
            specifications = self.ed_batch_serial.text().strip()
            batch_serial = self.ed_batch_serial_number.text().strip()
            args = (
                self.selected_batch_id,
                supplier_id,
                self.cb_batch_buyer.currentData(),
                self.ed_batch_inv.text().strip(),
                self.dt_batch_date.get_date(),
                self.cb_batch_qty.get_qty(),
                self.pr_batch_buy.get_value(),
                self.pr_batch_extra.get_value(),
                self.pr_batch_suggest.get_value(),
                self.pr_batch_paid.get_value(),
                batch_serial,
                specifications,
                self.cb_batch_status.currentText(),
            )
            kwargs = {
                "colors": self._checked_colors(self.btn_batch_colors),
                "supplier_name": supplier_name or None,
                "expected_row_version": getattr(self, "_selected_batch_row_version", None),
            }
            try:
                self.db.update_batch(*args, **kwargs)
            except ConcurrencyConflictError as conflict:
                live = conflict.live_row
                choice = self._ask_concurrency_resolution(
                    "تعارض ویرایش هم‌زمان محموله",
                    conflict,
                    [f"کد محموله: {live.get('batch_code', '')} | موجودی باقیمانده فعلی: {live.get('remaining_qty', '')}"],
                )
                if choice == "reload":
                    self.refresh_all_data()
                    return
                if choice == "overwrite":
                    kwargs["expected_row_version"] = conflict.actual_version
                    self.db.update_batch(*args, **kwargs)
                else:
                    return
            self.refresh_all_data()
            QMessageBox.information(
                self, "ذخیره شد", "محموله خرید با موفقیت اصلاح شد."
            )
        except (ValueError, sqlite3.IntegrityError, sqlite3.OperationalError) as exc:
            QMessageBox.critical(self, "خطا", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "خطا", str(exc))

    def _delete_selected_batch(self):
        if not self._require_license_feature("batch_delete"):
            return
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
        self._selected_sale_row_version = None

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
        self.ed_sale_inv.setPlaceholderText("شماره فاکتور فروش (خودکار یا دستی)...")
        self.ed_sale_inv.setToolTip("در صورت خالی بودن، شماره فاکتور بعدی خودکار تخصیص می‌یابد.")
        self.cb_sale_prod = SearchableComboBox()
        self.cb_sale_prod.setToolTip(
            "می‌توانید نام زیرگروه (مثلاً کیبورد، ماوس، مانیتور)، برند، مدل یا کد کالا را تایپ کنید"
        )
        self.cb_sale_prod.currentIndexChanged.connect(self._on_sale_prod_changed)
        self.cb_sale_batch = SearchableComboBox()
        self.cb_sale_batch.setLayoutDirection(Qt.RightToLeft)
        self.cb_sale_batch.view().setLayoutDirection(Qt.RightToLeft)
        self.cb_sale_batch.currentIndexChanged.connect(self._on_sale_batch_changed)
        self.cb_sale_seller = SearchableComboBox()
        self.cb_sale_seller.setEditable(False)
        self.ed_sale_customer = SmartLineEdit("")
        self.ed_sale_customer.setPlaceholderText("نام و نام خانوادگی مشتری را وارد کنید...")
        self.ed_sale_phone = SmartLineEdit("")
        self.ed_sale_phone.setPlaceholderText("شماره تماس مشتری (مثلاً ۰۹۱۲۳۴۵۶۷۸۹)...")
        self.ed_sale_phone.setToolTip("شماره تماس یا تلفن همراه مشتری را وارد کنید.")
        self.btn_sale_colors = ColorSelectionButton()
        self.ed_sale_specs = SmartLineEdit("مشخصات دقیق کالای فروخته‌شده؛ قابل ویرایش...")
        self.ed_sale_specs.setLayoutDirection(Qt.LeftToRight)
        self.ed_sale_specs.setToolTip("این مشخصات در زمان فروش ثبت و در گزارش‌های آینده حفظ می‌شود.")
        self.cb_sale_qty = QuantitySelector(100)
        self.cb_sale_qty.setEditable(0)
        self.cb_sale_qty.qtyChanged.connect(self._recalc_sale_live)

        self.pr_sale_suggest = PriceInput(self.db)
        self.pr_sale_suggest.setReadOnly(True)
        self.pr_sale_suggest.setObjectName("suggestedSalePrice")
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
        self.lbl_sale_summary.setObjectName("saleSummary")

        self.ed_war_company = SmartLineEdit("شرکت گارانتی‌کننده")
        self.dt_war_start = JalaliDateEdit(default_today=False)
        self.cb_war_months = QComboBox()
        self.cb_war_months.setEditable(True)
        self.cb_war_months.setInsertPolicy(QComboBox.NoInsert)
        self.cb_war_months.setLocale(QLocale.c())
        war_line_edit = WarrantyLineEdit("", self.cb_war_months)
        war_line_edit.setLocale(QLocale.c())
        self.cb_war_months.setLineEdit(war_line_edit)
        def _normalize_war_input(txt):
            norm = normalize_digits(txt)
            if norm != txt:
                pos = war_line_edit.cursorPosition()
                war_line_edit.setText(norm)
                war_line_edit.setCursorPosition(pos)
        war_line_edit.textEdited.connect(_normalize_war_input)
        self.cb_war_months.setCurrentText("بدون گارانتی")
        self.cb_war_months.setToolTip(
            "مدت را از فهرست انتخاب کنید یا تعداد روز/ماه را دستی وارد کنید."
        )
        warranty_options = [
            ("بدون گارانتی", 0), ("2 روز", 2), ("1 هفته", 7), ("2 هفته", 14),
            ("1 ماه", 30), ("2 ماه", 60), ("3 ماه", 90), ("6 ماه", 180),
            ("1 سال", 365), ("18 ماه", 540), ("2 سال", 730), ("3 سال", 1095),
        ]
        for label, days in warranty_options:
            self.cb_war_months.addItem(label, days)
        self.dt_war_end = JalaliDateEdit(default_today=False)
        self.dt_sale_date = JalaliDateEdit(default_today=True)
        self._synced_sale_war_start = None
        self.ed_sale_serial = SmartLineEdit("")
        self.ed_sale_serial.setPlaceholderText("اسکن بارکدخوان یا تایپ شماره سریال...")
        self.ed_sale_serial.setToolTip("شماره سریال یا بارکد کالا را وارد کنید یا با بارکدخوان اسکن نمایید.")
        self.ed_sale_serial.returnPressed.connect(self._on_sale_serial_scanned)

        self.dt_war_start.dateChanged.connect(self._recalc_warranty_end)
        self.dt_sale_date.dateChanged.connect(self._on_sale_date_changed)
        self.cb_war_months.currentIndexChanged.connect(self._recalc_warranty_end)
        self.cb_war_months.currentTextChanged.connect(self._recalc_warranty_end)

        grid.addWidget(QLabel("شماره فاکتور:"), 0, 0)
        grid.addWidget(self.ed_sale_inv, 0, 1)
        grid.addWidget(QLabel("انتخاب کالا:"), 0, 2)
        grid.addWidget(self.cb_sale_prod, 0, 3)
        grid.addWidget(QLabel("شماره سریال / بارکد:"), 0, 4)
        grid.addWidget(self.ed_sale_serial, 0, 5)

        grid.addWidget(QLabel("محموله موجود:"), 1, 0)
        grid.addWidget(self.cb_sale_batch, 1, 1)
        grid.addWidget(QLabel("فروشنده:"), 1, 2)
        grid.addWidget(self.cb_sale_seller, 1, 3)
        grid.addWidget(QLabel("تعداد فروش:"), 1, 4)
        grid.addWidget(self.cb_sale_qty, 1, 5)

        grid.addWidget(QLabel("قیمت فروش واحد:"), 2, 0)
        grid.addWidget(self.pr_sale_actual, 2, 1)
        grid.addWidget(QLabel("قیمت پیشنهادی واحد:"), 2, 2)
        grid.addWidget(self.pr_sale_suggest, 2, 3)
        grid.addWidget(QLabel("مبلغ دریافتی:"), 2, 4)
        grid.addWidget(self.pr_sale_paid, 2, 5)

        grid.addWidget(QLabel("وضعیت تسویه:"), 3, 0)
        grid.addWidget(self.cb_sale_status, 3, 1)
        grid.addWidget(QLabel("نام مشتری:"), 3, 2)
        grid.addWidget(self.ed_sale_customer, 3, 3)
        grid.addWidget(QLabel("شماره تماس مشتری:"), 3, 4)
        grid.addWidget(self.ed_sale_phone, 3, 5)

        grid.addWidget(QLabel("شرکت گارانتی:"), 4, 0)
        grid.addWidget(self.ed_war_company, 4, 1)
        grid.addWidget(QLabel("شروع گارانتی:"), 4, 2)
        grid.addWidget(self.dt_war_start, 4, 3)
        grid.addWidget(QLabel("مدت گارانتی:"), 4, 4)
        grid.addWidget(self.cb_war_months, 4, 5)

        grid.addWidget(QLabel("انقضای گارانتی:"), 5, 0)
        grid.addWidget(self.dt_war_end, 5, 1)
        grid.addWidget(QLabel("تاریخ فروش:"), 5, 2)
        grid.addWidget(self.dt_sale_date, 5, 3)
        grid.addWidget(QLabel("رنگ‌های فروخته‌شده:"), 5, 4)
        grid.addWidget(self.btn_sale_colors, 5, 5)

        grid.addWidget(QLabel("مشخصات فنی فروخته‌شده:"), 6, 0)
        grid.addWidget(self.ed_sale_specs, 6, 1, 1, 5)
        grid.addWidget(self.lbl_sale_summary, 7, 0, 1, 6)

        layout.addWidget(gb)

        btn_row = QHBoxLayout()
        btn_clear = QPushButton("پاک کردن فرم")
        btn_clear.setObjectName("btnSecondary")
        btn_clear.clicked.connect(self._clear_sale_form)
        btn_add = QPushButton("✅ ثبت فروش")
        btn_add.clicked.connect(self._save_new_sale)
        btn_edit = QPushButton("✏️ ویرایش فروش انتخابی")
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

        self.tbl_sales = self._create_table(
            [
                "شناسه",
                "شماره فاکتور",
                "کد کالا",
                "شماره سریال",
                "مشخصات کالا",
                "تاریخ و ساعت فروش",
                "کد محموله",
                "فروشنده",
                "نام مشتری",
                "شماره تماس مشتری",
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
                "مشخصات فنی فروخته‌شده",
                "رنگ‌های فروخته‌شده",
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
        """Compare variant specs only among batches belonging to the same product."""
        groups = {}
        for batch in batches:
            groups.setdefault(int(batch.get("product_id") or 0), []).append(batch)

        labels = {}
        for product_batches in groups.values():
            parsed_rows = []
            token_rows = []
            for batch in product_batches:
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

            for index, batch in enumerate(product_batches):
                pieces = []
                current = parsed_rows[index]
                for key in varying_keys:
                    pieces.append(f"{key}: {current.get(key) or 'ثبت نشده'}")
                if not varying_keys:
                    shared_tokens = (
                        set.intersection(*(set(tokens) for tokens in token_rows))
                        if token_rows and all(token_rows) else set()
                    )
                    pieces.extend(
                        token for token in token_rows[index] if token not in shared_tokens
                    )
                labels[int(batch["id"])] = (
                    "، ".join(dict.fromkeys(pieces)) if pieces else "بدون تفاوت ثبت‌شده"
                )
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

    def _on_sale_prod_changed(self, *_args, include_batch_id=None):
        """Load stocked batches for a product, optionally retaining an existing sold batch."""
        product = self.cb_sale_prod.currentData()
        self.cb_sale_batch.blockSignals(True)
        self.cb_sale_batch.clear()
        self.cb_sale_batch.blockSignals(False)
        if not isinstance(product, dict):
            self._on_sale_batch_changed()
            return

        all_products = bool(product.get("_all_products"))
        prod_serial = product.get("serial_number")
        if not prod_serial and product.get("id") and not all_products:
            try:
                with self.db.get_connection() as conn:
                    p_row = conn.execute("SELECT serial_number FROM products WHERE id=?", (product["id"],)).fetchone()
                    if p_row:
                        prod_serial = p_row["serial_number"]
            except Exception:
                pass
        if prod_serial:
            self.ed_sale_serial.setText(str(prod_serial))
        else:
            self.ed_sale_serial.clear()
        query = """
            SELECT b.id, b.batch_code, b.product_id, b.supplier_id, b.buyer_employee_id,
                       b.invoice_number, b.purchase_date, b.initial_qty, b.sold_qty, b.returned_qty,
                       b.remaining_qty, b.unit_purchase_price, b.extra_cost_total, b.upgrade_cost_unit,
                       b.unit_cost_price, b.suggested_sell_price, b.profit_pct, b.paid_amount,
                       b.settlement_status, b.serial_numbers, b.colors_json, b.initial_specs,
                       b.final_specs, b.supplier_name_snapshot, b.notes, b.created_at, b.updated_at,
                       b.row_version,
                       p.code AS p_code, p.category, p.sub_category, p.brand, p.model,
                   p.specs_json AS product_specs_json, p.description AS product_description
            FROM batches b
            JOIN products p ON p.id=b.product_id
            WHERE (b.remaining_qty > 0 OR b.id=?)
        """
        params = [int(include_batch_id) if include_batch_id is not None else None]
        if not all_products:
            query += " AND b.product_id=?"
            params.append(int(product["id"]))
        query += " ORDER BY b.updated_at DESC, b.id DESC"
        with self.db.get_connection() as conn:
            batch_rows = self._execute_scoped_query(
                conn, query, "b.buyer_employee_id", parameters=tuple(params)
            ).fetchall()

        batches = [dict(row) for row in batch_rows]
        searchable_batch_fields = (
            "batch_code", "initial_specs", "final_specs", "serial_numbers",
            "notes", "supplier_name_snapshot", "invoice_number", "purchase_date",
            "p_code", "category", "sub_category", "brand", "model",
        )
        for batch in batches:
            product_title = self._format_product_picker_label(batch)
            color_text = "، ".join(
                self._decode_colors(batch.get("colors_json"))
            ) or "-"
            label = (
                f"{batch['batch_code']} | رنگ: {color_text} | "
                f"قیمت پیشنهادی: {int(batch['suggested_sell_price']):,} تومان"
            )
            try:
                product_specs = json.loads(batch.get("product_specs_json") or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                product_specs = {}
            if not isinstance(product_specs, dict):
                product_specs = {}
            search_text = " ".join(
                str(batch.get(key) or "") for key in searchable_batch_fields
            )
            search_text = (
                f"{search_text} {batch.get('product_description') or ''} "
                f"{' '.join(str(value) for value in product_specs.values())}"
            ).strip()
            raw_batch_specs = (
                batch.get("final_specs") or batch.get("initial_specs") or ""
            ).strip()
            parsed_batch_specs, plain_batch_specs = self._parse_batch_specifications(
                raw_batch_specs
            )
            complete_specs = dict(product_specs)
            if parsed_batch_specs:
                complete_specs.update(parsed_batch_specs)
            formatted_specs = self._format_specs_for_tooltip(
                complete_specs, batch.get("category") or ""
            )
            if plain_batch_specs:
                existing_spec_lines = {
                    normalize_catalog_label(line)
                    for line in formatted_specs.splitlines() if line.strip()
                }
                unique_plain_specs = []
                for token in plain_batch_specs:
                    token_key = normalize_catalog_label(token)
                    if token_key and token_key not in existing_spec_lines:
                        existing_spec_lines.add(token_key)
                        unique_plain_specs.append(token)
                if unique_plain_specs:
                    formatted_specs = "\n".join(
                        part for part in (
                            formatted_specs, "، ".join(unique_plain_specs)
                        ) if part
                    )
            full_tooltip = (
                f"کد محموله: {batch['batch_code']}\n"
                f"کالا: {product_title}\n"
                f"موجودی: {batch['remaining_qty']}\n"
                f"قیمت پیشنهادی: {int(batch['suggested_sell_price']):,} تومان\n"
                f"رنگ‌ها: {color_text}\n"
                f"مشخصات فنی کامل:\n{formatted_specs or 'ثبت نشده'}"
            )
            index = self.cb_sale_batch.count()
            self.cb_sale_batch.addItem(bidi_isolate_text(label), batch)
            self.cb_sale_batch.setItemSearchText(index, search_text)
            self.cb_sale_batch.setItemData(
                index, bidi_isolate_text(full_tooltip), Qt.ToolTipRole
            )
        if self.cb_sale_batch.count():
            self.cb_sale_batch.setCurrentIndex(0)
        else:
            self._on_sale_batch_changed()

    def _on_sale_batch_changed(self):
        b = self.cb_sale_batch.currentData()
        tip = self.cb_sale_batch.currentData(Qt.ToolTipRole) if self.cb_sale_batch.currentIndex() >= 0 else ""
        self.cb_sale_batch.setToolTip(tip or "محموله دارای موجودی را انتخاب کنید.")
        if not b:
            self.cb_sale_qty.set_max_qty(1)
            self.pr_sale_suggest.set_value(0)
            self.pr_sale_actual.set_value(0)
            self.pr_sale_paid.set_value(0)
            self.ed_sale_specs.clear()
            self._populate_color_checklist(self.btn_sale_colors, [])
            self._recalc_sale_live()
            return
        self.cb_sale_qty.set_max_qty(b["remaining_qty"])
        self.ed_sale_specs.setText(
            str(b.get("final_specs") or b.get("initial_specs") or "")
        )
        self._populate_color_checklist(
            self.btn_sale_colors,
            self._decode_colors(b.get("colors_json")),
        )
        sug = int(b["suggested_sell_price"])
        self.pr_sale_suggest.set_value(sug)
        self.pr_sale_actual.set_value(sug)
        self._recalc_sale_live()

    def _on_sale_serial_scanned(self):
        """Hardware barcode scanner (Keyboard Wedge) and manual Enter event handler for sales."""
        if not self._require_license_feature("barcode_scanner"):
            return
        serial = self.ed_sale_serial.text().strip()
        if not serial:
            return
        result = self.db.lookup_by_serial_or_barcode(serial)
        product = result.get("product")
        matched_batch = result.get("matched_batch")

        if not product and matched_batch:
            with self.db.get_connection() as conn:
                p_row = conn.execute("SELECT * FROM products WHERE id=?", (matched_batch["product_id"],)).fetchone()
                if p_row:
                    product = dict(p_row)

        if product:
            target_prod_id = int(product["id"])
            found_index = -1
            for index in range(self.cb_sale_prod.count()):
                data = self.cb_sale_prod.itemData(index)
                if data and int(data.get("id", -1)) == target_prod_id:
                    found_index = index
                    break

            if found_index >= 0:
                self.cb_sale_prod.setCurrentIndex(found_index)

            # Crucial Automation: IF query results in only one unique cargo linked to that
            # specific serial/item (or matched a specific batch directly), select it in
            # "محموله موجود" and instantly auto-fill all dependent cascading fields!
            if matched_batch is not None:
                target_batch_id = int(matched_batch["id"])
                for b_idx in range(self.cb_sale_batch.count()):
                    b_data = self.cb_sale_batch.itemData(b_idx)
                    if b_data and int(b_data.get("id", -1)) == target_batch_id:
                        self.cb_sale_batch.setCurrentIndex(b_idx)
                        self._on_sale_batch_changed()
                        break
            elif self.cb_sale_batch.count() == 1:
                self.cb_sale_batch.setCurrentIndex(0)
                self._on_sale_batch_changed()

    def _clear_sale_form(self):
        self.selected_sale_id = None
        self._selected_sale_row_version = None
        self._set_generated_code_placeholder(self.ed_sale_inv, "sales", "invoice_number", "INV-")
        self.cb_sale_prod.blockSignals(True)
        self.cb_sale_prod.setCurrentIndex(0 if self.cb_sale_prod.count() else -1)
        self.cb_sale_prod.blockSignals(False)
        self._on_sale_prod_changed()
        self.cb_sale_seller.setCurrentIndex(-1)
        self.cb_sale_seller.clearEditText()
        self._select_default_operator(self.cb_sale_seller)
        self.ed_sale_customer.clear()
        self.ed_sale_phone.clear()
        self.ed_sale_specs.clear()
        self.pr_sale_actual.set_value(0)
        self.pr_sale_paid.set_value(0)
        self.cb_sale_status.setCurrentIndex(0)
        self.ed_war_company.clear()
        self.cb_war_months.setCurrentIndex(0)
        self._synced_sale_war_start = None
        self.dt_war_start.set_date("")
        self.dt_war_end.set_date("")
        if hasattr(self, "dt_sale_date"):
            self.dt_sale_date.set_date(self.get_today_date_str())
        self.ed_sale_serial.clear()
        self.tbl_sales.clearSelection()
        self.cb_sale_qty.setCurrentText("1")
        self._on_sale_batch_changed()
        self._populate_color_checklist(self.btn_sale_colors, [], selected=[])
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
        signed_diff_display = "\u200e" + signed_diff if signed_diff.startswith(("+", "-")) else signed_diff

        self.lbl_sale_summary.setText(
            f"تخفیف (-) / تشدید (+): {signed_diff_display} تومان   |   مبلغ کل فاکتور: {total_bill:,} تومان   |   سود فروش: {profit_total:,} تومان"
        )
        discount_color = "#dc2626" if act_u < sug_u else "#16a34a"
        self.lbl_sale_summary.setStyleSheet(
            f"color: {discount_color}; font-weight: bold;"
        )

    def _get_warranty_days(self):
        """Return warranty duration in days for preset or manually typed values (REQ-1)."""
        curr_text = normalize_digits(self.cb_war_months.currentText()).strip()
        if not curr_text or curr_text == "0" or curr_text == "بدون گارانتی":
            return 0
        # If matches an exact preset item, return its associated data
        idx = self.cb_war_months.findText(curr_text)
        if idx >= 0:
            data = self.cb_war_months.itemData(idx)
            if data is not None:
                return max(0, int(data))
        # Otherwise parse custom entry
        match = re.search(r"\d+", curr_text)
        if not match:
            return 0
        amount = max(0, int(match.group(0)))
        if "سال" in curr_text or "y" in curr_text.lower():
            return amount * 365
        if "ماه" in curr_text or "m" in curr_text.lower():
            return amount * 30
        if "هفته" in curr_text or "w" in curr_text.lower():
            return amount * 7
        if "روز" in curr_text or "d" in curr_text.lower():
            return amount
        # Bare number without unit (e.g., 6, 12, 18, 24, 0)
        if amount <= 36:
            return amount * 30  # Months context in retail warranty
        return amount

    def _on_sale_date_changed(self, new_date: str):
        days = self._get_warranty_days()
        if not new_date:
            self._recalc_warranty_end()
            return
        cur_start = self.dt_war_start.get_date()
        synced = getattr(self, "_synced_sale_war_start", None)
        if (days > 0 and not cur_start) or (synced and cur_start == synced):
            self.dt_war_start.blockSignals(True)
            self.dt_war_start.set_date(new_date)
            self.dt_war_start.blockSignals(False)
            self._synced_sale_war_start = new_date
        self._recalc_warranty_end()

    def _recalc_warranty_end(self, *_):
        days = self._get_warranty_days()
        if not days:
            self.dt_war_end.set_date("")
            return
        base_date = self.dt_war_start.get_date()
        if not base_date and hasattr(self, "dt_sale_date"):
            sale_d = self.dt_sale_date.get_date()
            if sale_d:
                self.dt_war_start.blockSignals(True)
                self.dt_war_start.set_date(sale_d)
                self.dt_war_start.blockSignals(False)
                self._synced_sale_war_start = sale_d
                base_date = sale_d
        self.dt_war_end.set_date(
            add_jalali_days(base_date, days, cal_type=self.get_active_calendar())
            if base_date
            else ""
        )

    def _save_new_sale(self):
        prod = self.cb_sale_prod.currentData()
        batch = self.cb_sale_batch.currentData()
        if not prod or not batch:
            QMessageBox.warning(
                self, "خطا", "محموله دارای موجودی را انتخاب کنید."
            )
            return
        product_id = int(batch["product_id"]) if prod.get("_all_products") else int(prod["id"])
        if product_id != int(batch["product_id"]):
            QMessageBox.warning(
                self, "عدم تطابق کالا",
                "محموله انتخاب‌شده متعلق به کالای دیگری است. لطفاً دوباره انتخاب کنید."
            )
            return
        qty_to_sell = self.cb_sale_qty.get_qty()
        sale_colors = self._checked_colors(self.btn_sale_colors)
        if len(sale_colors) > qty_to_sell:
            QMessageBox.warning(
                self, "تعداد رنگ‌ها",
                "تعداد رنگ‌های انتخاب‌شده نمی‌تواند از تعداد فروش بیشتر باشد."
            )
            return
        sale_d = self.dt_sale_date.get_date() if hasattr(self, "dt_sale_date") else ""
        now_dt = f"{sale_d} {self.get_now_time_str()}".strip() if sale_d else self.get_now_datetime_str()
        try:
            war_days = self._get_warranty_days()
            sale_kwargs = {
                "warranty_days": war_days,
                "specifications": self.ed_sale_specs.text().strip(),
                "colors": sale_colors,
                "customer_phone": self.ed_sale_phone.text().strip(),
                "expected_batch_row_version": batch.get("row_version"),
            }
            sale_args = (
                self.ed_sale_inv.text().strip(),
                product_id,
                batch["id"],
                self.cb_sale_seller.currentData(),
                self.ed_sale_customer.text().strip(),
                qty_to_sell,
                self.pr_sale_suggest.get_value(),
                self.pr_sale_actual.get_value(),
                self.pr_sale_paid.get_value(),
                now_dt,
                self.ed_war_company.text().strip(),
                self.dt_war_start.get_date(),
                war_days // 30,
                self.dt_war_end.get_date(),
                self.ed_sale_serial.text().strip(),
                "",
                self.cb_sale_status.currentText(),
            )
            try:
                self.db.add_sale(*sale_args, **sale_kwargs)
            except InsufficientStockError as stock_err:
                self.refresh_all_data()
                QMessageBox.warning(self, "کمبود موجودی", stock_err.message_fa)
                return
            except ConcurrencyConflictError as conflict:
                live = conflict.live_row
                live_rem = int(live.get("remaining_qty", 0))
                proceed = _ask_yes_no(
                    self,
                    "هشدار فروش هم‌زمان",
                    f"{conflict.message_fa}\n\nموجودی فعلی: {live_rem} عدد\n"
                    "آیا می‌خواهید با در نظر گرفتن موجودی جدید، فاکتور فروش را ثبت کنید؟",
                )
                if not proceed:
                    self.refresh_all_data()
                    return
                sale_kwargs["expected_batch_row_version"] = conflict.actual_version
                self.db.add_sale(*sale_args, **sale_kwargs)
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

        with self.db.get_connection() as conn:
            sale = conn.execute(
                """SELECT s.*, b.colors_json AS batch_colors, b.final_specs,
                          b.initial_specs, p.code AS product_code, p.name AS product_name,
                          p.category, p.sub_category, p.brand, p.model, p.specs_json,
                          p.description AS product_description, e.name AS seller_name
                   FROM sales s
                   JOIN batches b ON b.id=s.batch_id
                   JOIN products p ON p.id=s.product_id
                   LEFT JOIN employees e ON e.id=s.seller_employee_id
                   WHERE s.id=?""",
                (self.selected_sale_id,),
            ).fetchone()
        if not sale:
            return
        self._selected_sale_row_version = int(sale["row_version"]) if "row_version" in sale.keys() else 1

        # Restore selectors in dependency order: product -> batches -> batch -> seller.
        # The requested batch is included even when it has since sold out.
        product_index = next(
            (
                index for index in range(self.cb_sale_prod.count())
                if isinstance(self.cb_sale_prod.itemData(index), dict)
                and int(self.cb_sale_prod.itemData(index).get("id", 0))
                == int(sale["product_id"])
            ),
            -1,
        )
        if product_index < 0:
            product_data = {
                "id": int(sale["product_id"]), "code": sale["product_code"],
                "name": sale["product_name"], "category": sale["category"],
                "sub_category": sale["sub_category"], "brand": sale["brand"],
                "model": sale["model"], "specs_json": sale["specs_json"],
                "description": sale["product_description"],
            }
            product_index = self.cb_sale_prod.count()
            self.cb_sale_prod.addItem(
                bidi_isolate_text(self._format_product_picker_label(product_data)),
                product_data,
            )
        self.cb_sale_prod.blockSignals(True)
        self.cb_sale_prod.setCurrentIndex(product_index)
        self.cb_sale_prod.blockSignals(False)
        self._on_sale_prod_changed(include_batch_id=int(sale["batch_id"]))

        batch_index = next(
            (
                index for index in range(self.cb_sale_batch.count())
                if isinstance(self.cb_sale_batch.itemData(index), dict)
                and int(self.cb_sale_batch.itemData(index).get("id", 0))
                == int(sale["batch_id"])
            ),
            -1,
        )
        if batch_index >= 0:
            self.cb_sale_batch.setCurrentIndex(batch_index)

        seller_id = sale["seller_employee_id"]
        seller_index = self.cb_sale_seller.findData(seller_id)
        if seller_id is not None and seller_index < 0:
            seller_index = self.cb_sale_seller.count()
            self.cb_sale_seller.addItem(str(sale["seller_name"] or ""), seller_id)
        self.cb_sale_seller.setCurrentIndex(seller_index if seller_index >= 0 else -1)

        self.ed_sale_inv.setText(sale["invoice_number"] or "")
        self.ed_sale_customer.setText(sale["customer_name"] or "")
        self.ed_sale_phone.setText(sale["customer_phone"] or "")
        self.cb_sale_qty.setCurrentText(str(sale["qty"]))
        self.pr_sale_suggest.set_value(int(sale["suggested_unit_price"] or 0))
        self.pr_sale_actual.set_value(int(sale["actual_unit_price"] or 0))
        self.pr_sale_paid.set_value(int(sale["paid_amount"] or 0))
        self.cb_sale_status.setCurrentText(sale["settlement_status"] or "تسویه‌شده")
        self.ed_sale_serial.setText(sale["serial_number"] or "")
        self.ed_sale_specs.setText(
            sale["specifications"] or sale["final_specs"] or sale["initial_specs"] or ""
        )

        batch_colors = self._decode_colors(sale["batch_colors"])
        sold_colors = self._decode_colors(sale["colors_json"])
        self._populate_color_checklist(
            self.btn_sale_colors, list(dict.fromkeys(batch_colors + sold_colors)),
            selected=sold_colors,
        )

        self.ed_war_company.setText(sale["warranty_company"] or "")
        if hasattr(self, "dt_sale_date"):
            raw_sale_dt = str(sale["sale_datetime"] or "").strip()
            sale_date_part = raw_sale_dt.split(" ", 1)[0] if raw_sale_dt else ""
            self.dt_sale_date.blockSignals(True)
            self.dt_sale_date.set_date(sale_date_part)
            self.dt_sale_date.blockSignals(False)
            self._synced_sale_war_start = sale_date_part or None
        self.dt_war_start.set_date(sale["warranty_start"] or "")
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
        # Duration changes recalculate this field; restore the stored value last.
        self.dt_war_end.set_date(sale["warranty_end"] or "")


    def _update_selected_sale(self):
        if not self.selected_sale_id:
            return
        selected_colors = self._checked_colors(self.btn_sale_colors)
        if len(selected_colors) > self.cb_sale_qty.get_qty():
            QMessageBox.warning(
                self, "تعداد رنگ‌ها",
                "تعداد رنگ‌های انتخاب‌شده نمی‌تواند از تعداد فروش بیشتر باشد."
            )
            return
        try:
            war_days = self._get_warranty_days()
            args = (
                self.selected_sale_id,
                self.cb_sale_seller.currentData(),
                self.ed_sale_customer.text().strip(),
                self.cb_sale_qty.get_qty(),
                self.pr_sale_suggest.get_value(),
                self.pr_sale_actual.get_value(),
                self.pr_sale_paid.get_value(),
                self.ed_war_company.text().strip(),
                self.dt_war_start.get_date(),
                war_days // 30,
                self.dt_war_end.get_date(),
                self.ed_sale_serial.text().strip(),
                "",
                self.cb_sale_status.currentText(),
            )
            kwargs = {
                "warranty_days": war_days,
                "specifications": self.ed_sale_specs.text().strip(),
                "colors": selected_colors,
                "customer_phone": self.ed_sale_phone.text().strip(),
                "sale_datetime": (self.dt_sale_date.get_date() if hasattr(self, "dt_sale_date") else None),
                "expected_row_version": getattr(self, "_selected_sale_row_version", None),
            }
            try:
                self.db.update_sale(*args, **kwargs)
            except ConcurrencyConflictError as conflict:
                live = conflict.live_row
                choice = self._ask_concurrency_resolution(
                    "تعارض ویرایش هم‌زمان فاکتور فروش",
                    conflict,
                    [f"شماره فاکتور: {live.get('invoice_number', '')} | تعداد فعلی: {live.get('qty', '')}"],
                )
                if choice == "reload":
                    self.refresh_all_data()
                    return
                if choice == "overwrite":
                    kwargs["expected_row_version"] = conflict.actual_version
                    self.db.update_sale(*args, **kwargs)
                else:
                    return
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
            self.catalog_config.get("service_types") or []
        )
        self.ed_srv_code = SmartLineEdit("")
        self.ed_srv_code.setPlaceholderText("کد خدمت (مثلاً S-1001)...")
        self.ed_srv_code.setToolTip("در صورت خالی بودن، کد خدمت بعدی خودکار تخصیص می‌یابد.")
        self.ed_srv_name = SmartLineEdit("")
        self.ed_srv_name.setPlaceholderText("عنوان خدمت (مثلاً نصب ویندوز، نصب آنتی‌ویروس...)")
        self.pr_srv_def_fee = PriceInput(self.db)
        self.pr_srv_def_side = PriceInput(self.db)

        f_cat.addRow("نوع خدمت:", self.cb_srv_type)
        f_cat.addRow("کد خدمت:", self.ed_srv_code)
        f_cat.addRow("عنوان خدمت:", self.ed_srv_name)
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
        self.cb_srv_seller.setEditable(False)
        self.ed_srv_cust = SmartLineEdit("")
        self.ed_srv_cust.setPlaceholderText("نام و نام خانوادگی مشتری را وارد کنید...")
        self.pr_srv_fee = PriceInput(self.db)
        self.pr_srv_fee.setReadOnly(True)
        self.pr_srv_fee.setToolTip("این مبلغ از فهرست خدمات خوانده می‌شود. برای اعمال تخفیف یا تشدید، «مبلغ دریافتی» را تغییر دهید.")
        self.pr_srv_side = PriceInput(self.db)
        self.cb_srv_status = QComboBox()
        self.cb_srv_status.addItems(["تسویه‌شده", "تسویه‌نشده", "تسویه جزئی"])
        self.cb_srv_status.currentTextChanged.connect(self._on_srv_status_changed)
        self.pr_srv_paid = PriceInput(self.db)
        self.ed_srv_desc = SmartLineEdit("توضیحات خدمات انجام شده...")
        
        # نمایش زنده تخفیف/تشدید و سود خالص خدمت
        self.lbl_srv_diff_summary = QLabel("تخفیف (-) / تشدید (+): 0 تومان | سود خالص: 0 تومان")
        self.lbl_srv_diff_summary.setObjectName("saleSummary")

        self.pr_srv_paid.valueChanged.connect(self._recalc_srv_live_summary)
        self.pr_srv_side.valueChanged.connect(self._recalc_srv_live_summary)

        btn_rec_row = QHBoxLayout()
        btn_clr_srv = QPushButton("پاک کردن فرم")
        btn_clr_srv.setObjectName("btnSecondary")
        btn_clr_srv.clicked.connect(self._clear_service_rec_form)
        btn_add_srv = QPushButton("✅ ثبت فاکتور خدمات")
        btn_add_srv.clicked.connect(self._save_new_service_record)
        btn_edit_srv = QPushButton("✏️ ویرایش فاکتور خدمت")
        btn_edit_srv.setObjectName("btnSuccess")
        btn_edit_srv.clicked.connect(self._update_selected_service_record)
        btn_del_srv = QPushButton("🗑️ حذف فاکتور خدمت")
        btn_del_srv.setObjectName("btnDanger")
        btn_del_srv.clicked.connect(self._delete_selected_service_record)
        btn_rec_row.addWidget(btn_clr_srv)
        btn_rec_row.addWidget(btn_add_srv)
        btn_rec_row.addWidget(btn_edit_srv)
        btn_rec_row.addWidget(btn_del_srv)

        f_rec.addRow("انتخاب خدمت:", self.cb_srv_select)
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
        self.cb_srv_select.clearEditText()
        self.cb_srv_seller.setCurrentIndex(-1)
        self.cb_srv_seller.clearEditText()
        self._select_default_operator(self.cb_srv_seller)
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
        status = self.cb_srv_status.currentText()
        adjustment, receivable = service_financial_breakdown(
            base_fee, paid_val, status
        )
        diff_str = f"{adjustment:+,}" if adjustment else "0"
        diff_display = "\u200e" + diff_str if diff_str.startswith(("+", "-")) else diff_str
        net = paid_val - side
        self.lbl_srv_diff_summary.setText(
            f"تخفیف (-) / تشدید (+): {diff_display} تومان   |   "
            f"طلب/بدهی: {receivable:,} تومان   |   سود خالص خدمت: {net:,} تومان"
        )
        color = "#dc2626" if paid_val < base_fee else "#16a34a"
        self.lbl_srv_diff_summary.setStyleSheet(
            f"color: {color}; font-weight: bold;"
        )

    def _on_srv_status_changed(self, st):
        if st.startswith("تسویه‌شده"):
            self.pr_srv_paid.set_value(self.pr_srv_fee.get_value())
        elif st.startswith("تسویه‌نشده"):
            self.pr_srv_paid.set_value(0)
        self._recalc_srv_live_summary()

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
        now_dt = self.get_now_datetime_str()
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
        try:
            with self.db.get_connection() as conn:
                rv_row = conn.execute(
                    "SELECT row_version FROM service_records WHERE id=?", (self.selected_srv_rec_id,)
                ).fetchone()
                self._selected_srv_rec_row_version = int(rv_row["row_version"]) if rv_row else None
        except Exception:
            self._selected_srv_rec_row_version = None
        service_name = self.tbl_services.item(r, 4).text()
        seller_name = self.tbl_services.item(r, 5).text()
        if seller_name:
            idx = self.cb_srv_seller.findText(seller_name)
            if idx != -1:
                self.cb_srv_seller.setCurrentIndex(idx)
            else:
                self.cb_srv_seller.addItem(seller_name, None)
                self.cb_srv_seller.setCurrentText(seller_name)
        if service_name:
            idx = self.cb_srv_select.findText(service_name)
            if idx != -1:
                self.cb_srv_select.setCurrentIndex(idx)
            else:
                self.cb_srv_select.addItem(service_name, None)
                self.cb_srv_select.setCurrentText(service_name)
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
        expected_rv = getattr(self, "_selected_srv_rec_row_version", None)
        try:
            self.db.update_service_record(
                self.selected_srv_rec_id,
                self.cb_srv_seller.currentData(),
                self.ed_srv_cust.text().strip(),
                self.pr_srv_fee.get_value(),
                self.pr_srv_side.get_value(),
                self.pr_srv_paid.get_value(),
                self.ed_srv_desc.text().strip(),
                self.cb_srv_status.currentText(),
                expected_row_version=expected_rv,
            )
        except ConcurrencyConflictError as conflict:
            live = conflict.live_row
            choice = self._ask_concurrency_resolution(
                "تعارض ویرایش هم‌زمان فاکتور خدمت",
                conflict,
                [f"مشتری زنده: {live.get('customer_name', '')} | مبلغ زنده: {live.get('service_fee', '')}"],
            )
            if choice == "reload":
                self.refresh_all_data()
                return
            if choice == "overwrite":
                self.db.update_service_record(
                    self.selected_srv_rec_id,
                    self.cb_srv_seller.currentData(),
                    self.ed_srv_cust.text().strip(),
                    self.pr_srv_fee.get_value(),
                    self.pr_srv_side.get_value(),
                    self.pr_srv_paid.get_value(),
                    self.ed_srv_desc.text().strip(),
                    self.cb_srv_status.currentText(),
                    expected_row_version=conflict.actual_version,
                )
            else:
                return
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
        self.cb_upg_tech.setEditable(False)
        self.ed_upg_serial = SmartLineEdit("شماره سریال کالا")

        # مورد ۶: پیش‌فرض اضافه نشدن هزینه قطعه به قیمت کل محصول ارتقا یافته، مگر با فعال کردن تیک
        self.chk_upg_add_cost = QCheckBox(
            "افزودن هزینه قطعه مصرفی به بهای تمام‌شده و قیمت پیشنهادی کالای ارتقایافته"
        )
        self.chk_upg_add_cost.setChecked(False)
        self.chk_upg_consume_stock = QCheckBox(
            "کسر تعداد قطعه مصرفی از موجودی انبار"
        )
        self.chk_upg_consume_stock.setChecked(True)
        self.chk_upg_consume_stock.setToolTip(
            "در صورت غیرفعال بودن، مشخصات و هزینه ارتقا ثبت می‌شود اما موجودی فیزیکی قطعه تغییر نمی‌کند."
        )

        grid.addWidget(QLabel("محموله کالای هدف:"), 0, 0)
        grid.addWidget(self.cb_upg_target, 0, 1)
        grid.addWidget(QLabel("تعداد کالای هدف:"), 0, 2)
        grid.addWidget(self.cb_upg_target_qty, 0, 3)

        grid.addWidget(QLabel("قطعه مصرفی از انبار:"), 1, 0)
        grid.addWidget(self.cb_upg_part, 1, 1)
        grid.addWidget(QLabel("تعداد قطعه در هر کالا:"), 1, 2)
        grid.addWidget(self.cb_upg_part_qty, 1, 3)

        grid.addWidget(QLabel("اجرت ارتقا هر واحد:"), 2, 0)
        grid.addWidget(self.pr_upg_labor, 2, 1)
        grid.addWidget(QLabel("مشخصات جدید دستگاه:"), 2, 2)
        grid.addWidget(self.ed_upg_new_specs, 2, 3)

        grid.addWidget(QLabel("تاریخ ارتقا:"), 3, 0)
        grid.addWidget(self.dt_upg_date, 3, 1)
        grid.addWidget(QLabel("مسئول ارتقا:"), 3, 2)
        grid.addWidget(self.cb_upg_tech, 3, 3)

        grid.addWidget(self.chk_upg_add_cost, 4, 0, 1, 4)
        grid.addWidget(self.chk_upg_consume_stock, 5, 0, 1, 4)

        upg_btn_row = QHBoxLayout()
        btn_clear_upg = QPushButton("پاک کردن فرم")
        btn_clear_upg.setObjectName("btnSecondary")
        btn_clear_upg.clicked.connect(self._clear_upgrade_form)
        btn_upg = QPushButton("🔧 ثبت ارتقای جدید")
        btn_upg.clicked.connect(self._save_upgrade)
        btn_edit_upg = QPushButton("✏️ ویرایش ارتقای انتخاب‌شده")
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
        grid.addLayout(upg_btn_row, 6, 0, 1, 4)

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
                # Target stock is advisory for upgrade; allow an explicit quantity
                # and show a confirmation instead of disabling the operation.
                self.cb_upg_target_qty.set_max_qty(300)
                specs_txt = row["final_specs"] or row["initial_specs"] or ""
                if not specs_txt and row["specs_json"]:
                    specs_dict = json.loads(row["specs_json"] or "{}")
                    specs_txt = self._format_specs_for_display(specs_dict, row["category"])
                self.ed_upg_new_specs.setText(specs_txt or "")
                self._on_upg_part_changed()

    def _on_upg_part_changed(self, *_):
        # Inventory sufficiency is a confirmation decision during Save, not a
        # quantity-picker restriction: permit the requested quantity even at zero stock.
        self.cb_upg_part_qty.set_max_qty(300)
        self.cb_upg_part_qty.setEnabled(True)
        if hasattr(self, "chk_upg_consume_stock"):
            is_batch = (
                self.cb_upg_part.currentIndex() >= 0
                and self.cb_upg_part.currentData() is not None
            )
            self.chk_upg_consume_stock.setEnabled(is_batch)
            # Keep the default checked state even when manual parts disable stock deduction.
            # Manual parts have no batch inventory to consume, so the disabled flag is ignored.

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
            consume_stock = bool(self.chk_upg_consume_stock.isChecked())
            warning_messages = []
            part_row = None
            if p_id is not None:
                with self.db.get_connection() as conn:
                    part_row = conn.execute(
                        "SELECT remaining_qty, batch_code FROM batches WHERE id=?",
                        (p_id,),
                    ).fetchone()
                requested_parts = (
                    self.cb_upg_target_qty.get_qty()
                    * self.cb_upg_part_qty.get_qty()
                )
                if consume_stock and (
                    not part_row or int(part_row["remaining_qty"]) < requested_parts
                ):
                    warning_messages.append(
                        f"موجودی قطعه «{part_row['batch_code'] if part_row else part_text}» "
                        f"کافی نیست (موجودی: "
                        f"{int(part_row['remaining_qty']) if part_row else 0}، "
                        f"مقدار درخواستی: {requested_parts})."
                    )
            elif consume_stock:
                consume_stock = False

            if warning_messages and not _ask_yes_no(
                self, "موجودی قطعه مصرفی",
                "\n".join(warning_messages)
                + "\n\nآیا می‌خواهید مشخصات را اعمال کنید و بدون کسر موجودی ادامه دهید؟"
            ):
                return
            if warning_messages:
                consume_stock = False
            expected_rv = getattr(self, "_selected_upgrade_row_version", None) if self.selected_upgrade_id else None
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
                    upgrade_id=self.selected_upgrade_id,
                    manual_part_description=part_text if p_id is None else "",
                    consume_stock=consume_stock,
                    expected_row_version=expected_rv,
                )
            except ConcurrencyConflictError as conflict:
                choice = self._ask_concurrency_resolution("تعارض ویرایش هم‌زمان ارتقا", conflict)
                if choice == "reload":
                    self.refresh_all_data()
                    self._clear_upgrade_form()
                    return
                if choice == "overwrite":
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
                        expected_row_version=conflict.actual_version,
                    )
                else:
                    return
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
        self._selected_upgrade_row_version = None
        self.tbl_upgrades.clearSelection()
        self.cb_upg_target.setCurrentIndex(-1)
        self.cb_upg_part.setCurrentIndex(-1)
        self.cb_upg_part.setEditText("")
        self.cb_upg_tech.setCurrentIndex(-1)
        self._select_default_operator(self.cb_upg_tech)
        self.cb_upg_target_qty.setCurrentText("1")
        self.cb_upg_part_qty.setCurrentText("1")
        self.cb_upg_part_qty.setEnabled(0)
        self.pr_upg_labor.set_value(0)
        self.ed_upg_new_specs.clear()
        self.ed_upg_serial.clear()
        self.chk_upg_add_cost.setChecked(False)
        self.chk_upg_consume_stock.setChecked(True)
        self.chk_upg_consume_stock.setEnabled(False)
        self.dt_upg_date.set_date(self.get_today_date_str())
        self._on_upg_target_changed()

    def _on_upgrade_selected(self):
        selected = self.tbl_upgrades.selectedItems()
        if not selected:
            return
        row_index = selected[0].row()
        self.selected_upgrade_id = int(self.tbl_upgrades.item(row_index, 0).text())
        with self.db.get_connection() as conn:
            upgrade = conn.execute(
                "SELECT id, target_batch_id, part_batch_id, technician_id, target_qty, part_qty_used, "
                "stock_deducted_qty, part_unit_cost, labor_cost_unit, added_cost_unit, "
                "upgrade_date, serial_number, manual_part_description, old_specs, new_specs, "
                "notes, created_at, updated_at, row_version FROM upgrades WHERE id=?",
                (self.selected_upgrade_id,)
            ).fetchone()
            self._selected_upgrade_row_version = int(upgrade["row_version"]) if upgrade else None
            related_batches = conn.execute(
                """SELECT b.id, b.batch_code, b.product_id, b.supplier_id, b.buyer_employee_id,
                          b.invoice_number, b.purchase_date, b.initial_qty, b.sold_qty,
                          b.returned_qty, b.remaining_qty, b.unit_purchase_price,
                          b.extra_cost_total, b.upgrade_cost_unit, b.unit_cost_price,
                          b.suggested_sell_price, b.profit_pct, b.paid_amount,
                          b.settlement_status, b.serial_numbers, b.colors_json,
                          b.initial_specs, b.final_specs, b.supplier_name_snapshot,
                          b.notes, b.created_at, b.updated_at,
                          p.code, p.name AS product_name, p.category, p.sub_category,
                          p.brand, p.model, p.specs_json
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
        self.chk_upg_consume_stock.setChecked(
            int(upgrade["stock_deducted_qty"] or 0) > 0
        )
        self.chk_upg_consume_stock.setEnabled(upgrade["part_batch_id"] is not None)


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
        self.ed_sup_name = SmartLineEdit("")
        self.ed_sup_name.setPlaceholderText("نام تأمین‌کننده / شرکت...")
        self.ed_sup_phone = SmartLineEdit("")
        self.ed_sup_phone.setPlaceholderText("تلفن تماس...")
        self.ed_sup_addr = SmartLineEdit("")
        self.ed_sup_addr.setPlaceholderText("آدرس یا توضیحات...")
        h_sup.addWidget(QLabel("نام تأمین‌کننده:"))
        h_sup.addWidget(self.ed_sup_name)
        h_sup.addWidget(QLabel("تلفن:"))
        h_sup.addWidget(self.ed_sup_phone)
        h_sup.addWidget(QLabel("آدرس / توضیحات:"))
        h_sup.addWidget(self.ed_sup_addr)
        v_sup.addLayout(h_sup)

        btn_sup_row = QHBoxLayout()
        btn_add_sup = QPushButton("➕ افزودن تأمین‌کننده")
        btn_add_sup.clicked.connect(self._add_supplier)
        btn_edit_sup = QPushButton("✏️ ویرایش تأمین‌کننده انتخابی")
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
        self._add_scrollable_tab(tab, "💳 تأمین‌کنندگان")

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
        try:
            with self.db.get_connection() as conn:
                rv_row = conn.execute(
                    "SELECT row_version FROM suppliers WHERE id=?", (self.selected_supplier_id,)
                ).fetchone()
                self._selected_supplier_row_version = int(rv_row["row_version"]) if rv_row else None
        except Exception:
            self._selected_supplier_row_version = None
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
        expected_rv = getattr(self, "_selected_supplier_row_version", None)
        try:
            try:
                self.db.update_supplier(
                    self.selected_supplier_id,
                    name,
                    self.ed_sup_phone.text().strip(),
                    self.ed_sup_addr.text().strip(),
                    "",
                    expected_row_version=expected_rv,
                )
            except ConcurrencyConflictError as conflict:
                live = conflict.live_row
                choice = self._ask_concurrency_resolution(
                    "تعارض ویرایش هم‌زمان تأمین‌کننده",
                    conflict,
                    [f"نام زنده: {live.get('name', '')} | تلفن زنده: {live.get('phone', '')}"],
                )
                if choice == "reload":
                    self.refresh_all_data()
                    return
                if choice == "overwrite":
                    self.db.update_supplier(
                        self.selected_supplier_id,
                        name,
                        self.ed_sup_phone.text().strip(),
                        self.ed_sup_addr.text().strip(),
                        "",
                        expected_row_version=conflict.actual_version,
                    )
                else:
                    return
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
        self._sync_reports_tab_combo()

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
        self.cb_rep_emp.setEditable(False)
        self.cb_rep_cat = SearchableComboBox()
        self.cb_rep_cat.setEditable(False)
        report_categories = (
            list(self.catalog_config.get("categories") or [])
        )
        self.cb_rep_cat.addItems(["همه دسته‌ها"] + report_categories)
        self.ed_rep_search = SmartLineEdit(
            "جست‌وجوی کد کالا، دسته‌بندی، زیرگروه (مثلاً کیبورد)، برند، مدل، فاکتور..."
        )
        self.cb_rep_sort = QComboBox()
        self.cb_rep_sort.addItem("آخرین ویرایش / ایجاد (پیش‌فرض)", "activity_desc")
        self.cb_rep_sort.addItem("اولین ویرایش / ایجاد", "activity_asc")
        self.cb_rep_sort.addItem("تاریخ تراکنش: جدیدترین", "transaction_desc")
        self.cb_rep_sort.addItem("تاریخ تراکنش: قدیمی‌ترین", "transaction_asc")
        self.cb_rep_sort.addItem("مبلغ / قیمت: بیشترین", "amount_desc")
        self.cb_rep_sort.addItem("مبلغ / قیمت: کمترین", "amount_asc")
        self.cb_rep_sort.addItem("وضعیت تسویه", "settlement_asc")
        self.cb_rep_sort.addItem("دسته‌بندی", "category_asc")
        self.cb_rep_sort.addItem("کاربر / مسئول", "user_asc")

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

        grid.addWidget(QLabel("کاربر:"), 1, 0)
        grid.addWidget(self.cb_rep_emp, 1, 1)
        grid.addWidget(QLabel("دسته‌بندی:"), 1, 2)
        grid.addWidget(self.cb_rep_cat, 1, 3)
        grid.addWidget(QLabel("مرتب‌سازی بر اساس:"), 1, 4)
        grid.addWidget(self.cb_rep_sort, 1, 5, 1, 2)
        grid.addWidget(btn_exp_excel, 1, 7)

        layout.addWidget(gb_flt)

        self.lbl_rep_totals = QLabel("خلاصه مالی گزارش:")
        self.lbl_rep_totals.setObjectName("reportSummary")
        layout.addWidget(self.lbl_rep_totals)

        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        search_row.addWidget(QLabel("جست‌وجو / فیلتر:"))
        search_row.addWidget(self.ed_rep_search, 1)
        self.tbl_report = self._create_table(["ستون ۱"])
        search_row.addWidget(self._create_table_print_button(self.tbl_report, "reports"), 0)
        layout.addLayout(search_row)

        layout.addWidget(self.tbl_report)

        self.cb_rep_type.currentIndexChanged.connect(self._update_report_live)
        self.cb_rep_sort.currentIndexChanged.connect(self._update_report_live)
        self.cb_rep_preset.currentIndexChanged.connect(self._on_rep_preset_changed)
        self._on_rep_preset_changed()
        self.dt_rep_from.dateChanged.connect(self._update_report_live)
        self.dt_rep_to.dateChanged.connect(self._update_report_live)
        self.cb_rep_emp.currentIndexChanged.connect(self._update_report_live)
        self.cb_rep_cat.currentTextChanged.connect(self._update_report_live)
        self._rep_search_timer = QTimer(self.ed_rep_search)
        self._rep_search_timer.setSingleShot(True)
        self._rep_search_timer.setInterval(150)
        self._rep_search_timer.timeout.connect(self._update_report_live)

        def _on_rep_search_changed(_text):
            if self.tbl_report.rowCount() > 500:
                self._rep_search_timer.start()
            else:
                self._rep_search_timer.stop()
                self._update_report_live()

        self.ed_rep_search.textChanged.connect(_on_rep_search_changed)

        self._add_scrollable_tab(tab, "📈 گزارش‌های جامع")

    def _sync_reports_tab_combo(self):
        if not hasattr(self, "cb_rep_type"):
            return
        current_rep = self.cb_rep_type.currentText()
        self.cb_rep_type.blockSignals(True)
        self.cb_rep_type.clear()

        if self._is_scoped_access():
            permission = self._permission_policy(self.active_employee.get("permissions") or "")
            if "ثبت خرید و انبارداری" in permission:
                allowed_reports = [
                    "۲. گزارش کامل تمام خریدها (محموله‌ها)",
                    "۷. گزارش جامع عملکرد هر کاربر / فروشنده",
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
            self.cb_rep_type.addItems(allowed_reports)
        else:
            self.cb_rep_type.addItem("همه (گزارش جامع خرید، فروش و خدمات)")
            self.cb_rep_type.insertSeparator(self.cb_rep_type.count())
            self.cb_rep_type.addItems([
                "۱. گزارش کامل تمام فروش‌ها",
                "۱۱. گزارش تخفیف‌ها و تشدیدهای فروش",
                "۱۲. گزارش کامل خدمات انجام‌شده",
            ])
            self.cb_rep_type.insertSeparator(self.cb_rep_type.count())
            self.cb_rep_type.addItems([
                "۲. گزارش کامل تمام خریدها (محموله‌ها)",
                "۹. گزارش بدهی به تأمین‌کنندگان",
            ])
            self.cb_rep_type.insertSeparator(self.cb_rep_type.count())
            self.cb_rep_type.addItems([
                "۳. گزارش موجودی فعلی کالاها",
                "۴. گزارش موجودی و سود به تفکیک محموله",
                "۵. گزارش سود تجمعی هر کالا",
                "۶. گزارش سود و عملکرد هر محموله",
                "۸. گزارش کالاهای کم‌موجود (نیازمند خرید)",
            ])
            self.cb_rep_type.insertSeparator(self.cb_rep_type.count())
            self.cb_rep_type.addItem("۷. گزارش جامع عملکرد هر کاربر / فروشنده")
            self.cb_rep_type.addItem("۱۰. گزارش فاکتورهای تسویه‌نشده (طلب و بدهی)")

        custom_defs = self._get_custom_report_definitions()
        if custom_defs:
            self.cb_rep_type.insertSeparator(self.cb_rep_type.count())
            for name in custom_defs.keys():
                self.cb_rep_type.addItem(name)

        if current_rep:
            idx = self.cb_rep_type.findText(current_rep)
            if idx >= 0:
                self.cb_rep_type.setCurrentIndex(idx)
            else:
                self.cb_rep_type.setCurrentIndex(0)
        else:
            self.cb_rep_type.setCurrentIndex(0)
        self.cb_rep_type.blockSignals(False)

    def _on_rep_preset_changed(self):
        preset = self.cb_rep_preset.currentText()
        cal = self.get_active_calendar()
        self._sync_date_widgets_calendar()
        today_g = date.today()

        def _fmt_offset(days_ago: int) -> str:
            g = today_g - timedelta(days=days_ago)
            y, m, d = datetime_format.from_gregorian_date(g, cal)
            return f"{y:04d}/{m:02d}/{d:02d}"

        if preset == "همه زمان‌ها":
            if cal == CALENDAR_GREGORIAN:
                self.dt_rep_from.set_date("1990/01/01")
                self.dt_rep_to.set_date("2100/12/31")
            elif cal == CALENDAR_HIJRI:
                self.dt_rep_from.set_date("1430/01/01")
                self.dt_rep_to.set_date("1550/12/29")
            else:
                self.dt_rep_from.set_date("1400/01/01")
                self.dt_rep_to.set_date("1600/12/29")
        elif preset == "امروز":
            s = _fmt_offset(0)
            self.dt_rep_from.set_date(s)
            self.dt_rep_to.set_date(s)
        elif preset == "دیروز":
            s = _fmt_offset(1)
            self.dt_rep_from.set_date(s)
            self.dt_rep_to.set_date(s)
        elif preset == "هفته گذشته":
            self.dt_rep_from.set_date(_fmt_offset(7))
            self.dt_rep_to.set_date(_fmt_offset(0))
        elif preset == "یک ماه گذشته":
            self.dt_rep_from.set_date(_fmt_offset(30))
            self.dt_rep_to.set_date(_fmt_offset(0))
        elif preset == "سال گذشته":
            self.dt_rep_from.set_date(_fmt_offset(365))
            self.dt_rep_to.set_date(_fmt_offset(0))

        self._update_report_live()

    def _update_report_live(self):
        rep_type = self.cb_rep_type.currentText()
        active_cal = self.get_active_calendar()
        d_from = self.dt_rep_from.get_date()
        d_to = self.dt_rep_to.get_date()
        emp_id = self.cb_rep_emp.currentData()
        visible_employee_ids = self._visible_employee_ids()
        if visible_employee_ids is not None:
            emp_id = None

        def employee_is_visible(employee_id):
            return (
                visible_employee_ids is None
                or (employee_id is not None and int(employee_id) in visible_employee_ids)
            )

        def service_is_visible(seller_id, technician_id):
            return employee_is_visible(seller_id) or employee_is_visible(technician_id)

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
                    "مشخصات فنی",
                    "کاربر ثبت‌کننده",
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
                           COALESCE(s.updated_at, s.created_at) AS _activity_at,
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
                           COALESCE(b.updated_at, b.created_at) AS _activity_at,
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
                           COALESCE(sr.updated_at, sr.created_at) AS _activity_at,
                           sc.code as code, 'خدمات' as category, sr.service_type as sub_category,
                           sr.service_name as title, '' as specs, e.id as emp_id, e.name as emp_name,
                           sr.customer_name as party, 1 as qty, sr.service_fee as u_price,
                           sr.service_fee as sug_price, sr.side_cost as cost_total,
                           sr.service_fee as amt, sr.paid_amount as paid,
                           sr.net_profit as prof, sr.settlement_status as st,
                           sr.technician_employee_id as technician_id
                    FROM service_records sr
                    JOIN service_catalog sc ON sc.id=sr.service_id
                    LEFT JOIN employees e ON sr.seller_employee_id=e.id
                """).fetchall()

                total_income = 0
                total_buy = 0
                total_profit = 0
                for r in list(s_rows) + list(b_rows) + list(srv_rows):
                    d_only = (r["dt"] or "")[:10]
                    if not datetime_format.is_date_in_range(d_only, d_from, d_to, active_cal):
                        continue
                    if r["t_type"] == "خدمات":
                        if not service_is_visible(r["emp_id"], r["technician_id"]):
                            continue
                    elif not employee_is_visible(r["emp_id"]):
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
                    rem_balance = receivable_balance(amt, paid, r["st"])
                    prof = int(r["prof"])
                    if r["t_type"] == "فروش کالا":
                        diff_str = format_Signed_diff(r["u_price"], r["sug_price"], r["qty"])
                    elif r["t_type"] == "خدمات":
                        adjustment, rem_balance = service_financial_breakdown(
                            amt, paid, r["st"]
                        )
                        diff_str = f"{adjustment:+,}" if adjustment else "0"
                    else:
                        diff_str = "0"

                    if r["t_type"] == "خرید محموله":
                        total_buy += amt
                    else:
                        total_income += amt
                        total_profit += prof

                    rows_data.append(
                        [
                            r["_activity_at"] or r["dt"] or "",
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
                summary_text = (
                    f"مجموع فروش و خدمات: {total_income:,} تومان   |   "
                    f"مجموع خریدها: {total_buy:,} تومان   |   "
                    f"سود خالص کل: {total_profit:,} تومان"
                )

            # ۱ و ۱۱. گزارش کامل تمام فروش‌ها / تخفیف‌ها و تشدیدها
            elif rep_type.startswith("۱.") or rep_type.startswith("۱۱."):
                headers = [
                    "شماره فاکتور",
                    "کد کالا",
                    "شماره سریال",
                    "مشخصات کالا",
                    "تاریخ و ساعت فروش",
                    "دسته‌بندی",
                    "زیرمجموعه",
                    "کد محموله",
                    "فروشنده",
                    "نام مشتری",
                    "شماره تماس مشتری",
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
                    "مشخصات فنی",
                ]
                q = conn.execute("""
                    SELECT s.id, s.invoice_number, s.product_id, s.batch_id, s.seller_employee_id,
                           s.customer_name, s.customer_phone, s.qty, s.returned_qty, s.suggested_unit_price,
                           s.actual_unit_price, s.unit_cost_price, s.unit_discount, s.total_discount,
                           s.price_Markup_unit, s.unit_profit, s.total_profit, s.total_amount,
                           s.paid_amount, s.settlement_status, s.sale_datetime, s.warranty_company,
                           s.warranty_start, s.warranty_months, s.warranty_days, s.warranty_end,
                           s.serial_number, s.specifications, s.colors_json, s.notes,
                           s.created_at, s.updated_at, p.code, p.category, p.sub_category,
                           p.brand, p.model, b.batch_code, b.final_specs, b.initial_specs,
                           e.name as emp_name
                    FROM sales s
                    JOIN products p ON s.product_id=p.id
                    JOIN batches b ON s.batch_id=b.id
                    LEFT JOIN employees e ON s.seller_employee_id=e.id
                    ORDER BY s.updated_at DESC, s.id DESC
                """).fetchall()
                sum_sale, sum_prof, sum_disc = 0, 0, 0
                for r in q:
                    dt = r["sale_datetime"][:10]
                    if not datetime_format.is_date_in_range(dt, d_from, d_to, active_cal):
                        continue
                    if not employee_is_visible(r["seller_employee_id"]):
                        continue
                    if emp_id and r["seller_employee_id"] != emp_id:
                        continue
                    if cat and cat != "همه دسته‌ها" and r["category"] != cat:
                        continue
                    diff_val = (int(r["actual_unit_price"]) - int(r["suggested_unit_price"])) * int(r["qty"])
                    if rep_type.startswith("۱۱.") and diff_val == 0:
                        continue
                    search_pool = f"{r['invoice_number']} {r['code']} {r['serial_number'] or ''} {r['category']} {r['sub_category']} {r['brand']} {r['model']} {r['batch_code']} {r['customer_name'] or ''} {r['customer_phone'] or ''}".lower()
                    if q_txt and q_txt not in search_pool:
                        continue

                    sum_sale += int(r["total_amount"])
                    sum_prof += int(r["total_profit"])
                    sum_disc += int(r["total_discount"])
                    rem_pay = receivable_balance(
                        r["total_amount"], r["paid_amount"], r["settlement_status"]
                    )
                    signed_str = format_Signed_diff(
                        r["actual_unit_price"], r["suggested_unit_price"], r["qty"]
                    )
                    rows_data.append(
                        [
                            r["updated_at"] or r["sale_datetime"] or "",
                            r["invoice_number"],
                            r["code"],
                            r["serial_number"] or "-",
                            f"{r['brand']} {r['model']}".strip() or r["sub_category"],
                            r["sale_datetime"],
                            r["category"],
                            r["sub_category"],
                            r["batch_code"],
                            r["emp_name"],
                            r["customer_name"] or "-",
                            r["customer_phone"] or "-",
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
                    SELECT b.id, b.batch_code, b.product_id, b.supplier_id, b.buyer_employee_id,
                           b.invoice_number, b.purchase_date, b.initial_qty, b.sold_qty, b.returned_qty,
                           b.remaining_qty, b.unit_purchase_price, b.extra_cost_total, b.upgrade_cost_unit,
                           b.unit_cost_price, b.suggested_sell_price, b.profit_pct, b.paid_amount,
                           b.settlement_status, b.serial_numbers, b.colors_json, b.initial_specs,
                           b.final_specs, b.supplier_name_snapshot, b.notes, b.created_at, b.updated_at,
                           p.code, p.category, p.sub_category, p.brand, p.model,
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
                    if not datetime_format.is_date_in_range(r["purchase_date"], d_from, d_to, active_cal):
                        continue
                    if not employee_is_visible(r["buyer_employee_id"]):
                        continue
                    if emp_id and r["buyer_employee_id"] != emp_id:
                        continue
                    if cat and cat != "همه دسته‌ها" and r["category"] != cat:
                        continue
                    search_pool = f"{r['batch_code']} {r['invoice_number']} {r['code']} {r['category']} {r['sub_category']} {r['brand']} {r['model']} {r['sup_name']}".lower()
                    if q_txt and q_txt not in search_pool:
                        continue

                    total_buy = (r["unit_purchase_price"] * r["initial_qty"]) + r["extra_cost_total"]
                    debt = receivable_balance(
                        total_buy, r["paid_amount"], r["settlement_status"]
                    )
                    if rep_type.startswith("۹.") and debt == 0:
                        continue
                    sum_buy += total_buy
                    sum_debt += debt
                    sum_b_prof += int(r["batch_profit"])
                    rows_data.append(
                        [
                            r["updated_at"] or r["purchase_date"] or "",
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
                if visible_employee_ids is None:
                    batch_owner_filter = ""
                    sale_owner_filter = ""
                    product_scope_params = ()
                elif visible_employee_ids:
                    scope_ids = tuple(sorted(visible_employee_ids))
                    scope_marks = ",".join("?" for _ in scope_ids)
                    batch_owner_filter = f" AND b.buyer_employee_id IN ({scope_marks})"
                    sale_owner_filter = f" AND s.seller_employee_id IN ({scope_marks})"
                    product_scope_params = (*scope_ids, *scope_ids, *scope_ids, *scope_ids, *scope_ids)
                else:
                    batch_owner_filter = " AND 0=1"
                    sale_owner_filter = " AND 0=1"
                    product_scope_params = ()
                q = conn.execute(f"""
                    SELECT p.id, p.code, p.name, p.category, p.sub_category, p.brand, p.model,
                           p.specs_json, p.description, p.reorder_point, p.default_profit_pct,
                           p.is_active, p.created_at, p.updated_at,
                           COALESCE((SELECT SUM(initial_qty) FROM batches b WHERE b.product_id=p.id{batch_owner_filter}), 0) as init_qty,
                           COALESCE((SELECT SUM(remaining_qty) FROM batches b WHERE b.product_id=p.id{batch_owner_filter}), 0) as rem_qty,
                           COALESCE((SELECT SUM(sold_qty) FROM batches b WHERE b.product_id=p.id{batch_owner_filter}), 0) as s_qty,
                           COALESCE((SELECT SUM(total_amount) FROM sales s WHERE s.product_id=p.id{sale_owner_filter}), 0) as prod_rev,
                           COALESCE((SELECT SUM(total_profit) FROM sales s WHERE s.product_id=p.id{sale_owner_filter}), 0) as prod_prof
                    FROM products p
                    ORDER BY p.updated_at DESC, p.id DESC
                """, product_scope_params).fetchall()
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
                            r["updated_at"] or "",
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

            # ۷. گزارش جامع عملکرد هر کاربر
            elif rep_type.startswith("۷."):
                headers = [
                    "نام کاربر",
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
                    "مجموع سود ایجادی کاربر",
                ]
                emps = self._execute_scoped_query(
                    conn,
                    "SELECT id, name, role, phone, is_active, permissions, password, created_at, updated_at "
                    "FROM employees ORDER BY updated_at DESC, id DESC",
                    "id",
                ).fetchall()
                for e in emps:
                    if emp_id and e["id"] != emp_id:
                        continue
                    b_rows = [
                        r for r in conn.execute(
                            "SELECT purchase_date, unit_purchase_price, initial_qty, extra_cost_total "
                            "FROM batches WHERE buyer_employee_id=?",
                            (e["id"],),
                        ).fetchall()
                        if datetime_format.is_date_in_range(r["purchase_date"], d_from, d_to, active_cal)
                    ]
                    b_stat = {
                        "cnt": len(b_rows),
                        "amt": sum((int(r["unit_purchase_price"]) * int(r["initial_qty"])) + int(r["extra_cost_total"]) for r in b_rows),
                    }
                    s_rows = [
                        r for r in conn.execute(
                            "SELECT sale_datetime, qty, total_amount, total_discount, total_profit "
                            "FROM sales WHERE seller_employee_id=?",
                            (e["id"],),
                        ).fetchall()
                        if datetime_format.is_date_in_range(r["sale_datetime"], d_from, d_to, active_cal)
                    ]
                    s_stat = {
                        "cnt": len(s_rows),
                        "items_cnt": sum(int(r["qty"]) for r in s_rows),
                        "amt": sum(int(r["total_amount"]) for r in s_rows),
                        "disc": sum(int(r["total_discount"]) for r in s_rows),
                        "prof": sum(int(r["total_profit"]) for r in s_rows),
                    }
                    srv_rows = [
                        r for r in conn.execute(
                            "SELECT service_datetime, net_profit FROM service_records WHERE seller_employee_id=?",
                            (e["id"],),
                        ).fetchall()
                        if datetime_format.is_date_in_range(r["service_datetime"], d_from, d_to, active_cal)
                    ]
                    srv_stat = {
                        "cnt": len(srv_rows),
                        "prof": sum(int(r["net_profit"]) for r in srv_rows),
                    }
                    tot_emp_prof = int(s_stat["prof"]) + int(srv_stat["prof"])
                    rows_data.append(
                        [
                            e["updated_at"] or "",
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
                    "کاربر مسئول",
                    "شرح کالا / خدمت",
                    "مبلغ کل (تومان)",
                    "مبلغ پرداخت‌شده (تومان)",
                    "مانده تسویه‌نشده (تومان)",
                    "وضعیت تسویه",
                ]
                sum_receivable, sum_payable = 0, 0
                for r in self._execute_scoped_query(conn, """
                    SELECT s.id, s.invoice_number, s.product_id, s.batch_id, s.seller_employee_id,
                           s.customer_name, s.qty, s.returned_qty, s.suggested_unit_price,
                           s.actual_unit_price, s.unit_cost_price, s.unit_discount, s.total_discount,
                           s.price_Markup_unit, s.unit_profit, s.total_profit, s.total_amount,
                           s.paid_amount, s.settlement_status, s.sale_datetime, s.warranty_company,
                           s.warranty_start, s.warranty_months, s.warranty_days, s.warranty_end,
                           s.serial_number, s.specifications, s.colors_json, s.notes,
                           s.created_at, s.updated_at, p.sub_category, p.brand, p.model,
                           e.name as emp_name
                    FROM sales s JOIN products p ON s.product_id=p.id LEFT JOIN employees e ON s.seller_employee_id=e.id
                    WHERE s.settlement_status != 'تسویه‌شده'
                """, "s.seller_employee_id").fetchall():
                    rem_amt = receivable_balance(
                        r["total_amount"], r["paid_amount"], r["settlement_status"]
                    )
                    if rem_amt <= 0:
                        continue
                    sum_receivable += rem_amt
                    rows_data.append(
                        [
                            r["updated_at"] or r["sale_datetime"] or "",
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
                for r in self._execute_scoped_query(conn, """
                    SELECT b.id, b.batch_code, b.product_id, b.supplier_id, b.buyer_employee_id,
                           b.invoice_number, b.purchase_date, b.initial_qty, b.sold_qty, b.returned_qty,
                           b.remaining_qty, b.unit_purchase_price, b.extra_cost_total, b.upgrade_cost_unit,
                           b.unit_cost_price, b.suggested_sell_price, b.profit_pct, b.paid_amount,
                           b.settlement_status, b.serial_numbers, b.colors_json, b.initial_specs,
                           b.final_specs, b.supplier_name_snapshot, b.notes, b.created_at, b.updated_at,
                           p.sub_category, p.brand, p.model,
                           COALESCE(sup.name,b.supplier_name_snapshot) as sup_name, e.name as emp_name
                    FROM batches b JOIN products p ON b.product_id=p.id
                    LEFT JOIN suppliers sup ON b.supplier_id=sup.id LEFT JOIN employees e ON b.buyer_employee_id=e.id
                    WHERE b.settlement_status != 'تسویه‌شده'
                """, "b.buyer_employee_id").fetchall():
                    tot = (r["unit_purchase_price"] * r["initial_qty"]) + r["extra_cost_total"]
                    rem_amt = receivable_balance(
                        tot, r["paid_amount"], r["settlement_status"]
                    )
                    if rem_amt <= 0:
                        continue
                    sum_payable += rem_amt
                    rows_data.append(
                        [
                            r["updated_at"] or r["purchase_date"] or "",
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
                for r in self._execute_scoped_query(conn, """
                    SELECT sr.id, sr.invoice_number, sr.service_id, sr.seller_employee_id,
                           sr.technician_employee_id, sr.service_type, sr.service_name,
                           sr.customer_name, sr.historical_tariff, sr.service_fee, sr.side_cost,
                           sr.paid_amount, sr.net_profit, sr.settlement_status, sr.service_datetime,
                           sr.description, sr.created_at, sr.updated_at, e.name as emp_name
                    FROM service_records sr
                    LEFT JOIN employees e ON sr.seller_employee_id=e.id
                    WHERE sr.settlement_status != 'تسویه‌شده'
                """, "sr.seller_employee_id", "sr.technician_employee_id").fetchall():
                    rem_amt = receivable_balance(
                        r["service_fee"], r["paid_amount"], r["settlement_status"]
                    )
                    if rem_amt <= 0:
                        continue
                    sum_receivable += rem_amt
                    rows_data.append(
                        [
                            r["updated_at"] or r["service_datetime"] or "",
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
                    "تخفیف (-) / تشدید (+)",
                    "هزینه‌های جانبی (تومان)",
                    "سود خالص خدمت (تومان)",
                    "مبلغ دریافتی (تومان)",
                    "مانده طلب",
                    "وضعیت تسویه",
                    "شرح خدمات",
                ]
                q = conn.execute("""
                    SELECT sr.id, sr.invoice_number, sr.service_id, sr.seller_employee_id,
                           sr.technician_employee_id, sr.service_type, sr.service_name,
                           sr.customer_name, sr.historical_tariff, sr.service_fee, sr.side_cost,
                           sr.paid_amount, sr.net_profit, sr.settlement_status, sr.service_datetime,
                           sr.description, sr.created_at, sr.updated_at, e.name as emp_name
                    FROM service_records sr
                    LEFT JOIN employees e ON sr.seller_employee_id=e.id
                    ORDER BY sr.updated_at DESC, sr.id DESC
                """).fetchall()
                sum_fee, sum_side, sum_net, sum_adjustment, sum_receivable = 0, 0, 0, 0, 0
                for r in q:
                    dt = r["service_datetime"][:10]
                    if not datetime_format.is_date_in_range(dt, d_from, d_to, active_cal):
                        continue
                    if not service_is_visible(
                        r["seller_employee_id"], r["technician_employee_id"]
                    ):
                        continue
                    if emp_id and r["seller_employee_id"] != emp_id:
                        continue
                    if q_txt and q_txt not in f"{r['invoice_number']} {r['service_name']} {r['customer_name']} {r['description']}".lower():
                        continue
                    sum_fee += int(r["service_fee"])
                    sum_side += int(r["side_cost"])
                    sum_net += int(r["net_profit"])
                    adjustment, rem_srv = service_financial_breakdown(
                        r["service_fee"], r["paid_amount"], r["settlement_status"]
                    )
                    sum_adjustment += adjustment
                    sum_receivable += rem_srv
                    rows_data.append(
                        [
                            r["updated_at"] or r["service_datetime"] or "",
                            r["invoice_number"],
                            r["service_datetime"],
                            r["service_type"],
                            r["service_name"],
                            r["emp_name"],
                            r["customer_name"] or "-",
                            f"{r['service_fee']:,}",
                            f"{adjustment:+,}" if adjustment else "0",
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
                    f"تخفیف/تشدید: {sum_adjustment:+,} تومان   |   "
                    f"طلب خدمات: {sum_receivable:,} تومان   |   "
                    f"هزینه‌های جانبی: {sum_side:,} تومان   |   "
                    f"سود خالص خدمات: {sum_net:,} تومان"
                )

            else:
                custom_defs = self._get_custom_report_definitions()
                exp_cfgs = self._get_report_excel_export_configs()
                if rep_type in custom_defs:
                    selected_cols = exp_cfgs.get(rep_type, custom_defs[rep_type])
                    headers = list(selected_cols)
                    joined_query = conn.execute("""
                        SELECT s.id as sale_id, s.invoice_number, s.sale_datetime, s.qty,
                               s.suggested_unit_price, s.actual_unit_price, s.unit_cost_price,
                               s.unit_discount, s.total_discount, s.price_Markup_unit,
                               s.unit_profit, s.total_profit, s.total_amount, s.paid_amount,
                               s.settlement_status, s.warranty_company, s.warranty_end,
                               s.serial_number, s.customer_name, s.customer_phone,
                               s.specifications, s.colors_json, s.updated_at, s.seller_employee_id,
                               p.code as p_code, p.serial_number as prod_serial, p.category,
                               p.sub_category, p.brand, p.model, p.specs_json, p.description as prod_desc,
                               p.reorder_point, p.default_profit_pct,
                               b.batch_code, b.invoice_number as batch_inv, b.purchase_date,
                               b.initial_qty as batch_initial_qty, b.sold_qty as batch_sold_qty,
                               b.remaining_qty as batch_remaining_qty, b.unit_purchase_price,
                               b.extra_cost_total, b.upgrade_cost_unit, b.unit_cost_price as batch_unit_cost,
                               b.suggested_sell_price as batch_suggested_sell, b.profit_pct as batch_profit_pct,
                               b.paid_amount as batch_paid, b.settlement_status as batch_settlement,
                               b.serial_numbers as batch_serials, b.colors_json as batch_colors_json,
                               b.initial_specs as batch_initial_specs,
                               COALESCE(sup.name, b.supplier_name_snapshot) as sup_name,
                               e.name as emp_name
                        FROM sales s
                        JOIN products p ON s.product_id=p.id
                        JOIN batches b ON s.batch_id=b.id
                        LEFT JOIN suppliers sup ON b.supplier_id=sup.id
                        LEFT JOIN employees e ON s.seller_employee_id=e.id
                        ORDER BY s.updated_at DESC, s.id DESC
                    """).fetchall()

                    for r in joined_query:
                        dt = (r["sale_datetime"] or "")[:10]
                        if not datetime_format.is_date_in_range(dt, d_from, d_to, active_cal):
                            continue
                        if not employee_is_visible(r["seller_employee_id"]):
                            continue
                        if emp_id and r["seller_employee_id"] != emp_id:
                            continue
                        if cat and cat != "همه دسته‌ها" and r["category"] != cat:
                            continue
                        search_haystack = f"{r['invoice_number']} {r['p_code']} {r['prod_serial'] or ''} {r['serial_number'] or ''} {r['customer_name'] or ''} {r['customer_phone'] or ''} {r['brand']} {r['model']} {r['batch_code']}".lower()
                        if q_txt and q_txt not in search_haystack:
                            continue

                        val_map = {
                            "کد کالا": r["p_code"],
                            "شماره سریال": r["prod_serial"] or r["serial_number"] or "-",
                            "دسته‌بندی": r["category"],
                            "زیرمجموعه": r["sub_category"],
                            "برند": r["brand"],
                            "مدل": r["model"],
                            "مشخصات فنی": self._format_specs_for_display(json.loads(r["specs_json"] or "{}"), r["category"]),
                            "موجودی کل": r["batch_remaining_qty"],
                            "تعداد فروش": r["qty"],
                            "حداقل موجودی": r["reorder_point"],
                            "درصد سود (%)": r["default_profit_pct"],
                            "وضعیت موجودی": "موجود" if r["batch_remaining_qty"] > r["reorder_point"] else ("کم‌موجود" if r["batch_remaining_qty"] > 0 else "ناموجود"),
                            "توضیحات": r["prod_desc"] or "-",
                            "کد محموله": r["batch_code"],
                            "تأمین‌کننده": r["sup_name"] or "-",
                            "مسئول خرید": r["emp_name"] or "-",
                            "شماره فاکتور خرید": r["batch_inv"] or "-",
                            "تاریخ خرید": r["purchase_date"] or "-",
                            "ساعت خرید": (
                                r["purchase_date"].split(" ", 1)[1].strip()
                                if r["purchase_date"] and " " in r["purchase_date"]
                                else "-"
                            ),
                            "تعداد خرید": r["batch_initial_qty"],
                            "تعداد فروش محموله": r["batch_sold_qty"],
                            "موجودی فعلی محموله": r["batch_remaining_qty"],
                            "قیمت خرید واحد": f"{r['unit_purchase_price']:,}",
                            "هزینه جانبی کل": f"{r['extra_cost_total']:,}",
                            "هزینه ارتقا واحد": f"{r['upgrade_cost_unit']:,}",
                            "بهای تمام‌شده واحد": f"{r['batch_unit_cost']:,}",
                            "قیمت فروش پیشنهادی": f"{r['batch_suggested_sell']:,}",
                            "درصد سود (%) محموله": r["batch_profit_pct"],
                            "وضعیت تسویه خرید": r["batch_settlement"],
                            "پرداخت‌شده خرید": f"{r['batch_paid']:,}",
                            "مانده بدهی خرید": f"{receivable_balance((r['unit_purchase_price'] * r['batch_initial_qty'] + r['extra_cost_total']), r['batch_paid'], r['batch_settlement']):,}",
                            "مشخصات فنی محموله": r["batch_initial_specs"] or "-",
                            "بهای کل محموله (تومان)": f"{(r['unit_purchase_price'] * r['batch_initial_qty'] + r['extra_cost_total']):,}",
                            "رنگ‌های محموله": "، ".join(self._decode_colors(r["batch_colors_json"])) or "-",
                            "شماره فاکتور فروش": r["invoice_number"],
                            "تاریخ و ساعت فروش": r["sale_datetime"],
                            "فروشنده": r["emp_name"] or "-",
                            "نام مشتری": r["customer_name"] or "-",
                            "شماره تماس مشتری": r["customer_phone"] or "-",
                            "تعداد فروش": r["qty"],
                            "قیمت پیشنهادی واحد فروش": f"{r['suggested_unit_price']:,}",
                            "قیمت فروش واحد": f"{r['actual_unit_price']:,}",
                            "تخفیف (-) / تشدید (+)": format_Signed_diff(r["actual_unit_price"], r["suggested_unit_price"], r["qty"]),
                            "بهای تمام‌شده واحد فروش": f"{r['unit_cost_price']:,}",
                            "سود هر واحد": f"{r['unit_profit']:,}",
                            "سود کل فروش": f"{r['total_profit']:,}",
                            "مبلغ کل فاکتور": f"{r['total_amount']:,}",
                            "دریافتی فروش": f"{r['paid_amount']:,}",
                            "وضعیت تسویه فروش": r["settlement_status"],
                            "گارانتی و انقضا": f"{r['warranty_company']} ({r['warranty_end']})".strip(" ()") or "-",
                            "شماره سریال فروخته‌شده": r["serial_number"] or "-",
                            "مشخصات فنی فروخته‌شده": r["specifications"] or "-",
                            "رنگ‌های فروخته‌شده": "، ".join(self._decode_colors(r["colors_json"])) or "-",
                        }
                        row_vals = [r["updated_at"] or r["sale_datetime"] or ""] + [str(val_map.get(col, "-")) for col in selected_cols]
                        rows_data.append(row_vals)
                    summary_text = f"گزارش سفارشی «{rep_type}» | تعداد ردیف‌ها: {len(rows_data)}"

        if rows_data:
            sort_mode = self.cb_rep_sort.currentData() or "activity_desc"
            rows_data.sort(
                key=_report_sort_key(rows_data, headers, sort_mode),
                reverse=sort_mode.endswith("_desc") or sort_mode == "activity_desc",
            )
            rows_data = [row[1:] for row in rows_data]
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
        if not self._require_license_feature("excel_report_export"):
            return
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
        rep_type = self.cb_rep_type.currentText()
        try:
            export_configs = json.loads(self.db.get_setting("report_excel_export_configs", "{}") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            export_configs = {}

        if rep_type in export_configs and export_configs[rep_type]:
            custom_columns = export_configs[rep_type]
            header_to_idx = {h: idx for idx, h in enumerate(headers)}
            valid_col_indices = [
                (col_name, header_to_idx[col_name])
                for col_name in custom_columns
                if col_name in header_to_idx
            ]
            if valid_col_indices:
                headers = [item[0] for item in valid_col_indices]
                selected_indices = [item[1] for item in valid_col_indices]
                rows = [[row[idx] for idx in selected_indices] for row in rows]

        export_table_to_excel(
            rep_type,
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
    # ۹. تب مدیریت کاربران (بند ۲ و ۱۱: رفع کامل باگ نمایش جدول کاربران)
    # =========================================================================
    def _init_tab_employees(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.selected_emp_id = None

        gb = QGroupBox("مدیریت کاربران، نقش‌ها، سطوح دسترسی و رمز ورود")
        grid = QGridLayout(gb)

        self.ed_emp_name = SmartLineEdit("")
        self.ed_emp_name.setPlaceholderText("نام و نام خانوادگی کاربر...")
        self.cb_emp_role = QComboBox()
        self.cb_emp_role.addItems(
            ["مدیر", "فروشنده", "مسئول خرید", "تکنسین فنی"]
        )
        self.ed_emp_phone = SmartLineEdit("")
        self.ed_emp_phone.setPlaceholderText("شماره تماس...")
        self.ed_emp_old_pass = QLineEdit()
        self.ed_emp_old_pass.setEchoMode(QLineEdit.Password)
        self.ed_emp_old_pass.setPlaceholderText("رمز عبور فعلی کاربر...")
        self.ed_emp_pass = QLineEdit()
        self.ed_emp_pass.setEchoMode(QLineEdit.Password)
        self.ed_emp_pass.setPlaceholderText("رمز عبور جدید کاربر...")
        self.cb_emp_perm = QComboBox()
        for access_level in self._get_access_levels():
            self.cb_emp_perm.addItem(access_level["name"], access_level["name"])
        self.chk_emp_active = QCheckBox("کاربر فعال است")
        self.chk_emp_active.setChecked(True)

        grid.addWidget(QLabel("نام کاربر:"), 0, 0)
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
        btn_add = QPushButton("➕ افزودن کاربر جدید")
        btn_add.clicked.connect(self._add_employee)
        btn_edit = QPushButton("✏️ ویرایش کاربر انتخابی")
        btn_edit.setObjectName("btnSuccess")
        btn_edit.clicked.connect(self._update_employee)
        btn_del = QPushButton("🗑️ حذف کاربر")
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
                "نام کاربر",
                "نقش",
                "تلفن تماس",
                "سطح دسترسی",
                "دارای رمز عبور",
                "وضعیت فعالیت",
                "تاریخ ایجاد",
                "تاریخ ویرایش",
                "آخرین ورود",
            ]
        )
        self.tbl_employees.itemSelectionChanged.connect(self._on_emp_selected)
        self._add_table_search(btn_row, self.tbl_employees, "employees", "🔍 جست‌وجو در کارکنان...")
        layout.addWidget(self.tbl_employees)

        self._add_scrollable_tab(tab, "👤 مدیریت کاربران")

    def _add_employee(self):
        name = self.ed_emp_name.text().strip()
        if not name:
            QMessageBox.warning(self, "خطا", "نام کاربر را وارد کنید.")
            return
        raw_pass = normalize_digits(self.ed_emp_pass.text().strip())
        if self.db.cfg.get("require_login_password", False) and self.chk_emp_active.isChecked() and not raw_pass:
            QMessageBox.warning(
                self, "رمز عبور لازم است",
                "تا زمانی که اجبار رمز عبور فعال است، کاربر فعال باید هنگام ثبت رمز تعیین کند."
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
            QMessageBox.critical(self, "خطا در ثبت کاربر", str(e))

    def _on_emp_selected(self):
        items = self.tbl_employees.selectedItems()
        if not items:
            return
        r = items[0].row()
        self.selected_emp_id = int(self.tbl_employees.item(r, 0).text())
        with self.db.get_connection() as conn:
            emp = conn.execute(
                "SELECT id, name, role, phone, is_active, permissions, password, created_at, updated_at FROM employees WHERE id=?", (self.selected_emp_id,)
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
                    "این کاربر فعال باید پیش از ذخیره اطلاعات، رمز عبور دریافت کند."
                )
                return

            # مورد ۴: اگر کاربر قصد تغییر رمز (یا ثبت رمز جدید برای کاربر دارای رمز) را دارد، رمز فعلی الزامی است
            if new_raw:
                if saved_hash:
                    if not old_raw:
                        QMessageBox.warning(
                            self,
                            "نیاز به رمز فعلی",
                            "برای تغییر رمز عبور، لطفاً ابتدا «رمز عبور فعلی» این کاربر را وارد کنید.",
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
        QMessageBox.information(self, "ذخیره شد", "اطلاعات کاربر بروزرسانی شد.")

    def _remove_employee_password(self):
        if not self.selected_emp_id:
            QMessageBox.warning(self, "انتخاب کاربر", "ابتدا کاربر موردنظر را انتخاب کنید.")
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
                QMessageBox.information(self, "بدون رمز", "برای این کاربر رمزی ثبت نشده است.")
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
        """مورد ۳: پنجره سه‌گزینه‌ای حذف کاربر"""
        if not self.selected_emp_id:
            QMessageBox.warning(self, "انتخاب کاربر", "ابتدا یک کاربر را از جدول انتخاب کنید.")
            return

        if self.active_employee and int(self.active_employee.get("id", -1)) == int(self.selected_emp_id):
            QMessageBox.warning(
                self, "کاربر فعال",
                "حساب کاربری فعال را نمی‌توان از همان نشست حذف کرد. ابتدا با حساب مدیریتی دیگری وارد شوید."
            )
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("حذف کاربر")
        msg.setText(
            "روش حذف کاربر را انتخاب کنید."
        )
        btn_cancel = msg.addButton("انصراف", QMessageBox.RejectRole)
        btn_keep_data = msg.addButton(
            "فقط حذف کاربر", QMessageBox.AcceptRole
        )
        btn_del_data = msg.addButton(
            "حذف کاربر و داده های مربوط به آن", QMessageBox.DestructiveRole
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
            QMessageBox.information(self, "حذف شد", "عملیات حذف کاربر با موفقیت انجام شد.")
        except Exception as e:
            QMessageBox.critical(self, "خطا در حذف", str(e))

    # =========================================================================
    # موتور پیکربندی داینامیک خروجی اکسل گزارش‌ها (openpyxl)
    # =========================================================================
    def _build_report_export_config_page(self) -> QWidget:
        page = QWidget()
        page.setLayoutDirection(Qt.RightToLeft)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(12, 12, 12, 12)
        page_layout.setSpacing(10)

        gb = QGroupBox("تنظیمات ستون‌ها و ترتیب خروجی اکسل گزارش‌ها")
        self.gb_report_export_cfg = gb
        self.report_export_page = page
        gb_layout = QVBoxLayout(gb)
        gb_layout.setContentsMargins(12, 12, 12, 12)
        gb_layout.setSpacing(10)

        hint = QLabel(
            "نوع گزارش موردنظر را انتخاب کنید. ستون‌های دلخواه را انتخاب کرده و با دکمه‌های «انتقال به بالا» و «انتقال به پایین» ترتیب نمایش آنها را در خروجی اکسل مشخص نمایید."
        )
        hint.setWordWrap(True)
        hint.setObjectName("settingsHint")
        gb_layout.addWidget(hint)

        # مدیریت گزارش‌های سفارشی (بند ۸)
        custom_rep_row = QHBoxLayout()
        custom_rep_row.setSpacing(8)
        lbl_custom_name = QLabel("نام گزارش سفارشی:")
        lbl_custom_name.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.ed_custom_report_name = QLineEdit()
        self.ed_custom_report_name.setPlaceholderText("نام گزارش دلخواه جدید یا نام جایگزین...")
        btn_add_custom_rep = QPushButton("➕ ایجاد گزارش جدید")
        btn_add_custom_rep.clicked.connect(self._add_custom_report)
        btn_rename_custom_rep = QPushButton("✏️ تغییر نام گزارش")
        btn_rename_custom_rep.setObjectName("btnSecondary")
        btn_rename_custom_rep.clicked.connect(self._rename_custom_report)
        btn_delete_custom_rep = QPushButton("🗑️ حذف گزارش")
        btn_delete_custom_rep.setObjectName("btnDanger")
        btn_delete_custom_rep.clicked.connect(self._delete_custom_report)

        custom_rep_row.addWidget(lbl_custom_name)
        custom_rep_row.addWidget(self.ed_custom_report_name, 1)
        custom_rep_row.addWidget(btn_add_custom_rep)
        custom_rep_row.addWidget(btn_rename_custom_rep)
        custom_rep_row.addWidget(btn_delete_custom_rep)
        gb_layout.addLayout(custom_rep_row)

        type_row = QHBoxLayout()
        type_row.setSpacing(8)
        lbl_type = QLabel("نوع گزارش:")
        lbl_type.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.cb_report_export_type = QComboBox()
        self.cb_report_export_type.setMinimumHeight(32)
        self.cb_report_export_type.addItem("تعریف گزارش جدید")
        for report_type in REPORT_AVAILABLE_COLUMNS.keys():
            self.cb_report_export_type.addItem(report_type)
        custom_defs = self._get_custom_report_definitions()
        for name in custom_defs.keys():
            self.cb_report_export_type.addItem(name)
        type_row.addWidget(lbl_type)
        type_row.addWidget(self.cb_report_export_type, 1)
        gb_layout.addLayout(type_row)

        cols_container = QHBoxLayout()
        cols_container.setSpacing(10)

        self.lst_report_export_columns = SmoothScrollListWidget()
        self.lst_report_export_columns.enable_row_toggle = True
        self.lst_report_export_columns.setMinimumHeight(240)
        self.lst_report_export_columns.setMaximumHeight(350)
        self.lst_report_export_columns.itemClicked.connect(self._on_report_export_col_clicked)
        cols_container.addWidget(self.lst_report_export_columns, 1)

        btn_box = QVBoxLayout()
        btn_box.setSpacing(8)
        btn_box.setAlignment(Qt.AlignTop)

        btn_up = QPushButton("⬆️ انتقال به بالا")
        btn_up.setObjectName("btnSecondary")
        btn_up.setMinimumHeight(32)
        btn_up.clicked.connect(self._move_report_export_col_up)

        btn_down = QPushButton("⬇️ انتقال به پایین")
        btn_down.setObjectName("btnSecondary")
        btn_down.setMinimumHeight(32)
        btn_down.clicked.connect(self._move_report_export_col_down)

        btn_select_all = QPushButton("انتخاب همه")
        btn_select_all.setMinimumHeight(32)
        btn_select_all.clicked.connect(lambda: self._set_all_report_export_cols(True))

        btn_deselect_all = QPushButton("لغو انتخاب همه")
        btn_deselect_all.setMinimumHeight(32)
        btn_deselect_all.clicked.connect(lambda: self._set_all_report_export_cols(False))

        btn_reset_default = QPushButton("بازنشانی به پیش‌فرض")
        btn_reset_default.setObjectName("btnDanger")
        btn_reset_default.setMinimumHeight(32)
        btn_reset_default.clicked.connect(self._reset_report_export_cols_default)

        btn_save_report_cfg = QPushButton("✏️ ویرایش لیست گزارش")
        btn_save_report_cfg.setObjectName("btnSuccess")
        btn_save_report_cfg.setMinimumHeight(36)
        btn_save_report_cfg.clicked.connect(self._save_report_export_config_ui)

        btn_box.addWidget(btn_up)
        btn_box.addWidget(btn_down)
        btn_box.addWidget(btn_select_all)
        btn_box.addWidget(btn_deselect_all)
        btn_box.addWidget(btn_reset_default)
        btn_box.addWidget(btn_save_report_cfg)
        btn_box.addStretch(1)

        cols_container.addLayout(btn_box)
        gb_layout.addLayout(cols_container)

        page_layout.addWidget(gb)
        page_layout.addStretch(1)

        self.cb_report_export_type.currentTextChanged.connect(self._load_report_export_columns_ui)
        self._load_report_export_columns_ui(self.cb_report_export_type.currentText())

        return page

    def _on_report_export_col_clicked(self, item):
        if item is not None:
            item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)

    def _get_custom_report_definitions(self):
        if getattr(self, "_custom_report_draft_definitions", None) is not None:
            return self._custom_report_draft_definitions
        try:
            return json.loads(self.db.get_setting("custom_report_definitions", "{}") or "{}")
        except Exception:
            return {}

    def _get_report_excel_export_configs(self):
        if getattr(self, "_report_export_draft_configs", None) is not None:
            return self._report_export_draft_configs
        try:
            return json.loads(self.db.get_setting("report_excel_export_configs", "{}") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def _save_custom_report_definitions(self, defs: dict):
        self._custom_report_draft_definitions = defs

    def _refresh_report_export_types_combo(self):
        current = self.cb_report_export_type.currentText()
        self.cb_report_export_type.blockSignals(True)
        self.cb_report_export_type.clear()
        self.cb_report_export_type.addItem("تعریف گزارش جدید")
        for report_type in REPORT_AVAILABLE_COLUMNS.keys():
            self.cb_report_export_type.addItem(report_type)
        custom_defs = self._get_custom_report_definitions()
        for name in custom_defs.keys():
            self.cb_report_export_type.addItem(name)
        if current and self.cb_report_export_type.findText(current) >= 0:
            self.cb_report_export_type.setCurrentText(current)
        else:
            self.cb_report_export_type.setCurrentIndex(0)
        self.cb_report_export_type.blockSignals(False)
        self._load_report_export_columns_ui(self.cb_report_export_type.currentText())
        self._sync_reports_tab_combo()

    def _add_custom_report(self):
        if not self._require_license_write_allowed():
            return
        if not self._require_license_feature("report_builder"):
            return
        name = self.ed_custom_report_name.text().strip()
        if not name:
            QMessageBox.warning(self, "نام گزارش", "لطفاً نام گزارش را وارد کنید.")
            return
        if name in REPORT_AVAILABLE_COLUMNS or name == "تعریف گزارش جدید":
            QMessageBox.warning(self, "نام تکراری", "این نام متعلق به یکی از گزارش‌های سیستمی است.")
            return
        custom_defs = self._get_custom_report_definitions()
        if name in custom_defs:
            QMessageBox.warning(self, "نام تکراری", "گزارشی با این نام قبلاً ایجاد شده است.")
            return
        selected_cols = []
        for i in range(self.lst_report_export_columns.count()):
            item = self.lst_report_export_columns.item(i)
            if item.checkState() == Qt.Checked:
                selected_cols.append(item.text())
        custom_defs[name] = selected_cols if selected_cols else list(ALL_SYSTEM_COLUMNS)
        self._save_custom_report_definitions(custom_defs)
        self.ed_custom_report_name.clear()
        self._refresh_report_export_types_combo()
        self.cb_report_export_type.setCurrentText(name)
        QMessageBox.information(
            self, "گزارش جدید",
            f"گزارش سفارشی «{name}» در پیش‌نویس ایجاد شد. برای ذخیره نهایی، دکمه «ذخیره تنظیمات» را بزنید."
        )

    def _rename_custom_report(self):
        if not self._require_license_write_allowed():
            return
        if not self._require_license_feature("report_builder"):
            return
        current_name = self.cb_report_export_type.currentText()
        if current_name in REPORT_AVAILABLE_COLUMNS or current_name == "تعریف گزارش جدید":
            QMessageBox.warning(self, "عدم امکان تغییر نام", "این مورد قابل تغییر نام نیست.")
            return
        new_name = self.ed_custom_report_name.text().strip()
        if not new_name:
            QMessageBox.warning(self, "نام گزارش", "لطفاً نام جدید گزارش را وارد کنید.")
            return
        if new_name == current_name:
            return
        if new_name in REPORT_AVAILABLE_COLUMNS or new_name == "تعریف گزارش جدید":
            QMessageBox.warning(self, "نام تکراری", "این نام متعلق به گزارش‌های سیستمی است.")
            return
        custom_defs = self._get_custom_report_definitions()
        if new_name in custom_defs:
            QMessageBox.warning(self, "نام تکراری", "گزارشی با این نام از قبل وجود دارد.")
            return
        custom_defs[new_name] = custom_defs.pop(current_name, list(ALL_SYSTEM_COLUMNS))
        self._save_custom_report_definitions(custom_defs)
        exp_cfgs = self._get_report_excel_export_configs()
        if current_name in exp_cfgs:
            exp_cfgs[new_name] = exp_cfgs.pop(current_name)
            self._report_export_draft_configs = exp_cfgs
        self.ed_custom_report_name.clear()
        self._refresh_report_export_types_combo()
        self.cb_report_export_type.setCurrentText(new_name)
        QMessageBox.information(self, "تغییر نام", f"نام گزارش به «{new_name}» تغییر یافت (در انتظار ذخیره تنظیمات).")

    def _delete_custom_report(self):
        if not self._require_license_write_allowed():
            return
        if not self._require_license_feature("report_builder"):
            return
        current_name = self.cb_report_export_type.currentText()
        if current_name in REPORT_AVAILABLE_COLUMNS or current_name == "تعریف گزارش جدید":
            QMessageBox.warning(self, "عدم امکان حذف", "این مورد قابل حذف نیست.")
            return
        if _ask_yes_no(self, "حذف گزارش", f"آیا از حذف گزارش سفارشی «{current_name}» اطمینان دارید؟") is True:
            custom_defs = self._get_custom_report_definitions()
            custom_defs.pop(current_name, None)
            self._save_custom_report_definitions(custom_defs)
            exp_cfgs = self._get_report_excel_export_configs()
            exp_cfgs.pop(current_name, None)
            self._report_export_draft_configs = exp_cfgs
            self.ed_custom_report_name.clear()
            self._refresh_report_export_types_combo()
            QMessageBox.information(self, "حذف گزارش", f"گزارش «{current_name}» حذف شد (در انتظار ذخیره تنظیمات).")

    def _load_report_export_columns_ui(self, report_type=None):
        if not report_type:
            report_type = self.cb_report_export_type.currentText()
        if not report_type:
            return

        if report_type == "تعریف گزارش جدید":
            self.lst_report_export_columns.clear()
            for col in ALL_SYSTEM_COLUMNS:
                item = QListWidgetItem(col)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                self.lst_report_export_columns.addItem(item)
            return

        custom_defs = self._get_custom_report_definitions()
        if report_type in REPORT_AVAILABLE_COLUMNS:
            all_columns = list(REPORT_AVAILABLE_COLUMNS.get(report_type, []))
        else:
            all_columns = list(custom_defs.get(report_type, ALL_SYSTEM_COLUMNS))
            added_set = set(all_columns)
            for c in ALL_SYSTEM_COLUMNS:
                if c not in added_set:
                    all_columns.append(c)

        export_configs = self._get_report_excel_export_configs()

        self.lst_report_export_columns.clear()
        saved_enabled = None
        if report_type in export_configs and isinstance(export_configs[report_type], list):
            saved_enabled = export_configs[report_type]
        elif report_type in custom_defs and isinstance(custom_defs[report_type], list):
            saved_enabled = custom_defs[report_type]

        if saved_enabled:
            added = set()
            for col in saved_enabled:
                if col in all_columns:
                    item = QListWidgetItem(col)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked)
                    self.lst_report_export_columns.addItem(item)
                    added.add(col)
            for col in all_columns:
                if col not in added:
                    item = QListWidgetItem(col)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Unchecked)
                    self.lst_report_export_columns.addItem(item)
        else:
            for col in all_columns:
                item = QListWidgetItem(col)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                self.lst_report_export_columns.addItem(item)

    def _move_report_export_col_up(self):
        row = self.lst_report_export_columns.currentRow()
        if row > 0:
            item = self.lst_report_export_columns.takeItem(row)
            self.lst_report_export_columns.insertItem(row - 1, item)
            self.lst_report_export_columns.setCurrentRow(row - 1)
            self._save_report_export_config_internal()
            if hasattr(self, "_update_report_live"):
                self._update_report_live()

    def _move_report_export_col_down(self):
        row = self.lst_report_export_columns.currentRow()
        if 0 <= row < self.lst_report_export_columns.count() - 1:
            item = self.lst_report_export_columns.takeItem(row)
            self.lst_report_export_columns.insertItem(row + 1, item)
            self.lst_report_export_columns.setCurrentRow(row + 1)
            self._save_report_export_config_internal()
            if hasattr(self, "_update_report_live"):
                self._update_report_live()

    def _move_inventory_export_col_up(self):
        if not hasattr(self, "lst_inventory_export_columns"):
            return
        row = self.lst_inventory_export_columns.currentRow()
        if row > 0:
            item = self.lst_inventory_export_columns.takeItem(row)
            self.lst_inventory_export_columns.insertItem(row - 1, item)
            self.lst_inventory_export_columns.setCurrentRow(row - 1)

    def _move_inventory_export_col_down(self):
        if not hasattr(self, "lst_inventory_export_columns"):
            return
        row = self.lst_inventory_export_columns.currentRow()
        if 0 <= row < self.lst_inventory_export_columns.count() - 1:
            item = self.lst_inventory_export_columns.takeItem(row)
            self.lst_inventory_export_columns.insertItem(row + 1, item)
            self.lst_inventory_export_columns.setCurrentRow(row + 1)

    def _set_all_inventory_export_cols(self, checked: bool):
        if not hasattr(self, "lst_inventory_export_columns"):
            return
        st = Qt.Checked if checked else Qt.Unchecked
        for i in range(self.lst_inventory_export_columns.count()):
            self.lst_inventory_export_columns.item(i).setCheckState(st)

    def _reset_inventory_export_cols_default(self):
        default_keys = {"code", "batch_code", "category", "subcategory", "brand_model", "specs"}
        self._populate_inventory_export_columns_ui(selected_keys=default_keys)

    def _populate_inventory_export_columns_ui(self, items_or_keys=None, selected_keys=None):
        if not hasattr(self, "lst_inventory_export_columns"):
            return
        self.lst_inventory_export_columns.clear()

        all_cols = INVENTORY_EXPORT_AVAILABLE_COLUMNS
        col_map = dict(all_cols)

        if items_or_keys is not None and isinstance(items_or_keys, list) and items_or_keys and isinstance(items_or_keys[0], tuple):
            added_keys = set()
            for key, text, is_checked in items_or_keys:
                if key in col_map:
                    it = QListWidgetItem(text or col_map[key])
                    it.setData(Qt.UserRole, key)
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
                    it.setCheckState(Qt.Checked if is_checked else Qt.Unchecked)
                    self.lst_inventory_export_columns.addItem(it)
                    added_keys.add(key)
            for key, text in all_cols:
                if key not in added_keys:
                    it = QListWidgetItem(text)
                    it.setData(Qt.UserRole, key)
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
                    it.setCheckState(Qt.Unchecked)
                    self.lst_inventory_export_columns.addItem(it)
            return

        if items_or_keys is None:
            raw = self.db.get_setting("colleague_inventory_export_columns", "[]")
            try:
                saved_keys = json.loads(raw or "[]")
            except Exception:
                saved_keys = []
            if not saved_keys:
                saved_keys = ["code", "batch_code", "category", "subcategory", "brand_model", "specs"]
        else:
            saved_keys = list(items_or_keys)

        active_checked = set(selected_keys) if selected_keys is not None else set(saved_keys)

        added_keys = set()
        for key in saved_keys:
            if key in col_map:
                it = QListWidgetItem(col_map[key])
                it.setData(Qt.UserRole, key)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
                it.setCheckState(Qt.Checked if key in active_checked else Qt.Unchecked)
                self.lst_inventory_export_columns.addItem(it)
                added_keys.add(key)

        for key, text in all_cols:
            if key not in added_keys:
                it = QListWidgetItem(text)
                it.setData(Qt.UserRole, key)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
                it.setCheckState(Qt.Checked if key in active_checked else Qt.Unchecked)
                self.lst_inventory_export_columns.addItem(it)

    def _get_selected_inventory_export_columns(self) -> list:
        if not hasattr(self, "lst_inventory_export_columns"):
            raw = self.db.get_setting("colleague_inventory_export_columns", "[]")
            try:
                return json.loads(raw or "[]")
            except Exception:
                return ["code", "batch_code", "category", "subcategory", "brand_model", "specs"]
        result = []
        for i in range(self.lst_inventory_export_columns.count()):
            it = self.lst_inventory_export_columns.item(i)
            if it.checkState() == Qt.Checked:
                result.append(it.data(Qt.UserRole))
        return result

    def _set_all_report_export_cols(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for i in range(self.lst_report_export_columns.count()):
            self.lst_report_export_columns.item(i).setCheckState(state)

    def _reset_report_export_cols_default(self):
        report_type = self.cb_report_export_type.currentText()
        if report_type == "تعریف گزارش جدید":
            self._load_report_export_columns_ui(report_type)
            return
        exp_cfgs = self._get_report_excel_export_configs()
        if report_type in exp_cfgs:
            exp_cfgs.pop(report_type, None)
            self._report_export_draft_configs = exp_cfgs
        custom_defs = self._get_custom_report_definitions()
        if report_type in custom_defs:
            custom_defs[report_type] = list(ALL_SYSTEM_COLUMNS)
            self._save_custom_report_definitions(custom_defs)
        self._load_report_export_columns_ui(report_type)
        QMessageBox.information(
            self, "بازنشانی تنظیمات", f"تنظیمات خروجی اکسل برای «{report_type}» به حالت پیش‌فرض بازگشت (در انتظار ذخیره تنظیمات)."
        )

    def _save_report_export_config_internal(self):
        if not hasattr(self, "cb_report_export_type") or not hasattr(self, "lst_report_export_columns"):
            return
        report_type = self.cb_report_export_type.currentText()
        if not report_type or report_type == "تعریف گزارش جدید":
            return
        ordered_enabled = []
        for i in range(self.lst_report_export_columns.count()):
            item = self.lst_report_export_columns.item(i)
            if item.checkState() == Qt.Checked:
                ordered_enabled.append(item.text())
        export_configs = dict(self._get_report_excel_export_configs())
        if ordered_enabled:
            export_configs[report_type] = ordered_enabled
        else:
            export_configs.pop(report_type, None)
        self._report_export_draft_configs = export_configs
        custom_defs = dict(self._get_custom_report_definitions())
        if report_type in custom_defs:
            custom_defs[report_type] = ordered_enabled
            self._save_custom_report_definitions(custom_defs)

    def _commit_report_export_settings(self):
        self._save_report_export_config_internal()
        if getattr(self, "_report_export_draft_configs", None) is not None:
            self.db.set_setting("report_excel_export_configs", json.dumps(self._report_export_draft_configs, ensure_ascii=False))
        if getattr(self, "_custom_report_draft_definitions", None) is not None:
            self.db.set_setting("custom_report_definitions", json.dumps(self._custom_report_draft_definitions, ensure_ascii=False))

    def _save_report_export_config_ui(self):
        if not self._require_license_write_allowed():
            return
        if not self._require_license_feature("report_builder"):
            return
        report_type = self.cb_report_export_type.currentText()
        if report_type == "تعریف گزارش جدید":
            QMessageBox.information(
                self, "انتخاب گزارش",
                "لطفاً ابتدا نام گزارش دلخواه را وارد کرده و دکمهٔ «ایجاد گزارش جدید» را بزنید."
            )
            return
        ordered_enabled = []
        for i in range(self.lst_report_export_columns.count()):
            item = self.lst_report_export_columns.item(i)
            if item.checkState() == Qt.Checked:
                ordered_enabled.append(item.text())
        if not ordered_enabled:
            QMessageBox.warning(
                self, "خطا در تنظیم ستون‌ها", "دست‌کم یک ستون باید برای خروجی اکسل انتخاب شود."
            )
            return
        self._commit_report_export_settings()
        if hasattr(self, "_update_report_live"):
            self._update_report_live()
        QMessageBox.information(
            self, "ویرایش لیست گزارش", f"تنظیمات ستون‌ها و ترتیب خروجی اکسل برای «{report_type}» ذخیره شد."
        )

    # =========================================================================
    # ۱۰. تب تنظیمات و پشتیبان‌گیری
    # =========================================================================
    def _init_tab_settings(self):
        def labeled_field(caption, field_widget):
            wrapper = QWidget()
            wrapper.setLayoutDirection(Qt.RightToLeft)
            field_layout = QVBoxLayout(wrapper)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(3)
            caption_label = QLabel(caption)
            caption_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            caption_label.setFixedHeight(22)
            caption_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            field_layout.addWidget(caption_label)
            field_layout.addWidget(field_widget)
            field_layout.setAlignment(Qt.AlignTop)
            wrapper.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
            return wrapper

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignTop)

        self.lbl_app_version = QLabel(f"دقیق | نسخه برنامه: {APP_VERSION}")
        self.lbl_app_version.setObjectName("appVersion")
        self.lbl_app_version.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_app_version)

        lic_btn_row = QHBoxLayout()
        btn_license_mgmt = QPushButton("📜 مدیریت و وضعیت لایسنس")
        btn_license_mgmt.setStyleSheet(
            "background-color: #0f766e; color: white; padding: 6px 14px; font-weight: bold; border-radius: 6px;"
        )
        btn_license_mgmt.setToolTip(
            "مشاهده مشخصات لایسنس فعال، کپی شناسه سخت‌افزاری دستگاه، و وارد کردن لایسنس جدید"
        )
        btn_license_mgmt.clicked.connect(self._open_license_dialog)
        lic_btn_row.addWidget(btn_license_mgmt)

        btn_export_req = QPushButton("💾 دریافت فایل مشخصات سیستم (.daqreq)")
        btn_export_req.setStyleSheet(
            "background-color: #0d9488; color: white; padding: 6px 14px; font-weight: bold; border-radius: 6px;"
        )
        btn_export_req.setToolTip(
            "ایجاد و ذخیره فایل مشخصات سخت‌افزاری (.daqreq) برای ارسال به پشتیبانی"
        )
        btn_export_req.clicked.connect(self._export_device_request_from_settings)
        lic_btn_row.addWidget(btn_export_req)
        layout.addLayout(lic_btn_row)

        gb_security = QGroupBox("امنیت و ورود کاربران")
        self.gb_security = gb_security
        security_layout = QVBoxLayout(gb_security)
        security_layout.setContentsMargins(15, 15, 15, 15)
        security_layout.setSpacing(12)

        gb_login_policy = QGroupBox("سیاست ورود و احراز هویت کارکنان")
        login_policy_layout = QVBoxLayout(gb_login_policy)
        login_policy_layout.setContentsMargins(15, 15, 15, 15)
        login_policy_layout.setSpacing(8)
        self.chk_req_pass = QCheckBox(
            "اجبار ورود با رمز عبور برای تمام کارکنان فعال"
        )
        self.chk_req_pass.toggled.connect(self._confirm_password_policy_change)
        self.chk_req_pass.setToolTip(
            "در حالت فعال، تمام کارکنان فعال باید رمز عبور اختصاصی داشته باشند و هنگام ورود آن را وارد کنند."
        )
        security_hint = QLabel(
            "با فعال‌سازی این گزینه، ورود هر کاربر به برنامه تنها پس از وارد کردن رمز عبور شخصی مجاز خواهد بود. "
            "لطفاً پیش از فعال‌سازی، برای تمامی کارکنان فعال رمز عبور تعیین نمایید."
        )
        security_hint.setWordWrap(True)
        security_hint.setObjectName("settingsHint")
        login_policy_layout.addWidget(self.chk_req_pass)
        login_policy_layout.addWidget(security_hint)
        security_layout.addWidget(gb_login_policy)

        # مدیریت رمز عبور پایگاه داده با استاندارد بین‌المللی SQLCipher AES-256
        gb_db_pwd = QGroupBox("مدیریت رمز عبور و رمزنگاری پایگاه داده (SQLCipher AES-256)")
        db_pwd_layout = QVBoxLayout(gb_db_pwd)
        db_pwd_layout.setContentsMargins(15, 15, 15, 15)
        db_pwd_layout.setSpacing(12)

        self.lbl_db_pwd_status = QLabel()
        self.lbl_db_pwd_status.setWordWrap(False)
        self.lbl_db_pwd_status.setStyleSheet("font-weight: bold; font-size: 11pt;")
        self.lbl_db_pwd_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        db_pwd_btn_row = QHBoxLayout()
        db_pwd_btn_row.setSpacing(10)
        self.btn_set_db_pwd = QPushButton("🔑 تعیین رمز عبور دیتابیس")
        self.btn_set_db_pwd.setMinimumHeight(36)
        self.btn_set_db_pwd.setMinimumWidth(160)
        self.btn_set_db_pwd.clicked.connect(self._on_set_db_password_clicked)

        self.btn_change_db_pwd = QPushButton("✏️ تغییر رمز عبور")
        self.btn_change_db_pwd.setObjectName("btnSecondary")
        self.btn_change_db_pwd.setMinimumHeight(36)
        self.btn_change_db_pwd.setMinimumWidth(140)
        self.btn_change_db_pwd.clicked.connect(self._on_change_db_password_clicked)

        self.btn_remove_db_pwd = QPushButton("🔓 حذف رمز عبور")
        self.btn_remove_db_pwd.setObjectName("btnDanger")
        self.btn_remove_db_pwd.setMinimumHeight(36)
        self.btn_remove_db_pwd.setMinimumWidth(140)
        self.btn_remove_db_pwd.clicked.connect(self._on_remove_db_password_clicked)

        db_pwd_btn_row.addStretch()
        db_pwd_btn_row.addWidget(self.btn_set_db_pwd)
        db_pwd_btn_row.addWidget(self.btn_change_db_pwd)
        db_pwd_btn_row.addWidget(self.btn_remove_db_pwd)
        db_pwd_btn_row.addStretch()

        self.chk_db_req_startup_pass = QCheckBox("درخواست رمز دیتابیس هنگام ورود به برنامه")
        self.chk_db_req_startup_pass.toggled.connect(self._on_db_startup_password_toggled)
        self.chk_db_req_startup_pass.setToolTip(
            "در صورت فعال بودن، در هر بار اجرای برنامه، قبل از دسترسی به اطلاعات رمز دیتابیس درخواست می‌شود."
        )

        db_pwd_layout.addWidget(self.lbl_db_pwd_status)
        db_pwd_layout.addLayout(db_pwd_btn_row)
        db_pwd_layout.addWidget(self.chk_db_req_startup_pass)
        security_layout.addWidget(gb_db_pwd)

        gb_security.setTitle("")
        layout.addWidget(CollapsibleSection("امنیت و ورود کاربران", gb_security))

        gb_access_levels = QGroupBox("مدیریت سطوح دسترسی")
        self.gb_access_levels = gb_access_levels
        access_layout = QGridLayout(gb_access_levels)
        self.cb_cfg_access_level = QComboBox()
        self.ed_cfg_access_level = SmartLineEdit()
        self.ed_cfg_access_level.setPlaceholderText("نام سطح دسترسی جدید یا نام جایگزین...")
        self.cb_cfg_access_policy = QComboBox()
        for access_level in DEFAULT_ACCESS_LEVELS:
            self.cb_cfg_access_policy.addItem(
                access_level["name"], access_level["policy"]
            )
        access_layout.addWidget(QLabel("سطح:"), 0, 0)
        access_layout.addWidget(self.cb_cfg_access_level, 0, 1)
        access_layout.addWidget(QLabel("نام سطح دسترسی:"), 1, 0)
        access_layout.addWidget(self.ed_cfg_access_level, 1, 1)
        access_layout.addWidget(QLabel("مجوزها:"), 2, 0)
        access_layout.addWidget(self.cb_cfg_access_policy, 2, 1)

        permissions_scroll = SmoothScrollArea()
        permissions_scroll.setMaximumHeight(360)
        permissions_container = QWidget()
        permissions_grid = QGridLayout(permissions_container)
        self.access_permission_checks = {}
        for group_index, (group_title, module, actions) in enumerate(PERMISSION_GROUPS):
            group = QGroupBox(group_title)
            group_layout = QGridLayout(group)
            for action_index, (action, label_text) in enumerate(actions):
                key = f"{module}.{action}"
                checkbox = QCheckBox(label_text)
                self.access_permission_checks[key] = checkbox
                group_layout.addWidget(checkbox, action_index // 3, action_index % 3)
            permissions_grid.addWidget(group, group_index // 2, group_index % 2)
        permissions_scroll.setWidget(permissions_container)
        permissions_scroll.setWidgetResizable(True)
        access_layout.addWidget(permissions_scroll, 4, 0, 1, 2)

        scope_group = QGroupBox("دامنه مشاهده اطلاعات کاربران")
        scope_layout = QGridLayout(scope_group)
        self.cb_cfg_data_scope_mode = QComboBox()
        self.cb_cfg_data_scope_mode.addItem("همه کاربران (دسترسی نامحدود)", "all")
        self.cb_cfg_data_scope_mode.addItem("فقط اطلاعات خود کاربر", "self")
        self.cb_cfg_data_scope_mode.addItem("بر اساس سطوح دسترسی منتخب", "access_levels")
        self.cb_cfg_data_scope_mode.addItem("بر اساس کاربران منتخب", "users")
        self.lst_cfg_scope_levels = SmoothScrollListWidget()
        self.lst_cfg_scope_levels.setMaximumHeight(120)
        self.lst_cfg_scope_users = SmoothScrollListWidget()
        self.lst_cfg_scope_users.setMaximumHeight(120)
        self.scope_levels_container = QWidget()
        scope_levels_layout = QVBoxLayout(self.scope_levels_container)
        scope_levels_layout.setContentsMargins(0, 0, 0, 0)
        scope_levels_layout.addWidget(QLabel("سطوح دسترسی مجاز:"))
        scope_levels_layout.addWidget(self.lst_cfg_scope_levels)
        self.scope_users_container = QWidget()
        scope_users_layout = QVBoxLayout(self.scope_users_container)
        scope_users_layout.setContentsMargins(0, 0, 0, 0)
        scope_users_layout.addWidget(QLabel("کاربران مجاز:"))
        scope_users_layout.addWidget(self.lst_cfg_scope_users)
        scope_layout.addWidget(QLabel("نوع دامنه:"), 0, 0)
        scope_layout.addWidget(self.cb_cfg_data_scope_mode, 0, 1)
        scope_layout.addWidget(self.scope_levels_container, 1, 0, 1, 2)
        scope_layout.addWidget(self.scope_users_container, 2, 0, 1, 2)
        access_layout.addWidget(scope_group, 5, 0, 1, 2)
        self.cb_cfg_data_scope_mode.currentIndexChanged.connect(
            self._on_data_scope_mode_changed
        )
        self._on_data_scope_mode_changed()
        self.cb_cfg_access_policy.currentIndexChanged.connect(
            self._on_permission_preset_changed
        )
        access_buttons = QHBoxLayout()
        btn_add_access = QPushButton("افزودن سطح")
        btn_add_access.clicked.connect(self._add_access_level)
        btn_edit_access = QPushButton("ویرایش سطح")
        btn_edit_access.setObjectName("btnSecondary")
        btn_edit_access.clicked.connect(self._update_access_level)
        btn_delete_access = QPushButton("حذف سطح")
        btn_delete_access.setObjectName("btnDanger")
        btn_delete_access.clicked.connect(self._delete_access_level)
        access_buttons.addWidget(btn_add_access)
        access_buttons.addWidget(btn_edit_access)
        access_buttons.addWidget(btn_delete_access)
        access_layout.addLayout(access_buttons, 6, 0, 1, 2)
        self.cb_cfg_access_level.currentIndexChanged.connect(
            self._on_access_level_selected
        )
        self._refresh_access_level_settings_combo()

        gb_gen = QGroupBox("تنظیمات عمومی فروش و نمایش")
        self.gb_gen = gb_gen
        f_gen = QFormLayout(gb_gen)
        f_gen.setContentsMargins(12, 12, 12, 10)
        f_gen.setHorizontalSpacing(14)
        f_gen.setVerticalSpacing(8)

        self.sp_set_profit = QSpinBox()
        self.sp_set_profit.setRange(0, 300)
        self.sp_default_min_inventory = QSpinBox()
        self.sp_default_min_inventory.setRange(0, 1000)
        self.sp_default_min_inventory.setValue(int(self.db.cfg.get("default_min_inventory", 1)))
        self.sp_default_min_inventory.setToolTip("حداقل موجودی پیش‌فرض هنگام ثبت کالاهای جدید در سیستم")
        self.cb_zero_count = QComboBox()
        self.cb_zero_count.addItem("بدون صفر اضافی (۰)", "0")
        self.cb_zero_count.addItem("افزودن ۱ صفر (×۱۰)", "1")
        self.cb_zero_count.addItem("افزودن ۲ صفر (×۱۰۰)", "2")
        self.cb_zero_count.addItem("افزودن ۳ صفر (×۱٬۰۰۰)", "3")
        self.cb_zero_count.addItem("افزودن ۴ صفر (×۱۰٬۰۰۰)", "4")
        persian_digits = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
        for zeros in (5, 6, 7, 8, 9, 10, 11, 12):
            label = f"افزودن {zeros} صفر (×{10 ** zeros:,})".translate(persian_digits)
            self.cb_zero_count.addItem(label, str(zeros))

        self.cb_win_mode = QComboBox()
        self.cb_win_mode.addItem("تمام‌صفحه", "1")
        self.cb_win_mode.addItem("پنجره معمولی", "0")
        self.ed_shop_name = SmartLineEdit(preserve_persian_digits=True)
        self.ed_shop_name.setPlaceholderText("نام فروشگاه را وارد کنید...")
        self.ed_shop_name.setAlignment(Qt.AlignRight)
        self.ed_shop_name.setLayoutDirection(Qt.RightToLeft)

        self.cb_calendar_format = QComboBox()
        self.cb_calendar_format.addItem("شمسی", "jalali")
        self.cb_calendar_format.addItem("قمری", "hijri")
        self.cb_calendar_format.addItem("میلادی", "gregorian")

        self.cb_time_format = QComboBox()
        self.cb_time_format.addItem("۲۴ ساعته", "24h")
        self.cb_time_format.addItem("۱۲ ساعته (AM / PM)", "12h")

        f_gen.addRow("درصد سود پیش‌فرض فروشگاه (%):", self.sp_set_profit)
        f_gen.addRow("حداقل موجودی پیش‌فرض کالاها:", self.sp_default_min_inventory)
        f_gen.addRow("تعداد صفرهای اضافی قیمت:", self.cb_zero_count)
        f_gen.addRow("حالت باز شدن پنجره:", self.cb_win_mode)
        f_gen.addRow("نام فروشگاه:", self.ed_shop_name)
        f_gen.addRow("قالب تقویم:", self.cb_calendar_format)
        f_gen.addRow("قالب ساعت:", self.cb_time_format)
        gb_gen.setTitle("")
        layout.addWidget(CollapsibleSection("تنظیمات عمومی فروش و نمایش", gb_gen))

        # Per-database product taxonomy and catalog customization.
        gb_catalog = QGroupBox("")
        catalog_layout = QVBoxLayout(gb_catalog)
        self.catalog_tabs = QTabWidget()
        products_page = QWidget()

        gb_categories = QGroupBox("دسته‌بندی‌های اصلی")
        self.gb_categories = gb_categories
        categories_layout = QVBoxLayout(gb_categories)
        categories_layout.setContentsMargins(10, 10, 10, 10)
        categories_layout.setSpacing(8)
        self.cb_cfg_category = QComboBox()
        self.ed_cfg_category = SmartLineEdit()
        self.ed_cfg_category.setPlaceholderText("نام فارسی دسته‌بندی اصلی را وارد کنید...")
        self.ed_cfg_category.textChanged.connect(
            lambda _: getattr(self, "_catalog_settings_state", None) and self._catalog_settings_state.capture_from_window(self)
        )
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
        lbl_category_current = QLabel("دسته‌بندی اصلی:")
        lbl_category_current.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lbl_category_new = QLabel("نام جدید یا نام جایگزین:")
        lbl_category_new.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        categories_layout.addWidget(labeled_field("دسته‌بندی اصلی:", self.cb_cfg_category))
        categories_layout.addWidget(labeled_field("نام جدید یا نام جایگزین:", self.ed_cfg_category))
        categories_layout.addLayout(cat_btn_row)

        gb_subcategories = QGroupBox("زیرمجموعه‌های دستهٔ انتخاب‌شده")
        self.gb_subcategories = gb_subcategories
        sub_layout = QVBoxLayout(gb_subcategories)
        sub_layout.setContentsMargins(10, 10, 10, 10)
        sub_layout.setSpacing(8)
        self.lst_cfg_subcategories = SmoothScrollListWidget()
        self.lst_cfg_subcategories.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.lst_cfg_subcategories.verticalScrollBar().setSingleStep(18)
        self.lst_cfg_subcategories.setMinimumHeight(174)
        self.lst_cfg_subcategories.setMaximumHeight(234)
        self.ed_cfg_subcategory = SmartLineEdit()
        self.ed_cfg_subcategory.setPlaceholderText("نام زیرمجموعه را وارد کنید؛ مثلاً صفحه‌نمایش یا پردازنده...")
        self.ed_cfg_subcategory.textChanged.connect(
            lambda _: getattr(self, "_catalog_settings_state", None) and self._catalog_settings_state.capture_from_window(self)
        )
        sub_btn_row = QHBoxLayout()
        btn_add_sub = QPushButton("افزودن")
        btn_add_sub.setProperty("catalogAction", "addSubcategory")
        btn_add_sub.clicked.connect(self._add_catalog_subcategory)
        btn_rename_sub = QPushButton("تغییر نام")
        btn_rename_sub.setObjectName("btnSecondary")
        btn_rename_sub.setProperty("catalogAction", "renameSubcategory")
        btn_rename_sub.clicked.connect(self._rename_catalog_subcategory)
        btn_delete_sub = QPushButton("حذف")
        btn_delete_sub.setObjectName("btnDanger")
        btn_delete_sub.setProperty("catalogAction", "deleteSubcategory")
        btn_delete_sub.clicked.connect(self._delete_catalog_subcategory)
        sub_btn_row.addWidget(btn_add_sub)
        sub_btn_row.addWidget(btn_rename_sub)
        sub_btn_row.addWidget(btn_delete_sub)
        sub_layout.addWidget(CollapsibleSection("فهرست زیرمجموعه‌ها", self.lst_cfg_subcategories))
        sub_layout.addWidget(labeled_field("نام زیرمجموعه:", self.ed_cfg_subcategory))
        self.ed_subcategory_caption = QLineEdit()
        self.ed_subcategory_caption.setPlaceholderText("عنوان دلخواه؛ مانند نوع دستگاه")
        subcaption_editor = QWidget()
        subcaption_row = QHBoxLayout(subcaption_editor)
        subcaption_row.setContentsMargins(0, 0, 0, 0)
        subcaption_row.setSpacing(8)
        subcaption_row.addWidget(self.ed_subcategory_caption, 1)
        sub_layout.addWidget(
            labeled_field("عنوان فیلد زیرمجموعه:", subcaption_editor)
        )
        sub_layout.addLayout(sub_btn_row)

        gb_attributes = QGroupBox("مشخصات فنی سفارشی")
        self.gb_attributes = gb_attributes
        attr_layout = QVBoxLayout(gb_attributes)
        gb_attributes.setLayoutDirection(Qt.RightToLeft)
        attr_layout.setContentsMargins(12, 12, 12, 12)
        attr_layout.setSpacing(9)
        self.lst_cfg_attributes = SmoothScrollListWidget()
        self.lst_cfg_attributes.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.lst_cfg_attributes.verticalScrollBar().setSingleStep(18)
        self.lst_cfg_attributes.setMinimumHeight(192)
        self.lst_cfg_attributes.setMaximumHeight(252)
        self.lst_cfg_attributes.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed
        )
        self.ed_cfg_attribute_name = SmartLineEdit()
        self.ed_cfg_attribute_name.setMinimumHeight(32)
        self.ed_cfg_attribute_name.setPlaceholderText(
            "نام فارسی ویژگی؛ مثلاً پردازنده، ظرفیت رم یا نوع پنل"
        )
        self.ed_cfg_attribute_name.textChanged.connect(
            lambda _: getattr(self, "_catalog_settings_state", None) and self._catalog_settings_state.capture_from_window(self)
        )
        self.ed_cfg_attribute_label = SmartLineEdit()
        self.ed_cfg_attribute_label.setMinimumHeight(32)
        self.ed_cfg_attribute_label.setPlaceholderText(
            "عنوان انگلیسی برای نمایش؛ مثلاً CPU یا RAM. در صورت نیاز می‌توانید خالی بگذارید."
        )
        self.lbl_cfg_attribute_help = QLabel(
            "راهنما: نام ویژگی را فارسی بنویسید و در عنوان، معادل انگلیسی آن را وارد کنید؛ "
            "مثلاً «پردازنده» با عنوان «CPU». برای کنار هم نمایش‌دادن مقدار دو ویژگی، "
            "نام ویژگی اصلی را با علامت @ بنویسید؛ مثلاً «@ظرفیت رم». "
            "نمونه خروجی: RAM: 8GB DDR4"
        )
        self.lbl_cfg_attribute_help.setWordWrap(True)
        self.lbl_cfg_attribute_help.setObjectName("settingsHint")
        self.lbl_cfg_attribute_help.setMinimumHeight(38)
        self.attr_values_widget = DynamicAttributeValuesWidget()
        self.ed_cfg_attribute_values = self.attr_values_widget
        self.attr_values_widget.valuesChanged.connect(
            lambda: getattr(self, "_catalog_settings_state", None) and self._catalog_settings_state.capture_from_window(self)
        )
        self.cb_cfg_attribute_subcategory = QComboBox()
        self.cb_cfg_attribute_subcategory.addItem("همهٔ زیرمجموعه‌ها", "")
        self.cb_cfg_attribute_subcategory.setMinimumHeight(32)
        lbl_scope = QLabel("دامنه زیرمجموعه:")
        lbl_scope.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lbl_scope.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        attr_layout.addWidget(
            labeled_field("دامنه زیرمجموعه:", self.cb_cfg_attribute_subcategory)
        )

        self.lst_cfg_attributes.currentItemChanged.connect(
            self._on_catalog_attribute_selected
        )
        attr_btn_row = QHBoxLayout()
        attr_btn_row.setSpacing(8)
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

        lbl_attribute_list = QLabel("فهرست ویژگی‌های تعریف‌شده:")
        lbl_attribute_list.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lbl_attribute_list.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        attr_layout.addWidget(
            CollapsibleSection("فهرست ویژگی‌های تعریف‌شده", self.lst_cfg_attributes)
        )

        lbl_attribute_name = QLabel("نام ویژگی (فارسی):")
        lbl_attribute_name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lbl_attribute_title = QLabel("عنوان نمایشی (انگلیسی، اختیاری):")
        lbl_attribute_title.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lbl_attribute_values = QLabel("مقادیر پیشنهادی:")
        lbl_attribute_values.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        for label_widget in (
            lbl_attribute_name, lbl_attribute_title, lbl_attribute_values,
        ):
            label_widget.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        attribute_grid = QGridLayout()
        attribute_grid.setContentsMargins(0, 0, 0, 0)
        attribute_grid.setHorizontalSpacing(10)
        attribute_grid.setVerticalSpacing(8)
        attribute_grid.setColumnStretch(1, 1)
        attribute_grid.setColumnStretch(3, 1)
        attribute_grid.addWidget(
            labeled_field("نام ویژگی (فارسی):", self.ed_cfg_attribute_name), 0, 0, 1, 2
        )
        attribute_grid.addWidget(
            labeled_field("عنوان نمایشی (انگلیسی، اختیاری):", self.ed_cfg_attribute_label),
            0, 2, 1, 2,
        )
        attribute_grid.addWidget(
            labeled_field("مقادیر پیشنهادی:", self.attr_values_widget), 1, 0, 1, 4
        )
        attribute_grid.addWidget(self.lbl_cfg_attribute_help, 2, 0, 1, 4)
        attribute_grid.addLayout(attr_btn_row, 3, 0, 1, 4)
        attr_layout.addLayout(attribute_grid)

        gb_colors = QGroupBox("رنگ‌های قابل انتخاب کالا")
        self.gb_colors = gb_colors
        colors_layout = QVBoxLayout(gb_colors)
        colors_layout.setContentsMargins(10, 10, 10, 10)
        colors_layout.setSpacing(8)
        self.lst_cfg_colors = SmoothScrollListWidget()
        self.lst_cfg_colors.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.lst_cfg_colors.verticalScrollBar().setSingleStep(18)
        self.lst_cfg_colors.setMinimumHeight(174)
        self.lst_cfg_colors.setMaximumHeight(234)
        self.ed_cfg_color = SmartLineEdit()
        self.ed_cfg_color.setPlaceholderText("نام رنگ را وارد کنید؛ مثلاً سبز، ذغالی یا نقره‌ای...")
        self.ed_cfg_color.textChanged.connect(
            lambda _: getattr(self, "_catalog_settings_state", None) and self._catalog_settings_state.capture_from_window(self)
        )
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
        lbl_color_name = QLabel("نام رنگ:")
        lbl_color_name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        colors_layout.addWidget(CollapsibleSection("فهرست رنگ‌های تعریف‌شده", self.lst_cfg_colors))
        colors_layout.addWidget(labeled_field("نام رنگ:", self.ed_cfg_color))
        colors_layout.addLayout(color_btn_row)

        # چیدمان دو ستونه ارگونومیک راست‌به‌چپ مدیریت کالاها (بند ۹)
        # ستون راست (کانتینر اصلی ۱): دسته‌بندی‌ها، زیرمجموعه‌ها و رنگ‌ها به‌صورت عمودی و فضای گسترده
        # ستون چپ (کانتینر اصلی ۲): مشخصات فنی سفارشی با فضای بزرگ، اسکرول نرم و اشغال کامل ارتفاع
        products_page.setLayoutDirection(Qt.RightToLeft)
        products_page.setMinimumHeight(650)
        prod_page_layout = QVBoxLayout(products_page)
        prod_page_layout.setContentsMargins(10, 10, 10, 10)
        prod_page_layout.setSpacing(12)

        prod_actions_bar = QHBoxLayout()
        btn_clear_prod_tax = QPushButton("🗑️ پاک کردن فهرست‌های کالا")
        self.btn_clear_prod_tax = btn_clear_prod_tax
        btn_clear_prod_tax.setObjectName("btnDanger")
        btn_clear_prod_tax.setToolTip("پاک کردن کلیه دسته‌بندی‌ها، زیرمجموعه‌ها، مشخصات فنی و رنگ‌های کالا از پیش‌نویس")
        btn_clear_prod_tax.clicked.connect(self._clear_product_taxonomy)

        btn_import_prod_tax = QPushButton("📥 بارگذاری کالاها از فایل JSON")
        self.btn_import_prod_tax = btn_import_prod_tax
        btn_import_prod_tax.setObjectName("btnSecondary")
        btn_import_prod_tax.setToolTip("بارگذاری ساختار کالا از فایل taxonomy.json خارجی بدون تغییر خدمات")
        btn_import_prod_tax.clicked.connect(self._import_product_taxonomy)

        self.btn_export_prod_tax_section = QPushButton("📤 خروجی JSON همین بخش")
        self.btn_export_prod_tax_section.setObjectName("btnSecondary")
        self.btn_export_prod_tax_section.setToolTip("خروجی گرفتن از دسته‌بندی‌ها، زیرمجموعه‌ها، مشخصات و رنگ‌های کالا در قالب فایل JSON")
        self.btn_export_prod_tax_section.clicked.connect(self._export_product_taxonomy_section)

        self.btn_export_prod_tax_full = QPushButton("📦 خروجی جامع JSON")
        self.btn_export_prod_tax_full.setObjectName("btnSecondary")
        self.btn_export_prod_tax_full.setToolTip("خروجی گرفتن از ساختار کامل کالاها و انواع خدمات در یک فایل جامع default_taxonomy.json")
        self.btn_export_prod_tax_full.clicked.connect(self._export_comprehensive_taxonomy)

        prod_actions_bar.addWidget(btn_clear_prod_tax)
        prod_actions_bar.addWidget(btn_import_prod_tax)
        prod_actions_bar.addWidget(self.btn_export_prod_tax_section)
        prod_actions_bar.addWidget(self.btn_export_prod_tax_full)
        prod_actions_bar.addStretch()
        prod_page_layout.addLayout(prod_actions_bar)

        right_col_widget = QWidget()
        right_col_widget.setLayoutDirection(Qt.RightToLeft)
        right_col_layout = QVBoxLayout(right_col_widget)
        right_col_layout.setContentsMargins(0, 0, 0, 0)
        right_col_layout.setSpacing(14)
        gb_categories.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        gb_subcategories.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        gb_colors.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        right_col_layout.addWidget(gb_categories)
        right_col_layout.addWidget(gb_subcategories)
        right_col_layout.addWidget(gb_colors)
        right_col_layout.addStretch(1)

        right_col_scroll = SmoothScrollArea()
        right_col_scroll.setWidget(right_col_widget)
        right_col_scroll.setWidgetResizable(True)
        right_col_scroll.setFrameShape(QScrollArea.NoFrame)
        right_col_scroll.setMinimumWidth(400)

        gb_attributes.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_col_scroll = SmoothScrollArea()
        left_col_scroll.setWidget(gb_attributes)
        left_col_scroll.setWidgetResizable(True)
        left_col_scroll.setFrameShape(QScrollArea.NoFrame)
        left_col_scroll.setMinimumWidth(480)

        cols_layout = QHBoxLayout()
        cols_layout.setSpacing(16)
        cols_layout.addWidget(right_col_scroll, 1)
        cols_layout.addWidget(left_col_scroll, 1)
        prod_page_layout.addLayout(cols_layout, 1)

        self.cb_cfg_category.currentTextChanged.connect(
            self._refresh_catalog_management_lists
        )
        self.cb_cfg_category.currentTextChanged.connect(
            self._on_catalog_category_selected
        )
        self.cb_cfg_category.currentTextChanged.connect(
            self._load_subcategory_caption
        )
        self.cb_cfg_attribute_subcategory.currentIndexChanged.connect(
            self._refresh_catalog_attribute_list
        )
        self.lst_cfg_subcategories.currentItemChanged.connect(
            self._on_catalog_subcategory_selected
        )
        self.lst_cfg_colors.currentItemChanged.connect(
            self._on_catalog_color_selected
        )

        # Service types are managed beside the product catalog, not in a separate
        # application tab. Existing service records retain their stored snapshots.
        service_page = QWidget()
        service_page_layout = QVBoxLayout(service_page)

        service_actions_bar = QHBoxLayout()
        btn_clear_serv_tax = QPushButton("🗑️ پاک کردن فهرست انواع خدمت")
        self.btn_clear_serv_tax = btn_clear_serv_tax
        btn_clear_serv_tax.setObjectName("btnDanger")
        btn_clear_serv_tax.setToolTip("پاک کردن کلیه انواع خدمت از پیش‌نویس")
        btn_clear_serv_tax.clicked.connect(self._clear_service_taxonomy)

        btn_import_serv_tax = QPushButton("📥 بارگذاری خدمات از فایل JSON")
        self.btn_import_serv_tax = btn_import_serv_tax
        btn_import_serv_tax.setObjectName("btnSecondary")
        btn_import_serv_tax.setToolTip("بارگذاری انواع خدمت از فایل taxonomy.json خارجی بدون تغییر کالاها")
        btn_import_serv_tax.clicked.connect(self._import_service_taxonomy)

        self.btn_export_serv_tax_section = QPushButton("📤 خروجی JSON همین بخش")
        self.btn_export_serv_tax_section.setObjectName("btnSecondary")
        self.btn_export_serv_tax_section.setToolTip("خروجی گرفتن از فهرست انواع خدمات در قالب فایل JSON")
        self.btn_export_serv_tax_section.clicked.connect(self._export_service_taxonomy_section)

        self.btn_export_serv_tax_full = QPushButton("📦 خروجی جامع JSON")
        self.btn_export_serv_tax_full.setObjectName("btnSecondary")
        self.btn_export_serv_tax_full.setToolTip("خروجی گرفتن از ساختار کامل کالاها و انواع خدمات در یک فایل جامع default_taxonomy.json")
        self.btn_export_serv_tax_full.clicked.connect(self._export_comprehensive_taxonomy)

        service_actions_bar.addWidget(btn_clear_serv_tax)
        service_actions_bar.addWidget(btn_import_serv_tax)
        service_actions_bar.addWidget(self.btn_export_serv_tax_section)
        service_actions_bar.addWidget(self.btn_export_serv_tax_full)
        service_actions_bar.addStretch()
        service_page_layout.addLayout(service_actions_bar)

        gb_service_types = QGroupBox("مدیریت انواع خدمت")
        self.gb_service_types = gb_service_types
        service_types_layout = QVBoxLayout(gb_service_types)
        self.lst_cfg_service_types = SmoothScrollListWidget()
        self.lst_cfg_service_types.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.lst_cfg_service_types.verticalScrollBar().setSingleStep(18)
        self.lst_cfg_service_types.setMaximumHeight(220)
        self.ed_cfg_service_type = SmartLineEdit()
        self.ed_cfg_service_type.setPlaceholderText("نوع خدمت را وارد کنید؛ مثلاً سخت‌افزاری یا نرم‌افزاری...")
        self.lst_cfg_service_types.currentItemChanged.connect(
            self._on_catalog_service_type_selected
        )
        service_type_buttons = QHBoxLayout()
        btn_add_service_type = QPushButton("افزودن نوع خدمت")
        btn_add_service_type.clicked.connect(self._add_catalog_service_type)
        btn_edit_service_type = QPushButton("ویرایش نوع خدمت")
        btn_edit_service_type.setObjectName("btnSecondary")
        btn_edit_service_type.clicked.connect(self._rename_catalog_service_type)
        btn_delete_service_type = QPushButton("حذف نوع خدمت")
        btn_delete_service_type.setObjectName("btnDanger")
        btn_delete_service_type.clicked.connect(self._delete_catalog_service_type)
        service_type_buttons.addWidget(btn_add_service_type)
        service_type_buttons.addWidget(btn_edit_service_type)
        service_type_buttons.addWidget(btn_delete_service_type)
        lbl_service_type = QLabel("نام نوع خدمت:")
        lbl_service_type.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        service_types_layout.addWidget(
            CollapsibleSection("فهرست انواع خدمت", self.lst_cfg_service_types)
        )
        service_types_layout.addWidget(
            labeled_field("نام نوع خدمت:", self.ed_cfg_service_type)
        )
        service_types_layout.addLayout(service_type_buttons)
        service_page_layout.addWidget(gb_service_types)
        service_page_layout.addStretch()
        self.catalog_tabs.addTab(products_page, "مدیریت کالاها")
        self.catalog_tabs.addTab(service_page, "مدیریت خدمات")
        catalog_layout.addWidget(self.catalog_tabs)

        gb_inventory_export = QGroupBox("تنظیم ستون‌های خروجی موجودی همکار")
        self.gb_inventory_export = gb_inventory_export
        inventory_export_layout = QVBoxLayout(gb_inventory_export)
        inventory_export_layout.setContentsMargins(12, 12, 12, 12)
        inventory_export_layout.setSpacing(10)

        inv_hint = QLabel(
            "ستون‌های موردنظر برای خروجی موجودی همکار را انتخاب کرده و با دکمه‌های «انتقال به بالا» و «انتقال به پایین» یا جابجایی با ماوس ترتیب آنها را مشخص نمایید."
        )
        inv_hint.setWordWrap(True)
        inv_hint.setObjectName("settingsHint")
        inventory_export_layout.addWidget(inv_hint)

        inv_cols_container = QHBoxLayout()
        inv_cols_container.setSpacing(10)

        self.lst_inventory_export_columns = SmoothScrollListWidget()
        self.lst_inventory_export_columns.enable_row_toggle = True
        self.lst_inventory_export_columns.setMinimumHeight(240)
        self.lst_inventory_export_columns.setMaximumHeight(350)
        self.lst_inventory_export_columns.setDragDropMode(QAbstractItemView.InternalMove)
        self.lst_inventory_export_columns.setDefaultDropAction(Qt.MoveAction)
        inv_cols_container.addWidget(self.lst_inventory_export_columns, 1)

        inv_btn_box = QVBoxLayout()
        inv_btn_box.setSpacing(8)
        inv_btn_box.setAlignment(Qt.AlignTop)

        btn_inv_up = QPushButton("⬆️ انتقال به بالا")
        btn_inv_up.setObjectName("btnSecondary")
        btn_inv_up.setMinimumHeight(32)
        btn_inv_up.clicked.connect(self._move_inventory_export_col_up)

        btn_inv_down = QPushButton("⬇️ انتقال به پایین")
        btn_inv_down.setObjectName("btnSecondary")
        btn_inv_down.setMinimumHeight(32)
        btn_inv_down.clicked.connect(self._move_inventory_export_col_down)

        btn_inv_select_all = QPushButton("انتخاب همه")
        btn_inv_select_all.setMinimumHeight(32)
        btn_inv_select_all.clicked.connect(lambda: self._set_all_inventory_export_cols(True))

        btn_inv_deselect_all = QPushButton("لغو انتخاب همه")
        btn_inv_deselect_all.setMinimumHeight(32)
        btn_inv_deselect_all.clicked.connect(lambda: self._set_all_inventory_export_cols(False))

        btn_inv_reset = QPushButton("بازنشانی به پیش‌فرض")
        btn_inv_reset.setObjectName("btnDanger")
        btn_inv_reset.setMinimumHeight(32)
        btn_inv_reset.clicked.connect(self._reset_inventory_export_cols_default)

        inv_btn_box.addWidget(btn_inv_up)
        inv_btn_box.addWidget(btn_inv_down)
        inv_btn_box.addWidget(btn_inv_select_all)
        inv_btn_box.addWidget(btn_inv_deselect_all)
        inv_btn_box.addWidget(btn_inv_reset)
        inv_btn_box.addStretch(1)

        inv_cols_container.addLayout(inv_btn_box)
        inventory_export_layout.addLayout(inv_cols_container)

        self.inventory_export_column_checks = _InventoryColumnChecksProxy(self)
        self._populate_inventory_export_columns_ui()
        inventory_export_page = QWidget()
        inventory_export_page_layout = QVBoxLayout(inventory_export_page)
        inventory_export_page_layout.addWidget(gb_inventory_export)
        inventory_export_page_layout.addStretch(1)

        access_management_page = QWidget()
        access_management_page_layout = QVBoxLayout(access_management_page)
        access_management_page_layout.addWidget(gb_access_levels)
        access_management_page_layout.addStretch(1)

        self.catalog_tabs.addTab(inventory_export_page, "تنظیمات خروجی موجودی همکار")
        report_export_page = self._build_report_export_config_page()
        self.catalog_tabs.addTab(report_export_page, "تنظیمات خروجی اکسل گزارش‌ها")
        self.catalog_tabs.addTab(access_management_page, "مدیریت سطوح دسترسی")
        self.catalog_tabs.currentChanged.connect(self._on_catalog_subtab_changed)
        layout.addWidget(CollapsibleSection(
            "مدیریت ساختار کالاها، خدمات، خروجی‌ها و دسترسی‌ها", gb_catalog
        ))

        gb_db = QGroupBox("پایگاه دادهٔ فعال و پشتیبان‌گیری خودکار")
        self.gb_db = gb_db
        f_db = QFormLayout(gb_db)
        f_db.setContentsMargins(12, 12, 12, 10)
        f_db.setHorizontalSpacing(14)
        f_db.setVerticalSpacing(8)

        self.lbl_active_db_path = QLabel()
        self.lbl_active_db_path.setObjectName("activeDbPath")
        self.lbl_active_db_path.setWordWrap(False)
        self.lbl_active_db_path.setLayoutDirection(Qt.LeftToRight)
        self.lbl_active_db_path.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lbl_active_db_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_active_db_path.setFrameShape(QLabel.StyledPanel)
        self.lbl_active_db_path.setFrameShadow(QLabel.Sunken)
        self.lbl_active_db_path.setMargin(8)

        self.lst_recent_databases = SmoothScrollListWidget()
        self.lst_recent_databases.setObjectName("recentDatabasesList")
        self.lst_recent_databases.setMouseTracking(True)
        self.lst_recent_databases.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.lst_recent_databases.verticalScrollBar().setSingleStep(18)
        self.lst_recent_databases.setMinimumHeight(120)
        self.lst_recent_databases.setMaximumHeight(220)
        self.lst_recent_databases.setSpacing(4)
        self.lst_recent_databases.setUniformItemSizes(True)
        self.lst_recent_databases.setToolTip(
            "برای اتصال از دکمهٔ «اتصال» استفاده کنید؛ علامت × فقط مسیر را از فهرست حذف می‌کند و فایل را پاک نمی‌کند."
        )

        db_btn_row = QHBoxLayout()
        btn_new_db = QPushButton("ایجاد پایگاه داده")
        self.btn_new_db = btn_new_db
        btn_new_db.clicked.connect(self._create_and_connect_new_db)
        btn_open_existing_db = QPushButton("اتصال به پایگاه دادهٔ موجود")
        self.btn_open_existing_db = btn_open_existing_db
        btn_open_existing_db.setObjectName("btnSecondary")
        btn_open_existing_db.clicked.connect(self._connect_existing_db)
        btn_open_db_dir = QPushButton("باز کردن پوشه")
        self.btn_open_db_dir = btn_open_db_dir
        btn_open_db_dir.clicked.connect(self._open_db_folder)
        db_btn_row.addWidget(btn_new_db)
        db_btn_row.addWidget(btn_open_existing_db)
        db_btn_row.addWidget(btn_open_db_dir)

        self.chk_auto_bk = QCheckBox("پشتیبان‌گیری خودکار دوره‌ای فعال باشد")
        self.ed_auto_bk_dir = QLineEdit()
        self.ed_auto_bk_dir.setPlaceholderText("مسیر پوشه پشتیبان‌گیری...")
        btn_browse_bk_dir = QPushButton("انتخاب پوشه...")
        btn_browse_bk_dir.setObjectName("btnSecondary")
        btn_browse_bk_dir.clicked.connect(self._browse_auto_backup_dir)
        auto_bk_dir_row = QHBoxLayout()
        auto_bk_dir_row.addWidget(self.ed_auto_bk_dir, 1)
        auto_bk_dir_row.addWidget(btn_browse_bk_dir)

        self.sp_bk_interval = SelectAllSpinBox()
        self.sp_bk_interval.setRange(1, 1440)
        self.sp_bk_interval.setSuffix(" دقیقه")
        self.sp_bk_interval.setKeyboardTracking(False)
        self.sp_bk_interval.setButtonSymbols(QSpinBox.NoButtons)

        self.sp_bk_retention = SelectAllSpinBox()
        self.sp_bk_retention.setRange(1, 100)
        self.sp_bk_retention.setSuffix(" نسخه")
        self.sp_bk_retention.setKeyboardTracking(False)
        self.sp_bk_retention.setButtonSymbols(QSpinBox.NoButtons)
        self.sp_bk_retention.setToolTip(
            "نسخهٔ جدید ابتدا در پوشهٔ Backups ساخته و بررسی می‌شود؛ سپس نسخه‌های قدیمی‌تر از سقف تعیین‌شده حذف می‌شوند."
        )

        bk_btn_row = QHBoxLayout()
        btn_manual_bk = QPushButton("پشتیبان‌گیری دستی")
        self.btn_manual_bk = btn_manual_bk
        btn_manual_bk.setObjectName("btnSuccess")
        btn_manual_bk.clicked.connect(self._do_manual_backup)
        btn_restore_bk = QPushButton("بازیابی پشتیبان")
        self.btn_restore_bk = btn_restore_bk
        btn_restore_bk.setObjectName("btnDanger")
        btn_restore_bk.clicked.connect(self._do_restore_backup)
        bk_btn_row.addWidget(btn_manual_bk)
        bk_btn_row.addWidget(btn_restore_bk)

        self.lbl_last_backup = QLabel()
        self.lbl_last_backup.setWordWrap(True)
        self.lbl_last_backup.setObjectName("settingsHint")

        f_db.addRow("مسیر پایگاه دادهٔ فعال:", self.lbl_active_db_path)
        f_db.addRow("فهرست پایگاه‌های داده:", self.lst_recent_databases)
        f_db.addRow(db_btn_row)
        f_db.addRow(self.chk_auto_bk)
        f_db.addRow("پوشه پشتیبان‌گیری خودکار:", auto_bk_dir_row)
        f_db.addRow("فاصلهٔ پشتیبان‌گیری خودکار:", self.sp_bk_interval)
        f_db.addRow("حداکثر نسخه‌های پشتیبان خودکار:", self.sp_bk_retention)
        f_db.addRow(bk_btn_row)
        f_db.addRow(self.lbl_last_backup)
        gb_db.setTitle("")
        layout.addWidget(CollapsibleSection("پایگاه داده و پشتیبان‌گیری", gb_db))

        settings_container = QWidget()
        settings_container_layout = QVBoxLayout(settings_container)
        settings_container_layout.setContentsMargins(0, 0, 0, 0)
        settings_container_layout.setSpacing(0)

        tab.setMinimumWidth(940)
        scroll = SmoothScrollArea()
        scroll.setWidget(tab)
        settings_container_layout.addWidget(scroll, 1)

        floating_bar = QWidget()
        floating_bar.setObjectName("floatingSettingsBar")
        floating_bar.setLayoutDirection(Qt.RightToLeft)
        floating_layout = QHBoxLayout(floating_bar)
        floating_layout.setContentsMargins(16, 8, 16, 8)
        floating_layout.setSpacing(12)

        btn_save_set = QPushButton("💾 ذخیره تنظیمات")
        self.btn_save_settings = btn_save_set
        btn_save_set.setMinimumHeight(42)
        btn_save_set.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_save_set.clicked.connect(self._save_general_settings)

        btn_cancel_set = QPushButton("انصراف")
        self.btn_cancel_settings = btn_cancel_set
        btn_cancel_set.setObjectName("btnSecondary")
        btn_cancel_set.setMinimumHeight(42)
        btn_cancel_set.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_cancel_set.clicked.connect(self._rollback_settings)

        floating_layout.addWidget(btn_save_set, 1)
        floating_layout.addWidget(btn_cancel_set, 1)

        settings_container_layout.addWidget(floating_bar, 0)

        self._settings_tab_index = self.tabs.addTab(settings_container, "⚙️ تنظیمات")
        self._load_general_settings_form()

    def _load_general_settings_form(self):
        self._staged_db_password_action = None
        self._staged_db_startup_prompt = None
        cfg = self.db.cfg
        self.chk_req_pass.blockSignals(True)
        self.chk_req_pass.setChecked(bool(cfg.get("require_login_password", False)))
        self.chk_req_pass.blockSignals(False)
        self.sp_set_profit.setValue(int(float(cfg.get("default_profit_pct", 20))))
        if hasattr(self, "sp_default_min_inventory"):
            self.sp_default_min_inventory.setValue(int(cfg.get("default_min_inventory", 1)))

        zero_count = str(cfg.get("zero_append_count", 3))
        zero_index = self.cb_zero_count.findData(zero_count)
        self.cb_zero_count.setCurrentIndex(zero_index if zero_index >= 0 else 0)
        self.cb_win_mode.setCurrentIndex(
            0 if bool(cfg.get("default_window_maximized", True)) else 1
        )
        self.ed_shop_name.setText(
            self.db.get_setting("shop_name", "فروشگاه من") or "فروشگاه من"
        )
        if hasattr(self, "cb_calendar_format"):
            active_cal = self.db.get_setting("calendar_format", "jalali") or "jalali"
            cal_idx = self.cb_calendar_format.findData(active_cal)
            self.cb_calendar_format.setCurrentIndex(cal_idx if cal_idx >= 0 else 0)
        if hasattr(self, "cb_time_format"):
            active_time = self.db.get_setting("time_format", "24h") or "24h"
            time_idx = self.cb_time_format.findData(active_time)
            self.cb_time_format.setCurrentIndex(time_idx if time_idx >= 0 else 0)
        try:
            selected_export_columns = json.loads(
                self.db.get_setting("colleague_inventory_export_columns", "[]") or "[]"
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            selected_export_columns = []
        if not selected_export_columns:
            selected_export_columns = [
                "code", "batch_code", "category", "subcategory", "brand_model", "specs",
            ]
        if hasattr(self, "_populate_inventory_export_columns_ui"):
            self._populate_inventory_export_columns_ui(selected_export_columns)
        elif hasattr(self, "inventory_export_column_checks"):
            for key, checkbox in self.inventory_export_column_checks.items():
                checkbox.setChecked(key in selected_export_columns)
        self._load_subcategory_caption(
            self.cb_cfg_category.currentText()
        )
        self.chk_auto_bk.setChecked(bool(self.db.get_db_config("auto_backup_enabled", True)))
        if hasattr(self, "ed_auto_bk_dir"):
            self.ed_auto_bk_dir.setText(self.db.get_automatic_backup_directory())
        try:
            backup_interval = int(self.db.get_db_config("auto_backup_interval_min", 60))
        except (TypeError, ValueError):
            backup_interval = 60
        self.sp_bk_interval.setValue(max(1, min(1440, backup_interval)))
        self.sp_bk_retention.setValue(
            max(1, min(100, int(self.db.get_db_config("auto_backup_retention_count", 10))))
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
        self._refresh_db_password_status()
        self._refresh_report_export_types_combo()

    def _browse_auto_backup_dir(self):
        current_dir = self.ed_auto_bk_dir.text().strip() or self.db.get_automatic_backup_directory()
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "انتخاب پوشه پشتیبان‌گیری خودکار",
            current_dir,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if selected_dir:
            self.ed_auto_bk_dir.setText(os.path.abspath(selected_dir))

    def _refresh_db_password_status(self):
        if not hasattr(self, "lbl_db_pwd_status"):
            return
        self._updating_db_pwd_ui = True
        try:
            if self._staged_db_password_action:
                action = self._staged_db_password_action.get("action")
                if action == "set":
                    self.lbl_db_pwd_status.setText("🔒 وضعیت: رمز عبور جدید تعیین شده است (ذخیره‌نشده - نیازمند «ذخیره تنظیمات»).")
                    self.lbl_db_pwd_status.setStyleSheet("font-weight: bold; color: #e65100;")
                    self.btn_set_db_pwd.setVisible(False)
                    self.btn_change_db_pwd.setVisible(True)
                    self.btn_remove_db_pwd.setVisible(True)
                    self.chk_db_req_startup_pass.setEnabled(True)
                    req = self._staged_db_startup_prompt if self._staged_db_startup_prompt is not None else self._staged_db_password_action.get("req_startup", True)
                    self.chk_db_req_startup_pass.setChecked(bool(req))
                    return
                elif action == "change":
                    self.lbl_db_pwd_status.setText("🔒 وضعیت: رمز عبور تغییر یافته است (ذخیره‌نشده - نیازمند «ذخیره تنظیمات»).")
                    self.lbl_db_pwd_status.setStyleSheet("font-weight: bold; color: #e65100;")
                    self.btn_set_db_pwd.setVisible(False)
                    self.btn_change_db_pwd.setVisible(True)
                    self.btn_remove_db_pwd.setVisible(True)
                    self.chk_db_req_startup_pass.setEnabled(True)
                    req = self._staged_db_startup_prompt if self._staged_db_startup_prompt is not None else self.db.is_startup_password_prompt_required()
                    self.chk_db_req_startup_pass.setChecked(bool(req))
                    return
                elif action == "remove":
                    self.lbl_db_pwd_status.setText("🔓 وضعیت: رمز عبور حذف خواهد شد (ذخیره‌نشده - نیازمند «ذخیره تنظیمات»).")
                    self.lbl_db_pwd_status.setStyleSheet("font-weight: bold; color: #e65100;")
                    self.btn_set_db_pwd.setVisible(True)
                    self.btn_change_db_pwd.setVisible(False)
                    self.btn_remove_db_pwd.setVisible(False)
                    self.chk_db_req_startup_pass.setEnabled(False)
                    self.chk_db_req_startup_pass.setChecked(False)
                    return

            is_protected = self.db.is_password_protected()
            if is_protected:
                req_startup = self._staged_db_startup_prompt if self._staged_db_startup_prompt is not None else self.db.is_startup_password_prompt_required()
                if self._staged_db_startup_prompt is not None and self._staged_db_startup_prompt != self.db.is_startup_password_prompt_required():
                    self.lbl_db_pwd_status.setText("🔒 وضعیت: پایگاه داده با رمز عبور محافظت می‌شود (تنظیم درخواست ورود در انتظار «ذخیره تنظیمات»).")
                    self.lbl_db_pwd_status.setStyleSheet("font-weight: bold; color: #e65100;")
                else:
                    self.lbl_db_pwd_status.setText("🔒 وضعیت: پایگاه داده با رمز عبور محافظت می‌شود.")
                    self.lbl_db_pwd_status.setStyleSheet("font-weight: bold; color: #2e7d32;")
                self.btn_set_db_pwd.setVisible(False)
                self.btn_change_db_pwd.setVisible(True)
                self.btn_remove_db_pwd.setVisible(True)
                self.chk_db_req_startup_pass.setEnabled(True)
                self.chk_db_req_startup_pass.setChecked(bool(req_startup))
            else:
                self.lbl_db_pwd_status.setText("🔓 وضعیت: پایگاه داده فاقد رمز عبور است.")
                self.lbl_db_pwd_status.setStyleSheet("font-weight: bold; color: #757575;")
                self.btn_set_db_pwd.setVisible(True)
                self.btn_change_db_pwd.setVisible(False)
                self.btn_remove_db_pwd.setVisible(False)
                self.chk_db_req_startup_pass.setEnabled(False)
                self.chk_db_req_startup_pass.setChecked(False)
        finally:
            self._updating_db_pwd_ui = False

    def _on_db_startup_password_toggled(self, checked):
        if getattr(self, "_updating_db_pwd_ui", False):
            return
        is_prot = (self._staged_db_password_action and self._staged_db_password_action.get("action") in ("set", "change")) or (self.db.is_password_protected() and not (self._staged_db_password_action and self._staged_db_password_action.get("action") == "remove"))
        if not is_prot:
            return
        self._staged_db_startup_prompt = bool(checked)
        self._refresh_db_password_status()

    def _on_set_db_password_clicked(self):
        if not self._require_license_feature("database_encryption"):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("تعیین رمز عبور پایگاه داده")
        dialog.setLayoutDirection(Qt.RightToLeft)
        dialog.setFixedWidth(480)
        d_layout = QVBoxLayout(dialog)
        d_layout.setContentsMargins(20, 20, 20, 20)
        d_layout.setSpacing(14)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(15)
        form.setVerticalSpacing(12)
        ed_new = QLineEdit()
        ed_new.setEchoMode(QLineEdit.Password)
        ed_new.setPlaceholderText("رمز عبور جدید پایگاه داده...")
        ed_confirm = QLineEdit()
        ed_confirm.setEchoMode(QLineEdit.Password)
        ed_confirm.setPlaceholderText("تکرار رمز عبور جدید...")
        chk_show = QCheckBox("نمایش رمز عبور")
        chk_req_startup = QCheckBox("درخواست رمز عبور در زمان ورود به برنامه")
        chk_req_startup.setChecked(True)

        def toggle_show(state):
            mode = QLineEdit.Normal if state else QLineEdit.Password
            ed_new.setEchoMode(mode)
            ed_confirm.setEchoMode(mode)

        chk_show.toggled.connect(toggle_show)

        form.addRow("رمز عبور جدید:", ed_new)
        form.addRow("تکرار رمز عبور:", ed_confirm)
        form.addRow("", chk_show)
        form.addRow("", chk_req_startup)
        d_layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("💾 ثبت رمز عبور")
        btn_ok.setObjectName("btnSuccess")
        btn_cancel = QPushButton("انصراف")
        btn_cancel.setObjectName("btnSecondary")
        btn_cancel.clicked.connect(dialog.reject)

        def do_set():
            p1 = ed_new.text().strip()
            p2 = ed_confirm.text().strip()
            if not p1:
                QMessageBox.warning(dialog, "خطا", "رمز عبور نمی‌تواند خالی باشد.")
                ed_new.setFocus()
                return
            if p1 != p2:
                QMessageBox.warning(dialog, "خطا", "تکرار رمز عبور با رمز عبور واردشده همخوانی ندارد.")
                ed_confirm.setFocus()
                return
            self._staged_db_password_action = {
                "action": "set",
                "new_pwd": p1,
                "req_startup": chk_req_startup.isChecked(),
            }
            if self._staged_db_startup_prompt is None:
                self._staged_db_startup_prompt = chk_req_startup.isChecked()
            self._refresh_db_password_status()
            QMessageBox.information(self, "آماده ذخیره", "رمز عبور جدید ثبت شد. برای اعمال نهایی دکمه «ذخیره تنظیمات» را بزنید.")
            dialog.accept()

        btn_ok.clicked.connect(do_set)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        d_layout.addLayout(btn_row)
        apply_dialog_theme(dialog, parent=self)
        dialog.exec()

    def _on_change_db_password_clicked(self):
        if not self._require_license_feature("database_encryption"):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("تغییر رمز عبور پایگاه داده")
        dialog.setLayoutDirection(Qt.RightToLeft)
        dialog.setFixedWidth(480)
        d_layout = QVBoxLayout(dialog)
        d_layout.setContentsMargins(20, 20, 20, 20)
        d_layout.setSpacing(14)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(15)
        form.setVerticalSpacing(12)
        ed_old = QLineEdit()
        ed_old.setEchoMode(QLineEdit.Password)
        ed_old.setPlaceholderText("رمز عبور فعلی پایگاه داده...")
        ed_new = QLineEdit()
        ed_new.setEchoMode(QLineEdit.Password)
        ed_new.setPlaceholderText("رمز عبور جدید پایگاه داده...")
        ed_confirm = QLineEdit()
        ed_confirm.setEchoMode(QLineEdit.Password)
        ed_confirm.setPlaceholderText("تکرار رمز عبور جدید...")
        chk_show = QCheckBox("نمایش رمزهای عبور")

        def toggle_show(state):
            mode = QLineEdit.Normal if state else QLineEdit.Password
            ed_old.setEchoMode(mode)
            ed_new.setEchoMode(mode)
            ed_confirm.setEchoMode(mode)

        chk_show.toggled.connect(toggle_show)

        form.addRow("رمز عبور فعلی:", ed_old)
        form.addRow("رمز عبور جدید:", ed_new)
        form.addRow("تکرار رمز عبور جدید:", ed_confirm)
        form.addRow("", chk_show)
        d_layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("💾 تغییر رمز")
        btn_ok.setObjectName("btnSuccess")
        btn_cancel = QPushButton("انصراف")
        btn_cancel.setObjectName("btnSecondary")
        btn_cancel.clicked.connect(dialog.reject)

        def do_change():
            p_old = ed_old.text().strip()
            p1 = ed_new.text().strip()
            p2 = ed_confirm.text().strip()
            if not p_old:
                QMessageBox.warning(dialog, "خطا", "رمز عبور فعلی نمی‌تواند خالی باشد.")
                ed_old.setFocus()
                return
            effective_pwd_match = False
            if self._staged_db_password_action and self._staged_db_password_action.get("action") in ("set", "change"):
                effective_pwd_match = (p_old == self._staged_db_password_action.get("new_pwd"))
            else:
                effective_pwd_match = self.db.verify_database_password(p_old)
            if not effective_pwd_match:
                QMessageBox.warning(dialog, "خطا", "رمز عبور فعلی نادرست است.")
                ed_old.setFocus()
                return
            if not p1:
                QMessageBox.warning(dialog, "خطا", "رمز عبور جدید نمی‌تواند خالی باشد.")
                ed_new.setFocus()
                return
            if p1 != p2:
                QMessageBox.warning(dialog, "خطا", "تکرار رمز عبور با رمز عبور جدید همخوانی ندارد.")
                ed_confirm.setFocus()
                return
            if self._staged_db_password_action and self._staged_db_password_action.get("action") == "set":
                self._staged_db_password_action["new_pwd"] = p1
            else:
                orig_old = self._staged_db_password_action.get("old_pwd", p_old) if self._staged_db_password_action else p_old
                self._staged_db_password_action = {
                    "action": "change",
                    "old_pwd": orig_old,
                    "new_pwd": p1,
                }
            self._refresh_db_password_status()
            QMessageBox.information(self, "آماده ذخیره", "رمز عبور جدید ثبت شد. برای اعمال نهایی دکمه «ذخیره تنظیمات» را بزنید.")
            dialog.accept()

        btn_ok.clicked.connect(do_change)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        d_layout.addLayout(btn_row)
        apply_dialog_theme(dialog, parent=self)
        dialog.exec()

    def _on_remove_db_password_clicked(self):
        if not self._require_license_feature("database_encryption"):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("حذف رمز عبور پایگاه داده")
        dialog.setLayoutDirection(Qt.RightToLeft)
        dialog.setFixedWidth(480)
        d_layout = QVBoxLayout(dialog)
        d_layout.setContentsMargins(20, 20, 20, 20)
        d_layout.setSpacing(14)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(15)
        form.setVerticalSpacing(12)
        ed_cur = QLineEdit()
        ed_cur.setEchoMode(QLineEdit.Password)
        ed_cur.setPlaceholderText("رمز عبور فعلی پایگاه داده...")
        chk_show = QCheckBox("نمایش رمز عبور")

        def toggle_show(state):
            mode = QLineEdit.Normal if state else QLineEdit.Password
            ed_cur.setEchoMode(mode)

        chk_show.toggled.connect(toggle_show)

        form.addRow("رمز عبور فعلی:", ed_cur)
        form.addRow("", chk_show)
        d_layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("🔓 حذف رمز عبور")
        btn_ok.setObjectName("btnDanger")
        btn_cancel = QPushButton("انصراف")
        btn_cancel.setObjectName("btnSecondary")
        btn_cancel.clicked.connect(dialog.reject)

        def do_remove():
            p_cur = ed_cur.text().strip()
            if not p_cur:
                QMessageBox.warning(dialog, "خطا", "رمز عبور فعلی نمی‌تواند خالی باشد.")
                ed_cur.setFocus()
                return
            effective_pwd_match = False
            if self._staged_db_password_action and self._staged_db_password_action.get("action") in ("set", "change"):
                effective_pwd_match = (p_cur == self._staged_db_password_action.get("new_pwd"))
            else:
                effective_pwd_match = self.db.verify_database_password(p_cur)
            if not effective_pwd_match:
                QMessageBox.warning(dialog, "خطا", "رمز عبور فعلی نادرست است.")
                ed_cur.setFocus()
                return
            if not _ask_yes_no(
                dialog,
                "تأیید حذف رمز",
                "آیا مطمئن هستید که می‌خواهید رمز عبور پایگاه داده را حذف کنید؟\nدر این صورت فایل پایگاه داده بدون رمز قابل بازگشایی خواهد بود.",
            ):
                return
            if not self.db.is_password_protected():
                self._staged_db_password_action = None
                self._staged_db_startup_prompt = None
            else:
                orig_pwd = self._staged_db_password_action.get("old_pwd", p_cur) if (self._staged_db_password_action and self._staged_db_password_action.get("action") == "change") else p_cur
                # Stage removal instead of decrypting immediately on disk (REQ-4)
                self._staged_db_password_action = {"action": "remove", "pwd": orig_pwd}
                self._staged_db_startup_prompt = None
            self._refresh_db_password_status()
            QMessageBox.information(
                dialog,
                "حذف رمز عبور",
                "درخواست حذف رمز عبور ثبت شد.\nبرای اعمال نهایی روی فایل پایگاه داده، روی «ذخیره تنظیمات» کلیک کنید."
            )
            dialog.accept()

        btn_ok.clicked.connect(do_remove)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        d_layout.addLayout(btn_row)
        apply_dialog_theme(dialog, parent=self)
        dialog.exec()

    def _deduplicate_catalog_draft(self):
        """Collapse visually identical Persian catalogue names while tracking DB renames."""
        for category, values in list(self._taxonomy_draft.get("subcategories", {}).items()):
            seen = {}
            unique = []
            for value in values:
                key = normalize_catalog_label(value)
                if not key:
                    continue
                if key in seen:
                    canonical = seen[key]
                    if value != canonical:
                        self._pending_subcategory_renames.append((category, value, canonical))
                        for definition in self._taxonomy_draft.get("attributes", {}).get(category, []):
                            if normalize_catalog_label(definition.get("subcategory") or "") == key:
                                definition["subcategory"] = canonical
                    continue
                seen[key] = value
                unique.append(value)
            self._taxonomy_draft["subcategories"][category] = unique

        for category, definitions in list(self._taxonomy_draft.get("attributes", {}).items()):
            seen = {}
            unique = []
            for definition in definitions:
                name = str(definition.get("name") or "").strip()
                scope = str(definition.get("subcategory") or "").strip()
                key = (normalize_catalog_label(name), normalize_catalog_label(scope))
                if not key[0]:
                    continue
                existing = seen.get(key)
                if existing is None:
                    seen[key] = definition
                    unique.append(definition)
                    continue
                old_name = name
                canonical_name = str(existing.get("name") or "").strip()
                if old_name != canonical_name:
                    self._pending_attribute_renames.append(
                        (category, old_name, canonical_name, scope, scope)
                    )
                merged_values = list(existing.get("values") or []) + list(definition.get("values") or [])
                existing["values"] = list(dict.fromkeys(
                    str(value).strip() for value in merged_values if str(value).strip()
                ))
                if not str(existing.get("label") or "").strip():
                    existing["label"] = definition.get("label") or ""
            self._taxonomy_draft["attributes"][category] = unique

    @staticmethod
    def _merge_default_catalog_subcategories(config):
        merged = copy.deepcopy(config) if isinstance(config, dict) else {}
        categories = list(merged.get("categories") or [])
        subcategories = merged.setdefault("subcategories", {})
        attributes = merged.setdefault("attributes", {})
        for category in list(subcategories) + list(attributes):
            if category and category not in categories:
                categories.append(category)
        merged["categories"] = categories

        # Recover subcategories from attribute definitions
        for category, definitions in attributes.items():
            if not isinstance(definitions, list):
                continue
            values = subcategories.setdefault(category, [])
            known = {normalize_catalog_label(value) for value in values}
            for definition in definitions:
                scope = str(definition.get("subcategory") or "").strip()
                key = normalize_catalog_label(scope)
                if key and key not in known:
                    values.append(scope)
                    known.add(key)

        # Canonicalize attribute names & display titles
        name_aliases = {
            "cpu": "پردازنده", "processor": "پردازنده",
            "ram": "ظرفیت رم", "ramcapacity": "ظرفیت رم",
            "ramtype": "نسل رم", "ddrversion": "نسخه DDR",
            "storage": "حافظه داخلی", "internalstorage": "حافظه داخلی",
            "gpu": "پردازنده گرافیکی", "graphicsprocessor": "پردازنده گرافیکی",
            "display": "صفحه‌نمایش", "capacity": "ظرفیت",
            "interface": "نوع رابط", "socket": "نوع سوکت",
            "connectivity": "نوع اتصال / پورت",
            "مشخصه": "مشخصات", "specification": "مشخصات",
            "specifications": "مشخصات", "additionaldetails": "مشخصات تکمیلی",
            "size": "سایز", "panel": "نوع پنل", "paneltype": "نوع پنل",
            "refreshrate": "نرخ نوسازی", "ports": "درگاه‌ها",
            "voltage": "ولتاژ", "currentpower": "آمپر و توان",
            "connector": "نوع سوکت", "networkstandard": "استاندارد شبکه",
            "portcount": "تعداد درگاه", "printtechnology": "فناوری چاپ",
            "printcolor": "نوع چاپ", "printtype": "نوع چاپ",
            "frequency": "فرکانس", "bus": "فرکانس",
            "tdp": "توان طراحی حرارتی", "vram": "حافظه گرافیکی",
            "ramfrequency": "فرکانس", "memoryfrequency": "فرکانس",
            "resolution": "وضوح تصویر", "screensize": "سایز",
            "graphic": "پردازنده گرافیکی", "graphiccard": "پردازنده گرافیکی",
            "نوعram": "نسل رم",
            "warranty": "گارانتی", "serialnumber": "شماره سریال",
            "model": "مدل", "brand": "برند",
        }
        display_titles = {
            normalize_catalog_label(name): title
            for name, title in {
                "پردازنده": "CPU", "ظرفیت رم": "RAM Capacity",
                "نسل رم": "RAM Type", "نسخه DDR": "DDR Version",
                "حافظه داخلی": "Storage", "پردازنده گرافیکی": "GPU",
                "صفحه‌نمایش": "Display", "ظرفیت": "Capacity",
                "نوع رابط": "Interface", "نوع سوکت": "Socket",
                "نوع اتصال / پورت": "Connectivity", "مشخصات": "Specifications",
                "مشخصات تکمیلی": "Additional Specifications",
                "سایز": "Size", "نوع پنل": "Panel Type",
                "نرخ نوسازی": "Refresh Rate", "درگاه‌ها": "Ports",
                "ولتاژ": "Voltage", "آمپر و توان": "Current / Power",
                "استاندارد شبکه": "Network Standard", "تعداد درگاه": "Port Count",
                "فناوری چاپ": "Print Technology", "نوع چاپ": "Print Type",
                "فرکانس": "Frequency", "وضوح تصویر": "Resolution",
                "توان طراحی حرارتی": "TDP", "حافظه گرافیکی": "VRAM",
                "گارانتی": "Warranty", "شماره سریال": "Serial Number",
                "مدل": "Model", "برند": "Brand",
            }.items()
        }
        generic_titles = {
            "specification", "specifications", "additional details",
            "additional detail", "additional specifications",
        }
        for category, definitions in list(attributes.items()):
            if not isinstance(definitions, list):
                definitions = []
            for item in definitions:
                if not isinstance(item, dict):
                    continue
                raw_name = str(item.get("name") or "").strip()
                normalized_name = normalize_catalog_label(raw_name)
                if normalized_name in name_aliases:
                    item["name"] = name_aliases[normalized_name]
                name = str(item.get("name") or "").strip()
                raw_label = str(item.get("label") or "").strip()
                expected_title = display_titles.get(normalize_catalog_label(name))
                if expected_title and (
                    not raw_label
                    or raw_label.casefold() in generic_titles
                    or normalize_catalog_label(raw_label) ==
                       normalize_catalog_label("Additional Details")
                    or raw_label != expected_title
                ):
                    item["label"] = expected_title
                elif (
                    not raw_label
                    or raw_label.casefold() in generic_titles
                    or normalize_catalog_label(raw_label) ==
                       normalize_catalog_label("Additional Details")
                ):
                    item["label"] = "Technical Specifications"
            attributes[category] = definitions

        # Deduplicate subcategories for each category
        for category in categories:
            current = subcategories.setdefault(category, [])
            deduped = []
            seen_keys = set()
            for val in current:
                k = normalize_catalog_label(val)
                if k and k not in seen_keys:
                    seen_keys.add(k)
                    deduped.append(val)
            subcategories[category] = deduped

        merged["attributes"] = attributes
        merged["subcategories"] = subcategories
        return merged

    @staticmethod
    def _enforce_other_subcategory_attribute_contract(config):
        """Deduplicate subcategories and categories, keeping «سایر موارد» strictly last."""
        if not isinstance(config, dict):
            return config
        categories = list(config.get("categories") or [])
        subcategories = config.setdefault("subcategories", {})
        attributes = config.setdefault("attributes", {})
        other_key = normalize_catalog_label("سایر موارد")
        spec_keys = {
            normalize_catalog_label("مشخصات"),
            normalize_catalog_label("مشخصه"),
            normalize_catalog_label("specification"),
            normalize_catalog_label("specifications"),
        }

        # Keep «سایر موارد» strictly last in categories list
        clean_categories = []
        has_other_category = False
        other_category_label = "سایر موارد"
        for cat in categories:
            cat_key = normalize_catalog_label(cat)
            if cat_key == other_key:
                has_other_category = True
                other_category_label = cat
            elif cat and cat not in clean_categories:
                clean_categories.append(cat)
        if has_other_category:
            clean_categories.append(other_category_label)
        config["categories"] = clean_categories
        categories = clean_categories

        for category in categories:
            values = subcategories.setdefault(category, [])
            has_other = False
            other_label = "سایر موارد"
            unique_values = []
            seen = set()
            for value in values:
                key = normalize_catalog_label(value)
                if not key or key in seen:
                    continue
                seen.add(key)
                if key == other_key or "سایرموارد" in key:
                    has_other = True
                    other_label = value
                else:
                    unique_values.append(value)
            if has_other:
                unique_values.append(other_label)
            subcategories[category] = unique_values

            if has_other:
                definitions = attributes.setdefault(category, [])
                retained = []
                spec_values = []
                for item in definitions:
                    if not isinstance(item, dict):
                        continue
                    item_sub_key = normalize_catalog_label(item.get("subcategory") or "")
                    if item_sub_key != other_key and "سایرموارد" not in item_sub_key:
                        retained.append(item)
                        continue
                    if normalize_catalog_label(item.get("name") or "") in spec_keys:
                        spec_values.extend(item.get("values") or [])
                retained.append({
                    "name": "مشخصات",
                    "label": "Specifications",
                    "values": list(dict.fromkeys(
                        str(value).strip() for value in spec_values
                        if str(value).strip()
                    )),
                    "subcategory": other_label,
                })
                attributes[category] = retained

        config["attributes"] = attributes
        config["subcategories"] = subcategories
        return config

    def _set_default_subcategory_removed(self, category, value, removed=True):
        pass

    def _merge_product_subcategories_into_draft(self):
        """Expose categories/subcategories already referenced by persisted products."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT category, sub_category
                FROM products
                WHERE TRIM(COALESCE(category, '')) <> ''
                   OR TRIM(COALESCE(sub_category, '')) <> ''
                ORDER BY category COLLATE NOCASE, sub_category COLLATE NOCASE
                """
            ).fetchall()

        categories = self._taxonomy_draft.setdefault("categories", [])
        subcategories = self._taxonomy_draft.setdefault("subcategories", {})
        for row in rows:
            raw_category = str(row["category"] or "").strip()
            raw_subcategory = str(row["sub_category"] or "").strip()
            category = next(
                (
                    value for value in categories
                    if normalize_catalog_label(value)
                    == normalize_catalog_label(raw_category)
                ),
                raw_category,
            )
            if not category:
                continue
            if category not in categories:
                categories.append(category)
            values = subcategories.setdefault(category, [])
            if raw_subcategory and not any(
                normalize_catalog_label(value)
                == normalize_catalog_label(raw_subcategory)
                for value in values
            ):
                values.append(raw_subcategory)

    def _merge_builtin_product_features_into_draft(self):
        """No-op: All taxonomy and attributes are loaded strictly from config/seed."""
        pass

    def _merge_persisted_product_spec_fields_into_draft(self):
        """Recover feature keys saved on products but missing from the settings catalogue."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT category, sub_category, specs_json
                FROM products
                WHERE TRIM(COALESCE(category, '')) <> ''
                ORDER BY category COLLATE NOCASE, sub_category COLLATE NOCASE, id
                """
            ).fetchall()

        attributes = self._taxonomy_draft.setdefault("attributes", {})
        for row in rows:
            category = str(row["category"] or "").strip()
            scope = str(row["sub_category"] or "").strip()
            if not category or normalize_catalog_label(scope) == normalize_catalog_label("سایر موارد"):
                continue
            try:
                specs = json.loads(row["specs_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(specs, dict):
                continue
            definitions = attributes.setdefault(category, [])
            for raw_name in specs:
                name = str(raw_name or "").strip()
                name_key = normalize_catalog_label(name)
                if not name_key:
                    continue
                if any(
                    normalize_catalog_label(item.get("name")) == name_key
                    and (
                        not str(item.get("subcategory") or "").strip()
                        or normalize_catalog_label(item.get("subcategory"))
                        == normalize_catalog_label(scope)
                    )
                    for item in definitions
                ):
                    continue
                definitions.append({
                    "name": name,
                    "label": "",
                    "values": [],
                    "subcategory": scope,
                })

    def _add_or_rename_catalog_subcategory(self):
        """Apply subcategory create/rename and field-caption changes from one action."""
        selected = self.lst_cfg_subcategories.currentItem()
        new_name = self.ed_cfg_subcategory.text().strip()
        if selected is None and new_name:
            self._add_catalog_subcategory()
        elif selected is not None and new_name and new_name != selected.text():
            self._rename_catalog_subcategory()
        self._save_subcategory_caption(show_warning=False)

    def _load_catalog_customization_form(self):
        stored = self.db.get_product_catalog_config()
        self._taxonomy_draft = self._merge_default_catalog_subcategories(stored)
        self._merge_product_subcategories_into_draft()
        self._taxonomy_draft = self._merge_default_catalog_subcategories(
            self._taxonomy_draft
        )
        self._pending_category_renames = []
        self._pending_subcategory_renames = []
        self._pending_attribute_renames = []
        self._pending_color_renames = []
        self._pending_service_type_renames = []

        # Compare raw stored definitions with the draft. Queue JSON
        # key changes so product values are preserved when settings are saved.
        original_attributes = stored.get("attributes", {}) if isinstance(stored, dict) else {}
        localized_attributes = self._taxonomy_draft.get("attributes", {})
        other_key = normalize_catalog_label("سایر موارد")
        for category, original_definitions in original_attributes.items():
            localized_definitions = localized_attributes.get(category, [])
            if not isinstance(original_definitions, list):
                continue
            scopes = []
            for definition in original_definitions:
                scope = str(definition.get("subcategory") or "")
                scope_key = normalize_catalog_label(scope)
                if scope_key != other_key and scope_key not in scopes:
                    scopes.append(scope_key)
            for scope_key in scopes:
                originals = [
                    item for item in original_definitions
                    if normalize_catalog_label(item.get("subcategory") or "") == scope_key
                ]
                localized = [
                    item for item in localized_definitions
                    if normalize_catalog_label(item.get("subcategory") or "") == scope_key
                ]
                for original, localized_item in zip(originals, localized):
                    old_name = str(original.get("name") or "").strip()
                    new_name = str(localized_item.get("name") or "").strip()
                    if old_name and new_name and old_name != new_name:
                        scope = str(original.get("subcategory") or "")
                        self._pending_attribute_renames.append(
                            (category, old_name, new_name, scope, scope)
                        )

        self._merge_builtin_product_features_into_draft()
        self._merge_persisted_product_spec_fields_into_draft()
        self._deduplicate_catalog_draft()
        self._taxonomy_draft = self._enforce_other_subcategory_attribute_contract(
            self._taxonomy_draft
        )

        self.catalog_config = copy.deepcopy(self._taxonomy_draft)

        self.cb_cfg_category.blockSignals(True)
        self.cb_cfg_category.clear()
        self.cb_cfg_category.addItems(self._taxonomy_draft.get("categories", []))
        self.cb_cfg_category.blockSignals(False)
        if self.cb_cfg_category.count():
            self.cb_cfg_category.setCurrentIndex(0)
        self._load_subcategory_caption(self.cb_cfg_category.currentText())
        self._refresh_catalog_management_lists()
        if hasattr(self, "specs_widget"):
            current_category = self.cb_prod_cat.currentText()
            if current_category:
                self._configure_product_specs(current_category)

    def _refresh_catalog_management_lists(self, *_):
        if not hasattr(self, "_taxonomy_draft"):
            return
        category = self.cb_cfg_category.currentText().strip()
        self.lst_cfg_subcategories.clear()
        subcategories = self._taxonomy_draft["subcategories"].get(category, [])
        subcategories = list(dict.fromkeys(
            value for value in subcategories if normalize_catalog_label(value)
        ))
        unique_subcategories = []
        seen_subcategory_keys = set()
        for value in subcategories:
            key = normalize_catalog_label(value)
            if key not in seen_subcategory_keys:
                seen_subcategory_keys.add(key)
                unique_subcategories.append(value)
                self.lst_cfg_subcategories.addItem(value)
        subcategories = unique_subcategories

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
        self._refresh_catalog_attribute_list()
        self.lst_cfg_colors.clear()
        for color in self._taxonomy_draft["colors"]:
            self.lst_cfg_colors.addItem(color)
        self.lst_cfg_service_types.clear()
        for service_type in self._taxonomy_draft.get("service_types", []):
            self.lst_cfg_service_types.addItem(service_type)

    def _refresh_catalog_attribute_list(self, *_):
        if not hasattr(self, "_taxonomy_draft"):
            return
        category = self.cb_cfg_category.currentText().strip()
        selected_scope = normalize_catalog_label(
            self.cb_cfg_attribute_subcategory.currentData() or ""
        )
        self.lst_cfg_attributes.clear()
        seen = set()
        for definition_index, definition in enumerate(
            self._taxonomy_draft.get("attributes", {}).get(category, [])
        ):
            scope = str(definition.get("subcategory") or "").strip()
            scope_key = normalize_catalog_label(scope)
            feature_key = normalize_catalog_label(definition.get("name") or "")
            identity = (feature_key, scope_key)
            if not feature_key or identity in seen:
                continue
            if selected_scope and scope_key and scope_key != selected_scope:
                continue
            seen.add(identity)
            values = "، ".join(definition.get("values", []))
            display_scope = scope or "همهٔ زیرمجموعه‌ها"
            title = str(definition.get("label") or "").strip()
            title_text = f"  ← عنوان: {title}" if title else ""
            entry = QListWidgetItem(
                f"{definition['name']}{title_text}"
                + (f" — {values}" if values else "")
                + f"  [{display_scope}]"
            )
            entry.setData(Qt.UserRole, definition_index)
            entry.setToolTip(mixed_bidi_tooltip(
                f"ویژگی: {definition.get('name', '')}\n"
                f"عنوان نمایشی: {title or '-'}\n"
                f"محدوده: {display_scope}\n"
                f"مقادیر پیشنهادی: {values or '-'}"
            ))
            self.lst_cfg_attributes.addItem(entry)

    def _on_catalog_category_selected(self, category):
        if category:
            self.ed_cfg_category.setText(category)

    def _on_catalog_subcategory_selected(self, current, _previous=None):
        if current:
            self.ed_cfg_subcategory.setText(current.text())

    def _on_catalog_color_selected(self, current, _previous=None):
        if current:
            self.ed_cfg_color.setText(current.text())

    def _on_catalog_service_type_selected(self, current, _previous=None):
        if current:
            self.ed_cfg_service_type.setText(current.text())

    def _add_catalog_service_type(self):
        name = self.ed_cfg_service_type.text().strip()
        if not name:
            return
        values = self._taxonomy_draft.setdefault("service_types", [])
        existing = next(
            (value for value in values
             if normalize_catalog_label(value) == normalize_catalog_label(name)),
            None,
        )
        if existing is not None:
            QMessageBox.information(
                self, "نوع خدمت تکراری",
                f"این نام با «{existing}» یکسان است؛ از همان مورد استفاده کنید."
            )
            return
        values.append(name)
        self.ed_cfg_service_type.clear()
        self._refresh_catalog_management_lists()

    def _rename_catalog_service_type(self):
        selected = self.lst_cfg_service_types.currentItem()
        new_name = self.ed_cfg_service_type.text().strip()
        if not selected or not new_name:
            QMessageBox.information(self, "انتخاب نوع خدمت", "ابتدا یک نوع خدمت را انتخاب کنید.")
            return
        old_name = selected.text()
        if old_name == new_name:
            return
        values = self._taxonomy_draft.setdefault("service_types", [])
        duplicate = next(
            (value for value in values
             if value != old_name
             and normalize_catalog_label(value) == normalize_catalog_label(new_name)),
            None,
        )
        if duplicate is not None:
            QMessageBox.warning(
                self, "نام تکراری",
                f"نوع خدمت «{duplicate}» از قبل وجود دارد."
            )
            return
        values[values.index(old_name)] = new_name

        # Collapse chained renames into one database update.
        source_name = old_name
        for index, (source, target) in enumerate(self._pending_service_type_renames):
            if target == old_name:
                source_name = source
                self._pending_service_type_renames.pop(index)
                break
        self._pending_service_type_renames.append((source_name, new_name))
        self.ed_cfg_service_type.clear()
        self._refresh_catalog_management_lists()

    def _delete_catalog_service_type(self):
        selected = self.lst_cfg_service_types.currentItem()
        if not selected:
            return
        name = selected.text()
        source_names = [name]
        current_name = name
        for old_name, new_name in reversed(self._pending_service_type_renames):
            if current_name == new_name:
                if old_name not in source_names:
                    source_names.append(old_name)
                current_name = old_name
        marks = ",".join("?" for _ in source_names)
        with self.db.get_connection() as conn:
            used = conn.execute(
                f"SELECT COUNT(*) FROM service_catalog WHERE service_type IN ({marks})",
                tuple(source_names),
            ).fetchone()[0]
        if used:
            QMessageBox.warning(
                self, "نوع خدمت در حال استفاده است",
                "این نوع خدمت در تعرفه‌های ثبت‌شده استفاده شده است. برای حفظ سوابق، ابتدا خدمات وابسته را تغییر دهید."
            )
            return
        self._taxonomy_draft["service_types"] = [
            value for value in self._taxonomy_draft.get("service_types", [])
            if value != name
        ]
        self._pending_service_type_renames = [
            (old_name, new_name)
            for old_name, new_name in self._pending_service_type_renames
            if new_name != name
        ]
        self.ed_cfg_service_type.clear()
        self._refresh_catalog_management_lists()

    def _add_catalog_category(self):
        name = self.ed_cfg_category.text().strip()
        if not name:
            return
        categories = self._taxonomy_draft["categories"]
        existing = next(
            (value for value in categories
             if normalize_catalog_label(value) == normalize_catalog_label(name)),
            None,
        )
        if existing is not None:
            QMessageBox.information(
                self, "دسته‌بندی موجود است",
                f"این نام با دسته‌بندی «{existing}» یکسان است."
            )
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
        duplicate = next(
            (value for value in self._taxonomy_draft["categories"]
             if value != old
             and normalize_catalog_label(value) == normalize_catalog_label(new)),
            None,
        )
        if duplicate is not None:
            QMessageBox.warning(
                self, "نام تکراری",
                f"دسته‌بندی «{duplicate}» از قبل وجود دارد."
            )
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
        if not category:
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
        self._set_default_subcategory_removed(category, name, removed=False)
        existing = next(
            (value for value in values
             if normalize_catalog_label(value) == normalize_catalog_label(name)),
            None,
        )
        if existing is not None:
            QMessageBox.information(
                self, "زیرمجموعه موجود است",
                f"این نام با زیرمجموعهٔ «{existing}» یکسان است."
            )
        else:
            values.append(name)
        self.ed_cfg_subcategory.clear()
        self._merge_builtin_product_features_into_draft()
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
        new_key = normalize_catalog_label(new)
        duplicate = next(
            (value for value in values
             if value != old and normalize_catalog_label(value) == new_key),
            None,
        )
        if duplicate is not None:
            # The target spelling is already represented; merge this alias into it.
            values.remove(old)
            canonical = duplicate
        else:
            values[values.index(old)] = new
            canonical = new
        self._set_default_subcategory_removed(category, old, removed=True)
        self._set_default_subcategory_removed(category, canonical, removed=False)
        self._pending_subcategory_renames.append((category, old, canonical))
        self._pending_attribute_renames = [
            (
                pending_category,
                old_name,
                new_name,
                canonical if normalize_catalog_label(old_scope) == normalize_catalog_label(old) else old_scope,
                canonical if normalize_catalog_label(new_scope) == normalize_catalog_label(old) else new_scope,
            )
            for pending_category, old_name, new_name, old_scope, new_scope
            in self._pending_attribute_renames
        ]
        for definition in self._taxonomy_draft["attributes"].get(category, []):
            if normalize_catalog_label(definition.get("subcategory") or "") == normalize_catalog_label(old):
                definition["subcategory"] = canonical
        self.ed_cfg_subcategory.clear()
        self._merge_builtin_product_features_into_draft()
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
            if normalize_catalog_label(definition.get("subcategory") or "")
                == normalize_catalog_label(name)
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
        self._set_default_subcategory_removed(category, name, removed=True)
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
            normalize_catalog_label(item.get("name")) == normalize_catalog_label(name)
            and normalize_catalog_label(item.get("subcategory") or "")
                == normalize_catalog_label(selected_scope)
            for item in definitions
        ):
            QMessageBox.warning(
                self, "ویژگی تکراری",
                "این مشخصه قبلاً برای همین زیرمجموعه ثبت شده است."
            )
            return
        values = self.attr_values_widget.get_values()
        definitions.append({
            "name": name,
            "label": self.ed_cfg_attribute_label.text().strip(),
            "values": list(dict.fromkeys(values)),
            "subcategory": selected_scope,
        })
        self.ed_cfg_attribute_name.clear()
        self.ed_cfg_attribute_label.clear()
        self.attr_values_widget.clear()
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
            self.attr_values_widget.set_values(definition.get("values", []))
            # Selecting a feature populates its editor without changing the active filter.

    def _update_catalog_attribute(self):
        category = self.cb_cfg_category.currentText().strip()
        selected = self.lst_cfg_attributes.currentItem()
        if not selected:
            QMessageBox.information(
                self, "انتخاب ویژگی", "ابتدا ویژگی موردنظر را از فهرست انتخاب کنید."
            )
            return

        definition_index = selected.data(Qt.UserRole)
        definitions = self._taxonomy_draft["attributes"].setdefault(category, [])
        if not isinstance(definition_index, int) or not 0 <= definition_index < len(definitions):
            return

        current = definitions[definition_index]
        old_name = str(current.get("name") or "").strip()
        old_scope = str(current.get("subcategory") or "").strip()
        new_name = self.ed_cfg_attribute_name.text().strip() or old_name
        new_scope = self.cb_cfg_attribute_subcategory.currentData() or old_scope
        if not new_name:
            QMessageBox.warning(self, "نام ویژگی لازم است", "نام ویژگی را وارد کنید.")
            return

        new_key = normalize_catalog_label(new_name)
        new_scope_key = normalize_catalog_label(new_scope)
        duplicate_indexes = [
            index for index, item in enumerate(definitions)
            if index != definition_index
            and normalize_catalog_label(item.get("name")) == new_key
            and normalize_catalog_label(item.get("subcategory") or "") == new_scope_key
        ]

        widget_values = self.attr_values_widget.get_values()
        merged_values = list(widget_values)
        for index in duplicate_indexes:
            duplicate = definitions[index]
            duplicate_name = str(duplicate.get("name") or "").strip()
            duplicate_scope = str(duplicate.get("subcategory") or "").strip()
            merged_values.extend(duplicate.get("values") or [])
            if duplicate_name and duplicate_name != new_name:
                self._pending_attribute_renames.append(
                    (category, duplicate_name, new_name, duplicate_scope, new_scope)
                )

        # Remove aliases from the draft so the configuration itself, not just
        # the rendered form, contains one canonical feature definition.
        for index in sorted(duplicate_indexes, reverse=True):
            definitions.pop(index)
            if index < definition_index:
                definition_index -= 1
        current = definitions[definition_index]

        new_values = list(dict.fromkeys(
            str(value).strip() for value in merged_values if str(value).strip()
        ))

        if old_name != new_name or old_scope != new_scope:
            self._pending_attribute_renames.append(
                (category, old_name, new_name, old_scope, new_scope)
            )
        current["name"] = new_name
        current["label"] = self.ed_cfg_attribute_label.text().strip()
        current.pop("display_name", None)
        current["values"] = new_values
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
        if not color:
            return
        existing = next(
            (value for value in self._taxonomy_draft["colors"]
             if normalize_catalog_label(value) == normalize_catalog_label(color)),
            None,
        )
        if existing is not None:
            QMessageBox.information(
                self, "رنگ تکراری",
                f"رنگ «{existing}» از قبل در فهرست وجود دارد."
            )
            return
        self._taxonomy_draft["colors"].append(color)
        self.ed_cfg_color.clear()
        self._refresh_catalog_management_lists()

    def _rename_catalog_color(self):
        item = self.lst_cfg_colors.currentItem()
        new_name = self.ed_cfg_color.text().strip()
        if not item or not new_name:
            return
        old_name = item.text()
        if new_name == old_name:
            return
        duplicate = next(
            (value for value in self._taxonomy_draft["colors"]
             if value != old_name
             and normalize_catalog_label(value) == normalize_catalog_label(new_name)),
            None,
        )
        if duplicate is not None:
            QMessageBox.warning(
                self, "نام تکراری",
                f"رنگ «{duplicate}» از قبل وجود دارد."
            )
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
            color_key = normalize_catalog_label(color)
            self._taxonomy_draft["colors"] = [
                value for value in self._taxonomy_draft["colors"]
                if normalize_catalog_label(value) != color_key
            ]
            self._refresh_catalog_management_lists()

    def _refresh_catalog_draft_ui(self):
        """Refresh UI controls directly from current in-memory self._taxonomy_draft (REQ-3)."""
        if not hasattr(self, "_taxonomy_draft"):
            return
        self.catalog_config = copy.deepcopy(self._taxonomy_draft)
        self.cb_cfg_category.blockSignals(True)
        self.cb_cfg_category.clear()
        self.cb_cfg_category.addItems(self._taxonomy_draft.get("categories", []))
        self.cb_cfg_category.blockSignals(False)
        if self.cb_cfg_category.count():
            self.cb_cfg_category.setCurrentIndex(0)
        self._load_subcategory_caption(self.cb_cfg_category.currentText())
        self._refresh_catalog_management_lists()

    def _clear_product_taxonomy(self):
        """Action 1 (REQ-3): Clear all product taxonomy lists from in-memory draft (services untouched)."""
        if not _ask_yes_no(
            self,
            "تأیید پاک کردن فهرست‌های کالا",
            "آیا مطمئن هستید که می‌خواهید تمام دسته‌بندی‌ها، زیرمجموعه‌ها، مشخصات فنی و رنگ‌های کالا را از پیش‌نویس پاک کنید؟\n"
            "این تغییر فقط در پیش‌نویس تنظیمات اعمال می‌شود و تا زمان کلیک روی «ذخیره تنظیمات» در پایگاه داده ذخیره نخواهد شد."
        ):
            return
        self._taxonomy_draft["categories"] = []
        self._taxonomy_draft["subcategories"] = {}
        self._taxonomy_draft["attributes"] = {}
        self._taxonomy_draft["colors"] = []
        self._refresh_catalog_draft_ui()

    def _import_product_taxonomy(self, import_path=None):
        """Action 2 (REQ-3): Scoped manual JSON import for product taxonomy only (services untouched)."""
        if not import_path and not self._require_license_write_allowed():
            return
        if not import_path and not self._require_license_feature("taxonomy_import_export"):
            return
        if import_path:
            path = import_path
        else:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "انتخاب فایل ساختار کالا (JSON)",
                "",
                "JSON Files (*.json);;All Files (*.*)",
            )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("محتوای فایل JSON باید یک شیء (Object) معتبر باشد.")

            categories = data.get("categories", [])
            subcategories = data.get("subcategories", {})
            attributes = data.get("attributes", {})
            colors = data.get("colors", [])

            if not isinstance(categories, list) or not isinstance(subcategories, dict) or not isinstance(attributes, dict):
                raise ValueError("قالب فایل ساختار کالا معتبر نیست (باید شامل categories، subcategories و attributes باشد).")

            self._taxonomy_draft["categories"] = list(categories)
            self._taxonomy_draft["subcategories"] = {k: list(v) for k, v in subcategories.items() if isinstance(v, list)}
            self._taxonomy_draft["attributes"] = copy.deepcopy(attributes)
            if isinstance(colors, list):
                self._taxonomy_draft["colors"] = list(colors)

            self._taxonomy_draft = self._merge_default_catalog_subcategories(self._taxonomy_draft)
            self._taxonomy_draft = self._enforce_other_subcategory_attribute_contract(self._taxonomy_draft)

            self._refresh_catalog_draft_ui()
            if not import_path:
                QMessageBox.information(
                    self,
                    "بارگذاری ساختار کالا",
                    "ساختار کالاها با موفقیت در پیش‌نویس بارگذاری شد.\nبرای اعمال نهایی، روی «ذخیره تنظیمات» کلیک کنید."
                )
        except Exception as e:
            if not import_path:
                QMessageBox.critical(self, "خطا در بارگذاری فایل ساختار", f"فایل انتخاب‌شده نامعتبر است یا قابل خواندن نیست:\n{e}")
            else:
                raise

    def _clear_service_taxonomy(self):
        """Action 1 (REQ-3): Clear all service types from in-memory draft (products untouched)."""
        if not _ask_yes_no(
            self,
            "تأیید پاک کردن فهرست انواع خدمت",
            "آیا مطمئن هستید که می‌خواهید تمام انواع خدمت را از پیش‌نویس پاک کنید؟\n"
            "این تغییر فقط در پیش‌نویس تنظیمات اعمال می‌شود و تا زمان کلیک روی «ذخیره تنظیمات» در پایگاه داده ذخیره نخواهد شد."
        ):
            return
        self._taxonomy_draft["service_types"] = []
        self._refresh_catalog_draft_ui()

    def _import_service_taxonomy(self, import_path=None):
        """Action 2 (REQ-3): Scoped manual JSON import for service types only (products untouched)."""
        if not import_path and not self._require_license_write_allowed():
            return
        if not import_path and not self._require_license_feature("taxonomy_import_export"):
            return
        if import_path:
            path = import_path
        else:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "انتخاب فایل ساختار خدمات (JSON)",
                "",
                "JSON Files (*.json);;All Files (*.*)",
            )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("محتوای فایل JSON باید یک شیء (Object) معتبر باشد.")

            service_types = data.get("service_types")
            if service_types is None:
                service_types = data.get("نوع خدمت", [])
            if not isinstance(service_types, list):
                raise ValueError("قالب بخش خدمات معتبر نیست (باید آرایه‌ای از نام انواع خدمت باشد).")

            self._taxonomy_draft["service_types"] = [str(st).strip() for st in service_types if str(st).strip()]
            self._refresh_catalog_draft_ui()
            if not import_path:
                QMessageBox.information(
                    self,
                    "بارگذاری انواع خدمت",
                    "فهرست انواع خدمت با موفقیت در پیش‌نویس بارگذاری شد.\nبرای اعمال نهایی، روی «ذخیره تنظیمات» کلیک کنید."
                )
        except Exception as e:
            if not import_path:
                QMessageBox.critical(self, "خطا در بارگذاری فایل خدمات", f"فایل انتخاب‌شده نامعتبر است یا قابل خواندن نیست:\n{e}")
            else:
                raise

    def _export_product_taxonomy_section(self, export_path=None):
        """REQ-1: Scoped JSON export for product taxonomy only (categories, subcategories, attributes, colors)."""
        if not export_path and not self._require_license_feature("taxonomy_import_export"):
            return None
        if export_path:
            path = export_path
        else:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "ذخیره ساختار کالا در فایل JSON",
                "product_taxonomy.json",
                "JSON Files (*.json);;All Files (*.*)",
            )
        if not path:
            return None
        try:
            payload = {
                "categories": list(self._taxonomy_draft.get("categories") or []),
                "subcategories": copy.deepcopy(self._taxonomy_draft.get("subcategories") or {}),
                "attributes": copy.deepcopy(self._taxonomy_draft.get("attributes") or {}),
                "colors": list(self._taxonomy_draft.get("colors") or []),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            if not export_path:
                QMessageBox.information(
                    self,
                    "خروجی ساختار کالا",
                    f"فایل ساختار کالا با موفقیت ذخیره شد:\n{path}"
                )
            return path
        except Exception as e:
            if not export_path:
                QMessageBox.critical(self, "خطا در ذخیره فایل", f"ذخیره فایل با خطا مواجه شد:\n{e}")
                return None
            else:
                raise

    def _export_service_taxonomy_section(self, export_path=None):
        """REQ-1: Scoped JSON export for service types only (service_types)."""
        if not export_path and not self._require_license_feature("taxonomy_import_export"):
            return None
        if export_path:
            path = export_path
        else:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "ذخیره انواع خدمت در فایل JSON",
                "service_taxonomy.json",
                "JSON Files (*.json);;All Files (*.*)",
            )
        if not path:
            return None
        try:
            payload = {
                "service_types": list(self._taxonomy_draft.get("service_types") or []),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            if not export_path:
                QMessageBox.information(
                    self,
                    "خروجی انواع خدمت",
                    f"فایل انواع خدمت با موفقیت ذخیره شد:\n{path}"
                )
            return path
        except Exception as e:
            if not export_path:
                QMessageBox.critical(self, "خطا در ذخیره فایل", f"ذخیره فایل با خطا مواجه شد:\n{e}")
                return None
            else:
                raise

    def _export_comprehensive_taxonomy(self, export_path=None):
        """REQ-1: Comprehensive JSON export of products and services matching default_taxonomy.json schema."""
        if not export_path and not self._require_license_feature("taxonomy_import_export"):
            return None
        if export_path:
            path = export_path
        else:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "ذخیره فهرست جامع ساختار کالا و خدمات در فایل JSON",
                "default_taxonomy.json",
                "JSON Files (*.json);;All Files (*.*)",
            )
        if not path:
            return None
        try:
            payload = {
                "categories": list(self._taxonomy_draft.get("categories") or []),
                "subcategories": copy.deepcopy(self._taxonomy_draft.get("subcategories") or {}),
                "attributes": copy.deepcopy(self._taxonomy_draft.get("attributes") or {}),
                "colors": list(self._taxonomy_draft.get("colors") or []),
                "service_types": list(self._taxonomy_draft.get("service_types") or []),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            if not export_path:
                QMessageBox.information(
                    self,
                    "خروجی جامع ساختار",
                    f"فایل جامع ساختار کالا و خدمات با موفقیت ذخیره شد:\n{path}"
                )
            return path
        except Exception as e:
            if not export_path:
                QMessageBox.critical(self, "خطا در ذخیره فایل", f"ذخیره فایل با خطا مواجه شد:\n{e}")
                return None
            else:
                raise

    def _on_save_settings_clicked(self):
        return self._save_general_settings()

    def _on_cancel_settings_clicked(self):
        return self._rollback_settings()

    def _apply_product_catalog_config(self):
        self.catalog_config = self._effective_product_catalog_config()
        categories = list(self.catalog_config.get("categories") or [])
        categories = list(dict.fromkeys(categories))
        colors = self.catalog_config.get("colors") or []
        current_category = self.cb_prod_cat.currentText() if hasattr(self, "cb_prod_cat") else ""
        if hasattr(self, "cb_prod_cat"):
            self.cb_prod_cat.blockSignals(True)
            self.cb_prod_cat.clear()
            self.cb_prod_cat.addItems(categories)
            if current_category:
                self.cb_prod_cat.setCurrentText(current_category)
            self.cb_prod_cat.blockSignals(False)
        if hasattr(self, "btn_batch_colors"):
            selected_colors = self._checked_colors(self.btn_batch_colors)
            self._populate_color_checklist(self.btn_batch_colors, colors, selected_colors)
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
        if hasattr(self, "cb_srv_type"):
            current_type = self.cb_srv_type.currentText()
            self.cb_srv_type.blockSignals(True)
            self.cb_srv_type.clear()
            self.cb_srv_type.addItems(
                self.catalog_config.get("service_types") or []
            )
            if current_type and self.cb_srv_type.findText(current_type) >= 0:
                self.cb_srv_type.setCurrentText(current_type)
            self.cb_srv_type.blockSignals(False)

    def _effective_product_catalog_config(self):
        """Return the configured catalogue plus active subcategories."""
        stored = self.db.get_product_catalog_config()
        return self._merge_default_catalog_subcategories(stored)

    def _load_subcategory_caption(self, category):
        raw = self.db.get_setting("subcategory_field_labels", "{}")
        try:
            labels = json.loads(raw or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            labels = {}
        self.ed_subcategory_caption.setText(
            str(labels.get(category, "زیرمجموعه"))
            if isinstance(labels, dict) else "زیرمجموعه"
        )

    def _save_subcategory_caption(self, show_warning=True):
        category = self.cb_cfg_category.currentText().strip()
        caption = self.ed_subcategory_caption.text().strip()
        if not category or not caption:
            if show_warning:
                QMessageBox.warning(self, "عنوان فیلد", "دسته‌بندی و عنوان فیلد را وارد کنید.")
            return False
        raw = self.db.get_setting("subcategory_field_labels", "{}")
        try:
            labels = json.loads(raw or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            labels = {}
        if not isinstance(labels, dict):
            labels = {}
        labels[category] = caption
        self.db.set_setting(
            "subcategory_field_labels", json.dumps(labels, ensure_ascii=False)
        )
        if self.cb_prod_cat.currentText().strip() == category:
            self._configure_product_specs(category)
        return True

    def _configure_product_specs(self, category):
        if not hasattr(self, "specs_widget"):
            return
        category = (category or "").strip()
        previous_category = str(
            getattr(self.specs_widget, "current_category", "") or ""
        ).strip()
        previous_subcategory = (
            self.specs_widget.get_sub_category()
            if self.specs_widget.cb_sub is not None else ""
        )
        # The widget invokes this callback after category-specific built-in controls
        # have been rebuilt; a parent currentIndexChanged slot can run too early.
        self.specs_widget.set_custom_field_callback(
            self._apply_custom_specs_for_subcategory
        )
        self.specs_widget.set_category(category)
        raw_labels = self.db.get_setting("subcategory_field_labels", "{}")
        try:
            custom_labels = json.loads(raw_labels or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            custom_labels = {}
        custom_caption = (
            custom_labels.get(category, "زیرمجموعه")
            if isinstance(custom_labels, dict) else "زیرمجموعه"
        )
        self.specs_widget.set_subcategory_label(custom_caption)
        if hasattr(self, "catalog_config"):
            subcategories = self.catalog_config.get("subcategories", {}).get(category)
            self.specs_widget.apply_custom_catalog(subcategories, [])

            combo = self.specs_widget.cb_sub
            is_other_category = (normalize_catalog_label(category) == normalize_catalog_label("سایر موارد"))
            if combo is not None:
                combo.setEditable(is_other_category)
                if is_other_category:
                    combo.setToolTip("زیرمجموعه را انتخاب کنید یا نام دلخواه را تایپ کنید")
                else:
                    combo.setToolTip("زیرمجموعه را از فهرست انتخاب کنید")
                if combo.count():
                    target_index = -1
                    if (
                        normalize_catalog_label(previous_category)
                        == normalize_catalog_label(category)
                        and normalize_catalog_label(previous_subcategory)
                    ):
                        previous_key = normalize_catalog_label(previous_subcategory)
                        target_index = next(
                            (
                                index for index in range(combo.count())
                                if normalize_catalog_label(combo.itemText(index)) == previous_key
                            ),
                            -1,
                        )
                    if target_index < 0:
                        target_index = 0
                    if combo.currentIndex() != target_index:
                        combo.setCurrentIndex(target_index)

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
        is_other_category = (normalize_catalog_label(category) == normalize_catalog_label("سایر موارد"))
        is_other_subcategory = (
            normalize_catalog_label(subcategory) == normalize_catalog_label("سایر موارد")
            or "سایر موارد" in subcategory
            or "(other)" in subcategory.lower()
        )
        is_other = is_other_category or is_other_subcategory
        if is_other:
            for k in list(self.specs_widget.fields.keys()):
                if normalize_catalog_label(k) != normalize_catalog_label("مشخصات"):
                    w = self.specs_widget.fields.pop(k, None)
                    if w:
                        try:
                            row, _ = self.specs_widget.form_layout.getWidgetPosition(w)
                            if row >= 0:
                                self.specs_widget.form_layout.removeRow(row)
                        except Exception:
                            pass
                        try:
                            if hasattr(self.specs_widget, "sub_layout") and self.specs_widget.sub_layout:
                                row, _ = self.specs_widget.sub_layout.getWidgetPosition(w)
                                if row >= 0:
                                    self.specs_widget.sub_layout.removeRow(row)
                        except Exception:
                            pass
            applicable = [{"name": "مشخصات", "display_name": "Specifications", "values": []}]
        else:
            applicable = [
                item for item in definitions
                if not str(item.get("subcategory") or "").strip()
                or str(item.get("subcategory") or "").strip().casefold() == subcategory.casefold()
                or normalize_catalog_label(item.get("subcategory") or "") == normalize_catalog_label(subcategory)
            ]
            # Ensure universal "مشخصات" is always strictly the very last field
            specs_item = next((item for item in applicable if normalize_catalog_label(item.get("name") or "") == normalize_catalog_label("مشخصات")), None)
            applicable = [item for item in applicable if normalize_catalog_label(item.get("name") or "") != normalize_catalog_label("مشخصات")]
            if specs_item is not None:
                applicable.append(specs_item)
            else:
                applicable.append({"name": "مشخصات", "display_name": "Specifications", "values": []})
        self.specs_widget.apply_custom_catalog(None, applicable)

    def _refresh_multi_db_combo(self):
        self._refresh_recent_database_list()

    def _refresh_recent_database_list(self):
        self.lst_recent_databases.clear()
        recents = self.db.cfg.get("recent_databases", [])
        active_path = os.path.abspath(self.db.db_path)
        ordered = []
        seen_norm = set()
        for path in [active_path] + list(recents):
            if not path:
                continue
            abs_p = os.path.abspath(path)
            norm_p = os.path.normcase(abs_p)
            if norm_p not in seen_norm and os.path.isfile(abs_p):
                seen_norm.add(norm_p)
                ordered.append(abs_p)
        self.db.cfg["recent_databases"] = ordered

        for database_path in ordered:
            row_item = QListWidgetItem()
            row_widget = QWidget()
            row_widget.setObjectName("databaseRecentRow")
            row_widget.setAttribute(Qt.WA_StyledBackground, True)
            row_widget.setAttribute(Qt.WA_Hover, True)
            row_widget.setMouseTracking(True)
            row_layout = QHBoxLayout(row_widget)
            row_widget.setMinimumHeight(48)
            row_layout.setContentsMargins(8, 7, 8, 7)
            row_layout.setSpacing(10)

            is_active = os.path.normcase(database_path) == os.path.normcase(active_path)
            database_label = QLabel(os.path.basename(database_path))
            database_label.setToolTip(database_path)
            database_label.setMinimumWidth(100)
            database_label.setMinimumHeight(32)
            database_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            database_label.setLayoutDirection(Qt.LeftToRight)
            database_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            if is_active:
                database_label.setStyleSheet("font-weight: bold; color: #059669;")

            if is_active:
                active_badge = QLabel("فعال / متصل")
                active_badge.setObjectName("databaseActiveBadge")
                active_badge.setAlignment(Qt.AlignCenter)
                active_badge.setFixedSize(96, 32)
                active_badge.setStyleSheet(
                    "QLabel { color: #047857; background: rgba(16,185,129,0.12); "
                    "border: 1px solid #10b981; border-radius: 6px; "
                    "padding: 4px 8px; font-size: 11px; font-weight: bold; }"
                )
                row_layout.addWidget(active_badge)
            else:
                btn_connect = QPushButton("اتصال")
                btn_connect.setMinimumSize(84, 32)
                btn_connect.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                btn_connect.clicked.connect(
                    lambda checked=False, target=database_path: self._switch_to_database_path(target)
                )
                row_layout.addWidget(btn_connect)

            btn_remove = QToolButton()
            btn_remove.setText("×")
            btn_remove.setToolTip("حذف مسیر از فهرست؛ فایل پایگاه داده پاک نمی‌شود")
            btn_remove.setFixedSize(32, 32)
            btn_remove.setEnabled(not is_active)
            btn_remove.setStyleSheet(
                "QToolButton { color: #dc2626; font-size: 16px; font-weight: bold; "
                "padding: 0px; margin: 0px; border: 1px solid #cbd5e1; "
                "border-radius: 5px; background: palette(base); }"
                "QToolButton:hover { background: rgba(220,38,38,0.12); border-color: #dc2626; }"
            )
            btn_remove.clicked.connect(
                lambda checked=False, target=database_path: self._remove_recent_database(target)
            )

            row_layout.addWidget(database_label, 1)
            row_layout.addWidget(btn_remove, 0, Qt.AlignVCenter)
            row_item.setSizeHint(row_widget.sizeHint().expandedTo(
                row_widget.minimumSizeHint()
            ))
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
            and os.path.isfile(path)
        ]
        dbs = self.db.cfg.get("databases", {})
        if target in dbs:
            dbs.pop(target, None)
        SecureCredentialStore.purge_database_credential(database_path)
        save_app_config(self.db.cfg)
        self._refresh_recent_database_list()


    def _switch_to_database_path(self, target_path: str, *, create_if_missing=False):
        if not target_path:
            return
        target_path = os.path.abspath(os.path.expanduser(target_path))
        if self.db and os.path.normcase(os.path.abspath(self.db.db_path)) == os.path.normcase(target_path):
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

        old_db = self.db
        previous_employee = self.active_employee

        try:
            os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
            if create_if_missing:
                if old_db:
                    try:
                        old_db.sync_database()
                        old_db.close()
                    except Exception:
                        pass
                new_db = create_and_initialize_database(target_path)
            else:
                probe_db = DatabaseManager(target_path)
                pwd = None
                if probe_db.is_password_protected() and not probe_db.can_auto_unlock_locally():
                    unlocked = False
                    for _ in range(3):
                        p, ok = _prompt_database_password(self, "رمز عبور این پایگاه داده را وارد کنید:")
                        if not ok:
                            break
                        if probe_db.verify_database_password(p):
                            pwd = p
                            unlocked = True
                            break
                        else:
                            QMessageBox.warning(self, "رمز نادرست", "رمز عبور واردشده برای پایگاه داده صحیح نیست.")
                    if not unlocked:
                        probe_db.close()
                        return
                probe_db.close()
                if old_db:
                    try:
                        old_db.sync_database()
                        old_db.close()
                    except Exception:
                        pass
                new_db = DatabaseManager(target_path, password=pwd)

            new_db.cfg["db_path"] = target_path
            new_db.cfg["backup_dir"] = os.path.dirname(target_path) or "."
            recents = [
                os.path.abspath(path) for path in new_db.cfg.get("recent_databases", [])
                if path and os.path.normcase(os.path.abspath(path)) != os.path.normcase(target_path)
                and os.path.isfile(path)
            ]
            new_db.cfg["recent_databases"] = [target_path] + recents
            save_app_config(new_db.cfg)
            self.db = new_db
            self._staged_db_password_action = None
            self._staged_db_startup_prompt = None
        except Exception as exc:
            QMessageBox.critical(self, "خطا در اتصال", f"اتصال به پایگاه داده انجام نشد.\n{exc}")
            self._refresh_multi_db_combo()
            return

        selected_employee, accepted = _resolve_startup_employee(self.db, self)
        if not accepted:
            self.active_employee = previous_employee
            self._refresh_multi_db_combo()
            self._restart_backup_timer()
            return

        self.active_employee = selected_employee
        shop_name = (self.db.get_setting("shop_name", "فروشگاه من") or "فروشگاه من").strip()
        if shop_name and shop_name != "فروشگاه من":
            try:
                self.db.cfg["last_store_name"] = shop_name
                save_app_config(self.db.cfg)
            except Exception:
                pass
        self.setWindowTitle(_window_title(shop_name))
        if hasattr(self, "lbl_store_name"):
            self.lbl_store_name.setText(bidi_isolate_text(f"دقیق | {shop_name}"))
            self.lbl_store_name.setToolTip(f"نام فروشگاه: {shop_name}")

        self.catalog_config = self._effective_product_catalog_config()
        self._apply_product_catalog_config()
        self._refresh_multi_db_combo()
        self._restart_backup_timer()
        self.refresh_all_data()
        self._load_general_settings_form()
        if create_if_missing:
            QMessageBox.information(
                self, "ایجاد پایگاه داده",
                f"پایگاه دادهٔ جدید با موفقیت ایجاد و متصل شد:\n{target_path}"
            )
        else:
            QMessageBox.information(
                self, "تغییر پایگاه داده",
                f"برنامه به پایگاه دادهٔ زیر متصل شد:\n{target_path}"
            )

    def _create_and_connect_new_db(self):
        if not self._require_license_feature("multi_database"):
            return
        base_dir = os.path.dirname(os.path.abspath(self.db.db_path)) if self.db and self.db.db_path else None
        default_path = resolve_new_database_filename(base_dir)
        new_path, _ = QFileDialog.getSaveFileName(
            self, "ایجاد فایل پایگاه دادهٔ جدید", default_path,
            "پایگاه داده SQLite (*.db)"
        )
        if new_path:
            self._switch_to_database_path(new_path, create_if_missing=True)

    def _connect_existing_db(self):
        if not self._require_license_feature("multi_database"):
            return
        ext_path, _ = QFileDialog.getOpenFileName(
            self, "انتخاب فایل پایگاه دادهٔ موجود", "",
            "پایگاه داده SQLite (*.db *.sqlite *.sqlite3)"
        )
        if ext_path:
            self._switch_to_database_path(ext_path)

    def _confirm_password_policy_change(self, enabled):
        """Ask for explicit confirmation at the moment password enforcement is enabled."""
        if not enabled or bool(self.db.cfg.get("require_login_password", False)):
            return
        with self.db.get_connection() as conn:
            user_count = conn.execute(
                "SELECT COUNT(*) FROM employees"
            ).fetchone()[0]
            missing_passwords = conn.execute(
                """SELECT name FROM employees
                   WHERE is_active=1 AND (password IS NULL OR TRIM(password)='')
                   ORDER BY updated_at DESC, id DESC"""
            ).fetchall()
            active_user_count = conn.execute(
                "SELECT COUNT(*) FROM employees WHERE is_active=1"
            ).fetchone()[0]
        if user_count == 0:
            QMessageBox.information(
                self, "کاربری ثبت نشده",
                "برای فعال‌کردن اجبار ورود با رمز عبور، ابتدا حداقل یک کاربر در بخش «مدیریت کاربران» ثبت کنید."
            )
            self.chk_req_pass.blockSignals(True)
            self.chk_req_pass.setChecked(False)
            self.chk_req_pass.blockSignals(False)
            return
        if active_user_count == 0:
            impact_text = (
                "در حال حاضر کاربر فعالی وجود ندارد. این الزام برای کاربران فعال‌شده در آینده اعمال خواهد شد."
            )
        elif missing_passwords:
            names = "\n".join(f"• {row['name']}" for row in missing_passwords)
            impact_text = (
                "کارکنان زیر رمز عبور ندارند و پس از فعال‌سازی این قابلیت تا زمان تعریف رمز "
                "نمی‌توانند وارد برنامه شوند:\n\n"
                f"{names}"
            )
        else:
            impact_text = (
                "تمام کارکنان فعال در حال حاضر رمز عبور دارند و با فعال‌سازی این گزینه "
                "ورود همهٔ آن‌ها با رمز عبور انجام خواهد شد."
            )
        message = (
            f"{impact_text}\n\n"
            "آیا از فعال‌کردن اجبار ورود با رمز عبور اطمینان دارید؟"
        )
        if not _ask_yes_no(self, "تأیید اجبار ورود با رمز عبور", message):
            self.chk_req_pass.blockSignals(True)
            self.chk_req_pass.setChecked(False)
            self.chk_req_pass.blockSignals(False)

    def _save_general_settings(self):
        effective_password_policy = self.chk_req_pass.isChecked()

        # Check calendar/time format change
        current_stored_cal = self.db.get_setting("calendar_format", "jalali") or "jalali"
        current_stored_time = self.db.get_setting("time_format", "24h") or "24h"
        target_cal = self.cb_calendar_format.currentData() if hasattr(self, "cb_calendar_format") else current_stored_cal
        target_time = self.cb_time_format.currentData() if hasattr(self, "cb_time_format") else current_stored_time

        cal_time_changed = (target_cal != current_stored_cal or target_time != current_stored_time)
        perform_historical_migration = False

        if cal_time_changed:
            if not self._require_license_feature("custom_calendar_formats"):
                return
            dlg = DatetimeMigrationChoiceDialog(
                from_cal=current_stored_cal,
                to_cal=target_cal,
                from_time=current_stored_time,
                to_time=target_time,
                parent=self,
            )
            dlg.exec()
            if dlg.choice == DatetimeMigrationChoiceDialog.CANCEL:
                return
            elif dlg.choice == DatetimeMigrationChoiceDialog.MIGRATE_ALL:
                perform_historical_migration = True

        if perform_historical_migration:
            migrate_res = migrate_database_datetime(self.db, target_cal, target_time, create_backup=True)
            if migrate_res.get("status") == "error":
                QMessageBox.critical(self, "خطا در تبدیل اطلاعات", "خطایی در تبدیل تاریخ اطلاعات قبلی رخ داد.")
                return

        try:
            # Apply taxonomy edits and persist the new configuration atomically.
            # Existing product rows are renamed only after the explicit Save action.
            with self.db.get_connection() as conn:
                for old_category, new_category in self._pending_category_renames:
                    conn.execute(
                        "UPDATE products SET category=? WHERE category=?",
                        (new_category, old_category),
                    )

                # Match subcategory aliases by normalized Persian spelling so
                # existing rows with/without ZWNJ are moved to one canonical label.
                for category, old_subcategory, new_subcategory in self._pending_subcategory_renames:
                    rows = conn.execute(
                        "SELECT id, sub_category FROM products WHERE category=?",
                        (category,),
                    ).fetchall()
                    for row in rows:
                        if normalize_catalog_label(row["sub_category"]) == normalize_catalog_label(old_subcategory):
                            conn.execute(
                                "UPDATE products SET sub_category=? WHERE id=?",
                                (new_subcategory, row["id"]),
                            )

                for category, old_name, new_name, old_scope, new_scope in self._pending_attribute_renames:
                    if not old_name or not new_name or old_name == new_name:
                        continue
                    product_rows = conn.execute(
                        "SELECT id, sub_category, specs_json FROM products WHERE category=?",
                        (category,),
                    ).fetchall()
                    old_scope_key = normalize_catalog_label(old_scope)
                    new_scope_key = normalize_catalog_label(new_scope)
                    relevant_scope_keys = {key for key in (old_scope_key, new_scope_key) if key}
                    old_name_key = normalize_catalog_label(old_name)
                    new_name_key = normalize_catalog_label(new_name)
                    for product_row in product_rows:
                        if relevant_scope_keys and normalize_catalog_label(product_row["sub_category"]) not in relevant_scope_keys:
                            continue
                        try:
                            specs = json.loads(product_row["specs_json"] or "{}")
                        except (TypeError, ValueError, json.JSONDecodeError):
                            continue
                        if not isinstance(specs, dict):
                            continue
                        matching_keys = [
                            key for key in specs
                            if normalize_catalog_label(key) == old_name_key
                        ]
                        if not matching_keys and old_name_key == new_name_key:
                            matching_keys = [
                                key for key in specs
                                if normalize_catalog_label(key) == new_name_key
                            ]
                        if not matching_keys:
                            continue
                        values = [specs[key] for key in matching_keys]
                        if new_name in specs and new_name not in matching_keys:
                            values.append(specs[new_name])
                        text_values = list(dict.fromkeys(
                            str(value).strip() for value in values
                            if value is not None and str(value).strip()
                        ))
                        for key in matching_keys:
                            specs.pop(key, None)
                        if text_values:
                            specs[new_name] = " ".join(text_values)
                        conn.execute(
                            "UPDATE products SET specs_json=? WHERE id=?",
                            (json.dumps(specs, ensure_ascii=False), product_row["id"]),
                        )

                # Colour is a batch attribute. Keep each invoice's own colour snapshot,
                # while applying a catalogue rename consistently to existing records.
                if self._pending_color_renames:
                    for table_name in ("batches", "sales"):
                        rows = conn.execute(
                            f"SELECT id, colors_json FROM {table_name}"
                        ).fetchall()
                        for row in rows:
                            try:
                                colors = json.loads(row["colors_json"] or "[]")
                            except (TypeError, ValueError, json.JSONDecodeError):
                                colors = []
                            if not isinstance(colors, list):
                                continue
                            changed = False
                            renamed = []
                            for color in colors:
                                value = str(color).strip()
                                for old_color, new_color in self._pending_color_renames:
                                    if normalize_catalog_label(value) == normalize_catalog_label(old_color):
                                        value = new_color
                                        changed = True
                                        break
                                renamed.append(value)
                            unique_colors = []
                            seen_color_keys = set()
                            for color in renamed:
                                key = normalize_catalog_label(color)
                                if key and key not in seen_color_keys:
                                    unique_colors.append(color)
                                    seen_color_keys.add(key)
                            if changed or unique_colors != colors:
                                conn.execute(
                                    f"UPDATE {table_name} SET colors_json=? WHERE id=?",
                                    (json.dumps(unique_colors, ensure_ascii=False), row["id"]),
                                )

                for old_type, new_type in self._pending_service_type_renames:
                    conn.execute(
                        "UPDATE service_catalog SET service_type=? WHERE service_type=?",
                        (new_type, old_type),
                    )
                self.db.save_product_catalog_config(self._taxonomy_draft, conn=conn)

                shop_name = self.ed_shop_name.text().strip() or "فروشگاه من"
                selected_export_columns = self._get_selected_inventory_export_columns()
                if not selected_export_columns:
                    raise ValueError("برای خروجی موجودی همکار دست‌کم یک ستون را انتخاب کنید.")
                self.db.set_setting("shop_name", shop_name, conn=conn)
                self.db.set_setting(
                    "colleague_inventory_export_columns",
                    json.dumps(selected_export_columns, ensure_ascii=False),
                    conn=conn,
                )
                self.db.set_setting("calendar_format", target_cal, conn=conn)
                self.db.set_setting("time_format", target_time, conn=conn)
                conn.commit()

            self.db.cfg["default_profit_pct"] = self.sp_set_profit.value()
            if hasattr(self, "sp_default_min_inventory"):
                self.db.cfg["default_min_inventory"] = self.sp_default_min_inventory.value()
            self.db.cfg["zero_append_count"] = int(self.cb_zero_count.currentData())
            self.db.cfg["default_window_maximized"] = self.cb_win_mode.currentData() == "1"
            self.db.cfg["require_login_password"] = effective_password_policy
            self.db.cfg["last_store_name"] = shop_name
            self.db.cfg["calendar_type"] = target_cal
            self.db.cfg["time_format"] = target_time
            self.db.cfg["app_version"] = APP_VERSION
            self._save_report_export_config_internal()
            self.db.set_db_config("auto_backup_enabled", self.chk_auto_bk.isChecked(), persist=False)
            self.db.set_db_config("auto_backup_interval_min", self.sp_bk_interval.value(), persist=False)
            self.db.set_db_config("auto_backup_retention_count", self.sp_bk_retention.value(), persist=False)
            if hasattr(self, "ed_auto_bk_dir") and self.ed_auto_bk_dir.text().strip():
                try:
                    self.db.set_automatic_backup_directory(self.ed_auto_bk_dir.text().strip(), persist=False)
                except Exception as bke:
                    QMessageBox.warning(self, "خطای پوشه پشتیبان‌گیری", str(bke))
            else:
                self.db.cfg["backup_dir"] = os.path.dirname(os.path.abspath(self.db.db_path)) or "."

            if self._staged_db_password_action:
                action = self._staged_db_password_action.get("action")
                busy_dlg = None
                try:
                    if hasattr(self, "btn_save_settings"):
                        self.btn_save_settings.setEnabled(False)
                    if hasattr(self, "btn_cancel_settings"):
                        self.btn_cancel_settings.setEnabled(False)
                    QApplication.setOverrideCursor(Qt.WaitCursor)
                    busy_dlg = QDialog(self)
                    busy_dlg.setWindowTitle("اعمال تنظیمات امنیتی")
                    busy_dlg.setWindowModality(Qt.WindowModal)
                    busy_dlg.setLayoutDirection(Qt.RightToLeft)
                    busy_dlg.setFixedSize(380, 110)
                    busy_l = QVBoxLayout(busy_dlg)
                    busy_l.setContentsMargins(16, 16, 16, 16)
                    busy_l.setSpacing(10)
                    lbl_busy = QLabel("لطفاً چند لحظه صبر کنید...\nدر حال اعمال رمز عبور و ذخیره تنظیمات...")
                    lbl_busy.setAlignment(Qt.AlignCenter)
                    lbl_busy.setStyleSheet("font-size: 10pt; font-weight: bold; color: #0284c7;")
                    busy_l.addWidget(lbl_busy)
                    apply_dialog_theme(busy_dlg, parent=self)
                    busy_dlg.show()
                    QApplication.processEvents()

                    if action == "set":
                        req = self._staged_db_startup_prompt if self._staged_db_startup_prompt is not None else self._staged_db_password_action.get("req_startup", True)
                        self.db.set_database_password(self._staged_db_password_action["new_pwd"], require_startup_prompt=bool(req))
                    elif action == "change":
                        self.db.change_database_password(
                            self._staged_db_password_action["old_pwd"],
                            self._staged_db_password_action["new_pwd"],
                        )
                        if self._staged_db_startup_prompt is not None:
                            self.db.set_startup_password_prompt_required(self._staged_db_startup_prompt)
                    elif action == "remove":
                        self.db.remove_database_password(self._staged_db_password_action["pwd"])
                    self._staged_db_password_action = None
                finally:
                    if busy_dlg:
                        busy_dlg.close()
                    QApplication.restoreOverrideCursor()
                    if hasattr(self, "btn_save_settings"):
                        self.btn_save_settings.setEnabled(True)
                    if hasattr(self, "btn_cancel_settings"):
                        self.btn_cancel_settings.setEnabled(True)
            elif self._staged_db_startup_prompt is not None and self.db.is_password_protected():
                self.db.set_startup_password_prompt_required(self._staged_db_startup_prompt)
            self._staged_db_startup_prompt = None

            self.db._merge_disk_databases_into_cfg()
            save_app_config(self.db.cfg)
        except Exception as exc:
            QMessageBox.critical(self, "خطا در ذخیره تنظیمات", str(exc))
            return

        self.setWindowTitle(_window_title(shop_name))
        if hasattr(self, "lbl_store_name"):
            self.lbl_store_name.setText(bidi_isolate_text(f"دقیق | {shop_name}"))
            self.lbl_store_name.setToolTip(f"نام فروشگاه: {shop_name}")

        self._apply_product_catalog_config()
        self._sync_date_widgets_calendar()
        self._update_clock()
        self.refresh_all_data()
        if hasattr(self, "_on_rep_preset_changed"):
            self._on_rep_preset_changed()
        self._clear_batch_form()
        self._clear_sale_form()
        self._clear_upgrade_form()
        self._refresh_multi_db_combo()
        self._restart_backup_timer()
        self._refresh_visual_layout()
        self._load_general_settings_form()
        self._settings_snapshot = SettingsSnapshot(self)
        if hasattr(self, "_catalog_settings_state") and self._catalog_settings_state is not None:
            self._catalog_settings_state.capture_from_window(self)
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
        if not self._require_license_feature("manual_backup_restore"):
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "ذخیره فایل پشتیبان",
            f"Backup_{self.get_today_date_str().replace('/', '')}.db",
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
        if not self._require_license_feature("manual_backup_restore"):
            return
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
        self._sync_reports_tab_combo()
        self._update_report_live()
        self._apply_employee_permissions()
        if self._tables_auto_fit:
            self._reapply_auto_table_widths()

    def _refresh_combos(self):
        with self.db.get_connection() as conn:
            prods = conn.execute(
                """SELECT id, code, name, category, sub_category, brand, model, specs_json, description,
                      reorder_point, default_profit_pct, is_active, created_at, updated_at FROM products WHERE is_active=1 ORDER BY updated_at DESC, id DESC"""
            ).fetchall()
            emps = conn.execute(
                "SELECT id, name, role, phone, is_active, permissions, password, created_at, updated_at FROM employees WHERE is_active=1 ORDER BY updated_at DESC, id DESC"
            ).fetchall()
            visible_employee_ids = self._visible_employee_ids()
            if visible_employee_ids is not None:
                emps = [
                    employee for employee in emps
                    if int(employee["id"]) in visible_employee_ids
                ]
                if visible_employee_ids:
                    allowed_ids = tuple(sorted(visible_employee_ids))
                    marks = ",".join("?" for _ in allowed_ids)
                    sups = conn.execute(
                        f"""SELECT DISTINCT s.id, s.name, s.phone, s.address, s.notes, s.created_at, s.updated_at
                            FROM suppliers s JOIN batches b ON b.supplier_id=s.id
                            WHERE b.buyer_employee_id IN ({marks})
                            ORDER BY s.updated_at DESC, s.id DESC""",
                        allowed_ids,
                    ).fetchall()
                else:
                    sups = []
            else:
                sups = conn.execute(
                    "SELECT id, name, phone, address, notes, created_at, updated_at "
                    "FROM suppliers ORDER BY updated_at DESC, id DESC"
                ).fetchall()
            srvs = conn.execute(
                """SELECT id, code, service_type, name, default_fee, default_side_cost, description,
                      is_active, created_at, updated_at FROM service_catalog WHERE is_active=1 ORDER BY updated_at DESC, id DESC"""
            ).fetchall()
            batches = conn.execute(
                """
                SELECT b.id, b.batch_code, b.product_id, b.supplier_id, b.buyer_employee_id,
                       b.invoice_number, b.purchase_date, b.initial_qty, b.sold_qty, b.returned_qty,
                       b.remaining_qty, b.unit_purchase_price, b.extra_cost_total, b.upgrade_cost_unit,
                       b.unit_cost_price, b.suggested_sell_price, b.profit_pct, b.paid_amount,
                       b.settlement_status, b.serial_numbers, b.colors_json, b.initial_specs,
                       b.final_specs, b.supplier_name_snapshot, b.notes, b.created_at, b.updated_at,
                       p.code AS p_code, p.category, p.sub_category, p.brand, p.model
                FROM batches b
                JOIN products p ON b.product_id=p.id
                ORDER BY b.updated_at DESC, b.id DESC
            """
            ).fetchall()
            if visible_employee_ids is not None:
                batches = [
                    batch for batch in batches
                    if batch["buyer_employee_id"] is not None
                    and int(batch["buyer_employee_id"]) in visible_employee_ids
                ]
            # Keep products with historical sales selectable for invoice editing.
            sale_product_ids = {row["product_id"] for row in batches}

        # بند ۳: قرار دادن دسته‌بندی و زیرگروه در متن آیتم‌های کمبوباکس کالا برای جست‌وجوی مستقیم (مثلاً تایپ «کیبورد»)
        self.cb_batch_prod.blockSignals(True)
        self.cb_sale_prod.blockSignals(True)
        self.cb_batch_prod.clear()
        self.cb_sale_prod.clear()
        self.cb_sale_prod.addItem("همه کالاها", {"_all_products": True})
        self.cb_sale_prod.setItemSearchText(0, "همه کالاها همه محصولات تمام کالاها")
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
        if self.cb_batch_prod.count():
            self.cb_batch_prod.setCurrentIndex(0)
            self._on_batch_prod_changed()
        self.cb_sale_prod.setCurrentIndex(0)
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
            self._select_default_operator(cb)

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
            batch_scope, scope_params = self._employee_scope_filter("b.buyer_employee_id")
            batch_join = "LEFT JOIN batches b ON p.id = b.product_id"
            if batch_scope is not None:
                batch_join += f" AND {batch_scope}"
            rows = conn.execute(f"""
                SELECT p.id, p.code, p.name, p.category, p.sub_category, p.brand, p.model,
                       p.specs_json, p.description, p.reorder_point, p.default_profit_pct,
                       p.is_active, p.serial_number, p.created_at, p.updated_at,
                       COALESCE(SUM(b.remaining_qty), 0) as rem_qty,
                       COALESCE(SUM(b.sold_qty), 0) as sold_qty
                FROM products p
                {batch_join}
                GROUP BY p.id ORDER BY p.updated_at DESC, p.id DESC
            """, scope_params).fetchall()

        data = []
        for r in rows:
            specs = json.loads(r["specs_json"] or "{}")
            specs_str = self._format_specs_for_display(specs, r["category"])
            search_pool = f"{r['code']} {r['serial_number'] or ''} {r['category']} {r['sub_category']} {r['brand']} {r['model']} {specs_str} {r['description']}".lower()
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
                    r["serial_number"] or "",
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
        self._populate_table_safely(self.tbl_products, data, highlight_col=12)

    def _refresh_batches_table(self):
        with self.db.get_connection() as conn:
            rows = self._execute_scoped_query(conn, """
                SELECT b.id, b.batch_code, b.product_id, b.supplier_id, b.buyer_employee_id,
                       b.invoice_number, b.purchase_date, b.initial_qty, b.sold_qty, b.returned_qty,
                       b.remaining_qty, b.unit_purchase_price, b.extra_cost_total, b.upgrade_cost_unit,
                       b.unit_cost_price, b.suggested_sell_price, b.profit_pct, b.paid_amount,
                       b.settlement_status, b.serial_numbers, b.colors_json, b.initial_specs,
                       b.final_specs, b.supplier_name_snapshot, b.notes, b.created_at, b.updated_at,
                       p.code as p_code, p.category, p.sub_category, p.brand, p.model,
                       COALESCE(sup.name,b.supplier_name_snapshot) as sup_name, e.name as emp_name
                FROM batches b
                JOIN products p ON b.product_id=p.id
                LEFT JOIN suppliers sup ON b.supplier_id=sup.id
                LEFT JOIN employees e ON b.buyer_employee_id=e.id
                ORDER BY b.updated_at DESC, b.id DESC
            """, "b.buyer_employee_id").fetchall()
        data = []
        for r in rows:
            tot_bill = (r["unit_purchase_price"] * r["initial_qty"]) + r["extra_cost_total"]
            debt = receivable_balance(
                tot_bill, r["paid_amount"], r["settlement_status"]
            )
            prod_title = self._format_product_picker_label(dict(r))
            data.append(
                [
                    r["id"],
                    r["batch_code"],
                    r["p_code"],
                    r["serial_numbers"] or "-",
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
                    r["initial_specs"] or "-",
                    f"{tot_bill:,}",
                    "، ".join(self._decode_colors(r["colors_json"])) or "-",
                ]
            )
        self._populate_table_safely(self.tbl_batches, data, highlight_col=18)

    def _refresh_sales_table(self):
        with self.db.get_connection() as conn:
            rows = self._execute_scoped_query(conn, """
                SELECT s.id, s.invoice_number, s.product_id, s.batch_id, s.seller_employee_id,
                       s.customer_name, s.customer_phone, s.qty, s.returned_qty, s.suggested_unit_price,
                       s.actual_unit_price, s.unit_cost_price, s.unit_discount, s.total_discount,
                       s.price_Markup_unit, s.unit_profit, s.total_profit, s.total_amount,
                       s.paid_amount, s.settlement_status, s.sale_datetime, s.warranty_company,
                       s.warranty_start, s.warranty_months, s.warranty_days, s.warranty_end,
                       s.serial_number, s.specifications, s.colors_json, s.notes,
                       s.created_at, s.updated_at, p.code as p_code, p.category,
                       p.sub_category, p.brand, p.model, b.batch_code, b.final_specs,
                       b.initial_specs, e.name as emp_name
                FROM sales s
                JOIN products p ON s.product_id=p.id
                JOIN batches b ON s.batch_id=b.id
                LEFT JOIN employees e ON s.seller_employee_id=e.id
                ORDER BY s.updated_at DESC, s.id DESC
            """, "s.seller_employee_id").fetchall()
        data = []
        for r in rows:
            war_str = (
                f"{r['warranty_company']} ({r['warranty_end']})".strip()
                if r["warranty_company"] or r["warranty_end"]
                or r["warranty_months"] or r["warranty_days"]
                else ""
            )
            product_prefix = str(r["sub_category"] or r["category"] or "").strip()
            brand_model = " ".join(
                value for value in (str(r["brand"] or "").strip(), str(r["model"] or "").strip())
                if value
            )
            prod_title = " | ".join(
                value for value in (product_prefix, brand_model) if value
            )
            signed_diff = format_Signed_diff(
                r["actual_unit_price"], r["suggested_unit_price"], r["qty"]
            )
            data.append(
                [
                    r["id"],
                    r["invoice_number"],
                    r["p_code"],
                    r["serial_number"] or "",
                    prod_title,
                    r["sale_datetime"],
                    r["batch_code"],
                    r["emp_name"],
                    r["customer_name"] or "",
                    r["customer_phone"] or "",
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
                    r["specifications"] or r["final_specs"] or r["initial_specs"] or "-",
                    "، ".join(self._decode_colors(r["colors_json"])) or "-",
                ]
            )
        self._populate_table_safely(self.tbl_sales, data, highlight_col=19)

    def _refresh_upgrades_table(self):
        with self.db.get_connection() as conn:
            rows = self._execute_scoped_query(conn, """
                SELECT u.id, u.target_batch_id, u.part_batch_id, u.technician_id, u.target_qty,
                       u.part_qty_used, u.stock_deducted_qty, u.part_unit_cost, u.labor_cost_unit,
                       u.added_cost_unit, u.upgrade_date, u.serial_number, u.manual_part_description,
                       u.old_specs, u.new_specs, u.notes, u.created_at, u.updated_at,
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
            """, "u.technician_id", "b1.buyer_employee_id").fetchall()
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
                """SELECT id, code, service_type, name, default_fee, default_side_cost, description,
                      is_active, created_at, updated_at FROM service_catalog WHERE is_active=1 ORDER BY updated_at DESC, id DESC"""
            ).fetchall()
            rec_rows = self._execute_scoped_query(conn, """
                SELECT sr.id, sr.invoice_number, sr.service_id, sr.seller_employee_id,
                       sr.technician_employee_id, sr.service_type, sr.service_name,
                       sr.customer_name, sr.historical_tariff, sr.service_fee, sr.side_cost,
                       sr.paid_amount, sr.net_profit, sr.settlement_status, sr.service_datetime,
                       sr.description, sr.created_at, sr.updated_at, e.name as emp_name
                FROM service_records sr
                LEFT JOIN employees e ON sr.seller_employee_id=e.id
                ORDER BY sr.updated_at DESC, sr.id DESC
            """, "sr.seller_employee_id", "sr.technician_employee_id").fetchall()

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
                (
                    f"{service_financial_breakdown(r['service_fee'], r['paid_amount'], r['settlement_status'])[0]:+,}"
                    if service_financial_breakdown(
                        r["service_fee"], r["paid_amount"], r["settlement_status"]
                    )[0] else "0"
                ),
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
            rows = self._execute_scoped_query(conn, """
                SELECT s.id, s.name, s.phone, s.address, s.notes, s.created_at, s.updated_at,
                       COUNT(b.id) as b_cnt,
                       COALESCE(SUM(b.unit_purchase_price*b.initial_qty + b.extra_cost_total), 0) as tot_buy,
                       COALESCE(SUM(b.paid_amount), 0) as tot_paid,
                       COALESCE(SUM(
                           CASE
                               WHEN b.settlement_status IN ('تسویه جزئی', 'تسویه‌نشده')
                               THEN MAX(
                                   0,
                                   b.unit_purchase_price * b.initial_qty
                                   + COALESCE(b.extra_cost_total, 0)
                                   - COALESCE(b.paid_amount, 0)
                               )
                               ELSE 0
                           END
                       ), 0) AS tot_debt
                FROM suppliers s
                LEFT JOIN batches b ON s.id = b.supplier_id
                GROUP BY s.id
                ORDER BY s.updated_at DESC, s.id DESC
            """, "b.buyer_employee_id").fetchall()
        data = []
        for r in rows:
            debt = int(r["tot_debt"] or 0)
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
        cal = self.get_active_calendar()
        tf = self.get_active_time_format()
        with self.db.get_connection() as conn:
            rows = self._execute_scoped_query(
                conn,
                "SELECT id, name, role, phone, is_active, permissions, password, created_at, updated_at, last_login_at "
                "FROM employees ORDER BY updated_at DESC, id DESC",
                "id",
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
                format_iso_to_jalali(r["created_at"], cal_type=cal, time_fmt=tf),
                format_iso_to_jalali(r["updated_at"], cal_type=cal, time_fmt=tf),
                format_iso_to_jalali(r["last_login_at"], cal_type=cal, time_fmt=tf),
            ]
            for r in rows
        ]
        self._populate_table_safely(self.tbl_employees, data)

    def _refresh_dashboard(self):
        today = self.get_today_date_str()
        visible_employee_ids = self._visible_employee_ids()
        scoped = visible_employee_ids is not None
        permissions = self._permission_policy(self.active_employee.get("permissions") or "") if scoped and self.active_employee else ""
        sales_role = "فروش و خدمات" in permissions
        warehouse_role = "ثبت خرید و انبارداری" in permissions

        with self.db.get_connection() as conn:
            if scoped:
                ids = tuple(sorted(visible_employee_ids))
                if ids:
                    marks = ",".join("?" for _ in ids)
                    sales_today = (
                        {"cnt": 0, "amt": 0, "prof": 0}
                        if warehouse_role else conn.execute(
                            f"""SELECT COUNT(*) AS cnt,
                                COALESCE(SUM(total_amount),0) AS amt,
                                COALESCE(SUM(total_profit),0) AS prof
                                FROM sales
                                WHERE substr(sale_datetime,1,10)=?
                                  AND seller_employee_id IN ({marks})""",
                            (today, *ids),
                        ).fetchone()
                    )
                    service_profit_today = (
                        0 if warehouse_role else conn.execute(
                            f"""SELECT COALESCE(SUM(net_profit),0)
                                FROM service_records
                                WHERE substr(service_datetime,1,10)=?
                                  AND (seller_employee_id IN ({marks})
                                       OR technician_employee_id IN ({marks}))""",
                            (today, *ids, *ids),
                        ).fetchone()[0]
                    )
                    purchase_today = (
                        0 if sales_role else conn.execute(
                            f"""SELECT COALESCE(SUM(unit_purchase_price*initial_qty+extra_cost_total),0)
                                FROM batches WHERE substr(purchase_date,1,10)=? AND buyer_employee_id IN ({marks})""",
                            (today, *ids),
                        ).fetchone()[0]
                    )
                    employee_performance = conn.execute(
                        f"""SELECT e.name, COUNT(s.id) AS cnt,
                            COALESCE(SUM(s.total_amount),0) AS amt,
                            COALESCE(SUM(s.total_discount),0) AS disc,
                            COALESCE(SUM(s.total_profit),0) AS prof
                            FROM employees e LEFT JOIN sales s ON e.id=s.seller_employee_id
                            WHERE e.id IN ({marks}) GROUP BY e.id
                            ORDER BY e.name COLLATE NOCASE""",
                        ids,
                    ).fetchall()
                    total_stock = conn.execute(
                        f"SELECT COALESCE(SUM(remaining_qty),0) FROM batches WHERE buyer_employee_id IN ({marks})",
                        ids,
                    ).fetchone()[0]
                    supplier_debt = conn.execute(
                        f"""SELECT COALESCE(SUM(CASE
                            WHEN settlement_status IN ('تسویه جزئی', 'تسویه‌نشده')
                            THEN MAX(0, unit_purchase_price*initial_qty
                                     + COALESCE(extra_cost_total,0)-COALESCE(paid_amount,0))
                            ELSE 0 END),0)
                            FROM batches WHERE buyer_employee_id IN ({marks})""",
                        ids,
                    ).fetchone()[0]
                    low_products = conn.execute(
                        f"""SELECT p.code,p.category,p.sub_category,p.brand,p.model,p.specs_json,p.reorder_point,
                            COALESCE(SUM(b.remaining_qty),0) AS rem,
                            COALESCE((
                                SELECT GROUP_CONCAT(batch_code, ', ')
                                FROM (
                                    SELECT batch_code FROM batches b2
                                    WHERE b2.product_id=p.id AND b2.buyer_employee_id IN ({marks})
                                    ORDER BY b2.updated_at DESC, b2.id DESC
                                )
                            ), '') AS batch_codes
                            FROM products p LEFT JOIN batches b
                              ON b.product_id=p.id AND b.buyer_employee_id IN ({marks})
                            GROUP BY p.id HAVING rem<=p.reorder_point
                            ORDER BY p.updated_at DESC, p.id DESC""",
                        (*ids, *ids),
                    ).fetchall()
                else:
                    sales_today = {"cnt": 0, "amt": 0, "prof": 0}
                    service_profit_today = purchase_today = total_stock = supplier_debt = 0
                    employee_performance = []
                    low_products = []
            else:
                sales_today = conn.execute(
                    """SELECT COUNT(*) AS cnt, COALESCE(SUM(total_amount),0) AS amt,
                       COALESCE(SUM(total_profit),0) AS prof
                       FROM sales WHERE substr(sale_datetime,1,10)=?""",
                    (today,),
                ).fetchone()
                purchase_today = conn.execute(
                    """SELECT COALESCE(SUM(unit_purchase_price*initial_qty+extra_cost_total),0)
                       FROM batches WHERE substr(purchase_date,1,10)=?""",
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
                    """SELECT COALESCE(SUM(
                           CASE
                               WHEN settlement_status IN ('تسویه جزئی', 'تسویه‌نشده')
                               THEN MAX(
                                   0,
                                   unit_purchase_price*initial_qty
                                   + COALESCE(extra_cost_total, 0)
                                   - COALESCE(paid_amount, 0)
                               )
                               ELSE 0
                           END
                       ), 0) FROM batches"""
                ).fetchone()[0]
                low_products = conn.execute(
                    """SELECT p.code,p.category,p.sub_category,p.brand,p.model,p.specs_json,p.reorder_point,
                        COALESCE(SUM(b.remaining_qty),0) AS rem,
                        COALESCE((
                            SELECT GROUP_CONCAT(batch_code, ', ')
                            FROM (
                                SELECT batch_code FROM batches b2
                                WHERE b2.product_id=p.id
                                ORDER BY b2.updated_at DESC, b2.id DESC
                            )
                        ), '') AS batch_codes
                        FROM products p LEFT JOIN batches b ON p.id=b.product_id
                        GROUP BY p.id HAVING rem<=p.reorder_point
                        ORDER BY p.updated_at DESC, p.id DESC"""
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

        dashboard_values = (
            (self.lbl_dash_sales_today, int(sales_today["amt"]), "#1d4ed8"),
            (self.lbl_dash_profit_today, int(sales_today["prof"]), "#047857"),
            (self.lbl_dash_buy_today, int(purchase_today), "#b45309"),
            (self.lbl_dash_srv_profit, int(service_profit_today), "#4338ca"),
        )
        for label, amount, default_color in dashboard_values:
            label.setText(f"{amount:,}")
            color = "#dc2626" if amount < 0 else default_color
            label.setStyleSheet(
                f"color: {color}; background: transparent; "
                "font-size: 18px; font-weight: bold;"
            )
        self.lbl_dash_count_today.setText(str(sales_today["cnt"]))

        self.lbl_dash_total_stock.setText("—" if total_stock is None else f"{int(total_stock):,}")
        self.lbl_dash_low_stock.setText("—" if low_products is None else str(len(low_products)))
        self.lbl_dash_unpaid_supplier.setText(
            "—" if supplier_debt is None else f"{max(0, int(supplier_debt)):,}"
        )
        self.lbl_dash_unpaid_supplier.setStyleSheet(
            "color: #dc2626; background: transparent; "
            "font-size: 18px; font-weight: bold;"
        )

        low_data = []
        for row in low_products:
            status = "ناموجود" if int(row["rem"]) == 0 else "کم‌موجود"
            brand_model = f"{row['brand']} {row['model']}".strip()
            product_details = " / ".join(
                value for value in (
                    row["sub_category"] or "",
                    row["category"] or "",
                    brand_model,
                ) if value
            ) or "-"
            try:
                product_specs = json.loads(row["specs_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                product_specs = {}
            specs_text = self._format_specs_for_display(
                product_specs if isinstance(product_specs, dict) else {},
                row["category"],
            )
            low_data.append([
                row["code"], row["batch_codes"] or "-", product_details,
                specs_text or "-", row["rem"], row["reorder_point"], status,
            ])
        self._populate_table_safely(self.tbl_dash_low, low_data, highlight_col=6)

        employee_data = [[
            row["name"], row["cnt"], f"{int(row['amt']):,}",
            f"{int(row['disc']):,}", f"{int(row['prof']):,}",
        ] for row in employee_performance]
        self._populate_table_safely(self.tbl_dash_emp, employee_data)




def _run_smoke_launch_db(app: QApplication, db_path: str, mode: str = "create") -> int:
    """Non-interactive post-DB MainWindow launch verification for compiled-binary CI tests.

    Never unlocks interactive user usage: destroys MainWindow and exits after 1.5s Qt event loop.
    """
    from types import SimpleNamespace

    smoke_mode = (mode or "create").strip().lower()
    if smoke_mode not in ("create", "existing"):
        print(f"DAQIQ_SMOKE_LAUNCH_ERROR: Invalid --smoke-launch-mode: {mode!r}", file=sys.stderr, flush=True)
        return 1

    target_db = os.path.abspath(os.path.expanduser(db_path))
    db = None
    win = None
    try:
        dlg = DatabaseBootstrapDialog(target_db)
        if smoke_mode == "existing":
            dlg.rb_existing.setChecked(True)
        else:
            dlg.rb_create.setChecked(True)
        dlg.ed_path.setText(target_db)
        dlg._validate_and_accept()
        if dlg.result() != QDialog.Accepted or not dlg.selected_path:
            print("DAQIQ_SMOKE_LAUNCH_ERROR: DatabaseBootstrapDialog validation failed.", file=sys.stderr, flush=True)
            return 1
        chosen = os.path.abspath(dlg.selected_path)
        if smoke_mode == "create" or not os.path.isfile(chosen):
            created = create_and_initialize_database(chosen)
            try:
                created.close()
            except Exception:
                pass
        dlg.close()

        db = DatabaseManager(chosen)
        if db.is_password_protected():
            print("DAQIQ_SMOKE_LAUNCH_ERROR: Password-protected DB rejected in non-interactive smoke mode.", file=sys.stderr, flush=True)
            return 1
        active_emp, accepted = _resolve_startup_employee(db)
        if not accepted:
            print("DAQIQ_SMOKE_LAUNCH_ERROR: Employee login required in smoke DB.", file=sys.stderr, flush=True)
            return 1

        # Strictly ephemeral, input-locked, self-terminating smoke entitlement; never usable interactively.
        smoke_res = ValidationResult(
            status=ValidationStatus.VALID,
            is_valid=True,
            license=None,
            message_fa="smoke-check",
        )
        smoke_svc = SimpleNamespace(
            check_license=lambda force_reload=False: smoke_res,
            is_feature_enabled=lambda _feat: True,
            is_write_allowed=lambda: True,
            get_hardware_fingerprint=lambda: "fp_v1:smoke",
            get_active_key_fingerprints=lambda: [],
            store_name_provider=None,
        )

        win = MainWindow(db, active_emp, license_service=smoke_svc)
        win.setEnabled(False)
        win.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        win.setAttribute(Qt.WA_ShowWithoutActivating, True)
        win.setFocusPolicy(Qt.NoFocus)
        global _ACTIVE_MAIN_WINDOW
        _ACTIVE_MAIN_WINDOW = win
        win.show()

        import threading
        watchdog = threading.Timer(6.0, lambda: os._exit(2))
        watchdog.daemon = True
        watchdog.start()

        smoke_state = {"ok": False, "err": ""}

        def _finish_smoke():
            try:
                if win is None or not win.isVisible():
                    smoke_state["err"] = "MainWindow is not visible after 1.5s event loop."
                elif win.tabs.count() < 10:
                    smoke_state["err"] = f"Unexpected tab count: {win.tabs.count()}"
                else:
                    smoke_state["ok"] = True
            except Exception as exc:
                smoke_state["err"] = repr(exc)
            finally:
                try:
                    if win is not None:
                        win.close()
                except Exception:
                    pass
                app.quit()

        QTimer.singleShot(1500, _finish_smoke)
        try:
            app.exec()
        finally:
            watchdog.cancel()
        app.setQuitOnLastWindowClosed(True)

        if not smoke_state["ok"]:
            print(f"DAQIQ_SMOKE_LAUNCH_ERROR: {smoke_state['err']}", file=sys.stderr, flush=True)
            return 1

        print(
            f"DAQIQ_SMOKE_LAUNCH_OK: mode={smoke_mode} visible=True tabs={win.tabs.count()} db={chosen}",
            flush=True,
        )
        return 0
    except Exception as exc:
        write_crash_log(type(exc), exc, exc.__traceback__, context="smoke_launch_db")
        print(f"DAQIQ_SMOKE_LAUNCH_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        _ACTIVE_MAIN_WINDOW = None
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


def main():
    if "--print-paths" in sys.argv[1:]:
        try:
            print(format_resolved_paths_report(), flush=True)
        except OSError:
            pass
        sys.exit(0)

    install_native_fault_and_qt_loggers()

    smoke_log_file = None
    if os.environ.get("DAQIQ_SMOKE_TEST") == "1":
        try:
            smoke_log_file = os.environ.get("DAQIQ_SMOKE_LOG_PATH")
            if not smoke_log_file:
                exe_dir = str(get_executable_dir())
                smoke_log_file = os.path.join(exe_dir, "smoke_test.log")
            with open(smoke_log_file, "a", encoding="utf-8") as f:
                f.write("STEP 1: Entered main()\n")
        except Exception:
            pass

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            fn = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
            fn.argtypes = [wintypes.LPCWSTR]
            fn.restype = ctypes.c_long
            fn(f"ouncommono.Daqiq.{APP_VERSION}")
        except Exception:
            pass

    # Configure Qt library paths and platform plugins for Nuitka onefile and standalone
    try:
        import PySide6
        pyside_dir = os.path.dirname(PySide6.__file__)
        for sub in ["qt-plugins", "plugins", ""]:
            cand = os.path.join(pyside_dir, sub) if sub else pyside_dir
            if os.path.isdir(cand):
                QCoreApplication.addLibraryPath(cand)
                p_cand = os.path.join(cand, "platforms")
                if os.path.isdir(p_cand):
                    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = p_cand
    except Exception:
        pass

    app = QApplication.instance() or QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    font = QFont("Tahoma", 10)
    app.setFont(font)
    install_global_exception_hooks()
    app.setQuitOnLastWindowClosed(False)
    if not getattr(app, "_daqiq_msg_polisher", None):
        polisher = _MessageBoxPolisher(app)
        app.installEventFilter(polisher)
        app._daqiq_msg_polisher = polisher

    # Automated compiled-binary E2E launch smoke verification (--smoke-launch-db)
    if "--smoke-launch-db" in sys.argv[1:]:
        args = sys.argv[1:]
        idx = args.index("--smoke-launch-db")
        smoke_db = args[idx + 1] if idx + 1 < len(args) else ""
        smoke_mode = "create"
        if "--smoke-launch-mode" in args:
            m_idx = args.index("--smoke-launch-mode")
            if m_idx + 1 < len(args):
                smoke_mode = args[m_idx + 1]
        rc = _run_smoke_launch_db(app, smoke_db, mode=smoke_mode)
        app.setQuitOnLastWindowClosed(True)
        sys.exit(rc)

    if smoke_log_file:
        try:
            with open(smoke_log_file, "a", encoding="utf-8") as f:
                f.write("STEP 2: QApplication initialized\n")
        except Exception:
            pass

    icon_path = resource_path("assets/daqiq_logo.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Startup Offline Ed25519 Licensing Gate (Pre-DB, Pre-Login, Pre-MainWindow)
    license_service = LicenseService(app_version=APP_VERSION)
    if smoke_log_file:
        try:
            with open(smoke_log_file, "a", encoding="utf-8") as f:
                f.write("STEP 3: LicenseService instantiated\n")
        except Exception:
            pass

    val_res = license_service.check_license()
    if smoke_log_file:
        try:
            with open(smoke_log_file, "a", encoding="utf-8") as f:
                f.write(f"STEP 4: check_license completed ({val_res.status.value})\n")
        except Exception:
            pass

    if os.environ.get("DAQIQ_SMOKE_TEST") == "1":
        print(f"DAQIQ_SMOKE_TEST: Startup licensing gate successfully executed ({val_res.status.value}). Exiting.", flush=True)
        if smoke_log_file:
            try:
                with open(smoke_log_file, "a", encoding="utf-8") as f:
                    f.write("STEP 5: Clean exit sys.exit(0)\n")
            except Exception:
                pass
        app.setQuitOnLastWindowClosed(True)
        sys.exit(0)

    exit_code = 0
    try:
        if not val_res.is_valid:
            startup_cfg = load_app_config()
            startup_dark = startup_cfg.get("theme", "light") == "dark"
            dlg_icon = resource_path("assets/daqiq_logo.svg")
            if not os.path.exists(dlg_icon):
                dlg_icon = icon_path
            dlg = LicenseDialog(
                service=license_service,
                icon_path=dlg_icon if os.path.exists(dlg_icon) else None,
                is_dark_theme=startup_dark,
                is_startup_gate=True,
            )
            if dlg.exec() != QDialog.Accepted:
                app.setQuitOnLastWindowClosed(True)
                sys.exit(0)
            val_res = license_service.check_license(force_reload=True)
            if not val_res.is_valid:
                app.setQuitOnLastWindowClosed(True)
                sys.exit(0)

        selected_db_path = select_startup_database_path()
        if not selected_db_path:
            app.setQuitOnLastWindowClosed(True)
            sys.exit(0)
        db = DatabaseManager(selected_db_path)

        # Database Password Startup Check (Item 13, REQ-5)
        if db.is_password_protected() and not db.can_auto_unlock_locally():
            unlocked = False
            for _ in range(3):
                pwd, ok = _prompt_database_password(None, "رمز عبور پایگاه داده را وارد کنید:")
                if not ok:
                    break
                if db.verify_database_password(pwd):
                    unlocked = True
                    break
                else:
                    QMessageBox.warning(None, "رمز نادرست", "رمز عبور واردشده برای پایگاه داده صحیح نیست.")
            if not unlocked:
                app.setQuitOnLastWindowClosed(True)
                sys.exit(0)

        active_emp = None
        active_emp, accepted = _resolve_startup_employee(db)
        if not accepted:
            app.setQuitOnLastWindowClosed(True)
            sys.exit(0)

        win = MainWindow(db, active_emp, license_service=license_service)
        global _ACTIVE_MAIN_WINDOW
        _ACTIVE_MAIN_WINDOW = win
        if bool(db.cfg.get("default_window_maximized", True)):
            win.showMaximized()
        else:
            win.show()
        app.processEvents()
        app.setQuitOnLastWindowClosed(True)
        exit_code = app.exec()
    except Exception as exc:
        app.setQuitOnLastWindowClosed(True)
        handle_unhandled_exception(
            type(exc),
            exc,
            exc.__traceback__,
            context="main.startup",
            show_dialog=True,
        )
        sys.exit(1)
    finally:
        _ACTIVE_MAIN_WINDOW = None

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
