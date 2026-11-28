# database.py
from __future__ import annotations
import os
from typing import Any, Dict, List, Optional, Set, Tuple
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


class DuplicateInvoiceConflictError(RuntimeError):
    """Raised when saving an invoice/batch whose unique number already exists on LAN or DB."""

    def __init__(
        self,
        invoice_kind: str,
        conflict_field: str,
        duplicate_value: str,
        suggested_next_number: str,
        existing_version: int = 1,
        existing_summary: Optional[dict] = None,
        stale_replace: bool = False,
        message: str = "",
    ):
        self.invoice_kind = str(invoice_kind or "sale")
        self.conflict_field = str(conflict_field or "invoice_number")
        self.duplicate_value = str(duplicate_value or "")
        self.suggested_next_number = str(suggested_next_number or "")
        self.existing_version = int(existing_version or 1)
        self.existing_summary = dict(existing_summary or {})
        self.stale_replace = bool(stale_replace)
        self.message_fa = message or (
            f"شماره «{self.duplicate_value}» قبلاً ثبت شده است (نسخه {self.existing_version}). "
            f"شماره بعدی پیشنهادی: {self.suggested_next_number}"
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
    "installment_plans",
    "installment_payments",
    "supplier_installment_plans",
    "supplier_installment_payments",
    "checks",
    "invoice_headers",
    "proforma_invoices",
    "proforma_items",
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
    return "5.0.2"

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
    "customers": ("id", "name", "phone", "notes", "created_at", "updated_at", "row_version", "national_id", "address", "last_modified_by", "last_modified_at"),
    "products": ("id", "code", "serial_number", "name", "category", "sub_category", "brand", "model", "specs_json", "description", "reorder_point", "default_profit_pct", "is_active", "created_at", "updated_at", "row_version"),
    "batches": ("id", "batch_code", "product_id", "serial_numbers", "supplier_id", "buyer_employee_id", "invoice_number", "purchase_date", "initial_qty", "sold_qty", "returned_qty", "remaining_qty", "unit_purchase_price", "extra_cost_total", "upgrade_cost_unit", "unit_cost_price", "suggested_sell_price", "profit_pct", "paid_amount", "settlement_status", "colors_json", "initial_specs", "final_specs", "supplier_name_snapshot", "notes", "created_at", "updated_at", "row_version", "settlement_subtype", "check_due_date", "check_status", "purchase_invoice_code", "payment_type"),
    "upgrades": ("id", "target_batch_id", "part_batch_id", "technician_id", "target_qty", "part_qty_used", "stock_deducted_qty", "part_unit_cost", "labor_cost_unit", "added_cost_unit", "upgrade_date", "serial_number", "manual_part_description", "old_specs", "new_specs", "notes", "created_at", "updated_at", "row_version"),
    "sales": ("id", "invoice_number", "product_id", "batch_id", "serial_number", "seller_employee_id", "customer_name", "customer_phone", "qty", "returned_qty", "suggested_unit_price", "actual_unit_price", "unit_cost_price", "unit_discount", "total_discount", "price_Markup_unit", "unit_profit", "total_profit", "total_amount", "paid_amount", "settlement_status", "sale_datetime", "warranty_company", "warranty_start", "warranty_months", "warranty_days", "warranty_end", "specifications", "colors_json", "notes", "created_at", "updated_at", "row_version", "customer_id", "payment_type", "settlement_subtype", "check_due_date", "check_status"),
    "service_catalog": ("id", "code", "service_type", "name", "default_fee", "default_side_cost", "description", "is_active", "created_at", "updated_at", "row_version"),
    "service_price_history": ("id", "service_id", "change_date", "old_fee", "new_fee", "created_at", "updated_at"),
    "service_records": ("id", "invoice_number", "service_id", "seller_employee_id", "technician_employee_id", "service_type", "service_name", "customer_name", "historical_tariff", "service_fee", "side_cost", "paid_amount", "net_profit", "settlement_status", "service_datetime", "description", "created_at", "updated_at", "row_version", "settlement_subtype", "check_due_date", "check_status", "customer_phone", "customer_id", "payment_type"),
    "payments": ("id", "ref_type", "ref_id", "amount", "payment_date", "notes", "created_at", "updated_at", "row_version"),
    "audit_logs": ("id", "action_time", "action_type", "details", "created_at", "updated_at"),
    "installment_plans": ("id", "sale_id", "customer_id", "total_bill", "down_payment", "financed_amount", "installment_count", "interval_days", "start_due_date", "status", "notes", "last_modified_by", "last_modified_at", "created_at", "updated_at", "row_version", "first_installment_paid", "ref_type", "service_record_id"),
    "installment_payments": ("id", "plan_id", "installment_no", "due_date", "due_amount", "paid_amount", "paid_date", "status", "notes", "last_modified_by", "last_modified_at", "created_at", "updated_at", "row_version"),
    "supplier_installment_plans": ("id", "purchase_invoice_code", "batch_id", "supplier_id", "total_bill", "down_payment", "financed_amount", "installment_count", "interval_days", "start_due_date", "status", "notes", "last_modified_by", "last_modified_at", "created_at", "updated_at", "row_version", "first_installment_paid"),
    "supplier_installment_payments": ("id", "plan_id", "installment_no", "due_date", "due_amount", "paid_amount", "paid_date", "status", "notes", "last_modified_by", "last_modified_at", "created_at", "updated_at", "row_version"),
    "checks": ("id", "direction", "ref_type", "ref_id", "invoice_number", "customer_id", "supplier_id", "party_name", "party_phone", "check_number", "amount", "due_date", "status", "cleared_date", "notes", "last_modified_by", "last_modified_at", "created_at", "updated_at", "row_version"),
    "invoice_headers": ("id", "invoice_kind", "invoice_number", "party_id", "party_name", "party_phone", "operator_id", "total_amount", "paid_amount", "settlement_status", "settlement_subtype", "check_due_date", "check_status", "first_installment_paid", "item_count", "invoice_datetime", "notes", "last_modified_by", "last_modified_at", "created_at", "updated_at", "row_version", "extra_cost_total"),
    "proforma_invoices": ("id", "proforma_number", "customer_id", "customer_name", "customer_phone", "seller_employee_id", "proforma_datetime", "valid_until", "status", "converted_sale_invoice", "total_amount", "notes", "last_modified_by", "last_modified_at", "created_at", "updated_at", "row_version", "extra_cost_total", "payment_type", "settlement_status", "settlement_subtype", "paid_amount", "check_due_date", "check_status", "first_installment_paid", "installment_count", "installment_interval_days", "installment_start_due", "converted_service_invoice"),
    "proforma_items": ("id", "proforma_id", "line_no", "product_id", "batch_id", "qty", "suggested_unit_price", "actual_unit_price", "line_total", "serial_number", "warranty_company", "warranty_start", "warranty_months", "warranty_days", "warranty_end", "specifications", "colors_json", "notes", "created_at", "updated_at", "row_version", "item_kind", "service_id", "service_type", "service_name", "side_cost"),
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
                    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
                    phone TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    row_version INTEGER NOT NULL DEFAULT 1,
                    national_id TEXT DEFAULT '',
                    address TEXT DEFAULT '',
                    last_modified_by TEXT DEFAULT '',
                    last_modified_at TEXT DEFAULT ''
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
                    settlement_subtype TEXT NOT NULL DEFAULT '',
                    check_due_date TEXT DEFAULT '',
                    check_status TEXT DEFAULT '',
                    purchase_invoice_code TEXT NOT NULL DEFAULT '',
                    payment_type TEXT NOT NULL DEFAULT 'cash',
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
                    customer_id INTEGER,
                    payment_type TEXT NOT NULL DEFAULT 'cash'
                        CHECK (payment_type IN ('cash', 'check', 'installment', 'partial')),
                    settlement_subtype TEXT NOT NULL DEFAULT '',
                    check_due_date TEXT DEFAULT '',
                    check_status TEXT DEFAULT '',
                    FOREIGN KEY(product_id) REFERENCES products(id),
                    FOREIGN KEY(batch_id) REFERENCES batches(id),
                    FOREIGN KEY(seller_employee_id) REFERENCES employees(id),
                    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL
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
                    settlement_subtype TEXT NOT NULL DEFAULT '',
                    check_due_date TEXT DEFAULT '',
                    check_status TEXT DEFAULT '',
                    customer_phone TEXT DEFAULT '',
                    customer_id INTEGER,
                    payment_type TEXT NOT NULL DEFAULT 'cash'
                        CHECK (payment_type IN ('cash', 'check', 'installment', 'partial')),
                    FOREIGN KEY(service_id) REFERENCES service_catalog(id) ON DELETE SET NULL,
                    FOREIGN KEY(seller_employee_id) REFERENCES employees(id),
                    FOREIGN KEY(technician_employee_id) REFERENCES employees(id),
                    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL
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

            cur.execute("""
                CREATE TABLE IF NOT EXISTS installment_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sale_id INTEGER UNIQUE,
                    customer_id INTEGER,
                    total_bill INTEGER NOT NULL CHECK (total_bill >= 0),
                    down_payment INTEGER NOT NULL DEFAULT 0 CHECK (down_payment >= 0),
                    financed_amount INTEGER NOT NULL CHECK (financed_amount >= 0),
                    installment_count INTEGER NOT NULL CHECK (installment_count > 0),
                    interval_days INTEGER NOT NULL DEFAULT 30 CHECK (interval_days > 0),
                    start_due_date TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'completed', 'cancelled')),
                    notes TEXT DEFAULT '',
                    last_modified_by TEXT DEFAULT '',
                    last_modified_at TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    row_version INTEGER NOT NULL DEFAULT 1,
                    first_installment_paid INTEGER NOT NULL DEFAULT 0 CHECK (first_installment_paid IN (0, 1)),
                    ref_type TEXT NOT NULL DEFAULT 'sale' CHECK (ref_type IN ('sale', 'service')),
                    service_record_id INTEGER UNIQUE,
                    FOREIGN KEY(sale_id) REFERENCES sales(id) ON DELETE CASCADE,
                    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
                    FOREIGN KEY(service_record_id) REFERENCES service_records(id) ON DELETE CASCADE
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    direction TEXT NOT NULL DEFAULT 'receivable'
                        CHECK (direction IN ('receivable', 'payable')),
                    ref_type TEXT NOT NULL DEFAULT 'sale'
                        CHECK (ref_type IN ('sale', 'batch', 'service')),
                    ref_id INTEGER NOT NULL DEFAULT 0,
                    invoice_number TEXT NOT NULL DEFAULT '',
                    customer_id INTEGER,
                    supplier_id INTEGER,
                    party_name TEXT DEFAULT '',
                    party_phone TEXT DEFAULT '',
                    check_number TEXT DEFAULT '',
                    amount INTEGER NOT NULL CHECK (amount >= 0),
                    due_date TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'cleared', 'bounced')),
                    cleared_date TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    last_modified_by TEXT DEFAULT '',
                    last_modified_at TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    row_version INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL,
                    FOREIGN KEY(supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS invoice_headers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_kind TEXT NOT NULL CHECK (invoice_kind IN ('sale', 'batch', 'service')),
                    invoice_number TEXT NOT NULL,
                    party_id INTEGER,
                    party_name TEXT DEFAULT '',
                    party_phone TEXT DEFAULT '',
                    operator_id INTEGER,
                    total_amount INTEGER NOT NULL DEFAULT 0 CHECK (total_amount >= 0),
                    paid_amount INTEGER NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
                    settlement_status TEXT NOT NULL DEFAULT 'تسویه‌شده',
                    settlement_subtype TEXT NOT NULL DEFAULT '',
                    check_due_date TEXT DEFAULT '',
                    check_status TEXT DEFAULT '',
                    first_installment_paid INTEGER NOT NULL DEFAULT 0 CHECK (first_installment_paid IN (0, 1)),
                    item_count INTEGER NOT NULL DEFAULT 1 CHECK (item_count >= 1),
                    invoice_datetime TEXT NOT NULL DEFAULT '',
                    notes TEXT DEFAULT '',
                    last_modified_by TEXT DEFAULT '',
                    last_modified_at TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    row_version INTEGER NOT NULL DEFAULT 1,
                    extra_cost_total INTEGER NOT NULL DEFAULT 0 CHECK (extra_cost_total >= 0),
                    UNIQUE(invoice_kind, invoice_number)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS installment_payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id INTEGER NOT NULL,
                    installment_no INTEGER NOT NULL CHECK (installment_no > 0),
                    due_date TEXT NOT NULL,
                    due_amount INTEGER NOT NULL CHECK (due_amount >= 0),
                    paid_amount INTEGER NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
                    paid_date TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'partial', 'paid')),
                    notes TEXT DEFAULT '',
                    last_modified_by TEXT DEFAULT '',
                    last_modified_at TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    row_version INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(plan_id, installment_no),
                    FOREIGN KEY(plan_id) REFERENCES installment_plans(id) ON DELETE CASCADE
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS supplier_installment_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    purchase_invoice_code TEXT NOT NULL UNIQUE,
                    batch_id INTEGER NOT NULL,
                    supplier_id INTEGER NOT NULL,
                    total_bill INTEGER NOT NULL CHECK (total_bill >= 0),
                    down_payment INTEGER NOT NULL DEFAULT 0 CHECK (down_payment >= 0),
                    financed_amount INTEGER NOT NULL CHECK (financed_amount >= 0),
                    installment_count INTEGER NOT NULL CHECK (installment_count > 0),
                    interval_days INTEGER NOT NULL DEFAULT 30 CHECK (interval_days > 0),
                    start_due_date TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'completed', 'cancelled')),
                    notes TEXT DEFAULT '',
                    last_modified_by TEXT DEFAULT '',
                    last_modified_at TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    row_version INTEGER NOT NULL DEFAULT 1,
                    first_installment_paid INTEGER NOT NULL DEFAULT 0 CHECK (first_installment_paid IN (0, 1)),
                    FOREIGN KEY(batch_id) REFERENCES batches(id) ON DELETE CASCADE,
                    FOREIGN KEY(supplier_id) REFERENCES suppliers(id) ON DELETE CASCADE
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS supplier_installment_payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id INTEGER NOT NULL,
                    installment_no INTEGER NOT NULL CHECK (installment_no > 0),
                    due_date TEXT NOT NULL,
                    due_amount INTEGER NOT NULL CHECK (due_amount >= 0),
                    paid_amount INTEGER NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
                    paid_date TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'partial', 'paid')),
                    notes TEXT DEFAULT '',
                    last_modified_by TEXT DEFAULT '',
                    last_modified_at TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    row_version INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(plan_id, installment_no),
                    FOREIGN KEY(plan_id) REFERENCES supplier_installment_plans(id) ON DELETE CASCADE
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS proforma_invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proforma_number TEXT NOT NULL UNIQUE CHECK (length(trim(proforma_number)) > 0),
                    customer_id INTEGER,
                    customer_name TEXT DEFAULT '',
                    customer_phone TEXT DEFAULT '',
                    seller_employee_id INTEGER,
                    proforma_datetime TEXT NOT NULL,
                    valid_until TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'converted', 'cancelled')),
                    converted_sale_invoice TEXT DEFAULT '',
                    total_amount INTEGER NOT NULL DEFAULT 0 CHECK (total_amount >= 0),
                    notes TEXT DEFAULT '',
                    last_modified_by TEXT DEFAULT '',
                    last_modified_at TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    row_version INTEGER NOT NULL DEFAULT 1,
                    extra_cost_total INTEGER NOT NULL DEFAULT 0 CHECK (extra_cost_total >= 0),
                    payment_type TEXT NOT NULL DEFAULT 'cash'
                        CHECK (payment_type IN ('cash', 'check', 'installment', 'partial')),
                    settlement_status TEXT NOT NULL DEFAULT 'تسویه‌شده',
                    settlement_subtype TEXT NOT NULL DEFAULT 'تسویه نقدی',
                    paid_amount INTEGER NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
                    check_due_date TEXT DEFAULT '',
                    check_status TEXT DEFAULT '',
                    first_installment_paid INTEGER NOT NULL DEFAULT 0 CHECK (first_installment_paid IN (0, 1)),
                    installment_count INTEGER NOT NULL DEFAULT 1 CHECK (installment_count > 0),
                    installment_interval_days INTEGER NOT NULL DEFAULT 30 CHECK (installment_interval_days > 0),
                    installment_start_due TEXT DEFAULT '',
                    converted_service_invoice TEXT DEFAULT '',
                    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL,
                    FOREIGN KEY(seller_employee_id) REFERENCES employees(id) ON DELETE SET NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS proforma_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proforma_id INTEGER NOT NULL,
                    line_no INTEGER NOT NULL DEFAULT 1 CHECK (line_no > 0),
                    product_id INTEGER DEFAULT NULL,
                    batch_id INTEGER DEFAULT NULL,
                    qty INTEGER NOT NULL CHECK (qty > 0),
                    suggested_unit_price INTEGER NOT NULL DEFAULT 0 CHECK (suggested_unit_price >= 0),
                    actual_unit_price INTEGER NOT NULL CHECK (actual_unit_price >= 0),
                    line_total INTEGER NOT NULL CHECK (line_total >= 0),
                    serial_number TEXT DEFAULT '',
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
                    item_kind TEXT NOT NULL DEFAULT 'product' CHECK (item_kind IN ('product', 'service')),
                    service_id INTEGER DEFAULT NULL,
                    service_type TEXT DEFAULT '',
                    service_name TEXT DEFAULT '',
                    side_cost INTEGER NOT NULL DEFAULT 0 CHECK (side_cost >= 0),
                    FOREIGN KEY(proforma_id) REFERENCES proforma_invoices(id) ON DELETE CASCADE,
                    FOREIGN KEY(product_id) REFERENCES products(id),
                    FOREIGN KEY(batch_id) REFERENCES batches(id),
                    FOREIGN KEY(service_id) REFERENCES service_catalog(id) ON DELETE SET NULL
                )
            """)

            # Backward-compatible additive upgrade for existing v4 databases (row_version + v4.10.0 additive columns)
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
                additive_tail_columns = {
                    "customers": (
                        ("national_id", "TEXT DEFAULT ''"),
                        ("address", "TEXT DEFAULT ''"),
                        ("last_modified_by", "TEXT DEFAULT ''"),
                        ("last_modified_at", "TEXT DEFAULT ''"),
                    ),
                    "batches": (
                        ("settlement_subtype", "TEXT NOT NULL DEFAULT ''"),
                        ("check_due_date", "TEXT DEFAULT ''"),
                        ("check_status", "TEXT DEFAULT ''"),
                        ("purchase_invoice_code", "TEXT NOT NULL DEFAULT ''"),
                        ("payment_type", "TEXT NOT NULL DEFAULT 'cash'"),
                    ),
                    "sales": (
                        ("customer_id", "INTEGER REFERENCES customers(id) ON DELETE SET NULL"),
                        ("payment_type", "TEXT NOT NULL DEFAULT 'cash'"),
                        ("settlement_subtype", "TEXT NOT NULL DEFAULT ''"),
                        ("check_due_date", "TEXT DEFAULT ''"),
                        ("check_status", "TEXT DEFAULT ''"),
                    ),
                    "service_records": (
                        ("settlement_subtype", "TEXT NOT NULL DEFAULT ''"),
                        ("check_due_date", "TEXT DEFAULT ''"),
                        ("check_status", "TEXT DEFAULT ''"),
                        ("customer_phone", "TEXT DEFAULT ''"),
                        ("customer_id", "INTEGER REFERENCES customers(id) ON DELETE SET NULL"),
                        ("payment_type", "TEXT NOT NULL DEFAULT 'cash'"),
                    ),
                    "installment_plans": (
                        ("first_installment_paid", "INTEGER NOT NULL DEFAULT 0 CHECK (first_installment_paid IN (0, 1))"),
                    ),
                    "invoice_headers": (
                        ("extra_cost_total", "INTEGER NOT NULL DEFAULT 0 CHECK (extra_cost_total >= 0)"),
                    ),
                    "proforma_invoices": (
                        ("extra_cost_total", "INTEGER NOT NULL DEFAULT 0 CHECK (extra_cost_total >= 0)"),
                        ("payment_type", "TEXT NOT NULL DEFAULT 'cash'"),
                        ("settlement_status", "TEXT NOT NULL DEFAULT 'تسویه‌شده'"),
                        ("settlement_subtype", "TEXT NOT NULL DEFAULT 'تسویه نقدی'"),
                        ("paid_amount", "INTEGER NOT NULL DEFAULT 0 CHECK (paid_amount >= 0)"),
                        ("check_due_date", "TEXT DEFAULT ''"),
                        ("check_status", "TEXT DEFAULT ''"),
                        ("first_installment_paid", "INTEGER NOT NULL DEFAULT 0 CHECK (first_installment_paid IN (0, 1))"),
                        ("installment_count", "INTEGER NOT NULL DEFAULT 1 CHECK (installment_count > 0)"),
                        ("installment_interval_days", "INTEGER NOT NULL DEFAULT 30 CHECK (installment_interval_days > 0)"),
                        ("installment_start_due", "TEXT DEFAULT ''"),
                        ("converted_service_invoice", "TEXT DEFAULT ''"),
                    ),
                }
                for tbl_name, col_defs in additive_tail_columns.items():
                    if tbl_name in existing_tables:
                        cols_existing = {
                            row["name"]
                            for row in conn.execute(f"PRAGMA table_info({tbl_name})").fetchall()
                        }
                        for col_name, col_def in col_defs:
                            if col_name not in cols_existing:
                                conn.execute(
                                    f"ALTER TABLE {tbl_name} ADD COLUMN {col_name} {col_def}"
                                )
                # Upgrade sales table CHECK constraint on pre-v5.0.0 databases so payment_type='check' works natively.
                if "sales" in existing_tables:
                    sales_ddl_row = conn.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name='sales'"
                    ).fetchone()
                    sales_ddl = str(sales_ddl_row[0] if sales_ddl_row else "")
                    if sales_ddl and "'check'" not in sales_ddl:
                        conn.execute("PRAGMA foreign_keys = OFF")
                        try:
                            conn.execute("ALTER TABLE sales RENAME TO _sales_pre_v5")
                            conn.execute("""
                                CREATE TABLE sales (
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
                                    customer_id INTEGER,
                                    payment_type TEXT NOT NULL DEFAULT 'cash'
                                        CHECK (payment_type IN ('cash', 'check', 'installment', 'partial')),
                                    settlement_subtype TEXT NOT NULL DEFAULT '',
                                    check_due_date TEXT DEFAULT '',
                                    check_status TEXT DEFAULT '',
                                    FOREIGN KEY(product_id) REFERENCES products(id),
                                    FOREIGN KEY(batch_id) REFERENCES batches(id),
                                    FOREIGN KEY(seller_employee_id) REFERENCES employees(id),
                                    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL
                                )
                            """)
                            old_sales_cols = {
                                r["name"] for r in conn.execute("PRAGMA table_info(_sales_pre_v5)").fetchall()
                            }
                            common_sales_cols = ", ".join(
                                col for col in EXPECTED_SCHEMA_COLUMNS["sales"] if col in old_sales_cols
                            )
                            conn.execute(f"INSERT INTO sales ({common_sales_cols}) SELECT {common_sales_cols} FROM _sales_pre_v5")
                            conn.execute("DROP TABLE _sales_pre_v5")
                        finally:
                            conn.execute("PRAGMA foreign_keys = ON")

                # Upgrade installment_plans on pre-v5.0.2 databases to support nullable sale_id and service installments.
                if "installment_plans" in existing_tables:
                    ip_cols = {
                        r["name"] for r in conn.execute("PRAGMA table_info(installment_plans)").fetchall()
                    }
                    if "service_record_id" not in ip_cols:
                        conn.execute("PRAGMA foreign_keys = OFF")
                        try:
                            conn.execute("ALTER TABLE installment_plans RENAME TO _installment_plans_pre_v502")
                            conn.execute("""
                                CREATE TABLE installment_plans (
                                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    sale_id INTEGER UNIQUE,
                                    customer_id INTEGER,
                                    total_bill INTEGER NOT NULL CHECK (total_bill >= 0),
                                    down_payment INTEGER NOT NULL DEFAULT 0 CHECK (down_payment >= 0),
                                    financed_amount INTEGER NOT NULL CHECK (financed_amount >= 0),
                                    installment_count INTEGER NOT NULL CHECK (installment_count > 0),
                                    interval_days INTEGER NOT NULL DEFAULT 30 CHECK (interval_days > 0),
                                    start_due_date TEXT NOT NULL DEFAULT '',
                                    status TEXT NOT NULL DEFAULT 'active'
                                        CHECK (status IN ('active', 'completed', 'cancelled')),
                                    notes TEXT DEFAULT '',
                                    last_modified_by TEXT DEFAULT '',
                                    last_modified_at TEXT DEFAULT '',
                                    created_at TEXT NOT NULL DEFAULT '',
                                    updated_at TEXT NOT NULL DEFAULT '',
                                    row_version INTEGER NOT NULL DEFAULT 1,
                                    first_installment_paid INTEGER NOT NULL DEFAULT 0 CHECK (first_installment_paid IN (0, 1)),
                                    ref_type TEXT NOT NULL DEFAULT 'sale' CHECK (ref_type IN ('sale', 'service')),
                                    service_record_id INTEGER UNIQUE,
                                    FOREIGN KEY(sale_id) REFERENCES sales(id) ON DELETE CASCADE,
                                    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
                                    FOREIGN KEY(service_record_id) REFERENCES service_records(id) ON DELETE CASCADE
                                )
                            """)
                            common_ip_cols = ", ".join(
                                col for col in EXPECTED_SCHEMA_COLUMNS["installment_plans"] if col in ip_cols
                            )
                            conn.execute(
                                f"INSERT INTO installment_plans ({common_ip_cols}) SELECT {common_ip_cols} FROM _installment_plans_pre_v502"
                            )
                            conn.execute("DROP TABLE _installment_plans_pre_v502")
                        finally:
                            conn.execute("PRAGMA foreign_keys = ON")

                # Upgrade proforma_items on pre-v5.0.2 databases to support nullable product_id/batch_id and service lines.
                if "proforma_items" in existing_tables:
                    pfi_cols = {
                        r["name"] for r in conn.execute("PRAGMA table_info(proforma_items)").fetchall()
                    }
                    if "item_kind" not in pfi_cols:
                        conn.execute("PRAGMA foreign_keys = OFF")
                        try:
                            conn.execute("ALTER TABLE proforma_items RENAME TO _proforma_items_pre_v502")
                            conn.execute("""
                                CREATE TABLE proforma_items (
                                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    proforma_id INTEGER NOT NULL,
                                    line_no INTEGER NOT NULL DEFAULT 1 CHECK (line_no > 0),
                                    product_id INTEGER DEFAULT NULL,
                                    batch_id INTEGER DEFAULT NULL,
                                    qty INTEGER NOT NULL CHECK (qty > 0),
                                    suggested_unit_price INTEGER NOT NULL DEFAULT 0 CHECK (suggested_unit_price >= 0),
                                    actual_unit_price INTEGER NOT NULL CHECK (actual_unit_price >= 0),
                                    line_total INTEGER NOT NULL CHECK (line_total >= 0),
                                    serial_number TEXT DEFAULT '',
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
                                    item_kind TEXT NOT NULL DEFAULT 'product' CHECK (item_kind IN ('product', 'service')),
                                    service_id INTEGER DEFAULT NULL,
                                    service_type TEXT DEFAULT '',
                                    service_name TEXT DEFAULT '',
                                    side_cost INTEGER NOT NULL DEFAULT 0 CHECK (side_cost >= 0),
                                    FOREIGN KEY(proforma_id) REFERENCES proforma_invoices(id) ON DELETE CASCADE,
                                    FOREIGN KEY(product_id) REFERENCES products(id),
                                    FOREIGN KEY(batch_id) REFERENCES batches(id),
                                    FOREIGN KEY(service_id) REFERENCES service_catalog(id) ON DELETE SET NULL
                                )
                            """)
                            common_pfi_cols = ", ".join(
                                col for col in EXPECTED_SCHEMA_COLUMNS["proforma_items"] if col in pfi_cols
                            )
                            conn.execute(
                                f"INSERT INTO proforma_items ({common_pfi_cols}) SELECT {common_pfi_cols} FROM _proforma_items_pre_v502"
                            )
                            conn.execute("DROP TABLE _proforma_items_pre_v502")
                        finally:
                            conn.execute("PRAGMA foreign_keys = ON")

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
                "installment_plans", "installment_payments",
                "supplier_installment_plans", "supplier_installment_payments",
                "checks", "invoice_headers", "proforma_invoices", "proforma_items",
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
                "installment_plans", "installment_payments",
                "supplier_installment_plans", "supplier_installment_payments",
                "checks", "invoice_headers", "proforma_invoices", "proforma_items",
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
                "CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(name)",
                "CREATE INDEX IF NOT EXISTS idx_sales_customer_id ON sales(customer_id, sale_datetime DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_sales_payment_type ON sales(payment_type, sale_datetime DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_inst_plans_customer ON installment_plans(customer_id, status, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_inst_plans_sale ON installment_plans(sale_id)",
                "CREATE INDEX IF NOT EXISTS idx_inst_plans_service ON installment_plans(service_record_id)",
                "CREATE INDEX IF NOT EXISTS idx_inst_pay_plan ON installment_payments(plan_id, installment_no)",
                "CREATE INDEX IF NOT EXISTS idx_inst_pay_due ON installment_payments(status, due_date, id)",
                "CREATE INDEX IF NOT EXISTS idx_checks_dir_status_due ON checks(direction, status, due_date, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_checks_ref ON checks(ref_type, ref_id)",
                "CREATE INDEX IF NOT EXISTS idx_checks_invoice ON checks(invoice_number)",
                "CREATE INDEX IF NOT EXISTS idx_checks_customer ON checks(customer_id, status, due_date)",
                "CREATE INDEX IF NOT EXISTS idx_checks_supplier ON checks(supplier_id, status, due_date)",
                "CREATE INDEX IF NOT EXISTS idx_inv_headers_kind_num ON invoice_headers(invoice_kind, invoice_number)",
                "CREATE INDEX IF NOT EXISTS idx_inv_headers_datetime ON invoice_headers(invoice_datetime DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_batches_pinv ON batches(purchase_invoice_code, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_batches_invoice_num ON batches(invoice_number)",
                "CREATE INDEX IF NOT EXISTS idx_sup_inst_plans_sup ON supplier_installment_plans(supplier_id, status, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_sup_inst_plans_pinv ON supplier_installment_plans(purchase_invoice_code)",
                "CREATE INDEX IF NOT EXISTS idx_sup_inst_pay_plan ON supplier_installment_payments(plan_id, installment_no)",
                "CREATE INDEX IF NOT EXISTS idx_sup_inst_pay_due ON supplier_installment_payments(status, due_date, id)",
                "CREATE INDEX IF NOT EXISTS idx_proforma_num ON proforma_invoices(proforma_number)",
                "CREATE INDEX IF NOT EXISTS idx_proforma_status_dt ON proforma_invoices(status, proforma_datetime DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_proforma_items_pf ON proforma_items(proforma_id, line_no)",
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
            "batches": {"batch_code", "invoice_number", "purchase_invoice_code"},
            "sales": {"invoice_number"},
            "service_catalog": {"code"},
            "service_records": {"invoice_number"},
            "proforma_invoices": {"proforma_number"},
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
            kind_map = {
                ("sales", "invoice_number"): "sale",
                ("batches", "purchase_invoice_code"): "batch",
                ("batches", "invoice_number"): "batch",
                ("service_records", "invoice_number"): "service",
            }
            hdr_kind = kind_map.get((table, column))
            if hdr_kind:
                hrows = connection.execute(
                    "SELECT invoice_number FROM invoice_headers WHERE invoice_kind=? AND invoice_number LIKE ?",
                    (hdr_kind, f"{prefix}%"),
                ).fetchall()
                for row in hrows:
                    value = str(row[0] or "")[len(prefix):]
                    if value.isdigit():
                        max_num = max(max_num, int(value))
            if table == "batches" and column in ("purchase_invoice_code", "batch_code"):
                other_col = "batch_code" if column == "purchase_invoice_code" else "purchase_invoice_code"
                brows = connection.execute(
                    f"SELECT {other_col} FROM batches WHERE {other_col} LIKE ?",
                    (f"{prefix}%",),
                ).fetchall()
                for row in brows:
                    value = str(row[0] or "")[len(prefix):]
                    if value.isdigit():
                        max_num = max(max_num, int(value))
            return f"{prefix}{max_num + 1}"

        if conn is not None:
            return query_next(conn)
        with self.get_connection() as connection:
            return query_next(connection)

    def _next_available_invoice_code(self, conn, invoice_kind: str, field: str, prefix: str, start_num: int = 1001) -> str:
        """Allocate the next unused sequential code in a strict collision-free loop."""
        table_map = {
            "sale": "sales",
            "batch": "batches",
            "service": "service_records",
            "proforma": "proforma_invoices",
        }
        tbl = table_map[invoice_kind]
        if invoice_kind == "proforma":
            col = "proforma_number"
        elif field in ("batch_code", "purchase_invoice_code", "invoice_number"):
            col = field
        else:
            col = "invoice_number"
        candidate = self.generate_next_code(tbl, col, prefix, start_num, conn=conn)
        seq = int(candidate[len(prefix):]) if candidate.startswith(prefix) and candidate[len(prefix):].isdigit() else start_num
        while True:
            cand = f"{prefix}{seq}"
            exists_op = conn.execute(f"SELECT 1 FROM {tbl} WHERE {col}=? LIMIT 1", (cand,)).fetchone()
            exists_hdr = None
            exists_alt = None
            if col in ("invoice_number", "purchase_invoice_code") and invoice_kind in ("sale", "batch", "service"):
                exists_hdr = conn.execute(
                    "SELECT 1 FROM invoice_headers WHERE invoice_kind=? AND invoice_number=? LIMIT 1",
                    (invoice_kind, cand),
                ).fetchone()
            if invoice_kind == "batch" and col in ("purchase_invoice_code", "batch_code"):
                exists_alt = conn.execute(
                    "SELECT 1 FROM batches WHERE batch_code=? OR purchase_invoice_code=? LIMIT 1",
                    (cand, cand),
                ).fetchone()
            if not exists_op and not exists_hdr and not exists_alt:
                return cand
            seq += 1

    def _inspect_invoice_conflict(self, conn, invoice_kind: str, field: str, value: str) -> Optional[dict]:
        """Return live conflict metadata + row_version when an invoice/batch number already exists."""
        clean_val = str(value or "").strip()
        if not clean_val:
            return None
        hdr = None
        if field in ("invoice_number", "purchase_invoice_code"):
            hdr = conn.execute(
                "SELECT * FROM invoice_headers WHERE invoice_kind=? AND invoice_number=?",
                (invoice_kind, clean_val),
            ).fetchone()
        if invoice_kind == "sale":
            rows = conn.execute(
                """SELECT id, qty, total_amount, paid_amount, customer_name, settlement_status,
                          sale_datetime, row_version FROM sales WHERE invoice_number=? ORDER BY id ASC""",
                (clean_val,),
            ).fetchall()
            if not rows and not hdr:
                return None
            rv = int(hdr["row_version"]) if hdr else max(int(r["row_version"] or 1) for r in rows)
            return {
                "existing_version": rv,
                "summary": {
                    "party_name": (hdr["party_name"] if hdr else (rows[0]["customer_name"] if rows else "")) or "مشتری حضوری",
                    "total_amount": int(hdr["total_amount"]) if hdr else sum(int(r["total_amount"] or 0) for r in rows),
                    "paid_amount": int(hdr["paid_amount"]) if hdr else sum(int(r["paid_amount"] or 0) for r in rows),
                    "invoice_datetime": (hdr["invoice_datetime"] if hdr else (rows[0]["sale_datetime"] if rows else "")),
                    "item_count": len(rows) or (int(hdr["item_count"]) if hdr else 1),
                    "settlement_status": (hdr["settlement_status"] if hdr else (rows[0]["settlement_status"] if rows else "")),
                },
            }
        if invoice_kind == "service":
            rows = conn.execute(
                """SELECT id, service_fee, paid_amount, customer_name, settlement_status,
                          service_datetime, row_version FROM service_records WHERE invoice_number=? ORDER BY id ASC""",
                (clean_val,),
            ).fetchall()
            if not rows and not hdr:
                return None
            rv = int(hdr["row_version"]) if hdr else max(int(r["row_version"] or 1) for r in rows)
            return {
                "existing_version": rv,
                "summary": {
                    "party_name": (hdr["party_name"] if hdr else (rows[0]["customer_name"] if rows else "")) or "مشتری",
                    "total_amount": int(hdr["total_amount"]) if hdr else sum(int(r["service_fee"] or 0) for r in rows),
                    "paid_amount": int(hdr["paid_amount"]) if hdr else sum(int(r["paid_amount"] or 0) for r in rows),
                    "invoice_datetime": (hdr["invoice_datetime"] if hdr else (rows[0]["service_datetime"] if rows else "")),
                    "item_count": len(rows) or (int(hdr["item_count"]) if hdr else 1),
                    "settlement_status": (hdr["settlement_status"] if hdr else (rows[0]["settlement_status"] if rows else "")),
                },
            }
        if invoice_kind == "batch":
            where_col = (
                "batch_code" if field == "batch_code"
                else ("purchase_invoice_code" if field == "purchase_invoice_code" else "invoice_number")
            )
            rows = conn.execute(
                f"""SELECT id, batch_code, purchase_invoice_code, invoice_number, initial_qty, sold_qty, unit_purchase_price,
                           extra_cost_total, paid_amount, supplier_name_snapshot, settlement_status,
                           purchase_date, row_version
                    FROM batches WHERE {where_col}=? ORDER BY id ASC""",
                (clean_val,),
            ).fetchall()
            if not rows and not hdr:
                return None
            rv = int(hdr["row_version"]) if hdr else max(int(r["row_version"] or 1) for r in rows)
            total_b = sum(int(r["unit_purchase_price"] or 0) * int(r["initial_qty"] or 0) + int(r["extra_cost_total"] or 0) for r in rows)
            return {
                "existing_version": rv,
                "summary": {
                    "party_name": (hdr["party_name"] if hdr else (rows[0]["supplier_name_snapshot"] if rows else "")) or "تأمین‌کننده",
                    "total_amount": int(hdr["total_amount"]) if hdr else total_b,
                    "paid_amount": int(hdr["paid_amount"]) if hdr else sum(int(r["paid_amount"] or 0) for r in rows),
                    "invoice_datetime": (hdr["invoice_datetime"] if hdr else (rows[0]["purchase_date"] if rows else "")),
                    "item_count": len(rows) or (int(hdr["item_count"]) if hdr else 1),
                    "settlement_status": (hdr["settlement_status"] if hdr else (rows[0]["settlement_status"] if rows else "")),
                },
            }
        return None

    def _reverse_existing_invoice_tx(self, conn, invoice_kind: str, field: str, value: str) -> Optional[int]:
        """Atomically reverse all stock, check, payment, and installment side effects of an existing invoice."""
        clean_val = str(value or "").strip()
        prev_hdr = None
        if field in ("invoice_number", "purchase_invoice_code"):
            prev_hdr = conn.execute(
                "SELECT id, row_version FROM invoice_headers WHERE invoice_kind=? AND invoice_number=?",
                (invoice_kind, clean_val),
            ).fetchone()

        if invoice_kind == "sale":
            rows = conn.execute("SELECT id, batch_id, qty, row_version FROM sales WHERE invoice_number=?", (clean_val,)).fetchall()
            prev_ver = int(prev_hdr["row_version"]) if prev_hdr else (max(int(r["row_version"] or 1) for r in rows) if rows else 1)
            sale_ids = [int(r["id"]) for r in rows]
            for r in rows:
                upd = conn.execute(
                    "UPDATE batches SET sold_qty=sold_qty-?, remaining_qty=remaining_qty+? WHERE id=? AND sold_qty >= ?",
                    (int(r["qty"]), int(r["qty"]), int(r["batch_id"]), int(r["qty"])),
                )
                if upd.rowcount != 1:
                    raise ValueError("بازگشت موجودی فاکتور قبلی هنگام جایگزینی با ناسازگاری مواجه شد.")
            if sale_ids:
                marks = ",".join("?" for _ in sale_ids)
                conn.execute(
                    f"DELETE FROM installment_payments WHERE plan_id IN (SELECT id FROM installment_plans WHERE sale_id IN ({marks}))",
                    sale_ids,
                )
                conn.execute(f"DELETE FROM installment_plans WHERE sale_id IN ({marks})", sale_ids)
                conn.execute(f"DELETE FROM payments WHERE ref_type='sale' AND ref_id IN ({marks})", sale_ids)
                conn.execute(f"DELETE FROM checks WHERE ref_type='sale' AND ref_id IN ({marks})", sale_ids)
            conn.execute("DELETE FROM checks WHERE direction='receivable' AND ref_type='sale' AND invoice_number=?", (clean_val,))
            conn.execute("DELETE FROM sales WHERE invoice_number=?", (clean_val,))
            return prev_ver

        if invoice_kind == "service":
            rows = conn.execute("SELECT id, row_version FROM service_records WHERE invoice_number=?", (clean_val,)).fetchall()
            prev_ver = int(prev_hdr["row_version"]) if prev_hdr else (max(int(r["row_version"] or 1) for r in rows) if rows else 1)
            srv_ids = [int(r["id"]) for r in rows]
            if srv_ids:
                marks = ",".join("?" for _ in srv_ids)
                conn.execute(
                    f"DELETE FROM installment_payments WHERE plan_id IN (SELECT id FROM installment_plans WHERE service_record_id IN ({marks}))",
                    srv_ids,
                )
                conn.execute(f"DELETE FROM installment_plans WHERE service_record_id IN ({marks})", srv_ids)
                conn.execute(f"DELETE FROM payments WHERE ref_type='service' AND ref_id IN ({marks})", srv_ids)
                conn.execute(f"DELETE FROM checks WHERE ref_type='service' AND ref_id IN ({marks})", srv_ids)
            conn.execute("DELETE FROM checks WHERE direction='receivable' AND ref_type='service' AND invoice_number=?", (clean_val,))
            conn.execute("DELETE FROM service_records WHERE invoice_number=?", (clean_val,))
            return prev_ver

        if invoice_kind == "batch":
            where_col = (
                "batch_code" if field == "batch_code"
                else ("purchase_invoice_code" if field == "purchase_invoice_code" else "invoice_number")
            )
            rows = conn.execute(
                f"SELECT id, batch_code, purchase_invoice_code, sold_qty, returned_qty, row_version FROM batches WHERE {where_col}=?",
                (clean_val,),
            ).fetchall()
            prev_ver = int(prev_hdr["row_version"]) if prev_hdr else (max(int(r["row_version"] or 1) for r in rows) if rows else 1)
            batch_ids = [int(r["id"]) for r in rows]
            for r in rows:
                if int(r["sold_qty"] or 0) > 0 or int(r["returned_qty"] or 0) > 0:
                    raise ValueError(
                        f"محموله قبلی «{r['batch_code']}» دارای سابقه فروش است و جایگزینی خودکار آن مجاز نیست."
                    )
            if batch_ids:
                marks = ",".join("?" for _ in batch_ids)
                has_upg = conn.execute(
                    f"SELECT 1 FROM upgrades WHERE target_batch_id IN ({marks}) OR part_batch_id IN ({marks}) LIMIT 1",
                    (*batch_ids, *batch_ids),
                ).fetchone()
                if has_upg:
                    raise ValueError("محموله قبلی دارای سابقه ارتقا است و جایگزینی خودکار آن مجاز نیست.")
                conn.execute(
                    f"DELETE FROM supplier_installment_payments WHERE plan_id IN (SELECT id FROM supplier_installment_plans WHERE batch_id IN ({marks}))",
                    batch_ids,
                )
                conn.execute(f"DELETE FROM supplier_installment_plans WHERE batch_id IN ({marks})", batch_ids)
                conn.execute(f"DELETE FROM payments WHERE ref_type='batch' AND ref_id IN ({marks})", batch_ids)
                conn.execute(f"DELETE FROM checks WHERE ref_type='batch' AND ref_id IN ({marks})", batch_ids)
            conn.execute("DELETE FROM checks WHERE direction='payable' AND ref_type='batch' AND invoice_number=?", (clean_val,))
            conn.execute(f"DELETE FROM batches WHERE {where_col}=?", (clean_val,))
            return prev_ver
        return None

    def _resolve_or_raise_invoice_conflict_tx(
        self,
        conn,
        *,
        invoice_kind: str,
        field: str,
        value: str,
        prefix: str,
        start_num: int = 1001,
        conflict_resolution: Optional[str] = None,
        expected_existing_version: Optional[int] = None,
    ) -> Tuple[str, Optional[int]]:
        """Check and atomically resolve duplicate invoice/batch number conflict on LAN.

        Returns (resolved_number, bumped_version_if_replaced).
        """
        conflict = self._inspect_invoice_conflict(conn, invoice_kind, field, value)
        if not conflict:
            return value, None
        live_ver = int(conflict["existing_version"])
        res_mode = str(conflict_resolution or "").strip().lower()
        suggested = self._next_available_invoice_code(conn, invoice_kind, field, prefix, start_num)
        if res_mode == "next_number":
            return suggested, None
        if res_mode == "replace":
            if expected_existing_version is not None and int(expected_existing_version) != live_ver:
                raise DuplicateInvoiceConflictError(
                    invoice_kind=invoice_kind,
                    conflict_field=field,
                    duplicate_value=value,
                    suggested_next_number=suggested,
                    existing_version=live_ver,
                    existing_summary=conflict["summary"],
                    stale_replace=True,
                    message=(
                        f"شماره «{value}» پیش از تایید شما توسط سیستم دیگری دوباره تغییر یافت (نسخه {live_ver}). "
                        "لطفاً با اطلاعات جدید تصمیم‌گیری کنید."
                    ),
                )
            prev_ver = self._reverse_existing_invoice_tx(conn, invoice_kind, field, value)
            return value, (int(prev_ver or live_ver) + 1)
        raise DuplicateInvoiceConflictError(
            invoice_kind=invoice_kind,
            conflict_field=field,
            duplicate_value=value,
            suggested_next_number=suggested,
            existing_version=live_ver,
            existing_summary=conflict["summary"],
            stale_replace=False,
        )

    def _upsert_invoice_header_tx(
        self,
        conn,
        *,
        invoice_kind: str,
        invoice_number: str,
        party_id: Optional[int],
        party_name: str,
        party_phone: str,
        operator_id: Optional[int],
        total_amount: int,
        paid_amount: int,
        settlement_status: str,
        settlement_subtype: str,
        check_due_date: str,
        check_status: str,
        first_installment_paid: bool,
        item_count: int,
        invoice_datetime: str,
        notes: str = "",
        operator_name: str = "",
        forced_version: Optional[int] = None,
        extra_cost_total: int = 0,
    ) -> int:
        if not str(invoice_number or "").strip():
            return 0
        mod_at = time.strftime("%Y-%m-%d %H:%M:%S")
        mod_by = str(operator_name or "").strip()
        clean_extra = self._batch_integer(extra_cost_total, "هزینه جانبی کل")
        existing = conn.execute(
            "SELECT id, row_version FROM invoice_headers WHERE invoice_kind=? AND invoice_number=?",
            (invoice_kind, invoice_number),
        ).fetchone()
        if existing:
            new_ver = int(forced_version) if forced_version is not None else int(existing["row_version"] or 1) + 1
            conn.execute(
                """
                UPDATE invoice_headers SET
                    party_id=?, party_name=?, party_phone=?, operator_id=?,
                    total_amount=?, paid_amount=?, settlement_status=?, settlement_subtype=?,
                    check_due_date=?, check_status=?, first_installment_paid=?, item_count=?,
                    invoice_datetime=?, notes=?, last_modified_by=?, last_modified_at=?,
                    row_version=?, extra_cost_total=?
                WHERE id=?
                """,
                (
                    party_id, party_name, party_phone, operator_id,
                    int(total_amount), int(paid_amount), settlement_status, settlement_subtype,
                    check_due_date, check_status, 1 if first_installment_paid else 0, max(1, int(item_count)),
                    invoice_datetime, notes, mod_by, mod_at, new_ver, clean_extra, int(existing["id"]),
                ),
            )
            return int(existing["id"])
        cur = conn.execute(
            """
            INSERT INTO invoice_headers (
                invoice_kind, invoice_number, party_id, party_name, party_phone, operator_id,
                total_amount, paid_amount, settlement_status, settlement_subtype,
                check_due_date, check_status, first_installment_paid, item_count,
                invoice_datetime, notes, last_modified_by, last_modified_at, row_version, extra_cost_total
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invoice_kind, invoice_number, party_id, party_name, party_phone, operator_id,
                int(total_amount), int(paid_amount), settlement_status, settlement_subtype,
                check_due_date, check_status, 1 if first_installment_paid else 0, max(1, int(item_count)),
                invoice_datetime, notes, mod_by, mod_at, int(forced_version or 1), clean_extra,
            ),
        )
        return int(cur.lastrowid)

    def _record_check_tx(
        self,
        conn,
        *,
        direction: str,
        ref_type: str,
        ref_id: int,
        invoice_number: str,
        customer_id: Optional[int] = None,
        supplier_id: Optional[int] = None,
        party_name: str = "",
        party_phone: str = "",
        check_number: str = "",
        amount: int = 0,
        due_date: str = "",
        status: str = "pending",
        cleared_date: str = "",
        notes: str = "",
        operator_name: str = "",
    ) -> int:
        clean_status = str(status or "pending").strip().lower()
        if clean_status not in ("pending", "cleared", "bounced"):
            status_map = {
                "در انتظار وصول": "pending",
                "وصول شده": "cleared",
                "وصول‌شده": "cleared",
                "برگشتی": "bounced",
                "برگشت خورده": "bounced",
            }
            clean_status = status_map.get(str(status or "").strip(), "pending")
        mod_by = str(operator_name or "").strip()
        mod_at = time.strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute(
            """
            INSERT INTO checks (
                direction, ref_type, ref_id, invoice_number, customer_id, supplier_id,
                party_name, party_phone, check_number, amount, due_date, status, cleared_date,
                notes, last_modified_by, last_modified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                direction, ref_type, int(ref_id or 0), str(invoice_number or "").strip(),
                customer_id, supplier_id, str(party_name or "").strip(), str(party_phone or "").strip(),
                str(check_number or "").strip(), max(0, int(amount)), str(due_date or "").strip(),
                clean_status, str(cleared_date or "").strip(), str(notes or "").strip(), mod_by, mod_at,
            ),
        )
        return int(cur.lastrowid)

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
                code = self.generate_next_code("products", "code", "SKU-", 1001, conn=conn)
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
            "SELECT id,batch_id,qty,invoice_number FROM sales WHERE " + " OR ".join(clauses) + " ORDER BY updated_at DESC, id DESC",
            params,
        ).fetchall()
        removed_batches = set(batch_ids)
        touched_invoices = set()
        for sale in rows:
            if sale["batch_id"] not in removed_batches:
                conn.execute(
                    """UPDATE batches SET sold_qty=MAX(0,sold_qty-?),
                       remaining_qty=remaining_qty+? WHERE id=?""",
                    (sale["qty"], sale["qty"], sale["batch_id"]),
                )
            conn.execute(
                "DELETE FROM installment_payments WHERE plan_id IN (SELECT id FROM installment_plans WHERE sale_id=?)",
                (sale["id"],),
            )
            conn.execute("DELETE FROM installment_plans WHERE sale_id=?", (sale["id"],))
            conn.execute("DELETE FROM payments WHERE ref_type='sale' AND ref_id=?", (sale["id"],))
            conn.execute("DELETE FROM checks WHERE ref_type='sale' AND ref_id=?", (sale["id"],))
            conn.execute("DELETE FROM sales WHERE id=?", (sale["id"],))
            if str(sale["invoice_number"] or "").strip():
                touched_invoices.add(str(sale["invoice_number"]).strip())
        for inv_no in touched_invoices:
            rem_cnt = conn.execute(
                "SELECT COUNT(*) FROM sales WHERE invoice_number=?",
                (inv_no,),
            ).fetchone()[0]
            if int(rem_cnt or 0) == 0:
                conn.execute("DELETE FROM checks WHERE ref_type='sale' AND invoice_number=?", (inv_no,))
                conn.execute("DELETE FROM invoice_headers WHERE invoice_kind='sale' AND invoice_number=?", (inv_no,))

    def _hard_delete_batches(self, conn, batch_ids):
        batch_ids = list(dict.fromkeys(int(value) for value in batch_ids))
        if not batch_ids:
            return
        self._delete_linked_upgrades(conn, batch_ids=batch_ids)
        self._delete_linked_sales(conn, batch_ids=batch_ids)
        marks = ",".join("?" for _ in batch_ids)
        b_rows = conn.execute(
            f"SELECT id, batch_code, invoice_number, purchase_invoice_code FROM batches WHERE id IN ({marks})",
            batch_ids,
        ).fetchall()
        pinv_codes = {str(r["purchase_invoice_code"] or "").strip() for r in b_rows if str(r["purchase_invoice_code"] or "").strip()}
        inv_codes = {str(r["invoice_number"] or "").strip() for r in b_rows if str(r["invoice_number"] or "").strip()}
        batch_codes = {str(r["batch_code"] or "").strip() for r in b_rows if str(r["batch_code"] or "").strip()}
        conn.execute(
            f"DELETE FROM supplier_installment_payments WHERE plan_id IN (SELECT id FROM supplier_installment_plans WHERE batch_id IN ({marks}))",
            batch_ids,
        )
        conn.execute(f"DELETE FROM supplier_installment_plans WHERE batch_id IN ({marks})", batch_ids)
        conn.execute(
            f"DELETE FROM payments WHERE ref_type='batch' AND ref_id IN ({marks})",
            batch_ids,
        )
        conn.execute(
            f"DELETE FROM checks WHERE ref_type='batch' AND ref_id IN ({marks})",
            batch_ids,
        )
        conn.execute(f"DELETE FROM proforma_items WHERE batch_id IN ({marks})", batch_ids)
        conn.execute(f"DELETE FROM batches WHERE id IN ({marks})", batch_ids)
        for pcode in pinv_codes:
            rem_p = conn.execute(
                "SELECT COUNT(*) FROM batches WHERE purchase_invoice_code=?",
                (pcode,),
            ).fetchone()[0]
            if int(rem_p or 0) == 0:
                conn.execute(
                    "DELETE FROM supplier_installment_payments WHERE plan_id IN (SELECT id FROM supplier_installment_plans WHERE purchase_invoice_code=?)",
                    (pcode,),
                )
                conn.execute("DELETE FROM supplier_installment_plans WHERE purchase_invoice_code=?", (pcode,))
                conn.execute("DELETE FROM checks WHERE ref_type='batch' AND invoice_number=?", (pcode,))
                conn.execute("DELETE FROM invoice_headers WHERE invoice_kind='batch' AND invoice_number=?", (pcode,))
        for icode in inv_codes | batch_codes:
            rem_i = conn.execute(
                "SELECT COUNT(*) FROM batches WHERE invoice_number=? OR batch_code=? OR purchase_invoice_code=?",
                (icode, icode, icode),
            ).fetchone()[0]
            if int(rem_i or 0) == 0:
                conn.execute("DELETE FROM checks WHERE ref_type='batch' AND invoice_number=?", (icode,))
                conn.execute("DELETE FROM invoice_headers WHERE invoice_kind='batch' AND invoice_number=?", (icode,))

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
            if not delete_related_data:
                active_plan = conn.execute(
                    "SELECT id FROM supplier_installment_plans WHERE supplier_id=? AND status='active' LIMIT 1",
                    (sup_id,),
                ).fetchone()
                if active_plan:
                    raise ValueError(
                        "این تأمین‌کننده دارای طرح خرید اقساطی فعال است. ابتدا اقساط تسویه یا با حذف سوابق اقدام کنید."
                    )
            batch_rows = conn.execute(
                "SELECT id FROM batches WHERE supplier_id=?", (sup_id,)
            ).fetchall()
            batch_ids = [int(row["id"]) for row in batch_rows]
            if delete_related_data:
                self._hard_delete_batches(conn, batch_ids)
                conn.execute("UPDATE checks SET supplier_id=NULL WHERE supplier_id=?", (sup_id,))
            else:
                conn.execute(
                    """UPDATE batches
                       SET supplier_name_snapshot=?, supplier_id=NULL
                       WHERE supplier_id=?""",
                    (supplier["name"], sup_id),
                )
                conn.execute("UPDATE checks SET supplier_id=NULL WHERE supplier_id=?", (sup_id,))
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
        settlement_subtype="",
        check_due_date="",
        check_status="pending",
        operator_name="",
        conflict_resolution=None,
        expected_existing_version=None,
        enforce_unique_invoice=False,
        purchase_invoice_code="",
        payment_type="cash",
        installment_plan=None,
    ):
        """Create a purchase shipment and all linked records atomically."""
        return self.add_purchase_invoice(
            invoice_number,
            [
                {
                    "batch_code": batch_code,
                    "product_id": product_id,
                    "initial_qty": initial_qty,
                    "unit_purchase_price": unit_purchase_price,
                    "extra_cost_total": extra_cost_total,
                    "suggested_sell_price": suggested_sell_price,
                    "serial_numbers": serial_numbers,
                    "initial_specs": initial_specs,
                    "colors": colors,
                    "notes": notes,
                }
            ],
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            buyer_employee_id=buyer_employee_id,
            purchase_date=purchase_date,
            purchase_time=purchase_time,
            settlement_status=settlement_status,
            settlement_subtype=settlement_subtype,
            paid_amount=paid_amount,
            check_due_date=check_due_date,
            check_status=check_status,
            operator_name=operator_name,
            conflict_resolution=conflict_resolution,
            expected_existing_version=expected_existing_version,
            enforce_unique_invoice=enforce_unique_invoice,
            return_invoice_number=False,
            purchase_invoice_code=purchase_invoice_code,
            payment_type=payment_type,
            installment_plan=installment_plan,
        )

    def _create_supplier_installment_plan_tx(
        self,
        conn,
        *,
        purchase_invoice_code: str,
        batch_id: int,
        supplier_id: int,
        total_bill: int,
        down_payment: int,
        count: int,
        start_due_date: str,
        interval_days: int = 30,
        notes: str = "",
        operator_name: str = "",
        cal_type: Optional[str] = None,
        first_installment_paid: bool = False,
        purchase_date: str = "",
    ) -> dict:
        financed = self._sqlite_integer(total_bill - down_payment, "مبلغ باقی‌مانده اقساط خرید")
        if financed <= 0:
            raise ValueError("مبلغ تقسیط‌شده خرید باید بیشتر از صفر باشد.")
        schedule = self.build_installment_schedule(
            financed_amount=financed,
            count=count,
            start_due_date=start_due_date,
            interval_days=interval_days,
            cal_type=cal_type,
        )
        mod_by = str(operator_name or "").strip()
        mod_at = time.strftime("%Y-%m-%d %H:%M:%S")
        first_paid_flag = bool(first_installment_paid)
        first_paid_amt = int(schedule[0]["due_amount"]) if (first_paid_flag and schedule) else 0
        paid_date_first = str(purchase_date or start_due_date or "").split(" ")[0].strip()
        plan_status = "completed" if (first_paid_flag and len(schedule) == 1) else "active"
        cur = conn.execute(
            """
            INSERT INTO supplier_installment_plans (
                purchase_invoice_code, batch_id, supplier_id, total_bill, down_payment,
                financed_amount, installment_count, interval_days, start_due_date, status,
                notes, last_modified_by, last_modified_at, first_installment_paid
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                purchase_invoice_code,
                int(batch_id),
                int(supplier_id),
                int(total_bill),
                int(down_payment),
                int(financed),
                int(count),
                int(interval_days),
                start_due_date,
                plan_status,
                notes,
                mod_by,
                mod_at,
                1 if first_paid_flag else 0,
            ),
        )
        plan_id = int(cur.lastrowid)
        rows_to_insert = []
        for idx, item in enumerate(schedule):
            is_first_paid = (idx == 0 and first_paid_flag)
            rows_to_insert.append((
                plan_id,
                item["installment_no"],
                item["due_date"],
                item["due_amount"],
                item["due_amount"] if is_first_paid else 0,
                paid_date_first if is_first_paid else "",
                "paid" if is_first_paid else "pending",
                "پرداخت قسط اول هنگام ثبت خرید" if is_first_paid else "",
                mod_by,
                mod_at,
            ))
        conn.executemany(
            """
            INSERT INTO supplier_installment_payments (
                plan_id, installment_no, due_date, due_amount, paid_amount, paid_date,
                status, notes, last_modified_by, last_modified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows_to_insert,
        )
        return {
            "plan_id": plan_id,
            "first_paid_amount": first_paid_amt,
            "plan_status": plan_status,
        }

    def add_purchase_invoice(
        self,
        invoice_number,
        items,
        *,
        purchase_invoice_code="",
        supplier_id=None,
        supplier_name=None,
        buyer_employee_id=None,
        purchase_date="",
        purchase_time="",
        settlement_status=None,
        settlement_subtype="تسویه نقدی",
        paid_amount=0,
        payment_type="cash",
        check_due_date="",
        check_status="pending",
        installment_plan=None,
        extra_cost_total=None,
        notes="",
        operator_name="",
        conflict_resolution=None,
        expected_existing_version=None,
        enforce_unique_invoice=True,
        return_invoice_number=True,
    ):
        """Atomically record a 1-item or multi-item purchase invoice grouped by PINV- code."""
        if not items or not isinstance(items, (list, tuple)):
            raise ValueError("حداقل یک قلم کالا برای ثبت خرید لازم است.")
        supplier_id = self._batch_optional_id(supplier_id, "تأمین‌کننده")
        buyer_employee_id = self._batch_optional_id(buyer_employee_id, "مسئول خرید")
        purchase_date = str(purchase_date or "").strip()
        if not purchase_date:
            raise ValueError("تاریخ خرید وارد نشده است.")
        purchase_time_arg = str(purchase_time or "").strip()
        if purchase_time_arg and " " not in purchase_date:
            purchase_date = f"{purchase_date} {purchase_time_arg}"
        purchase_payment_date = purchase_date.split(" ", 1)[0].strip()
        invoice_number = str(invoice_number or "").strip()
        p_inv_input = str(purchase_invoice_code or "").strip()
        clean_subtype = str(settlement_subtype or "").strip()
        resolved_payment_type = str(payment_type or "cash").strip().lower()
        if installment_plan:
            resolved_payment_type = "installment"
        elif clean_subtype == "تسویه چکی":
            resolved_payment_type = "check"
        elif resolved_payment_type not in ("cash", "check", "installment", "partial"):
            resolved_payment_type = "cash"
        if str(settlement_status or "").strip() == "تسویه‌شده" and resolved_payment_type == "cash" and clean_subtype not in ("تسویه نقدی", "تسویه چکی", ""):
            clean_subtype = "تسویه نقدی"
        if resolved_payment_type != "check" and clean_subtype == "تسویه چکی":
            clean_subtype = ""
        clean_chk_due = str(check_due_date or "").strip() if resolved_payment_type == "check" else ""
        clean_chk_status = (
            ("cleared" if str(check_status or "").strip().lower() in ("cleared", "وصول شده", "وصول‌شده")
             else ("bounced" if str(check_status or "").strip().lower() in ("bounced", "برگشتی", "برگشت خورده") else "pending"))
            if resolved_payment_type == "check" else ""
        )
        first_inst_paid = False
        if installment_plan:
            down_p = self._batch_integer(
                installment_plan.get("down_payment", paid_amount),
                "پیش‌پرداخت",
            )
            inst_count = self._batch_integer(
                installment_plan.get("count", 1),
                "تعداد اقساط",
                minimum=1,
            )
            inst_interval = self._batch_integer(
                installment_plan.get("interval_days", 30),
                "فاصله اقساط (روز)",
                minimum=1,
            )
            inst_start_due = str(
                installment_plan.get("start_due_date") or purchase_payment_date
            ).strip()
            if not inst_start_due:
                raise ValueError("تاریخ سررسید قسط اول مشخص نشده است.")
            first_inst_paid = bool(installment_plan.get("first_installment_paid", False))
            paid_amount = down_p

        hdr_extra_cost = (
            self._batch_integer(extra_cost_total, "هزینه جانبی کل")
            if extra_cost_total is not None
            else 0
        )
        prepared_items = []
        total_invoice_bill = 0
        for raw_item in items:
            pid = self._batch_integer(raw_item.get("product_id"), "کالا", minimum=1)
            iqty = self._batch_integer(raw_item.get("initial_qty"), "تعداد خرید", minimum=1)
            u_buy = self._batch_integer(raw_item.get("unit_purchase_price"), "قیمت خرید واحد")
            # REQ-07: when invoice-level extra_cost_total is specified, store it once on invoice_headers (0 per line)
            e_cost = (
                0
                if extra_cost_total is not None
                else self._batch_integer(raw_item.get("extra_cost_total", 0), "هزینه جانبی کل")
            )
            s_sell = self._batch_integer(raw_item.get("suggested_sell_price"), "قیمت فروش پیشنهادی")
            e_per_u = round_integer_division(e_cost, iqty)
            u_cost = self._batch_integer(u_buy + e_per_u, "بهای تمام‌شده واحد")
            pct = round(((s_sell - u_cost) / u_cost) * 100, 2) if u_cost > 0 else 0.0
            line_bill = self._sqlite_integer(u_buy * iqty + e_cost, "بهای کل محموله")
            total_invoice_bill = self._sqlite_integer(total_invoice_bill + line_bill, "جمع کل فاکتور خرید")
            prepared_items.append({
                "batch_code": str(raw_item.get("batch_code") or "").strip(),
                "product_id": pid,
                "initial_qty": iqty,
                "unit_purchase_price": u_buy,
                "extra_cost_total": e_cost,
                "suggested_sell_price": s_sell,
                "unit_cost_price": u_cost,
                "profit_pct": pct,
                "line_bill": line_bill,
                "serial_numbers": str(raw_item.get("serial_numbers") or "").strip(),
                "initial_specs": str(raw_item.get("initial_specs") or "").strip(),
                "notes": str(raw_item.get("notes") or notes or "").strip(),
                "color_json": json.dumps(self._normalize_color_list(raw_item.get("colors")) or [], ensure_ascii=False),
            })
        if hdr_extra_cost > 0:
            total_invoice_bill = self._sqlite_integer(total_invoice_bill + hdr_extra_cost, "جمع کل فاکتور خرید با هزینه جانبی")

        if resolved_payment_type == "check" and not clean_chk_due:
            raise ValueError("برای تسویه چکی، تاریخ سررسید چک باید مشخص شود.")

        if resolved_payment_type == "check":
            total_paid_val = total_invoice_bill
            inv_status = "تسویه‌شده"
        elif installment_plan:
            total_paid_val = self._batch_integer(paid_amount, "پیش‌پرداخت")
            if total_paid_val > total_invoice_bill:
                raise ValueError("پیش‌پرداخت نمی‌تواند از مبلغ کل فاکتور خرید بیشتر باشد.")
            if total_invoice_bill - total_paid_val <= 0:
                raise ValueError("برای خرید اقساطی باید مبلغی پس از پیش‌پرداخت باقی بماند.")
            inv_status = "تسویه جزئی" if total_paid_val > 0 else "تسویه‌نشده"
        else:
            total_paid_val, inv_status = self._purchase_settlement(total_invoice_bill, paid_amount)

        def _tx(conn):
            nonlocal supplier_id, invoice_number, p_inv_input
            bumped_ver = None
            explicit_pinv = bool(p_inv_input)
            if explicit_pinv and (enforce_unique_invoice or conflict_resolution):
                p_inv_input, bumped_ver = self._resolve_or_raise_invoice_conflict_tx(
                    conn,
                    invoice_kind="batch",
                    field="purchase_invoice_code",
                    value=p_inv_input,
                    prefix="PINV-",
                    start_num=1001,
                    conflict_resolution=conflict_resolution,
                    expected_existing_version=expected_existing_version,
                )
            elif not explicit_pinv:
                p_inv_input = self._next_available_invoice_code(
                    conn, "batch", "purchase_invoice_code", "PINV-", 1001
                )
                if invoice_number and (enforce_unique_invoice or conflict_resolution):
                    invoice_number, bumped_ver = self._resolve_or_raise_invoice_conflict_tx(
                        conn,
                        invoice_kind="batch",
                        field="invoice_number",
                        value=invoice_number,
                        prefix="PINV-",
                        start_num=1001,
                        conflict_resolution=conflict_resolution,
                        expected_existing_version=expected_existing_version,
                    )

            if supplier_id is None and str(supplier_name or "").strip():
                supplier_id = self.get_or_create_supplier(supplier_name, conn=conn)
            if installment_plan and supplier_id is None:
                raise ValueError("برای خرید اقساطی، انتخاب یا ثبت تأمین‌کننده الزامی است.")
            supplier_row = conn.execute(
                "SELECT name, phone FROM suppliers WHERE id=?", (supplier_id,)
            ).fetchone() if supplier_id is not None else None
            supplier_snapshot = supplier_row["name"] if supplier_row else ""
            supplier_phone = (supplier_row["phone"] if supplier_row else "") or ""

            allocated_batch_codes = []
            inserted_batches = []
            for idx, item in enumerate(prepared_items):
                bcode = item["batch_code"]
                if not bcode:
                    base_b = p_inv_input
                    cand = base_b if (len(prepared_items) == 1 and idx == 0) else f"{base_b}-{idx + 1}"
                    if cand in allocated_batch_codes or conn.execute("SELECT 1 FROM batches WHERE batch_code=? LIMIT 1", (cand,)).fetchone():
                        bcode = self._next_available_invoice_code(conn, "batch", "batch_code", "PINV-", 1001)
                    else:
                        bcode = cand
                elif len(prepared_items) == 1 and not explicit_pinv:
                    bcode, bcode_bumped = self._resolve_or_raise_invoice_conflict_tx(
                        conn,
                        invoice_kind="batch",
                        field="batch_code",
                        value=bcode,
                        prefix="PINV-",
                        start_num=1001,
                        conflict_resolution=conflict_resolution,
                        expected_existing_version=expected_existing_version if not invoice_number else None,
                    )
                    if bumped_ver is None and bcode_bumped is not None:
                        bumped_ver = bcode_bumped
                while bcode in allocated_batch_codes or conn.execute("SELECT 1 FROM batches WHERE batch_code=? LIMIT 1", (bcode,)).fetchone():
                    bcode = self._next_available_invoice_code(conn, "batch", "batch_code", "PINV-", 1001)

                cursor = conn.execute(
                    """
                    INSERT INTO batches (
                        batch_code, product_id, supplier_id, buyer_employee_id, invoice_number,
                        purchase_date, initial_qty, sold_qty, returned_qty, remaining_qty,
                        unit_purchase_price, extra_cost_total, upgrade_cost_unit, unit_cost_price,
                        suggested_sell_price, profit_pct, settlement_status, paid_amount,
                        serial_numbers, initial_specs, final_specs, notes, supplier_name_snapshot,
                        colors_json, settlement_subtype, check_due_date, check_status,
                        purchase_invoice_code, payment_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        bcode, item["product_id"], supplier_id, buyer_employee_id, invoice_number,
                        purchase_date, item["initial_qty"], item["initial_qty"], item["unit_purchase_price"],
                        item["extra_cost_total"], item["unit_cost_price"], item["suggested_sell_price"], item["profit_pct"],
                        inv_status, 0, item["serial_numbers"], item["initial_specs"], item["initial_specs"],
                        item["notes"], supplier_snapshot, item["color_json"],
                        clean_subtype, clean_chk_due, clean_chk_status,
                        p_inv_input, resolved_payment_type,
                    ),
                )
                bid = int(cursor.lastrowid)
                allocated_batch_codes.append(bcode)
                inserted_batches.append({"id": bid, "line_bill": item["line_bill"]})

            first_batch_id = inserted_batches[0]["id"]
            first_inst_paid_amt = 0
            if installment_plan:
                plan_res = self._create_supplier_installment_plan_tx(
                    conn=conn,
                    purchase_invoice_code=p_inv_input,
                    batch_id=first_batch_id,
                    supplier_id=int(supplier_id),
                    total_bill=total_invoice_bill,
                    down_payment=total_paid_val,
                    count=inst_count,
                    start_due_date=inst_start_due,
                    interval_days=inst_interval,
                    notes=str(installment_plan.get("notes") or "").strip(),
                    operator_name=operator_name,
                    cal_type=installment_plan.get("cal_type") or self.cfg.get("calendar_type", "jalali"),
                    first_installment_paid=first_inst_paid,
                    purchase_date=purchase_payment_date,
                )
                first_inst_paid_amt = int(plan_res.get("first_paid_amount") or 0)

            final_paid_total = min(total_invoice_bill, total_paid_val + first_inst_paid_amt)
            if resolved_payment_type == "check":
                final_status = "تسویه‌شده"
            elif installment_plan:
                final_status = (
                    "تسویه‌شده" if final_paid_total >= total_invoice_bill
                    else ("تسویه جزئی" if final_paid_total > 0 else "تسویه‌نشده")
                )
            else:
                final_status = inv_status

            rem_paid = final_paid_total
            for idx, brow in enumerate(inserted_batches):
                if final_paid_total >= total_invoice_bill:
                    line_paid = brow["line_bill"]
                    line_status = "تسویه‌شده"
                elif final_paid_total == 0:
                    line_paid = 0
                    line_status = "تسویه‌نشده"
                else:
                    line_paid = min(brow["line_bill"], rem_paid)
                    rem_paid = max(0, rem_paid - line_paid)
                    line_status = (
                        "تسویه‌شده" if line_paid >= brow["line_bill"]
                        else ("تسویه‌نشده" if line_paid == 0 else "تسویه جزئی")
                    )
                conn.execute(
                    "UPDATE batches SET paid_amount=?, settlement_status=? WHERE id=?",
                    (line_paid, line_status, brow["id"]),
                )
                if line_paid > 0 and resolved_payment_type != "check":
                    note_txt = (
                        "پیش‌پرداخت / قسط اول خرید اقساطی" if installment_plan
                        else "پرداخت اولیه هنگام ثبت خرید"
                    )
                    conn.execute(
                        """
                        INSERT INTO payments (ref_type, ref_id, amount, payment_date, notes)
                        VALUES ('batch', ?, ?, ?, ?)
                        """,
                        (brow["id"], line_paid, purchase_payment_date, note_txt),
                    )

            hdr_inv_no = p_inv_input if (explicit_pinv or not invoice_number) else invoice_number
            if resolved_payment_type == "check" and first_batch_id is not None:
                self._record_check_tx(
                    conn,
                    direction="payable",
                    ref_type="batch",
                    ref_id=first_batch_id,
                    invoice_number=hdr_inv_no,
                    supplier_id=supplier_id,
                    party_name=supplier_snapshot,
                    party_phone=supplier_phone,
                    amount=total_invoice_bill,
                    due_date=clean_chk_due,
                    status=clean_chk_status or "pending",
                    cleared_date=purchase_payment_date if clean_chk_status == "cleared" else "",
                    notes=str(notes or "").strip(),
                    operator_name=operator_name,
                )

            self._upsert_invoice_header_tx(
                conn,
                invoice_kind="batch",
                invoice_number=hdr_inv_no,
                party_id=supplier_id,
                party_name=supplier_snapshot,
                party_phone=supplier_phone,
                operator_id=buyer_employee_id,
                total_amount=total_invoice_bill,
                paid_amount=final_paid_total,
                settlement_status=final_status,
                settlement_subtype=clean_subtype,
                check_due_date=clean_chk_due,
                check_status=clean_chk_status,
                first_installment_paid=first_inst_paid,
                item_count=len(prepared_items),
                invoice_datetime=purchase_date,
                notes=str(notes or "").strip(),
                operator_name=operator_name,
                forced_version=bumped_ver,
                extra_cost_total=hdr_extra_cost,
            )

            self.log_audit(
                conn,
                "ثبت خرید",
                f"شناسه فاکتور خرید: {p_inv_input} | فاکتور تأمین‌کننده: {invoice_number or '-'} | اقلام: {len(allocated_batch_codes)}",
            )
            if return_invoice_number:
                return hdr_inv_no
            return allocated_batch_codes[0]

        return self.run_write_transaction(_tx)

    def get_purchase_invoice_detail(self, ref_or_batch_id) -> Optional[dict]:
        """Return invoice header + all sibling line items for a purchase invoice or single batch ID."""
        with self.get_connection() as conn:
            row = None
            if isinstance(ref_or_batch_id, int) or str(ref_or_batch_id).strip().isdigit():
                row = conn.execute(
                    "SELECT id, purchase_invoice_code, invoice_number, batch_code FROM batches WHERE id=?",
                    (int(ref_or_batch_id),),
                ).fetchone()
            if not row:
                code = str(ref_or_batch_id or "").strip()
                if not code:
                    return None
                row = conn.execute(
                    "SELECT id, purchase_invoice_code, invoice_number, batch_code FROM batches WHERE purchase_invoice_code=? OR batch_code=? OR invoice_number=? ORDER BY id ASC LIMIT 1",
                    (code, code, code),
                ).fetchone()
            if not row:
                return None
            pinv = str(row["purchase_invoice_code"] or "").strip()
            inv_no = str(row["invoice_number"] or "").strip()
            if pinv:
                items = conn.execute(
                    """
                    SELECT b.*, p.code AS product_code, p.name AS product_name,
                           p.category AS product_category, p.sub_category AS product_sub_category,
                           p.brand AS product_brand, p.model AS product_model,
                           COALESCE(sup.name, b.supplier_name_snapshot) AS supplier_name
                    FROM batches b
                    LEFT JOIN products p ON p.id = b.product_id
                    LEFT JOIN suppliers sup ON sup.id = b.supplier_id
                    WHERE b.purchase_invoice_code=?
                    ORDER BY b.id ASC
                    """,
                    (pinv,),
                ).fetchall()
            elif inv_no:
                items = conn.execute(
                    """
                    SELECT b.*, p.code AS product_code, p.name AS product_name,
                           p.category AS product_category, p.sub_category AS product_sub_category,
                           p.brand AS product_brand, p.model AS product_model,
                           COALESCE(sup.name, b.supplier_name_snapshot) AS supplier_name
                    FROM batches b
                    LEFT JOIN products p ON p.id = b.product_id
                    LEFT JOIN suppliers sup ON sup.id = b.supplier_id
                    WHERE b.invoice_number=?
                    ORDER BY b.id ASC
                    """,
                    (inv_no,),
                ).fetchall()
            else:
                items = conn.execute(
                    """
                    SELECT b.*, p.code AS product_code, p.name AS product_name,
                           p.category AS product_category, p.sub_category AS product_sub_category,
                           p.brand AS product_brand, p.model AS product_model,
                           COALESCE(sup.name, b.supplier_name_snapshot) AS supplier_name
                    FROM batches b
                    LEFT JOIN products p ON p.id = b.product_id
                    LEFT JOIN suppliers sup ON sup.id = b.supplier_id
                    WHERE b.id=?
                    """,
                    (int(row["id"]),),
                ).fetchall()
            if not items:
                return None
            hdr_key = pinv or inv_no or str(items[0]["batch_code"])
            hdr = conn.execute(
                "SELECT * FROM invoice_headers WHERE invoice_kind='batch' AND invoice_number IN (?, ?, ?) ORDER BY id DESC LIMIT 1",
                (hdr_key, inv_no, str(items[0]["batch_code"])),
            ).fetchone()
            item_dicts = [dict(it) for it in items]
            first = item_dicts[0]
            plan = conn.execute(
                "SELECT * FROM supplier_installment_plans WHERE purchase_invoice_code=? OR batch_id=? ORDER BY id DESC LIMIT 1",
                (pinv or hdr_key, int(first["id"])),
            ).fetchone()
            hdr_extra = int(hdr["extra_cost_total"]) if hdr and hdr["extra_cost_total"] is not None else 0
            if hdr_extra == 0 and len(item_dicts) == 1:
                hdr_extra = int(first.get("extra_cost_total") or 0)
            sum_lines = sum(int(it["unit_purchase_price"]) * int(it["initial_qty"]) for it in item_dicts)
            tot_amt = int(hdr["total_amount"]) if hdr else (sum_lines + sum(int(it.get("extra_cost_total") or 0) for it in item_dicts))
            paid_amt = int(hdr["paid_amount"]) if hdr else sum(int(it["paid_amount"] or 0) for it in item_dicts)
            return {
                "purchase_invoice_code": pinv or str(first["batch_code"]),
                "invoice_number": inv_no,
                "supplier_id": first["supplier_id"],
                "supplier_name": first.get("supplier_name") or "",
                "buyer_employee_id": first["buyer_employee_id"],
                "purchase_date": first["purchase_date"],
                "extra_cost_total": hdr_extra,
                "total_amount": tot_amt,
                "paid_amount": paid_amt,
                "settlement_status": str(hdr["settlement_status"] if hdr else first["settlement_status"]),
                "settlement_subtype": str(hdr["settlement_subtype"] if hdr else first.get("settlement_subtype") or ""),
                "payment_type": str(first.get("payment_type") or "cash"),
                "check_due_date": str(hdr["check_due_date"] if hdr else first.get("check_due_date") or ""),
                "check_status": str(hdr["check_status"] if hdr else first.get("check_status") or ""),
                "installment_plan": dict(plan) if plan else None,
                "notes": str(hdr["notes"] if hdr else first.get("notes") or ""),
                "row_version": int(hdr["row_version"]) if hdr else int(first.get("row_version") or 1),
                "items": item_dicts,
            }

    def update_purchase_invoice(
        self,
        purchase_invoice_code: str,
        invoice_number: str,
        items,
        *,
        supplier_id=None,
        supplier_name=None,
        buyer_employee_id=None,
        purchase_date="",
        purchase_time="",
        settlement_status=None,
        settlement_subtype="تسویه نقدی",
        paid_amount=0,
        payment_type="cash",
        check_due_date="",
        check_status="pending",
        installment_plan=None,
        extra_cost_total=0,
        notes="",
        operator_name="",
        expected_existing_version=None,
    ) -> str:
        """Atomically update an entire multi-item purchase invoice with OCC."""
        pinv = str(purchase_invoice_code or "").strip()
        if not pinv:
            raise ValueError("شناسه فاکتور خرید برای ویرایش مشخص نشده است.")
        return self.add_purchase_invoice(
            invoice_number,
            items,
            purchase_invoice_code=pinv,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            buyer_employee_id=buyer_employee_id,
            purchase_date=purchase_date,
            purchase_time=purchase_time,
            settlement_status=settlement_status,
            settlement_subtype=settlement_subtype,
            paid_amount=paid_amount,
            payment_type=payment_type,
            check_due_date=check_due_date,
            check_status=check_status,
            installment_plan=installment_plan,
            extra_cost_total=extra_cost_total,
            notes=notes,
            operator_name=operator_name,
            conflict_resolution="replace",
            expected_existing_version=expected_existing_version,
            enforce_unique_invoice=True,
            return_invoice_number=True,
        )

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
        customer_id=None,
        payment_type="cash",
        installment_plan=None,
        operator_name="",
        settlement_subtype="",
        check_due_date="",
        check_status="pending",
        conflict_resolution=None,
        expected_existing_version=None,
        enforce_unique_invoice=False,
    ):
        return self.add_sale_invoice(
            invoice_number,
            [
                {
                    "product_id": product_id,
                    "batch_id": batch_id,
                    "qty": qty,
                    "suggested_unit_price": suggested_unit_price,
                    "actual_unit_price": actual_unit_price,
                    "serial_number": serial_number,
                    "specifications": specifications,
                    "colors": colors,
                    "warranty_company": warranty_company,
                    "warranty_start": warranty_start,
                    "warranty_months": warranty_months,
                    "warranty_days": warranty_days,
                    "warranty_end": warranty_end,
                    "expected_batch_row_version": expected_batch_row_version,
                    "notes": notes,
                }
            ],
            seller_employee_id=seller_employee_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_id=customer_id,
            sale_datetime=sale_datetime,
            settlement_status=settlement_status,
            settlement_subtype=settlement_subtype,
            paid_amount=paid_amount,
            payment_type=payment_type,
            check_due_date=check_due_date,
            check_status=check_status,
            installment_plan=installment_plan,
            notes=notes,
            operator_name=operator_name,
            conflict_resolution=conflict_resolution,
            expected_existing_version=expected_existing_version,
            enforce_unique_invoice=enforce_unique_invoice,
        )

    def add_sale_invoice(
        self,
        invoice_number,
        items,
        *,
        seller_employee_id=None,
        customer_name="",
        customer_phone="",
        customer_id=None,
        sale_datetime="",
        settlement_status=None,
        settlement_subtype="",
        paid_amount=0,
        payment_type="cash",
        check_due_date="",
        check_status="pending",
        installment_plan=None,
        extra_cost_total=0,
        notes="",
        operator_name="",
        conflict_resolution=None,
        expected_existing_version=None,
        enforce_unique_invoice=True,
    ):
        """Atomically record a 1-item or multi-item sale invoice, checks, and installment plan."""
        if not items or not isinstance(items, (list, tuple)):
            raise ValueError("حداقل یک قلم کالا برای ثبت فاکتور فروش لازم است.")
        invoice_number = str(invoice_number or "").strip()
        customer_name = str(customer_name or "").strip()
        customer_phone = str(customer_phone or "").strip()
        notes = str(notes or "").strip()
        sale_datetime = str(sale_datetime or "").strip()
        clean_subtype = str(settlement_subtype or "").strip()
        resolved_payment_type = str(payment_type or "cash").strip().lower()
        if clean_subtype == "تسویه چکی" and not installment_plan:
            resolved_payment_type = "check"
        elif resolved_payment_type not in ("cash", "check", "installment", "partial"):
            resolved_payment_type = "cash"
        clean_chk_due = str(check_due_date or "").strip() if resolved_payment_type == "check" else ""
        clean_chk_status = (
            ("cleared" if str(check_status or "").strip().lower() in ("cleared", "وصول شده", "وصول‌شده")
             else ("bounced" if str(check_status or "").strip().lower() in ("bounced", "برگشتی", "برگشت خورده") else "pending"))
            if resolved_payment_type == "check" else ""
        )
        if resolved_payment_type == "check" and not clean_chk_due:
            raise ValueError("برای تسویه چکی، تاریخ سررسید چک باید مشخص شود.")

        first_inst_paid = False
        if installment_plan:
            resolved_payment_type = "installment"
            down_p = self._batch_integer(
                installment_plan.get("down_payment", paid_amount),
                "پیش‌پرداخت",
            )
            inst_count = self._batch_integer(
                installment_plan.get("count", 1),
                "تعداد اقساط",
                minimum=1,
            )
            inst_interval = self._batch_integer(
                installment_plan.get("interval_days", 30),
                "فاصله اقساط (روز)",
                minimum=1,
            )
            inst_start_due = str(
                installment_plan.get("start_due_date") or sale_datetime.split(" ")[0]
            ).strip()
            if not inst_start_due:
                raise ValueError("تاریخ سررسید قسط اول مشخص نشده است.")
            first_inst_paid = bool(installment_plan.get("first_installment_paid", False))
            paid_amount = down_p
        else:
            paid_amount = self._batch_integer(paid_amount, "مبلغ دریافتی")

        hdr_extra_cost = self._batch_integer(extra_cost_total, "هزینه جانبی کل")
        prepared_lines = []
        total_invoice_amount = 0
        for raw in items:
            q = self._batch_integer(raw.get("qty"), "تعداد فروش", minimum=1)
            pid = self._batch_integer(raw.get("product_id"), "کالا", minimum=1)
            bid = self._batch_integer(raw.get("batch_id"), "محموله", minimum=1)
            sug_u = self._batch_integer(raw.get("suggested_unit_price"), "قیمت پیشنهادی واحد")
            act_u = self._batch_integer(raw.get("actual_unit_price"), "قیمت فروش واحد")
            line_total = self._batch_integer(act_u * q, "مبلغ کل ردیف")
            total_invoice_amount = self._batch_integer(total_invoice_amount + line_total, "مبلغ کل فاکتور")
            prepared_lines.append({
                "product_id": pid,
                "batch_id": bid,
                "qty": q,
                "suggested_unit_price": sug_u,
                "actual_unit_price": act_u,
                "line_total": line_total,
                "serial_number": str(raw.get("serial_number") or "").strip(),
                "specifications": str(raw.get("specifications") or ""),
                "colors": raw.get("colors"),
                "warranty_company": str(raw.get("warranty_company") or "").strip(),
                "warranty_start": str(raw.get("warranty_start") or "").strip(),
                "warranty_months": int(raw.get("warranty_months") or 0),
                "warranty_days": raw.get("warranty_days"),
                "warranty_end": str(raw.get("warranty_end") or "").strip(),
                "expected_batch_row_version": raw.get("expected_batch_row_version"),
                "notes": str(raw.get("notes") or notes or "").strip(),
            })
        if hdr_extra_cost > 0:
            total_invoice_amount = self._batch_integer(
                total_invoice_amount + hdr_extra_cost,
                "جمع کل فاکتور فروش با هزینه جانبی",
            )

        def _tx(conn):
            return self._insert_sale_invoice_tx(
                conn,
                invoice_number=invoice_number,
                prepared_lines=prepared_lines,
                total_invoice_amount=total_invoice_amount,
                seller_employee_id=seller_employee_id,
                customer_name=customer_name,
                customer_phone=customer_phone,
                customer_id=customer_id,
                sale_datetime=sale_datetime,
                settlement_status=settlement_status,
                clean_subtype=clean_subtype,
                paid_amount=paid_amount,
                resolved_payment_type=resolved_payment_type,
                clean_chk_due=clean_chk_due,
                clean_chk_status=clean_chk_status,
                installment_plan=installment_plan,
                inst_count=inst_count if installment_plan else 0,
                inst_interval=inst_interval if installment_plan else 30,
                inst_start_due=inst_start_due if installment_plan else "",
                first_inst_paid=first_inst_paid,
                extra_cost_total=hdr_extra_cost,
                notes=notes,
                operator_name=operator_name,
                conflict_resolution=conflict_resolution,
                expected_existing_version=expected_existing_version,
                enforce_unique_invoice=enforce_unique_invoice,
            )

        return self.run_write_transaction(_tx)

    def _insert_sale_invoice_tx(
        self,
        conn,
        *,
        invoice_number: str,
        prepared_lines: list,
        total_invoice_amount: int,
        seller_employee_id=None,
        customer_name: str = "",
        customer_phone: str = "",
        customer_id=None,
        sale_datetime: str = "",
        settlement_status=None,
        clean_subtype: str = "",
        paid_amount: int = 0,
        resolved_payment_type: str = "cash",
        clean_chk_due: str = "",
        clean_chk_status: str = "",
        installment_plan=None,
        inst_count: int = 0,
        inst_interval: int = 30,
        inst_start_due: str = "",
        first_inst_paid: bool = False,
        extra_cost_total: int = 0,
        notes: str = "",
        operator_name: str = "",
        conflict_resolution=None,
        expected_existing_version=None,
        enforce_unique_invoice: bool = True,
    ) -> str:
        """Execute transactional sale invoice creation inside the caller's write lock."""
        bumped_ver = None
        if not invoice_number:
            invoice_number = self._next_available_invoice_code(conn, "sale", "invoice_number", "INV-", 1001)
        elif enforce_unique_invoice or conflict_resolution:
            invoice_number, bumped_ver = self._resolve_or_raise_invoice_conflict_tx(
                conn,
                invoice_kind="sale",
                field="invoice_number",
                value=invoice_number,
                prefix="INV-",
                start_num=1001,
                conflict_resolution=conflict_resolution,
                expected_existing_version=expected_existing_version,
            )

        if installment_plan:
            if paid_amount > total_invoice_amount:
                raise ValueError("پیش‌پرداخت نمی‌تواند بیشتر از مبلغ کل فاکتور باشد.")
            financed_amount = total_invoice_amount - paid_amount
            if financed_amount <= 0:
                raise ValueError("برای فروش اقساطی باید مبلغی پس از پیش‌پرداخت باقی بماند.")
            if customer_id is None and customer_name:
                customer_id = self.get_or_create_customer(
                    customer_name,
                    phone=customer_phone,
                    conn=conn,
                    operator_name=operator_name,
                )
            if customer_id is None:
                raise ValueError("برای فروش اقساطی، انتخاب یا ثبت نام مشتری الزامی است.")
        elif customer_id is None and customer_name and customer_name != "مشتری حضوری":
            row_cust = conn.execute(
                "SELECT id FROM customers WHERE name=? AND (?='' OR phone=?) ORDER BY id DESC LIMIT 1",
                (customer_name, customer_phone, customer_phone),
            ).fetchone()
            if row_cust:
                customer_id = int(row_cust["id"])
            elif resolved_payment_type == "check":
                customer_id = self.get_or_create_customer(
                    customer_name,
                    phone=customer_phone,
                    conn=conn,
                    operator_name=operator_name,
                )

        if resolved_payment_type == "check":
            inv_paid_initial = total_invoice_amount
            inv_status = "تسویه‌شده"
        elif installment_plan:
            inv_paid_initial = paid_amount
            inv_status = "تسویه جزئی" if inv_paid_initial > 0 else "تسویه‌نشده"
        elif settlement_status in ("تسویه‌شده", "تسویه‌نشده", "تسویه جزئی"):
            inv_status = settlement_status
            if inv_status == "تسویه‌شده":
                inv_paid_initial = total_invoice_amount
            elif inv_status == "تسویه‌نشده":
                inv_paid_initial = 0
            else:
                inv_paid_initial = min(total_invoice_amount, paid_amount)
        else:
            if paid_amount >= total_invoice_amount:
                inv_status = "تسویه‌شده"
                inv_paid_initial = total_invoice_amount
            elif paid_amount == 0:
                inv_status = "تسویه‌نشده"
                inv_paid_initial = 0
            else:
                inv_status = "تسویه جزئی"
                inv_paid_initial = paid_amount

        cur = conn.cursor()
        inserted_sales = []
        for line in prepared_lines:
            batch = conn.execute(
                """SELECT id, batch_code, product_id, remaining_qty, unit_cost_price,
                          colors_json, row_version FROM batches WHERE id=?""",
                (line["batch_id"],),
            ).fetchone()
            if not batch:
                raise ValueError("محموله انتخاب شده وجود ندارد.")
            live_rv = int(batch["row_version"] if "row_version" in batch.keys() else 1)
            exp_rv = line["expected_batch_row_version"]
            q = line["qty"]
            if batch["remaining_qty"] < q:
                concurrent_flag = exp_rv is not None and live_rv != int(exp_rv)
                raise InsufficientStockError(
                    available_qty=batch["remaining_qty"],
                    requested_qty=q,
                    batch_code=batch["batch_code"],
                    concurrent_modified=concurrent_flag,
                    message=(
                        f"موجودی محموله «{batch['batch_code']}» به دلیل ثبت فروش هم‌زمان کافی نیست! موجودی قابل فروش: {batch['remaining_qty']} عدد"
                        if concurrent_flag
                        else f"موجودی محموله کافی نیست! موجودی قابل فروش: {batch['remaining_qty']} عدد"
                    ),
                )
            if exp_rv is not None and live_rv != int(exp_rv):
                raise ConcurrencyConflictError(
                    "batch_sale",
                    line["batch_id"],
                    int(exp_rv),
                    live_rv,
                    dict(batch),
                    f"در فاصله انتخاب محموله تا ثبت فاکتور، فروش یا تغییری در محموله «{batch['batch_code']}» ثبت شده است. موجودی فعلی: {batch['remaining_qty']} عدد.",
                )
            normalized_colors = self._normalize_color_list(line["colors"])
            if normalized_colors is not None:
                if len(normalized_colors) > q:
                    raise ValueError("تعداد رنگ‌های انتخاب‌شده نمی‌تواند از تعداد فروش بیشتر باشد.")
                try:
                    batch_colors = json.loads(batch["colors_json"] or "[]")
                except (TypeError, ValueError, json.JSONDecodeError):
                    batch_colors = []
                unavailable = [value for value in normalized_colors if value not in batch_colors]
                if unavailable:
                    raise ValueError("یکی از رنگ‌های انتخاب‌شده در این محموله ثبت نشده است.")

            unit_cost_price = self._batch_integer(batch["unit_cost_price"], "بهای تمام‌شده واحد")
            sug_u = line["suggested_unit_price"]
            act_u = line["actual_unit_price"]
            if act_u < sug_u:
                unit_discount = sug_u - act_u
                price_markup_unit = 0
            else:
                unit_discount = 0
                price_markup_unit = act_u - sug_u
            total_discount = self._batch_integer(unit_discount * q, "تخفیف کل فروش")
            unit_profit = self._sqlite_integer(act_u - unit_cost_price, "سود هر واحد")
            total_profit = self._sqlite_integer(unit_profit * q, "سود کل فروش")

            cur.execute(
                """
                INSERT INTO sales (
                    invoice_number, product_id, batch_id, serial_number, seller_employee_id, customer_name,
                    customer_phone, qty, suggested_unit_price, actual_unit_price, unit_cost_price,
                    unit_discount, total_discount, price_Markup_unit, unit_profit, total_profit,
                    total_amount, paid_amount, settlement_status, sale_datetime,
                    warranty_company, warranty_start, warranty_months, warranty_days, warranty_end,
                    specifications, colors_json, notes, customer_id, payment_type,
                    settlement_subtype, check_due_date, check_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invoice_number, line["product_id"], line["batch_id"], line["serial_number"],
                    seller_employee_id, customer_name, customer_phone, q, sug_u, act_u, unit_cost_price,
                    unit_discount, total_discount, price_markup_unit, unit_profit, total_profit,
                    line["line_total"], 0, inv_status, sale_datetime,
                    line["warranty_company"], line["warranty_start"],
                    int(line["warranty_months"]),
                    int(line["warranty_days"] if line["warranty_days"] is not None else int(line["warranty_months"] or 0) * 30),
                    line["warranty_end"], line["specifications"],
                    json.dumps(normalized_colors or [], ensure_ascii=False),
                    line["notes"],
                    int(customer_id) if customer_id is not None else None,
                    resolved_payment_type, clean_subtype, clean_chk_due, clean_chk_status,
                ),
            )
            sid = int(cur.lastrowid)
            stock_update = conn.execute(
                "UPDATE batches SET sold_qty=sold_qty+?, remaining_qty=remaining_qty-? WHERE id=? AND remaining_qty>=?",
                (q, q, line["batch_id"], q),
            )
            if stock_update.rowcount != 1:
                raise ValueError("موجودی محموله برای ثبت این تعداد کافی نیست.")
            inserted_sales.append({"id": sid, "line_total": line["line_total"], "total_profit": total_profit})

        first_sale_id = inserted_sales[0]["id"]
        first_inst_paid_amt = 0
        sale_d_only = sale_datetime.split(" ")[0]
        if installment_plan:
            plan_res = self._create_installment_plan_tx(
                conn=conn,
                sale_id=first_sale_id,
                customer_id=int(customer_id),
                total_bill=total_invoice_amount,
                down_payment=inv_paid_initial,
                count=inst_count,
                start_due_date=inst_start_due,
                interval_days=inst_interval,
                notes=str(installment_plan.get("notes") or "").strip(),
                operator_name=operator_name,
                cal_type=installment_plan.get("cal_type") or self.cfg.get("calendar_type", "jalali"),
                first_installment_paid=first_inst_paid,
                sale_date=sale_d_only,
            )
            first_inst_paid_amt = int(plan_res.get("first_paid_amount") or 0)

        final_paid_total = min(total_invoice_amount, inv_paid_initial + first_inst_paid_amt)
        if resolved_payment_type == "check":
            final_status = "تسویه‌شده"
        elif installment_plan:
            final_status = (
                "تسویه‌شده" if final_paid_total >= total_invoice_amount
                else ("تسویه جزئی" if final_paid_total > 0 else "تسویه‌نشده")
            )
        else:
            final_status = inv_status

        rem_to_alloc = final_paid_total
        for srow in inserted_sales:
            if final_paid_total >= total_invoice_amount:
                l_paid = srow["line_total"]
                l_status = "تسویه‌شده"
            elif final_paid_total == 0:
                l_paid = 0
                l_status = "تسویه‌نشده"
            else:
                l_paid = min(srow["line_total"], rem_to_alloc)
                rem_to_alloc = max(0, rem_to_alloc - l_paid)
                l_status = (
                    "تسویه‌شده" if l_paid >= srow["line_total"]
                    else ("تسویه‌نشده" if l_paid == 0 else "تسویه جزئی")
                )
            conn.execute(
                "UPDATE sales SET paid_amount=?, settlement_status=? WHERE id=?",
                (l_paid, l_status, srow["id"]),
            )

        if inv_paid_initial > 0 and resolved_payment_type != "check":
            conn.execute(
                """
                INSERT INTO payments (ref_type, ref_id, amount, payment_date, notes)
                VALUES ('sale', ?, ?, ?, ?)
                """,
                (
                    first_sale_id,
                    inv_paid_initial,
                    sale_d_only,
                    "پیش‌پرداخت فروش اقساطی" if installment_plan else "دریافت وجه هنگام فروش",
                ),
            )
        if first_inst_paid_amt > 0:
            conn.execute(
                """
                INSERT INTO payments (ref_type, ref_id, amount, payment_date, notes)
                VALUES ('sale', ?, ?, ?, 'پرداخت قسط اول هنگام خرید')
                """,
                (first_sale_id, first_inst_paid_amt, sale_d_only),
            )

        if resolved_payment_type == "check":
            self._record_check_tx(
                conn,
                direction="receivable",
                ref_type="sale",
                ref_id=first_sale_id,
                invoice_number=invoice_number,
                customer_id=int(customer_id) if customer_id is not None else None,
                party_name=customer_name,
                party_phone=customer_phone,
                amount=total_invoice_amount,
                due_date=clean_chk_due,
                status=clean_chk_status or "pending",
                cleared_date=sale_d_only if clean_chk_status == "cleared" else "",
                notes=notes,
                operator_name=operator_name,
            )

        self._upsert_invoice_header_tx(
            conn,
            invoice_kind="sale",
            invoice_number=invoice_number,
            party_id=int(customer_id) if customer_id is not None else None,
            party_name=customer_name,
            party_phone=customer_phone,
            operator_id=seller_employee_id,
            total_amount=total_invoice_amount,
            paid_amount=final_paid_total,
            settlement_status=final_status,
            settlement_subtype=clean_subtype,
            check_due_date=clean_chk_due,
            check_status=clean_chk_status,
            first_installment_paid=first_inst_paid,
            item_count=len(inserted_sales),
            invoice_datetime=sale_datetime,
            notes=notes,
            operator_name=operator_name,
            forced_version=bumped_ver,
            extra_cost_total=int(extra_cost_total or 0),
        )

        self.log_audit(
            conn,
            "ثبت فروش",
            f"فاکتور: {invoice_number} - تعداد اقلام: {len(inserted_sales)} - جمع: {total_invoice_amount:,}",
        )
        return invoice_number

    def get_sale_invoice_detail(self, ref_or_sale_id) -> Optional[dict]:
        """Return invoice header + all sibling line items for a sale invoice or single sale ID."""
        with self.get_connection() as conn:
            row = None
            if isinstance(ref_or_sale_id, int) or str(ref_or_sale_id).strip().isdigit():
                row = conn.execute(
                    "SELECT id, invoice_number FROM sales WHERE id=?",
                    (int(ref_or_sale_id),),
                ).fetchone()
            if not row:
                inv = str(ref_or_sale_id or "").strip()
                if inv:
                    row = conn.execute(
                        "SELECT id, invoice_number FROM sales WHERE invoice_number=? ORDER BY id ASC LIMIT 1",
                        (inv,),
                    ).fetchone()
            if not row:
                return None
            inv_no = str(row["invoice_number"] or "").strip()
            items = conn.execute(
                """
                SELECT s.*,
                       p.code AS product_code,
                       p.name AS product_name,
                       p.category AS product_category,
                       p.sub_category AS product_sub_category,
                       p.brand AS product_brand,
                       p.model AS product_model,
                       b.batch_code,
                       b.remaining_qty AS batch_remaining_qty,
                       b.unit_cost_price AS batch_unit_cost,
                       b.suggested_sell_price AS batch_suggested_sell_price,
                       b.purchase_invoice_code,
                       b.invoice_number AS supplier_invoice_number
                FROM sales s
                LEFT JOIN products p ON p.id = s.product_id
                LEFT JOIN batches b ON b.id = s.batch_id
                WHERE s.invoice_number=?
                ORDER BY s.id ASC
                """,
                (inv_no,),
            ).fetchall()
            if not items:
                return None
            item_dicts = [dict(it) for it in items]
            first = item_dicts[0]
            hdr = conn.execute(
                "SELECT * FROM invoice_headers WHERE invoice_kind='sale' AND invoice_number=?",
                (inv_no,),
            ).fetchone()
            plan = conn.execute(
                "SELECT * FROM installment_plans WHERE sale_id=? ORDER BY id DESC LIMIT 1",
                (int(first["id"]),),
            ).fetchone()
            hdr_extra = int(hdr["extra_cost_total"] or 0) if hdr else 0
            tot_amt = int(hdr["total_amount"]) if hdr else (sum(int(it["total_amount"]) for it in item_dicts) + hdr_extra)
            paid_amt = int(hdr["paid_amount"]) if hdr else sum(int(it["paid_amount"] or 0) for it in item_dicts)
            return {
                "invoice_number": inv_no,
                "customer_id": first["customer_id"],
                "customer_name": first["customer_name"] or "",
                "customer_phone": first["customer_phone"] or "",
                "seller_employee_id": first["seller_employee_id"],
                "sale_datetime": first["sale_datetime"] or "",
                "extra_cost_total": hdr_extra,
                "total_amount": tot_amt,
                "paid_amount": paid_amt,
                "settlement_status": str(hdr["settlement_status"] if hdr else first["settlement_status"]),
                "settlement_subtype": str(hdr["settlement_subtype"] if hdr else first.get("settlement_subtype") or ""),
                "payment_type": str(first.get("payment_type") or "cash"),
                "check_due_date": str(hdr["check_due_date"] if hdr else first.get("check_due_date") or ""),
                "check_status": str(hdr["check_status"] if hdr else first.get("check_status") or ""),
                "installment_plan": dict(plan) if plan else None,
                "notes": str(hdr["notes"] if hdr else first.get("notes") or ""),
                "row_version": int(hdr["row_version"]) if hdr else int(first.get("row_version") or 1),
                "items": item_dicts,
            }

    def update_sale_invoice(
        self,
        invoice_number: str,
        items,
        *,
        seller_employee_id=None,
        customer_name="",
        customer_phone="",
        customer_id=None,
        sale_datetime="",
        settlement_status=None,
        settlement_subtype="",
        paid_amount=0,
        payment_type="cash",
        check_due_date="",
        check_status="pending",
        installment_plan=None,
        extra_cost_total=0,
        notes="",
        operator_name="",
        expected_existing_version=None,
    ) -> str:
        """Atomically update an entire multi-item sale invoice inside one write lock with OCC."""
        clean_inv = str(invoice_number or "").strip()
        if not clean_inv:
            raise ValueError("شماره فاکتور فروش برای ویرایش مشخص نشده است.")
        return self.add_sale_invoice(
            clean_inv,
            items,
            seller_employee_id=seller_employee_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_id=customer_id,
            sale_datetime=sale_datetime,
            settlement_status=settlement_status,
            settlement_subtype=settlement_subtype,
            paid_amount=paid_amount,
            payment_type=payment_type,
            check_due_date=check_due_date,
            check_status=check_status,
            installment_plan=installment_plan,
            extra_cost_total=extra_cost_total,
            notes=notes,
            operator_name=operator_name,
            conflict_resolution="replace",
            expected_existing_version=expected_existing_version,
            enforce_unique_invoice=True,
        )

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
            conn.execute(
                "DELETE FROM installment_payments WHERE plan_id IN (SELECT id FROM installment_plans WHERE sale_id=?)",
                (sale_id,),
            )
            conn.execute("DELETE FROM installment_plans WHERE sale_id=?", (sale_id,))
            conn.execute("DELETE FROM payments WHERE ref_type='sale' AND ref_id=?", (sale_id,))
            conn.execute("DELETE FROM checks WHERE ref_type='sale' AND ref_id=?", (sale_id,))
            conn.execute("DELETE FROM sales WHERE id=?", (sale_id,))
            rem_lines = conn.execute(
                "SELECT COUNT(*) FROM sales WHERE invoice_number=?",
                (old_sale["invoice_number"],),
            ).fetchone()[0]
            if int(rem_lines or 0) == 0:
                conn.execute(
                    "DELETE FROM invoice_headers WHERE invoice_kind='sale' AND invoice_number=?",
                    (old_sale["invoice_number"],),
                )
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
                    srv_code = self.generate_next_code("service_catalog", "code", "SVC-", 1001, conn=conn)
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
        settlement_subtype="",
        check_due_date="",
        check_status="pending",
        customer_phone="",
        operator_name="",
        conflict_resolution=None,
        expected_existing_version=None,
        enforce_unique_invoice=False,
    ):
        return self.add_service_invoice(
            invoice_number,
            [
                {
                    "service_id": service_id,
                    "service_fee": service_fee,
                    "side_cost": side_cost,
                    "description": description,
                }
            ],
            seller_employee_id=seller_employee_id,
            technician_employee_id=technician_employee_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            service_datetime=service_datetime,
            settlement_status=settlement_status,
            settlement_subtype=settlement_subtype,
            paid_amount=paid_amount,
            check_due_date=check_due_date,
            check_status=check_status,
            operator_name=operator_name,
            conflict_resolution=conflict_resolution,
            expected_existing_version=expected_existing_version,
            enforce_unique_invoice=enforce_unique_invoice,
        )

    def add_service_invoice(
        self,
        invoice_number,
        items,
        *,
        seller_employee_id=None,
        technician_employee_id=None,
        customer_id=None,
        customer_name="",
        customer_phone="",
        service_datetime="",
        settlement_status=None,
        settlement_subtype="",
        paid_amount=0,
        payment_type="cash",
        check_due_date="",
        check_status="pending",
        installment_plan=None,
        extra_cost_total=0,
        operator_name="",
        conflict_resolution=None,
        expected_existing_version=None,
        enforce_unique_invoice=True,
    ):
        """Atomically record a 1-item or multi-item service invoice under one SINV- number."""
        if not items or not isinstance(items, (list, tuple)):
            raise ValueError("حداقل یک خدمت برای ثبت فاکتور لازم است.")
        invoice_number = str(invoice_number or "").strip()
        customer_id = self._batch_optional_id(customer_id, "مشتری")
        customer_name = str(customer_name or "").strip()
        customer_phone = str(customer_phone or "").strip()
        service_datetime = str(service_datetime or "").strip()
        clean_subtype = str(settlement_subtype or "").strip()
        resolved_payment_type = str(payment_type or "cash").strip().lower()
        if installment_plan:
            resolved_payment_type = "installment"
        elif clean_subtype == "تسویه چکی":
            resolved_payment_type = "check"
        elif resolved_payment_type not in ("cash", "check", "installment", "partial"):
            resolved_payment_type = "cash"
        clean_chk_due = str(check_due_date or "").strip() if resolved_payment_type == "check" else ""
        clean_chk_status = (
            ("cleared" if str(check_status or "").strip().lower() in ("cleared", "وصول شده", "وصول‌شده")
             else ("bounced" if str(check_status or "").strip().lower() in ("bounced", "برگشتی", "برگشت خورده") else "pending"))
            if resolved_payment_type == "check" else ""
        )
        if resolved_payment_type == "check" and not clean_chk_due:
            raise ValueError("برای تسویه چکی، تاریخ سررسید چک باید مشخص شود.")
        hdr_extra_cost = self._batch_integer(extra_cost_total, "هزینه جانبی کل")
        first_inst_paid = False
        inst_count = 0
        inst_interval = 30
        inst_start_due = ""
        if installment_plan:
            down_p = self._batch_integer(installment_plan.get("down_payment", paid_amount), "پیش‌پرداخت")
            inst_count = self._batch_integer(installment_plan.get("count", 1), "تعداد اقساط", minimum=1)
            inst_interval = self._batch_integer(installment_plan.get("interval_days", 30), "فاصله اقساط (روز)", minimum=1)
            inst_start_due = str(installment_plan.get("start_due_date") or service_datetime.split(" ")[0]).strip()
            if not inst_start_due:
                raise ValueError("تاریخ سررسید قسط اول مشخص نشده است.")
            first_inst_paid = bool(installment_plan.get("first_installment_paid", False))
            paid_amount = down_p
        else:
            paid_amount = self._batch_integer(paid_amount, "مبلغ دریافتی")

        def _tx(conn):
            nonlocal invoice_number, paid_amount, customer_id
            return self._insert_service_invoice_tx(
                conn,
                invoice_number=invoice_number,
                items=items,
                seller_employee_id=seller_employee_id,
                technician_employee_id=technician_employee_id,
                customer_id=customer_id,
                customer_name=customer_name,
                customer_phone=customer_phone,
                service_datetime=service_datetime,
                settlement_status=settlement_status,
                clean_subtype=clean_subtype,
                paid_amount=paid_amount,
                resolved_payment_type=resolved_payment_type,
                clean_chk_due=clean_chk_due,
                clean_chk_status=clean_chk_status,
                installment_plan=installment_plan,
                inst_count=inst_count,
                inst_interval=inst_interval,
                inst_start_due=inst_start_due,
                first_inst_paid=first_inst_paid,
                extra_cost_total=hdr_extra_cost,
                operator_name=operator_name,
                conflict_resolution=conflict_resolution,
                expected_existing_version=expected_existing_version,
                enforce_unique_invoice=enforce_unique_invoice,
            )

        return self.run_write_transaction(_tx)

    def _insert_service_invoice_tx(
        self,
        conn,
        *,
        invoice_number: str,
        items,
        seller_employee_id=None,
        technician_employee_id=None,
        customer_id=None,
        customer_name: str = "",
        customer_phone: str = "",
        service_datetime: str = "",
        settlement_status=None,
        clean_subtype: str = "",
        paid_amount: int = 0,
        resolved_payment_type: str = "cash",
        clean_chk_due: str = "",
        clean_chk_status: str = "",
        installment_plan=None,
        inst_count: int = 0,
        inst_interval: int = 30,
        inst_start_due: str = "",
        first_inst_paid: bool = False,
        extra_cost_total: int = 0,
        operator_name: str = "",
        conflict_resolution=None,
        expected_existing_version=None,
        enforce_unique_invoice: bool = True,
    ) -> str:
        """Transactional core for creating a single/multi-item service invoice + optional installment/check."""
        bumped_ver = None
        if not invoice_number:
            invoice_number = self._next_available_invoice_code(
                conn, "service", "invoice_number", "SINV-", 1001
            )
        elif enforce_unique_invoice or conflict_resolution:
            invoice_number, bumped_ver = self._resolve_or_raise_invoice_conflict_tx(
                conn,
                invoice_kind="service",
                field="invoice_number",
                value=invoice_number,
                prefix="SINV-",
                start_num=1001,
                conflict_resolution=conflict_resolution,
                expected_existing_version=expected_existing_version,
            )

        resolved_lines = []
        total_fee = 0
        for raw in items:
            sid = raw.get("service_id")
            srv = None
            if sid is not None:
                srv = conn.execute(
                    "SELECT id, service_type, name, default_fee FROM service_catalog WHERE id=?",
                    (sid,),
                ).fetchone()
                if not srv:
                    raise ValueError("تعرفه خدمت یافت نشد.")
            desc = str(raw.get("description") or "").strip()
            sfee = self._batch_integer(raw.get("service_fee"), "هزینه خدمت")
            scost = self._batch_integer(raw.get("side_cost", 0), "هزینه جانبی")
            total_fee = self._batch_integer(total_fee + sfee, "جمع کل فاکتور خدمات")
            resolved_lines.append({
                "service_id": sid,
                "service_type": srv["service_type"] if srv else str(raw.get("service_type") or "خدمات عمومی"),
                "service_name": srv["name"] if srv else (str(raw.get("service_name") or "").strip() or desc or "خدمت متفرقه"),
                "historical_tariff": self._batch_integer(srv["default_fee"] if srv else sfee, "تعرفه تاریخی"),
                "service_fee": sfee,
                "side_cost": scost,
                "description": desc,
            })

        total_invoice_bill = self._batch_integer(total_fee + int(extra_cost_total or 0), "جمع کل فاکتور خدمات")

        if installment_plan:
            if paid_amount > total_invoice_bill:
                raise ValueError("پیش‌پرداخت نمی‌تواند بیشتر از مبلغ کل فاکتور خدمات باشد.")
            if total_invoice_bill - paid_amount <= 0:
                raise ValueError("برای فروش اقساطی خدمات باید مبلغی پس از پیش‌پرداخت باقی بماند.")
            if customer_id is None and customer_name and customer_name != "مشتری حضوری":
                customer_id = self.get_or_create_customer(
                    customer_name,
                    phone=customer_phone,
                    conn=conn,
                    operator_name=operator_name,
                )
            if customer_id is None:
                raise ValueError("برای فروش اقساطی خدمات، انتخاب یا ثبت نام مشتری الزامی است.")
        elif customer_id is None and customer_name and customer_name != "مشتری حضوری":
            cust_row = conn.execute(
                "SELECT id FROM customers WHERE name=? AND (?='' OR phone=?) ORDER BY id DESC LIMIT 1",
                (customer_name, customer_phone, customer_phone),
            ).fetchone()
            if cust_row:
                customer_id = int(cust_row["id"])
            elif resolved_payment_type == "check":
                customer_id = self.get_or_create_customer(
                    customer_name,
                    phone=customer_phone,
                    conn=conn,
                    operator_name=operator_name,
                )

        if resolved_payment_type == "check":
            inv_paid_initial = total_invoice_bill
            inv_status = "تسویه‌شده"
        elif installment_plan:
            inv_paid_initial = paid_amount
            inv_status = "تسویه جزئی" if inv_paid_initial > 0 else "تسویه‌نشده"
        elif settlement_status in ("تسویه‌شده", "تسویه‌نشده", "تسویه جزئی"):
            inv_status = settlement_status
            if inv_status == "تسویه‌شده":
                inv_paid_initial = (
                    min(total_invoice_bill, paid_amount)
                    if (paid_amount is not None and 0 < int(paid_amount) < total_invoice_bill)
                    else total_invoice_bill
                )
            elif inv_status == "تسویه‌نشده":
                inv_paid_initial = 0
            else:
                inv_paid_initial = min(total_invoice_bill, paid_amount)
        else:
            inv_paid_initial = min(total_invoice_bill, paid_amount)
            inv_status = (
                "تسویه‌شده" if inv_paid_initial >= total_invoice_bill
                else ("تسویه‌نشده" if inv_paid_initial == 0 else "تسویه جزئی")
            )

        inserted_rows = []
        for line in resolved_lines:
            cur = conn.execute(
                """
                INSERT INTO service_records (
                    invoice_number, service_id, service_type, service_name,
                    seller_employee_id, technician_employee_id, customer_name,
                    historical_tariff, service_fee, side_cost, net_profit,
                    paid_amount, settlement_status, service_datetime, description,
                    settlement_subtype, check_due_date, check_status, customer_phone,
                    customer_id, payment_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invoice_number, line["service_id"], line["service_type"], line["service_name"],
                    seller_employee_id, technician_employee_id, customer_name,
                    line["historical_tariff"], line["service_fee"], line["side_cost"], 0,
                    0, inv_status, service_datetime, line["description"],
                    clean_subtype, clean_chk_due, clean_chk_status, customer_phone,
                    int(customer_id) if customer_id is not None else None,
                    resolved_payment_type,
                ),
            )
            inserted_rows.append({"id": int(cur.lastrowid), "line": line})

        first_rec_id = inserted_rows[0]["id"]
        srv_date_only = service_datetime.split(" ")[0]
        first_inst_paid_amt = 0
        if installment_plan:
            plan_res = self._create_installment_plan_tx(
                conn=conn,
                sale_id=None,
                service_record_id=first_rec_id,
                ref_type="service",
                customer_id=int(customer_id),
                total_bill=total_invoice_bill,
                down_payment=inv_paid_initial,
                count=inst_count,
                start_due_date=inst_start_due,
                interval_days=inst_interval,
                notes=str(installment_plan.get("notes") or "").strip(),
                operator_name=operator_name,
                cal_type=installment_plan.get("cal_type") or self.cfg.get("calendar_type", "jalali"),
                first_installment_paid=first_inst_paid,
                sale_date=srv_date_only,
            )
            first_inst_paid_amt = int(plan_res.get("first_paid_amount") or 0)

        final_paid_total = min(total_invoice_bill, inv_paid_initial + first_inst_paid_amt)
        if resolved_payment_type == "check":
            final_status = "تسویه‌شده"
        elif installment_plan:
            final_status = (
                "تسویه‌شده" if final_paid_total >= total_invoice_bill
                else ("تسویه جزئی" if final_paid_total > 0 else "تسویه‌نشده")
            )
        else:
            final_status = inv_status

        rem_paid = final_paid_total
        total_net_profit = 0
        for idx_line, row_info in enumerate(inserted_rows):
            line = row_info["line"]
            if final_paid_total >= total_invoice_bill:
                l_paid = line["service_fee"]
                l_status = "تسویه‌شده"
            elif final_paid_total == 0:
                l_paid = 0
                l_status = "تسویه‌نشده"
            elif final_status == "تسویه‌شده":
                l_paid = rem_paid if idx_line == len(inserted_rows) - 1 else min(line["service_fee"], rem_paid)
                rem_paid = max(0, rem_paid - l_paid)
                l_status = "تسویه‌شده"
            else:
                l_paid = min(line["service_fee"], rem_paid)
                rem_paid = max(0, rem_paid - l_paid)
                l_status = (
                    "تسویه‌شده" if l_paid >= line["service_fee"]
                    else ("تسویه‌نشده" if l_paid == 0 else "تسویه جزئی")
                )
            net_profit = self._sqlite_integer(l_paid - line["side_cost"], "سود خالص خدمت")
            total_net_profit = self._sqlite_integer(total_net_profit + net_profit, "جمع سود خدمات")
            conn.execute(
                "UPDATE service_records SET paid_amount=?, net_profit=?, settlement_status=? WHERE id=?",
                (l_paid, net_profit, l_status, row_info["id"]),
            )

        if inv_paid_initial > 0 and resolved_payment_type != "check":
            conn.execute(
                "INSERT INTO payments (ref_type, ref_id, amount, payment_date, notes) VALUES ('service', ?, ?, ?, ?)",
                (
                    first_rec_id,
                    inv_paid_initial,
                    srv_date_only,
                    "پیش‌پرداخت فروش اقساطی خدمت" if installment_plan else "دریافت وجه هنگام ثبت خدمت",
                ),
            )
        if first_inst_paid_amt > 0:
            conn.execute(
                "INSERT INTO payments (ref_type, ref_id, amount, payment_date, notes) VALUES ('service', ?, ?, ?, 'پرداخت قسط اول خدمت')",
                (first_rec_id, first_inst_paid_amt, srv_date_only),
            )

        if resolved_payment_type == "check" and first_rec_id is not None:
            self._record_check_tx(
                conn,
                direction="receivable",
                ref_type="service",
                ref_id=first_rec_id,
                invoice_number=invoice_number,
                customer_id=customer_id,
                party_name=customer_name,
                party_phone=customer_phone,
                amount=total_invoice_bill,
                due_date=clean_chk_due,
                status=clean_chk_status or "pending",
                cleared_date=srv_date_only if clean_chk_status == "cleared" else "",
                notes=resolved_lines[0]["description"],
                operator_name=operator_name,
            )

        self._upsert_invoice_header_tx(
            conn,
            invoice_kind="service",
            invoice_number=invoice_number,
            party_id=customer_id,
            party_name=customer_name,
            party_phone=customer_phone,
            operator_id=seller_employee_id,
            total_amount=total_invoice_bill,
            paid_amount=final_paid_total,
            settlement_status=final_status,
            settlement_subtype=clean_subtype,
            check_due_date=clean_chk_due,
            check_status=clean_chk_status,
            first_installment_paid=first_inst_paid,
            item_count=len(resolved_lines),
            invoice_datetime=service_datetime,
            notes=resolved_lines[0]["description"],
            operator_name=operator_name,
            forced_version=bumped_ver,
            extra_cost_total=int(extra_cost_total or 0),
        )

        self.log_audit(
            conn,
            "ثبت خدمت",
            f"فاکتور خدمت: {invoice_number} - تعداد: {len(resolved_lines)} - سود خالص: {total_net_profit:,}",
        )
        return invoice_number

    def get_service_invoice_detail(self, ref_or_record_id) -> Optional[dict]:
        """Return invoice header + all sibling line items for a service invoice or record ID."""
        with self.get_connection() as conn:
            row = None
            if isinstance(ref_or_record_id, int) or str(ref_or_record_id).strip().isdigit():
                row = conn.execute(
                    "SELECT id, invoice_number FROM service_records WHERE id=?",
                    (int(ref_or_record_id),),
                ).fetchone()
            if not row:
                inv = str(ref_or_record_id or "").strip()
                if inv:
                    row = conn.execute(
                        "SELECT id, invoice_number FROM service_records WHERE invoice_number=? ORDER BY id ASC LIMIT 1",
                        (inv,),
                    ).fetchone()
            if not row:
                return None
            inv_no = str(row["invoice_number"] or "").strip()
            items = conn.execute(
                """
                SELECT sr.*, sc.code AS service_code,
                       e_sel.name AS seller_name,
                       e_tech.name AS technician_name
                FROM service_records sr
                LEFT JOIN service_catalog sc ON sc.id = sr.service_id
                LEFT JOIN employees e_sel ON e_sel.id = sr.seller_employee_id
                LEFT JOIN employees e_tech ON e_tech.id = sr.technician_employee_id
                WHERE sr.invoice_number=?
                ORDER BY sr.id ASC
                """,
                (inv_no,),
            ).fetchall()
            if not items:
                return None
            item_dicts = [dict(it) for it in items]
            first = item_dicts[0]
            hdr = conn.execute(
                "SELECT * FROM invoice_headers WHERE invoice_kind='service' AND invoice_number=?",
                (inv_no,),
            ).fetchone()
            srv_ids = [int(it["id"]) for it in item_dicts]
            marks = ",".join("?" for _ in srv_ids)
            plan = conn.execute(
                f"SELECT * FROM installment_plans WHERE ref_type='service' AND service_record_id IN ({marks}) ORDER BY id DESC LIMIT 1",
                srv_ids,
            ).fetchone()
            hdr_extra = int(hdr["extra_cost_total"] or 0) if hdr else 0
            tot_amt = int(hdr["total_amount"]) if hdr else (sum(int(it["service_fee"]) for it in item_dicts) + hdr_extra)
            paid_amt = int(hdr["paid_amount"]) if hdr else sum(int(it["paid_amount"] or 0) for it in item_dicts)
            return {
                "invoice_number": inv_no,
                "customer_id": first.get("customer_id"),
                "customer_name": first.get("customer_name") or "",
                "customer_phone": first.get("customer_phone") or "",
                "seller_employee_id": first.get("seller_employee_id"),
                "technician_employee_id": first.get("technician_employee_id"),
                "service_datetime": first.get("service_datetime") or "",
                "extra_cost_total": hdr_extra,
                "total_amount": tot_amt,
                "paid_amount": paid_amt,
                "settlement_status": str(hdr["settlement_status"] if hdr else first["settlement_status"]),
                "settlement_subtype": str(hdr["settlement_subtype"] if hdr else first.get("settlement_subtype") or ""),
                "payment_type": str(first.get("payment_type") or "cash"),
                "check_due_date": str(hdr["check_due_date"] if hdr else first.get("check_due_date") or ""),
                "check_status": str(hdr["check_status"] if hdr else first.get("check_status") or ""),
                "installment_plan": dict(plan) if plan else None,
                "description": str(hdr["notes"] if hdr else first.get("description") or ""),
                "row_version": int(hdr["row_version"]) if hdr else int(first.get("row_version") or 1),
                "items": item_dicts,
            }

    def update_service_invoice(
        self,
        invoice_number: str,
        items,
        *,
        seller_employee_id=None,
        technician_employee_id=None,
        customer_id=None,
        customer_name="",
        customer_phone="",
        service_datetime="",
        settlement_status=None,
        settlement_subtype="",
        paid_amount=0,
        payment_type="cash",
        check_due_date="",
        check_status="pending",
        installment_plan=None,
        extra_cost_total=0,
        operator_name="",
        expected_existing_version=None,
    ) -> str:
        """Atomically update a single/multi-item service invoice inside one write lock with OCC."""
        clean_inv = str(invoice_number or "").strip()
        if not clean_inv:
            raise ValueError("شماره فاکتور خدمات برای ویرایش مشخص نشده است.")
        return self.add_service_invoice(
            clean_inv,
            items,
            seller_employee_id=seller_employee_id,
            technician_employee_id=technician_employee_id,
            customer_id=customer_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            service_datetime=service_datetime,
            settlement_status=settlement_status,
            settlement_subtype=settlement_subtype,
            paid_amount=paid_amount,
            payment_type=payment_type,
            check_due_date=check_due_date,
            check_status=check_status,
            installment_plan=installment_plan,
            extra_cost_total=extra_cost_total,
            operator_name=operator_name,
            conflict_resolution="replace",
            expected_existing_version=expected_existing_version,
            enforce_unique_invoice=True,
        )

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
            old = conn.execute("SELECT invoice_number FROM service_records WHERE id=?", (record_id,)).fetchone()
            conn.execute(
                "DELETE FROM installment_payments WHERE plan_id IN (SELECT id FROM installment_plans WHERE service_record_id=?)",
                (record_id,),
            )
            conn.execute("DELETE FROM installment_plans WHERE service_record_id=?", (record_id,))
            conn.execute("DELETE FROM payments WHERE ref_type='service' AND ref_id=?", (record_id,))
            conn.execute("DELETE FROM checks WHERE ref_type='service' AND ref_id=?", (record_id,))
            conn.execute("DELETE FROM service_records WHERE id=?", (record_id,))
            if old:
                rem = conn.execute(
                    "SELECT COUNT(*) FROM service_records WHERE invoice_number=?",
                    (old["invoice_number"],),
                ).fetchone()[0]
                if int(rem or 0) == 0:
                    conn.execute(
                        "DELETE FROM checks WHERE ref_type='service' AND invoice_number=?",
                        (old["invoice_number"],),
                    )
                    conn.execute(
                        "DELETE FROM invoice_headers WHERE invoice_kind='service' AND invoice_number=?",
                        (old["invoice_number"],),
                    )
                self.log_audit(conn, "حذف رکورد خدمت", f"شناسه: {record_id} | فاکتور: {old['invoice_number']}")

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

    # =========================================================================
    # مشتریان، فروش اقساطی و آمار نموداری (v4.10.0 - REQ-05, REQ-06, REQ-00)
    # =========================================================================
    @staticmethod
    def build_installment_schedule(
        financed_amount: int,
        count: int,
        start_due_date: str,
        interval_days: int = 30,
        cal_type: Optional[str] = None,
    ) -> list[dict]:
        """Build an exact integer installment schedule putting division remainder onto the final installment."""
        total = int(financed_amount)
        if total < 0:
            raise ValueError("مبلغ اقساط نمی‌تواند منفی باشد.")
        n = int(count)
        if n <= 0:
            raise ValueError("تعداد اقساط باید بزرگ‌تر از صفر باشد.")
        step_days = int(interval_days)
        if step_days <= 0:
            raise ValueError("فاصله زمانی اقساط باید حداقل یک روز باشد.")
        start_date = str(start_due_date or "").strip()
        if not start_date:
            raise ValueError("تاریخ سررسید قسط اول وارد نشده است.")

        from datetime import timedelta

        active_cal = cal_type or datetime_format.CALENDAR_JALALI
        base_greg = datetime_format.parse_date_to_gregorian(start_date, fallback_cal=active_cal)
        base_amt, remainder = divmod(total, n)
        rows = []
        for idx in range(n):
            amt = base_amt + (remainder if idx == n - 1 else 0)
            if base_greg is not None:
                target_g = base_greg + timedelta(days=idx * step_days)
                ny, nm, nd = datetime_format.from_gregorian_date(target_g, active_cal)
                due = f"{ny:04d}/{nm:02d}/{nd:02d}"
            else:
                due = start_date
            rows.append({
                "installment_no": idx + 1,
                "due_date": due,
                "due_amount": int(amt),
            })
        return rows

    def get_or_create_customer(
        self,
        name: str,
        phone: str = "",
        national_id: str = "",
        address: str = "",
        notes: str = "",
        *,
        conn=None,
        operator_name: str = "",
    ) -> int:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("نام مشتری نمی‌تواند خالی باشد.")
        clean_phone = str(phone or "").strip()
        clean_nid = str(national_id or "").strip()
        clean_addr = str(address or "").strip()
        clean_notes = str(notes or "").strip()
        mod_by = str(operator_name or "").strip()
        mod_at = time.strftime("%Y-%m-%d %H:%M:%S")

        def _resolve(connection):
            if clean_phone:
                row = connection.execute(
                    "SELECT id FROM customers WHERE name=? AND phone=? ORDER BY id DESC LIMIT 1",
                    (clean_name, clean_phone),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT id FROM customers WHERE name=? ORDER BY id DESC LIMIT 1",
                    (clean_name,),
                ).fetchone()
            if row:
                return int(row["id"])
            cur = connection.execute(
                """
                INSERT INTO customers (name, phone, notes, national_id, address, last_modified_by, last_modified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (clean_name, clean_phone, clean_notes, clean_nid, clean_addr, mod_by, mod_at),
            )
            return int(cur.lastrowid)

        if conn is not None:
            return _resolve(conn)
        return self.run_write_transaction(_resolve)

    def add_customer(
        self,
        name: str,
        phone: str = "",
        national_id: str = "",
        address: str = "",
        notes: str = "",
        operator_name: str = "",
    ) -> int:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("نام مشتری را وارد کنید.")
        mod_by = str(operator_name or "").strip()
        mod_at = time.strftime("%Y-%m-%d %H:%M:%S")

        def _tx(conn):
            cur = conn.execute(
                """
                INSERT INTO customers (name, phone, notes, national_id, address, last_modified_by, last_modified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_name,
                    str(phone or "").strip(),
                    str(notes or "").strip(),
                    str(national_id or "").strip(),
                    str(address or "").strip(),
                    mod_by,
                    mod_at,
                ),
            )
            cid = int(cur.lastrowid)
            self.log_audit(conn, "ثبت مشتری جدید", f"شناسه: {cid} | نام: {clean_name}")
            return cid

        return self.run_write_transaction(_tx)

    def update_customer(
        self,
        customer_id: int,
        name: str,
        phone: str = "",
        national_id: str = "",
        address: str = "",
        notes: str = "",
        operator_name: str = "",
        expected_row_version: Optional[int] = None,
    ) -> None:
        cid = self._batch_integer(customer_id, "شناسه مشتری", minimum=1)
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("نام مشتری نمی‌تواند خالی باشد.")
        mod_by = str(operator_name or "").strip()
        mod_at = time.strftime("%Y-%m-%d %H:%M:%S")

        def _tx(conn):
            if expected_row_version is not None:
                self._check_row_version(conn, "customers", cid, expected_row_version, "مشتری")
            conn.execute(
                """
                UPDATE customers
                SET name=?, phone=?, national_id=?, address=?, notes=?,
                    last_modified_by=?, last_modified_at=?
                WHERE id=?
                """,
                (
                    clean_name,
                    str(phone or "").strip(),
                    str(national_id or "").strip(),
                    str(address or "").strip(),
                    str(notes or "").strip(),
                    mod_by,
                    mod_at,
                    cid,
                ),
            )
            self.log_audit(conn, "ویرایش مشتری", f"شناسه: {cid} | نام: {clean_name}")

        self.run_write_transaction(_tx)

    def _delete_customers_tx(self, conn, cids: list[int], delete_related_data: bool = False) -> int:
        if not cids:
            return 0
        marks = ",".join("?" for _ in cids)
        if not delete_related_data:
            active_plan = conn.execute(
                f"SELECT id FROM installment_plans WHERE customer_id IN ({marks}) AND status='active' LIMIT 1",
                cids,
            ).fetchone()
            if active_plan:
                raise ValueError(
                    "این مشتری دارای طرح فروش اقساطی فعال است. ابتدا اقساط تسویه یا همراه با سوابق مرتبط حذف شود."
                )
            conn.execute(f"UPDATE sales SET customer_id=NULL WHERE customer_id IN ({marks})", cids)
            conn.execute(f"UPDATE service_records SET customer_id=NULL WHERE customer_id IN ({marks})", cids)
            conn.execute(f"UPDATE installment_plans SET customer_id=NULL WHERE customer_id IN ({marks})", cids)
            conn.execute(f"UPDATE checks SET customer_id=NULL WHERE customer_id IN ({marks})", cids)
            conn.execute(f"UPDATE proforma_invoices SET customer_id=NULL WHERE customer_id IN ({marks})", cids)
        else:
            sale_rows = conn.execute(
                f"SELECT id, invoice_number, batch_id, qty FROM sales WHERE customer_id IN ({marks}) ORDER BY id DESC",
                cids,
            ).fetchall()
            sale_ids = [int(r["id"]) for r in sale_rows]
            sale_invs = {str(r["invoice_number"] or "").strip() for r in sale_rows if str(r["invoice_number"] or "").strip()}
            for sr in sale_rows:
                conn.execute(
                    "UPDATE batches SET sold_qty=MAX(0, sold_qty-?), remaining_qty=remaining_qty+? WHERE id=?",
                    (int(sr["qty"]), int(sr["qty"]), int(sr["batch_id"])),
                )
            if sale_ids:
                s_marks = ",".join("?" for _ in sale_ids)
                conn.execute(
                    f"DELETE FROM installment_payments WHERE plan_id IN (SELECT id FROM installment_plans WHERE sale_id IN ({s_marks}))",
                    sale_ids,
                )
                conn.execute(f"DELETE FROM installment_plans WHERE sale_id IN ({s_marks})", sale_ids)
                conn.execute(f"DELETE FROM payments WHERE ref_type='sale' AND ref_id IN ({s_marks})", sale_ids)
                conn.execute(f"DELETE FROM checks WHERE ref_type='sale' AND ref_id IN ({s_marks})", sale_ids)
                conn.execute(f"DELETE FROM sales WHERE id IN ({s_marks})", sale_ids)
            for inv_no in sale_invs:
                if int(conn.execute("SELECT COUNT(*) FROM sales WHERE invoice_number=?", (inv_no,)).fetchone()[0] or 0) == 0:
                    conn.execute("DELETE FROM checks WHERE ref_type='sale' AND invoice_number=?", (inv_no,))
                    conn.execute("DELETE FROM invoice_headers WHERE invoice_kind='sale' AND invoice_number=?", (inv_no,))

            srv_rows = conn.execute(
                f"SELECT id, invoice_number FROM service_records WHERE customer_id IN ({marks})",
                cids,
            ).fetchall()
            srv_ids = [int(r["id"]) for r in srv_rows]
            srv_invs = {str(r["invoice_number"] or "").strip() for r in srv_rows if str(r["invoice_number"] or "").strip()}
            if srv_ids:
                v_marks = ",".join("?" for _ in srv_ids)
                conn.execute(
                    f"DELETE FROM installment_payments WHERE plan_id IN (SELECT id FROM installment_plans WHERE service_record_id IN ({v_marks}))",
                    srv_ids,
                )
                conn.execute(f"DELETE FROM installment_plans WHERE service_record_id IN ({v_marks})", srv_ids)
                conn.execute(f"DELETE FROM payments WHERE ref_type='service' AND ref_id IN ({v_marks})", srv_ids)
                conn.execute(f"DELETE FROM checks WHERE ref_type='service' AND ref_id IN ({v_marks})", srv_ids)
                conn.execute(f"DELETE FROM service_records WHERE id IN ({v_marks})", srv_ids)
            for inv_no in srv_invs:
                if int(conn.execute("SELECT COUNT(*) FROM service_records WHERE invoice_number=?", (inv_no,)).fetchone()[0] or 0) == 0:
                    conn.execute("DELETE FROM checks WHERE ref_type='service' AND invoice_number=?", (inv_no,))
                    conn.execute("DELETE FROM invoice_headers WHERE invoice_kind='service' AND invoice_number=?", (inv_no,))

            conn.execute(
                f"DELETE FROM installment_payments WHERE plan_id IN (SELECT id FROM installment_plans WHERE customer_id IN ({marks}))",
                cids,
            )
            conn.execute(f"DELETE FROM installment_plans WHERE customer_id IN ({marks})", cids)
            conn.execute(f"DELETE FROM checks WHERE customer_id IN ({marks})", cids)
            conn.execute(
                f"DELETE FROM proforma_items WHERE proforma_id IN (SELECT id FROM proforma_invoices WHERE customer_id IN ({marks}))",
                cids,
            )
            conn.execute(f"DELETE FROM proforma_invoices WHERE customer_id IN ({marks})", cids)

        cur = conn.execute(f"DELETE FROM customers WHERE id IN ({marks})", cids)
        return int(cur.rowcount or 0)

    def delete_customer(
        self,
        customer_id: int,
        delete_related_data: bool = False,
        expected_row_version: Optional[int] = None,
    ) -> None:
        cid = self._batch_integer(customer_id, "شناسه مشتری", minimum=1)

        def _tx(conn):
            if expected_row_version is not None:
                self._check_row_version(conn, "customers", cid, expected_row_version, "مشتری")
            self._delete_customers_tx(conn, [cid], delete_related_data=bool(delete_related_data))
            self.log_audit(conn, "حذف مشتری", f"شناسه مشتری: {cid} | حذف سوابق: {bool(delete_related_data)}")

        self.run_write_transaction(_tx)

    def _create_installment_plan_tx(
        self,
        conn,
        *,
        sale_id: Optional[int] = None,
        customer_id: int,
        total_bill: int,
        down_payment: int,
        count: int,
        start_due_date: str,
        interval_days: int = 30,
        notes: str = "",
        operator_name: str = "",
        cal_type: Optional[str] = None,
        first_installment_paid: bool = False,
        sale_date: str = "",
        ref_type: str = "sale",
        service_record_id: Optional[int] = None,
    ) -> dict:
        clean_ref_type = "service" if str(ref_type or "sale").strip().lower() == "service" else "sale"
        financed = self._sqlite_integer(total_bill - down_payment, "مبلغ باقی‌مانده اقساط")
        if financed <= 0:
            raise ValueError("مبلغ تقسیط‌شده باید بیشتر از صفر باشد.")
        schedule = self.build_installment_schedule(
            financed_amount=financed,
            count=count,
            start_due_date=start_due_date,
            interval_days=interval_days,
            cal_type=cal_type,
        )
        mod_by = str(operator_name or "").strip()
        mod_at = time.strftime("%Y-%m-%d %H:%M:%S")
        first_paid_flag = bool(first_installment_paid)
        first_paid_amt = int(schedule[0]["due_amount"]) if (first_paid_flag and schedule) else 0
        paid_date_first = str(sale_date or start_due_date or "").split(" ")[0].strip()
        plan_status = "completed" if (first_paid_flag and len(schedule) == 1) else "active"
        cur = conn.execute(
            """
            INSERT INTO installment_plans (
                sale_id, customer_id, total_bill, down_payment, financed_amount,
                installment_count, interval_days, start_due_date, status, notes,
                last_modified_by, last_modified_at, first_installment_paid,
                ref_type, service_record_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sale_id,
                customer_id,
                total_bill,
                down_payment,
                financed,
                count,
                interval_days,
                start_due_date,
                plan_status,
                notes,
                mod_by,
                mod_at,
                1 if first_paid_flag else 0,
                clean_ref_type,
                service_record_id,
            ),
        )
        plan_id = int(cur.lastrowid)
        rows_to_insert = []
        for idx, item in enumerate(schedule):
            is_first_paid = (idx == 0 and first_paid_flag)
            rows_to_insert.append((
                plan_id,
                item["installment_no"],
                item["due_date"],
                item["due_amount"],
                item["due_amount"] if is_first_paid else 0,
                paid_date_first if is_first_paid else "",
                "paid" if is_first_paid else "pending",
                ("پرداخت قسط اول هنگام ثبت خدمت" if clean_ref_type == "service" else "پرداخت قسط اول هنگام خرید") if is_first_paid else "",
                mod_by,
                mod_at,
            ))
        conn.executemany(
            """
            INSERT INTO installment_payments (
                plan_id, installment_no, due_date, due_amount, paid_amount, paid_date,
                status, notes, last_modified_by, last_modified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows_to_insert,
        )
        return {
            "plan_id": plan_id,
            "first_paid_amount": first_paid_amt,
            "plan_status": plan_status,
        }

    def pay_installment(
        self,
        installment_id: int,
        pay_amount: int,
        payment_date: str,
        notes: str = "",
        operator_name: str = "",
        expected_row_version: Optional[int] = None,
    ) -> dict:
        iid = self._batch_integer(installment_id, "شناسه قسط", minimum=1)
        amt = self._batch_integer(pay_amount, "مبلغ پرداختی قسط", minimum=1)
        p_date = str(payment_date or "").strip()
        if not p_date:
            raise ValueError("تاریخ پرداخت قسط مشخص نشده است.")
        clean_notes = str(notes or "").strip()
        mod_by = str(operator_name or "").strip()
        mod_at = time.strftime("%Y-%m-%d %H:%M:%S")

        def _tx(conn):
            if expected_row_version is not None:
                self._check_row_version(conn, "installment_payments", iid, expected_row_version, "قسط")
            row = conn.execute(
                """
                SELECT ip.*, p.sale_id, p.service_record_id, COALESCE(p.ref_type, 'sale') AS ref_type, p.customer_id
                FROM installment_payments ip
                JOIN installment_plans p ON p.id = ip.plan_id
                WHERE ip.id=?
                """,
                (iid,),
            ).fetchone()
            if not row:
                raise ValueError("قسط انتخاب‌شده یافت نشد.")
            rem_due = int(row["due_amount"]) - int(row["paid_amount"])
            if rem_due <= 0:
                raise ValueError("این قسط قبلاً به‌طور کامل تسویه شده است.")
            if amt > rem_due:
                raise ValueError(
                    f"مبلغ پرداختی ({amt:,} تومان) نمی‌تواند از مانده همین قسط ({rem_due:,} تومان) بیشتر باشد."
                )
            new_paid = int(row["paid_amount"]) + amt
            new_status = "paid" if new_paid >= int(row["due_amount"]) else "partial"
            merged_note = clean_notes or str(row["notes"] or "")
            conn.execute(
                """
                UPDATE installment_payments
                SET paid_amount=?, paid_date=?, status=?, notes=?,
                    last_modified_by=?, last_modified_at=?
                WHERE id=?
                """,
                (new_paid, p_date, new_status, merged_note, mod_by, mod_at, iid),
            )
            plan_ref_type = str(row["ref_type"] or "sale")
            inv_no = ""
            if plan_ref_type == "service" and row["service_record_id"] is not None:
                srv_id = int(row["service_record_id"])
                srv_row = conn.execute(
                    "SELECT invoice_number, service_fee, paid_amount, side_cost FROM service_records WHERE id=?",
                    (srv_id,),
                ).fetchone()
                if srv_row:
                    inv_no = str(srv_row["invoice_number"] or "").strip()
                    new_srv_paid = min(int(srv_row["service_fee"]), int(srv_row["paid_amount"]) + amt)
                    srv_status = "تسویه‌شده" if new_srv_paid >= int(srv_row["service_fee"]) else "تسویه جزئی"
                    new_net_prof = self._sqlite_integer(new_srv_paid - int(srv_row["side_cost"] or 0), "سود خالص خدمت")
                    conn.execute(
                        "UPDATE service_records SET paid_amount=?, net_profit=?, settlement_status=? WHERE id=?",
                        (new_srv_paid, new_net_prof, srv_status, srv_id),
                    )
                conn.execute(
                    "INSERT INTO payments (ref_type, ref_id, amount, payment_date, notes) VALUES ('service', ?, ?, ?, ?)",
                    (srv_id, amt, p_date.split(" ")[0], f"پرداخت قسط شماره {row['installment_no']}"),
                )
                if inv_no:
                    hdr = conn.execute(
                        "SELECT id, total_amount, paid_amount FROM invoice_headers WHERE invoice_kind='service' AND invoice_number=?",
                        (inv_no,),
                    ).fetchone()
                    if hdr:
                        h_paid = min(int(hdr["total_amount"]), int(hdr["paid_amount"]) + amt)
                        h_st = "تسویه‌شده" if h_paid >= int(hdr["total_amount"]) else "تسویه جزئی"
                        conn.execute(
                            "UPDATE invoice_headers SET paid_amount=?, settlement_status=?, last_modified_by=?, last_modified_at=? WHERE id=?",
                            (h_paid, h_st, mod_by, mod_at, int(hdr["id"])),
                        )
            elif row["sale_id"] is not None:
                sale_id = int(row["sale_id"])
                sale_row = conn.execute(
                    "SELECT invoice_number, total_amount, paid_amount FROM sales WHERE id=?", (sale_id,)
                ).fetchone()
                if sale_row:
                    inv_no = str(sale_row["invoice_number"] or "").strip()
                    new_sale_paid = min(int(sale_row["total_amount"]), int(sale_row["paid_amount"]) + amt)
                    sale_status = "تسویه‌شده" if new_sale_paid >= int(sale_row["total_amount"]) else "تسویه جزئی"
                    conn.execute(
                        "UPDATE sales SET paid_amount=?, settlement_status=? WHERE id=?",
                        (new_sale_paid, sale_status, sale_id),
                    )
                conn.execute(
                    "INSERT INTO payments (ref_type, ref_id, amount, payment_date, notes) VALUES ('sale', ?, ?, ?, ?)",
                    (sale_id, amt, p_date.split(" ")[0], f"پرداخت قسط شماره {row['installment_no']}"),
                )
                if inv_no:
                    hdr = conn.execute(
                        "SELECT id, total_amount, paid_amount FROM invoice_headers WHERE invoice_kind='sale' AND invoice_number=?",
                        (inv_no,),
                    ).fetchone()
                    if hdr:
                        h_paid = min(int(hdr["total_amount"]), int(hdr["paid_amount"]) + amt)
                        h_st = "تسویه‌شده" if h_paid >= int(hdr["total_amount"]) else "تسویه جزئی"
                        conn.execute(
                            "UPDATE invoice_headers SET paid_amount=?, settlement_status=?, last_modified_by=?, last_modified_at=? WHERE id=?",
                            (h_paid, h_st, mod_by, mod_at, int(hdr["id"])),
                        )

            open_cnt = conn.execute(
                "SELECT COUNT(*) FROM installment_payments WHERE plan_id=? AND status <> 'paid'",
                (int(row["plan_id"]),),
            ).fetchone()[0]
            plan_status = "completed" if int(open_cnt) == 0 else "active"
            conn.execute(
                "UPDATE installment_plans SET status=?, last_modified_by=?, last_modified_at=? WHERE id=?",
                (plan_status, mod_by, mod_at, int(row["plan_id"])),
            )
            self.log_audit(
                conn,
                "ثبت پرداخت قسط",
                f"قسط #{row['installment_no']} طرح {row['plan_id']} | مبلغ: {amt:,}",
            )
            return {
                "installment_id": iid,
                "plan_id": int(row["plan_id"]),
                "plan_status": plan_status,
                "new_paid": new_paid,
                "status": new_status,
            }

        return self.run_write_transaction(_tx)

    def list_customers_with_ledgers(
        self,
        today_str: str = "",
        search_text: str = "",
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[dict]:
        """Single-query SQL aggregation of customers across sales, services, invoice extra costs, installments & checks."""
        q_filter = ""
        params = [str(today_str or "").strip()]
        clean_search = str(search_text or "").strip()
        if clean_search:
            like = f"%{clean_search}%"
            q_filter = "WHERE (c.name LIKE ? OR c.phone LIKE ? OR c.national_id LIKE ? OR c.address LIKE ? OR c.notes LIKE ?)"
            params.extend([like, like, like, like, like])
        limit_sql = ""
        if limit is not None and int(limit) > 0:
            limit_sql = f" LIMIT {int(limit)} OFFSET {max(0, int(offset))}"
        sql = f"""
            WITH sale_inv AS (
                SELECT
                    s.customer_id,
                    s.invoice_number,
                    COALESCE(SUM(s.total_amount), 0) + COALESCE(MAX(ih.extra_cost_total), 0) AS inv_total,
                    MIN(
                        COALESCE(SUM(s.total_amount), 0) + COALESCE(MAX(ih.extra_cost_total), 0),
                        MAX(COALESCE(SUM(s.paid_amount), 0), COALESCE(MAX(ih.paid_amount), 0))
                    ) AS inv_paid
                FROM sales s
                LEFT JOIN invoice_headers ih ON ih.invoice_kind='sale' AND ih.invoice_number=s.invoice_number
                WHERE s.customer_id IS NOT NULL
                GROUP BY s.customer_id, s.invoice_number
            ),
            srv_inv AS (
                SELECT
                    sr.customer_id,
                    sr.invoice_number,
                    COALESCE(SUM(sr.service_fee), 0) + COALESCE(MAX(ih.extra_cost_total), 0) AS inv_total,
                    MIN(
                        COALESCE(SUM(sr.service_fee), 0) + COALESCE(MAX(ih.extra_cost_total), 0),
                        MAX(COALESCE(SUM(sr.paid_amount), 0), COALESCE(MAX(ih.paid_amount), 0))
                    ) AS inv_paid
                FROM service_records sr
                LEFT JOIN invoice_headers ih ON ih.invoice_kind='service' AND ih.invoice_number=sr.invoice_number
                WHERE sr.customer_id IS NOT NULL
                GROUP BY sr.customer_id, sr.invoice_number
            ),
            all_cust_inv AS (
                SELECT customer_id, inv_total, inv_paid FROM sale_inv
                UNION ALL
                SELECT customer_id, inv_total, inv_paid FROM srv_inv
            ),
            sale_agg AS (
                SELECT
                    customer_id,
                    COUNT(*) AS invoice_count,
                    COALESCE(SUM(inv_total), 0) AS total_purchases,
                    COALESCE(SUM(inv_paid), 0) AS total_paid,
                    COALESCE(SUM(MAX(0, inv_total - inv_paid)), 0) AS remaining_debt
                FROM all_cust_inv
                GROUP BY customer_id
            ),
            inst_agg AS (
                SELECT
                    p.customer_id,
                    COALESCE(SUM(CASE WHEN ip.status <> 'paid' THEN 1 ELSE 0 END), 0) AS open_installments,
                    COALESCE(SUM(CASE WHEN ip.status <> 'paid' AND ? <> '' AND substr(ip.due_date, 1, 10) < substr(?, 1, 10) THEN 1 ELSE 0 END), 0) AS overdue_count
                FROM installment_plans p
                JOIN installment_payments ip ON ip.plan_id = p.id
                WHERE p.status = 'active' AND p.customer_id IS NOT NULL
                GROUP BY p.customer_id
            ),
            chk_agg AS (
                SELECT
                    customer_id,
                    COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END), 0) AS pending_checks_count,
                    COALESCE(SUM(CASE WHEN status='pending' THEN amount ELSE 0 END), 0) AS pending_checks_amount
                FROM checks
                WHERE customer_id IS NOT NULL AND direction='receivable'
                GROUP BY customer_id
            )
            SELECT
                c.id, c.name, c.phone, c.national_id, c.address, c.notes,
                c.created_at, c.updated_at, c.row_version, c.last_modified_by, c.last_modified_at,
                COALESCE(sa.invoice_count, 0) AS invoice_count,
                COALESCE(sa.total_purchases, 0) AS total_purchases,
                COALESCE(sa.total_paid, 0) AS total_paid,
                COALESCE(sa.remaining_debt, 0) AS remaining_debt,
                COALESCE(ia.open_installments, 0) AS open_installments,
                COALESCE(ia.overdue_count, 0) AS overdue_count,
                COALESCE(ca.pending_checks_count, 0) AS pending_checks_count,
                COALESCE(ca.pending_checks_amount, 0) AS pending_checks_amount
            FROM customers c
            LEFT JOIN sale_agg sa ON sa.customer_id = c.id
            LEFT JOIN inst_agg ia ON ia.customer_id = c.id
            LEFT JOIN chk_agg ca ON ca.customer_id = c.id
            {q_filter}
            ORDER BY COALESCE(sa.remaining_debt, 0) DESC, c.updated_at DESC, c.id DESC
            {limit_sql}
        """
        full_params = [params[0], params[0]] + params[1:]
        with self.get_connection() as conn:
            return [dict(r) for r in conn.execute(sql, full_params).fetchall()]

    def get_customer_sales_and_installments(self, customer_id: Optional[int] = None) -> dict:
        cid = int(customer_id) if customer_id is not None else None
        with self.get_connection() as conn:
            cust = conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone() if cid is not None else None
            c_clause_s = "WHERE s.customer_id=?" if cid is not None else ""
            c_params_s = (cid,) if cid is not None else ()
            sales_rows = conn.execute(
                f"""
                SELECT s.id, 'sale' AS record_kind, s.invoice_number, s.sale_datetime AS tx_datetime,
                       s.sale_datetime, s.qty, s.total_amount, s.paid_amount,
                       s.settlement_status, s.payment_type, s.settlement_subtype, s.check_due_date, s.check_status,
                       COALESCE(NULLIF(trim(COALESCE(p.brand, '') || ' ' || COALESCE(p.model, '')), ''), p.name, '-') AS product_label,
                       COALESCE(c.name, s.customer_name, '-') AS party_name
                FROM sales s
                LEFT JOIN products p ON p.id = s.product_id
                LEFT JOIN customers c ON c.id = s.customer_id
                {c_clause_s}
                ORDER BY s.sale_datetime DESC, s.id DESC
                """,
                c_params_s,
            ).fetchall()
            c_clause_srv = "WHERE sr.customer_id=?" if cid is not None else ""
            srv_rows = conn.execute(
                f"""
                SELECT sr.id, 'service' AS record_kind, sr.invoice_number, sr.service_datetime AS tx_datetime,
                       sr.service_datetime AS sale_datetime, 1 AS qty, sr.service_fee AS total_amount, sr.paid_amount,
                       sr.settlement_status, sr.payment_type, sr.settlement_subtype, sr.check_due_date, sr.check_status,
                       ('خدمت: ' || COALESCE(sr.service_name, '-')) AS product_label,
                       COALESCE(c.name, sr.customer_name, '-') AS party_name
                FROM service_records sr
                LEFT JOIN customers c ON c.id = sr.customer_id
                {c_clause_srv}
                ORDER BY sr.service_datetime DESC, sr.id DESC
                """,
                c_params_srv := c_params_s,
            ).fetchall()
            merged_tx = [dict(r) for r in sales_rows] + [dict(r) for r in srv_rows]
            merged_tx.sort(key=lambda r: (str(r.get("tx_datetime") or ""), int(r.get("id") or 0)), reverse=True)
            c_clause_ip = "WHERE pl.customer_id=?" if cid is not None else ""
            installments_rows = conn.execute(
                f"""
                SELECT ip.*, pl.sale_id, pl.service_record_id, COALESCE(pl.ref_type, 'sale') AS ref_type,
                       COALESCE(s.invoice_number, sr.invoice_number, '-') AS invoice_number,
                       COALESCE(c.name, s.customer_name, sr.customer_name, '-') AS party_name
                FROM installment_payments ip
                JOIN installment_plans pl ON pl.id = ip.plan_id
                LEFT JOIN sales s ON s.id = pl.sale_id
                LEFT JOIN service_records sr ON sr.id = pl.service_record_id
                LEFT JOIN customers c ON c.id = pl.customer_id
                {c_clause_ip}
                ORDER BY ip.due_date ASC, ip.installment_no ASC, ip.id ASC
                """,
                c_params_s,
            ).fetchall()
            c_clause_chk = "WHERE customer_id=? AND direction='receivable'" if cid is not None else "WHERE direction='receivable'"
            check_rows = conn.execute(
                f"""
                SELECT * FROM checks
                {c_clause_chk}
                ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'bounced' THEN 1 ELSE 2 END, due_date ASC, id DESC
                """,
                c_params_s,
            ).fetchall()
            return {
                "customer": dict(cust) if cust else None,
                "sales": merged_tx,
                "installments": [dict(r) for r in installments_rows],
                "checks": [dict(r) for r in check_rows],
            }

    def get_installments_overview(self, today_str: str = "") -> dict:
        t_date = str(today_str or "").strip()[:10]
        with self.get_connection() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN ip.status <> 'paid' THEN MAX(0, ip.due_amount - ip.paid_amount) ELSE 0 END), 0) AS total_unpaid_installments,
                    COALESCE(SUM(CASE WHEN ip.status <> 'paid' AND ? <> '' AND substr(ip.due_date, 1, 10) < ? THEN 1 ELSE 0 END), 0) AS overdue_count,
                    COALESCE(SUM(CASE WHEN ip.status <> 'paid' AND ? <> '' AND substr(ip.due_date, 1, 10) < ? THEN MAX(0, ip.due_amount - ip.paid_amount) ELSE 0 END), 0) AS overdue_amount,
                    COALESCE(SUM(CASE WHEN ip.status <> 'paid' THEN 1 ELSE 0 END), 0) AS open_count
                FROM installment_payments ip
                JOIN installment_plans pl ON pl.id = ip.plan_id
                WHERE pl.status = 'active'
                """,
                (t_date, t_date, t_date, t_date),
            ).fetchone()
            cust_debt = conn.execute(
                """
                SELECT (
                    COALESCE((
                        SELECT SUM(MAX(0, inv_tot - inv_paid))
                        FROM (
                            SELECT s.invoice_number,
                                   COALESCE(SUM(s.total_amount), 0) + COALESCE(MAX(ih.extra_cost_total), 0) AS inv_tot,
                                   MIN(
                                       COALESCE(SUM(s.total_amount), 0) + COALESCE(MAX(ih.extra_cost_total), 0),
                                       MAX(COALESCE(SUM(s.paid_amount), 0), COALESCE(MAX(ih.paid_amount), 0))
                                   ) AS inv_paid
                            FROM sales s
                            LEFT JOIN invoice_headers ih ON ih.invoice_kind='sale' AND ih.invoice_number=s.invoice_number
                            GROUP BY s.invoice_number
                        )
                    ), 0)
                    +
                    COALESCE((
                        SELECT SUM(MAX(0, inv_tot - inv_paid))
                        FROM (
                            SELECT sr.invoice_number,
                                   COALESCE(SUM(sr.service_fee), 0) + COALESCE(MAX(ih.extra_cost_total), 0) AS inv_tot,
                                   MIN(
                                       COALESCE(SUM(sr.service_fee), 0) + COALESCE(MAX(ih.extra_cost_total), 0),
                                       MAX(COALESCE(SUM(sr.paid_amount), 0), COALESCE(MAX(ih.paid_amount), 0))
                                   ) AS inv_paid
                            FROM service_records sr
                            LEFT JOIN invoice_headers ih ON ih.invoice_kind='service' AND ih.invoice_number=sr.invoice_number
                            GROUP BY sr.invoice_number
                        )
                    ), 0)
                )
                """
            ).fetchone()[0]
            return {
                "total_receivables": int(cust_debt or 0),
                "total_unpaid_installments": int(row["total_unpaid_installments"] or 0) if row else 0,
                "overdue_count": int(row["overdue_count"] or 0) if row else 0,
                "overdue_amount": int(row["overdue_amount"] or 0) if row else 0,
                "open_count": int(row["open_count"] or 0) if row else 0,
            }

    def get_chart_analytics_data(
        self,
        date_from: str = "",
        date_to: str = "",
        seller_employee_id: Optional[int] = None,
        category: str = "",
        top_n: int = 10,
        visible_employee_ids: Optional[set] = None,
    ) -> dict:
        """Fast SQL GROUP BY aggregations for 50k+ sales across all native QPainter charts."""
        clauses = ["1=1"]
        params = []
        d_from = str(date_from or "").strip()[:10]
        d_to = str(date_to or "").strip()[:10]
        if d_from:
            clauses.append("substr(s.sale_datetime, 1, 10) >= ?")
            params.append(d_from)
        if d_to:
            clauses.append("substr(s.sale_datetime, 1, 10) <= ?")
            params.append(d_to)
        if seller_employee_id is not None:
            clauses.append("s.seller_employee_id = ?")
            params.append(int(seller_employee_id))
        elif visible_employee_ids is not None:
            if not visible_employee_ids:
                return {
                    "best_selling": [], "most_profitable": [], "time_trend": [],
                    "by_category": [], "by_seller": [], "payment_mix": {},
                }
            marks = ",".join("?" for _ in visible_employee_ids)
            clauses.append(f"s.seller_employee_id IN ({marks})")
            params.extend(sorted(visible_employee_ids))
        clean_cat = str(category or "").strip()
        if clean_cat and clean_cat != "همه دسته‌ها":
            clauses.append("p.category = ?")
            params.append(clean_cat)

        where_sql = " AND ".join(clauses)
        n_lim = max(1, min(50, int(top_n or 10)))

        with self.get_connection() as conn:
            best_selling = [
                {
                    "label": (
                        f"{r['category'] or ''} {r['brand'] or ''} {r['model'] or ''}".strip()
                        or str(r["name"] or r["code"] or "-")
                    ),
                    "qty": int(r["tot_qty"] or 0),
                    "revenue": int(r["tot_rev"] or 0),
                    "profit": int(r["tot_prof"] or 0),
                }
                for r in conn.execute(
                    f"""
                    SELECT p.code, p.category, p.brand, p.model, p.name,
                           COALESCE(SUM(s.qty), 0) AS tot_qty,
                           COALESCE(SUM(s.total_amount), 0) AS tot_rev,
                           COALESCE(SUM(s.total_profit), 0) AS tot_prof
                    FROM sales s
                    JOIN products p ON p.id = s.product_id
                    WHERE {where_sql}
                    GROUP BY s.product_id
                    ORDER BY tot_qty DESC, tot_rev DESC
                    LIMIT {n_lim}
                    """,
                    params,
                ).fetchall()
            ]
            most_profitable = [
                {
                    "label": (
                        f"{r['category'] or ''} {r['brand'] or ''} {r['model'] or ''}".strip()
                        or str(r["name"] or r["code"] or "-")
                    ),
                    "profit": int(r["tot_prof"] or 0),
                    "revenue": int(r["tot_rev"] or 0),
                    "qty": int(r["tot_qty"] or 0),
                }
                for r in conn.execute(
                    f"""
                    SELECT p.code, p.category, p.brand, p.model, p.name,
                           COALESCE(SUM(s.total_profit), 0) AS tot_prof,
                           COALESCE(SUM(s.total_amount), 0) AS tot_rev,
                           COALESCE(SUM(s.qty), 0) AS tot_qty
                    FROM sales s
                    JOIN products p ON p.id = s.product_id
                    WHERE {where_sql}
                    GROUP BY s.product_id
                    ORDER BY tot_prof DESC, tot_rev DESC
                    LIMIT {n_lim}
                    """,
                    params,
                ).fetchall()
            ]
            time_trend = [
                {
                    "date": str(r["d_bucket"] or "-"),
                    "revenue": int(r["tot_rev"] or 0),
                    "profit": int(r["tot_prof"] or 0),
                    "qty": int(r["tot_qty"] or 0),
                }
                for r in conn.execute(
                    f"""
                    SELECT substr(s.sale_datetime, 1, 10) AS d_bucket,
                           COALESCE(SUM(s.total_amount), 0) AS tot_rev,
                           COALESCE(SUM(s.total_profit), 0) AS tot_prof,
                           COALESCE(SUM(s.qty), 0) AS tot_qty
                    FROM sales s
                    JOIN products p ON p.id = s.product_id
                    WHERE {where_sql} AND length(trim(s.sale_datetime)) >= 10
                    GROUP BY d_bucket
                    ORDER BY d_bucket ASC
                    LIMIT 90
                    """,
                    params,
                ).fetchall()
            ]
            by_category = [
                {
                    "label": str(r["cat"] or "سایر"),
                    "revenue": int(r["tot_rev"] or 0),
                    "profit": int(r["tot_prof"] or 0),
                    "qty": int(r["tot_qty"] or 0),
                }
                for r in conn.execute(
                    f"""
                    SELECT COALESCE(NULLIF(trim(p.category), ''), 'سایر') AS cat,
                           COALESCE(SUM(s.total_amount), 0) AS tot_rev,
                           COALESCE(SUM(s.total_profit), 0) AS tot_prof,
                           COALESCE(SUM(s.qty), 0) AS tot_qty
                    FROM sales s
                    JOIN products p ON p.id = s.product_id
                    WHERE {where_sql}
                    GROUP BY cat
                    ORDER BY tot_rev DESC
                    LIMIT 20
                    """,
                    params,
                ).fetchall()
            ]
            by_seller = [
                {
                    "label": str(r["seller_name"] or "نامشخص"),
                    "revenue": int(r["tot_rev"] or 0),
                    "profit": int(r["tot_prof"] or 0),
                    "qty": int(r["tot_qty"] or 0),
                    "invoices": int(r["inv_cnt"] or 0),
                }
                for r in conn.execute(
                    f"""
                    SELECT COALESCE(NULLIF(trim(e.name), ''), 'نامشخص') AS seller_name,
                           COALESCE(SUM(s.total_amount), 0) AS tot_rev,
                           COALESCE(SUM(s.total_profit), 0) AS tot_prof,
                           COALESCE(SUM(s.qty), 0) AS tot_qty,
                           COUNT(*) AS inv_cnt
                    FROM sales s
                    JOIN products p ON p.id = s.product_id
                    LEFT JOIN employees e ON e.id = s.seller_employee_id
                    WHERE {where_sql}
                    GROUP BY seller_name
                    ORDER BY tot_rev DESC
                    LIMIT 20
                    """,
                    params,
                ).fetchall()
            ]
            pm_row = conn.execute(
                f"""
                SELECT
                    COALESCE(SUM(CASE WHEN COALESCE(s.payment_type, 'cash') = 'cash' THEN s.total_amount ELSE 0 END), 0) AS cash_total,
                    COALESCE(SUM(CASE WHEN s.payment_type = 'installment' THEN s.paid_amount ELSE 0 END), 0) AS inst_collected,
                    COALESCE(SUM(CASE WHEN s.payment_type = 'installment' THEN MAX(0, s.total_amount - s.paid_amount) ELSE 0 END), 0) AS inst_outstanding,
                    COALESCE(SUM(CASE WHEN COALESCE(s.payment_type, 'cash') <> 'installment' AND s.settlement_status <> 'تسویه‌شده' THEN MAX(0, s.total_amount - s.paid_amount) ELSE 0 END), 0) AS credit_outstanding
                FROM sales s
                JOIN products p ON p.id = s.product_id
                WHERE {where_sql}
                """,
                params,
            ).fetchone()
            payment_mix = {
                "cash_total": int(pm_row["cash_total"] or 0) if pm_row else 0,
                "installment_collected": int(pm_row["inst_collected"] or 0) if pm_row else 0,
                "installment_outstanding": int(pm_row["inst_outstanding"] or 0) if pm_row else 0,
                "credit_outstanding": int(pm_row["credit_outstanding"] or 0) if pm_row else 0,
            }
            return {
                "best_selling": best_selling,
                "most_profitable": most_profitable,
                "time_trend": time_trend,
                "by_category": by_category,
                "by_seller": by_seller,
                "payment_mix": payment_mix,
            }

    # =========================================================================
    # چک‌ها و گزارش عملکرد بازه‌ای کاربران (Daqiq v5.0.0)
    # =========================================================================
    def get_checks_overview(self, today_str: str = "") -> dict:
        t_date = str(today_str or "").strip()[:10]
        with self.get_connection() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN direction='receivable' AND status='pending' THEN 1 ELSE 0 END), 0) AS recv_pending_cnt,
                    COALESCE(SUM(CASE WHEN direction='receivable' AND status='pending' THEN amount ELSE 0 END), 0) AS recv_pending_amt,
                    COALESCE(SUM(CASE WHEN direction='receivable' AND status='pending' AND ? <> '' AND substr(due_date, 1, 10) < ? THEN 1 ELSE 0 END), 0) AS recv_overdue_cnt,
                    COALESCE(SUM(CASE WHEN direction='payable' AND status='pending' THEN 1 ELSE 0 END), 0) AS pay_pending_cnt,
                    COALESCE(SUM(CASE WHEN direction='payable' AND status='pending' THEN amount ELSE 0 END), 0) AS pay_pending_amt,
                    COALESCE(SUM(CASE WHEN direction='payable' AND status='pending' AND ? <> '' AND substr(due_date, 1, 10) < ? THEN 1 ELSE 0 END), 0) AS pay_overdue_cnt
                FROM checks
                """,
                (t_date, t_date, t_date, t_date),
            ).fetchone()
            return {
                "receivable_pending_count": int(row["recv_pending_cnt"] or 0) if row else 0,
                "receivable_pending_amount": int(row["recv_pending_amt"] or 0) if row else 0,
                "receivable_overdue_count": int(row["recv_overdue_cnt"] or 0) if row else 0,
                "payable_pending_count": int(row["pay_pending_cnt"] or 0) if row else 0,
                "payable_pending_amount": int(row["pay_pending_amt"] or 0) if row else 0,
                "payable_overdue_count": int(row["pay_overdue_cnt"] or 0) if row else 0,
            }

    def list_checks(
        self,
        *,
        direction: Optional[str] = None,
        status: Optional[str] = None,
        customer_id: Optional[int] = None,
        supplier_id: Optional[int] = None,
        search_text: str = "",
    ) -> list[dict]:
        clauses = ["1=1"]
        params: list = []
        if direction in ("receivable", "payable"):
            clauses.append("c.direction = ?")
            params.append(direction)
        if status in ("pending", "cleared", "bounced"):
            clauses.append("c.status = ?")
            params.append(status)
        if customer_id is not None:
            clauses.append("c.customer_id = ?")
            params.append(int(customer_id))
        if supplier_id is not None:
            clauses.append("c.supplier_id = ?")
            params.append(int(supplier_id))
        clean_q = str(search_text or "").strip()
        if clean_q:
            like = f"%{clean_q}%"
            clauses.append("(c.invoice_number LIKE ? OR c.party_name LIKE ? OR c.party_phone LIKE ? OR c.check_number LIKE ?)")
            params.extend([like, like, like, like])
        where_sql = " AND ".join(clauses)
        with self.get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT c.*
                FROM checks c
                WHERE {where_sql}
                ORDER BY CASE c.status WHEN 'pending' THEN 0 WHEN 'bounced' THEN 1 ELSE 2 END,
                         c.due_date ASC, c.id DESC
                """,
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def update_check_status(
        self,
        check_id: int,
        new_status: str,
        cleared_date: str = "",
        notes: str = "",
        operator_name: str = "",
        expected_row_version: Optional[int] = None,
    ) -> dict:
        cid = self._batch_integer(check_id, "شناسه چک", minimum=1)
        clean_st = str(new_status or "").strip().lower()
        if clean_st not in ("pending", "cleared", "bounced"):
            st_map = {
                "در انتظار وصول": "pending",
                "وصول شده": "cleared",
                "وصول‌شده": "cleared",
                "برگشتی": "bounced",
                "برگشت خورده": "bounced",
            }
            clean_st = st_map.get(str(new_status or "").strip(), "")
        if clean_st not in ("pending", "cleared", "bounced"):
            raise ValueError("وضعیت چک نامعتبر است.")
        mod_by = str(operator_name or "").strip()
        mod_at = time.strftime("%Y-%m-%d %H:%M:%S")

        def _tx(conn):
            if expected_row_version is not None:
                self._check_row_version(conn, "checks", cid, expected_row_version, "چک")
            chk = conn.execute("SELECT * FROM checks WHERE id=?", (cid,)).fetchone()
            if not chk:
                raise ValueError("چک انتخاب‌شده یافت نشد.")
            c_date = str(cleared_date or "").strip() if clean_st == "cleared" else ""
            merged_note = str(notes or "").strip() or str(chk["notes"] or "")
            conn.execute(
                """
                UPDATE checks
                SET status=?, cleared_date=?, notes=?, last_modified_by=?, last_modified_at=?
                WHERE id=?
                """,
                (clean_st, c_date, merged_note, mod_by, mod_at, cid),
            )
            inv_no = str(chk["invoice_number"] or "").strip()
            ref_type = str(chk["ref_type"] or "")
            if inv_no:
                if ref_type == "sale":
                    conn.execute("UPDATE sales SET check_status=? WHERE invoice_number=?", (clean_st, inv_no))
                elif ref_type == "batch":
                    conn.execute(
                        "UPDATE batches SET check_status=? WHERE purchase_invoice_code=? OR invoice_number=?",
                        (clean_st, inv_no, inv_no),
                    )
                elif ref_type == "service":
                    conn.execute("UPDATE service_records SET check_status=? WHERE invoice_number=?", (clean_st, inv_no))
                conn.execute(
                    "UPDATE invoice_headers SET check_status=?, last_modified_by=?, last_modified_at=? WHERE invoice_kind=? AND invoice_number=?",
                    (clean_st, mod_by, mod_at, ref_type, inv_no),
                )
            self.log_audit(conn, "تغییر وضعیت چک", f"فاکتور {inv_no or cid} -> {clean_st}")
            return {"check_id": cid, "status": clean_st, "cleared_date": c_date}

        return self.run_write_transaction(_tx)

    def get_employee_performance_report(
        self,
        date_from: str = "",
        date_to: str = "",
        visible_employee_ids: Optional[set] = None,
    ) -> list[dict]:
        """Aggregate per-employee sales, services, upgrades, and installment/check collections over a date range."""
        d_from = str(date_from or "").strip()[:10]
        d_to = str(date_to or "").strip()[:10]
        with self.get_connection() as conn:
            emp_sql = "SELECT id, name, role, is_active FROM employees"
            emp_params: list = []
            if visible_employee_ids is not None:
                if not visible_employee_ids:
                    return []
                marks = ",".join("?" for _ in visible_employee_ids)
                emp_sql += f" WHERE id IN ({marks})"
                emp_params.extend(sorted(visible_employee_ids))
            emp_sql += " ORDER BY name COLLATE NOCASE"
            employees = conn.execute(emp_sql, emp_params).fetchall()

            def _dt_clause(col: str) -> tuple[str, list]:
                cl = ["1=1"]
                pr: list = []
                if d_from:
                    cl.append(f"substr({col}, 1, 10) >= ?")
                    pr.append(d_from)
                if d_to:
                    cl.append(f"substr({col}, 1, 10) <= ?")
                    pr.append(d_to)
                return " AND ".join(cl), pr

            s_where, s_p = _dt_clause("sale_datetime")
            sales_map = {
                int(r["eid"]): dict(r)
                for r in conn.execute(
                    f"""
                    SELECT seller_employee_id AS eid,
                           COUNT(DISTINCT invoice_number) AS sale_invoices,
                           COALESCE(SUM(qty), 0) AS sale_qty,
                           COALESCE(SUM(total_amount), 0) AS sale_revenue,
                           COALESCE(SUM(paid_amount), 0) AS sale_collected,
                           COALESCE(SUM(total_discount), 0) AS sale_discount,
                           COALESCE(SUM(total_profit), 0) AS sale_profit
                    FROM sales
                    WHERE seller_employee_id IS NOT NULL AND {s_where}
                    GROUP BY seller_employee_id
                    """,
                    s_p,
                ).fetchall()
            }

            srv_where, srv_p = _dt_clause("service_datetime")
            srv_seller_map = {
                int(r["eid"]): dict(r)
                for r in conn.execute(
                    f"""
                    SELECT seller_employee_id AS eid,
                           COUNT(DISTINCT invoice_number) AS srv_count,
                           COALESCE(SUM(service_fee), 0) AS srv_revenue,
                           COALESCE(SUM(net_profit), 0) AS srv_profit
                    FROM service_records
                    WHERE seller_employee_id IS NOT NULL AND {srv_where}
                    GROUP BY seller_employee_id
                    """,
                    srv_p,
                ).fetchall()
            }
            srv_tech_map = {
                int(r["eid"]): dict(r)
                for r in conn.execute(
                    f"""
                    SELECT technician_employee_id AS eid,
                           COUNT(DISTINCT invoice_number) AS tech_count,
                           COALESCE(SUM(net_profit), 0) AS tech_profit
                    FROM service_records
                    WHERE technician_employee_id IS NOT NULL AND technician_employee_id <> COALESCE(seller_employee_id, -1)
                      AND {srv_where}
                    GROUP BY technician_employee_id
                    """,
                    srv_p,
                ).fetchall()
            }

            u_where, u_p = _dt_clause("upgrade_date")
            upg_map = {
                int(r["eid"]): dict(r)
                for r in conn.execute(
                    f"""
                    SELECT technician_id AS eid,
                           COUNT(*) AS upg_count,
                           COALESCE(SUM(labor_cost_unit * target_qty), 0) AS upg_labor
                    FROM upgrades
                    WHERE technician_id IS NOT NULL AND {u_where}
                    GROUP BY technician_id
                    """,
                    u_p,
                ).fetchall()
            }

            inst_where, inst_p = _dt_clause("paid_date")
            inst_map = {
                str(r["op"] or "").strip(): dict(r)
                for r in conn.execute(
                    f"""
                    SELECT last_modified_by AS op,
                           COUNT(*) AS inst_collected_cnt,
                           COALESCE(SUM(paid_amount), 0) AS inst_collected_amt
                    FROM installment_payments
                    WHERE status IN ('paid', 'partial') AND paid_amount > 0
                      AND trim(COALESCE(last_modified_by, '')) <> ''
                      AND {inst_where}
                    GROUP BY last_modified_by
                    """,
                    inst_p,
                ).fetchall()
            }

            results = []
            for emp in employees:
                eid = int(emp["id"])
                ename = str(emp["name"] or "")
                s_data = sales_map.get(eid, {})
                sv_data = srv_seller_map.get(eid, {})
                st_data = srv_tech_map.get(eid, {})
                ug_data = upg_map.get(eid, {})
                in_data = inst_map.get(ename.strip(), {})
                s_prof = int(s_data.get("sale_profit") or 0)
                sv_prof = int(sv_data.get("srv_profit") or 0) + int(st_data.get("tech_profit") or 0)
                ug_lab = int(ug_data.get("upg_labor") or 0)
                results.append({
                    "employee_id": eid,
                    "name": ename,
                    "role": str(emp["role"] or ""),
                    "is_active": bool(emp["is_active"]),
                    "sale_invoices": int(s_data.get("sale_invoices") or 0),
                    "sale_qty": int(s_data.get("sale_qty") or 0),
                    "sale_revenue": int(s_data.get("sale_revenue") or 0),
                    "sale_discount": int(s_data.get("sale_discount") or 0),
                    "sale_profit": s_prof,
                    "service_count": int(sv_data.get("srv_count") or 0) + int(st_data.get("tech_count") or 0),
                    "service_revenue": int(sv_data.get("srv_revenue") or 0),
                    "service_profit": sv_prof,
                    "upgrade_count": int(ug_data.get("upg_count") or 0),
                    "upgrade_labor": ug_lab,
                    "installments_collected": int(in_data.get("inst_collected_amt") or 0),
                    "total_profit": s_prof + sv_prof,
                })
            return results

    # =========================================================================
    # اقساط خرید و دفتر حساب تأمین‌کنندگان (Daqiq v5.0.1 - REQ-06)
    # =========================================================================
    def pay_supplier_installment(
        self,
        installment_id: int,
        pay_amount: int,
        payment_date: str,
        notes: str = "",
        operator_name: str = "",
        expected_row_version: Optional[int] = None,
    ) -> dict:
        iid = self._batch_integer(installment_id, "شناسه قسط تأمین‌کننده", minimum=1)
        amt = self._batch_integer(pay_amount, "مبلغ پرداختی قسط", minimum=1)
        p_date = str(payment_date or "").strip()
        if not p_date:
            raise ValueError("تاریخ پرداخت قسط مشخص نشده است.")
        clean_notes = str(notes or "").strip()
        mod_by = str(operator_name or "").strip()
        mod_at = time.strftime("%Y-%m-%d %H:%M:%S")

        def _tx(conn):
            if expected_row_version is not None:
                self._check_row_version(conn, "supplier_installment_payments", iid, expected_row_version, "قسط تأمین‌کننده")
            row = conn.execute(
                """
                SELECT sp.*, pl.purchase_invoice_code, pl.batch_id, pl.supplier_id
                FROM supplier_installment_payments sp
                JOIN supplier_installment_plans pl ON pl.id = sp.plan_id
                WHERE sp.id=?
                """,
                (iid,),
            ).fetchone()
            if not row:
                raise ValueError("قسط انتخاب‌شده یافت نشد.")
            rem_due = int(row["due_amount"]) - int(row["paid_amount"])
            if rem_due <= 0:
                raise ValueError("این قسط قبلاً به‌طور کامل پرداخت شده است.")
            if amt > rem_due:
                raise ValueError(
                    f"مبلغ پرداختی ({amt:,} تومان) نمی‌تواند از مانده همین قسط ({rem_due:,} تومان) بیشتر باشد."
                )
            new_paid = int(row["paid_amount"]) + amt
            new_status = "paid" if new_paid >= int(row["due_amount"]) else "partial"
            merged_note = clean_notes or str(row["notes"] or "")
            conn.execute(
                """
                UPDATE supplier_installment_payments
                SET paid_amount=?, paid_date=?, status=?, notes=?,
                    last_modified_by=?, last_modified_at=?
                WHERE id=?
                """,
                (new_paid, p_date, new_status, merged_note, mod_by, mod_at, iid),
            )
            pinv_code = str(row["purchase_invoice_code"] or "").strip()
            batch_rows = conn.execute(
                """
                SELECT id, initial_qty, unit_purchase_price, extra_cost_total, paid_amount
                FROM batches
                WHERE (purchase_invoice_code=? AND ? <> '') OR id=?
                ORDER BY id ASC
                """,
                (pinv_code, pinv_code, int(row["batch_id"])),
            ).fetchall()
            hdr_extra_row = None
            if pinv_code:
                hdr_extra_row = conn.execute(
                    "SELECT total_amount, extra_cost_total, paid_amount FROM invoice_headers WHERE invoice_kind='batch' AND invoice_number=?",
                    (pinv_code,),
                ).fetchone()
            rem_to_apply = amt
            total_bill_all = int(hdr_extra_row["extra_cost_total"] or 0) if hdr_extra_row else 0
            prev_hdr_paid = int(hdr_extra_row["paid_amount"] or 0) if hdr_extra_row else 0
            total_paid_all = 0
            for br in batch_rows:
                line_bill = int(br["unit_purchase_price"]) * int(br["initial_qty"]) + int(br["extra_cost_total"])
                cur_paid = int(br["paid_amount"])
                room = max(0, line_bill - cur_paid)
                add_here = min(room, rem_to_apply)
                rem_to_apply = max(0, rem_to_apply - add_here)
                upd_paid = cur_paid + add_here
                b_status = "تسویه‌شده" if upd_paid >= line_bill else ("تسویه‌نشده" if upd_paid == 0 else "تسویه جزئی")
                conn.execute(
                    "UPDATE batches SET paid_amount=?, settlement_status=? WHERE id=?",
                    (upd_paid, b_status, int(br["id"])),
                )
                total_bill_all += line_bill
                total_paid_all += upd_paid

            if batch_rows:
                conn.execute(
                    """
                    INSERT INTO payments (ref_type, ref_id, amount, payment_date, notes)
                    VALUES ('batch', ?, ?, ?, ?)
                    """,
                    (
                        int(batch_rows[0]["id"]),
                        amt,
                        p_date.split(" ")[0],
                        f"پرداخت قسط #{row['installment_no']} فاکتور خرید {pinv_code or row['batch_id']}",
                    ),
                )
            if pinv_code:
                eff_hdr_paid = min(total_bill_all, max(total_paid_all, prev_hdr_paid + amt))
                hdr_st = "تسویه‌شده" if eff_hdr_paid >= total_bill_all else ("تسویه‌نشده" if eff_hdr_paid == 0 else "تسویه جزئی")
                conn.execute(
                    """
                    UPDATE invoice_headers
                    SET paid_amount=?, settlement_status=?, last_modified_by=?, last_modified_at=?
                    WHERE invoice_kind='batch' AND invoice_number=?
                    """,
                    (eff_hdr_paid, hdr_st, mod_by, mod_at, pinv_code),
                )
            open_cnt = conn.execute(
                "SELECT COUNT(*) FROM supplier_installment_payments WHERE plan_id=? AND status <> 'paid'",
                (int(row["plan_id"]),),
            ).fetchone()[0]
            plan_status = "completed" if int(open_cnt) == 0 else "active"
            conn.execute(
                "UPDATE supplier_installment_plans SET status=?, last_modified_by=?, last_modified_at=? WHERE id=?",
                (plan_status, mod_by, mod_at, int(row["plan_id"])),
            )
            self.log_audit(
                conn,
                "ثبت پرداخت قسط تأمین‌کننده",
                f"قسط #{row['installment_no']} فاکتور {pinv_code} | مبلغ: {amt:,}",
            )
            return {
                "installment_id": iid,
                "plan_id": int(row["plan_id"]),
                "plan_status": plan_status,
                "new_paid": new_paid,
                "status": new_status,
            }

        return self.run_write_transaction(_tx)

    def list_suppliers_with_ledgers(
        self,
        today_str: str = "",
        search_text: str = "",
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[dict]:
        """Single-query SQL aggregation of suppliers, purchase volume, debt, installments, and payable checks."""
        q_filter = ""
        clean_search = str(search_text or "").strip()
        params: list = [str(today_str or "").strip(), str(today_str or "").strip()]
        if clean_search:
            like = f"%{clean_search}%"
            q_filter = "WHERE (s.name LIKE ? OR s.phone LIKE ? OR s.address LIKE ? OR s.notes LIKE ?)"
            params.extend([like, like, like, like])
        limit_sql = ""
        if limit is not None and int(limit) > 0:
            limit_sql = f" LIMIT {int(limit)} OFFSET {max(0, int(offset))}"
        sql = f"""
            WITH batch_inv AS (
                SELECT
                    b.supplier_id,
                    COALESCE(NULLIF(b.purchase_invoice_code, ''), NULLIF(b.invoice_number, ''), b.batch_code) AS inv_key,
                    COALESCE(SUM(b.unit_purchase_price * b.initial_qty + b.extra_cost_total), 0)
                        + COALESCE(MAX(ih.extra_cost_total), 0) AS inv_total,
                    MIN(
                        COALESCE(SUM(b.unit_purchase_price * b.initial_qty + b.extra_cost_total), 0)
                            + COALESCE(MAX(ih.extra_cost_total), 0),
                        MAX(COALESCE(SUM(b.paid_amount), 0), COALESCE(MAX(ih.paid_amount), 0))
                    ) AS inv_paid
                FROM batches b
                LEFT JOIN invoice_headers ih
                       ON ih.invoice_kind='batch'
                      AND ih.invoice_number=COALESCE(NULLIF(b.purchase_invoice_code, ''), NULLIF(b.invoice_number, ''), b.batch_code)
                WHERE b.supplier_id IS NOT NULL
                GROUP BY b.supplier_id, COALESCE(NULLIF(b.purchase_invoice_code, ''), NULLIF(b.invoice_number, ''), b.batch_code)
            ),
            batch_agg AS (
                SELECT
                    supplier_id,
                    COUNT(*) AS invoice_count,
                    COALESCE(SUM(inv_total), 0) AS total_purchases,
                    COALESCE(SUM(inv_paid), 0) AS total_paid,
                    COALESCE(SUM(MAX(0, inv_total - inv_paid)), 0) AS remaining_debt
                FROM batch_inv
                GROUP BY supplier_id
            ),
            inst_agg AS (
                SELECT
                    p.supplier_id,
                    COALESCE(SUM(CASE WHEN sp.status <> 'paid' THEN 1 ELSE 0 END), 0) AS open_installments,
                    COALESCE(SUM(CASE WHEN sp.status <> 'paid' AND ? <> '' AND substr(sp.due_date, 1, 10) < substr(?, 1, 10) THEN 1 ELSE 0 END), 0) AS overdue_count
                FROM supplier_installment_plans p
                JOIN supplier_installment_payments sp ON sp.plan_id = p.id
                WHERE p.status = 'active'
                GROUP BY p.supplier_id
            ),
            chk_agg AS (
                SELECT
                    supplier_id,
                    COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END), 0) AS pending_checks_count,
                    COALESCE(SUM(CASE WHEN status='pending' THEN amount ELSE 0 END), 0) AS pending_checks_amount
                FROM checks
                WHERE supplier_id IS NOT NULL AND direction='payable'
                GROUP BY supplier_id
            )
            SELECT
                s.id, s.name, s.phone, s.address, s.notes, s.created_at, s.updated_at, s.row_version,
                COALESCE(ba.invoice_count, 0) AS invoice_count,
                COALESCE(ba.total_purchases, 0) AS total_purchases,
                COALESCE(ba.total_paid, 0) AS total_paid,
                COALESCE(ba.remaining_debt, 0) AS remaining_debt,
                COALESCE(ia.open_installments, 0) AS open_installments,
                COALESCE(ia.overdue_count, 0) AS overdue_count,
                COALESCE(ca.pending_checks_count, 0) AS pending_checks_count,
                COALESCE(ca.pending_checks_amount, 0) AS pending_checks_amount
            FROM suppliers s
            LEFT JOIN batch_agg ba ON ba.supplier_id = s.id
            LEFT JOIN inst_agg ia ON ia.supplier_id = s.id
            LEFT JOIN chk_agg ca ON ca.supplier_id = s.id
            {q_filter}
            ORDER BY COALESCE(ba.remaining_debt, 0) DESC, s.updated_at DESC, s.id DESC
            {limit_sql}
        """
        with self.get_connection() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def get_supplier_purchases_and_installments(self, supplier_id: Optional[int] = None) -> dict:
        sid = int(supplier_id) if supplier_id is not None else None
        s_clause = "WHERE b.supplier_id=?" if sid is not None else ""
        s_params = (sid,) if sid is not None else ()
        with self.get_connection() as conn:
            sup = conn.execute("SELECT * FROM suppliers WHERE id=?", (sid,)).fetchone() if sid is not None else None
            batches_rows = conn.execute(
                f"""
                SELECT b.id, b.batch_code, b.purchase_invoice_code, b.invoice_number, b.purchase_date,
                       b.initial_qty, (b.unit_purchase_price * b.initial_qty + b.extra_cost_total) AS total_amount,
                       b.paid_amount, b.settlement_status, b.payment_type, b.settlement_subtype,
                       b.check_due_date, b.check_status,
                       COALESCE(NULLIF(trim(COALESCE(p.brand, '') || ' ' || COALESCE(p.model, '')), ''), p.name, '-') AS product_label,
                       COALESCE(s.name, b.supplier_name_snapshot, '-') AS party_name
                FROM batches b
                LEFT JOIN products p ON p.id = b.product_id
                LEFT JOIN suppliers s ON s.id = b.supplier_id
                {s_clause}
                ORDER BY b.purchase_date DESC, b.id DESC
                """,
                s_params,
            ).fetchall()
            ip_clause = "WHERE pl.supplier_id=?" if sid is not None else ""
            installments_rows = conn.execute(
                f"""
                SELECT sp.*, pl.purchase_invoice_code, pl.batch_id,
                       COALESCE(s.name, '-') AS party_name
                FROM supplier_installment_payments sp
                JOIN supplier_installment_plans pl ON pl.id = sp.plan_id
                LEFT JOIN suppliers s ON s.id = pl.supplier_id
                {ip_clause}
                ORDER BY sp.due_date ASC, sp.installment_no ASC, sp.id ASC
                """,
                s_params,
            ).fetchall()
            chk_clause = "WHERE supplier_id=? AND direction='payable'" if sid is not None else "WHERE direction='payable'"
            check_rows = conn.execute(
                f"""
                SELECT * FROM checks
                {chk_clause}
                ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'bounced' THEN 1 ELSE 2 END, due_date ASC, id DESC
                """,
                s_params,
            ).fetchall()
            return {
                "supplier": dict(sup) if sup else None,
                "batches": [dict(r) for r in batches_rows],
                "installments": [dict(r) for r in installments_rows],
                "checks": [dict(r) for r in check_rows],
            }

    def get_supplier_installments_overview(self, today_str: str = "") -> dict:
        t_date = str(today_str or "").strip()[:10]
        with self.get_connection() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN sp.status <> 'paid' THEN MAX(0, sp.due_amount - sp.paid_amount) ELSE 0 END), 0) AS total_unpaid_installments,
                    COALESCE(SUM(CASE WHEN sp.status <> 'paid' AND ? <> '' AND substr(sp.due_date, 1, 10) < ? THEN 1 ELSE 0 END), 0) AS overdue_count,
                    COALESCE(SUM(CASE WHEN sp.status <> 'paid' AND ? <> '' AND substr(sp.due_date, 1, 10) < ? THEN MAX(0, sp.due_amount - sp.paid_amount) ELSE 0 END), 0) AS overdue_amount,
                    COALESCE(SUM(CASE WHEN sp.status <> 'paid' THEN 1 ELSE 0 END), 0) AS open_count
                FROM supplier_installment_payments sp
                JOIN supplier_installment_plans pl ON pl.id = sp.plan_id
                WHERE pl.status = 'active'
                """,
                (t_date, t_date, t_date, t_date),
            ).fetchone()
            sup_debt = conn.execute(
                """
                SELECT COALESCE(SUM(MAX(0, inv_tot - inv_paid)), 0)
                FROM (
                    SELECT
                        COALESCE(NULLIF(b.purchase_invoice_code, ''), NULLIF(b.invoice_number, ''), b.batch_code) AS inv_key,
                        COALESCE(SUM(b.unit_purchase_price * b.initial_qty + b.extra_cost_total), 0)
                            + COALESCE(MAX(ih.extra_cost_total), 0) AS inv_tot,
                        MIN(
                            COALESCE(SUM(b.unit_purchase_price * b.initial_qty + b.extra_cost_total), 0)
                                + COALESCE(MAX(ih.extra_cost_total), 0),
                            MAX(COALESCE(SUM(b.paid_amount), 0), COALESCE(MAX(ih.paid_amount), 0))
                        ) AS inv_paid
                    FROM batches b
                    LEFT JOIN invoice_headers ih
                           ON ih.invoice_kind='batch'
                          AND ih.invoice_number=COALESCE(NULLIF(b.purchase_invoice_code, ''), NULLIF(b.invoice_number, ''), b.batch_code)
                    GROUP BY COALESCE(NULLIF(b.purchase_invoice_code, ''), NULLIF(b.invoice_number, ''), b.batch_code)
                )
                """
            ).fetchone()[0]
            return {
                "total_unpaid_installments": int(row["total_unpaid_installments"] or 0) if row else 0,
                "overdue_count": int(row["overdue_count"] or 0) if row else 0,
                "overdue_amount": int(row["overdue_amount"] or 0) if row else 0,
                "open_count": int(row["open_count"] or 0) if row else 0,
                "total_supplier_debt": int(sup_debt or 0),
            }

    # =========================================================================
    # پیش‌فاکتورها (Proforma Invoices - Daqiq v5.0.2 - PI- & Mixed Product/Service)
    # =========================================================================
    def _prepare_proforma_items(self, items, notes: str = ""):
        if not items or not isinstance(items, (list, tuple)):
            raise ValueError("حداقل یک قلم کالا یا خدمت برای ثبت پیش‌فاکتور لازم است.")
        prepared = []
        total_amount = 0
        for raw in items:
            kind = str(raw.get("item_kind") or "").strip().lower()
            if not kind:
                kind = "service" if (raw.get("service_id") is not None or raw.get("service_name")) and raw.get("batch_id") is None else "product"
            if kind == "service":
                srv_id = self._batch_optional_id(raw.get("service_id"), "خدمت")
                q = self._batch_integer(raw.get("qty", 1), "تعداد", minimum=1)
                act_u = self._batch_integer(raw.get("actual_unit_price", raw.get("service_fee", 0)), "هزینه خدمت")
                sug_u = self._batch_integer(raw.get("suggested_unit_price", act_u), "تعرفه مرجع")
                scost = self._batch_integer(raw.get("side_cost", 0), "هزینه جانبی")
                line_tot = self._sqlite_integer(act_u * q, "مبلغ کل ردیف خدمت پیش‌فاکتور")
                total_amount = self._sqlite_integer(total_amount + line_tot, "جمع کل پیش‌فاکتور")
                prepared.append({
                    "item_kind": "service",
                    "product_id": None,
                    "batch_id": None,
                    "service_id": srv_id,
                    "service_type": str(raw.get("service_type") or "خدمات عمومی").strip(),
                    "service_name": str(raw.get("service_name") or raw.get("description") or "خدمت فنی").strip(),
                    "side_cost": scost,
                    "qty": q,
                    "suggested_unit_price": sug_u,
                    "actual_unit_price": act_u,
                    "line_total": line_tot,
                    "serial_number": "",
                    "warranty_company": "",
                    "warranty_start": "",
                    "warranty_months": 0,
                    "warranty_days": 0,
                    "warranty_end": "",
                    "specifications": "",
                    "colors_json": "[]",
                    "notes": str(raw.get("notes") or raw.get("description") or notes or "").strip(),
                })
            else:
                pid = self._batch_integer(raw.get("product_id"), "کالا", minimum=1)
                bid = self._batch_integer(raw.get("batch_id"), "محموله", minimum=1)
                q = self._batch_integer(raw.get("qty"), "تعداد", minimum=1)
                sug_u = self._batch_integer(raw.get("suggested_unit_price", raw.get("actual_unit_price", 0)), "قیمت پیشنهادی واحد")
                act_u = self._batch_integer(raw.get("actual_unit_price"), "قیمت واحد")
                line_tot = self._sqlite_integer(act_u * q, "مبلغ کل ردیف پیش‌فاکتور")
                total_amount = self._sqlite_integer(total_amount + line_tot, "جمع کل پیش‌فاکتور")
                prepared.append({
                    "item_kind": "product",
                    "product_id": pid,
                    "batch_id": bid,
                    "service_id": None,
                    "service_type": "",
                    "service_name": "",
                    "side_cost": 0,
                    "qty": q,
                    "suggested_unit_price": sug_u,
                    "actual_unit_price": act_u,
                    "line_total": line_tot,
                    "serial_number": str(raw.get("serial_number") or "").strip(),
                    "warranty_company": str(raw.get("warranty_company") or "").strip(),
                    "warranty_start": str(raw.get("warranty_start") or "").strip(),
                    "warranty_months": int(raw.get("warranty_months") or 0),
                    "warranty_days": int(raw.get("warranty_days") if raw.get("warranty_days") is not None else int(raw.get("warranty_months") or 0) * 30),
                    "warranty_end": str(raw.get("warranty_end") or "").strip(),
                    "specifications": str(raw.get("specifications") or ""),
                    "colors_json": json.dumps(self._normalize_color_list(raw.get("colors")) or [], ensure_ascii=False),
                    "notes": str(raw.get("notes") or notes or "").strip(),
                })
        return prepared, total_amount

    def _normalize_proforma_payment_meta(
        self,
        total_amount: int,
        dt_str: str,
        *,
        payment_type: str = "cash",
        settlement_status: str = "تسویه‌شده",
        settlement_subtype: str = "تسویه نقدی",
        paid_amount=None,
        check_due_date: str = "",
        check_status: str = "",
        installment_plan=None,
    ) -> dict:
        clean_sub = str(settlement_subtype or "").strip()
        ptype = str(payment_type or "cash").strip().lower()
        if installment_plan:
            ptype = "installment"
        elif clean_sub == "تسویه چکی":
            ptype = "check"
        elif ptype not in ("cash", "check", "installment", "partial"):
            ptype = "cash"
        clean_chk_due = str(check_due_date or "").strip() if ptype == "check" else ""
        clean_chk_st = (
            ("cleared" if str(check_status or "").strip().lower() in ("cleared", "وصول شده", "وصول‌شده")
             else ("bounced" if str(check_status or "").strip().lower() in ("bounced", "برگشتی", "برگشت خورده") else "pending"))
            if ptype == "check" else ""
        )
        first_inst_paid = False
        inst_count = 1
        inst_interval = 30
        inst_start_due = ""
        if installment_plan:
            paid_val = self._batch_integer(
                installment_plan.get("down_payment", paid_amount if paid_amount is not None else 0),
                "پیش‌پرداخت",
            )
            inst_count = self._batch_integer(installment_plan.get("count", 1), "تعداد اقساط", minimum=1)
            inst_interval = self._batch_integer(installment_plan.get("interval_days", 30), "فاصله اقساط (روز)", minimum=1)
            inst_start_due = str(installment_plan.get("start_due_date") or dt_str.split(" ")[0]).strip()
            first_inst_paid = bool(installment_plan.get("first_installment_paid", False))
            st_val = "تسویه جزئی" if paid_val > 0 else "تسویه‌نشده"
            clean_sub = ""
        elif ptype == "check":
            paid_val = total_amount
            st_val = "تسویه‌شده"
            clean_sub = "تسویه چکی"
        else:
            st_raw = str(settlement_status or "").strip()
            if st_raw in ("تسویه‌شده", "تسویه‌نشده", "تسویه جزئی"):
                st_val = st_raw
            else:
                st_val = "تسویه‌شده"
            if st_val == "تسویه‌شده":
                paid_val = total_amount if paid_amount is None else min(total_amount, self._batch_integer(paid_amount, "مبلغ دریافتی"))
                if paid_val == 0 and paid_amount is None:
                    paid_val = total_amount
                elif paid_amount is None:
                    paid_val = total_amount
                if not clean_sub:
                    clean_sub = "تسویه نقدی"
            elif st_val == "تسویه‌نشده":
                paid_val = 0
                clean_sub = ""
                ptype = "partial"
            else:
                paid_val = min(total_amount, self._batch_integer(paid_amount or 0, "مبلغ دریافتی"))
                clean_sub = ""
                ptype = "partial"
        return {
            "payment_type": ptype,
            "settlement_status": st_val,
            "settlement_subtype": clean_sub,
            "paid_amount": paid_val,
            "check_due_date": clean_chk_due,
            "check_status": clean_chk_st,
            "first_installment_paid": 1 if first_inst_paid else 0,
            "installment_count": inst_count,
            "installment_interval_days": inst_interval,
            "installment_start_due": inst_start_due,
        }

    def add_proforma_invoice(
        self,
        proforma_number,
        items,
        *,
        customer_id=None,
        customer_name="",
        customer_phone="",
        seller_employee_id=None,
        proforma_datetime="",
        valid_until="",
        extra_cost_total=0,
        payment_type="cash",
        settlement_status="تسویه‌شده",
        settlement_subtype="تسویه نقدی",
        paid_amount=None,
        check_due_date="",
        check_status="pending",
        installment_plan=None,
        notes="",
        operator_name="",
    ) -> str:
        clean_num = str(proforma_number or "").strip()
        customer_id = self._batch_optional_id(customer_id, "مشتری")
        seller_employee_id = self._batch_optional_id(seller_employee_id, "فروشنده")
        c_name = str(customer_name or "").strip()
        c_phone = str(customer_phone or "").strip()
        dt_str = str(proforma_datetime or "").strip()
        if not dt_str:
            cal, tf = self._active_datetime_prefs()
            dt_str = datetime_format.get_now_datetime(cal, tf)
        v_until = str(valid_until or "").strip()
        clean_notes = str(notes or "").strip()
        hdr_extra = self._batch_integer(extra_cost_total, "هزینه جانبی کل")
        prepared, items_total = self._prepare_proforma_items(items, clean_notes)
        total_amount = self._sqlite_integer(items_total + hdr_extra, "جمع کل پیش‌فاکتور با هزینه جانبی")
        pmeta = self._normalize_proforma_payment_meta(
            total_amount,
            dt_str,
            payment_type=payment_type,
            settlement_status=settlement_status,
            settlement_subtype=settlement_subtype,
            paid_amount=paid_amount,
            check_due_date=check_due_date,
            check_status=check_status,
            installment_plan=installment_plan,
        )
        mod_by = str(operator_name or "").strip()
        mod_at = time.strftime("%Y-%m-%d %H:%M:%S")

        def _tx(conn):
            nonlocal clean_num, customer_id
            if not clean_num:
                clean_num = self._next_available_invoice_code(conn, "proforma", "proforma_number", "PI-", 1001)
            else:
                dup = conn.execute(
                    "SELECT id FROM proforma_invoices WHERE proforma_number=?",
                    (clean_num,),
                ).fetchone()
                if dup:
                    clean_num = self._next_available_invoice_code(conn, "proforma", "proforma_number", "PI-", 1001)
            if customer_id is None and c_name and c_name != "مشتری حضوری":
                row_cust = conn.execute(
                    "SELECT id FROM customers WHERE name=? AND (?='' OR phone=?) ORDER BY id DESC LIMIT 1",
                    (c_name, c_phone, c_phone),
                ).fetchone()
                if row_cust:
                    customer_id = int(row_cust["id"])
            cur = conn.execute(
                """
                INSERT INTO proforma_invoices (
                    proforma_number, customer_id, customer_name, customer_phone, seller_employee_id,
                    proforma_datetime, valid_until, status, converted_sale_invoice, converted_service_invoice,
                    total_amount, extra_cost_total, payment_type, settlement_status, settlement_subtype,
                    paid_amount, check_due_date, check_status, first_installment_paid,
                    installment_count, installment_interval_days, installment_start_due,
                    notes, last_modified_by, last_modified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', '', '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_num, customer_id, c_name, c_phone, seller_employee_id,
                    dt_str, v_until, total_amount, hdr_extra,
                    pmeta["payment_type"], pmeta["settlement_status"], pmeta["settlement_subtype"],
                    pmeta["paid_amount"], pmeta["check_due_date"], pmeta["check_status"],
                    pmeta["first_installment_paid"], pmeta["installment_count"],
                    pmeta["installment_interval_days"], pmeta["installment_start_due"],
                    clean_notes, mod_by, mod_at,
                ),
            )
            pf_id = int(cur.lastrowid)
            for line_no, item in enumerate(prepared, start=1):
                conn.execute(
                    """
                    INSERT INTO proforma_items (
                        proforma_id, line_no, product_id, batch_id, qty,
                        suggested_unit_price, actual_unit_price, line_total,
                        serial_number, warranty_company, warranty_start, warranty_months,
                        warranty_days, warranty_end, specifications, colors_json, notes,
                        item_kind, service_id, service_type, service_name, side_cost
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pf_id, line_no, item["product_id"], item["batch_id"], item["qty"],
                        item["suggested_unit_price"], item["actual_unit_price"], item["line_total"],
                        item["serial_number"], item["warranty_company"], item["warranty_start"],
                        item["warranty_months"], item["warranty_days"], item["warranty_end"],
                        item["specifications"], item["colors_json"], item["notes"],
                        item["item_kind"], item["service_id"], item["service_type"],
                        item["service_name"], item["side_cost"],
                    ),
                )
            self.log_audit(
                conn,
                "ثبت پیش‌فاکتور",
                f"شماره: {clean_num} | مشتری: {c_name or 'حضوری'} | مبلغ کل: {total_amount:,}",
            )
            return clean_num

        return self.run_write_transaction(_tx)

    def update_proforma_invoice(
        self,
        proforma_id: int,
        proforma_number: str,
        items,
        *,
        customer_id=None,
        customer_name="",
        customer_phone="",
        seller_employee_id=None,
        proforma_datetime="",
        valid_until="",
        status="open",
        extra_cost_total=0,
        payment_type="cash",
        settlement_status="تسویه‌شده",
        settlement_subtype="تسویه نقدی",
        paid_amount=None,
        check_due_date="",
        check_status="pending",
        installment_plan=None,
        notes="",
        operator_name="",
        expected_row_version=None,
    ) -> str:
        pf_id = self._batch_integer(proforma_id, "شناسه پیش‌فاکتور", minimum=1)
        clean_num = str(proforma_number or "").strip()
        customer_id = self._batch_optional_id(customer_id, "مشتری")
        seller_employee_id = self._batch_optional_id(seller_employee_id, "فروشنده")
        c_name = str(customer_name or "").strip()
        c_phone = str(customer_phone or "").strip()
        dt_str = str(proforma_datetime or "").strip()
        v_until = str(valid_until or "").strip()
        clean_st = str(status or "open").strip().lower()
        if clean_st not in ("open", "cancelled"):
            clean_st = "open"
        clean_notes = str(notes or "").strip()
        hdr_extra = self._batch_integer(extra_cost_total, "هزینه جانبی کل")
        prepared, items_total = self._prepare_proforma_items(items, clean_notes)
        total_amount = self._sqlite_integer(items_total + hdr_extra, "جمع کل پیش‌فاکتور با هزینه جانبی")
        pmeta = self._normalize_proforma_payment_meta(
            total_amount,
            dt_str,
            payment_type=payment_type,
            settlement_status=settlement_status,
            settlement_subtype=settlement_subtype,
            paid_amount=paid_amount,
            check_due_date=check_due_date,
            check_status=check_status,
            installment_plan=installment_plan,
        )
        mod_by = str(operator_name or "").strip()
        mod_at = time.strftime("%Y-%m-%d %H:%M:%S")

        def _tx(conn):
            old = self._check_row_version(conn, "proforma_invoices", pf_id, expected_row_version, "پیش‌فاکتور")
            if old is None:
                old = conn.execute("SELECT * FROM proforma_invoices WHERE id=?", (pf_id,)).fetchone()
            if not old:
                raise ValueError("پیش‌فاکتور انتخاب‌شده یافت نشد.")
            if str(old["status"]) == "converted":
                raise ValueError("پیش‌فاکتور تبدیل‌شده به فاکتور فروش قابل ویرایش نیست.")
            final_num = clean_num or str(old["proforma_number"])
            conn.execute(
                """
                UPDATE proforma_invoices
                SET proforma_number=?, customer_id=?, customer_name=?, customer_phone=?,
                    seller_employee_id=?, proforma_datetime=?, valid_until=?, status=?,
                    total_amount=?, extra_cost_total=?, payment_type=?, settlement_status=?,
                    settlement_subtype=?, paid_amount=?, check_due_date=?, check_status=?,
                    first_installment_paid=?, installment_count=?, installment_interval_days=?,
                    installment_start_due=?, notes=?, last_modified_by=?, last_modified_at=?
                WHERE id=?
                """,
                (
                    final_num, customer_id, c_name, c_phone, seller_employee_id,
                    dt_str or old["proforma_datetime"], v_until, clean_st,
                    total_amount, hdr_extra,
                    pmeta["payment_type"], pmeta["settlement_status"], pmeta["settlement_subtype"],
                    pmeta["paid_amount"], pmeta["check_due_date"], pmeta["check_status"],
                    pmeta["first_installment_paid"], pmeta["installment_count"],
                    pmeta["installment_interval_days"], pmeta["installment_start_due"],
                    clean_notes, mod_by, mod_at, pf_id,
                ),
            )
            conn.execute("DELETE FROM proforma_items WHERE proforma_id=?", (pf_id,))
            for line_no, item in enumerate(prepared, start=1):
                conn.execute(
                    """
                    INSERT INTO proforma_items (
                        proforma_id, line_no, product_id, batch_id, qty,
                        suggested_unit_price, actual_unit_price, line_total,
                        serial_number, warranty_company, warranty_start, warranty_months,
                        warranty_days, warranty_end, specifications, colors_json, notes,
                        item_kind, service_id, service_type, service_name, side_cost
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pf_id, line_no, item["product_id"], item["batch_id"], item["qty"],
                        item["suggested_unit_price"], item["actual_unit_price"], item["line_total"],
                        item["serial_number"], item["warranty_company"], item["warranty_start"],
                        item["warranty_months"], item["warranty_days"], item["warranty_end"],
                        item["specifications"], item["colors_json"], item["notes"],
                        item["item_kind"], item["service_id"], item["service_type"],
                        item["service_name"], item["side_cost"],
                    ),
                )
            self.log_audit(conn, "ویرایش پیش‌فاکتور", f"شماره: {final_num} | مبلغ کل: {total_amount:,}")
            return final_num

        return self.run_write_transaction(_tx)

    def append_services_to_proforma(
        self,
        proforma_id: Optional[int],
        service_items,
        *,
        proforma_number: str = "",
        customer_id: Optional[int] = None,
        customer_name: str = "",
        customer_phone: str = "",
        seller_employee_id: Optional[int] = None,
        proforma_datetime: str = "",
        extra_cost_total: int = 0,
        notes: str = "",
        operator_name: str = "",
    ) -> dict:
        """Append service items to an existing open proforma or create a new PI- proforma."""
        norm_srv = []
        for raw in (service_items or []):
            norm_srv.append({
                "item_kind": "service",
                "service_id": raw.get("service_id"),
                "service_type": str(raw.get("service_type") or "").strip(),
                "service_name": str(raw.get("service_name") or raw.get("description") or "").strip(),
                "qty": int(raw.get("qty") or 1),
                "actual_unit_price": int(raw.get("service_fee", raw.get("actual_unit_price", 0)) or 0),
                "suggested_unit_price": int(raw.get("suggested_unit_price", raw.get("service_fee", 0)) or 0),
                "side_cost": int(raw.get("side_cost", 0) or 0),
                "notes": str(raw.get("description") or raw.get("notes") or notes or "").strip(),
            })
        if proforma_id is None:
            new_num = self.add_proforma_invoice(
                proforma_number,
                norm_srv,
                customer_id=customer_id,
                customer_name=customer_name,
                customer_phone=customer_phone,
                seller_employee_id=seller_employee_id,
                proforma_datetime=proforma_datetime,
                extra_cost_total=extra_cost_total,
                notes=notes,
                operator_name=operator_name,
            )
            with self.get_connection() as conn:
                r = conn.execute("SELECT id FROM proforma_invoices WHERE proforma_number=?", (new_num,)).fetchone()
                return {"proforma_id": int(r["id"]) if r else 0, "proforma_number": new_num, "created": True}

        pf_id = self._batch_integer(proforma_id, "شناسه پیش‌فاکتور", minimum=1)
        prepared, added_total = self._prepare_proforma_items(norm_srv, notes)
        hdr_extra_add = self._batch_integer(extra_cost_total, "هزینه جانبی کل")
        mod_by = str(operator_name or "").strip()
        mod_at = time.strftime("%Y-%m-%d %H:%M:%S")

        def _tx(conn):
            pf = conn.execute("SELECT * FROM proforma_invoices WHERE id=?", (pf_id,)).fetchone()
            if not pf:
                raise ValueError("پیش‌فاکتور انتخاب‌شده یافت نشد.")
            if str(pf["status"]) != "open":
                raise ValueError("فقط پیش‌فاکتورهای باز قابل افزودن خدمت هستند.")
            max_line = conn.execute(
                "SELECT COALESCE(MAX(line_no), 0) FROM proforma_items WHERE proforma_id=?",
                (pf_id,),
            ).fetchone()[0]
            next_ln = int(max_line or 0) + 1
            for offset_ln, item in enumerate(prepared):
                conn.execute(
                    """
                    INSERT INTO proforma_items (
                        proforma_id, line_no, product_id, batch_id, qty,
                        suggested_unit_price, actual_unit_price, line_total,
                        serial_number, warranty_company, warranty_start, warranty_months,
                        warranty_days, warranty_end, specifications, colors_json, notes,
                        item_kind, service_id, service_type, service_name, side_cost
                    ) VALUES (?, ?, NULL, NULL, ?, ?, ?, ?, '', '', '', 0, 0, '', '', '[]', ?, 'service', ?, ?, ?, ?)
                    """,
                    (
                        pf_id, next_ln + offset_ln, item["qty"],
                        item["suggested_unit_price"], item["actual_unit_price"], item["line_total"],
                        item["notes"], item["service_id"], item["service_type"],
                        item["service_name"], item["side_cost"],
                    ),
                )
            new_tot = self._sqlite_integer(int(pf["total_amount"]) + added_total + hdr_extra_add, "جمع کل پیش‌فاکتور")
            new_extra = self._sqlite_integer(int(pf["extra_cost_total"] or 0) + hdr_extra_add, "هزینه جانبی پیش‌فاکتور")
            conn.execute(
                """
                UPDATE proforma_invoices
                SET total_amount=?, extra_cost_total=?, last_modified_by=?, last_modified_at=?
                WHERE id=?
                """,
                (new_tot, new_extra, mod_by, mod_at, pf_id),
            )
            self.log_audit(
                conn,
                "افزودن خدمت به پیش‌فاکتور",
                f"پیش‌فاکتور: {pf['proforma_number']} | تعداد خدمات: {len(prepared)}",
            )
            return {"proforma_id": pf_id, "proforma_number": str(pf["proforma_number"]), "created": False}

        return self.run_write_transaction(_tx)

    def list_proforma_invoices(
        self,
        *,
        search_text: str = "",
        status: str = "",
        include_converted: bool = False,
        date_from: str = "",
        date_to: str = "",
        visible_employee_ids: Optional[set] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[dict]:
        clauses = ["1=1"]
        params: list = []
        if status in ("open", "converted", "cancelled"):
            clauses.append("pf.status = ?")
            params.append(status)
        elif not include_converted:
            clauses.append("pf.status <> 'converted'")
        d_from = str(date_from or "").strip()[:10]
        d_to = str(date_to or "").strip()[:10]
        if d_from:
            clauses.append("substr(pf.proforma_datetime, 1, 10) >= ?")
            params.append(d_from)
        if d_to:
            clauses.append("substr(pf.proforma_datetime, 1, 10) <= ?")
            params.append(d_to)
        if visible_employee_ids is not None:
            if not visible_employee_ids:
                return []
            marks = ",".join("?" for _ in visible_employee_ids)
            clauses.append(f"(pf.seller_employee_id IN ({marks}) OR pf.seller_employee_id IS NULL)")
            params.extend(sorted(visible_employee_ids))
        clean_q = str(search_text or "").strip()
        if clean_q:
            like = f"%{clean_q}%"
            clauses.append(
                "(pf.proforma_number LIKE ? OR pf.customer_name LIKE ? OR pf.customer_phone LIKE ? OR pf.converted_sale_invoice LIKE ? OR pf.converted_service_invoice LIKE ?)"
            )
            params.extend([like, like, like, like, like])
        where_sql = " AND ".join(clauses)
        limit_sql = f" LIMIT {int(limit)} OFFSET {max(0, int(offset))}" if (limit is not None and int(limit) > 0) else ""
        with self.get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT pf.*,
                       COALESCE(e.name, '-') AS seller_name,
                       (SELECT COUNT(*) FROM proforma_items pi WHERE pi.proforma_id = pf.id) AS item_count,
                       (SELECT COALESCE(SUM(pi.qty), 0) FROM proforma_items pi WHERE pi.proforma_id = pf.id) AS total_qty
                FROM proforma_invoices pf
                LEFT JOIN employees e ON e.id = pf.seller_employee_id
                WHERE {where_sql}
                ORDER BY pf.proforma_datetime DESC, pf.id DESC
                {limit_sql}
                """,
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def get_proforma_detail(self, proforma_id: int) -> Optional[dict]:
        pf_id = int(proforma_id)
        with self.get_connection() as conn:
            hdr = conn.execute(
                """
                SELECT pf.*, COALESCE(e.name, '-') AS seller_name
                FROM proforma_invoices pf
                LEFT JOIN employees e ON e.id = pf.seller_employee_id
                WHERE pf.id=?
                """,
                (pf_id,),
            ).fetchone()
            if not hdr:
                return None
            items = conn.execute(
                """
                SELECT pi.*,
                       p.code AS product_code,
                       p.name AS product_name,
                       p.brand AS product_brand,
                       p.model AS product_model,
                       b.batch_code,
                       b.purchase_invoice_code,
                       b.invoice_number AS supplier_invoice_number,
                       b.remaining_qty AS batch_remaining_qty,
                       sc.code AS service_code,
                       COALESCE(NULLIF(pi.service_name, ''), sc.name, '') AS resolved_service_name,
                       COALESCE(NULLIF(pi.service_type, ''), sc.service_type, '') AS resolved_service_type
                FROM proforma_items pi
                LEFT JOIN products p ON p.id = pi.product_id
                LEFT JOIN batches b ON b.id = pi.batch_id
                LEFT JOIN service_catalog sc ON sc.id = pi.service_id
                WHERE pi.proforma_id=?
                ORDER BY pi.line_no ASC, pi.id ASC
                """,
                (pf_id,),
            ).fetchall()
            res = dict(hdr)
            res["items"] = [dict(r) for r in items]
            return res

    def delete_proformas_batch(self, proforma_ids: list[int], operator_name: str = "") -> int:
        ids = list(dict.fromkeys(self._batch_integer(x, "شناسه پیش‌فاکتور", minimum=1) for x in (proforma_ids or [])))
        if not ids:
            return 0

        def _tx(conn):
            marks = ",".join("?" for _ in ids)
            nums = [
                str(r["proforma_number"])
                for r in conn.execute(f"SELECT proforma_number FROM proforma_invoices WHERE id IN ({marks})", ids).fetchall()
            ]
            if not nums:
                return 0
            conn.execute(f"DELETE FROM proforma_items WHERE proforma_id IN ({marks})", ids)
            conn.execute(f"DELETE FROM proforma_invoices WHERE id IN ({marks})", ids)
            self.log_audit(
                conn,
                "حذف گروهی پیش‌فاکتور",
                f"تعداد: {len(nums)} | شماره‌ها: {', '.join(nums)}",
            )
            return len(nums)

        return self.run_write_transaction(_tx)

    def convert_proforma_to_sale(
        self,
        proforma_id: int,
        *,
        sale_datetime: str = "",
        settlement_status: Optional[str] = None,
        settlement_subtype: Optional[str] = None,
        paid_amount: Optional[int] = None,
        payment_type: Optional[str] = None,
        check_due_date: Optional[str] = None,
        check_status: Optional[str] = None,
        installment_plan: Optional[dict] = None,
        sale_invoice_number: str = "",
        service_invoice_number: str = "",
        technician_employee_id: Optional[int] = None,
        operator_name: str = "",
        expected_row_version: Optional[int] = None,
        conflict_resolution: Optional[str] = None,
        expected_existing_version: Optional[int] = None,
    ) -> str:
        """Atomically convert an open proforma (products, services, or mixed) into INV-/SINV- invoices."""
        pf_id = self._batch_integer(proforma_id, "شناسه پیش‌فاکتور", minimum=1)
        clean_sale_inv = str(sale_invoice_number or "").strip()
        clean_srv_inv = str(service_invoice_number or "").strip()
        clean_dt = str(sale_datetime or "").strip()
        if not clean_dt:
            cal, tf = self._active_datetime_prefs()
            clean_dt = datetime_format.get_now_datetime(cal, tf)
        mod_by = str(operator_name or "").strip()
        mod_at = time.strftime("%Y-%m-%d %H:%M:%S")

        def _tx(conn):
            pf = self._check_row_version(conn, "proforma_invoices", pf_id, expected_row_version, "پیش‌فاکتور")
            if pf is None:
                pf = conn.execute("SELECT * FROM proforma_invoices WHERE id=?", (pf_id,)).fetchone()
            if not pf:
                raise ValueError("پیش‌فاکتور انتخاب‌شده یافت نشد.")
            if str(pf["status"]) != "open":
                raise ValueError(
                    f"این پیش‌فاکتور در وضعیت «{pf['status']}» است و قبلاً تبدیل یا لغو شده است."
                )
            pf_items = conn.execute(
                "SELECT * FROM proforma_items WHERE proforma_id=? ORDER BY line_no ASC, id ASC",
                (pf_id,),
            ).fetchall()
            if not pf_items:
                raise ValueError("این پیش‌فاکتور هیچ قلم کالایی یا خدمتی ندارد.")

            eff_settlement = settlement_status if settlement_status is not None else (str(pf["settlement_status"] or "تسویه‌شده"))
            eff_subtype = settlement_subtype if settlement_subtype is not None else (str(pf["settlement_subtype"] or ""))
            eff_ptype = (payment_type if payment_type is not None else str(pf["payment_type"] or "cash")).strip().lower()
            eff_chk_due = check_due_date if check_due_date is not None else str(pf["check_due_date"] or "")
            eff_chk_st = check_status if check_status is not None else str(pf["check_status"] or "pending")
            eff_inst = installment_plan
            if eff_inst is None and eff_ptype == "installment":
                eff_inst = {
                    "down_payment": int(pf["paid_amount"] or 0),
                    "count": max(1, int(pf["installment_count"] or 1)),
                    "interval_days": max(1, int(pf["installment_interval_days"] or 30)),
                    "start_due_date": str(pf["installment_start_due"] or clean_dt.split(" ")[0]).strip(),
                    "first_installment_paid": bool(int(pf["first_installment_paid"] or 0)),
                }

            if eff_inst:
                eff_ptype = "installment"
            elif eff_subtype == "تسویه چکی":
                eff_ptype = "check"
            elif eff_ptype not in ("cash", "check", "installment", "partial"):
                eff_ptype = "cash"
            clean_chk_due = str(eff_chk_due or "").strip() if eff_ptype == "check" else ""
            clean_chk_status = (
                ("cleared" if str(eff_chk_st or "").strip().lower() in ("cleared", "وصول شده", "وصول‌شده")
                 else ("bounced" if str(eff_chk_st or "").strip().lower() in ("bounced", "برگشتی", "برگشت خورده") else "pending"))
                if eff_ptype == "check" else ""
            )
            if eff_ptype == "check" and not clean_chk_due:
                raise ValueError("برای تسویه چکی، تاریخ سررسید چک باید مشخص شود.")

            first_inst_paid = False
            inst_count = 0
            inst_interval = 30
            inst_start_due = ""
            if eff_inst:
                resolved_paid = self._batch_integer(
                    eff_inst.get("down_payment", paid_amount if paid_amount is not None else pf["paid_amount"] or 0),
                    "پیش‌پرداخت",
                )
                inst_count = self._batch_integer(eff_inst.get("count", 1), "تعداد اقساط", minimum=1)
                inst_interval = self._batch_integer(eff_inst.get("interval_days", 30), "فاصله اقساط (روز)", minimum=1)
                inst_start_due = str(eff_inst.get("start_due_date") or clean_dt.split(" ")[0]).strip()
                if not inst_start_due:
                    raise ValueError("تاریخ سررسید قسط اول مشخص نشده است.")
                first_inst_paid = bool(eff_inst.get("first_installment_paid", False))
            else:
                resolved_paid = paid_amount if paid_amount is not None else (
                    int(pf["paid_amount"]) if pf["settlement_status"] != "تسویه‌شده" or pf["paid_amount"] > 0 else None
                )

            hdr_extra = int(pf["extra_cost_total"] or 0)
            product_lines = []
            service_lines = []
            product_subtotal = 0
            service_subtotal = 0
            for pi in pf_items:
                kind = str(pi["item_kind"] or "product").strip().lower()
                line_tot = int(pi["line_total"])
                if kind == "service":
                    service_subtotal = self._sqlite_integer(service_subtotal + line_tot, "جمع خدمات پیش‌فاکتور")
                    service_lines.append({
                        "service_id": pi["service_id"],
                        "service_type": str(pi["service_type"] or "خدمات عمومی"),
                        "service_name": str(pi["service_name"] or "خدمت فنی"),
                        "service_fee": line_tot,
                        "side_cost": int(pi["side_cost"] or 0),
                        "description": str(pi["notes"] or pf["notes"] or "").strip(),
                    })
                else:
                    product_subtotal = self._sqlite_integer(product_subtotal + line_tot, "جمع کالاهای پیش‌فاکتور")
                    try:
                        cols_list = json.loads(pi["colors_json"] or "[]")
                    except (TypeError, ValueError, json.JSONDecodeError):
                        cols_list = []
                    product_lines.append({
                        "product_id": int(pi["product_id"]),
                        "batch_id": int(pi["batch_id"]),
                        "qty": int(pi["qty"]),
                        "suggested_unit_price": int(pi["suggested_unit_price"]),
                        "actual_unit_price": int(pi["actual_unit_price"]),
                        "line_total": line_tot,
                        "serial_number": str(pi["serial_number"] or "").strip(),
                        "specifications": str(pi["specifications"] or ""),
                        "colors": cols_list,
                        "warranty_company": str(pi["warranty_company"] or "").strip(),
                        "warranty_start": str(pi["warranty_start"] or "").strip(),
                        "warranty_months": int(pi["warranty_months"] or 0),
                        "warranty_days": int(pi["warranty_days"] or 0),
                        "warranty_end": str(pi["warranty_end"] or "").strip(),
                        "expected_batch_row_version": None,
                        "notes": str(pi["notes"] or pf["notes"] or "").strip(),
                    })

            converted_sale_inv = ""
            converted_srv_inv = ""
            grand_total = product_subtotal + service_subtotal + hdr_extra
            eff_paid_total = grand_total if resolved_paid is None else self._batch_integer(resolved_paid, "مبلغ دریافتی")

            if product_lines and not service_lines:
                total_sale_bill = product_subtotal + hdr_extra
                converted_sale_inv = self._insert_sale_invoice_tx(
                    conn,
                    invoice_number=clean_sale_inv,
                    prepared_lines=product_lines,
                    total_invoice_amount=total_sale_bill,
                    seller_employee_id=pf["seller_employee_id"],
                    customer_name=str(pf["customer_name"] or "").strip(),
                    customer_phone=str(pf["customer_phone"] or "").strip(),
                    customer_id=pf["customer_id"],
                    sale_datetime=clean_dt,
                    settlement_status=eff_settlement,
                    clean_subtype=eff_subtype,
                    paid_amount=min(total_sale_bill, eff_paid_total),
                    resolved_payment_type=eff_ptype,
                    clean_chk_due=clean_chk_due,
                    clean_chk_status=clean_chk_status,
                    installment_plan=eff_inst,
                    inst_count=inst_count,
                    inst_interval=inst_interval,
                    inst_start_due=inst_start_due,
                    first_inst_paid=first_inst_paid,
                    extra_cost_total=hdr_extra,
                    notes=str(pf["notes"] or "").strip(),
                    operator_name=operator_name,
                    conflict_resolution=conflict_resolution,
                    expected_existing_version=expected_existing_version,
                    enforce_unique_invoice=True,
                )
            elif service_lines and not product_lines:
                total_srv_bill = service_subtotal + hdr_extra
                converted_srv_inv = self._insert_service_invoice_tx(
                    conn,
                    invoice_number=clean_srv_inv,
                    items=service_lines,
                    seller_employee_id=pf["seller_employee_id"],
                    technician_employee_id=technician_employee_id or pf["seller_employee_id"],
                    customer_id=pf["customer_id"],
                    customer_name=str(pf["customer_name"] or "").strip(),
                    customer_phone=str(pf["customer_phone"] or "").strip(),
                    service_datetime=clean_dt,
                    settlement_status=eff_settlement,
                    clean_subtype=eff_subtype,
                    paid_amount=min(total_srv_bill, eff_paid_total),
                    resolved_payment_type=eff_ptype,
                    clean_chk_due=clean_chk_due,
                    clean_chk_status=clean_chk_status,
                    installment_plan=eff_inst,
                    inst_count=inst_count,
                    inst_interval=inst_interval,
                    inst_start_due=inst_start_due,
                    first_inst_paid=first_inst_paid,
                    extra_cost_total=hdr_extra,
                    operator_name=operator_name,
                    conflict_resolution=conflict_resolution,
                    expected_existing_version=expected_existing_version,
                    enforce_unique_invoice=True,
                )
            else:
                # Mixed product + service conversion in one atomic transaction; extra_cost_total assigned once to INV-
                sale_bill = product_subtotal + hdr_extra
                srv_bill = service_subtotal
                sale_paid = min(sale_bill, eff_paid_total)
                srv_paid = min(srv_bill, max(0, eff_paid_total - sale_paid))
                sale_st = "تسویه‌شده" if sale_paid >= sale_bill else ("تسویه‌نشده" if sale_paid == 0 else "تسویه جزئی")
                srv_st = "تسویه‌شده" if srv_paid >= srv_bill else ("تسویه‌نشده" if srv_paid == 0 else "تسویه جزئی")
                converted_sale_inv = self._insert_sale_invoice_tx(
                    conn,
                    invoice_number=clean_sale_inv,
                    prepared_lines=product_lines,
                    total_invoice_amount=sale_bill,
                    seller_employee_id=pf["seller_employee_id"],
                    customer_name=str(pf["customer_name"] or "").strip(),
                    customer_phone=str(pf["customer_phone"] or "").strip(),
                    customer_id=pf["customer_id"],
                    sale_datetime=clean_dt,
                    settlement_status=eff_settlement if not eff_inst else sale_st,
                    clean_subtype=eff_subtype if sale_paid >= sale_bill else "",
                    paid_amount=sale_paid,
                    resolved_payment_type=eff_ptype if eff_inst or sale_paid >= sale_bill else ("partial" if sale_paid > 0 else eff_ptype),
                    clean_chk_due=clean_chk_due if eff_ptype == "check" else "",
                    clean_chk_status=clean_chk_status if eff_ptype == "check" else "",
                    installment_plan=eff_inst if eff_inst and (sale_bill - sale_paid > 0) else None,
                    inst_count=inst_count,
                    inst_interval=inst_interval,
                    inst_start_due=inst_start_due,
                    first_inst_paid=first_inst_paid,
                    extra_cost_total=hdr_extra,
                    notes=str(pf["notes"] or "").strip(),
                    operator_name=operator_name,
                    conflict_resolution=conflict_resolution,
                    expected_existing_version=expected_existing_version,
                    enforce_unique_invoice=True,
                )
                converted_srv_inv = self._insert_service_invoice_tx(
                    conn,
                    invoice_number=clean_srv_inv,
                    items=service_lines,
                    seller_employee_id=pf["seller_employee_id"],
                    technician_employee_id=technician_employee_id or pf["seller_employee_id"],
                    customer_id=pf["customer_id"],
                    customer_name=str(pf["customer_name"] or "").strip(),
                    customer_phone=str(pf["customer_phone"] or "").strip(),
                    service_datetime=clean_dt,
                    settlement_status=srv_st,
                    clean_subtype="",
                    paid_amount=srv_paid,
                    resolved_payment_type="cash" if srv_paid >= srv_bill else "partial",
                    clean_chk_due="",
                    clean_chk_status="",
                    installment_plan=None,
                    extra_cost_total=0,
                    operator_name=operator_name,
                    enforce_unique_invoice=True,
                )

            upd = conn.execute(
                """
                UPDATE proforma_invoices
                SET status='converted', converted_sale_invoice=?, converted_service_invoice=?,
                    last_modified_by=?, last_modified_at=?
                WHERE id=? AND status='open' AND row_version=?
                """,
                (converted_sale_inv, converted_srv_inv, mod_by, mod_at, pf_id, int(pf["row_version"] or 1)),
            )
            if upd.rowcount != 1:
                raise ConcurrencyConflictError(
                    "proforma",
                    pf_id,
                    int(pf["row_version"] or 1),
                    int(pf["row_version"] or 1) + 1,
                    dict(pf),
                    "پیش‌فاکتور هم‌زمان توسط کاربر دیگری تبدیل یا تغییر یافته است.",
                )
            self.log_audit(
                conn,
                "تبدیل پیش‌فاکتور",
                f"پیش‌فاکتور: {pf['proforma_number']} -> فروش: {converted_sale_inv or '-'} | خدمات: {converted_srv_inv or '-'}",
            )
            return converted_sale_inv or converted_srv_inv

        return self.run_write_transaction(_tx)

    # =========================================================================
    # حذف گروهی اتمیک رکوردها (Atomic Batch Deletion - Daqiq v5.0.1 - REQ-05)
    # =========================================================================
    def delete_products_batch(self, prod_ids: list[int]) -> int:
        ids = list(dict.fromkeys(self._batch_integer(x, "شناسه کالا", minimum=1) for x in (prod_ids or [])))
        if not ids:
            return 0

        def _tx(conn):
            marks = ",".join("?" for _ in ids)
            batch_rows = conn.execute(f"SELECT id FROM batches WHERE product_id IN ({marks})", ids).fetchall()
            self._hard_delete_batches(conn, [int(r["id"]) for r in batch_rows])
            for pid in ids:
                self._delete_linked_sales(conn, product_id=pid)
            conn.execute(f"DELETE FROM proforma_items WHERE product_id IN ({marks})", ids)
            cur = conn.execute(f"DELETE FROM products WHERE id IN ({marks})", ids)
            self.log_audit(conn, "حذف گروهی کالاها", f"تعداد: {cur.rowcount} | شناسه‌ها: {ids}")
            return int(cur.rowcount or 0)

        return self.run_write_transaction(_tx)

    def delete_batches_batch(self, batch_ids: list[int]) -> int:
        ids = list(dict.fromkeys(self._batch_integer(x, "شناسه محموله", minimum=1) for x in (batch_ids or [])))
        if not ids:
            return 0

        def _tx(conn):
            marks = ",".join("?" for _ in ids)
            rows = conn.execute(f"SELECT id, batch_code FROM batches WHERE id IN ({marks})", ids).fetchall()
            if not rows:
                return 0
            found_ids = [int(r["id"]) for r in rows]
            codes = [str(r["batch_code"]) for r in rows]
            self._hard_delete_batches(conn, found_ids)
            self.log_audit(conn, "حذف گروهی محموله‌ها", f"تعداد: {len(codes)} | کدها: {', '.join(codes)}")
            return len(found_ids)

        return self.run_write_transaction(_tx)

    def delete_sales_batch(self, sale_ids: list[int]) -> int:
        ids = list(dict.fromkeys(self._batch_integer(x, "شناسه فروش", minimum=1) for x in (sale_ids or [])))
        if not ids:
            return 0

        def _tx(conn):
            marks = ",".join("?" for _ in ids)
            rows = conn.execute(
                f"SELECT id, invoice_number, batch_id, qty FROM sales WHERE id IN ({marks}) ORDER BY id DESC",
                ids,
            ).fetchall()
            if not rows:
                return 0
            touched_invoices = set()
            for r in rows:
                stock_upd = conn.execute(
                    "UPDATE batches SET sold_qty=sold_qty-?, remaining_qty=remaining_qty+? WHERE id=? AND sold_qty>=?",
                    (int(r["qty"]), int(r["qty"]), int(r["batch_id"]), int(r["qty"])),
                )
                if stock_upd.rowcount != 1:
                    raise ValueError(f"موجودی مصرف‌شدهٔ محموله برای فاکتور {r['invoice_number']} سازگار نیست.")
                touched_invoices.add(str(r["invoice_number"] or "").strip())
            conn.execute(
                f"DELETE FROM installment_payments WHERE plan_id IN (SELECT id FROM installment_plans WHERE sale_id IN ({marks}))",
                ids,
            )
            conn.execute(f"DELETE FROM installment_plans WHERE sale_id IN ({marks})", ids)
            conn.execute(f"DELETE FROM payments WHERE ref_type='sale' AND ref_id IN ({marks})", ids)
            conn.execute(f"DELETE FROM checks WHERE ref_type='sale' AND ref_id IN ({marks})", ids)
            conn.execute(f"DELETE FROM sales WHERE id IN ({marks})", ids)
            for inv_no in touched_invoices:
                if not inv_no:
                    continue
                rem = conn.execute("SELECT COUNT(*) FROM sales WHERE invoice_number=?", (inv_no,)).fetchone()[0]
                if int(rem or 0) == 0:
                    conn.execute("DELETE FROM checks WHERE ref_type='sale' AND invoice_number=?", (inv_no,))
                    conn.execute("DELETE FROM invoice_headers WHERE invoice_kind='sale' AND invoice_number=?", (inv_no,))
            self.log_audit(conn, "حذف گروهی فروش", f"تعداد: {len(rows)} | فاکتورها: {', '.join(sorted(touched_invoices))}")
            return len(rows)

        return self.run_write_transaction(_tx)

    def delete_service_records_batch(self, record_ids: list[int]) -> int:
        ids = list(dict.fromkeys(self._batch_integer(x, "شناسه خدمت", minimum=1) for x in (record_ids or [])))
        if not ids:
            return 0

        def _tx(conn):
            marks = ",".join("?" for _ in ids)
            rows = conn.execute(
                f"SELECT id, invoice_number FROM service_records WHERE id IN ({marks})",
                ids,
            ).fetchall()
            if not rows:
                return 0
            invs = {str(r["invoice_number"] or "").strip() for r in rows if str(r["invoice_number"] or "").strip()}
            conn.execute(
                f"DELETE FROM installment_payments WHERE plan_id IN (SELECT id FROM installment_plans WHERE service_record_id IN ({marks}))",
                ids,
            )
            conn.execute(f"DELETE FROM installment_plans WHERE service_record_id IN ({marks})", ids)
            conn.execute(f"DELETE FROM payments WHERE ref_type='service' AND ref_id IN ({marks})", ids)
            conn.execute(f"DELETE FROM checks WHERE ref_type='service' AND ref_id IN ({marks})", ids)
            conn.execute(f"DELETE FROM service_records WHERE id IN ({marks})", ids)
            for inv_no in invs:
                rem = conn.execute("SELECT COUNT(*) FROM service_records WHERE invoice_number=?", (inv_no,)).fetchone()[0]
                if int(rem or 0) == 0:
                    conn.execute("DELETE FROM checks WHERE ref_type='service' AND invoice_number=?", (inv_no,))
                    conn.execute("DELETE FROM invoice_headers WHERE invoice_kind='service' AND invoice_number=?", (inv_no,))
            self.log_audit(conn, "حذف گروهی خدمات", f"تعداد: {len(rows)} | فاکتورها: {', '.join(sorted(invs))}")
            return len(rows)

        return self.run_write_transaction(_tx)

    def revert_upgrades_batch(self, upgrade_ids: list[int]) -> int:
        ids = list(dict.fromkeys(self._batch_integer(x, "شناسه ارتقا", minimum=1) for x in (upgrade_ids or [])))
        if not ids:
            return 0

        def _tx(conn):
            marks = ",".join("?" for _ in ids)
            selected = conn.execute(
                f"""
                SELECT id, target_batch_id, part_batch_id, technician_id, target_qty,
                       part_qty_used, stock_deducted_qty, part_unit_cost, labor_cost_unit,
                       added_cost_unit, upgrade_date, serial_number, manual_part_description,
                       old_specs, new_specs, notes, created_at, updated_at
                FROM upgrades
                WHERE id IN ({marks})
                ORDER BY updated_at DESC, id DESC
                """,
                ids,
            ).fetchall()
            if not selected:
                return 0
            selected_set = {int(r["id"]) for r in selected}
            target_batches = {int(r["target_batch_id"]) for r in selected}
            for tb_id in target_batches:
                chain = conn.execute(
                    "SELECT id FROM upgrades WHERE target_batch_id=? ORDER BY updated_at DESC, id DESC",
                    (tb_id,),
                ).fetchall()
                chain_ids = [int(r["id"]) for r in chain]
                seen_unselected = False
                for cid in chain_ids:
                    if cid in selected_set:
                        if seen_unselected:
                            raise ValueError(
                                "برای جلوگیری از برهم خوردن زنجیره بهای تمام‌شده، ارتقاهای هر محموله باید از جدیدترین به قدیم‌تر به‌صورت پیوسته انتخاب و حذف شوند."
                            )
                    else:
                        seen_unselected = True
            for upg in selected:
                self._reverse_upgrade_effects(conn, upg)
                conn.execute("DELETE FROM upgrades WHERE id=?", (int(upg["id"]),))
            self.log_audit(conn, "حذف گروهی ارتقای کالا", f"تعداد: {len(selected)} | شناسه‌ها: {list(selected_set)}")
            return len(selected)

        return self.run_write_transaction(_tx)

    def delete_suppliers_batch(self, sup_ids: list[int], delete_related_data: bool = False) -> int:
        ids = list(dict.fromkeys(self._batch_integer(x, "شناسه تأمین‌کننده", minimum=1) for x in (sup_ids or [])))
        if not ids:
            return 0

        def _tx(conn):
            marks = ",".join("?" for _ in ids)
            sups = conn.execute(f"SELECT id, name FROM suppliers WHERE id IN ({marks})", ids).fetchall()
            if not sups:
                return 0
            if not delete_related_data:
                act = conn.execute(
                    f"SELECT id FROM supplier_installment_plans WHERE supplier_id IN ({marks}) AND status='active' LIMIT 1",
                    ids,
                ).fetchone()
                if act:
                    raise ValueError(
                        "حداقل یکی از تأمین‌کنندگان انتخاب‌شده دارای طرح خرید اقساطی فعال است. ابتدا اقساط تسویه یا با حذف سوابق اقدام کنید."
                    )
                for sup in sups:
                    conn.execute(
                        "UPDATE batches SET supplier_name_snapshot=?, supplier_id=NULL WHERE supplier_id=?",
                        (sup["name"], int(sup["id"])),
                    )
            else:
                batch_rows = conn.execute(f"SELECT id FROM batches WHERE supplier_id IN ({marks})", ids).fetchall()
                self._hard_delete_batches(conn, [int(r["id"]) for r in batch_rows])
            conn.execute(f"UPDATE checks SET supplier_id=NULL WHERE supplier_id IN ({marks})", ids)
            conn.execute(f"DELETE FROM suppliers WHERE id IN ({marks})", ids)
            self.log_audit(conn, "حذف گروهی تأمین‌کنندگان", f"تعداد: {len(sups)}")
            return len(sups)

        return self.run_write_transaction(_tx)

    def delete_customers_batch(self, customer_ids: list[int], delete_related_data: bool = False) -> int:
        ids = list(dict.fromkeys(self._batch_integer(x, "شناسه مشتری", minimum=1) for x in (customer_ids or [])))
        if not ids:
            return 0

        def _tx(conn):
            deleted = self._delete_customers_tx(conn, ids, delete_related_data=bool(delete_related_data))
            self.log_audit(conn, "حذف گروهی مشتریان", f"تعداد: {deleted} | حذف سوابق: {bool(delete_related_data)}")
            return deleted

        return self.run_write_transaction(_tx)

    def delete_employees_batch(self, emp_ids: list[int], delete_related_data: bool = False) -> int:
        ids = list(dict.fromkeys(self._batch_integer(x, "شناسه کاربر", minimum=1) for x in (emp_ids or [])))
        if not ids:
            return 0

        def _tx(conn):
            marks = ",".join("?" for _ in ids)
            emps = conn.execute(f"SELECT id FROM employees WHERE id IN ({marks})", ids).fetchall()
            if not emps:
                return 0
            if delete_related_data:
                batch_rows = conn.execute(f"SELECT id FROM batches WHERE buyer_employee_id IN ({marks})", ids).fetchall()
                self._hard_delete_batches(conn, [int(r["id"]) for r in batch_rows])
                for eid in ids:
                    self._delete_linked_sales(conn, seller_id=eid)
                conn.execute(
                    f"DELETE FROM installment_payments WHERE plan_id IN (SELECT id FROM installment_plans WHERE service_record_id IN (SELECT id FROM service_records WHERE seller_employee_id IN ({marks}) OR technician_employee_id IN ({marks})))",
                    (*ids, *ids),
                )
                conn.execute(
                    f"DELETE FROM installment_plans WHERE service_record_id IN (SELECT id FROM service_records WHERE seller_employee_id IN ({marks}) OR technician_employee_id IN ({marks}))",
                    (*ids, *ids),
                )
                conn.execute(
                    f"DELETE FROM service_records WHERE seller_employee_id IN ({marks}) OR technician_employee_id IN ({marks})",
                    (*ids, *ids),
                )
                conn.execute(f"DELETE FROM upgrades WHERE technician_id IN ({marks})", ids)
            else:
                conn.execute(f"UPDATE batches SET buyer_employee_id=NULL WHERE buyer_employee_id IN ({marks})", ids)
                conn.execute(f"UPDATE sales SET seller_employee_id=NULL WHERE seller_employee_id IN ({marks})", ids)
                conn.execute(
                    f"UPDATE service_records SET seller_employee_id=NULL, technician_employee_id=NULL WHERE seller_employee_id IN ({marks}) OR technician_employee_id IN ({marks})",
                    (*ids, *ids),
                )
                conn.execute(f"UPDATE upgrades SET technician_id=NULL WHERE technician_id IN ({marks})", ids)
            conn.execute(f"UPDATE proforma_invoices SET seller_employee_id=NULL WHERE seller_employee_id IN ({marks})", ids)
            conn.execute(f"DELETE FROM access_level_scope_users WHERE employee_id IN ({marks})", ids)
            conn.execute(f"DELETE FROM employees WHERE id IN ({marks})", ids)
            self.log_audit(conn, "حذف گروهی کاربران", f"تعداد: {len(emps)}")
            return len(emps)

        return self.run_write_transaction(_tx)
