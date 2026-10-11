"""
"Версии" page - official Minecraft releases list (UI mockup 2).

Layout: a filter/search toolbar, a scrollable list of releases on the left and
a detail card for the currently selected version on the right.
"""
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QScrollArea, QSizePolicy, QMenu
)

from ui.ui_helpers import make_icon
from core import (
    get_official_releases, get_install_stats, get_required_java_version,
    is_version_installed, get_installed_stats,
)
from utils.config import Config


ACCENT = "#89b4fa"
TEXT = "#cdd6f4"
MUTED = "#a6adc8"
GREEN = "#a6e3a1"

# Chips shown in the toolbar, in mockup order.
FILTERS = ["Все", "Release", "Snapshot", "Beta", "Alpha"]

# Width of the detail column on the right.
DETAIL_WIDTH = 320


class StatsThread(QThread):
    """Computes the install stats (file count / size) of a single version."""

    ready = pyqtSignal(str, int, int)  # version, files, size_bytes

    def __init__(self, version: str, parent=None):
        super().__init__(parent)
        self.version = version

    def run(self):
        try:
            stats = get_install_stats(self.version)
            self.ready.emit(
                self.version,
                int(stats.get("files", 0)),
                int(stats.get("size", 0)),
            )
        except Exception:
            self.ready.emit(self.version, 0, 0)


