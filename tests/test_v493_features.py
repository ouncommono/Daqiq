"""
Comprehensive QA Automation and Regression Suite for Daqiq v4.9.3.

Covers:
1. Multi-Calendar Conversion Engine (Jalali, Hijri, Gregorian, Leap years, Digits)
2. Time Format Conversion Engine (24h <-> 12h with Persian markers ق.ظ / ب.ظ)
3. Lossless Atomic Database Datetime Migration (Backup safety, table updates, settings persistence)
4. Migration Choice Dialog (3 choices: Migrate All, New Only, Cancel)
5. Partner Export Dynamic Reordering, Persistence & Export Parity
6. Report Export Renamed Button & Live View Refresh
7. Complete Zero 'تجاری' Invariant in UI Layer
8. External Taxonomy Resolution under Nuitka Onefile Environment
"""

import os
import json
import tempfile
import pytest
from unittest.mock import patch, MagicMock

import datetime_format as dtf
from database import DatabaseManager, get_default_taxonomy_path
import exporter
from openpyxl import load_workbook


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ---------------------------------------------------------------------------
# 1. Multi-Calendar Conversion Engine
# ---------------------------------------------------------------------------

def test_calendar_roundtrip_conversions():
    """Verify bidirectional roundtrip date conversions between Jalali, Hijri, and Gregorian."""
    # Jalali to Gregorian
    greg_date = dtf.convert_date("1403/05/20", "jalali", "gregorian")
    assert greg_date == "2024/08/10"

    # Gregorian to Hijri
    hijri_date = dtf.convert_date("2024/08/10", "gregorian", "hijri")
    assert hijri_date == "1446/02/06"

    # Hijri to Jalali
    jalali_date = dtf.convert_date(hijri_date, "hijri", "jalali")
    assert jalali_date == "1403/05/20"


def test_calendar_leap_years():
    """Verify leap year handling in Jalali (1403), Gregorian (2024), and Hijri."""
    # Esfand 30th in leap year 1403
    greg = dtf.convert_date("1403/12/30", "jalali", "gregorian")
    assert greg == "2025/03/20"

    # Leap day in Gregorian 2024-02-29
    jalali = dtf.convert_date("2024/02/29", "gregorian", "jalali")
    assert jalali == "1402/12/10"


def test_persian_and_arabic_digits_normalization():
    """Verify Persian and Arabic digits in date strings are normalized seamlessly."""
    persian_str = "۱۴۰۳/۰۵/۲۰"
    converted = dtf.convert_date(persian_str, "jalali", "gregorian")
    assert converted == "2024/08/10"

    arabic_str = "١٤٠٣/٠٥/٢٠"
    converted_ar = dtf.convert_date(arabic_str, "jalali", "gregorian")
    assert converted_ar == "2024/08/10"


# ---------------------------------------------------------------------------
# 2. Time Format Conversion Engine
# ---------------------------------------------------------------------------

def test_time_conversions_24h_to_12h():
    """Verify 24h to 12h format conversions with AM/PM markers."""
    # Afternoon
    assert dtf.convert_time("14:30:15", "24h", "12h") == "02:30:15 PM"
    # Morning
    assert dtf.convert_time("09:15:00", "24h", "12h") == "09:15:00 AM"
    # Midnight (00:00 -> 12:00 AM)
    assert dtf.convert_time("00:00:00", "24h", "12h") == "12:00:00 AM"
    # Noon (12:00 -> 12:00 PM)
    assert dtf.convert_time("12:00:00", "24h", "12h") == "12:00:00 PM"


def test_time_conversions_12h_to_24h():
    """Verify 12h to 24h format conversions with Persian and English markers."""
    assert dtf.convert_time("02:30:15 ب.ظ", "12h", "24h") == "14:30:15"
    assert dtf.convert_time("09:15:00 ق.ظ", "12h", "24h") == "09:15:00"
    assert dtf.convert_time("12:00:00 ق.ظ", "12h", "24h") == "00:00:00"
    assert dtf.convert_time("12:00:00 ب.ظ", "12h", "24h") == "12:00:00"

    # English PM/AM support
    assert dtf.convert_time("02:30:00 PM", "12h", "24h") == "14:30:00"
    assert dtf.convert_time("09:15:00 AM", "12h", "24h") == "09:15:00"


