"""
Daqiq Multi-Calendar and Time Formatting Service.

Supports:
- Calendars:
    - 'jalali' (شمسی, default)
    - 'hijri' (قمری via hijridate)
    - 'gregorian' (میلادی)
- Time formats:
    - '24h' (۲۴ ساعته, default)
    - '12h' (۱۲ ساعته with English AM / PM markers)
- Normalization:
    - Seamlessly parses Persian digits (۰-۹), Arabic digits (٠-٩), ASCII digits (0-9),
      and both English (AM/PM) and legacy Persian (ق.ظ/ب.ظ) period markers.
- Deterministic Multi-Origin Migration & Chronological Ordering:
    - Auto-detects calendar origin by year band (Jalali 1300-1429, Hijri 1430-1550,
      Gregorian 1900-2199) so mixed-origin DBs convert idempotently and accurately.
    - Discovers all user tables and date/time columns dynamically from ``sqlite_master``.
"""

from __future__ import annotations

import calendar as std_calendar
import os
import re
import shutil
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import hijridate
import jdatetime

CALENDAR_JALALI = "jalali"
CALENDAR_HIJRI = "hijri"
CALENDAR_GREGORIAN = "gregorian"

SUPPORTED_CALENDARS = (CALENDAR_JALALI, CALENDAR_HIJRI, CALENDAR_GREGORIAN)

TIME_FORMAT_24H = "24h"
TIME_FORMAT_12H = "12h"

SUPPORTED_TIME_FORMATS = (TIME_FORMAT_24H, TIME_FORMAT_12H)

CALENDAR_NAMES_FA = {
    CALENDAR_JALALI: "شمسی",
    CALENDAR_HIJRI: "قمری",
    CALENDAR_GREGORIAN: "میلادی",
}

CALENDAR_LOOKUP = {
    "شمسی": CALENDAR_JALALI,
    "jalali": CALENDAR_JALALI,
    "shamsi": CALENDAR_JALALI,
    "قمری": CALENDAR_HIJRI,
    "hijri": CALENDAR_HIJRI,
    "ghamari": CALENDAR_HIJRI,
    "میلادی": CALENDAR_GREGORIAN,
    "gregorian": CALENDAR_GREGORIAN,
    "miladi": CALENDAR_GREGORIAN,
}

TIME_FORMAT_NAMES_FA = {
    TIME_FORMAT_24H: "۲۴ ساعته",
    TIME_FORMAT_12H: "۱۲ ساعته (AM / PM)",
}

TIME_FORMAT_LOOKUP = {
    "۲۴ ساعته": TIME_FORMAT_24H,
    "24h": TIME_FORMAT_24H,
    "24": TIME_FORMAT_24H,
    "۱۲ ساعته": TIME_FORMAT_12H,
    "۱۲ ساعته (AM / PM)": TIME_FORMAT_12H,
    "۱۲ ساعته (با ق.ظ / ب.ظ)": TIME_FORMAT_12H,
    "12h": TIME_FORMAT_12H,
    "12": TIME_FORMAT_12H,
}

_BIDI_RE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")

# Digits translation tables
_PERSIAN_ARABIC_TO_ASCII = str.maketrans({
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
})

_ASCII_TO_PERSIAN = str.maketrans({
    "0": "۰", "1": "۱", "2": "۲", "3": "۳", "4": "۴",
    "5": "۵", "6": "۶", "7": "۷", "8": "۸", "9": "۹",
})


def normalize_digits(s: Optional[str]) -> str:
    """Convert Persian and Arabic unicode digits to ASCII standard digits."""
    if s is None:
        return ""
    return str(s).translate(_PERSIAN_ARABIC_TO_ASCII)


def to_persian_digits(s: Optional[str]) -> str:
    """Convert ASCII digits to Persian digits."""
    if s is None:
        return ""
    return str(s).translate(_ASCII_TO_PERSIAN)


# ---------------------------------------------------------------------------
# Core Date Parsing, Origin Detection & Conversion
# ---------------------------------------------------------------------------

