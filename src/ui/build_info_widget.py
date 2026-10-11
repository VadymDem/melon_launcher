from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QFont, QColor, QPainter

from core import Manifest, IconManager, create_placeholder_icon


class BuildInfoWidget(QWidget):
    def __init__(self, icon_manager: IconManager = None):
        super().__init__()
        self.icon_manager = icon_manager or IconManager(Path.home() / ".melon_launcher" / "icons")
        self._icon_loaded = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Build cover / image placeholder
        self.cover_frame = QFrame()
        self.cover_frame.setFixedHeight(180)
        self.cover_frame.setStyleSheet("""
            QFrame {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 10px;
            }
        """)
        cover_layout = QVBoxLayout(self.cover_frame)
        cover_layout.setContentsMargins(0, 0, 0, 0)

        self.cover_label = QLabel()
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet("background: transparent;")
        cover_layout.addWidget(self.cover_label)

        layout.addWidget(self.cover_frame)

        # Build name and version
        info_layout = QHBoxLayout()
        info_layout.setSpacing(12)

        self.name_label = QLabel()
        self.name_label.setObjectName("titleLabel")
        self.name_label.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        info_layout.addWidget(self.name_label)

        self.version_label = QLabel()
        self.version_label.setObjectName("versionLabel")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        info_layout.addWidget(self.version_label, 1)

        layout.addLayout(info_layout)

        # Description
        self.desc_label = QLabel()
        self.desc_label.setObjectName("infoLabel")
        self.desc_label.setWordWrap(True)
        self.desc_label.setMinimumHeight(60)
        layout.addWidget(self.desc_label)

        # Details
        self.details_label = QLabel()
        self.details_label.setObjectName("infoLabel")
        self.details_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        layout.addWidget(self.details_label)

        self._show_placeholder()

    def _show_placeholder(self):
        self.name_label.setText("Выберите сборку")
        self.version_label.setText("")
        self.desc_label.setText("Выберите сборку из списка слева, чтобы увидеть подробную информацию.")
        self.details_label.setText("")
        self._set_cover_pixmap(create_placeholder_icon((400, 180), "MELON LAUNCHER"))

    def _set_cover_pixmap(self, pixmap: QPixmap):
        """Set cover pixmap with proper scaling."""
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(
                self.cover_frame.width(), self.cover_frame.height(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            self.cover_label.setPixmap(scaled)

    def update_build(self, build_name: str):
        # Placeholder data for different builds
        builds_data = {
            "Vanilla 1.20.4": {
                "version": "1.20.4",
                "desc": "Официальная версия Minecraft без модификаций. Чистый ванильный опыт с последними обновлениями.",
                "details": "Тип: Vanilla | Загрузчик: Нет | Модов: 0",
                "icon_url": "https://raw.githubusercontent.com/InventivetalentDev/minecraft-assets/1.20.4/assets/minecraft/icon.png"
            },
            "Fabric 1.20.4": {
                "version": "1.20.4-fabric-0.15.11",
                "desc": "Лёгкий и быстрый модлоадер Fabric с базовыми оптимизациями и API для модов.",
                "details": "Тип: Fabric | Загрузчик: Fabric Loader 0.15.11 | Модов: 0",
                "icon_url": "https://raw.githubusercontent.com/FabricMC/fabric-meta/main/favicon.png"
            },
            "Forge 1.20.4": {
                "version": "1.20.4-forge-49.0.0",
                "desc": "Популярный модлоадер Forge с поддержкой огромного количества модов и аддонов.",
                "details": "Тип: Forge | Загрузчик: Forge 49.0.0 | Модов: 0",
                "icon_url": "https://raw.githubusercontent.com/MinecraftForge/MinecraftForge/main/logo.png"
            },
            "Custom Build": {
                "version": "Custom",
                "desc": "Пользовательская сборка. Добавьте URL манифеста в настройках для загрузки кастомной сборки.",
                "details": "Тип: Custom | Источник: GitHub / Modrinth / CurseForge",
                "icon_url": ""
            }
        }

        data = builds_data.get(build_name, builds_data["Vanilla 1.20.4"])

        self.name_label.setText(build_name)
        self.version_label.setText(data["version"])
        self.desc_label.setText(data["desc"])
        self.details_label.setText(data["details"])

        # Load icon asynchronously
        self._load_icon_async(data.get("icon_url", ""), build_name)

    def _load_icon_async(self, url: str, build_name: str):
        """Load icon asynchronously using IconManager."""
        self._icon_loaded = False
        
        # Set placeholder first
        placeholder = create_placeholder_icon((400, 180), build_name.upper())
        self._set_cover_pixmap(placeholder)
        
        if not url:
            return
        
        # Use QTimer to allow UI to update first
        QTimer.singleShot(0, lambda: self._download_icon(url, build_name))

    def _download_icon(self, url: str, build_name: str):
        """Download icon in background."""
        # Check if we already have it cached
        local_path = self.icon_manager.get_icon_path(url)
        
        if local_path.exists():
            pixmap = self.icon_manager.load_icon(url, (400, 180))
            if pixmap:
                self._set_cover_pixmap(pixmap)
                return
        
        # Track active download threads
        if not hasattr(self, '_download_threads'):
            self._download_threads = []
        
        # Download with progress callback
        def on_downloaded(path_or_none):
            if path_or_none:
                pixmap = self.icon_manager.load_icon(url, (400, 180))
                if pixmap:
                    self._set_cover_pixmap(pixmap)
            # Clean up finished thread
            self._cleanup_download_threads()
        
        # Run download in thread
        from PyQt6.QtCore import QThread
        class DownloadThread(QThread):
            def __init__(self, manager, url, callback):
                super().__init__()
                self.setObjectName(f"BuildInfoDownloadThread-{url}")
                self.manager = manager
                self.url = url
                self.callback = callback
            
            def run(self):
                result = self.manager.download_icon(self.url)
                self.callback(result)
        
        thread = DownloadThread(self.icon_manager, url, on_downloaded)
        thread.finished.connect(thread.deleteLater)
        self._download_threads.append(thread)
        thread.start()

    def _cleanup_download_threads(self):
        """Remove finished download threads from tracking."""
        if hasattr(self, '_download_threads'):
            # Use a safer approach - check if thread object still exists
            alive_threads = []
            for t in self._download_threads:
                try:
                    if t.isRunning():
                        alive_threads.append(t)
                except RuntimeError:
                    # Thread object already deleted
                    pass
            self._download_threads = alive_threads

    def closeEvent(self, event):
        """Clean up download threads on widget close."""
        if hasattr(self, '_download_threads'):
            for thread in self._download_threads:
                try:
                    if thread.isRunning():
                        thread.terminate()
                        thread.wait(1000)
                except RuntimeError:
                    # Thread object already deleted
                    pass
        super().closeEvent(event)

    def update_build_from_manifest(self, manifest: Manifest):
        self.name_label.setText(manifest.name)
        self.version_label.setText(manifest.version)
        self.desc_label.setText(manifest.description or "Нет описания")
        loader_type = manifest.loader.type.capitalize()
        loader_version = manifest.loader.version
        file_count = len(manifest.files)
        total_mb = manifest.get_total_size() / (1024 * 1024)
        self.details_label.setText(
            f"Тип: {loader_type} | Загрузчик: {loader_version} | "
            f"Файлов: {file_count} | Размер: {total_mb:.1f} MB"
        )

        # Load icon from manifest
        self._load_icon_async(manifest.icon_url, manifest.name)

        # Generate fallback cover if no icon
        QTimer.singleShot(100, lambda: self._generate_manifest_cover(manifest) if not self._icon_loaded else None)

    def _generate_manifest_cover(self, manifest: Manifest):
        w, h = 400, 180
        pixmap = QPixmap(w, h)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        loader_colors = {
            "fabric": QColor("#a6e3a1"),
            "forge": QColor("#fab387"),
            "quilt": QColor("#f5c2e7"),
            "vanilla": QColor("#89b4fa"),
        }
        loader_type = manifest.loader.type.lower()
        accent_color = loader_colors.get(loader_type, QColor("#cba6f7"))

        base_color = QColor("#313244")
        painter.fillRect(0, 0, w, h, base_color)

        # Accent bar
        painter.fillRect(0, h - 4, w, 4, accent_color)

        # Loader badge
        painter.setPen(accent_color)
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.drawText(20, 30, loader_type.upper())

        # Name
        painter.setPen(QColor("#cdd6f4"))
        painter.setFont(QFont("Segoe UI", 28, QFont.Weight.Bold))
        painter.drawText(20, h - 50, w - 40, 40, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, manifest.name)

        # Version
        painter.setPen(QColor("#a6adc8"))
        painter.setFont(QFont("Segoe UI", 14))
        painter.drawText(20, h - 20, w - 40, 20, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         f"Minecraft {manifest.minecraft_version} | {manifest.version}")

        painter.end()

        self._set_cover_pixmap(pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'cover_label') and self.cover_label.pixmap():
            self._set_cover_pixmap(self.cover_label.pixmap())