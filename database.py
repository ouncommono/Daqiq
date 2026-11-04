# database.py
import os
import sys
import json
import sqlite3
import jdatetime
import time
import hashlib
from decimal import Decimal, ROUND_HALF_EVEN

APP_VERSION = "4.0.0"
SCHEMA_VERSION = 400

SQLITE_INTEGER_MIN = -(1 << 63)
SQLITE_INTEGER_MAX = (1 << 63) - 1

# New v4 databases have a deliberate, testable physical column order. Application
# SQL uses named columns; this contract protects all positional consumers.
EXPECTED_SCHEMA_COLUMNS = {
    "settings": ("key", "value"),
    "employees": ("id", "name", "role", "phone", "is_active", "permissions", "password", "created_at", "updated_at"),
    "access_level_data_scopes": ("access_level_name", "mode"),
    "access_level_scope_levels": ("access_level_name", "selected_access_level_name"),
    "access_level_scope_users": ("access_level_name", "employee_id"),
    "suppliers": ("id", "name", "phone", "address", "notes", "created_at", "updated_at"),
    "customers": ("id", "name", "phone", "notes", "created_at", "updated_at"),
    "products": ("id", "code", "name", "category", "sub_category", "brand", "model", "specs_json", "description", "reorder_point", "default_profit_pct", "is_active", "created_at", "updated_at"),
    "batches": ("id", "batch_code", "product_id", "supplier_id", "buyer_employee_id", "invoice_number", "purchase_date", "initial_qty", "sold_qty", "returned_qty", "remaining_qty", "unit_purchase_price", "extra_cost_total", "upgrade_cost_unit", "unit_cost_price", "suggested_sell_price", "profit_pct", "paid_amount", "settlement_status", "serial_numbers", "colors_json", "initial_specs", "final_specs", "supplier_name_snapshot", "notes", "created_at", "updated_at"),
    "upgrades": ("id", "target_batch_id", "part_batch_id", "technician_id", "target_qty", "part_qty_used", "stock_deducted_qty", "part_unit_cost", "labor_cost_unit", "added_cost_unit", "upgrade_date", "serial_number", "manual_part_description", "old_specs", "new_specs", "notes", "created_at", "updated_at"),
    "sales": ("id", "invoice_number", "product_id", "batch_id", "seller_employee_id", "customer_name", "qty", "returned_qty", "suggested_unit_price", "actual_unit_price", "unit_cost_price", "unit_discount", "total_discount", "price_Markup_unit", "unit_profit", "total_profit", "total_amount", "paid_amount", "settlement_status", "sale_datetime", "warranty_company", "warranty_start", "warranty_months", "warranty_days", "warranty_end", "serial_number", "specifications", "colors_json", "notes", "created_at", "updated_at"),
    "service_catalog": ("id", "code", "service_type", "name", "default_fee", "default_side_cost", "description", "is_active", "created_at", "updated_at"),
    "service_price_history": ("id", "service_id", "change_date", "old_fee", "new_fee", "created_at", "updated_at"),
    "service_records": ("id", "invoice_number", "service_id", "seller_employee_id", "technician_employee_id", "service_type", "service_name", "customer_name", "historical_tariff", "service_fee", "side_cost", "paid_amount", "net_profit", "settlement_status", "service_datetime", "description", "created_at", "updated_at"),
    "payments": ("id", "ref_type", "ref_id", "amount", "payment_date", "payment_method", "notes", "created_at", "updated_at"),
    "audit_logs": ("id", "action_time", "action_type", "details", "created_at", "updated_at"),
}

def validate_schema_column_order(conn):
    """Fail fast when a database does not match the exact v4 column contract."""
    for table_name, expected_columns in EXPECTED_SCHEMA_COLUMNS.items():
        actual_columns = tuple(
            row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")
        )
        if actual_columns != expected_columns:
            raise RuntimeError(
                f"ساختار ستون‌های جدول {table_name} با قرارداد نسخه 4.0.0 سازگار نیست."
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


def get_default_database_dir():
    """Return the user's Documents/Daqiq directory for the default store database."""
    documents_dir = os.path.join(os.path.expanduser("~"), "Documents")
    path = os.path.join(documents_dir, "Daqiq")
    os.makedirs(path, exist_ok=True)
    return path


def get_default_database_path():
    return os.path.join(get_default_database_dir(), "Daqiq.db")


def get_config_file_path():
    """Keep portable settings beside the executable whenever that location is writable."""
    app_dir = os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__
    ))
    local_path = os.path.join(app_dir, "app_config.json")
    try:
        probe = local_path + ".write-test"
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("")
        os.remove(probe)
        return local_path
    except OSError:
        return os.path.join(get_app_data_dir(), "app_config.json")


