import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow
from utils.config import Config


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Melon Launcher")
    app.setOrganizationName("MelonLauncher")

    config = Config()
    config.load()

    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()