def test_combined_datetime_conversions():
    """Verify full datetime strings convert date and time simultaneously."""
    dt_str = "1403/05/20 14:30:00"
    conv = dtf.convert_datetime_str(
        dt_str,
        from_cal="jalali",
        from_time_fmt="24h",
        to_cal="gregorian",
        to_time_fmt="12h",
    )
    assert conv == "2024/08/10 02:30:00 PM"

    roundtrip = dtf.convert_datetime_str(
        conv,
        from_cal="gregorian",
        from_time_fmt="12h",
        to_cal="jalali",
        to_time_fmt="24h",
    )
    assert roundtrip == "1403/05/20 14:30:00"


# ---------------------------------------------------------------------------
# 3. Lossless Atomic Database Datetime Migration
# ---------------------------------------------------------------------------

def test_database_datetime_migration_with_backup(tmp_path):
    """Verify migrate_database_datetime converts records across tables and creates a safety backup."""
    db_file = str(tmp_path / "test_migration.db")
    db = DatabaseManager(db_file)

    # Seed data in Jalali / 24h
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO products (code, name, category, sub_category, brand, model, is_active, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
            ("P-1", "Test Product", "قطعات", "رم", "Kingston", "DDR4", "1403/05/20 10:00:00", "1403/05/20 10:00:00"),
        )
        p_id = conn.execute("SELECT id FROM products WHERE code='P-1'").fetchone()[0]

        conn.execute(
            "INSERT INTO batches (batch_code, product_id, purchase_date, initial_qty, remaining_qty, unit_purchase_price, unit_cost_price, suggested_sell_price, created_at, updated_at) "
            "VALUES (?, ?, ?, 10, 10, 100000, 100000, 150000, ?, ?)",
            ("B-1", p_id, "1403/05/20", "1403/05/20 10:15:00", "1403/05/20 10:15:00"),
        )
        b_id = conn.execute("SELECT id FROM batches WHERE batch_code='B-1'").fetchone()[0]

        conn.execute(
            "INSERT INTO sales (invoice_number, product_id, batch_id, qty, suggested_unit_price, actual_unit_price, unit_cost_price, total_amount, paid_amount, settlement_status, sale_datetime, warranty_start, warranty_end, created_at, updated_at) "
            "VALUES (?, ?, ?, 1, 150000, 150000, 100000, 150000, 150000, 'تسویه کامل', ?, ?, ?, ?, ?)",
            ("INV-101", p_id, b_id, "1403/05/20 14:30:00", "1403/05/20", "1404/05/20", "1403/05/20 14:30:00", "1403/05/20 14:30:00"),
        )

        conn.execute(
            "INSERT INTO payments (ref_type, ref_id, amount, payment_date, created_at, updated_at) "
            "VALUES (?, ?, 150000, ?, ?, ?)",
            ("sale", 1, "1403/05/20", "1403/05/20 14:35:00", "1403/05/20 14:35:00"),
        )

        conn.execute(
            "INSERT INTO audit_logs (action_time, action_type, details, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("1403/05/20 14:40:00", "LOGIN", "Test Login", "1403/05/20 14:40:00", "1403/05/20 14:40:00"),
        )

    # Verify initial settings
    assert db.get_setting("calendar_format", "jalali") == "jalali"
    assert db.get_setting("time_format", "24h") == "24h"

    # Migrate to Gregorian / 12h
    res = dtf.migrate_database_datetime(db, target_cal="gregorian", target_time_fmt="12h", create_backup=True)
    assert res["status"] == "success"
    assert res["total_updated"] > 0
    assert res["backup_path"] is not None
    assert os.path.isfile(res["backup_path"])

    # Verify settings updated
    assert db.get_setting("calendar_format") == "gregorian"
    assert db.get_setting("time_format") == "12h"

    # Verify table fields converted
    with db.get_connection() as conn:
        b_row = conn.execute("SELECT purchase_date, created_at FROM batches WHERE batch_code='B-1'").fetchone()
        assert b_row["purchase_date"] == "2024/08/10"
        assert b_row["created_at"] == "2024/08/10 10:15:00 AM"

        s_row = conn.execute("SELECT sale_datetime, warranty_start, warranty_end FROM sales WHERE invoice_number='INV-101'").fetchone()
        assert s_row["sale_datetime"] == "2024/08/10 02:30:00 PM"
        assert s_row["warranty_start"] == "2024/08/10"
        assert s_row["warranty_end"] == "2025/08/11"

        p_row = conn.execute("SELECT payment_date FROM payments WHERE id=1").fetchone()
        assert p_row["payment_date"] == "2024/08/10"

        a_row = conn.execute("SELECT action_time FROM audit_logs WHERE id=1").fetchone()
        assert a_row["action_time"] == "2024/08/10 02:40:00 PM"

    # Migrate back to Jalali / 24h (lossless roundtrip)
    res_back = dtf.migrate_database_datetime(db, target_cal="jalali", target_time_fmt="24h", create_backup=False)
    assert res_back["status"] == "success"
    assert db.get_setting("calendar_format") == "jalali"
    assert db.get_setting("time_format") == "24h"

    with db.get_connection() as conn:
        b_back = conn.execute("SELECT purchase_date FROM batches WHERE batch_code='B-1'").fetchone()
        assert b_back["purchase_date"] == "1403/05/20"


