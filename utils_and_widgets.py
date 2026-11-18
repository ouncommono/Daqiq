# utils_and_widgets.py
import datetime
import re
import weakref
import html
import jdatetime
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QComboBox,
    QCompleter,
    QDialog,
    QGridLayout,
    QSpinBox,
    QGroupBox,
    QFormLayout,
    QScrollArea,
    QTableWidget,
    QListWidget,
    QAbstractItemView,
)
from PySide6.QtCore import (
    Qt,
    Signal,
    QModelIndex,
    QSortFilterProxyModel,
    QPropertyAnimation,
    QEasingCurve,
    QAbstractAnimation,
)
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QSizePolicy

PERSIAN_ARABIC_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

_LTR_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9._/+%-]*:|[A-Za-z][A-Za-z0-9._/+%-]*|\d+(?:[.,]\d+)?(?:[A-Za-z]+|%))"
)
_BIDI_CONTROL_RE = re.compile(r"[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def bidi_isolate_text(value) -> str:
    """Return clean logical text. Widgets choose paragraph direction; data stays unmarked."""
    text = "" if value is None else str(value)
    return _BIDI_CONTROL_RE.sub("", text).translate(
        dict.fromkeys(map(ord, "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"))
    )


def strip_bidi_controls(value) -> str:
    """Remove invisible directional controls before searching or parsing visible UI text."""
    return _BIDI_CONTROL_RE.sub("", "" if value is None else str(value))


def mixed_bidi_tooltip(value) -> str:
    """Render mixed Persian/English tooltip lines with explicit paragraph direction."""
    rendered = []
    for line in str(value or "").splitlines():
        direction = "ltr" if re.search(r"[A-Za-z]", line) else "rtl"
        alignment = "left" if direction == "ltr" else "right"
        rendered.append(
            f'<div dir="{direction}" align="{alignment}" '
            f'style="direction:{direction}; text-align:{alignment}; '
            f'width:100%; white-space:pre-wrap;">'
            f'{html.escape(line)}</div>'
        )
    return (
        '<html dir="rtl"><body dir="rtl" align="right" '
        'style="direction:rtl; text-align:right; width:100%; '
        'margin:0; padding:4px;">'
        + "".join(rendered)
        + "</body></html>"
    )


def normalize_catalog_label(value) -> str:
    """Canonical comparison key for Persian labels with optional spaces/ZWNJ."""
    text = "" if value is None else str(value)
    text = text.replace("\u064a", "\u06cc").replace("\u0643", "\u06a9")
    text = text.replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    return re.sub(r"\s+", "", text).casefold()


def _unique_catalog_labels(values):
    """Deduplicate labels by their normalized Persian/Latin spelling."""
    result = []
    seen = set()
    for value in values or []:
        label = str(value).strip()
        key = normalize_catalog_label(label)
        if label and key and key not in seen:
            seen.add(key)
            result.append(label)
    return result

# فهرست جامع دسته‌بندی‌های اصلی فروشگاه (بند ۱ و ۲)
MAIN_CATEGORIES = [
    "لپ‌تاپ",
    "قطعات",
    "لوازم جانبی",
    "مانیتور",
    "کیس و مینی‌کیس",
    "آداپتور و تغذیه",
    "شبکه و مودم",
    "ماشین‌های اداری",
    "سایر موارد",
]

# زیرمجموعه‌های پیش‌فرض برای شروع؛ پس از ذخیره قابل تغییر توسط هر فروشگاه هستند.
DEFAULT_SUBCATEGORIES = {
    "لپ‌تاپ": [
        "لپ‌تاپ عمومی / مالتی‌مدیا", "لپ‌تاپ گیمینگ (Gaming)",
        "لپ‌تاپ مهندسی و رندرینگ", "لپ‌تاپ استوک / صنعتی",
        "اولترابوک / تبلت‌شو", "مک‌بوک (MacBook)", "سایر موارد",
    ],
    "قطعات": [
        "پردازنده (CPU)", "رم کامپیوتر (RAM PC)",
        "رم لپ‌تاپ (RAM Laptop)", "حافظه اس‌اس‌دی (SSD)",
        "هارد دیسک اینترنال (HDD)", "کارت گرافیک (Graphic Card)",
        "مادربرد (Motherboard)", "پاور / منبع تغذیه کیس (Power)",
        "فن و خنک‌کننده (Cooling / Fan)", "صفحه‌نمایش لپ‌تاپ (LED / LCD Panel)",
        "باتری لپ‌تاپ (Laptop Battery)", "کیبورد تعمیراتی لپ‌تاپ (Internal Keyboard)",
        "قاب، لولا و فلت لپ‌تاپ", "کارت شبکه و صدا اینترنال",
        "درایو نوری (DVD RW / Caddy)", "سایر موارد",
    ],
    "لوازم جانبی": [
        "ماوس (Mouse)", "کیبورد (Keyboard)",
        "پک کمبو ماوس و کیبورد", "هدست، هدفون و هندزفری", "اسپیکر (Speaker)",
        "فلش مموری (Flash Memory)", "هارد اکسترنال (External HDD)",
        "اس‌اس‌دی اکسترنال (External SSD)", "کول‌پد لپ‌تاپ (Coolpad)",
        "کیف و کوله‌پشتی لپ‌تاپ", "هاب USB و Type-C",
        "کابل تصویر (HDMI / DisplayPort / VGA)", "کابل برق، شبکه و افزایش طول",
        "مبدل و دانگل (Converter / Dongle)", "ماوس‌پد (Mouse Pad)",
        "وب‌کم و میکروفون (Webcam / Mic)", "گیم‌پد و دسته بازی (Gamepad)",
        "خمیر سیلیکون و اسپری تمیزکننده", "سایر موارد",
    ],
    "مانیتور": [
        "مانیتور اداری و خانگی", "مانیتور گیمینگ (Gaming)",
        "مانیتور طراحی و صنعتی", "مانیتور استوک", "مانیتور منحنی (Curved)",
    ],
    "کیس و مینی‌کیس": [
        "مینی‌کیس استوک (Mini Case)", "کیس کامل اسمبل‌شده (PC)",
        "آل‌این‌وان (All-in-One)", "تین‌کلاینت (Thin Client)",
        "پوسته کیس خالی (Case Chassis)",
    ],
    "آداپتور و تغذیه": [
        "شارژر و آداپتور لپ‌تاپ", "آداپتور مانیتور و مینی‌کیس",
        "آداپتور مودم و سوئیچ (9V/12V)", "محافظ برق و چندراهی",
        "برق اضطراری (UPS) و باتری UPS", "کابل برق سهند / سه‌پین / دوپین",
    ],
    "شبکه و مودم": [
        "مودم ADSL / VDSL", "مودم سیم‌کارتی 4G / 5G / TD-LTE",
        "روتر و اکسس‌پوینت بی‌سیم", "سوئیچ شبکه (5/8/16/24 پورت)",
        "کارت شبکه USB / PCIe", "سایر موارد",
    ],
    "ماشین‌های اداری": [
        "پرینتر و چندکاره", "اسکنر", "کارتریج و تونر", "سایر موارد",
    ],
    "سایر موارد": ["سایر موارد"],
}

# فهرست جامع پردازنده‌های قدیمی و جدید (بند ۲)
# Broad CPU families and suffix patterns. The editable search field lets the user
# replace xxx with the exact SKU digits without maintaining an endless model catalogue.
CPU_LIST = [
    "",
    "Intel Celeron N4xxx / N5xxx",
    "Intel Celeron 4xxxU / 5xxxU",
    "Intel Pentium N5xxx / N6xxx",
    "Intel Pentium 6xxxU / 7xxxU",
    "Intel Processor N100 / N200 / N300",
    "Intel Core i3 Xxxx U / H / HQ",
    "Intel Core i5 Xxxx U / H / HQ / HK",
    "Intel Core i7 Xxxx U / H / HQ / HK / HX",
    "Intel Core i9 Xxxx H / HK / HX",
    "Intel Core Ultra 5 XxxV / XxxU / XxxH",
    "Intel Core Ultra 7 XxxV / XxxU / XxxH",
    "Intel Core Ultra 9 XxxV / XxxU / XxxH",
    "Intel Xeon E-Series",
    "Intel Xeon W-Series",
    "AMD Athlon 3xxxU / 3xxxG",
    "AMD Ryzen 3 XxxxU / XxxxG",
    "AMD Ryzen 5 XxxxU / XxxxH / XxxxHS / XxxxHX / XxxxG",
    "AMD Ryzen 7 XxxxU / XxxxH / XxxxHS / XxxxHX / XxxxG",
    "AMD Ryzen 9 XxxxHS / XxxxHX",
    "AMD Ryzen AI 5 / 7 / 9",
    "AMD Ryzen Threadripper Xxxx",
    "Apple M1",
    "Apple M2",
    "Apple M3",
    "Apple M4",

]

RAM_CAPACITIES = [
    "",
    "2GB",
    "4GB",
    "6GB",
    "8GB",
    "12GB",
    "16GB",
    "20GB",
    "24GB",
    "32GB",
    "48GB",
    "64GB",
    "128GB",
]

STORAGE_LIST = [
    "",
    "120GB SSD",
    "128GB SSD",
    "240GB SSD",
    "256GB SSD",
    "480GB SSD",
    "512GB SSD",
    "1TB SSD NVMe",
    "2TB SSD NVMe",
    "4TB SSD",
    "320GB HDD",
    "500GB HDD",
    "1TB HDD",
    "2TB HDD",
    "4TB HDD",
    "1TB HDD + 128GB SSD",
    "1TB HDD + 256GB SSD",
    "1TB HDD + 512GB SSD",
]

GPU_LIST = [
    "",
    "Intel HD / UHD Graphics (Onboard)",
    "Intel Iris Xe Graphics",
    "AMD Radeon Vega / Integrated",
    "NVIDIA GeForce MX110 / MX130 / MX150",
    "NVIDIA GeForce MX230 / MX250 / MX330 / MX350 / MX450 / MX550",
    "NVIDIA GeForce GT 710 / 730 / 1030",
    "NVIDIA GeForce GTX 1050 / 1050Ti / 1060 / 1070 / 1080",
    "NVIDIA GeForce GTX 1650 / 1650Ti / 1660 / 1660Ti / 1660 Super",
    "NVIDIA GeForce RTX 2050 / 2060 / 2070 / 2080",
    "NVIDIA GeForce RTX 3050 / 3050Ti / 3060 / 3070 / 3080 / 3090",
    "NVIDIA GeForce RTX 4050 / 4060 / 4070 / 4080 / 4090",
    "AMD Radeon RX 550 / 560 / 570 / 580 / 590",
    "AMD Radeon RX 5500 / 5600 / 5700 XT",
    "AMD Radeon RX 6500 / 6600 / 6700 / 6800 / 6900 XT",
    "AMD Radeon RX 7600 / 7700 / 7800 / 7900 XT",
]


DEFAULT_COLORS = [
    "مشکی", "سفید", "نقره‌ای", "خاکستری", "ذغالی", "سرمه‌ای",
    "آبی", "قرمز", "زرشکی", "سبز", "زیتونی", "طلایی",
    "رزگلد", "صورتی", "بنفش", "قهوه‌ای", "بژ", "شفاف",
    "چند‌رنگ", "سایر",
]


# فهرست ویژگی‌های فنی اولیه؛ هر فروشگاه می‌تواند مقادیر و محدودهٔ زیرمجموعه را تغییر دهد.
DEFAULT_ATTRIBUTES = {
    "لپ‌تاپ": [
        {"name": "پردازنده", "label": "CPU", "values": CPU_LIST[1:]},
        {"name": "ظرفیت رم", "label": "RAM", "values": RAM_CAPACITIES[1:]},
        {"name": "نسل رم", "label": "RAM Type", "values": ["DDR3 / DDR3L", "DDR4", "DDR5", "LPDDR4 / LPDDR5"]},
        {"name": "حافظه داخلی", "label": "Storage", "values": STORAGE_LIST[1:]},
        {"name": "پردازنده گرافیکی", "label": "GPU", "values": GPU_LIST[1:]},
        {"name": "صفحه‌نمایش", "label": "Display", "values": [
            "13.3 inch", "14 inch HD / FHD", "15.6 inch HD",
            "15.6 inch FHD IPS", "15.6 inch 144Hz / 165Hz",
            "16 inch FHD+ / 2K", "17.3 inch FHD",
        ]},
    ],
    "قطعات": [
        {"name": "ظرفیت", "label": "Capacity", "values": RAM_CAPACITIES[1:], "subcategory": "رم کامپیوتر (RAM PC)"},
        {"name": "ظرفیت", "label": "Capacity", "values": RAM_CAPACITIES[1:], "subcategory": "رم لپ‌تاپ (RAM Laptop)"},
        {"name": "نوع رابط", "label": "Interface", "values": ["SATA", "NVMe", "PCIe"], "subcategory": "حافظه اس‌اس‌دی (SSD)"},
        {"name": "ظرفیت", "label": "Capacity", "values": [], "subcategory": "هارد دیسک اینترنال (HDD)"},
        {"name": "نوع سوکت", "label": "Socket", "values": [], "subcategory": "پردازنده (CPU)"},
    ],
    "لوازم جانبی": [
        {"name": "نوع اتصال / پورت", "label": "Connectivity", "values": [
            "Wired USB", "2.4GHz Wireless", "Bluetooth",
            "Tri-mode (Wired / Wireless / Bluetooth)", "USB Type-C",
            "3.5mm Audio Jack", "HDMI / DisplayPort / VGA",
        ]},
        {"name": "مشخصات", "label": "Specifications", "values": []},
    ],
    "مانیتور": [
        {"name": "سایز", "label": "Size", "values": ["19 inch", "20 inch", "22 inch", "24 inch", "27 inch", "32 inch", "34 inch"]},
        {"name": "نوع پنل", "label": "Panel", "values": ["IPS", "VA", "TN", "OLED", "Nano IPS"]},
        {"name": "نرخ نوسازی", "label": "Refresh Rate", "values": ["60Hz", "75Hz", "100Hz", "144Hz", "165Hz", "180Hz", "240Hz"]},
        {"name": "درگاه‌ها", "label": "Ports", "values": ["HDMI + VGA", "HDMI + DisplayPort", "HDMI + DP + Type-C", "VGA + DVI"]},
    ],
    "کیس و مینی‌کیس": [
        {"name": "پردازنده", "label": "CPU", "values": CPU_LIST[1:]},
        {"name": "ظرفیت رم", "label": "RAM", "values": RAM_CAPACITIES[1:]},
        {"name": "حافظه داخلی", "label": "Storage", "values": STORAGE_LIST[1:]},
        {"name": "پردازنده گرافیکی", "label": "GPU", "values": GPU_LIST[1:]},
    ],
    "آداپتور و تغذیه": [
        {"name": "ولتاژ", "label": "Voltage", "values": ["5V", "9V", "12V", "19V", "19.5V", "20V", "220V AC"]},
        {"name": "آمپر و توان", "label": "Current / Power", "values": ["1A / 1.5A / 2A", "2.31A (45W)", "3.25A (65W)", "4.5A (90W)", "6.75A / 7.7A (135W-150W)"]},
        {"name": "نوع سوکت", "label": "Connector", "values": ["5.5x2.5mm", "HP / Dell Barrel", "Lenovo Rectangular", "USB Type-C PD"]},
    ],
    "شبکه و مودم": [
        {"name": "استاندارد شبکه", "label": "Network Standard", "values": ["Wi-Fi 4", "Wi-Fi 5", "Wi-Fi 6", "Wi-Fi 6E", "Wi-Fi 7", "4G", "5G"]},
        {"name": "تعداد درگاه", "label": "Ports", "values": []},
    ],
    "ماشین‌های اداری": [
        {"name": "فناوری چاپ", "label": "Print Technology", "values": ["Laser", "Inkjet", "Thermal", "Dot Matrix"]},
        {"name": "نوع چاپ", "label": "Print Color", "values": ["Monochrome", "Color"]},
    ],
    "سایر موارد": [
        {"name": "مشخصات", "label": "Specifications", "values": []},
    ],
}


def normalize_digits(text: str) -> str:
    if not text:
        return ""
    return str(text).translate(PERSIAN_ARABIC_MAP)


def auto_capitalize_english(text: str) -> str:
    """مورد ۲: تبدیل واقعی تمامی حروف انگلیسی به حروف بزرگ (UPPERCASE) به همراه نرمال‌سازی اعداد"""
    if not text:
        return ""
    return normalize_digits(text).upper()


def add_jalali_months(start_date_str: str, months: int) -> str:
    try:
        parts = [int(x) for x in normalize_digits(start_date_str).split("/")]
        y, m, d = parts[0], parts[1], parts[2]
        total_m = (m - 1) + int(months)
        ny = y + (total_m // 12)
        nm = (total_m % 12) + 1
        if nm <= 6:
            max_d = 31
        elif nm <= 11:
            max_d = 30
        else:
            is_leap = jdatetime.date(ny, 1, 1).isleap()
            max_d = 30 if is_leap else 29
        nd = min(d, max_d)
        return f"{ny:04d}/{nm:02d}/{nd:02d}"
    except Exception:
        return start_date_str


def add_jalali_days(start_date_str: str, days: int) -> str:
    """Add exact calendar days to a Jalali date."""
    try:
        parts = [int(x) for x in normalize_digits(start_date_str).split("/")]
        result = jdatetime.date(parts[0], parts[1], parts[2]) + datetime.timedelta(days=int(days))
        return result.strftime("%Y/%m/%d")
    except Exception:
        return start_date_str




def _animate_scrollbar(owner, scrollbar, amount):
    """Accumulate successive wheel ticks against the pending animation target."""
    if not amount or scrollbar.maximum() <= scrollbar.minimum():
        return False

    animation = getattr(owner, "_wheel_animation", None)
    base_value = scrollbar.value()
    if animation is not None and animation.state() == QAbstractAnimation.Running:
        try:
            base_value = int(animation.endValue())
        except (TypeError, ValueError):
            base_value = scrollbar.value()

    target = max(
        scrollbar.minimum(),
        min(scrollbar.maximum(), base_value - int(amount)),
    )
    if target == scrollbar.value():
        if animation is not None and animation.state() == QAbstractAnimation.Running:
            animation.stop()
        return True

    if animation is not None:
        animation.stop()
        animation.deleteLater()
        owner._wheel_animation = None

    animation = QPropertyAnimation(scrollbar, b"value", owner)
    animation.setDuration(180)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.setStartValue(scrollbar.value())
    animation.setEndValue(target)

    def release_animation():
        if getattr(owner, "_wheel_animation", None) is animation:
            owner._wheel_animation = None
        animation.deleteLater()

    animation.finished.connect(release_animation)
    owner._wheel_animation = animation
    animation.start()
    return True


def _wheel_amount(event, horizontal=False):
    """Normalize mouse-wheel and touchpad deltas to pixel-like scroll steps."""
    pixel_delta = event.pixelDelta()
    angle_delta = event.angleDelta()
    if horizontal:
        amount = pixel_delta.x() or pixel_delta.y() or angle_delta.x() or angle_delta.y()
    else:
        amount = pixel_delta.y() or pixel_delta.x() or angle_delta.y() or angle_delta.x()
        if not pixel_delta.y() and not pixel_delta.x():
            amount = int(amount)
    return int(amount)


class SmoothScrollArea(QScrollArea):
    """A pixel-based scroll area with accumulated, eased mouse-wheel animation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._wheel_animation = None

    def wheelEvent(self, event):
        horizontal = bool(event.modifiers() & Qt.ShiftModifier)
        scrollbar = (
            self.horizontalScrollBar() if horizontal else self.verticalScrollBar()
        )
        amount = _wheel_amount(event, horizontal=horizontal)
        if not amount or scrollbar.maximum() <= scrollbar.minimum():
            return super().wheelEvent(event)
        if _animate_scrollbar(self, scrollbar, amount):
            event.accept()
        else:
            super().wheelEvent(event)


class SmoothScrollTableWidget(QTableWidget):
    """Table widget with smooth pixel scrolling, including when the cursor is over a table."""

    def __init__(self, rows=0, columns=0, parent=None):
        super().__init__(rows, columns, parent)
        self._wheel_animation = None

    def wheelEvent(self, event):
        horizontal = bool(event.modifiers() & Qt.ShiftModifier)
        scrollbar = (
            self.horizontalScrollBar() if horizontal else self.verticalScrollBar()
        )
        amount = _wheel_amount(event, horizontal=horizontal)
        if not amount or scrollbar.maximum() <= scrollbar.minimum():
            return super().wheelEvent(event)
        if _animate_scrollbar(self, scrollbar, amount):
            event.accept()
        else:
            super().wheelEvent(event)


class SmoothScrollListWidget(QListWidget):
    """List widget with the same eased wheel scrolling as pages and tables."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._wheel_animation = None
        self.enable_row_toggle = False
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(18)

    def mousePressEvent(self, event):
        if getattr(self, "enable_row_toggle", False) and event.button() == Qt.LeftButton:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            item = self.itemAt(pos)
            if item is not None and (item.flags() & Qt.ItemIsUserCheckable):
                new_state = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
                item.setCheckState(new_state)
                self.setCurrentItem(item)
                event.accept()
                return
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        amount = _wheel_amount(event, horizontal=False)
        scrollbar = self.verticalScrollBar()
        if not amount or scrollbar.maximum() <= scrollbar.minimum():
            return super().wheelEvent(event)
        if _animate_scrollbar(self, scrollbar, amount):
            event.accept()
        else:
            super().wheelEvent(event)


class CollapsibleSection(QWidget):
    """Compact, keyboard-accessible section whose content is collapsed by default."""

    def __init__(self, title: str, content: QWidget, parent=None):
        super().__init__(parent)
        self.content = content
        self.header = QPushButton(f"▸  {title}")
        self.header.setObjectName("collapsibleSectionHeader")
        self._expanded = False
        self.header.setMinimumHeight(38)
        self.content.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(self.header)
        layout.addWidget(self.content)
        # Use pressed(), which has no Python bool payload. Expansion state is kept
        # in this widget instead of relying on QPushButton's checkable state.
        self.header.pressed.connect(self._on_header_pressed)

    def _on_header_pressed(self):
        self._expanded = not self._expanded
        title = self.header.text().lstrip("▸▾ ").strip()
        if self._expanded:
            self.content.show()
            self.header.setText("▾  " + title)
        else:
            self.content.hide()
            self.header.setText("▸  " + title)

    def collapse(self):
        if self._expanded:
            self._expanded = False
            title = self.header.text().lstrip("▸▾ ").strip()
            self.content.hide()
            self.header.setText("▸  " + title)

    def expand(self):
        if not self._expanded:
            self._expanded = True
            title = self.header.text().lstrip("▸▾ ").strip()
            self.content.show()
            self.header.setText("▾  " + title)

    def is_expanded(self) -> bool:
        return self._expanded


class SmartLineEdit(QLineEdit):
    """فیلد متنی که اعداد را انگلیسی و تمام حروف انگلیسی را به طور واقعی بزرگ (UPPERCASE) ذخیره می‌کند"""

    def __init__(self, placeholder="", parent=None):
        super().__init__(parent)
        if placeholder:
            self.setPlaceholderText(placeholder)
        self.textEdited.connect(self._on_text_edited)

    def _on_text_edited(self, txt):
        new_txt = auto_capitalize_english(txt)
        if new_txt != txt:
            pos = self.cursorPosition()
            self.blockSignals(True)
            super().setText(new_txt)
            self.setCursorPosition(pos)
            self.blockSignals(False)

    def setText(self, txt: str):
        super().setText(auto_capitalize_english(txt))

    def text(self) -> str:
        return auto_capitalize_english(super().text())


class PriceInput(QLineEdit):
    """فیلد قیمت بر حسب تومان با جداکننده هزارگان و افزودن خودکار صفر طبق تنظیمات"""

    # object keeps Python's full 64-bit integer value; Qt's C++ int signal is 32-bit.
    valueChanged = Signal(object)

    def __init__(self, db_manager, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self._raw_typed = False
        self.setPlaceholderText("مبلغ (تومان)")
        zero_count = int(self.db.cfg.get("zero_append_count", 3) or 0)
        self.setToolTip(
            "مبلغ را به تومان وارد کنید (بدون صفر اضافی)"
            if zero_count <= 0 else
            f"مبلغ را به تومان وارد کنید ({zero_count} صفر به‌صورت خودکار اضافه می‌شود)"
        )
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.textEdited.connect(self._on_edited)
        self.editingFinished.connect(self._apply_auto_zeros)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.selectAll()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.selectAll()

    def _on_edited(self, txt):
        self._raw_typed = True
        clean = "".join(ch for ch in normalize_digits(txt) if ch.isdigit())
        self.blockSignals(True)
        if clean:
            self.setText(f"{int(clean):,}")
        else:
            self.setText("")
        self.blockSignals(False)
        self.valueChanged.emit(self.get_value())

    def _apply_auto_zeros(self):
        if not self._raw_typed:
            return
        self._raw_typed = False
        zeros = max(0, int(self.db.cfg.get("zero_append_count", 3) or 0))
        val = self.get_value()
        if zeros > 0 and val > 0:
            val = val * (10**zeros)
            self.blockSignals(True)
            self.setText(f"{val:,}")
            self.blockSignals(False)
            self.valueChanged.emit(val)

    def get_value(self) -> int:
        clean = "".join(ch for ch in normalize_digits(self.text()) if ch.isdigit())
        return int(clean) if clean else 0

    def set_value(self, amount: int):
        self._raw_typed = False
        self.blockSignals(True)
        self.setText(f"{int(amount):,}" if amount else "0")
        self.blockSignals(False)
        self.setToolTip(f"{int(amount):,} تومان" if amount else "0 تومان")
        self.valueChanged.emit(int(amount) if amount else 0)


class _ComboSearchProxyModel(QSortFilterProxyModel):
    """Filter combo suggestions using visible text plus an optional hidden search field."""

    def __init__(self, search_role, parent=None):
        super().__init__(parent)
        self.search_role = search_role
        self.query = ""
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)

    def set_query(self, query):
        self.query = auto_capitalize_english(query).strip()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self.query:
            return True
        source = self.sourceModel()
        index = source.index(source_row, self.filterKeyColumn(), source_parent)
        visible = source.data(index, Qt.DisplayRole) or ""
        searchable = source.data(index, self.search_role) or ""
        q = self.query.casefold().strip()
        haystack = f"{visible} {searchable}".casefold()
        return q in haystack or auto_capitalize_english(self.query) in auto_capitalize_english(f"{visible} {searchable}")


class SearchableComboBox(QComboBox):
    """Editable combo with completion against visible labels and hidden search keywords."""

    SEARCH_ROLE = Qt.UserRole + 37

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        # Keep the logical order of mixed Persian/Latin selectors in the collapsed view.
        self.lineEdit().setLayoutDirection(Qt.LeftToRight)
        self.lineEdit().setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._search_proxy = _ComboSearchProxyModel(self.SEARCH_ROLE, self)
        self._search_proxy.setSourceModel(self.model())
        completer = QCompleter(self._search_proxy, self)
        # Proxy model is the sole filter source; Qt must not apply a second visible-text filter.
        completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        completer.setCompletionColumn(0)
        completer.setCompletionRole(Qt.DisplayRole)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.setCompleter(completer)
        self.lineEdit().textEdited.connect(self._normalize_search)
        self.currentTextChanged.connect(lambda t: self.setToolTip(t))

    def setItemSearchText(self, index: int, search_text: str):
        if 0 <= index < self.count():
            self.setItemData(index, str(search_text or ""), self.SEARCH_ROLE)
            self._search_proxy.invalidateFilter()

    def _normalize_search(self, txt):
        norm = auto_capitalize_english(txt)
        self._search_proxy.set_query(norm)
        if norm != txt:
            pos = self.lineEdit().cursorPosition()
            self.lineEdit().blockSignals(True)
            self.lineEdit().setText(norm)
            self.lineEdit().setCursorPosition(pos)
            self.lineEdit().blockSignals(False)

    def currentText(self) -> str:
        return auto_capitalize_english(super().currentText())


class QuantitySelector(QComboBox):
    qtyChanged = Signal(int)

    def __init__(self, max_qty=100, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.set_max_qty(max_qty)
        self.currentTextChanged.connect(self._on_change)

    def set_max_qty(self, max_qty: int):
        current = self.get_qty()
        self.blockSignals(True)
        self.clear()
        limit = max(1, min(int(max_qty), 300))
        for i in range(1, limit + 1):
            self.addItem(str(i), i)
        if 1 <= current <= max_qty:
            self.setCurrentText(str(current))
        else:
            self.setCurrentText("1")
        self.blockSignals(False)

    def _on_change(self, txt):
        clean = "".join(ch for ch in normalize_digits(txt) if ch.isdigit())
        if clean != txt and clean:
            self.setCurrentText(clean)
        self.qtyChanged.emit(self.get_qty())

    def get_qty(self) -> int:
        clean = "".join(
            ch for ch in normalize_digits(self.currentText()) if ch.isdigit()
        )
        return max(1, int(clean)) if clean else 1


class JalaliCalendarDialog(QDialog):
    """
    بند ۸: پنجره بزرگ‌تر تقویم شمسی گرافیکی با خوانایی کامل اعداد سال و ماه
    """

    def __init__(self, initial_date_str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("انتخاب تاریخ شمسی")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setFixedSize(470, 438)
        self.selected_date = initial_date_str

        dark = False
        ancestor = parent
        while ancestor is not None:
            if hasattr(ancestor, "db"):
                dark = ancestor.db.cfg.get("theme", "light") == "dark"
                break
            ancestor = ancestor.parentWidget() if hasattr(ancestor, "parentWidget") else None

        self._calendar_colors = {
            "surface": "#263244" if dark else "#ffffff",
            "base": "#1e293b" if dark else "#f8fafc",
            "text": "#e5eaf2" if dark else "#0f172a",
            "muted": "#aab6c8" if dark else "#475569",
            "border": "#46556c" if dark else "#cbd5e1",
            "selected": "#2563eb",
            "disabled": "#334155" if dark else "#e2e8f0",
        }
        colors = self._calendar_colors
        self.setStyleSheet(
            f"QDialog {{ background: {colors['base']}; color: {colors['text']}; }}"
            f"QLabel {{ color: {colors['text']}; }}"
            f"QComboBox {{ background: {colors['surface']}; color: {colors['text']}; "
            f"border: 1px solid {colors['border']}; border-radius: 6px; padding: 5px; min-height: 30px; }}"
            f"QComboBox QAbstractItemView {{ background: {colors['surface']}; color: {colors['text']}; "
            f"selection-background-color: {colors['selected']}; selection-color: #ffffff; }}"
            f"QPushButton {{ background: {colors['surface']}; color: {colors['text']}; "
            f"border: 1px solid {colors['border']}; border-radius: 6px; padding: 6px 10px; }}"
            f"QPushButton:hover {{ border: 1px solid {colors['selected']}; }}"
        )

        try:
            p = [int(x) for x in normalize_digits(initial_date_str).split("/")]
            self.cur_year, self.cur_month, self.cur_day = p[0], p[1], p[2]
        except Exception:
            today = jdatetime.date.today()
            self.cur_year, self.cur_month, self.cur_day = (
                today.year,
                today.month,
                today.day,
            )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        nav = QVBoxLayout()
        nav.setSpacing(3)
        controls_grid = QGridLayout()
        controls_grid.setContentsMargins(0, 0, 0, 0)
        controls_grid.setHorizontalSpacing(10)
        controls_grid.setVerticalSpacing(8)
        controls_grid.setColumnStretch(0, 1)
        controls_grid.setColumnStretch(1, 1)

        self.cb_year = QComboBox()
        self.cb_year.setEditable(True)
        self.cb_year.addItems([str(year) for year in range(1400, 1601)])
        self.cb_year.setInsertPolicy(QComboBox.NoInsert)
        self.cb_year.setCurrentText(str(self.cur_year))
        self.cb_year.setMinimumHeight(38)
        self.cb_year.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cb_year.lineEdit().setAlignment(Qt.AlignCenter)
        self.cb_year.lineEdit().setValidator(QIntValidator(1400, 1600, self.cb_year))
        self.cb_year.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.cb_year.currentTextChanged.connect(self._refresh_grid)

        self.cb_month = QComboBox()
        self.cb_month.setMinimumHeight(38)
        self.cb_month.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cb_month.setStyleSheet("font-size: 15px; font-weight: bold;")
        months = [
            "فروردین",
            "اردیبهشت",
            "خرداد",
            "تیر",
            "مرداد",
            "شهریور",
            "مهر",
            "آبان",
            "آذر",
            "دی",
            "بهمن",
            "اسفند",
        ]
        for idx, m in enumerate(months, 1):
            self.cb_month.addItem(f"{idx:02d} - {m}", idx)
        self.cb_month.setCurrentIndex(self.cur_month - 1)
        self.cb_month.currentIndexChanged.connect(self._refresh_grid)

        self.cb_day = QComboBox()
        self.cb_day.setMinimumHeight(38)
        self.cb_day.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cb_day.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.cb_day.addItems([f"{day:02d}" for day in range(1, 32)])
        self.cb_day.setCurrentIndex(max(0, min(30, self.cur_day - 1)))
        self.cb_day.activated.connect(self._on_day_combo_activated)

        btn_today = QPushButton("برو به امروز")
        btn_today.setMinimumHeight(38)
        btn_today.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_today.clicked.connect(self._go_today)

        lbl_y = QLabel("سال:")
        lbl_y.setStyleSheet("font-weight: bold; font-size: 14px;")
        lbl_m = QLabel("ماه:")
        lbl_m.setStyleSheet("font-weight: bold; font-size: 14px;")
        lbl_d = QLabel("روز:")
        lbl_d.setStyleSheet("font-weight: bold; font-size: 14px;")

        year_cell = QWidget()
        year_cell_layout = QHBoxLayout(year_cell)
        year_cell_layout.setContentsMargins(0, 0, 0, 0)
        year_cell_layout.setSpacing(6)
        year_cell_layout.addWidget(lbl_y)
        year_cell_layout.addWidget(self.cb_year, 1)

        month_cell = QWidget()
        month_cell_layout = QHBoxLayout(month_cell)
        month_cell_layout.setContentsMargins(0, 0, 0, 0)
        month_cell_layout.setSpacing(6)
        month_cell_layout.addWidget(lbl_m)
        month_cell_layout.addWidget(self.cb_month, 1)

        day_cell = QWidget()
        day_cell_layout = QHBoxLayout(day_cell)
        day_cell_layout.setContentsMargins(0, 0, 0, 0)
        day_cell_layout.setSpacing(6)
        day_cell_layout.addWidget(lbl_d)
        day_cell_layout.addWidget(self.cb_day, 1)

        controls_grid.addWidget(year_cell, 0, 0)
        controls_grid.addWidget(btn_today, 0, 1)
        controls_grid.addWidget(month_cell, 1, 0)
        controls_grid.addWidget(day_cell, 1, 1)
        nav.addLayout(controls_grid)
        layout.addLayout(nav)

        self.grid = QGridLayout()
        self.grid.setSpacing(5)
        days_header = ["ش", "ی", "د", "س", "چ", "پ", "ج"]
        for col, d_name in enumerate(days_header):
            lbl = QLabel(d_name)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(
                f"font-weight: bold; font-size: 14px; color: {colors['muted']}; padding: 4px;"
            )
            lbl.setMinimumHeight(30)
            self.grid.addWidget(lbl, 0, col)

        self.day_buttons = []
        for r in range(1, 7):
            for c in range(7):
                btn = QPushButton("")
                btn.setFixedSize(50, 42)
                btn.setStyleSheet(
                    f"background: {colors['surface']}; color: {colors['text']}; "
                    f"font-size: 15px; font-weight: bold; border: 1px solid {colors['border']}; "
                    "border-radius: 6px;"
                )
                btn.clicked.connect(self._on_day_clicked)
                self.grid.addWidget(btn, r, c)
                self.day_buttons.append(btn)

        layout.addLayout(self.grid)
        self._refresh_grid()

    def _go_today(self):
        t = jdatetime.date.today()
        self.cb_year.setCurrentText(str(t.year))
        self.cb_month.setCurrentIndex(t.month - 1)
        self.cb_day.setCurrentIndex(t.day - 1)
        self.selected_date = t.strftime("%Y/%m/%d")
        self.accept()

    def _on_day_combo_activated(self, index):
        try:
            year = int(normalize_digits(self.cb_year.currentText()))
            month = int(self.cb_month.currentData())
            day = int(self.cb_day.itemText(index))
            jdatetime.date(year, month, day)
        except (TypeError, ValueError):
            return
        self.selected_date = f"{year:04d}/{month:02d}/{day:02d}"
        self.accept()

    def _refresh_grid(self):
        # Clear the calendar first; typing an incomplete year must never crash the dialog.
        colors = self._calendar_colors
        for button in self.day_buttons:
            button.setText("")
            button.setEnabled(0)
            button.setStyleSheet(
                f"background: {colors['disabled']}; color: {colors['muted']}; "
                "border: none; border-radius: 6px;"
            )

        raw_year = normalize_digits(self.cb_year.currentText()).strip()
        try:
            year = int(raw_year)
        except (TypeError, ValueError):
            return
        if not 1400 <= year <= 1600:
            return

        month = self.cb_month.currentData()
        if month is None:
            return
        try:
            first_day = jdatetime.date(year, int(month), 1)
        except (TypeError, ValueError):
            return
        start_weekday = first_day.weekday()

        if month <= 6:
            max_days = 31
        elif month <= 11:
            max_days = 30
        else:
            max_days = 30 if first_day.isleap() else 29

        for day_index in range(self.cb_day.count()):
            item = self.cb_day.model().item(day_index)
            if item is not None:
                flags = item.flags()
                if day_index < max_days:
                    item.setFlags(flags | Qt.ItemIsEnabled)
                else:
                    item.setFlags(flags & ~Qt.ItemIsEnabled)

        for day in range(1, max_days + 1):
            index = start_weekday + day - 1
            button = self.day_buttons[index]
            button.setText(str(day))
            button.setEnabled(1)
            if year == self.cur_year and month == self.cur_month and day == self.cur_day:
                button.setStyleSheet(
                    f"background-color: {colors['selected']}; color: white; "
                    "font-size: 15px; font-weight: bold; border-radius: 6px;"
                )
            else:
                button.setStyleSheet(
                    f"background-color: {colors['surface']}; color: {colors['text']}; "
                    f"font-size: 15px; font-weight: bold; border: 1px solid {colors['border']}; "
                    "border-radius: 6px;"
                )


    def _on_day_clicked(self):
        btn = self.sender()
        if not btn.text():
            return
        d = int(btn.text())
        try:
            y = int(normalize_digits(self.cb_year.currentText()))
        except (TypeError, ValueError):
            return
        m = self.cb_month.currentData()
        if m is None or not 1400 <= y <= 1600:
            return
        try:
            jdatetime.date(y, int(m), d)
        except ValueError:
            return
        self.selected_date = f"{y:04d}/{int(m):02d}/{d:02d}"
        self.accept()


class JalaliDateEdit(QWidget):
    """
    مورد ۷: فیلد تاریخ شمسی ۳ کادره با ترتیب و پرش خودکار از روز -> ماه -> سال
    """

    dateChanged = Signal(str)

    def __init__(self, default_today=True, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.ed_day = QLineEdit()
        self.ed_day.setFixedWidth(50)
        self.ed_day.setFixedHeight(36)
        self.ed_day.setStyleSheet("font-size: 12px; padding: 2px;")
        self.ed_day.setMaxLength(2)
        self.ed_day.setAlignment(Qt.AlignCenter)
        self.ed_day.setPlaceholderText("روز")

        self.ed_month = QLineEdit()
        self.ed_month.setFixedWidth(50)
        self.ed_month.setFixedHeight(36)
        self.ed_month.setStyleSheet("font-size: 12px; padding: 2px;")
        self.ed_month.setMaxLength(2)
        self.ed_month.setAlignment(Qt.AlignCenter)
        self.ed_month.setPlaceholderText("ماه")

        self.ed_year = QLineEdit()
        self.ed_year.setFixedWidth(68)
        self.ed_year.setFixedHeight(36)
        self.ed_year.setStyleSheet("font-size: 12px; padding: 2px;")
        self.ed_year.setMaxLength(4)
        self.ed_year.setAlignment(Qt.AlignCenter)
        self.ed_year.setPlaceholderText("سال")

        self.btn_cal = QPushButton("📅")
        self.btn_cal.setFixedSize(34, 36)
        self.btn_cal.setToolTip("انتخاب از تقویم شمسی")
        self.btn_cal.clicked.connect(self._open_calendar)

        # چیدمان راست به چپ: روز / ماه / سال
        layout.addWidget(self.ed_day)
        layout.addWidget(QLabel("/"))
        layout.addWidget(self.ed_month)
        layout.addWidget(QLabel("/"))
        layout.addWidget(self.ed_year)
        layout.addWidget(self.btn_cal)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedWidth(self.sizeHint().width())

        self.ed_day.textEdited.connect(self._on_day_edited)
        self.ed_month.textEdited.connect(self._on_month_edited)
        self.ed_year.textEdited.connect(self._on_year_edited)

        if default_today:
            self.set_date(jdatetime.date.today().strftime("%Y/%m/%d"))

    def _clean_num(self, line_edit):
        txt = normalize_digits(line_edit.text())
        clean = "".join(c for c in txt if c.isdigit())
        if clean != line_edit.text():
            line_edit.blockSignals(True)
            line_edit.setText(clean)
            line_edit.blockSignals(False)
        return clean

    def _on_day_edited(self):
        c = self._clean_num(self.ed_day)
        if len(c) == 2:
            if int(c) > 31:
                self.ed_day.setText("31")
            self.ed_month.setFocus()
            self.ed_month.selectAll()
        self.dateChanged.emit(self.get_date())

    def _on_month_edited(self):
        c = self._clean_num(self.ed_month)
        if len(c) == 2:
            if int(c) > 12:
                self.ed_month.setText("12")
            self.ed_year.setFocus()
            self.ed_year.selectAll()
        self.dateChanged.emit(self.get_date())

    def _on_year_edited(self):
        self._clean_num(self.ed_year)
        self.dateChanged.emit(self.get_date())

    def _open_calendar(self):
        dlg = JalaliCalendarDialog(self.get_date(), self)
        if dlg.exec() == QDialog.Accepted:
            self.set_date(dlg.selected_date)

    def get_date(self) -> str:
        year = self.ed_year.text().strip()
        month = self.ed_month.text().strip()
        day = self.ed_day.text().strip()
        if not (year and month and day):
            return ""
        return f"{year.zfill(4)}/{month.zfill(2)}/{day.zfill(2)}"

    def set_date(self, date_str: str):
        raw = normalize_digits(str(date_str or "")).strip()
        if not raw:
            for editor in (self.ed_year, self.ed_month, self.ed_day):
                editor.clear()
            self.dateChanged.emit("")
            return
        try:
            parts = raw.split("/")
            if len(parts) != 3 or not all(part.strip() for part in parts):
                raise ValueError("Invalid Jalali date")
            self.ed_year.setText(parts[0].strip())
            self.ed_month.setText(parts[1].strip().zfill(2))
            self.ed_day.setText(parts[2].strip().zfill(2))
            self.dateChanged.emit(self.get_date())
        except (TypeError, ValueError):
            self.set_date("")


class DynamicSpecsWidget(QGroupBox):
    """
    بند ۱ و ۲: ویجت جامع زیرمجموعه‌ها و مشخصات فنی با قابلیت تایپ دستی زیرمجموعه
    و پوشش کامل لپ‌تاپ، قطعات، لوازم جانبی، مانیتور، کیس/مینی‌کیس، آداپتور و...
    """

    def __init__(self, parent=None):
        super().__init__("انتخاب زیرمجموعه و مشخصات فنی کالا", parent)
        self.main_layout = QVBoxLayout(self)
        self.form_widget = QWidget()
        self.form_layout = QFormLayout(self.form_widget)
        self.form_widget.setLayoutDirection(Qt.RightToLeft)
        self.form_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.form_layout.setFormAlignment(Qt.AlignRight | Qt.AlignTop)
        self.form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.form_layout.setHorizontalSpacing(12)
        self.form_layout.setVerticalSpacing(9)
        self.form_scroll = SmoothScrollArea(self)
        self.form_scroll.setWidget(self.form_widget)
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setMinimumHeight(150)
        self.form_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.form_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.main_layout.addWidget(self.form_scroll)
        self.current_category = "لپ‌تاپ"
        self.fields = {}
        self._custom_field_widgets = {}
        self.cb_sub = None
        self._custom_field_callback = None
        self.set_category("لپ‌تاپ")

    def set_custom_field_callback(self, callback):
        """Store bound callbacks weakly to avoid a MainWindow <-> widget cycle."""
        if not callable(callback):
            self._custom_field_callback = None
        elif getattr(callback, "__self__", None) is not None:
            self._custom_field_callback = weakref.WeakMethod(callback)
        else:
            self._custom_field_callback = callback

    def _notify_custom_field_callback(self, *_):
        callback = self._custom_field_callback
        if isinstance(callback, weakref.WeakMethod):
            callback = callback()
        if callback is not None:
            callback()

    def _clear_form(self):
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.fields.clear()
        self._custom_field_widgets.clear()
        self.cb_sub = None

    def _apply_compact_form_layouts(self):
        """Keep RTL field captions compact while giving editors consistent spacing."""
        layouts = [self.form_layout]
        sub_layout = getattr(self, "sub_layout", None)
        if sub_layout is not None:
            try:
                layouts.append(sub_layout)
            except RuntimeError:
                pass

        for form_layout in layouts:
            try:
                form_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
                form_layout.setFormAlignment(Qt.AlignRight | Qt.AlignTop)
                form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
                form_layout.setHorizontalSpacing(12)
                form_layout.setVerticalSpacing(9)
                for row in range(form_layout.rowCount()):
                    field_item = form_layout.itemAt(row, QFormLayout.FieldRole)
                    field_widget = field_item.widget() if field_item else None
                    label_widget = (
                        form_layout.labelForField(field_widget)
                        if field_widget is not None else None
                    )
                    if isinstance(label_widget, QLabel):
                        label_widget.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        label_widget.setLayoutDirection(Qt.RightToLeft)
                        label_widget.setSizePolicy(
                            QSizePolicy.Maximum, QSizePolicy.Fixed
                        )
                        label_widget.setMinimumWidth(72)
                        label_widget.setMaximumWidth(
                            max(100, min(220, label_widget.sizeHint().width() + 8))
                        )
                        label_widget.setWordWrap(False)
                    if field_widget is not None:
                        field_widget.setMinimumHeight(
                            max(30, field_widget.minimumHeight())
                        )
                        field_widget.setSizePolicy(
                            QSizePolicy.Expanding, QSizePolicy.Fixed
                        )
            except RuntimeError:
                # A category rebuild may have just scheduled this layout for deletion.
                continue

    def set_subcategory_label(self, label: str):
        """Customize the caption associated with the category-specific subcategory selector."""
        if self.cb_sub is None:
            return
        label_widget = self.form_layout.labelForField(self.cb_sub)
        if label_widget is not None:
            label_widget.setText(f"{str(label or 'زیرمجموعه').strip()}:")

    def set_category(self, category: str):
        self.current_category = category.strip()
        self._clear_form()

        self.cb_sub = SearchableComboBox()
        self.cb_sub.setEditable(0)
        self.cb_sub.setToolTip("زیرمجموعه را از فهرست انتخاب کنید")

        cat_key = normalize_catalog_label(self.current_category)

        if cat_key == normalize_catalog_label("لپ تاپ"):
            self.cb_sub.currentTextChanged.connect(self._notify_custom_field_callback)
            self.cb_sub.addItems(
                [
                    "لپ‌تاپ عمومی / مالتی‌مدیا",
                    "لپ‌تاپ گیمینگ (Gaming)",
                    "لپ‌تاپ مهندسی و رندرینگ",
                    "لپ‌تاپ استوک / صنعتی",
                    "اولترابوک / تبلت‌شو",
                    "مک‌بوک (MacBook)",
                    "سایر موارد",
                ]
            )
            self.form_layout.addRow("زیرمجموعه لپ‌تاپ:", self.cb_sub)

            cb_cpu = SearchableComboBox()
            cb_cpu.addItems(CPU_LIST)
            cb_ram = SearchableComboBox()
            cb_ram.addItems(RAM_CAPACITIES)
            cb_ram_type = SearchableComboBox()
            cb_ram_type.addItems(["", "DDR3 / DDR3L", "DDR4", "DDR5", "LPDDR4 / LPDDR5"])
            cb_storage = SearchableComboBox()
            cb_storage.addItems(STORAGE_LIST)
            cb_gpu = SearchableComboBox()
            cb_gpu.addItems(GPU_LIST)
            cb_screen = SearchableComboBox()
            cb_screen.addItems(
                [
                    "",
                    "13.3 اینچ",
                    "14 اینچ HD/FHD",
                    "15.6 اینچ HD",
                    "15.6 اینچ FHD IPS",
                    "15.6 اینچ 144Hz/165Hz",
                    "16 اینچ FHD+/2K",
                    "17.3 اینچ FHD",
                ]
            )

            self.fields = {
                "پردازنده": cb_cpu,
                "ظرفیت رم": cb_ram,
                "نسل رم": cb_ram_type,
                "حافظه داخلی": cb_storage,
                "پردازنده گرافیکی": cb_gpu,
                "صفحه‌نمایش": cb_screen,
            }
            self.form_layout.addRow("پردازنده (CPU):", cb_cpu)
            self.form_layout.addRow("ظرفیت رم (RAM):", cb_ram)
            self.form_layout.addRow("نسخه رم:", cb_ram_type)
            self.form_layout.addRow("حافظه داخلی (Storage):", cb_storage)
            self.form_layout.addRow("کارت گرافیک (GPU):", cb_gpu)
            self.form_layout.addRow("صفحه‌نمایش:", cb_screen)

        elif cat_key == normalize_catalog_label("قطعات"):
            self.cb_sub.addItems(
                [
                    "سایر موارد",
                    "پردازنده (CPU)",
                    "رم کامپیوتر (RAM PC)",
                    "رم لپ‌تاپ (RAM Laptop)",
                    "حافظه اس‌اس‌دی (SSD)",
                    "هارد دیسک اینترنال (HDD)",
                    "کارت گرافیک (Graphic Card)",
                    "مادربرد (Motherboard)",
                    "پاور / منبع تغذیه کیس (Power)",
                    "فن و خنک‌کننده (Cooling / Fan)",
                    "صفحه‌نمایش لپ‌تاپ (LED / LCD Panel)",
                    "باتری لپ‌تاپ (Laptop Battery)",
                    "کیبورد تعمیراتی لپ‌تاپ (Internal Keyboard)",
                    "قاب، لولا و فلت لپ‌تاپ",
                    "کارت شبکه و صدا اینترنال",
                    "درایو نوری (DVD RW / Caddy)",
                ]
            )
            self.cb_sub.setCurrentText("سایر موارد")
            self.cb_sub.currentTextChanged.connect(self._rebuild_part_subfields)
            self.form_layout.addRow("نوع قطعه:", self.cb_sub)

            self.sub_container = QWidget()
            self.sub_layout = QFormLayout(self.sub_container)
            self.sub_layout.setContentsMargins(0, 0, 0, 0)
            self.form_layout.addRow(self.sub_container)
            self._rebuild_part_subfields("سایر موارد")

        elif cat_key == normalize_catalog_label("لوازم جانبی"):
            self.cb_sub.currentTextChanged.connect(self._notify_custom_field_callback)
            self.cb_sub.addItems(
                [
                    "سایر موارد",
                    "ماوس (Mouse)",
                    "کیبورد (Keyboard)",
                    "پک کمبو ماوس و کیبورد",
                    "هدست، هدفون و هندزفری",
                    "اسپیکر (Speaker)",
                    "فلش مموری (Flash Memory)",
                    "هارد اکسترنال (External HDD)",
                    "اس‌اس‌دی اکسترنال (External SSD)",
                    "کول‌پد لپ‌تاپ (Coolpad)",
                    "کیف و کوله‌پشتی لپ‌تاپ",
                    "هاب USB و Type-C",
                    "کابل تصویر (HDMI / DisplayPort / VGA)",
                    "کابل برق، شبکه و افزایش طول",
                    "مبدل و دانگل (Converter / Dongle)",
                    "ماوس‌پد (Mouse Pad)",
                    "وب‌کم و میکروفون (Webcam / Mic)",
                    "گیم‌پد و دسته بازی (Gamepad)",
                    "خمیر سیلیکون و اسپری تمیزکننده",
                ]
            )
            self.cb_sub.setCurrentText("سایر موارد")
            cb_conn = SearchableComboBox()
            cb_conn.addItems(
                [
                    "",
                    "باسیم (USB)",
                    "بی‌سیم ( دانگل 2.4GHz)",
                    "بلوتوث (Bluetooth)",
                    "دوحالته و سه‌حالته (باسیم + بی‌سیم + بلوتوث)",
                    "Type-C",
                    "جک ۳.۵ میلی‌متری صدا",
                    "HDMI / DisplayPort / VGA",
                    "بدون پورت (فیزیکی)",
                ]
            )
            ed_extra = SmartLineEdit("ویژگی تکمیلی (مثلاً طول کابل، ظرفیت، رنگ...)")
            self.fields = {"نوع اتصال / پورت": cb_conn, "مشخصه": ed_extra}
            self.form_layout.addRow("نوع لوازم جانبی:", self.cb_sub)
            self.form_layout.addRow("نوع اتصال / پورت:", cb_conn)
            self.form_layout.addRow("مشخصات تکمیلی:", ed_extra)

        elif cat_key in (normalize_catalog_label("مانیتور"), normalize_catalog_label("مانیتور و نمایشگر")):
            self.cb_sub.currentTextChanged.connect(self._notify_custom_field_callback)
            self.cb_sub.addItems(
                [
                    "مانیتور اداری و خانگی",
                    "مانیتور گیمینگ (Gaming)",
                    "مانیتور طراحی و صنعتی",
                    "مانیتور استوک",
                    "مانیتور منحنی (Curved)",
                ]
            )
            cb_size = SearchableComboBox()
            cb_size.addItems(["", "19 اینچ", "20 اینچ", "22 اینچ", "24 اینچ", "27 اینچ", "32 اینچ", "34 اینچ"])
            cb_panel = SearchableComboBox()
            cb_panel.addItems(["", "IPS", "VA", "TN", "OLED", "Nano IPS"])
            cb_hz = SearchableComboBox()
            cb_hz.addItems(["", "60Hz", "75Hz", "100Hz", "144Hz", "165Hz", "180Hz", "240Hz"])
            cb_ports = SearchableComboBox()
            cb_ports.addItems(["", "HDMI + VGA", "HDMI + DisplayPort", "HDMI + DP + Type-C", "VGA + DVI"])
            self.fields = {"سایز": cb_size, "پنل": cb_panel, "نرخ بروزرسانی": cb_hz, "پورت‌ها": cb_ports}
            self.form_layout.addRow("زیرمجموعه مانیتور:", self.cb_sub)
            self.form_layout.addRow("سایز صفحه:", cb_size)
            self.form_layout.addRow("نوع پنل:", cb_panel)
            self.form_layout.addRow("نرخ تصویر (Hz):", cb_hz)
            self.form_layout.addRow("پورت‌های ورودی:", cb_ports)

        elif cat_key in (normalize_catalog_label("کیس و مینی‌کیس"), normalize_catalog_label("کامپیوتر و کیس اسمبل شده")):
            self.cb_sub.currentTextChanged.connect(self._notify_custom_field_callback)
            self.cb_sub.addItems(
                [
                    "مینی‌کیس استوک (Mini Case)",
                    "کیس کامل اسمبل‌شده (PC)",
                    "آل‌این‌وان (All-in-One)",
                    "تین‌کلاینت (Thin Client)",
                    "پوسته کیس خالی (Case Chassis)",
                ]
            )
            cb_cpu = SearchableComboBox()
            cb_cpu.addItems(CPU_LIST)
            cb_ram = SearchableComboBox()
            cb_ram.addItems(RAM_CAPACITIES)
            cb_st = SearchableComboBox()
            cb_st.addItems(STORAGE_LIST)
            cb_gpu = SearchableComboBox()
            cb_gpu.addItems(GPU_LIST)
            self.fields = {
                "پردازنده": cb_cpu,
                "ظرفیت رم": cb_ram,
                "حافظه داخلی": cb_st,
                "پردازنده گرافیکی": cb_gpu,
            }
            self.form_layout.addRow("نوع دستگاه:", self.cb_sub)
            self.form_layout.addRow("پردازنده (CPU):", cb_cpu)
            self.form_layout.addRow("رم (RAM):", cb_ram)
            self.form_layout.addRow("حافظه (Storage):", cb_st)
            self.form_layout.addRow("گرافیک (GPU):", cb_gpu)

        elif cat_key in (normalize_catalog_label("آداپتور و تغذیه"), normalize_catalog_label("آداپتور")):
            self.cb_sub.currentTextChanged.connect(self._notify_custom_field_callback)
            self.cb_sub.addItems(
                [
                    "شارژر و آداپتور لپ‌تاپ",
                    "آداپتور مانیتور و مینی‌کیس",
                    "آداپتور مودم و سوئیچ (9V/12V)",
                    "محافظ برق و چندراهی",
                    "برق اضطراری (UPS) و باتری UPS",
                    "کابل برق سهند / سه‌پین / دوپین",
                ]
            )
            cb_volt = SearchableComboBox()
            cb_volt.addItems(["", "19V", "19.5V", "20V", "12V", "9V", "5V", "220V AC"])
            cb_amp = SearchableComboBox()
            cb_amp.addItems(["", "1A / 1.5A / 2A", "2.31A (45W)", "3.25A (65W)", "3.42A (65W)", "4.5A (90W)", "4.74A (90W)", "6.15A (120W)", "6.75A / 7.7A (135W-150W)", "9A / 10A (180W-240W)"])
            cb_tip = SearchableComboBox()
            cb_tip.addItems(["", "سوکت معمولی (5.5x2.5)", "سوکت سوزنی آبی/مشکی HP/Dell", "سوکت USB / مستطیلی Lenovo", "سوکت Type-C PD", "سوکت ریز Asus/Acer"])
            self.fields = {"ولتاژ": cb_volt, "آمپر و توان": cb_amp, "نوع سوکت": cb_tip}
            self.form_layout.addRow("نوع آداپتور / تغذیه:", self.cb_sub)
            self.form_layout.addRow("ولتاژ خروجی:", cb_volt)
            self.form_layout.addRow("آمپر / توان (وات):", cb_amp)
            self.form_layout.addRow("نوع سری / سوکت:", cb_tip)

        else:
            # شبکه و مودم، ماشین‌های اداری و سایر موارد
            self.cb_sub.currentTextChanged.connect(self._notify_custom_field_callback)
            self.cb_sub.addItems(
                [
                    "سایر موارد",
                    "مودم ADSL / VDSL",
                    "مودم سیم‌کارتی 4G / 5G / TD-LTE",
                    "روتر و اکسس‌پوینت بی‌سیم",
                    "سوئیچ شبکه (5/8/16/24 پورت)",
                    "کارت شبکه USB / PCIe",
                    "پرینتر و چندکاره",
                    "اسکنر",
                    "کارتریج و تونر",
                ]
            )
            ed_spec = SmartLineEdit("مشخصات فنی، پورت‌ها یا توضیحات تخصصی...")
            self.fields = {"مشخصات": ed_spec}
            self.form_layout.addRow("زیرمجموعه:", self.cb_sub)
            self.form_layout.addRow("مشخصات فنی:", ed_spec)

        self._apply_compact_form_layouts()

    def apply_custom_catalog(self, subcategories=None, custom_fields=None):
        """Apply user-managed subcategories and extra specification fields."""
        if self.cb_sub is not None and isinstance(subcategories, list):
            current = self.cb_sub.currentText()
            clean_subcategories = _unique_catalog_labels(subcategories)
            current_key = normalize_catalog_label(current)
            self.cb_sub.blockSignals(True)
            self.cb_sub.clear()
            self.cb_sub.addItems(clean_subcategories)
            self.cb_sub.setEditable(0)
            selected_index = next(
                (i for i, value in enumerate(clean_subcategories)
                 if normalize_catalog_label(value) == current_key),
                -1,
            )
            if selected_index >= 0:
                self.cb_sub.setCurrentIndex(selected_index)
            elif clean_subcategories:
                self.cb_sub.setCurrentIndex(0)
            else:
                self.cb_sub.setCurrentText("")
            self.cb_sub.blockSignals(False)
            if self.current_category == "قطعات":
                self._rebuild_part_subfields(self.cb_sub.currentText())

        # Remove custom widgets from the previously selected subcategory before
        # adding the next set. Built-in fields remain in place and can be reconfigured.
        for field_name, widget in list(self._custom_field_widgets.items()):
            if self.fields.get(field_name) is widget:
                self.fields.pop(field_name, None)
            # QFormLayout.removeRow(row) owns and destroys the row widgets. Calling
            # deleteLater() afterwards can target an already-deleted Shiboken wrapper.
            try:
                row, _role = self.form_layout.getWidgetPosition(widget)
                if row >= 0:
                    self.form_layout.removeRow(row)
            except RuntimeError:
                # The Qt parent may already have destroyed this widget during a
                # category rebuild; clearing the Python reference is sufficient.
                pass
        self._custom_field_widgets.clear()

        if not isinstance(custom_fields, list):
            return
        seen_custom_names = set()
        for definition in custom_fields:
            if not isinstance(definition, dict):
                continue
            field_name = str(definition.get("name", "")).strip()
            normalized_name = normalize_catalog_label(field_name)
            if not field_name or not normalized_name or normalized_name in seen_custom_names:
                continue
            seen_custom_names.add(normalized_name)
            # The feature name is always the form label. "label" is a storage/output
            # title and may contain @reference syntax, not a widget caption.
            form_label = field_name
            raw_values = definition.get("values", [])
            values = [
                str(value).strip() for value in raw_values
                if str(value).strip()
            ] if isinstance(raw_values, list) else []

            existing_key = next(
                (
                    key for key in self.fields
                    if normalize_catalog_label(key) == normalized_name
                ),
                None,
            )
            existing_widget = self.fields.get(existing_key) if existing_key is not None else None
            if existing_widget is not None:
                try:
                    _ = existing_widget.parent()
                except RuntimeError:
                    self.fields.pop(existing_key, None)
                    existing_widget = None

            if existing_widget is not None:
                try:
                    # A custom Persian spelling (for example «صفحه نمایش») may be the
                    # same feature as a built-in spelling with ZWNJ («صفحه‌نمایش»).
                    # Reuse that widget and rename its storage key instead of showing a
                    # duplicate control in the product form.
                    if existing_key != field_name:
                        self.fields.pop(existing_key, None)
                        self.fields[field_name] = existing_widget
                    if isinstance(existing_widget, QComboBox):
                        current_value = existing_widget.currentText()
                        existing_widget.blockSignals(True)
                        existing_widget.clear()
                        existing_widget.addItem("")
                        existing_widget.addItems(list(dict.fromkeys(values)))
                        if current_value in values:
                            existing_widget.setCurrentText(current_value)
                        existing_widget.blockSignals(False)
                    field_label = self.form_layout.labelForField(existing_widget)
                    if field_label is None and hasattr(self, "sub_layout") and self.sub_layout:
                        field_label = self.sub_layout.labelForField(existing_widget)
                    if isinstance(field_label, QLabel):
                        field_label.setText(f"{form_label}:")
                    existing_widget.setToolTip(f"مشخصه سفارشی: {form_label}")
                    continue
                except RuntimeError:
                    self.fields.pop(field_name, None)
                    self.fields.pop(existing_key, None)
                    existing_widget = None

            if values:
                widget = SearchableComboBox()
                widget.addItem("")
                widget.addItems(list(dict.fromkeys(values)))
            else:
                widget = SmartLineEdit(f"{field_name}...")
            widget.setToolTip(f"مشخصه سفارشی: {form_label}")
            self.fields[field_name] = widget
            self._custom_field_widgets[field_name] = widget
            self.form_layout.addRow(f"{form_label}:", widget)

        # Guarantee universal "مشخصات" is strictly the very last field in self.fields and layout
        specs_key = next((k for k in list(self.fields.keys()) if normalize_catalog_label(k) == normalize_catalog_label("مشخصات")), None)
        if specs_key is not None:
            spec_widget = self.fields.pop(specs_key)
            self.fields[specs_key] = spec_widget
            try:
                row, _ = self.form_layout.getWidgetPosition(spec_widget)
                if row >= 0 and row < self.form_layout.rowCount() - 1:
                    res = self.form_layout.takeRow(row)
                    if res.labelItem and res.labelItem.widget():
                        self.form_layout.addRow(res.labelItem.widget(), spec_widget)
                    else:
                        self.form_layout.addRow(spec_widget)
            except Exception:
                pass

        self._apply_compact_form_layouts()

    def _rebuild_part_subfields(self, part_type: str):
        while self.sub_layout.count():
            it = self.sub_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.fields.clear()

        if "CPU" in part_type or "پردازنده" in part_type:
            cb_title = SearchableComboBox()
            cb_title.addItems(CPU_LIST)
            cb_sock = SearchableComboBox()
            cb_sock.addItems(["", "LGA 775 / 1155 / 1150", "LGA 1151", "LGA 1200", "LGA 1700", "AM4", "AM5"])
            self.fields = {"سری پردازنده": cb_title, "سوکت": cb_sock}
            self.sub_layout.addRow("عنوان و نسل CPU:", cb_title)
            self.sub_layout.addRow("سوکت پردازنده:", cb_sock)

        elif "RAM" in part_type or "رم" in part_type:
            cb_cap = SearchableComboBox()
            cb_cap.addItems(RAM_CAPACITIES)
            cb_ddr = SearchableComboBox()
            # Start blank so DDR2 is never silently assigned to an unspecified module.
            cb_ddr.addItems(["", "DDR2", "DDR3 / DDR3L", "DDR4", "DDR5"])
            cb_bus = SearchableComboBox()
            cb_bus.addItems(["", "1333MHz", "1600MHz", "2400MHz", "2666MHz", "3200MHz", "3600MHz", "4800MHz", "5600MHz", "6000MHz"])
            self.fields = {"ظرفیت": cb_cap, "نسخه DDR": cb_ddr, "فرکانس": cb_bus}
            self.sub_layout.addRow("ظرفیت رم:", cb_cap)
            self.sub_layout.addRow("نسخه DDR:", cb_ddr)
            self.sub_layout.addRow("فرکانس (Bus):", cb_bus)

        elif "SSD" in part_type or "HDD" in part_type or "هارد" in part_type:
            cb_cap = SearchableComboBox()
            cb_cap.addItems(STORAGE_LIST)
            cb_iface = SearchableComboBox()
            cb_iface.addItems(["NVMe M.2 PCIe", "M.2 SATA", "SATA 2.5 اینچ", "SATA 3.5 اینچ (کیس)"])
            self.fields = {"ظرفیت": cb_cap, "رابط و فرم": cb_iface}
            self.sub_layout.addRow("ظرفیت حافظه:", cb_cap)
            self.sub_layout.addRow("نوع رابط و سایز:", cb_iface)

        elif "گرافیک" in part_type or "Graphic" in part_type:
            cb_gpu = SearchableComboBox()
            cb_gpu.addItems(GPU_LIST)
            cb_vram = SearchableComboBox()
            cb_vram.addItems(["", "1GB", "2GB", "4GB", "6GB", "8GB", "12GB", "16GB", "24GB"])
            self.fields = {"چیپست گرافیک": cb_gpu, "حافظه VRAM": cb_vram}
            self.sub_layout.addRow("مدل چیپ گرافیک:", cb_gpu)
            self.sub_layout.addRow("ظرفیت حافظه گرافیک:", cb_vram)

        elif "پاور" in part_type or "Power" in part_type:
            cb_watt = SearchableComboBox()
            cb_watt.addItems(["", "250W - 330W", "380W - 430W", "480W - 550W", "600W - 700W", "750W - 850W", "1000W+"])
            cb_cert = SearchableComboBox()
            cb_cert.addItems(["", "معمولی", "80Plus Standard/White", "80Plus Bronze", "80Plus Gold", "Full Modular"])
            self.fields = {"توان پاور": cb_watt, "استاندارد": cb_cert}
            self.sub_layout.addRow("توان خروجی (Watt):", cb_watt)
            self.sub_layout.addRow("استاندارد / کابل‌کشی:", cb_cert)

        else:
            self.fields = {}

        self._apply_compact_form_layouts()
        # Run only after the built-in fields for the newly selected part type exist.
        self._notify_custom_field_callback()

    def get_sub_category(self) -> str:
        if self.cb_sub:
            return self.cb_sub.currentText().strip() or "سایر موارد"
        return "سایر موارد"

    def set_sub_category(self, sub_text: str):
        if self.cb_sub and sub_text:
            self.cb_sub.setCurrentText(sub_text)

    def get_specs_dict(self) -> dict:
        res = {}
        for k, w in self.fields.items():
            val = w.currentText() if isinstance(w, QComboBox) else w.text()
            if val.strip():
                res[k] = val.strip()
        return res

    def set_specs_dict(self, data: dict):
        if not isinstance(data, dict):
            return
        for k, val in data.items():
            if k in self.fields:
                w = self.fields[k]
                if isinstance(w, QComboBox):
                    w.setCurrentText(str(val))
                else:
                    w.setText(str(val))


class DynamicDomainValueRow(QWidget):
    """Single row representing one domain/suggested value with input field and dedicated (+) and (-) buttons."""
    removed = Signal(object)
    added_after = Signal(object)
    changed = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(6)

        self.ed_value = QLineEdit(text)
        self.ed_value.setPlaceholderText("مقدار پیشنهادی (مثلاً USB 3.0, Type-C, HDMI)...")
        self.ed_value.textChanged.connect(lambda: self.changed.emit())

        self.btn_add = QPushButton("➕")
        self.btn_add.setToolTip("افزودن مقدار جدید بعد از این سطر")
        self.btn_add.setFixedSize(28, 28)
        self.btn_add.clicked.connect(lambda: self.added_after.emit(self))

        self.btn_remove = QPushButton("➖")
        self.btn_remove.setToolTip("حذف این مقدار")
        self.btn_remove.setFixedSize(28, 28)
        self.btn_remove.setObjectName("btnDanger")
        self.btn_remove.clicked.connect(lambda: self.removed.emit(self))

        layout.addWidget(self.ed_value, 1)
        layout.addWidget(self.btn_add)
        layout.addWidget(self.btn_remove)

    def text(self) -> str:
        return self.ed_value.text().strip()

    def setText(self, text: str):
        self.ed_value.setText(text)


class DynamicAttributeValuesWidget(QWidget):
    """Dynamic list view component replacing comma-separated text fields for sub-category domains."""
    valuesChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(4)

        self.scroll_area = SmoothScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(90)
        self.scroll_area.setMaximumHeight(150)

        self.container = QWidget()
        self.rows_layout = QVBoxLayout(self.container)
        self.rows_layout.setContentsMargins(4, 4, 4, 4)
        self.rows_layout.setSpacing(4)
        self.rows_layout.addStretch()

        self.scroll_area.setWidget(self.container)
        main_layout.addWidget(self.scroll_area)

        btn_bar = QHBoxLayout()
        self.btn_add_initial = QPushButton("➕ افزودن مقدار جدید")
        self.btn_add_initial.setObjectName("btnSecondary")
        self.btn_add_initial.clicked.connect(lambda: self.add_row(""))
        btn_bar.addWidget(self.btn_add_initial)
        btn_bar.addStretch()
        main_layout.addLayout(btn_bar)

        self.rows = []
        self.add_row("")

    def get_values(self) -> list:
        result = []
        for r in self.rows:
            val = r.text()
            if val and val not in result:
                result.append(val)
        return result

    def set_values(self, values_list: list):
        self.clear()
        if not values_list:
            self.add_row("")
            return
        for val in values_list:
            val_str = str(val).strip()
            if val_str:
                self.add_row(val_str)
        if not self.rows:
            self.add_row("")

    def add_row(self, text="", after_row=None):
        row = DynamicDomainValueRow(text, self.container)
        row.removed.connect(self._on_remove_row)
        row.added_after.connect(self._on_add_after)
        row.changed.connect(lambda: self.valuesChanged.emit())

        if after_row is not None and after_row in self.rows:
            idx = self.rows.index(after_row)
            self.rows.insert(idx + 1, row)
            self.rows_layout.insertWidget(idx + 1, row)
        else:
            idx = len(self.rows)
            self.rows.append(row)
            self.rows_layout.insertWidget(idx, row)

        self.valuesChanged.emit()
        return row

    def _on_remove_row(self, row):
        if row in self.rows:
            self.rows.remove(row)
            self.rows_layout.removeWidget(row)
            row.deleteLater()
            if not self.rows:
                self.add_row("")
            self.valuesChanged.emit()

    def _on_add_after(self, row):
        self.add_row("", after_row=row)

    def clear(self):
        for r in list(self.rows):
            self.rows_layout.removeWidget(r)
            r.deleteLater()
        self.rows.clear()