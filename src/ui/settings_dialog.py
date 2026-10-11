from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QPushButton, QSlider, QGroupBox,
    QFileDialog, QMessageBox, QRadioButton, QButtonGroup,
    QFormLayout, QSpinBox, QProgressBar, QComboBox, QListWidget,
    QListWidgetItem, QTextEdit, QCheckBox, QScrollArea
)
from PyQt6.QtCore import Qt, QStandardPaths, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from utils.config import Config
from core import AuthManager, JavaManager, JavaInstallation, ModrinthAPI, ModrinthProject
import psutil


class ModrinthSearchWorker(QThread):
    """Worker thread for searching Modrinth modpacks."""
    
    search_finished = pyqtSignal(list)
    search_error = pyqtSignal(str)
    
    def __init__(self, query: str, game_version: str = None, loader: str = None):
        super().__init__()
        self.query = query
        self.game_version = game_version
        self.loader = loader
    
    def run(self):
        try:
            api = ModrinthAPI()
            results = api.search_modpacks(
                query=self.query,
                game_version=self.game_version,
                loader=self.loader,
                limit=20
            )
            self.search_finished.emit(results)
        except Exception as e:
            self.search_error.emit(str(e))


class JavaDownloadWorker(QThread):
    """Worker thread for downloading Java."""
    
    progress_changed = pyqtSignal(int, int)  # current, total
    status_changed = pyqtSignal(str)
    download_finished = pyqtSignal(bool, str, object)  # success, message, JavaInstallation
    
    def __init__(self, java_manager: JavaManager, version: int):
        super().__init__()
        self.java_manager = java_manager
        self.version = version
    
    def run(self):
        try:
            self.status_changed.emit(f"Скачивание Java {self.version}...")
            
            def progress(current, total):
                if total > 0:
                    pct = int((current / total) * 100)
                    self.progress_changed.emit(pct, 100)
                self.status_changed.emit(f"Загрузка: {current}/{total} байт")
            
            install = self.java_manager.ensure_java(self.version, progress_callback=progress)
            
            if install.is_valid:
                self.download_finished.emit(True, f"Java {self.version} установлена успешно", install)
            else:
                self.download_finished.emit(False, f"Ошибка установки: {install.error}", install)
                
        except Exception as e:
            self.download_finished.emit(False, f"Критическая ошибка: {e}", None)


