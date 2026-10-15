from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QLabel, QPushButton, QFrame, QProgressBar,
    QSizePolicy, QMessageBox, QApplication, QTextEdit, QSplitter,
    QCheckBox, QLineEdit, QInputDialog, QStackedWidget
)
from PyQt6.QtCore import Qt, QSize, QTimer, QThread, pyqtSignal
from typing import Callable, List, Optional
from PyQt6.QtGui import QIcon, QPixmap, QFont, QTextCursor

from ui.settings_dialog import SettingsDialog
from ui.sidebar import Sidebar
from ui.home_page import HomePage
from ui.console_page import ConsolePage
from ui.placeholder_page import PlaceholderPage
from ui.versions_page import VersionsPage
from ui.builds_page import BuildsPage
from ui.profile_widget import ProfileWidget
from ui.build_info_widget import BuildInfoWidget  # noqa: F401  (kept for settings dialog)
from utils.config import Config
from core import (
    ManifestManager, FileChecker, DownloadWorker, Manifest,
    AuthManager, AuthProfile, OfflineAuthError,
    JavaManager, JavaInstallation, JVMConfigBuilder,
    LaunchManager, LaunchConfig, GameProcessHandler,
    parse_jvm_args, IconManager,
    get_builtin_manifest, get_builtin_profiles, is_builtin_profile,
    get_all_versions, get_versions_cached, get_official_releases,
    build_vanilla_manifest, get_required_java_version,
    get_install_stats, delete_installed_version, get_installed_size,
    get_installed_packs, get_pack, is_version_installed,
    ensure_instance_dir, get_instance_dir, remove_empty_instance, instance_exists
)
from pathlib import Path
from datetime import datetime
import os


SOURCE_JAVA = "Java-Edition"
SOURCE_CUSTOM = "Custom-Modpack (GitHub)"
SOURCE_CURSEFORGE = "CurseForge"
SOURCE_MODRINTH = "Modrinth"

PROFILE_CATEGORIES = [
    SOURCE_JAVA,
    SOURCE_CUSTOM,
    SOURCE_CURSEFORGE,
    SOURCE_MODRINTH,
]


class StatsThread(QThread):
    """Background thread that computes the install size of a version."""

    ready = pyqtSignal(str, int, int)  # version, file_count, size_bytes

    def __init__(self, version: str):
        super().__init__()
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


class InstallThread(QThread):
    """Background thread that installs an official Minecraft version."""

    progress_changed = pyqtSignal(int, int, str)  # value, maximum, status
    # Must be declared explicitly: otherwise self.finished resolves to the
    # built-in QThread.finished() and emitting two arguments raises TypeError.
    finished = pyqtSignal(bool, str)  # success, message

    # The library reports English status strings; map the common ones.
    STATUS_RU = {
        "Download Libraries": "Загрузка библиотек",
        "Download Assets": "Загрузка ресурсов",
        "Download client.jar": "Загрузка client.jar",
        "Download version json": "Загрузка информации о версии",
    }

    def __init__(self, version: str, minecraft_directory: Path):
        super().__init__()
        self.setObjectName(f"InstallThread-{version}")
        self.version = version
        self.minecraft_directory = minecraft_directory

    def run(self):
        import minecraft_launcher_lib.install as mcl_install

        # The library tracks item counts, not bytes.
        state = {"current": 0, "maximum": 0}

        def emit(status: str = ""):
            self.progress_changed.emit(state["current"], state["maximum"], status)

        def set_max(value):
            state["maximum"] = int(value)
            emit()

        def set_progress(value):
            state["current"] = int(value)
            emit()

        def set_status(message):
            message = str(message)
            emit(self.STATUS_RU.get(message, message))

        callback = {
            "setMax": set_max,
            "setProgress": set_progress,
            "setStatus": set_status,
        }

        try:
            mcl_install.install_minecraft_version(
                self.version, str(self.minecraft_directory), callback
            )
            self.finished.emit(True, f"Minecraft {self.version} установлен")
        except Exception as e:
            self.finished.emit(False, f"Ошибка установки: {e}")


class DeleteThread(QThread):
    """Removes an installed version folder from disk."""

    finished = pyqtSignal(str, bool, str)  # version, success, message

    def __init__(self, version: str, minecraft_directory: Path):
        super().__init__()
        self.setObjectName(f"DeleteThread-{version}")
        self.version = version
        self.minecraft_directory = minecraft_directory

    def run(self):
        try:
            freed = delete_installed_version(self.minecraft_directory, self.version)
            self.finished.emit(self.version, True, str(freed))
        except Exception as e:
            self.finished.emit(self.version, False, str(e))


