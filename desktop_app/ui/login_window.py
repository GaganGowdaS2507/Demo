"""
desktop_app/ui/login_window.py
Authentication & Server Connection Widget for Faculty.
Performs automatic Initial Setup on sign-in (syncing assigned sections, subjects,
timetable sessions, and student face embeddings), exactly like the mobile app.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QFrame, QCheckBox, QProgressBar
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont

try:
    from network.api_client import get_api_client
    from database.local_store import get_local_store
except ImportError:
    from ..network.api_client import get_api_client
    from ..database.local_store import get_local_store


class LoginAndSetupWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, object, object)

    def __init__(self, api_client, store, email, password):
        super().__init__()
        self.api_client = api_client
        self.store = store
        self.email = email
        self.password = password

    def run(self):
        # Step 1: Login
        self.progress.emit(5, "Authenticating with central server...")
        success, login_data = self.api_client.login(self.email, self.password)
        if not success:
            self.finished.emit(False, login_data, None)
            return

        # Step 2: Full initial setup (sections, subjects, sessions, embeddings)
        try:
            def cb(pct, msg):
                self.progress.emit(pct, msg)

            setup_result = self.api_client.run_full_initial_setup(self.store, progress_callback=cb)
            self.finished.emit(True, login_data, setup_result)
        except Exception as e:
            # Login was okay, but sync had an issue
            self.finished.emit(True, login_data, {"error": str(e)})


class LoginWidget(QWidget):
    login_successful = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = get_local_store()
        self.api_client = get_api_client()

        self._init_ui()
        self._load_saved_settings()

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QFrame(self)
        card.setObjectName("card")
        card.setFixedWidth(490)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(34, 34, 34, 34)
        card_layout.setSpacing(14)

        # Title Card
        title_label = QLabel("AttendAI Edge", card)
        title_label.setObjectName("heading")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title_label)

        subtitle_label = QLabel("Faculty Desktop Biometric Workstation\nOffline-First Local Inference", card)
        subtitle_label.setObjectName("subheading")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(subtitle_label)

        card_layout.addSpacing(10)

        # Server URL
        server_lbl = QLabel("Central Server URL:", card)
        card_layout.addWidget(server_lbl)

        server_row = QHBoxLayout()
        self.server_input = QLineEdit(card)
        self.server_input.setPlaceholderText("http://localhost:5000 or http://192.168.1.100:5000")
        server_row.addWidget(self.server_input)

        self.ping_btn = QPushButton("Ping", card)
        self.ping_btn.setObjectName("secondary")
        self.ping_btn.setFixedWidth(65)
        self.ping_btn.clicked.connect(self._on_ping_server)
        server_row.addWidget(self.ping_btn)
        card_layout.addLayout(server_row)

        # Email
        email_lbl = QLabel("Faculty Email / Username:", card)
        card_layout.addWidget(email_lbl)
        self.email_input = QLineEdit(card)
        self.email_input.setPlaceholderText("faculty@institution.edu")
        card_layout.addWidget(self.email_input)

        # Password
        pass_lbl = QLabel("Password:", card)
        card_layout.addWidget(pass_lbl)
        self.pass_input = QLineEdit(card)
        self.pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_input.setPlaceholderText("••••••••")
        self.pass_input.returnPressed.connect(self._on_login)
        card_layout.addWidget(self.pass_input)

        # Remember me
        self.remember_cb = QCheckBox("Remember Server & Credentials", card)
        self.remember_cb.setChecked(True)
        card_layout.addWidget(self.remember_cb)

        # Progress Bar for Sync
        self.progress_bar = QProgressBar(card)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        card_layout.addWidget(self.progress_bar)

        # Status Label
        self.status_lbl = QLabel("", card)
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.status_lbl)

        # Action Buttons
        self.login_btn = QPushButton("Sign In & Synchronize Data", card)
        self.login_btn.setMinimumHeight(44)
        self.login_btn.clicked.connect(self._on_login)
        card_layout.addWidget(self.login_btn)

        self.offline_btn = QPushButton("Work in Offline Mode (Cached Data)", card)
        self.offline_btn.setObjectName("secondary")
        self.offline_btn.clicked.connect(self._on_offline_mode)
        card_layout.addWidget(self.offline_btn)

        root_layout.addWidget(card)

    def _load_saved_settings(self):
        saved_server = self.store.get_setting("server_url", "http://localhost:5000")
        saved_email = self.store.get_setting("saved_email", "")
        self.server_input.setText(saved_server)
        self.email_input.setText(saved_email)
        self.api_client.set_base_url(saved_server)

        # Check if offline mode is possible
        token, profile = self.store.get_faculty_session()
        cached_sections = self.store.get_cached_sections()
        self.offline_btn.setEnabled(bool(profile or cached_sections))

    def _on_ping_server(self):
        server = self.server_input.text().strip()
        if not server:
            QMessageBox.warning(self, "Missing URL", "Please enter server URL first.")
            return
        self.api_client.set_base_url(server)
        alive, msg = self.api_client.test_connection()
        if alive:
            QMessageBox.information(self, "Server Reachable", f"Successfully connected to {server}!\n{msg}")
        else:
            QMessageBox.warning(self, "Connection Failed", f"Could not reach server:\n{msg}")

    def _on_login(self):
        server = self.server_input.text().strip()
        email = self.email_input.text().strip()
        password = self.pass_input.text()

        if not server or not email or not password:
            QMessageBox.warning(self, "Missing Fields", "Please enter Server URL, Email, and Password.")
            return

        self.api_client.set_base_url(server)
        self.login_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(5)
        self.status_lbl.setText("Connecting...")

        self.worker = LoginAndSetupWorker(self.api_client, self.store, email, password)
        self.worker.progress.connect(self._on_sync_progress)
        self.worker.finished.connect(self._on_login_finished)
        self.worker.start()

    def _on_sync_progress(self, pct, msg):
        self.progress_bar.setValue(pct)
        self.status_lbl.setText(msg)

    def _on_login_finished(self, success, login_data, setup_result):
        self.login_btn.setEnabled(True)
        if success:
            self.progress_bar.setValue(100)
            self.status_lbl.setText("Sync complete! Opening dashboard...")

            # Save settings
            if self.remember_cb.isChecked():
                self.store.set_setting("server_url", self.server_input.text().strip())
                self.store.set_setting("saved_email", self.email_input.text().strip())

            token = login_data.get("token")
            self.store.save_faculty_session(token, login_data)

            self.login_successful.emit(login_data)
        else:
            self.progress_bar.setVisible(False)
            self.status_lbl.setText(f"Login failed: {login_data}")
            QMessageBox.warning(self, "Authentication Failed", f"Server response: {login_data}")

    def _on_offline_mode(self):
        token, profile = self.store.get_faculty_session()
        if not profile:
            profile = {"name": "Offline Faculty", "role": "faculty"}
        self.login_successful.emit(profile)


LoginWindow = LoginWidget
