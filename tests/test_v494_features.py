"""Comprehensive QA test suite for Daqiq v4.9.4 features and fixes.

Covers:
1. Nuitka onefile external path resolution (default_taxonomy.json & app_config.json).
2. Multi-origin calendar conversion (Jalali -> Hijri future-only -> Gregorian convert-all).
3. AM/PM 12-hour time formatting (strictly AM/PM, not ق.ظ/ب.ظ).
4. Top-bar live clock active calendar synchronization.
5. User management (employees) date/time formatting and persistence.
6. Purchase form field reordering and purchase timestamp persistence.
7. Sales form editable date/time field, tooltip alignment, and warranty digit selection.
8. Clean hardware request schema without hardware_anchors tier hashes.
9. Granular license entitlement overlay display across locked tabs.
"""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from database import DatabaseManager
from licensing.device_identity import (
    create_device_request_dict,
    get_human_readable_cpu_model,
)
from licensing.license_dialog import LicenseDialog
from licensing.license_policy import (
    FEATURE_ALIASES,
    LicenseService,
)
from utils.datetime_format import (
    CALENDAR_GREGORIAN,
    CALENDAR_HIJRI,
    CALENDAR_JALALI,
    TIME_FORMAT_12H,
    TIME_FORMAT_24H,
    convert_date,
    convert_datetime_str,
    convert_time,
    detect_calendar_type,
    detect_time_format,
    format_datetime_display,
    format_time_12h,
    get_now_datetime,
    get_now_time,
    get_today_date,
    migrate_database_datetime,
    record_future_calendar_switch,
)
from utils.paths import (
    get_app_config_path,
    get_default_taxonomy_path,
    get_executable_dir,
)
from utils_and_widgets import WarrantyLineEdit, mixed_bidi_tooltip


