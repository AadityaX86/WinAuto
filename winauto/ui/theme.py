"""Colours, fonts and stylesheet. Follows the Windows light/dark setting."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QLinearGradient, QPainter, QPalette, QPixmap


@dataclass(frozen=True)
class Palette:
    name: str
    panel: str  # window background
    surface: str  # cards, icon tiles
    hover: str
    selection: str  # selected result row
    border: str
    text: str
    muted: str
    faint: str
    accent: str
    accent_2: str  # second gradient stop
    accent_text: str
    user_bg: str
    bot_bg: str
    card_bg: str
    input_bg: str
    danger: str
    success: str
    warning: str


DARK = Palette(
    name="dark", panel="#17181c", surface="#22232a", hover="#25262d", selection="#2b2a4d", border="#2d2e36",
    text="#ececf1", muted="#9598a6", faint="#5e616e", accent="#7c74ff", accent_2="#a65cff", accent_text="#ffffff",
    user_bg="#34306f", bot_bg="#212228", card_bg="#1e1f25", input_bg="#111216", danger="#ff6b6b",
    success="#45d18f", warning="#f5b54a",
)
LIGHT = Palette(
    name="light", panel="#fbfbfd", surface="#f0f0f5", hover="#f2f2f7", selection="#e9e7ff", border="#e2e2ea",
    text="#15161b", muted="#696c79", faint="#a3a5b1", accent="#5b55f0", accent_2="#9146ff", accent_text="#ffffff",
    user_bg="#e8e6ff", bot_bg="#f2f2f6", card_bg="#ffffff", input_bg="#ffffff", danger="#d93f3f",
    success="#13a26b", warning="#c98a0c",
)


def is_dark() -> bool:
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except AttributeError:
        pass
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            ) as key:
                return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
        except OSError:
            pass
    return False


def palette(mode: str = "system") -> Palette:
    if mode == "dark":
        return DARK
    if mode == "light":
        return LIGHT
    return DARK if is_dark() else LIGHT


FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", "sans-serif"]
DISPLAY_FAMILIES = ["Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI", "Inter", "Noto Sans", "sans-serif"]


def base_font(size: float = 10.0) -> QFont:
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSizeF(size)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def display_font(size: float, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    font = QFont()
    font.setFamilies(DISPLAY_FAMILIES)
    font.setPointSizeF(size)
    font.setWeight(weight)
    return font


def rgba(hex_color: str, alpha: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha:.2f})"


def apply_palette(app: QGuiApplication, p: Palette) -> None:
    """Link colours in rich text and default text colours come from the QPalette."""
    qp = app.palette()
    qp.setColor(QPalette.ColorRole.Link, QColor(p.accent))
    qp.setColor(QPalette.ColorRole.LinkVisited, QColor(p.accent))
    qp.setColor(QPalette.ColorRole.Highlight, QColor(p.accent))
    qp.setColor(QPalette.ColorRole.HighlightedText, QColor(p.accent_text))
    qp.setColor(QPalette.ColorRole.Window, QColor(p.panel))
    qp.setColor(QPalette.ColorRole.WindowText, QColor(p.text))
    qp.setColor(QPalette.ColorRole.Base, QColor(p.input_bg))
    qp.setColor(QPalette.ColorRole.Text, QColor(p.text))
    qp.setColor(QPalette.ColorRole.PlaceholderText, QColor(p.faint))
    qp.setColor(QPalette.ColorRole.Button, QColor(p.surface))
    qp.setColor(QPalette.ColorRole.ButtonText, QColor(p.text))
    app.setPalette(qp)


def stylesheet(p: Palette) -> str:
    return f"""
    QWidget {{ color: {p.text}; }}
    QToolTip {{ background: {p.card_bg}; color: {p.text}; border: 1px solid {p.border}; padding: 4px 8px; border-radius: 6px; }}
    #Panel {{ background: {p.panel}; border: 1px solid {p.border}; border-radius: 16px; }}
    #Divider {{ background: {p.border}; max-height: 1px; min-height: 1px; border: none; }}
    #SearchInput {{ background: transparent; border: none; padding: 4px 2px; font-size: 15pt;
                   selection-background-color: {p.accent}; }}
    #Greeting {{ font-size: 16pt; font-weight: 600; }}
    #SubGreeting, #Status, #Muted {{ color: {p.muted}; }}
    #Muted {{ font-size: 9pt; }}
    #SectionTitle {{ color: {p.faint}; font-size: 8.5pt; font-weight: 600; letter-spacing: 0.6px; }}
    #Footer {{ color: {p.muted}; font-size: 9pt; }}
    #Kbd {{ color: {p.muted}; background: {p.surface}; border: 1px solid {p.border}; border-radius: 4px;
            padding: 0px 5px; font-size: 8.5pt; }}
    #Toast {{ color: {p.success}; font-size: 9pt; font-weight: 600; }}
    #Widget {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px; }}
    #WidgetText {{ font-size: 9.5pt; }}
    QScrollArea, #Conversation, #Transparent {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {rgba(p.muted, 0.35)}; border-radius: 3px; min-height: 30px; margin: 0 2px; }}
    QScrollBar::handle:vertical:hover {{ background: {rgba(p.muted, 0.6)}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
    QListView {{ background: transparent; border: none; outline: none; }}
    #UserBubble {{ background: {p.user_bg}; border-radius: 14px; padding: 9px 13px; }}
    #BotBubble {{ background: {p.bot_bg}; border: 1px solid {p.border}; border-radius: 14px; padding: 9px 13px; }}
    #ErrorBubble {{ background: {rgba(p.danger, 0.10)}; border: 1px solid {rgba(p.danger, 0.45)}; border-radius: 14px; padding: 9px 13px; }}
    #Steps {{ color: {p.muted}; font-size: 8.5pt; }}
    #Quote {{ background: {p.surface}; border-left: 3px solid {p.accent}; border-radius: 8px; padding: 10px 12px; color: {p.muted}; }}
    #Card {{ background: {p.card_bg}; border: 1px solid {rgba(p.accent, 0.55)}; border-radius: 14px; }}
    #CardTitle {{ font-weight: 600; font-size: 10.5pt; }}
    QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{ background: {p.input_bg}; border: 1px solid {p.border};
        border-radius: 8px; padding: 6px 9px; selection-background-color: {p.accent}; selection-color: {p.accent_text}; }}
    QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {p.accent}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QSpinBox::up-button, QSpinBox::down-button {{ width: 0px; border: none; }}
    QMenu {{ background: {p.card_bg}; border: 1px solid {p.border}; border-radius: 10px; padding: 6px; }}
    QMenu::item {{ padding: 7px 26px 7px 14px; border-radius: 6px; color: {p.text}; }}
    QMenu::item:selected {{ background: {p.selection}; }}
    QMenu::separator {{ height: 1px; background: {p.border}; margin: 5px 8px; }}
    QComboBox QAbstractItemView {{ background: {p.card_bg}; border: 1px solid {p.border}; selection-background-color: {p.selection};
        selection-color: {p.text}; outline: none; padding: 4px; }}
    QPushButton {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px; padding: 7px 14px; }}
    QPushButton:hover {{ background: {p.hover}; border-color: {rgba(p.accent, 0.6)}; }}
    QPushButton:pressed {{ background: {p.selection}; }}
    QPushButton:disabled {{ color: {p.faint}; }}
    QPushButton#Primary {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {p.accent}, stop:1 {p.accent_2});
        color: {p.accent_text}; border: none; font-weight: 600; }}
    QPushButton#Primary:hover {{ background: {p.accent}; }}
    QPushButton#Danger {{ color: {p.danger}; }}
    QPushButton#Chip {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 15px; padding: 6px 13px;
        text-align: left; }}
    QPushButton#Chip:hover {{ border-color: {p.accent}; background: {p.selection}; }}
    QToolButton#IconButton {{ background: transparent; border: none; border-radius: 8px; padding: 6px; }}
    QToolButton#IconButton:hover {{ background: {p.hover}; }}
    QToolButton#IconButton:checked {{ background: {p.selection}; }}
    QDialog, #SettingsPage {{ background: {p.panel}; }}
    #Sidebar {{ background: {p.surface}; border: none; border-right: 1px solid {p.border}; padding: 8px 6px; }}
    #Sidebar::item {{ padding: 8px 10px; border-radius: 8px; margin: 1px 4px; color: {p.text}; }}
    #Sidebar::item:selected {{ background: {p.selection}; color: {p.text}; }}
    #Sidebar::item:hover:!selected {{ background: {p.hover}; }}
    #PageTitle {{ font-size: 17pt; font-weight: 600; }}
    #SettingsCard {{ background: {p.card_bg}; border: 1px solid {p.border}; border-radius: 12px; }}
    #RowTitle {{ font-weight: 500; }}
    #RowHelp {{ color: {p.muted}; font-size: 9pt; }}
    #RowDivider {{ background: {p.border}; max-height: 1px; min-height: 1px; }}
    QCheckBox {{ spacing: 8px; }}
    QLabel {{ background: transparent; }}
    """


def app_icon() -> QIcon:
    """A drawn icon so the app ships without image files: gradient tile with a spark."""
    icon = QIcon()
    for s in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        pix = QPixmap(s, s)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        grad = QLinearGradient(0, 0, s, s)
        grad.setColorAt(0, QColor("#6b7bff"))
        grad.setColorAt(1, QColor("#a14dff"))
        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, s, s, s * 0.24, s * 0.24)
        # Four-point spark
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPainterPath

        c, r, w = s / 2, s * 0.30, s * 0.075
        path = QPainterPath()
        path.moveTo(QPointF(c, c - r))
        path.cubicTo(QPointF(c + w * 0.4, c - w), QPointF(c + w, c - w * 0.4), QPointF(c + r, c))
        path.cubicTo(QPointF(c + w, c + w * 0.4), QPointF(c + w * 0.4, c + w), QPointF(c, c + r))
        path.cubicTo(QPointF(c - w * 0.4, c + w), QPointF(c - w, c + w * 0.4), QPointF(c - r, c))
        path.cubicTo(QPointF(c - w, c - w * 0.4), QPointF(c - w * 0.4, c - w), QPointF(c, c - r))
        painter.setBrush(QColor("white"))
        painter.drawPath(path)
        painter.end()
        icon.addPixmap(pix)
    return icon
