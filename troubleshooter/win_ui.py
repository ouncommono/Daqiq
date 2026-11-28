"""Zero-Qt pure Win32 / CLI UI for Daqiq-Troubleshooter.exe (v5.0.1).

Uses ONLY Python standard library + native Win32 APIs (``user32.CreateWindowExW`` with
``WS_EX_LAYOUTRTL``, GDI typography, and 100% Persian horizontally-centered bottom buttons).
Strictly ZERO imports from Qt (PySide6/PyQt), tkinter, main, database, licensing, utils, or ui.
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from .core import (
    TroubleshootingPlan,
    discover_troubleshooting_targets,
    execute_troubleshooting_reset,
    find_running_daqiq_pids,
    terminate_running_daqiq,
)

# Canonical Persian button labels (ZERO English OS button text)
BTN_AUTO_CLOSE = "بستن خودکار و ادامه"
BTN_RECHECK = "بررسی مجدد"
BTN_START_RESET = "شروع پاک‌سازی امن"
BTN_KEEP_DBS = "نگهداری پایگاه‌های داده (توصیه‌شده)"
BTN_DELETE_DBS = "حذف پایگاه‌های داده فعال"
BTN_CONFIRM_DELETE_DBS = "تأیید حذف پایگاه‌های داده"
BTN_CANCEL = "انصراف"
BTN_CLOSE = "بستن"
BTN_OK = "تأیید و بستن"


def compute_centered_button_rects(
    client_width: int,
    client_height: int,
    button_labels: Sequence[str],
    *,
    button_height: int = 34,
    gap: int = 12,
    bottom_margin: int = 16,
) -> List[Dict[str, int]]:
    """Compute horizontally centered Win32 bottom button geometry in RTL coordinates."""
    labels = [str(lbl or "").strip() for lbl in (button_labels or [])]
    if not labels:
        return []
    widths = [max(108, min(250, len(lbl) * 8 + 34)) for lbl in labels]
    total_w = sum(widths) + gap * max(0, len(widths) - 1)
    if total_w > client_width - 24 and len(widths) > 0:
        scale = max(60, client_width - 24 - gap * max(0, len(widths) - 1)) / max(1, sum(widths))
        widths = [max(72, int(w * scale)) for w in widths]
        total_w = sum(widths) + gap * max(0, len(widths) - 1)

    x_cursor = max(12, (client_width - total_w) // 2)
    y_pos = max(12, client_height - bottom_margin - button_height)
    rects: List[Dict[str, int]] = []
    for idx, (lbl, w) in enumerate(zip(labels, widths)):
        rects.append({
            "index": idx,
            "label": lbl,
            "x": int(x_cursor),
            "y": int(y_pos),
            "w": int(w),
            "h": int(button_height),
        })
        x_cursor += w + gap
    return rects


def show_native_persian_dialog(
    title: str,
    body_text: str,
    buttons: Sequence[Tuple[str, str]],
    *,
    width: int = 560,
    min_height: int = 240,
) -> str:
    """Render a native pure-Win32 RTL dialog with 100% Persian centered bottom buttons."""
    if sys.platform != "win32" or not hasattr(ctypes, "windll"):
        print(f"[{title}]\n{body_text}")
        return buttons[-1][0] if buttons else "cancel"

    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    kernel32 = ctypes.windll.kernel32

    WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HICON),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", wintypes.HICON),
        ]

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt", wintypes.POINT),
        ]

    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    user32.RegisterClassExW.restype = wintypes.ATOM
    user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    user32.UnregisterClassW.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
    user32.DispatchMessageW.restype = ctypes.c_ssize_t
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostQuitMessage.restype = None
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user32.LoadCursorW.restype = wintypes.HICON
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
    gdi32.CreateFontW.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR,
    ]
    gdi32.CreateFontW.restype = wintypes.HFONT
    gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
    gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.SetBkMode.restype = ctypes.c_int
    gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
    gdi32.SetTextColor.restype = wintypes.COLORREF

    WS_EX_LAYOUTRTL = 0x00400000
    WS_EX_TOPMOST = 0x00000008
    WS_OVERLAPPED = 0x00000000
    WS_CAPTION = 0x00C00000
    WS_SYSMENU = 0x00080000
    WS_CHILD = 0x40000000
    WS_VISIBLE = 0x10000000
    WS_TABSTOP = 0x00010000
    SS_LEFT = 0x00000000
    BS_PUSHBUTTON = 0x00000000
    BS_DEFPUSHBUTTON = 0x00000001
    WM_CREATE = 0x0001
    WM_DESTROY = 0x0002
    WM_CLOSE = 0x0010
    WM_COMMAND = 0x0111
    WM_KEYDOWN = 0x0100
    WM_SETFONT = 0x0030
    WM_CTLCOLORSTATIC = 0x0138
    VK_RETURN = 0x0D
    VK_ESCAPE = 0x1B
    TRANSPARENT = 1
    IDC_ARROW = ctypes.c_void_p(32512)

    line_cnt = sum(max(1, (len(line) // 62) + 1) for line in body_text.splitlines())
    win_h = max(min_height, min(580, 118 + line_cnt * 22))
    btn_labels = [lbl for _key, lbl in buttons]
    total_btn_needed = sum(max(108, min(250, len(lbl) * 8 + 34)) for lbl in btn_labels) + 12 * max(0, len(btn_labels) - 1) + 48
    win_w = max(width, min(760, total_btn_needed))

    screen_w = int(user32.GetSystemMetrics(0) or 1280)
    screen_h = int(user32.GetSystemMetrics(1) or 720)
    pos_x = max(20, (screen_w - win_w) // 2)
    pos_y = max(20, (screen_h - win_h) // 2)

    state = {"result": buttons[-1][0] if buttons else "cancel"}
    bg_brush = gdi32.CreateSolidBrush(0x00FAF8F8)  # Clean warm light surface
    h_font = gdi32.CreateFontW(-14, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
    h_font_bold = gdi32.CreateFontW(-14, 0, 0, 0, 700, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
    hinst = kernel32.GetModuleHandleW(None)
    cls_name = f"DaqiqNativeTSDlg_{id(state)}"

    def _wnd_proc(hwnd, msg, wparam, lparam):
        if msg == WM_COMMAND:
            ctrl_id = int(wparam) & 0xFFFF
            idx = ctrl_id - 1000
            if 0 <= idx < len(buttons):
                state["result"] = buttons[idx][0]
                user32.DestroyWindow(hwnd)
                return 0
        elif msg == WM_KEYDOWN:
            if int(wparam) == VK_RETURN and buttons:
                state["result"] = buttons[0][0]
                user32.DestroyWindow(hwnd)
                return 0
            if int(wparam) == VK_ESCAPE and buttons:
                state["result"] = buttons[-1][0]
                user32.DestroyWindow(hwnd)
                return 0
        elif msg == WM_CTLCOLORSTATIC:
            gdi32.SetBkMode(wintypes.HDC(wparam), TRANSPARENT)
            gdi32.SetTextColor(wintypes.HDC(wparam), 0x002A170F)
            return bg_brush
        elif msg == WM_CLOSE:
            if buttons:
                state["result"] = buttons[-1][0]
            user32.DestroyWindow(hwnd)
            return 0
        elif msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    wnd_proc_cb = WNDPROC(_wnd_proc)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = wnd_proc_cb
    wc.hInstance = hinst
    wc.hCursor = user32.LoadCursorW(None, IDC_ARROW)
    wc.hbrBackground = bg_brush
    wc.lpszClassName = cls_name

    atom = user32.RegisterClassExW(ctypes.byref(wc))
    if not atom:
        gdi32.DeleteObject(bg_brush)
        gdi32.DeleteObject(h_font)
        gdi32.DeleteObject(h_font_bold)
        return state["result"]

    hwnd = None
    try:
        hwnd = user32.CreateWindowExW(
            WS_EX_LAYOUTRTL | WS_EX_TOPMOST,
            cls_name,
            str(title),
            WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
            pos_x, pos_y, win_w, win_h,
            None, None, hinst, None,
        )
        if not hwnd:
            return state["result"]

        rc = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rc))
        cw = max(320, int(rc.right - rc.left))
        ch = max(180, int(rc.bottom - rc.top))

        btn_rects = compute_centered_button_rects(cw, ch, btn_labels, button_height=34, gap=12, bottom_margin=16)
        lbl_hwnd = user32.CreateWindowExW(
            0, "STATIC", str(body_text).replace("\n", "\r\n"),
            WS_CHILD | WS_VISIBLE | SS_LEFT,
            18, 18, max(200, cw - 36), max(80, ch - 76),
            hwnd, wintypes.HMENU(500), hinst, None,
        )
        if lbl_hwnd and h_font:
            user32.SendMessageW(lbl_hwnd, WM_SETFONT, wintypes.WPARAM(h_font), 1)

        for spec in btn_rects:
            idx = spec["index"]
            b_style = WS_CHILD | WS_VISIBLE | WS_TABSTOP | (BS_DEFPUSHBUTTON if idx == 0 else BS_PUSHBUTTON)
            b_hwnd = user32.CreateWindowExW(
                0, "BUTTON", spec["label"],
                b_style,
                spec["x"], spec["y"], spec["w"], spec["h"],
                hwnd, wintypes.HMENU(1000 + idx), hinst, None,
            )
            if b_hwnd and h_font_bold:
                user32.SendMessageW(b_hwnd, WM_SETFONT, wintypes.WPARAM(h_font_bold), 1)

        msg_struct = MSG()
        while user32.GetMessageW(ctypes.byref(msg_struct), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg_struct))
            user32.DispatchMessageW(ctypes.byref(msg_struct))
    finally:
        user32.UnregisterClassW(cls_name, hinst)
        gdi32.DeleteObject(bg_brush)
        gdi32.DeleteObject(h_font)
        gdi32.DeleteObject(h_font_bold)

    return state["result"]


def run_interactive_native_ui() -> int:
    """Execute the complete native Win32 RTL Persian wizard for Daqiq-Troubleshooter."""
    plan = discover_troubleshooting_targets()

    while plan.running_pids:
        pids_str = ", ".join(str(p) for p in plan.running_pids)
        choice = show_native_persian_dialog(
            "بستن برنامه دقیق پیش از بازنشانی",
            (
                f"نرم‌افزار حسابداری دقیق در حال اجرا است (شناسه پردازش: {pids_str}).\n\n"
                "برای جلوگیری از آسیب به فایل‌ها، پیش از بازنشانی باید برنامه دقیق بسته شود.\n"
                "می‌توانید برنامه را به‌صورت خودکار ببندید یا پس از بستن دستی، گزینه «بررسی مجدد» را بزنید."
            ),
            buttons=[
                ("auto_close", BTN_AUTO_CLOSE),
                ("recheck", BTN_RECHECK),
                ("cancel", BTN_CANCEL),
            ],
        )
        if choice == "cancel":
            return 0
        if choice == "auto_close":
            remaining = terminate_running_daqiq()
            if remaining:
                show_native_persian_dialog(
                    "خطا در بستن برنامه دقیق",
                    "بستن خودکار برخی پردازش‌های دقیق ممکن نشد.\nلطفاً نرم‌افزار دقیق را به‌صورت دستی ببندید و دوباره تلاش کنید.",
                    buttons=[("close", BTN_CLOSE)],
                )
                return 1
        plan = discover_troubleshooting_targets()

    summary_lines = [
        "ابزار مستقل عیب‌یابی و بازنشانی کامل دقیق (بدون وابستگی به Qt)",
        "",
        f"• فایل‌های پیکربندی شناسایی‌شده: {len(plan.config_files)}",
        f"• پوشه/فایل‌های کش و گزارش خطا: {len(plan.cache_paths)}",
        f"• پوشه‌های موقت اجرا: {len(plan.runtime_paths)}",
        f"• فایل‌ها و لنگرهای لایسنس برای بازنشانی کامل: {len(plan.license_paths)}",
        f"• فایل‌های پایگاه داده فعال یافت‌شده: {len(plan.database_files)}",
        "",
        f"• حفاظت کامل از پشتیبان‌ها: {len(plan.protected_backup_dirs)} پوشه پشتیبان و "
        f"{len(plan.protected_backup_files)} فایل پشتیبان (دستی و خودکار، مسیر پیش‌فرض و سفارشی) "
        "به‌طور کامل حفظ می‌شوند و به هیچ عنوان حذف نخواهند شد.",
        "",
        "آیا مایل به شروع بازنشانی کامل برنامه (پاک‌سازی پیکربندی، کش و لایسنس) هستید؟",
    ]
    proceed = show_native_persian_dialog(
        "عیب‌یابی و بازنشانی امن دقیق",
        "\n".join(summary_lines),
        buttons=[("proceed", BTN_START_RESET), ("cancel", BTN_CANCEL)],
    )
    if proceed != "proceed":
        return 0

    delete_dbs = False
    if plan.database_files:
        db_choice = show_native_persian_dialog(
            "وضعیت فایل‌های پایگاه داده",
            (
                f"تعداد {len(plan.database_files)} فایل پایگاه داده فعال شناسایی شد.\n\n"
                "لطفاً وضعیت فایل‌های پایگاه داده فعال را مشخص کنید.\n"
                "(توجه: تمامی پشتیبان‌های دستی و خودکار در هر دو حالت کاملاً حفظ می‌شوند.)"
            ),
            buttons=[
                ("keep", BTN_KEEP_DBS),
                ("delete", BTN_DELETE_DBS),
                ("cancel", BTN_CANCEL),
            ],
        )
        if db_choice == "cancel":
            return 0
        if db_choice == "delete":
            confirm_del = show_native_persian_dialog(
                "تأیید نهایی حذف پایگاه داده",
                (
                    "آیا مطمئن هستید که فایل‌های فعال پایگاه داده حذف شوند؟\n"
                    "پشتیبان‌های دستی و خودکار در مسیر پیش‌فرض و مسیر سفارشی دست‌نخورده باقی می‌مانند."
                ),
                buttons=[
                    ("cancel", BTN_CANCEL),
                    ("confirm_delete", BTN_CONFIRM_DELETE_DBS),
                ],
            )
            if confirm_del != "confirm_delete":
                return 0
            delete_dbs = True

    result = execute_troubleshooting_reset(plan, delete_databases=delete_dbs)
    if result.aborted_reason:
        show_native_persian_dialog(
            "عملیات متوقف شد",
            result.aborted_reason,
            buttons=[("close", BTN_CLOSE)],
        )
        return 1

    done_lines = [
        "بازنشانی با موفقیت کامل انجام شد:",
        f"• پیکربندی‌های پاک‌شده: {len(result.removed_configs)}",
        f"• کش‌های پاک‌شده: {len(result.removed_caches)}",
        f"• پوشه‌های موقت پاک‌شده: {len(result.removed_runtime)}",
        f"• فایل‌ها و لنگرهای لایسنس پاک‌شده: {len(result.removed_licenses)}",
        f"• پایگاه‌های داده حذف‌شده: {len(result.removed_databases)}",
        f"• پشتیبان‌های محافظت‌شده (بدون تغییر): {len(result.preserved_backups)}",
    ]
    if result.warnings:
        done_lines.extend(["", "هشدارها:", *result.warnings])

    show_native_persian_dialog(
        "پایان پاک‌سازی و بازنشانی دقیق",
        "\n".join(done_lines),
        buttons=[("ok", BTN_OK)],
    )
    return 0


def launch_gui() -> int:
    """Entry alias launching the zero-Qt native Win32 troubleshooting wizard."""
    return run_interactive_native_ui()


def run_self_test() -> int:
    """Headless automated self-test proving zero-Qt reset logic, centered Persian buttons, and backup preservation."""
    with tempfile.TemporaryDirectory(prefix="daqiq_ts_selftest_") as tmp_str:
        root = Path(tmp_str)
        exe_dir = root / "exe"
        local_app = root / "local"
        roaming_app = root / "roaming"
        prog_data = root / "progdata"
        tmp_dir = root / "tmp"
        db_dir = root / "docs" / "DaqiqDBs"
        custom_bk = root / "custom_bk"
        default_bk = db_dir / "Backups"
        nuitka_daqiq = local_app / "Nuitka" / "Daqiq"
        for d in (
            exe_dir,
            local_app / "Daqiq" / "license",
            roaming_app / "Daqiq",
            prog_data / "Daqiq" / "license",
            nuitka_daqiq,
            tmp_dir,
            default_bk,
            custom_bk,
        ):
            d.mkdir(parents=True, exist_ok=True)
        (local_app / "Daqiq" / "license" / "license.daqlic").write_text("{}", encoding="utf-8")
        (roaming_app / "Daqiq" / ".runtime_anchor.dat").write_text("{}", encoding="utf-8")
        (prog_data / "Daqiq" / "license" / "license.daqlic").write_text("{}", encoding="utf-8")
        (nuitka_daqiq / "cached.bin").write_bytes(b"123")
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
            program_data=prog_data,
            temp_dir=tmp_dir,
            process_lister=lambda: [],
        )
        res = execute_troubleshooting_reset(plan, delete_databases=True, process_lister=lambda: [])
        assert not res.aborted_reason, res.aborted_reason
        assert not (exe_dir / "app_config.json").exists()
        assert not (local_app / "Daqiq" / "license" / "license.daqlic").exists()
        assert not (roaming_app / "Daqiq" / ".runtime_anchor.dat").exists()
        assert not (prog_data / "Daqiq" / "license" / "license.daqlic").exists()
        assert not nuitka_daqiq.exists()
        assert not active_db.exists()
        assert bk_file.read_bytes() == b"BACKUP_SAFE"
        assert bk_custom.read_bytes() == b"CUSTOM_BACKUP_SAFE"

    rects = compute_centered_button_rects(560, 240, [BTN_START_RESET, BTN_CANCEL])
    assert len(rects) == 2
    left_gap = rects[0]["x"]
    right_gap = 560 - (rects[-1]["x"] + rects[-1]["w"])
    assert abs(left_gap - right_gap) <= 1

    # Verify native CreateWindowExW symbol resolves on Windows cleanly (without showing a dialog)
    if sys.platform == "win32" and hasattr(ctypes, "windll"):
        assert callable(getattr(ctypes.windll.user32, "CreateWindowExW", None))

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