CONFIG_FILE = get_config_file_path()


def app_config_exists():
    """Return whether an explicit database-selection/configuration file exists."""
    return os.path.isfile(CONFIG_FILE)


def load_app_config():
    default_db = get_default_database_path()
    default_cfg = {
        "db_path": default_db,
        "recent_databases": [default_db],
        "backup_dir": os.path.join(get_default_database_dir(), "backups"),
        "auto_backup_enabled": True,
        "auto_backup_interval_min": 60,
        "auto_backup_retention_count": 10,
        "auto_backup_last_success_by_db": {},
        "last_backup_time": "ثبت نشده",
        "default_profit_pct": 20,
        "zero_append_count": 3,
        "default_window_maximized": True,
        "require_login_password": False,
        "config_schema_version": 2,
        "app_version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
        "theme": "light",
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                default_cfg.update(data)
        except Exception:
            pass
    if default_cfg["db_path"] not in default_cfg["recent_databases"]:
        default_cfg["recent_databases"].append(default_cfg["db_path"])
    return default_cfg

def hash_password(raw_password: str) -> str:
    """هش کردن یک‌طرفه و امن رمز عبور با الگوریتم SHA-256"""
    if not raw_password:
        return ""
    return hashlib.sha256(raw_password.encode("utf-8")).hexdigest()


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


class DatabaseManager:
    def __init__(self, db_path=None):
        self.cfg = load_app_config()
        self.db_path = os.path.abspath(db_path or self.cfg["db_path"])
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self.cfg["db_path"] = self.db_path
        self.cfg["backup_dir"] = os.path.dirname(self.db_path) or "."
        self.init_db()
        self._normalize_application_config()
        save_app_config(self.cfg)

    def get_connection(self):
        """Create a bounded-wait connection with referential integrity enabled."""
        conn = sqlite3.connect(
            self.db_path,
            timeout=30.0,
            isolation_level="DEFERRED",
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def sync_database(self):
        """همگام‌سازی و اطمینان از ثبت کامل تراکنش‌های باز روی دیسک"""
        with self.get_connection() as conn:
            conn.execute("PRAGMA wal_checkpoint(FULL);")
            conn.commit()

    def init_db(self):
        with self.get_connection() as conn:
            # WAL keeps readers available while serialized writers commit.  The
            # setting is persistent for this file and is applied before schema DDL.
            conn.execute("PRAGMA journal_mode = WAL")
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
                    "این پایگاه داده برای نسخه 4.0.0 ساخته نشده است. "
                    "نسخه 4.0.0 به پایگاه داده تازه نیاز دارد و مهاجرت خودکار "
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
                    updated_at TEXT NOT NULL DEFAULT ''
                )
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
                    updated_at TEXT NOT NULL DEFAULT ''
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    phone TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE CHECK (length(trim(code)) > 0),
                    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
                    category TEXT NOT NULL CHECK (length(trim(category)) > 0),
                    sub_category TEXT DEFAULT 'سایر موارد',
                    brand TEXT DEFAULT '',
                    model TEXT DEFAULT '',
                    specs_json TEXT DEFAULT '{}',
                    description TEXT DEFAULT '',
                    reorder_point INTEGER NOT NULL DEFAULT 2 CHECK (reorder_point >= 0),
                    default_profit_pct REAL NOT NULL DEFAULT 20.0,
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_code TEXT NOT NULL UNIQUE CHECK (length(trim(batch_code)) > 0),
                    product_id INTEGER NOT NULL,
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
                    serial_numbers TEXT DEFAULT '',
                    colors_json TEXT NOT NULL DEFAULT '[]',
                    initial_specs TEXT DEFAULT '',
                    final_specs TEXT DEFAULT '',
                    supplier_name_snapshot TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
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
                    seller_employee_id INTEGER,
                    customer_name TEXT DEFAULT '',
                    qty INTEGER NOT NULL CHECK (qty > 0),
                    returned_qty INTEGER NOT NULL DEFAULT 0 CHECK (returned_qty >= 0 AND returned_qty <= qty),
                    suggested_unit_price INTEGER NOT NULL CHECK (suggested_unit_price >= 0),
                    actual_unit_price INTEGER NOT NULL CHECK (actual_unit_price >= 0),
                    unit_cost_price INTEGER NOT NULL CHECK (unit_cost_price >= 0),
                    unit_discount INTEGER NOT NULL DEFAULT 0,
                    total_discount INTEGER NOT NULL DEFAULT 0,
                    price_Markup_unit INTEGER NOT NULL DEFAULT 0,
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
                    serial_number TEXT DEFAULT '',
                    specifications TEXT DEFAULT '',
                    colors_json TEXT NOT NULL DEFAULT '[]',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
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
                    updated_at TEXT NOT NULL DEFAULT ''
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS service_price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service_id INTEGER NOT NULL,
                    change_date TEXT NOT NULL,
                    old_fee INTEGER,
                    new_fee INTEGER,
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(service_id) REFERENCES service_catalog(id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS service_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_number TEXT NOT NULL,
                    service_id INTEGER NOT NULL,
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
                    FOREIGN KEY(service_id) REFERENCES service_catalog(id),
                    FOREIGN KEY(seller_employee_id) REFERENCES employees(id),
                    FOREIGN KEY(technician_employee_id) REFERENCES employees(id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ref_type TEXT NOT NULL,
                    ref_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    payment_date TEXT NOT NULL,
                    payment_method TEXT DEFAULT 'کارت‌خوان',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
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

            validate_schema_column_order(conn)

            # نام فروشگاه به هر پایگاه داده تعلق دارد؛ تنظیمات عمومی برنامه
            # در app_config.json نگهداری می‌شوند.
            default_settings = {
                "shop_name": str(self.cfg.get("shop_name") or "فروشگاه من"),
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
                "service_records", "suppliers", "employees", "customers", "payments",
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
            ):
                conn.execute(index_sql)

            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

            conn.commit()

    def _normalize_application_config(self):
        """Normalize current application settings without database migration."""
        self.cfg["config_schema_version"] = 2
        self.cfg["app_version"] = APP_VERSION
        self.cfg["schema_version"] = SCHEMA_VERSION
        self.cfg["backup_dir"] = os.path.dirname(os.path.abspath(self.db_path)) or "."
        self.cfg["db_path"] = os.path.abspath(self.db_path)
        self.cfg["auto_backup_retention_count"] = max(
            1, int(self.cfg.get("auto_backup_retention_count", 10) or 10)
        )
        if not isinstance(self.cfg.get("auto_backup_last_success_by_db"), dict):
            self.cfg["auto_backup_last_success_by_db"] = {}

    def get_setting(self, key, default=""):
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key, value):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, str(value)),
            )
            conn.commit()

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
                    label = str(item.get("label", "") or "").strip()
                    if label:
                        normalized_item["label"] = label
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
                    else ["نرم‌افزاری", "سخت‌افزاری"]
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
        service_types = config.get("service_types", ["نرم‌افزاری", "سخت‌افزاری"])
        removed_default_subcategories = config.get("removed_default_subcategories", {})
        if not isinstance(categories, list) or not isinstance(subcategories, dict):
            raise ValueError("ساختار دسته‌بندی یا زیرمجموعه‌ها معتبر نیست.")
        if not isinstance(attributes, dict) or not isinstance(colors, list):
            raise ValueError("ساختار مشخصات فنی یا رنگ‌ها معتبر نیست.")
        if not isinstance(service_types, list):
            raise ValueError("فهرست نوع خدمات معتبر نیست.")
        if not isinstance(removed_default_subcategories, dict):
            raise ValueError("فهرست زیرمجموعه‌های غیرفعال معتبر نیست.")

        clean_categories = list(dict.fromkeys(
            str(value).strip() for value in categories
            if value is not None and str(value).strip()
        ))
        clean_subcategories = {}
        for category, values in subcategories.items():
            if not isinstance(values, list):
                raise ValueError(f"فهرست زیرمجموعه‌های «{category}» معتبر نیست.")
            clean_subcategories[str(category)] = list(dict.fromkeys(
                str(value).strip() for value in values
                if value is not None and str(value).strip()
            ))

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
        if conn is not None:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("product_catalog_config", serialized),
            )
            return
        self.set_setting("product_catalog_config", serialized)

    def log_audit(self, conn, action_type, details):
        now_str = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
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
        reorder_point,
        default_profit_pct,
    ):
        auto_name = (
            name.strip()
            if name and name.strip()
            else self.build_product_title(category, sub_category, brand, model)
        )
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not code:
                code = self.generate_next_code("products", "code", "P-", 1001, conn=conn)
            conn.execute(
                """
                INSERT INTO products (code, name, category, sub_category, brand, model, specs_json, description, reorder_point, default_profit_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            self.log_audit(conn, "ثبت کالا", f"کد کالا: {code} - {auto_name}")
            conn.commit()
            return code

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
    ):
        auto_name = (
            name.strip()
            if name and name.strip()
            else self.build_product_title(category, sub_category, brand, model)
        )
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE products SET code=?, name=?, category=?, sub_category=?, brand=?, model=?,
                specs_json=?, description=?, reorder_point=?, default_profit_pct=?
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
                    prod_id,
                ),
            )
            self.log_audit(conn, "ویرایش کالا", f"کد کالا: {code} - {auto_name}")
            conn.commit()

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

    def delete_product(self, prod_id):
        """Hard-delete product history and dependent batches transactionally."""
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            batch_rows = conn.execute(
                "SELECT id FROM batches WHERE product_id=?", (prod_id,)
            ).fetchall()
            batch_ids = [int(row["id"]) for row in batch_rows]
            self._hard_delete_batches(conn, batch_ids)
            # Also remove any orphaned sale records created by older versions.
            self._delete_linked_sales(conn, product_id=prod_id)
            conn.execute("DELETE FROM products WHERE id=?", (prod_id,))
            self.log_audit(conn, "حذف کامل کالا", f"شناسه کالا: {prod_id}")
            conn.commit()


    def add_supplier(self, name, phone, address, notes=""):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO suppliers (name, phone, address, notes) VALUES (?, ?, ?, ?)",
                (name.strip(), phone.strip(), address.strip(), notes.strip()),
            )
            conn.commit()

    def update_supplier(self, sup_id, name, phone, address, notes=""):
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE suppliers SET name=?, phone=?, address=?, notes=? WHERE id=?",
                (name.strip(), phone.strip(), address.strip(), notes.strip(), sup_id),
            )
            conn.commit()

    def delete_supplier(self, sup_id, delete_related_data=False):
        """Remove a supplier while optionally retaining its purchase records and historical name."""
        with self.get_connection() as conn:
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
            conn.commit()


    def delete_employee_custom(self, emp_id: int, delete_related_data: bool = False):
        """Delete an employee; optionally remove all linked operations and reverse inventory effects."""
        with self.get_connection() as conn:
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
            conn.commit()


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

        with self.get_connection() as conn:
            # Reserve the writer before generating codes or creating suppliers;
            # every side effect then commits or rolls back as one unit.
            conn.execute("BEGIN IMMEDIATE")
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
                        (ref_type, ref_id, amount, payment_date, payment_method, notes)
                    VALUES ('batch', ?, ?, ?, 'حواله/کارت',
                            'پرداخت اولیه هنگام ثبت خرید')
                    """,
                    (batch_id, paid_amount, purchase_date),
                )
            self.log_audit(
                conn, "ثبت خرید",
                f"کد محموله: {batch_code} - تعداد: {initial_qty}",
            )
            conn.commit()
            return batch_code

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
        invoice_number = str(invoice_number or "").strip()
        serial_numbers = str(serial_numbers or "").strip()
        notes = str(notes or "").strip()
        batch_code = str(batch_code or "").strip()
        initial_specs = (
            str(initial_specs or "").strip() if initial_specs is not None else None
        )

        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute(
                """
                SELECT id, batch_code, product_id, supplier_id, buyer_employee_id,
                       invoice_number, purchase_date, initial_qty, sold_qty,
                       returned_qty, remaining_qty, unit_purchase_price,
                       extra_cost_total, upgrade_cost_unit, unit_cost_price,
                       suggested_sell_price, profit_pct, paid_amount,
                       settlement_status, serial_numbers, colors_json, initial_specs,
                       final_specs, supplier_name_snapshot, notes, created_at, updated_at
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
            paid_amount, status = self._purchase_settlement(total_bill, paid_amount)

            new_colors_json = (
                json.dumps(self._normalize_color_list(colors), ensure_ascii=False)
                if colors is not None else old["colors_json"] or "[]"
            )
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
                    purchase_date, new_initial_qty, new_remaining, unit_purchase_price,
                    extra_cost_total, unit_cost_price, suggested_sell_price, profit_pct,
                    status, paid_amount, serial_numbers,
                    initial_specs if initial_specs is not None else old["initial_specs"],
                    notes, supplier_snapshot, new_colors_json, batch_id,
                ),
            )
            # The purchase form stores one current paid-amount snapshot. Replace
            # its linked payment row in this same transaction so cash-flow totals
            # cannot diverge from batches.paid_amount after an edit.
            conn.execute(
                "DELETE FROM payments WHERE ref_type='batch' AND ref_id=?",
                (batch_id,),
            )
            if paid_amount > 0:
                conn.execute(
                    """
                    INSERT INTO payments
                        (ref_type, ref_id, amount, payment_date, payment_method, notes)
                    VALUES ('batch', ?, ?, ?, 'حواله/کارت',
                            'پرداخت اصلاح‌شده هنگام ویرایش محموله')
                    """,
                    (batch_id, paid_amount, purchase_date),
                )

            self.log_audit(
                conn, "ویرایش محموله", f"کد محموله: {old['batch_code']}"
            )
            conn.commit()

    def delete_batch(self, batch_id):
        """Hard-delete a purchase batch and its dependent records atomically."""
        batch_id = self._batch_integer(batch_id, "شناسه محموله", minimum=1)
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT batch_code FROM batches WHERE id=?", (batch_id,)
            ).fetchone()
            if row is None:
                return
            self._hard_delete_batches(conn, [batch_id])
            self.log_audit(
                conn, "حذف کامل محموله", f"کد محموله: {row['batch_code']}"
            )
            conn.commit()


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

        with self.get_connection() as conn:
            previous_upgrade = None
            if upgrade_id is not None:
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
            conn.commit()

    def revert_upgrade(self, upgrade_id: int):
        """Delete an upgrade and reverse its stock and cost effects atomically."""
        with self.get_connection() as conn:
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
            conn.commit()


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
    ):
        qty = self._batch_integer(qty, "تعداد فروش", minimum=1)
        product_id = self._batch_integer(product_id, "کالا", minimum=1)
        batch_id = self._batch_integer(batch_id, "محموله", minimum=1)
        customer_name = str(customer_name or "").strip()
        warranty_company = str(warranty_company or "").strip()
        warranty_start = str(warranty_start or "").strip()
        warranty_end = str(warranty_end or "").strip()
        serial_number = str(serial_number or "").strip()
        notes = str(notes or "").strip()
        specifications = str(specifications or "").strip()
        sale_datetime = str(sale_datetime or "").strip()

        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            batch = conn.execute("""SELECT id, batch_code, product_id, supplier_id, buyer_employee_id, invoice_number,
            purchase_date, initial_qty, sold_qty, returned_qty, remaining_qty,
            unit_purchase_price, extra_cost_total, upgrade_cost_unit, unit_cost_price,
            suggested_sell_price, profit_pct, paid_amount, settlement_status,
            serial_numbers, colors_json, initial_specs, final_specs,
            supplier_name_snapshot, notes, created_at, updated_at FROM batches WHERE id=?""", (batch_id,)).fetchone()
            if not batch:
                raise ValueError("محموله انتخاب شده وجود ندارد.")
            if batch["remaining_qty"] < qty:
                raise ValueError(
                    f"موجودی محموله کافی نیست! موجودی قابل فروش: {batch['remaining_qty']} عدد"
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
                    invoice_number, product_id, batch_id, seller_employee_id, customer_name,
                    qty, suggested_unit_price, actual_unit_price, unit_cost_price,
                    unit_discount, total_discount, price_Markup_unit, unit_profit, total_profit,
                    total_amount, paid_amount, settlement_status, sale_datetime,
                    warranty_company, warranty_start, warranty_months, warranty_days, warranty_end,
                    serial_number, notes, specifications, colors_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    invoice_number,
                    product_id,
                    batch_id,
                    seller_employee_id,
                    customer_name,
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
                    serial_number,
                    notes,
                    str(specifications or ""),
                    json.dumps(normalized_colors or [], ensure_ascii=False),
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
                    INSERT INTO payments (ref_type, ref_id, amount, payment_date, payment_method, notes)
                    VALUES ('sale', ?, ?, ?, 'کارت‌خوان', 'دریافت وجه هنگام فروش')
                """,
                    (sale_id, paid_amount, sale_datetime.split(" ")[0]),
                )

            self.log_audit(
                conn,
                "ثبت فروش",
                f"فاکتور: {invoice_number} - تعداد: {qty} - سود: {total_profit:,}",
            )
            conn.commit()
            return invoice_number

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
    ):
        new_qty = self._batch_integer(new_qty, "تعداد فروش", minimum=1)
        sale_id = self._batch_integer(sale_id, "شناسه فروش", minimum=1)
        customer_name = str(customer_name or "").strip()
        warranty_company = str(warranty_company or "").strip()
        warranty_start = str(warranty_start or "").strip()
        warranty_end = str(warranty_end or "").strip()
        serial_number = str(serial_number or "").strip()
        notes = str(notes or "").strip()
        specifications = (
            str(specifications or "").strip() if specifications is not None else None
        )

        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            old_sale = conn.execute("""SELECT id, invoice_number, product_id, batch_id, seller_employee_id,
            customer_name, qty, returned_qty, suggested_unit_price, actual_unit_price,
            unit_cost_price, unit_discount, total_discount, price_Markup_unit,
            unit_profit, total_profit, total_amount, paid_amount, settlement_status,
            sale_datetime, warranty_company, warranty_start, warranty_months,
            warranty_days, warranty_end, serial_number, specifications, colors_json,
            notes, created_at, updated_at FROM sales WHERE id=?""", (sale_id,)).fetchone()
            if not old_sale:
                raise ValueError("ردیف فروش یافت نشد.")

            batch = conn.execute(
                """SELECT id, batch_code, product_id, supplier_id, buyer_employee_id, invoice_number,
            purchase_date, initial_qty, sold_qty, returned_qty, remaining_qty,
            unit_purchase_price, extra_cost_total, upgrade_cost_unit, unit_cost_price,
            suggested_sell_price, profit_pct, paid_amount, settlement_status,
            serial_numbers, colors_json, initial_specs, final_specs,
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

            conn.execute(
                """
                UPDATE sales SET seller_employee_id=?, customer_name=?, qty=?,
                suggested_unit_price=?, actual_unit_price=?, unit_discount=?, total_discount=?,
                price_Markup_unit=?, unit_profit=?, total_profit=?, total_amount=?,
                paid_amount=?, settlement_status=?, warranty_company=?, warranty_start=?,
                warranty_months=?, warranty_days=?, warranty_end=?, serial_number=?, notes=?,
                specifications=?, colors_json=?
                WHERE id=?
            """,
                (
                    seller_employee_id,
                    customer_name,
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
            conn.commit()

    def delete_sale(self, sale_id):
        sale_id = self._batch_integer(sale_id, "شناسه فروش", minimum=1)
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
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
            conn.commit()

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
        now_date = jdatetime.date.today().strftime("%Y/%m/%d")

        with self.get_connection() as conn:
            target_id = service_id

            if not target_id:
                if not code:
                    code = self.generate_next_code("service_catalog", "code", "S-", 1001)
                cur = conn.execute(
                    """
                    INSERT INTO service_catalog (code, service_type, name, default_fee, default_side_cost, description)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (code, type_clean, name_clean, default_fee, default_side_cost, description),
                )
                srv_id = cur.lastrowid
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
                        code or conn.execute("SELECT code FROM service_catalog WHERE id=?", (target_id,)).fetchone()["code"],
                        type_clean,
                        name_clean,
                        default_fee,
                        default_side_cost,
                        description,
                        target_id,
                    ),
                )
            conn.commit()

    def delete_service_catalog(self, service_id):
        """Hard-delete a service tariff together with dependent invoices and price history."""
        with self.get_connection() as conn:
            service = conn.execute(
                "SELECT name FROM service_catalog WHERE id=?", (service_id,)
            ).fetchone()
            if not service:
                return
            conn.execute("DELETE FROM service_records WHERE service_id=?", (service_id,))
            conn.execute("DELETE FROM service_price_history WHERE service_id=?", (service_id,))
            conn.execute("DELETE FROM service_catalog WHERE id=?", (service_id,))
            self.log_audit(conn, "حذف کامل خدمت", f"شناسه خدمت: {service_id} - {service['name']}")
            conn.commit()

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
        with self.get_connection() as conn:
            srv = conn.execute(
                """SELECT id, code, service_type, name, default_fee, default_side_cost,
            description, is_active, created_at, updated_at FROM service_catalog WHERE id=?""", (service_id,)
            ).fetchone()
            if not srv:
                raise ValueError("تعرفه خدمت یافت نشد.")
            if not invoice_number:
                invoice_number = self.generate_next_code(
                    "service_records", "invoice_number", "SINV-", 1001
                )

            historical_tariff = self._batch_integer(srv["default_fee"], "تعرفه تاریخی")
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
                    srv["service_type"],
                    srv["name"],
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
            conn.commit()
            return invoice_number

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
        with self.get_connection() as conn:
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
            conn.commit()

    def delete_service_record(self, record_id):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM service_records WHERE id=?", (record_id,))
            conn.commit()

    # --- پشتیبان‌گیری و بازیابی ---
    def get_automatic_backup_directory(self):
        """Return the Backups folder belonging to the currently active database."""
        database_dir = os.path.dirname(os.path.abspath(self.db_path)) or "."
        return os.path.join(database_dir, "Backups")

    def _automatic_backup_entries(self, directory, database_name):
        """Return this database's automatic snapshots, ordered oldest first."""
        prefix = f"{database_name}_"
        candidates = []
        if not os.path.isdir(directory):
            return candidates
        with os.scandir(directory) as entries:
            for entry in entries:
                if not entry.is_file() or not entry.name.endswith(".db"):
                    continue
                if not entry.name.startswith(prefix):
                    continue
                stamp = entry.name[len(prefix):-3]
                if (
                    len(stamp) >= 15
                    and stamp[:8].isdigit()
                    and stamp[8] == "_"
                    and stamp[9:15].isdigit()
                    and (len(stamp) == 15 or stamp[15:].startswith("_"))
                ):
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
        """Keep at most N automatic copies; tolerate files held open by another app."""
        candidates = self._automatic_backup_entries(directory, database_name)
        keep_count = max(1, int(self.cfg.get("auto_backup_retention_count", 10) or 10))
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
            backup_file = os.path.join(backup_dir, f"{database_name}_{stamp}.db")
            suffix = 1
            while os.path.exists(backup_file):
                backup_file = os.path.join(
                    backup_dir, f"{database_name}_{stamp}_{suffix:02d}.db"
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
            source = sqlite3.connect(database_path, timeout=30)
            destination = None
            try:
                source.execute("PRAGMA busy_timeout=30000")
                destination = sqlite3.connect(write_file, timeout=30)
                destination.execute("PRAGMA busy_timeout=30000")
                source.backup(destination, pages=256, sleep=0.25)
                destination.commit()
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

        self.cfg["last_backup_time"] = jdatetime.datetime.now().strftime(
            "%Y/%m/%d %H:%M:%S"
        )
        self.cfg["backup_dir"] = os.path.dirname(database_path) or "."
        if automatic:
            database_key = os.path.normcase(database_path)
            backup_state = dict(self.cfg.get("auto_backup_last_success_by_db", {}))
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
        self.create_backup()
        with sqlite3.connect(backup_file_path) as source:
            with sqlite3.connect(self.db_path) as destination:
                source.backup(destination)