# licensing/license_dialog.py
"""Persian RTL PySide6 Activation and License Management Dialog for Daqiq Desktop."""

import json
import os
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QFont, QDragEnterEvent, QDropEvent, QPixmap, QCursor
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
    QScrollArea,
    QWidget,
)

from .license_models import ValidationStatus, ValidationResult
from .license_policy import LicenseService


def _try_update_app_config_theme(is_dark: bool):
    """Safely persist theme preference to app_config.json if possible."""
    try:
        from database import load_app_config, save_app_config
        cfg = load_app_config()
        cfg["theme"] = "dark" if is_dark else "light"
        save_app_config(cfg)
    except Exception:
        pass


class LicenseDialog(QDialog):
    """Persian RTL activation and license status dialog."""

    def __init__(
        self,
        service: LicenseService,
        parent=None,
        icon_path: Optional[str] = None,
        is_dark_theme: bool = False,
        is_startup_gate: bool = True,
    ):
        super().__init__(parent)
        self.service = service
        self.icon_path = icon_path
        self.is_dark_theme = is_dark_theme
        self.is_startup_gate = is_startup_gate
        self.current_result: Optional[ValidationResult] = None
        self._current_key_fp_text: str = ""

        self.setWindowTitle("مدیریت و فعال‌سازی لایسنس دقیق")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setFont(QFont("Tahoma", 10))
        self.setMinimumSize(640, 600)
        self.resize(680, 650)
        self.setAcceptDrops(True)

        if self.icon_path and os.path.exists(self.icon_path):
            self.setWindowIcon(QIcon(self.icon_path))

        self._build_ui()
        self._apply_theme()
        self.refresh_status()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(10)

        # Header section
        self.header_frame = QFrame()
        self.header_frame.setFrameShape(QFrame.StyledPanel)
        h_layout = QHBoxLayout(self.header_frame)
        h_layout.setContentsMargins(12, 8, 12, 8)

        # Crisp brand logo
        self.icon_lbl = QLabel()
        svg_path = ""
        if self.icon_path:
            cand = self.icon_path.replace(".png", ".svg")
            if os.path.exists(cand):
                svg_path = cand
        if not svg_path:
            from utils_and_widgets import resource_path
            cand = resource_path("assets/daqiq_logo.svg")
            if os.path.exists(cand):
                svg_path = cand

        pix = None
        if svg_path and os.path.exists(svg_path):
            try:
                from PySide6.QtSvg import QSvgRenderer
                from PySide6.QtGui import QPainter, QImage
                renderer = QSvgRenderer(svg_path)
                dpr = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
                target_w, target_h = 60, 60
                img = QImage(int(target_w * dpr), int(target_h * dpr), QImage.Format_ARGB32_Premultiplied)
                img.fill(Qt.transparent)
                painter = QPainter(img)
                renderer.render(painter)
                painter.end()
                img.setDevicePixelRatio(dpr)
                pix = QPixmap.fromImage(img)
            except Exception:
                pix = None

        if pix is None and self.icon_path and os.path.exists(self.icon_path):
            raw_pix = QPixmap(self.icon_path)
            if not raw_pix.isNull():
                pix = raw_pix.scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        if pix and not pix.isNull():
            self.icon_lbl.setPixmap(pix)
        self.icon_lbl.setFixedSize(64, 64)
        self.icon_lbl.setAlignment(Qt.AlignCenter)
        h_layout.addWidget(self.icon_lbl)

        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(4)
        self.title_lbl = QLabel("مدیریت و وضعیت لایسنس")
        self.title_lbl.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: bold;")
        self.sub_lbl = QLabel("سامانه مدیریت اشتراک و فعال‌سازی آفلاین نرم‌افزار دقیق")
        self.sub_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
        title_vbox.addWidget(self.title_lbl)
        title_vbox.addWidget(self.sub_lbl)
        h_layout.addLayout(title_vbox, 1)

        # Theme toggle button in header
        self.btn_theme_toggle = QPushButton()
        self.btn_theme_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_theme_toggle.clicked.connect(self._toggle_theme)
        h_layout.addWidget(self.btn_theme_toggle)

        main_layout.addWidget(self.header_frame)

        # Scrollable container for middle contents
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(scroll_widget)
        self.scroll_layout.setContentsMargins(4, 4, 4, 4)
        self.scroll_layout.setSpacing(10)

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
        self.lbl_status_desc.setStyleSheet("padding: 4px;")
        sb_layout.addWidget(self.lbl_status_desc)

        self.scroll_layout.addWidget(self.status_box)

        # Step 1: Hardware Request Box
        self.step1_box = QGroupBox("گام ۱: دریافت فایل مشخصات سیستم یا شناسه سخت‌افزاری")
        self.step1_box.setAlignment(Qt.AlignRight)
        step1_layout = QVBoxLayout(self.step1_box)

        self.step1_hint = QLabel(
            "جهت صدور یا تمدید لایسنس، فایل مشخصات سیستم (.daqreq) را ذخیره نموده و برای واحد فروش/پشتیبانی ارسال فرمایید، یا شناسه دستگاه را کپی کنید:"
        )
        self.step1_hint.setWordWrap(True)
        self.step1_hint.setStyleSheet("font-size: 10px;")
        step1_layout.addWidget(self.step1_hint)

        hw_row = QHBoxLayout()
        self.ed_hw_fp = QLineEdit()
        self.ed_hw_fp.setReadOnly(True)
        self.ed_hw_fp.setAlignment(Qt.AlignLeft)
        self.ed_hw_fp.setStyleSheet("font-family: Consolas, monospace; font-size: 11px; padding: 5px;")
        hw_row.addWidget(self.ed_hw_fp, 1)

        self.btn_copy_fp = QPushButton("📋 کپی شناسه")
        self.btn_copy_fp.setCursor(Qt.PointingHandCursor)
        self.btn_copy_fp.setToolTip("کپی شناسه سخت‌افزاری در حافظه کلیپ‌بورد")
        self.btn_copy_fp.clicked.connect(self._copy_fingerprint)
        hw_row.addWidget(self.btn_copy_fp)

        self.btn_export_req = QPushButton("💾 ذخیره فایل مشخصات (.daqreq)")
        self.btn_export_req.setCursor(Qt.PointingHandCursor)
        self.btn_export_req.setStyleSheet(
            "background-color: #0d9488; color: white; font-weight: bold; padding: 5px 12px; border-radius: 4px;"
        )
        self.btn_export_req.setToolTip("ایجاد و ذخیره فایل درخواست صدور لایسنس برای پشتیبانی")
        self.btn_export_req.clicked.connect(self._export_request_flow)
        hw_row.addWidget(self.btn_export_req)

        step1_layout.addLayout(hw_row)
        self.scroll_layout.addWidget(self.step1_box)

        # Step 2: License Import Box
        self.step2_box = QGroupBox("گام ۲: بارگذاری فایل لایسنس دریافتی (.daqlic) یا درج متن فعال‌سازی")
        self.step2_box.setAlignment(Qt.AlignRight)
        step2_layout = QVBoxLayout(self.step2_box)

        self.step2_hint = QLabel(
            "فایل لایسنس (.daqlic) دریافتی از پشتیبانی را انتخاب کنید یا آن را به داخل این پنجره بکشید (Drag & Drop):"
        )
        self.step2_hint.setWordWrap(True)
        self.step2_hint.setStyleSheet("font-size: 10px;")
        step2_layout.addWidget(self.step2_hint)

        import_row = QHBoxLayout()
        self.btn_import_file = QPushButton("📂 انتخاب فایل لایسنس (.daqlic)")
        self.btn_import_file.setCursor(Qt.PointingHandCursor)
        self.btn_import_file.setStyleSheet(
            "padding: 7px 14px; font-weight: bold; background-color: #0284c7; color: white; border-radius: 4px;"
        )
        self.btn_import_file.clicked.connect(self._import_license_file_flow)
        import_row.addWidget(self.btn_import_file)

        self.btn_paste_token = QPushButton("📝 درج متن فعال‌سازی / توکن")
        self.btn_paste_token.setCursor(Qt.PointingHandCursor)
        self.btn_paste_token.setStyleSheet(
            "padding: 7px 12px; background-color: #475569; color: white; border-radius: 4px;"
        )
        self.btn_paste_token.clicked.connect(self._toggle_token_box)
        import_row.addWidget(self.btn_paste_token)

        self.btn_retry = QPushButton("🔄 بررسی مجدد")
        self.btn_retry.setCursor(Qt.PointingHandCursor)
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
        self.txt_token.setFixedHeight(65)
        self.txt_token.setStyleSheet("font-family: Consolas, monospace; font-size: 10px;")
        t_layout.addWidget(self.txt_token)
        btn_apply_token = QPushButton("ثبت و فعال‌سازی با متن بالا ✅")
        btn_apply_token.setCursor(Qt.PointingHandCursor)
        btn_apply_token.setStyleSheet("background-color: #2563eb; color: white; padding: 5px 12px; border-radius: 4px;")
        btn_apply_token.clicked.connect(self._apply_token_flow)
        t_layout.addWidget(btn_apply_token)
        step2_layout.addWidget(self.token_frame)

        self.scroll_layout.addWidget(self.step2_box)

        # License Details Area (Visible when valid)
        self.details_box = QGroupBox("مشخصات لایسنس فعال")
        self.details_box.setAlignment(Qt.AlignRight)
        dt_layout = QVBoxLayout(self.details_box)

        self.lbl_details = QLabel()
        self.lbl_details.setWordWrap(True)
        self.lbl_details.setStyleSheet("font-size: 11px; line-height: 1.6;")
        dt_layout.addWidget(self.lbl_details)
        self.scroll_layout.addWidget(self.details_box)

        self.scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(self.scroll_area, 1)

        # Action Buttons Footer
        act_row = QHBoxLayout()

        self.btn_remove = QPushButton("🗑️ حذف لایسنس از این سیستم")
        self.btn_remove.setCursor(Qt.PointingHandCursor)
        self.btn_remove.setToolTip("حذف فایل لایسنس ذخیره‌شده از روی این رایانه")
        self.btn_remove.clicked.connect(self._remove_license_flow)
        act_row.addWidget(self.btn_remove)

        act_row.addStretch()

        # Startup gate buttons
        self.btn_enter = QPushButton("ورود به برنامه ✅")
        self.btn_enter.setCursor(Qt.PointingHandCursor)
        self.btn_enter.setStyleSheet(
            "padding: 7px 20px; font-weight: bold; background-color: #16a34a; color: white; font-size: 12px; border-radius: 4px;"
        )
        self.btn_enter.clicked.connect(self.accept)
        act_row.addWidget(self.btn_enter)

        self.btn_exit = QPushButton("خروج ❌")
        self.btn_exit.setCursor(Qt.PointingHandCursor)
        self.btn_exit.setStyleSheet(
            "padding: 7px 16px; background-color: #64748b; color: white; border-radius: 4px;"
        )
        self.btn_exit.clicked.connect(self.reject)
        act_row.addWidget(self.btn_exit)

        # In-app close button
        self.btn_close = QPushButton("بستن")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setStyleSheet(
            "padding: 7px 20px; font-weight: bold; background-color: #0284c7; color: white; font-size: 12px; border-radius: 4px;"
        )
        self.btn_close.clicked.connect(self.accept)
        act_row.addWidget(self.btn_close)

        main_layout.addLayout(act_row)

        # Clickable App identifier footer
        self.lbl_key_fp = QLabel("شناسه برنامه: در حال بارگذاری...")
        self.lbl_key_fp.setAlignment(Qt.AlignCenter)
        self.lbl_key_fp.setCursor(Qt.PointingHandCursor)
        self.lbl_key_fp.setToolTip("برای کپی کردن شناسه برنامه کلیک کنید")
        self.lbl_key_fp.mousePressEvent = self._copy_key_fingerprint
        main_layout.addWidget(self.lbl_key_fp)

    def _toggle_theme(self):
        """Toggle between Dark and Light mode and apply immediately."""
        self.is_dark_theme = not self.is_dark_theme
        _try_update_app_config_theme(self.is_dark_theme)
        self._apply_theme()

    def _apply_theme(self):
        """Apply coherent styling based on is_dark_theme."""
        if self.is_dark_theme:
            self.setStyleSheet(
                "QDialog { background-color: #0f172a; color: #f8fafc; } "
                "QGroupBox { font-weight: bold; border: 1px solid #334155; border-radius: 6px; margin-top: 8px; padding-top: 14px; background-color: #1e293b; color: #38bdf8; } "
                "QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top right; padding: 0 8px; color: #38bdf8; } "
                "QLabel { color: #f1f5f9; } "
                "QLineEdit, QPlainTextEdit { background-color: #0f172a; color: #f8fafc; border: 1px solid #475569; border-radius: 4px; } "
            )
            self.header_frame.setStyleSheet(
                "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #090d16, stop:1 #1e3a8a); "
                "border-radius: 8px; padding: 10px; border: 1px solid #334155;"
            )
            self.btn_theme_toggle.setText("☀️ حالت روشن")
            self.btn_theme_toggle.setStyleSheet(
                "background-color: #334155; color: #f8fafc; border: 1px solid #64748b; border-radius: 6px; padding: 5px 12px; font-weight: bold;"
            )
            self.btn_remove.setStyleSheet(
                "background-color: #7f1d1d; border: 1px solid #ef4444; color: #fef2f2; font-weight: bold; padding: 6px 14px; border-radius: 4px;"
            )
            self.btn_retry.setStyleSheet(
                "background-color: #334155; color: #f8fafc; border: 1px solid #64748b; padding: 6px 12px; border-radius: 4px;"
            )
            self.btn_copy_fp.setStyleSheet(
                "background-color: #334155; color: #f8fafc; border: 1px solid #64748b; padding: 5px 10px; border-radius: 4px;"
            )
            self.lbl_key_fp.setStyleSheet(
                "color: #94a3b8; font-size: 11px; font-family: Consolas, monospace; padding-top: 4px;"
            )
            self.step1_hint.setStyleSheet("font-size: 10px; color: #94a3b8;")
            self.step2_hint.setStyleSheet("font-size: 10px; color: #94a3b8;")
        else:
            self.setStyleSheet(
                "QDialog { background-color: #f8fafc; color: #0f172a; } "
                "QGroupBox { font-weight: bold; border: 1px solid #cbd5e1; border-radius: 6px; margin-top: 8px; padding-top: 14px; background-color: #ffffff; color: #0369a1; } "
                "QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top right; padding: 0 8px; color: #0369a1; } "
                "QLabel { color: #0f172a; } "
                "QLineEdit, QPlainTextEdit { background-color: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 4px; } "
            )
            self.header_frame.setStyleSheet(
                "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1e3a8a, stop:1 #0284c7); "
                "border-radius: 8px; padding: 10px;"
            )
            self.btn_theme_toggle.setText("🌙 حالت تاریک")
            self.btn_theme_toggle.setStyleSheet(
                "background-color: #f1f5f9; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 6px; padding: 5px 12px; font-weight: bold;"
            )
            self.btn_remove.setStyleSheet(
                "background-color: #fee2e2; border: 1px solid #dc2626; color: #991b1b; font-weight: bold; padding: 6px 14px; border-radius: 4px;"
            )
            self.btn_retry.setStyleSheet(
                "background-color: #f1f5f9; color: #0f172a; border: 1px solid #cbd5e1; padding: 6px 12px; border-radius: 4px;"
            )
            self.btn_copy_fp.setStyleSheet(
                "background-color: #f1f5f9; color: #0f172a; border: 1px solid #cbd5e1; padding: 5px 10px; border-radius: 4px;"
            )
            self.lbl_key_fp.setStyleSheet(
                "color: #64748b; font-size: 11px; font-family: Consolas, monospace; padding-top: 4px;"
            )
            self.step1_hint.setStyleSheet("font-size: 10px; color: #64748b;")
            self.step2_hint.setStyleSheet("font-size: 10px; color: #64748b;")

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

    def _copy_key_fingerprint(self, event=None):
        """Copy active public key fingerprint to clipboard with 2.5s auto-reverting feedback."""
        raw_fp = getattr(self, "_current_key_fp_text", "")
        if raw_fp:
            app = QApplication.instance()
            if app:
                app.clipboard().setText(raw_fp)
                if hasattr(self, "_key_fp_timer") and self._key_fp_timer:
                    try:
                        self._key_fp_timer.stop()
                    except Exception:
                        pass
                orig = f"شناسه برنامه: {raw_fp} (کلیک جهت کپی)"
                self.lbl_key_fp.setText("شناسه برنامه کپی شد ✓")
                self._key_fp_timer = QTimer(self)
                self._key_fp_timer.setSingleShot(True)
                self._key_fp_timer.timeout.connect(
                    lambda: self.lbl_key_fp.setText(orig) if not self.isHidden() else None
                )
                self._key_fp_timer.start(2500)

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
            self._current_key_fp_text = key_fp_str
            self.lbl_key_fp.setText(f"شناسه برنامه: {key_fp_str} (کلیک جهت کپی)")
        except Exception:
            self._current_key_fp_text = "پیش‌فرض"
            self.lbl_key_fp.setText("شناسه برنامه: پیش‌فرض")

        # Configure action buttons based on is_startup_gate and validity
        if self.is_startup_gate:
            self.btn_close.setVisible(False)
            self.btn_exit.setVisible(True)
        else:
            self.btn_enter.setVisible(False)
            self.btn_exit.setVisible(False)
            self.btn_close.setVisible(True)

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
            modules_str = "، ".join(active_modules) if active_modules else "تمامی ماژول‌ها فعال"

            if res.in_grace_period:
                self.lbl_status_badge.setText("⚠️ لایسنس در دوره مهلت (Grace Period) قرار دارد")
                self.lbl_status_badge.setStyleSheet(
                    "background-color: #fef3c7; color: #b45309; font-size: 13px; font-weight: bold; padding: 8px; border-radius: 6px;"
                )
                self.lbl_status_desc.setText(
                    f"اشتراک شما به پایان رسیده است اما امکان استفاده موقت ({res.grace_mode}) فعال است. لطفاً جهت تمدید اقدام نمایید."
                )
            elif res.is_trial:
                self.lbl_status_badge.setText(f"🔷 نسخه آزمایشی فعال است ({res.days_remaining} روز باقیمانده)")
                self.lbl_status_badge.setStyleSheet(
                    "background-color: #e0e7ff; color: #3730a3; font-size: 13px; font-weight: bold; padding: 8px; border-radius: 6px;"
                )
                self.lbl_status_desc.setText("نسخه آزمایشی نرم‌افزار فعال است و تمامی قابلیت‌ها در دسترس هستند.")
            else:
                self.lbl_status_badge.setText("✅ لایسنس معتبر و فعال است")
                self.lbl_status_badge.setStyleSheet(
                    "background-color: #dcfce7; color: #15803d; font-size: 13px; font-weight: bold; padding: 8px; border-radius: 6px;"
                )
                self.lbl_status_desc.setText(res.message_fa or "تمامی دسترسی‌ها و امضای دیجیتال نرم‌افزار تأیید شدند.")

            info_text = (
                f"<b>نام دارنده:</b> {payload.customer.name}<br>"
                f"<b>شماره لایسنس:</b> {payload.license_id}<br>"
                f"<b>پلن/نسخه:</b> {lic_type_fa}<br>"
                f"<b>تاریخ انقضا:</b> {expiry_text}<br>"
                f"<b>دستگاه‌های مجاز:</b> {payload.max_devices} سیستم<br>"
                f"<b>ماژول‌های فعال:</b> {modules_str}<br>"
                f"<b>شناسه برنامه:</b> <code>{key_fp_str}</code>"
            )
            self.lbl_details.setText(info_text)
            self.details_box.setVisible(True)
            if self.is_startup_gate:
                self.btn_enter.setVisible(True)
                self.btn_enter.setEnabled(True)
            self.btn_remove.setVisible(True)
        else:
            if res.status == ValidationStatus.MISSING:
                self.lbl_status_badge.setText("⚠️ لایسنس فعالی روی این سیستم ثبت نشده است")
                self.lbl_status_badge.setStyleSheet(
                    "background-color: #fef3c7; color: #b45309; font-size: 13px; font-weight: bold; padding: 8px; border-radius: 6px;"
                )
                self.lbl_status_desc.setText(
                    "برای فعال‌سازی نرم‌افزار، لطفاً فایل لایسنس دریافتی از پشتیبانی (.daqlic) را در بخش زیر بارگذاری نمایید."
                )
            elif res.status == ValidationStatus.EXPIRED:
                self.lbl_status_badge.setText("❌ اعتبار زمانی لایسنس به پایان رسیده است")
                self.lbl_status_badge.setStyleSheet(
                    "background-color: #fee2e2; color: #b91c1c; font-size: 13px; font-weight: bold; padding: 8px; border-radius: 6px;"
                )
                self.lbl_status_desc.setText(
                    "مدت زمان اشتراک شما منقضی شده است. جهت تمدید لایسنس با واحد پشتیبانی تماس بگیرید."
                )
            elif res.status in (ValidationStatus.HARDWARE_MISMATCH, ValidationStatus.UNAUTHORIZED_DEVICE):
                self.lbl_status_badge.setText("❌ این لایسنس برای این رایانه مجاز نیست")
                self.lbl_status_badge.setStyleSheet(
                    "background-color: #fee2e2; color: #b91c1c; font-size: 13px; font-weight: bold; padding: 8px; border-radius: 6px;"
                )
                self.lbl_status_desc.setText(
                    "مشخصات سخت‌افزاری این رایانه با مشخصات ثبت‌شده در فایل لایسنس همخوانی ندارد."
                )
            elif res.status in (ValidationStatus.CLOCK_ROLLBACK, ValidationStatus.CLOCK_TAMPERED):
                self.lbl_status_badge.setText("❌ عدم انطباق ساعت یا تاریخ سیستم")
                self.lbl_status_badge.setStyleSheet(
                    "background-color: #fee2e2; color: #b91c1c; font-size: 13px; font-weight: bold; padding: 8px; border-radius: 6px;"
                )
                self.lbl_status_desc.setText(
                    "تاریخ و ساعت سیستم نسبت به زمان ثبت‌شده به عقب بازگردانده شده است. لطفاً ساعت سیستم را تنظیم نمایید."
                )
            else:
                self.lbl_status_badge.setText("❌ لایسنس غیرفعال است")
                self.lbl_status_badge.setStyleSheet(
                    "background-color: #fee2e2; color: #b91c1c; font-size: 13px; font-weight: bold; padding: 8px; border-radius: 6px;"
                )
                msg = res.message_fa or "لایسنس معتبری برای اجرای برنامه یافت نشد."
                if "یافت نشد" in msg and "موجود نیست" in str(res.detail or ""):
                    msg = "لایسنس فعالی روی این سیستم ثبت نشده است. لطفاً فایل لایسنس را بارگذاری نمایید."
                self.lbl_status_desc.setText(msg)

            self.details_box.setVisible(False)
            if self.is_startup_gate:
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
