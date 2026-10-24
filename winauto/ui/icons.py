"""Line icons drawn from small SVG paths (24×24, Lucide-style), coloured to match the theme.

Special names:
- "file:<path>"  the file's own icon (real app icons in the launcher)
- "swatch:#hex"  a colour sample
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QFileInfo, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QFileIconProvider

PATHS: dict[str, str] = {
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4.2-4.2"/>',
    "sparkles": '<path d="M12 3l1.8 4.9L18.7 9.7l-4.9 1.8L12 16.4l-1.8-4.9L5.3 9.7l4.9-1.8z"/><path d="M19 15v4M17 17h4M5 3v3M3.5 4.5h3"/>',
    "app": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18"/>',
    "calculator": '<rect x="5" y="2.5" width="14" height="19" rx="2"/><path d="M8.5 6.5h7"/><path d="M8.5 11h.01M12 11h.01M15.5 11h.01M8.5 14.5h.01M12 14.5h.01M15.5 14.5h.01M8.5 18h.01M12 18h.01M15.5 18h.01"/>',
    "settings": '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3"/><path d="M1.5 14h5M9.5 8h5M17.5 16h5"/>',
    "note": '<path d="M14 2.5H6.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V8z"/><path d="M14 2.5V8h5.5"/><path d="M8.5 13h7M8.5 17h5"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "bell": '<path d="M6 8.5a6 6 0 0 1 12 0c0 6.5 2.5 8.5 2.5 8.5h-17S6 15 6 8.5"/><path d="M10.3 20.5a2 2 0 0 0 3.4 0"/>',
    "mail": '<rect x="2.5" y="4.5" width="19" height="15" rx="2"/><path d="m21.5 7-9.5 6-9.5-6"/>',
    "message": '<path d="M20.5 14.5a2 2 0 0 1-2 2H8l-4.5 4V5.5a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2z"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5v-1a5.5 5.5 0 0 1 5.5-5.5h4a5.5 5.5 0 0 1 5.5 5.5v1"/>',
    "folder": '<path d="M3.5 19.5h17a1.5 1.5 0 0 0 1.5-1.5V8.5A1.5 1.5 0 0 0 20.5 7h-8.2l-2-2.5H3.5A1.5 1.5 0 0 0 2 6v12a1.5 1.5 0 0 0 1.5 1.5z"/>',
    "clipboard": '<rect x="8" y="2.5" width="8" height="4" rx="1"/><path d="M16 4.5h2a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2h2"/>',
    "music": '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    "layout": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M12 3v18"/>',
    "window": '<rect x="2.5" y="4" width="19" height="16" rx="2"/><path d="M2.5 8.5h19"/><path d="M6 6.3h.01M8.5 6.3h.01"/>',
    "zap": '<path d="M13 2.5 4 13.5h7.5L10.5 21.5l9.5-11h-7.5z"/>',
    "link": '<path d="M10 13.5a4.5 4.5 0 0 0 6.8.5l3-3a4.5 4.5 0 0 0-6.4-6.4l-1.6 1.6"/><path d="M14 10.5a4.5 4.5 0 0 0-6.8-.5l-3 3a4.5 4.5 0 0 0 6.4 6.4l1.6-1.6"/>',
    "text": '<path d="M4.5 7V4.5h15V7"/><path d="M12 4.5v15"/><path d="M9 19.5h6"/>',
    "tool": '<path d="M14.5 6.5a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.6-3.6a6 6 0 0 1-7.9 7.9l-6.6 6.6a2.1 2.1 0 0 1-3-3l6.6-6.6a6 6 0 0 1 7.9-7.9z"/>',
    "brain": '<path d="M9 18h6M10 21.5h4"/><path d="M15 14.5c.2-1 .7-1.8 1.4-2.5A5.5 5.5 0 1 0 7.6 12c.7.7 1.2 1.5 1.4 2.5"/>',
    "book": '<path d="M4.5 19.5v-15A2.5 2.5 0 0 1 7 2h12.5v20H7a2.5 2.5 0 0 1 0-5h12.5"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/>',
    "calendar": '<rect x="3" y="4.5" width="18" height="17" rx="2"/><path d="M16 2.5v4M8 2.5v4M3 10h18"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "mic": '<rect x="9" y="2.5" width="6" height="12" rx="3"/><path d="M18.5 10.5v1a6.5 6.5 0 0 1-13 0v-1"/><path d="M12 18v3.5"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20.5 14.5A8.5 8.5 0 1 1 9.5 3.5a6.5 6.5 0 0 0 11 11z"/>',
    "lock": '<rect x="4" y="11" width="16" height="10.5" rx="2"/><path d="M7.5 11V7.5a4.5 4.5 0 0 1 9 0V11"/>',
    "power": '<path d="M12 2.5v9.5"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/>',
    "refresh": '<path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1L20.5 8.5"/><path d="M20.5 3.5v5h-5"/>',
    "log-out": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    "trash": '<path d="M3.5 6h17"/><path d="M18.5 6v13.5a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2V6"/><path d="M8.5 6V4.5a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2V6"/>',
    "volume": '<path d="M11 5 6 9H2.5v6H6l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.8 5.2a9.5 9.5 0 0 1 0 13.6"/>',
    "volume-x": '<path d="M11 5 6 9H2.5v6H6l5 4z"/><path d="m22 9-6 6M16 9l6 6"/>',
    "battery": '<rect x="2" y="7" width="16.5" height="10" rx="2"/><path d="M22 11v2"/><path d="M5.5 10.5v3M9 10.5v3"/>',
    "activity": '<path d="M22 12h-4l-3 8.5L9 3.5 6 12H2"/>',
    "wifi": '<path d="M5 12.5a10.5 10.5 0 0 1 14 0"/><path d="M1.8 9a15 15 0 0 1 20.4 0"/><path d="M8.5 16a5.5 5.5 0 0 1 7 0"/><path d="M12 19.8h.01"/>',
    "bluetooth": '<path d="m7 7 10 10-5 5V2l5 5L7 17"/>',
    "terminal": '<path d="m4.5 17 6-5-6-5"/><path d="M12.5 19h7"/>',
    "smile": '<circle cx="12" cy="12" r="9"/><path d="M8 14.5s1.5 2 4 2 4-2 4-2"/><path d="M9 9.5h.01M15 9.5h.01"/>',
    "key": '<circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.7 12.3 9.8-9.8M17 6l3 3M14.5 8.5l2 2"/>',
    "dot": '<circle cx="12" cy="12" r="3"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "arrow-up": '<path d="M12 19V5"/><path d="m5.5 11.5 6.5-6.5 6.5 6.5"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2.5"/>',
    "copy": '<rect x="8.5" y="8.5" width="13" height="13" rx="2"/><path d="M15.5 8.5v-3a2 2 0 0 0-2-2h-8a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h3"/>',
    "replace": '<path d="M4 7h11.5"/><path d="m12 3.5 3.5 3.5-3.5 3.5"/><path d="M20 17H8.5"/><path d="m12 20.5-3.5-3.5 3.5-3.5"/>',
    "history": '<path d="M3 12a9 9 0 1 0 2.6-6.4L3 8"/><path d="M3 3v5h5"/><path d="M12 7.5V12l3 2"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "enter": '<path d="m9 10-5 5 5 5"/><path d="M20 4v7a4 4 0 0 1-4 4H4"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "briefcase": '<rect x="2.5" y="7" width="19" height="13.5" rx="2"/><path d="M16 20.5V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v15.5"/>',
    "minimize": '<path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/>',
    "maximize": '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
    "list": '<path d="M8.5 6h12.5M8.5 12h12.5M8.5 18h12.5M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
    "languages": '<path d="m5 8 6 6M4 14l6-6 2-3M2 5h12M7 2h1M22 22l-5-10-5 10M14 18h6"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
    "reply": '<path d="m9 17-5-5 5-5"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/>',
    "cloud": '<path d="M17.5 19.5H8.5a6.5 6.5 0 1 1 6.2-8.5h2.8a4.25 4.25 0 0 1 0 8.5z"/>',
    "home": '<path d="m3 9.5 9-7 9 7V20a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 20z"/><path d="M9 21.5v-9h6v9"/>',
    "camera": '<path d="M14.5 4h-5L7.5 6.5H4.5a2 2 0 0 0-2 2V18a2 2 0 0 0 2 2h15a2 2 0 0 0 2-2V8.5a2 2 0 0 0-2-2h-3z"/><circle cx="12" cy="13" r="3.5"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4.5M12 8h.01"/>',
    "puzzle": '<path d="M19.4 14.4a2.4 2.4 0 1 0 0-4.8H18V6a1.5 1.5 0 0 0-1.5-1.5h-3.6V3.1a2.4 2.4 0 1 0-4.8 0v1.4H4.5A1.5 1.5 0 0 0 3 6v3.6h1.4a2.4 2.4 0 1 1 0 4.8H3V18a1.5 1.5 0 0 0 1.5 1.5h3.6v-1.4a2.4 2.4 0 1 1 4.8 0v1.4h3.6A1.5 1.5 0 0 0 18 18v-3.6z"/>',
    "keyboard": '<rect x="2" y="5.5" width="20" height="13" rx="2"/><path d="M6 9.5h.01M10 9.5h.01M14 9.5h.01M18 9.5h.01M7 14.5h10"/>',
    "check-circle": '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.8 2.8L16.5 9.5"/>',
    "alert": '<path d="M10.3 3.9 2.4 17.5a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9.5v4M12 17h.01"/>',
}


def _svg(name: str, color: str, stroke: float = 1.8) -> bytes:
    body = PATHS.get(name, PATHS["dot"])
    fill = color if name == "dot" else "none"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{fill}" stroke="{color}" '
        f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    ).encode("utf-8")


def _ratio() -> float:
    app = QApplication.instance()
    try:
        return max(1.0, app.devicePixelRatio()) if app else 1.0  # type: ignore[union-attr]
    except AttributeError:
        return 1.0


@lru_cache(maxsize=512)
def pixmap(name: str, color: str = "#888888", size: int = 18, stroke: float = 1.8) -> QPixmap:
    ratio = _ratio()
    px = QPixmap(int(size * ratio), int(size * ratio))
    px.fill(Qt.GlobalColor.transparent)
    if name.startswith("swatch:"):
        painter = QPainter(px)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(name.split(":", 1)[1]))
        painter.setPen(QColor(0, 0, 0, 40))
        r = px.rect().adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(r, r.width() * 0.25, r.height() * 0.25)
        painter.end()
    elif name.startswith("file:"):
        path = name.split(":", 1)[1]
        info = QFileInfo(path)
        if info.isSymLink() or path.lower().endswith(".lnk"):
            target = info.symLinkTarget()
            if target:
                info = QFileInfo(target)
        icon = QFileIconProvider().icon(info)
        if icon.isNull():
            return pixmap("app", color, size, stroke)
        px = icon.pixmap(QSize(int(size * ratio), int(size * ratio)))
    else:
        renderer = QSvgRenderer(QByteArray(_svg(name, color, stroke)))
        painter = QPainter(px)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, px.width(), px.height()))
        painter.end()
    px.setDevicePixelRatio(ratio)
    return px


def icon(name: str, color: str = "#888888", size: int = 18) -> QIcon:
    return QIcon(pixmap(name, color, size))