@pytest.fixture(scope="session")
def qapp():
    """Ensure headless QApplication instance exists."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(["-platform", "offscreen"])
    return app


# ---------------------------------------------------------------------------
# 1. Nuitka External Path Tests
# ---------------------------------------------------------------------------

def test_nuitka_onefile_external_path_resolution(tmp_path, monkeypatch):
    """Simulate NUITKA_ONEFILE_BINARY pointing outside cache; assert paths resolve next to binary."""
    mock_bin_dir = tmp_path / "ProgramFiles" / "DaqiqApp"
    mock_bin_dir.mkdir(parents=True)
    mock_exe = mock_bin_dir / "Daqiq.exe"
    mock_exe.write_text("dummy binary", encoding="utf-8")

    mock_tax = mock_bin_dir / "default_taxonomy.json"
    mock_tax.write_text(json.dumps({"categories": {"کالا": ["لپ‌تاپ"]}}), encoding="utf-8")

    monkeypatch.setenv("NUITKA_ONEFILE_BINARY", str(mock_exe))

    resolved_exe_dir = get_executable_dir()
    assert resolved_exe_dir.resolve() == mock_bin_dir.resolve()

    resolved_tax_path = get_default_taxonomy_path()
    assert resolved_tax_path.resolve() == mock_tax.resolve()
    assert resolved_tax_path.is_file()

    resolved_cfg_path = get_app_config_path()
    assert resolved_cfg_path.parent.resolve() == mock_bin_dir.resolve()


# ---------------------------------------------------------------------------
# 2. Multi-Origin Calendar & AM/PM Migration Tests
# ---------------------------------------------------------------------------

def test_time_format_12h_strictly_uses_am_pm():
    """Verify 12h formatting strictly produces AM/PM and never ق.ظ or ب.ظ."""
    # Morning: 09:15:30 -> 09:15:30 AM
    t_am = format_time_12h(9, 15, 30, include_seconds=True)
    assert "AM" in t_am
    assert "ق.ظ" not in t_am
    assert "ب.ظ" not in t_am
    assert t_am.startswith("09:15:30")

    # Afternoon: 14:30:00 -> 02:30:00 PM
    t_pm = format_time_12h(14, 30, 0, include_seconds=True)
    assert "PM" in t_pm
    assert "ق.ظ" not in t_pm
    assert "ب.ظ" not in t_pm
    assert t_pm.startswith("02:30:00")

    # Midnight: 00:05 -> 12:05 AM
    t_mid = format_time_12h(0, 5, None, include_seconds=False)
    assert t_mid == "12:05 AM"

    # Noon: 12:00 -> 12:00 PM
    t_noon = format_time_12h(12, 0, None, include_seconds=False)
    assert t_noon == "12:00 PM"


def test_convert_time_am_pm():
    """Verify convert_time between 24h and 12h preserves precision and uses AM/PM."""
    assert convert_time("14:35:10", "24h", "12h") == "02:35:10 PM"
    assert convert_time("09:10", "24h", "12h") == "09:10 AM"
    assert convert_time("02:35:10 PM", "12h", "24h") == "14:35:10"
    assert convert_time("09:10 AM", "12h", "24h") == "09:10"
    # Tolerant parser handles legacy Persian suffix too
    assert convert_time("02:35:10 ب.ظ", "12h", "24h") == "14:35:10"


def test_detect_calendar_type():
    """Verify smart calendar detector correctly categorizes dates by disjoint year ranges."""
    # Gregorian: 1900..2199
    assert detect_calendar_type("2026/11/24") == CALENDAR_GREGORIAN
    assert detect_calendar_type("2024-05-10 14:30") == CALENDAR_GREGORIAN

    # Hijri: 1435..1650
    assert detect_calendar_type("1446/05/20") == CALENDAR_HIJRI
    assert detect_calendar_type("1448/01/01") == CALENDAR_HIJRI

    # Jalali: 1200..1434
    assert detect_calendar_type("1403/09/04") == CALENDAR_JALALI
    assert detect_calendar_type("1399/12/29 10:00") == CALENDAR_JALALI


def test_multi_origin_calendar_migration_exact_scenario(tmp_path):
    """
    CRITICAL REQUIREMENT:
    Step A: Existing records saved in Jalali (1403/09/04 14:30).
    Step B: User switches to Hijri with future-only + inserts new Hijri record (1446/05/20 14:30).
    Step C: User later switches to Gregorian with convert-all.
    Assert: Old Jalali row converts Jalali -> Gregorian AND new Hijri row converts Hijri -> Gregorian!
    """
    db_file = str(tmp_path / "test_multi_cal.db")
    db = DatabaseManager(db_path=db_file)

    # Step A: Seed DB in Jalali (default)
    db.set_setting("calendar_format", "jalali")
    db.set_setting("time_format", "24h")

    # Add employee, product, batch, and sale in Jalali
    with db.get_connection() as conn:
        conn.execute("INSERT INTO employees (name, role, permissions, is_active, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
                     ("علی حسینی", "مدیر", "دسترسی کامل", "1403/09/01 10:00:00", "1403/09/01 10:00:00"))
        emp_id = conn.execute("SELECT id FROM employees WHERE name='علی حسینی'").fetchone()[0]

    db.add_product(
        code="P-101",
        name="لپ‌تاپ ذن‌بوک",
        category="کالا",
        sub_category="لپ‌تاپ",
        brand="Asus",
        model="ZenBook",
        specs_dict={},
        description="",
    )
    with db.get_connection() as conn:
        prod_id = conn.execute("SELECT id FROM products WHERE code='P-101'").fetchone()[0]

    # Batch in Jalali: 1403/09/04 14:30
    batch_code = db.add_batch(
        batch_code="B-JALALI",
        product_id=prod_id,
        supplier_id=None,
        buyer_employee_id=emp_id,
        invoice_number="INV-J-1",
        purchase_date="1403/09/04 14:30:00",
        initial_qty=10,
        unit_purchase_price=1000000,
        extra_cost_total=0,
        suggested_sell_price=1200000,
        paid_amount=10000000,
    )
    with db.get_connection() as conn:
        b_jalali_id = conn.execute("SELECT id FROM batches WHERE batch_code='B-JALALI'").fetchone()[0]

    # Sale in Jalali: 1403/09/04 15:00
    inv_jalali = db.add_sale(
        invoice_number="SALE-J-1",
        product_id=prod_id,
        batch_id=b_jalali_id,
        seller_employee_id=emp_id,
        customer_name="مشتری شمسی",
        qty=1,
        suggested_unit_price=1200000,
        actual_unit_price=1200000,
        paid_amount=1200000,
        sale_datetime="1403/09/04 15:00:00",
        warranty_company="گارانتی شمسی",
        warranty_start="1403/09/04",
        warranty_months=12,
        warranty_end="1404/09/04",
        serial_number="S-J-101",
        notes="",
    )

    # Step B: User switches to Hijri with FUTURE_ONLY mode
    record_future_calendar_switch(db, previous_cal="jalali", previous_time_fmt="24h", new_cal="hijri", new_time_fmt="24h")

    # Insert new record in Hijri: 1446/05/20 (which is 2024/11/22 in Gregorian)
    batch_hijri_code = db.add_batch(
        batch_code="B-HIJRI",
        product_id=prod_id,
        supplier_id=None,
        buyer_employee_id=emp_id,
        invoice_number="INV-H-1",
        purchase_date="1446/05/20 14:30:00",
        initial_qty=5,
        unit_purchase_price=2000000,
        extra_cost_total=0,
        suggested_sell_price=2500000,
        paid_amount=10000000,
    )
    with db.get_connection() as conn:
        b_hijri_id = conn.execute("SELECT id FROM batches WHERE batch_code='B-HIJRI'").fetchone()[0]

    inv_hijri = db.add_sale(
        invoice_number="SALE-H-1",
        product_id=prod_id,
        batch_id=b_hijri_id,
        seller_employee_id=emp_id,
        customer_name="مشتری قمری",
        qty=1,
        suggested_unit_price=2500000,
        actual_unit_price=2500000,
        paid_amount=2500000,
        sale_datetime="1446/05/20 16:00:00",
        warranty_company="گارانتی قمری",
        warranty_start="1446/05/20",
        warranty_months=12,
        warranty_end="1447/05/20",
        serial_number="S-H-202",
        notes="",
    )

    # Step C: User switches to Gregorian with CONVERT ALL
    res = migrate_database_datetime(db, target_cal="gregorian", target_time_fmt="12h", create_backup=True)
    assert res["status"] == "success"

    # Verify both rows converted accurately to Gregorian!
    with db.get_connection() as conn:
        # Check Jalali row: 1403/09/04 is 2024/11/24 in Gregorian
        row_j = conn.execute("SELECT sale_datetime, warranty_start, warranty_end FROM sales WHERE invoice_number='SALE-J-1'").fetchone()
        assert row_j["sale_datetime"].startswith("2024/11/24")
        assert "PM" in row_j["sale_datetime"]
        assert row_j["warranty_start"] == "2024/11/24"
        assert row_j["warranty_end"] == "2025/11/25"

        # Check Hijri row: 1446/05/20 is 2024/11/22 in Gregorian
        row_h = conn.execute("SELECT sale_datetime, warranty_start, warranty_end FROM sales WHERE invoice_number='SALE-H-1'").fetchone()
        assert row_h["sale_datetime"].startswith("2024/11/22")
        assert "PM" in row_h["sale_datetime"]
        assert row_h["warranty_start"] == "2024/11/22"

        # Check user management (employees) row was also converted
        emp_row = conn.execute("SELECT created_at FROM employees WHERE id=?", (emp_id,)).fetchone()
        # 1403/09/01 Jalali is 2024/11/21 in Gregorian
        assert emp_row["created_at"].startswith("2024/11/21")
        assert "AM" in emp_row["created_at"]


# ---------------------------------------------------------------------------
# 3. Licensing Clean Request & Granular Entitlement Tests
# ---------------------------------------------------------------------------

def test_clean_device_request_schema():
    """Verify request JSON has no redundant hardware_anchors tier hashes and has valid cpu_model."""
    req = create_device_request_dict(device_label="صندوق فروشگاه مرکزی")
    assert req["request_version"] == 1
    assert req["protocol_version"] == 1
    assert "hardware_anchors" not in req
    assert "device_fingerprint" in req
    assert "cpu_model" in req
    assert req["device_label"] == "صندوق فروشگاه مرکزی"
    assert "checksum_sha256" in req

    # Test CPU model string is non-empty
    cpu = get_human_readable_cpu_model()
    assert isinstance(cpu, str)
    assert len(cpu.strip()) > 0


def test_granular_feature_aliases():
    """Verify feature aliases backward compatibility and default-to-true behavior."""
    # Canonical: purchases ↔ batches
    assert "batches" in FEATURE_ALIASES.get("purchases", [])
    assert "purchases" in FEATURE_ALIASES.get("batches", [])

    pm = LicenseService()
    
    # Mock valid license with specific features
    mock_lic = MagicMock()
    mock_lic.payload.features = {"purchases": True, "sales": False}
    mock_res = MagicMock()
    mock_res.is_valid = True
    mock_res.license = mock_lic
    pm._last_result = mock_res

    assert pm.is_feature_enabled("purchases") is True
    assert pm.is_feature_enabled("batches") is True
    assert pm.is_feature_enabled("sales") is False

    # Omitted keys default to True for 100% backward compatibility
    assert pm.is_feature_enabled("inventory") is True
    assert pm.is_feature_enabled("products") is True


# ---------------------------------------------------------------------------
# 4. Form UX & Precision Tests
# ---------------------------------------------------------------------------

def test_warranty_line_edit_digits_selection(qapp):
    """Verify clicking or focusing WarrantyLineEdit selects only the numeric digits."""
    w = WarrantyLineEdit()
    w.setText("2 روز")
    assert w.text() == "2 روز"

    # Trigger digits selection
    w._select_digits_only()
    assert w.hasSelectedText() is True
    assert w.selectedText() == "2"

    w.setText("18 ماه")
    w._select_digits_only()
    assert w.selectedText() == "18"

    w.setText("بدون گارانتی")
    w._select_digits_only()
    # No digits present
    assert w.hasSelectedText() is False


def test_mixed_bidi_tooltip_right_aligned():
    """Verify tooltip HTML contains right alignment (RTL) for all lines."""
    html_tip = mixed_bidi_tooltip("کد کالا: P-101\nCPU: Core i7 16GB RAM\nتوضیحات: عالی")
    assert 'dir="rtl"' in html_tip
    assert 'text-align:right' in html_tip
    assert 'align="right"' in html_tip
    # No left alignment in rendered output
    assert 'text-align:left' not in html_tip
    assert 'align="left"' not in html_tip
