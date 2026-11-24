"""
Daqiq Multi-Calendar and Time Formatting Service.

Supports:
- Calendars:
    - 'jalali' (شمسی, default)
    - 'hijri' (قمری via hijridate)
    - 'gregorian' (میلادی)
- Time formats:
    - '24h' (۲۴ ساعته, default)
    - '12h' (۱۲ ساعته with ق.ظ / ب.ظ)
- Normalization:
    - Seamlessly parses Persian digits (۰-۹), Arabic digits (٠-٩), and ASCII digits (0-9).
- Safe Lossless Migration:
    - Converts historical records across sales, batches, upgrades, payments,
      service records, audit logs, and timestamps atomically with pre-migration backup.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from datetime import date, datetime
from typing import Dict, Optional, Tuple, Any

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
    TIME_FORMAT_12H: "۱۲ ساعته",
}

TIME_FORMAT_LOOKUP = {
    "۲۴ ساعته": TIME_FORMAT_24H,
    "24h": TIME_FORMAT_24H,
    "24": TIME_FORMAT_24H,
    "۱۲ ساعته": TIME_FORMAT_12H,
    "12h": TIME_FORMAT_12H,
    "12": TIME_FORMAT_12H,
}

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
# Core Date Parsing & Conversion
# ---------------------------------------------------------------------------

def parse_date_parts(date_str: str) -> Optional[Tuple[int, int, int]]:
    """Parse 'YYYY/MM/DD' or 'YYYY-MM-DD' into (year, month, day) using normalized digits."""
    if not date_str:
        return None
    cleaned = normalize_digits(str(date_str).strip())
    # Match 3 digit components separated by / or - (supporting optional trailing time)
    m = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})(?:\s+.*)?$", cleaned)
    if not m:
        return None
    try:
        y, mth, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mth <= 12 and 1 <= d <= 31:
            return y, mth, d
    except (ValueError, TypeError):
        pass
    return None


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


def convert_date(date_str: str, from_cal: str, to_cal: str) -> str:
    """
    Convert date string from one calendar system to another.
    Returns normalized 'YYYY/MM/DD'. If invalid, returns original string unmodified.
    """
    if not date_str:
        return date_str
    src_cal = CALENDAR_LOOKUP.get(from_cal, CALENDAR_JALALI)
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


# ---------------------------------------------------------------------------
# Core Time Parsing & Conversion
# ---------------------------------------------------------------------------

def parse_time_parts(time_str: str) -> Optional[Tuple[int, int, int]]:
    """
    Parse time string into 24-hour (hour, minute, second).
    Supports:
      - 24h: '14:30:00', '14:30', '09:15:20'
      - 12h Persian: '02:30:00 ب.ظ', '02:30:00 ق.ظ', '2:30 ب.ظ', '12:00:00 ب.ظ'
      - 12h English: '02:30:00 PM', '02:30:00 AM'
    """
    if not time_str:
        return None
    raw = normalize_digits(str(time_str).strip())
    # Check for period markers
    is_pm = bool(re.search(r"(?:ب\.?\s*ظ|pm)", raw, re.IGNORECASE))
    is_am = bool(re.search(r"(?:ق\.?\s*ظ|am)", raw, re.IGNORECASE))

    # Strip non-digits and non-colons
    clean_digits = re.sub(r"[^\d:]", "", raw)
    time_parts = clean_digits.split(":")
    if len(time_parts) < 2:
        return None

    try:
        h = int(time_parts[0])
        m = int(time_parts[1])
        s = int(time_parts[2]) if len(time_parts) > 2 else 0

        if not (0 <= m < 60 and 0 <= s < 60):
            return None

        if is_pm or is_am:
            # 12-hour logic
            if not (1 <= h <= 12):
                return None
            if is_pm and h < 12:
                h += 12
            elif is_am and h == 12:
                h = 0
        else:
            # 24-hour logic
            if not (0 <= h < 24):
                return None

        return h, m, s
    except (ValueError, TypeError):
        return None


def format_time_24h(h: int, m: int, s: int) -> str:
    """Format hour, minute, second into 24h 'HH:MM:SS'."""
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_time_12h(h: int, m: int, s: Optional[int] = None, include_seconds: bool = True) -> str:
    """Format 24h hour, minute, second into standard 12h 'hh:mm:ss AM/PM' or 'hh:mm AM/PM'."""
    suffix = "PM" if h >= 12 else "AM"
    h12 = h % 12
    if h12 == 0:
        h12 = 12
    if include_seconds and s is not None:
        return f"{h12:02d}:{m:02d}:{s:02d} {suffix}"
    return f"{h12:02d}:{m:02d} {suffix}"


def convert_time(time_str: str, from_fmt: str, to_fmt: str) -> str:
    """
    Convert time string between 24h and 12h formats.
    Returns converted time string or original if unparseable.
    """
    if not time_str:
        return time_str
    src_fmt = TIME_FORMAT_LOOKUP.get(from_fmt, TIME_FORMAT_24H)
    dst_fmt = TIME_FORMAT_LOOKUP.get(to_fmt, TIME_FORMAT_24H)

    parts = parse_time_parts(time_str)
    if not parts:
        return time_str

    h, m, s = parts
    raw = normalize_digits(str(time_str).strip())
    has_seconds = len(re.sub(r"[^\d:]", "", raw).split(":")) > 2

    if dst_fmt == TIME_FORMAT_12H:
        return format_time_12h(h, m, s if has_seconds else None, include_seconds=has_seconds)
    if has_seconds:
        return format_time_24h(h, m, s)
    return f"{h:02d}:{m:02d}"


def detect_calendar_type(date_str: str, default_cal: str = CALENDAR_JALALI) -> str:
    """
    Detect calendar origin by year range:
    - Gregorian: 1900 <= year <= 2199
    - Hijri: 1435 <= year <= 1650
    - Jalali: 1200 <= year < 1435 (standard retail range 1300..1434)
    """
    if not date_str:
        return default_cal
    parts = parse_date_parts(date_str)
    if not parts:
        return default_cal
    y, _, _ = parts
    if 1900 <= y <= 2199:
        return CALENDAR_GREGORIAN
    elif 1435 <= y <= 1650:
        return CALENDAR_HIJRI
    elif 1200 <= y < 1435:
        return CALENDAR_JALALI
    return default_cal


def detect_time_format(time_str: str, default_fmt: str = TIME_FORMAT_24H) -> str:
    """Detect whether time string is in 12h format (contains AM/PM or ق.ظ/ب.ظ) or 24h."""
    if not time_str:
        return default_fmt
    raw = normalize_digits(str(time_str).strip())
    if re.search(r"(?:ب\.?\s*ظ|ق\.?\s*ظ|pm|am)", raw, re.IGNORECASE):
        return TIME_FORMAT_12H
    return TIME_FORMAT_24H


def format_datetime_display(
    dt_val: Optional[str],
    target_cal: str = CALENDAR_JALALI,
    target_time_fmt: str = TIME_FORMAT_24H,
) -> str:
    """
    Format any timestamp (ISO YYYY-MM-DD HH:MM:SS, Jalali, Hijri, Gregorian)
    into target calendar and time format for consistent display across all tables.
    """
    if not dt_val or not str(dt_val).strip():
        return "—"
    s = str(dt_val).strip().replace("T", " ")
    if "." in s:
        s = s.split(".")[0]

    # Check if it's ISO Gregorian format YYYY-MM-DD ...
    m_iso = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}:\d{1,2}(?::\d{1,2})?.*))?$", normalize_digits(s))
    if m_iso:
        gy, gm, gd = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        time_sub = m_iso.group(4) or ""
        if 1900 <= gy <= 2199:
            try:
                g_date = date(gy, gm, gd)
                ty, tm, td = from_gregorian_date(g_date, target_cal)
                date_out = f"{ty:04d}/{tm:02d}/{td:02d}"
                if time_sub:
                    t_parts = parse_time_parts(time_sub)
                    if t_parts:
                        th, tmnt, ts = t_parts
                        has_sec = len(re.sub(r"[^\d:]", "", time_sub).split(":")) > 2
                        if target_time_fmt == TIME_FORMAT_12H:
                            time_out = format_time_12h(th, tmnt, ts if has_sec else None, include_seconds=has_sec)
                        else:
                            time_out = format_time_24h(th, tmnt, ts) if has_sec else f"{th:02d}:{tmnt:02d}"
                        return f"{date_out} {time_out}"
                return date_out
            except Exception:
                pass

    # Fallback: general convert_datetime_str with auto-detected calendar
    tokens = s.split(" ", 1)
    date_p = tokens[0]
    time_p = tokens[1] if len(tokens) > 1 else ""

    detected_cal = detect_calendar_type(date_p, default_cal=target_cal)
    detected_time = detect_time_format(time_p, default_fmt=target_time_fmt)

    return convert_datetime_str(
        s,
        from_cal=detected_cal,
        from_time_fmt=detected_time,
        to_cal=target_cal,
        to_time_fmt=target_time_fmt,
    )


# ---------------------------------------------------------------------------
# Combined Datetime String Conversion
# ---------------------------------------------------------------------------

def convert_datetime_str(
    dt_str: str,
    from_cal: str = CALENDAR_JALALI,
    from_time_fmt: str = TIME_FORMAT_24H,
    to_cal: str = CALENDAR_JALALI,
    to_time_fmt: str = TIME_FORMAT_24H,
) -> str:
    """
    Convert combined datetime string (e.g. '1403/05/20 14:30:00' or '1403/05/20').
    Safely preserves original text if unparseable.
    """
    if not dt_str:
        return dt_str

    cleaned = str(dt_str).strip()
    if not cleaned:
        return dt_str

    # Split date portion and time portion
    tokens = cleaned.split(" ", 1)
    date_part = tokens[0]
    time_part = tokens[1] if len(tokens) > 1 else ""

    converted_date = convert_date(date_part, from_cal, to_cal)
    if not time_part:
        return converted_date

    converted_time = convert_time(time_part, from_time_fmt, to_time_fmt)
    return f"{converted_date} {converted_time}"


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
# Lossless Database Migration Engine
# ---------------------------------------------------------------------------

# Tables and their respective date/time columns to migrate
_DATETIME_COLUMNS_MAP = {
    "sales": {
        "date_cols": ("warranty_start", "warranty_end"),
        "datetime_cols": ("sale_datetime", "created_at", "updated_at"),
    },
    "batches": {
        "date_cols": ("purchase_date",),
        "datetime_cols": ("created_at", "updated_at"),
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


def ensure_calendar_segments_table(conn: Any) -> None:
    """Ensure db_calendar_segments metadata table exists."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS db_calendar_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            min_rowid INTEGER NOT NULL,
            max_rowid INTEGER NOT NULL,
            calendar_type TEXT NOT NULL,
            time_format TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)


