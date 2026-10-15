"""
"Сборки" page - modpack catalog.

Top: a provider swiper (Modrinth / CurseForge / GitHub). Modrinth is fully
implemented (search + version/category filters + modpack details); CurseForge
and the custom/GitHub provider are placeholders for now.

Clicking a card opens a full detail screen inside the section (with a "back"
button to the catalog).
"""

from typing import List, Optional
from pathlib import Path

from PyQt6.QtCore import (
    Qt, pyqtSignal, QThread, QThreadPool, QRunnable, QTimer, QEvent, QObject,
    QSize, QRect, QPoint, QPointF, QSizeF,
)
from PyQt6.QtGui import (
    QColor, QFont, QPixmap, QPainter, QPainterPath, QLinearGradient,
    QPolygonF, QPen, QIcon,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLayout, QLabel,
    QPushButton, QCheckBox, QLineEdit, QComboBox, QFrame, QScrollArea,
    QSizePolicy, QStackedWidget, QMenu,
)

from ui.ui_helpers import make_icon, apply_letter_spacing
from core.modrinth_catalog import _game_version_key
from core import (
    ModrinthCatalogClient, CurseForgeCatalogClient, ModpackHit, ModpackDetail,
    ModpackTags, CatalogError, format_downloads, IconManager,
    KNOWN_LOADERS, LOADER_LABELS,
)
 

# ---------- layout constants ----------

CARD_WIDTH = 300
CARD_PREVIEW_HEIGHT = 150
GRID_SPACING = 22
PAGE_SIZE = 20
DETAIL_VERSION_LIMIT = 50

ROW_COVER_SIZE = 104
FILTERS_PANEL_WIDTH = 270

MINI_CARD_WIDTH = 190
MINI_COVER_HEIGHT = 112
MINI_CARD_HEIGHT = 196

ALL_GAME_VERSIONS = "Все версии"
ALL_CATEGORIES = "Все категории"
ALL_LOADERS = "Все загрузчики"

# Brand colour per provider, drives the swiper, filters and primary buttons.
PROVIDER_ACCENTS = {
    "modrinth": "#1bd96a",
    "curseforge": "#f16436",
    "github": "#89b4fa",
}

# Environment filter; Modrinth has no such project tags, so it stays inert.
ENVIRONMENT_OPTIONS = [("client", "Клиент"), ("server", "Сервер")]

# Russian labels for the most common catalog categories (fallback: title-case).
CATEGORY_LABELS = {
    "adventure": "Приключения",
    "combat": "Сражения",
    "challenging": "Сложные",
    "kitchen-sink": "Много модов",
    "lightweight": "Лёгкие сборки",
    "magic": "Магия",
    "multiplayer": "Мультиплеер",
    "optimization": "Оптимизация",
    "quests": "Квесты",
    "technology": "Tech",
    "exploration": "Исследование",
    "minigame": "Мини-игры",
    "sci-fi": "Sci-Fi",
    "worldgen": "Генерация мира",
}


def category_label(name: str) -> str:
    key = name.strip().lower()
    if key in CATEGORY_LABELS:
        return CATEGORY_LABELS[key]
    return key.replace("-", " ").title()

# Monogram avatars: (background, foreground) pairs, like the mockup.
MONOGRAM_COLORS = [
    ("#1f2a44", "#89b4fa"),
    ("#1e3326", "#a6e3a1"),
    ("#3a2230", "#f38ba8"),
    ("#332e1e", "#f9e2af"),
    ("#2b2340", "#cba6f7"),
    ("#3a2a20", "#fab387"),
]