# ---------------------------------------------------------------------------
# 4. Migration Dialog Choices
# ---------------------------------------------------------------------------

def test_migration_dialog_choices(qapp):
    """Verify DatetimeMigrationChoiceDialog returns correct choice codes for all 3 buttons."""
    from main import DatetimeMigrationChoiceDialog

    # Button 1: Migrate all
    dlg1 = DatetimeMigrationChoiceDialog("jalali", "gregorian", "24h", "12h")
    dlg1._choose_all()
    assert dlg1.choice == DatetimeMigrationChoiceDialog.MIGRATE_ALL

    # Button 2: New only
    dlg2 = DatetimeMigrationChoiceDialog("jalali", "gregorian", "24h", "12h")
    dlg2._choose_new()
    assert dlg2.choice == DatetimeMigrationChoiceDialog.APPLY_NEW_ONLY

    # Button 3: Cancel
    dlg3 = DatetimeMigrationChoiceDialog("jalali", "gregorian", "24h", "12h")
    dlg3._choose_cancel()
    assert dlg3.choice == DatetimeMigrationChoiceDialog.CANCEL


# ---------------------------------------------------------------------------
# 5. Partner Export Dynamic Reordering & Persistence
# ---------------------------------------------------------------------------

def test_partner_export_reordering_and_persistence(qapp, tmp_path):
    """Verify partner export list widget supports reordering, staging, and Excel output order."""
    from main import MainWindow
    db_file = str(tmp_path / "partner_export.db")
    db = DatabaseManager(db_file)
    win = MainWindow(db)

    # 1. Check list widget exists and has 32 columns
    assert hasattr(win, "lst_inventory_export_columns")
    assert win.lst_inventory_export_columns.count() == len(exporter.INVENTORY_EXPORT_AVAILABLE_COLUMNS)

    # 2. Check compatibility proxy
    assert "code" in win.inventory_export_column_checks
    assert win.inventory_export_column_checks["code"].isChecked() is True

    # 3. Reorder: move second item to top
    from PySide6.QtCore import Qt
    item1 = win.lst_inventory_export_columns.item(1)
    key1 = item1.data(Qt.UserRole)
    win.lst_inventory_export_columns.setCurrentRow(1)
    win._move_inventory_export_col_up()
    assert win.lst_inventory_export_columns.item(0).data(Qt.UserRole) == key1

    # 4. Verify _get_selected_inventory_export_columns reflects new order
    ordered = win._get_selected_inventory_export_columns()
    assert ordered[0] == key1

    # 5. Test Excel export output honors exact order
    out_xlsx = str(tmp_path / "partner_out.xlsx")
    exporter.export_safe_inventory_excel(db, out_xlsx, included_columns=ordered[:3])

    wb = load_workbook(out_xlsx, read_only=True)
    ws = wb["موجودی همکار"]
    headers = [c.value for c in ws[2]]
    col_map = dict(exporter.INVENTORY_EXPORT_AVAILABLE_COLUMNS)
    expected_headers = [col_map[k] for k in ordered[:3]]
    assert headers == expected_headers
    wb.close()
    win.close()


