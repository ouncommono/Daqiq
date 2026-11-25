"""Zero-Qt pure Win32 / CLI UI for Daqiq-Troubleshooter.exe.

Uses ONLY Python standard library + native Win32 ``user32.MessageBoxW`` (with
``MB_RTLREADING | MB_RIGHT``) and optional ``comctl32.TaskDialogIndirect``.
Strictly ZERO imports from Qt (PySide6/PyQt), tkinter, main, database, licensing, utils, or ui.
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import tempfile
from pathlib import Path
from typing import Optional

from .core import (
    TroubleshootingPlan,
    discover_troubleshooting_targets,
    execute_troubleshooting_reset,
    find_running_daqiq_pids,
    terminate_running_daqiq,
)

# Win32 MessageBox flags
_MB_OK = 0x00000000
_MB_YESNO = 0x00000004
_MB_YESNOCANCEL = 0x00000003
_MB_ICONWARNING = 0x00000030
_MB_ICONQUESTION = 0x00000020
_MB_ICONINFORMATION = 0x00000040
_MB_DEFBUTTON1 = 0x00000000
_MB_DEFBUTTON2 = 0x00000100
_MB_SETFOREGROUND = 0x00010000
_MB_TOPMOST = 0x00040000
_MB_RIGHT = 0x00080000
_MB_RTLREADING = 0x00100000

_IDYES = 6
_IDNO = 7
_IDCANCEL = 2

_RTL_FLAGS = _MB_RIGHT | _MB_RTLREADING | _MB_SETFOREGROUND | _MB_TOPMOST


def _win32_messagebox(title: str, text: str, flags: int) -> int:
    """Display native Windows RTL Persian dialog cleanly with zero Qt dependencies."""
    if sys.platform != "win32" or not hasattr(ctypes, "windll"):
        print(f"[{title}]\n{text}")
        return _IDCANCEL
    user32 = ctypes.windll.user32
    return int(user32.MessageBoxW(0, str(text), str(title), int(flags) | _RTL_FLAGS))


def run_interactive_native_ui() -> int:
    """Execute the complete native Win32 RTL Persian wizard for Daqiq-Troubleshooter."""
    plan = discover_troubleshooting_targets()

    if plan.running_pids:
        pids_str = ", ".join(str(p) for p in plan.running_pids)
        ans = _win32_messagebox(
            "بستن برنامه دقیق پیش از بازنشانی",
            (
                f"نرم‌افزار حسابداری دقیق در حال اجرا است (شناسه پردازش: {pids_str}).\n\n"
                "برای جلوگیری از آسیب به فایل‌ها، پیش از بازنشانی باید برنامه دقیق بسته شود.\n"
                "آیا برنامه دقیق به‌صورت خودکار بسته شود؟\n\n"
                "• بله: بستن دقیق و ادامه عیب‌یابی\n"
                "• خیر: انصراف و خروج"
            ),
            _MB_YESNO | _MB_ICONWARNING | _MB_DEFBUTTON1,
        )
        if ans != _IDYES:
            return 0
        remaining = terminate_running_daqiq()
        if remaining:
            _win32_messagebox(
                "خطا در بستن برنامه دقیق",
                "بستن خودکار برخی پردازش‌های دقیق ممکن نشد.\nلطفاً نرم‌افزار دقیق را به‌صورت دستی ببندید و دوباره تلاش کنید.",
                _MB_OK | _MB_ICONWARNING,
            )
            return 1
        plan = discover_troubleshooting_targets()

    summary_lines = [
        "ابزار مستقل عیب‌یابی و بازنشانی امن دقیق (بدون وابستگی به Qt)",
        "",
        f"• فایل‌های پیکربندی شناسایی‌شده: {len(plan.config_files)}",
        f"• پوشه/فایل‌های کش و گزارش خطا: {len(plan.cache_paths)}",
        f"• پوشه‌های موقت اجرا: {len(plan.runtime_paths)}",
        f"• فایل‌های پایگاه داده فعال یافت‌شده: {len(plan.database_files)}",
        "",
        f"🛡️ حفاظت قطعی از پشتیبان‌ها: {len(plan.protected_backup_dirs)} پوشه پشتیبان و "
        f"{len(plan.protected_backup_files)} فایل پشتیبان (دستی و خودکار، مسیر پیش‌فرض و سفارشی) "
        "به‌طور کامل حفظ می‌شوند و به هیچ عنوان حذف نخواهند شد.",
        "",
        "آیا مایل به شروع پاک‌سازی کش، پوشه‌های موقت و پیکربندی آسیب‌دیده هستید؟",
    ]
    proceed = _win32_messagebox(
        "عیب‌یابی و بازنشانی امن دقیق",
        "\n".join(summary_lines),
        _MB_YESNO | _MB_ICONQUESTION | _MB_DEFBUTTON1,
    )
    if proceed != _IDYES:
        return 0

    delete_dbs = False
    if plan.database_files:
        db_choice = _win32_messagebox(
            "وضعیت فایل‌های پایگاه داده",
            (
                f"تعداد {len(plan.database_files)} فایل پایگاه داده فعال شناسایی شد.\n\n"
                "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:\n"
                "• بله: نگهداری فایل‌های پایگاه داده (توصیه‌شده)\n"
                "• خیر: حذف فایل‌های پایگاه داده فعال\n"
                "• انصراف: توقف کامل عملیات\n\n"
                "(توجه: پشتیبان‌های دستی و خودکار در هر دو حالت کاملاً حفظ می‌شوند.)"
            ),
            _MB_YESNOCANCEL | _MB_ICONQUESTION | _MB_DEFBUTTON1,
        )
        if db_choice == _IDCANCEL:
            return 0
        if db_choice == _IDNO:
            confirm_del = _win32_messagebox(
                "تأیید نهایی حذف پایگاه داده",
                (
                    "آیا مطمئن هستید که فایل‌های فعال پایگاه داده حذف شوند؟\n"
                    "پشتیبان‌های دستی و خودکار در مسیر پیش‌فرض و مسیر سفارشی دست‌نخورده باقی می‌مانند."
                ),
                _MB_YESNO | _MB_ICONWARNING | _MB_DEFBUTTON2,
            )
            if confirm_del != _IDYES:
                return 0
            delete_dbs = True

    result = execute_troubleshooting_reset(plan, delete_databases=delete_dbs)
    if result.aborted_reason:
        _win32_messagebox("عملیات متوقف شد", result.aborted_reason, _MB_OK | _MB_ICONWARNING)
        return 1

    done_lines = [
        "بازنشانی با موفقیت کامل انجام شد:",
        f"• پیکربندی‌های پاک‌شده: {len(result.removed_configs)}",
        f"• کش‌های پاک‌شده: {len(result.removed_caches)}",
        f"• پوشه‌های موقت پاک‌شده: {len(result.removed_runtime)}",
        f"• پایگاه‌های داده حذف‌شده: {len(result.removed_databases)}",
        f"• پشتیبان‌های محافظت‌شده (بدون تغییر): {len(result.preserved_backups)}",
    ]
    if result.warnings:
        done_lines.extend(["", "هشدارها:", *result.warnings])

    _win32_messagebox(
        "پایان پاک‌سازی و بازنشانی دقیق",
        "\n".join(done_lines),
        _MB_OK | _MB_ICONINFORMATION,
    )
    return 0


def launch_gui() -> int:
    """Entry alias launching the zero-Qt native Win32 troubleshooting wizard."""
    return run_interactive_native_ui()


def run_self_test() -> int:
    """Headless automated self-test proving zero-Qt reset logic and backup preservation."""
    with tempfile.TemporaryDirectory(prefix="daqiq_ts_selftest_") as tmp_str:
        root = Path(tmp_str)
        exe_dir = root / "exe"
        local_app = root / "local"
        roaming_app = root / "roaming"
        tmp_dir = root / "tmp"
        db_dir = root / "docs" / "DaqiqDBs"
        custom_bk = root / "custom_bk"
        default_bk = db_dir / "Backups"
        for d in (exe_dir, local_app / "Daqiq", roaming_app / "Daqiq", tmp_dir, default_bk, custom_bk):
            d.mkdir(parents=True, exist_ok=True)
        active_db = db_dir / "store.db"
        active_db.write_bytes(b"SQLite format 3\x00test")
        bk_file = default_bk / "store_backup_14050101_000000.db"
        bk_file.write_bytes(b"BACKUP_SAFE")
        bk_custom = custom_bk / "store_backup_14050101_010000.db"
        bk_custom.write_bytes(b"CUSTOM_BACKUP_SAFE")
        (exe_dir / "app_config.json").write_text(
            f'{{"db_path": "{active_db.as_posix()}", "auto_backup_dir": "{custom_bk.as_posix()}"}}',
            encoding="utf-8",
        )
        plan = discover_troubleshooting_targets(
            executable_dir=exe_dir,
            local_app_data=local_app,
            roaming_app_data=roaming_app,
            temp_dir=tmp_dir,
            process_lister=lambda: [],
        )
        res = execute_troubleshooting_reset(plan, delete_databases=True, process_lister=lambda: [])
        assert not res.aborted_reason, res.aborted_reason
        assert not (exe_dir / "app_config.json").exists()
        assert not active_db.exists()
        assert bk_file.read_bytes() == b"BACKUP_SAFE"
        assert bk_custom.read_bytes() == b"CUSTOM_BACKUP_SAFE"

    # Verify native MessageBoxW symbol resolves on Windows cleanly (without showing a dialog)
    if sys.platform == "win32" and hasattr(ctypes, "windll"):
        assert callable(getattr(ctypes.windll.user32, "MessageBoxW", None))

    # Assert zero Qt/GUI modules loaded in this process
    for forbidden_mod in ("PySide6", "PyQt5", "PyQt6", "shiboken6", "tkinter"):
        assert forbidden_mod not in sys.modules, f"Forbidden GUI module loaded: {forbidden_mod}"

    print("DAQIQ_TROUBLESHOOTER_SELF_TEST_OK")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="Daqiq-Troubleshooter",
        description="Zero-Qt standalone cache/config troubleshooting and safe reset tool for Daqiq.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan paths cleanly and print reset plan without modifying any files.",
    )
    parser.add_argument(
        "--delete-databases",
        action="store_true",
        help="Include active database deletion in --dry-run preview (never deletes backups).",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run non-interactive internal reset & zero-Qt verification test.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if args.dry_run:
        plan = discover_troubleshooting_targets()
        res = execute_troubleshooting_reset(
            plan,
            delete_databases=bool(args.delete_databases),
            dry_run=True,
        )
        print("DAQIQ_TROUBLESHOOTER_DRY_RUN_OK")
        print(f"RUNNING_DAQIQ_PIDS={plan.running_pids}")
        print(f"CONFIGS_TO_CLEAR={len(res.removed_configs)}")
        print(f"CACHES_TO_CLEAR={len(res.removed_caches)}")
        print(f"RUNTIME_TO_CLEAR={len(res.removed_runtime)}")
        print(f"PROTECTED_BACKUP_DIRS={len(plan.protected_backup_dirs)}")
        print(f"PROTECTED_BACKUP_FILES={len(plan.protected_backup_files)}")
        print(f"DATABASE_FILES={len(plan.database_files)}")
        return 0

    return run_interactive_native_ui()
