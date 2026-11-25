# licensing/license_dialog.py
"""Persian RTL PySide6 Activation and License Management Dialog for Daqiq Desktop."""

import html
import os
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QByteArray
from PySide6.QtGui import (
    QIcon,
    QFont,
    QDragEnterEvent,
    QDropEvent,
    QPixmap,
    QPainter,
    QPalette,
    QColor,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QPlainTextEdit,
    QFileDialog,
    QGroupBox,
    QFrame,
    QSizePolicy,
    QScrollArea,
    QWidget,
)

from .license_models import ValidationStatus, ValidationResult
from .license_policy import (
    LicenseService,
    FEATURE_LABELS_FA,
    get_active_features_fa,
    get_grace_mode_label_fa,
)


def _try_update_app_config_theme(is_dark: bool):
    """Safely persist theme preference to app_config.json if possible."""
    try:
        from database import load_app_config, save_app_config
        cfg = load_app_config()
        cfg["theme"] = "dark" if is_dark else "light"
        save_app_config(cfg)
    except Exception:
        pass


def _render_crisp_logo_pixmap(icon_path: Optional[str], target_px: int = 60, dpr: float = 2.0) -> Optional[QPixmap]:
    """Render crisp HiDPI-aware logo preferring vector SVG over raster PNG."""
    candidates = []
    if icon_path:
        base, ext = os.path.splitext(icon_path)
        svg_sibling = f"{base}.svg"
        if ext.lower() != ".svg" and os.path.isfile(svg_sibling):
            candidates.append(svg_sibling)
        candidates.append(icon_path)

    for cand in candidates:
        if not cand or not os.path.isfile(cand):
            continue
        if cand.lower().endswith(".svg"):
            try:
                from PySide6.QtSvg import QSvgRenderer
                with open(cand, "rb") as f:
                    svg_bytes = f.read()
                renderer = QSvgRenderer(QByteArray(svg_bytes))
                if renderer.isValid():
                    phys = max(1, int(round(target_px * max(1.0, dpr))))
                    pix = QPixmap(phys, phys)
                    pix.fill(Qt.transparent)
                    painter = QPainter(pix)
                    painter.setRenderHint(QPainter.Antialiasing, True)
                    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                    renderer.render(painter)
                    painter.end()
                    pix.setDevicePixelRatio(max(1.0, dpr))
                    return pix
            except Exception:
                pass
        pix = QPixmap(cand)
        if not pix.isNull():
            phys = max(1, int(round(target_px * max(1.0, dpr))))
            scaled = pix.scaled(phys, phys, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(max(1.0, dpr))
            return scaled
    return None


def _build_light_palette() -> QPalette:
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#f4f7fb"))
    pal.setColor(QPalette.WindowText, QColor("#0f172a"))
    pal.setColor(QPalette.Base, QColor("#ffffff"))
    pal.setColor(QPalette.AlternateBase, QColor("#f1f5f9"))
    pal.setColor(QPalette.Text, QColor("#0f172a"))
    pal.setColor(QPalette.Button, QColor("#e2e8f0"))
    pal.setColor(QPalette.ButtonText, QColor("#0f172a"))
    pal.setColor(QPalette.Highlight, QColor("#0284c7"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    return pal


def _build_dark_palette() -> QPalette:
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#0b1220"))
    pal.setColor(QPalette.WindowText, QColor("#f8fafc"))
    pal.setColor(QPalette.Base, QColor("#111c30"))
    pal.setColor(QPalette.AlternateBase, QColor("#17253d"))
    pal.setColor(QPalette.Text, QColor("#f8fafc"))
    pal.setColor(QPalette.Button, QColor("#1e293b"))
    pal.setColor(QPalette.ButtonText, QColor("#f8fafc"))
    pal.setColor(QPalette.Highlight, QColor("#38bdf8"))
    pal.setColor(QPalette.HighlightedText, QColor("#0b1220"))
    return pal


class ThemedNoticeDialog(QDialog):
    """Self-contained theme-aware Persian RTL alert/confirmation dialog."""

    _KIND_META = {
        "info": ("ℹ", "#0284c7", "#e0f2fe", "#0c4a6e"),
        "success": ("✓", "#16a34a", "#dcfce7", "#064e3b"),
        "warning": ("!", "#d97706", "#fef3c7", "#451a03"),
        "error": ("✕", "#dc2626", "#fee2e2", "#450a0a"),
        "danger": ("✕", "#dc2626", "#fee2e2", "#450a0a"),
        "question": ("؟", "#0284c7", "#e0f2fe", "#0c4a6e"),
    }

    def __init__(
        self,
        parent=None,
        title: str = "",
        message: str = "",
        *,
        kind: str = "info",
        is_dark_theme: Optional[bool] = None,
        buttons: str = "ok",
        destructive: bool = False,
        details: str = "",
    ):
        super().__init__(parent)
        if is_dark_theme is None:
            is_dark_theme = bool(getattr(parent, "is_dark_theme", False))
        self.is_dark_theme = bool(is_dark_theme)
        self.kind = kind if kind in self._KIND_META else "info"
        self.buttons_mode = buttons
        self.destructive = bool(destructive)
        self.result_button = "no" if buttons == "yes_no" else "ok"

        self.setObjectName("DaqiqNoticeDialogRoot")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setModal(True)
        self.setWindowTitle(title or "اعلان سیستم")
        self.setMinimumWidth(420)
        self.setMaximumWidth(620)
        if parent is not None and hasattr(parent, "windowIcon") and not parent.windowIcon().isNull():
            self.setWindowIcon(parent.windowIcon())

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # Header card with icon badge + Persian title
        self.header_card = QFrame()
        self.header_card.setObjectName("noticeBodyCard")
        card_layout = QVBoxLayout(self.header_card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        symbol, accent_hex, _, _ = self._KIND_META[self.kind]
        self.lbl_icon = QLabel(symbol)
        self.lbl_icon.setObjectName("noticeIconBadge")
        self.lbl_icon.setAlignment(Qt.AlignCenter)
        self.lbl_icon.setFixedSize(40, 40)
        top_row.addWidget(self.lbl_icon, 0, Qt.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(6)
        self.lbl_title = QLabel(title or "اعلان")
        self.lbl_title.setObjectName("noticeTitleLabel")
        self.lbl_title.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_title.setWordWrap(True)
        text_col.addWidget(self.lbl_title)

        self.lbl_message = QLabel(message or "")
        self.lbl_message.setObjectName("noticeMessageLabel")
        self.lbl_message.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self.lbl_message.setWordWrap(True)
        self.lbl_message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text_col.addWidget(self.lbl_message)

        top_row.addLayout(text_col, 1)
        card_layout.addLayout(top_row)

        if details:
            self.txt_details = QPlainTextEdit()
            self.txt_details.setObjectName("noticeDetailsEdit")
            self.txt_details.setReadOnly(True)
            self.txt_details.setLayoutDirection(Qt.LeftToRight)
            self.txt_details.setPlainText(details)
            self.txt_details.setFixedHeight(96)
            card_layout.addWidget(self.txt_details)
        else:
            self.txt_details = None

        root.addWidget(self.header_card)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)

        self.btn_ok = None
        self.btn_yes = None
        self.btn_no = None
        self._action_buttons = []

        if self.buttons_mode == "yes_no":
            self.btn_yes = QPushButton("بله")
            self.btn_yes.setObjectName("noticeDangerBtn" if self.destructive else "noticePrimaryBtn")
            self.btn_yes.setCursor(Qt.PointingHandCursor)
            self.btn_yes.clicked.connect(self._accept_yes)
            btn_row.addWidget(self.btn_yes)

            self.btn_no = QPushButton("خیر")
            self.btn_no.setObjectName("noticeSecondaryBtn")
            self.btn_no.setCursor(Qt.PointingHandCursor)
            self.btn_no.setDefault(True)
            self.btn_no.clicked.connect(self._reject_no)
            btn_row.addWidget(self.btn_no)
            self._action_buttons = [self.btn_yes, self.btn_no]
        else:
            self.btn_ok = QPushButton("تأیید")
            self.btn_ok.setObjectName("noticeDangerBtn" if self.kind in ("error", "danger") else "noticePrimaryBtn")
            self.btn_ok.setCursor(Qt.PointingHandCursor)
            self.btn_ok.setDefault(True)
            self.btn_ok.clicked.connect(self._accept_ok)
            btn_row.addWidget(self.btn_ok)
            self._action_buttons = [self.btn_ok]

        btn_row.addStretch(1)
        root.addLayout(btn_row)

        self._accent_hex = accent_hex
        self._apply_theme()

    def _accept_ok(self):
        self.result_button = "ok"
        self.accept()

    def _accept_yes(self):
        self.result_button = "yes"
        self.accept()

    def _reject_no(self):
        self.result_button = "no"
        self.reject()

    def buttons(self):
        """Return action QPushButtons for consistent dialog inspection."""
        return list(self._action_buttons)

    def _apply_theme(self):
        _, accent_hex, light_badge_bg, dark_badge_bg = self._KIND_META[self.kind]
        if self.is_dark_theme:
            pal = _build_dark_palette()
            bg = "#0b1220"
            card_bg = "#111c30"
            border = "#2a3b58"
            title_fg = "#f8fafc"
            msg_fg = "#e2e8f0"
            badge_bg = dark_badge_bg
            badge_fg = "#f8fafc"
            sec_bg = "#1e293b"
            sec_hover = "#334155"
            sec_fg = "#f8fafc"
            sec_border = "#64748b"
            input_bg = "#0f172a"
        else:
            pal = _build_light_palette()
            bg = "#f4f7fb"
            card_bg = "#ffffff"
            border = "#cbd5e1"
            title_fg = "#0f172a"
            msg_fg = "#1e293b"
            badge_bg = light_badge_bg
            badge_fg = accent_hex
            sec_bg = "#e2e8f0"
            sec_hover = "#cbd5e1"
            sec_fg = "#0f172a"
            sec_border = "#94a3b8"
            input_bg = "#f8fafc"

        self.setPalette(pal)
        qss = f"""
        QDialog#DaqiqNoticeDialogRoot {{
            background-color: {bg};
            color: {title_fg};
            font-family: "Tahoma", "Vazirmatn", "Segoe UI", sans-serif;
        }}
        #DaqiqNoticeDialogRoot QFrame#noticeBodyCard {{
            background-color: {card_bg};
            border: 1px solid {border};
            border-radius: 10px;
        }}
        #DaqiqNoticeDialogRoot QLabel#noticeIconBadge {{
            background-color: {badge_bg};
            color: {badge_fg};
            border: 2px solid {accent_hex};
            border-radius: 20px;
            font-size: 17px;
            font-weight: bold;
        }}
        #DaqiqNoticeDialogRoot QLabel#noticeTitleLabel {{
            background: transparent;
            color: {title_fg};
            font-size: 14px;
            font-weight: bold;
        }}
        #DaqiqNoticeDialogRoot QLabel#noticeMessageLabel {{
            background: transparent;
            color: {msg_fg};
            font-size: 12px;
            line-height: 1.45;
        }}
        #DaqiqNoticeDialogRoot QPlainTextEdit#noticeDetailsEdit {{
            background-color: {input_bg};
            color: {msg_fg};
            border: 1px solid {border};
            border-radius: 6px;
            padding: 6px;
            font-family: "Consolas", "Courier New", monospace;
            font-size: 11px;
        }}
        #DaqiqNoticeDialogRoot QPushButton {{
            min-width: 96px;
            min-height: 32px;
            border-radius: 7px;
            padding: 6px 18px;
            font-size: 12px;
            font-weight: bold;
        }}
        #DaqiqNoticeDialogRoot QPushButton#noticePrimaryBtn {{
            background-color: #0284c7;
            color: #ffffff;
            border: 1px solid #0369a1;
        }}
        #DaqiqNoticeDialogRoot QPushButton#noticePrimaryBtn:hover {{
            background-color: #0369a1;
        }}
        #DaqiqNoticeDialogRoot QPushButton#noticePrimaryBtn:pressed {{
            background-color: #075985;
        }}
        #DaqiqNoticeDialogRoot QPushButton#noticeDangerBtn {{
            background-color: #dc2626;
            color: #ffffff;
            border: 1px solid #b91c1c;
        }}
        #DaqiqNoticeDialogRoot QPushButton#noticeDangerBtn:hover {{
            background-color: #b91c1c;
        }}
        #DaqiqNoticeDialogRoot QPushButton#noticeDangerBtn:pressed {{
            background-color: #991b1b;
        }}
        #DaqiqNoticeDialogRoot QPushButton#noticeSecondaryBtn {{
            background-color: {sec_bg};
            color: {sec_fg};
            border: 1px solid {sec_border};
        }}
        #DaqiqNoticeDialogRoot QPushButton#noticeSecondaryBtn:hover {{
            background-color: {sec_hover};
        }}
        """
        self.setStyleSheet(qss)
        st = self.style()
        for w in [self] + self.findChildren(QWidget):
            try:
                st.unpolish(w)
                st.polish(w)
                w.update()
            except Exception:
                pass


class LicenseDialog(QDialog):
    """Persian RTL activation and license status dialog with 100% isolated Light/Dark theming."""

    def __init__(
        self,
        service: LicenseService,
        parent=None,
        icon_path: Optional[str] = None,
        is_dark_theme: bool = False,
        is_startup_gate: bool = True,
    ):
        super().__init__(parent)
        self.setObjectName("LicenseDialogRoot")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(True)

        self.service = service
        self.icon_path = icon_path
        self.is_dark_theme = bool(is_dark_theme)
        self.is_startup_gate = bool(is_startup_gate)
        self.current_result: Optional[ValidationResult] = None
        self._current_key_fp_text: str = ""
        self._status_state: str = "missing"

        self._key_fp_revert_timer = QTimer(self)
        self._key_fp_revert_timer.setSingleShot(True)
        self._key_fp_revert_timer.timeout.connect(self._restore_key_fp_label)

        self._hw_fp_revert_timer = QTimer(self)
        self._hw_fp_revert_timer.setSingleShot(True)
        self._hw_fp_revert_timer.timeout.connect(self._restore_copy_fp_button)

        self.setWindowTitle("سامانه مدیریت و فعال‌سازی لایسنس دقیق")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setFont(QFont("Tahoma", 10))
        self.setMinimumSize(600, 560)
        self.resize(700, 660)
        self.setAcceptDrops(True)

        if self.icon_path and os.path.exists(self.icon_path):
            self.setWindowIcon(QIcon(self.icon_path))

        self._build_ui()
        self._apply_theme()
        self.refresh_status()

    def accept(self):
        """Enforce fail-closed startup gate: never accept unless license evaluates active/valid."""
        if self.is_startup_gate:
            try:
                res = self.service.check_license(force_reload=True)
            except Exception:
                res = None
            if not res or not res.is_valid:
                self.refresh_status()
                self._show_notice(
                    "لایسنس معتبر نیست",
                    (res.message_fa if res and res.message_fa else "برای ورود به برنامه باید لایسنس معتبر و منقضی‌نشده فعال باشد."),
                    kind="warning",
                )
                return
        super().accept()

    def closeEvent(self, event):
        self._key_fp_revert_timer.stop()
        self._hw_fp_revert_timer.stop()
        super().closeEvent(event)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 14, 16, 12)
        main_layout.setSpacing(10)

        # Header section (symmetrical 3-column grid so title stays geometrically centered)
        self.header_frame = QFrame()
        self.header_frame.setObjectName("licHeaderFrame")
        self.header_frame.setFrameShape(QFrame.NoFrame)
        self.header_grid = QGridLayout(self.header_frame)
        self.header_grid.setContentsMargins(14, 12, 14, 12)
        self.header_grid.setHorizontalSpacing(12)
        self.header_grid.setVerticalSpacing(0)
        self.header_grid.setColumnStretch(0, 0)
        self.header_grid.setColumnStretch(1, 1)
        self.header_grid.setColumnStretch(2, 0)

        # Crisp HiDPI vector logo
        self.icon_lbl = QLabel()
        self.icon_lbl.setObjectName("licLogoLabel")
        self.icon_lbl.setAlignment(Qt.AlignCenter)
        self.icon_lbl.setFixedSize(64, 64)
        dpr = max(1.0, float(self.devicePixelRatioF() or 2.0))
        logo_pix = _render_crisp_logo_pixmap(self.icon_path, target_px=58, dpr=dpr)
        if logo_pix is not None and not logo_pix.isNull():
            self.icon_lbl.setPixmap(logo_pix)
        self.header_grid.addWidget(self.icon_lbl, 0, 0, Qt.AlignLeading | Qt.AlignVCenter)

        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(4)
        self.title_lbl = QLabel("سامانه مدیریت و فعال‌سازی لایسنس دقیق")
        self.title_lbl.setObjectName("licHeaderTitle")
        self.title_lbl.setAlignment(Qt.AlignCenter)
        self.sub_lbl = QLabel("بررسی وضعیت اعتبار، دریافت شناسه دستگاه و فعال‌سازی نرم‌افزار")
        self.sub_lbl.setObjectName("licHeaderSubtitle")
        self.sub_lbl.setAlignment(Qt.AlignCenter)
        self.sub_lbl.setWordWrap(True)
        title_vbox.addWidget(self.title_lbl)
        title_vbox.addWidget(self.sub_lbl)
        self.header_grid.addLayout(title_vbox, 0, 1)

        # Theme toggle button in header
        self.btn_theme_toggle = QPushButton()
        self.btn_theme_toggle.setObjectName("licThemeToggleBtn")
        self.btn_theme_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_theme_toggle.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_theme_toggle.clicked.connect(self._toggle_theme)
        self.header_grid.addWidget(self.btn_theme_toggle, 0, 2, Qt.AlignTrailing | Qt.AlignVCenter)

        main_layout.addWidget(self.header_frame)
        self._sync_header_symmetry()

        # Scrollable container for middle contents
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("licScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.scroll_widget = QWidget()
        self.scroll_widget.setObjectName("licScrollContent")
        self.scroll_widget.setAttribute(Qt.WA_StyledBackground, True)
        self.scroll_widget.setAutoFillBackground(True)
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setContentsMargins(4, 4, 4, 4)
        self.scroll_layout.setSpacing(10)

        # Status Box
        self.status_box = QGroupBox("وضعیت لایسنس")
        self.status_box.setObjectName("licStatusBox")
        self.status_box.setAlignment(Qt.AlignRight)
        sb_layout = QVBoxLayout(self.status_box)
        sb_layout.setSpacing(8)

        self.lbl_status_badge = QLabel("در حال بررسی وضعیت...")
        self.lbl_status_badge.setObjectName("licStatusBadge")
        self.lbl_status_badge.setLayoutDirection(Qt.RightToLeft)
        self.lbl_status_badge.setAlignment(Qt.AlignCenter)
        sb_layout.addWidget(self.lbl_status_badge)

        self.lbl_status_desc = QLabel("")
        self.lbl_status_desc.setObjectName("licStatusDesc")
        self.lbl_status_desc.setWordWrap(True)
        self.lbl_status_desc.setLayoutDirection(Qt.RightToLeft)
        self.lbl_status_desc.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sb_layout.addWidget(self.lbl_status_desc)

        self.scroll_layout.addWidget(self.status_box)

        # Step 1: Hardware Request Box
        self.step1_box = QGroupBox("گام ۱: دریافت فایل مشخصات سیستم")
        self.step1_box.setObjectName("licStep1Box")
        self.step1_box.setAlignment(Qt.AlignRight)
        step1_layout = QVBoxLayout(self.step1_box)
        step1_layout.setSpacing(8)

        self.step1_hint = QLabel(
            "برای صدور یا تمدید لایسنس، فایل مشخصات سیستم (.daqreq) را ذخیره کرده و برای پشتیبانی ارسال کنید:"
        )
        self.step1_hint.setObjectName("licHintLabel")
        self.step1_hint.setWordWrap(True)
        self.step1_hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        step1_layout.addWidget(self.step1_hint)

        hw_row = QHBoxLayout()
        hw_row.setSpacing(8)
        self.ed_hw_fp = QLineEdit()
        self.ed_hw_fp.setObjectName("licHwFpEdit")
        self.ed_hw_fp.setReadOnly(True)
        self.ed_hw_fp.setLayoutDirection(Qt.LeftToRight)
        self.ed_hw_fp.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hw_row.addWidget(self.ed_hw_fp, 1)

        self.btn_copy_fp = QPushButton("کپی شناسه")
        self.btn_copy_fp.setObjectName("licSecondaryBtn")
        self.btn_copy_fp.setCursor(Qt.PointingHandCursor)
        self.btn_copy_fp.setToolTip("کپی شناسه سخت‌افزاری سیستم")
        self.btn_copy_fp.clicked.connect(self._copy_fingerprint)
        hw_row.addWidget(self.btn_copy_fp)

        self.btn_export_req = QPushButton("دریافت فایل مشخصات سیستم")
        self.btn_export_req.setObjectName("licTealBtn")
        self.btn_export_req.setCursor(Qt.PointingHandCursor)
        self.btn_export_req.setToolTip("ایجاد و ذخیره فایل مشخصات سیستم (.daqreq)")
        self.btn_export_req.clicked.connect(self._export_request_flow)
        hw_row.addWidget(self.btn_export_req)

        step1_layout.addLayout(hw_row)
        self.scroll_layout.addWidget(self.step1_box)

        # Step 2: License Import Box
        self.step2_box = QGroupBox("گام ۲: فعال‌سازی لایسنس")
        self.step2_box.setObjectName("licStep2Box")
        self.step2_box.setAlignment(Qt.AlignRight)
        step2_layout = QVBoxLayout(self.step2_box)
        step2_layout.setSpacing(8)

        self.step2_hint = QLabel(
            "فایل لایسنس دریافتی (.daqlic) را انتخاب کنید، به داخل این پنجره بکشید، یا متن فعال‌سازی را وارد نمایید:"
        )
        self.step2_hint.setObjectName("licHintLabel")
        self.step2_hint.setWordWrap(True)
        self.step2_hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        step2_layout.addWidget(self.step2_hint)

        import_row = QHBoxLayout()
        import_row.setSpacing(8)
        self.btn_import_file = QPushButton("انتخاب فایل لایسنس (.daqlic)")
        self.btn_import_file.setObjectName("licPrimaryBtn")
        self.btn_import_file.setCursor(Qt.PointingHandCursor)
        self.btn_import_file.clicked.connect(self._import_license_file_flow)
        import_row.addWidget(self.btn_import_file)

        self.btn_paste_token = QPushButton("درج متن فعال‌سازی")
        self.btn_paste_token.setObjectName("licSlateBtn")
        self.btn_paste_token.setCursor(Qt.PointingHandCursor)
        self.btn_paste_token.clicked.connect(self._toggle_token_box)
        import_row.addWidget(self.btn_paste_token)

        self.btn_retry = QPushButton("بررسی مجدد")
        self.btn_retry.setObjectName("licSecondaryBtn")
        self.btn_retry.setCursor(Qt.PointingHandCursor)
        self.btn_retry.clicked.connect(self.refresh_status)
        import_row.addWidget(self.btn_retry)

        import_row.addStretch()
        step2_layout.addLayout(import_row)

        # Collapsible text token input
        self.token_frame = QFrame()
        self.token_frame.setObjectName("licTokenFrame")
        self.token_frame.setVisible(False)
        t_layout = QVBoxLayout(self.token_frame)
        t_layout.setContentsMargins(0, 6, 0, 2)
        t_layout.setSpacing(6)
        self.txt_token = QPlainTextEdit()
        self.txt_token.setObjectName("licTokenEdit")
        self.txt_token.setPlaceholderText("متن کد فعال‌سازی را در اینجا وارد نمایید...")
        self.txt_token.setFixedHeight(68)
        t_layout.addWidget(self.txt_token)
        self.btn_apply_token = QPushButton("ثبت و فعال‌سازی")
        self.btn_apply_token.setObjectName("licPrimaryBtn")
        self.btn_apply_token.setCursor(Qt.PointingHandCursor)
        self.btn_apply_token.clicked.connect(self._apply_token_flow)
        t_layout.addWidget(self.btn_apply_token)
        step2_layout.addWidget(self.token_frame)

        self.scroll_layout.addWidget(self.step2_box)

        # License Details Area (Visible when valid)
        self.details_box = QGroupBox("اطلاعات لایسنس فعال")
        self.details_box.setObjectName("licDetailsBox")
        self.details_box.setAlignment(Qt.AlignRight)
        dt_layout = QVBoxLayout(self.details_box)

        self.lbl_details = QLabel()
        self.lbl_details.setObjectName("licDetailsLabel")
        self.lbl_details.setWordWrap(True)
        self.lbl_details.setLayoutDirection(Qt.RightToLeft)
        self.lbl_details.setAlignment(Qt.AlignRight | Qt.AlignTop)
        dt_layout.addWidget(self.lbl_details)
        self.scroll_layout.addWidget(self.details_box)
        self.scroll_layout.addStretch(1)

        self.scroll_area.setWidget(self.scroll_widget)
        main_layout.addWidget(self.scroll_area, 1)

        # Action Buttons Footer
        self.footer_frame = QFrame()
        self.footer_frame.setObjectName("licFooterFrame")
        act_row = QHBoxLayout(self.footer_frame)
        act_row.setContentsMargins(0, 4, 0, 0)
        act_row.setSpacing(8)

        self.btn_remove = QPushButton("حذف لایسنس")
        self.btn_remove.setObjectName("licDangerBtn")
        self.btn_remove.setCursor(Qt.PointingHandCursor)
        self.btn_remove.setToolTip("حذف لایسنس فعال از روی این سیستم")
        self.btn_remove.clicked.connect(self._remove_license_flow)
        act_row.addWidget(self.btn_remove)

        act_row.addStretch()

        # Startup gate buttons
        self.btn_enter = QPushButton("ورود به برنامه")
        self.btn_enter.setObjectName("licSuccessBtn")
        self.btn_enter.setCursor(Qt.PointingHandCursor)
        self.btn_enter.clicked.connect(self.accept)
        act_row.addWidget(self.btn_enter)

        self.btn_exit = QPushButton("خروج")
        self.btn_exit.setObjectName("licSlateBtn")
        self.btn_exit.setCursor(Qt.PointingHandCursor)
        self.btn_exit.clicked.connect(self.reject)
        act_row.addWidget(self.btn_exit)

        # In-app close button
        self.btn_close = QPushButton("بستن")
        self.btn_close.setObjectName("licPrimaryBtn")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.accept)
        act_row.addWidget(self.btn_close)

        main_layout.addWidget(self.footer_frame)

        # Clickable Security Key ID Footer (exact label: شناسه امنیتی برنامه)
        self.lbl_key_fp = QLabel("شناسه امنیتی برنامه: در حال بارگذاری...")
        self.lbl_key_fp.setObjectName("licKeyFpFooter")
        self.lbl_key_fp.setAlignment(Qt.AlignCenter)
        self.lbl_key_fp.setCursor(Qt.PointingHandCursor)
        self.lbl_key_fp.setToolTip("برای کپی کردن شناسه امنیتی برنامه کلیک کنید")
        self.lbl_key_fp.mousePressEvent = self._copy_key_fingerprint
        main_layout.addWidget(self.lbl_key_fp)

    def _sync_header_symmetry(self):
        """Match left and right header column widths so title remains centered."""
        if not hasattr(self, "header_grid"):
            return
        toggle_w = int(self.btn_theme_toggle.sizeHint().width() or 0)
        icon_w = int(self.icon_lbl.width() or 64)
        side_w = max(icon_w, toggle_w, 132)
        self.header_grid.setColumnMinimumWidth(0, side_w)
        self.header_grid.setColumnMinimumWidth(2, side_w)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_header_symmetry()

    def _toggle_theme(self):
        """Toggle between Dark and Light mode and apply immediately."""
        self.is_dark_theme = not self.is_dark_theme
        _try_update_app_config_theme(self.is_dark_theme)
        self._apply_theme()

    def _style_status_badge(self):
        """Style status badge cleanly for current theme and validation state."""
        state = getattr(self, "_status_state", "missing")
        if self.is_dark_theme:
            palette_map = {
                "valid": ("#064e3b", "#6ee7b7", "#10b981"),
                "grace": ("#451a03", "#fcd34d", "#f59e0b"),
                "trial": ("#1e1b4b", "#a5b4fc", "#6366f1"),
                "invalid": ("#450a0a", "#fca5a5", "#ef4444"),
            }
        else:
            palette_map = {
                "valid": ("#dcfce7", "#15803d", "#86efac"),
                "grace": ("#fef3c7", "#b45309", "#fcd34d"),
                "trial": ("#e0e7ff", "#3730a3", "#a5b4fc"),
                "invalid": ("#fee2e2", "#b91c1c", "#fca5a5"),
            }
        bg, fg, border = palette_map.get(state, palette_map["invalid"])
        self.lbl_status_badge.setStyleSheet(
            f"#LicenseDialogRoot QLabel#licStatusBadge {{ "
            f"background-color: {bg}; color: {fg}; border: 1px solid {border}; "
            f"font-size: 13px; font-weight: bold; padding: 9px 12px; border-radius: 8px; }}"
        )

    def _apply_theme(self):
        """Apply 100% self-contained Light or Dark styling isolated from parent QApplication QSS."""
        if self.is_dark_theme:
            pal = _build_dark_palette()
            bg = "#0b1220"
            card_bg = "#111c30"
            input_bg = "#17253d"
            border = "#2a3b58"
            text = "#f8fafc"
            sub_text = "#cbd5e1"
            muted = "#94a3b8"
            group_title = "#38bdf8"
            header_grad = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0f172a, stop:1 #1e3a8a)"
            header_border = "#334155"
            sec_bg = "#1e293b"
            sec_hover = "#334155"
            sec_fg = "#f8fafc"
            sec_border = "#475569"
            danger_bg = "#991b1b"
            danger_hover = "#b91c1c"
            danger_fg = "#fef2f2"
            danger_border = "#f87171"
            scroll_track = "#111c30"
            scroll_handle = "#334155"
            self.btn_theme_toggle.setText("☀️ حالت روشن")
        else:
            pal = _build_light_palette()
            bg = "#f4f7fb"
            card_bg = "#ffffff"
            input_bg = "#f8fafc"
            border = "#cbd5e1"
            text = "#0f172a"
            sub_text = "#334155"
            muted = "#475569"
            group_title = "#0369a1"
            header_grad = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1e3a8a, stop:1 #0284c7)"
            header_border = "#0284c7"
            sec_bg = "#f1f5f9"
            sec_hover = "#e2e8f0"
            sec_fg = "#0f172a"
            sec_border = "#cbd5e1"
            danger_bg = "#fee2e2"
            danger_hover = "#fecaca"
            danger_fg = "#991b1b"
            danger_border = "#ef4444"
            scroll_track = "#e2e8f0"
            scroll_handle = "#94a3b8"
            self.btn_theme_toggle.setText("🌙 حالت تاریک")

        # Reset QPalette across root and scroll viewport so parent Dark QPalette never bleeds into Light mode
        for target in (self, self.scroll_area, self.scroll_area.viewport(), self.scroll_widget):
            target.setPalette(pal)

        qss = f"""
        QDialog#LicenseDialogRoot {{
            background-color: {bg};
            color: {text};
        }}
        #LicenseDialogRoot QWidget,
        #LicenseDialogRoot QWidget#licScrollContent {{
            background-color: {bg};
            color: {text};
        }}
        #LicenseDialogRoot QScrollArea#licScrollArea {{
            background-color: {bg};
            border: none;
        }}
        #LicenseDialogRoot QFrame#licHeaderFrame {{
            background: {header_grad};
            border: 1px solid {header_border};
            border-radius: 10px;
        }}
        #LicenseDialogRoot QLabel#licLogoLabel {{
            background: transparent;
            border: none;
        }}
        #LicenseDialogRoot QLabel#licHeaderTitle {{
            background: transparent;
            color: #ffffff;
            font-size: 15px;
            font-weight: bold;
        }}
        #LicenseDialogRoot QLabel#licHeaderSubtitle {{
            background: transparent;
            color: #e2e8f0;
            font-size: 11px;
        }}
        #LicenseDialogRoot QFrame#licFooterFrame,
        #LicenseDialogRoot QFrame#licTokenFrame {{
            background: transparent;
            border: none;
        }}
        #LicenseDialogRoot QGroupBox {{
            background-color: {card_bg};
            color: {group_title};
            border: 1px solid {border};
            border-radius: 9px;
            margin-top: 10px;
            padding: 14px 12px 12px 12px;
            font-weight: bold;
        }}
        #LicenseDialogRoot QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top right;
            padding: 0 8px;
            color: {group_title};
            background-color: {card_bg};
        }}
        #LicenseDialogRoot QLabel {{
            background: transparent;
            color: {text};
        }}
        #LicenseDialogRoot QLabel#licHintLabel {{
            color: {sub_text};
            font-size: 11px;
            font-weight: normal;
        }}
        #LicenseDialogRoot QLabel#licStatusDesc {{
            color: {text};
            font-size: 11.5px;
            font-weight: normal;
            padding: 4px 2px;
        }}
        #LicenseDialogRoot QLabel#licDetailsLabel {{
            color: {text};
            font-size: 11px;
            font-weight: normal;
            line-height: 1.7;
        }}
        #LicenseDialogRoot QLabel#licKeyFpFooter {{
            color: {muted};
            font-size: 11px;
            font-family: Consolas, monospace;
            padding: 4px 6px;
        }}
        #LicenseDialogRoot QLineEdit,
        #LicenseDialogRoot QPlainTextEdit {{
            background-color: {input_bg};
            color: {text};
            border: 1px solid {border};
            border-radius: 6px;
            padding: 6px 8px;
            selection-background-color: #0284c7;
            selection-color: #ffffff;
        }}
        #LicenseDialogRoot QLineEdit#licHwFpEdit {{
            font-family: Consolas, monospace;
            font-size: 11px;
        }}
        #LicenseDialogRoot QPlainTextEdit#licTokenEdit {{
            font-family: Consolas, monospace;
            font-size: 10px;
        }}
        #LicenseDialogRoot QPushButton {{
            border-radius: 6px;
            padding: 7px 14px;
            font-weight: bold;
            border: 1px solid transparent;
        }}
        #LicenseDialogRoot QPushButton#licThemeToggleBtn {{
            background-color: rgba(255, 255, 255, 0.16);
            color: #ffffff;
            border: 1px solid rgba(255, 255, 255, 0.35);
            padding: 6px 12px;
        }}
        #LicenseDialogRoot QPushButton#licThemeToggleBtn:hover {{
            background-color: rgba(255, 255, 255, 0.28);
        }}
        #LicenseDialogRoot QPushButton#licPrimaryBtn {{
            background-color: #0284c7;
            color: #ffffff;
        }}
        #LicenseDialogRoot QPushButton#licPrimaryBtn:hover {{
            background-color: #0369a1;
        }}
        #LicenseDialogRoot QPushButton#licTealBtn {{
            background-color: #0d9488;
            color: #ffffff;
        }}
        #LicenseDialogRoot QPushButton#licTealBtn:hover {{
            background-color: #0f766e;
        }}
        #LicenseDialogRoot QPushButton#licSuccessBtn {{
            background-color: #16a34a;
            color: #ffffff;
            font-size: 12px;
            padding: 7px 20px;
        }}
        #LicenseDialogRoot QPushButton#licSuccessBtn:hover {{
            background-color: #15803d;
        }}
        #LicenseDialogRoot QPushButton#licSlateBtn {{
            background-color: #475569;
            color: #ffffff;
        }}
        #LicenseDialogRoot QPushButton#licSlateBtn:hover {{
            background-color: #334155;
        }}
        #LicenseDialogRoot QPushButton#licSecondaryBtn {{
            background-color: {sec_bg};
            color: {sec_fg};
            border: 1px solid {sec_border};
        }}
        #LicenseDialogRoot QPushButton#licSecondaryBtn:hover {{
            background-color: {sec_hover};
        }}
        #LicenseDialogRoot QPushButton#licDangerBtn {{
            background-color: {danger_bg};
            color: {danger_fg};
            border: 1px solid {danger_border};
        }}
        #LicenseDialogRoot QPushButton#licDangerBtn:hover {{
            background-color: {danger_hover};
        }}
        #LicenseDialogRoot QScrollBar:vertical {{
            width: 10px;
            background: {scroll_track};
            border-radius: 5px;
            margin: 0px;
        }}
        #LicenseDialogRoot QScrollBar::handle:vertical {{
            min-height: 28px;
            background: {scroll_handle};
            border-radius: 5px;
        }}
        #LicenseDialogRoot QScrollBar::add-line:vertical,
        #LicenseDialogRoot QScrollBar::sub-line:vertical {{
            height: 0px;
            border: none;
            background: transparent;
        }}
        """
        self.setStyleSheet(qss)
        self._style_status_badge()
        self._sync_header_symmetry()

        # Force Qt style re-polish across the dialog tree to eliminate any parent QSS cache bleed
        st = self.style()
        for w in [self, self.scroll_area, self.scroll_area.viewport(), self.scroll_widget] + self.findChildren(QWidget):
            try:
                st.unpolish(w)
                st.polish(w)
                w.update()
            except Exception:
                pass

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

    def _restore_key_fp_label(self):
        fp_str = self._current_key_fp_text or "پیش‌فرض"
        self.lbl_key_fp.setText(f"شناسه امنیتی برنامه: {fp_str}")

    def _copy_key_fingerprint(self, event=None):
        """Copy active security ID to clipboard with safe auto-revert timer."""
        raw_fp = getattr(self, "_current_key_fp_text", "")
        if raw_fp:
            app = QApplication.instance()
            if app:
                app.clipboard().setText(raw_fp)
                self._key_fp_revert_timer.stop()
                self.lbl_key_fp.setText("شناسه امنیتی برنامه کپی شد ✓")
                self._key_fp_revert_timer.start(2500)

    def _restore_copy_fp_button(self):
        self.btn_copy_fp.setText("کپی شناسه")

    def refresh_status(self):
        """Re-evaluate licensing state and update dialog controls."""
        try:
            fp = self.service.get_hardware_fingerprint()
            self.ed_hw_fp.setText(fp)
        except Exception:
            self.ed_hw_fp.setText("خطا در دریافت شناسه سخت‌افزاری")

        res = self.service.check_license(force_reload=True)
        self.current_result = res

        sec_id = None
        getter = getattr(self.service, "get_app_security_id_display", None)
        if callable(getter):
            cand = getter()
            if isinstance(cand, str) and cand.strip():
                sec_id = cand
        if sec_id:
            self._current_key_fp_text = sec_id
        else:
            fps = self.service.get_active_key_fingerprints()
            if fps:
                first_fp = fps[0]
                if isinstance(first_fp, dict):
                    self._current_key_fp_text = str(
                        first_fp.get("display") or first_fp.get("fingerprint") or "نامشخص"
                    )
                else:
                    self._current_key_fp_text = str(first_fp)
            else:
                self._current_key_fp_text = "نامشخص"
        key_fp_str = self._current_key_fp_text
        self._key_fp_revert_timer.stop()
        self._restore_key_fp_label()

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
                "trial": "آزمایشی",
            }
            lic_type_fa = lic_type_map.get(payload.license_type, payload.license_type)

            expiry_text = "نامحدود"
            if payload.expires_at:
                try:
                    import jdatetime
                    from .license_verifier import parse_iso8601_utc
                    dt = parse_iso8601_utc(payload.expires_at, end_of_day_if_date_only=True)
                    jdt = jdatetime.datetime.fromgregorian(datetime=dt)
                    expiry_text = f"{jdt.strftime('%Y/%m/%d %H:%M')} (میلادی: {dt.strftime('%Y-%m-%d')})"
                except Exception:
                    expiry_text = payload.expires_at

            active_modules = get_active_features_fa(payload.features)
            modules_str = "، ".join(active_modules) if active_modules else "هیچ ماژولی فعال نیست"
            support_phone = ""
            try:
                support_phone = str(self.service.get_support_phone() or "").strip()
            except Exception:
                support_phone = ""

            if res.in_grace_period:
                self._status_state = "grace"
                mode_fa = get_grace_mode_label_fa(res.grace_mode)
                rem_grace = (
                    f"{res.grace_days_remaining} روز باقیمانده"
                    if res.grace_days_remaining is not None
                    else "فعال"
                )
                self.lbl_status_badge.setText(f"دوره مهلت لایسنس ({rem_grace} • {mode_fa})")
                mode_hint = (
                    "امکان مشاهده گزارش‌ها، پشتیبان‌گیری و دریافت خروجی اکسل فعال است؛ ثبت یا ویرایش داده جدید تا زمان تمدید محدود شده است."
                    if res.grace_mode == "readonly"
                    else "دسترسی کامل نرم‌افزار در طول دوره مهلت فعال است؛ لطفاً پیش از اتمام مهلت نسبت به تمدید اقدام فرمایید."
                )
                desc_html = (
                    f'<div dir="rtl" align="right">'
                    f"لایسنس شما به پایان رسیده است و هم‌اکنون در دوره مهلت موقت قرار دارید ({html.escape(rem_grace)}، حالت {html.escape(mode_fa)}). "
                    f"{html.escape(mode_hint)}"
                )
                if support_phone:
                    desc_html += (
                        f'<br><b>تماس با پشتیبانی جهت تمدید:</b> '
                        f'<span dir="ltr">{html.escape(support_phone)}</span>'
                    )
                desc_html += "</div>"
                self.lbl_status_desc.setText(desc_html)
            elif res.is_trial:
                self._status_state = "trial"
                rem = f" ({res.days_remaining} روز باقیمانده)" if res.days_remaining is not None else ""
                self.lbl_status_badge.setText(f"نسخه آزمایشی فعال است{rem}")
                desc_text = "تمامی بررسی‌های امنیتی و اعتبار لایسنس با موفقیت تأیید شدند."
                self.lbl_status_desc.setText(
                    f'<div dir="rtl" align="right">{html.escape(desc_text)}</div>'
                )
            else:
                self._status_state = "valid"
                self.lbl_status_badge.setText("لایسنس معتبر و فعال است")
                desc_text = res.message_fa or "تمامی بررسی‌های امنیتی و اعتبار لایسنس با موفقیت تأیید شدند."
                self.lbl_status_desc.setText(
                    f'<div dir="rtl" align="right">{html.escape(desc_text)}</div>'
                )

            info_text = (
                '<div dir="rtl" align="right">'
                f"<b>نام دارنده:</b> {html.escape(str(payload.customer.name))}<br>"
                f"<b>شماره لایسنس:</b> {html.escape(str(payload.license_id))}<br>"
                f"<b>نوع اشتراک:</b> {html.escape(str(lic_type_fa))}<br>"
                f"<b>تاریخ انقضا:</b> {html.escape(str(expiry_text))}<br>"
                f"<b>دستگاه‌های مجاز:</b> {payload.max_devices} سیستم<br>"
                f"<b>بخش‌های فعال:</b> {html.escape(modules_str)}<br>"
                f"<b>شناسه امنیتی برنامه:</b> <code>{html.escape(key_fp_str)}</code>"
                "</div>"
            )
            self.lbl_details.setText(info_text)
            self.details_box.setVisible(True)
            if self.is_startup_gate:
                self.btn_enter.setVisible(True)
                self.btn_enter.setEnabled(True)
            self.btn_remove.setVisible(True)
        else:
            self._status_state = "invalid"
            support_phone = ""
            try:
                support_phone = str(self.service.get_support_phone() or "").strip()
            except Exception:
                support_phone = ""

            if res.status == ValidationStatus.MISSING:
                self.lbl_status_badge.setText("لایسنس فعال نیست")
                friendly_msg = "لایسنس فعالی روی این سیستم ثبت نشده است. برای فعال‌سازی، فایل لایسنس خود را بارگذاری کنید."
            elif res.status == ValidationStatus.EXPIRED:
                self.lbl_status_badge.setText("اعتبار لایسنس به پایان رسیده است")
                friendly_msg = res.message_fa or "اعتبار این لایسنس به پایان رسیده است. لطفاً برای تمدید با پشتیبانی تماس بگیرید."
            elif res.status in (ValidationStatus.CLOCK_ROLLBACK, ValidationStatus.CLOCK_TAMPERED):
                self.lbl_status_badge.setText("نیاز به همگام‌سازی ساعت سیستم")
                friendly_msg = res.message_fa or "ساعت سیستم نیاز به تنظیم دارد. لطفاً ساعت و تاریخ ویندوز را تنظیم نمایید."
            else:
                self.lbl_status_badge.setText("لایسنس معتبر نیست")
                friendly_msg = res.message_fa or "فایل لایسنس معتبر نیست. لطفاً فایل صحیح را انتخاب کنید."

            desc_html = f'<div dir="rtl" align="right">{html.escape(friendly_msg)}'
            if support_phone and res.status in (
                ValidationStatus.MISSING,
                ValidationStatus.EXPIRED,
                ValidationStatus.CLOCK_ROLLBACK,
                ValidationStatus.CLOCK_TAMPERED,
                ValidationStatus.UNAUTHORIZED_DEVICE,
                ValidationStatus.HARDWARE_MISMATCH,
                ValidationStatus.INVALID_SIGNATURE,
                ValidationStatus.CORRUPTED_LICENSE,
            ):
                desc_html += (
                    f'<br><b>شماره پشتیبانی جهت دریافت یا تمدید لایسنس:</b> '
                    f'<span dir="ltr">{html.escape(support_phone)}</span>'
                )
            desc_html += "</div>"
            self.lbl_status_desc.setText(desc_html)
            self.details_box.setVisible(False)
            if self.is_startup_gate:
                self.btn_enter.setVisible(False)
                self.btn_enter.setEnabled(False)
            self.btn_remove.setVisible(False)

        self._style_status_badge()

    def _copy_fingerprint(self):
        """Copy the hardware fingerprint to system clipboard."""
        fp = self.ed_hw_fp.text().strip()
        if fp and not fp.startswith("خطا"):
            app = QApplication.instance()
            if app:
                app.clipboard().setText(fp)
                self._hw_fp_revert_timer.stop()
                self.btn_copy_fp.setText("کپی شد ✓")
                self._hw_fp_revert_timer.start(2500)

    def _show_notice(
        self,
        title: str,
        message: str,
        *,
        kind: str = "info",
        buttons: str = "ok",
        destructive: bool = False,
    ) -> int:
        dlg = ThemedNoticeDialog(
            parent=self,
            title=title,
            message=message,
            kind=kind,
            is_dark_theme=self.is_dark_theme,
            buttons=buttons,
            destructive=destructive,
        )
        return dlg.exec()

    def _export_request_flow(self):
        """Prompt user to save .daqreq hardware request file."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "دریافت فایل مشخصات سیستم",
            "Daqiq_Hardware_Request.daqreq",
            "Daqiq Request (*.daqreq);;JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            self.service.export_device_request_file(path)
            self._show_notice(
                "ذخیره موفق",
                f"فایل مشخصات سیستم با موفقیت ذخیره شد:\n{path}\n\nلطفاً این فایل را برای پشتیبانی ارسال فرمایید.",
                kind="success",
            )
        except Exception as e:
            self._show_notice(
                "خطا در ذخیره فایل",
                f"امکان ذخیره فایل مشخصات سیستم وجود ندارد:\n{e}",
                kind="error",
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
            self._show_notice(
                "فعال‌سازی موفق",
                "لایسنس با موفقیت بررسی و بر روی این سیستم فعال شد.",
                kind="success",
            )
        else:
            msg = res.message_fa or "فایل لایسنس انتخاب‌شده معتبر نیست."
            self._show_notice(
                "خطا در فعال‌سازی",
                msg,
                kind="warning",
            )
        self.refresh_status()

    def _apply_token_flow(self):
        token = self.txt_token.toPlainText().strip()
        if not token:
            return
        res = self.service.import_license_token(token)
        if res.is_valid:
            self._show_notice(
                "فعال‌سازی موفق",
                "لایسنس با موفقیت بررسی و ثبت شد.",
                kind="success",
            )
            self.txt_token.clear()
            self.token_frame.setVisible(False)
        else:
            msg = res.message_fa or "کد واردشده معتبر نیست."
            self._show_notice(
                "خطا در فعال‌سازی",
                msg,
                kind="warning",
            )
        self.refresh_status()

    def _remove_license_flow(self):
        """Remove active license after user confirmation."""
        confirm = self._show_notice(
            "تأیید حذف لایسنس",
            "آیا از حذف لایسنس فعال از روی این سیستم اطمینان دارید؟\nپس از حذف، تا زمان ثبت لایسنس جدید، دسترسی به بخش‌های برنامه متوقف خواهد شد.",
            kind="question",
            buttons="yes_no",
            destructive=True,
        )
        if confirm == QDialog.Accepted:
            self.service.remove_license()
            self._show_notice(
                "حذف لایسنس",
                "لایسنس با موفقیت از این سیستم حذف شد.",
                kind="info",
            )
            self.refresh_status()
