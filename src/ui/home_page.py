"""
Home page ("Главная") as shown in the first UI mockup.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFrame, QSizePolicy
)

from ui.ui_helpers import make_icon, CubeWidget, apply_letter_spacing

# Sizes taken from the mockup (1200x760 window)
HERO_MIN_HEIGHT = 292
QUICK_CARD_WIDTH = 292
CUBE_SIZE = 200


class Tag(QLabel):
    """Small pill used for Vanilla / Java 21 / Offline."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("tagPill")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(26)


class RecentCard(QFrame):
    """Card in the "Недавно" row."""

    def __init__(self, icon_name: str, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setObjectName("recentCard")
        self.setMinimumHeight(76)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        icon_box = QLabel()
        icon_box.setObjectName("recentIcon")
        icon_box.setFixedSize(44, 44)
        icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_box.setPixmap(make_icon(icon_name, "#89b4fa", 22).pixmap(22, 22))
        layout.addWidget(icon_box)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        text_col.addStretch()
        title_label = QLabel(title)
        title_label.setObjectName("recentTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("recentSubtitle")
        subtitle_label.setWordWrap(True)
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        text_col.addWidget(title_label)
        text_col.addWidget(subtitle_label)
        text_col.addStretch()
        layout.addLayout(text_col, 1)


class HomePage(QWidget):
    """Home page with hero card, quick selection and recent items."""

    play_requested = pyqtSignal()
    version_changed = pyqtSignal(str)
    browse_versions_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homePage")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(22)

        root.addLayout(self._build_top_row())

        self.recent_title, self.recent_row = self._build_recent_section()
        self.recent_empty = QLabel("Запущенных сборок и миров пока нет")
        self.recent_empty.setObjectName("recentEmpty")
        self.recent_empty.setVisible(False)
        root.addWidget(self.recent_title)
        root.addLayout(self.recent_row)
        root.addWidget(self.recent_empty)

        root.addStretch()

    # ---------- construction ----------

    def _build_top_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(22)

        row.addWidget(self._build_hero_card(), 1)
        # AlignTop: the quick card keeps its own height instead of being
        # stretched to the height of the hero card.
        row.addWidget(self._build_quick_card(), 0, Qt.AlignmentFlag.AlignTop)
        return row

    def _build_hero_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("heroCard")
        card.setMinimumHeight(HERO_MIN_HEIGHT)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(30, 30, 24, 30)
        layout.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(0)

        # Text block is pinned to the top ...
        info = QVBoxLayout()
        info.setSpacing(12)

        caption = QLabel("ПОСЛЕДНИЙ ЗАПУСК")
        caption.setObjectName("heroCaption")
        caption.setAlignment(Qt.AlignmentFlag.AlignLeft)
        apply_letter_spacing(caption, 1.2)
        info.addWidget(caption)

        self.hero_title = QLabel("Minecraft 26.3")
        self.hero_title.setObjectName("heroTitle")
        self.hero_title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        info.addWidget(self.hero_title)

        tags = QHBoxLayout()
        tags.setSpacing(8)
        self.tag_loader = Tag("Vanilla")
        self.tag_java = Tag("Java 21")
        self.tag_auth = Tag("Offline")
        for tag in (self.tag_loader, self.tag_java, self.tag_auth):
            tags.addWidget(tag)
        tags.addStretch()
        info.addLayout(tags)

        # No manual "\n" any more: the label wraps by itself.
        self.hero_description = QLabel(
            "Официальная версия без модификаций. Игра готова к запуску, "
            "нужные файлы скачаются автоматически."
        )
        self.hero_description.setObjectName("heroDescription")
        self.hero_description.setWordWrap(True)
        self.hero_description.setMaximumWidth(420)
        self.hero_description.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        info.addWidget(self.hero_description)

        left.addLayout(info)

        # ... and the buttons sit at the bottom of the card.
        left.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(12)

        self.play_button = QPushButton("Скачать и играть")
        self.play_button.setObjectName("primaryButton")
        self.play_button.setMinimumHeight(52)
        self.play_button.setMinimumWidth(180)
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_button.setIcon(make_icon("play", "#11111b", 18))
        self.play_button.clicked.connect(self.play_requested.emit)
        buttons.addWidget(self.play_button)

        # Shown instead of "play" when no pack is installed yet.
        self.browse_button = QPushButton("Выбрать версию")
        self.browse_button.setObjectName("secondaryButton")
        self.browse_button.setMinimumHeight(52)
        self.browse_button.setMinimumWidth(180)
        self.browse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_button.clicked.connect(self.browse_versions_requested.emit)
        self.browse_button.setVisible(False)
        buttons.addWidget(self.browse_button)

        buttons.addStretch()
        left.addLayout(buttons)

        layout.addLayout(left, 1)

        cube = CubeWidget()
        cube.setFixedSize(CUBE_SIZE, CUBE_SIZE)
        layout.addWidget(cube, 0, Qt.AlignmentFlag.AlignVCenter)

        return card

    def _build_field(self, label_text: str, widget: QWidget) -> QVBoxLayout:
        """Label + control with a tight 6 px gap (fields themselves are 16 px apart)."""
        col = QVBoxLayout()
        col.setSpacing(6)
        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        col.addWidget(label)
        col.addWidget(widget)
        return col

    def _build_quick_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("quickCard")
        card.setFixedWidth(QUICK_CARD_WIDTH)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(16)

        title = QLabel("Быстрый выбор")
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        self.version_combo = QComboBox()
        self.version_combo.setObjectName("fieldCombo")
        self.version_combo.setMinimumHeight(42)
        self.version_combo.currentTextChanged.connect(self.version_changed.emit)
        layout.addLayout(self._build_field("Сборка", self.version_combo))

        self.summary_label = QLabel("Тип: Vanilla · Файлов: 0 · Размер: 0.0 МБ")
        self.summary_label.setObjectName("summaryLabel")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        return card

    def _build_recent_section(self):
        """Return the "Недавно" title and an (initially empty) card row."""
        title = QLabel("Недавно")
        title.setObjectName("sectionTitle")
        title.setVisible(False)

        row = QHBoxLayout()
        row.setSpacing(14)
        return title, row

    def set_recent_items(self, items):
        """
        Fill the "Недавно" row.

        items: list of (icon_name, title, subtitle). The section stays hidden
        when there is nothing real to show, and shows a hint when empty.
        """
        # Clear previous cards
        while self.recent_row.count():
            item = self.recent_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        if not items:
            self.recent_title.setVisible(False)
            self.recent_empty.setVisible(True)
            return

        for icon_name, title, subtitle in items:
            self.recent_row.addWidget(RecentCard(icon_name, title, subtitle), 1)

        self.recent_title.setVisible(True)
        self.recent_empty.setVisible(False)

    # ---------- behaviour ----------

    # ---------- state updates ----------

    def set_versions(self, versions):
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        self.version_combo.addItems(versions)
        self.version_combo.blockSignals(False)

    def set_packs(self, packs):
        """
        Fill the quick selection with installed packs.

        When nothing is installed the combo shows a hint instead and the play
        button is disabled - official versions are installed from the
        "Версии" page, never from here.
        """
        self.version_combo.blockSignals(True)
        self.version_combo.clear()

        if packs:
            self.version_combo.addItems([p.display_name for p in packs])
            self.version_combo.setEnabled(True)
        else:
            self.version_combo.addItem("Нет установленных сборок")
            self.version_combo.setEnabled(False)

        self.version_combo.blockSignals(False)

    def set_hero(self, title: str, description: str,
                 loader: str, java: str, auth: str):
        self.hero_title.setText(title)
        self.hero_description.setText(description)
        self.tag_loader.setText(loader)
        self.tag_java.setText(java)
        self.tag_auth.setText(auth)

    def set_hero_tags_visible(self, visible: bool):
        """Hide the Vanilla/Java/Offline pills when there is nothing to show."""
        for tag in (self.tag_loader, self.tag_java, self.tag_auth):
            tag.setVisible(visible)

    def set_play_button(self, text: str):
        self.play_button.setText(text)

    def set_play_enabled(self, enabled: bool):
        """Swap "play" for "choose a version" when no pack is installed."""
        self.play_button.setVisible(enabled)
        self.browse_button.setVisible(not enabled)

    def set_summary(self, text: str):
        self.summary_label.setText(text)
