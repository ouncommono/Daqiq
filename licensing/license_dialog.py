# licensing/license_dialog.py
"""Persian RTL PySide6 Activation and License Management Dialog for Daqiq Desktop."""

import os
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QFont, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QPlainTextEdit,
    QFileDialog,
    QGroupBox,
    QMessageBox,
    QFrame,
    QSizePolicy,
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

        self.setWindowTitle("پنجره ورودی و فعال‌سازی دقیق")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setFont(QFont("Tahoma", 10))
        self.setMinimumSize(620, 560)
        self.resize(650, 600)
        self.setAcceptDrops(True)

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
        sub_lbl = QLabel("نسخه تجاری آفلاین مبتنی بر رمزنگاری نامتقارن Ed25519 و شناسه سخت‌افزاری پایدار")
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
        self.status_box = QGroupBox("وضعیت فعال‌سازی لایسنس")
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

        # Step 1: Hardware Request Box
        step1_box = QGroupBox("گام ۱: دریافت فایل مشخصات سیستم یا شناسه سخت‌افزاری")
        step1_box.setAlignment(Qt.AlignRight)
        step1_layout = QVBoxLayout(step1_box)

        step1_hint = QLabel(
            "جهت صدور یا تمدید لایسنس، فایل مشخصات سیستم (.daqreq) را ذخیره نموده و برای واحد فروش/پشتیبانی ارسال فرمایید، یا شناسه دستگاه را کپی کنید:"
        )
        step1_hint.setWordWrap(True)
        step1_hint.setStyleSheet("font-size: 10px; color: #64748b;")
        step1_layout.addWidget(step1_hint)

        hw_row = QHBoxLayout()
        self.ed_hw_fp = QLineEdit()
        self.ed_hw_fp.setReadOnly(True)
        self.ed_hw_fp.setAlignment(Qt.AlignLeft)
        self.ed_hw_fp.setStyleSheet("font-family: Consolas, monospace; font-size: 11px; padding: 5px;")
        hw_row.addWidget(self.ed_hw_fp, 1)

        self.btn_copy_fp = QPushButton("📋 کپی شناسه")
        self.btn_copy_fp.setToolTip("کپی شناسه سخت‌افزاری در حافظه کلیپ‌بورد")
        self.btn_copy_fp.clicked.connect(self._copy_fingerprint)
        hw_row.addWidget(self.btn_copy_fp)

        self.btn_export_req = QPushButton("💾 ذخیره فایل مشخصات (.daqreq)")
        self.btn_export_req.setStyleSheet("background-color: #0d9488; color: white; font-weight: bold; padding: 5px 10px;")
        self.btn_export_req.setToolTip("ایجاد و ذخیره فایل درخواست صدور لایسنس برای پشتیبانی")
        self.btn_export_req.clicked.connect(self._export_request_flow)
        hw_row.addWidget(self.btn_export_req)

        step1_layout.addLayout(hw_row)
        layout.addWidget(step1_box)

        # Step 2: License Import Box
        step2_box = QGroupBox("گام ۲: بارگذاری فایل لایسنس دریافتی (.daqlic) یا درج متن فعال‌سازی")
        step2_box.setAlignment(Qt.AlignRight)
        step2_layout = QVBoxLayout(step2_box)

        step2_hint = QLabel(
            "فایل لایسنس (.daqlic) دریافتی از پشتیبانی را انتخاب کنید یا آن را به داخل این پنجره بکشید (Drag & Drop):"
        )
        step2_hint.setWordWrap(True)
        step2_hint.setStyleSheet("font-size: 10px; color: #64748b;")
        step2_layout.addWidget(step2_hint)

        import_row = QHBoxLayout()
        self.btn_import_file = QPushButton("📂 انتخاب فایل لایسنس (.daqlic)")
        self.btn_import_file.setStyleSheet("padding: 7px 14px; font-weight: bold; background-color: #0284c7; color: white;")
        self.btn_import_file.clicked.connect(self._import_license_file_flow)
        import_row.addWidget(self.btn_import_file)

        self.btn_paste_token = QPushButton("📝 درج متن فعال‌سازی / توکن")
        self.btn_paste_token.setStyleSheet("padding: 7px 12px; background-color: #475569; color: white;")
        self.btn_paste_token.clicked.connect(self._toggle_token_box)
        import_row.addWidget(self.btn_paste_token)

        self.btn_retry = QPushButton("🔄 بررسی مجدد")
        self.btn_retry.clicked.connect(self.refresh_status)
        import_row.addWidget(self.btn_retry)

        import_row.addStretch()
        step2_layout.addLayout(import_row)

        # Collapsible text token input
        self.token_frame = QFrame()
        self.token_frame.setVisible(False)
        t_layout = QVBoxLayout(self.token_frame)
        t_layout.setContentsMargins(0, 4, 0, 4)
        self.txt_token = QPlainTextEdit()
        self.txt_token.setPlaceholderText("متن کد فعال‌سازی یا توکن Base64 را در اینجا الصاق نمایید...")
        self.txt_token.setFixedHeight(60)
        self.txt_token.setStyleSheet("font-family: Consolas, monospace; font-size: 10px;")
        t_layout.addWidget(self.txt_token)
        btn_apply_token = QPushButton("ثبت و فعال‌سازی با متن بالا ✅")
        btn_apply_token.setStyleSheet("background-color: #2563eb; color: white; padding: 4px 10px;")
        btn_apply_token.clicked.connect(self._apply_token_flow)
        t_layout.addWidget(btn_apply_token)
        step2_layout.addWidget(self.token_frame)

        layout.addWidget(step2_box)

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

        self.btn_remove = QPushButton("🗑️ حذف لایسنس از این سیستم")
        self.btn_remove.setStyleSheet("padding: 6px 12px; color: #dc2626; border: 1px solid #f87171; border-radius: 4px;")
        self.btn_remove.setToolTip("حذف فایل لایسنس ذخیره‌شده از روی این رایانه")
        self.btn_remove.clicked.connect(self._remove_license_flow)
        act_row.addWidget(self.btn_remove)

        act_row.addStretch()

        self.btn_enter = QPushButton("ورود به برنامه ✅")
        self.btn_enter.setStyleSheet("padding: 7px 18px; font-weight: bold; background-color: #16a34a; color: white; font-size: 12px;")
        self.btn_enter.clicked.connect(self.accept)
        act_row.addWidget(self.btn_enter)

        self.btn_exit = QPushButton("خروج ❌")
        self.btn_exit.setStyleSheet("padding: 7px 14px; background-color: #64748b; color: white;")
        self.btn_exit.clicked.connect(self.reject)
        act_row.addWidget(self.btn_exit)

        layout.addLayout(act_row)

        # Key fingerprint subtle footer
        self.lbl_key_fp = QLabel("شناسه کلید امنیتی: در حال بارگذاری...")
        self.lbl_key_fp.setAlignment(Qt.AlignCenter)
        self.lbl_key_fp.setStyleSheet("color: #64748b; font-size: 10px; font-family: monospace; padding-top: 4px;")
        layout.addWidget(self.lbl_key_fp)

    def _toggle_token_box(self):
        self.token_frame.setVisible(not self.token_frame.isVisible())

    def dragEnterEvent(self, event: QDragEnterEvent):
        """Accept dropped files with .daqlic extension."""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                p = url.toLocalFile()
                if p.endswith(".daqlic") or p.endswith(".lic") or p.endswith(".json"):
                    event.acceptProposedAction()
                    return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent):
        """Process dropped license file."""
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.isfile(file_path):
                self._import_from_path(file_path)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def refresh_status(self):
        """Re-evaluate licensing state and update dialog controls."""
        try:
            fp = self.service.get_hardware_fingerprint()
            self.ed_hw_fp.setText(fp)
        except Exception:
            self.ed_hw_fp.setText("خطا در استخراج مشخصات سخت‌افزاری")

        res = self.service.check_license(force_reload=True)
        self.current_result = res

        try:
            key_fps = self.service.get_active_key_fingerprints()
            key_fp_str = ", ".join(k.get("display", k.get("fingerprint", "")) for k in key_fps) if key_fps else "پیش‌فرض"
            self.lbl_key_fp.setText(f"شناسه کلید امنیتی (Key FP): {key_fp_str}")
        except Exception:
            key_fp_str = "پیش‌فرض"
            self.lbl_key_fp.setText("شناسه کلید امنیتی: پیش‌فرض")

        if res.is_valid and res.license:
            payload = res.license.payload
            lic_type_map = {
                "perpetual": "دائمی (مادام‌العمر)",
                "subscription": "اشتراکی زمان‌دار",
                "trial": "آزمایشی (Trial)",
            }
            lic_type_fa = lic_type_map.get(payload.license_type, payload.license_type)

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

            if res.in_grace_period:
                self.lbl_status_badge.setText("⚠️ لایسنس در دوره مهلت (Grace Period) قرار دارد")
                self.lbl_status_badge.setStyleSheet(
                    "background-color: #fef3c7; color: #b45309; font-size: 13px; font-weight: bold; padding: 8px; border-radius: 6px;"
                )
                self.lbl_status_desc.setText(
                    f"اشتراک شما به پایان رسیده است اما به مدت چند روز امکان استفاده موقت ({res.grace_mode}) فعال است. لطفاً جهت تمدید اقدام نمایید."
                )
            elif res.is_trial:
                self.lbl_status_badge.setText(f"🔷 نسخه آزمایشی فعال است ({res.days_remaining} روز باقیمانده)")
                self.lbl_status_badge.setStyleSheet(
                    "background-color: #e0e7ff; color: #3730a3; font-size: 13px; font-weight: bold; padding: 8px; border-radius: 6px;"
                )
                self.lbl_status_desc.setText("تمامی استانداردهای امنیتی و امضای دیجیتال آزمایشی تأیید شدند.")
            else:
                self.lbl_status_badge.setText("✅ لایسنس معتبر و فعال است")
                self.lbl_status_badge.setStyleSheet(
                    "background-color: #dcfce7; color: #15803d; font-size: 13px; font-weight: bold; padding: 8px; border-radius: 6px;"
                )
                self.lbl_status_desc.setText(res.message_fa or "تمامی استانداردهای امنیتی و امضای دیجیتال تأیید شدند.")

            info_text = (
                f"<b>نام دارنده:</b> {payload.customer.name}<br>"
                f"<b>شماره لایسنس:</b> {payload.license_id}<br>"
                f"<b>پلن/نسخه:</b> {lic_type_fa}<br>"
                f"<b>تاریخ انقضا:</b> {expiry_text}<br>"
                f"<b>دستگاه‌های مجاز:</b> {payload.max_devices} سیستم<br>"
                f"<b>ماژول‌های فعال:</b> {modules_str}<br>"
                f"<b>شناسه کلید امنیتی:</b> <code>{key_fp_str}</code>"
            )
            self.lbl_details.setText(info_text)
            self.details_box.setVisible(True)
            self.btn_enter.setVisible(True)
            self.btn_enter.setEnabled(True)
            self.btn_remove.setVisible(True)
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
            self.btn_remove.setVisible(False)

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

    def _export_request_flow(self):
        """Prompt user to save .daqreq hardware request file."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "ذخیره فایل مشخصات سیستم جهت دریافت لایسنس",
            "Daqiq_Hardware_Request.daqreq",
            "Daqiq Request (*.daqreq);;JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            self.service.export_device_request_file(path)
            QMessageBox.information(
                self,
                "ذخیره موفق",
                f"فایل مشخصات سیستم با موفقیت در مسیر زیر ذخیره شد:\n{path}\n\nلطفاً این فایل را برای واحد پشتیبانی ارسال فرمایید.",
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "خطا در ذخیره فایل",
                f"امکان ذخیره فایل مشخصات سیستم وجود ندارد:\n{e}",
            )

    def _import_license_file_flow(self):
        """Prompt user to select a .daqlic file."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "انتخاب فایل لایسنس دقیق",
            "",
            "Daqiq License (*.daqlic *.lic);;JSON Files (*.json);;All Files (*)",
        )
        if path:
            self._import_from_path(path)

    def _import_from_path(self, path: str):
        res = self.service.import_license_file(path)
        if res.is_valid:
            QMessageBox.information(
                self,
                "فعال‌سازی موفق",
                "لایسنس با موفقیت اعتبارسنجی و بر روی این سیستم ثبت گردید.",
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

    def _apply_token_flow(self):
        token = self.txt_token.toPlainText().strip()
        if not token:
            return
        res = self.service.import_license_token(token)
        if res.is_valid:
            QMessageBox.information(
                self,
                "فعال‌سازی موفق",
                "کد لایسنس با موفقیت بررسی و ثبت گردید.",
            )
            self.txt_token.clear()
            self.token_frame.setVisible(False)
        else:
            msg = res.message_fa or "کد لایسنس نامعتبر است."
            if res.detail:
                msg += f"\nجزئیات: {res.detail}"
            QMessageBox.warning(
                self,
                "خطا در فعال‌سازی",
                f"کد وارد شده معتبر نیست:\n{msg}",
            )
        self.refresh_status()

    def _remove_license_flow(self):
        """Remove active license after user confirmation."""
        confirm = QMessageBox.question(
            self,
            "تأیید حذف لایسنس",
            "آیا از حذف لایسنس فعال از روی این سیستم اطمینان دارید؟\nپس از حذف، تا زمان ثبت لایسنس جدید، دسترسی به امکانات نرم‌افزار متوقف خواهد شد.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self.service.remove_license()
            QMessageBox.information(self, "حذف لایسنس", "لایسنس با موفقیت از سیستم حذف گردید.")
            self.refresh_status()
