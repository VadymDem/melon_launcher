import sys
from pathlib import Path

from PyQt6.QtCore import qInstallMessageHandler
from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow
from utils.config import Config


def install_message_filter():
    def handler(mode, context, message):
        if "QFont::setPointSize" in message and "Point size <= 0" in message:
            return
        print(message, file=sys.stderr)

    qInstallMessageHandler(handler)


def main():
    install_message_filter()
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