def parse_date_parts(date_str: str) -> Optional[Tuple[int, int, int]]:
    """Parse 'YYYY/MM/DD' or 'YYYY-MM-DD' into (year, month, day) using normalized digits."""
    if not date_str:
        return None
    cleaned = _BIDI_RE.sub("", normalize_digits(str(date_str))).strip()
    m = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$", cleaned)
    if not m:
        return None
    try:
        y, mth, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mth <= 12 and 1 <= d <= 31:
            return y, mth, d
    except (ValueError, TypeError):
        pass
    return None


def detect_date_calendar(
    date_str: str,
    fallback_cal: str = CALENDAR_JALALI,
) -> str:
    """Deterministically detect calendar system from a date or datetime string.

    Year bands used across commercial retail data:
      - 1900..2199 -> Gregorian
      - 1430..1550 -> Hijri (Islamic lunar)
      - 1300..1429 -> Jalali (Persian solar)
    """
    fallback = CALENDAR_LOOKUP.get(fallback_cal, CALENDAR_JALALI)
    if not date_str:
        return fallback
    cleaned = _BIDI_RE.sub("", normalize_digits(str(date_str))).strip()
    m = re.match(r"^(\d{4})([/-])(\d{1,2})\2(\d{1,2})", cleaned)
    if not m:
        return fallback
    y = int(m.group(1))
    sep = m.group(2)
    if 1900 <= y <= 2199:
        return CALENDAR_GREGORIAN
    if 1430 <= y <= 1550:
        return CALENDAR_HIJRI
    if 1300 <= y <= 1429:
        return CALENDAR_JALALI
    if sep == "-" and y >= 1900:
        return CALENDAR_GREGORIAN
    return fallback


def to_gregorian_date(y: int, m: int, d: int, cal_type: str) -> date:
    """Convert a year, month, day from the given calendar to python datetime.date."""
    cal = CALENDAR_LOOKUP.get(cal_type, CALENDAR_JALALI)
    if cal == CALENDAR_JALALI:
        jd = jdatetime.date(y, m, d)
        return jd.togregorian()
    elif cal == CALENDAR_HIJRI:
        h = hijridate.Hijri(y, m, d)
        return h.to_gregorian()
    elif cal == CALENDAR_GREGORIAN:
        return date(y, m, d)
    raise ValueError(f"Unsupported calendar type: {cal_type}")


def from_gregorian_date(g_date: date, cal_type: str) -> Tuple[int, int, int]:
    """Convert a python datetime.date to (year, month, day) in the target calendar."""
    cal = CALENDAR_LOOKUP.get(cal_type, CALENDAR_JALALI)
    if cal == CALENDAR_JALALI:
        jd = jdatetime.date.fromgregorian(date=g_date)
        return jd.year, jd.month, jd.day
    elif cal == CALENDAR_HIJRI:
        h = hijridate.Gregorian(g_date.year, g_date.month, g_date.day).to_hijri()
        return h.year, h.month, h.day
    elif cal == CALENDAR_GREGORIAN:
        return g_date.year, g_date.month, g_date.day
    raise ValueError(f"Unsupported calendar type: {cal_type}")


def convert_date(
    date_str: str,
    from_cal: str,
    to_cal: str,
    auto_detect_origin: bool = False,
) -> str:
    """Convert date string from one calendar system to another.

    Returns normalized 'YYYY/MM/DD'. If invalid, returns original string unmodified.
    """
    if not date_str:
        return date_str
    src_cal = CALENDAR_LOOKUP.get(from_cal, CALENDAR_JALALI)
    if auto_detect_origin:
        src_cal = detect_date_calendar(date_str, fallback_cal=src_cal)
    dst_cal = CALENDAR_LOOKUP.get(to_cal, CALENDAR_JALALI)

    parts = parse_date_parts(date_str)
    if not parts:
        return date_str

    y, m, d = parts
    if src_cal == dst_cal:
        return f"{y:04d}/{m:02d}/{d:02d}"

    try:
        g_date = to_gregorian_date(y, m, d, src_cal)
        ny, nm, nd = from_gregorian_date(g_date, dst_cal)
        return f"{ny:04d}/{nm:02d}/{nd:02d}"
    except Exception:
        return date_str


