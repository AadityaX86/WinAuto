"""Reusable widgets: toggle switch, spinner, icon buttons, and the launcher's result list."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QModelIndex,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QLabel,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QWidget,
)

from winauto.core.skill import Suggestion
from winauto.ui.icons import icon, pixmap
from winauto.ui.theme import Palette, base_font

SUGGESTION_ROLE = Qt.ItemDataRole.UserRole + 1
HEADER_ROLE = Qt.ItemDataRole.UserRole + 2


class ToggleSwitch(QAbstractButton):
    """An iOS/Windows 11 style on/off switch."""

    def __init__(self, palette: Palette, checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.p = palette
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 24)
        self._offset = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(1, 1, self.width() - 2, self.height() - 2)
        on = QColor(self.p.accent)
        off = QColor(self.p.border)
        mix = QColor(
            int(off.red() + (on.red() - off.red()) * self._offset),
            int(off.green() + (on.green() - off.green()) * self._offset),
            int(off.blue() + (on.blue() - off.blue()) * self._offset),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(mix)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        d = track.height() - 6
        x = track.left() + 3 + (track.width() - d - 6) * self._offset
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(x, track.top() + 3, d, d))


class Spinner(QWidget):
    """A small spinning arc shown while WinAuto is working."""

    def __init__(self, palette: Palette, size: int = 18, parent: QWidget | None = None):
        super().__init__(parent)
        self.p = palette
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self.hide()

    def _step(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def start(self) -> None:
        self.show()
        self._timer.start(60)

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(self.p.accent), 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        r = QRectF(2, 2, self.width() - 4, self.height() - 4)
        painter.drawArc(r, -self._angle * 16, 100 * 16)


def icon_button(name: str, tip: str, palette: Palette, size: int = 18, checkable: bool = False) -> QToolButton:
    btn = QToolButton()
    btn.setObjectName("IconButton")
    btn.setIcon(icon(name, palette.muted, size))
    btn.setIconSize(QSize(size, size))
    btn.setToolTip(tip)
    btn.setCheckable(checkable)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setAutoRaise(True)
    return btn


def kbd(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Kbd")
    return label


class ResultDelegate(QStyledItemDelegate):
    ROW = 46
    HEADER = 30

    def __init__(self, palette: Palette, parent: QWidget | None = None):
        super().__init__(parent)
        self.p = palette
        self.title_font = base_font(10.5)
        self.sub_font = base_font(9.5)
        self.kind_font = base_font(8.5)
        self.header_font = base_font(8.5)
        self.header_font.setWeight(QFont.Weight.DemiBold)
        self.header_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), self.HEADER if index.data(HEADER_ROLE) else self.ROW)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect
        header = index.data(HEADER_ROLE)
        if header:
            painter.setFont(self.header_font)
            painter.setPen(QColor(self.p.faint))
            painter.drawText(rect.adjusted(20, 0, -16, -6), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                             header.upper())
            painter.restore()
            return
        s: Suggestion = index.data(SUGGESTION_ROLE)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        bg = rect.adjusted(8, 2, -8, -2)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.p.selection))
            painter.drawRoundedRect(bg, 9, 9)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.p.hover))
            painter.drawRoundedRect(bg, 9, 9)

        # Icon tile
        tile = QRect(bg.left() + 10, bg.center().y() - 14, 28, 28)
        name = s.icon or "dot"
        real_icon = name.startswith(("file:", "swatch:"))
        if not real_icon:
            painter.setPen(Qt.PenStyle.NoPen)
            accent_tile = name == "sparkles"
            painter.setBrush(QColor(self.p.accent) if accent_tile else QColor(self.p.surface))
            painter.drawRoundedRect(tile, 7, 7)
            color = self.p.accent_text if accent_tile else self.p.text
            px = pixmap(name, color, 16)
            painter.drawPixmap(tile.center().x() - 8, tile.center().y() - 8, px)
        else:
            px = pixmap(name, self.p.text, 24 if name.startswith("file:") else 20)
            size = 24 if name.startswith("file:") else 20
            painter.drawPixmap(tile.center().x() - size // 2, tile.center().y() - size // 2, px)

        # Kind label on the right
        right = bg.right() - 12
        if selected:
            enter = pixmap("enter", self.p.muted, 14)
            painter.drawPixmap(right - 14, bg.center().y() - 7, enter)
            right -= 22
        if s.kind:
            painter.setFont(self.kind_font)
            fm = QFontMetrics(self.kind_font)
            w = fm.horizontalAdvance(s.kind) + 14
            pill = QRect(right - w, bg.center().y() - 10, w, 20)
            painter.setPen(QColor(self.p.muted))
            painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, s.kind)
            right = pill.left() - 8

        # Title + subtitle
        x = tile.right() + 12
        avail = right - x
        painter.setFont(self.title_font)
        tfm = QFontMetrics(self.title_font)
        title = tfm.elidedText(s.title, Qt.TextElideMode.ElideRight, int(avail * 0.75))
        painter.setPen(QColor(self.p.text))
        painter.drawText(QRect(x, bg.top(), avail, bg.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, title)
        if s.subtitle:
            sx = x + tfm.horizontalAdvance(title) + 10
            painter.setFont(self.sub_font)
            sfm = QFontMetrics(self.sub_font)
            sub = sfm.elidedText(s.subtitle, Qt.TextElideMode.ElideRight, max(0, right - sx))
            painter.setPen(QColor(self.p.muted))
            painter.drawText(QRect(sx, bg.top(), right - sx, bg.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, sub)
        painter.restore()


class ResultList(QListView):
    """Keyboard-friendly list of Suggestions, with optional section headers."""

    chosen = Signal(object)  # Suggestion

    def __init__(self, palette: Palette, parent: QWidget | None = None):
        super().__init__(parent)
        self.model_ = QStandardItemModel(self)
        self.setModel(self.model_)
        self.setItemDelegate(ResultDelegate(palette, self))
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setUniformItemSizes(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clicked.connect(self._clicked)

    def set_items(self, groups: list[tuple[str, list[Suggestion]]]) -> None:
        """groups: [(header or "", [Suggestion, ...]), ...]"""
        self.model_.clear()
        first = None
        for header, items in groups:
            if not items:
                continue
            if header:
                h = QStandardItem()
                h.setData(header, HEADER_ROLE)
                h.setFlags(Qt.ItemFlag.NoItemFlags)
                self.model_.appendRow(h)
            for s in items:
                it = QStandardItem(s.title)
                it.setData(s, SUGGESTION_ROLE)
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.model_.appendRow(it)
                if first is None:
                    first = it
        if first is not None:
            self.setCurrentIndex(first.index())
        self.scrollToTop()

    def count(self) -> int:
        return sum(1 for r in range(self.model_.rowCount()) if self.model_.item(r).data(SUGGESTION_ROLE))

    def current(self) -> Suggestion | None:
        idx = self.currentIndex()
        return idx.data(SUGGESTION_ROLE) if idx.isValid() else None

    def move(self, step: int) -> None:
        rows = [r for r in range(self.model_.rowCount()) if self.model_.item(r).data(SUGGESTION_ROLE)]
        if not rows:
            return
        cur = self.currentIndex().row()
        pos = rows.index(cur) if cur in rows else -1
        nxt = rows[max(0, min(len(rows) - 1, pos + step))]
        self.setCurrentIndex(self.model_.index(nxt, 0))
        self.scrollTo(self.model_.index(nxt, 0))

    def _clicked(self, index: QModelIndex) -> None:
        s = index.data(SUGGESTION_ROLE)
        if s is not None:
            self.chosen.emit(s)

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        idx = self.indexAt(event.position().toPoint())
        if idx.isValid() and idx.data(SUGGESTION_ROLE) is not None and idx != self.currentIndex():
            self.setCurrentIndex(idx)
        super().mouseMoveEvent(event)
