"""Small helpers shared by the popup's views (labels, clean-up, dividers)."""

from __future__ import annotations

from PySide6.QtCore import (
    Qt,
)
from PySide6.QtGui import (
    QTextDocument,
)
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QWidget,
)

# Popup size, and the margin its painted shadow needs.
WIDTH = 780
HEIGHT = 560
SHADOW = 18


def hard_breaks(text: str) -> str:
    """Keep single line breaks from the model (Markdown would merge the lines)."""
    out, in_code = [], False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
        out.append(line if in_code or not line.strip() else line + "  ")
    return "\n".join(out)


def fit_label(label: QLabel, max_width: int) -> None:
    """Word-wrapped labels otherwise wrap far too early; size them to their text."""
    label.ensurePolished()
    doc = QTextDocument()
    doc.setDefaultFont(label.font())
    if label.textFormat() == Qt.TextFormat.MarkdownText:
        doc.setMarkdown(label.text())
    else:
        doc.setPlainText(label.text())
    label.setMinimumWidth(min(int(doc.idealWidth()) + 32, max_width))


def make_label(text: str, markdown: bool = False, object_name: str = "") -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.MarkdownText if markdown else Qt.TextFormat.PlainText)
    label.setText(text)
    label.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
    )
    label.setOpenExternalLinks(True)
    if object_name:
        label.setObjectName(object_name)
    return label


def dispose(widget: QWidget | None) -> None:
    """Hide now, delete later: otherwise the old widget is still drawn until Qt gets to it."""
    if widget is not None:
        widget.hide()
        widget.deleteLater()


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            dispose(item.widget())


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.Shape.NoFrame)
    return line
