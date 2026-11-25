"""Standalone RTL Persian PySide6 GUI for Daqiq-Troubleshooter.exe.

ZERO imports from main, database, licensing, utils, or ui.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from .core import (
    TroubleshootingPlan,
    discover_troubleshooting_targets,
    execute_troubleshooting_reset,
    find_running_daqiq_pids,
    terminate_running_daqiq,
)


def _resource_asset_path(rel_path: str) -> Optional[str]:
    candidates = []
    try:
        candidates.append(Path(__file__).resolve().parent.parent / rel_path)
    except Exception:
        pass
    try:
        candidates.append(Path(sys.argv[0]).resolve().parent / rel_path)
    except Exception:
        pass
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return None


def launch_gui() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon, QFont
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QVBoxLayout,
    )

    app = QApplication.instance() or QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)

    class TroubleshooterWindow(QDialog):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("ابزار عیب‌یابی و بازنشانی امن دقیق (Daqiq Troubleshooter)")
            self.setLayoutDirection(Qt.RightToLeft)
            self.setMinimumSize(640, 520)
            icon_file = _resource_asset_path("assets/daqiq_logo.ico") or _resource_asset_path("assets/daqiq_logo.png")
            if icon_file:
                self.setWindowIcon(QIcon(icon_file))

            self.setStyleSheet("""
                QDialog { background-color: #f8fafc; color: #0f172a; font-family: 'Segoe UI', Tahoma, sans-serif; font-size: 13px; }
                QFrame#card { background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 10px; padding: 12px; }
                QFrame#backupBanner { background-color: #ecfdf5; border: 1.5px solid #10b981; border-radius: 8px; padding: 10px; }
                QFrame#procBanner { background-color: #fef2f2; border: 1.5px solid #ef4444; border-radius: 8px; padding: 10px; }
                QPlainTextEdit { background-color: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px; font-family: Consolas, 'Segoe UI', monospace; font-size: 11px; }
                QPushButton { background-color: #2563eb; color: white; font-weight: bold; border-radius: 6px; padding: 8px 14px; border: none; }
                QPushButton:hover { background-color: #1d4ed8; }
                QPushButton:disabled { background-color: #94a3b8; }
                QPushButton#btnDanger { background-color: #dc2626; }
                QPushButton#btnDanger:hover { background-color: #b91c1c; }
                QPushButton#btnSecondary { background-color: #475569; }
                QPushButton#btnSecondary:hover { background-color: #334155; }
            """)

            root = QVBoxLayout(self)
            root.setContentsMargins(16, 16, 16, 16)
            root.setSpacing(12)

            title = QLabel("ابزار عیب‌یابی و بازنشانی امن نرم‌افزار حسابداری دقیق")
            f = QFont()
            f.setPointSize(13)
            f.setBold(True)
            title.setFont(f)
            root.addWidget(title)

            subtitle = QLabel(
                "این ابزار مستقل فایل‌های کش اجرا، پوشه‌های موقت خراب و پیکربندی آسیب‌دیده (app_config.json) را پاک‌سازی می‌کند "
                "تا نرم‌افزار دقیق بدون خطا اجرا شود."
            )
            subtitle.setWordWrap(True)
            root.addWidget(subtitle)

            self.proc_frame = QFrame()
            self.proc_frame.setObjectName("procBanner")
            proc_layout = QHBoxLayout(self.proc_frame)
            self.lbl_proc = QLabel()
            self.lbl_proc.setWordWrap(True)
            self.btn_kill_daqiq = QPushButton("بستن برنامه دقیق")
            self.btn_kill_daqiq.setObjectName("btnDanger")
            self.btn_kill_daqiq.clicked.connect(self._kill_daqiq)
            proc_layout.addWidget(self.lbl_proc, 1)
            proc_layout.addWidget(self.btn_kill_daqiq, 0)
            root.addWidget(self.proc_frame)

            backup_frame = QFrame()
            backup_frame.setObjectName("backupBanner")
            bk_layout = QVBoxLayout(backup_frame)
            self.lbl_backup_guard = QLabel()
            self.lbl_backup_guard.setWordWrap(True)
            self.lbl_backup_guard.setStyleSheet("color: #065f46; font-weight: bold;")
            bk_layout.addWidget(self.lbl_backup_guard)
            root.addWidget(backup_frame)

            details_card = QFrame()
            details_card.setObjectName("card")
            d_layout = QVBoxLayout(details_card)
            d_layout.addWidget(QLabel("موارد شناسایی‌شده برای بررسی و پاک‌سازی:"))
            self.txt_preview = QPlainTextEdit()
            self.txt_preview.setReadOnly(True)
            self.txt_preview.setLayoutDirection(Qt.LeftToRight)
            d_layout.addWidget(self.txt_preview, 1)
            root.addWidget(details_card, 1)

            btn_row = QHBoxLayout()
            self.btn_refresh = QPushButton("🔄 بررسی مجدد")
            self.btn_refresh.setObjectName("btnSecondary")
            self.btn_refresh.clicked.connect(self.refresh_plan)
            self.btn_reset = QPushButton("🧹 شروع پاک‌سازی و بازنشانی")
            self.btn_reset.clicked.connect(self._run_reset)
            btn_close = QPushButton("خروج")
            btn_close.setObjectName("btnSecondary")
            btn_close.clicked.connect(self.reject)
            btn_row.addWidget(self.btn_reset)
            btn_row.addWidget(self.btn_refresh)
            btn_row.addStretch(1)
            btn_row.addWidget(btn_close)
            root.addLayout(btn_row)

            self.plan: Optional[TroubleshootingPlan] = None
            self.refresh_plan()

        def refresh_plan(self):
            self.plan = discover_troubleshooting_targets()
            if self.plan.running_pids:
                self.proc_frame.setVisible(True)
                self.lbl_proc.setText(
                    f"⚠️ نرم‌افزار دقیق در حال اجرا است (شناسه پردازش: {', '.join(map(str, self.plan.running_pids))}). "
                    "پیش از بازنشانی باید برنامه دقیق بسته شود."
                )
                self.btn_reset.setEnabled(False)
            else:
                self.proc_frame.setVisible(False)
                self.btn_reset.setEnabled(True)

            self.lbl_backup_guard.setText(
                f"🛡️ حفاظت مطلق از پشتیبان‌ها: {len(self.plan.protected_backup_dirs)} پوشه پشتیبان و "
                f"{len(self.plan.protected_backup_files)} فایل پشتیبان (دستی و خودکار) شناسایی و در لیست سفید قفل شدند و به هیچ وجه حذف نمی‌شوند."
            )

            lines = [
                f"[Configs to clear] ({len(self.plan.config_files)}):",
                *[f"  - {p}" for p in self.plan.config_files],
                f"[Caches to clear] ({len(self.plan.cache_paths)}):",
                *[f"  - {p}" for p in self.plan.cache_paths],
                f"[Runtime dirs to clear] ({len(self.plan.runtime_paths)}):",
                *[f"  - {p}" for p in self.plan.runtime_paths],
                f"[Detected DB files (separate prompt)] ({len(self.plan.database_files)}):",
                *[f"  - {p}" for p in self.plan.database_files],
                f"[Protected Backup Dirs (NEVER deleted)] ({len(self.plan.protected_backup_dirs)}):",
                *[f"  * {p}" for p in self.plan.protected_backup_dirs],
            ]
            self.txt_preview.setPlainText("\n".join(lines))

        def _kill_daqiq(self):
            remaining = terminate_running_daqiq()
            self.refresh_plan()
            if remaining:
                QMessageBox.warning(
                    self,
                    "هشدار",
                    "بستن خودکار برخی پردازش‌های دقیق ممکن نشد. لطفاً برنامه را به صورت دستی ببندید.",
                )

        def _run_reset(self):
            if self.plan is None:
                return
            if find_running_daqiq_pids():
                self.refresh_plan()
                return

            delete_dbs = False
            if self.plan.database_files:
                msg = QMessageBox(self)
                msg.setWindowTitle("وضعیت فایل‌های پایگاه داده")
                msg.setIcon(QMessageBox.Question)
                msg.setLayoutDirection(Qt.RightToLeft)
                msg.setText(
                    f"تعداد {len(self.plan.database_files)} فایل پایگاه داده شناسایی شد.\n"
                    "آیا مایلید فایل‌های پایگاه داده حفظ شوند یا حذف گردند؟\n"
                    "(پشتیبان‌های دستی و خودکار در هر دو حالت کاملاً حفظ می‌شوند.)"
                )
                btn_keep = msg.addButton("نگهداری پایگاه داده", QMessageBox.AcceptRole)
                btn_del = msg.addButton("حذف فایلهای پایگاه داده", QMessageBox.DestructiveRole)
                btn_cancel = msg.addButton("انصراف", QMessageBox.RejectRole)
                msg.exec()
                clicked = msg.clickedButton()
                if clicked is btn_cancel or clicked is None:
                    return
                if clicked is btn_del:
                    confirm = QMessageBox.question(
                        self,
                        "تأیید نهایی حذف پایگاه داده",
                        "آیا مطمئن هستید که فایل‌های فعال پایگاه داده حذف شوند؟\n"
                        "(فایل‌های پشتیبان دستی و خودکار دست‌نخورده باقی می‌مانند.)",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,
                    )
                    if confirm != QMessageBox.Yes:
                        return
                    delete_dbs = True
                elif clicked is btn_keep:
                    delete_dbs = False

            result = execute_troubleshooting_reset(self.plan, delete_databases=delete_dbs)
            if result.aborted_reason:
                QMessageBox.warning(self, "متوقف شد", result.aborted_reason)
                self.refresh_plan()
                return

            summary = (
                f"بازنشانی با موفقیت انجام شد:\n"
                f"• پیکربندی‌های پاک‌شده: {len(result.removed_configs)}\n"
                f"• کش‌های پاک‌شده: {len(result.removed_caches)}\n"
                f"• پوشه‌های موقت پاک‌شده: {len(result.removed_runtime)}\n"
                f"• پایگاه‌های داده حذف‌شده: {len(result.removed_databases)}\n"
                f"• پشتیبان‌های محافظت‌شده (دست‌نخورده): {len(result.preserved_backups)}"
            )
            if result.warnings:
                summary += "\n\nهشدارها:\n" + "\n".join(result.warnings)
            QMessageBox.information(self, "پایان پاک‌سازی", summary)
            self.refresh_plan()

    dlg = TroubleshooterWindow()
    dlg.exec()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="Daqiq-Troubleshooter",
        description="Standalone cache/config troubleshooting and safe reset tool for Daqiq.",
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
    args = parser.parse_args(argv)

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

    return launch_gui()