def parse_date_to_gregorian(
    date_or_dt_str: Optional[str],
    fallback_cal: str = CALENDAR_JALALI,
) -> Optional[date]:
    """Extract the leading date from a date/datetime value and convert to Gregorian ``date``."""
    if not date_or_dt_str:
        return None
    cleaned = _BIDI_RE.sub("", normalize_digits(str(date_or_dt_str))).strip()
    m = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})", cleaned)
    if not m:
        return None
    y, mth, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    origin_cal = detect_date_calendar(cleaned, fallback_cal=fallback_cal)
    try:
        return to_gregorian_date(y, mth, d, origin_cal)
    except Exception:
        return None


def is_date_in_range(
    value: Optional[str],
    from_str: Optional[str],
    to_str: Optional[str],
    active_cal: str = CALENDAR_JALALI,
) -> bool:
    """Return True if *value* falls within [from_str, to_str] inclusive across mixed calendars."""
    d_val = parse_date_to_gregorian(value, fallback_cal=active_cal)
    d_from = parse_date_to_gregorian(from_str, fallback_cal=active_cal)
    d_to = parse_date_to_gregorian(to_str, fallback_cal=active_cal)
    if d_val is not None:
        if d_from is not None and d_val < d_from:
            return False
        if d_to is not None and d_val > d_to:
            return False
        if d_from is not None or d_to is not None:
            return True
    raw_val = normalize_digits(str(value or ""))[:10]
    raw_from = normalize_digits(str(from_str or ""))[:10]
    raw_to = normalize_digits(str(to_str or ""))[:10]
    if raw_from and raw_val < raw_from:
        return False
    if raw_to and raw_val > raw_to:
        return False
    return True


def add_calendar_days(
    start_date_str: str,
    days: int,
    cal_type: str = CALENDAR_JALALI,
) -> str:
    """Add exact calendar days while preserving/targeting the active calendar."""
    if not start_date_str or not str(start_date_str).strip():
        return ""
    g_start = parse_date_to_gregorian(start_date_str, fallback_cal=cal_type)
    if g_start is None:
        return start_date_str
    g_end = g_start + timedelta(days=int(days))
    dst_cal = CALENDAR_LOOKUP.get(cal_type, detect_date_calendar(start_date_str))
    y, m, d = from_gregorian_date(g_end, dst_cal)
    return f"{y:04d}/{m:02d}/{d:02d}"


def get_calendar_month_days(year: int, month: int, cal_type: str) -> int:
    """Return the exact number of days in (year, month) for the specified calendar."""
    cal = CALENDAR_LOOKUP.get(cal_type, CALENDAR_JALALI)
    if cal == CALENDAR_JALALI:
        if month <= 6:
            return 31
        if month <= 11:
            return 30
        return 30 if jdatetime.date(year, 1, 1).isleap() else 29
    if cal == CALENDAR_HIJRI:
        return hijridate.Hijri(year, month, 1).month_length()
    return std_calendar.monthrange(year, month)[1]


# ---------------------------------------------------------------------------
# Core Time Parsing & Conversion
# ---------------------------------------------------------------------------

def parse_time_parts(time_str: str) -> Optional[Tuple[int, int, int]]:
    """
    Parse time string into 24-hour (hour, minute, second).
    Supports:
      - 24h: '14:30:00', '14:30', '09:15:20'
      - 12h English: '02:30:00 PM', '02:30:00 AM', '2:30 PM'
      - 12h legacy Persian: '02:30:00 ب.ظ', '02:30:00 ق.ظ'
    """
    if not time_str:
        return None
    raw = _BIDI_RE.sub("", normalize_digits(str(time_str))).strip()
    is_pm = bool(re.search(r"(?:ب\.?\s*ظ|\bpm\b)", raw, re.IGNORECASE))
    is_am = bool(re.search(r"(?:ق\.?\s*ظ|\bam\b)", raw, re.IGNORECASE))

    clean_digits = re.sub(r"[^\d:]", "", raw)
    time_parts = [p for p in clean_digits.split(":") if p != ""]
    if len(time_parts) < 2:
        return None

    try:
        h = int(time_parts[0])
        m = int(time_parts[1])
        s = int(time_parts[2]) if len(time_parts) > 2 else 0

        if not (0 <= m < 60 and 0 <= s < 60):
            return None

        if is_pm or is_am:
            if not (1 <= h <= 12):
                return None
            if is_pm and h < 12:
                h += 12
            elif is_am and h == 12:
                h = 0
        else:
            if not (0 <= h < 24):
                return None

        return h, m, s
    except (ValueError, TypeError):
        return None


