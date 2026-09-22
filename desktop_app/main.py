"""
desktop_app/main.py
Entry point for AttendAI Faculty Edge Desktop Application.
Initializes High-DPI support, local database, bundled AI models, and launches GUI.
"""

import sys
import os
import logging
import ctypes

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from core.engine import DesktopRecognitionEngine
from database.local_store import get_local_store
from network.api_client import get_api_client
from ui.main_window import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("AttendAI-Desktop")


def main():
    # Enable High-DPI scaling
    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("AttendAI Desktop Edge Station")
    app.setOrganizationName("AttendAI")

    store = get_local_store()
    api_client = get_api_client()

    saved_server = store.get_setting("server_url", "http://localhost:5000")
    api_client.set_base_url(saved_server)

    logger.info("Initializing Desktop Edge Recognition Engine with bundled models...")
    engine = DesktopRecognitionEngine(models_root=CURRENT_DIR)
    engine.initialize()

    token, profile = store.get_faculty_session()
    if token:
        api_client.set_token(token)

    main_win = MainWindow(engine=engine, user_profile=profile)
    main_win.show()
    main_win.raise_()
    main_win.activateWindow()

    # Force Windows window manager to bring window to the front
    try:
        hwnd = int(main_win.winId())
        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE / SW_NORMAL
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception as win32_err:
        logger.debug(f"Win32 foreground hook: {win32_err}")

    logger.info("Application main window displayed. Entering Qt event loop...")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
