# utils_and_widgets.py
import os
import sys
import datetime
import re
import weakref
import html
import jdatetime

def resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev, Nuitka standalone, and Nuitka onefile."""
    # 1. Check relative to sys.executable (Nuitka compiled standalone/onefile)
    try:
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidate = os.path.normpath(os.path.join(exe_dir, relative_path))
        if os.path.exists(candidate):
            return candidate
    except Exception:
        pass

    # 2. Legacy extraction directory (_MEIPASS fallback if present)
    if hasattr(sys, "_MEIPASS"):
        candidate = os.path.normpath(os.path.join(sys._MEIPASS, relative_path))
        if os.path.exists(candidate):
            return candidate

    # 3. Source directory relative to this file
    base_path = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.normpath(os.path.join(base_path, relative_path))
    if os.path.exists(candidate):
        return candidate

    return os.path.normpath(os.path.join(base_path, relative_path))

from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QComboBox,
    QCompleter,
    QDialog,
    QGridLayout,
    QSpinBox,
    QGroupBox,
    QFormLayout,
    QScrollArea,
    QTableWidget,
    QListWidget,
    QAbstractItemView,
)
from PySide6.QtCore import (
    Qt,
    Signal,
    QEvent,
    QModelIndex,
    QSortFilterProxyModel,
    QPropertyAnimation,
    QEasingCurve,
    QAbstractAnimation,
    QTimer,
)
from PySide6.QtGui import QColor, QIntValidator, QPalette
from PySide6.QtWidgets import QApplication, QSizePolicy


def resolve_active_dark_theme(parent=None, db=None, default: bool = False) -> bool:
    """Resolve active Light/Dark theme from db, ancestor widget, or persisted app_config.json."""
    if db is not None and isinstance(getattr(db, "cfg", None), dict):
        return str(db.cfg.get("theme", "light")).strip().lower() == "dark"
    node = parent
    visited = set()
    while node is not None and id(node) not in visited:
        visited.add(id(node))
        explicit = getattr(node, "is_dark_theme", None)
        if isinstance(explicit, bool):
            return explicit
        node_db = getattr(node, "db", None)
        if node_db is not None and isinstance(getattr(node_db, "cfg", None), dict):
            return str(node_db.cfg.get("theme", "light")).strip().lower() == "dark"
        node = node.parentWidget() if hasattr(node, "parentWidget") else None
    app = QApplication.instance()
    if app is not None:
        active_win = app.activeWindow()
        candidates = ([active_win] if active_win is not None else []) + list(app.topLevelWidgets())
        for w in candidates:
            if w is None or not getattr(w, "isVisible", lambda: False)():
                continue
            explicit = getattr(w, "is_dark_theme", None)
            if isinstance(explicit, bool):
                return explicit
            w_db = getattr(w, "db", None)
            if w_db is not None and isinstance(getattr(w_db, "cfg", None), dict):
                return str(w_db.cfg.get("theme", "light")).strip().lower() == "dark"
    try:
        from database import load_app_config
        cfg = load_app_config()
        if isinstance(cfg, dict) and "theme" in cfg:
            return str(cfg.get("theme", "light")).strip().lower() == "dark"
    except Exception:
        pass
    return bool(default)


def build_theme_palette(is_dark: bool) -> QPalette:
    """Construct an explicit Light/Dark QPalette so OS/global themes never bleed into popups."""
    pal = QPalette()
    if is_dark:
        pal.setColor(QPalette.Window, QColor("#0f172a"))
        pal.setColor(QPalette.WindowText, QColor("#f8fafc"))
        pal.setColor(QPalette.Base, QColor("#1e293b"))
        pal.setColor(QPalette.AlternateBase, QColor("#263449"))
        pal.setColor(QPalette.Text, QColor("#f8fafc"))
        pal.setColor(QPalette.Button, QColor("#334155"))
        pal.setColor(QPalette.ButtonText, QColor("#f8fafc"))
        pal.setColor(QPalette.Highlight, QColor("#2563eb"))
        pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    else:
        pal.setColor(QPalette.Window, QColor("#f8fafc"))
        pal.setColor(QPalette.WindowText, QColor("#0f172a"))
        pal.setColor(QPalette.Base, QColor("#ffffff"))
        pal.setColor(QPalette.AlternateBase, QColor("#f1f5f9"))
        pal.setColor(QPalette.Text, QColor("#0f172a"))
        pal.setColor(QPalette.Button, QColor("#e2e8f0"))
        pal.setColor(QPalette.ButtonText, QColor("#0f172a"))
        pal.setColor(QPalette.Highlight, QColor("#2563eb"))
        pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    return pal


def apply_dialog_theme(dialog, is_dark=None, *, parent=None, db=None, include_message_box: bool = True) -> bool:
    """Apply consistent RTL Light/Dark QPalette and QSS to any QDialog/QMessageBox popup."""
    if is_dark is None:
        is_dark = resolve_active_dark_theme(parent=parent or dialog, db=db)
    dark = bool(is_dark)
    if hasattr(dialog, "is_dark_theme"):
        dialog.is_dark_theme = dark
    dialog.setAttribute(Qt.WA_StyledBackground, True)
    dialog.setAutoFillBackground(True)
    dialog.setLayoutDirection(Qt.RightToLeft)
    dialog.setPalette(build_theme_palette(dark))

    if dark:
        bg = "#0f172a"
        panel = "#1e293b"
        fg = "#f8fafc"
        muted = "#cbd5e1"
        input_bg = "#1e293b"
        border = "#475569"
        hover = "#334155"
        sec_bg = "#334155"
        sec_fg = "#f8fafc"
        sec_border = "#64748b"
        sec_hover = "#475569"
    else:
        bg = "#f8fafc"
        panel = "#ffffff"
        fg = "#0f172a"
        muted = "#475569"
        input_bg = "#ffffff"
        border = "#cbd5e1"
        hover = "#e2e8f0"
        sec_bg = "#e2e8f0"
        sec_fg = "#0f172a"
        sec_border = "#94a3b8"
        sec_hover = "#cbd5e1"

    selector = "QDialog, QMessageBox" if include_message_box else "QDialog"
    qss = f"""
        {selector} {{
            background-color: {bg};
            color: {fg};
            font-family: 'Segoe UI', 'Tahoma', sans-serif;
        }}
        QLabel {{
            background: transparent;
            color: {fg};
        }}
        QLabel#settingsHint {{
            color: {muted};
            font-size: 11px;
        }}
        QGroupBox {{
            background-color: {panel};
            color: {fg};
            border: 1px solid {border};
            border-radius: 8px;
            margin-top: 12px;
            padding-top: 14px;
            font-weight: bold;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top right;
            right: 12px;
            padding: 0 8px;
            color: {muted};
        }}
        QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {{
            background-color: {input_bg};
            color: {fg};
            border: 1px solid {border};
            border-radius: 6px;
            padding: 6px 8px;
            min-height: 24px;
        }}
        QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
            border: 1.5px solid #3b82f6;
        }}
        QComboBox QAbstractItemView, QListWidget, QScrollArea, QWidget#scrollContent {{
            background-color: {input_bg};
            color: {fg};
            border: 1px solid {border};
        }}
        QComboBox QAbstractItemView::item:hover, QListWidget::item:hover {{
            background-color: {hover};
            color: {fg};
        }}
        QComboBox QAbstractItemView::item:selected, QListWidget::item:selected {{
            background-color: #2563eb;
            color: #ffffff;
        }}
        QCheckBox, QRadioButton {{
            background: transparent;
            color: {fg};
            spacing: 8px;
            font-weight: bold;
        }}
        QCheckBox::indicator, QRadioButton::indicator {{
            width: 17px;
            height: 17px;
            border: 1.5px solid {sec_border};
            background-color: {input_bg};
            border-radius: 4px;
        }}
        QRadioButton::indicator {{
            border-radius: 9px;
        }}
        QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
            background-color: #2563eb;
            border: 1.5px solid #1d4ed8;
        }}
        QPushButton {{
            background-color: #0284c7;
            color: #ffffff;
            border: 1px solid #0369a1;
            border-radius: 6px;
            padding: 7px 16px;
            font-weight: bold;
            min-height: 26px;
        }}
        QPushButton:hover {{
            background-color: #0369a1;
        }}
        QPushButton#btnSuccess {{
            background-color: #059669;
            color: #ffffff;
            border: 1px solid #047857;
        }}
        QPushButton#btnSuccess:hover {{
            background-color: #047857;
        }}
        QPushButton#btnDanger {{
            background-color: #dc2626;
            color: #ffffff;
            border: 1px solid #b91c1c;
        }}
        QPushButton#btnDanger:hover {{
            background-color: #b91c1c;
        }}
        QPushButton#btnSecondary {{
            background-color: {sec_bg};
            color: {sec_fg};
            border: 1px solid {sec_border};
        }}
        QPushButton#btnSecondary:hover {{
            background-color: {sec_hover};
        }}
    """
    dialog.setStyleSheet(qss)
    st = dialog.style()
    if st is not None:
        for w in [dialog] + dialog.findChildren(QWidget):
            try:
                st.unpolish(w)
                st.polish(w)
                w.update()
            except Exception:
                pass
    return dark

PERSIAN_ARABIC_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

_LTR_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9._/+%-]*:|[A-Za-z][A-Za-z0-9._/+%-]*|\d+(?:[.,]\d+)?(?:[A-Za-z]+|%))"
)
_BIDI_CONTROL_RE = re.compile(r"[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def bidi_isolate_text(value) -> str:
    """Return clean logical text. Widgets choose paragraph direction; data stays unmarked."""
    text = "" if value is None else str(value)
    return _BIDI_CONTROL_RE.sub("", text).translate(
        dict.fromkeys(map(ord, "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"))
    )


def strip_bidi_controls(value) -> str:
    """Remove invisible directional controls before searching or parsing visible UI text."""
    return _BIDI_CONTROL_RE.sub("", "" if value is None else str(value))


def mixed_bidi_tooltip(value) -> str:
    """Render mixed Persian/English tooltip lines with explicit paragraph direction."""
    rendered = []
    for line in str(value or "").splitlines():
        direction = "ltr" if re.search(r"[A-Za-z]", line) else "rtl"
        alignment = "left" if direction == "ltr" else "right"
        rendered.append(
            f'<div dir="{direction}" align="{alignment}" '
            f'style="direction:{direction}; text-align:{alignment}; '
            f'width:100%; white-space:pre-wrap;">'
            f'{html.escape(line)}</div>'
        )
    return (
        '<html dir="rtl"><body dir="rtl" align="right" '
        'style="direction:rtl; text-align:right; width:100%; '
        'margin:0; padding:4px;">'
        + "".join(rendered)
        + "</body></html>"
    )


def normalize_catalog_label(value) -> str:
    """Canonical comparison key for Persian labels with optional spaces/ZWNJ."""
    text = "" if value is None else str(value)
    text = text.replace("\u064a", "\u06cc").replace("\u0643", "\u06a9")
    text = text.replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    return re.sub(r"\s+", "", text).casefold()


def _unique_catalog_labels(values):
    """Deduplicate labels by their normalized Persian/Latin spelling."""
    result = []
    seen = set()
    for value in values or []:
        label = str(value).strip()
        key = normalize_catalog_label(label)
        if label and key and key not in seen:
            seen.add(key)
            result.append(label)
    return result

# Taxonomy constants are dynamically populated from external seed or database config; no hardcoded taxonomy in source.
MAIN_CATEGORIES = []
DEFAULT_SUBCATEGORIES = {}
CPU_LIST = []
RAM_CAPACITIES = []
STORAGE_LIST = []
GPU_LIST = []
DEFAULT_COLORS = []
DEFAULT_ATTRIBUTES = {}


def normalize_digits(text: str) -> str:
    if not text:
        return ""
    return str(text).translate(PERSIAN_ARABIC_MAP)


def auto_capitalize_first_char(text: str) -> str:
    """Uppercase ONLY the first Latin letter if lowercased, leaving all remaining characters untouched (REQ-1).
    Does NOT use str.capitalize() to avoid destroying mixed-case hardware strings (e.g. DDR4, NVMe, Core i7, RTX 4060).
    """
    if not text:
        return ""
    text = normalize_digits(text)
    for i, ch in enumerate(text):
        if ch.isspace():
            continue
        if ch.islower():
            return text[:i] + ch.upper() + text[i + 1:]
        break
    return text


def auto_capitalize_english(text: str) -> str:
    """تبدیل تمامی حروف انگلیسی به حروف بزرگ (UPPERCASE) ویژه برند و مدل کالا"""
    if not text:
        return ""
    return normalize_digits(text).upper()


from utils.datetime_format import (
    CALENDAR_GREGORIAN,
    CALENDAR_HIJRI,
    CALENDAR_JALALI,
    CALENDAR_LOOKUP,
    add_calendar_days,
    convert_date,
    detect_date_calendar,
    from_gregorian_date,
    get_calendar_month_days,
    get_today_date,
    to_gregorian_date,
)

def add_jalali_months(start_date_str: str, months: int) -> str:
    try:
        parts = [int(x) for x in normalize_digits(start_date_str).split("/")]
        y, m, d = parts[0], parts[1], parts[2]
        total_m = (m - 1) + int(months)
        ny = y + (total_m // 12)
        nm = (total_m % 12) + 1
        max_d = get_calendar_month_days(ny, nm, detect_date_calendar(start_date_str))
        nd = min(d, max_d)
        return f"{ny:04d}/{nm:02d}/{nd:02d}"
    except Exception:
        return start_date_str


def add_jalali_days(start_date_str: str, days: int, cal_type: str | None = None) -> str:
    """Add exact calendar days respecting the active/detected calendar."""
    try:
        cal = cal_type or detect_date_calendar(start_date_str)
        res = add_calendar_days(start_date_str, int(days), cal)
        return res or start_date_str
    except Exception:
        return start_date_str




def _animate_scrollbar(owner, scrollbar, amount):
    """Accumulate successive wheel ticks against the pending animation target."""
    if not amount or scrollbar.maximum() <= scrollbar.minimum():
        return False

    animation = getattr(owner, "_wheel_animation", None)
    base_value = scrollbar.value()
    if animation is not None and animation.state() == QAbstractAnimation.Running:
        try:
            base_value = int(animation.endValue())
        except (TypeError, ValueError):
            base_value = scrollbar.value()

    target = max(
        scrollbar.minimum(),
        min(scrollbar.maximum(), base_value - int(amount)),
    )
    if target == scrollbar.value():
        if animation is not None and animation.state() == QAbstractAnimation.Running:
            animation.stop()
        return True

    if animation is not None:
        animation.stop()
        animation.deleteLater()
        owner._wheel_animation = None

    animation = QPropertyAnimation(scrollbar, b"value", owner)
    animation.setDuration(180)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.setStartValue(scrollbar.value())
    animation.setEndValue(target)

    def release_animation():
        if getattr(owner, "_wheel_animation", None) is animation:
            owner._wheel_animation = None
        animation.deleteLater()

    animation.finished.connect(release_animation)
    owner._wheel_animation = animation
    animation.start()
    return True


def _wheel_amount(event, horizontal=False):
    """Normalize mouse-wheel and touchpad deltas to pixel-like scroll steps."""
    pixel_delta = event.pixelDelta()
    angle_delta = event.angleDelta()
    if horizontal:
        amount = pixel_delta.x() or pixel_delta.y() or angle_delta.x() or angle_delta.y()
    else:
        amount = pixel_delta.y() or pixel_delta.x() or angle_delta.y() or angle_delta.x()
        if not pixel_delta.y() and not pixel_delta.x():
            amount = int(amount)
    return int(amount)


class SmoothScrollArea(QScrollArea):
    """A pixel-based scroll area with accumulated, eased mouse-wheel animation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._wheel_animation = None

    def wheelEvent(self, event):
        horizontal = bool(event.modifiers() & Qt.ShiftModifier)
        scrollbar = (
            self.horizontalScrollBar() if horizontal else self.verticalScrollBar()
        )
        amount = _wheel_amount(event, horizontal=horizontal)
        if not amount or scrollbar.maximum() <= scrollbar.minimum():
            return super().wheelEvent(event)
        if _animate_scrollbar(self, scrollbar, amount):
            event.accept()
        else:
            super().wheelEvent(event)


