"""
Placeholder pages for the navigation entries that are not implemented yet.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ui.ui_helpers import make_icon


class PlaceholderPage(QWidget):
    """Simple empty-state page used for not-yet-implemented sections."""

    def __init__(self, title: str, icon_name: str = "cube", parent=None):
        super().__init__(parent)
        self.setObjectName("placeholderPage")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(14)

        icon = QLabel()
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(make_icon(icon_name, "#45475a", 56).pixmap(56, 56))
        layout.addWidget(icon)

        heading = QLabel(title)
        heading.setObjectName("placeholderTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        hint = QLabel("Раздел в разработке")
        hint.setObjectName("placeholderHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)