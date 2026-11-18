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
    QStyledItemDelegate,
)
from PySide6.QtCore import (
    Qt,
    Signal,
    QEvent,
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

# فهرست جامع دسته‌بندی‌های اصلی فروشگاه (100% فارسی)
MAIN_CATEGORIES = [
    "لپ تاپ",
    "کیس و سیستم آماده",
    "قطعات",
    "ذخیره ساز و حافظه",
    "مانیتور و نمایشگر",
    "لوازم جانبی",
    "تجهیزات شبکه",
    "ماشین های اداری",
    "کابل و مبدل",
    "سایر موارد",
]

# زیرمجموعه‌های پیش‌فرض استاندارد بین‌المللی با فرمت دو زبانه "فارسی (English)"
DEFAULT_SUBCATEGORIES = {
    "لپ تاپ": [
        "لپ تاپ عمومی و مالتی مدیا (General & Multimedia Laptop)",
        "لپ تاپ گیمینگ (Gaming Laptop)",
        "لپ تاپ مهندسی و رندرینگ (Workstation & Engineering Laptop)",
        "اولترابوک و باریک (Ultrabook & Slim)",
        "مک بوک (MacBook)",
        "سایر موارد (Other)",
    ],
    "کیس و سیستم آماده": [
        "کیس کامل اسمبل شده (Desktop PC)",
        "مینی کیس (Mini PC)",
        "آل این وان (All-in-One)",
        "تین کلاینت و زیرو کلاینت (Thin Client & Zero Client)",
        "پوسته کیس (Case)",
        "سایر موارد (Other)",
    ],
    "قطعات": [
        "پردازنده (CPU)",
        "مادربرد (Motherboard)",
        "کارت گرافیک (GPU)",
        "رم کامپیوتر (Desktop RAM)",
        "رم لپ تاپ (Laptop RAM)",
        "منبع تغذیه (PSU)",
        "خنک کننده (Cooler)",
        "درایو نوری (Optical Drive)",
        "کارت صدا و شبکه (Sound & Network Card)",
        "سایر موارد (Other)",
    ],
    "ذخیره ساز و حافظه": [
        "حافظه اس اس دی (SSD)",
        "هارد دیسک اینترنال (Internal HDD)",
        "هارد اکسترنال (External HDD)",
        "اس اس دی اکسترنال (External SSD)",
        "فلش مموری (Flash Drive)",
        "کارت حافظه (Memory Card)",
        "سایر موارد (Other)",
    ],
    "مانیتور و نمایشگر": [
        "مانیتور اداری و خانگی (Office & Home Monitor)",
        "مانیتور گیمینگ (Gaming Monitor)",
        "مانیتور طراحی و حرفه ای (Professional & Design Monitor)",
        "مانیتور خمیده (Curved Monitor)",
        "سایر موارد (Other)",
    ],
    "لوازم جانبی": [
        "ماوس (Mouse)",
        "کیبورد (Keyboard)",
        "کمبو ماوس و کیبورد (Keyboard & Mouse Combo)",
        "هدست و هدفون (Headset & Headphones)",
        "اسپیکر (Speaker)",
        "پد ماوس (Mousepad)",
        "وب کم (Webcam)",
        "میکروفون (Microphone)",
        "کول پد و خنک کننده لپ تاپ (Laptop Cooling Pad)",
        "کیف و کوله پشتی (Bag & Backpack)",
        "دسته بازی (Gamepad & Controller)",
        "سایر موارد (Other)",
    ],
    "تجهیزات شبکه": [
        "مودم و روتر (Modem & Router)",
        "سوئیچ شبکه (Network Switch)",
        "اکسس پوینت (Access Point)",
        "کارت شبکه (Network Adapter)",
        "سایر موارد (Other)",
    ],
    "ماشین های اداری": [
        "پرینتر (Printer)",
        "اسکنر (Scanner)",
        "دستگاه کپی (Copier)",
        "کارتریج و تونر (Cartridge & Toner)",
        "بارکدخوان (Barcode Scanner)",
        "سایر موارد (Other)",
    ],
    "کابل و مبدل": [
        "کابل تصویر (Video Cable - HDMI / DP / VGA)",
        "کابل و تبدیل برق (Power Cable & Adapter)",
        "کابل شبکه (LAN / Ethernet Cable)",
        "کابل و رابط USB و Type-C (USB & Type-C Cable)",
        "مبدل و دانگل (Converter & Dongle)",
        "هاب USB و Type-C (USB & Type-C Hub)",
        "سایر موارد (Other)",
    ],
    "سایر موارد": [
        "سایر موارد (Other)",
    ],
}

# مقادیر استاندارد بین‌المللی انگلیسی برای ویژگی‌ها
CPU_LIST = [
    "",
    "Intel Core i3",
    "Intel Core i5",
    "Intel Core i7",
    "Intel Core i9",
    "Intel Core Ultra 5",
    "Intel Core Ultra 7",
    "Intel Core Ultra 9",
    "Intel Xeon",
    "Intel Pentium / Celeron",
    "AMD Ryzen 3",
    "AMD Ryzen 5",
    "AMD Ryzen 7",
    "AMD Ryzen 9",
    "AMD Ryzen AI 7 / 9",
    "AMD Threadripper",
    "Apple M1 / M2 / M3 / M4",
]

RAM_CAPACITIES = [
    "",
    "2GB",
    "4GB",
    "8GB",
    "16GB",
    "24GB",
    "32GB",
    "64GB",
    "128GB",
]

DDR_VERSIONS = [
    "",
    "DDR2",
    "DDR3 / DDR3L",
    "DDR4",
    "DDR5",
    "LPDDR4 / LPDDR5",
]

RAM_FREQUENCIES = [
    "",
    "800MHz",
    "1333MHz",
    "1600MHz",
    "2133MHz",
    "2400MHz",
    "2666MHz",
    "3000MHz",
    "3200MHz",
    "3600MHz",
    "4800MHz",
    "5200MHz",
    "5600MHz",
    "6000MHz",
    "6400MHz",
]

SYSTEM_STORAGE_LIST = [
    "",
    "128GB SSD",
    "256GB SSD",
    "512GB SSD",
    "1TB SSD",
    "2TB SSD",
    "500GB HDD",
    "1TB HDD",
    "2TB HDD",
    "128GB SSD + 1TB HDD",
    "256GB SSD + 1TB HDD",
    "512GB SSD + 1TB HDD",
    "1TB SSD + 2TB HDD",
]

SSD_CAPACITIES = [
    "",
    "120GB",
    "128GB",
    "240GB",
    "256GB",
    "480GB",
    "500GB",
    "512GB",
    "960GB",
    "1TB",
    "2TB",
    "4TB",
    "8TB",
]

HDD_CAPACITIES = [
    "",
    "500GB",
    "1TB",
    "2TB",
    "4TB",
    "6TB",
    "8TB",
    "10TB",
    "12TB",
    "16TB",
    "18TB",
    "20TB",
]

SSD_INTERFACES = [
    "",
    "M.2 NVMe PCIe 3.0",
    "M.2 NVMe PCIe 4.0",
    "M.2 NVMe PCIe 5.0",
    "M.2 SATA (NGFF)",
    "SATA III 2.5-inch",
    "PCIe Add-in Card (AIC)",
    "U.2 / U.3",
    "mSATA",
]

HDD_INTERFACES = [
    "",
    "SATA III 3.5-inch",
    "SATA III 2.5-inch",
    "SAS 3.5-inch",
    "SAS 2.5-inch",
]

GPU_LIST = [
    "",
    "Intel HD / UHD Graphics (Onboard)",
    "Intel Iris Xe Graphics",
    "AMD Radeon Graphics (Integrated)",
    "NVIDIA GeForce GT 710 / 730 / 1030",
    "NVIDIA GeForce GTX 1650 / 1660 / 1660 Super / Ti",
    "NVIDIA GeForce RTX 2060 / 2070 / 2080",
    "NVIDIA GeForce RTX 3050 / 3060 / 3070 / 3080 / 3090",
    "NVIDIA GeForce RTX 4050 / 4060 / 4070 / 4080 / 4090",
    "AMD Radeon RX 580 / 590",
    "AMD Radeon RX 6600 / 6700 / 6800 / 6900 XT",
    "AMD Radeon RX 7600 / 7700 / 7800 / 7900 XT",
]

CONNECTIVITY_OPTIONS = [
    "",
    "Wired USB-A",
    "Wired USB-C",
    "Wireless 2.4GHz (USB Dongle)",
    "Bluetooth",
    "Dual-Mode (Wired + Wireless 2.4GHz)",
    "Dual-Mode (Wired + Bluetooth)",
    "Dual-Mode (Wireless 2.4GHz + Bluetooth)",
    "Tri-Mode / Multi-Mode (Wired + 2.4GHz + Bluetooth)",
    "3.5mm Audio Jack",
    "USB + 3.5mm Jack",
]

BAG_TYPES = [
    "",
    "Backpack",
    "Shoulder Bag",
    "Sleeve",
    "Hard Case",
]

BAG_SIZES = [
    "",
    "13-inch",
    "14-inch",
    "15.6-inch",
    "16-inch",
    "17.3-inch",
]

BAG_MATERIALS = [
    "",
    "Water-Resistant Polyester",
    "Nylon",
    "Leather",
    "Anti-Theft Hard Shell",
]

SCREEN_SIZES = [
    "",
    "13.3-inch",
    "14-inch",
    "15.6-inch",
    "16-inch",
    "17.3-inch",
    "19-inch",
    "20-inch",
    "21.5-inch",
    "22-inch",
    "24-inch",
    "27-inch",
    "32-inch",
    "34-inch",
    "49-inch",
]

RESOLUTIONS = [
    "",
    "HD (1366x768)",
    "HD+ (1600x900)",
    "FHD (1920x1080)",
    "2K / QHD (2560x1440)",
    "4K UHD (3840x2160)",
    "UltraWide FHD (2560x1080)",
    "UltraWide QHD (3440x1440)",
]

PANEL_TYPES = [
    "",
    "IPS",
    "VA",
    "TN",
    "OLED",
    "Fast IPS",
    "Nano IPS",
]

REFRESH_RATES = [
    "",
    "60Hz",
    "75Hz",
    "100Hz",
    "120Hz",
    "144Hz",
    "165Hz",
    "180Hz",
    "240Hz",
    "360Hz",
]

STORAGE_LIST = SYSTEM_STORAGE_LIST

DEFAULT_COLORS = [
    "مشکی", "سفید", "نقره‌ای", "خاکستری", "ذغالی", "سرمه‌ای",
    "آبی", "قرمز", "زرشکی", "سبز", "زیتونی", "طلایی",
    "رزگلد", "صورتی", "بنفش", "قهوه‌ای", "بژ", "شفاف",
    "چند‌رنگ", "سایر",
]

DEFAULT_ATTRIBUTES = {
    "لپ تاپ": [
        {"name": "پردازنده", "label": "CPU", "values": CPU_LIST[1:]},
        {"name": "ظرفیت رم", "label": "RAM Capacity", "values": RAM_CAPACITIES[1:]},
        {"name": "نسخه DDR", "label": "DDR Version", "values": DDR_VERSIONS[1:]},
        {"name": "حافظه داخلی", "label": "Storage", "values": SYSTEM_STORAGE_LIST[1:]},
        {"name": "پردازنده گرافیکی", "label": "GPU", "values": GPU_LIST[1:]},
        {"name": "سایز صفحه نمایش", "label": "Screen Size", "values": SCREEN_SIZES[1:]},
        {"name": "دقت صفحه نمایش", "label": "Resolution", "values": RESOLUTIONS[1:]},
        {"name": "نرخ نوسازی", "label": "Refresh Rate", "values": REFRESH_RATES[1:]},
        {"name": "مشخصات", "label": "Specifications", "values": []},
    ],
    "کیس و سیستم آماده": [
        {"name": "پردازنده", "label": "CPU", "values": CPU_LIST[1:]},
        {"name": "ظرفیت رم", "label": "RAM Capacity", "values": RAM_CAPACITIES[1:]},
        {"name": "نسخه DDR", "label": "DDR Version", "values": DDR_VERSIONS[1:]},
        {"name": "حافظه داخلی", "label": "Storage", "values": SYSTEM_STORAGE_LIST[1:]},
        {"name": "پردازنده گرافیکی", "label": "GPU", "values": GPU_LIST[1:]},
        {"name": "مشخصات", "label": "Specifications", "values": []},
    ],
    "قطعات": [
        {"name": "سری پردازنده", "label": "Processor Series", "values": CPU_LIST[1:], "subcategory": "پردازنده (CPU)"},
        {"name": "سوکت", "label": "Socket", "values": ["LGA 775", "LGA 1155", "LGA 1150", "LGA 1151", "LGA 1200", "LGA 1700", "LGA 1851", "AM3 / AM3+", "AM4", "AM5", "TR4 / sTRX4", "BGA"], "subcategory": "پردازنده (CPU)"},
        {"name": "سوکت", "label": "Socket", "values": ["LGA 1155", "LGA 1150", "LGA 1151", "LGA 1200", "LGA 1700", "LGA 1851", "AM4", "AM5"], "subcategory": "مادربرد (Motherboard)"},
        {"name": "چیپست", "label": "Chipset", "values": ["Intel H81 / B85", "Intel H110 / B250", "Intel H310 / B360 / B365", "Intel H410 / B460 / Z490", "Intel H510 / B560 / Z590", "Intel H610 / B660 / B760 / Z790", "AMD A320 / B450 / X470 / B550 / X570", "AMD A620 / B650 / X670 / X870"], "subcategory": "مادربرد (Motherboard)"},
        {"name": "فرم فاکتور", "label": "Form Factor", "values": ["ATX", "Micro-ATX (mATX)", "Mini-ITX", "E-ATX"], "subcategory": "مادربرد (Motherboard)"},
        {"name": "نسخه DDR", "label": "DDR Version", "values": DDR_VERSIONS[1:], "subcategory": "مادربرد (Motherboard)"},
        {"name": "چیپست گرافیک", "label": "GPU Chipset", "values": GPU_LIST[1:], "subcategory": "کارت گرافیک (GPU)"},
        {"name": "حافظه VRAM", "label": "VRAM Capacity", "values": ["1GB", "2GB", "4GB", "6GB", "8GB", "10GB", "12GB", "16GB", "20GB", "24GB"], "subcategory": "کارت گرافیک (GPU)"},
        {"name": "نوع حافظه", "label": "Memory Type", "values": ["GDDR3", "GDDR5", "GDDR6", "GDDR6X"], "subcategory": "کارت گرافیک (GPU)"},
        {"name": "ظرفیت", "label": "Capacity", "values": RAM_CAPACITIES[1:], "subcategory": "رم کامپیوتر (Desktop RAM)"},
        {"name": "نسخه DDR", "label": "DDR Version", "values": DDR_VERSIONS[1:], "subcategory": "رم کامپیوتر (Desktop RAM)"},
        {"name": "فرکانس", "label": "Frequency", "values": RAM_FREQUENCIES[1:], "subcategory": "رم کامپیوتر (Desktop RAM)"},
        {"name": "ظرفیت", "label": "Capacity", "values": RAM_CAPACITIES[1:], "subcategory": "رم لپ تاپ (Laptop RAM)"},
        {"name": "نسخه DDR", "label": "DDR Version", "values": DDR_VERSIONS[1:], "subcategory": "رم لپ تاپ (Laptop RAM)"},
        {"name": "فرکانس", "label": "Frequency", "values": RAM_FREQUENCIES[1:], "subcategory": "رم لپ تاپ (Laptop RAM)"},
        {"name": "توان خروجی", "label": "Wattage", "values": ["300W", "350W", "400W", "450W", "500W", "550W", "600W", "650W", "700W", "750W", "850W", "1000W", "1200W+"], "subcategory": "منبع تغذیه (PSU)"},
        {"name": "استاندارد بازدهی", "label": "Efficiency Certification", "values": ["Standard", "80 Plus Bronze", "80 Plus Silver", "80 Plus Gold", "80 Plus Platinum", "80 Plus Titanium"], "subcategory": "منبع تغذیه (PSU)"},
        {"name": "مدیریت کابل", "label": "Modularity", "values": ["Non-Modular", "Semi-Modular", "Full Modular"], "subcategory": "منبع تغذیه (PSU)"},
        {"name": "نوع خنک کننده", "label": "Cooler Type", "values": ["Air Cooler", "Liquid Cooler 120mm (AIO)", "Liquid Cooler 240mm (AIO)", "Liquid Cooler 360mm (AIO)"], "subcategory": "خنک کننده (Cooler)"},
        {"name": "نورپردازی", "label": "Lighting", "values": ["None", "Single Color LED", "RGB", "ARGB"], "subcategory": "خنک کننده (Cooler)"},
        {"name": "مشخصات", "label": "Specifications", "values": []},
    ],
    "ذخیره ساز و حافظه": [
        {"name": "ظرفیت", "label": "Capacity", "values": SSD_CAPACITIES[1:], "subcategory": "حافظه اس اس دی (SSD)"},
        {"name": "رابط و فرم", "label": "Interface & Form Factor", "values": SSD_INTERFACES[1:], "subcategory": "حافظه اس اس دی (SSD)"},
        {"name": "ظرفیت", "label": "Capacity", "values": HDD_CAPACITIES[1:], "subcategory": "هارد دیسک اینترنال (Internal HDD)"},
        {"name": "رابط و فرم", "label": "Interface & Form Factor", "values": HDD_INTERFACES[1:], "subcategory": "هارد دیسک اینترنال (Internal HDD)"},
        {"name": "ظرفیت", "label": "Capacity", "values": SSD_CAPACITIES[1:], "subcategory": "هارد اکسترنال (External HDD)"},
        {"name": "نوع اتصال / پورت", "label": "Connectivity / Port", "values": ["USB 3.0 / USB 3.2 Gen 1", "USB 3.2 Gen 2 (Type-C)", "USB4 / Thunderbolt"], "subcategory": "هارد اکسترنال (External HDD)"},
        {"name": "ظرفیت", "label": "Capacity", "values": SSD_CAPACITIES[1:], "subcategory": "اس اس دی اکسترنال (External SSD)"},
        {"name": "نوع اتصال / پورت", "label": "Connectivity / Port", "values": ["USB 3.2 Gen 2 (Type-C)", "USB 3.2 Gen 2x2 (20Gbps)", "USB4 / Thunderbolt"], "subcategory": "اس اس دی اکسترنال (External SSD)"},
        {"name": "ظرفیت", "label": "Capacity", "values": ["16GB", "32GB", "64GB", "128GB", "256GB", "512GB", "1TB"], "subcategory": "فلش مموری (Flash Drive)"},
        {"name": "نوع رابط", "label": "Interface", "values": ["USB 2.0", "USB 3.0 / 3.2", "Dual USB-A + Type-C"], "subcategory": "فلش مموری (Flash Drive)"},
        {"name": "ظرفیت", "label": "Capacity", "values": ["16GB", "32GB", "64GB", "128GB", "256GB", "512GB"], "subcategory": "کارت حافظه (Memory Card)"},
        {"name": "نوع رابط", "label": "Interface", "values": ["microSDXC / SDXC UHS-I", "microSDXC UHS-II"], "subcategory": "کارت حافظه (Memory Card)"},
        {"name": "مشخصات", "label": "Specifications", "values": []},
    ],
    "مانیتور و نمایشگر": [
        {"name": "سایز صفحه نمایش", "label": "Screen Size", "values": SCREEN_SIZES[1:]},
        {"name": "نوع پنل", "label": "Panel Type", "values": PANEL_TYPES[1:]},
        {"name": "دقت تصویر", "label": "Resolution", "values": RESOLUTIONS[1:]},
        {"name": "نرخ نوسازی", "label": "Refresh Rate", "values": REFRESH_RATES[1:]},
        {"name": "پورت های ورودی", "label": "Input Ports", "values": ["HDMI + VGA", "HDMI + DisplayPort", "HDMI + DP + Type-C", "Dual HDMI + DP", "VGA + DVI"]},
        {"name": "مشخصات", "label": "Specifications", "values": []},
    ],
    "لوازم جانبی": [
        {"name": "نوع اتصال / پورت", "label": "Connectivity / Port", "values": CONNECTIVITY_OPTIONS[1:], "subcategory": "ماوس (Mouse)"},
        {"name": "دقت حسگر (DPI)", "label": "Sensor DPI", "values": ["1000 DPI", "1200 DPI", "1600 DPI", "2400 DPI", "3200 DPI", "6400 DPI", "12000+ DPI (Gaming)"], "subcategory": "ماوس (Mouse)"},
        {"name": "نوع اتصال / پورت", "label": "Connectivity / Port", "values": CONNECTIVITY_OPTIONS[1:], "subcategory": "کیبورد (Keyboard)"},
        {"name": "نوع سوییچ / کلید", "label": "Switch Type", "values": ["Membrane", "Mechanical Blue Switch", "Mechanical Red Switch", "Mechanical Brown Switch", "Optical-Mechanical"], "subcategory": "کیبورد (Keyboard)"},
        {"name": "نوع اتصال / پورت", "label": "Connectivity / Port", "values": CONNECTIVITY_OPTIONS[1:], "subcategory": "کمبو ماوس و کیبورد (Keyboard & Mouse Combo)"},
        {"name": "نوع اتصال / پورت", "label": "Connectivity / Port", "values": CONNECTIVITY_OPTIONS[1:], "subcategory": "هدست و هدفون (Headset & Headphones)"},
        {"name": "نوع اتصال / پورت", "label": "Connectivity / Port", "values": CONNECTIVITY_OPTIONS[1:], "subcategory": "اسپیکر (Speaker)"},
        {"name": "نوع کاربری", "label": "Type", "values": BAG_TYPES[1:], "subcategory": "کیف و کوله پشتی (Bag & Backpack)"},
        {"name": "سایز مناسب لپ تاپ", "label": "Compatible Size", "values": BAG_SIZES[1:], "subcategory": "کیف و کوله پشتی (Bag & Backpack)"},
        {"name": "جنس و مقاومت", "label": "Material", "values": BAG_MATERIALS[1:], "subcategory": "کیف و کوله پشتی (Bag & Backpack)"},
        {"name": "نوع اتصال / پورت", "label": "Connectivity / Port", "values": CONNECTIVITY_OPTIONS[1:]},
        {"name": "مشخصات", "label": "Specifications", "values": []},
    ],
    "تجهیزات شبکه": [
        {"name": "استاندارد وای فای", "label": "Wi-Fi Standard", "values": ["Wi-Fi 4 (802.11n)", "Wi-Fi 5 (802.11ac)", "Wi-Fi 6 (802.11ax)", "Wi-Fi 6E", "Wi-Fi 7", "4G LTE", "5G"]},
        {"name": "سرعت پورت های شبکه", "label": "Port Speed", "values": ["10/100 Fast Ethernet", "Gigabit (10/100/1000)", "2.5G / 10G Multi-Gig"]},
        {"name": "مشخصات", "label": "Specifications", "values": []},
    ],
    "ماشین های اداری": [
        {"name": "فناوری چاپ", "label": "Print Technology", "values": ["Laser Monochrome", "Laser Color", "Inkjet Color", "Thermal"]},
        {"name": "قابلیت های دستگاه", "label": "Functions", "values": ["Single Function (Print Only)", "3-in-1 (Print, Scan, Copy)", "4-in-1 (Print, Scan, Copy, Fax)"]},
        {"name": "نوع اتصال", "label": "Connectivity", "values": ["USB Only", "USB + Network (LAN)", "USB + Wi-Fi", "USB + LAN + Wi-Fi"]},
        {"name": "مشخصات", "label": "Specifications", "values": []},
    ],
    "کابل و مبدل": [
        {"name": "نوع درگاه / رابط", "label": "Connector Type", "values": ["HDMI to HDMI", "DisplayPort to DisplayPort", "HDMI to VGA", "Type-C to HDMI", "Type-C to Type-C", "USB-A to Type-C", "USB-A to USB-B (Printer)", "Cat6 RJ45"]},
        {"name": "طول کابل", "label": "Cable Length", "values": ["0.5m", "1m", "1.5m", "1.8m", "2m", "3m", "5m", "10m", "15m", "20m+"]},
        {"name": "مشخصات", "label": "Specifications", "values": []},
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

    def selectRow(self, row: int):
        super().selectRow(row)
        if 0 <= row < self.rowCount() and not self.selectionModel().hasSelection():
            self.setCurrentCell(row, 0)

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
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(18)

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

    def collapse(self):
        if self._expanded:
            self._expanded = False
            self.content.hide()
            title = self.header.text().lstrip("▸▾ ").strip()
            self.header.setText("▸  " + title)

    def expand(self):
        if not self._expanded:
            self._expanded = True
            self.content.show()
            title = self.header.text().lstrip("▸▾ ").strip()
            self.header.setText("▾  " + title)

    def is_expanded(self) -> bool:
        return self._expanded

    def _on_header_pressed(self):
        if self._expanded:
            self.collapse()
        else:
            self.expand()


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
        haystack = auto_capitalize_english(f"{visible} {searchable}")
        return self.query in haystack


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


class FullRowCheckDelegate(QStyledItemDelegate):
    """Ensure clicking anywhere on an item row or label toggles its check state without double toggling."""
    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            current = index.data(Qt.CheckStateRole)
            if current is not None:
                new_state = Qt.Unchecked if current == Qt.Checked else Qt.Checked
                model.setData(index, new_state, Qt.CheckStateRole)
                return True
        return super().editorEvent(event, model, option, index)


class _FormLayoutCompat:
    """Compatibility adapter for tests expecting a QFormLayout API on DynamicSpecsWidget."""
    def __init__(self, owner):
        self._owner = owner

    def labelForField(self, field_widget):
        return self._owner._field_labels.get(field_widget)


class DynamicSpecsWidget(QWidget):
    """
    ویجت تخصصی و پیشرفته مشخصات فنی زیرمجموعه‌ها با چیدمان گرید دو ستونه منظم و ریسپانسیو.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(4, 4, 4, 4)
        self.main_layout.setSpacing(8)

        # ردیف بالای انتخاب زیرمجموعه
        self.sub_header_layout = QHBoxLayout()
        self.sub_header_layout.setSpacing(8)
        self.lbl_sub = QLabel("زیرمجموعه:")
        self.lbl_sub.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_sub.setMinimumWidth(80)
        self.cb_sub = SearchableComboBox()
        self.cb_sub.setEditable(0)
        self.cb_sub.setToolTip("زیرمجموعه را از فهرست انتخاب کنید")
        self.sub_header_layout.addWidget(self.lbl_sub)
        self.sub_header_layout.addWidget(self.cb_sub, 1)
        self.main_layout.addLayout(self.sub_header_layout)

        # کانتینر مشخصات فنی تخصصی با لایه‌بندی شبکه (Grid) دو ستونه
        self.sub_container = QWidget()
        self.sub_container.setLayoutDirection(Qt.RightToLeft)
        self.sub_layout = QGridLayout(self.sub_container)
        self.sub_layout.setContentsMargins(0, 4, 0, 4)
        self.sub_layout.setHorizontalSpacing(10)
        self.sub_layout.setVerticalSpacing(8)
        self.main_layout.addWidget(self.sub_container)

        self.current_category = "لپ تاپ"
        self.fields = {}
        self._custom_field_widgets = {}
        self._field_labels = {}
        self.form_layout = _FormLayoutCompat(self)
        self._custom_field_callback = None
        self.set_category("لپ تاپ")

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
        while self.sub_layout.count():
            item = self.sub_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.fields.clear()
        self._custom_field_widgets.clear()

    def set_subcategory_label(self, label: str):
        """Customize the caption associated with the category-specific subcategory selector."""
        if hasattr(self, "lbl_sub") and self.lbl_sub is not None:
            self.lbl_sub.setText(f"{str(label or 'زیرمجموعه').strip()}:")

    def set_category(self, category: str):
        self.current_category = category.strip()
        self._clear_form()

        cat_key = self.current_category
        for k in DEFAULT_SUBCATEGORIES:
            if normalize_catalog_label(k) == normalize_catalog_label(self.current_category):
                cat_key = k
                break

        subs = DEFAULT_SUBCATEGORIES.get(cat_key, ["سایر موارد (Other)"])
        self.cb_sub.blockSignals(True)
        self.cb_sub.clear()
        self.cb_sub.addItems(subs)
        self.cb_sub.blockSignals(False)
        self.lbl_sub.setText(f"زیرمجموعه {self.current_category}:")

        try:
            self.cb_sub.currentTextChanged.disconnect()
        except Exception:
            pass
        self.cb_sub.currentTextChanged.connect(self._rebuild_subfields)
        if subs:
            self._rebuild_subfields(subs[0])

    def _rebuild_subfields(self, sub_text: str = ""):
        if not hasattr(self, "sub_layout") or self.sub_layout is None:
            return
        while self.sub_layout.count():
            it = self.sub_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.fields.clear()
        self._custom_field_widgets.clear()
        self._field_labels.clear()

        sub_clean = (sub_text or (self.cb_sub.currentText() if self.cb_sub else "")).strip()
        cat_norm = normalize_catalog_label(self.current_category)

        # Rule B.1: If "سایر موارد" or "Other", keep ONLY "مشخصات" (Specifications)
        if "سایر موارد" in sub_clean or "other" in sub_clean.lower() or cat_norm == normalize_catalog_label("سایر موارد"):
            ed_spec = SmartLineEdit("مشخصات فنی یا توضیحات...")
            lbl_spec = QLabel("مشخصات (Specifications):")
            lbl_spec.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl_spec.setMinimumWidth(80)
            ed_spec.setMinimumHeight(30)
            ed_spec.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.sub_layout.addWidget(lbl_spec, 0, 0)
            self.sub_layout.addWidget(ed_spec, 0, 1, 1, 3)
            self.fields["مشخصات"] = ed_spec
            self._field_labels[ed_spec] = lbl_spec
            self._notify_custom_field_callback()
            return

        regular_fields = []
        ed_spec = None

        if "لپ تاپ" in cat_norm or "لپتاپ" in cat_norm:
            cb_cpu = SearchableComboBox()
            cb_cpu.addItems(CPU_LIST)
            cb_ram = SearchableComboBox()
            cb_ram.addItems(RAM_CAPACITIES)
            cb_ram_type = SearchableComboBox()
            cb_ram_type.addItems(DDR_VERSIONS)
            cb_storage = SearchableComboBox()
            cb_storage.addItems(SYSTEM_STORAGE_LIST)
            cb_gpu = SearchableComboBox()
            cb_gpu.addItems(GPU_LIST)
            cb_screen = SearchableComboBox()
            cb_screen.addItems(SCREEN_SIZES)
            cb_res = SearchableComboBox()
            cb_res.addItems(RESOLUTIONS)
            cb_hz = SearchableComboBox()
            cb_hz.addItems(REFRESH_RATES)
            ed_spec = SmartLineEdit("سایر مشخصات فنی (پورت‌ها، وب‌کم، کیبورد با نور پس‌زمینه و...)")

            regular_fields = [
                ("پردازنده", "پردازنده (CPU):", cb_cpu),
                ("ظرفیت رم", "ظرفیت رم (RAM):", cb_ram),
                ("نسخه DDR", "نسخه DDR:", cb_ram_type),
                ("حافظه داخلی", "حافظه داخلی (Storage):", cb_storage),
                ("پردازنده گرافیکی", "کارت گرافیک (GPU):", cb_gpu),
                ("سایز صفحه نمایش", "سایز صفحه نمایش:", cb_screen),
                ("دقت صفحه نمایش", "دقت تصویر (Resolution):", cb_res),
                ("نرخ نوسازی", "نرخ نوسازی (Refresh Rate):", cb_hz),
            ]

        elif "کیس" in cat_norm or "سیستم" in cat_norm:
            if "case" in sub_clean.lower() or "پوسته" in sub_clean:
                cb_form = SearchableComboBox()
                cb_form.addItems(["", "Mid Tower", "Full Tower", "Mini Tower (Micro-ATX)", "Small Form Factor (SFF)"])
                cb_rgb = SearchableComboBox()
                cb_rgb.addItems(["", "None", "Single Color LED", "RGB", "ARGB"])
                ed_spec = SmartLineEdit("مشخصات بدنه و فن‌های نصب‌شده...")
                regular_fields = [
                    ("فرم فاکتور کیس", "فرم فاکتور کیس:", cb_form),
                    ("نورپردازی", "نورپردازی:", cb_rgb),
                ]
            else:
                cb_cpu = SearchableComboBox()
                cb_cpu.addItems(CPU_LIST)
                cb_ram = SearchableComboBox()
                cb_ram.addItems(RAM_CAPACITIES)
                cb_ram_type = SearchableComboBox()
                cb_ram_type.addItems(DDR_VERSIONS)
                cb_storage = SearchableComboBox()
                cb_storage.addItems(SYSTEM_STORAGE_LIST)
                cb_gpu = SearchableComboBox()
                cb_gpu.addItems(GPU_LIST)
                ed_spec = SmartLineEdit("سایر مشخصات سیستم...")
                regular_fields = [
                    ("پردازنده", "پردازنده (CPU):", cb_cpu),
                    ("ظرفیت رم", "ظرفیت رم (RAM):", cb_ram),
                    ("نسخه DDR", "نسخه DDR:", cb_ram_type),
                    ("حافظه داخلی", "حافظه داخلی (Storage):", cb_storage),
                    ("پردازنده گرافیکی", "کارت گرافیک (GPU):", cb_gpu),
                ]

        elif "قطعات" in cat_norm:
            if "cpu" in sub_clean.lower() or "پردازنده" in sub_clean:
                cb_title = SearchableComboBox()
                cb_title.addItems(CPU_LIST)
                cb_sock = SearchableComboBox()
                cb_sock.addItems(["", "LGA 775", "LGA 1155", "LGA 1150", "LGA 1151", "LGA 1200", "LGA 1700", "LGA 1851", "AM3 / AM3+", "AM4", "AM5", "TR4 / sTRX4", "BGA"])
                ed_spec = SmartLineEdit("فرکانس، تعداد هسته و مشخصات دیگر...")
                regular_fields = [
                    ("سری پردازنده", "سری پردازنده:", cb_title),
                    ("سوکت", "سوکت:", cb_sock),
                ]

            elif "motherboard" in sub_clean.lower() or "مادربرد" in sub_clean:
                cb_sock = SearchableComboBox()
                cb_sock.addItems(["", "LGA 1155", "LGA 1150", "LGA 1151", "LGA 1200", "LGA 1700", "LGA 1851", "AM4", "AM5"])
                cb_chip = SearchableComboBox()
                cb_chip.addItems(["", "Intel H81 / B85", "Intel H110 / B250", "Intel H310 / B360 / B365", "Intel H410 / B460 / Z490", "Intel H510 / B560 / Z590", "Intel H610 / B660 / B760 / Z790", "AMD A320 / B450 / X470 / B550 / X570", "AMD A620 / B650 / X670 / X870"])
                cb_form = SearchableComboBox()
                cb_form.addItems(["", "ATX", "Micro-ATX (mATX)", "Mini-ITX", "E-ATX"])
                cb_ddr = SearchableComboBox()
                cb_ddr.addItems(DDR_VERSIONS)
                ed_spec = SmartLineEdit("مشخصات اسلات‌ها و درگاه‌ها...")
                regular_fields = [
                    ("سوکت", "سوکت:", cb_sock),
                    ("چیپست", "چیپست:", cb_chip),
                    ("فرم فاکتور", "فرم فاکتور:", cb_form),
                    ("نسخه DDR", "نسخه DDR:", cb_ddr),
                ]

            elif "ram" in sub_clean.lower() or "رم" in sub_clean:
                cb_cap = SearchableComboBox()
                cb_cap.addItems(RAM_CAPACITIES)
                cb_ddr = SearchableComboBox()
                cb_ddr.addItems(DDR_VERSIONS)
                cb_bus = SearchableComboBox()
                cb_bus.addItems(RAM_FREQUENCIES)
                ed_spec = SmartLineEdit("تایمینگ، هیت‌سینک، ولتاژ...")
                regular_fields = [
                    ("ظرفیت", "ظرفیت رم:", cb_cap),
                    ("نسخه DDR", "نسخه DDR:", cb_ddr),
                    ("فرکانس", "فرکانس (Frequency):", cb_bus),
                ]

            elif "gpu" in sub_clean.lower() or "graphic" in sub_clean.lower() or "گرافیک" in sub_clean:
                cb_gpu = SearchableComboBox()
                cb_gpu.addItems(GPU_LIST)
                cb_vram = SearchableComboBox()
                cb_vram.addItems(["", "1GB", "2GB", "4GB", "6GB", "8GB", "10GB", "12GB", "16GB", "20GB", "24GB"])
                cb_mem = SearchableComboBox()
                cb_mem.addItems(["", "GDDR3", "GDDR5", "GDDR6", "GDDR6X"])
                ed_spec = SmartLineEdit("درگاه‌های خروجی و برق ورودی...")
                regular_fields = [
                    ("چیپست گرافیک", "چیپست گرافیک:", cb_gpu),
                    ("حافظه VRAM", "حافظه VRAM:", cb_vram),
                    ("نوع حافظه", "نوع حافظه:", cb_mem),
                ]

            elif "psu" in sub_clean.lower() or "power" in sub_clean.lower() or "پاور" in sub_clean or "تغذیه" in sub_clean:
                cb_watt = SearchableComboBox()
                cb_watt.addItems(["", "300W", "350W", "400W", "450W", "500W", "550W", "600W", "650W", "700W", "750W", "850W", "1000W", "1200W+"])
                cb_cert = SearchableComboBox()
                cb_cert.addItems(["", "Standard", "80 Plus Bronze", "80 Plus Silver", "80 Plus Gold", "80 Plus Platinum", "80 Plus Titanium"])
                cb_mod = SearchableComboBox()
                cb_mod.addItems(["", "Non-Modular", "Semi-Modular", "Full Modular"])
                ed_spec = SmartLineEdit("کانکتورهای برق و گارانتی...")
                regular_fields = [
                    ("توان خروجی", "توان خروجی (Watt):", cb_watt),
                    ("استاندارد بازدهی", "استاندارد بازدهی:", cb_cert),
                    ("مدیریت کابل", "مدیریت کابل:", cb_mod),
                ]

            elif "cooler" in sub_clean.lower() or "خنک کننده" in sub_clean:
                cb_type = SearchableComboBox()
                cb_type.addItems(["", "Air Cooler", "Liquid Cooler 120mm (AIO)", "Liquid Cooler 240mm (AIO)", "Liquid Cooler 360mm (AIO)"])
                cb_rgb = SearchableComboBox()
                cb_rgb.addItems(["", "None", "Single Color LED", "RGB", "ARGB"])
                ed_spec = SmartLineEdit("سوکت‌های پشتیبانی‌شده...")
                regular_fields = [
                    ("نوع خنک کننده", "نوع خنک‌کننده:", cb_type),
                    ("نورپردازی", "نورپردازی:", cb_rgb),
                ]

            else:
                ed_spec = SmartLineEdit("مشخصات فنی قطعه...")

        elif "ذخیره ساز" in cat_norm or "حافظه" in cat_norm:
            if "ssd" in sub_clean.lower() and "external" not in sub_clean.lower() and "اکسترنال" not in sub_clean:
                cb_cap = SearchableComboBox()
                cb_cap.addItems(SSD_CAPACITIES)
                cb_iface = SearchableComboBox()
                cb_iface.addItems(SSD_INTERFACES)
                ed_spec = SmartLineEdit("سرعت خواندن/نوشتن، کنترلر و چیپ حافظه...")
                regular_fields = [
                    ("ظرفیت", "ظرفیت حافظه (Capacity):", cb_cap),
                    ("رابط و فرم", "رابط و فرم (Interface & Form Factor):", cb_iface),
                ]

            elif "hdd" in sub_clean.lower() and "external" not in sub_clean.lower() and "اکسترنال" not in sub_clean:
                cb_cap = SearchableComboBox()
                cb_cap.addItems(HDD_CAPACITIES)
                cb_iface = SearchableComboBox()
                cb_iface.addItems(HDD_INTERFACES)
                ed_spec = SmartLineEdit("سرعت چرخش RPM، بافر و کش...")
                regular_fields = [
                    ("ظرفیت", "ظرفیت هارد (Capacity):", cb_cap),
                    ("رابط و فرم", "رابط و فرم (Interface & Form Factor):", cb_iface),
                ]

            elif "اکسترنال" in sub_clean or "external" in sub_clean.lower():
                cb_cap = SearchableComboBox()
                cb_cap.addItems(SSD_CAPACITIES)
                cb_port = SearchableComboBox()
                cb_port.addItems(["", "USB 3.0 / USB 3.2 Gen 1", "USB 3.2 Gen 2 (Type-C)", "USB4 / Thunderbolt"])
                ed_spec = SmartLineEdit("مقاومت در برابر ضربه و آب...")
                regular_fields = [
                    ("ظرفیت", "ظرفیت:", cb_cap),
                    ("نوع اتصال / پورت", "نوع اتصال / پورت:", cb_port),
                ]

            elif "flash" in sub_clean.lower() or "فلش" in sub_clean or "کارت" in sub_clean:
                cb_cap = SearchableComboBox()
                cb_cap.addItems(["", "16GB", "32GB", "64GB", "128GB", "256GB", "512GB", "1TB"])
                cb_iface = SearchableComboBox()
                cb_iface.addItems(["", "USB 2.0", "USB 3.0 / 3.2", "Dual USB-A + Type-C", "microSDXC / SDXC UHS-I", "microSDXC UHS-II"])
                ed_spec = SmartLineEdit("جنس بدنه و سرعت انتقال...")
                regular_fields = [
                    ("ظرفیت", "ظرفیت:", cb_cap),
                    ("نوع رابط", "نوع رابط:", cb_iface),
                ]

            else:
                ed_spec = SmartLineEdit("مشخصات فنی حافظه...")

        elif "مانیتور" in cat_norm:
            cb_size = SearchableComboBox()
            cb_size.addItems(SCREEN_SIZES)
            cb_panel = SearchableComboBox()
            cb_panel.addItems(PANEL_TYPES)
            cb_res = SearchableComboBox()
            cb_res.addItems(RESOLUTIONS)
            cb_hz = SearchableComboBox()
            cb_hz.addItems(REFRESH_RATES)
            cb_ports = SearchableComboBox()
            cb_ports.addItems(["", "HDMI + VGA", "HDMI + DisplayPort", "HDMI + DP + Type-C", "Dual HDMI + DP", "VGA + DVI"])
            ed_spec = SmartLineEdit("اسپیکر داخلی، پایه آسانسوری، HDR...")
            regular_fields = [
                ("سایز صفحه نمایش", "سایز صفحه نمایش:", cb_size),
                ("نوع پنل", "نوع پنل:", cb_panel),
                ("دقت تصویر", "دقت تصویر:", cb_res),
                ("نرخ نوسازی", "نرخ نوسازی (Hz):", cb_hz),
                ("پورت های ورودی", "پورت‌های ورودی:", cb_ports),
            ]

        elif "لوازم جانبی" in cat_norm:
            if "mouse" in sub_clean.lower() or "ماوس" in sub_clean:
                cb_conn = SearchableComboBox()
                cb_conn.addItems(CONNECTIVITY_OPTIONS)
                cb_dpi = SearchableComboBox()
                cb_dpi.addItems(["", "1000 DPI", "1200 DPI", "1600 DPI", "2400 DPI", "3200 DPI", "6400 DPI", "12000+ DPI (Gaming)"])
                cb_sensor = SearchableComboBox()
                cb_sensor.addItems(["", "Optical", "Laser"])
                ed_spec = SmartLineEdit("تعداد کلیدها، سایلنت، نورپردازی RGB...")
                regular_fields = [
                    ("نوع اتصال / پورت", "نوع اتصال / پورت:", cb_conn),
                    ("دقت حسگر (DPI)", "دقت حسگر (DPI):", cb_dpi),
                    ("نوع حسگر", "نوع حسگر:", cb_sensor),
                ]

            elif "keyboard" in sub_clean.lower() or "کیبورد" in sub_clean:
                cb_conn = SearchableComboBox()
                cb_conn.addItems(CONNECTIVITY_OPTIONS)
                cb_switch = SearchableComboBox()
                cb_switch.addItems(["", "Membrane", "Mechanical Blue Switch", "Mechanical Red Switch", "Mechanical Brown Switch", "Optical-Mechanical"])
                cb_farsi = SearchableComboBox()
                cb_farsi.addItems(["", "Yes (Factory Printed)", "No (English Only)"])
                ed_spec = SmartLineEdit("نور پس‌زمینه، نام‌پد، استراحتگاه مچ...")
                regular_fields = [
                    ("نوع اتصال / پورت", "نوع اتصال / پورت:", cb_conn),
                    ("نوع سوییچ / کلید", "نوع کلید / سوییچ:", cb_switch),
                    ("حروف فارسی", "حروف فارسی چاپ کارخانه:", cb_farsi),
                ]

            elif "bag" in sub_clean.lower() or "backpack" in sub_clean.lower() or "کیف" in sub_clean or "کوله" in sub_clean:
                cb_bag_type = SearchableComboBox()
                cb_bag_type.addItems(BAG_TYPES)
                cb_bag_size = SearchableComboBox()
                cb_bag_size.addItems(BAG_SIZES)
                cb_bag_mat = SearchableComboBox()
                cb_bag_mat.addItems(BAG_MATERIALS)
                ed_spec = SmartLineEdit("ضربه گیر حبابی، پورت USB، ضد سرقت...")
                regular_fields = [
                    ("نوع کاربری", "نوع کیف / کوله:", cb_bag_type),
                    ("سایز مناسب لپ تاپ", "سایز مناسب لپ‌تاپ:", cb_bag_size),
                    ("جنس و مقاومت", "جنس و مقاومت بدنه:", cb_bag_mat),
                ]

            elif "headset" in sub_clean.lower() or "headphone" in sub_clean.lower() or "هدست" in sub_clean or "هدفون" in sub_clean or "اسپیکر" in sub_clean:
                cb_conn = SearchableComboBox()
                cb_conn.addItems(CONNECTIVITY_OPTIONS)
                ed_spec = SmartLineEdit("میکروفون، نویزکنسلینگ، توان خروجی...")
                regular_fields = [
                    ("نوع اتصال / پورت", "نوع اتصال / پورت:", cb_conn),
                ]

            else:
                cb_conn = SearchableComboBox()
                cb_conn.addItems(CONNECTIVITY_OPTIONS)
                ed_spec = SmartLineEdit("مشخصات لوازم جانبی...")
                regular_fields = [
                    ("نوع اتصال / پورت", "نوع اتصال / پورت:", cb_conn),
                ]

        elif "تجهیزات شبکه" in cat_norm or "شبکه" in cat_norm:
            cb_wifi = SearchableComboBox()
            cb_wifi.addItems(["", "Wi-Fi 4 (802.11n)", "Wi-Fi 5 (802.11ac)", "Wi-Fi 6 (802.11ax)", "Wi-Fi 6E", "Wi-Fi 7", "4G LTE", "5G"])
            cb_speed = SearchableComboBox()
            cb_speed.addItems(["", "10/100 Fast Ethernet", "Gigabit (10/100/1000)", "2.5G / 10G Multi-Gig"])
            ed_spec = SmartLineEdit("تعداد پورت، آنتن‌ها، توان خروجی...")
            regular_fields = [
                ("استاندارد وای فای", "استاندارد وای‌فای:", cb_wifi),
                ("سرعت پورت های شبکه", "سرعت پورت‌های شبکه:", cb_speed),
            ]

        elif "ماشین های اداری" in cat_norm or "ماشین‌های اداری" in cat_norm:
            cb_tech = SearchableComboBox()
            cb_tech.addItems(["", "Laser Monochrome", "Laser Color", "Inkjet Color", "Thermal"])
            cb_func = SearchableComboBox()
            cb_func.addItems(["", "Single Function (Print Only)", "3-in-1 (Print, Scan, Copy)", "4-in-1 (Print, Scan, Copy, Fax)"])
            cb_conn = SearchableComboBox()
            cb_conn.addItems(["", "USB Only", "USB + Network (LAN)", "USB + Wi-Fi", "USB + LAN + Wi-Fi"])
            ed_spec = SmartLineEdit("سرعت چاپ بر دقیقه، رزولوشن DPI، ظرفیت سینی...")
            regular_fields = [
                ("فناوری چاپ", "فناوری چاپ:", cb_tech),
                ("قابلیت های دستگاه", "قابلیت‌های دستگاه:", cb_func),
                ("نوع اتصال", "نوع اتصال:", cb_conn),
            ]

        elif "کابل" in cat_norm or "مبدل" in cat_norm:
            cb_type = SearchableComboBox()
            cb_type.addItems(["", "HDMI to HDMI", "DisplayPort to DisplayPort", "HDMI to VGA", "Type-C to HDMI", "Type-C to Type-C", "USB-A to Type-C", "USB-A to USB-B (Printer)", "Cat6 RJ45"])
            cb_len = SearchableComboBox()
            cb_len.addItems(["", "0.5m", "1m", "1.5m", "1.8m", "2m", "3m", "5m", "10m", "15m", "20m+"])
            ed_spec = SmartLineEdit("پشتیبانی از 4K / 8K، جنس روکش، روکش کنفی...")
            regular_fields = [
                ("نوع درگاه / رابط", "نوع درگاه / رابط:", cb_type),
                ("طول کابل", "طول کابل:", cb_len),
            ]

        else:
            ed_spec = SmartLineEdit("مشخصات فنی کالا...")

        if ed_spec is None:
            ed_spec = SmartLineEdit("مشخصات فنی...")

        # Build grid: 2 columns of (Label, Widget)
        for i, (name, label_str, widget) in enumerate(regular_fields):
            row = i // 2
            col_offset = (i % 2) * 2
            lbl = QLabel(label_str)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setMinimumWidth(80)
            widget.setMinimumHeight(30)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.sub_layout.addWidget(lbl, row, col_offset)
            self.sub_layout.addWidget(widget, row, col_offset + 1)
            self.fields[name] = widget
            self._field_labels[widget] = lbl

        spec_row = (len(regular_fields) + 1) // 2
        lbl_spec = QLabel("مشخصات (Specifications):")
        lbl_spec.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lbl_spec.setMinimumWidth(80)
        ed_spec.setMinimumHeight(30)
        ed_spec.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.sub_layout.addWidget(lbl_spec, spec_row, 0)
        self.sub_layout.addWidget(ed_spec, spec_row, 1, 1, 3)
        self.fields["مشخصات"] = ed_spec
        self._field_labels[ed_spec] = lbl_spec

        self._notify_custom_field_callback()

    def _rebuild_part_subfields(self, part_type: str):
        self._rebuild_subfields(part_type)

    def _reorganize_grid(self):
        """Place all regular fields in a clean 2-column grid, followed by 'مشخصات' spanning full width at the bottom."""
        while self.sub_layout.count():
            item = self.sub_layout.takeAt(0)
            if item.widget() and not any(item.widget() is w for w in self.fields.values()):
                item.widget().deleteLater()

        self._field_labels.clear()
        regular = [(k, v) for k, v in self.fields.items() if k != "مشخصات"]
        for i, (name, widget) in enumerate(regular):
            row = i // 2
            col_offset = (i % 2) * 2
            lbl = QLabel(f"{name}:")
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setMinimumWidth(80)
            widget.setMinimumHeight(30)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.sub_layout.addWidget(lbl, row, col_offset)
            self.sub_layout.addWidget(widget, row, col_offset + 1)
            self._field_labels[widget] = lbl

        spec_row = (len(regular) + 1) // 2
        ed_spec = self.fields.get("مشخصات")
        if ed_spec is not None:
            lbl_spec = QLabel("مشخصات (Specifications):")
            lbl_spec.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl_spec.setMinimumWidth(80)
            ed_spec.setMinimumHeight(30)
            ed_spec.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.sub_layout.addWidget(lbl_spec, spec_row, 0)
            self.sub_layout.addWidget(ed_spec, spec_row, 1, 1, 3)
            self._field_labels[ed_spec] = lbl_spec

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
            self._rebuild_subfields(self.cb_sub.currentText())

        if not isinstance(custom_fields, list):
            return

        has_new_custom = False
        for definition in custom_fields:
            if not isinstance(definition, dict):
                continue
            field_name = str(definition.get("name", "")).strip()
            normalized_name = normalize_catalog_label(field_name)
            if not field_name or not normalized_name or normalized_name == normalize_catalog_label("مشخصات"):
                continue
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
                if isinstance(existing_widget, QComboBox):
                    current_value = existing_widget.currentText()
                    existing_widget.blockSignals(True)
                    existing_widget.clear()
                    existing_widget.addItem("")
                    existing_widget.addItems(list(dict.fromkeys(values)))
                    if current_value in values:
                        existing_widget.setCurrentText(current_value)
                    existing_widget.blockSignals(False)
                continue

            if values:
                widget = SearchableComboBox()
                widget.addItem("")
                widget.addItems(list(dict.fromkeys(values)))
            else:
                widget = SmartLineEdit(f"{field_name}...")
            widget.setToolTip(f"مشخصه سفارشی: {field_name}")
            widget.setMinimumHeight(30)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.fields[field_name] = widget
            self._custom_field_widgets[field_name] = widget
            has_new_custom = True

        if has_new_custom:
            self._reorganize_grid()

    def get_sub_category(self) -> str:
        if self.cb_sub:
            return self.cb_sub.currentText().strip() or "سایر موارد (Other)"
        return "سایر موارد (Other)"

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