def format_time_24h(h: int, m: int, s: int) -> str:
    """Format hour, minute, second into 24h 'HH:MM:SS'."""
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_time_12h(h: int, m: int, s: int) -> str:
    """Format 24h hour, minute, second into English 12h 'hh:mm:ss AM/PM'."""
    suffix = "PM" if h >= 12 else "AM"
    h12 = h % 12
    if h12 == 0:
        h12 = 12
    return f"{h12:02d}:{m:02d}:{s:02d} {suffix}"


def convert_time(time_str: str, from_fmt: str, to_fmt: str) -> str:
    """
    Convert time string between 24h and 12h (English AM/PM) formats.
    Returns converted time string or original if unparseable.
    """
    if not time_str:
        return time_str
    dst_fmt = TIME_FORMAT_LOOKUP.get(to_fmt, TIME_FORMAT_24H)

    parts = parse_time_parts(time_str)
    if not parts:
        return time_str

    h, m, s = parts
    if dst_fmt == TIME_FORMAT_12H:
        return format_time_12h(h, m, s)
    return format_time_24h(h, m, s)


# ---------------------------------------------------------------------------
# Combined Datetime Conversion & Display Formatting
# ---------------------------------------------------------------------------

def convert_datetime_str(
    dt_str: str,
    from_cal: str = CALENDAR_JALALI,
    from_time_fmt: str = TIME_FORMAT_24H,
    to_cal: str = CALENDAR_JALALI,
    to_time_fmt: str = TIME_FORMAT_24H,
    auto_detect_origin: bool = False,
) -> str:
    """
    Convert combined datetime string (e.g. '1403/05/20 14:30:00' or '1403/05/20').
    Supports 'T' ISO separator as well as space separator.
    Safely preserves original text if unparseable.
    """
    if not dt_str:
        return dt_str

    cleaned = _BIDI_RE.sub("", str(dt_str)).strip()
    if not cleaned:
        return dt_str

    # Handle ISO T separator and optional subseconds cleanly
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", cleaned):
        cleaned = cleaned.replace("T", " ", 1)
    if "." in cleaned:
        m_sub = re.match(r"^(\d{4}[/-]\d{1,2}[/-]\d{1,2}\s+\d{1,2}:\d{2}:\d{2})\.\d+(.*)$", cleaned)
        if m_sub:
            cleaned = m_sub.group(1) + m_sub.group(2)

    # Normalize legacy 'Date - Time' separator into canonical single-space 'Date Time'
    cleaned = re.sub(r"\s*-\s*(?=\d{1,2}:\d{2})", " ", cleaned)

    tokens = cleaned.split(" ", 1)
    date_part = tokens[0]
    time_part = tokens[1].strip() if len(tokens) > 1 else ""

    converted_date = convert_date(
        date_part,
        from_cal,
        to_cal,
        auto_detect_origin=auto_detect_origin,
    )
    if not time_part:
        return converted_date

    converted_time = convert_time(time_part, from_time_fmt, to_time_fmt)
    return f"{converted_date} {converted_time}"


def format_timestamp_for_display(
    dt_str: Optional[str],
    cal_type: str = CALENDAR_JALALI,
    time_fmt: str = TIME_FORMAT_24H,
) -> str:
    """Format an ISO or localized timestamp for user-facing tables as 'YYYY/MM/DD HH:MM'."""
    if not dt_str or not str(dt_str).strip():
        return "—"
    raw = _BIDI_RE.sub("", normalize_digits(str(dt_str))).strip()
    target_cal = CALENDAR_LOOKUP.get(cal_type, CALENDAR_JALALI)
    target_tf = TIME_FORMAT_LOOKUP.get(time_fmt, TIME_FORMAT_24H)

    cleaned = raw.replace("T", " ", 1)
    cleaned = re.sub(r"\s*-\s*(?=\d{1,2}:\d{2})", " ", cleaned)
    if "." in cleaned and re.match(r"^\d{4}[/-]\d{1,2}[/-]\d{1,2}", cleaned):
        cleaned = re.sub(r"\.\d+", "", cleaned)

    tokens = cleaned.split(" ", 1)
    g_date = parse_date_to_gregorian(tokens[0], fallback_cal=target_cal)
    if g_date is None:
        return raw or "—"

    ny, nm, nd = from_gregorian_date(g_date, target_cal)
    date_out = f"{ny:04d}/{nm:02d}/{nd:02d}"

    t_parts = parse_time_parts(tokens[1]) if len(tokens) > 1 else None
    if t_parts is None:
        return f"{date_out} 12:00 AM" if target_tf == TIME_FORMAT_12H else f"{date_out} 00:00"

    h, m, _s = t_parts
    if target_tf == TIME_FORMAT_12H:
        suffix = "PM" if h >= 12 else "AM"
        h12 = h % 12 or 12
        return f"{date_out} {h12:02d}:{m:02d} {suffix}"
    return f"{date_out} {h:02d}:{m:02d}"