class LaunchThread(QThread):
    """Background thread for game launch sequence."""
    
    progress_changed = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(
        self,
        launch_manager: LaunchManager,
        process_handler: GameProcessHandler,
        manifest: Manifest,
        auth_profile: AuthProfile,
        game_directory: Path,
        java_version: int,
        jvm_args: List[str],
        custom_args: List[str],
        on_progress: Callable[[int, str], None],
        on_finished: Callable[[bool, str], None],
        minecraft_directory: Path = None
    ):
        super().__init__()
        self.setObjectName(f"LaunchThread-{manifest.minecraft_version}")
        self.launch_manager = launch_manager
        self.process_handler = process_handler
        self.manifest = manifest
        self.auth_profile = auth_profile
        self.game_directory = game_directory
        self.minecraft_directory = minecraft_directory or game_directory
        self.java_version = java_version
        self.jvm_args = jvm_args
        self.custom_args = custom_args
        self.on_progress = on_progress
        self.on_finished = on_finished
        self._cancelled = False

    def cancel(self):
        """Ask the thread to stop at the next checkpoint."""
        self._cancelled = True

    def _cancelled_check(self):
        if self._cancelled:
            raise RuntimeError("Запуск отменён пользователем")

    def _on_java_progress(self, current: int, total: int):
        """
        Forward the Java download progress to the GUI.

        The Java step owns the 5-20 % band of the launch progress bar so the
        window visibly reacts instead of appearing to hang.
        """
        if total > 0:
            percent = int((current / total) * 100)
            stage = 12 + percent * 8 // 100
            self.progress_changed.emit(
                stage,
                f"Загрузка Java {self.java_version}: {percent}%"
                f" ({current // (1024 * 1024)} из {total // (1024 * 1024)} МБ)",
            )
        else:
            self.progress_changed.emit(
                12, f"Загрузка Java {self.java_version}..."
            )

    def run(self):
        try:
            self.progress_changed.emit(0, "Проверка требований...")

            # 1. Ensure Java - runtimes are shared by every instance, so they
            #    live in the install root and not inside the instance folder.
            #    ensure_java() may download ~100 MB, so its progress has to be
            #    forwarded; otherwise the UI looks frozen for minutes.
            self.progress_changed.emit(
                5, f"Проверка Java {self.java_version}..."
            )

            java_install = JavaManager(
                self.minecraft_directory
            ).ensure_java(self.java_version, progress_callback=self._on_java_progress)

            if not java_install.is_valid:
                self.finished.emit(
                    False,
                    f"Java {self.java_version} недоступна: {java_install.error}"
                )
                return
            
            # 2. Check game files
            self._cancelled_check()
            self.progress_changed.emit(20, "Проверка файлов игры...")
            # (File check/download handled by previous stage)

            # 3. Build launch config
            self._cancelled_check()
            self.progress_changed.emit(40, "Подготовка команды запуска...")
            launch_config = LaunchConfig(
                manifest=self.manifest,
                java_installation=java_install,
                auth_profile=self.auth_profile,
                game_directory=self.game_directory,
                jvm_args=self.jvm_args,
                custom_args=self.custom_args,
                minecraft_directory=self.minecraft_directory
            )
            
            # Validate
            valid, error = self.launch_manager.validate_launch_requirements(launch_config)
            if not valid:
                self.finished.emit(False, f"Проверка запуска не пройдена: {error}")
                return
            
            # 4. Build command
            self._cancelled_check()
            self.progress_changed.emit(60, "Сборка команды запуска...")
            if self.auth_profile and self.auth_profile.auth_type == "offline":
                command = self.launch_manager.build_offline_command(launch_config)
            else:
                command = self.launch_manager.build_command(launch_config)
            
            self.progress_changed.emit(80, "Запуск процесса игры...")
            
            # 5. Start process
            success = self.process_handler.start(command, cwd=self.game_directory)
            
            if success:
                self.progress_changed.emit(100, "Игра запущена")
                self.finished.emit(True, "")
            else:
                self.finished.emit(False, "Не удалось запустить процесс игры")
                
        except Exception as e:
            self.finished.emit(False, f"Ошибка запуска: {e}")


