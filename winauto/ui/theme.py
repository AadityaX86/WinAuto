"""Colors and stylesheet. Follows the Windows light/dark setting."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QLinearGradient, QPainter, QPalette, QPixmap


@dataclass(frozen=True)
class Palette:
    panel: str
    border: str
    text: str
    muted: str
    accent: str
    accent_text: str
    user_bg: str
    bot_bg: str
    card_bg: str
    input_bg: str
    danger: str
    success: str


DARK = Palette(
    panel="#1e1f24", border="#373945", text="#ececf1", muted="#9a9cab", accent="#4f8cff",
    accent_text="#ffffff", user_bg="#2a3a5c", bot_bg="#2a2b32", card_bg="#25262d",
    input_bg="#16171b", danger="#f06a6a", success="#4cc38a",
)
LIGHT = Palette(
    panel="#ffffff", border="#d8d9e0", text="#1b1c20", muted="#6b6d78", accent="#2563eb",
    accent_text="#ffffff", user_bg="#e6efff", bot_bg="#f2f3f6", card_bg="#fafafc",
    input_bg="#f6f7f9", danger="#d33b3b", success="#1f9d61",
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


def palette() -> Palette:
    return DARK if is_dark() else LIGHT


def apply_palette(app: QGuiApplication, p: Palette) -> None:
    """Link colours in rich text come from the palette, not the stylesheet."""
    qp = app.palette()
    qp.setColor(QPalette.ColorRole.Link, QColor(p.accent))
    qp.setColor(QPalette.ColorRole.LinkVisited, QColor(p.accent))
    app.setPalette(qp)


def base_font() -> QFont:
    font = QFont()
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", "sans-serif"])
    font.setPointSizeF(10.0)
    return font


def stylesheet(p: Palette) -> str:
    return f"""
    QWidget {{ color: {p.text}; }}
    #Panel {{ background: {p.panel}; border: 1px solid {p.border}; border-radius: 14px; }}
    #Title {{ font-weight: 600; font-size: 11pt; }}
    #Status {{ color: {p.muted}; }}
    #Muted {{ color: {p.muted}; font-size: 9pt; }}
    QScrollArea, #Conversation {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 4px; min-height: 24px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    #UserBubble {{ background: {p.user_bg}; border-radius: 12px; padding: 8px 12px; }}
    #BotBubble {{ background: {p.bot_bg}; border-radius: 12px; padding: 8px 12px; }}
    #ErrorBubble {{ background: {p.bot_bg}; border: 1px solid {p.danger}; border-radius: 12px; padding: 8px 12px; }}
    #Card {{ background: {p.card_bg}; border: 1px solid {p.accent}; border-radius: 12px; }}
    #CardTitle {{ font-weight: 600; }}
    #Input {{ background: {p.input_bg}; border: 1px solid {p.border}; border-radius: 10px;
              padding: 9px 12px; font-size: 11pt; selection-background-color: {p.accent}; }}
    #Input:focus {{ border: 1px solid {p.accent}; }}
    QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{ background: {p.input_bg}; border: 1px solid {p.border};
              border-radius: 6px; padding: 4px 6px; selection-background-color: {p.accent}; }}
    QPushButton {{ background: {p.bot_bg}; border: 1px solid {p.border}; border-radius: 8px; padding: 6px 14px; }}
    QPushButton:hover {{ border-color: {p.accent}; }}
    QPushButton:disabled {{ color: {p.muted}; }}
    QPushButton#Primary {{ background: {p.accent}; color: {p.accent_text}; border: 1px solid {p.accent}; font-weight: 600; }}
    QPushButton#Danger {{ color: {p.danger}; }}
    QPushButton#Icon {{ background: transparent; border: none; padding: 4px 8px; color: {p.muted}; font-size: 11pt; }}
    QPushButton#Icon:hover {{ color: {p.text}; }}
    QDialog {{ background: {p.panel}; }}
    QGroupBox {{ border: 1px solid {p.border}; border-radius: 8px; margin-top: 12px; padding-top: 8px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
    QCheckBox {{ spacing: 8px; }}
    QTabWidget::pane {{ border: 1px solid {p.border}; border-radius: 8px; background: {p.panel}; top: -1px; }}
    QTabWidget > QStackedWidget > QWidget {{ background: {p.panel}; }}
    QTabBar::tab {{ background: {p.bot_bg}; color: {p.muted}; border: 1px solid {p.border}; padding: 6px 16px;
                   border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
    QTabBar::tab:selected {{ background: {p.panel}; color: {p.text}; border-bottom-color: {p.panel}; }}
    QLabel {{ background: transparent; }}
    """


def app_icon(size: int = 64) -> QIcon:
    """A simple drawn icon so the app ships without image files."""
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        pix = QPixmap(s, s)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        grad = QLinearGradient(0, 0, s, s)
        grad.setColorAt(0, QColor("#5b8cff"))
        grad.setColorAt(1, QColor("#7b4dff"))
        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, s, s, s * 0.22, s * 0.22)
        font = QFont("Segoe UI")
        font.setBold(True)
        font.setPixelSize(int(s * 0.6))
        painter.setFont(font)
        painter.setPen(QColor("white"))
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "W")
        painter.end()
        icon.addPixmap(pix)
    return icon