class SettingsDialog(QDialog):
    def __init__(self, config: Config, auth_manager: AuthManager, java_manager: JavaManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.auth_manager = auth_manager
        self.java_manager = java_manager
        self.setWindowTitle("Настройки")
        self.setMinimumSize(560, 520)
        self.resize(700, 580)
        self.setModal(True)

        self._search_worker: ModrinthSearchWorker | None = None
        self._java_download_worker: JavaDownloadWorker | None = None

        self._setup_ui()
        self._load_values()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Tabs
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # General tab
        self.tabs.addTab(self._create_general_tab(), "Общие")

        # Java & RAM tab
        self.tabs.addTab(self._create_java_tab(), "Java и память")

        # Modrinth tab
        self.tabs.addTab(self._create_modrinth_tab(), "Modrinth")

        # Auth tab
        self.tabs.addTab(self._create_auth_tab(), "Авторизация")

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setObjectName("secondaryButton")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(self._save_and_accept)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    def _create_general_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Manifest URL
        manifest_group = QGroupBox("Источник сборок")
        manifest_layout = QVBoxLayout(manifest_group)
        manifest_layout.setSpacing(10)

        self.manifest_url = QLineEdit()
        self.manifest_url.setPlaceholderText("https://github.com/user/repo/raw/main/manifest.json")
        manifest_layout.addWidget(QLabel("URL манифеста (GitHub raw):"))
        manifest_layout.addWidget(self.manifest_url)

        # Presets
        presets_layout = QHBoxLayout()
        preset_vanilla = QPushButton("Vanilla")
        preset_vanilla.setObjectName("secondaryButton")
        preset_vanilla.clicked.connect(lambda: self.manifest_url.setText(""))
        presets_layout.addWidget(preset_vanilla)

        preset_fabric = QPushButton("Fabric")
        preset_fabric.setObjectName("secondaryButton")
        preset_fabric.clicked.connect(lambda: self.manifest_url.setText(""))
        presets_layout.addWidget(preset_fabric)

        preset_forge = QPushButton("Forge")
        preset_forge.setObjectName("secondaryButton")
        preset_forge.clicked.connect(lambda: self.manifest_url.setText(""))
        presets_layout.addWidget(preset_forge)

        presets_layout.addStretch()
        manifest_layout.addLayout(presets_layout)

        layout.addWidget(manifest_group)

        # Install path
        path_group = QGroupBox("Путь установки")
        path_layout = QVBoxLayout(path_group)
        path_layout.setSpacing(10)

        path_row = QHBoxLayout()
        self.install_path = QLineEdit()
        self.install_path.setReadOnly(True)
        path_row.addWidget(self.install_path, 1)

        browse_btn = QPushButton("Обзор...")
        browse_btn.setObjectName("secondaryButton")
        browse_btn.setFixedWidth(100)
        browse_btn.clicked.connect(self._browse_install_path)
        path_row.addWidget(browse_btn)

        path_layout.addLayout(path_row)
        layout.addWidget(path_group)

        layout.addStretch()
        return widget

    def _create_java_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # RAM slider
        ram_group = QGroupBox("Выделенная оперативная память")
        ram_layout = QVBoxLayout(ram_group)
        ram_layout.setSpacing(12)

        # Slider with value display
        slider_row = QHBoxLayout()
        self.ram_slider = QSlider(Qt.Orientation.Horizontal)
        self.ram_slider.setMinimum(1024)
        max_ram = self._get_max_ram_mb()
        self.ram_slider.setMaximum(max_ram)
        self.ram_slider.setSingleStep(256)
        self.ram_slider.setPageStep(1024)
        self.ram_slider.setTickInterval(1024)
        self.ram_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        slider_row.addWidget(self.ram_slider, 1)

        self.ram_value = QLabel()
        self.ram_value.setFixedWidth(80)
        self.ram_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.ram_value.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        slider_row.addWidget(self.ram_value)

        ram_layout.addLayout(slider_row)

        # Info label
        self.ram_info = QLabel()
        self.ram_info.setObjectName("infoLabel")
        self.ram_info.setWordWrap(True)
        ram_layout.addWidget(self.ram_info)

        self.ram_slider.valueChanged.connect(self._update_ram_label)
        layout.addWidget(ram_group)

        # Java Runtime selection
        java_group = QGroupBox("Java Runtime")
        java_layout = QVBoxLayout(java_group)
        java_layout.setSpacing(10)

        # Java version selector
        version_row = QHBoxLayout()
        version_row.addWidget(QLabel("Версия Java:"))
        self.java_version_combo = QComboBox()
        self.java_version_combo.addItems(["8", "11", "17", "21"])
        self.java_version_combo.setCurrentText("17")
        self.java_version_combo.currentTextChanged.connect(self._on_java_version_changed)
        version_row.addWidget(self.java_version_combo)
        version_row.addStretch()
        java_layout.addLayout(version_row)

        # Java path
        path_row = QHBoxLayout()
        self.java_path = QLineEdit()
        self.java_path.setPlaceholderText("Автоопределение (путь к java.exe)")
        self.java_path.setReadOnly(True)
        path_row.addWidget(self.java_path, 1)

        self.java_browse_btn = QPushButton("Обзор...")
        self.java_browse_btn.setObjectName("secondaryButton")
        self.java_browse_btn.setFixedWidth(100)
        self.java_browse_btn.clicked.connect(self._browse_java_path)
        path_row.addWidget(self.java_browse_btn)

        self.java_download_btn = QPushButton("Скачать Java")
        self.java_download_btn.setToolTip("Скачать и установить выбранную версию Java")
        self.java_download_btn.clicked.connect(self._download_java)
        path_row.addWidget(self.java_download_btn)

        java_layout.addLayout(path_row)

        # Java progress
        self.java_progress = QProgressBar()
        self.java_progress.setVisible(False)
        java_layout.addWidget(self.java_progress)

        self.java_status = QLabel("")
        self.java_status.setObjectName("infoLabel")
        self.java_status.setVisible(False)
        java_layout.addWidget(self.java_status)

        layout.addWidget(java_group)

        # JVM Args (advanced)
        jvm_group = QGroupBox("Дополнительные JVM аргументы (дополнительно)")
        jvm_layout = QVBoxLayout(jvm_group)
        self.jvm_args = QLineEdit()
        self.jvm_args.setPlaceholderText("Например: -XX:+UseZGC -Dcustom.property=value")
        jvm_layout.addWidget(QLabel("Пользовательские флаги JVM:"))
        jvm_layout.addWidget(self.jvm_args)
        layout.addWidget(jvm_group)

        layout.addStretch()
        return widget

    def _create_modrinth_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Search
        search_group = QGroupBox("Поиск модпаков на Modrinth")
        search_layout = QVBoxLayout(search_group)
        search_layout.setSpacing(10)

        search_row = QHBoxLayout()
        self.modrinth_search = QLineEdit()
        self.modrinth_search.setPlaceholderText("Название модпака...")
        self.modrinth_search.returnPressed.connect(self._search_modrinth)
        search_row.addWidget(self.modrinth_search, 1)

        self.modrinth_game_version = QComboBox()
        self.modrinth_game_version.addItems(["1.20.4", "1.20.1", "1.19.4", "1.19.2", "1.18.2", "1.16.5"])
        self.modrinth_game_version.setCurrentText("1.20.4")
        self.modrinth_game_version.setFixedWidth(120)
        search_row.addWidget(self.modrinth_game_version)

        self.modrinth_loader = QComboBox()
        self.modrinth_loader.addItems(["Все", "fabric", "forge", "quilt", "neoforge"])
        self.modrinth_loader.setFixedWidth(120)
        search_row.addWidget(self.modrinth_loader)

        search_btn = QPushButton("Поиск")
        search_btn.clicked.connect(self._search_modrinth)
        search_row.addWidget(search_btn)

        search_layout.addLayout(search_row)

        # Results list
        self.modrinth_results = QListWidget()
        self.modrinth_results.setAlternatingRowColors(True)
        self.modrinth_results.itemDoubleClicked.connect(self._on_modrinth_selected)
        search_layout.addWidget(self.modrinth_results)

        # Progress
        self.modrinth_progress = QProgressBar()
        self.modrinth_progress.setVisible(False)
        search_layout.addWidget(self.modrinth_progress)

        layout.addWidget(search_group)

        # Selected modpack info
        info_group = QGroupBox("Выбранный модпак")
        info_layout = QVBoxLayout(info_group)
        
        self.modrinth_info = QLabel("Модпак не выбран")
        self.modrinth_info.setObjectName("infoLabel")
        self.modrinth_info.setWordWrap(True)
        info_layout.addWidget(self.modrinth_info)

        self.modrinth_use_btn = QPushButton("Использовать этот модпак")
        self.modrinth_use_btn.setEnabled(False)
        self.modrinth_use_btn.clicked.connect(self._use_modrinth_modpack)
        info_layout.addWidget(self.modrinth_use_btn)

        layout.addWidget(info_group)

        layout.addStretch()
        return widget

    def _create_auth_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Current session info
        session_group = QGroupBox("Текущая сессия")
        session_layout = QVBoxLayout(session_group)
        session_layout.setSpacing(8)

        self.session_info = QLabel()
        self.session_info.setObjectName("infoLabel")
        self.session_info.setWordWrap(True)
        session_layout.addWidget(self.session_info)

        layout.addWidget(session_group)

        # Auth actions
        auth_group = QGroupBox("Авторизация")
        auth_layout = QVBoxLayout(auth_group)
        auth_layout.setSpacing(12)

        # Microsoft login button
        self.microsoft_login_btn = QPushButton("Войти через Microsoft")
        self.microsoft_login_btn.setToolTip("Откроет браузер для входа через Microsoft")
        self.microsoft_login_btn.clicked.connect(self._on_microsoft_login)
        auth_layout.addWidget(self.microsoft_login_btn)

        # Offline login button
        self.offline_login_btn = QPushButton("Войти в Offline-режим")
        self.offline_login_btn.setObjectName("secondaryButton")
        self.offline_login_btn.setToolTip("Вход без интернета, только игровое имя")
        self.offline_login_btn.clicked.connect(self._on_offline_login)
        auth_layout.addWidget(self.offline_login_btn)

        # Logout button
        self.logout_btn = QPushButton("Выйти из аккаунта")
        self.logout_btn.setObjectName("dangerButton")
        self.logout_btn.setToolTip("Выйти из текущего аккаунта")
        self.logout_btn.clicked.connect(self._on_logout)
        auth_layout.addWidget(self.logout_btn)

        layout.addWidget(auth_group)

        # Offline username setting
        offline_group = QGroupBox("Настройки Offline-режима")
        offline_layout = QVBoxLayout(offline_group)
        offline_layout.setSpacing(8)

        self.offline_name = QLineEdit()
        self.offline_name.setPlaceholderText("Ваше игровое имя (3-16 символов)")
        offline_layout.addWidget(QLabel("Имя для Offline-режима:"))
        offline_layout.addWidget(self.offline_name)

        layout.addWidget(offline_group)

        layout.addStretch()
        return widget

    def _get_max_ram_mb(self):
        try:
            total_mb = psutil.virtual_memory().total // (1024 * 1024)
            # Leave at least 2GB for system
            return max(1024, total_mb - 2048)
        except Exception:
            return 16384  # Default 16GB max

    def _update_ram_label(self, value: int):
        gb = value / 1024
        if gb >= 1:
            self.ram_value.setText(f"{gb:.1f} GB")
        else:
            self.ram_value.setText(f"{value} MB")

        max_ram = self.ram_slider.maximum()
        max_gb = max_ram / 1024
        self.ram_info.setText(
            f"Минимум: 1 GB | Максимум: {max_gb:.1f} GB "
            f"(автоматически ограничено физической памятью: {psutil.virtual_memory().total // (1024**3)} GB)"
        )

    def _browse_install_path(self):
        path = QFileDialog.getExistingDirectory(
            self, "Выберите папку установки", self.install_path.text()
        )
        if path:
            self.install_path.setText(path)

    def _on_java_version_changed(self, version_text: str):
        """Update Java path display when version changes."""
        version = int(version_text)
        install = self.java_manager.check_java_installed(version)
        if install.is_valid:
            self.java_path.setText(str(install.path))
            self.java_path.setToolTip(f"Найдено: {install.vendor} {install.version}")
        else:
            self.java_path.setText("")
            self.java_path.setPlaceholderText(f"Java {version} не найдена - нажмите 'Скачать Java'")
            self.java_path.setToolTip(install.error)

    def _browse_java_path(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите java.exe", "", "Java Executable (java.exe);;All Files (*)"
        )
        if path:
            self.java_path.setText(path)

    def _download_java(self):
        version = int(self.java_version_combo.currentText())
        
        self.java_download_btn.setEnabled(False)
        self.java_progress.setVisible(True)
        self.java_progress.setValue(0)
        self.java_status.setVisible(True)
        self.java_status.setText("Подготовка...")
        
        self._java_download_worker = JavaDownloadWorker(self.java_manager, version)
        self._java_download_worker.progress_changed.connect(self._on_java_progress)
        self._java_download_worker.status_changed.connect(self._on_java_status)
        self._java_download_worker.download_finished.connect(self._on_java_finished)
        self._java_download_worker.start()

    def _on_java_progress(self, current: int, total: int):
        self.java_progress.setMaximum(total)
        self.java_progress.setValue(current)

    def _on_java_status(self, message: str):
        self.java_status.setText(message)

    def _on_java_finished(self, success: bool, message: str, install: JavaInstallation):
        self.java_download_btn.setEnabled(True)
        self.java_progress.setVisible(False)
        
        if success and install:
            self.java_path.setText(str(install.path))
            self.java_path.setToolTip(f"Установлено: {install.vendor} {install.version}")
            self.java_status.setText("Установка завершена успешно")
            self.java_status.setStyleSheet("color: #a6e3a1;")
        else:
            self.java_status.setText(f"Ошибка: {message}")
            self.java_status.setStyleSheet("color: #f38ba8;")
        
        self._java_download_worker = None

    def _search_modrinth(self):
        query = self.modrinth_search.text().strip()
        game_version = self.modrinth_game_version.currentText() if self.modrinth_game_version.currentText() != "Все" else None
        loader = self.modrinth_loader.currentText() if self.modrinth_loader.currentText() != "Все" else None
        
        self.modrinth_results.clear()
        self.modrinth_progress.setVisible(True)
        self.modrinth_progress.setRange(0, 0)  # Indeterminate
        
        self._search_worker = ModrinthSearchWorker(query, game_version, loader)
        self._search_worker.search_finished.connect(self._on_modrinth_results)
        self._search_worker.search_error.connect(self._on_modrinth_error)
        self._search_worker.start()

    def _on_modrinth_results(self, projects: list[ModrinthProject]):
        self.modrinth_progress.setVisible(False)
        
        for project in projects:
            item = QListWidgetItem(f"{project.title} ({project.slug})")
            item.setData(Qt.ItemDataRole.UserRole, project)
            item.setToolTip(f"{project.description[:200]}...\nКатегории: {', '.join(project.categories)}\nЗагрузки: {project.downloads:,}")
            self.modrinth_results.addItem(item)
        
        if not projects:
            item = QListWidgetItem("Ничего не найдено")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.modrinth_results.addItem(item)

    def _on_modrinth_error(self, error: str):
        self.modrinth_progress.setVisible(False)
        QMessageBox.critical(self, "Ошибка поиска", f"Не удалось выполнить поиск: {error}")

    def _on_modrinth_selected(self, item: QListWidgetItem):
        project: ModrinthProject = item.data(Qt.ItemDataRole.UserRole)
        if project:
            self._selected_modrinth_project = project
            self.modrinth_info.setText(
                f"<b>{project.title}</b> ({project.slug})<br>"
                f"{project.description[:300]}...<br>"
                f"Категории: {', '.join(project.categories)}<br>"
                f"Загрузки: {project.downloads:,} | Подписчики: {project.follows:,}"
            )
            self.modrinth_use_btn.setEnabled(True)
        else:
            self.modrinth_use_btn.setEnabled(False)

    def _use_modrinth_modpack(self):
        """Set the selected Modrinth modpack as the manifest URL."""
        if hasattr(self, '_selected_modrinth_project'):
            project = self._selected_modrinth_project
            # We'll need to fetch versions and let user pick one
            # For now, just show a message
            QMessageBox.information(
                self, "Модпак выбран",
                f"Выбран: {project.title}\n\n"
                f"Для полной интеграции нужно выбрать версию модпака.\n"
                f"Это будет реализовано в следующем обновлении."
            )
            # TODO: Fetch versions, let user pick, build manifest URL

    def _browse_install_path(self):
        path = QFileDialog.getExistingDirectory(
            self, "Выберите папку установки", self.install_path.text()
        )
        if path:
            self.install_path.setText(path)

    def _load_values(self):
        self.manifest_url.setText(self.config.manifest_url)
        self.install_path.setText(self.config.install_path)
        self.ram_slider.setValue(self.config.ram_mb)
        self._update_ram_label(self.config.ram_mb)

        self.offline_name.setText(self.config.username)
        self.jvm_args.setText(self.config.custom_jvm_args if hasattr(self.config, 'custom_jvm_args') else "")
        self._update_session_info()

        # Set Java version from config or default to 17
        java_version = getattr(self.config, 'java_version', 17)
        self.java_version_combo.setCurrentText(str(java_version))
        self._on_java_version_changed(str(java_version))

    def _update_session_info(self):
        profile = self.auth_manager.get_profile()
        if profile:
            if profile.auth_type == "microsoft":
                self.session_info.setText(
                    f"Вход выполнен: <b>{profile.username}</b> (Microsoft)<br>"
                    f"UUID: {profile.uuid[:8]}...{profile.uuid[-8:]}"
                )
                self.microsoft_login_btn.setText("Сменить аккаунт Microsoft")
                self.logout_btn.setVisible(True)
            else:
                self.session_info.setText(
                    f"Offline-режим: <b>{profile.username}</b><br>"
                    f"UUID: {profile.uuid[:8]}...{profile.uuid[-8:]}"
                )
                self.microsoft_login_btn.setText("Войти через Microsoft")
                self.logout_btn.setVisible(True)
        else:
            self.session_info.setText("Не вошли в систему")
            self.microsoft_login_btn.setText("Войти через Microsoft")
            self.logout_btn.setVisible(False)

    def _on_microsoft_login(self):
        """Trigger Microsoft login - handled by MainWindow."""
        self.microsoft_login_requested.emit()

    def _on_offline_login(self):
        username = self.offline_name.text().strip()
        if not username:
            QMessageBox.warning(self, "Ошибка", "Введите имя для Offline-режима")
            return

        try:
            profile = self.auth_manager.login_offline(username)
            self.config.username = profile.username
            self.config.auth_type = "offline"
            self.config.save()
            self._update_session_info()
            # Let the main window refresh the sidebar account card right away.
            self.auth_changed.emit()
            QMessageBox.information(self, "Успех", f"Вход выполнен как {profile.username}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _on_logout(self):
        self.auth_manager.logout()
        self.config.auth_type = "offline"
        self.config.username = "Player"
        self.config.save()
        self._update_session_info()
        self.auth_changed.emit()
        QMessageBox.information(self, "Выход", "Вы вышли из аккаунта")

    def _save_and_accept(self):
        self.config.manifest_url = self.manifest_url.text().strip()
        self.config.install_path = self.install_path.text().strip()
        self.config.ram_mb = self.ram_slider.value()
        self.config.username = self.offline_name.text().strip() or "Player"
        self.config.java_version = int(self.java_version_combo.currentText())
        self.config.custom_jvm_args = self.jvm_args.text().strip()
        self.config.save()
        self.accept()

    def closeEvent(self, event):
        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.terminate()
            self._search_worker.wait(1000)
        if self._java_download_worker and self._java_download_worker.isRunning():
            self._java_download_worker.terminate()
            self._java_download_worker.wait(1000)
        super().closeEvent(event)

    # Signal for Microsoft login request
    from PyQt6.QtCore import pyqtSignal
    microsoft_login_requested = pyqtSignal()
    # Emitted when the account changes (offline login / logout) so the main
    # window can refresh the sidebar without closing this dialog.
    auth_changed = pyqtSignal()