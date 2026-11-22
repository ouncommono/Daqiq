# licensing/license_dialog.py
"""Persian RTL PySide6 Activation and License Management Dialog."""

import os
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QFileDialog,
    QGroupBox,
    QMessageBox,
    QFrame,
    QSizePolicy,
    QScrollArea,
)

from .license_models import ValidationStatus, ValidationResult
from .license_policy import LicenseService


class LicenseDialog(QDialog):
    """Persian RTL activation and license status dialog."""

    def __init__(
        self,
        service: LicenseService,
        parent=None,
        icon_path: Optional[str] = None,
        is_dark_theme: bool = False,
    ):
        super().__init__(parent)
        self.service = service
        self.icon_path = icon_path
        self.is_dark_theme = is_dark_theme
        self.current_result: Optional[ValidationResult] = None

        self.setWindowTitle("مدیریت و فعال‌سازی لایسنس دقیق")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setFont(QFont("Tahoma", 10))
        self.setMinimumSize(560, 480)
        self.resize(600, 520)

        if self.icon_path and os.path.exists(self.icon_path):
            self.setWindowIcon(QIcon(self.icon_path))

        self._build_ui()
        self.refresh_status()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # Header section
        header_frame = QFrame()
        header_frame.setFrameShape(QFrame.StyledPanel)
        header_frame.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0f172a, stop:1 #1e3a8a); "
            "border-radius: 8px; padding: 10px;"
        )
        h_layout = QHBoxLayout(header_frame)
        h_layout.setContentsMargins(10, 6, 10, 6)

        title_vbox = QVBoxLayout()
        title_lbl = QLabel("سامانه مدیریت و فعال‌سازی لایسنس دقیق")
        title_lbl.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: bold;")
        sub_lbl = QLabel("نسخه تجاری آفلاین مبتنی بر رمزنگاری نامتقارن Ed25519")
        sub_lbl.setStyleSheet("color: #94a3b8; font-size: 10px;")
        title_vbox.addWidget(title_lbl)
        title_vbox.addWidget(sub_lbl)
        h_layout.addLayout(title_vbox)
        h_layout.addStretch()

        if self.icon_path and os.path.exists(self.icon_path):
            icon_lbl = QLabel()
            pix = QIcon(self.icon_path).pixmap(36, 36)
            icon_lbl.setPixmap(pix)
            h_layout.addWidget(icon_lbl)

        layout.addWidget(header_frame)

        # Status Box
        self.status_box = QGroupBox("وضعیت فعال‌سازی")
        self.status_box.setAlignment(Qt.AlignRight)
        sb_layout = QVBoxLayout(self.status_box)

        self.lbl_status_badge = QLabel("در حال بررسی وضعیت لایسنس...")
        self.lbl_status_badge.setAlignment(Qt.AlignCenter)
        self.lbl_status_badge.setStyleSheet(
            "font-size: 13px; font-weight: bold; padding: 8px; border-radius: 6px;"
        )
        sb_layout.addWidget(self.lbl_status_badge)

        self.lbl_status_desc = QLabel("")
        self.lbl_status_desc.setWordWrap(True)
        self.lbl_status_desc.setAlignment(Qt.AlignRight)
        self.lbl_status_desc.setStyleSheet("color: #475569; padding: 4px;")
        sb_layout.addWidget(self.lbl_status_desc)

        layout.addWidget(self.status_box)

        # Hardware ID Box
        hw_box = QGroupBox("شناسه سخت‌افزاری دستگاه (جهت صدور لایسنس)")
        hw_box.setAlignment(Qt.AlignRight)
        hw_layout = QVBoxLayout(hw_box)

        hw_hint = QLabel(
            "شناسه زیر به صورت امن و یکتا از مشخصات سخت‌افزاری رایانه شما تولید شده است. "
            "جهت صدور یا ارتقای لایسنس، این شناسه را برای واحد پشتیبانی ارسال نمایید:"
        )
        hw_hint.setWordWrap(True)
        hw_hint.setStyleSheet("font-size: 10px; color: #64748b;")
        hw_layout.addWidget(hw_hint)

        hw_row = QHBoxLayout()
        self.ed_hw_fp = QLineEdit()
        self.ed_hw_fp.setReadOnly(True)
        self.ed_hw_fp.setAlignment(Qt.AlignLeft)
        self.ed_hw_fp.setStyleSheet("font-family: Consolas, monospace; font-size: 11px; padding: 5px;")
        hw_row.addWidget(self.ed_hw_fp, 1)

        self.btn_copy_fp = QPushButton("📋 کپی شناسه دستگاه")
        self.btn_copy_fp.setToolTip("کپی شناسه سخت‌افزاری در حافظه کلیپ‌بورد")
        self.btn_copy_fp.clicked.connect(self._copy_fingerprint)
        hw_row.addWidget(self.btn_copy_fp)
        hw_layout.addLayout(hw_row)

        layout.addWidget(hw_box)

        # License Details Area (Visible when valid)
        self.details_box = QGroupBox("مشخصات لایسنس فعال")
        self.details_box.setAlignment(Qt.AlignRight)
        dt_layout = QVBoxLayout(self.details_box)

        self.lbl_details = QLabel()
        self.lbl_details.setWordWrap(True)
        self.lbl_details.setStyleSheet("font-size: 11px; line-height: 1.6;")
        dt_layout.addWidget(self.lbl_details)
        layout.addWidget(self.details_box)

        # Action Buttons
        act_row = QHBoxLayout()

        self.btn_import = QPushButton("📂 انتخاب و وارد کردن فایل لایسنس (.daqlic)")
        self.btn_import.setStyleSheet("padding: 7px 12px; font-weight: bold; background-color: #0284c7; color: white;")
        self.btn_import.clicked.connect(self._import_license_flow)
        act_row.addWidget(self.btn_import)

        self.btn_retry = QPushButton("🔄 بررسی مجدد")
        self.btn_retry.clicked.connect(self.refresh_status)
        act_row.addWidget(self.btn_retry)

        act_row.addStretch()

        self.btn_enter = QPushButton("ورود به برنامه ✅")
        self.btn_enter.setStyleSheet("padding: 7px 16px; font-weight: bold; background-color: #16a34a; color: white;")
        self.btn_enter.clicked.connect(self.accept)
        act_row.addWidget(self.btn_enter)

        self.btn_exit = QPushButton("خروج ❌")
        self.btn_exit.setStyleSheet("padding: 7px 14px; background-color: #64748b; color: white;")
        self.btn_exit.clicked.connect(self.reject)
        act_row.addWidget(self.btn_exit)

        layout.addLayout(act_row)

    def refresh_status(self):
        """Re-evaluate licensing state and update dialog controls."""
        try:
            fp = self.service.get_hardware_fingerprint()
            self.ed_hw_fp.setText(fp)
        except Exception as e:
            self.ed_hw_fp.setText("خطا در تولید شناسه سخت‌افزاری")

        res = self.service.check_license(force_reload=True)
        self.current_result = res

        if res.is_valid and res.license:
            self.lbl_status_badge.setText("✅ لایسنس معتبر و فعال است")
            self.lbl_status_badge.setStyleSheet(
                "background-color: #dcfce7; color: #15803d; font-size: 13px; font-weight: bold; padding: 8px; border-radius: 6px;"
            )
            self.lbl_status_desc.setText("تمامی استانداردهای امنیتی و امضای دیجیتال تأیید شدند.")

            payload = res.license.payload
            lic_type_fa = "دائمی (مادام‌العمر)" if payload.license_type == "perpetual" else "اشتراکی زمان‌دار"

            expiry_text = "نامحدود"
            if payload.expires_at:
                try:
                    import jdatetime
                    from .license_verifier import parse_iso8601_utc
                    dt = parse_iso8601_utc(payload.expires_at)
                    jdt = jdatetime.datetime.fromgregorian(datetime=dt)
                    expiry_text = f"{jdt.strftime('%Y/%m/%d %H:%M')} (میلادی: {dt.strftime('%Y-%m-%d')})"
                except Exception:
                    expiry_text = payload.expires_at

            active_modules = [k for k, v in payload.features.items() if v]
            modules_str = "، ".join(active_modules) if active_modules else "هیچ ماژولی فعال نیست"

            info_text = (
                f"<b>نام مشتری:</b> {payload.customer.name}<br>"
                f"<b>شناسه لایسنس:</b> {payload.license_id}<br>"
                f"<b>نوع مجوز:</b> {lic_type_fa}<br>"
                f"<b>تاریخ انقضا:</b> {expiry_text}<br>"
                f"<b>سقف دستگاه‌های مجاز:</b> {payload.max_devices} دستگاه<br>"
                f"<b>ماژول‌های فعال:</b> {modules_str}"
            )
            self.lbl_details.setText(info_text)
            self.details_box.setVisible(True)
            self.btn_enter.setVisible(True)
            self.btn_enter.setEnabled(True)
        else:
            self.lbl_status_badge.setText(f"❌ لایسنس غیرفعال است ({res.status.value})")
            self.lbl_status_badge.setStyleSheet(
                "background-color: #fee2e2; color: #b91c1c; font-size: 13px; font-weight: bold; padding: 8px; border-radius: 6px;"
            )
            msg = res.message_fa or "مجوز معتبری یافت نشد."
            if res.detail:
                msg += f"\nجزئیات: {res.detail}"
            self.lbl_status_desc.setText(msg)
            self.details_box.setVisible(False)
            self.btn_enter.setVisible(False)
            self.btn_enter.setEnabled(False)

    def _copy_fingerprint(self):
        """Copy the hardware fingerprint to system clipboard."""
        fp = self.ed_hw_fp.text().strip()
        if fp and not fp.startswith("خطا"):
            app = QApplication.instance()
            if app:
                clipboard = app.clipboard()
                clipboard.setText(fp)
                orig_text = self.btn_copy_fp.text()
                self.btn_copy_fp.setText("کپی شد! ✔")
                QTimer.singleShot(2000, lambda: self.btn_copy_fp.setText(orig_text))

    def _import_license_flow(self):
        """Prompt user to select a .daqlic file and attempt atomic import."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "انتخاب فایل لایسنس دقیق",
            "",
            "Daqiq License (*.daqlic);;All Files (*)",
        )
        if not path:
            return

        res = self.service.import_license_file(path)
        if res.is_valid:
            QMessageBox.information(
                self,
                "فعال‌سازی موفق",
                "لایسنس با موفقیت اعتبارسنجی و در سیستم ثبت گردید.",
            )
        else:
            msg = res.message_fa or "فایل لایسنس نامعتبر است."
            if res.detail:
                msg += f"\nجزئیات: {res.detail}"
            QMessageBox.warning(
                self,
                "خطا در فعال‌سازی",
                f"فایل لایسنس انتخاب‌شده معتبر نیست:\n{msg}",
            )
        self.refresh_status()