class MainWindow(QMainWindow):
    # Signal for thread-safe auth completion
    auth_completed = pyqtSignal(bool, str, object)  # success, message, profile

    # Game process events - emitted from the background monitor thread and
    # delivered to the GUI thread as queued connections.
    game_output = pyqtSignal(str)
    game_started = pyqtSignal(int)
    game_exited = pyqtSignal(int)
    game_crashed = pyqtSignal(int, str)

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.setWindowTitle("Melon Launcher")
        self.setMinimumSize(1000, 650)
        self.resize(1320, 760)

        # Initialize IconManager
        self.icon_manager = IconManager(Path(config.install_path) / "icons")

        # Initialize AuthManager with real Microsoft client_id
        auth_config_path = Path(config.install_path) / "auth.json"
        self.auth_manager = AuthManager(
            config_path=auth_config_path,
            client_id=config.microsoft_client_id,
            redirect_uri="http://localhost:8080/callback",
            on_login_url=self._on_login_url,
            on_auth_complete=self._on_auth_complete_async
        )
        
        # Connect thread-safe auth completion signal
        self.auth_completed.connect(self._on_auth_completed)

        # Game events must run on the GUI thread
        self.game_output.connect(self._append_log)
        self.game_started.connect(self._on_game_started)
        self.game_exited.connect(self._on_game_exit)
        self.game_crashed.connect(self._on_game_crash)

        # Initialize JavaManager
        self.java_manager = JavaManager(Path(config.install_path))

        self.manifest_manager = ManifestManager()
        self.current_manifest: Manifest | None = None
        self.download_worker: DownloadWorker | None = None
        self.install_thread: InstallThread | None = None
        self.delete_thread: DeleteThread | None = None
        self._stats_thread: StatsThread | None = None
        self._launch_thread: LaunchThread | None = None

        self._packs: List = []

        self._setup_ui()
        self._apply_styles()
        self._update_profile_widget()
        self._refresh_home_page()
        self._refresh_packs()
        self._update_last_launch_hero()
        self._refresh_recent_items()
        QTimer.singleShot(0, self._load_official_versions)

    def _refresh_recent_items(self):
        """Fill the 'Недавно' row from the installed packs."""
        packs = get_installed_packs(self.config.install_path)

        items = [
            ("cube", pack.display_name, f"{pack.loader} · {pack.size_mb:.0f} МБ")
            for pack in packs[:3]
        ]
        self.home_page.set_recent_items(items)

    def _refresh_home_page(self):
        """Sync account card, RAM and hero with the current state."""
        profile = self.auth_manager.get_profile()
        username = profile.username if profile else (self.config.username or "MelonBiba")
        status = "Офлайн режим" if (profile and profile.auth_type == "offline") else \
                 ("Microsoft" if profile else "Не вошли в систему")

        initials = "".join(part[0] for part in username.split()[:2]).upper() or "ME"
        self.sidebar.set_account(username, status, initials)
        self.sidebar.set_login_text(
            "Выйти" if profile and profile.auth_type == "microsoft" else "Войти (Microsoft)"
        )

        if profile:
            self.page_subtitle.setText(f"С возвращением, {profile.username}")
        else:
            self.page_subtitle.setText("С возвращением")

    def _update_java_badge(self):
        required = getattr(self.current_manifest, "java_version", 21) if self.current_manifest else 21
        install = self.java_manager.check_java_installed(required)
        if install and install.is_valid:
            self.java_badge.setText(f"Java {required} найдена")
        else:
            self.java_badge.setText(f"Java {required} не найдена")

    def _setup_ui(self):
        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # --- Left sidebar ---
        self.sidebar = Sidebar()
        self.sidebar.page_requested.connect(self._on_page_requested)
        self.sidebar.settings_requested.connect(self._open_settings)
        self.sidebar.login_button.clicked.connect(self._on_account_button)
        root_layout.addWidget(self.sidebar)

        # --- Right content area ---
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 28, 32, 24)
        content_layout.setSpacing(22)

        content_layout.addLayout(self._create_header())

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p% - %v/%m файлов")
        content_layout.addWidget(self.progress_bar)

        # Lets the user abort a launch that is stuck (e.g. downloading Java).
        self.cancel_button = QPushButton("Отменить запуск")
        self.cancel_button.setObjectName("dangerButton")
        self.cancel_button.setFixedHeight(32)
        self.cancel_button.setVisible(False)
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(self._on_cancel_launch)
        content_layout.addWidget(self.cancel_button, 0, Qt.AlignmentFlag.AlignRight)

        self.status_label = QLabel("")
        self.status_label.setObjectName("infoLabel")
        self.status_label.setVisible(False)
        self.status_label.setWordWrap(True)
        content_layout.addWidget(self.status_label)

        # Page stack
        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")
        content_layout.addWidget(self.stack, 1)

        self.home_page = HomePage()
        self.home_page.play_requested.connect(self._on_play_clicked)
        self.home_page.version_changed.connect(self._on_home_pack_changed)
        self.home_page.browse_versions_requested.connect(self._go_to_versions_page)
        self.stack.addWidget(self.home_page)

        self.versions_page = VersionsPage(self.config)
        self.versions_page.load_requested.connect(self._on_version_load_requested)
        self.versions_page.play_requested.connect(self._on_version_play_requested)
        self.versions_page.delete_requested.connect(self._on_version_delete_requested)
        self.versions_page.launch_options_requested.connect(self._open_settings)
        self.versions_page.open_folder_requested.connect(self._open_instance_folder)
        self.versions_page.refresh_requested.connect(self._on_refresh_versions)
        self.stack.addWidget(self.versions_page)

        self.builds_page = BuildsPage(self.config)
        self.stack.addWidget(self.builds_page)
        self.stack.addWidget(PlaceholderPage("Миры", "worlds"))
        self.stack.addWidget(PlaceholderPage("Серверы", "servers"))

        self.console_page = ConsolePage()
        self.console_page.clear_requested.connect(self._clear_log)
        self.stack.addWidget(self.console_page)

        root_layout.addWidget(content, 1)

        # Log console lives inside its own page now
        self._setup_log_console()
        self.console_page.set_console_widget(self.log_console_widget)
        self.console_page.set_empty(True)
        # Header is hidden while the console page is open
        self.page_title.setVisible(True)
        self.page_subtitle.setVisible(True)

        # Keep legacy widgets referenced by existing logic
        self.play_button = self.home_page.play_button
        self.profile_combo = self.home_page.version_combo
        self.profile_widget = ProfileWidget(self.config, self.auth_manager)
        # The profile widget changes auth state on its own (offline login,
        # logout, mode switch); keep the sidebar card in sync.
        self.profile_widget.auth_changed.connect(self._on_auth_changed)
        self.profile_widget.microsoft_login_requested.connect(self._start_microsoft_login)
        self.main_splitter = QSplitter(Qt.Orientation.Vertical)

    def _create_header(self):
        header = QHBoxLayout()
        header.setSpacing(16)

        titles = QVBoxLayout()
        titles.setSpacing(2)

        self.page_title = QLabel("Главная")
        self.page_title.setObjectName("pageTitle")
        titles.addWidget(self.page_title)

        self.page_subtitle = QLabel("С возвращением")
        self.page_subtitle.setObjectName("pageSubtitle")
        titles.addWidget(self.page_subtitle)

        header.addLayout(titles)
        header.addStretch()

        # Java status badge
        badge = QFrame()
        badge.setObjectName("javaBadge")
        badge_layout = QHBoxLayout(badge)
        badge_layout.setContentsMargins(16, 8, 16, 8)
        badge_layout.setSpacing(8)

        dot = QLabel("●")
        dot.setStyleSheet("color: #a6e3a1; font-size: 12px;")
        badge_layout.addWidget(dot)

        self.java_badge = QLabel("Java 21 найдена")
        self.java_badge.setObjectName("javaBadgeText")
        badge_layout.addWidget(self.java_badge)

        header.addWidget(badge)
        return header

    def _on_page_requested(self, key: str):
        pages = {
            "home": 0, "versions": 1, "builds": 2,
            "worlds": 3, "servers": 4, "console": 5,
        }
        titles = {
            "home": ("Главная", "С возвращением"),
            "versions": ("Версии", "Официальные версии Minecraft"),
            "builds": ("Сборки", "Модпаки и сборки"),
            "worlds": ("Миры", "Ваши миры"),
            "servers": ("Серверы", "Список серверов"),
            "console": ("Консоль", "Вывод игры и лаунчера"),
        }
        index = pages.get(key, 0)
        self.stack.setCurrentIndex(index)
        title, subtitle = titles.get(key, ("", ""))
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)

        # The console fills the page, so hide the shared header widgets
        is_console = (key == "console")
        self.page_title.setVisible(not is_console)
        self.page_subtitle.setVisible(not is_console)

    def _on_account_button(self):
        if self.profile_widget is None:
            return
        self.profile_widget._on_auth_clicked()

    def _on_refresh_versions(self):
        """Refetch the version list from Mojang and rewrite the cache."""
        button = self.versions_page.refresh_button
        button.setEnabled(False)
        button.setText("Обновление...")

        def restore():
            button.setEnabled(True)
            button.setText("Обновить")

        def do_refresh():
            self._load_official_versions(True)
            restore()

        # Deferred so the button state is painted before the fetch starts.
        QTimer.singleShot(0, do_refresh)

    def _open_instance_folder(self, pack_id: str):
        """Open the per-instance game folder of a pack in the file manager."""
        if not pack_id:
            return

        try:
            instance = ensure_instance_dir(Path(self.config.install_path), pack_id)
        except ValueError as e:
            QMessageBox.warning(self, "Ошибка", str(e))
            return

        try:
            os.startfile(str(instance))
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось открыть папку: {e}")

    def _setup_log_console(self):
        """Create the log console widget (hosted by the Console page)."""
        self.log_console_widget = QWidget()
        log_layout = QVBoxLayout(self.log_console_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(8)

        self.log_auto_scroll = QCheckBox("Автопрокрутка")
        self.log_auto_scroll.setObjectName("consoleAutoScroll")
        self.log_auto_scroll.setChecked(True)
        self.log_auto_scroll.setVisible(False)  # kept for _append_log compatibility
        log_layout.addWidget(self.log_auto_scroll)

        # Log text area
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setFont(QFont("Consolas", 9))
        self.log_console.setStyleSheet("""
            QTextEdit {
                background-color: #181825;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        log_layout.addWidget(self.log_console, 1)

    def _clear_log(self):
        """Clear the log console."""
        self.log_console.clear()
        self.console_page.set_empty(True)

    def _append_log(self, message: str):
        """Append a message to the log console (must run on the GUI thread)."""
        # Guard: if a background thread calls this directly, re-dispatch it
        # through the signal so Qt delivers it on the GUI thread.
        if QThread.currentThread() is not self.thread():
            self.game_output.emit(message)
            return

        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        
        # Color code based on content
        if "[ERR]" in message:
            color = "#f38ba8"
        elif "[OUT]" in message:
            color = "#a6e3a1"
        else:
            color = "#cdd6f4"
        
        # Use HTML for colors
        self.log_console.append(f'<span style="color: {color};">{formatted}</span>')

        if self.log_console.document().characterCount() > 1:
            self.console_page.set_empty(False)

        # Auto scroll
        if self.console_page.auto_scroll.isChecked():
            scrollbar = self.log_console.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _apply_styles(self):
        from pathlib import Path
        qss_path = Path(__file__).parent.parent / "assets" / "style.qss"
        if qss_path.exists():
            with open(qss_path, "r", encoding="utf-8") as f:
                qss = f.read()
            # url(assets/...) in the QSS is resolved against the current working
            # directory; make it absolute so icons work wherever the app is started.
            qss = qss.replace("url(assets/", f"url({qss_path.parent.as_posix()}/")
            self.setStyleSheet(qss)

    def _load_official_versions(self, force_refresh: bool = False):
        """
        Provide the official version list for the "Версии" page.

        The list is served from the on-disk cache, so the page opens instantly.
        Passing force_refresh (the "Обновить" button) goes back to Mojang and
        rewrites the cache.
        """
        try:
            versions = get_versions_cached(self.config.install_path, force_refresh)
        except Exception as e:
            self.status_label.setText(f"Ошибка загрузки списка версий: {e}")
            self.status_label.setVisible(True)
            self._refresh_packs()
            return

        if hasattr(self, "versions_page"):
            self.versions_page.set_versions(versions)

        if force_refresh:
            self.status_label.setText(f"Список версий обновлён: {len(versions)}")
            self.status_label.setVisible(True)

        self._refresh_packs()

    def _refresh_packs(self):
        """
        Fill the home quick selection with the installed packs.

        Also restores the previously selected pack when it is still installed.
        """
        packs = get_installed_packs(self.config.install_path)
        self._packs = packs

        self.home_page.set_packs(packs)

        if not packs:
            self.current_manifest = None
            self.home_page.set_play_enabled(False)
            self.home_page.set_summary(
                "Официальные версии устанавливаются во вкладке «Версии»"
            )
            self._update_last_launch_hero()
            return

        index = 0
        wanted = self.config.last_pack
        for position, pack in enumerate(packs):
            if pack.id == wanted:
                index = position
                break

        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentIndex(index)
        self.profile_combo.blockSignals(False)

        self.home_page.set_play_enabled(True)
        self._select_pack(packs[index].id)

    def _on_home_pack_changed(self, display_name: str):
        """The quick selection combo shows "Minecraft <id>" labels."""
        if not display_name:
            return

        pack_id = display_name.replace("Minecraft ", "", 1)
        self._select_pack(pack_id)

    def _select_pack(self, pack_id: str):
        """Select a pack by id and refresh everything that depends on it."""
        if not pack_id:
            return

        self.config.last_pack = pack_id
        self.config.last_profile = pack_id
        self.config.save()

        self.current_manifest = build_vanilla_manifest(pack_id)
        self._update_home_hero()
        self._update_play_button(pack_id)
        self._update_java_badge()

    def _go_to_versions_page(self):
        self.sidebar.set_active("versions")
        self._on_page_requested("versions")

    def _update_home_hero(self):
        """
        Hero card + quick selection summary for the selected pack.

        The pack is already installed at this point, so its file count and size
        are read from disk instead of the (empty) manifest file list.
        """
        pack = self._selected_pack()
        if not pack:
            return

        profile = self.auth_manager.get_profile()
        auth_label = "Offline" if (profile and profile.auth_type == "offline") else "Microsoft"

        played = self._format_last_played(self.config.last_pack_time)

        self.home_page.set_hero(
            title=pack.display_name,
            description=(
                f"Готова к запуску · {pack.size_mb:.1f} МБ"
                + (f" · {played}" if played else "")
            ),
            loader=pack.loader,
            java=f"Java {pack.java_version}",
            auth=auth_label,
        )
        self.home_page.set_hero_tags_visible(True)

        self.home_page.set_summary(
            f"Тип: {pack.loader} · Размер: {pack.size_mb:.1f} МБ"
        )

    def _update_last_launch_hero(self):
        """
        Hero card content for the "Последний запуск" section.

        Shows the pack launched last; when nothing was ever played the card
        falls back to a friendly invitation instead of stale data.
        """
        pack = get_pack(self.config.install_path, self.config.last_pack) \
            if self.config.last_pack else None

        if not pack:
            self.home_page.set_hero(
                title="Melon Launcher",
                description="Вы давно не заходили в свой мир, сыграем?",
                loader="Vanilla",
                java="",
                auth="",
            )
            self.home_page.set_hero_tags_visible(False)
            return

        played = self._format_last_played(self.config.last_pack_time)
        profile = self.auth_manager.get_profile()
        auth_label = "Offline" if (profile and profile.auth_type == "offline") else "Microsoft"

        self.home_page.set_hero(
            title=pack.display_name,
            description=(
                f"Последний запуск{': ' + played if played else ''} · "
                f"Java {pack.java_version} · {pack.size_mb:.1f} МБ"
            ),
            loader=pack.loader,
            java=f"Java {pack.java_version}",
            auth=auth_label,
        )
        self.home_page.set_hero_tags_visible(True)

    def _selected_pack(self):
        """The pack currently chosen in the quick selection combo."""
        return get_pack(self.config.install_path, self.config.last_pack) \
            if self.config.last_pack else None

    @staticmethod
    def _format_last_played(raw: str) -> str:
        """Human readable "when was this played last" text."""
        if not raw:
            return ""

        try:
            moment = datetime.fromisoformat(raw)
        except ValueError:
            return ""

        delta = datetime.now() - moment.replace(tzinfo=None)
        seconds = delta.total_seconds()

        if seconds < 60:
            return "только что"
        if seconds < 3600:
            return f"{int(seconds // 60)} мин назад"
        if seconds < 86400:
            return f"{int(seconds // 3600)} ч назад"
        if seconds < 86400 * 7:
            return f"{int(seconds // 86400)} дн назад"
        return moment.strftime("%d.%m.%Y")

    def _request_install_stats(self, version: str):
        """Fetch file count / size for an official version in the background."""
        if getattr(self, "_stats_thread", None) is not None:
            if self._stats_thread.isRunning():
                return
        self._stats_thread = StatsThread(version)
        self._stats_thread.ready.connect(self._on_install_stats)
        self._stats_thread.start()

    def _on_install_stats(self, version: str, files: int, size_bytes: int):
        """Show the real file count and size once Mojang answered."""
        manifest = self.current_manifest
        if not manifest or manifest.minecraft_version != version:
            return

        size_mb = size_bytes / (1024 * 1024)
        loader = manifest.loader.type.capitalize() if manifest.loader.type else "Vanilla"
        self.home_page.set_summary(
            f"Тип: {loader} · Файлов: {files:,} · Размер: {size_mb:.0f} МБ"
        )

    def _update_play_button(self, pack_id: str):
        """
        The home page only launches packs that are already installed -
        downloading an official version happens in the "Версии" page.
        """
        if not pack_id or not self._is_official_installed(pack_id):
            self.play_button.setText("Нет сборок")
            self.play_button.setEnabled(False)
            self.home_page.set_play_enabled(False)
            return

        self.home_page.set_play_enabled(True)
        self.play_button.setText("Играть")
        self.play_button.setEnabled(True)

    def _is_official_installed(self, mc_version: str) -> bool:
        """Check whether an official Minecraft version is already installed."""
        return is_version_installed(self.config.install_path, mc_version)

    def _on_play_clicked(self):
        pack_id = self.config.last_pack
        if not pack_id or not self._is_official_installed(pack_id):
            self._offer_versions_page()
            return
        self._launch_game()

    def _offer_versions_page(self):
        """No pack installed - send the user to the versions page."""
        answer = QMessageBox.question(
            self, "Нет установленных сборок",
            "Пока нет установленных сборок.\n"
            "Официальные версии устанавливаются во вкладке «Версии».\n\n"
            "Перейти во вкладку «Версии»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.sidebar.set_active("versions")
            self._on_page_requested("versions")

    def _start_official_install(self, version: str):
        """Download and install an official Minecraft version."""
        self.play_button.setEnabled(False)
        self.play_button.setText("Загрузка...")
        self._show_progress(0, f"Подготовка загрузки {version}...")

        self.install_thread = InstallThread(
            version=version,
            minecraft_directory=Path(self.config.install_path)
        )
        self.install_thread.progress_changed.connect(self._on_install_progress)
        self.install_thread.finished.connect(self._on_install_finished)
        self.install_thread.start()

    def _on_install_progress(self, value: int, maximum: int, status: str):
        self.progress_bar.setVisible(True)
        if maximum > 0:
            self.progress_bar.setMaximum(maximum)
        if value >= 0:
            self.progress_bar.setValue(value)
        if status:
            self.status_label.setText(status)
            self.status_label.setVisible(True)

    def _on_install_finished(self, success: bool, message: str):
        self.install_thread = None
        self._hide_progress()

        if success:
            self._refresh_packs()
            self._refresh_recent_items()
            self._update_play_button(self.config.last_pack)
            self.versions_page.refresh_installed_states()
            QMessageBox.information(self, "Успех", message)
        else:
            self.play_button.setEnabled(True)
            self.play_button.setText("Повторить загрузку")
            QMessageBox.critical(self, "Ошибка загрузки", message)

    def _on_version_load_requested(self, version_id: str):
        """Install an official version selected from the versions page."""
        if self._is_official_installed(version_id):
            QMessageBox.information(
                self, "Установка",
                f"Версия {version_id} уже установлена."
            )
            return
        self._start_official_install(version_id)

    def _on_version_play_requested(self, version_id: str):
        """Play an official version selected from the versions page."""
        if not self._is_official_installed(version_id):
            QMessageBox.warning(self, "Ошибка", f"Версия {version_id} не установлена.")
            return

        # Make it the pack the home page works with, then launch it.
        index = self.profile_combo.findText(f"Minecraft {version_id}")
        if index >= 0:
            self.profile_combo.blockSignals(True)
            self.profile_combo.setCurrentIndex(index)
            self.profile_combo.blockSignals(False)

        self._select_pack(version_id)
        self._launch_game()

    def _on_version_delete_requested(self, version_id: str):
        """Ask for confirmation, then delete an installed version."""
        if not self._is_official_installed(version_id):
            return

        freed_mb = get_installed_size(
            Path(self.config.install_path), version_id
        ) / (1024 * 1024)

        if self._is_game_running():
            QMessageBox.warning(
                self, "Удаление версии",
                "Сначала закройте игру, затем удалите версию."
            )
            return

        answer = QMessageBox.question(
            self,
            "Удалить версию",
            f"Удалить Minecraft {version_id}?\n\n"
            f"Будет освобождено {freed_mb:.1f} МБ.\n"
            f"Миры, настройки и общие библиотеки останутся.\n\n"
            f"Версию можно скачать заново.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.delete_thread = DeleteThread(
            version_id, Path(self.config.install_path)
        )
        self.delete_thread.finished.connect(self._on_version_delete_finished)
        self.delete_thread.start()

    def _on_version_delete_finished(self, version_id: str, success: bool, info: str):
        self.delete_thread = None

        if not success:
            QMessageBox.critical(self, "Ошибка удаления", info)
            return

        # A deleted version must not stay selected or remembered as "last launch".
        if self.config.last_pack == version_id:
            self.config.last_pack = ""
            self.config.last_profile = ""
            self.config.save()

        self.versions_page.refresh_installed_states()
        self._refresh_packs()
        self._refresh_recent_items()

        freed_mb = int(info) / (1024 * 1024)
        message = f"Версия {version_id} удалена, освобождено {freed_mb:.1f} МБ"

        # The instance folder is only dropped when the player never used it.
        try:
            if remove_empty_instance(Path(self.config.install_path), version_id):
                message += ". Папка сборки удалена"
            elif instance_exists(Path(self.config.install_path), version_id):
                message += f". Миры и настройки сохранены в папке сборки {version_id}"
        except ValueError:
            pass

        self.status_label.setText(message)
        self.status_label.setVisible(True)

    def _is_game_running(self) -> bool:
        handler = getattr(self, "_process_handler", None)
        if handler is None:
            return False
        try:
            return bool(handler.is_running())
        except Exception:
            return False

    def _start_download(self):
        """Download files of a custom modpack manifest (used by builds)."""
        if not self.current_manifest:
            return

        self.play_button.setEnabled(False)
        self.play_button.setText("Загрузка...")
        self._show_progress(0, "Подготовка загрузки...")

        self.download_worker = DownloadWorker(
            manifest=self.current_manifest,
            base_path=Path(self.config.install_path),
            base_url=self.config.manifest_url.rsplit("/", 1)[0] if self.config.manifest_url else ""
        )

        self.download_worker.progress_changed.connect(self._on_download_progress)
        self.download_worker.status_changed.connect(self._on_download_status)
        self.download_worker.download_finished.connect(self._on_download_finished)
        self.download_worker.error_occurred.connect(self._on_download_error)

        self.download_worker.start()

    def _on_download_progress(self, value: int):
        self.progress_bar.setValue(value)

    def _on_download_status(self, message: str):
        self.status_label.setText(message)
        self.status_label.setVisible(True)

    def _on_download_finished(self, success: bool, message: str):
        self.download_worker = None
        self._hide_progress()

        if success:
            self._refresh_packs()
            QMessageBox.information(self, "Успех", message)
        else:
            self.play_button.setEnabled(True)
            self.play_button.setText("Повторить загрузку")
            QMessageBox.critical(self, "Ошибка", message)

    def _on_download_error(self, error: str):
        self._hide_progress()
        self.play_button.setEnabled(True)
        self.play_button.setText("Повторить загрузку")
        QMessageBox.critical(self, "Ошибка загрузки", error)

    def _show_progress(self, value: int, status: str):
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(value)
        self.status_label.setText(status)
        self.status_label.setVisible(True)
        # The cancel button belongs to the launch flow only.
        self.cancel_button.setVisible(self._launch_thread is not None)

    def _hide_progress(self):
        self.progress_bar.setVisible(False)
        self.status_label.setVisible(False)
        self.cancel_button.setVisible(False)

    def _on_cancel_launch(self):
        """Abort a launch that is stuck (typically a silent Java download)."""
        thread = getattr(self, "_launch_thread", None)
        if thread is None or not thread.isRunning():
            return

        thread.cancel()
        self.cancel_button.setEnabled(False)
        self._append_log("[LAUNCH] Отмена запуска...")
        self._show_progress(0, "Отмена запуска...")

    def _offer_offline_login(self) -> Optional[AuthProfile]:
        """
        Offer offline play when the user is not signed in.
        Returns an offline AuthProfile, or None if the user cancelled.
        """
        answer = QMessageBox.question(
            self,
            "Авторизация",
            "Вы не вошли в аккаунт Microsoft.\n\n"
            "Запустить в оффлайн-режиме? Работают одиночная игра и локальные миры.\n"
            "Realms и онлайн-серверы будут недоступны.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )

        if answer != QMessageBox.StandardButton.Yes:
            return None

        default = self.config.username or "Player"
        username, ok = QInputDialog.getText(
            self, "Оффлайн-режим", "Введите игровое имя:",
            QLineEdit.EchoMode.Normal, default
        )
        if not ok or not username.strip():
            return None

        try:
            profile = self.auth_manager.login_offline(username.strip())
        except OfflineAuthError as e:
            QMessageBox.critical(self, "Ошибка", str(e))
            return None

        self.config.username = profile.username
        self.config.auth_type = "offline"
        self.config.save()
        self._update_profile_widget()
        self._append_log(f"[AUTH] Оффлайн-вход как {profile.username}")
        return profile

    def _launch_game(self):
        """Full game launch implementation using LaunchManager and GameProcessHandler."""
        if not self.current_manifest:
            QMessageBox.warning(self, "Ошибка", "Сборка не выбрана")
            return

        profile = self.auth_manager.get_profile()
        if not profile:
            profile = self._offer_offline_login()
            if not profile:
                return

        # Determine required Java version from manifest
        required_java = getattr(self.current_manifest, 'java_version', 17)
        
        # Get JVM args from config
        jvm_args = parse_jvm_args(self.config.custom_jvm_args) if self.config.custom_jvm_args else []
        
        # Add RAM settings from config
        builder = JVMConfigBuilder.from_config(self.config)
        jvm_args.extend(builder.build_jvm_args())

        # Each pack plays in its own folder so worlds and mods never mix.
        pack_id = self.current_manifest.minecraft_version
        loader = (self.current_manifest.loader.type or "vanilla").lower()
        is_modded = loader not in ("vanilla", "")
        install_root = Path(self.config.install_path)
        try:
            instance_dir = ensure_instance_dir(install_root, pack_id, modded=is_modded)
        except ValueError as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать папку сборки: {e}")
            return
        
        # Switch to the console tab so the user sees the launch output
        self.sidebar.set_active("console")
        self._on_page_requested("console")
        self._clear_log()
        self._append_log("=== Начало запуска ===")
        self._append_log(f"Сборка: {self.current_manifest.name} {self.current_manifest.version}")
        self._append_log(f"Java версия: {required_java}")
        self._append_log(f"Память: {self.config.ram_mb} MB")
        self._append_log(f"Папка игры: {instance_dir}")
        self._append_log(f"Авторизация: {profile.username} ({profile.auth_type})")

        # Disable play button during launch
        self.play_button.setEnabled(False)
        self.play_button.setText("Запуск...")
        self.cancel_button.setEnabled(True)
        self.cancel_button.setVisible(True)

        # Create launch manager
        self._launch_manager = LaunchManager()
        self._process_handler = GameProcessHandler(
            # Emitting signals is thread-safe; the slots run on the GUI thread.
            on_output=self.game_output.emit,
            on_crash=self.game_crashed.emit,
            on_exit=self.game_exited.emit,
            on_started=self.game_started.emit,
            log_file=instance_dir / "logs" / "latest.log"
        )

        # Start launch sequence in a thread to avoid blocking UI
        self._launch_thread = LaunchThread(
            launch_manager=self._launch_manager,
            process_handler=self._process_handler,
            manifest=self.current_manifest,
            auth_profile=profile,
            game_directory=instance_dir,
            minecraft_directory=install_root,
            java_version=required_java,
            jvm_args=jvm_args,
            custom_args=[],
            on_progress=self._on_launch_progress,
            on_finished=self._on_launch_finished
        )
        # The thread reports through signals, not through the callbacks above,
        # so they must be connected - otherwise the window gets no feedback at
        # all and looks frozen while Java is downloading.
        self._launch_thread.progress_changed.connect(self._on_launch_progress)
        self._launch_thread.finished.connect(self._on_launch_finished)
        self._launch_thread.start()

    def _on_launch_progress(self, progress: int, message: str):
        """Handle launch progress updates."""
        self._show_progress(progress, message)
        self._append_log(message)

    def _on_launch_finished(self, success: bool, error: str = ""):
        """Handle launch completion."""
        self._hide_progress()
        self.play_button.setEnabled(True)
        self.play_button.setText("Играть")
        
        if success:
            self._append_log("=== Игра запущена успешно ===")
            # Minimize launcher window
            self.showMinimized()
        else:
            self._append_log(f"=== Ошибка запуска: {error} ===")
            QMessageBox.critical(self, "Ошибка запуска", error)

    def _on_game_started(self, pid: int):
        """Handle game process started."""
        self._append_log(f"Процесс игры запущен (PID: {pid})")

        # Remember what was launched - it drives the "Последний запуск" card.
        if self.current_manifest and self.current_manifest.minecraft_version:
            self.config.last_pack = self.current_manifest.minecraft_version
            self.config.last_pack_time = datetime.now().isoformat(timespec="seconds")
            self.config.save()
            self._update_home_hero()

    def _reset_after_game_end(self):
        """Restore the launcher to its idle state after the game ends."""
        self.play_button.setEnabled(True)
        self._update_play_button(self.config.last_pack)

        if self._process_handler is not None:
            self._process_handler = None
        if self._launch_thread is not None:
            self._launch_thread = None

        if self.isMinimized():
            self.showNormal()
        self.activateWindow()

    def _on_game_crash(self, exit_code: int, error_log: str):
        """Handle game crash."""
        self._append_log(f"=== ИГРА УПАЛА (код: {exit_code}) ===")
        self._append_log("Последние ошибки:")
        for line in (error_log or "").split("\n")[-20:]:
            if line.strip():
                self._append_log(f"  {line}")

        self._reset_after_game_end()

        QMessageBox.critical(
            self, "Игра упала",
            f"Minecraft завершился с кодом {exit_code}.\n\n"
            f"Проверьте консоль для деталей ошибки."
        )

    def _on_game_exit(self, exit_code: int):
        """Handle normal game exit (closing the game window, Alt+F4, ...)."""
        self._append_log(f"=== Игра закрыта (код: {exit_code}) ===")
        self._reset_after_game_end()

    def closeEvent(self, event):
        if self.download_worker and self.download_worker.isRunning():
            self.download_worker.cancel()
            self.download_worker.wait(3000)
        if self.install_thread and self.install_thread.isRunning():
            self.install_thread.terminate()
            self.install_thread.wait(3000)
        if self._stats_thread and self._stats_thread.isRunning():
            self._stats_thread.terminate()
            self._stats_thread.wait(2000)
        if self.delete_thread and self.delete_thread.isRunning():
            self.delete_thread.wait(3000)
        # A launch still in progress is a live QThread too; without this Qt
        # prints "QThread: Destroyed while thread is still running".
        # Give it a moment to finish on its own first - it only performs
        # file and network work - then force it.
        launch_thread = getattr(self, "_launch_thread", None)
        if launch_thread is not None and launch_thread.isRunning():
            if not launch_thread.wait(2000):
                launch_thread.terminate()
                launch_thread.wait(2000)
        # The versions page runs its own stats thread; stop it before the
        # window is destroyed, otherwise Qt aborts on a live QThread.
        if hasattr(self, "versions_page"):
            self.versions_page.shutdown()
        # The builds page runs Modrinth request threads.
        if hasattr(self, "builds_page"):
            self.builds_page.shutdown()
        # Stop auth callback server
        if hasattr(self, 'auth_manager') and self.auth_manager:
            self.auth_manager.stop_callback_server()
        # Stop game if running
        if hasattr(self, '_process_handler') and self._process_handler:
            self._process_handler.stop()
        super().closeEvent(event)

    # ==================== AUTHENTICATION ====================

    def _update_profile_widget(self):
        """Update profile widget with current auth state."""
        self.profile_widget.refresh()

    def _on_login_url(self, login_url: str):
        """Called when the Microsoft login URL is generated.

        The browser is opened automatically and the local callback server waits
        for the redirect, so no modal dialog is shown - just inform the user.
        """
        self._append_log(f"[AUTH] Открываю браузер для входа Microsoft: {login_url}")
        self.status_label.setText(
            "Вход через Microsoft: завершите авторизацию в открытом браузере..."
        )
        self.status_label.setVisible(True)

    def _on_auth_complete_async(self, success: bool, message: str, profile: Optional[AuthProfile]):
        """Thread-safe callback - emits signal for main thread processing."""
        self.auth_completed.emit(success, message, profile)

    def _on_auth_completed(self, success: bool, message: str, profile: Optional[AuthProfile]):
        """Main thread slot - handles UI updates after auth completion."""
        self.status_label.setVisible(False)

        if success:
            self.config.auth_type = "microsoft"
            self.config.username = profile.username
            self.config.save()
            self._on_auth_changed()
            self._append_log(f"[AUTH] Вход выполнен: {profile.username}")
            QMessageBox.information(self, "Успех", f"Вход выполнен: {profile.username}")
        else:
            self._append_log(f"[AUTH] {message}")
            QMessageBox.critical(self, "Ошибка входа", message)

    def _start_microsoft_login(self):
        """Start Microsoft OAuth Authorization Code Flow."""
        try:
            self.auth_manager.start_microsoft_login()
        except Exception as e:
            self.status_label.setVisible(False)
            self._append_log(f"[AUTH] Не удалось начать вход: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось начать вход: {e}")

    def _open_settings(self):
        dialog = SettingsDialog(self.config, self.auth_manager, self.java_manager, self)
        dialog.microsoft_login_requested.connect(self._start_microsoft_login)
        dialog.auth_changed.connect(self._on_auth_changed)
        if dialog.exec():
            self._apply_styles()
            self._refresh_packs()
            self._update_profile_widget()
            self._on_auth_changed()

    def _on_auth_changed(self):
        """Refresh the sidebar account card after a login or logout."""
        self._refresh_home_page()
        self._update_profile_widget()