def record_future_calendar_switch(
    db: Any,
    previous_cal: str,
    previous_time_fmt: str,
    new_cal: str,
    new_time_fmt: str,
) -> None:
    """
    Record existing rowid ranges in db_calendar_segments under previous calendar format
    when the user switches formats in 'future-only' mode.
    """
    get_conn = getattr(db, "get_connection", None) or getattr(db, "transaction", None)
    with get_conn() as conn:
        ensure_calendar_segments_table(conn)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for table in _DATETIME_COLUMNS_MAP:
            cur = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
            if not cur.fetchone()[0]:
                continue
            row_range = conn.execute(
                f"SELECT MIN(id), MAX(id) FROM {table}"
            ).fetchone()
            if row_range and row_range[0] is not None and row_range[1] is not None:
                min_id, max_id = row_range[0], row_range[1]
                conn.execute(
                    """INSERT INTO db_calendar_segments
                       (table_name, min_rowid, max_rowid, calendar_type, time_format, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (table, min_id, max_id, previous_cal, previous_time_fmt, now_str),
                )
        db.set_setting("calendar_format", new_cal, conn=conn)
        db.set_setting("time_format", new_time_fmt, conn=conn)


def migrate_database_datetime(
    db: Any,
    target_cal: str,
    target_time_fmt: str,
    create_backup: bool = True,
) -> Dict[str, Any]:
    """
    Perform an atomic, lossless migration of all date and datetime fields in the database.
    
    1. Creates safety backup copy if requested.
    2. Opens atomic transaction.
    3. Reads stored calendar and time format from settings table.
    4. Evaluates recorded db_calendar_segments and smart year ranges to detect
       mixed-origin records (e.g. older Jalali records + newer Hijri future-only records).
    5. Migrates date columns and datetime columns row by row from their actual origins.
    6. Collapses calendar segments to unified target format.
    7. Saves new calendar_format and time_format in settings table.
    8. Commits cleanly; rolls back on any error.
    
    Returns a result dict with migration statistics.
    """
    src_cal = db.get_setting("calendar_format", CALENDAR_JALALI) or CALENDAR_JALALI
    src_time_fmt = db.get_setting("time_format", TIME_FORMAT_24H) or TIME_FORMAT_24H

    dst_cal = CALENDAR_LOOKUP.get(target_cal, CALENDAR_JALALI)
    dst_time_fmt = TIME_FORMAT_LOOKUP.get(target_time_fmt, TIME_FORMAT_24H)

    # Backup if database file exists on disk
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
        ensure_calendar_segments_table(conn)

        # Load existing segment boundaries
        segments_by_table: Dict[str, list] = {}
        try:
            seg_rows = conn.execute(
                "SELECT table_name, min_rowid, max_rowid, calendar_type, time_format FROM db_calendar_segments ORDER BY id ASC"
            ).fetchall()
            for sr in seg_rows:
                segments_by_table.setdefault(sr[0], []).append({
                    "min": sr[1],
                    "max": sr[2],
                    "cal": sr[3],
                    "time": sr[4],
                })
        except Exception:
            pass

        for table, cols in _DATETIME_COLUMNS_MAP.items():
            # Check if table exists in SQLite
            cur = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
            if not cur.fetchone()[0]:
                continue

            date_cols = cols.get("date_cols", ())
            datetime_cols = cols.get("datetime_cols", ())
            all_cols = list(date_cols) + list(datetime_cols)

            if not all_cols:
                continue

            # Query primary key and target columns
            col_sql = ", ".join(["id"] + all_cols)
            rows = conn.execute(f"SELECT {col_sql} FROM {table}").fetchall()

            table_segments = segments_by_table.get(table, [])
            table_updates = 0

            for row in rows:
                row_id = row[0]
                update_clauses = []
                params = []

                # Find segment if recorded
                row_seg_cal = None
                row_seg_time = None
                for seg in table_segments:
                    if seg["min"] <= row_id <= seg["max"]:
                        row_seg_cal = seg["cal"]
                        row_seg_time = seg["time"]
                        break

                idx = 1
                for d_col in date_cols:
                    val = row[idx]
                    idx += 1
                    if val:
                        val_str = str(val).strip()
                        # Detect origin: priority segment -> smart year range detector -> global src_cal
                        detected_cal = row_seg_cal or detect_calendar_type(val_str, default_cal=src_cal)
                        conv = convert_date(val_str, detected_cal, dst_cal)
                        if conv != val_str:
                            update_clauses.append(f"{d_col} = ?")
                            params.append(conv)

                for dt_col in datetime_cols:
                    val = row[idx]
                    idx += 1
                    if val:
                        val_str = str(val).strip()
                        tokens = val_str.split(" ", 1)
                        date_tok = tokens[0]
                        time_tok = tokens[1] if len(tokens) > 1 else ""

                        detected_cal = row_seg_cal or detect_calendar_type(date_tok, default_cal=src_cal)
                        detected_time = row_seg_time or detect_time_format(time_tok, default_fmt=src_time_fmt)

                        conv = convert_datetime_str(
                            val_str,
                            from_cal=detected_cal,
                            from_time_fmt=detected_time,
                            to_cal=dst_cal,
                            to_time_fmt=dst_time_fmt,
                        )
                        if conv != val_str:
                            update_clauses.append(f"{dt_col} = ?")
                            params.append(conv)

                if update_clauses:
                    params.append(row_id)
                    conn.execute(
                        f"UPDATE {table} SET {', '.join(update_clauses)} WHERE id = ?",
                        tuple(params),
                    )
                    table_updates += 1

            stats[table] = table_updates
            total_updated += table_updates

            # Reset segments for this table to unified target format
            conn.execute("DELETE FROM db_calendar_segments WHERE table_name = ?", (table,))
            row_range = conn.execute(f"SELECT MIN(id), MAX(id) FROM {table}").fetchone()
            if row_range and row_range[0] is not None and row_range[1] is not None:
                conn.execute(
                    """INSERT INTO db_calendar_segments
                       (table_name, min_rowid, max_rowid, calendar_type, time_format, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (table, row_range[0], row_range[1], dst_cal, dst_time_fmt, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )

        # Update settings inside same atomic transaction
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
