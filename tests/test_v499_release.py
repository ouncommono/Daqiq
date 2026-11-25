"""Comprehensive v4.9.9 commercial release QA suite (REQ-00 through REQ-10)."""

from __future__ import annotations

import ast
import datetime
import json
import multiprocessing
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from PySide6.QtWidgets import QComboBox, QGroupBox, QMessageBox

import database as db_mod
from database import (
    ConcurrencyConflictError,
    DatabaseManager,
    InsufficientStockError,
    ROW_VERSION_TABLES,
    ReadOnlyGraceError,
    is_network_database_path,
)
from licensing import (
    LicenseDialog,
    LicenseService,
    LicenseStore,
    LicenseVerifier,
    MockHardwareProvider,
    ValidationStatus,
    get_active_features_fa,
    get_feature_label_fa,
    get_support_phone,
)
from licensing.keys import KeyRegistry
from licensing.license_verifier import DOMAIN_PREFIX
from tools.build_key_shards import build_shards
from troubleshooter.core import (
    discover_troubleshooting_targets,
    execute_troubleshooting_reset,
)


def _signed_license_bytes(
    private_key: ed25519.Ed25519PrivateKey,
    *,
    key_id: str,
    fp: str,
    expires_at: str,
    grace_period_days: int = 5,
    grace_mode: str = "readonly",
    features: dict | None = None,
    license_type: str = "subscription",
) -> bytes:
    payload = {
        "format_version": 1,
        "product_id": "daqiq.desktop",
        "license_id": "LIC-V499-TEST",
        "key_id": key_id,
        "license_type": license_type,
        "issued_at": "2026-01-01T00:00:00Z",
        "not_before": "2026-01-01T00:00:00Z",
        "expires_at": expires_at,
        "grace_period_days": grace_period_days,
        "grace_mode": grace_mode,
        "expiry_warning_days": 14,
        "max_clock_skew_hours": 24,
        "min_app_version": "4.0.0",
        "max_app_version": None,
        "max_devices": 1,
        "device_fingerprints": [fp],
        "customer": {"name": "فروشگاه نمونه دقیق"},
        "features": features
        or {
            "dashboard": True,
            "products": True,
            "batches": True,
            "sales": True,
            "services": True,
            "upgrades": True,
            "suppliers_payments": True,
            "reports": True,
            "employees": True,
            "settings": True,
        },
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    import base64

    sig = base64.b64encode(private_key.sign(DOMAIN_PREFIX + canonical)).decode("ascii")
    envelope = {
        "envelope_version": 1,
        "algorithm": "Ed25519",
        "key_id": key_id,
        "payload": payload,
        "signature": sig,
    }
    return json.dumps(envelope, ensure_ascii=False, indent=2).encode("utf-8")


def _make_license_env(tmp_path: Path, now_utc: datetime.datetime):
    priv = ed25519.Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    registry = KeyRegistry({"test-k1": pub_raw})
    hw = MockHardwareProvider()
    fp = hw.get_fingerprint()
    store = LicenseStore(
        machine_dir=str(tmp_path / "lic_machine"),
        user_dir=str(tmp_path / "lic_user"),
        roaming_dir=str(tmp_path / "lic_roaming"),
    )
    svc = LicenseService(
        store=store,
        verifier=LicenseVerifier(key_registry=registry),
        hardware_provider=hw,
        clock_provider=lambda: now_utc,
        app_version="4.9.9",
    )
    return priv, fp, svc


def _mp_worker_concurrent_sales(
    db_path: str,
    cfg_path: str,
    batch_id: int,
    product_id: int,
    worker_id: int,
    attempts: int,
    out_queue,
):
    """Top-level multiprocessing worker simulating a second/third LAN cashier PC."""
    db_mod.CONFIG_FILE = cfg_path
    mgr = DatabaseManager(db_path, journal_mode="DELETE")
    success_count = 0
    blocked_count = 0
    unexpected_errors = []
    try:
        for i in range(attempts):
            try:
                mgr.add_sale(
                    f"LAN-W{worker_id}-{i}",
                    product_id,
                    batch_id,
                    None,
                    f"مشتری {worker_id}-{i}",
                    1,
                    100_000,
                    100_000,
                    100_000,
                    "1405/01/10 10:00:00",
                    settlement_status="تسویه‌شده",
                )
                success_count += 1
            except (InsufficientStockError, ValueError):
                blocked_count += 1
            except Exception as exc:
                unexpected_errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        mgr.close()
    out_queue.put((worker_id, success_count, blocked_count, unexpected_errors))


def test_v498_additive_row_version_upgrade_and_triggers(tmp_path, monkeypatch):
    """v4.9.8 DBs auto-upgrade cleanly with row_version=1 and monotonic triggers."""
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db_path = tmp_path / "v498_legacy_compat.db"
    mgr = DatabaseManager(str(db_path))
    mgr.close()

    # Rebuild products table without row_version to emulate an untouched v4.9.8 file
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ALTER TABLE products RENAME TO products_old")
        conn.execute(
            """
            CREATE TABLE products (
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
                default_profit_pct REAL NOT NULL DEFAULT 20.0 CHECK (default_profit_pct >= 0),
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "INSERT INTO products (code, name, category) VALUES ('P-900', 'کالای قدیمی', 'لپ‌تاپ')"
        )
        conn.execute("DROP TABLE products_old")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
    finally:
        conn.close()

    upgraded_mgr = DatabaseManager(str(db_path))
    try:
        with upgraded_mgr.get_connection() as c:
            cols = [r["name"] for r in c.execute("PRAGMA table_info(products)").fetchall()]
            assert "row_version" in cols
            row = c.execute("SELECT id, row_version FROM products WHERE code='P-900'").fetchone()
            assert int(row["row_version"]) == 1
        upgraded_mgr.update_product(
            row["id"], "P-900", "کالای به‌روز", "لپ‌تاپ", "", "Asus", "Zen", {}, "", 1, 20.0,
            expected_row_version=1,
        )
        with upgraded_mgr.get_connection() as c:
            rv2 = int(c.execute("SELECT row_version FROM products WHERE id=?", (row["id"],)).fetchone()["row_version"])
            assert rv2 == 2
        # Stale version 1 now raises ConcurrencyConflictError
        with pytest.raises(ConcurrencyConflictError) as exc_info:
            upgraded_mgr.update_product(
                row["id"], "P-900", "ویرایش کهنه", "لپ‌تاپ", "", "Asus", "Old", {}, "", 1, 20.0,
                expected_row_version=1,
            )
        assert exc_info.value.actual_version == 2
    finally:
        upgraded_mgr.close()


def test_network_path_detection_and_lan_delete_pragmas(tmp_path, monkeypatch):
    """SMB/UNC/network paths force DELETE + synchronous=FULL + locking_mode=NORMAL + busy_timeout=15000."""
    assert is_network_database_path(r"\\192.168.1.10\SharedDaqiq\Daqiq.db") is True
    assert is_network_database_path("//fileserver/store/Daqiq.db") is True
    assert is_network_database_path(str(tmp_path / "local.db")) is False

    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    db_file = tmp_path / "lan_sim.db"
    mgr = DatabaseManager(str(db_file), network_mode=True)
    try:
        with mgr.get_connection() as conn:
            jm = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            sync_val = int(conn.execute("PRAGMA synchronous").fetchone()[0])
            lock_val = str(conn.execute("PRAGMA locking_mode").fetchone()[0]).lower()
            busy_val = int(conn.execute("PRAGMA busy_timeout").fetchone()[0])
            assert jm == "delete"
            assert sync_val == 2  # FULL
            assert lock_val == "normal"
            assert busy_val == 15000
    finally:
        mgr.close()


def test_three_process_lan_concurrency_no_oversell_and_online_backup(tmp_path, monkeypatch):
    """Real 3-process concurrent sales & backup against 1 SQLite DB prevents overselling with zero locks."""
    cfg_path = str(tmp_path / "app_config.json")
    monkeypatch.setattr(db_mod, "CONFIG_FILE", cfg_path)
    db_file = str(tmp_path / "shared_store.db")

    mgr = DatabaseManager(db_file, journal_mode="DELETE")
    prod_code = mgr.add_product("", "لپ‌تاپ تست شبکه", "لپ‌تاپ", "", "HP", "ProBook", {}, "")
    with mgr.get_connection() as conn:
        prod_id = int(conn.execute("SELECT id FROM products WHERE code=?", (prod_code,)).fetchone()["id"])
    batch_code = mgr.add_batch(
        "C-LAN-1", prod_id, None, None, "INV-IN", "1405/01/01", 8, 50_000, 0, 100_000, 0
    )
    with mgr.get_connection() as conn:
        b_row = conn.execute("SELECT id, row_version FROM batches WHERE batch_code=?", (batch_code,)).fetchone()
        batch_id = int(b_row["id"])
        orig_ver = int(b_row["row_version"])

    # Establish baseline data_version on observer before workers write
    _, changed_before = mgr.poll_external_data_version()
    assert changed_before is False

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    workers = [
        ctx.Process(
            target=_mp_worker_concurrent_sales,
            args=(db_file, cfg_path, batch_id, prod_id, w, 6, q),
        )
        for w in range(3)
    ]
    for w in workers:
        w.start()
    # Simultaneously perform an online SQLite backup while writers contend!
    bk_path = mgr.create_backup(custom_dir=str(tmp_path / "bk"))
    for w in workers:
        w.join(timeout=60)
        assert w.exitcode == 0

    results = [q.get(timeout=5) for _ in workers]
    total_sold = sum(r[1] for r in results)
    total_blocked = sum(r[2] for r in results)
    errors = [err for r in results for err in r[3]]

    assert errors == []
    assert total_sold == 8
    assert total_blocked == 10

    with mgr.get_connection() as conn:
        b_after = conn.execute(
            "SELECT initial_qty, sold_qty, remaining_qty, row_version FROM batches WHERE id=?",
            (batch_id,),
        ).fetchone()
        assert b_after["initial_qty"] == 8
        assert b_after["sold_qty"] == 8
        assert b_after["remaining_qty"] == 0
        assert b_after["row_version"] > orig_ver

    _, changed_after = mgr.poll_external_data_version()
    assert changed_after is True
    assert os.path.isfile(bk_path)
    mgr.close()


def test_grace_period_readonly_vs_full_and_banner_themes(tmp_path, monkeypatch, qapp):
    """Verify readonly grace blocks UI+DB mutations while allowing views/backups/exports; post-grace locks."""
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    clock_now = [datetime.datetime(2026, 5, 11, 12, 0, 0, tzinfo=datetime.timezone.utc)]
    priv, fp, svc = _make_license_env(tmp_path, clock_now[0])
    # Hack clock provider to read mutable cell cleanly
    svc.clock_provider = lambda: clock_now[0]

    lic_bytes = _signed_license_bytes(
        priv,
        key_id="test-k1",
        fp=fp,
        expires_at="2026-05-10",
        grace_period_days=5,
        grace_mode="readonly",
    )
    res = svc.import_license_bytes(lic_bytes)
    assert res.status == ValidationStatus.GRACE_PERIOD
    assert res.in_grace_period is True
    assert res.grace_mode == "readonly"
    assert res.grace_days_remaining >= 4
    assert svc.is_write_allowed() is False

    mgr = DatabaseManager(str(tmp_path / "grace.db"))
    import main as main_mod

    win = main_mod.MainWindow(mgr, license_service=svc)
    win.show()
    try:
        assert mgr.is_read_only_mode() is True
        assert win.license_banner_frame.isVisible() is True
        banner_txt = win.lbl_license_banner.text()
        assert "روز باقیمانده" in banner_txt
        assert "فقط خواندنی" in banner_txt
        assert get_support_phone() in banner_txt

        # DB mutation blocked cleanly by ReadOnlyGraceError
        with pytest.raises(ReadOnlyGraceError):
            mgr.add_product("P-BLK", "مسدود", "لپ‌تاپ", "", "Dell", "XPS", {}, "")

        # Backup and exports remain permitted during readonly grace
        bk_file = mgr.create_backup(custom_dir=str(tmp_path / "grace_backups"))
        assert os.path.isfile(bk_file)
        assert win.btn_manual_bk.isEnabled() is True
        assert win.btn_safe_export.isEnabled() is True

        # Theme toggle updates to حالت تیره / حالت روشن and refreshes banner cleanly
        assert win.btn_theme.text() in ("🌙 حالت تیره", "☀️ حالت روشن")
        win._toggle_theme()
        assert "حالت" in win.btn_theme.text()
        assert "تم تیره" not in win.btn_theme.text()
        assert "تم روشن" not in win.btn_theme.text()

        # Full grace allows writes
        lic_full = _signed_license_bytes(
            priv,
            key_id="test-k1",
            fp=fp,
            expires_at="2026-05-10",
            grace_period_days=5,
            grace_mode="full",
        )
        res_full = svc.import_license_bytes(lic_full)
        assert res_full.in_grace_period is True
        assert res_full.grace_mode == "full"
        assert svc.is_write_allowed() is True
        win._periodic_license_check()
        assert mgr.is_read_only_mode() is False
        code = mgr.add_product("P-OK", "آزاد", "لپ‌تاپ", "", "Dell", "XPS", {}, "")
        assert code == "P-OK"

        # Post-grace expires hard-lock
        clock_now[0] = datetime.datetime(2026, 5, 20, 12, 0, 0, tzinfo=datetime.timezone.utc)
        res_exp = svc.check_license(force_reload=True)
        assert res_exp.is_valid is False
        assert res_exp.status == ValidationStatus.EXPIRED
    finally:
        win._license_timer.stop()
        win._sync_timer.stop()
        win.close()
        mgr.close()


def test_persian_module_labels_and_configurable_support_phone(tmp_path):
    """Zero raw English keys in active modules; custom & default support phone work without doc leaks."""
    labels = get_active_features_fa(
        {
            "dashboard": True,
            "products": True,
            "batches": True,
            "sales": True,
            "report_sales": True,
            "backup_manage": True,
            "unknown_future_module": True,
        }
    )
    assert len(labels) == 7
    for lbl in labels:
        assert not any("a" <= ch.lower() <= "z" for ch in lbl), f"Raw ASCII leaked: {lbl}"
    assert get_feature_label_fa("unknown_key_123") == "قابلیت تخصصی سامانه"

    # Default fallback check & README/example JSON leak check
    readme_text = Path("README.md").read_text(encoding="utf-8")
    example_text = Path("build_license_config.example.json").read_text(encoding="utf-8")
    assert "09193352435" not in readme_text
    assert "09193352435" not in example_text
    assert "09XXXXXXXXX" in example_text

    # Build shard configurable support_phone override
    priv = ed25519.Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    import base64

    out_mod = tmp_path / "_test_embedded_keys.py"
    res = build_shards(
        output_path=str(out_mod),
        manifest_path="licensing/trusted_keys.json",
        override_key_b64=base64.b64encode(pub_raw).decode("ascii"),
        override_support_phone="09120001122",
    )
    assert res.support_phone == "09120001122"
    src = out_mod.read_text(encoding="utf-8")
    ns = {}
    exec(compile(src, str(out_mod), "exec"), ns)
    assert ns["get_embedded_support_phone"]() == "09120001122"


def test_settings_ui_copy_license_wording_and_dialog_phone(tmp_path, monkeypatch, qapp):
    """Settings dropdowns drop '(پیش‌فرض)', chk_req_pass is inside a dedicated QGroupBox, and UI uses لایسنس."""
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "app_config.json"))
    clock_now = datetime.datetime(2026, 5, 11, 12, 0, 0, tzinfo=datetime.timezone.utc)
    priv, fp, svc = _make_license_env(tmp_path, clock_now)

    mgr = DatabaseManager(str(tmp_path / "ui_copy.db"))
    import main as main_mod

    win = main_mod.MainWindow(mgr, license_service=svc)
    try:
        cal_items = [win.cb_calendar_format.itemText(i) for i in range(win.cb_calendar_format.count())]
        time_items = [win.cb_time_format.itemText(i) for i in range(win.cb_time_format.count())]
        assert cal_items == ["شمسی", "قمری", "میلادی"]
        assert time_items == ["۲۴ ساعته", "۱۲ ساعته (AM / PM)"]
        assert isinstance(win.chk_req_pass.parentWidget(), QGroupBox)

        # MISSING license shows support phone cleanly in LicenseDialog
        dlg = LicenseDialog(svc, parent=win, is_startup_gate=False)
        try:
            assert get_support_phone() in dlg.lbl_status_desc.text()

            # Valid perpetual license retains conceptual نوع اشتراک / اشتراکی زمان‌دار
            sub_bytes = _signed_license_bytes(
                priv, key_id="test-k1", fp=fp, expires_at="2027-01-01"
            )
            svc.import_license_bytes(sub_bytes)
            dlg.refresh_status()
            details_html = dlg.lbl_details.text()
            assert "نوع اشتراک:" in details_html
            assert "اشتراکی زمان‌دار" in details_html
        finally:
            dlg.close()
    finally:
        win._license_timer.stop()
        win._sync_timer.stop()
        win.close()
        mgr.close()


def test_troubleshooter_isolation_backup_protection_and_db_prompt(tmp_path):
    """Troubleshooter has zero Daqiq imports, blocks while running, protects all backups even on DB delete."""
    # 1. Strict decoupling AST check
    forbidden = {"main", "database", "licensing", "utils", "ui", "tools"}
    for py_file in Path("troubleshooter").glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top not in forbidden, f"{py_file} imports {top}"
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                top = node.module.split(".")[0]
                assert top not in forbidden, f"{py_file} imports from {top}"

    exe_dir = tmp_path / "exe_dir"
    local_app = tmp_path / "LocalAppData"
    roaming_app = tmp_path / "RoamingAppData"
    tmp_env = tmp_path / "Temp"
    db_dir = tmp_path / "UserDocs" / "DaqiqDBs"
    custom_bk_dir = tmp_path / "ExternalBackupDrive" / "MyAutoBackups"
    default_bk_dir = db_dir / "Backups"

    for d in (exe_dir, local_app / "Daqiq" / "4.9.8", local_app / "Daqiq" / "logs", roaming_app / "Daqiq", tmp_env / "Daqiq_old", default_bk_dir, custom_bk_dir):
        d.mkdir(parents=True, exist_ok=True)

    active_db = db_dir / "StoreActive.db"
    active_db.write_bytes(b"SQLite format 3\x00" + b"x" * 64)
    manual_bk_in_db_dir = db_dir / "DaqiqBackup_14050101_100000.db"
    manual_bk_in_db_dir.write_bytes(b"MANUAL_BACKUP_KEEP")
    auto_bk_default = default_bk_dir / "StoreActive_backup_14050101_101500.db"
    auto_bk_default.write_bytes(b"DEFAULT_AUTO_BACKUP_KEEP")
    auto_bk_custom = custom_bk_dir / "StoreActive_backup_14050101_103000.db"
    auto_bk_custom.write_bytes(b"CUSTOM_AUTO_BACKUP_KEEP")
    (local_app / "Daqiq" / "4.9.8" / "cache.bin").write_bytes(b"cache")
    (local_app / "Daqiq" / "logs" / "daqiq_crash.log").write_text("log", encoding="utf-8")

    cfg_file = exe_dir / "app_config.json"
    cfg_file.write_text(
        json.dumps(
            {
                "db_path": str(active_db),
                "backup_dir": str(db_dir),
                "auto_backup_dir": str(custom_bk_dir),
                "databases": {str(active_db).lower(): {"auto_backup_dir": str(custom_bk_dir)}},
            }
        ),
        encoding="utf-8",
    )

    # Running Daqiq.exe aborts cleanup safely
    running_plan = discover_troubleshooting_targets(
        executable_dir=exe_dir,
        local_app_data=local_app,
        roaming_app_data=roaming_app,
        temp_dir=tmp_env,
        process_lister=lambda: [99999],
    )
    blocked_res = execute_troubleshooting_reset(
        running_plan, delete_databases=True, process_lister=lambda: [99999]
    )
    assert blocked_res.aborted_reason
    assert cfg_file.is_file()
    assert active_db.is_file()

    # Stopped Daqiq.exe: step 1 keep DBs
    plan = discover_troubleshooting_targets(
        executable_dir=exe_dir,
        local_app_data=local_app,
        roaming_app_data=roaming_app,
        temp_dir=tmp_env,
        process_lister=lambda: [],
    )
    res_keep = execute_troubleshooting_reset(plan, delete_databases=False, process_lister=lambda: [])
    assert not res_keep.aborted_reason
    assert not cfg_file.exists()
    assert not (local_app / "Daqiq" / "4.9.8" / "cache.bin").exists()
    assert active_db.is_file()
    assert manual_bk_in_db_dir.is_file()
    assert auto_bk_default.is_file()
    assert auto_bk_custom.is_file()

    # Step 2 explicit delete_databases=True removes ONLY active DB, NEVER any backup!
    res_del = execute_troubleshooting_reset(plan, delete_databases=True, process_lister=lambda: [])
    assert not res_del.aborted_reason
    assert not active_db.exists()
    assert manual_bk_in_db_dir.read_bytes() == b"MANUAL_BACKUP_KEEP"
    assert auto_bk_default.read_bytes() == b"DEFAULT_AUTO_BACKUP_KEEP"
    assert auto_bk_custom.read_bytes() == b"CUSTOM_AUTO_BACKUP_KEEP"

    # CLI --dry-run runs cleanly headlessly
    proc = subprocess.run(
        [sys.executable, "-m", "troubleshooter", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert "DAQIQ_TROUBLESHOOTER_DRY_RUN_OK" in proc.stdout


def test_v499_version_ci_and_config_alignment():
    """Verify live version consistency and CI dual-exe + Node 24 pipeline alignment."""
    live_ver = Path("VERSION").read_text(encoding="utf-8").strip()
    assert live_ver in ("4.9.9", "4.9.10", "4.10.0")
    assert db_mod.get_live_app_version() == live_ver

    ci_yml = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "actions/checkout@v7" in ci_yml
    assert "actions/setup-python@v7" in ci_yml
    assert "actions/upload-artifact@v7" in ci_yml
    assert "actions/download-artifact@v8" in ci_yml
    assert "DAQIQ_SUPPORT_PHONE" in ci_yml
    assert "Daqiq-Troubleshooter.exe" in ci_yml

    build_py = Path("scripts/build_nuitka.py").read_text(encoding="utf-8")
    assert "--nofollow-import-to=" in build_py and "troubleshooter" in build_py
    assert "DaqiqReset_{PID}" in build_py or "DaqiqTroubleshooter_{PID}" in build_py
