from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QMessageBox, QInputDialog, QLineEdit, QComboBox
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QFont

from utils.config import Config
from core import AuthManager, AuthProfile, OfflineAuthError, MicrosoftAuthError


class ProfileWidget(QWidget):
    # Emitted whenever the auth state changes (offline login, logout, mode
    # switch) so the main window can refresh the sidebar account card, which
    # this widget does not own.
    auth_changed = pyqtSignal()
    # Request to start the Microsoft OAuth flow - handled by MainWindow.
    microsoft_login_requested = pyqtSignal()

    def __init__(self, config: Config, auth_manager: AuthManager):
        super().__init__()
        self.config = config
        self.auth_manager = auth_manager
        self.setFixedWidth(280)
        self._setup_ui()
        self._update_profile()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Background frame
        self.frame = QFrame()
        self.frame.setObjectName("profileFrame")
        self.frame.setStyleSheet("""
            QFrame#profileFrame {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 12px;
            }
        """)
        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(16, 16, 16, 16)
        frame_layout.setSpacing(12)

        # Avatar
        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(80, 80)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame_layout.addWidget(self.avatar_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Username
        self.username_label = QLabel()
        self.username_label.setObjectName("titleLabel")
        self.username_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Medium))
        self.username_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.username_label.setWordWrap(True)
        frame_layout.addWidget(self.username_label)

        # Status
        self.status_label = QLabel()
        self.status_label.setObjectName("infoLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame_layout.addWidget(self.status_label)

        # Auth type badge
        self.auth_badge = QLabel()
        self.auth_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.auth_badge.setStyleSheet("""
            QLabel {
                background-color: #45475a;
                color: #a6adc8;
                border-radius: 12px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: 600;
            }
        """)
        frame_layout.addWidget(self.auth_badge, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Auth mode switcher
        self.auth_mode_combo = QComboBox()
        self.auth_mode_combo.addItems(["Microsoft", "Offline"])
        self.auth_mode_combo.setToolTip("Режим авторизации")
        self.auth_mode_combo.setFixedHeight(32)
        self.auth_mode_combo.currentTextChanged.connect(self._on_auth_mode_changed)
        frame_layout.addWidget(self.auth_mode_combo)

        # Login/Logout button
        self.auth_button = QPushButton("Войти")
        self.auth_button.setObjectName("secondaryButton")
        self.auth_button.setFixedHeight(36)
        self.auth_button.clicked.connect(self._on_auth_clicked)
        frame_layout.addWidget(self.auth_button)

        layout.addWidget(self.frame)

    def _update_profile(self):
        profile = self.auth_manager.get_profile()

        # Keep the mode selector in sync with the active profile
        mode = "Microsoft" if (profile and profile.auth_type == "microsoft") else "Offline"
        if self.auth_mode_combo.currentText() != mode:
            self.auth_mode_combo.blockSignals(True)
            self.auth_mode_combo.setCurrentText(mode)
            self.auth_mode_combo.blockSignals(False)
        
        if profile:
            self.username_label.setText(profile.username)
            
            if profile.auth_type == "microsoft":
                self.status_label.setText("Вход выполнен (Microsoft)")
                self.auth_badge.setText("Microsoft Account")
                self.auth_badge.setStyleSheet("""
                    QLabel {
                        background-color: #1e66f5;
                        color: white;
                        border-radius: 12px;
                        padding: 4px 12px;
                        font-size: 11px;
                        font-weight: 600;
                    }
                """)
                self.auth_button.setText("Выйти")
            else:
                self.status_label.setText("Офлайн режим")
                self.auth_badge.setText("Offline")
                self.auth_badge.setStyleSheet("""
                    QLabel {
                        background-color: #45475a;
                        color: #a6adc8;
                        border-radius: 12px;
                        padding: 4px 12px;
                        font-size: 11px;
                        font-weight: 600;
                    }
                """)
                self.auth_button.setText("Войти (Microsoft)")
        else:
            self.username_label.setText("Не вошли в систему")
            self.status_label.setText("Требуется авторизация")
            self.auth_badge.setText("Guest")
            self.auth_badge.setStyleSheet("""
                QLabel {
                    background-color: #f38ba8;
                    color: #1e1e2e;
                    border-radius: 12px;
                    padding: 4px 12px;
                    font-size: 11px;
                    font-weight: 600;
                }
            """)
            self.auth_button.setText("Войти (Microsoft)")

        self._generate_avatar(profile.username if profile else "Guest")

    def _generate_avatar(self, username: str):
        size = 80
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background circle
        colors = [
            QColor("#89b4fa"), QColor("#f38ba8"), QColor("#a6e3a1"),
            QColor("#f9e2af"), QColor("#cba6f7"), QColor("#fab387")
        ]
        color_idx = hash(username) % len(colors)
        painter.setBrush(colors[color_idx])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, size, size)

        # Initials
        name_parts = username.strip().split()
        if len(name_parts) >= 2:
            initials = (name_parts[0][0] + name_parts[-1][0]).upper()
        elif name_parts:
            initials = name_parts[0][:2].upper()
        else:
            initials = "??"

        painter.setPen(QColor("#1e1e2e"))
        painter.setFont(QFont("Segoe UI", 28, QFont.Weight.Bold))
        painter.drawText(0, 0, size, size, Qt.AlignmentFlag.AlignCenter, initials)
        painter.end()

        self.avatar_label.setPixmap(pixmap)

    def _on_auth_mode_changed(self, mode: str):
        """Switch between Microsoft and offline authorisation."""
        profile = self.auth_manager.get_profile()

        if profile:
            current = "Microsoft" if profile.auth_type == "microsoft" else "Offline"
            if mode == current:
                return
            self._logout(reset_username=True)
            self.config.auth_type = mode.lower()
            self.config.save()

        if mode == "Offline":
            self._start_offline_login()
        else:
            self._start_microsoft_login()

    def _logout(self, reset_username: bool = True):
        """Clear the session and refresh every account view.

        Sets the offline username back to the default so the sidebar does not
        keep showing the name of the account that just logged out.
        """
        self.auth_manager.logout()
        if reset_username:
            self.config.username = "Player"
            self.config.auth_type = "offline"
            self.config.save()
        self._update_profile()
        self.auth_changed.emit()

    def _on_auth_clicked(self):
        profile = self.auth_manager.get_profile()
        
        if profile and profile.auth_type == "microsoft":
            # Logout
            self._logout()
            QMessageBox.information(self, "Выход", "Вы вышли из аккаунта Microsoft")
        elif profile and profile.auth_type == "offline":
            # Switch to Microsoft login
            self._start_microsoft_login()
        else:
            # Not logged in - show options
            self._show_login_options()

    def _show_login_options(self):
        """Show dialog to choose login method."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QRadioButton, QButtonGroup, QDialogButtonBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Выбор входа")
        dialog.setMinimumWidth(300)
        
        layout = QVBoxLayout(dialog)
        
        layout.addWidget(QLabel("Выберите способ входа:"))
        
        btn_group = QButtonGroup(dialog)
        
        microsoft_radio = QRadioButton("Microsoft OAuth (рекомендуется)")
        microsoft_radio.setChecked(True)
        btn_group.addButton(microsoft_radio, 0)
        layout.addWidget(microsoft_radio)
        
        offline_radio = QRadioButton("Offline (только имя)")
        btn_group.addButton(offline_radio, 1)
        layout.addWidget(offline_radio)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if btn_group.checkedId() == 0:
                self._start_microsoft_login()
            else:
                self._start_offline_login()

    def _start_offline_login(self):
        """Show dialog for offline username and login."""
        username, ok = QInputDialog.getText(
            self, "Offline-режим",
            "Введите игровое имя (3-16 символов, буквы, цифры, _):",
            QLineEdit.EchoMode.Normal,
            self.config.username
        )
        
        if ok and username:
            try:
                profile = self.auth_manager.login_offline(username.strip())
                self.config.username = profile.username
                self.config.auth_type = "offline"
                self.config.save()
                self._update_profile()
                self.auth_changed.emit()
                QMessageBox.information(self, "Успех", f"Вход выполнен как {profile.username}")
            except OfflineAuthError as e:
                QMessageBox.critical(self, "Ошибка", str(e))

    def _start_microsoft_login(self):
        """Start Microsoft OAuth flow - will be handled by MainWindow."""
        # Emit a custom event or call a callback
        # For now, we'll use a simple approach - MainWindow will connect to this
        self.microsoft_login_requested.emit()

    def refresh(self):
        self._update_profile()