# ---------------------------------------------------------------------------
# 6. Report Export Renamed Button & Live Refresh
# ---------------------------------------------------------------------------

def test_report_export_renamed_button_and_live_refresh(qapp, tmp_path):
    """Verify button is renamed to 'ویرایش لیست گزارش' and triggers live report refresh."""
    from main import MainWindow
    db_file = str(tmp_path / "report_refresh.db")
    db = DatabaseManager(db_file)
    win = MainWindow(db)

    # Verify button rename in page
    btn_found = False
    for btn in win.findChildren(type(win.btn_save_settings)):
        if "ویرایش لیست گزارش" in btn.text():
            btn_found = True
            break
    assert btn_found, "Button 'ویرایش لیست گزارش' not found in MainWindow"

    # Verify live report update is triggered on save without blocking modal
    with patch.object(win, "_update_report_live") as mock_update, \
         patch("PySide6.QtWidgets.QMessageBox.information"):
        win.cb_report_export_type.setCurrentText("تعریف گزارش جدید")
        # Switch to an actual report
        first_rep = list(exporter.REPORT_AVAILABLE_COLUMNS.keys())[0] if hasattr(exporter, "REPORT_AVAILABLE_COLUMNS") else "۱. گزارش کامل تمام فروش‌ها"
        win.cb_report_export_type.setCurrentText(first_rep)
        win._save_report_export_config_ui()
        mock_update.assert_called()

    win.close()


# ---------------------------------------------------------------------------
# 7. Complete Zero 'تجاری' Invariant in UI Layer
# ---------------------------------------------------------------------------

def test_zero_tejari_in_ui_layer():
    """Verify zero occurrences of the Persian word 'تجاری' in the entire UI layer."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    target_files = [
        os.path.join(repo_root, "main.py"),
        os.path.join(repo_root, "utils_and_widgets.py"),
        os.path.join(repo_root, "licensing", "license_dialog.py"),
        os.path.join(repo_root, "licensing", "device_identity.py"),
    ]

    prohibited_word = "تجاری"
    violations = []

    for filepath in target_files:
        if not os.path.isfile(filepath):
            continue
        with open(filepath, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                if prohibited_word in line:
                    violations.append(f"{os.path.basename(filepath)}:{line_no} -> {line.strip()}")

    assert not violations, f"Found '{prohibited_word}' in UI files:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# 8. External Taxonomy Resolution under Nuitka Onefile Environment
# ---------------------------------------------------------------------------

def test_external_taxonomy_resolution(tmp_path):
    """Verify get_default_taxonomy_path resolves alongside executable even in simulated Nuitka onefile mode."""
    mock_bin_dir = tmp_path / "mock_install"
    mock_bin_dir.mkdir()
    mock_exe = mock_bin_dir / "Daqiq.exe"
    mock_exe.touch()
    mock_tax = mock_bin_dir / "default_taxonomy.json"
    mock_tax.touch()

    with patch.dict(os.environ, {"NUITKA_ONEFILE_BINARY": str(mock_exe)}):
        resolved = get_default_taxonomy_path()
        assert os.path.abspath(resolved) == os.path.abspath(str(mock_tax))
