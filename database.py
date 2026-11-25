# database.py
import os
import sys
import json
import re
import threading
try:
    import sqlcipher3 as sqlite3
except ImportError:
    import sqlite3
import shutil
import jdatetime
import time
import hashlib
import random
from decimal import Decimal, ROUND_HALF_EVEN
from utils import datetime_format

APP_VERSION = "4.8.4"
# SQLite database schema version written into PRAGMA user_version and settings.schema_version.
# Preserved as 484 for 100% zero-breaking compatibility with existing commercial retail DBs.
SCHEMA_VERSION = 484
# app_config.json configuration format version (distinct from SQLite DB SCHEMA_VERSION).
CONFIG_SCHEMA_VERSION = 2


class ReadOnlyGraceError(PermissionError):
    """Raised when a mutating operation is attempted during a read-only license grace period."""


class ConcurrencyConflictError(RuntimeError):
    """Raised when optimistic concurrency control detects a newer row_version in SQLite."""

    def __init__(
        self,
        entity: str,
        record_id: int,
        expected_version: int,
        actual_version: int,
        live_row: dict = None,
        message: str = "",
    ):
        self.entity = entity
        self.record_id = record_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        self.live_row = dict(live_row or {})
        self.message_fa = message or (
            "این رکورد هم‌زمان توسط کاربر یا سیستم دیگری در شبکه تغییر کرده است."
        )
        super().__init__(self.message_fa)


class InsufficientStockError(ValueError):
    """Raised when atomic stock deduction finds insufficient remaining quantity."""

    def __init__(
        self,
        available_qty: int,
        requested_qty: int,
        batch_code: str = "",
        concurrent_modified: bool = False,
        message: str = "",
    ):
        self.available_qty = int(available_qty)
        self.requested_qty = int(requested_qty)
        self.batch_code = str(batch_code or "")
        self.concurrent_modified = bool(concurrent_modified)
        self.message_fa = message or (
            f"موجودی محموله «{self.batch_code}» کافی نیست. موجودی فعلی: {self.available_qty}، درخواستی: {self.requested_qty}"
        )
        super().__init__(self.message_fa)


def is_network_database_path(db_path: str) -> bool:
    """Return True when db_path points to an SMB/UNC share or Windows mapped network drive."""
    raw = str(db_path or "").strip()
    if not raw:
        return False
    if raw.startswith("\\\\") or raw.startswith("//") or raw.lower().startswith("file:////"):
        return True
    try:
        abs_path = os.path.abspath(raw)
        if abs_path.startswith("\\\\") or abs_path.startswith("//"):
            return True
        if sys.platform == "win32":
            drive, _ = os.path.splitdrive(abs_path)
            if drive and len(drive) == 2 and drive[1] == ":":
                import ctypes
                DRIVE_REMOTE = 4
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")
                if drive_type == DRIVE_REMOTE:
                    return True
    except Exception:
        pass
    return False


ROW_VERSION_TABLES = (
    "employees",
    "suppliers",
    "customers",
    "products",
    "batches",
    "upgrades",
    "sales",
    "service_catalog",
    "service_records",
    "payments",
)


def get_live_app_version() -> str:
    """Resolve the running application's live version string from VERSION."""
    candidates = []
    try:
        from utils.paths import get_resource_path
        candidates.append(str(get_resource_path("VERSION")))
    except Exception:
        pass
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION"))
    for ver_path in candidates:
        try:
            if os.path.isfile(ver_path):
                with open(ver_path, "r", encoding="utf-8") as vf:
                    text = vf.read().strip()
                if text:
                    return text
        except OSError:
            pass
    return "4.9.10"

SQLITE_INTEGER_MIN = -(1 << 63)
SQLITE_INTEGER_MAX = (1 << 63) - 1

# New v4 databases have a deliberate, testable physical column order. Application
# SQL uses named columns; this contract protects all positional consumers.
EXPECTED_SCHEMA_COLUMNS = {
    "settings": ("key", "value"),
    "employees": ("id", "name", "role", "phone", "is_active", "permissions", "password", "created_at", "updated_at", "last_login_at", "row_version"),
    "access_level_data_scopes": ("access_level_name", "mode"),
    "access_level_scope_levels": ("access_level_name", "selected_access_level_name"),
    "access_level_scope_users": ("access_level_name", "employee_id"),
    "suppliers": ("id", "name", "phone", "address", "notes", "created_at", "updated_at", "row_version"),
    "customers": ("id", "name", "phone", "notes", "created_at", "updated_at", "row_version"),
    "products": ("id", "code", "serial_number", "name", "category", "sub_category", "brand", "model", "specs_json", "description", "reorder_point", "default_profit_pct", "is_active", "created_at", "updated_at", "row_version"),
    "batches": ("id", "batch_code", "product_id", "serial_numbers", "supplier_id", "buyer_employee_id", "invoice_number", "purchase_date", "initial_qty", "sold_qty", "returned_qty", "remaining_qty", "unit_purchase_price", "extra_cost_total", "upgrade_cost_unit", "unit_cost_price", "suggested_sell_price", "profit_pct", "paid_amount", "settlement_status", "colors_json", "initial_specs", "final_specs", "supplier_name_snapshot", "notes", "created_at", "updated_at", "row_version"),
    "upgrades": ("id", "target_batch_id", "part_batch_id", "technician_id", "target_qty", "part_qty_used", "stock_deducted_qty", "part_unit_cost", "labor_cost_unit", "added_cost_unit", "upgrade_date", "serial_number", "manual_part_description", "old_specs", "new_specs", "notes", "created_at", "updated_at", "row_version"),
    "sales": ("id", "invoice_number", "product_id", "batch_id", "serial_number", "seller_employee_id", "customer_name", "customer_phone", "qty", "returned_qty", "suggested_unit_price", "actual_unit_price", "unit_cost_price", "unit_discount", "total_discount", "price_Markup_unit", "unit_profit", "total_profit", "total_amount", "paid_amount", "settlement_status", "sale_datetime", "warranty_company", "warranty_start", "warranty_months", "warranty_days", "warranty_end", "specifications", "colors_json", "notes", "created_at", "updated_at", "row_version"),
    "service_catalog": ("id", "code", "service_type", "name", "default_fee", "default_side_cost", "description", "is_active", "created_at", "updated_at", "row_version"),
    "service_price_history": ("id", "service_id", "change_date", "old_fee", "new_fee", "created_at", "updated_at"),
    "service_records": ("id", "invoice_number", "service_id", "seller_employee_id", "technician_employee_id", "service_type", "service_name", "customer_name", "historical_tariff", "service_fee", "side_cost", "paid_amount", "net_profit", "settlement_status", "service_datetime", "description", "created_at", "updated_at", "row_version"),
    "payments": ("id", "ref_type", "ref_id", "amount", "payment_date", "notes", "created_at", "updated_at", "row_version"),
    "audit_logs": ("id", "action_time", "action_type", "details", "created_at", "updated_at"),
}

def validate_schema_column_order(conn):
    """Fail fast when a database does not match the exact v4 column contract."""
    for table_name, expected_columns in EXPECTED_SCHEMA_COLUMNS.items():
        actual_columns = tuple(
            row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")
        )
        if actual_columns == expected_columns:
            continue
        raise RuntimeError(
            f"ساختار ستون‌های جدول {table_name} با قرارداد نسخه {APP_VERSION} سازگار نیست."
        )


def round_integer_division(numerator, denominator):
    """Round an integer ratio using exact round-half-to-even arithmetic."""
    numerator = int(numerator)
    denominator = int(denominator)
    if denominator <= 0:
        raise ValueError("مقسوم‌علیه باید بزرگ‌تر از صفر باشد.")
    sign = -1 if numerator < 0 else 1
    quotient, remainder = divmod(abs(numerator), denominator)
    doubled_remainder = remainder * 2
    if doubled_remainder > denominator or (
        doubled_remainder == denominator and quotient % 2
    ):
        quotient += 1
    return sign * quotient


def round_percentage_amount(amount, percentage):
    """Apply a percentage to an integer amount without binary-float precision loss."""
    multiplier = Decimal(100) + Decimal(str(percentage))
    result = Decimal(int(amount)) * multiplier / Decimal(100)
    return int(result.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))


def get_app_data_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "Daqiq")
    os.makedirs(path, exist_ok=True)
    return path


def get_windows_documents_path():
    """Dynamically resolve the user's OS-registered Windows Documents directory."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", wintypes.BYTE * 8)
                ]
            # FOLDERID_Documents: {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
            guid_documents = GUID(
                0xFDD39AD0, 0x238F, 0x46AF,
                (wintypes.BYTE * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7)
            )
            sh_get_known_folder_path = ctypes.windll.shell32.SHGetKnownFolderPath
            sh_get_known_folder_path.argtypes = [
                ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)
            ]
            sh_get_known_folder_path.restype = ctypes.c_long
            path_ptr = ctypes.c_wchar_p()
            try:
                res = sh_get_known_folder_path(ctypes.byref(guid_documents), 0, 0, ctypes.byref(path_ptr))
                if res == 0 and path_ptr.value:
                    return os.path.normpath(path_ptr.value)
            finally:
                if path_ptr.value:
                    ole32 = ctypes.windll.ole32
                    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
                    ole32.CoTaskMemFree.restype = None
                    ole32.CoTaskMemFree(path_ptr)
        except Exception:
            pass
        try:
            from PySide6.QtCore import QStandardPaths
            loc = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
            if loc:
                return os.path.normpath(loc)
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def get_default_database_dir():
    """Return the user's Documents/Daqiq directory for the default store database."""
    documents_dir = get_windows_documents_path()
    path = os.path.join(documents_dir, "Daqiq")
    os.makedirs(path, exist_ok=True)
    return path


def get_default_database_path():
    return os.path.join(get_default_database_dir(), "Daqiq.db")


def resolve_new_database_filename(base_dir=None, known_paths=None) -> str:
    """Enforce REQ-2 sequential database naming:
    - If 'Daqiq.db' does NOT exist -> select 'Daqiq.db'.
    - If 'Daqiq.db' EXISTS -> find the next available sequential filename:
      'Daqiq_2.db', 'Daqiq_3.db', 'Daqiq_4.db', ...
    Checks both disk existence and registered/known DB paths so it NEVER overwrites an existing file.
    """
    if base_dir is None:
        base_dir = get_default_database_dir()
    os.makedirs(base_dir, exist_ok=True)

    registered_norms = set()
    if known_paths:
        for p in known_paths:
            if p:
                registered_norms.add(os.path.normcase(os.path.abspath(p)))
    else:
        try:
            cfg = load_app_config()
            for p in cfg.get("recent_databases", []) + [cfg.get("db_path")]:
                if p:
                    registered_norms.add(os.path.normcase(os.path.abspath(p)))
        except Exception:
            pass

    cand_1 = os.path.abspath(os.path.join(base_dir, "Daqiq.db"))
    if not os.path.exists(cand_1):
        return cand_1

    idx = 2
    while True:
        cand = os.path.abspath(os.path.join(base_dir, f"Daqiq_{idx}.db"))
        if not os.path.exists(cand) and os.path.normcase(cand) not in registered_norms:
            return cand
        idx += 1


def generate_timestamped_database_filename(base_dir=None, prefix="Daqiq", extension=".db"):
    """Generate a Windows-filesystem-safe, sortable timestamped database filename (Daqiq_YYYY-MM-DD_HH-MM-SS.db).
    Guarantees no colons or invalid path characters and ensures no collisions with existing files."""
    from datetime import datetime
    if base_dir is None:
        base_dir = get_default_database_dir()
    now_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{prefix}_{now_str}{extension}"
    candidate = os.path.join(base_dir, filename)
    suffix = 1
    while os.path.exists(candidate):
        candidate = os.path.join(base_dir, f"{prefix}_{now_str}_{suffix}{extension}")
        suffix += 1
    return candidate


def create_and_initialize_database(target_path: str, password: str = None) -> "DatabaseManager":
    """Unified database creation and bootstrap service (REQ-1).
    Initializes clean-slate schema on target_path, seeds from default_taxonomy.json if present
    (or initializes completely empty taxonomy if absent), checkpoints WAL, and returns active DatabaseManager.
    """
    target_path = os.path.abspath(os.path.expanduser(target_path))
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
    db = DatabaseManager(target_path, password=password)
    tax = load_default_taxonomy_from_seed()
    if tax and isinstance(tax, dict):
        db.save_product_catalog_config(tax)
    else:
        db.save_product_catalog_config({
            "categories": [],
            "subcategories": {},
            "attributes": {},
            "colors": [],
            "service_types": [],
        })
    db.sync_database()
    return db


