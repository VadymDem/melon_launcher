"""
Left navigation sidebar.
"""
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
)

from ui.ui_helpers import make_icon, make_logo, apply_letter_spacing


NAV_ITEMS = [
    ("home", "Главная"),
    ("versions", "Версии"),
    ("builds", "Сборки"),
    ("worlds", "Миры"),
    ("servers", "Серверы"),
    ("console", "Консоль"),
]

ICON_SIZE = 20
ICON_IDLE = "#a6adc8"
ICON_ACTIVE = "#89b4fa"   # accent colour, like in the mockup


class NavButton(QPushButton):
    """A single sidebar navigation entry."""

    def __init__(self, icon_name: str, text: str, checkable: bool = True, parent=None):
        # Two leading spaces widen the gap between the icon and the text,
        # which Qt style sheets cannot control for QPushButton.
        super().__init__(f"  {text}", parent)
        self.icon_name = icon_name
        self.setObjectName("navButton")
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setIcon(make_icon(icon_name, ICON_IDLE, ICON_SIZE))
        self.setFixedHeight(42)

    def set_active(self, active: bool):
        self.setChecked(active)
        color = ICON_ACTIVE if active else ICON_IDLE
        self.setIcon(make_icon(self.icon_name, color, ICON_SIZE))


class Sidebar(QWidget):
    """Application sidebar with logo, navigation and account card."""

    page_requested = pyqtSignal(str)
    settings_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(232)
        # A QWidget subclass does not paint its own stylesheet background
        # (and border-right) unless this attribute is set.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._buttons: dict[str, NavButton] = {}
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 22, 14, 18)
        layout.setSpacing(6)

        # Logo block
        logo_row = QHBoxLayout()
        logo_row.setContentsMargins(8, 0, 8, 0)
        logo_row.setSpacing(12)

        logo = QLabel()
        logo.setPixmap(make_logo(36).pixmap(36, 36))
        logo.setObjectName("logoBox")
        logo.setFixedSize(36, 36)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_row.addWidget(logo)

        logo_text = QVBoxLayout()
        logo_text.setSpacing(1)
        title = QLabel("Melon Launcher")
        title.setObjectName("sidebarTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        version = QLabel("v0.1.0-dev")
        version.setObjectName("sidebarVersion")
        version.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        logo_text.addWidget(title)
        logo_text.addWidget(version)
        logo_row.addLayout(logo_text)
        logo_row.addStretch()

        layout.addLayout(logo_row)
        layout.addSpacing(22)

        # Menu label
        menu_label = QLabel("МЕНЮ")
        menu_label.setObjectName("sidebarSection")
        menu_label.setContentsMargins(12, 0, 0, 0)
        apply_letter_spacing(menu_label, 1.0)
        layout.addWidget(menu_label)

        # Navigation
        for icon_name, text in NAV_ITEMS:
            button = NavButton(icon_name, text)
            button.clicked.connect(lambda _=False, key=icon_name: self._select(key))
            layout.addWidget(button)
            self._buttons[icon_name] = button

        layout.addStretch()

        # Settings opens a dialog, so it must not stay "checked" afterwards.
        settings_btn = NavButton("settings", "Настройки", checkable=False)
        settings_btn.clicked.connect(self.settings_requested.emit)
        layout.addWidget(settings_btn)

        layout.addSpacing(8)

        # Account card (QFrame so that border / radius from the QSS are painted)
        self.account_card = QFrame()
        self.account_card.setObjectName("accountCard")
        self._build_account_card()
        layout.addWidget(self.account_card)

        self.set_active("home")

    def _build_account_card(self):
        card_layout = QVBoxLayout(self.account_card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(12)

        self.avatar = QLabel("ME")
        self.avatar.setObjectName("accountAvatar")
        self.avatar.setFixedSize(40, 40)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.avatar)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.account_name = QLabel("MelonBiba")
        self.account_name.setObjectName("accountName")
        self.account_name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.account_status = QLabel("Офлайн режим")
        self.account_status.setObjectName("accountStatus")
        self.account_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        text_col.addStretch()
        text_col.addWidget(self.account_name)
        text_col.addWidget(self.account_status)
        text_col.addStretch()
        row.addLayout(text_col, 1)

        card_layout.addLayout(row)

        self.login_button = QPushButton("Войти (Microsoft)")
        self.login_button.setObjectName("accountButton")
        self.login_button.setFixedHeight(36)
        self.login_button.setCursor(Qt.CursorShape.PointingHandCursor)
        card_layout.addWidget(self.login_button)

    def _select(self, key: str):
        self.set_active(key)
        self.page_requested.emit(key)

    def set_active(self, key: str):
        for name, button in self._buttons.items():
            button.set_active(name == key)

    def set_account(self, username: str, status: str, initials: str):
        self.account_name.setText(username)
        self.account_status.setText(status)
        self.avatar.setText(initials)

    def set_login_text(self, text: str):
        self.login_button.setText(text)