def chronological_sort_key(
    value: Optional[str],
    fallback_cal: str = CALENDAR_JALALI,
) -> Optional[Tuple[int, int, int, int, int]]:
    """Build a chronological sort tuple ``(0, date_ordinal, hour24, min, sec)``.

    Normalizes 12h AM/PM, 24h, ISO timestamps, and multi-calendar dates into a single
    monotonically ordered comparison key so ``09:00:00 AM`` always precedes ``02:30:00 PM``
    and mixed-calendar entries order identically by true timeline.
    Returns ``None`` if *value* is not a recognized date or time string.
    """
    raw = _BIDI_RE.sub("", normalize_digits(str(value or ""))).strip()
    if not raw:
        return None

    # Normalize separator between date and time (e.g. '1405/01/15 - 02:30 PM' or ISO 'T')
    normalized = re.sub(r"\s*-\s*(?=\d{1,2}:\d{2})", " ", raw.replace("T", " ", 1))

    # Case 1: Leading date YYYY/MM/DD (or YYYY-MM-DD) + optional time
    m_date = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})(.*)$", normalized)
    if m_date:
        date_token = f"{m_date.group(1)}/{m_date.group(2)}/{m_date.group(3)}"
        g_date = parse_date_to_gregorian(date_token, fallback_cal=fallback_cal)
        ordinal = (
            g_date.toordinal()
            if g_date is not None
            else (int(m_date.group(1)) * 400 + int(m_date.group(2)) * 32 + int(m_date.group(3)))
        )
        tail = m_date.group(4).strip()
        t_parts = parse_time_parts(tail) if tail else None
        h, m, s = t_parts if t_parts is not None else (0, 0, 0)
        return (0, ordinal, h, m, s)

    # Case 2: DD/MM/YYYY format
    m_dmy = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})(.*)$", normalized)
    if m_dmy:
        y, mth, d = int(m_dmy.group(3)), int(m_dmy.group(2)), int(m_dmy.group(1))
        g_date = parse_date_to_gregorian(f"{y:04d}/{mth:02d}/{d:02d}", fallback_cal=fallback_cal)
        ordinal = g_date.toordinal() if g_date is not None else (y * 400 + mth * 32 + d)
        tail = m_dmy.group(4).strip()
        t_parts = parse_time_parts(tail) if tail else None
        h, m, s = t_parts if t_parts is not None else (0, 0, 0)
        return (0, ordinal, h, m, s)

    # Case 3: Pure time string (e.g. '09:15:00 AM' vs '02:30:00 PM')
    if re.match(r"^\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:am|pm|ق\.?\s*ظ|ب\.?\s*ظ))?$", normalized, re.IGNORECASE):
        t_parts = parse_time_parts(normalized)
        if t_parts is not None:
            h, m, s = t_parts
            return (0, 0, h, m, s)

    return None


# ---------------------------------------------------------------------------
# Live "Now" & "Today" Helpers
# ---------------------------------------------------------------------------

def get_today_date(cal_type: str = CALENDAR_JALALI) -> str:
    """Return today's date formatted as 'YYYY/MM/DD' in the requested calendar."""
    today_g = date.today()
    y, m, d = from_gregorian_date(today_g, cal_type)
    return f"{y:04d}/{m:02d}/{d:02d}"