class SecureCredentialStore:
    """Zero-plaintext, OS-protected credential vault for encrypted database auto-unlock (REQ-4).
    Uses native Windows DPAPI (CryptProtectData/CryptUnprotectData) bound to the current Windows user,
    with an isolated cryptographic fallback for cross-platform/Linux headless CI testing.
    Never stores plaintext passwords or weak reversible encodings.
    """
    _vault_file = None

    @classmethod
    def _get_vault_path(cls) -> str:
        if cls._vault_file:
            return cls._vault_file
        config_dir = os.path.dirname(os.path.abspath(get_config_file_path()))
        return os.path.join(config_dir, ".secure_vault.dat")

    @classmethod
    def set_vault_path(cls, path: str):
        cls._vault_file = path

    @classmethod
    def _dpapi_protect(cls, data: bytes, entropy: bytes) -> bytes:
        import ctypes
        from ctypes import wintypes
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(DATA_BLOB),
            wintypes.LPCWSTR,
            ctypes.POINTER(DATA_BLOB),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(DATA_BLOB),
        ]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        data_in = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_byte)))
        ent_blob = DATA_BLOB(len(entropy), ctypes.cast(ctypes.create_string_buffer(entropy), ctypes.POINTER(ctypes.c_byte))) if entropy else None
        ent_ptr = ctypes.byref(ent_blob) if ent_blob else None
        data_out = DATA_BLOB()
        # CRYPTPROTECT_UI_FORBIDDEN = 0x01
        if not crypt32.CryptProtectData(ctypes.byref(data_in), "DaqiqAutoUnlock", ent_ptr, None, None, 0x01, ctypes.byref(data_out)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(data_out.pbData, data_out.cbData)
        finally:
            kernel32.LocalFree(data_out.pbData)

    @classmethod
    def _dpapi_unprotect(cls, cipher: bytes, entropy: bytes) -> bytes:
        import ctypes
        from ctypes import wintypes
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(DATA_BLOB),
            ctypes.c_void_p,
            ctypes.POINTER(DATA_BLOB),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(DATA_BLOB),
        ]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        data_in = DATA_BLOB(len(cipher), ctypes.cast(ctypes.create_string_buffer(cipher), ctypes.POINTER(ctypes.c_byte)))
        ent_blob = DATA_BLOB(len(entropy), ctypes.cast(ctypes.create_string_buffer(entropy), ctypes.POINTER(ctypes.c_byte))) if entropy else None
        ent_ptr = ctypes.byref(ent_blob) if ent_blob else None
        data_out = DATA_BLOB()
        if not crypt32.CryptUnprotectData(ctypes.byref(data_in), None, ent_ptr, None, None, 0x01, ctypes.byref(data_out)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(data_out.pbData, data_out.cbData)
        finally:
            kernel32.LocalFree(data_out.pbData)

    @classmethod
    def _protect_bytes(cls, raw: bytes, entropy: bytes) -> bytes:
        if sys.platform == "win32":
            try:
                return b"DPAPI:" + cls._dpapi_protect(raw, entropy)
            except Exception:
                pass
        # Cross-platform fallback: machine/entropy-bound cryptographic transformation
        salt = hashlib.sha256(entropy + b"DaqiqSecureSalt").digest()
        key = hashlib.pbkdf2_hmac("sha256", entropy, salt, 50000, 32)
        stream = hashlib.sha256(key + salt).digest()
        cipher = bytes(b ^ stream[i % len(stream)] for i, b in enumerate(raw))
        return b"FALLBACK:" + cipher

    @classmethod
    def _unprotect_bytes(cls, payload: bytes, entropy: bytes) -> bytes:
        if payload.startswith(b"DPAPI:"):
            if sys.platform == "win32":
                return cls._dpapi_unprotect(payload[6:], entropy)
            raise RuntimeError("DPAPI payload cannot be decrypted on non-Windows.")
        if payload.startswith(b"FALLBACK:"):
            cipher = payload[9:]
            salt = hashlib.sha256(entropy + b"DaqiqSecureSalt").digest()
            key = hashlib.pbkdf2_hmac("sha256", entropy, salt, 50000, 32)
            stream = hashlib.sha256(key + salt).digest()
            return bytes(b ^ stream[i % len(stream)] for i, b in enumerate(cipher))
        raise ValueError("Unknown ciphertext format.")

    @classmethod
    def _read_vault(cls) -> dict:
        vpath = cls._get_vault_path()
        if not os.path.isfile(vpath):
            return {}
        try:
            with open(vpath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @classmethod
    def _write_vault(cls, data: dict):
        vpath = cls._get_vault_path()
        if not data:
            if os.path.isfile(vpath):
                try:
                    os.remove(vpath)
                except OSError:
                    pass
            return
        os.makedirs(os.path.dirname(vpath) or ".", exist_ok=True)
        tmp = vpath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, vpath)

    @classmethod
    def store_database_credential(cls, db_path: str, password: str):
        if not db_path or not password:
            return
        norm = os.path.normcase(os.path.abspath(db_path))
        entropy = norm.encode("utf-8")
        protected = cls._protect_bytes(password.encode("utf-8"), entropy)
        vault = cls._read_vault()
        vault[norm] = protected.hex()
        cls._write_vault(vault)

    @classmethod
    def retrieve_database_credential(cls, db_path: str):
        if not db_path:
            return None
        norm = os.path.normcase(os.path.abspath(db_path))
        vault = cls._read_vault()
        hex_val = vault.get(norm)
        if not hex_val:
            return None
        try:
            raw = bytes.fromhex(hex_val)
            entropy = norm.encode("utf-8")
            dec = cls._unprotect_bytes(raw, entropy)
            return dec.decode("utf-8")
        except Exception:
            cls.purge_database_credential(db_path)
            return None

    @classmethod
    def purge_database_credential(cls, db_path: str):
        if not db_path:
            return
        norm = os.path.normcase(os.path.abspath(db_path))
        vault = cls._read_vault()
        if norm in vault:
            vault.pop(norm, None)
            cls._write_vault(vault)

    @classmethod
    def purge_all_credentials(cls):
        vpath = cls._get_vault_path()
        if os.path.isfile(vpath):
            try:
                os.remove(vpath)
            except OSError:
                pass


from utils.paths import (
    get_app_config_path as _get_app_config_path_obj,
    get_default_taxonomy_path as _get_default_taxonomy_path_obj,
    get_executable_dir as _get_executable_dir_obj,
)


def get_executable_dir():
    """Return the real outer directory containing Daqiq.exe (or source root)."""
    return str(_get_executable_dir_obj())


def get_default_taxonomy_path():
    """Return path to default_taxonomy.json located directly alongside Daqiq.exe."""
    onefile_bin = os.environ.get("NUITKA_ONEFILE_BINARY")
    if onefile_bin and str(onefile_bin).strip():
        return str(_get_default_taxonomy_path_obj())
    if not getattr(sys, "frozen", False):
        cfg_dir = os.path.dirname(os.path.abspath(get_config_file_path()))
        if os.path.normcase(cfg_dir) != os.path.normcase(str(_get_executable_dir_obj())):
            return os.path.join(cfg_dir, "default_taxonomy.json")
    return str(_get_default_taxonomy_path_obj())


def load_default_taxonomy_from_seed():
    """Read default_taxonomy.json if present; return None if missing without fallback."""
    path = get_default_taxonomy_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return None


def get_config_file_path():
    """Keep portable settings beside the executable whenever that location is writable."""
    return str(_get_app_config_path_obj())


CONFIG_FILE = get_config_file_path()


def app_config_exists():
    """Return whether an explicit database-selection/configuration file exists."""
    return os.path.isfile(CONFIG_FILE)


def app_config_has_database_selection():
    """Require a parseable config with an explicitly stored active database path."""
    if not app_config_exists():
        return False
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return (
        isinstance(data, dict)
        and bool(str(data.get("db_path") or "").strip())
    )


def reconcile_app_config(raw_cfg=None):
    """Reconcile config dict against canonical keys and the live running APP_VERSION.

    Migrates legacy aliases (``last_db_path`` -> ``db_path``,
    ``calendar_format`` -> ``calendar_type``, ``store_name`` -> ``last_store_name``),
    drops orphaned legacy keys, validates bounds/types without touching user preferences,
    and returns ``(reconciled_cfg, changed)``.
    """
    default_db = get_default_database_path()
    default_backup_dir = os.path.join(get_default_database_dir(), "Backups")
    live_version = get_live_app_version()
    cfg = {
        "db_path": default_db,
        "recent_databases": [default_db] if os.path.isfile(default_db) else [],
        "backup_dir": default_backup_dir,
        "auto_backup_dir": "",
        "auto_backup_enabled": True,
        "auto_backup_interval_min": 60,
        "auto_backup_retention_count": 10,
        "auto_backup_last_success_by_db": {},
        "last_backup_time": "ثبت نشده",
        "default_profit_pct": 20,
        "default_min_inventory": 1,
        "zero_append_count": 3,
        "default_window_maximized": True,
        "require_login_password": False,
        "config_schema_version": CONFIG_SCHEMA_VERSION,
        "app_version": live_version,
        "schema_version": CONFIG_SCHEMA_VERSION,
        "theme": "light",
        "calendar_type": datetime_format.CALENDAR_JALALI,
        "time_format": datetime_format.TIME_FORMAT_24H,
        "last_store_name": "فروشگاه من",
        "databases": {},
    }
    raw_dict = raw_cfg if isinstance(raw_cfg, dict) else {}
    if raw_dict:
        cfg.update(raw_dict)

    # Migrate legacy aliases without clobbering user preferences
    if (not str(raw_dict.get("db_path") or "").strip()) and str(raw_dict.get("last_db_path") or "").strip():
        cfg["db_path"] = raw_dict["last_db_path"]
    if "calendar_format" in raw_dict and "calendar_type" not in raw_dict:
        cfg["calendar_type"] = raw_dict["calendar_format"]
    if "store_name" in raw_dict and not str(raw_dict.get("last_store_name") or "").strip():
        cfg["last_store_name"] = raw_dict["store_name"]

    for orphan_key in ("local_db_unlock_tokens", "last_db_path", "calendar_format", "store_name", "shop_name"):
        cfg.pop(orphan_key, None)

    cfg["app_version"] = live_version
    cfg["config_schema_version"] = CONFIG_SCHEMA_VERSION
    cfg["schema_version"] = CONFIG_SCHEMA_VERSION
    cfg["theme"] = "dark" if str(cfg.get("theme") or "").strip().lower() == "dark" else "light"
    cfg["calendar_type"] = datetime_format.CALENDAR_LOOKUP.get(
        str(cfg.get("calendar_type") or "").strip().lower(),
        datetime_format.CALENDAR_JALALI,
    )
    cfg["time_format"] = datetime_format.TIME_FORMAT_LOOKUP.get(
        str(cfg.get("time_format") or "").strip().lower(),
        datetime_format.TIME_FORMAT_24H,
    )
    cfg["last_store_name"] = str(cfg.get("last_store_name") or "فروشگاه من").strip() or "فروشگاه من"
    cfg["auto_backup_enabled"] = bool(cfg.get("auto_backup_enabled", True))
    cfg["default_window_maximized"] = bool(cfg.get("default_window_maximized", True))
    cfg["require_login_password"] = bool(cfg.get("require_login_password", False))
    try:
        cfg["auto_backup_interval_min"] = max(1, int(cfg.get("auto_backup_interval_min", 60) or 60))
    except (TypeError, ValueError):
        cfg["auto_backup_interval_min"] = 60
    try:
        cfg["auto_backup_retention_count"] = max(1, int(cfg.get("auto_backup_retention_count", 10) or 10))
    except (TypeError, ValueError):
        cfg["auto_backup_retention_count"] = 10
    try:
        zero_raw = cfg.get("zero_append_count", 3)
        cfg["zero_append_count"] = max(0, int(3 if zero_raw is None else zero_raw))
    except (TypeError, ValueError):
        cfg["zero_append_count"] = 3
    try:
        min_inv_raw = cfg.get("default_min_inventory", 1)
        cfg["default_min_inventory"] = max(0, int(1 if min_inv_raw is None else min_inv_raw))
    except (TypeError, ValueError):
        cfg["default_min_inventory"] = 1
    try:
        profit_raw = cfg.get("default_profit_pct", 20)
        cfg["default_profit_pct"] = max(0, int(float(20 if profit_raw is None else profit_raw)))
    except (TypeError, ValueError):
        cfg["default_profit_pct"] = 20

    if not isinstance(cfg.get("auto_backup_last_success_by_db"), dict):
        cfg["auto_backup_last_success_by_db"] = {}
    if cfg.get("auto_backup_dir"):
        cfg["auto_backup_dir"] = os.path.abspath(str(cfg["auto_backup_dir"]))
    else:
        cfg["auto_backup_dir"] = ""

    raw_dbs = cfg.get("databases")
    if isinstance(raw_dbs, dict):
        clean_dbs = {}
        for dbk, dbv in raw_dbs.items():
            if not isinstance(dbk, str) or not isinstance(dbv, dict):
                continue
            clean_dbs[dbk] = {
                "auto_backup_enabled": bool(dbv.get("auto_backup_enabled", cfg["auto_backup_enabled"])),
                "auto_backup_dir": os.path.abspath(str(dbv["auto_backup_dir"])) if dbv.get("auto_backup_dir") else "",
                "auto_backup_interval_min": max(1, int(dbv.get("auto_backup_interval_min", cfg["auto_backup_interval_min"]) or 60)),
                "auto_backup_retention_count": max(1, int(dbv.get("auto_backup_retention_count", cfg["auto_backup_retention_count"]) or 10)),
            }
        cfg["databases"] = clean_dbs
    else:
        cfg["databases"] = {}

    # Normalize paths and deduplicate recent_databases to physical files only
    cleaned_recents = []
    seen = set()
    raw_recents = cfg.get("recent_databases")
    if isinstance(raw_recents, list):
        for p in raw_recents:
            if not p or not isinstance(p, str):
                continue
            norm = os.path.normcase(os.path.abspath(p))
            if norm not in seen and os.path.isfile(p):
                seen.add(norm)
                cleaned_recents.append(os.path.abspath(p))
    cur_p = cfg.get("db_path")
    if cur_p and isinstance(cur_p, str) and os.path.isfile(cur_p):
        cur_norm = os.path.normcase(os.path.abspath(cur_p))
        if cur_norm not in seen:
            cleaned_recents.insert(0, os.path.abspath(cur_p))
    cfg["recent_databases"] = cleaned_recents

    if cfg.get("last_backup_warning") is not None:
        warn_txt = str(cfg.get("last_backup_warning") or "").strip()
        if warn_txt:
            cfg["last_backup_warning"] = warn_txt
        else:
            cfg.pop("last_backup_warning", None)

    canonical_keys = {
        "db_path",
        "recent_databases",
        "backup_dir",
        "auto_backup_dir",
        "auto_backup_enabled",
        "auto_backup_interval_min",
        "auto_backup_retention_count",
        "auto_backup_last_success_by_db",
        "last_backup_time",
        "last_backup_warning",
        "default_profit_pct",
        "default_min_inventory",
        "zero_append_count",
        "default_window_maximized",
        "require_login_password",
        "config_schema_version",
        "app_version",
        "schema_version",
        "theme",
        "calendar_type",
        "time_format",
        "last_store_name",
        "databases",
    }
    for extra_k in list(cfg.keys()):
        if extra_k not in canonical_keys:
            cfg.pop(extra_k, None)

    changed = (not raw_dict) or (raw_dict != cfg)
    return cfg, changed


def load_app_config():
    raw_data = None
    file_exists = os.path.exists(CONFIG_FILE)
    if file_exists:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    raw_data = loaded
        except Exception:
            raw_data = None

    cfg, changed = reconcile_app_config(raw_data)
    if file_exists and changed:
        try:
            save_app_config(cfg)
        except OSError:
            pass
    return cfg


def hash_password(raw_password: str) -> str:
    """هش کردن یک‌طرفه و امن رمز عبور با الگوریتم SHA-256"""
    if not raw_password:
        return ""
    return hashlib.sha256(raw_password.encode("utf-8")).hexdigest()


def hash_database_password(raw_password: str, salt: bytes) -> str:
    """Derive secure PBKDF2-HMAC-SHA256 password hash for database authorization."""
    if not raw_password:
        return ""
    if not salt:
        salt = b""
    return hashlib.pbkdf2_hmac("sha256", raw_password.encode("utf-8"), salt, 100000).hex()


def receivable_balance(total_amount, paid_amount, settlement_status):
    """Only partially-settled or unsettled transactions can have a receivable."""
    status = str(settlement_status or "").strip().replace(" ", "")
    if status not in ("تسویهجزئی", "تسویه‌نشده", "تسویهنشده"):
        return 0
    return max(0, int(total_amount or 0) - int(paid_amount or 0))


def service_financial_breakdown(service_fee, paid_amount, settlement_status):
    """Return service discount/markup and receivable using the settlement state.

    Settled services classify the full difference as discount/markup and never
    create a receivable. Only explicitly partial or unsettled services may carry
    a receivable balance.
    """
    fee = int(service_fee or 0)
    paid = int(paid_amount or 0)
    status = str(settlement_status or "").strip().replace(" ", "")
    if status in ("تسویه‌شده", "تسویهشده"):
        return paid - fee, 0
    return 0, receivable_balance(fee, paid, settlement_status)

def save_app_config(cfg):
    """Write config atomically; preserve the last valid settings file."""
    temp_path = CONFIG_FILE + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, CONFIG_FILE)


class ManagedConnection(sqlite3.Connection):
    """Context manager for SQLite connections that commits/rollbacks and guarantees handle closure."""

    def __enter__(self):
        super().__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


class ManagedConnectionContext:
    """Connection proxy managing transactions on a cached connection without derivation overhead."""

    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        self._conn.__enter__()
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._conn.__exit__(exc_type, exc_val, exc_tb)

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._conn, name)