def monogram(title: str) -> str:
    """Two-letter monogram from a modpack title ("Melon Vanilla" -> "MV")."""
    words = [w for w in title.replace("-", " ").replace("_", " ").split() if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def monogram_colors(key: str):
    """Deterministic palette entry so a pack keeps its colour between renders."""
    if not key:
        return MONOGRAM_COLORS[0]
    index = sum(ord(ch) for ch in key) % len(MONOGRAM_COLORS)
    return MONOGRAM_COLORS[index]


def rounded_pixmap(
    pixmap: Optional[QPixmap], width: int, height: int, radius: int
) -> Optional[QPixmap]:
    """Scale-to-fill, centre-crop and round the corners of ``pixmap``."""
    if pixmap is None or pixmap.isNull() or width <= 0 or height <= 0:
        return None

    scaled = pixmap.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    left = max(0, (scaled.width() - width) // 2)
    top = max(0, (scaled.height() - height) // 2)
    cropped = scaled.copy(left, top, width, height)

    result = QPixmap(width, height)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(0, 0, width, height, radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, cropped)
    painter.end()
    return result


def dot_pixmap(color: str, size: int = 10) -> QPixmap:
    """A small filled circle, used as the provider dot in the switcher pills."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(0, 0, size - 1, size - 1)
    painter.end()
    return pixmap


# ---------- icon loading (covers) ----------


class _IconTask(QRunnable):
    """Downloads one cover on the shared thread pool (via :class:`IconManager`)."""

    def __init__(self, manager: IconManager, loader: "IconLoader", url: str, size):
        super().__init__()
        self._manager = manager
        self._loader = loader
        self._url = url
        self._size = size

    def run(self):
        try:
            pixmap = self._manager.load_icon(self._url, self._size)
        except Exception:  # noqa: BLE001 - a broken cover must not crash the app
            pixmap = None
        # Emitted from a worker thread; the loader's slot runs on the GUI thread.
        self._loader._task_done.emit(self._url, pixmap)


class IconLoader(QObject):
    """Fetches and caches modpack covers without blocking the UI.

    Only created when a real install path is available, so tests (which build
    the page with ``config=None``) never touch the network.
    """

    icon_ready = pyqtSignal(str, object)  # url, QPixmap (or None)
    _task_done = pyqtSignal(str, object)

    def __init__(self, cache_dir, parent=None):
        super().__init__(parent)
        self._manager = IconManager(Path(cache_dir))
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)
        self._cache = {}
        self._pending = set()
        self._tasks = {}
        self._task_done.connect(self._deliver)

    def request(self, url: str, size=(512, 512)):
        if not url:
            return
        if url in self._cache:
            pixmap = self._cache[url]
            # Deliver on the next tick so callers can finish building first.
            QTimer.singleShot(0, lambda u=url, p=pixmap: self.icon_ready.emit(u, p))
            return
        if url in self._pending:
            return
        self._pending.add(url)
        task = _IconTask(self._manager, self, url, size)
        self._tasks[url] = task
        self._pool.start(task)

    def _deliver(self, url: str, pixmap):
        self._pending.discard(url)
        self._tasks.pop(url, None)
        if pixmap is not None and not pixmap.isNull():
            self._cache[url] = pixmap
        else:
            pixmap = None
        self.icon_ready.emit(url, pixmap)

    def shutdown(self):
        self._pool.clear()
        self._pool.waitForDone(3000)


# ---------- background workers ----------


class TagsThread(QThread):
    """Fetches the filter values (game versions / categories / loaders)."""

    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.setObjectName("BuildsTagsThread")
        self.client = client

    def run(self):
        try:
            self.ready.emit(self.client.get_tags())
        except Exception as exc:  # noqa: BLE001 - report anything to the UI
            self.failed.emit(str(exc))


class SearchThread(QThread):
    """Runs one catalog search request off the GUI thread."""

    ready = pyqtSignal(object, int, int)  # hits, total, offset
    failed = pyqtSignal(str)

    def __init__(self, client, params: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("BuildsSearchThread")
        self.client = client
        self.params = params

    def run(self):
        try:
            result = self.client.search(**self.params)
            self.ready.emit(result.hits, result.total, result.offset)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class DetailThread(QThread):
    """Loads the full description and version list of one modpack."""

    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, client, project_key: str, parent=None):
        super().__init__(parent)
        self.setObjectName(f"BuildsDetailThread-{project_key}")
        self.client = client
        self.project_key = project_key

    def run(self):
        try:
            self.ready.emit(self.client.get_details(self.project_key))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


# ---------- small widgets ----------


class FilterChip(QFrame):
    """A read-only pill used to show categories in the detail screen."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("tagPill")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        label = QLabel(text)
        label.setObjectName("tagPillText")
        layout.addWidget(label)


class ElidedLabel(QLabel):
    """QLabel that shortens its text with "…" instead of clipping it."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setToolTip(text)
        self._apply_elide()

    def setText(self, text: str):
        self._full_text = text
        self.setToolTip(text)
        self._apply_elide()

    def full_text(self) -> str:
        return self._full_text

    def _apply_elide(self):
        metrics = self.fontMetrics()
        available = max(self.width(), 1)
        super().setText(
            metrics.elidedText(self._full_text, Qt.TextElideMode.ElideRight, available)
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_elide()

    def changeEvent(self, event):
        super().changeEvent(event)
        # The stylesheet font is applied after construction.
        if event.type() == QEvent.Type.FontChange:
            self._apply_elide()


class ModpackVersionRow(QFrame):
    """One line in the version list of the detail screen."""

    def __init__(self, version, parent=None):
        super().__init__(parent)
        self.setObjectName("modpackVersionRow")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        name = QLabel(version.name or version.version_number)
        name.setObjectName("modpackVersionName")
        meta_bits = [b for b in (
            version.loader_label,
            ", ".join(version.game_versions[:4]),
        ) if b]
        meta = QLabel(" · ".join(meta_bits))
        meta.setObjectName("modpackVersionMeta")
        titles.addWidget(name)
        titles.addWidget(meta)
        layout.addLayout(titles, 1)

        date = QLabel((version.date_published or "")[:10])
        date.setObjectName("modpackVersionDate")
        layout.addWidget(date)

        download = QPushButton("Скачать")
        download.setObjectName("cardSecondaryButton")
        download.setFixedHeight(32)
        download.setEnabled(False)
        download.setToolTip("Установка сборок появится в следующем обновлении")
        layout.addWidget(download)


class CoverPreview(QFrame):
    """Card preview: the modpack cover when it is known, a monogram otherwise.

    The cover is drawn clipped to the rounded tile so the image reaches the
    corners, and the loader badge is painted on top.
    """

    def __init__(self, hit: ModpackHit, size=None, radius: int = 14,
                 show_badge: bool = True, font_scale: float = 0.36, parent=None):
        super().__init__(parent)
        self.setObjectName("modpackPreview")
        self._hit = hit
        self._title = hit.title
        self._show_badge = show_badge
        self._loader_text = hit.primary_loader if show_badge else ""
        self._radius = radius
        self._font_scale = font_scale
        self._background, self._foreground = monogram_colors(hit.key)
        self._cover: Optional[QPixmap] = None
        self._icon_loader: Optional["IconLoader"] = None
        if size is not None:
            self.setFixedSize(int(size[0]), int(size[1]))
        else:
            self.setFixedHeight(CARD_PREVIEW_HEIGHT)
        self._apply_background()

    def _apply_background(self):
        self.setStyleSheet(
            f"QFrame#modpackPreview {{ background-color: {self._background};"
            f" border-radius: {self._radius}px; }}"
        )

    def replace_hit(self, hit: ModpackHit):
        """Point the preview at another pack (used by the hero banner)."""
        self._hit = hit
        self._title = hit.title
        self._loader_text = hit.primary_loader if self._show_badge else ""
        self._background, self._foreground = monogram_colors(hit.key)
        self._cover = None
        self._apply_background()
        self.update()

    def bind_icon(self, loader: Optional["IconLoader"]):
        if loader is None or self._hit is None or not self._hit.icon_url:
            return
        self._icon_loader = loader
        loader.icon_ready.connect(self._on_icon_ready)
        loader.request(self._hit.icon_url)

    def _on_icon_ready(self, url: str, pixmap):
        if self._hit is not None and url == self._hit.icon_url and pixmap is not None:
            self.set_cover(pixmap)

    def set_cover(self, pixmap: Optional[QPixmap]):
        if pixmap is None or pixmap.isNull():
            return
        self._cover = pixmap
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = self.rect()
        path = QPainterPath()
        path.addRoundedRect(0, 0, rect.width(), rect.height(),
                            self._radius, self._radius)
        painter.setClipPath(path)

        if self._cover is not None:
            scaled = self._cover.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (scaled.width() - rect.width()) // 2
            y = (scaled.height() - rect.height()) // 2
            painter.drawPixmap(-x, -y, scaled)
        else:
            font = QFont(self.font())
            font.setPixelSize(max(18, int(rect.height() * self._font_scale)))
            font.setWeight(QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(QColor(self._foreground))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, monogram(self._title))

        if self._loader_text:
            self._draw_badge(painter, self._loader_text)

        painter.end()

    def _draw_badge(self, painter: QPainter, text: str):
        font = QFont(self.font())
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)

        padding = 9
        width = painter.fontMetrics().horizontalAdvance(text) + padding * 2
        height = 22
        x = self.width() - width - 12
        y = 12

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(17, 17, 27, 200))
        path = QPainterPath()
        path.addRoundedRect(x, y, width, height, height / 2, height / 2)
        painter.drawPath(path)

        painter.setPen(QColor("#cdd6f4"))
        painter.drawText(
            x, y, width, height, Qt.AlignmentFlag.AlignCenter, text
        )


class ModpackCard(QFrame):
    """A modpack tile in the catalog grid (mockup style)."""

    opened = pyqtSignal(object)

    def __init__(self, hit: ModpackHit, parent=None):
        super().__init__(parent)
        self.hit = hit
        self._icon_loader: Optional[IconLoader] = None
        self.setObjectName("modpackCard")
        self.setFixedWidth(CARD_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # --- preview (cover / monogram + loader badge) ---
        self.preview = CoverPreview(hit)
        layout.addWidget(self.preview)

        # --- text ---
        title = ElidedLabel(hit.title)
        title.setObjectName("modpackTitle")
        layout.addWidget(title)

        meta_parts = [hit.primary_loader]
        if hit.latest_game_version:
            meta_parts.append(hit.latest_game_version)
        meta_parts.append(f"{format_downloads(hit.downloads)} загрузок")
        meta = QLabel(" · ".join(meta_parts))
        meta.setObjectName("modpackMeta")
        layout.addWidget(meta)

        layout.addStretch()

        # --- actions ---
        actions = QHBoxLayout()
        actions.setSpacing(8)

        open_button = QPushButton("Открыть")
        open_button.setObjectName("cardPrimaryButton")
        open_button.setFixedHeight(42)
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.clicked.connect(self._emit_open)
        actions.addWidget(open_button, 1)

        menu_button = QPushButton("…")
        menu_button.setObjectName("cardMenuButton")
        menu_button.setFixedSize(46, 42)
        menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        menu_button.clicked.connect(self._open_menu)
        actions.addWidget(menu_button)

        layout.addLayout(actions)

    def bind_icon(self, loader: Optional["IconLoader"]):
        """Start loading the cover and swap it in when it arrives."""
        if loader is None or not self.hit.icon_url:
            return
        self._icon_loader = loader
        loader.icon_ready.connect(self._on_icon_ready)
        loader.request(self.hit.icon_url)

    def _on_icon_ready(self, url: str, pixmap):
        if url == self.hit.icon_url and pixmap is not None:
            self.preview.set_cover(pixmap)

    def _emit_open(self):
        self.opened.emit(self.hit)

    def _open_menu(self):
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        open_action = menu.addAction("Открыть страницу")
        menu.addSeparator()
        download_action = menu.addAction("Скачать сборку")
        download_action.setEnabled(False)
        download_action.setToolTip("Появится в следующем обновлении")

        chosen = menu.exec(
            self.mapToGlobal(self.rect().bottomRight())
        )
        if chosen is open_action:
            self.opened.emit(self.hit)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.opened.emit(self.hit)
        super().mousePressEvent(event)


class FlowLayout(QLayout):
    """Left-to-right layout that wraps widgets onto new lines (chips)."""

    def __init__(self, parent=None, margin: int = 0, spacing: int = 6):
        super().__init__(parent)
        self._items: List = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )
        return size

    def _do_layout(self, rect, test_only: bool) -> int:
        x, y = rect.x(), rect.y()
        line_height = 0
        spacing = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > rect.right() and line_height > 0:
                x = rect.x()
                y += line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


class ActiveFilterChip(QFrame):
    """A removable chip summarising one active filter (in the header row)."""

    removed = pyqtSignal(str, str)

    def __init__(self, group: str, value: str, text: str, parent=None):
        super().__init__(parent)
        self.group = group
        self.value = value
        self.setObjectName("activeFilterChip")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 4, 6, 4)
        layout.setSpacing(6)

        label = QLabel(text)
        label.setObjectName("activeFilterChipText")
        layout.addWidget(label)

        close = QPushButton("×")
        close.setObjectName("activeFilterClose")
        close.setFixedSize(16, 16)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(lambda: self.removed.emit(self.group, self.value))
        layout.addWidget(close)


class FiltersPanel(QFrame):
    """The shared left-hand filter sidebar (loaders, categories, version…)."""

    changed = pyqtSignal()
    reset_requested = pyqtSignal()

    def __init__(self, provider_key: str = "", environment=(),
                 show_environment: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("filtersPanel")
        self.setProperty("provider", provider_key)
        self.setFixedWidth(FILTERS_PANEL_WIDTH)

        self._provider_key = provider_key
        self._environment_options = list(environment) if show_environment else []
        self._loader_buttons: dict = {}
        self._category_boxes: dict = {}
        self._env_boxes: dict = {}
        self._build()

    # ---------- construction ----------

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("filtersSection")
        apply_letter_spacing(label, 1.0)
        return label

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Фильтры")
        title.setObjectName("filtersTitle")
        header.addWidget(title)
        header.addStretch()
        self.reset_button = QPushButton("Сбросить")
        self.reset_button.setObjectName("filtersReset")
        self.reset_button.setProperty("provider", self._provider_key)
        self.reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_button.clicked.connect(self.reset_requested.emit)
        header.addWidget(self.reset_button)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setObjectName("filtersPanelScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("filtersPanelContent")
        box = QVBoxLayout(content)
        box.setContentsMargins(0, 0, 4, 0)
        box.setSpacing(16)

        box.addWidget(self._section("ЗАГРУЗЧИК"))
        self.loaders_flow = FlowLayout(spacing=8)
        box.addLayout(self.loaders_flow)

        box.addWidget(self._section("КАТЕГОРИЯ"))
        self.categories_box = QVBoxLayout()
        self.categories_box.setSpacing(10)
        box.addLayout(self.categories_box)

        if self._environment_options:
            box.addWidget(self._section("ОКРУЖЕНИЕ"))
            env_box = QVBoxLayout()
            env_box.setSpacing(10)
            for key, label in self._environment_options:
                chk = QCheckBox(label)
                chk.setObjectName("filterCheck")
                chk.toggled.connect(lambda _checked: self.changed.emit())
                self._env_boxes[key] = chk
                env_box.addWidget(chk)
            box.addLayout(env_box)

        box.addWidget(self._section("ВЕРСИЯ ИГРЫ"))
        self.game_combo = QComboBox()
        self.game_combo.setObjectName("buildsCombo")
        self.game_combo.setFixedHeight(38)
        self.game_combo.currentIndexChanged.connect(
            lambda _index: self.changed.emit()
        )
        box.addWidget(self.game_combo)

        self.compat_check = QCheckBox("Только совместимые с профилем")
        self.compat_check.setObjectName("filterCompat")
        self.compat_check.setEnabled(False)
        self.compat_check.setToolTip("Появится в следующем обновлении")
        box.addWidget(self.compat_check)

        box.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    # ---------- data ----------

    def set_tags(self, tags: ModpackTags):
        self.game_combo.blockSignals(True)
        self.game_combo.clear()
        self.game_combo.addItem(ALL_GAME_VERSIONS, "")
        for version in tags.game_versions:
            self.game_combo.addItem(version, version)
        self.game_combo.setCurrentIndex(0)
        self.game_combo.blockSignals(False)

        self._clear_layout(self.loaders_flow)
        self._loader_buttons = {}
        for loader in tags.loaders:
            chip = QPushButton(LOADER_LABELS.get(loader, loader.title()))
            chip.setObjectName("filterChip")
            chip.setCheckable(True)
            chip.setFixedHeight(32)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setProperty("loader", loader)
            chip.toggled.connect(
                lambda checked, key=loader: self._on_loader_toggled(key, checked)
            )
            self.loaders_flow.addWidget(chip)
            self._loader_buttons[loader] = chip

        self._clear_layout(self.categories_box)
        self._category_boxes = {}
        for category in tags.categories:
            chk = QCheckBox(category_label(category))
            chk.setObjectName("filterCheck")
            chk.toggled.connect(lambda _checked: self.changed.emit())
            self._category_boxes[category] = chk
            self.categories_box.addWidget(chk)

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def loader(self) -> str:
        for key, chip in self._loader_buttons.items():
            if chip.isChecked():
                return key
        return ""

    def categories(self) -> List[str]:
        return [key for key, chk in self._category_boxes.items() if chk.isChecked()]

    def environment(self) -> List[str]:
        return [key for key, chk in self._env_boxes.items() if chk.isChecked()]

    def game_version(self) -> str:
        return self.game_combo.currentData() or ""

    # ---------- mutations ----------

    def _on_loader_toggled(self, key: str, checked: bool):
        if checked:
            for other_key, chip in self._loader_buttons.items():
                if other_key != key and chip.isChecked():
                    chip.blockSignals(True)
                    chip.setChecked(False)
                    chip.blockSignals(False)
        self.changed.emit()

    def select_loader(self, key: str):
        chip = self._loader_buttons.get(key)
        if chip is not None and not chip.isChecked():
            chip.setChecked(True)

    def deselect_loader(self, key: str):
        chip = self._loader_buttons.get(key)
        if chip is not None and chip.isChecked():
            chip.blockSignals(True)
            chip.setChecked(False)
            chip.blockSignals(False)

    def set_category(self, name: str, checked: bool = True):
        chk = self._category_boxes.get(name)
        if chk is not None:
            chk.blockSignals(True)
            chk.setChecked(checked)
            chk.blockSignals(False)

    def set_environment(self, key: str, checked: bool = True):
        chk = self._env_boxes.get(key)
        if chk is not None:
            chk.blockSignals(True)
            chk.setChecked(checked)
            chk.blockSignals(False)

    def set_game_version(self, value: str):
        index = self.game_combo.findData(value) if value else 0
        if index >= 0:
            self.game_combo.blockSignals(True)
            self.game_combo.setCurrentIndex(index)
            self.game_combo.blockSignals(False)

    def reset(self):
        for chip in self._loader_buttons.values():
            chip.blockSignals(True)
            chip.setChecked(False)
            chip.blockSignals(False)
        for chk in self._category_boxes.values():
            chk.blockSignals(True)
            chk.setChecked(False)
            chk.blockSignals(False)
        for chk in self._env_boxes.values():
            chk.blockSignals(True)
            chk.setChecked(False)
            chk.blockSignals(False)
        self.game_combo.blockSignals(True)
        self.game_combo.setCurrentIndex(0)
        self.game_combo.blockSignals(False)
        self.changed.emit()


class ViewToggle(QFrame):
    """Small segmented control switching the catalog between grid and list."""

    changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("viewToggle")
        self.setFixedHeight(38)
        self._buttons: dict = {}
        self._mode = "list"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        for mode, icon_name, tip in (
            ("grid", "grid", "Сетка"),
            ("list", "list", "Список"),
        ):
            button = QPushButton()
            button.setObjectName("viewToggleButton")
            button.setCheckable(True)
            button.setFixedSize(30, 30)
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(make_icon(icon_name, "#a6adc8", 17))
            button.clicked.connect(lambda _=False, m=mode: self.set_mode(m))
            layout.addWidget(button)
            self._buttons[mode] = button

        self._sync()

    def _sync(self):
        for key, button in self._buttons.items():
            button.setChecked(key == self._mode)

    def set_mode(self, mode: str, emit: bool = True):
        if mode not in self._buttons:
            return
        self._mode = mode
        self._sync()
        if emit:
            self.changed.emit(mode)

    def mode(self) -> str:
        return self._mode


class ModpackRow(QFrame):
    """A horizontal modpack entry used by the list view (mockup style)."""

    opened = pyqtSignal(object)

    def __init__(self, hit: ModpackHit, provider_key: str = "", parent=None):
        super().__init__(parent)
        self.hit = hit
        self._icon_loader: Optional[IconLoader] = None
        self.setObjectName("modpackRow")
        self.setProperty("provider", provider_key)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(18)

        self.preview = CoverPreview(
            hit, size=(ROW_COVER_SIZE, ROW_COVER_SIZE), radius=12,
            show_badge=False, font_scale=0.30,
        )
        layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(7)
        title = ElidedLabel(hit.title)
        title.setObjectName("rowTitle")
        info.addWidget(title)

        desc = ElidedLabel(hit.description)
        desc.setObjectName("rowDescription")
        info.addWidget(desc)

        tags = QHBoxLayout()
        tags.setSpacing(8)
        for text in self._tag_texts(hit):
            pill = QLabel(text)
            pill.setObjectName("rowTag")
            tags.addWidget(pill)
        tags.addStretch()
        info.addLayout(tags)
        info.addStretch()
        layout.addLayout(info, 1)

        side = QVBoxLayout()
        side.setSpacing(10)

        downloads = QHBoxLayout()
        downloads.setSpacing(6)
        downloads.addStretch()
        arrow = QLabel()
        arrow.setPixmap(make_icon("download", "#7f849c", 14).pixmap(14, 14))
        downloads.addWidget(arrow)
        self.downloads_label = QLabel(f"{format_downloads(hit.downloads)} загрузок")
        self.downloads_label.setObjectName("rowDownloads")
        downloads.addWidget(self.downloads_label)
        side.addLayout(downloads)
        side.addStretch()

        actions = QHBoxLayout()
        actions.setSpacing(8)
        install = QPushButton("Установить")
        install.setObjectName("rowInstallButton")
        install.setProperty("provider", provider_key)
        install.setFixedHeight(38)
        install.setCursor(Qt.CursorShape.PointingHandCursor)
        install.setToolTip("Открыть сборку")
        install.clicked.connect(self._emit_open)
        actions.addWidget(install)

        self.more_button = QPushButton("…")
        self.more_button.setObjectName("rowMenuButton")
        self.more_button.setFixedSize(42, 38)
        self.more_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_button.clicked.connect(self._open_menu)
        actions.addWidget(self.more_button)
        side.addLayout(actions)
        layout.addLayout(side, 0)

    @staticmethod
    def _tag_texts(hit: ModpackHit) -> List[str]:
        texts = [hit.primary_loader]
        if hit.latest_game_version:
            texts.append(hit.latest_game_version)
        cats = [c for c in hit.categories if c not in KNOWN_LOADERS]
        if cats:
            texts.append(" · ".join(category_label(c) for c in cats[:2]))
        return texts

    def bind_icon(self, loader: Optional["IconLoader"]):
        if loader is None or not self.hit.icon_url:
            return
        self._icon_loader = loader
        loader.icon_ready.connect(self._on_icon_ready)
        loader.request(self.hit.icon_url)

    def _on_icon_ready(self, url: str, pixmap):
        if url == self.hit.icon_url and pixmap is not None:
            self.preview.set_cover(pixmap)

    def _emit_open(self):
        self.opened.emit(self.hit)

    def _open_menu(self):
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        open_action = menu.addAction("Открыть страницу")
        menu.addSeparator()
        action = menu.addAction("Скачать сборку")
        action.setEnabled(False)
        action.setToolTip("Появится в следующем обновлении")
        chosen = menu.exec(self.mapToGlobal(self.rect().bottomRight()))
        if chosen is open_action:
            self.opened.emit(self.hit)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.opened.emit(self.hit)
        super().mousePressEvent(event)


class ProviderSwitcher(QFrame):
    """The provider pills (CurseForge / Modrinth / GitHub) in one container."""

    provider_requested = pyqtSignal(int)

    def __init__(self, providers, parent=None):
        super().__init__(parent)
        self.setObjectName("providerSwitcher")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)

        self.buttons: List[QPushButton] = []
        for index, (label, key) in enumerate(providers):
            button = QPushButton(label)
            button.setObjectName("providerPill")
            button.setProperty("provider", key)
            button.setCheckable(True)
            button.setFixedHeight(34)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(QIcon(dot_pixmap(PROVIDER_ACCENTS.get(key, "#6c7086"))))
            button.setIconSize(QSize(10, 10))
            button.clicked.connect(
                lambda _=False, i=index: self.provider_requested.emit(i)
            )
            layout.addWidget(button)
            self.buttons.append(button)

        self.set_current(0)

    def set_current(self, index: int):
        for i, button in enumerate(self.buttons):
            button.setChecked(i == index)


class FiltersButton(QFrame):
    """The "Фильтры (N)" button that reveals the collapsed filter panel."""

    clicked = pyqtSignal()

    def __init__(self, provider_key: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("filtersButton")
        self.setProperty("provider", provider_key)
        self.setProperty("active", False)
        self.setFixedHeight(42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 12, 0)
        layout.setSpacing(8)

        self._icon = QLabel()
        self._icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self._icon)

        self.label = QLabel("Фильтры")
        self.label.setObjectName("filtersButtonText")
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.label)

        self.badge = QLabel("0")
        self.badge.setObjectName("filtersBadge")
        self.badge.setFixedSize(18, 18)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.badge.setVisible(False)
        layout.addWidget(self.badge)

        self._set_icon(False)

    def _set_icon(self, active: bool):
        color = PROVIDER_ACCENTS.get(self.property("provider"), "#cba6f7") if active \
            else "#cdd6f4"
        self._icon.setPixmap(make_icon("filter", color, 16).pixmap(16, 16))

    def set_count(self, count: int):
        self.badge.setText(str(count))
        self.badge.setVisible(count > 0)

    def set_checked(self, checked: bool):
        self.setProperty("active", bool(checked))
        self._set_icon(bool(checked))
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class MiniPackCard(QFrame):
    """A compact pack card used in the CurseForge hero sections."""

    opened = pyqtSignal(object)

    def __init__(self, hit: ModpackHit, provider_key: str = "curseforge", parent=None):
        super().__init__(parent)
        self.hit = hit
        self._icon_loader: Optional[IconLoader] = None
        self.setObjectName("miniCard")
        self.setFixedSize(MINI_CARD_WIDTH, MINI_CARD_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        self.preview = CoverPreview(
            hit, size=(MINI_CARD_WIDTH - 12, MINI_COVER_HEIGHT),
            radius=11, show_badge=True, font_scale=0.30,
        )
        layout.addWidget(self.preview)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = ElidedLabel(hit.title)
        title.setObjectName("miniCardTitle")
        titles.addWidget(title)
        meta_bits = [b for b in (hit.latest_game_version,
                                 f"{format_downloads(hit.downloads)}") if b]
        meta = QLabel(" · ".join(meta_bits))
        meta.setObjectName("miniCardMeta")
        titles.addWidget(meta)
        footer.addLayout(titles, 1)

        download = QPushButton()
        download.setObjectName("miniDownloadButton")
        download.setFixedSize(34, 34)
        download.setCursor(Qt.CursorShape.PointingHandCursor)
        download.setIcon(make_icon("download", "#1b0d06", 16))
        download.setIconSize(QSize(16, 16))
        download.setToolTip("Открыть сборку")
        download.clicked.connect(self._emit_open)
        footer.addWidget(download, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(footer)

    def bind_icon(self, loader: Optional["IconLoader"]):
        if loader is None or not self.hit.icon_url:
            return
        self._icon_loader = loader
        loader.icon_ready.connect(self._on_icon_ready)
        loader.request(self.hit.icon_url)

    def _on_icon_ready(self, url: str, pixmap):
        if url == self.hit.icon_url and pixmap is not None:
            self.preview.set_cover(pixmap)

    def _emit_open(self):
        self.opened.emit(self.hit)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.opened.emit(self.hit)
        super().mousePressEvent(event)


class CatalogSection(QWidget):
    """A horizontally scrolling row of pack cards with a "Все →" link."""

    opened = pyqtSignal(object)
    show_all_requested = pyqtSignal()

    def __init__(self, title: str, suffix: str = "", parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("sectionTitle")
        header.addWidget(self.title_label)

        self.suffix_label = QLabel(suffix)
        self.suffix_label.setObjectName("sectionSuffix")
        self.suffix_label.setVisible(bool(suffix))
        header.addWidget(self.suffix_label)
        header.addStretch()

        self.all_button = QPushButton("Все →")
        self.all_button.setObjectName("sectionLink")
        self.all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.all_button.clicked.connect(self.show_all_requested.emit)
        header.addWidget(self.all_button)
        root.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("sectionScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFixedHeight(MINI_CARD_HEIGHT + 14)

        self._content = QWidget()
        self._content.setObjectName("sectionContent")
        self._row = QHBoxLayout(self._content)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(12)
        self._row.addStretch()
        self.scroll.setWidget(self._content)
        root.addWidget(self.scroll)

        self._cards: List[MiniPackCard] = []
        self._icon_loader: Optional[IconLoader] = None

    def set_title(self, title: str):
        self.title_label.setText(title)

    def set_hits(self, hits, icon_loader=None):
        if icon_loader is not None:
            self._icon_loader = icon_loader
        for card in self._cards:
            self._row.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards = []
        # keep the trailing stretch last
        for hit in hits:
            card = MiniPackCard(hit)
            card.opened.connect(self.opened.emit)
            card.bind_icon(self._icon_loader)
            self._row.insertWidget(self._row.count() - 1, card)
            self._cards.append(card)


class HeroBanner(QFrame):
    """The "Популярно сейчас" featured banner at the top of the CurseForge tab."""

    opened = pyqtSignal(object)

    def __init__(self, provider_key: str = "curseforge", parent=None):
        super().__init__(parent)
        self.setObjectName("heroBanner")
        self.setFixedHeight(272)
        self._hit: Optional[ModpackHit] = None
        self._icon_loader: Optional[IconLoader] = None

        root = QHBoxLayout(self)
        root.setContentsMargins(34, 26, 30, 26)
        root.setSpacing(24)

        left = QVBoxLayout()
        left.setSpacing(10)

        caption = QLabel("ПОПУЛЯРНО СЕЙЧАС")
        caption.setObjectName("heroCaption")
        apply_letter_spacing(caption, 2.0)
        left.addWidget(caption)

        self.title_label = ElidedLabel("")
        self.title_label.setObjectName("heroTitle")
        left.addWidget(self.title_label)

        self.pills_row = QHBoxLayout()
        self.pills_row.setSpacing(8)
        self.pills_row.addStretch()
        left.addLayout(self.pills_row)

        self.description = QLabel("")
        self.description.setObjectName("heroDescription")
        self.description.setWordWrap(True)
        self.description.setMaximumWidth(560)
        left.addWidget(self.description)

        left.addStretch()

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.install_button = QPushButton("Установить")
        self.install_button.setObjectName("heroPrimaryButton")
        self.install_button.setFixedHeight(44)
        self.install_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_button.clicked.connect(self._emit_open)
        buttons.addWidget(self.install_button)

        self.more_button = QPushButton("Подробнее")
        self.more_button.setObjectName("heroSecondaryButton")
        self.more_button.setFixedHeight(44)
        self.more_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_button.clicked.connect(self._emit_open)
        buttons.addWidget(self.more_button)
        buttons.addStretch()
        left.addLayout(buttons)

        root.addLayout(left, 1)

        self.cover = CoverPreview(
            ModpackHit(
                project_id="", slug="", title="", description="", author="",
                downloads=0, follows=0, icon_url="", categories=[],
                game_versions=[], loaders=[], latest_version="", date_updated="",
            ),
            size=(300, 220), radius=16, show_badge=False, font_scale=0.4,
        )
        self.cover.setVisible(False)
        root.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignVCenter)

        self.dots = QLabel("●  ·  ·")
        self.dots.setObjectName("heroDots")
        root.addWidget(self.dots, 0, Qt.AlignmentFlag.AlignBottom)

    # ---------- painting ----------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()

        path = QPainterPath()
        path.addRoundedRect(0, 0, rect.width(), rect.height(), 18, 18)
        painter.setClipPath(path)

        gradient = QLinearGradient(0, 0, rect.width(), rect.height())
        gradient.setColorAt(0.0, QColor("#e05a1e"))
        gradient.setColorAt(0.55, QColor("#c94a17"))
        gradient.setColorAt(1.0, QColor("#a83a13"))
        painter.fillRect(rect, gradient)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 16))
        height = rect.height()
        stripe_w = 13
        step = 27
        x = -height
        while x < rect.width() + height:
            painter.drawPolygon(QPolygonF([
                QPointF(x, 0),
                QPointF(x + stripe_w, 0),
                QPointF(x + stripe_w + height, height),
                QPointF(x + height, height),
            ]))
            x += step
        painter.end()

    # ---------- data ----------

    def set_hit(self, hit: Optional[ModpackHit], icon_loader=None):
        self._hit = hit
        self._icon_loader = icon_loader
        if hit is None:
            self.setVisible(False)
            return

        self.title_label.setText(hit.title)
        self.description.setText(hit.description)
        self.setVisible(True)

        while self.pills_row.count() > 1:
            item = self.pills_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        pills = [hit.primary_loader]
        if hit.latest_game_version:
            pills.append(hit.latest_game_version)
        pills.append(f"{format_downloads(hit.downloads)} загрузок")
        for text in pills:
            pill = QLabel(text)
            pill.setObjectName("heroPill")
            self.pills_row.insertWidget(self.pills_row.count() - 1, pill)

        self.cover.setVisible(bool(hit.icon_url))
        if hit.icon_url:
            self.cover.replace_hit(hit)
            self.cover.bind_icon(icon_loader)

    def _emit_open(self):
        if self._hit is not None:
            self.opened.emit(self._hit)


class PlaceholderProvider(QWidget):
    """Empty state for the providers that are not implemented yet."""

    def __init__(self, title: str, hint: str, icon_name: str = "builds", parent=None):
        super().__init__(parent)
        self.setObjectName("providerPlaceholder")

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

        sub = QLabel(hint)
        sub.setObjectName("placeholderHint")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        layout.addWidget(sub)


# ---------- catalog ----------


class CatalogView(QWidget):
    """Filters plus the modpack list/grid for one provider.

    Any catalog client exposing ``get_tags`` / ``search`` / ``get_details``
    (Modrinth, CurseForge, …) can drive it. The search box lives in the section
    header (see :class:`BuildsPage`) and feeds :meth:`set_query`.
    """

    open_requested = pyqtSignal(object)
    count_changed = pyqtSignal(int)
    active_filters_changed = pyqtSignal(int)
    query_changed = pyqtSignal()

    def __init__(self, client: ModrinthCatalogClient, icon_loader=None,
                 provider_key: str = "", collapsible: bool = False,
                 show_environment: bool = True, parent=None):
        super().__init__(parent)
        self.client = client
        self.provider_key = provider_key
        self._icon_loader = icon_loader
        self._collapsible = collapsible
        self.is_collapsible = collapsible
        self._show_environment = show_environment

        self._cards: List[QWidget] = []
        self._hits: List[ModpackHit] = []
        self._total = 0
        self._columns = 0
        self._rows = 0
        self._view_mode = "list"
        self._query = ""
        self._filters_open = not collapsible
        self.grid: Optional[QGridLayout] = None
        self._tags_thread: Optional[TagsThread] = None
        self._search_thread: Optional[SearchThread] = None
        self._loaded = False

        # Debounce so typing in the search box does not fire a request per key.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(400)
        self._search_timer.timeout.connect(self._on_debounce_finished)

        self._build()

    # ---------- construction ----------

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        self.filters = FiltersPanel(
            provider_key=self.provider_key,
            environment=ENVIRONMENT_OPTIONS,
            show_environment=self._show_environment,
        )
        self.filters.changed.connect(self._on_filters_changed)
        self.filters.reset_requested.connect(self.filters.reset)
        root.addWidget(self.filters)
        if self._collapsible:
            self.filters.setVisible(False)
        self.filters.setProperty("provider", self.provider_key)

        content = QVBoxLayout()
        content.setSpacing(14)
        content.addLayout(self._build_header())

        self.status_label = QLabel("")
        self.status_label.setObjectName("buildsStatus")
        content.addWidget(self.status_label)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("buildsScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content.addWidget(self.scroll, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        self.more_button = QPushButton("Показать ещё")
        self.more_button.setObjectName("secondaryButton")
        self.more_button.setFixedHeight(42)
        self.more_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_button.clicked.connect(self._on_more_clicked)
        self.more_button.setVisible(False)
        footer.addWidget(self.more_button)
        footer.addStretch()
        content.addLayout(footer)

        root.addLayout(content, 1)

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        self.count_label = QLabel("")
        self.count_label.setObjectName("buildsCount")
        row.addWidget(self.count_label)

        self.chips_host = QWidget()
        chips_policy = QSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        chips_policy.setHeightForWidth(True)
        self.chips_host.setSizePolicy(chips_policy)
        self.chips_layout = FlowLayout(self.chips_host, spacing=8)
        row.addWidget(self.chips_host, 1)

        sort_caption = QLabel("Сортировка")
        sort_caption.setObjectName("sortCaption")
        row.addWidget(sort_caption)

        self.sort_combo = self._make_combo()
        for value, label in self.client.sort_options:
            self.sort_combo.addItem(label, value)
        self.sort_combo.setMinimumWidth(170)
        self.sort_combo.currentIndexChanged.connect(self._on_filter_changed)
        row.addWidget(self.sort_combo)

        self.view_toggle = ViewToggle()
        self.view_toggle.changed.connect(self.set_view_mode)
        row.addWidget(self.view_toggle)

        return row

    @staticmethod
    def _make_combo() -> QComboBox:
        combo = QComboBox()
        combo.setObjectName("buildsCombo")
        combo.setFixedHeight(38)
        return combo

    # ---------- query / filters ----------

    def activate(self, query: str):
        """Select this catalog and (re)run its search for ``query``."""
        self._query = query or ""
        if not self._loaded:
            self.load()
        else:
            self.refresh()

    def set_query(self, text: str):
        """Search text coming from the section header (debounced)."""
        text = text or ""
        if text == self._query:
            return
        self._query = text
        self.query_changed.emit()
        self._search_timer.start()

    def filters_visible(self) -> bool:
        return self._filters_open

    def has_active_filters(self) -> bool:
        return bool(self._active_filters())

    def active_filter_count(self) -> int:
        return len(self._active_filters())

    def toggle_filters(self, checked: Optional[bool] = None):
        if checked is None:
            checked = not self._filters_open
        self._filters_open = bool(checked)
        self.filters.setVisible(self._filters_open)

    def _on_debounce_finished(self):
        self._start_search(append=False)

    def _on_filter_changed(self, _index: int = 0):
        self._start_search(append=False)

    def _on_filters_changed(self):
        self._refresh_chips()
        self._start_search(append=False)

    def _active_filters(self) -> List:
        active = []
        loader = self.filters.loader()
        if loader:
            active.append(("loader", loader, LOADER_LABELS.get(loader, loader.title())))
        for category in self.filters.categories():
            active.append(("category", category, category_label(category)))
        version = self.filters.game_version()
        if version:
            active.append(("game_version", version, version))
        env_labels = dict(ENVIRONMENT_OPTIONS)
        for env in self.filters.environment():
            active.append(("environment", env, env_labels.get(env, env)))
        return active

    def _refresh_chips(self):
        while self.chips_layout.count():
            item = self.chips_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        active = self._active_filters()
        for group, value, text in active:
            chip = ActiveFilterChip(group, value, text)
            chip.removed.connect(self._on_chip_removed)
            self.chips_layout.addWidget(chip)
        self.active_filters_changed.emit(len(active))

    def _on_chip_removed(self, group: str, value: str):
        if group == "loader":
            self.filters.deselect_loader(value)
        elif group == "category":
            self.filters.set_category(value, False)
        elif group == "game_version":
            self.filters.set_game_version("")
        elif group == "environment":
            self.filters.set_environment(value, False)
        self._refresh_chips()
        self._start_search(append=False)

    # ---------- loading ----------

    def load(self):
        """First load: fetch the tags, then run the initial search."""
        if self._loaded:
            return
        self._loaded = True

        self._set_status("Загрузка каталога…")
        self._tags_thread = TagsThread(self.client, self)
        self._tags_thread.ready.connect(self._on_tags_ready)
        self._tags_thread.failed.connect(self._on_tags_failed)
        self._tags_thread.start()

        # The first results do not depend on the tags, so start right away.
        self._start_search(append=False)

    def refresh(self):
        self._start_search(append=False)

    def _on_tags_ready(self, tags):
        self.filters.set_tags(tags)
        self._refresh_chips()

    def _on_tags_failed(self, message: str):
        # Filters are a nice-to-have; keep the catalog usable without them.
        self._set_status(f"Фильтры недоступны: {message}")

    def _on_more_clicked(self):
        self._start_search(append=True)

    def _current_params(self, offset: int) -> dict:
        categories = self.filters.categories()
        return {
            "query": self._query,
            "game_version": self.filters.game_version(),
            "category": categories[0] if categories else "",
            "categories": categories,
            "loader": self.filters.loader(),
            "sort": self.sort_combo.currentData() or "relevance",
            "limit": PAGE_SIZE,
            "offset": offset,
        }

    def _start_search(self, append: bool):
        if self._search_thread is not None and self._search_thread.isRunning():
            return

        offset = len(self._hits) if append else 0
        if not append:
            self._set_status("Поиск…")

        self.more_button.setEnabled(False)
        # A bound method (not a lambda) keeps Qt's lifetime management: the
        # connection is dropped when this widget is destroyed, so a late
        # "ready" from a previous page can never reach a freed object.
        self._search_thread = SearchThread(self.client, self._current_params(offset), self)
        self._search_thread.ready.connect(self._on_search_ready)
        self._search_thread.failed.connect(self._on_search_failed)
        self._search_thread.start()

    def _on_search_ready(self, hits, total: int, offset: int):
        append = offset > 0
        if append:
            self._hits.extend(hits)
        else:
            self._hits = list(hits)

        self._total = total
        self._rebuild_items()
        if not append:
            # New results start from the top; a repaint may otherwise leave the
            # scroll area scrolled past the first row.
            self.scroll.verticalScrollBar().setValue(0)

        self.count_label.setText(f"{total:,}".replace(",", " ") + " сборок")
        self.count_changed.emit(total)

        if not self._hits:
            self._set_status("Ничего не найдено. Попробуйте изменить фильтры.")
        elif len(self._hits) < total:
            self._set_status(f"Показано {len(self._hits)} из {self._total}")
        else:
            self._set_status("")

        has_more = len(self._hits) < total
        self.more_button.setVisible(has_more)
        self.more_button.setEnabled(has_more)

    def _on_search_failed(self, message: str):
        self._set_status(f"Не удалось загрузить каталог: {message}")
        self.more_button.setEnabled(True)

    def _set_status(self, text: str):
        self.status_label.setText(text)

    # ---------- items ----------

    def set_view_mode(self, mode: str):
        if mode not in ("list", "grid"):
            return
        changed = mode != self._view_mode
        self._view_mode = mode
        self.view_toggle.set_mode(mode, emit=False)
        if changed:
            self._rebuild_items()
            self.scroll.verticalScrollBar().setValue(0)

    def _rebuild_items(self):
        for item in self._cards:
            item.setParent(None)
            item.deleteLater()
        self._cards = []

        for hit in self._hits:
            if self._view_mode == "list":
                widget = ModpackRow(hit, self.provider_key)
            else:
                widget = ModpackCard(hit)
            widget.opened.connect(self.open_requested.emit)
            widget.bind_icon(self._icon_loader)
            self._cards.append(widget)

        container = QWidget()
        container.setObjectName("buildsGridContainer")
        if self._view_mode == "list":
            layout = QVBoxLayout(container)
            layout.setContentsMargins(2, 2, 2, 2)
            layout.setSpacing(14)
            for widget in self._cards:
                layout.addWidget(widget)
            layout.addStretch()
            self.grid = None
        else:
            layout = QGridLayout(container)
            layout.setContentsMargins(2, 2, 2, 2)
            layout.setSpacing(GRID_SPACING)
            layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            self.grid = layout
            self._columns = 0
            self._rows = 0
            self._place_grid()

        previous = self.scroll.takeWidget()
        if previous is not None:
            previous.deleteLater()
        self.scroll.setWidget(container)

    def _place_grid(self):
        layout = self.grid
        if layout is None:
            return
        viewport_w = self.scroll.viewport().width()
        columns = max(1, (viewport_w + GRID_SPACING) // (CARD_WIDTH + GRID_SPACING))

        # Reset previously stretched filler columns and rows.
        for col in range(self._columns + 1):
            layout.setColumnStretch(col, 0)
        for row in range(self._rows + 1):
            layout.setRowStretch(row, 0)

        for index, widget in enumerate(self._cards):
            row, col = divmod(index, columns)
            layout.addWidget(widget, row, col)

        rows = (len(self._cards) + columns - 1) // columns if self._cards else 0
        # Trailing filler column/row keep the cards left-aligned and stop the
        # last row from stretching to fill the viewport when there are few hits.
        layout.setColumnStretch(columns, 1)
        if rows:
            layout.setRowStretch(rows, 1)
        self._columns = columns
        self._rows = rows
        layout.invalidate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._view_mode == "grid" and self.grid is not None:
            self._place_grid()

    # ---------- lifecycle ----------

    def shutdown(self):
        for thread in (self._tags_thread, self._search_thread):
            if thread is not None and thread.isRunning():
                # Requests are short; give them a moment to finish before
                # forcing. Terminating a live QThread can abort the process.
                if not thread.wait(2000):
                    thread.terminate()
                    thread.wait(2000)
        self._tags_thread = None
        self._search_thread = None


# ---------- CurseForge discovery home ----------


class DiscoverThread(QThread):
    """Loads the hero pack and the two home sections in one background pass."""

    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, client, profile_version: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("BuildsDiscoverThread")
        self.client = client
        self.profile_version = profile_version

    def run(self):
        try:
            hero = self.client.search(sort="popularity", limit=1)
            hero_hit = hero.hits[0] if hero.hits else None

            version = self.profile_version
            if not version:
                try:
                    tags = self.client.get_tags()
                except Exception:  # noqa: BLE001 - sections still work
                    tags = None
                if tags is not None and tags.game_versions:
                    version = max(tags.game_versions, key=_game_version_key)

            version_hits = []
            if version:
                version_hits = self.client.search(
                    game_version=version, sort="popularity", limit=5
                ).hits

            seen = {hit.project_id for hit in version_hits}
            other = [
                hit for hit in self.client.search(sort="downloads", limit=8).hits
                if hit.project_id not in seen
            ][:5]

            self.ready.emit({
                "hero": hero_hit,
                "version": version_hits,
                "other": other,
                "version_label": version,
            })
        except Exception as exc:  # noqa: BLE001 - report anything to the UI
            self.failed.emit(str(exc))


class DiscoverView(QWidget):
    """The CurseForge home: the hero banner and the two pack carousels."""

    open_requested = pyqtSignal(object)
    show_all_requested = pyqtSignal(str)

    def __init__(self, client, icon_loader=None, provider_key: str = "curseforge",
                 profile_version: str = "", parent=None):
        super().__init__(parent)
        self.client = client
        self._icon_loader = icon_loader
        self.profile_version = profile_version
        self._thread: Optional[DiscoverThread] = None
        self._loaded = False
        self.version_label = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("discoverScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("discoverContent")
        box = QVBoxLayout(content)
        box.setContentsMargins(2, 2, 2, 2)
        box.setSpacing(22)

        self.hero = HeroBanner(provider_key)
        self.hero.opened.connect(self.open_requested.emit)
        box.addWidget(self.hero)

        self.section_version = CatalogSection("Для вашей версии", "совместимо с вашим профилем")
        self.section_version.opened.connect(self.open_requested.emit)
        self.section_version.show_all_requested.connect(
            lambda: self.show_all_requested.emit("version")
        )
        box.addWidget(self.section_version)

        self.section_other = CatalogSection("Другие версии и загрузчики", "Fabric · Forge · NeoForge")
        self.section_other.opened.connect(self.open_requested.emit)
        self.section_other.show_all_requested.connect(
            lambda: self.show_all_requested.emit("other")
        )
        box.addWidget(self.section_other)

        box.addStretch()
        self.scroll.setWidget(content)
        root.addWidget(self.scroll)

        self._status = QLabel("")
        self._status.setObjectName("buildsStatus")
        root.addWidget(self._status)

    def load(self):
        if self._loaded:
            return
        self._loaded = True
        self._status.setText("Загрузка подборок…")
        self._thread = DiscoverThread(self.client, self.profile_version, self)
        self._thread.ready.connect(self._on_ready)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _on_ready(self, payload):
        self.version_label = payload.get("version_label", "")
        if self.version_label:
            self.section_version.set_title(f"Для вашей версии {self.version_label}")

        self.hero.set_hit(payload.get("hero"), self._icon_loader)
        self.section_version.set_hits(payload.get("version") or [], self._icon_loader)
        self.section_other.set_hits(payload.get("other") or [], self._icon_loader)
        self._status.setText("")

    def _on_failed(self, message: str):
        self._status.setText(f"Не удалось загрузить подборки: {message}")

    def shutdown(self):
        if self._thread is not None and self._thread.isRunning():
            if not self._thread.wait(2000):
                self._thread.terminate()
                self._thread.wait(2000)
        self._thread = None


class DiscoverCatalog(QWidget):
    """CurseForge tab: a discovery home plus the regular search results view."""

    open_requested = pyqtSignal(object)
    active_filters_changed = pyqtSignal(int)
    query_changed = pyqtSignal()

    def __init__(self, client, icon_loader=None, profile_version: str = "",
                 parent=None):
        super().__init__(parent)
        self.client = client
        self._icon_loader = icon_loader
        self._query = ""
        self._loaded = False
        # Set when the user opens the results list from a section ("Все →")
        # without any query/filter, so we don't fall back to the home page.
        self._results_requested = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        self.discover = DiscoverView(
            client, icon_loader, profile_version=profile_version
        )
        self.results = CatalogView(
            client, icon_loader,
            provider_key="curseforge", collapsible=True, show_environment=True,
        )
        self.stack.addWidget(self.discover)
        self.stack.addWidget(self.results)

        self.results.open_requested.connect(self.open_requested.emit)
        self.discover.open_requested.connect(self.open_requested.emit)
        self.results.active_filters_changed.connect(self.active_filters_changed.emit)
        self.results.query_changed.connect(self._on_query_changed)
        self.results.filters.changed.connect(self._on_query_changed)
        self.discover.show_all_requested.connect(self._on_show_all)

        self.stack.setCurrentWidget(self.discover)

    # ---------- facade used by BuildsPage ----------

    @property
    def filters(self):
        return self.results.filters

    @property
    def is_collapsible(self) -> bool:
        return True

    def activate(self, query: str):
        self._query = query or ""
        self._results_requested = False
        self.results._query = self._query
        if not self._loaded:
            self._loaded = True
            self.discover.load()
            self.results.load()
        else:
            self.results.refresh()
        self._update_page()

    def load(self):
        self.activate(self._query)

    def refresh(self):
        self.results.refresh()

    def set_query(self, text: str):
        self.results.set_query(text)
        self._query = self.results._query
        self._update_page()

    def filters_visible(self) -> bool:
        return self.results.filters_visible()

    def has_active_filters(self) -> bool:
        return self.results.has_active_filters()

    def active_filter_count(self) -> int:
        return self.results.active_filter_count()

    def toggle_filters(self):
        self.results.toggle_filters()
        self._update_page()

    def shutdown(self):
        self.results.shutdown()
        self.discover.shutdown()

    # ---------- internals ----------

    def _on_query_changed(self):
        self._query = self.results._query
        self._update_page()

    def _update_page(self):
        show_results = (
            bool(self.results._query.strip())
            or self.results.has_active_filters()
            or self.results.filters_visible()
            or self._results_requested
        )
        target = self.results if show_results else self.discover
        if self.stack.currentWidget() is not target:
            self.stack.setCurrentWidget(target)
        if target is self.discover:
            self.discover.load()
        self.query_changed.emit()

    def _on_show_all(self, which: str):
        if which == "version" and self.discover.version_label:
            self.results.filters.set_game_version(self.discover.version_label)
        else:
            self.results.filters.set_game_version("")
        self._results_requested = True
        self.results._on_filters_changed()
        self._update_page()


# ---------- detail ----------


class ModpackDetailView(QWidget):
    """Full screen view of a single modpack inside the section."""

    back_requested = pyqtSignal()

    def __init__(self, icon_loader=None, parent=None):
        super().__init__(parent)
        self.setObjectName("modpackDetail")
        self._hit: Optional[ModpackHit] = None
        self._icon_loader: Optional[IconLoader] = icon_loader
        self._icon_url = ""
        self._version_rows: List[QWidget] = []
        self._build()
        self.bind_icon(icon_loader)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        top = QHBoxLayout()
        back = QPushButton("←  Назад к каталогу")
        back.setObjectName("backButton")
        back.setFixedHeight(38)
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self.back_requested.emit)
        top.addWidget(back)
        top.addStretch()
        root.addLayout(top)

        scroll = QScrollArea()
        scroll.setObjectName("detailScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("modpackDetailContent")
        body = QVBoxLayout(content)
        body.setContentsMargins(2, 2, 16, 16)
        body.setSpacing(18)

        # header
        header = QHBoxLayout()
        header.setSpacing(20)

        self.preview = QLabel()
        self.preview.setObjectName("modpackDetailPreview")
        self.preview.setFixedSize(112, 112)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)

        titles = QVBoxLayout()
        titles.setSpacing(6)
        self.title_label = QLabel("—")
        self.title_label.setObjectName("detailTitle")
        self.author_label = QLabel("")
        self.author_label.setObjectName("modpackDetailAuthor")
        self.description_label = QLabel("")
        self.description_label.setObjectName("detailDescription")
        self.description_label.setWordWrap(True)
        titles.addWidget(self.title_label)
        titles.addWidget(self.author_label)
        titles.addWidget(self.description_label)
        titles.addStretch()
        header.addLayout(titles, 1)
        body.addLayout(header)

        # meta
        self.meta_row = QHBoxLayout()
        self.meta_row.setSpacing(28)
        self.meta_labels = {}
        for key, caption in (
            ("downloads", "Загрузки"),
            ("follows", "Подписчики"),
            ("updated", "Обновлено"),
            ("loader", "Загрузчик"),
        ):
            column = QVBoxLayout()
            column.setSpacing(2)
            caption_label = QLabel(caption)
            caption_label.setObjectName("modpackMetaCaption")
            value_label = QLabel("—")
            value_label.setObjectName("modpackMetaValue")
            column.addWidget(caption_label)
            column.addWidget(value_label)
            self.meta_labels[key] = value_label
            self.meta_row.addLayout(column)
        self.meta_row.addStretch()
        body.addLayout(self.meta_row)

        # categories
        self.categories_row = QHBoxLayout()
        self.categories_row.setSpacing(8)
        self.categories_row.addStretch()
        body.addLayout(self.categories_row)

        # install (placeholder for now)
        install_row = QHBoxLayout()
        install_row.setSpacing(14)
        self.install_button = QPushButton("Скачать и играть")
        self.install_button.setObjectName("primaryButton")
        self.install_button.setFixedHeight(50)
        self.install_button.setMinimumWidth(220)
        self.install_button.setEnabled(False)
        self.install_button.setToolTip("Установка сборок появится в следующем обновлении")
        install_row.addWidget(self.install_button)
        hint = QLabel("Установка, редактирование и докачивание модов появятся позже.")
        hint.setObjectName("modpackHint")
        install_row.addWidget(hint)
        install_row.addStretch()
        body.addLayout(install_row)

        separator = QFrame()
        separator.setObjectName("detailSeparator")
        separator.setFixedHeight(1)
        body.addWidget(separator)

        versions_title = QLabel("Версии")
        versions_title.setObjectName("sectionTitle")
        body.addWidget(versions_title)

        self.versions_status = QLabel("Загрузка…")
        self.versions_status.setObjectName("buildsStatus")
        body.addWidget(self.versions_status)

        self.versions_box = QVBoxLayout()
        self.versions_box.setSpacing(8)
        body.addLayout(self.versions_box)

        body.addStretch()

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    # ---------- data ----------

    def show_hit(self, hit: ModpackHit):
        """Immediately show what the card already knows, before the fetch."""
        self._hit = hit
        self._icon_url = hit.icon_url
        self._clear_versions()

        background, foreground = monogram_colors(hit.key)
        self.preview.clear()
        self.preview.setText(monogram(hit.title))
        self.preview.setStyleSheet(
            f"#modpackDetailPreview {{ background-color: {background};"
            f" color: {foreground}; border-radius: 20px;"
            f" font-size: 40px; font-weight: 800; }}"
        )
        self._request_cover(hit.icon_url)

        self.title_label.setText(hit.title)
        self.author_label.setText(f"Автор: {hit.author}" if hit.author else "")
        self.description_label.setText(hit.description)

        self.meta_labels["downloads"].setText(format_downloads(hit.downloads))
        self.meta_labels["follows"].setText(
            format_downloads(hit.follows) if hit.follows else "—"
        )
        self.meta_labels["updated"].setText((hit.date_updated or "")[:10])
        self.meta_labels["loader"].setText(hit.primary_loader)

        self._set_categories(hit.categories)
        self.versions_status.setText("Загрузка…")

    def set_detail(self, detail: ModpackDetail):
        """Fill in the full description and version list."""
        if detail.description and not self.description_label.text():
            self.description_label.setText(detail.description)

        self.meta_labels["downloads"].setText(format_downloads(detail.downloads))
        self.meta_labels["follows"].setText(
            format_downloads(detail.follows) if detail.follows else "—"
        )
        if detail.date_updated:
            self.meta_labels["updated"].setText(detail.date_updated[:10])
        if detail.loaders:
            self.meta_labels["loader"].setText(
                ", ".join(loader.title() for loader in detail.loaders)
            )
        if detail.categories:
            self._set_categories(detail.categories)
        if detail.title:
            self.title_label.setText(detail.title)

        if detail.icon_url and detail.icon_url != self._icon_url:
            self._icon_url = detail.icon_url
            self._request_cover(detail.icon_url)

        self._fill_versions(detail.versions)

    def set_error(self, message: str):
        self.versions_status.setText(f"Не удалось загрузить версии: {message}")

    # ---------- helpers ----------

    def bind_icon(self, loader: Optional["IconLoader"]):
        self._icon_loader = loader
        if loader is not None:
            loader.icon_ready.connect(self._on_icon_ready)

    def _request_cover(self, url: str):
        if self._icon_loader is not None and url:
            self._icon_loader.request(url, (256, 256))

    def _on_icon_ready(self, url: str, pixmap):
        if pixmap is None or url != self._icon_url:
            return
        rounded = rounded_pixmap(
            pixmap, self.preview.width(), self.preview.height(), 20
        )
        if rounded is None:
            return
        self.preview.setText("")
        self.preview.setStyleSheet(
            "#modpackDetailPreview { background: transparent; border-radius: 20px; }"
        )
        self.preview.setPixmap(rounded)

    def _set_categories(self, categories: List[str]):
        while self.categories_row.count():
            item = self.categories_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for category in categories[:8]:
            self.categories_row.addWidget(FilterChip(category.replace("-", " ")))
        self.categories_row.addStretch()

    def _clear_versions(self):
        while self.versions_box.count():
            item = self.versions_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._version_rows = []

    def _fill_versions(self, versions):
        self._clear_versions()

        if not versions:
            self.versions_status.setText("У этой сборки пока нет версий.")
            return

        shown = versions[:DETAIL_VERSION_LIMIT]
        for version in shown:
            row = ModpackVersionRow(version)
            self.versions_box.addWidget(row)
            self._version_rows.append(row)

        if len(versions) > len(shown):
            more = QLabel(f"… и ещё {len(versions) - len(shown)} версий")
            more.setObjectName("buildsStatus")
            self.versions_box.addWidget(more)
            self.versions_status.setText(f"Всего версий: {len(versions)}")
        else:
            self.versions_status.setText(f"Всего версий: {len(versions)}")


# ---------- page ----------

PROVIDERS = [
    ("Modrinth", "modrinth"),
    ("CurseForge", "curseforge"),
    ("GitHub (Custom)", "github"),
]


class BuildsPage(QWidget):
    """The "Сборки" section: provider swiper + catalog + detail screen."""

    def __init__(self, config=None, client=None, curseforge_client=None,
                 icon_loader=None, parent=None):
        super().__init__(parent)
        self.setObjectName("buildsPage")
        self.config = config
        self.client = client or ModrinthCatalogClient()
        self.curseforge_client = curseforge_client or CurseForgeCatalogClient()
        self._icon_loader = icon_loader or self._make_icon_loader(config)
        self._detail_thread: Optional[DetailThread] = None
        self._build()

    def _make_icon_loader(self, config) -> Optional[IconLoader]:
        """Covers need somewhere to cache; only enable it with a real install."""
        install_path = getattr(config, "install_path", "") if config else ""
        if not install_path:
            return None
        try:
            return IconLoader(Path(install_path) / "icons", self)
        except Exception:  # noqa: BLE001 - browsing works without covers
            return None

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.view_stack = QStackedWidget()

        # --- catalog screen ---
        catalog = QWidget()
        catalog_layout = QVBoxLayout(catalog)
        catalog_layout.setContentsMargins(0, 0, 0, 0)
        catalog_layout.setSpacing(18)
        catalog_layout.addLayout(self._build_topbar())

        self.provider_stack = QStackedWidget()
        self.modrinth = CatalogView(
            self.client, self._icon_loader,
            provider_key="modrinth", collapsible=False, show_environment=True,
        )
        self.modrinth.open_requested.connect(self._open_detail)
        self.modrinth.active_filters_changed.connect(self._sync_filters_button)
        self.provider_stack.addWidget(self.modrinth)

        self.curseforge = DiscoverCatalog(
            self.curseforge_client, self._icon_loader,
            profile_version=self._profile_version(),
        )
        self.curseforge.open_requested.connect(self._open_detail)
        self.curseforge.active_filters_changed.connect(self._sync_filters_button)
        self.provider_stack.addWidget(self.curseforge)

        self.provider_stack.addWidget(PlaceholderProvider(
            "GitHub (Custom Pack)",
            "Загрузка сборок из GitHub и из файла будет добавлена позже.",
            icon_name="cube",
        ))
        self._catalogs = [self.modrinth, self.curseforge, None]
        catalog_layout.addWidget(self.provider_stack, 1)

        self.catalog_view = catalog
        self.view_stack.addWidget(catalog)

        # --- detail screen ---
        self.detail_view = ModpackDetailView(self._icon_loader)
        self.detail_view.back_requested.connect(self._show_catalog)
        self.view_stack.addWidget(self.detail_view)

        self.view_stack.setCurrentIndex(0)
        root.addWidget(self.view_stack)

    def _profile_version(self) -> str:
        """Best-effort Minecraft version the user is on (empty when unknown)."""
        if self.config is None:
            return ""
        return str(getattr(self.config, "game_version", "") or "")

    def _build_topbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        self.switcher = ProviderSwitcher(PROVIDERS)
        self.switcher.provider_requested.connect(self._set_provider)
        self.swiper_buttons = self.switcher.buttons
        row.addWidget(self.switcher)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("buildsSearch")
        self.search_input.setFixedHeight(42)
        self.search_input.setMinimumWidth(260)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setPlaceholderText("Поиск сборки на Modrinth")
        self.search_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.search_input.addAction(
            make_icon("search", "#6c7086", 16),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.search_input.textChanged.connect(self._on_search_text)
        row.addWidget(self.search_input, 1)

        self.filters_button = FiltersButton()
        self.filters_button.clicked.connect(self._on_filters_button)
        self.filters_button.setVisible(False)
        row.addWidget(self.filters_button)

        return row

    def _on_search_text(self, text: str):
        catalog = self._current_catalog()
        if catalog is not None:
            catalog.set_query(text)
            self._sync_filters_button()

    def _on_filters_button(self):
        catalog = self._current_catalog()
        if catalog is None:
            return
        catalog.toggle_filters()
        self._sync_filters_button()

    def _sync_filters_button(self, *_args):
        catalog = self._current_catalog()
        collapsible = catalog is not None and getattr(
            catalog, "is_collapsible", False
        )
        if not collapsible:
            self.filters_button.setVisible(False)
            return
        self.filters_button.setVisible(True)
        self.filters_button.setProperty("provider", PROVIDERS[
            self.provider_stack.currentIndex()
        ][1])
        self.filters_button.set_checked(catalog.filters_visible())
        self.filters_button.set_count(catalog.active_filter_count())

    # ---------- navigation ----------

    def _current_catalog(self) -> Optional["CatalogView"]:
        index = self.provider_stack.currentIndex()
        if 0 <= index < len(self._catalogs):
            return self._catalogs[index]
        return None

    def _current_client(self):
        catalog = self._current_catalog()
        return catalog.client if catalog is not None else self.client

    def _set_provider(self, index: int):
        self.switcher.set_current(index)
        self.provider_stack.setCurrentIndex(index)

        catalog = self._current_catalog()
        self.search_input.setEnabled(catalog is not None)
        if catalog is None:
            self.search_input.setPlaceholderText("Поиск недоступен")
            self.filters_button.setVisible(False)
            return

        label = PROVIDERS[index][0] if 0 <= index < len(PROVIDERS) else ""
        self.search_input.setPlaceholderText(f"Поиск сборки на {label}")
        catalog.activate(self.search_input.text().strip())
        self._sync_filters_button()

    def _open_detail(self, hit: ModpackHit):
        self.detail_view.show_hit(hit)
        self.view_stack.setCurrentIndex(1)

        if self._detail_thread is not None and self._detail_thread.isRunning():
            self._detail_thread.terminate()
            self._detail_thread.wait(2000)

        # project_id works for both providers (CurseForge rejects slugs).
        self._detail_thread = DetailThread(
            self._current_client(), hit.project_id, self
        )
        self._detail_thread.ready.connect(self.detail_view.set_detail)
        self._detail_thread.failed.connect(self.detail_view.set_error)
        self._detail_thread.start()

    def _show_catalog(self):
        self.view_stack.setCurrentIndex(0)

    def ensure_loaded(self):
        """Load the catalog of the currently selected provider (once)."""
        catalog = self._current_catalog()
        if catalog is not None:
            catalog.load()

    def showEvent(self, event):
        super().showEvent(event)
        self.ensure_loaded()

    # ---------- lifecycle ----------

    def shutdown(self):
        if self._icon_loader is not None:
            self._icon_loader.shutdown()
        for catalog in (self.modrinth, self.curseforge):
            catalog.shutdown()
        if self._detail_thread is not None and self._detail_thread.isRunning():
            if not self._detail_thread.wait(2000):
                self._detail_thread.terminate()
                self._detail_thread.wait(2000)
        self._detail_thread = None
