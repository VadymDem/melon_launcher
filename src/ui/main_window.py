from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QLabel, QPushButton, QFrame, QProgressBar,
    QSizePolicy, QMessageBox, QApplication, QTextEdit, QSplitter,
    QCheckBox, QLineEdit
)
from PyQt6.QtCore import Qt, QSize, QTimer, QThread, pyqtSignal
from typing import Callable, List, Optional
from PyQt6.QtGui import QIcon, QPixmap, QFont, QTextCursor

from ui.settings_dialog import SettingsDialog
from ui.profile_widget import ProfileWidget
from ui.build_info_widget import BuildInfoWidget
from utils.config import Config
from core import (
    ManifestManager, FileChecker, DownloadWorker, Manifest,
    AuthManager, AuthProfile,
    JavaManager, JavaInstallation, JVMConfigBuilder,
    LaunchManager, LaunchConfig, GameProcessHandler,
    parse_jvm_args, IconManager,
    get_builtin_manifest, get_builtin_profiles, is_builtin_profile
)
from pathlib import Path
import os


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
        on_finished: Callable[[bool, str], None]
    ):
        super().__init__()
        self.launch_manager = launch_manager
        self.process_handler = process_handler
        self.manifest = manifest
        self.auth_profile = auth_profile
        self.game_directory = game_directory
        self.java_version = java_version
        self.jvm_args = jvm_args
        self.custom_args = custom_args
        self.on_progress = on_progress
        self.on_finished = on_finished

    def run(self):
        try:
            self.progress_changed.emit(0, "Проверка требований...")
            
            # 1. Ensure Java
            self.progress_changed.emit(10, f"Проверка Java {self.java_version}...")
            java_install = JavaManager(self.game_directory).ensure_java(self.java_version)
            if not java_install.is_valid:
                self.finished.emit(False, f"Java {self.java_version} недоступна: {java_install.error}")
                return
            
            # 2. Check game files
            self.progress_changed.emit(20, "Проверка файлов игры...")
            # (File check/download handled by previous stage)
            
            # 3. Build launch config
            self.progress_changed.emit(40, "Подготовка команды запуска...")
            launch_config = LaunchConfig(
                manifest=self.manifest,
                java_installation=java_install,
                auth_profile=self.auth_profile,
                game_directory=self.game_directory,
                jvm_args=self.jvm_args,
                custom_args=self.custom_args
            )
            
            # Validate
            valid, error = self.launch_manager.validate_launch_requirements(launch_config)
            if not valid:
                self.finished.emit(False, f"Проверка запуска не пройдена: {error}")
                return
            
            # 4. Build command
            self.progress_changed.emit(60, "Сборка команды запуска...")
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

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.setWindowTitle("Melon Launcher")
        self.setMinimumSize(1000, 650)
        self.resize(1200, 720)

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

        # Initialize JavaManager
        self.java_manager = JavaManager(Path(config.install_path))

        self.manifest_manager = ManifestManager()
        self.current_manifest: Manifest | None = None
        self.download_worker: DownloadWorker | None = None

        self._setup_ui()
        self._apply_styles()
        self._load_profiles()
        self._update_profile_widget()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # Header
        header = self._create_header()
        main_layout.addLayout(header)

        # Separator
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        main_layout.addWidget(sep)

        # Content area - use splitter for log panel
        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_layout.addWidget(self.main_splitter, 1)

        # Upper content area
        upper_widget = QWidget()
        upper_layout = QHBoxLayout(upper_widget)
        upper_layout.setContentsMargins(0, 0, 0, 0)
        upper_layout.setSpacing(24)

        # Left panel - Profile selector + Build info
        left_panel = QVBoxLayout()
        left_panel.setSpacing(16)
        upper_layout.addLayout(left_panel, 2)

        # Profile selector
        self.profile_combo = QComboBox()
        self.profile_combo.setPlaceholderText("Выберите сборку...")
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        left_panel.addWidget(self.profile_combo)

        # Build info widget
        self.build_info = BuildInfoWidget(self.icon_manager)
        left_panel.addWidget(self.build_info)

        # Progress bar (hidden by default)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p% - %v/%m MB")
        left_panel.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setObjectName("infoLabel")
        self.status_label.setVisible(False)
        self.status_label.setWordWrap(True)
        left_panel.addWidget(self.status_label)

        # Play/Download button
        self.play_button = QPushButton("Скачать и играть")
        self.play_button.setMinimumHeight(56)
        self.play_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.play_button.clicked.connect(self._on_play_clicked)
        left_panel.addWidget(self.play_button)

        left_panel.addStretch()

        # Right panel - User profile
        right_panel = QVBoxLayout()
        right_panel.setSpacing(16)
        upper_layout.addLayout(right_panel, 1)

        self.profile_widget = ProfileWidget(self.config, self.auth_manager)
        self.profile_widget.microsoft_login_requested.connect(self._start_microsoft_login)
        right_panel.addWidget(self.profile_widget)

        right_panel.addStretch()

        self.main_splitter.addWidget(upper_widget)

        # Log console panel (bottom)
        self._setup_log_console()
        self.main_splitter.addWidget(self.log_console_widget)
        self.main_splitter.setSizes([500, 150])  # Initial sizes
        self.main_splitter.setCollapsible(1, True)

        # Bottom bar - Settings button
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()
        settings_btn = QPushButton("Настройки")
        settings_btn.setObjectName("secondaryButton")
        settings_btn.setFixedWidth(140)
        settings_btn.clicked.connect(self._open_settings)
        bottom_bar.addWidget(settings_btn)
        main_layout.addLayout(bottom_bar)

    def _create_header(self):
        header = QHBoxLayout()
        header.setSpacing(16)

        # App title
        title = QLabel("Melon Launcher")
        title.setObjectName("titleLabel")
        header.addWidget(title)

        header.addStretch()

        # Version label (placeholder)
        version = QLabel("v0.1.0-dev")
        version.setObjectName("versionLabel")
        header.addWidget(version)

        return header

    def _setup_log_console(self):
        """Setup the game log console panel."""
        self.log_console_widget = QWidget()
        log_layout = QVBoxLayout(self.log_console_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(8)

        # Log header
        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("Консоль игры"))
        log_header.addStretch()

        self.log_clear_btn = QPushButton("Очистить")
        self.log_clear_btn.setObjectName("secondaryButton")
        self.log_clear_btn.setFixedWidth(80)
        self.log_clear_btn.clicked.connect(self._clear_log)
        log_header.addWidget(self.log_clear_btn)

        self.log_auto_scroll = QCheckBox("Автопрокрутка")
        self.log_auto_scroll.setChecked(True)
        log_header.addWidget(self.log_auto_scroll)

        log_layout.addLayout(log_header)

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

        # Initially hidden
        self.log_console_widget.setVisible(False)

    def _clear_log(self):
        """Clear the log console."""
        self.log_console.clear()

    def _append_log(self, message: str):
        """Append a message to the log console."""
        # Add timestamp
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
        
        # Auto scroll
        if self.log_auto_scroll.isChecked():
            scrollbar = self.log_console.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _apply_styles(self):
        from pathlib import Path
        qss_path = Path(__file__).parent.parent / "assets" / "style.qss"
        if qss_path.exists():
            with open(qss_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())

    def _load_profiles(self):
        # Built-in profiles
        profiles = get_builtin_profiles() + ["Custom Build"]
        self.profile_combo.addItems(profiles)
        if self.config.last_profile:
            idx = self.profile_combo.findText(self.config.last_profile)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)

    def _on_profile_changed(self, profile_name: str):
        self.config.last_profile = profile_name
        self.config.save()
        self.build_info.update_build(profile_name)
        self._load_manifest_for_profile(profile_name)
        self._update_play_button(profile_name)

    def _load_manifest_for_profile(self, profile_name: str):
        # For built-in profiles, use real manifest
        if is_builtin_profile(profile_name):
            self.current_manifest = get_builtin_manifest(profile_name)
            self.build_info.update_build_from_manifest(self.current_manifest)
            self._hide_progress()
            return

        # For Custom Build, try to fetch from manifest URL
        if profile_name == "Custom Build" and self.config.manifest_url:
            self._show_progress(0, "Загрузка манифеста...")
            QTimer.singleShot(0, lambda: self._fetch_manifest_async(self.config.manifest_url))
        else:
            self.current_manifest = None
            self._hide_progress()

    def _fetch_manifest_async(self, url: str):
        try:
            manifest = self.manifest_manager.fetch_manifest(url)
            self.current_manifest = manifest
            self.build_info.update_build_from_manifest(manifest)
            self._hide_progress()
            self._update_play_button(self.profile_combo.currentText())
        except Exception as e:
            self._hide_progress()
            self.status_label.setText(f"Ошибка загрузки манифеста: {e}")
            self.status_label.setVisible(True)
            self.current_manifest = None
            self._update_play_button(self.profile_combo.currentText())

    def _update_play_button(self, profile_name: str):
        if profile_name == "Custom Build":
            if self.current_manifest is None:
                if self.config.manifest_url:
                    self.play_button.setText("Ошибка манифеста")
                    self.play_button.setEnabled(False)
                else:
                    self.play_button.setText("Настройте URL манифеста")
                    self.play_button.setEnabled(False)
            else:
                # Check if installed
                if self._is_installed():
                    self.play_button.setText("Играть")
                else:
                    total_mb = self.current_manifest.get_total_size() / (1024 * 1024)
                    self.play_button.setText(f"Скачать ({total_mb:.0f} MB) и играть")
                self.play_button.setEnabled(True)
        else:
            # Built-in profiles - use real manifest
            if self.current_manifest and is_builtin_profile(profile_name):
                if self._is_installed():
                    self.play_button.setText("Играть")
                else:
                    total_mb = self.current_manifest.get_total_size() / (1024 * 1024)
                    self.play_button.setText(f"Скачать ({total_mb:.0f} MB) и играть")
                self.play_button.setEnabled(True)
            else:
                self.play_button.setText("Играть")
                self.play_button.setEnabled(True)

    def _is_installed(self) -> bool:
        if not self.current_manifest:
            return False
        # Built-in profiles have no files to download
        if is_builtin_profile(self.profile_combo.currentText()):
            return True
        checker = FileChecker(Path(self.config.install_path))
        to_download = checker.get_files_to_download(self.current_manifest)
        return len(to_download) == 0

    def _on_play_clicked(self):
        profile = self.profile_combo.currentText()

        if profile == "Custom Build" and self.current_manifest:
            if self._is_installed():
                self._launch_game()
            else:
                self._start_download()
        else:
            QMessageBox.information(
                self, "Запуск",
                f"Запуск сборки: {profile}\n\n(Реализация запуска будет в Этапе 5)"
            )

    def _start_download(self):
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
            self._update_play_button(self.profile_combo.currentText())
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

    def _hide_progress(self):
        self.progress_bar.setVisible(False)
        self.status_label.setVisible(False)

    def _launch_game(self):
        """Full game launch implementation using LaunchManager and GameProcessHandler."""
        if not self.current_manifest:
            QMessageBox.warning(self, "Ошибка", "Сборка не выбрана")
            return

        profile = self.auth_manager.get_profile()
        if not profile:
            QMessageBox.warning(self, "Ошибка", "Требуется авторизация")
            return

        # Determine required Java version from manifest
        required_java = getattr(self.current_manifest, 'java_version', 17)
        
        # Get JVM args from config
        jvm_args = parse_jvm_args(self.config.custom_jvm_args) if self.config.custom_jvm_args else []
        
        # Add RAM settings from config
        builder = JVMConfigBuilder.from_config(self.config)
        jvm_args.extend(builder.build_jvm_args())
        
        # Show log console
        self.log_console_widget.setVisible(True)
        self.main_splitter.setSizes([450, 200])
        self._clear_log()
        self._append_log("=== Начало запуска ===")
        self._append_log(f"Сборка: {self.current_manifest.name} {self.current_manifest.version}")
        self._append_log(f"Java версия: {required_java}")
        self._append_log(f"Память: {self.config.ram_mb} MB")
        self._append_log(f"Авторизация: {profile.username} ({profile.auth_type})")

        # Disable play button during launch
        self.play_button.setEnabled(False)
        self.play_button.setText("Запуск...")

        # Create launch manager
        self._launch_manager = LaunchManager()
        self._process_handler = GameProcessHandler(
            on_output=self._append_log,
            on_crash=self._on_game_crash,
            on_exit=self._on_game_exit,
            on_started=self._on_game_started,
            log_file=Path(self.config.install_path) / "logs" / "latest.log"
        )

        # Start launch sequence in a thread to avoid blocking UI
        self._launch_thread = LaunchThread(
            launch_manager=self._launch_manager,
            process_handler=self._process_handler,
            manifest=self.current_manifest,
            auth_profile=profile,
            game_directory=Path(self.config.install_path),
            java_version=required_java,
            jvm_args=jvm_args,
            custom_args=[],
            on_progress=self._on_launch_progress,
            on_finished=self._on_launch_finished
        )
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

    def _on_game_crash(self, exit_code: int, error_log: str):
        """Handle game crash."""
        self._append_log(f"=== ИГРА УПАЛА (код: {exit_code}) ===")
        self._append_log("Последние ошибки:")
        for line in error_log.split("\n")[-20:]:
            if line.strip():
                self._append_log(f"  {line}")
        
        # Restore launcher window
        self.showNormal()
        self.activateWindow()
        
        # Show crash dialog
        QMessageBox.critical(
            self, "Игра упала",
            f"Minecraft завершился с кодом {exit_code}.\n\n"
            f"Проверьте консоль для деталей ошибки."
        )

    def _on_game_exit(self, exit_code: int):
        """Handle normal game exit."""
        self._append_log(f"=== Игра закрыта (код: {exit_code}) ===")
        
        # Restore launcher window
        self.showNormal()
        self.activateWindow()

    def closeEvent(self, event):
        if self.download_worker and self.download_worker.isRunning():
            self.download_worker.cancel()
            self.download_worker.wait(3000)
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
            self._update_profile_widget()
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
        if dialog.exec():
            self._apply_styles()
            self.profile_combo.clear()
            self._load_profiles()
            self._update_profile_widget()