class DatabaseManager:
    def close(self):
        """Idempotent close hook for test harnesses and lifecycle management."""
        self._close_cached_conn()
        self._close_observer_conn()
        with getattr(self, "_conn_lock", threading.Lock()):
            for c in list(getattr(self, "_open_conns", [])):
                try:
                    c.close()
                except Exception:
                    pass
            if hasattr(self, "_open_conns"):
                self._open_conns.clear()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _close_cached_conn(self):
        conn = getattr(getattr(self, "_thread_local", None), "cached_conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._thread_local.cached_conn = None

    def _close_observer_conn(self):
        conn = getattr(self, "_observer_conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._observer_conn = None

    def set_read_only_mode(self, enabled: bool, reason: str = ""):
        """Enable or disable read-only grace-period write guard on this DatabaseManager."""
        self._read_only_mode = bool(enabled)
        self._read_only_reason = str(reason or "").strip()

    def is_read_only_mode(self) -> bool:
        return bool(getattr(self, "_read_only_mode", False))

    def _ensure_writable(self):
        if getattr(self, "_read_only_mode", False):
            raise ReadOnlyGraceError(
                getattr(self, "_read_only_reason", "")
                or "سامانه در دوره مهلت فقط خواندنی است و ثبت یا ویرایش داده جدید مجاز نیست."
            )

    @staticmethod
    def _check_row_version(conn, table: str, record_id: int, expected_row_version, entity_label: str):
        if expected_row_version is None:
            return None
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (int(record_id),)).fetchone()
        if row is None:
            raise ValueError(f"{entity_label} یافت نشد یا توسط کاربر دیگری حذف شده است.")
        actual_version = int(row["row_version"] if "row_version" in row.keys() else 1)
        if actual_version != int(expected_row_version):
            raise ConcurrencyConflictError(
                table,
                int(record_id),
                int(expected_row_version),
                actual_version,
                dict(row),
                f"اطلاعات «{entity_label}» هم‌زمان توسط کاربر یا سیستم دیگری تغییر کرده است.",
            )
        return row

    @staticmethod
    def _quote_key(key: str) -> str:
        escaped = str(key or "").replace("'", "''")
        return f"'{escaped}'"

    @staticmethod
    def is_database_file_encrypted(path: str) -> bool:
        if not path or not os.path.isfile(path):
            return False
        size = os.path.getsize(path)
        if size < 1024 or size % 512 != 0:
            return False
        try:
            with open(path, "rb") as f:
                header = f.read(16)
            if header == b"SQLite format 3\x00":
                return False
            conn = sqlite3.connect(path, timeout=5)
            try:
                conn.execute("SELECT count(*) FROM sqlite_master")
                return False
            except Exception:
                return True
            finally:
                conn.close()
        except Exception:
            return False

    def _verify_key_on_file(self, key: str) -> bool:
        if not os.path.isfile(self.db_path) or os.path.getsize(self.db_path) == 0:
            return True
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            conn.execute(f"PRAGMA key = {self._quote_key(key)}")
            conn.execute("SELECT count(*) FROM sqlite_master")
            return True
        except Exception:
            return False
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def __init__(self, db_path=None, password=None, network_mode=None, journal_mode=None):
        self._conn_lock = threading.Lock()
        self._thread_local = threading.local()
        self._open_conns = set()
        self._observer_conn = None
        self._last_data_version = None
        self._read_only_mode = False
        self._read_only_reason = ""
        self.cfg = load_app_config()
        self.db_path = os.path.abspath(db_path or self.cfg["db_path"])
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self.cfg["db_path"] = self.db_path
        self.cfg["backup_dir"] = os.path.dirname(self.db_path) or "."
        self._encryption_key = password

        env_jm = (os.environ.get("DAQIQ_SQLITE_JOURNAL_MODE") or "").strip().upper()
        req_jm = (str(journal_mode).strip().upper() if journal_mode else "") or env_jm
        detected_net = is_network_database_path(self.db_path)
        self.is_network_db = bool(network_mode) if network_mode is not None else detected_net
        self._requested_journal_mode = "DELETE" if (self.is_network_db or req_jm == "DELETE") else (req_jm or "")
        self._use_delete_journal = self._requested_journal_mode == "DELETE"

        if self.is_password_protected() and not self._encryption_key:
            if not self.auto_unlock_if_permitted():
                return

        self.init_db()
        self._normalize_application_config()
        save_app_config(self.cfg)

    def _configure_connection_pragmas(self, conn):
        conn.execute("PRAGMA busy_timeout = 15000")
        conn.execute("PRAGMA foreign_keys = ON")
        if getattr(self, "_use_delete_journal", False):
            conn.execute("PRAGMA synchronous = FULL")
            conn.execute("PRAGMA locking_mode = NORMAL")

    def get_connection(self):
        """Create a bounded-wait connection with referential integrity enabled."""
        if self.is_password_protected() and not self._encryption_key:
            raise PermissionError("پایگاه داده دارای رمز عبور است و قفل آن باز نشده است.")
        if self._encryption_key:
            conn = getattr(self._thread_local, "cached_conn", None)
            if conn is None:
                conn = sqlite3.connect(
                    self.db_path,
                    timeout=15.0,
                    isolation_level="DEFERRED",
                    check_same_thread=False,
                )
                conn.row_factory = sqlite3.Row
                conn.execute(f"PRAGMA key = {self._quote_key(self._encryption_key)}")
                self._configure_connection_pragmas(conn)
                self._thread_local.cached_conn = conn
                with self._conn_lock:
                    self._open_conns.add(conn)
            return ManagedConnectionContext(conn)

        conn = sqlite3.connect(
            self.db_path,
            timeout=15.0,
            isolation_level="DEFERRED",
            factory=ManagedConnection,
        )
        conn.row_factory = sqlite3.Row
        self._configure_connection_pragmas(conn)
        return conn

    def run_write_transaction(self, fn, *, check_writable: bool = True, max_retries: int = 8):
        """Execute ``fn(conn)`` inside an atomic BEGIN IMMEDIATE transaction with bounded backoff."""
        if check_writable:
            self._ensure_writable()
        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                with self.get_connection() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    result = fn(conn)
                    conn.commit()
                    return result
            except sqlite3.OperationalError as exc:
                msg = str(exc).lower()
                if ("locked" in msg or "busy" in msg) and attempt < max_retries:
                    last_exc = exc
                    base_delay = min(0.45, 0.03 * (1.7 ** attempt))
                    time.sleep(base_delay + random.uniform(0.005, 0.025))
                    continue
                raise
        raise last_exc

    def poll_external_data_version(self) -> tuple:
        """Return ``(data_version, changed_externally)`` using a dedicated persistent observer connection."""
        if self.is_password_protected() and not self._encryption_key:
            return (0, False)
        conn = getattr(self, "_observer_conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self.db_path,
                timeout=5.0,
                isolation_level="DEFERRED",
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            if self._encryption_key:
                conn.execute(f"PRAGMA key = {self._quote_key(self._encryption_key)}")
            conn.execute("PRAGMA busy_timeout = 5000")
            self._observer_conn = conn
            self._last_data_version = int(conn.execute("PRAGMA data_version").fetchone()[0])
            return (self._last_data_version, False)
        try:
            ver = int(conn.execute("PRAGMA data_version").fetchone()[0])
        except sqlite3.DatabaseError:
            self._close_observer_conn()
            return (0, False)
        changed = self._last_data_version is not None and ver != self._last_data_version
        self._last_data_version = ver
        return (ver, changed)

    def sync_database(self):
        """همگام‌سازی و اطمینان از ثبت کامل تراکنش‌های باز روی دیسک"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=15.0)
            if self._encryption_key:
                conn.execute(f"PRAGMA key = {self._quote_key(self._encryption_key)}")
            jm = str(conn.execute("PRAGMA journal_mode").fetchone()[0] or "").lower()
            if jm == "wal":
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            conn.commit()
            conn.close()
        except Exception:
            pass
        finally:
            self._close_cached_conn()
            self._close_observer_conn()

    def init_db(self):
        def _apply_journal_mode(conn):
            current_jm = str(conn.execute("PRAGMA journal_mode").fetchone()[0] or "").lower()
            if self.is_network_db or self._requested_journal_mode == "DELETE" or current_jm == "delete":
                self._use_delete_journal = True
                if current_jm != "delete":
                    conn.execute("PRAGMA journal_mode = DELETE")
                conn.execute("PRAGMA synchronous = FULL")
                conn.execute("PRAGMA locking_mode = NORMAL")
            elif current_jm != "wal":
                conn.execute("PRAGMA journal_mode = WAL")

        with self.get_connection() as conn:
            _apply_journal_mode(conn)
            current_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            existing_tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            if existing_tables and current_version != SCHEMA_VERSION:
                raise RuntimeError(
                    f"این پایگاه داده برای نسخه {APP_VERSION} ساخته نشده است. "
                    f"نسخه {APP_VERSION} به پایگاه داده تازه نیاز دارد و مهاجرت خودکار "
                    "از نسخه‌های قبلی پشتیبانی نمی‌شود."
                )
            cur = conn.cursor()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                ) WITHOUT ROWID
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS employees (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0),
                    role TEXT NOT NULL DEFAULT 'فروشنده',
                    phone TEXT DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    permissions TEXT DEFAULT 'دسترسی کامل',
                    password TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT DEFAULT NULL,
                    last_login_at TEXT DEFAULT NULL,
                    row_version INTEGER NOT NULL DEFAULT 1
                )
            """)

            cur.execute("""
                CREATE VIEW IF NOT EXISTS users AS
                SELECT id, name, role, phone, is_active, permissions, password, created_at, updated_at, last_login_at
                FROM employees;
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS access_level_data_scopes (
                    access_level_name TEXT PRIMARY KEY,
                    mode TEXT NOT NULL DEFAULT 'self'
                        CHECK (mode IN ('all', 'self', 'access_levels', 'users'))
                ) WITHOUT ROWID
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS access_level_scope_levels (
                    access_level_name TEXT NOT NULL,
                    selected_access_level_name TEXT NOT NULL,
                    PRIMARY KEY (access_level_name, selected_access_level_name),
                    FOREIGN KEY (access_level_name)
                        REFERENCES access_level_data_scopes(access_level_name)
                        ON DELETE CASCADE
                ) WITHOUT ROWID
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS access_level_scope_users (
                    access_level_name TEXT NOT NULL,
                    employee_id INTEGER NOT NULL,
                    PRIMARY KEY (access_level_name, employee_id),
                    FOREIGN KEY (access_level_name)
                        REFERENCES access_level_data_scopes(access_level_name)
                        ON DELETE CASCADE,
                    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
                ) WITHOUT ROWID
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS suppliers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE
                        CHECK (length(trim(name)) > 0),
                    phone TEXT DEFAULT '',
                    address TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    row_version INTEGER NOT NULL DEFAULT 1
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    phone TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    row_version INTEGER NOT NULL DEFAULT 1
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE CHECK (length(trim(code)) > 0),
                    serial_number TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
                    category TEXT NOT NULL CHECK (length(trim(category)) > 0),
                    sub_category TEXT DEFAULT '',
                    brand TEXT DEFAULT '',
                    model TEXT DEFAULT '',
                    specs_json TEXT DEFAULT '{}',
                    description TEXT DEFAULT '',
                    reorder_point INTEGER NOT NULL DEFAULT 1 CHECK (reorder_point >= 0),
                    default_profit_pct REAL NOT NULL DEFAULT 20.0
                        CHECK (default_profit_pct >= 0),
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    row_version INTEGER NOT NULL DEFAULT 1
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_code TEXT NOT NULL UNIQUE CHECK (length(trim(batch_code)) > 0),
                    product_id INTEGER NOT NULL,
                    serial_numbers TEXT DEFAULT '',
                    supplier_id INTEGER,
                    buyer_employee_id INTEGER,
                    invoice_number TEXT DEFAULT '',
                    purchase_date TEXT NOT NULL CHECK (length(trim(purchase_date)) > 0),
                    initial_qty INTEGER NOT NULL CHECK (initial_qty > 0),
                    sold_qty INTEGER NOT NULL DEFAULT 0 CHECK (sold_qty >= 0),
                    returned_qty INTEGER NOT NULL DEFAULT 0 CHECK (returned_qty >= 0),
                    remaining_qty INTEGER NOT NULL CHECK (remaining_qty >= 0),
                    unit_purchase_price INTEGER NOT NULL CHECK (unit_purchase_price >= 0),
                    extra_cost_total INTEGER NOT NULL DEFAULT 0 CHECK (extra_cost_total >= 0),
                    upgrade_cost_unit INTEGER NOT NULL DEFAULT 0 CHECK (upgrade_cost_unit >= 0),
                    unit_cost_price INTEGER NOT NULL CHECK (unit_cost_price >= 0),
                    suggested_sell_price INTEGER NOT NULL CHECK (suggested_sell_price >= 0),
                    profit_pct REAL NOT NULL DEFAULT 0,
                    paid_amount INTEGER NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
                    settlement_status TEXT NOT NULL DEFAULT 'تسویه‌شده',
                    colors_json TEXT NOT NULL DEFAULT '[]',
                    initial_specs TEXT DEFAULT '',
                    final_specs TEXT DEFAULT '',
                    supplier_name_snapshot TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    row_version INTEGER NOT NULL DEFAULT 1,
                    CONSTRAINT ck_batches_stock_balance CHECK (
                        sold_qty + returned_qty <= initial_qty
                        AND remaining_qty = initial_qty - sold_qty - returned_qty
                    ),
                    FOREIGN KEY(product_id) REFERENCES products(id),
                    FOREIGN KEY(supplier_id) REFERENCES suppliers(id),
                    FOREIGN KEY(buyer_employee_id) REFERENCES employees(id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS upgrades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_batch_id INTEGER NOT NULL,
                    part_batch_id INTEGER,
                    technician_id INTEGER,
                    target_qty INTEGER NOT NULL DEFAULT 1 CHECK (target_qty > 0),
                    part_qty_used INTEGER NOT NULL CHECK (part_qty_used >= 0),
                    stock_deducted_qty INTEGER NOT NULL DEFAULT 0 CHECK (stock_deducted_qty >= 0),
                    part_unit_cost INTEGER NOT NULL DEFAULT 0 CHECK (part_unit_cost >= 0),
                    labor_cost_unit INTEGER NOT NULL DEFAULT 0 CHECK (labor_cost_unit >= 0),
                    added_cost_unit INTEGER NOT NULL DEFAULT 0 CHECK (added_cost_unit >= 0),
                    upgrade_date TEXT NOT NULL,
                    serial_number TEXT DEFAULT '',
                    manual_part_description TEXT DEFAULT '',
                    old_specs TEXT DEFAULT '',
                    new_specs TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    row_version INTEGER NOT NULL DEFAULT 1,
                    CONSTRAINT ck_upgrades_distinct_batches CHECK (
                        part_batch_id IS NULL OR part_batch_id <> target_batch_id
                    ),
                    FOREIGN KEY(target_batch_id) REFERENCES batches(id),
                    FOREIGN KEY(part_batch_id) REFERENCES batches(id),
                    FOREIGN KEY(technician_id) REFERENCES employees(id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_number TEXT NOT NULL,
                    product_id INTEGER NOT NULL,
                    batch_id INTEGER NOT NULL,
                    serial_number TEXT DEFAULT '',
                    seller_employee_id INTEGER,
                    customer_name TEXT DEFAULT '',
                    customer_phone TEXT DEFAULT '',
                    qty INTEGER NOT NULL CHECK (qty > 0),
                    returned_qty INTEGER NOT NULL DEFAULT 0 CHECK (returned_qty >= 0 AND returned_qty <= qty),
                    suggested_unit_price INTEGER NOT NULL CHECK (suggested_unit_price >= 0),
                    actual_unit_price INTEGER NOT NULL CHECK (actual_unit_price >= 0),
                    unit_cost_price INTEGER NOT NULL CHECK (unit_cost_price >= 0),
                    unit_discount INTEGER NOT NULL DEFAULT 0 CHECK (unit_discount >= 0),
                    total_discount INTEGER NOT NULL DEFAULT 0 CHECK (total_discount >= 0),
                    price_Markup_unit INTEGER NOT NULL DEFAULT 0 CHECK (price_Markup_unit >= 0),
                    unit_profit INTEGER NOT NULL DEFAULT 0,
                    total_profit INTEGER NOT NULL DEFAULT 0,
                    total_amount INTEGER NOT NULL CHECK (total_amount >= 0),
                    paid_amount INTEGER NOT NULL CHECK (paid_amount >= 0),
                    settlement_status TEXT NOT NULL DEFAULT 'تسویه‌شده',
                    sale_datetime TEXT NOT NULL,
                    warranty_company TEXT DEFAULT '',
                    warranty_start TEXT DEFAULT '',
                    warranty_months INTEGER NOT NULL DEFAULT 0,
                    warranty_days INTEGER NOT NULL DEFAULT 0,
                    warranty_end TEXT DEFAULT '',
                    specifications TEXT DEFAULT '',
                    colors_json TEXT NOT NULL DEFAULT '[]',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    row_version INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(product_id) REFERENCES products(id),
                    FOREIGN KEY(batch_id) REFERENCES batches(id),
                    FOREIGN KEY(seller_employee_id) REFERENCES employees(id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS service_catalog (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    service_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    default_fee INTEGER NOT NULL CHECK (default_fee >= 0),
                    default_side_cost INTEGER NOT NULL DEFAULT 0 CHECK (default_side_cost >= 0),
                    description TEXT DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    row_version INTEGER NOT NULL DEFAULT 1
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS service_price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service_id INTEGER NOT NULL,
                    change_date TEXT NOT NULL,
                    old_fee INTEGER CHECK (old_fee IS NULL OR old_fee >= 0),
                    new_fee INTEGER CHECK (new_fee IS NULL OR new_fee >= 0),
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(service_id) REFERENCES service_catalog(id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS service_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_number TEXT NOT NULL,
                    service_id INTEGER,
                    seller_employee_id INTEGER,
                    technician_employee_id INTEGER,
                    service_type TEXT NOT NULL,
                    service_name TEXT NOT NULL,
                    customer_name TEXT DEFAULT '',
                    historical_tariff INTEGER NOT NULL CHECK (historical_tariff >= 0),
                    service_fee INTEGER NOT NULL CHECK (service_fee >= 0),
                    side_cost INTEGER NOT NULL DEFAULT 0 CHECK (side_cost >= 0),
                    paid_amount INTEGER NOT NULL CHECK (paid_amount >= 0),
                    net_profit INTEGER NOT NULL DEFAULT 0,
                    settlement_status TEXT NOT NULL DEFAULT 'تسویه‌شده',
                    service_datetime TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    row_version INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(service_id) REFERENCES service_catalog(id) ON DELETE SET NULL,
                    FOREIGN KEY(seller_employee_id) REFERENCES employees(id),
                    FOREIGN KEY(technician_employee_id) REFERENCES employees(id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ref_type TEXT NOT NULL,
                    ref_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL CHECK (amount >= 0),
                    payment_date TEXT NOT NULL,
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    row_version INTEGER NOT NULL DEFAULT 1
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_time TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                )
            """)

            # Backward-compatible additive upgrade for v4.9.8 databases lacking row_version
            if existing_tables:
                for rv_table in ROW_VERSION_TABLES:
                    if rv_table in existing_tables:
                        cols_existing = {
                            row["name"]
                            for row in conn.execute(f"PRAGMA table_info({rv_table})").fetchall()
                        }
                        if "row_version" not in cols_existing:
                            conn.execute(
                                f"ALTER TABLE {rv_table} ADD COLUMN row_version INTEGER NOT NULL DEFAULT 1"
                            )

            validate_schema_column_order(conn)

            # نام فروشگاه به هر پایگاه داده تعلق دارد؛ تنظیمات عمومی برنامه
            # در app_config.json نگهداری می‌شوند.
            default_settings = {
                "shop_name": str(self.cfg.get("last_store_name") or self.cfg.get("shop_name") or "فروشگاه من"),
                "app_version": APP_VERSION,
                "schema_version": str(SCHEMA_VERSION),
            }
            for k, v in default_settings.items():
                cur.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (k, v),
                )

            # Activity timestamps are ISO-like local datetimes with millisecond precision.
            # The audit columns are appended in one stable order on every operational table:
            # created_at, updated_at. Business dates (sale_datetime, purchase_date, etc.)
            # remain separate and are never changed by these triggers.
            activity_tables = (
                "products", "batches", "sales", "upgrades", "service_catalog",
                "service_records", "suppliers", "customers", "payments",
                "service_price_history", "audit_logs",
            )
            for table_name in activity_tables:
                conn.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_updated_at_insert")
                conn.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_updated_at_update")
                conn.execute(f"""
                    CREATE TRIGGER trg_{table_name}_updated_at_insert
                    AFTER INSERT ON {table_name}
                    FOR EACH ROW
                    BEGIN
                        UPDATE {table_name}
                        SET created_at = CASE
                                WHEN NEW.created_at IS NULL OR NEW.created_at=''
                                THEN strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')
                                ELSE NEW.created_at END,
                            updated_at = CASE
                                WHEN NEW.updated_at IS NULL OR NEW.updated_at=''
                                THEN strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')
                                ELSE NEW.updated_at END
                        WHERE id = NEW.id;
                    END
                """)
                rv_set_sql = (
                    ", row_version = CASE WHEN NEW.row_version = OLD.row_version "
                    "THEN OLD.row_version + 1 ELSE NEW.row_version END"
                    if table_name in ROW_VERSION_TABLES
                    else ""
                )
                conn.execute(f"""
                    CREATE TRIGGER trg_{table_name}_updated_at_update
                    AFTER UPDATE ON {table_name}
                    FOR EACH ROW
                    WHEN NEW.updated_at IS OLD.updated_at
                    BEGIN
                        UPDATE {table_name}
                        SET updated_at = CASE
                            WHEN julianday(OLD.updated_at) IS NOT NULL
                             AND strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime') <= OLD.updated_at
                            THEN strftime(
                                '%Y-%m-%d %H:%M:%f',
                                julianday(OLD.updated_at) + (2.0 / 86400000.0)
                            )
                            ELSE strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')
                        END{rv_set_sql}
                        WHERE id = NEW.id;
                    END
                """)

            # User lifecycle audit triggers:
            # created_at: immutable timestamp initialized on insert.
            # updated_at: NULL on insert, updated ONLY when core user data changes.
            # last_login_at: NULL on insert, updated without affecting updated_at or created_at.
            conn.execute("DROP TRIGGER IF EXISTS trg_employees_updated_at_insert")
            conn.execute("DROP TRIGGER IF EXISTS trg_employees_updated_at_update")
            conn.execute("""
                CREATE TRIGGER trg_employees_updated_at_insert
                AFTER INSERT ON employees
                FOR EACH ROW
                BEGIN
                    UPDATE employees
                    SET created_at = CASE
                            WHEN NEW.created_at IS NULL OR NEW.created_at=''
                            THEN strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')
                            ELSE NEW.created_at END,
                        updated_at = NEW.updated_at,
                        last_login_at = NEW.last_login_at
                    WHERE id = NEW.id;
                END
            """)
            conn.execute("""
                CREATE TRIGGER trg_employees_updated_at_update
                AFTER UPDATE ON employees
                FOR EACH ROW
                WHEN (NEW.name <> OLD.name
                   OR NEW.role <> OLD.role
                   OR COALESCE(NEW.phone, '') <> COALESCE(OLD.phone, '')
                   OR NEW.is_active <> OLD.is_active
                   OR COALESCE(NEW.permissions, '') <> COALESCE(OLD.permissions, '')
                   OR COALESCE(NEW.password, '') <> COALESCE(OLD.password, ''))
                  AND (NEW.updated_at IS OLD.updated_at)
                BEGIN
                    UPDATE employees
                    SET updated_at = CASE
                        WHEN OLD.updated_at IS NOT NULL
                         AND julianday(OLD.updated_at) IS NOT NULL
                         AND strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime') <= OLD.updated_at
                        THEN strftime(
                            '%Y-%m-%d %H:%M:%f',
                            julianday(OLD.updated_at) + (2.0 / 86400000.0)
                        )
                        ELSE strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')
                    END,
                    row_version = CASE
                        WHEN NEW.row_version = OLD.row_version THEN OLD.row_version + 1
                        ELSE NEW.row_version
                    END
                    WHERE id = NEW.id;
                END
            """)

            # Index the same COALESCE expression used by the default activity sort,
            # followed by the stable primary-key tie-breaker.
            for table_name in (
                "products", "batches", "sales", "upgrades", "service_catalog",
                "service_records", "suppliers", "employees", "customers", "payments",
            ):
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table_name}_activity "
                    f"ON {table_name}(COALESCE(updated_at, created_at) DESC, id DESC)"
                )
            for index_sql in (
                "CREATE INDEX IF NOT EXISTS idx_products_taxonomy ON products(category, sub_category, updated_at DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_products_serial ON products(serial_number)",
                "CREATE INDEX IF NOT EXISTS idx_batches_serial ON batches(serial_numbers)",
                "CREATE INDEX IF NOT EXISTS idx_batches_code ON batches(batch_code)",
                "CREATE INDEX IF NOT EXISTS idx_sales_serial ON sales(serial_number)",
                "CREATE INDEX IF NOT EXISTS idx_batches_product_stock ON batches(product_id, remaining_qty)",
                "CREATE INDEX IF NOT EXISTS idx_batches_product_activity ON batches(product_id, updated_at DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_batches_supplier_activity ON batches(supplier_id, updated_at DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_batches_buyer_activity ON batches(buyer_employee_id, updated_at DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_sales_batch_activity ON sales(batch_id, updated_at DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_sales_product_activity ON sales(product_id, updated_at DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_sales_seller_activity ON sales(seller_employee_id, updated_at DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_upgrades_target_activity ON upgrades(target_batch_id, updated_at DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_upgrades_part_activity ON upgrades(part_batch_id, updated_at DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_upgrades_technician_activity ON upgrades(technician_id, updated_at DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_service_records_service_activity ON service_records(service_id, updated_at DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_services_seller_activity ON service_records(seller_employee_id, updated_at DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_services_technician_activity ON service_records(technician_employee_id, updated_at DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_service_history_service_date ON service_price_history(service_id, change_date DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_payments_reference ON payments(ref_type, ref_id, payment_date DESC)",
                "CREATE INDEX IF NOT EXISTS idx_employees_permission_activity ON employees(permissions, updated_at DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_access_scope_users_employee ON access_level_scope_users(employee_id, access_level_name)",
                "CREATE INDEX IF NOT EXISTS idx_sales_customer_phone ON sales(customer_phone)",
                "CREATE INDEX IF NOT EXISTS idx_sales_invoice_number ON sales(invoice_number)",
                "CREATE INDEX IF NOT EXISTS idx_service_records_invoice_number ON service_records(invoice_number)",
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_action_time ON audit_logs(action_time DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_products_active_cat ON products(is_active, category, sub_category, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_products_name ON products(name)",
                "CREATE INDEX IF NOT EXISTS idx_batches_purchase_date ON batches(purchase_date DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_batches_settlement ON batches(settlement_status, paid_amount)",
                "CREATE INDEX IF NOT EXISTS idx_sales_sale_datetime ON sales(sale_datetime DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_sales_settlement ON sales(settlement_status, paid_amount)",
                "CREATE INDEX IF NOT EXISTS idx_services_service_datetime ON service_records(service_datetime DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_upgrades_upgrade_date ON upgrades(upgrade_date DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone)",
            ):
                conn.execute(index_sql)

            # Seed default taxonomy if new database has no taxonomy configuration yet
            cat_row = cur.execute("SELECT value FROM settings WHERE key='product_catalog_config'").fetchone()
            if not cat_row:
                seed_data = load_default_taxonomy_from_seed()
                if seed_data:
                    cur.execute(
                        "INSERT INTO settings (key, value) VALUES (?, ?)",
                        ("product_catalog_config", json.dumps(seed_data, ensure_ascii=False)),
                    )
                else:
                    cur.execute(
                        "INSERT INTO settings (key, value) VALUES (?, ?)",
                        ("product_catalog_config", json.dumps({
                            "categories": [],
                            "subcategories": {},
                            "attributes": {},
                            "colors": [],
                            "service_types": []
                        }, ensure_ascii=False)),
                    )

            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

            conn.commit()

    def _normalize_application_config(self):
        """Normalize current application settings without database migration."""
        reconciled, _ = reconcile_app_config(self.cfg)
        self.cfg.clear()
        self.cfg.update(reconciled)
        self.cfg["app_version"] = get_live_app_version()
        self.cfg["backup_dir"] = os.path.dirname(os.path.abspath(self.db_path)) or "."
        self.cfg["db_path"] = os.path.abspath(self.db_path)
        try:
            db_cal = self.get_setting("calendar_format", "")
            if db_cal:
                self.cfg["calendar_type"] = datetime_format.CALENDAR_LOOKUP.get(
                    str(db_cal).strip().lower(), self.cfg["calendar_type"]
                )
            db_tf = self.get_setting("time_format", "")
            if db_tf:
                self.cfg["time_format"] = datetime_format.TIME_FORMAT_LOOKUP.get(
                    str(db_tf).strip().lower(), self.cfg["time_format"]
                )
            db_shop = self.get_setting("shop_name", "")
            if db_shop:
                self.cfg["last_store_name"] = str(db_shop).strip()
        except Exception:
            pass

    def get_setting(self, key, default=""):
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key, value, conn=None):
        self._ensure_writable()
        if conn is not None:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, str(value)),
            )
            return

        def _tx(c):
            c.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, str(value)),
            )

        self.run_write_transaction(_tx, check_writable=False)

    def set_settings_batch(self, mapping: dict, conn=None):
        """Batch multiple settings in a single connection transaction."""
        if not mapping:
            return
        self._ensure_writable()
        items = [(str(k), str(v)) for k, v in mapping.items()]
        if conn is not None:
            conn.executemany(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                items,
            )
            return

        def _tx(c):
            c.executemany(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                items,
            )

        self.run_write_transaction(_tx, check_writable=False)

    def get_product_catalog_config(self):
        """Return a normalized, per-database product taxonomy and specification catalog."""
        raw = self.get_setting("product_catalog_config", "{}")
        try:
            config = json.loads(raw or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            config = {}
        if not isinstance(config, dict):
            config = {}

        raw_categories = config.get("categories")
        categories = raw_categories if isinstance(raw_categories, list) else []
        raw_subcategories = config.get("subcategories")
        raw_attributes = config.get("attributes")
        raw_colors = config.get("colors")
        raw_service_types = config.get("service_types")
        raw_removed_defaults = config.get("removed_default_subcategories")

        removed_default_subcategories = {}
        if isinstance(raw_removed_defaults, dict):
            for category, values in raw_removed_defaults.items():
                if not isinstance(values, list):
                    continue
                removed_default_subcategories[str(category)] = list(dict.fromkeys(
                    str(value).strip() for value in values
                    if value is not None and str(value).strip()
                ))

        subcategories = {}
        if isinstance(raw_subcategories, dict):
            for category, values in raw_subcategories.items():
                if not isinstance(values, list):
                    continue
                subcategories[str(category)] = list(dict.fromkeys(
                    str(value).strip() for value in values if value is not None and str(value).strip()
                ))

        attributes = {}
        if isinstance(raw_attributes, dict):
            for category, items in raw_attributes.items():
                if not isinstance(items, list):
                    continue
                normalized_items = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name", "") or "").strip()
                    if not name:
                        continue
                    values = item.get("values", [])
                    if not isinstance(values, list):
                        values = []
                    normalized_item = {
                        "name": name,
                        "values": list(dict.fromkeys(
                            str(value).strip() for value in values
                            if value is not None and str(value).strip()
                        )),
                        "subcategory": str(item.get("subcategory", "") or "").strip(),
                    }
                    display_name = str(item.get("display_name", "") or item.get("label", "") or "").strip()
                    if display_name:
                        normalized_item["display_name"] = display_name
                        normalized_item["label"] = display_name
                    elif str(item.get("label", "") or "").strip():
                        normalized_item["label"] = str(item.get("label", "") or "").strip()
                    normalized_items.append(normalized_item)
                attributes[str(category)] = normalized_items

        colors = raw_colors if isinstance(raw_colors, list) else []
        result = {
            "categories": list(dict.fromkeys(
                str(value).strip() for value in categories
                if value is not None and str(value).strip()
            )),
            "subcategories": subcategories,
            "attributes": attributes,
            "colors": list(dict.fromkeys(
                str(value).strip() for value in colors
                if value is not None and str(value).strip()
            )),
            "service_types": list(dict.fromkeys(
                str(value).strip() for value in (
                    raw_service_types if isinstance(raw_service_types, list)
                    else []
                )
                if value is not None and str(value).strip()
            )),
        }
        if isinstance(raw_removed_defaults, dict):
            result["removed_default_subcategories"] = removed_default_subcategories
        return result

    def save_product_catalog_config(self, config, conn=None):
        """Validate and persist product taxonomy in the active database."""
        if not isinstance(config, dict):
            raise ValueError("ساختار شخصی‌سازی کالا معتبر نیست.")

        categories = config.get("categories", [])
        subcategories = config.get("subcategories", {})
        attributes = config.get("attributes", {})
        colors = config.get("colors", [])
        service_types = config.get("service_types", [])
        removed_default_subcategories = config.get("removed_default_subcategories", {})
        if not isinstance(categories, list) or not isinstance(subcategories, dict):
            raise ValueError("ساختار دسته‌بندی یا زیرمجموعه‌ها معتبر نیست.")
        if not isinstance(attributes, dict) or not isinstance(colors, list):
            raise ValueError("ساختار مشخصات فنی یا رنگ‌ها معتبر نیست.")
        if not isinstance(service_types, list):
            raise ValueError("فهرست نوع خدمات معتبر نیست.")
        if not isinstance(removed_default_subcategories, dict):
            raise ValueError("فهرست زیرمجموعه‌های غیرفعال معتبر نیست.")

        def _norm_cat_lbl(val):
            t = "" if val is None else str(val)
            t = t.replace("\u064a", "\u06cc").replace("\u0643", "\u06a9")
            t = t.replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
            return re.sub(r"\s+", "", t).casefold()

        other_key = _norm_cat_lbl("سایر موارد")

        clean_categories = list(dict.fromkeys(
            str(value).strip() for value in categories
            if value is not None and str(value).strip()
        ))
        other_cats = [c for c in clean_categories if _norm_cat_lbl(c) == other_key]
        clean_categories = [c for c in clean_categories if _norm_cat_lbl(c) != other_key]
        if other_cats:
            clean_categories.append(other_cats[0])

        clean_subcategories = {}
        for category, values in subcategories.items():
            if not isinstance(values, list):
                raise ValueError(f"فهرست زیرمجموعه‌های «{category}» معتبر نیست.")
            raw_subs = list(dict.fromkeys(
                str(value).strip() for value in values
                if value is not None and str(value).strip()
            ))
            other_subs = [s for s in raw_subs if _norm_cat_lbl(s) == other_key or "سایرموارد" in _norm_cat_lbl(s)]
            clean_subs = [s for s in raw_subs if _norm_cat_lbl(s) != other_key and "سایرموارد" not in _norm_cat_lbl(s)]
            if other_subs:
                clean_subs.append(other_subs[0])
            clean_subcategories[str(category)] = clean_subs

        clean_removed_defaults = {}
        for category, values in removed_default_subcategories.items():
            if not isinstance(values, list):
                raise ValueError(f"فهرست زیرمجموعه‌های غیرفعال «{category}» معتبر نیست.")
            clean_removed_defaults[str(category)] = list(dict.fromkeys(
                str(value).strip() for value in values
                if value is not None and str(value).strip()
            ))

        clean_attributes = {}
        for category, items in attributes.items():
            if not isinstance(items, list):
                raise ValueError(f"فهرست مشخصات «{category}» معتبر نیست.")
            clean_items = []
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError(f"یکی از مشخصات «{category}» ساختار معتبری ندارد.")
                name = str(item.get("name", "") or "").strip()
                if not name:
                    continue
                values = item.get("values", [])
                if not isinstance(values, list):
                    raise ValueError(f"مقادیر مشخصهٔ «{name}» باید به‌صورت فهرست باشند.")
                clean_item = {
                    "name": name,
                    "values": list(dict.fromkeys(
                        str(value).strip() for value in values
                        if value is not None and str(value).strip()
                    )),
                    "subcategory": str(item.get("subcategory", "") or "").strip(),
                }
                label = str(item.get("label", "") or "").strip()
                if label:
                    clean_item["label"] = label
                clean_items.append(clean_item)
            clean_attributes[str(category)] = clean_items

        clean = {
            "categories": clean_categories,
            "subcategories": clean_subcategories,
            "removed_default_subcategories": clean_removed_defaults,
            "attributes": clean_attributes,
            "colors": list(dict.fromkeys(
                str(value).strip() for value in colors
                if value is not None and str(value).strip()
            )),
            "service_types": list(dict.fromkeys(
                str(value).strip() for value in service_types
                if value is not None and str(value).strip()
            )),
        }
        serialized = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
        self._ensure_writable()
        if conn is not None:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("product_catalog_config", serialized),
            )
            return
        self.set_setting("product_catalog_config", serialized)

    def _active_datetime_prefs(self, conn=None):
        """Return active (calendar_format, time_format) from settings without opening nested connections."""
        cal = "jalali"
        tf = "24h"
        try:
            if conn is not None:
                rows = conn.execute(
                    "SELECT key, value FROM settings WHERE key IN ('calendar_format', 'time_format')"
                ).fetchall()
                for row in rows:
                    if row["key"] == "calendar_format" and row["value"]:
                        cal = row["value"]
                    elif row["key"] == "time_format" and row["value"]:
                        tf = row["value"]
            else:
                cal = self.get_setting("calendar_format", "jalali") or "jalali"
                tf = self.get_setting("time_format", "24h") or "24h"
        except Exception:
            pass
        return cal, tf

    def log_audit(self, conn, action_type, details):
        cal, tf = self._active_datetime_prefs(conn=conn)
        now_str = datetime_format.get_now_datetime(cal, tf)
        conn.execute(
            "INSERT INTO audit_logs (action_time, action_type, details) VALUES (?, ?, ?)",
            (now_str, action_type, details),
        )

    def generate_next_code(
        self, table, column, prefix, start_num=1001, *, conn=None
    ):
        """Generate a code, optionally inside the caller's serialized write transaction."""
        allowed_columns = {
            "products": {"code"},
            "batches": {"batch_code"},
            "sales": {"invoice_number"},
            "service_catalog": {"code"},
            "service_records": {"invoice_number"},
        }
        if column not in allowed_columns.get(table, set()):
            raise ValueError("جدول یا ستون تولید کد معتبر نیست.")

        def query_next(connection):
            rows = connection.execute(
                f"SELECT {column} FROM {table} WHERE {column} LIKE ?",
                (f"{prefix}%",),
            ).fetchall()
            max_num = int(start_num) - 1
            for row in rows:
                value = str(row[0] or "")[len(prefix):]
                if value.isdigit():
                    max_num = max(max_num, int(value))
            return f"{prefix}{max_num + 1}"

        if conn is not None:
            return query_next(conn)
        with self.get_connection() as connection:
            return query_next(connection)

    @staticmethod
    def build_product_title(category, sub_category, brand, model):
        """تولید خودکار عنوان کالا از ترکیب زیرمجموعه/دسته‌بندی + برند + مدل (بند ۱)"""
        base = (
            sub_category.strip()
            if sub_category and sub_category.strip() not in ("", "عمومی", "سایر موارد")
            else category.strip()
        )
        parts = [p.strip() for p in (base, brand, model) if p and p.strip()]
        return " ".join(parts) if parts else "کالای عمومی"

    # --- مدیریت کالاها ---
    def add_product(
        self,
        code,
        name,
        category,
        sub_category,
        brand,
        model,
        specs_dict,
        description,
        reorder_point=1,
        default_profit_pct=20.0,
        serial_number="",
    ):
        auto_name = (
            name.strip()
            if name and name.strip()
            else self.build_product_title(category, sub_category, brand, model)
        )
        norm_specs = {}
        if isinstance(specs_dict, dict):
            for sk, sv in specs_dict.items():
                if sk in ("Specs", "specs") or str(sk).strip() == "مشخصات":
                    norm_specs["Specs"] = sv
                else:
                    norm_specs[sk] = sv
        elif specs_dict:
            norm_specs = specs_dict
        specs_dict = norm_specs

        def _tx(conn):
            nonlocal code
            if not code:
                code = self.generate_next_code("products", "code", "P-", 1001, conn=conn)
            conn.execute(
                """
                INSERT INTO products (code, name, category, sub_category, brand, model, specs_json, description, reorder_point, default_profit_pct, serial_number)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    code,
                    auto_name,
                    category,
                    sub_category,
                    brand,
                    model,
                    json.dumps(specs_dict, ensure_ascii=False),
                    description,
                    int(reorder_point),
                    float(default_profit_pct),
                    str(serial_number or "").strip(),
                ),
            )
            self.log_audit(conn, "ثبت کالا", f"کد کالا: {code} - {auto_name}")
            return code

        return self.run_write_transaction(_tx)

    def update_product(
        self,
        prod_id,
        code,
        name,
        category,
        sub_category,
        brand,
        model,
        specs_dict,
        description,
        reorder_point,
        default_profit_pct,
        serial_number="",
        expected_row_version=None,
    ):
        auto_name = (
            name.strip()
            if name and name.strip()
            else self.build_product_title(category, sub_category, brand, model)
        )
        norm_specs = {}
        if isinstance(specs_dict, dict):
            for sk, sv in specs_dict.items():
                if sk in ("Specs", "specs") or str(sk).strip() == "مشخصات":
                    norm_specs["Specs"] = sv
                else:
                    norm_specs[sk] = sv
        elif specs_dict:
            norm_specs = specs_dict
        specs_dict = norm_specs

        def _tx(conn):
            self._check_row_version(conn, "products", prod_id, expected_row_version, "کالا")
            conn.execute(
                """
                UPDATE products SET code=?, name=?, category=?, sub_category=?, brand=?, model=?,
                specs_json=?, description=?, reorder_point=?, default_profit_pct=?, serial_number=?
                WHERE id=?
            """,
                (
                    code,
                    auto_name,
                    category,
                    sub_category,
                    brand,
                    model,
                    json.dumps(specs_dict, ensure_ascii=False),
                    description,
                    int(reorder_point),
                    float(default_profit_pct),
                    str(serial_number or "").strip(),
                    prod_id,
                ),
            )
            self.log_audit(conn, "ویرایش کالا", f"کد کالا: {code} - {auto_name}")

        self.run_write_transaction(_tx)

    def lookup_by_serial_or_barcode(self, query_string):
        """Lookup product and batch information matching a serial number, barcode, or cargo code.
        
        Optimized for barcode scanner (Keyboard Wedge) and manual search:
        Checks batches (batch_code, serial_numbers) and products (serial_number, code).
        Returns a dict with 'product', 'batches', and 'matched_batch'.
        """
        query = str(query_string or "").strip()
        if not query:
            return {"product": None, "batches": [], "matched_batch": None}

        with self.get_connection() as conn:
            # 1. Search batches by batch_code or exact/contained serial_numbers
            batch_row = conn.execute(
                """
                SELECT b.*, p.id AS p_id, p.code AS p_code, p.name AS p_name,
                       p.category AS p_category, p.sub_category AS p_sub_category,
                       p.brand AS p_brand, p.model AS p_model, p.specs_json AS p_specs_json,
                       p.description AS p_description, p.serial_number AS p_serial_number
                FROM batches b
                JOIN products p ON b.product_id = p.id
                WHERE b.batch_code = ? OR b.serial_numbers = ? OR b.serial_numbers LIKE ?
                ORDER BY b.remaining_qty > 0 DESC, b.updated_at DESC
                LIMIT 1
                """,
                (query, query, f"%{query}%"),
            ).fetchone()

            matched_batch = None
            product = None
            if batch_row:
                matched_batch = dict(batch_row)
                product = {
                    "id": batch_row["p_id"],
                    "code": batch_row["p_code"],
                    "name": batch_row["p_name"],
                    "category": batch_row["p_category"],
                    "sub_category": batch_row["p_sub_category"],
                    "brand": batch_row["p_brand"],
                    "model": batch_row["p_model"],
                    "specs_json": batch_row["p_specs_json"],
                    "description": batch_row["p_description"],
                    "serial_number": batch_row["p_serial_number"],
                }

            # 2. If no batch match, search products directly by serial_number or code
            if not product:
                prod_row = conn.execute(
                    "SELECT * FROM products WHERE serial_number = ? OR code = ?",
                    (query, query),
                ).fetchone()
                if prod_row:
                    product = dict(prod_row)

            # 3. If product is found, fetch available active batches with remaining stock
            available_batches = []
            if product:
                rows = conn.execute(
                    """
                    SELECT b.*, p.code AS p_code, p.name AS p_name, p.category, p.sub_category,
                           p.brand, p.model, p.specs_json AS product_specs_json,
                           p.description AS product_description
                    FROM batches b
                    JOIN products p ON b.product_id = p.id
                    WHERE b.product_id = ? AND b.remaining_qty > 0
                    ORDER BY b.updated_at DESC, b.id DESC
                    """,
                    (product["id"],),
                ).fetchall()
                available_batches = [dict(r) for r in rows]

            return {
                "product": product,
                "batches": available_batches,
                "matched_batch": matched_batch,
            }

    def _delete_linked_upgrades(self, conn, batch_ids=None, technician_id=None):
        batch_ids = list(batch_ids or [])
        clauses = []
        params = []
        if batch_ids:
            marks = ",".join("?" for _ in batch_ids)
            clauses.extend([f"target_batch_id IN ({marks})", f"part_batch_id IN ({marks})"])
            params.extend(batch_ids + batch_ids)
        if technician_id is not None:
            clauses.append("technician_id=?")
            params.append(technician_id)
        if not clauses:
            return
        rows = conn.execute(
            """SELECT id, target_batch_id, part_batch_id, technician_id, target_qty,
            part_qty_used, stock_deducted_qty, part_unit_cost, labor_cost_unit,
            added_cost_unit, upgrade_date, serial_number, manual_part_description,
            old_specs, new_specs, notes, created_at, updated_at FROM upgrades WHERE """ + " OR ".join(clauses) + " ORDER BY updated_at DESC, id DESC",
            params,
        ).fetchall()
        removed_ids = set(batch_ids)
        for upgrade in rows:
            stock_deducted = int(upgrade["stock_deducted_qty"] or 0)
            if (
                upgrade["part_batch_id"] not in removed_ids
                and stock_deducted > 0
            ):
                conn.execute(
                    """UPDATE batches SET sold_qty=MAX(0,sold_qty-?),
                       remaining_qty=remaining_qty+? WHERE id=?""",
                    (stock_deducted, stock_deducted, upgrade["part_batch_id"]),
                )
            if upgrade["target_batch_id"] not in removed_ids:
                target = conn.execute(
                    """SELECT id, batch_code, product_id, supplier_id, buyer_employee_id, invoice_number,
            purchase_date, initial_qty, sold_qty, returned_qty, remaining_qty,
            unit_purchase_price, extra_cost_total, upgrade_cost_unit, unit_cost_price,
            suggested_sell_price, profit_pct, paid_amount, settlement_status,
            serial_numbers, colors_json, initial_specs, final_specs,
            supplier_name_snapshot, notes, created_at, updated_at FROM batches WHERE id=?""", (upgrade["target_batch_id"],)
                ).fetchone()
                if target:
                    added = int(upgrade["added_cost_unit"] or 0)
                    deducted = round_percentage_amount(added, target["profit_pct"] or 0)
                    conn.execute(
                        """UPDATE batches SET upgrade_cost_unit=MAX(0,upgrade_cost_unit-?),
                           unit_cost_price=MAX(0,unit_cost_price-?),
                           suggested_sell_price=MAX(0,suggested_sell_price-?), final_specs=?
                           WHERE id=?""",
                        (added, added, deducted, upgrade["old_specs"], upgrade["target_batch_id"]),
                    )
            conn.execute("DELETE FROM upgrades WHERE id=?", (upgrade["id"],))

    def _delete_linked_sales(self, conn, batch_ids=None, seller_id=None, product_id=None):
        batch_ids = list(batch_ids or [])
        clauses = []
        params = []
        if batch_ids:
            clauses.append("batch_id IN (" + ",".join("?" for _ in batch_ids) + ")")
            params.extend(batch_ids)
        if seller_id is not None:
            clauses.append("seller_employee_id=?")
            params.append(seller_id)
        if product_id is not None:
            clauses.append("product_id=?")
            params.append(product_id)
        if not clauses:
            return
        rows = conn.execute(
            "SELECT id,batch_id,qty FROM sales WHERE " + " OR ".join(clauses) + " ORDER BY updated_at DESC, id DESC",
            params,
        ).fetchall()
        removed_batches = set(batch_ids)
        for sale in rows:
            if sale["batch_id"] not in removed_batches:
                conn.execute(
                    """UPDATE batches SET sold_qty=MAX(0,sold_qty-?),
                       remaining_qty=remaining_qty+? WHERE id=?""",
                    (sale["qty"], sale["qty"], sale["batch_id"]),
                )
            conn.execute("DELETE FROM payments WHERE ref_type='sale' AND ref_id=?", (sale["id"],))
            conn.execute("DELETE FROM sales WHERE id=?", (sale["id"],))

    def _hard_delete_batches(self, conn, batch_ids):
        batch_ids = list(dict.fromkeys(int(value) for value in batch_ids))
        if not batch_ids:
            return
        self._delete_linked_upgrades(conn, batch_ids=batch_ids)
        self._delete_linked_sales(conn, batch_ids=batch_ids)
        marks = ",".join("?" for _ in batch_ids)
        conn.execute(
            f"DELETE FROM payments WHERE ref_type='batch' AND ref_id IN ({marks})",
            batch_ids,
        )
        conn.execute(f"DELETE FROM batches WHERE id IN ({marks})", batch_ids)

    def delete_product(self, prod_id, expected_row_version=None):
        """Hard-delete product history and dependent batches transactionally."""
        def _tx(conn):
            self._check_row_version(conn, "products", prod_id, expected_row_version, "کالا")
            batch_rows = conn.execute(
                "SELECT id FROM batches WHERE product_id=?", (prod_id,)
            ).fetchall()
            batch_ids = [int(row["id"]) for row in batch_rows]
            self._hard_delete_batches(conn, batch_ids)
            # Also remove any orphaned sale records created by older versions.
            self._delete_linked_sales(conn, product_id=prod_id)
            conn.execute("DELETE FROM products WHERE id=?", (prod_id,))
            self.log_audit(conn, "حذف کامل کالا", f"شناسه کالا: {prod_id}")

        self.run_write_transaction(_tx)

    def add_supplier(self, name, phone, address, notes=""):
        def _tx(conn):
            conn.execute(
                "INSERT INTO suppliers (name, phone, address, notes) VALUES (?, ?, ?, ?)",
                (name.strip(), phone.strip(), address.strip(), notes.strip()),
            )

        self.run_write_transaction(_tx)

    def update_supplier(self, sup_id, name, phone, address, notes="", expected_row_version=None):
        def _tx(conn):
            self._check_row_version(conn, "suppliers", sup_id, expected_row_version, "تأمین‌کننده")
            conn.execute(
                "UPDATE suppliers SET name=?, phone=?, address=?, notes=? WHERE id=?",
                (name.strip(), phone.strip(), address.strip(), notes.strip(), sup_id),
            )

        self.run_write_transaction(_tx)

    def delete_supplier(self, sup_id, delete_related_data=False):
        """Remove a supplier while optionally retaining its purchase records and historical name."""
        def _tx(conn):
            supplier = conn.execute(
                "SELECT name FROM suppliers WHERE id=?", (sup_id,)
            ).fetchone()
            if not supplier:
                return
            batch_rows = conn.execute(
                "SELECT id FROM batches WHERE supplier_id=?", (sup_id,)
            ).fetchall()
            batch_ids = [int(row["id"]) for row in batch_rows]
            if delete_related_data:
                self._hard_delete_batches(conn, batch_ids)
            else:
                conn.execute(
                    """UPDATE batches
                       SET supplier_name_snapshot=?, supplier_id=NULL
                       WHERE supplier_id=?""",
                    (supplier["name"], sup_id),
                )
            conn.execute("DELETE FROM suppliers WHERE id=?", (sup_id,))
            self.log_audit(
                conn, "حذف تأمین‌کننده",
                f"شناسه: {sup_id} | حذف داده‌های وابسته: {'بله' if delete_related_data else 'خیر'}"
            )

        self.run_write_transaction(_tx)

    def add_employee(self, name: str, role: str, phone: str = "", password: str = "", permissions: str = "", is_active: int = 1) -> int:
        """Insert a new employee record and return its row ID."""
        def _tx(conn):
            cur = conn.execute(
                """
                INSERT INTO employees (name, role, phone, password, permissions, is_active)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name.strip(), role.strip(), phone.strip(), password, permissions.strip(), int(is_active)),
            )
            emp_id = cur.lastrowid
            self.log_audit(conn, "ثبت کاربر جدید", f"شناسه: {emp_id} | نام: {name} | نقش: {role}")
            return emp_id

        return self.run_write_transaction(_tx)

    def record_employee_login(self, employee_id: int, timestamp: str = None) -> None:
        """Record employee/user login timestamp without touching created_at or updated_at."""
        if not employee_id:
            return
        now_ts = timestamp or time.strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE employees SET last_login_at = ? WHERE id = ?",
                (now_ts, int(employee_id)),
            )
            conn.commit()

    record_user_login = record_employee_login
    add_user = add_employee

    def delete_employee_custom(self, emp_id: int, delete_related_data: bool = False):
        """Delete an employee; optionally remove all linked operations and reverse inventory effects."""
        def _tx(conn):
            if delete_related_data:
                owned_batches = conn.execute(
                    "SELECT id FROM batches WHERE buyer_employee_id=?", (emp_id,)
                ).fetchall()
                batch_ids = [int(row["id"]) for row in owned_batches]
                self._hard_delete_batches(conn, batch_ids)
                # Remove this employee's sales made from batches owned by someone else.
                self._delete_linked_sales(conn, seller_id=emp_id)
                # Also remove upgrades performed on batches that remain in inventory.
                self._delete_linked_upgrades(conn, technician_id=emp_id)
                conn.execute(
                    "DELETE FROM service_records WHERE seller_employee_id=? OR technician_employee_id=?",
                    (emp_id, emp_id),
                )
            else:
                conn.execute(
                    "UPDATE batches SET buyer_employee_id=NULL WHERE buyer_employee_id=?",
                    (emp_id,),
                )
                conn.execute(
                    "UPDATE sales SET seller_employee_id=NULL WHERE seller_employee_id=?",
                    (emp_id,),
                )
                conn.execute(
                    """UPDATE service_records
                       SET seller_employee_id=NULL, technician_employee_id=NULL
                       WHERE seller_employee_id=? OR technician_employee_id=?""",
                    (emp_id, emp_id),
                )
                conn.execute(
                    "UPDATE upgrades SET technician_id=NULL WHERE technician_id=?",
                    (emp_id,),
                )
            conn.execute("DELETE FROM employees WHERE id=?", (emp_id,))
            self.log_audit(
                conn, "حذف کاربر",
                f"شناسه: {emp_id} | حذف داده‌های وابسته: {'بله' if delete_related_data else 'خیر'}"
            )

        self.run_write_transaction(_tx)


    def get_or_create_supplier(self, supplier_name: str, *, conn=None):
        """Resolve a supplier, optionally participating in the caller's transaction."""
        name = str(supplier_name or "").strip()
        if not name:
            return None

        def resolve(connection):
            connection.execute(
                "INSERT OR IGNORE INTO suppliers (name, phone, address, notes) "
                "VALUES (?, '', '', 'ثبت خودکار از فرم خرید')",
                (name,),
            )
            row = connection.execute(
                "SELECT id FROM suppliers WHERE name=? COLLATE NOCASE",
                (name,),
            ).fetchone()
            if row is None:
                raise RuntimeError("تأمین‌کننده پس از ثبت قابل بازیابی نیست.")
            return int(row["id"])

        if conn is not None:
            return resolve(conn)
        with self.get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            supplier_id = resolve(connection)
            connection.commit()
            return supplier_id

    # --- مدیریت محموله‌های خرید (Batches) ---
    @staticmethod
    def _normalize_color_list(colors):
        if colors is None:
            return None
        if isinstance(colors, str):
            colors = [colors]
        if not isinstance(colors, (list, tuple, set)):
            raise ValueError("فهرست رنگ‌های کالا معتبر نیست.")
        return list(dict.fromkeys(
            str(value).strip() for value in colors
            if value is not None and str(value).strip()
        ))

    @staticmethod
    def _sqlite_integer(value, field_name):
        """Normalize an integer and enforce SQLite's signed 64-bit storage range."""
        if isinstance(value, bool):
            number = int(value)
        elif isinstance(value, float):
            if not value.is_integer():
                raise ValueError(f"مقدار «{field_name}» باید عدد صحیح باشد.")
            number = int(value)
        else:
            raw = str(value).strip().translate(
                str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
            ).replace(",", "").replace("٬", "")
            if not raw:
                raise ValueError(f"مقدار «{field_name}» وارد نشده است.")
            try:
                number = int(raw)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"مقدار «{field_name}» معتبر نیست.") from exc
        if number < SQLITE_INTEGER_MIN or number > SQLITE_INTEGER_MAX:
            raise ValueError(
                f"مقدار «{field_name}» از محدودهٔ عدد صحیح ۶۴ بیتی SQLite خارج است."
            )
        return number

    @staticmethod
    def _batch_integer(value, field_name, *, minimum=0):
        """Convert UI/database values and enforce signed 64-bit integer bounds."""
        number = DatabaseManager._sqlite_integer(value, field_name)
        if number < minimum:
            operator = "بزرگ‌تر از صفر" if minimum == 1 else "صفر یا بیشتر"
            raise ValueError(f"مقدار «{field_name}» باید {operator} باشد.")
        return number

    @staticmethod
    def _batch_optional_id(value, field_name):
        if value is None or str(value).strip() == "":
            return None
        return DatabaseManager._batch_integer(value, field_name, minimum=1)

    @staticmethod
    def _purchase_settlement(total_bill, paid_amount):
        paid = DatabaseManager._batch_integer(paid_amount, "مبلغ پرداخت‌شده")
        if paid > total_bill:
            raise ValueError("مبلغ پرداخت‌شده نمی‌تواند از مبلغ کل محموله بیشتر باشد.")
        if paid >= total_bill:
            return paid, "تسویه‌شده"
        if paid == 0:
            return paid, "تسویه‌نشده"
        return paid, "تسویه جزئی"

    def add_batch(
        self,
        batch_code,
        product_id,
        supplier_id,
        buyer_employee_id,
        invoice_number,
        purchase_date,
        initial_qty,
        unit_purchase_price,
        extra_cost_total,
        suggested_sell_price,
        paid_amount,
        serial_numbers="",
        initial_specs="",
        notes="",
        settlement_status=None,
        colors=None,
        supplier_name=None,
        purchase_time="",
    ):
        """Create a purchase shipment and all linked records atomically."""
        product_id = self._batch_integer(product_id, "کالا", minimum=1)
        supplier_id = self._batch_optional_id(supplier_id, "تأمین‌کننده")
        buyer_employee_id = self._batch_optional_id(
            buyer_employee_id, "مسئول خرید"
        )
        initial_qty = self._batch_integer(initial_qty, "تعداد خرید", minimum=1)
        unit_purchase_price = self._batch_integer(
            unit_purchase_price, "قیمت خرید واحد"
        )
        extra_cost_total = self._batch_integer(
            extra_cost_total, "هزینه جانبی کل"
        )
        suggested_sell_price = self._batch_integer(
            suggested_sell_price, "قیمت فروش پیشنهادی"
        )
        purchase_date = str(purchase_date or "").strip()
        if not purchase_date:
            raise ValueError("تاریخ خرید وارد نشده است.")
        purchase_time_arg = str(purchase_time or "").strip()
        if purchase_time_arg and " " not in purchase_date:
            purchase_date = f"{purchase_date} {purchase_time_arg}"
        purchase_payment_date = purchase_date.split(" ", 1)[0].strip()
        invoice_number = str(invoice_number or "").strip()
        serial_numbers = str(serial_numbers or "").strip()
        initial_specs = str(initial_specs or "").strip()
        notes = str(notes or "").strip()
        batch_code = str(batch_code or "").strip()

        extra_per_unit = round_integer_division(extra_cost_total, initial_qty)
        unit_cost_price = self._batch_integer(
            unit_purchase_price + extra_per_unit, "بهای تمام‌شده واحد"
        )
        profit_pct = (
            round(((suggested_sell_price - unit_cost_price) / unit_cost_price) * 100, 2)
            if unit_cost_price > 0 else 0.0
        )
        total_bill = self._sqlite_integer(
            unit_purchase_price * initial_qty + extra_cost_total, "بهای کل محموله"
        )
        paid_amount, status = self._purchase_settlement(total_bill, paid_amount)
        color_json = json.dumps(
            self._normalize_color_list(colors) or [], ensure_ascii=False
        )

        def _tx(conn):
            nonlocal batch_code, supplier_id
            if not batch_code:
                batch_code = self.generate_next_code(
                    "batches", "batch_code", "C-", 1001, conn=conn
                )
            if supplier_id is None and str(supplier_name or "").strip():
                supplier_id = self.get_or_create_supplier(supplier_name, conn=conn)

            supplier_row = conn.execute(
                "SELECT name FROM suppliers WHERE id=?", (supplier_id,)
            ).fetchone() if supplier_id is not None else None
            supplier_snapshot = supplier_row["name"] if supplier_row else ""

            cursor = conn.execute(
                """
                INSERT INTO batches (
                    batch_code, product_id, supplier_id, buyer_employee_id, invoice_number,
                    purchase_date, initial_qty, sold_qty, returned_qty, remaining_qty,
                    unit_purchase_price, extra_cost_total, upgrade_cost_unit, unit_cost_price,
                    suggested_sell_price, profit_pct, settlement_status, paid_amount,
                    serial_numbers, initial_specs, final_specs, notes, supplier_name_snapshot,
                    colors_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_code, product_id, supplier_id, buyer_employee_id, invoice_number,
                    purchase_date, initial_qty, initial_qty, unit_purchase_price,
                    extra_cost_total, unit_cost_price, suggested_sell_price, profit_pct,
                    status, paid_amount, serial_numbers, initial_specs, initial_specs,
                    notes, supplier_snapshot, color_json,
                ),
            )
            batch_id = int(cursor.lastrowid)
            if paid_amount > 0:
                conn.execute(
                    """
                    INSERT INTO payments
                        (ref_type, ref_id, amount, payment_date, notes)
                    VALUES ('batch', ?, ?, ?,
                            'پرداخت اولیه هنگام ثبت خرید')
                    """,
                    (batch_id, paid_amount, purchase_payment_date),
                )
            self.log_audit(
                conn, "ثبت خرید",
                f"کد محموله: {batch_code} - تعداد: {initial_qty}",
            )
            return batch_code

        return self.run_write_transaction(_tx)

    def update_batch(
        self,
        batch_id,
        supplier_id,
        buyer_employee_id,
        invoice_number,
        purchase_date,
        new_initial_qty,
        unit_purchase_price,
        extra_cost_total,
        suggested_sell_price,
        paid_amount,
        serial_numbers,
        notes,
        settlement_status=None,
        product_id=None,
        initial_specs=None,
        batch_code=None,
        colors=None,
        supplier_name=None,
        purchase_time=None,
        expected_row_version=None,
    ):
        """Update a shipment under a write lock while preserving sold/returned stock."""
        batch_id = self._batch_integer(batch_id, "شناسه محموله", minimum=1)
        supplier_id = self._batch_optional_id(supplier_id, "تأمین‌کننده")
        buyer_employee_id = self._batch_optional_id(
            buyer_employee_id, "مسئول خرید"
        )
        new_initial_qty = self._batch_integer(
            new_initial_qty, "تعداد اولیه محموله", minimum=1
        )
        unit_purchase_price = self._batch_integer(
            unit_purchase_price, "قیمت خرید واحد"
        )
        extra_cost_total = self._batch_integer(
            extra_cost_total, "هزینه جانبی کل"
        )
        suggested_sell_price = self._batch_integer(
            suggested_sell_price, "قیمت فروش پیشنهادی"
        )
        purchase_date = str(purchase_date or "").strip()
        if not purchase_date:
            raise ValueError("تاریخ خرید وارد نشده است.")
        purchase_time_arg = str(purchase_time or "").strip()
        if purchase_time_arg and " " not in purchase_date:
            purchase_date = f"{purchase_date} {purchase_time_arg}"
        purchase_payment_date = purchase_date.split(" ", 1)[0].strip()
        invoice_number = str(invoice_number or "").strip()
        serial_numbers = str(serial_numbers or "").strip()
        notes = str(notes or "").strip()
        batch_code = str(batch_code or "").strip()
        initial_specs = (
            str(initial_specs or "").strip() if initial_specs is not None else None
        )

        def _tx(conn):
            nonlocal supplier_id, suggested_sell_price
            old = self._check_row_version(
                conn, "batches", batch_id, expected_row_version, "محموله"
            )
            if old is None:
                old = conn.execute(
                    """
                    SELECT id, batch_code, product_id, supplier_id, buyer_employee_id,
                           invoice_number, purchase_date, initial_qty, sold_qty,
                           returned_qty, remaining_qty, unit_purchase_price,
                           extra_cost_total, upgrade_cost_unit, unit_cost_price,
                           suggested_sell_price, profit_pct, paid_amount,
                           settlement_status, serial_numbers, colors_json, initial_specs,
                           final_specs, supplier_name_snapshot, notes, created_at, updated_at, row_version
                    FROM batches WHERE id=?
                    """,
                    (batch_id,),
                ).fetchone()
            if old is None:
                raise ValueError("محموله یافت نشد.")

            new_product_id = (
                self._batch_integer(product_id, "کالا", minimum=1)
                if product_id is not None else int(old["product_id"])
            )
            sold_qty = int(old["sold_qty"] or 0)
            returned_qty = int(old["returned_qty"] or 0)
            if (sold_qty > 0 or returned_qty > 0) and new_product_id != int(old["product_id"]):
                raise ValueError(
                    "کالای محموله‌ای که فروش، مرجوعی یا مصرف در ارتقا داشته است قابل تعویض نیست."
                )
            unavailable_qty = sold_qty + returned_qty
            if new_initial_qty < unavailable_qty:
                raise ValueError(
                    "تعداد اولیه نمی‌تواند کمتر از مجموع تعداد فروخته‌شده و مرجوعی باشد "
                    f"({unavailable_qty} عدد)."
                )
            new_remaining = new_initial_qty - unavailable_qty

            if supplier_id is None and str(supplier_name or "").strip():
                supplier_id = self.get_or_create_supplier(supplier_name, conn=conn)
            supplier_row = conn.execute(
                "SELECT name FROM suppliers WHERE id=?", (supplier_id,)
            ).fetchone() if supplier_id is not None else None
            supplier_snapshot = (
                supplier_row["name"] if supplier_row else old["supplier_name_snapshot"]
            )

            extra_per_unit = round_integer_division(extra_cost_total, new_initial_qty)
            unit_cost_price = self._batch_integer(
                unit_purchase_price + extra_per_unit + int(old["upgrade_cost_unit"] or 0),
                "بهای تمام‌شده واحد",
            )
            suggested_sell_price = int(suggested_sell_price)
            profit_pct = (
                round(((suggested_sell_price - unit_cost_price) / unit_cost_price) * 100, 2)
                if unit_cost_price > 0 else 0.0
            )
            total_bill = self._sqlite_integer(
                unit_purchase_price * new_initial_qty + extra_cost_total, "بهای کل محموله"
            )
            paid_amount_val, status = self._purchase_settlement(total_bill, paid_amount)

            new_colors_json = (
                json.dumps(self._normalize_color_list(colors), ensure_ascii=False)
                if colors is not None else old["colors_json"] or "[]"
            )
            new_purchase_date = purchase_date
            if " " not in new_purchase_date and purchase_time is None:
                old_pd = str(old["purchase_date"] or "").strip()
                if " " in old_pd:
                    new_purchase_date = f"{new_purchase_date} {old_pd.split(' ', 1)[1].strip()}"
            conn.execute(
                """
                UPDATE batches SET
                    batch_code=?, product_id=?, supplier_id=?, buyer_employee_id=?,
                    invoice_number=?, purchase_date=?, initial_qty=?, remaining_qty=?,
                    unit_purchase_price=?, extra_cost_total=?, unit_cost_price=?,
                    suggested_sell_price=?, profit_pct=?, settlement_status=?, paid_amount=?,
                    serial_numbers=?, initial_specs=?, notes=?, supplier_name_snapshot=?,
                    colors_json=?
                WHERE id=?
                """,
                (
                    (batch_code or old["batch_code"]).strip(),
                    new_product_id, supplier_id, buyer_employee_id, invoice_number,
                    new_purchase_date, new_initial_qty, new_remaining, unit_purchase_price,
                    extra_cost_total, unit_cost_price, suggested_sell_price, profit_pct,
                    status, paid_amount_val, serial_numbers,
                    initial_specs if initial_specs is not None else old["initial_specs"],
                    notes, supplier_snapshot, new_colors_json, batch_id,
                ),
            )
            conn.execute(
                "DELETE FROM payments WHERE ref_type='batch' AND ref_id=?",
                (batch_id,),
            )
            if paid_amount_val > 0:
                conn.execute(
                    """
                    INSERT INTO payments
                        (ref_type, ref_id, amount, payment_date, notes)
                    VALUES ('batch', ?, ?, ?,
                            'پرداخت اصلاح‌شده هنگام ویرایش محموله')
                    """,
                    (batch_id, paid_amount_val, purchase_payment_date),
                )

            self.log_audit(
                conn, "ویرایش محموله", f"کد محموله: {old['batch_code']}"
            )

        self.run_write_transaction(_tx)

    def delete_batch(self, batch_id, expected_row_version=None):
        """Hard-delete a purchase batch and its dependent records atomically."""
        batch_id = self._batch_integer(batch_id, "شناسه محموله", minimum=1)
        def _tx(conn):
            if expected_row_version is not None:
                self._check_row_version(conn, "batches", batch_id, expected_row_version, "محموله")
            row = conn.execute(
                "SELECT batch_code FROM batches WHERE id=?", (batch_id,)
            ).fetchone()
            if row is None:
                return
            self._hard_delete_batches(conn, [batch_id])
            self.log_audit(
                conn, "حذف کامل محموله", f"کد محموله: {row['batch_code']}"
            )

        self.run_write_transaction(_tx)


    def _reverse_upgrade_effects(self, conn, upgrade):
        """Reverse one upgrade's stock and target-cost effects inside the caller's transaction."""
        part_batch = conn.execute(
            "SELECT id FROM batches WHERE id=?", (upgrade["part_batch_id"],)
        ).fetchone()
        stock_deducted = int(upgrade["stock_deducted_qty"] or 0)
        if part_batch and stock_deducted > 0:
            conn.execute(
                """UPDATE batches SET sold_qty=MAX(0,sold_qty-?),
                   remaining_qty=remaining_qty+? WHERE id=?""",
                (stock_deducted, stock_deducted, upgrade["part_batch_id"]),
            )

        target = conn.execute(
            """SELECT id, batch_code, product_id, supplier_id, buyer_employee_id, invoice_number,
            purchase_date, initial_qty, sold_qty, returned_qty, remaining_qty,
            unit_purchase_price, extra_cost_total, upgrade_cost_unit, unit_cost_price,
            suggested_sell_price, profit_pct, paid_amount, settlement_status,
            serial_numbers, colors_json, initial_specs, final_specs,
            supplier_name_snapshot, notes, created_at, updated_at FROM batches WHERE id=?""", (upgrade["target_batch_id"],)
        ).fetchone()
        if target:
            added_cost = int(upgrade["added_cost_unit"] or 0)
            deducted_suggested = round_percentage_amount(
                added_cost, target["profit_pct"] or 0
            )
            conn.execute(
                """UPDATE batches SET
                   upgrade_cost_unit=MAX(0,upgrade_cost_unit-?),
                   unit_cost_price=MAX(0,unit_cost_price-?),
                   suggested_sell_price=MAX(0,suggested_sell_price-?),
                   final_specs=?
                   WHERE id=?""",
                (
                    added_cost,
                    added_cost,
                    deducted_suggested,
                    (upgrade["old_specs"] or target["initial_specs"] or ""),
                    upgrade["target_batch_id"],
                ),
            )

    def upgrade_batch_product(
        self,
        target_batch_id,
        target_qty,
        part_batch_id,
        part_qty_per_unit,
        labor_cost_unit,
        new_specs,
        upgrade_date,
        technician_id,
        serial_number="",
        notes="",
        add_part_cost_to_product=False,
        upgrade_id=None,
        manual_part_description="",
        consume_stock=True,
        expected_row_version=None,
    ):
        target_qty = self._batch_integer(target_qty, "تعداد کالای هدف", minimum=1)
        part_qty_per_unit = self._batch_integer(part_qty_per_unit, "تعداد قطعه برای هر واحد", minimum=1)
        part_qty_total = self._batch_integer(
            target_qty * part_qty_per_unit, "تعداد قطعه مصرفی کل", minimum=1
        )
        labor_cost_unit = self._batch_integer(labor_cost_unit, "اجرت ارتقا")
        if target_qty <= 0 or part_qty_per_unit <= 0:
            raise ValueError("تعداد کالای هدف و تعداد قطعه مصرفی باید بیشتر از صفر باشند.")
        if labor_cost_unit < 0:
            raise ValueError("اجرت ارتقا نمی‌تواند منفی باشد.")
        if part_batch_id is not None and int(target_batch_id) == int(part_batch_id):
            raise ValueError("محموله کالای هدف و محموله قطعه مصرفی باید متفاوت باشند.")
        manual_part_description = str(manual_part_description or "").strip()
        if part_batch_id is None and not manual_part_description:
            raise ValueError("محموله قطعه یا شرح دستی قطعه مصرفی را مشخص کنید.")

        def _tx(conn):
            previous_upgrade = None
            if upgrade_id is not None:
                self._check_row_version(conn, "upgrades", upgrade_id, expected_row_version, "ارتقا")
                previous_upgrade = conn.execute(
                    """SELECT id, target_batch_id, part_batch_id, technician_id, target_qty,
            part_qty_used, stock_deducted_qty, part_unit_cost, labor_cost_unit,
            added_cost_unit, upgrade_date, serial_number, manual_part_description,
            old_specs, new_specs, notes, created_at, updated_at FROM upgrades WHERE id=?""", (upgrade_id,)
                ).fetchone()
                if not previous_upgrade:
                    raise ValueError("رکورد ارتقای انتخاب‌شده یافت نشد.")
                latest = conn.execute(
                    "SELECT id FROM upgrades WHERE target_batch_id=? ORDER BY updated_at DESC, id DESC LIMIT 1",
                    (previous_upgrade["target_batch_id"],),
                ).fetchone()
                if not latest or int(latest["id"]) != int(upgrade_id):
                    raise ValueError(
                        "برای حفظ زنجیره محاسبه بهای تمام‌شده، فقط آخرین ارتقای هر محموله قابل ویرایش است."
                    )
                self._reverse_upgrade_effects(conn, previous_upgrade)

            target_b = conn.execute(
                """SELECT id, batch_code, product_id, supplier_id, buyer_employee_id, invoice_number,
            purchase_date, initial_qty, sold_qty, returned_qty, remaining_qty,
            unit_purchase_price, extra_cost_total, upgrade_cost_unit, unit_cost_price,
            suggested_sell_price, profit_pct, paid_amount, settlement_status,
            serial_numbers, colors_json, initial_specs, final_specs,
            supplier_name_snapshot, notes, created_at, updated_at FROM batches WHERE id=?""", (target_batch_id,)
            ).fetchone()
            part_b = (
                conn.execute("""SELECT id, batch_code, product_id, supplier_id, buyer_employee_id, invoice_number,
            purchase_date, initial_qty, sold_qty, returned_qty, remaining_qty,
            unit_purchase_price, extra_cost_total, upgrade_cost_unit, unit_cost_price,
            suggested_sell_price, profit_pct, paid_amount, settlement_status,
            serial_numbers, colors_json, initial_specs, final_specs,
            supplier_name_snapshot, notes, created_at, updated_at FROM batches WHERE id=?""", (part_batch_id,)).fetchone()
                if part_batch_id is not None else None
            )
            if not target_b or (part_batch_id is not None and not part_b):
                raise ValueError("محموله هدف یا محموله قطعه یافت نشد.")
            # Only the consumed component's availability controls stock deduction.
            # The target device is not consumed by an upgrade.
            part_has_stock = bool(part_b) and int(part_b["remaining_qty"]) >= part_qty_total
            if part_b and consume_stock and not part_has_stock:
                raise ValueError(
                    "موجودی قطعه کافی نیست؛ برای ادامه بدون کسر موجودی، تأیید کاربر لازم است."
                )
            # UI passes consume_stock=False only after the user approves the warning.
            stock_deducted_qty = (
                part_qty_total if part_b and consume_stock and part_has_stock else 0
            )
            if stock_deducted_qty:
                conn.execute(
                    """UPDATE batches SET sold_qty=sold_qty+?, remaining_qty=remaining_qty-?
                       WHERE id=? AND remaining_qty>=?""",
                    (stock_deducted_qty, stock_deducted_qty, part_batch_id, stock_deducted_qty),
                )
                if conn.execute("SELECT changes()").fetchone()[0] != 1:
                    raise ValueError("موجودی قطعه در حین ثبت تغییر کرده است؛ دوباره تلاش کنید.")

            part_unit_cost = int(part_b["unit_cost_price"]) if part_b else 0
            part_cost_share = self._sqlite_integer(
                part_unit_cost * part_qty_per_unit if add_part_cost_to_product and part_b else 0,
                "هزینه قطعات ارتقا",
            )
            added_cost_per_unit = self._batch_integer(
                part_cost_share + labor_cost_unit, "هزینه ارتقا برای هر واحد"
            )
            new_upgrade_cost = self._batch_integer(
                int(target_b["upgrade_cost_unit"]) + added_cost_per_unit, "هزینه کل ارتقا"
            )
            new_unit_cost = self._batch_integer(
                int(target_b["unit_cost_price"]) + added_cost_per_unit, "بهای تمام‌شده جدید"
            )
            suggested_increase = round_percentage_amount(
                added_cost_per_unit, target_b["profit_pct"] or 0
            )
            new_suggested = self._batch_integer(
                int(target_b["suggested_sell_price"]) + suggested_increase,
                "قیمت پیشنهادی جدید",
            )

            conn.execute(
                """UPDATE batches SET upgrade_cost_unit=?, unit_cost_price=?,
                   suggested_sell_price=?, final_specs=? WHERE id=?""",
                (new_upgrade_cost, new_unit_cost, new_suggested, new_specs, target_batch_id),
            )

            values = (
                target_batch_id,
                target_qty,
                part_batch_id,
                part_qty_total,
                part_unit_cost,
                labor_cost_unit,
                added_cost_per_unit,
                target_b["final_specs"] or target_b["initial_specs"] or "",
                new_specs,
                upgrade_date,
                technician_id,
                serial_number,
                notes,
                manual_part_description,
                stock_deducted_qty,
            )
            if upgrade_id is None:
                conn.execute(
                    """INSERT INTO upgrades (
                       target_batch_id, target_qty, part_batch_id, part_qty_used,
                       part_unit_cost, labor_cost_unit, added_cost_unit, old_specs, new_specs,
                       upgrade_date, technician_id, serial_number, notes,
                       manual_part_description, stock_deducted_qty
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    values,
                )
            else:
                conn.execute(
                    """UPDATE upgrades SET target_batch_id=?, target_qty=?, part_batch_id=?,
                       part_qty_used=?, part_unit_cost=?, labor_cost_unit=?, added_cost_unit=?,
                       old_specs=?, new_specs=?, upgrade_date=?, technician_id=?, serial_number=?, notes=?,
                       manual_part_description=?, stock_deducted_qty=?
                       WHERE id=?""",
                    values + (upgrade_id,),
                )

            part_label = (
                part_b["batch_code"] if part_b
                else manual_part_description or "قطعه با شرح دستی"
            )
            self.log_audit(
                conn,
                "ویرایش ارتقای کالا" if upgrade_id is not None else "ثبت ارتقای کالا",
                (
                    f"محموله هدف: {target_b['batch_code']} با قطعه {part_label}؛ "
                    f"کسر موجودی: {stock_deducted_qty} عدد"
                    if stock_deducted_qty
                    else f"محموله هدف: {target_b['batch_code']} با قطعه {part_label}؛ بدون کسر موجودی"
                ),
            )

        self.run_write_transaction(_tx)

    def revert_upgrade(self, upgrade_id: int, expected_row_version=None):
        """Delete an upgrade and reverse its stock and cost effects atomically."""
        def _tx(conn):
            if expected_row_version is not None:
                self._check_row_version(conn, "upgrades", upgrade_id, expected_row_version, "ارتقا")
            upgrade = conn.execute(
                """SELECT id, target_batch_id, part_batch_id, technician_id, target_qty,
            part_qty_used, stock_deducted_qty, part_unit_cost, labor_cost_unit,
            added_cost_unit, upgrade_date, serial_number, manual_part_description,
            old_specs, new_specs, notes, created_at, updated_at FROM upgrades WHERE id=?""", (upgrade_id,)
            ).fetchone()
            if not upgrade:
                raise ValueError("رکورد ارتقا یافت نشد.")
            latest = conn.execute(
                "SELECT id FROM upgrades WHERE target_batch_id=? ORDER BY updated_at DESC, id DESC LIMIT 1",
                (upgrade["target_batch_id"],),
            ).fetchone()
            if not latest or int(latest["id"]) != int(upgrade_id):
                raise ValueError(
                    "برای جلوگیری از برهم خوردن سوابق ارتقا، ابتدا ارتقاهای جدیدتر همین محموله را حذف کنید."
                )
            self._reverse_upgrade_effects(conn, upgrade)
            conn.execute("DELETE FROM upgrades WHERE id=?", (upgrade_id,))
            self.log_audit(conn, "حذف کامل ارتقای کالا", f"شناسه ارتقا: {upgrade_id}")

        self.run_write_transaction(_tx)


    def add_sale(
        self,
        invoice_number,
        product_id,
        batch_id,
        seller_employee_id,
        customer_name,
        qty,
        suggested_unit_price,
        actual_unit_price,
        paid_amount,
        sale_datetime,
        warranty_company="",
        warranty_start="",
        warranty_months=0,
        warranty_end="",
        serial_number="",
        notes="",
        settlement_status=None,
        warranty_days=None,
        specifications="",
        colors=None,
        customer_phone="",
        expected_batch_row_version=None,
    ):
        qty = self._batch_integer(qty, "تعداد فروش", minimum=1)
        product_id = self._batch_integer(product_id, "کالا", minimum=1)
        batch_id = self._batch_integer(batch_id, "محموله", minimum=1)
        customer_name = str(customer_name or "").strip()
        customer_phone = str(customer_phone or "").strip()
        warranty_company = str(warranty_company or "").strip()
        warranty_start = str(warranty_start or "").strip()
        warranty_end = str(warranty_end or "").strip()
        serial_number = str(serial_number or "").strip()
        notes = str(notes or "").strip()
        specifications = str(specifications or "").strip()
        sale_datetime = str(sale_datetime or "").strip()

        def _tx(conn):
            nonlocal invoice_number, paid_amount, suggested_unit_price, actual_unit_price
            batch = conn.execute("""SELECT id, batch_code, product_id, serial_numbers, supplier_id, buyer_employee_id, invoice_number,
            purchase_date, initial_qty, sold_qty, returned_qty, remaining_qty,
            unit_purchase_price, extra_cost_total, upgrade_cost_unit, unit_cost_price,
            suggested_sell_price, profit_pct, paid_amount, settlement_status,
            colors_json, initial_specs, final_specs,
            supplier_name_snapshot, notes, created_at, updated_at, row_version FROM batches WHERE id=?""", (batch_id,)).fetchone()
            if not batch:
                raise ValueError("محموله انتخاب شده وجود ندارد.")
            live_rv = int(batch["row_version"] if "row_version" in batch.keys() else 1)
            if batch["remaining_qty"] < qty:
                concurrent_flag = (
                    expected_batch_row_version is not None
                    and live_rv != int(expected_batch_row_version)
                )
                raise InsufficientStockError(
                    available_qty=batch["remaining_qty"],
                    requested_qty=qty,
                    batch_code=batch["batch_code"],
                    concurrent_modified=concurrent_flag,
                    message=(
                        f"موجودی محموله «{batch['batch_code']}» به دلیل ثبت فروش هم‌زمان کافی نیست! موجودی قابل فروش: {batch['remaining_qty']} عدد"
                        if concurrent_flag
                        else f"موجودی محموله کافی نیست! موجودی قابل فروش: {batch['remaining_qty']} عدد"
                    ),
                )
            if expected_batch_row_version is not None and live_rv != int(expected_batch_row_version):
                raise ConcurrencyConflictError(
                    "batch_sale",
                    batch_id,
                    int(expected_batch_row_version),
                    live_rv,
                    dict(batch),
                    f"در فاصله انتخاب محموله تا ثبت فاکتور، فروش یا تغییری در محموله «{batch['batch_code']}» ثبت شده است. موجودی فعلی: {batch['remaining_qty']} عدد.",
                )
            normalized_colors = self._normalize_color_list(colors)
            if normalized_colors is not None:
                if len(normalized_colors) > qty:
                    raise ValueError("تعداد رنگ‌های انتخاب‌شده نمی‌تواند از تعداد فروش بیشتر باشد.")
                try:
                    batch_colors = json.loads(batch["colors_json"] or "[]")
                except (TypeError, ValueError, json.JSONDecodeError):
                    batch_colors = []
                unavailable = [value for value in normalized_colors if value not in batch_colors]
                if unavailable:
                    raise ValueError("یکی از رنگ‌های انتخاب‌شده در این محموله ثبت نشده است.")

            if not invoice_number:
                invoice_number = self.generate_next_code("sales", "invoice_number", "INV-", 1001, conn=conn)

            suggested_unit_price = self._batch_integer(
                suggested_unit_price, "قیمت پیشنهادی واحد"
            )
            actual_unit_price = self._batch_integer(actual_unit_price, "قیمت فروش واحد")
            paid_amount = self._batch_integer(paid_amount, "مبلغ دریافتی")
            unit_cost_price = self._batch_integer(batch["unit_cost_price"], "بهای تمام‌شده واحد")

            if actual_unit_price < suggested_unit_price:
                unit_discount = suggested_unit_price - actual_unit_price
                price_markup_unit = 0
            else:
                unit_discount = 0
                price_markup_unit = actual_unit_price - suggested_unit_price

            total_discount = self._batch_integer(
                unit_discount * qty, "تخفیف کل فروش"
            )
            unit_profit = self._sqlite_integer(
                actual_unit_price - unit_cost_price, "سود هر واحد"
            )
            total_profit = self._sqlite_integer(unit_profit * qty, "سود کل فروش")
            total_amount = self._batch_integer(
                actual_unit_price * qty, "مبلغ کل فاکتور"
            )
            if settlement_status in ("تسویه‌شده", "تسویه‌نشده", "تسویه جزئی"):
                status = settlement_status
            else:
                if paid_amount >= total_amount:
                    status = "تسویه‌شده"
                    paid_amount = total_amount
                elif paid_amount == 0:
                    status = "تسویه‌نشده"
                else:
                    status = "تسویه جزئی"

            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO sales (
                    invoice_number, product_id, batch_id, serial_number, seller_employee_id, customer_name,
                    customer_phone, qty, suggested_unit_price, actual_unit_price, unit_cost_price,
                    unit_discount, total_discount, price_Markup_unit, unit_profit, total_profit,
                    total_amount, paid_amount, settlement_status, sale_datetime,
                    warranty_company, warranty_start, warranty_months, warranty_days, warranty_end,
                    specifications, colors_json, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    invoice_number,
                    product_id,
                    batch_id,
                    serial_number,
                    seller_employee_id,
                    customer_name,
                    customer_phone,
                    qty,
                    suggested_unit_price,
                    actual_unit_price,
                    unit_cost_price,
                    unit_discount,
                    total_discount,
                    price_markup_unit,
                    unit_profit,
                    total_profit,
                    total_amount,
                    paid_amount,
                    status,
                    sale_datetime,
                    warranty_company,
                    warranty_start,
                    int(warranty_months),
                    int(warranty_days if warranty_days is not None else int(warranty_months or 0) * 30),
                    warranty_end,
                    str(specifications or ""),
                    json.dumps(normalized_colors or [], ensure_ascii=False),
                    notes,
                ),
            )
            sale_id = cur.lastrowid

            stock_update = conn.execute(
                """
                UPDATE batches
                SET sold_qty = sold_qty + ?, remaining_qty = remaining_qty - ?
                WHERE id = ? AND remaining_qty >= ?
                """,
                (qty, qty, batch_id, qty),
            )
            if stock_update.rowcount != 1:
                raise ValueError("موجودی محموله برای ثبت این تعداد کافی نیست.")

            if paid_amount > 0:
                cur.execute(
                    """
                    INSERT INTO payments (ref_type, ref_id, amount, payment_date, notes)
                    VALUES ('sale', ?, ?, ?, 'دریافت وجه هنگام فروش')
                """,
                    (sale_id, paid_amount, sale_datetime.split(" ")[0]),
                )

            self.log_audit(
                conn,
                "ثبت فروش",
                f"فاکتور: {invoice_number} - تعداد: {qty} - سود: {total_profit:,}",
            )
            return invoice_number

        return self.run_write_transaction(_tx)

    def update_sale(
        self,
        sale_id,
        seller_employee_id,
        customer_name,
        new_qty,
        suggested_unit_price,
        actual_unit_price,
        paid_amount,
        warranty_company,
        warranty_start,
        warranty_months,
        warranty_end,
        serial_number,
        notes,
        settlement_status=None,
        warranty_days=None,
        specifications=None,
        colors=None,
        customer_phone="",
        sale_datetime=None,
        expected_row_version=None,
    ):
        new_qty = self._batch_integer(new_qty, "تعداد فروش", minimum=1)
        sale_id = self._batch_integer(sale_id, "شناسه فروش", minimum=1)
        customer_name = str(customer_name or "").strip()
        customer_phone = str(customer_phone or "").strip()
        warranty_company = str(warranty_company or "").strip()
        warranty_start = str(warranty_start or "").strip()
        warranty_end = str(warranty_end or "").strip()
        serial_number = str(serial_number or "").strip()
        notes = str(notes or "").strip()
        specifications = (
            str(specifications or "").strip() if specifications is not None else None
        )

        def _tx(conn):
            nonlocal suggested_unit_price, actual_unit_price, paid_amount
            self._check_row_version(conn, "sales", sale_id, expected_row_version, "فروش")
            old_sale = conn.execute("""SELECT id, invoice_number, product_id, batch_id, serial_number, seller_employee_id,
            customer_name, customer_phone, qty, returned_qty, suggested_unit_price, actual_unit_price,
            unit_cost_price, unit_discount, total_discount, price_Markup_unit,
            unit_profit, total_profit, total_amount, paid_amount, settlement_status,
            sale_datetime, warranty_company, warranty_start, warranty_months,
            warranty_days, warranty_end, specifications, colors_json,
            notes, created_at, updated_at, row_version FROM sales WHERE id=?""", (sale_id,)).fetchone()
            if not old_sale:
                raise ValueError("ردیف فروش یافت نشد.")

            batch = conn.execute(
                """SELECT id, batch_code, product_id, serial_numbers, supplier_id, buyer_employee_id, invoice_number,
            purchase_date, initial_qty, sold_qty, returned_qty, remaining_qty,
            unit_purchase_price, extra_cost_total, upgrade_cost_unit, unit_cost_price,
            suggested_sell_price, profit_pct, paid_amount, settlement_status,
            colors_json, initial_specs, final_specs,
            supplier_name_snapshot, notes, created_at, updated_at FROM batches WHERE id=?""", (old_sale["batch_id"],)
            ).fetchone()
            if batch is None:
                raise ValueError("محموله مربوط به این فروش یافت نشد.")
            if new_qty < int(old_sale["returned_qty"] or 0):
                raise ValueError("تعداد فروش نمی‌تواند از تعداد مرجوع‌شده کمتر باشد.")
            diff_qty = new_qty - int(old_sale["qty"])
            if diff_qty > batch["remaining_qty"]:
                raise ValueError(
                    f"موجودی محموله برای افزایش تعداد کافی نیست. موجودی فعلی: {batch['remaining_qty']}"
                )
            normalized_colors = self._normalize_color_list(colors)
            if normalized_colors is not None:
                if len(normalized_colors) > new_qty:
                    raise ValueError("تعداد رنگ‌های انتخاب‌شده نمی‌تواند از تعداد فروش بیشتر باشد.")
                try:
                    batch_colors = json.loads(batch["colors_json"] or "[]")
                except (TypeError, ValueError, json.JSONDecodeError):
                    batch_colors = []
                try:
                    old_sale_colors = json.loads(old_sale["colors_json"] or "[]")
                except (TypeError, ValueError, json.JSONDecodeError):
                    old_sale_colors = []
                allowed_existing = set(batch_colors or []) | set(old_sale_colors or [])
                unavailable = [value for value in normalized_colors if value not in allowed_existing]
                if unavailable:
                    raise ValueError("یکی از رنگ‌های انتخاب‌شده در این محموله ثبت نشده است.")

            suggested_unit_price = self._batch_integer(
                suggested_unit_price, "قیمت پیشنهادی واحد"
            )
            actual_unit_price = self._batch_integer(actual_unit_price, "قیمت فروش واحد")
            paid_amount = self._batch_integer(paid_amount, "مبلغ دریافتی")
            unit_cost_price = self._batch_integer(
                old_sale["unit_cost_price"], "بهای تمام‌شده واحد"
            )

            if actual_unit_price < suggested_unit_price:
                unit_discount = suggested_unit_price - actual_unit_price
                price_markup = 0
            else:
                unit_discount = 0
                price_markup = actual_unit_price - suggested_unit_price

            total_discount = self._batch_integer(
                unit_discount * new_qty, "تخفیف کل فروش"
            )
            unit_profit = self._sqlite_integer(
                actual_unit_price - unit_cost_price, "سود هر واحد"
            )
            total_profit = self._sqlite_integer(unit_profit * new_qty, "سود کل فروش")
            total_amount = self._batch_integer(
                actual_unit_price * new_qty, "مبلغ کل فاکتور"
            )

            if settlement_status in ("تسویه‌شده", "تسویه‌نشده", "تسویه جزئی"):
                status = settlement_status
            else:
                status = (
                    "تسویه‌شده"
                    if paid_amount >= total_amount
                    else ("تسویه‌نشده" if paid_amount == 0 else "تسویه جزئی")
                )

            new_sale_dt = old_sale["sale_datetime"]
            if sale_datetime is not None and str(sale_datetime).strip():
                candidate_dt = str(sale_datetime).strip()
                if " " not in candidate_dt and old_sale["sale_datetime"] and " " in str(old_sale["sale_datetime"]):
                    time_tail = str(old_sale["sale_datetime"]).split(" ", 1)[1].strip()
                    new_sale_dt = f"{candidate_dt} {time_tail}".strip()
                else:
                    new_sale_dt = candidate_dt

            conn.execute(
                """
                UPDATE sales SET seller_employee_id=?, customer_name=?, customer_phone=?, qty=?,
                suggested_unit_price=?, actual_unit_price=?, unit_discount=?, total_discount=?,
                price_Markup_unit=?, unit_profit=?, total_profit=?, total_amount=?,
                paid_amount=?, settlement_status=?, sale_datetime=?, warranty_company=?, warranty_start=?,
                warranty_months=?, warranty_days=?, warranty_end=?, serial_number=?, notes=?,
                specifications=?, colors_json=?
                WHERE id=?
            """,
                (
                    seller_employee_id,
                    customer_name,
                    customer_phone,
                    new_qty,
                    suggested_unit_price,
                    actual_unit_price,
                    unit_discount,
                    total_discount,
                    price_markup,
                    unit_profit,
                    total_profit,
                    total_amount,
                    paid_amount,
                    status,
                    new_sale_dt,
                    warranty_company,
                    warranty_start,
                    int(warranty_months),
                    int(warranty_days if warranty_days is not None else int(warranty_months or 0) * 30),
                    warranty_end,
                    serial_number,
                    notes,
                    str(specifications if specifications is not None else old_sale["specifications"] or ""),
                    (
                        json.dumps(normalized_colors, ensure_ascii=False)
                        if normalized_colors is not None else old_sale["colors_json"] or "[]"
                    ),
                    sale_id,
                ),
            )

            if diff_qty > 0:
                stock_update = conn.execute(
                    """
                    UPDATE batches
                    SET sold_qty = sold_qty + ?, remaining_qty = remaining_qty - ?
                    WHERE id = ? AND remaining_qty >= ?
                    """,
                    (diff_qty, diff_qty, old_sale["batch_id"], diff_qty),
                )
            elif diff_qty < 0:
                restored_qty = -diff_qty
                stock_update = conn.execute(
                    """
                    UPDATE batches
                    SET sold_qty = sold_qty - ?, remaining_qty = remaining_qty + ?
                    WHERE id = ? AND sold_qty >= ?
                    """,
                    (restored_qty, restored_qty, old_sale["batch_id"], restored_qty),
                )
            else:
                stock_update = None
            if diff_qty and stock_update.rowcount != 1:
                raise ValueError("تغییر تعداد فروش با موجودی محموله سازگار نیست.")

            self.log_audit(
                conn,
                "ویرایش فروش",
                f"فاکتور {old_sale['invoice_number']} اصلاح شد (تغییر تعداد: {diff_qty})",
            )

        self.run_write_transaction(_tx)

    def delete_sale(self, sale_id, expected_row_version=None):
        sale_id = self._batch_integer(sale_id, "شناسه فروش", minimum=1)
        def _tx(conn):
            if expected_row_version is not None:
                self._check_row_version(conn, "sales", sale_id, expected_row_version, "فروش")
            old_sale = conn.execute("""SELECT id, invoice_number, product_id, batch_id, seller_employee_id,
            customer_name, qty, returned_qty, suggested_unit_price, actual_unit_price,
            unit_cost_price, unit_discount, total_discount, price_Markup_unit,
            unit_profit, total_profit, total_amount, paid_amount, settlement_status,
            sale_datetime, warranty_company, warranty_start, warranty_months,
            warranty_days, warranty_end, serial_number, specifications, colors_json,
            notes, created_at, updated_at FROM sales WHERE id=?""", (sale_id,)).fetchone()
            if not old_sale:
                return
            stock_update = conn.execute(
                """
                UPDATE batches
                SET sold_qty = sold_qty - ?, remaining_qty = remaining_qty + ?
                WHERE id = ? AND sold_qty >= ?
                """,
                (old_sale["qty"], old_sale["qty"], old_sale["batch_id"], old_sale["qty"]),
            )
            if stock_update.rowcount != 1:
                raise ValueError("موجودی مصرف‌شدهٔ محموله با سابقهٔ فروش سازگار نیست.")
            conn.execute("DELETE FROM payments WHERE ref_type='sale' AND ref_id=?", (sale_id,))
            conn.execute("DELETE FROM sales WHERE id=?", (sale_id,))
            self.log_audit(
                conn,
                "حذف فروش و بازگشت به انبار",
                f"فاکتور: {old_sale['invoice_number']} - تعداد برگشتی: {old_sale['qty']}",
            )

        self.run_write_transaction(_tx)

    # --- مدیریت کاتالوگ خدمات و تعرفه‌های تاریخی (بند ۴) ---
    def save_service_catalog(
        self, service_id, code, service_type, name, default_fee, default_side_cost, description
    ):
        """
        بند ۴: اگر خدمت جدیدی ثبت شود، فقط در صورتی که خدمتی با همان عنوان و نوع وجود داشته باشد
        جایگزین می‌شود؛ در غیر این صورت به عنوان یک خدمت جدید به لیست اضافه می‌گردد.
        """
        default_fee = self._batch_integer(default_fee, "تعرفه خدمت")
        default_side_cost = self._batch_integer(default_side_cost, "هزینه جانبی پیش‌فرض")
        name_clean = name.strip()
        type_clean = service_type.strip()
        cal, _tf = self._active_datetime_prefs()
        now_date = datetime_format.get_today_date(cal)

        def _tx(conn):
            target_id = service_id
            srv_code = code

            if not target_id:
                if not srv_code:
                    srv_code = self.generate_next_code("service_catalog", "code", "S-", 1001, conn=conn)
                cur = conn.execute(
                    """
                    INSERT INTO service_catalog (code, service_type, name, default_fee, default_side_cost, description)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (srv_code, type_clean, name_clean, default_fee, default_side_cost, description),
                )
                srv_id = cur.lastrowid
                target_id = srv_id
                conn.execute(
                    """
                    INSERT INTO service_price_history (service_id, old_fee, new_fee, change_date)
                    VALUES (?, ?, ?, ?)
                """,
                    (srv_id, default_fee, default_fee, now_date),
                )
            else:
                old = conn.execute(
                    "SELECT default_fee FROM service_catalog WHERE id=?", (target_id,)
                ).fetchone()
                if old and old["default_fee"] != default_fee:
                    conn.execute(
                        """
                        INSERT INTO service_price_history (service_id, old_fee, new_fee, change_date)
                        VALUES (?, ?, ?, ?)
                    """,
                        (target_id, old["default_fee"], default_fee, now_date),
                    )
                conn.execute(
                    """
                    UPDATE service_catalog SET code=?, service_type=?, name=?, default_fee=?, default_side_cost=?, description=?
                    WHERE id=?
                """,
                    (
                        srv_code or conn.execute("SELECT code FROM service_catalog WHERE id=?", (target_id,)).fetchone()["code"],
                        type_clean,
                        name_clean,
                        default_fee,
                        default_side_cost,
                        description,
                        target_id,
                    ),
                )
            return target_id

        return self.run_write_transaction(_tx)

    def delete_service_catalog(self, service_id):
        """Hard-delete a service tariff from the catalog without deleting past transactional service records (REQ-1)."""
        def _tx(conn):
            service = conn.execute(
                "SELECT name FROM service_catalog WHERE id=?", (service_id,)
            ).fetchone()
            if not service:
                return
            conn.execute("UPDATE service_records SET service_id=NULL WHERE service_id=?", (service_id,))
            conn.execute("DELETE FROM service_price_history WHERE service_id=?", (service_id,))
            conn.execute("DELETE FROM service_catalog WHERE id=?", (service_id,))
            self.log_audit(conn, "حذف کامل خدمت", f"شناسه خدمت: {service_id} - {service['name']}")

        self.run_write_transaction(_tx)

    def add_service_record(
        self,
        invoice_number,
        service_id,
        seller_employee_id,
        technician_employee_id,
        customer_name,
        service_fee,
        side_cost,
        paid_amount,
        service_datetime,
        description,
        settlement_status=None,
    ):
        def _tx(conn):
            nonlocal invoice_number, service_fee, side_cost, paid_amount, customer_name, description
            srv = None
            if service_id is not None:
                srv = conn.execute(
                    """SELECT id, code, service_type, name, default_fee, default_side_cost,
                description, is_active, created_at, updated_at FROM service_catalog WHERE id=?""", (service_id,)
                ).fetchone()
                if not srv:
                    raise ValueError("تعرفه خدمت یافت نشد.")
            if not invoice_number:
                invoice_number = self.generate_next_code(
                    "service_records", "invoice_number", "SINV-", 1001, conn=conn
                )

            srv_type = srv["service_type"] if srv else "خدمات عمومی"
            srv_name = srv["name"] if srv else (description or "خدمت متفرقه")
            default_fee_val = srv["default_fee"] if srv else service_fee
            historical_tariff = self._batch_integer(default_fee_val, "تعرفه تاریخی")
            service_fee = self._batch_integer(service_fee, "هزینه خدمت")
            side_cost = self._batch_integer(side_cost, "هزینه جانبی")
            paid_amount = self._batch_integer(paid_amount, "مبلغ دریافتی")
            net_profit = self._sqlite_integer(paid_amount - side_cost, "سود خالص خدمت")
            customer_name = str(customer_name or "").strip()
            description = str(description or "").strip()

            if settlement_status in ("تسویه‌شده", "تسویه‌نشده", "تسویه جزئی"):
                status = settlement_status
            else:
                status = (
                    "تسویه‌شده"
                    if paid_amount >= service_fee
                    else ("تسویه‌نشده" if paid_amount == 0 else "تسویه جزئی")
                )

            conn.execute(
                """
                INSERT INTO service_records (
                    invoice_number, service_id, service_type, service_name,
                    seller_employee_id, technician_employee_id, customer_name,
                    historical_tariff, service_fee, side_cost, net_profit,
                    paid_amount, settlement_status, service_datetime, description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    invoice_number,
                    service_id,
                    srv_type,
                    srv_name,
                    seller_employee_id,
                    technician_employee_id,
                    customer_name,
                    historical_tariff,
                    service_fee,
                    side_cost,
                    net_profit,
                    paid_amount,
                    status,
                    service_datetime,
                    description,
                ),
            )
            self.log_audit(
                conn,
                "ثبت خدمت",
                f"فاکتور خدمت: {invoice_number} - سود خالص خدمت: {net_profit:,}",
            )
            return invoice_number

        return self.run_write_transaction(_tx)

    def update_service_record(
        self,
        record_id,
        seller_id,
        customer_name,
        service_fee,
        side_cost,
        paid_amount,
        description,
        settlement_status=None,
        expected_row_version=None,
    ):
        service_fee = self._batch_integer(service_fee, "هزینه خدمت")
        side_cost = self._batch_integer(side_cost, "هزینه جانبی")
        paid_amount = self._batch_integer(paid_amount, "مبلغ دریافتی")
        net_profit = self._sqlite_integer(paid_amount - side_cost, "سود خالص خدمت")
        customer_name = str(customer_name or "").strip()
        description = str(description or "").strip()
        if settlement_status in ("تسویه‌شده", "تسویه‌نشده", "تسویه جزئی"):
            status = settlement_status
        else:
            status = (
                "تسویه‌شده"
                if paid_amount >= service_fee
                else ("تسویه‌نشده" if paid_amount == 0 else "تسویه جزئی")
            )
        def _tx(conn):
            self._check_row_version(conn, "service_records", record_id, expected_row_version, "خدمت")
            conn.execute(
                """
                UPDATE service_records SET seller_employee_id=?, customer_name=?,
                service_fee=?, side_cost=?, net_profit=?, paid_amount=?, settlement_status=?, description=?
                WHERE id=?
            """,
                (
                    seller_id,
                    customer_name,
                    service_fee,
                    side_cost,
                    net_profit,
                    paid_amount,
                    status,
                    description,
                    record_id,
                ),
            )

        self.run_write_transaction(_tx)

    def delete_service_record(self, record_id, expected_row_version=None):
        def _tx(conn):
            if expected_row_version is not None:
                self._check_row_version(conn, "service_records", record_id, expected_row_version, "خدمت")
            conn.execute("DELETE FROM service_records WHERE id=?", (record_id,))

        self.run_write_transaction(_tx)

    # --- پشتیبان‌گیری و بازیابی (REQ-2 Per-DB Scoped Backup & Collision Guard) ---
    def _get_db_entry_config(self) -> dict:
        norm_key = os.path.normcase(os.path.abspath(self.db_path))
        dbs = self.cfg.setdefault("databases", {})
        if norm_key not in dbs:
            default_bk_dir = os.path.join(os.path.dirname(os.path.abspath(self.db_path)), "Backups")
            dbs[norm_key] = {
                "auto_backup_enabled": bool(self.cfg.get("auto_backup_enabled", True)),
                "auto_backup_dir": default_bk_dir,
                "auto_backup_interval_min": int(self.cfg.get("auto_backup_interval_min", 60)),
                "auto_backup_retention_count": int(self.cfg.get("auto_backup_retention_count", 10)),
            }
        return dbs[norm_key]

    def get_db_config(self, key: str, default=None):
        norm_key = os.path.normcase(os.path.abspath(self.db_path))
        dbs = self.cfg.get("databases", {})
        if norm_key in dbs and key in dbs[norm_key]:
            return dbs[norm_key][key]
        return self.cfg.get(key, default)

    def _merge_disk_databases_into_cfg(self):
        disk_cfg = load_app_config()
        disk_dbs = disk_cfg.get("databases", {})
        dbs = self.cfg.setdefault("databases", {})
        for dbk, dbv in disk_dbs.items():
            if dbk not in dbs:
                dbs[dbk] = dbv
            elif isinstance(dbv, dict):
                for k, v in dbv.items():
                    if k not in dbs[dbk]:
                        dbs[dbk][k] = v
        return dbs

    def set_db_config(self, key: str, value, persist: bool = True):
        if persist:
            dbs = self._merge_disk_databases_into_cfg()
        else:
            dbs = self.cfg.setdefault("databases", {})
        norm_key = os.path.normcase(os.path.abspath(self.db_path))
        entry = dbs.setdefault(norm_key, {})
        entry[key] = value
        self.cfg[key] = value
        if persist:
            save_app_config(self.cfg)

    def get_automatic_backup_directory(self):
        """Return this database's configured or default Backups folder."""
        entry_dir = str(self.get_db_config("auto_backup_dir") or "").strip()
        if entry_dir:
            return os.path.abspath(entry_dir)
        database_dir = os.path.dirname(os.path.abspath(self.db_path)) or "."
        return os.path.join(database_dir, "Backups")

    def set_automatic_backup_directory(self, new_dir, persist: bool = True):
        """Validate, persist and create a new automatic backup directory for this database."""
        if not new_dir or not str(new_dir).strip():
            raise ValueError("مسیر ذخیره پشتیبان‌گیری نمی‌تواند خالی باشد.")
        target_path = os.path.abspath(str(new_dir).strip())
        os.makedirs(target_path, exist_ok=True)
        test_file = os.path.join(target_path, ".write_test")
        try:
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
        except Exception as e:
            raise PermissionError(f"دسترسی ذخیره در پوشه انتخاب‌شده وجود ندارد: {e}")
        if persist:
            self._merge_disk_databases_into_cfg()
        self.set_db_config("auto_backup_dir", target_path, persist=False)
        self.cfg["backup_dir"] = target_path
        if persist:
            save_app_config(self.cfg)
        return target_path

    def _automatic_backup_entries(self, directory, database_name):
        """Return this database's automatic snapshots, ordered oldest first.
        Prefix-Collision Guard (REQ-2): strictly match this database's stem, preventing
        accidental collision/pruning between e.g. Daqiq and Daqiq_2 or Daqiq_3 in the same folder.
        """
        candidates = []
        if not os.path.isdir(directory):
            return candidates
        pattern = re.compile(rf"^{re.escape(database_name)}_(?:backup_)?(\d{{8}}_\d{{6}})(?:_\d+)?\.db$")
        with os.scandir(directory) as entries:
            for entry in entries:
                if not entry.is_file() or not entry.name.endswith(".db"):
                    continue
                match = pattern.match(entry.name)
                if not match:
                    continue
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                candidates.append((stat.st_mtime_ns, entry.name, entry.path))
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates

    def get_last_automatic_backup_timestamp(self):
        """Return this database's last successful automatic backup epoch timestamp."""
        database_key = os.path.normcase(os.path.abspath(self.db_path))
        state = self.cfg.get("auto_backup_last_success_by_db", {})
        try:
            stored = float(state.get(database_key, 0) or 0)
        except (TypeError, ValueError):
            stored = 0.0
        if stored > 0:
            return stored

        database_name = os.path.splitext(os.path.basename(self.db_path))[0]
        entries = self._automatic_backup_entries(
            self.get_automatic_backup_directory(), database_name
        )
        if not entries:
            # Backward compatibility: discover snapshots created by older versions
            # beside the database, without counting or deleting them in new rotations.
            legacy_directory = os.path.dirname(os.path.abspath(self.db_path)) or "."
            entries = self._automatic_backup_entries(legacy_directory, database_name)
        if not entries:
            return 0.0
        return max(timestamp_ns for timestamp_ns, _, _ in entries) / 1_000_000_000

    def _prune_automatic_backups(self, directory, database_name):
        """Keep at most N automatic copies scoped to this database stem; tolerate files held open by another app."""
        candidates = self._automatic_backup_entries(directory, database_name)
        keep_count = max(1, int(self.get_db_config("auto_backup_retention_count", 10) or 10))
        failed_removals = []
        for _, _, old_path in candidates[:-keep_count]:
            last_error = None
            for attempt in range(3):
                try:
                    os.remove(old_path)
                    last_error = None
                    break
                except OSError as exc:
                    last_error = exc
                    if attempt < 2:
                        # Windows antivirus/indexer handles can briefly prevent deletion.
                        time.sleep(0.15 * (attempt + 1))
            if last_error is not None:
                failed_removals.append(os.path.basename(old_path))
        return failed_removals

    def create_backup(self, custom_dir=None, automatic=False, target_file=None):
        """Create a verified SQLite copy directly at its final .db path."""
        database_path = os.path.abspath(self.db_path)
        database_name = os.path.splitext(os.path.basename(database_path))[0]

        if target_file:
            backup_file = os.path.abspath(target_file)
            if os.path.normcase(backup_file) == os.path.normcase(database_path):
                raise ValueError("مسیر فایل پشتیبان نمی‌تواند با مسیر پایگاه داده فعال یکسان باشد.")
        elif automatic:
            backup_dir = self.get_automatic_backup_directory()
            os.makedirs(backup_dir, exist_ok=True)
            stamp = jdatetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(backup_dir, f"{database_name}_backup_{stamp}.db")
            suffix = 1
            while os.path.exists(backup_file):
                backup_file = os.path.join(
                    backup_dir, f"{database_name}_backup_{stamp}_{suffix:02d}.db"
                )
                suffix += 1
        else:
            target_dir = custom_dir or self.cfg.get("backup_dir") or os.path.dirname(database_path)
            os.makedirs(target_dir, exist_ok=True)
            stamp = jdatetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(target_dir, f"DaqiqBackup_{stamp}.db")
            suffix = 1
            base_file = backup_file
            while os.path.exists(backup_file):
                backup_file = base_file[:-3] + f"_{suffix:02d}.db"
                suffix += 1

        backup_dir = os.path.dirname(backup_file) or "."
        os.makedirs(backup_dir, exist_ok=True)

        # Automatic copies are written directly into their final .db files:
        # no staging file and no rename/replace operation is involved.
        # For a manual overwrite, use a same-folder .db staging copy so a failed
        # overwrite never destroys the user's existing manual backup.
        write_file = backup_file
        replace_manual_target = bool(
            not automatic and target_file and os.path.exists(backup_file)
        )
        if replace_manual_target:
            stamp = jdatetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            suffix = 1
            write_file = os.path.join(
                backup_dir, f".{database_name}_manual_{stamp}_{suffix:02d}.db"
            )
            while os.path.exists(write_file):
                suffix += 1
                write_file = os.path.join(
                    backup_dir, f".{database_name}_manual_{stamp}_{suffix:02d}.db"
                )

        file_descriptor = None
        created_backup = False
        try:
            file_descriptor = os.open(
                write_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
            os.close(file_descriptor)
            file_descriptor = None
            created_backup = True

            # sqlite3.Connection as a context manager commits/rolls back but
            # does not close the OS file handle. Explicit close is essential on
            # Windows before rotation or rollback attempts to delete/rename files.
            if self.is_password_protected():
                self.sync_database()
                shutil.copyfile(database_path, write_file)

                check_db = sqlite3.connect(write_file, timeout=30)
                try:
                    check_db.execute(f"PRAGMA key = {self._quote_key(self._encryption_key)}")
                    integrity = check_db.execute("PRAGMA cipher_integrity_check").fetchall()
                    quick = check_db.execute("PRAGMA quick_check").fetchone()
                finally:
                    check_db.close()
                if (integrity and integrity[0][0] != "ok") or (not quick or quick[0] != "ok"):
                    raise sqlite3.DatabaseError(
                        "نسخه پشتیبان رمزنگاری‌شده از آزمون یکپارچگی عبور نکرد."
                    )

                plain_leak_test = sqlite3.connect(write_file, timeout=30)
                try:
                    plain_leak_test.execute("SELECT count(*) FROM sqlite_master")
                    plain_leak_test.close()
                    raise RuntimeError("خطای امنیتی نشت اطلاعات: فایل پشتیبان بدون کلید رمز قابل بازگشایی است.")
                except sqlite3.DatabaseError:
                    plain_leak_test.close()
            else:
                for backup_attempt in range(6):
                    source = sqlite3.connect(database_path, timeout=15.0)
                    destination = None
                    try:
                        source.execute("PRAGMA busy_timeout=15000")
                        destination = sqlite3.connect(write_file, timeout=15.0)
                        destination.execute("PRAGMA busy_timeout=15000")
                        source.backup(destination, pages=256, sleep=0.05)
                        destination.commit()
                        break
                    except sqlite3.OperationalError as exc:
                        err = str(exc).lower()
                        if ("locked" in err or "busy" in err) and backup_attempt < 5:
                            time.sleep(0.08 * (1.5 ** backup_attempt))
                            continue
                        raise
                    finally:
                        if destination is not None:
                            destination.close()
                        source.close()

                check_db = sqlite3.connect(write_file, timeout=30)
                try:
                    check_result = check_db.execute("PRAGMA quick_check").fetchone()
                finally:
                    check_db.close()
                if not check_result or check_result[0] != "ok":
                    raise sqlite3.DatabaseError(
                        "نسخه پشتیبان از آزمون یکپارچگی پایگاه داده SQLite عبور نکرد."
                    )

            if replace_manual_target:
                os.replace(write_file, backup_file)
                created_backup = False

            pruning_warnings = []
            if automatic:
                pruning_warnings = self._prune_automatic_backups(
                    backup_dir, database_name
                )
                if pruning_warnings:
                    # The retention cap is a hard invariant: do not keep the
                    # just-created N+1 copy when an older locked file cannot be
                    # removed. Roll back the new copy and retry at the next timer.
                    try:
                        os.remove(backup_file)
                        created_backup = False
                    except OSError as rollback_error:
                        raise OSError(
                            "حذف نسخه پشتیبان جدید برای رعایت سقف نگهداری نیز ممکن نشد؛ "
                            "لطفاً فایل‌های پوشه Backups را که در برنامه دیگری باز هستند ببندید."
                        ) from rollback_error
                    raise PermissionError(
                        "نسخه‌های قدیمی پایگاه داده در برنامه دیگری باز هستند. "
                        "برای جلوگیری از عبور تعداد نسخه‌ها از سقف تعیین‌شده، "
                        "نسخه جدید حذف شد؛ فایل‌های Backups را ببندید و تلاش مجدد انجام می‌شود."
                    )
        except Exception:
            if file_descriptor is not None:
                os.close(file_descriptor)
            if created_backup and os.path.exists(write_file):
                try:
                    os.remove(write_file)
                except OSError:
                    pass
            raise

        cal, tf = self._active_datetime_prefs()
        self.cfg["last_backup_time"] = datetime_format.get_now_datetime(cal, tf)
        self.cfg["backup_dir"] = os.path.dirname(database_path) or "."
        if automatic:
            database_key = os.path.normcase(database_path)
            disk_cfg = load_app_config()
            for dbk, dbv in disk_cfg.get("databases", {}).items():
                if dbk not in self.cfg.setdefault("databases", {}):
                    self.cfg["databases"][dbk] = dbv
            backup_state = dict(self.cfg.get("auto_backup_last_success_by_db", {}))
            backup_state.update(disk_cfg.get("auto_backup_last_success_by_db", {}))
            backup_state[database_key] = time.time()
            self.cfg["auto_backup_last_success_by_db"] = backup_state
            if pruning_warnings:
                self.cfg["last_backup_warning"] = (
                    "برخی نسخه‌های قدیمی به دلیل باز بودن فایل در برنامه دیگری حذف نشدند: "
                    + "، ".join(pruning_warnings)
                )
            else:
                self.cfg.pop("last_backup_warning", None)
        save_app_config(self.cfg)
        return backup_file


    def restore_backup(self, backup_file_path):
        self._ensure_writable()
        self.create_backup()
        self.sync_database()
        shutil.copyfile(backup_file_path, self.db_path)
        for ext in ("-wal", "-shm"):
            wal_file = self.db_path + ext
            if os.path.exists(wal_file):
                try:
                    os.remove(wal_file)
                except OSError:
                    pass

    # =========================================================================
    # مدیریت رمز و امنیت پایگاه داده با استاندارد SQLCipher (AES-256)
    # =========================================================================
    def is_password_protected(self) -> bool:
        """Return True if this database has true file-level encryption enabled."""
        return self.is_database_file_encrypted(self.db_path)

    def is_startup_password_prompt_required(self) -> bool:
        """Return True if password prompt is strictly required on startup."""
        if not self.is_password_protected():
            return False
        key = self._encryption_key
        if not key:
            stored = SecureCredentialStore.retrieve_database_credential(self.db_path)
            if stored and self._verify_key_on_file(stored):
                key = stored
            else:
                return True
        try:
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            esc_key = str(key).replace("'", "''")
            conn.execute(f"PRAGMA key = '{esc_key}'")
            row = conn.execute("SELECT value FROM settings WHERE key='db_require_startup_password'").fetchone()
            conn.close()
            if row:
                return str(row[0]).strip() != "0"
        except Exception:
            return True
        return False

    def self_heal_vault_credential(self, valid_password: str):
        """Self-heal .secure_vault.dat if auto-unlock is enabled for this database (REQ-5).
        Recreates/updates vault entry without touching other databases, even if vault was deleted/corrupted.
        """
        if not self.is_password_protected() or not valid_password:
            return
        try:
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            esc_key = str(valid_password).replace("'", "''")
            conn.execute(f"PRAGMA key = '{esc_key}'")
            row = conn.execute("SELECT value FROM settings WHERE key='db_require_startup_password'").fetchone()
            conn.close()
            prompt_required = str(row[0]).strip() != "0" if row else True
            if not prompt_required:
                SecureCredentialStore.store_database_credential(self.db_path, valid_password)
            else:
                SecureCredentialStore.purge_database_credential(self.db_path)
        except Exception:
            pass

    def verify_database_password(self, raw_password: str) -> bool:
        """Verify provided password against SQLCipher encryption key."""
        clean_pwd = str(raw_password or "")
        if not self.is_password_protected():
            return clean_pwd == ""
        if self._verify_key_on_file(clean_pwd):
            self._close_cached_conn()
            self._encryption_key = clean_pwd
            try:
                self.init_db()
                self._normalize_application_config()
            except Exception:
                pass
            self.self_heal_vault_credential(clean_pwd)
            return True
        return False

    def can_auto_unlock_locally(self) -> bool:
        """Return True if this database can be unlocked without interactive prompt."""
        if not self.is_password_protected():
            return True
        stored = SecureCredentialStore.retrieve_database_credential(self.db_path)
        if stored and self._verify_key_on_file(stored):
            try:
                conn = sqlite3.connect(self.db_path, timeout=5.0)
                esc_stored = str(stored).replace("'", "''")
                conn.execute(f"PRAGMA key = '{esc_stored}'")
                row = conn.execute("SELECT value FROM settings WHERE key='db_require_startup_password'").fetchone()
                conn.close()
                if row and str(row[0]).strip() == "0":
                    return True
            except Exception:
                pass
        return False

    def auto_unlock_if_permitted(self) -> bool:
        """Attempt seamless auto-unlock using OS-protected credentials if permitted (REQ-4, REQ-5)."""
        if not self.is_password_protected():
            return True
        stored = SecureCredentialStore.retrieve_database_credential(self.db_path)
        if not stored:
            return False
        if not self.verify_database_password(stored):
            return False
        if self.is_startup_password_prompt_required():
            self._close_cached_conn()
            self._encryption_key = None
            SecureCredentialStore.purge_database_credential(self.db_path)
            return False
        return True

    def set_database_password(self, new_password: str, require_startup_prompt: bool = True):
        """Encrypt an unencrypted database with true SQLCipher AES-256."""
        self._ensure_writable()
        clean_pwd = str(new_password or "").strip()
        if not clean_pwd:
            raise ValueError("رمز عبور پایگاه داده نمی‌تواند خالی باشد.")
        if self.is_password_protected():
            raise ValueError("پایگاه داده در حال حاضر دارای رمز عبور است.")

        self._close_cached_conn()
        self.sync_database()

        dir_name = os.path.dirname(self.db_path) or "."
        temp_enc = os.path.join(dir_name, f".{os.path.basename(self.db_path)}.enc.tmp")
        if os.path.exists(temp_enc):
            try:
                os.remove(temp_enc)
            except OSError:
                pass

        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.execute(f"ATTACH DATABASE '{temp_enc}' AS encrypted KEY {self._quote_key(clean_pwd)}")
            conn.execute("SELECT sqlcipher_export('encrypted')")
            conn.execute("DETACH DATABASE encrypted")
            conn.close()

            test_conn = sqlite3.connect(temp_enc, timeout=30)
            test_conn.execute(f"PRAGMA key = {self._quote_key(clean_pwd)}")
            test_conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            test_conn.commit()
            integrity = test_conn.execute("PRAGMA cipher_integrity_check").fetchall()
            quick = test_conn.execute("PRAGMA quick_check").fetchone()
            test_conn.close()

            if (integrity and integrity[0][0] != "ok") or (not quick or quick[0] != "ok"):
                raise RuntimeError("خطا در آزمون یکپارچگی پایگاه داده رمزنگاری‌شده.")

            for ext in ("-wal", "-shm"):
                wal_path = self.db_path + ext
                if os.path.exists(wal_path):
                    try:
                        os.remove(wal_path)
                    except OSError:
                        pass

            import gc
            gc.collect()
            os.replace(temp_enc, self.db_path)
            self._encryption_key = clean_pwd
            self.set_setting("db_require_startup_password", "1" if require_startup_prompt else "0")
            if not require_startup_prompt:
                SecureCredentialStore.store_database_credential(self.db_path, clean_pwd)
            else:
                SecureCredentialStore.purge_database_credential(self.db_path)
            self.cfg.pop("local_db_unlock_tokens", None)
            save_app_config(self.cfg)
        finally:
            if os.path.exists(temp_enc):
                try:
                    os.remove(temp_enc)
                except OSError:
                    pass

    def change_database_password(self, old_password: str, new_password: str, require_startup_prompt: bool = None):
        """Change the password on an encrypted database using SQLCipher PRAGMA rekey."""
        self._ensure_writable()
        if not self.is_password_protected():
            raise ValueError("این پایگاه داده رمز ندارد؛ از گزینه تعیین رمز استفاده کنید.")
        clean_old = str(old_password or "").strip()
        clean_new = str(new_password or "").strip()
        if not clean_new:
            raise ValueError("رمز عبور جدید پایگاه داده نمی‌تواند خالی باشد.")
        if not self.verify_database_password(clean_old):
            raise ValueError("رمز عبور فعلی پایگاه داده نادرست است.")

        self._close_cached_conn()
        self.sync_database()

        conn = sqlite3.connect(self.db_path, timeout=30)
        try:
            conn.execute(f"PRAGMA key = {self._quote_key(clean_old)}")
            conn.execute(f"PRAGMA rekey = {self._quote_key(clean_new)}")
        finally:
            conn.close()

        test_conn = sqlite3.connect(self.db_path, timeout=30)
        try:
            test_conn.execute(f"PRAGMA key = {self._quote_key(clean_new)}")
            quick = test_conn.execute("PRAGMA quick_check").fetchone()
            if not quick or quick[0] != "ok":
                raise RuntimeError("خطا در یکپارچگی پس از تغییر رمز پایگاه داده.")
        finally:
            test_conn.close()

        self._encryption_key = clean_new
        if require_startup_prompt is not None:
            self.set_setting("db_require_startup_password", "1" if require_startup_prompt else "0")
        if not self.is_startup_password_prompt_required():
            SecureCredentialStore.store_database_credential(self.db_path, clean_new)
        else:
            SecureCredentialStore.purge_database_credential(self.db_path)
        self.cfg.pop("local_db_unlock_tokens", None)
        save_app_config(self.cfg)

    def remove_database_password(self, current_password: str):
        """Decrypt an encrypted database back to plain SQLite."""
        self._ensure_writable()
        if not self.is_password_protected():
            return
        clean_cur = str(current_password or "").strip()
        if not self.verify_database_password(clean_cur):
            raise ValueError("رمز عبور فعلی پایگاه داده نادرست است.")

        self._close_cached_conn()
        self.sync_database()

        dir_name = os.path.dirname(self.db_path) or "."
        temp_dec = os.path.join(dir_name, f".{os.path.basename(self.db_path)}.plain.tmp")
        if os.path.exists(temp_dec):
            try:
                os.remove(temp_dec)
            except OSError:
                pass

        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.execute(f"PRAGMA key = {self._quote_key(clean_cur)}")
            conn.execute(f"ATTACH DATABASE '{temp_dec}' AS plaintext KEY ''")
            conn.execute("SELECT sqlcipher_export('plaintext')")
            conn.execute("DETACH DATABASE plaintext")
            conn.close()

            test_conn = sqlite3.connect(temp_dec, timeout=30)
            test_conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            test_conn.commit()
            quick = test_conn.execute("PRAGMA quick_check").fetchone()
            test_conn.close()

            if not quick or quick[0] != "ok":
                raise RuntimeError("خطا در آزمون یکپارچگی نسخه غیررمزنگاری‌شده.")

            for ext in ("-wal", "-shm"):
                wal_path = self.db_path + ext
                if os.path.exists(wal_path):
                    try:
                        os.remove(wal_path)
                    except OSError:
                        pass

            import gc
            gc.collect()
            os.replace(temp_dec, self.db_path)
            self._encryption_key = None
            SecureCredentialStore.purge_database_credential(self.db_path)
            self.cfg.pop("local_db_unlock_tokens", None)
            save_app_config(self.cfg)
            self.set_setting("db_require_startup_password", "0")
        finally:
            if os.path.exists(temp_dec):
                try:
                    os.remove(temp_dec)
                except OSError:
                    pass

    def set_startup_password_prompt_required(self, required: bool):
        """Toggle whether password is required on application startup."""
        self._ensure_writable()
        req_str = "1" if required else "0"
        self.set_setting("db_require_startup_password", req_str)
        if required:
            SecureCredentialStore.purge_database_credential(self.db_path)
        elif self._encryption_key:
            SecureCredentialStore.store_database_credential(self.db_path, self._encryption_key)
        self.cfg.pop("local_db_unlock_tokens", None)
        save_app_config(self.cfg)
