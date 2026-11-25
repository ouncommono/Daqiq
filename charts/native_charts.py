"""Pure QPainter high-DPI RTL interactive charts (zero matplotlib / QtCharts)."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from utils.printing import to_persian_digits

_PALETTE_LIGHT = (
    "#2563eb",
    "#059669",
    "#d97706",
    "#7c3aed",
    "#db2777",
    "#0891b2",
    "#dc2626",
    "#4f46e5",
    "#65a30d",
    "#ea580c",
)

_PALETTE_DARK = (
    "#60a5fa",
    "#34d399",
    "#fbbf24",
    "#a78bfa",
    "#f472b6",
    "#22d3ee",
    "#f87171",
    "#818cf8",
    "#a3e635",
    "#fb923c",
)


def format_persian_compact_number(val: float, is_currency: bool = True) -> str:
    """Smart Persian axis scaling without cramped decimals (هزار / میلیون / میلیارد)."""
    sign = "-" if val < 0 else ""
    abs_v = abs(float(val))
    if abs_v >= 1_000_000_000:
        num = abs_v / 1_000_000_000.0
        txt = f"{num:.1f}".rstrip("0").rstrip(".") + " میلیارد"
    elif abs_v >= 1_000_000:
        num = abs_v / 1_000_000.0
        txt = f"{num:.1f}".rstrip("0").rstrip(".") + " میلیون"
    elif abs_v >= 1_000:
        num = abs_v / 1_000.0
        txt = f"{num:.1f}".rstrip("0").rstrip(".") + " هزار"
    else:
        txt = f"{int(round(abs_v)):,}"
    return to_persian_digits(f"{sign}{txt}")


def format_exact_value_fa(val: float, unit_label: str = "تومان") -> str:
    num = int(round(val))
    suffix = f" {unit_label}" if unit_label else ""
    return to_persian_digits(f"{num:,}{suffix}")


class NativeChartWidget(QWidget):
    """High-DPI RTL native QPainter chart canvas supporting Bar, HBar, Line/Area, and Donut."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMouseTracking(True)
        self.setMinimumHeight(340)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._title: str = "نمودار تحلیلی"
        self._subtitle: str = ""
        self._chart_type: str = "bar"  # bar | hbar | line | donut
        self._series: List[Dict[str, Any]] = []
        self._unit_label: str = "تومان"
        self._dark: bool = False
        self._hovered_index: int = -1
        self._hit_regions: List[Tuple[int, QRectF, str]] = []
        self._wedge_centers: List[Tuple[int, QPointF, float, float, float, str]] = []

    def set_dark_theme(self, dark: bool) -> None:
        self._dark = bool(dark)
        self.update()

    def set_data(
        self,
        *,
        title: str,
        subtitle: str = "",
        chart_type: str = "bar",
        items: Sequence[Dict[str, Any]],
        unit_label: str = "تومان",
    ) -> None:
        """Update chart series items: [{'label': str, 'value': float, 'extra': str?}]."""
        self._title = str(title or "").strip()
        self._subtitle = str(subtitle or "").strip()
        self._chart_type = str(chart_type or "bar").strip().lower()
        self._unit_label = str(unit_label or "").strip()
        clean_items: List[Dict[str, Any]] = []
        for idx, item in enumerate(items or []):
            clean_items.append({
                "label": str(item.get("label") or f"مورد {idx + 1}").strip(),
                "value": float(item.get("value") or 0),
                "extra": str(item.get("extra") or "").strip(),
            })
        self._series = clean_items
        self._hovered_index = -1
        self.update()

    def _palette(self) -> Tuple[str, ...]:
        return _PALETTE_DARK if self._dark else _PALETTE_LIGHT

    def _theme_tokens(self) -> Dict[str, QColor]:
        if self._dark:
            return {
                "bg": QColor("#111827"),
                "card": QColor("#1f2937"),
                "border": QColor("#374151"),
                "grid": QColor("#2d3a4f"),
                "axis": QColor("#64748b"),
                "text": QColor("#f1f5f9"),
                "muted": QColor("#94a3b8"),
                "highlight": QColor(255, 255, 255, 45),
            }
        return {
            "bg": QColor("#ffffff"),
            "card": QColor("#ffffff"),
            "border": QColor("#cbd5e1"),
            "grid": QColor("#e2e8f0"),
            "axis": QColor("#64748b"),
            "text": QColor("#0f172a"),
            "muted": QColor("#475569"),
            "highlight": QColor(37, 99, 235, 30),
        }

    def render_to_painter(self, p: QPainter, width: int, height: int, print_bw: bool = False) -> None:
        """Render the complete chart onto any QPainter (widget screen or offscreen PNG/print)."""
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        if print_bw:
            tokens = {
                "bg": QColor("#ffffff"),
                "card": QColor("#ffffff"),
                "border": QColor("#000000"),
                "grid": QColor("#cccccc"),
                "axis": QColor("#000000"),
                "text": QColor("#000000"),
                "muted": QColor("#222222"),
                "highlight": QColor(0, 0, 0, 20),
            }
            palette = ("#111111", "#3b3b3b", "#666666", "#888888", "#262626", "#525252")
        else:
            tokens = self._theme_tokens()
            palette = self._palette()

        self._hit_regions = []
        self._wedge_centers = []

        # Background card
        rect = QRectF(0, 0, max(200, width), max(180, height))
        p.fillRect(rect, tokens["card"])
        p.setPen(QPen(tokens["border"], 1.2))
        p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 10, 10)

        # Header area
        pad = 16.0
        title_font = QFont("B Titr" if print_bw else "Tahoma", 12, QFont.Bold)
        sub_font = QFont("Tahoma", 9)
        p.setFont(title_font)
        p.setPen(tokens["text"])
        title_rect = QRectF(pad, 10, width - 2 * pad, 24)
        p.drawText(title_rect, Qt.AlignRight | Qt.AlignVCenter, to_persian_digits(self._title))

        top_offset = 40.0
        if self._subtitle:
            p.setFont(sub_font)
            p.setPen(tokens["muted"])
            p.drawText(
                QRectF(pad, 34, width - 2 * pad, 18),
                Qt.AlignRight | Qt.AlignVCenter,
                to_persian_digits(self._subtitle),
            )
            top_offset = 56.0

        # Empty state check
        has_nonzero = bool(self._series) and any(abs(float(x["value"])) > 0 for x in self._series)
        if not self._series or not has_nonzero:
            empty_rect = QRectF(pad, top_offset, width - 2 * pad, height - top_offset - pad)
            p.setFont(QFont("Tahoma", 11, QFont.Bold))
            p.setPen(tokens["muted"])
            p.drawText(
                empty_rect,
                Qt.AlignCenter | Qt.TextWordWrap,
                "داده‌ای برای نمایش در بازه یا فیلتر انتخاب‌شده وجود ندارد.",
            )
            p.restore()
            return

        plot_rect = QRectF(pad, top_offset + 6, width - 2 * pad, max(80.0, height - top_offset - pad - 10))
        ctype = self._chart_type
        if ctype == "hbar":
            self._draw_hbar(p, plot_rect, tokens, palette)
        elif ctype == "line":
            self._draw_line(p, plot_rect, tokens, palette)
        elif ctype == "donut":
            self._draw_donut(p, plot_rect, tokens, palette)
        else:
            self._draw_vbar(p, plot_rect, tokens, palette)

        p.restore()

    def _nice_max_value(self) -> float:
        vals = [max(0.0, float(item["value"])) for item in self._series]
        mx = max(vals) if vals else 0.0
        if mx <= 0:
            return 1.0
        mag = 10.0 ** math.floor(math.log10(mx))
        norm = mx / mag
        if norm <= 1.2:
            nice = 1.2
        elif norm <= 1.5:
            nice = 1.5
        elif norm <= 2.0:
            nice = 2.0
        elif norm <= 2.5:
            nice = 2.5
        elif norm <= 5.0:
            nice = 5.0
        elif norm <= 8.0:
            nice = 8.0
        else:
            nice = 10.0
        return nice * mag

    def _draw_vbar(self, p: QPainter, area: QRectF, tokens: Dict[str, QColor], palette: Tuple[str, ...]) -> None:
        left_margin = 76.0
        bottom_margin = 52.0
        right_margin = 14.0
        chart = QRectF(
            area.left() + left_margin,
            area.top() + 8.0,
            max(60.0, area.width() - left_margin - right_margin),
            max(50.0, area.height() - bottom_margin - 8.0),
        )
        y_max = self._nice_max_value()
        ticks = 4
        p.setFont(QFont("Tahoma", 8))
        for i in range(ticks + 1):
            frac = i / ticks
            y = chart.bottom() - frac * chart.height()
            p.setPen(QPen(tokens["axis"] if i == 0 else tokens["grid"], 1.2 if i == 0 else 1.0, Qt.SolidLine if i == 0 else Qt.DashLine))
            p.drawLine(QPointF(chart.left(), y), QPointF(chart.right(), y))
            lbl = format_persian_compact_number(y_max * frac)
            p.setPen(tokens["muted"])
            p.drawText(QRectF(area.left(), y - 10, left_margin - 8, 20), Qt.AlignLeft | Qt.AlignVCenter, lbl)

        n = len(self._series)
        slot_w = chart.width() / max(1, n)
        bar_w = min(56.0, max(10.0, slot_w * 0.58))
        for idx, item in enumerate(self._series):
            # Under RTL reading order, place index 0 cleanly from RIGHT toward LEFT
            x_center = chart.right() - (idx + 0.5) * slot_w
            val = max(0.0, float(item["value"]))
            bar_h = (val / y_max) * chart.height() if y_max > 0 else 0.0
            bar_rect = QRectF(x_center - bar_w / 2.0, chart.bottom() - bar_h, bar_w, max(2.0 if val > 0 else 0.0, bar_h))

            col = QColor(palette[idx % len(palette)])
            if idx == self._hovered_index:
                p.fillRect(QRectF(x_center - slot_w / 2.0, chart.top(), slot_w, chart.height()), tokens["highlight"])
                col = col.lighter(115)

            path = QPainterPath()
            r = min(5.0, bar_w / 2.0, bar_rect.height())
            path.addRoundedRect(bar_rect, r, r)
            p.fillPath(path, QBrush(col))

            # Value label above bar if enough room
            if slot_w >= 46:
                p.setFont(QFont("Tahoma", 7))
                p.setPen(tokens["text"])
                p.drawText(
                    QRectF(x_center - slot_w / 2.0, max(area.top(), bar_rect.top() - 18), slot_w, 16),
                    Qt.AlignCenter,
                    format_persian_compact_number(val),
                )

            # X-axis label
            p.setFont(QFont("Tahoma", 8))
            p.setPen(tokens["text"])
            lbl = item["label"]
            fm = p.fontMetrics()
            elided = fm.elidedText(to_persian_digits(lbl), Qt.ElideRight, int(max(28.0, slot_w - 6)))
            p.drawText(
                QRectF(x_center - slot_w / 2.0 + 2, chart.bottom() + 4, max(24.0, slot_w - 4), bottom_margin - 6),
                Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                elided,
            )

            tip = f"{to_persian_digits(lbl)}\nمقدار: {format_exact_value_fa(val, self._unit_label)}"
            if item.get("extra"):
                tip += f"\n{to_persian_digits(item['extra'])}"
            self._hit_regions.append((idx, QRectF(x_center - slot_w / 2.0, chart.top(), slot_w, chart.height()), tip))

    def _draw_hbar(self, p: QPainter, area: QRectF, tokens: Dict[str, QColor], palette: Tuple[str, ...]) -> None:
        label_col_w = min(190.0, area.width() * 0.34)
        value_col_w = 88.0
        chart = QRectF(
            area.left() + value_col_w,
            area.top() + 8.0,
            max(60.0, area.width() - label_col_w - value_col_w - 8.0),
            max(50.0, area.height() - 18.0),
        )
        x_max = self._nice_max_value()
        n = len(self._series)
        row_h = chart.height() / max(1, n)
        bar_h = min(28.0, max(8.0, row_h * 0.56))

        for idx, item in enumerate(self._series):
            y_center = chart.top() + (idx + 0.5) * row_h
            val = max(0.0, float(item["value"]))
            bar_w = (val / x_max) * chart.width() if x_max > 0 else 0.0
            # Bars grow leftward from the right axis under RTL
            bar_rect = QRectF(chart.right() - bar_w, y_center - bar_h / 2.0, max(2.0 if val > 0 else 0.0, bar_w), bar_h)

            if idx == self._hovered_index:
                p.fillRect(QRectF(area.left(), y_center - row_h / 2.0, area.width(), row_h), tokens["highlight"])

            col = QColor(palette[idx % len(palette)])
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(bar_rect, 4, 4)

            p.setFont(QFont("Tahoma", 8))
            p.setPen(tokens["text"])
            fm = p.fontMetrics()
            elided = fm.elidedText(to_persian_digits(item["label"]), Qt.ElideRight, int(label_col_w - 8))
            p.drawText(
                QRectF(chart.right() + 6, y_center - row_h / 2.0, label_col_w - 6, row_h),
                Qt.AlignRight | Qt.AlignVCenter,
                elided,
            )

            p.setPen(tokens["muted"])
            p.drawText(
                QRectF(area.left(), y_center - row_h / 2.0, value_col_w - 6, row_h),
                Qt.AlignLeft | Qt.AlignVCenter,
                format_persian_compact_number(val),
            )

            tip = f"{to_persian_digits(item['label'])}\nمقدار: {format_exact_value_fa(val, self._unit_label)}"
            if item.get("extra"):
                tip += f"\n{to_persian_digits(item['extra'])}"
            self._hit_regions.append((idx, QRectF(area.left(), y_center - row_h / 2.0, area.width(), row_h), tip))

    def _draw_line(self, p: QPainter, area: QRectF, tokens: Dict[str, QColor], palette: Tuple[str, ...]) -> None:
        left_margin = 76.0
        bottom_margin = 44.0
        right_margin = 18.0
        chart = QRectF(
            area.left() + left_margin,
            area.top() + 10.0,
            max(60.0, area.width() - left_margin - right_margin),
            max(50.0, area.height() - bottom_margin - 10.0),
        )
        y_max = self._nice_max_value()
        ticks = 4
        p.setFont(QFont("Tahoma", 8))
        for i in range(ticks + 1):
            frac = i / ticks
            y = chart.bottom() - frac * chart.height()
            p.setPen(QPen(tokens["axis"] if i == 0 else tokens["grid"], 1.2 if i == 0 else 1.0, Qt.SolidLine if i == 0 else Qt.DashLine))
            p.drawLine(QPointF(chart.left(), y), QPointF(chart.right(), y))
            p.setPen(tokens["muted"])
            p.drawText(
                QRectF(area.left(), y - 10, left_margin - 8, 20),
                Qt.AlignLeft | Qt.AlignVCenter,
                format_persian_compact_number(y_max * frac),
            )

        n = len(self._series)
        pts: List[QPointF] = []
        for idx, item in enumerate(self._series):
            # Chronological trends read intuitively left->right in time (standard financial/analytics axis)
            x = chart.left() + (chart.width() * 0.5 if n == 1 else (idx / max(1, n - 1)) * chart.width())
            val = max(0.0, float(item["value"]))
            y = chart.bottom() - (val / y_max) * chart.height() if y_max > 0 else chart.bottom()
            pts.append(QPointF(x, y))

        line_color = QColor(palette[0])
        if len(pts) >= 2:
            fill_path = QPainterPath(QPointF(pts[0].x(), chart.bottom()))
            for pt in pts:
                fill_path.lineTo(pt)
            fill_path.lineTo(QPointF(pts[-1].x(), chart.bottom()))
            fill_path.closeSubpath()
            grad = QLinearGradient(0, chart.top(), 0, chart.bottom())
            c_top = QColor(line_color)
            c_top.setAlpha(75)
            c_bot = QColor(line_color)
            c_bot.setAlpha(6)
            grad.setColorAt(0.0, c_top)
            grad.setColorAt(1.0, c_bot)
            p.fillPath(fill_path, grad)

            stroke = QPainterPath(pts[0])
            for pt in pts[1:]:
                stroke.lineTo(pt)
            p.setPen(QPen(line_color, 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(stroke)

        step_label = max(1, (n + 7) // 8)
        slot_w = chart.width() / max(1, n)
        for idx, (pt, item) in enumerate(zip(pts, self._series)):
            is_hov = idx == self._hovered_index
            r = 6.0 if is_hov else 3.8
            p.setPen(QPen(tokens["card"], 1.5))
            p.setBrush(line_color.lighter(120) if is_hov else line_color)
            p.drawEllipse(pt, r, r)
            if is_hov:
                p.setPen(QPen(tokens["grid"], 1, Qt.DashLine))
                p.drawLine(QPointF(pt.x(), chart.top()), QPointF(pt.x(), chart.bottom()))

            if idx % step_label == 0 or idx == n - 1:
                p.setFont(QFont("Tahoma", 7))
                p.setPen(tokens["muted"])
                p.drawText(
                    QRectF(pt.x() - 38, chart.bottom() + 4, 76, 22),
                    Qt.AlignCenter,
                    to_persian_digits(item["label"]),
                )

            tip = f"{to_persian_digits(item['label'])}\nمقدار: {format_exact_value_fa(item['value'], self._unit_label)}"
            if item.get("extra"):
                tip += f"\n{to_persian_digits(item['extra'])}"
            self._hit_regions.append((idx, QRectF(pt.x() - max(10.0, slot_w / 2.0), chart.top(), max(20.0, slot_w), chart.height()), tip))

    def _draw_donut(self, p: QPainter, area: QRectF, tokens: Dict[str, QColor], palette: Tuple[str, ...]) -> None:
        total = sum(max(0.0, float(x["value"])) for x in self._series)
        if total <= 0:
            return
        legend_w = min(260.0, area.width() * 0.42)
        pie_box = QRectF(area.left() + 12, area.top() + 8, max(80.0, area.width() - legend_w - 24), area.height() - 16)
        side = min(pie_box.width(), pie_box.height()) * 0.88
        center = pie_box.center()
        pie_rect = QRectF(center.x() - side / 2.0, center.y() - side / 2.0, side, side)

        start_deg = 90.0
        legend_top = area.top() + 12.0
        legend_x = area.right() - legend_w
        row_h = min(26.0, (area.height() - 20.0) / max(1, len(self._series)))

        for idx, item in enumerate(self._series):
            val = max(0.0, float(item["value"]))
            span_deg = (val / total) * 360.0
            col = QColor(palette[idx % len(palette)])
            if idx == self._hovered_index:
                col = col.lighter(115)

            p.setPen(QPen(tokens["card"], 1.5))
            p.setBrush(col)
            draw_rect = pie_rect.adjusted(-4, -4, 4, 4) if idx == self._hovered_index else pie_rect
            p.drawPie(draw_rect, int(round(start_deg * 16)), int(round(-span_deg * 16)))

            tip = (
                f"{to_persian_digits(item['label'])}\n"
                f"سهم: {to_persian_digits(f'{(val / total) * 100:.1f}%')}\n"
                f"مبلغ: {format_exact_value_fa(val, self._unit_label)}"
            )
            if item.get("extra"):
                tip += f"\n{to_persian_digits(item['extra'])}"
            self._wedge_centers.append((idx, center, side * 0.24, side * 0.52, start_deg, span_deg, tip))
            start_deg -= span_deg

            # Legend row on right
            ly = legend_top + idx * row_h
            swatch = QRectF(legend_x + legend_w - 18, ly + (row_h - 12) / 2.0, 12, 12)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(swatch, 3, 3)

            pct_str = to_persian_digits(f"{(val / total) * 100:.1f}%")
            p.setFont(QFont("Tahoma", 8))
            p.setPen(tokens["text"])
            fm = p.fontMetrics()
            lbl_max = int(max(40.0, legend_w - 86))
            elided = fm.elidedText(to_persian_digits(item["label"]), Qt.ElideRight, lbl_max)
            p.drawText(QRectF(legend_x + 56, ly, legend_w - 80, row_h), Qt.AlignRight | Qt.AlignVCenter, elided)
            p.setPen(tokens["muted"])
            p.drawText(QRectF(legend_x, ly, 54, row_h), Qt.AlignLeft | Qt.AlignVCenter, pct_str)
            self._hit_regions.append((idx, QRectF(legend_x, ly, legend_w, row_h), tip))

        # Inner hole for Donut crispness + total label
        hole_r = side * 0.27
        hole_rect = QRectF(center.x() - hole_r, center.y() - hole_r, hole_r * 2.0, hole_r * 2.0)
        p.setPen(Qt.NoPen)
        p.setBrush(tokens["card"])
        p.drawEllipse(hole_rect)
        p.setFont(QFont("Tahoma", 8, QFont.Bold))
        p.setPen(tokens["text"])
        p.drawText(hole_rect, Qt.AlignCenter, f"کل\n{format_persian_compact_number(total)}")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        self.render_to_painter(painter, self.width(), self.height(), print_bw=False)
        painter.end()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        hit_idx = -1
        hit_tip = ""
        for idx, rect, tip in self._hit_regions:
            if rect.contains(pos):
                hit_idx = idx
                hit_tip = tip
                break
        if hit_idx < 0 and self._wedge_centers:
            for item in self._wedge_centers:
                idx, center, r_in, r_out, start_deg, span_deg, tip = item
                dx = pos.x() - center.x()
                dy = center.y() - pos.y()
                dist = math.hypot(dx, dy)
                if r_in <= dist <= r_out:
                    ang = (math.degrees(math.atan2(dy, dx))) % 360.0
                    # Wedges sweep clockwise from start_deg
                    offset = (start_deg - ang) % 360.0
                    if 0.0 <= offset <= abs(span_deg):
                        hit_idx = idx
                        hit_tip = tip
                        break

        if hit_idx != self._hovered_index:
            self._hovered_index = hit_idx
            self.update()
        if hit_idx >= 0 and hit_tip:
            QToolTip.showText(event.globalPosition().toPoint(), hit_tip, self)
        else:
            QToolTip.hideText()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hovered_index != -1:
            self._hovered_index = -1
            self.update()
        QToolTip.hideText()
        super().leaveEvent(event)

    def render_png_bytes(self, width: int = 920, height: int = 440, print_bw: bool = False) -> bytes:
        """Render the chart crisp & standalone to PNG bytes (for Word/Print/PNG export)."""
        pm = QPixmap(max(400, width), max(220, height))
        pm.fill(Qt.white if print_bw else self._theme_tokens()["card"])
        p = QPainter(pm)
        self.render_to_painter(p, pm.width(), pm.height(), print_bw=print_bw)
        p.end()
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        pm.save(buf, "PNG")
        return bytes(buf.data())
