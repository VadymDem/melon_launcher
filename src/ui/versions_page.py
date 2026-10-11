"""
"Версии" page - official Minecraft releases list (UI mockup 2).

Layout: a filter/search toolbar, a scrollable list of releases on the left and
a detail card for the currently selected version on the right.
"""
from typing import List, Optional
from pathlib import Path

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

# Cards have a 1 px border; the content is inset by that much so it cannot
# paint over the rounded corners.
CARD_INSET = 1
CARD_RADIUS = 16

# Version list geometry: the list is virtualised, so the row height decides how
# many rows exist as widgets at any moment.
ROW_HEIGHT = 56
# Extra rows kept above and below the viewport so fast scrolling stays smooth.
ROW_BUFFER = 6


class StatsThread(QThread):
    """Computes the install stats (file count / size) of a single version."""

    ready = pyqtSignal(str, int, int)  # version, files, size_bytes

    def __init__(self, version: str, parent=None):
        super().__init__(parent)
        self.setObjectName(f"StatsThread-{version}")
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
        self.setMinimumWidth(48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class VersionRow(QFrame):
    """
    One line of the version list.

    Rows are pooled and reused: switching category chips must not create or
    destroy hundreds of widgets, which caused visible glitches.
    """

    clicked = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self, version: str = "", mc_version: str = "", java: int = 21,
                 installed: bool = False, category: str = "Release", parent=None):
        super().__init__(parent)
        self.version = version
        self.installed = installed
        self._selected = False
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

        # Snapshots / beta / alpha get their own muted colour.
        self.type_label = QLabel(category)
        self.type_label.setMinimumWidth(88)
        layout.addWidget(self.type_label)

        self.java_label = QLabel(f"Java {java}")
        self.java_label.setObjectName("versionRowJava")
        self.java_label.setMinimumWidth(88)
        layout.addWidget(self.java_label)

        self.status_label = QLabel("Не скачана")
        layout.addWidget(self.status_label, 1)

        self.setVersion(version, java, installed, category)

    def setVersion(self, version: str, java: int, installed: bool,
                   category: str):
        """Rebind this row to another version without recreating widgets."""
        self.version = version
        self.installed = installed

        self.name_label.setText(version)
        self.type_label.setText(category)
        self.java_label.setText(f"Java {java}")

        type_object = (
            "versionRowType" if category == "Release" else "versionRowTypeAlt"
        )
        if self.type_label.objectName() != type_object:
            self.type_label.setObjectName(type_object)
            self._repolish(self.type_label)

        status_text = "Установлена" if installed else "Не скачана"
        status_object = (
            "versionRowInstalled" if installed else "versionRowMissing"
        )
        if self.status_label.objectName() != status_object:
            self.status_label.setObjectName(status_object)
            self._repolish(self.status_label)
        if self.status_label.text() != status_text:
            self.status_label.setText(status_text)

        self.set_selected(self._selected)

    @staticmethod
    def _repolish(widget):
        """Re-evaluate the stylesheet after an object name change."""
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def set_selected(self, selected: bool):
        """Highlight or un-highlight the row."""
        if selected == self._selected and self.objectName() != "":
            return
        self._selected = selected
        self.setObjectName("versionRowSelected" if selected else "versionRow")
        self._repolish(self)

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
        self._by_id = {}
        self._pool: List[VersionRow] = []
        self._visible = []
        self._installed: set[str] = set()
        self._syncing = False
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
        # Shrinks hard so the toolbar keeps every button on screen even on
        # high-DPI setups where the window has few logical pixels.
        self.search_input.setMinimumWidth(70)
        self.search_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.search_input.textChanged.connect(self._set_search)
        row.addWidget(self.search_input, 1)

        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.setObjectName("compactButton")
        self.refresh_button.setToolTip("Обновить список версий")
        self.refresh_button.setFixedHeight(34)
        # Never squeezed: the label must stay readable, so the search field
        # gives up space first.
        self.refresh_button.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        row.addWidget(self.refresh_button, 0)
        row.addSpacing(2)

        return row

    def _build_list(self) -> QFrame:
        card = QFrame()
        card.setObjectName("versionsListCard")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(card)
        # Inset by the border width so rows never overlap the rounded frame.
        layout.setContentsMargins(CARD_INSET, CARD_INSET, CARD_INSET, CARD_INSET)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("versionHeaderRow")
        # A plain QWidget ignores stylesheet backgrounds (including radius)
        # unless this attribute is set.
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
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
        self.scroll.setWidgetResizable(False)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # Rebinding rows while scrolling must not wait for a repaint.
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scrolled)

        # Virtualised list: only the rows inside the viewport exist as widgets.
        # The two spacers provide the scrollable height, so switching category
        # only has to fill the visible slice instead of all ~900 entries.
        self.list_content = QWidget()
        self.list_content.setObjectName("versionsListContent")
        self.list_content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.list_layout = QVBoxLayout(self.list_content)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)

        self.top_spacer = QWidget()
        self.top_spacer.setFixedHeight(0)
        self.list_layout.addWidget(self.top_spacer)

        self.rows_host = QWidget()
        self.rows_host.setObjectName("versionsListContent")
        self.list_layout.addWidget(self.rows_host)

        self.bottom_spacer = QWidget()
        self.bottom_spacer.setFixedHeight(0)
        self.list_layout.addWidget(self.bottom_spacer)

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
        """Fill the page with the official version list (all categories)."""
        self._versions = list(versions)
        self._by_id = {v.id: v for v in self._versions}
        self._refresh_installed()

        # The default selection has to match the active filter, otherwise the
        # detail card describes a version that is not in the visible list.
        matching = self._visible_versions()
        if self._selected not in {v.id for v in matching}:
            self._selected = matching[0].id if matching else ""

        self._render_rows()
        if self._selected:
            self._select(self._selected)

    def _visible_versions(self):
        """Apply the category chip and the search box to the full list."""
        result = []
        for version in self._versions:
            if self._filter != "Все" and version.category != self._filter:
                continue
            if self._search and self._search.lower() not in version.id.lower():
                continue
            result.append(version)
        return result

    def _render_rows(self):
        """
        Rebuild the visible slice of the list.

        Only rows near the viewport exist as widgets; the spacers above and
        below provide the full scroll height. This keeps switching categories
        instant even though the list holds ~900 versions.
        """
        visible = self._visible_versions()
        self._visible = visible

        has_rows = bool(visible)
        self.scroll.setVisible(has_rows)
        self.list_empty.setVisible(not has_rows)
        if not has_rows:
            self.list_empty.setText("Ничего не найдено")

        total_height = len(visible) * ROW_HEIGHT
        self.list_content.setFixedHeight(max(total_height, 1))
        self.list_content.setMinimumWidth(self.scroll.viewport().width())

        self._sync_rows()

    def _visible_range(self):
        """Index range of rows that must exist as widgets right now."""
        total = len(self._visible)
        if not total:
            return 0, 0

        viewport_h = max(self.scroll.viewport().height(), ROW_HEIGHT)
        offset = self.scroll.verticalScrollBar().value()

        first = max(0, offset // ROW_HEIGHT - ROW_BUFFER)
        visible_count = viewport_h // ROW_HEIGHT + 1
        last = min(total, first + visible_count + ROW_BUFFER * 2)
        return first, last

    def _on_scrolled(self, _value):
        """Rebind rows after the scroll position changed."""
        self._sync_rows()

    def _sync_rows(self):
        """Fill the pooled rows with whatever belongs in the viewport."""
        # Resizing the spacers moves the scrollbar, which fires valueChanged
        # and would re-enter this method; the guard stops that recursion.
        if self._syncing:
            return
        self._syncing = True
        try:
            self._sync_rows_inner()
        finally:
            self._syncing = False

    def _sync_rows_inner(self):
        visible = self._visible
        first, last = self._visible_range()
        needed = last - first

        pool = self._pool
        while len(pool) < needed:
            row = VersionRow()
            row.clicked.connect(self._select)
            row.delete_requested.connect(self.delete_requested.emit)
            self.list_layout.insertWidget(
                self.list_layout.indexOf(self.bottom_spacer), row
            )
            pool.append(row)
        for row in pool[needed:]:
            row.hide()

        # Spacers frame the visible block and create the scrollable height.
        top_height = first * ROW_HEIGHT
        bottom_height = max(0, (len(visible) - last) * ROW_HEIGHT)
        if self.top_spacer.height() != top_height:
            self.top_spacer.setFixedHeight(top_height)
        if self.bottom_spacer.height() != bottom_height:
            self.bottom_spacer.setFixedHeight(bottom_height)

        self._rows = {}
        # Only the slice that fits the viewport gets real data; the rest of the
        # pool stays hidden until it scrolls into view.
        for offset, row in enumerate(pool[:needed]):
            version = visible[first + offset]
            row.setVersion(
                version.id,
                get_required_java_version(version.id),
                self._is_installed(version.id),
                version.category,
            )
            row.set_selected(version.id == self._selected)
            row.show()
            self._rows[version.id] = row

    def _is_installed(self, version_id: str) -> bool:
        return version_id in self._installed

    def _refresh_installed(self):
        """
        Snapshot which versions are on disk.

        Checking the filesystem once per render made every chip switch walk
        hundreds of paths; the result is cached until it is invalidated.
        """
        versions_dir = Path(self.config.install_path) / "versions"
        installed = set()
        if versions_dir.is_dir():
            try:
                for folder in versions_dir.iterdir():
                    if folder.is_dir() and is_version_installed(
                        self.config.install_path, folder.name
                    ):
                        installed.add(folder.name)
            except OSError:
                pass
        self._installed = installed
        return installed

    # ---------- selection ----------

    def _set_filter(self, name: str):
        """Switch the category chip. Selection follows when it stays valid."""
        if name == self._filter:
            return

        self._filter = name
        for chip in self.chips:
            chip.setChecked(chip.text() == name)

        self._render_rows()

        # A version from another category is no longer in the list, so pick the
        # first one instead of leaving the detail card on a hidden entry.
        if self._selected not in self._rows:
            self._select(self._visible[0].id if self._visible else "")
        else:
            self._highlight_rows()

    def _set_search(self, text: str):
        self._search = text.strip()
        self._render_rows()

        if self._selected not in self._rows:
            self._select(self._visible[0].id if self._visible else "")

    def _select(self, version: str, fetch_stats: bool = True):
        if not version:
            self._selected = None
            self._highlight_rows()
            return

        self._selected = version
        self._highlight_rows()

        info = self._by_id.get(version)
        java = get_required_java_version(version)
        installed = self._is_installed(version)

        category = info.category if info else "Release"
        is_stable = category == "Release"

        self.detail_title.setText(f"Minecraft {version}")
        self.detail_subtitle.setText(
            "Установлена" if installed else f"{category} · Vanilla"
        )
        if is_stable:
            self.detail_description.setText(
                f"Официальная версия Minecraft {version} без модификаций. "
                f"Требуется Java {java}."
            )
        else:
            self.detail_description.setText(
                f"Сборка {category} Minecraft {version}. Могут быть "
                f"нестабильности и изменения. Требуется Java {java}."
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
            self.detail_subtitle.setText(f"{category} · Vanilla · Установлена")

        if fetch_stats and not installed:
            self._request_stats(version)

    def _highlight_rows(self):
        for version, row in self._rows.items():
            row.set_selected(version == self._selected)

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
        self._refresh_installed()
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