def get_now_time(time_fmt: str = TIME_FORMAT_24H) -> str:
    """Return current time in requested time format ('24h' or '12h')."""
    now = datetime.now()
    if TIME_FORMAT_LOOKUP.get(time_fmt) == TIME_FORMAT_12H:
        return format_time_12h(now.hour, now.minute, now.second)
    return format_time_24h(now.hour, now.minute, now.second)


def get_now_datetime(cal_type: str = CALENDAR_JALALI, time_fmt: str = TIME_FORMAT_24H) -> str:
    """Return current formatted datetime string."""
    return f"{get_today_date(cal_type)} {get_now_time(time_fmt)}"


# ---------------------------------------------------------------------------
# Dynamic SQLite Schema Discovery & Lossless Mixed-Origin Migration Engine
# ---------------------------------------------------------------------------

_DATE_ONLY_COLUMNS = {
    "warranty_start",
    "warranty_end",
    "upgrade_date",
    "payment_date",
    "change_date",
    "due_date",
    "paid_date",
    "cleared_date",
    "check_due_date",
    "start_due_date",
    "valid_until",
}

_TIME_ONLY_COLUMNS = set()

_DATETIME_COLUMNS = {
    "purchase_date",
    "sale_datetime",
    "service_datetime",
    "proforma_datetime",
    "invoice_datetime",
    "action_time",
    "created_at",
    "updated_at",
    "last_login_at",
}

# Retained for backward-compatible inspection/tests
_DATETIME_COLUMNS_MAP = {
    "sales": {
        "date_cols": ("warranty_start", "warranty_end"),
        "datetime_cols": ("sale_datetime", "created_at", "updated_at"),
    },
    "batches": {
        "date_cols": (),
        "datetime_cols": ("purchase_date", "created_at", "updated_at"),
    },
    "upgrades": {
        "date_cols": ("upgrade_date",),
        "datetime_cols": ("created_at", "updated_at"),
    },
    "payments": {
        "date_cols": ("payment_date",),
        "datetime_cols": ("created_at", "updated_at"),
    },
    "service_records": {
        "date_cols": (),
        "datetime_cols": ("service_datetime", "created_at", "updated_at"),
    },
    "service_price_history": {
        "date_cols": ("change_date",),
        "datetime_cols": ("created_at", "updated_at"),
    },
    "audit_logs": {
        "date_cols": (),
        "datetime_cols": ("action_time", "created_at", "updated_at"),
    },
    "employees": {
        "date_cols": (),
        "datetime_cols": ("created_at", "updated_at", "last_login_at"),
    },
    "suppliers": {
        "date_cols": (),
        "datetime_cols": ("created_at", "updated_at"),
    },
    "customers": {
        "date_cols": (),
        "datetime_cols": ("created_at", "updated_at"),
    },
    "products": {
        "date_cols": (),
        "datetime_cols": ("created_at", "updated_at"),
    },
    "service_catalog": {
        "date_cols": (),
        "datetime_cols": ("created_at", "updated_at"),
    },
}


def discover_datetime_columns(conn) -> Dict[str, Dict[str, Any]]:
    """Dynamically discover all SQLite user tables and their date/time/datetime columns."""
    discovered: Dict[str, Dict[str, Any]] = {}
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    for table in tables:
        info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        col_names = [row[1] for row in info]
        pk_col = "id" if "id" in col_names else "rowid"

        date_cols: List[str] = []
        time_cols: List[str] = []
        datetime_cols: List[str] = []

        for col in col_names:
            low = col.lower()
            if low in _DATETIME_COLUMNS or low.endswith("_datetime") or low.endswith("_at"):
                datetime_cols.append(col)
            elif low in _TIME_ONLY_COLUMNS or (low.endswith("_time") and low != "action_time"):
                time_cols.append(col)
            elif low in _DATE_ONLY_COLUMNS or low.endswith("_date"):
                date_cols.append(col)

        if date_cols or time_cols or datetime_cols:
            discovered[table] = {
                "pk": pk_col,
                "date_cols": tuple(date_cols),
                "time_cols": tuple(time_cols),
                "datetime_cols": tuple(datetime_cols),
            }
    return discovered


