"""
UI helpers: tinted SVG icons and the isometric cube illustration.
"""
from pathlib import Path

from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QPolygonF, QFont
from PyQt6.QtWidgets import QLabel

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
ICONS_DIR = ASSETS_DIR / "icons"


def make_icon(name: str, color: str = "#cdd6f4", size: int = 24) -> QIcon:
    """
    Load an SVG from assets/icons and re-colour it to the given colour.

    The shipped SVGs use #000000 as a placeholder stroke so it can be
    substituted here for any theme colour.
    """
    path = ICONS_DIR / f"{name}.svg"
    if not path.exists():
        return QIcon()

    svg = path.read_text(encoding="utf-8").replace("#000000", color)
    pixmap = QPixmap()
    pixmap.loadFromData(svg.encode("utf-8"), "SVG")
    if pixmap.isNull():
        return QIcon()

    scaled = pixmap.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation
    )
    return QIcon(scaled)


def make_logo(size: int = 40) -> QIcon:
    """Load the application logo."""
    path = ASSETS_DIR / "logo.svg"
    if not path.exists():
        return QIcon()
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return QIcon()
    return QIcon(pixmap.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation
    ))


def apply_letter_spacing(label: QLabel, spacing: float = 1.0) -> None:
    """
    Qt style sheets do not support `letter-spacing`, so spaced-out caps
    ("ПОСЛЕДНИЙ ЗАПУСК", "МЕНЮ") are set through QFont instead.
    """
    font = label.font()
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    label.setFont(font)


class CubeWidget(QWidget):
    """
    Draws the large isometric cube used as the hero illustration.

    The cube is a regular hexagon silhouette split into three faces
    (top, left, right) meeting in one centre point. It scales with the
    widget, so no image asset is needed.
    """

    TOP_COLOR = "#89b4fa"
    LEFT_COLOR = "#6a8fd6"
    RIGHT_COLOR = "#4a68a6"
    EDGE_COLOR = (13, 13, 18, 80)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(150, 150)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        cx = self.width() / 2
        cy = self.height() / 2
        # The cube spans 144 x 164 units, 190 leaves a small margin.
        k = min(self.width(), self.height()) / 190.0

        def pt(dx: float, dy: float) -> QPointF:
            return QPointF(cx + dx * k, cy + dy * k)

        top = pt(0, -82)
        upper_right = pt(72, -42)
        lower_right = pt(72, 42)
        bottom = pt(0, 82)
        lower_left = pt(-72, 42)
        upper_left = pt(-72, -42)
        center = pt(0, 0)

        painter.setBrush(QColor(self.LEFT_COLOR))
        painter.drawPolygon(QPolygonF([upper_left, center, bottom, lower_left]))

        painter.setBrush(QColor(self.RIGHT_COLOR))
        painter.drawPolygon(QPolygonF([center, upper_right, lower_right, bottom]))

        painter.setBrush(QColor(self.TOP_COLOR))
        painter.drawPolygon(QPolygonF([top, upper_right, center, upper_left]))

        # Inner edges between the faces
        r, g, b, a = self.EDGE_COLOR
        edge = QPen(QColor(r, g, b, a), 1.5 * max(k, 0.8))
        edge.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(edge)
        painter.drawLine(center, upper_left)
        painter.drawLine(center, upper_right)
        painter.drawLine(center, bottom)

        painter.end()
