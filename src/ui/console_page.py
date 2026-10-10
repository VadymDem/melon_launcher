"""
Console page: hosts the game log output in a dedicated tab.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox
)


class ConsolePage(QWidget):
    """Full-height view of the launcher/game log."""

    clear_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("consolePage")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)

        self.auto_scroll = QCheckBox("Автопрокрутка")
        self.auto_scroll.setChecked(True)
        header.addWidget(self.auto_scroll)
        header.addStretch()

        self.clear_button = QPushButton("Очистить")
        self.clear_button.setObjectName("consoleClearButton")
        self.clear_button.setFixedHeight(34)
        self.clear_button.setMinimumWidth(104)
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.clicked.connect(self.clear_requested.emit)
        header.addWidget(self.clear_button)

        root.addLayout(header)

        self.placeholder = QLabel("Запустите игру — здесь появится вывод")
        self.placeholder.setObjectName("recentEmpty")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setVisible(False)

        self.console_widget: QWidget | None = None
        root.addWidget(self.placeholder)

    def set_console_widget(self, widget: QWidget):
        """Insert the real log console below the header."""
        self.console_widget = widget
        layout = self.layout()
        layout.insertWidget(layout.count() - 1, widget, 1)

    def set_empty(self, empty: bool):
        """Show either the placeholder (empty) or the log console."""
        self.placeholder.setVisible(empty)
        if self.console_widget is not None:
            self.console_widget.setVisible(not empty)