class SmoothScrollTableWidget(QTableWidget):
    """Table widget with smooth pixel scrolling, including when the cursor is over a table."""

    def __init__(self, rows=0, columns=0, parent=None):
        super().__init__(rows, columns, parent)
        self._wheel_animation = None

    def wheelEvent(self, event):
        horizontal = bool(event.modifiers() & Qt.ShiftModifier)
        scrollbar = (
            self.horizontalScrollBar() if horizontal else self.verticalScrollBar()
        )
        amount = _wheel_amount(event, horizontal=horizontal)
        if not amount or scrollbar.maximum() <= scrollbar.minimum():
            return super().wheelEvent(event)
        if _animate_scrollbar(self, scrollbar, amount):
            event.accept()
        else:
            super().wheelEvent(event)


class SmoothScrollListWidget(QListWidget):
    """List widget with the same eased wheel scrolling as pages and tables."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._wheel_animation = None
        self.enable_row_toggle = False
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(18)

    def mousePressEvent(self, event):
        if getattr(self, "enable_row_toggle", False) and event.button() == Qt.LeftButton:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            item = self.itemAt(pos)
            if item is not None and (item.flags() & Qt.ItemIsUserCheckable):
                new_state = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
                item.setCheckState(new_state)
                self.setCurrentItem(item)
                event.accept()
                return
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        amount = _wheel_amount(event, horizontal=False)
        scrollbar = self.verticalScrollBar()
        if not amount or scrollbar.maximum() <= scrollbar.minimum():
            return super().wheelEvent(event)
        if _animate_scrollbar(self, scrollbar, amount):
            event.accept()
        else:
            super().wheelEvent(event)


class CollapsibleSection(QWidget):
    """Compact, keyboard-accessible section whose content is collapsed by default."""

    def __init__(self, title: str, content: QWidget, parent=None):
        super().__init__(parent)
        self.content = content
        self.header = QPushButton(f"▸  {title}")
        self.header.setObjectName("collapsibleSectionHeader")
        self._expanded = False
        self.header.setMinimumHeight(38)
        self.content.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(self.header)
        layout.addWidget(self.content)
        # Use pressed(), which has no Python bool payload. Expansion state is kept
        # in this widget instead of relying on QPushButton's checkable state.
        self.header.pressed.connect(self._on_header_pressed)

    def _on_header_pressed(self):
        self._expanded = not self._expanded
        title = self.header.text().lstrip("▸▾ ").strip()
        if self._expanded:
            self.content.show()
            self.header.setText("▾  " + title)
        else:
            self.content.hide()
            self.header.setText("▸  " + title)

    def collapse(self):
        if self._expanded:
            self._expanded = False
            title = self.header.text().lstrip("▸▾ ").strip()
            self.content.hide()
            self.header.setText("▸  " + title)

    def expand(self):
        if not self._expanded:
            self._expanded = True
            title = self.header.text().lstrip("▸▾ ").strip()
            self.content.show()
            self.header.setText("▾  " + title)

    def is_expanded(self) -> bool:
        return self._expanded


class SmartLineEdit(QLineEdit):
    """فیلد متنی هوشمند با تبدیل اعداد به انگلیسی و بزرگ‌نویسی خودکار حرف اول (یا تمام حروف برای برند و مدل)."""

    def __init__(self, placeholder="", parent=None, all_caps=False, preserve_persian_digits=False):
        super().__init__(parent)
        self.all_caps = bool(all_caps)
        self.preserve_persian_digits = bool(preserve_persian_digits)
        if placeholder:
            self.setPlaceholderText(placeholder)
        self.textEdited.connect(self._on_text_edited)

    def _transform_text(self, txt: str) -> str:
        if not txt:
            return ""
        if self.preserve_persian_digits:
            for i, ch in enumerate(txt):
                if ch.isspace():
                    continue
                if ch.islower():
                    return txt[:i] + ch.upper() + txt[i + 1:]
                break
            return txt
        if self.all_caps:
            return auto_capitalize_english(txt)
        return auto_capitalize_first_char(txt)


    def _on_text_edited(self, txt):
        new_txt = self._transform_text(txt)
        if new_txt != txt:
            pos = self.cursorPosition()
            has_sel = self.hasSelectedText()
            sel_start = self.selectionStart()
            sel_len = self.selectionLength()
            self.blockSignals(True)
            super().setText(new_txt)
            if has_sel and sel_start >= 0 and sel_len > 0:
                self.setSelection(sel_start, sel_len)
            else:
                self.setCursorPosition(pos)
            self.blockSignals(False)

    def setText(self, txt: str):
        super().setText(self._transform_text(str(txt or "")))

    def text(self) -> str:
        return self._transform_text(super().text())


class WarrantyLineEdit(SmartLineEdit):
    """فیلد ویرایش مدت گارانتی با انتخاب هوشمند صرفاً بخش عددی هنگام کلیک یا فوکوس."""

    _DIGITS_PREFIX_RE = re.compile(r"^\s*([0-9\u06f0-\u06f9]+)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._had_focus_on_press = False
        self._digits_selected_on_press = False
        self._press_pos = None
        self.installEventFilter(self)

    def _digits_span(self):
        match = self._DIGITS_PREFIX_RE.match(self.text())
        if not match:
            return None
        return match.start(1), match.end(1) - match.start(1)

    def eventFilter(self, watched, event):
        if watched is self:
            etype = event.type()
            if etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._had_focus_on_press = self.hasFocus()
                span = self._digits_span()
                self._digits_selected_on_press = bool(
                    span is not None
                    and self.hasSelectedText()
                    and self.selectionStart() == span[0]
                    and len(self.selectedText()) == span[1]
                )
                self._press_pos = (
                    event.position().toPoint() if hasattr(event, "position") else event.pos()
                )
            elif etype == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                release_pos = (
                    event.position().toPoint() if hasattr(event, "position") else event.pos()
                )
                dragged = False
                if self._press_pos is not None:
                    dragged = (release_pos - self._press_pos).manhattanLength() > 4
                self._press_pos = None
                # Ignore drags or an already-active selection so manual cursor edits still work.
                if not dragged and not self.hasSelectedText() and not (
                    self._had_focus_on_press and self._digits_selected_on_press
                ):
                    self._schedule_select_digits_only()
        return super().eventFilter(watched, event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if event.reason() != Qt.MouseFocusReason:
            self._schedule_select_digits_only()

    def _schedule_select_digits_only(self):
        QTimer.singleShot(0, self, self._select_digits_only)

    def _select_digits_only(self):
        span = self._digits_span()
        if span is not None:
            self.setSelection(span[0], span[1])


class PriceInput(QLineEdit):
    """فیلد قیمت بر حسب تومان با جداکننده هزارگان و افزودن خودکار صفر طبق تنظیمات"""

    # object keeps Python's full 64-bit integer value; Qt's C++ int signal is 32-bit.
    valueChanged = Signal(object)

    def __init__(self, db_manager, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self._raw_typed = False
        self.setPlaceholderText("مبلغ (تومان)")
        zero_count = int(self.db.cfg.get("zero_append_count", 3) or 0)
        self.setToolTip(
            "مبلغ را به تومان وارد کنید (بدون صفر اضافی)"
            if zero_count <= 0 else
            f"مبلغ را به تومان وارد کنید ({zero_count} صفر به‌صورت خودکار اضافه می‌شود)"
        )
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.textEdited.connect(self._on_edited)
        self.editingFinished.connect(self._apply_auto_zeros)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.selectAll()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.selectAll()

    def _on_edited(self, txt):
        self._raw_typed = True
        clean = "".join(ch for ch in normalize_digits(txt) if ch.isdigit())
        self.blockSignals(True)
        if clean:
            self.setText(f"{int(clean):,}")
        else:
            self.setText("")
        self.blockSignals(False)
        self.valueChanged.emit(self.get_value())

    def _apply_auto_zeros(self):
        if not self._raw_typed:
            return
        self._raw_typed = False
        zeros = max(0, int(self.db.cfg.get("zero_append_count", 3) or 0))
        val = self.get_value()
        if zeros > 0 and val > 0:
            val = val * (10**zeros)
            self.blockSignals(True)
            self.setText(f"{val:,}")
            self.blockSignals(False)
            self.valueChanged.emit(val)

    def get_value(self) -> int:
        clean = "".join(ch for ch in normalize_digits(self.text()) if ch.isdigit())
        return int(clean) if clean else 0

    def set_value(self, amount: int):
        self._raw_typed = False
        self.blockSignals(True)
        self.setText(f"{int(amount):,}" if amount else "0")
        self.blockSignals(False)
        self.setToolTip(f"{int(amount):,} تومان" if amount else "0 تومان")
        self.valueChanged.emit(int(amount) if amount else 0)


class _ComboSearchProxyModel(QSortFilterProxyModel):
    """Filter combo suggestions using visible text plus an optional hidden search field."""

    def __init__(self, search_role, parent=None):
        super().__init__(parent)
        self.search_role = search_role
        self.query = ""
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)

    def refresh_filter(self):
        """Re-evaluate proxy filter without deprecated invalidateFilter() warnings."""
        if hasattr(self, "beginFilterChange") and hasattr(self, "endFilterChange"):
            self.beginFilterChange()
            self.endFilterChange()
        else:
            self.invalidateFilter()

    def set_query(self, query):
        self.query = auto_capitalize_first_char(query).strip()
        self.refresh_filter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self.query:
            return True
        source = self.sourceModel()
        index = source.index(source_row, self.filterKeyColumn(), source_parent)
        visible = source.data(index, Qt.DisplayRole) or ""
        searchable = source.data(index, self.search_role) or ""
        q = self.query.casefold().strip()
        haystack = f"{visible} {searchable}".casefold()
        return q in haystack or auto_capitalize_first_char(self.query) in auto_capitalize_first_char(f"{visible} {searchable}")


class SearchableComboBox(QComboBox):
    """Editable combo with completion against visible labels and hidden search keywords."""

    SEARCH_ROLE = Qt.UserRole + 37

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        # Keep the logical order of mixed Persian/Latin selectors in the collapsed view.
        self.lineEdit().setLayoutDirection(Qt.LeftToRight)
        self.lineEdit().setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._search_proxy = _ComboSearchProxyModel(self.SEARCH_ROLE, self)
        self._search_proxy.setSourceModel(self.model())
        completer = QCompleter(self._search_proxy, self)
        # Proxy model is the sole filter source; Qt must not apply a second visible-text filter.
        completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        completer.setCompletionColumn(0)
        completer.setCompletionRole(Qt.DisplayRole)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.setCompleter(completer)
        self.lineEdit().textEdited.connect(self._normalize_search)
        self.currentTextChanged.connect(lambda t: self.setToolTip(t))

    def setItemSearchText(self, index: int, search_text: str):
        if 0 <= index < self.count():
            self.setItemData(index, str(search_text or ""), self.SEARCH_ROLE)
            self._search_proxy.refresh_filter()

    def _normalize_search(self, txt):
        norm = auto_capitalize_first_char(txt)
        self._search_proxy.set_query(norm)
        if norm != txt:
            pos = self.lineEdit().cursorPosition()
            self.lineEdit().blockSignals(True)
            self.lineEdit().setText(norm)
            self.lineEdit().setCursorPosition(pos)
            self.lineEdit().blockSignals(False)
        return norm

    def currentText(self) -> str:
        return auto_capitalize_first_char(super().currentText())


class QuantitySelector(QComboBox):
    qtyChanged = Signal(int)

    def __init__(self, max_qty=100, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.set_max_qty(max_qty)
        self.currentTextChanged.connect(self._on_change)

    def set_max_qty(self, max_qty: int):
        current = self.get_qty()
        self.blockSignals(True)
        self.clear()
        limit = max(1, min(int(max_qty), 300))
        for i in range(1, limit + 1):
            self.addItem(str(i), i)
        if 1 <= current <= max_qty:
            self.setCurrentText(str(current))
        else:
            self.setCurrentText("1")
        self.blockSignals(False)

    def _on_change(self, txt):
        clean = "".join(ch for ch in normalize_digits(txt) if ch.isdigit())
        if clean != txt and clean:
            self.setCurrentText(clean)
        self.qtyChanged.emit(self.get_qty())

    def get_qty(self) -> int:
        clean = "".join(
            ch for ch in normalize_digits(self.currentText()) if ch.isdigit()
        )
        return max(1, int(clean)) if clean else 1


_CALENDAR_TITLES = {
    CALENDAR_JALALI: "انتخاب تاریخ شمسی",
    CALENDAR_HIJRI: "انتخاب تاریخ قمری",
    CALENDAR_GREGORIAN: "انتخاب تاریخ میلادی",
}

_CALENDAR_YEAR_BOUNDS = {
    CALENDAR_JALALI: (1400, 1600),
    CALENDAR_HIJRI: (1400, 1550),
    CALENDAR_GREGORIAN: (1950, 2150),
}

_CALENDAR_MONTHS = {
    CALENDAR_JALALI: [
        "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
        "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
    ],
    CALENDAR_HIJRI: [
        "محرم", "صفر", "ربیع‌الاول", "ربیع‌الثانی", "جمادی‌الاول", "جمادی‌الثانی",
        "رجب", "شعبان", "رمضان", "شوال", "ذیقعده", "ذیحجه",
    ],
    CALENDAR_GREGORIAN: [
        "ژانویه (Jan)", "فوریه (Feb)", "مارس (Mar)", "آوریل (Apr)",
        "مه (May)", "ژوئن (Jun)", "ژوئیه (Jul)", "اوت (Aug)",
        "سپتامبر (Sep)", "اکتبر (Oct)", "نوامبر (Nov)", "دسامبر (Dec)",
    ],
}


def _resolve_ancestor_calendar(widget, explicit_cal=None, _visited=None) -> str:
    if explicit_cal:
        return CALENDAR_LOOKUP.get(explicit_cal, CALENDAR_JALALI)
    visited = _visited if _visited is not None else set()
    ancestor = widget
    while ancestor is not None:
        obj_id = id(ancestor)
        if obj_id in visited:
            break
        visited.add(obj_id)
        if hasattr(ancestor, "get_active_calendar"):
            try:
                return CALENDAR_LOOKUP.get(ancestor.get_active_calendar(), CALENDAR_JALALI)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        explicit_attr = getattr(ancestor, "_explicit_calendar_format", None)
        if explicit_attr:
            return CALENDAR_LOOKUP.get(explicit_attr, CALENDAR_JALALI)
        if not isinstance(ancestor, JalaliDateEdit) and hasattr(ancestor, "get_calendar_format"):
            try:
                return CALENDAR_LOOKUP.get(ancestor.get_calendar_format(), CALENDAR_JALALI)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        if hasattr(ancestor, "db") and getattr(ancestor, "db", None) is not None:
            try:
                return CALENDAR_LOOKUP.get(
                    ancestor.db.get_setting("calendar_format", CALENDAR_JALALI),
                    CALENDAR_JALALI,
                )
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        ancestor = ancestor.parentWidget() if hasattr(ancestor, "parentWidget") else None
    return CALENDAR_JALALI


class JalaliCalendarDialog(QDialog):
    """
    پنجره گرافیکی انتخاب تاریخ مطابق با تقویم فعال برنامه (شمسی / قمری / میلادی)
    """

    def __init__(self, initial_date_str, parent=None, cal_format=None):
        super().__init__(parent)
        self.cal_format = _resolve_ancestor_calendar(parent, cal_format)
        self.setWindowTitle(_CALENDAR_TITLES.get(self.cal_format, "انتخاب تاریخ"))
        self.setLayoutDirection(Qt.RightToLeft)
        self.setFixedSize(470, 438)
        self.selected_date = initial_date_str

        dark = resolve_active_dark_theme(parent=parent)
        self.setPalette(build_theme_palette(dark))

        self._calendar_colors = {
            "surface": "#263244" if dark else "#ffffff",
            "base": "#1e293b" if dark else "#f8fafc",
            "text": "#e5eaf2" if dark else "#0f172a",
            "muted": "#aab6c8" if dark else "#475569",
            "border": "#46556c" if dark else "#cbd5e1",
            "selected": "#2563eb",
            "disabled": "#334155" if dark else "#e2e8f0",
        }
        colors = self._calendar_colors
        self.setStyleSheet(
            f"QDialog {{ background: {colors['base']}; color: {colors['text']}; }}"
            f"QLabel {{ color: {colors['text']}; }}"
            f"QComboBox {{ background: {colors['surface']}; color: {colors['text']}; "
            f"border: 1px solid {colors['border']}; border-radius: 6px; padding: 5px; min-height: 30px; }}"
            f"QComboBox QAbstractItemView {{ background: {colors['surface']}; color: {colors['text']}; "
            f"selection-background-color: {colors['selected']}; selection-color: #ffffff; }}"
            f"QPushButton {{ background: {colors['surface']}; color: {colors['text']}; "
            f"border: 1px solid {colors['border']}; border-radius: 6px; padding: 6px 10px; }}"
            f"QPushButton:hover {{ border: 1px solid {colors['selected']}; }}"
        )

        y_min, y_max = _CALENDAR_YEAR_BOUNDS.get(self.cal_format, (1350, 1600))
        try:
            normalized_init = convert_date(
                initial_date_str,
                detect_date_calendar(initial_date_str, self.cal_format),
                self.cal_format,
            )
            p = [int(x) for x in normalize_digits(normalized_init).split("/")]
            self.cur_year, self.cur_month, self.cur_day = p[0], p[1], p[2]
            if not (y_min <= self.cur_year <= y_max):
                raise ValueError("Out of calendar bounds")
        except Exception:
            today_str = get_today_date(self.cal_format)
            p = [int(x) for x in today_str.split("/")]
            self.cur_year, self.cur_month, self.cur_day = p[0], p[1], p[2]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        nav = QVBoxLayout()
        nav.setSpacing(3)
        controls_grid = QGridLayout()
        controls_grid.setContentsMargins(0, 0, 0, 0)
        controls_grid.setHorizontalSpacing(10)
        controls_grid.setVerticalSpacing(8)
        controls_grid.setColumnStretch(0, 1)
        controls_grid.setColumnStretch(1, 1)

        self.cb_year = QComboBox()
        self.cb_year.setEditable(True)
        self.cb_year.addItems([str(year) for year in range(y_min, y_max + 1)])
        self.cb_year.setInsertPolicy(QComboBox.NoInsert)
        self.cb_year.setCurrentText(str(self.cur_year))
        self.cb_year.setMinimumHeight(38)
        self.cb_year.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cb_year.lineEdit().setAlignment(Qt.AlignCenter)
        self.cb_year.lineEdit().setValidator(QIntValidator(y_min, y_max, self.cb_year))
        self.cb_year.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.cb_year.currentTextChanged.connect(self._refresh_grid)

        self.cb_month = QComboBox()
        self.cb_month.setMinimumHeight(38)
        self.cb_month.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cb_month.setStyleSheet("font-size: 15px; font-weight: bold;")
        months = _CALENDAR_MONTHS.get(self.cal_format, _CALENDAR_MONTHS[CALENDAR_JALALI])
        for idx, m in enumerate(months, 1):
            self.cb_month.addItem(f"{idx:02d} - {m}", idx)
        self.cb_month.setCurrentIndex(max(0, min(11, self.cur_month - 1)))
        self.cb_month.currentIndexChanged.connect(self._refresh_grid)

        self.cb_day = QComboBox()
        self.cb_day.setMinimumHeight(38)
        self.cb_day.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cb_day.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.cb_day.addItems([f"{day:02d}" for day in range(1, 32)])
        self.cb_day.setCurrentIndex(max(0, min(30, self.cur_day - 1)))
        self.cb_day.activated.connect(self._on_day_combo_activated)

        btn_today = QPushButton("برو به امروز")
        btn_today.setMinimumHeight(38)
        btn_today.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_today.clicked.connect(self._go_today)

        lbl_y = QLabel("سال:")
        lbl_y.setStyleSheet("font-weight: bold; font-size: 14px;")
        lbl_m = QLabel("ماه:")
        lbl_m.setStyleSheet("font-weight: bold; font-size: 14px;")
        lbl_d = QLabel("روز:")
        lbl_d.setStyleSheet("font-weight: bold; font-size: 14px;")

        year_cell = QWidget()
        year_cell_layout = QHBoxLayout(year_cell)
        year_cell_layout.setContentsMargins(0, 0, 0, 0)
        year_cell_layout.setSpacing(6)
        year_cell_layout.addWidget(lbl_y)
        year_cell_layout.addWidget(self.cb_year, 1)

        month_cell = QWidget()
        month_cell_layout = QHBoxLayout(month_cell)
        month_cell_layout.setContentsMargins(0, 0, 0, 0)
        month_cell_layout.setSpacing(6)
        month_cell_layout.addWidget(lbl_m)
        month_cell_layout.addWidget(self.cb_month, 1)

        day_cell = QWidget()
        day_cell_layout = QHBoxLayout(day_cell)
        day_cell_layout.setContentsMargins(0, 0, 0, 0)
        day_cell_layout.setSpacing(6)
        day_cell_layout.addWidget(lbl_d)
        day_cell_layout.addWidget(self.cb_day, 1)

        controls_grid.addWidget(year_cell, 0, 0)
        controls_grid.addWidget(btn_today, 0, 1)
        controls_grid.addWidget(month_cell, 1, 0)
        controls_grid.addWidget(day_cell, 1, 1)
        nav.addLayout(controls_grid)
        layout.addLayout(nav)

        self.grid = QGridLayout()
        self.grid.setSpacing(5)
        days_header = ["ش", "ی", "د", "س", "چ", "پ", "ج"]
        for col, d_name in enumerate(days_header):
            lbl = QLabel(d_name)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(
                f"font-weight: bold; font-size: 14px; color: {colors['muted']}; padding: 4px;"
            )
            lbl.setMinimumHeight(30)
            self.grid.addWidget(lbl, 0, col)

        self.day_buttons = []
        for r in range(1, 7):
            for c in range(7):
                btn = QPushButton("")
                btn.setFixedSize(50, 42)
                btn.setStyleSheet(
                    f"background: {colors['surface']}; color: {colors['text']}; "
                    f"font-size: 15px; font-weight: bold; border: 1px solid {colors['border']}; "
                    "border-radius: 6px;"
                )
                btn.clicked.connect(self._on_day_clicked)
                self.grid.addWidget(btn, r, c)
                self.day_buttons.append(btn)

        layout.addLayout(self.grid)
        self._refresh_grid()

    def _go_today(self):
        today_str = get_today_date(self.cal_format)
        ty, tm, td = [int(x) for x in today_str.split("/")]
        self.cb_year.setCurrentText(str(ty))
        self.cb_month.setCurrentIndex(tm - 1)
        self.cb_day.setCurrentIndex(td - 1)
        self.selected_date = today_str
        self.accept()

    def _on_day_combo_activated(self, index):
        try:
            year = int(normalize_digits(self.cb_year.currentText()))
            month = int(self.cb_month.currentData())
            day = int(self.cb_day.itemText(index))
            to_gregorian_date(year, month, day, self.cal_format)
        except (TypeError, ValueError):
            return
        self.selected_date = f"{year:04d}/{month:02d}/{day:02d}"
        self.accept()

    def _refresh_grid(self):
        # Clear the calendar first; typing an incomplete year must never crash the dialog.
        colors = self._calendar_colors
        for button in self.day_buttons:
            button.setText("")
            button.setEnabled(0)
            button.setStyleSheet(
                f"background: {colors['disabled']}; color: {colors['muted']}; "
                "border: none; border-radius: 6px;"
            )

        raw_year = normalize_digits(self.cb_year.currentText()).strip()
        try:
            year = int(raw_year)
        except (TypeError, ValueError):
            return
        y_min, y_max = _CALENDAR_YEAR_BOUNDS.get(self.cal_format, (1350, 1600))
        if not y_min <= year <= y_max:
            return

        month = self.cb_month.currentData()
        if month is None:
            return
        try:
            first_greg = to_gregorian_date(year, int(month), 1, self.cal_format)
            max_days = get_calendar_month_days(year, int(month), self.cal_format)
        except (TypeError, ValueError):
            return
        # Grid columns run Sat (0) .. Fri (6). Python date.weekday(): Mon=0 .. Sun=6 -> Sat=(wd+2)%7
        start_weekday = (first_greg.weekday() + 2) % 7

        for day_index in range(self.cb_day.count()):
            item = self.cb_day.model().item(day_index)
            if item is not None:
                flags = item.flags()
                if day_index < max_days:
                    item.setFlags(flags | Qt.ItemIsEnabled)
                else:
                    item.setFlags(flags & ~Qt.ItemIsEnabled)

        for day in range(1, max_days + 1):
            index = start_weekday + day - 1
            if index >= len(self.day_buttons):
                break
            button = self.day_buttons[index]
            button.setText(str(day))
            button.setEnabled(1)
            if year == self.cur_year and month == self.cur_month and day == self.cur_day:
                button.setStyleSheet(
                    f"background-color: {colors['selected']}; color: white; "
                    "font-size: 15px; font-weight: bold; border-radius: 6px;"
                )
            else:
                button.setStyleSheet(
                    f"background-color: {colors['surface']}; color: {colors['text']}; "
                    f"font-size: 15px; font-weight: bold; border: 1px solid {colors['border']}; "
                    "border-radius: 6px;"
                )

    def _on_day_clicked(self):
        btn = self.sender()
        if not btn.text():
            return
        d = int(btn.text())
        try:
            y = int(normalize_digits(self.cb_year.currentText()))
        except (TypeError, ValueError):
            return
        m = self.cb_month.currentData()
        y_min, y_max = _CALENDAR_YEAR_BOUNDS.get(self.cal_format, (1350, 1600))
        if m is None or not y_min <= y <= y_max:
            return
        try:
            to_gregorian_date(y, int(m), d, self.cal_format)
        except ValueError:
            return
        self.selected_date = f"{y:04d}/{int(m):02d}/{d:02d}"
        self.accept()


class JalaliDateEdit(QWidget):
    """
    فیلد تاریخ ۳ کادره (روز / ماه / سال) منطبق با تقویم فعال برنامه (شمسی، قمری، میلادی)
    """

    dateChanged = Signal(str)

    def __init__(self, default_today=True, parent=None, calendar_format=None):
        super().__init__(parent)
        self._explicit_calendar_format = (
            CALENDAR_LOOKUP.get(calendar_format, CALENDAR_JALALI) if calendar_format else None
        )
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.ed_day = QLineEdit()
        self.ed_day.setFixedWidth(50)
        self.ed_day.setFixedHeight(36)
        self.ed_day.setStyleSheet("font-size: 12px; padding: 2px;")
        self.ed_day.setMaxLength(2)
        self.ed_day.setAlignment(Qt.AlignCenter)
        self.ed_day.setPlaceholderText("روز")

        self.ed_month = QLineEdit()
        self.ed_month.setFixedWidth(50)
        self.ed_month.setFixedHeight(36)
        self.ed_month.setStyleSheet("font-size: 12px; padding: 2px;")
        self.ed_month.setMaxLength(2)
        self.ed_month.setAlignment(Qt.AlignCenter)
        self.ed_month.setPlaceholderText("ماه")

        self.ed_year = QLineEdit()
        self.ed_year.setFixedWidth(68)
        self.ed_year.setFixedHeight(36)
        self.ed_year.setStyleSheet("font-size: 12px; padding: 2px;")
        self.ed_year.setMaxLength(4)
        self.ed_year.setAlignment(Qt.AlignCenter)
        self.ed_year.setPlaceholderText("سال")

        self.btn_cal = QPushButton("📅")
        self.btn_cal.setFixedSize(34, 36)
        self.btn_cal.setToolTip("انتخاب از تقویم شمسی")
        self.btn_cal.clicked.connect(self._open_calendar)

        # چیدمان راست به چپ: روز / ماه / سال
        layout.addWidget(self.ed_day)
        layout.addWidget(QLabel("/"))
        layout.addWidget(self.ed_month)
        layout.addWidget(QLabel("/"))
        layout.addWidget(self.ed_year)
        layout.addWidget(self.btn_cal)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedWidth(self.sizeHint().width())

        self.ed_day.textEdited.connect(self._on_day_edited)
        self.ed_month.textEdited.connect(self._on_month_edited)
        self.ed_year.textEdited.connect(self._on_year_edited)

        self._update_calendar_tooltip()
        if default_today:
            self.set_date(get_today_date(self.get_calendar_format()))

    def get_calendar_format(self) -> str:
        if self._explicit_calendar_format:
            return CALENDAR_LOOKUP.get(self._explicit_calendar_format, CALENDAR_JALALI)
        return _resolve_ancestor_calendar(self.parentWidget(), None)

    def _update_calendar_tooltip(self):
        cal = self.get_calendar_format()
        self.btn_cal.setToolTip(
            {
                CALENDAR_JALALI: "انتخاب از تقویم شمسی",
                CALENDAR_HIJRI: "انتخاب از تقویم قمری",
                CALENDAR_GREGORIAN: "انتخاب از تقویم میلادی",
            }.get(cal, "انتخاب از تقویم")
        )

    def set_calendar_format(self, cal_type: str, convert_existing: bool = False):
        target = CALENDAR_LOOKUP.get(cal_type, CALENDAR_JALALI)
        old_cal = self.get_calendar_format()
        self._explicit_calendar_format = target
        self._update_calendar_tooltip()
        if convert_existing:
            current = self.get_date()
            if current:
                detected = detect_date_calendar(current, fallback_cal=old_cal)
                self.set_date(convert_date(current, detected, target))

    def _clean_num(self, line_edit):
        txt = normalize_digits(line_edit.text())
        clean = "".join(c for c in txt if c.isdigit())
        if clean != line_edit.text():
            line_edit.blockSignals(True)
            line_edit.setText(clean)
            line_edit.blockSignals(False)
        return clean

    def _on_day_edited(self):
        c = self._clean_num(self.ed_day)
        if len(c) == 2:
            if int(c) > 31:
                self.ed_day.setText("31")
            self.ed_month.setFocus()
            self.ed_month.selectAll()
        self.dateChanged.emit(self.get_date())

    def _on_month_edited(self):
        c = self._clean_num(self.ed_month)
        if len(c) == 2:
            if int(c) > 12:
                self.ed_month.setText("12")
            self.ed_year.setFocus()
            self.ed_year.selectAll()
        self.dateChanged.emit(self.get_date())

    def _on_year_edited(self):
        self._clean_num(self.ed_year)
        self.dateChanged.emit(self.get_date())

    def _open_calendar(self):
        cal = self.get_calendar_format()
        self._update_calendar_tooltip()
        dlg = JalaliCalendarDialog(self.get_date(), self, cal_format=cal)
        if dlg.exec() == QDialog.Accepted:
            self.set_date(dlg.selected_date)

    def get_date(self) -> str:
        year = self.ed_year.text().strip()
        month = self.ed_month.text().strip()
        day = self.ed_day.text().strip()
        if not (year and month and day):
            return ""
        return f"{year.zfill(4)}/{month.zfill(2)}/{day.zfill(2)}"

    def set_date(self, date_str: str):
        raw = normalize_digits(str(date_str or "")).strip()
        if not raw:
            for editor in (self.ed_year, self.ed_month, self.ed_day):
                editor.clear()
            self.dateChanged.emit("")
            return
        try:
            parts = raw.split("/")
            if len(parts) != 3 or not all(part.strip() for part in parts):
                raise ValueError("Invalid Jalali date")
            self.ed_year.setText(parts[0].strip())
            self.ed_month.setText(parts[1].strip().zfill(2))
            self.ed_day.setText(parts[2].strip().zfill(2))
            self.dateChanged.emit(self.get_date())
        except (TypeError, ValueError):
            self.set_date("")


class DynamicSpecsWidget(QGroupBox):
    """
    ویجت زیرمجموعه‌ها و مشخصات فنی کالا مبتنی بر تنظیمات پویای پایگاه داده (فاقد هرگونه ساختار هاردکدشده در سورس)
    """

    def __init__(self, parent=None, *, external_sub_combo=None, external_sub_label=None):
        super().__init__("مشخصات فنی کالا", parent)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setAlignment(Qt.AlignRight)
        self._external_sub_combo = external_sub_combo
        self._external_sub_label = external_sub_label
        self.main_layout = QVBoxLayout(self)
        self.form_widget = QWidget()
        self.form_layout = QFormLayout(self.form_widget)
        self.form_widget.setLayoutDirection(Qt.RightToLeft)
        self.form_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.form_layout.setFormAlignment(Qt.AlignRight | Qt.AlignTop)
        self.form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.form_layout.setHorizontalSpacing(10)
        self.form_layout.setVerticalSpacing(7)
        self.form_scroll = SmoothScrollArea(self)
        self.form_scroll.setWidget(self.form_widget)
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setMinimumHeight(80)
        self.form_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.form_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.main_layout.addWidget(self.form_scroll)
        self.current_category = ""
        self.fields = {}
        self._custom_field_widgets = {}
        self.cb_sub = self._external_sub_combo
        self._custom_field_callback = None
        if self._external_sub_combo is not None:
            self._external_sub_combo.currentTextChanged.connect(self._notify_custom_field_callback)

    def set_custom_field_callback(self, callback):
        """Store bound callbacks weakly to avoid cycle."""
        if not callable(callback):
            self._custom_field_callback = None
        elif getattr(callback, "__self__", None) is not None:
            self._custom_field_callback = weakref.WeakMethod(callback)
        else:
            self._custom_field_callback = callback

    def _notify_custom_field_callback(self, *_):
        callback = self._custom_field_callback
        if isinstance(callback, weakref.WeakMethod):
            callback = callback()
        if callback is not None:
            callback()

    def _clear_form(self):
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.fields.clear()
        self._custom_field_widgets.clear()
        self.cb_sub = self._external_sub_combo

    def _apply_compact_form_layouts(self):
        """Keep RTL field captions compact while giving editors consistent spacing."""
        layouts = [self.form_layout]
        for form_layout in layouts:
            try:
                form_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
                form_layout.setFormAlignment(Qt.AlignRight | Qt.AlignTop)
                form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
                form_layout.setHorizontalSpacing(12)
                form_layout.setVerticalSpacing(9)
                for row in range(form_layout.rowCount()):
                    field_item = form_layout.itemAt(row, QFormLayout.FieldRole)
                    field_widget = field_item.widget() if field_item else None
                    label_widget = (
                        form_layout.labelForField(field_widget)
                        if field_widget is not None else None
                    )
                    if isinstance(label_widget, QLabel):
                        label_widget.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        label_widget.setLayoutDirection(Qt.RightToLeft)
                        label_widget.setSizePolicy(
                            QSizePolicy.Maximum, QSizePolicy.Fixed
                        )
                        label_widget.setMinimumWidth(72)
                        label_widget.setMaximumWidth(
                            max(100, min(220, label_widget.sizeHint().width() + 8))
                        )
                        label_widget.setWordWrap(False)
                    if field_widget is not None:
                        field_widget.setMinimumHeight(
                            max(30, field_widget.minimumHeight())
                        )
                        field_widget.setSizePolicy(
                            QSizePolicy.Expanding, QSizePolicy.Fixed
                        )
            except RuntimeError:
                continue

    def set_subcategory_label(self, label: str):
        """Customize the caption associated with the category-specific subcategory selector."""
        clean = str(label or "زیرمجموعه").strip() or "زیرمجموعه"
        if self._external_sub_label is not None:
            self._external_sub_label.setText(f"{clean}:")
            return
        if self.cb_sub is None:
            return
        label_widget = self.form_layout.labelForField(self.cb_sub)
        if label_widget is not None:
            label_widget.setText(f"{clean}:")

    def set_category(self, category: str):
        self.current_category = str(category or "").strip()
        self._clear_form()

        is_other = normalize_catalog_label(self.current_category) == normalize_catalog_label("سایر موارد")
        if self._external_sub_combo is not None:
            self.cb_sub = self._external_sub_combo
            self.cb_sub.setEditable(is_other)
            if is_other:
                self.cb_sub.setToolTip("زیرمجموعه را انتخاب کنید یا نام دلخواه را تایپ کنید")
            else:
                self.cb_sub.setToolTip("زیرمجموعه را از فهرست انتخاب کنید")
        else:
            self.cb_sub = SearchableComboBox()
            self.cb_sub.setEditable(is_other)
            if is_other:
                self.cb_sub.setToolTip("زیرمجموعه را انتخاب کنید یا نام دلخواه را تایپ کنید")
            else:
                self.cb_sub.setToolTip("زیرمجموعه را از فهرست انتخاب کنید")
            self.cb_sub.currentTextChanged.connect(self._notify_custom_field_callback)
            self.form_layout.addRow("زیرمجموعه:", self.cb_sub)
        self._apply_compact_form_layouts()

    def apply_custom_catalog(self, subcategories=None, custom_fields=None):
        """Apply user-managed subcategories and extra specification fields."""
        if self.cb_sub is not None and isinstance(subcategories, list):
            current = self.cb_sub.currentText()
            clean_subcategories = _unique_catalog_labels(subcategories)
            current_key = normalize_catalog_label(current)
            self.cb_sub.blockSignals(True)
            self.cb_sub.clear()
            self.cb_sub.addItems(clean_subcategories)
            is_other = normalize_catalog_label(self.current_category) == normalize_catalog_label("سایر موارد")
            self.cb_sub.setEditable(is_other)
            if is_other:
                self.cb_sub.setToolTip("زیرمجموعه را انتخاب کنید یا نام دلخواه را تایپ کنید")
            else:
                self.cb_sub.setToolTip("زیرمجموعه را از فهرست انتخاب کنید")
            selected_index = next(
                (i for i, value in enumerate(clean_subcategories)
                 if normalize_catalog_label(value) == current_key),
                -1,
            )
            if selected_index >= 0:
                self.cb_sub.setCurrentIndex(selected_index)
            elif clean_subcategories:
                self.cb_sub.setCurrentIndex(0)
            else:
                self.cb_sub.setCurrentText("")
            self.cb_sub.blockSignals(False)

        for field_name, widget in list(self._custom_field_widgets.items()):
            if self.fields.get(field_name) is widget:
                self.fields.pop(field_name, None)
            try:
                row, _role = self.form_layout.getWidgetPosition(widget)
                if row >= 0:
                    self.form_layout.removeRow(row)
            except RuntimeError:
                pass
        self._custom_field_widgets.clear()

        if not isinstance(custom_fields, list):
            return
        seen_custom_names = set()
        for definition in custom_fields:
            if not isinstance(definition, dict):
                continue
            field_name = str(definition.get("name", "")).strip()
            if normalize_catalog_label(field_name) == normalize_catalog_label("مشخصه"):
                field_name = "مشخصات"
            normalized_name = normalize_catalog_label(field_name)
            if not field_name or not normalized_name or normalized_name in seen_custom_names:
                continue
            seen_custom_names.add(normalized_name)
            form_label = field_name
            raw_values = definition.get("values", [])
            values = [
                str(value).strip() for value in raw_values
                if str(value).strip()
            ] if isinstance(raw_values, list) else []

            existing_key = next(
                (
                    key for key in self.fields
                    if normalize_catalog_label(key) == normalized_name
                ),
                None,
            )
            existing_widget = self.fields.get(existing_key) if existing_key is not None else None
            if existing_widget is not None:
                try:
                    if existing_key != field_name:
                        self.fields.pop(existing_key, None)
                        self.fields[field_name] = existing_widget
                    if isinstance(existing_widget, QComboBox):
                        current_value = existing_widget.currentText()
                        existing_widget.blockSignals(True)
                        existing_widget.clear()
                        existing_widget.addItem("")
                        existing_widget.addItems(list(dict.fromkeys(values)))
                        if current_value in values:
                            existing_widget.setCurrentText(current_value)
                        existing_widget.blockSignals(False)
                    field_label = self.form_layout.labelForField(existing_widget)
                    if isinstance(field_label, QLabel):
                        field_label.setText(f"{form_label}:")
                    existing_widget.setToolTip(f"مشخصات فنی: {form_label}")
                    continue
                except RuntimeError:
                    self.fields.pop(field_name, None)
                    self.fields.pop(existing_key, None)
                    existing_widget = None

            if values:
                widget = SearchableComboBox()
                widget.addItem("")
                widget.addItems(list(dict.fromkeys(values)))
            else:
                widget = SmartLineEdit()
            widget.setToolTip(f"مشخصات فنی: {form_label}")
            self.fields[field_name] = widget
            self._custom_field_widgets[field_name] = widget
            self.form_layout.addRow(f"{form_label}:", widget)

        specs_key = next((k for k in list(self.fields.keys()) if normalize_catalog_label(k) == normalize_catalog_label("مشخصات")), None)
        if specs_key is not None:
            spec_widget = self.fields.pop(specs_key)
            self.fields[specs_key] = spec_widget
            try:
                row, _ = self.form_layout.getWidgetPosition(spec_widget)
                if row >= 0 and row < self.form_layout.rowCount() - 1:
                    res = self.form_layout.takeRow(row)
                    if res.labelItem and res.labelItem.widget():
                        self.form_layout.addRow(res.labelItem.widget(), spec_widget)
                    else:
                        self.form_layout.addRow(spec_widget)
            except Exception:
                pass

        self._apply_compact_form_layouts()

    def get_sub_category(self) -> str:
        if self.cb_sub:
            if self.cb_sub.isEditable() and self.cb_sub.lineEdit():
                return self.cb_sub.lineEdit().text().strip()
            return self.cb_sub.currentText().strip()
        return ""

    def set_sub_category(self, sub_text: str):
        if self.cb_sub and sub_text:
            idx = self.cb_sub.findText(sub_text)
            if idx >= 0:
                self.cb_sub.setCurrentIndex(idx)
            else:
                if self.cb_sub.isEditable():
                    self.cb_sub.setEditText(sub_text)
                else:
                    self.cb_sub.addItem(sub_text)
                    self.cb_sub.setCurrentText(sub_text)

    def get_specs_dict(self) -> dict:
        res = {}
        for k, w in self.fields.items():
            val = w.currentText() if isinstance(w, QComboBox) else w.text()
            if val.strip():
                clean_val = val.strip()
                if normalize_catalog_label(k) == normalize_catalog_label("مشخصات") or k in ("Specs", "specs"):
                    res["Specs"] = clean_val
                else:
                    res[k] = clean_val
        return res

    def set_specs_dict(self, data: dict):
        if not isinstance(data, dict):
            return
        for k, val in data.items():
            if k in ("Specs", "specs") or normalize_catalog_label(k) == normalize_catalog_label("مشخصات"):
                target_key = next((f_key for f_key in self.fields if normalize_catalog_label(f_key) == normalize_catalog_label("مشخصات")), None)
                if not target_key:
                    w = SmartLineEdit()
                    self.fields["مشخصات"] = w
                    self.form_layout.addRow("مشخصات:", w)
                    target_key = "مشخصات"
            else:
                target_key = next((f_key for f_key in self.fields if normalize_catalog_label(f_key) == normalize_catalog_label(k)), k)
                if target_key not in self.fields:
                    w = SmartLineEdit()
                    self.fields[target_key] = w
                    self.form_layout.addRow(f"{target_key}:", w)
            if target_key and target_key in self.fields:
                w = self.fields[target_key]
                if isinstance(w, QComboBox):
                    w.setCurrentText(str(val))
                else:
                    w.setText(str(val))


class DynamicDomainValueRow(QWidget):
    """Single row representing one domain/suggested value with input field and dedicated (+) and (-) buttons."""
    removed = Signal(object)
    added_after = Signal(object)
    changed = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(6)

        self.ed_value = QLineEdit(text)
        self.ed_value.setPlaceholderText("مقدار پیشنهادی (مثلاً USB 3.0, Type-C, HDMI)...")
        self.ed_value.textChanged.connect(lambda: self.changed.emit())

        self.btn_add = QPushButton("➕")
        self.btn_add.setToolTip("افزودن مقدار جدید بعد از این سطر")
        self.btn_add.setFixedSize(28, 28)
        self.btn_add.clicked.connect(lambda: self.added_after.emit(self))

        self.btn_remove = QPushButton("➖")
        self.btn_remove.setToolTip("حذف این مقدار")
        self.btn_remove.setFixedSize(28, 28)
        self.btn_remove.setObjectName("btnDanger")
        self.btn_remove.clicked.connect(lambda: self.removed.emit(self))

        layout.addWidget(self.ed_value, 1)
        layout.addWidget(self.btn_add)
        layout.addWidget(self.btn_remove)

    def text(self) -> str:
        return self.ed_value.text().strip()

    def setText(self, text: str):
        self.ed_value.setText(text)


class DynamicAttributeValuesWidget(QWidget):
    """Dynamic list view component replacing comma-separated text fields for sub-category domains."""
    valuesChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(4)

        self.scroll_area = SmoothScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(160)
        self.scroll_area.setMaximumHeight(220)

        self.container = QWidget()
        self.rows_layout = QVBoxLayout(self.container)
        self.rows_layout.setContentsMargins(4, 4, 4, 4)
        self.rows_layout.setSpacing(4)
        self.rows_layout.addStretch()

        self.scroll_area.setWidget(self.container)
        main_layout.addWidget(self.scroll_area)

        self.rows = []
        self.add_row("")

    def get_values(self) -> list:
        result = []
        for r in self.rows:
            val = r.text()
            if val and val not in result:
                result.append(val)
        return result

    def _clear_rows(self):
        for r in list(self.rows):
            self.rows_layout.removeWidget(r)
            r.deleteLater()
        self.rows.clear()

    def clear(self):
        self._clear_rows()
        self.add_row("")

    def set_values(self, values_list: list):
        self._clear_rows()
        if not values_list:
            self.add_row("")
            return
        for val in values_list:
            val_str = str(val).strip()
            if val_str:
                self.add_row(val_str)
        if not self.rows:
            self.add_row("")

    def add_row(self, text="", after_row=None):
        row = DynamicDomainValueRow(text, self.container)
        row.removed.connect(self._on_remove_row)
        row.added_after.connect(self._on_add_after)
        row.changed.connect(lambda: self.valuesChanged.emit())

        if after_row is not None and after_row in self.rows:
            idx = self.rows.index(after_row)
            self.rows.insert(idx + 1, row)
            self.rows_layout.insertWidget(idx + 1, row)
        else:
            idx = len(self.rows)
            self.rows.append(row)
            self.rows_layout.insertWidget(idx, row)

        self.valuesChanged.emit()
        return row

    def _on_remove_row(self, row):
        if row in self.rows:
            self.rows.remove(row)
            self.rows_layout.removeWidget(row)
            row.deleteLater()
            if not self.rows:
                self.add_row("")
            self.valuesChanged.emit()

    def _on_add_after(self, row):
        self.add_row("", after_row=row)