def migrate_database_datetime(
    db: Any,
    target_cal: str,
    target_time_fmt: str,
    create_backup: bool = True,
    force_normalize: bool = False,
) -> Dict[str, Any]:
    """
    Perform an atomic, lossless, idempotent migration of all date, time, and datetime
    columns across all user tables discovered via ``sqlite_master``.

    Supports mixed-origin databases (e.g. legacy rows in Jalali + newer rows in Hijri)
    by inspecting each cell's deterministic calendar year band and time format.
    """
    src_cal = db.get_setting("calendar_format", CALENDAR_JALALI) or CALENDAR_JALALI
    src_time_fmt = db.get_setting("time_format", TIME_FORMAT_24H) or TIME_FORMAT_24H

    dst_cal = CALENDAR_LOOKUP.get(target_cal, CALENDAR_JALALI)
    dst_time_fmt = TIME_FORMAT_LOOKUP.get(target_time_fmt, TIME_FORMAT_24H)

    if src_cal == dst_cal and src_time_fmt == dst_time_fmt and not force_normalize:
        db.set_setting("calendar_format", dst_cal)
        db.set_setting("time_format", dst_time_fmt)
        return {
            "status": "noop",
            "from_cal": src_cal,
            "to_cal": dst_cal,
            "from_time": src_time_fmt,
            "to_time": dst_time_fmt,
            "total_updated": 0,
        }

    backup_path = None
    if create_backup and hasattr(db, "db_path") and os.path.isfile(db.db_path):
        ts = int(time.time())
        backup_path = f"{db.db_path}.pre_cal_migration_{ts}.bak"
        try:
            shutil.copy2(db.db_path, backup_path)
        except Exception:
            backup_path = None

    stats: Dict[str, int] = {}
    total_updated = 0

    get_conn = getattr(db, "get_connection", None) or getattr(db, "transaction", None)
    with get_conn() as conn:
        table_map = discover_datetime_columns(conn)
        for table, spec in table_map.items():
            pk_col = spec["pk"]
            date_cols = spec["date_cols"]
            time_cols = spec["time_cols"]
            datetime_cols = spec["datetime_cols"]
            all_cols = list(date_cols) + list(time_cols) + list(datetime_cols)
            if not all_cols:
                continue

            col_sql = ", ".join([f'"{pk_col}"'] + [f'"{c}"' for c in all_cols])
            rows = conn.execute(f'SELECT {col_sql} FROM "{table}"').fetchall()

            table_updates = 0
            for row in rows:
                row_id = row[0]
                update_clauses: List[str] = []
                params: List[Any] = []

                idx = 1
                for d_col in date_cols:
                    val = row[idx]
                    idx += 1
                    if val:
                        conv = convert_date(
                            str(val),
                            src_cal,
                            dst_cal,
                            auto_detect_origin=True,
                        )
                        if conv != str(val):
                            update_clauses.append(f'"{d_col}" = ?')
                            params.append(conv)

                for t_col in time_cols:
                    val = row[idx]
                    idx += 1
                    if val:
                        conv = convert_time(str(val), src_time_fmt, dst_time_fmt)
                        if conv != str(val):
                            update_clauses.append(f'"{t_col}" = ?')
                            params.append(conv)

                for dt_col in datetime_cols:
                    val = row[idx]
                    idx += 1
                    if val:
                        conv = convert_datetime_str(
                            str(val),
                            from_cal=src_cal,
                            from_time_fmt=src_time_fmt,
                            to_cal=dst_cal,
                            to_time_fmt=dst_time_fmt,
                            auto_detect_origin=True,
                        )
                        if conv != str(val):
                            update_clauses.append(f'"{dt_col}" = ?')
                            params.append(conv)

                if update_clauses:
                    params.append(row_id)
                    conn.execute(
                        f'UPDATE "{table}" SET {", ".join(update_clauses)} WHERE "{pk_col}" = ?',
                        tuple(params),
                    )
                    table_updates += 1

            stats[table] = table_updates
            total_updated += table_updates

        db.set_setting("calendar_format", dst_cal, conn=conn)
        db.set_setting("time_format", dst_time_fmt, conn=conn)

    return {
        "status": "success",
        "from_cal": src_cal,
        "to_cal": dst_cal,
        "from_time": src_time_fmt,
        "to_time": dst_time_fmt,
        "backup_path": backup_path,
        "stats": stats,
        "total_updated": total_updated,
    }