class FilterChip(QPushButton):
    """Small toggleable pill used as a category filter."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("filterChip")
        self.setCheckable(True)
        self.setFixedHeight(34)
        self.setMinimumWidth(54)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class VersionRow(QFrame):
    """One line of the version list."""

    clicked = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self, version: str, mc_version: str, java: int,
                 installed: bool, parent=None):
        super().__init__(parent)
        self.version = version
        self.installed = installed
        self.setObjectName("versionRow")
        self.setFixedHeight(56)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_menu)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(16)

        self.name_label = QLabel(version)
        self.name_label.setObjectName("versionRowName")
        self.name_label.setMinimumWidth(96)
        layout.addWidget(self.name_label)

        self.type_label = QLabel("Release")
        self.type_label.setObjectName("versionRowType")
        self.type_label.setMinimumWidth(88)
        layout.addWidget(self.type_label)

        self.java_label = QLabel(f"Java {java}")
        self.java_label.setObjectName("versionRowJava")
        self.java_label.setMinimumWidth(88)
        layout.addWidget(self.java_label)

        self.status_label = QLabel("Установлена" if installed else "Не скачана")
        self.status_label.setObjectName("versionRowInstalled" if installed
                                        else "versionRowMissing")
        layout.addWidget(self.status_label, 1)

    def mousePressEvent(self, event):
        self.clicked.emit(self.version)
        super().mousePressEvent(event)

    def _open_menu(self, pos):
        menu = QMenu(self)
        play = menu.addAction("Играть")
        delete = menu.addAction("Удалить версию")
        delete.setEnabled(self.installed)

        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is play:
            self.clicked.emit(self.version)
        elif chosen is delete:
            self.delete_requested.emit(self.version)


class DetailRow(QWidget):
    """"Label ......... value" line inside the detail card."""

    def __init__(self, label: str, value: str = "—", parent=None):
        super().__init__(parent)
        self.setObjectName("detailRow")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("detailValue")
        self.value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        name = QLabel(label)
        name.setObjectName("detailLabel")
        name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(name, 1)
        layout.addWidget(self.value_label)

    def set_value(self, text: str):
        self.value_label.setText(text)


class VersionsPage(QWidget):
    """Official releases list with search, category filters and a detail card."""

    play_requested = pyqtSignal(str)
    load_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    refresh_requested = pyqtSignal()
    launch_options_requested = pyqtSignal()
    open_folder_requested = pyqtSignal(str)

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setObjectName("versionsPage")

        self._versions = []
        self._filter = "Release"
        self._search = ""
        self._selected: Optional[str] = None
        self._stats_thread: Optional[StatsThread] = None
        self._pending_stats: Optional[str] = None
        self._rows = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addLayout(self._build_toolbar())

        body = QHBoxLayout()
        body.setSpacing(22)
        body.addWidget(self._build_list(), 1)
        body.addWidget(self._build_detail(), 0)
        root.addLayout(body, 1)

    # ---------- construction ----------

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.chips = []
        for name in FILTERS:
            chip = FilterChip(name)
            chip.setChecked(name == self._filter)
            chip.clicked.connect(lambda _=False, key=name: self._set_filter(key))
            row.addWidget(chip)
            self.chips.append(chip)

        row.addSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("versionsSearch")
        self.search_input.setPlaceholderText("Поиск версии")
        self.search_input.setFixedHeight(34)
        # Shrinkable so the toolbar never pushes the buttons off-screen.
        self.search_input.setMinimumWidth(110)
        self.search_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.search_input.textChanged.connect(self._set_search)
        row.addWidget(self.search_input, 1)

        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.setFixedHeight(34)
        # Never squeezed: the label must stay readable, so the search field
        # gives up space first.
        self.refresh_button.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        row.addWidget(self.refresh_button, 0)

        return row

    def _build_list(self) -> QFrame:
        card = QFrame()
        card.setObjectName("versionsListCard")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("versionHeaderRow")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 0, 18, 0)
        header_layout.setSpacing(16)
        for text, width in (("ВЕРСИЯ", 96), ("ТИП", 88), ("JAVA", 88)):
            label = QLabel(text)
            label.setObjectName("versionHeaderCell")
            label.setFixedWidth(width)
            header_layout.addWidget(label)
        status = QLabel("СТАТУС")
        status.setObjectName("versionHeaderCell")
        header_layout.addWidget(status, 1)
        layout.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("versionsScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.list_content = QWidget()
        self.list_content.setObjectName("versionsListContent")
        self.list_layout = QVBoxLayout(self.list_content)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        self.list_layout.addStretch()

        self.scroll.setWidget(self.list_content)
        layout.addWidget(self.scroll, 1)

        self.list_empty = QLabel("Ничего не найдено")
        self.list_empty.setObjectName("listEmpty")
        self.list_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list_empty.setVisible(False)
        layout.addWidget(self.list_empty)

        return card

    def _build_detail(self) -> QFrame:
        card = QFrame()
        card.setObjectName("versionDetailCard")
        card.setFixedWidth(DETAIL_WIDTH)
        # Minimum vertically: the card must never be squeezed below its
        # content, otherwise the buttons start to overlap.
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(14)

        icon = QLabel()
        icon.setObjectName("detailIcon")
        icon.setFixedSize(56, 56)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(make_icon("cube", ACCENT, 30).pixmap(30, 30))
        header.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        titles = QVBoxLayout()
        titles.setSpacing(4)
        self.detail_title = QLabel("—")
        self.detail_title.setObjectName("detailTitle")
        self.detail_subtitle = QLabel("Выберите версию")
        self.detail_subtitle.setObjectName("detailSubtitle")
        titles.addWidget(self.detail_title)
        titles.addWidget(self.detail_subtitle)
        header.addLayout(titles, 1)

        layout.addLayout(header)

        self.detail_description = QLabel("")
        self.detail_description.setObjectName("detailDescription")
        self.detail_description.setWordWrap(True)
        layout.addWidget(self.detail_description)

        separator = QFrame()
        separator.setObjectName("detailSeparator")
        separator.setFixedHeight(1)
        layout.addWidget(separator)

        self.row_java = DetailRow("Java")
        self.row_files = DetailRow("Файлов")
        self.row_size = DetailRow("Размер")
        for row in (self.row_java, self.row_files, self.row_size):
            layout.addWidget(row)

        layout.addSpacing(4)

        profile_label = QLabel("Имя профиля")
        profile_label.setObjectName("fieldLabel")
        layout.addWidget(profile_label)

        self.profile_input = QLineEdit()
        self.profile_input.setObjectName("profileNameInput")
        self.profile_input.setMinimumHeight(42)
        layout.addWidget(self.profile_input)

        layout.addSpacing(6)

        self.play_button = QPushButton("Скачать и играть")
        self.play_button.setObjectName("primaryButton")
        self.play_button.setMinimumHeight(50)
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_button.clicked.connect(self._on_play_clicked)
        layout.addWidget(self.play_button)

        # Secondary actions are grouped so the primary button reads as separate.
        # The group is vertically Fixed, otherwise the card squeezes it and the
        # buttons overlap each other.
        layout.addSpacing(14)

        secondary = QWidget()
        secondary.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        secondary_layout = QVBoxLayout(secondary)
        secondary_layout.setContentsMargins(0, 0, 0, 0)
        secondary_layout.setSpacing(10)

        self.options_button = QPushButton("Параметры запуска")
        self.options_button.setObjectName("secondaryButton")
        self.options_button.setMinimumHeight(46)
        self.options_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.options_button.clicked.connect(self.launch_options_requested.emit)
        secondary_layout.addWidget(self.options_button)

        self.folder_button = QPushButton("Открыть папку")
        self.folder_button.setObjectName("secondaryButton")
        self.folder_button.setMinimumHeight(46)
        self.folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_button.setToolTip("Миры и настройки этой версии")
        self.folder_button.clicked.connect(self._on_folder_clicked)
        self.folder_button.setEnabled(False)
        secondary_layout.addWidget(self.folder_button)

        self.delete_button = QPushButton("Удалить версию")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.setMinimumHeight(46)
        self.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_button.clicked.connect(self._on_delete_clicked)
        self.delete_button.setVisible(False)
        secondary_layout.addWidget(self.delete_button)

        layout.addWidget(secondary)

        layout.addStretch()
        self._set_detail_enabled(False)

        # On short windows the card would otherwise be cut off, so its content
        # lives in a scroll area.
        scroll = QScrollArea()
        scroll.setObjectName("detailScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Without this the parent layout squeezes the column and the card gets
        # cut off, because its 320 px no longer fit into the viewport.
        scroll.setMinimumWidth(DETAIL_WIDTH + 12)
        scroll.setWidget(card)
        return scroll

    # ---------- data ----------

    def set_versions(self, versions):
        """Fill the page with the official release list."""
        self._versions = list(versions)

        if self._selected and self._selected not in {v.id for v in self._versions}:
            self._selected = None

        if not self._selected and self._versions:
            self._selected = self._versions[0].id

        self._render_rows()
        if self._selected:
            self._select(self._selected)

    def _visible_versions(self):
        result = []
        for version in self._versions:
            if self._filter not in ("Все", "Release"):
                # Snapshots / beta / alpha are not published by the loader yet.
                continue
            if self._search and self._search.lower() not in version.id.lower():
                continue
            result.append(version)
        return result

    def _render_rows(self):
        while self.list_layout.count() > 1:  # keep the trailing stretch
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        self._rows = {}
        visible = self._visible_versions()

        for version in visible:
            row = VersionRow(
                version=version.id,
                mc_version=version.id,
                java=get_required_java_version(version.id),
                installed=self._is_installed(version.id),
            )
            row.clicked.connect(self._select)
            row.delete_requested.connect(self.delete_requested.emit)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
            self._rows[version.id] = row

        has_rows = bool(visible)
        self.scroll.setVisible(has_rows)
        self.list_empty.setVisible(not has_rows)
        if not has_rows:
            self.list_empty.setText(
                "Поддерживаются только релизные версии"
                if self._filter not in ("Все", "Release")
                else "Ничего не найдено"
            )

    def _is_installed(self, version_id: str) -> bool:
        return is_version_installed(self.config.install_path, version_id)

    # ---------- selection ----------

    def _set_filter(self, name: str):
        self._filter = name
        for chip in self.chips:
            chip.setChecked(chip.text() == name)
        self._render_rows()

    def _set_search(self, text: str):
        self._search = text.strip()
        self._render_rows()

    def _select(self, version: str, fetch_stats: bool = True):
        self._selected = version
        self._highlight_rows()

        java = get_required_java_version(version)
        installed = self._is_installed(version)

        self.detail_title.setText(f"Minecraft {version}")
        self.detail_subtitle.setText("Release · Vanilla")
        self.detail_description.setText(
            f"Официальная версия Minecraft {version} без модификаций. "
            f"Требуется Java {java}."
        )

        self.row_java.set_value(f"{java} найдена")
        self.row_files.set_value("…")
        self.row_size.set_value("…")
        self.delete_button.setVisible(installed)

        # Every version gets its own profile name.
        self.profile_input.setText(f"Minecraft {version}")

        self._set_detail_enabled(True)
        self.play_button.setText("Играть" if installed else "Скачать и играть")
        # The instance folder only exists once the version is installed.
        self.folder_button.setEnabled(installed)

        if installed:
            disk = get_installed_stats(self.config.install_path, version)
            self.row_files.set_value(f"{disk['files']:,}".replace(",", " "))
            self.row_size.set_value(f"{disk['size'] / (1024 * 1024):.1f} МБ")
            self.detail_subtitle.setText("Release · Vanilla · Установлена")
        else:
            self.detail_subtitle.setText("Release · Vanilla")

        if fetch_stats and not installed:
            self._request_stats(version)

    def _highlight_rows(self):
        for version, row in self._rows.items():
            selected = version == self._selected
            row.setObjectName("versionRowSelected" if selected else "versionRow")
            # Re-apply the stylesheet so the new object name takes effect.
            row.style().unpolish(row)
            row.style().polish(row)

    def _set_detail_enabled(self, enabled: bool):
        self.play_button.setEnabled(enabled)
        self.options_button.setEnabled(enabled)
        self.profile_input.setEnabled(enabled)

    # ---------- stats ----------

    def _request_stats(self, version: str):
        """Fetch the stats of one version at a time (one thread, queued)."""
        if self._stats_thread is not None and self._stats_thread.isRunning():
            self._pending_stats = version
            return

        self._stats_thread = StatsThread(version, self)
        self._stats_thread.ready.connect(self._on_stats_ready)
        self._stats_thread.start()

    def _on_stats_ready(self, version: str, files: int, size_bytes: int):
        if version == self._selected:
            self.row_files.set_value(f"{files:,}".replace(",", " "))
            self.row_size.set_value(f"{size_bytes / (1024 * 1024):.1f} МБ")

        # A newer selection arrived while this request was running.
        pending = self._pending_stats
        self._pending_stats = None
        if pending and pending != version:
            self._request_stats(pending)

    # ---------- actions ----------

    def _on_play_clicked(self):
        if not self._selected:
            return
        if self._is_installed(self._selected):
            self.play_requested.emit(self._selected)
        else:
            self.load_requested.emit(self._selected)

    def _on_delete_clicked(self):
        if self._selected and self._is_installed(self._selected):
            self.delete_requested.emit(self._selected)

    def _on_folder_clicked(self):
        if self._selected and self._is_installed(self._selected):
            self.open_folder_requested.emit(self._selected)

    def profile_name(self) -> str:
        return self.profile_input.text().strip()

    def refresh_installed_states(self):
        """Called after an install/delete finished so states stay correct."""
        self._render_rows()
        if self._selected:
            self._select(self._selected, fetch_stats=False)

    def shutdown(self):
        """
        Stop the background stats thread.

        A QThread that is still running when its parent widget is destroyed
        makes Qt abort the process, so it has to be joined first.
        """
        thread = self._stats_thread
        self._stats_thread = None
        self._pending_stats = None

        if thread is not None and thread.isRunning():
            thread.terminate()
            thread.wait(2000)