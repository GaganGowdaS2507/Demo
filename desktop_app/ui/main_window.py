"""
desktop_app/ui/main_window.py
Main Application Window for AttendAI Faculty Desktop.
Manages stacked views: Login Screen and Dashboard (Attendance Workspace, Today's Classes, Offline Queue, and Engine Settings).
Implements the full mobile sync pipeline (downloading faculty profile, sections, subjects, sessions, and student face embeddings).
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QFrame, QStatusBar, QStackedWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

try:
    from ui.styles import MODERN_DARK_STYLE
    from ui.login_window import LoginWidget
    from ui.attendance_view import AttendanceView
    from database.local_store import get_local_store
    from network.api_client import get_api_client
except ImportError:
    from .styles import MODERN_DARK_STYLE
    from .login_window import LoginWidget
    from .attendance_view import AttendanceView
    from ..database.local_store import get_local_store
    from ..network.api_client import get_api_client


class FullSyncWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, object)

    def __init__(self, api_client, store):
        super().__init__()
        self.api_client = api_client
        self.store = store

    def run(self):
        try:
            def cb(pct, msg):
                self.progress.emit(pct, msg)

            result = self.api_client.run_full_initial_setup(self.store, progress_callback=cb)
            self.finished.emit(True, result)
        except Exception as e:
            self.finished.emit(False, str(e))


class MainWindow(QMainWindow):
    def __init__(self, engine, user_profile=None):
        super().__init__()
        self.engine = engine
        self.user_profile = user_profile or {}
        self.store = get_local_store()
        self.api_client = get_api_client()

        self.setWindowTitle("AttendAI - Faculty Edge Biometric Attendance Station")
        self.resize(1280, 820)
        self.setMinimumSize(960, 640)
        self.setStyleSheet(MODERN_DARK_STYLE)

        self._init_ui()

        if self.user_profile:
            self._switch_to_dashboard(self.user_profile)
        else:
            self.stack.setCurrentIndex(0)

    def _init_ui(self):
        self.stack = QStackedWidget(self)
        self.setCentralWidget(self.stack)

        # Page 0: Login View
        self.login_widget = LoginWidget(self)
        self.login_widget.login_successful.connect(self._on_login_success)
        self.stack.addWidget(self.login_widget)

        # Page 1: Dashboard View
        self.dashboard_container = QWidget(self)
        self._init_dashboard_ui(self.dashboard_container)
        self.stack.addWidget(self.dashboard_container)

    def _init_dashboard_ui(self, container):
        root_layout = QVBoxLayout(container)
        root_layout.setContentsMargins(16, 12, 16, 12)
        root_layout.setSpacing(12)

        # Top Header Bar
        header_card = QFrame(container)
        header_card.setObjectName("card")
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(16, 10, 16, 10)

        title_vbox = QVBoxLayout()
        app_title = QLabel("AttendAI Edge Station", header_card)
        app_title.setObjectName("heading")
        title_vbox.addWidget(app_title)

        self.fac_sub = QLabel("Logged in: Faculty User", header_card)
        self.fac_sub.setObjectName("subheading")
        title_vbox.addWidget(self.fac_sub)
        header_layout.addLayout(title_vbox)

        header_layout.addStretch()

        # Engine Badge
        engine_device = getattr(self.engine, "device", "CPU")
        self.engine_badge = QLabel(f"InsightFace Buffalo_l ({engine_device})", header_card)
        self.engine_badge.setObjectName("badge")
        header_layout.addWidget(self.engine_badge)

        # Full Sync Button
        self.header_sync_btn = QPushButton("Sync Central Data (Mobile Pipeline)", header_card)
        self.header_sync_btn.setObjectName("secondary")
        self.header_sync_btn.clicked.connect(self._on_sync_clicked)
        header_layout.addWidget(self.header_sync_btn)

        # Logout Button
        logout_btn = QPushButton("Sign Out", header_card)
        logout_btn.setObjectName("danger")
        logout_btn.clicked.connect(self._on_logout)
        header_layout.addWidget(logout_btn)

        root_layout.addWidget(header_card)

        # Main Tab Widget
        self.tabs = QTabWidget(container)

        # Tab 1: Attendance Workspace
        self.attendance_view = AttendanceView(engine=self.engine, parent=self)
        self.attendance_view.attendance_submitted.connect(self._on_attendance_submitted)
        self.tabs.addTab(self.attendance_view, "Mark Attendance (Edge AI)")

        # Tab 2: Today's Schedule & Sections
        self.schedule_widget = self._create_schedule_tab()
        self.tabs.addTab(self.schedule_widget, "Today's Classes & Sections")

        # Tab 3: Offline Queue & Sync
        self.queue_widget = self._create_queue_tab()
        self.tabs.addTab(self.queue_widget, "Offline Sync Queue")

        # Tab 4: Engine & System Info
        self.settings_widget = self._create_settings_tab()
        self.tabs.addTab(self.settings_widget, "AI Engine Status")

        root_layout.addWidget(self.tabs)

        # Status Bar
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. Bundled models loaded locally.")

    def _create_schedule_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        hdr = QLabel("Today's Schedule & Assigned Sections", w)
        hdr.setObjectName("heading")
        layout.addWidget(hdr)

        self.schedule_table = QTableWidget(w)
        self.schedule_table.setColumnCount(6)
        self.schedule_table.setHorizontalHeaderLabels(["Class / Section", "Section ID", "Time Slot", "Room", "Type", "Action"])
        self.schedule_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.schedule_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.schedule_table.verticalHeader().setVisible(False)
        layout.addWidget(self.schedule_table)

        return w

    def _create_queue_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        hdr_row = QHBoxLayout()
        hdr = QLabel("Offline Attendance Dispatch Queue", w)
        hdr.setObjectName("heading")
        hdr_row.addWidget(hdr)
        hdr_row.addStretch()

        self.flush_queue_btn = QPushButton("Flush Offline Queue to Server", w)
        self.flush_queue_btn.clicked.connect(self._on_flush_queue)
        hdr_row.addWidget(self.flush_queue_btn)
        layout.addLayout(hdr_row)

        desc = QLabel("Attendance marked while disconnected is safely buffered here in local SQLite.", w)
        layout.addWidget(desc)

        self.queue_table = QTableWidget(w)
        self.queue_table.setColumnCount(6)
        self.queue_table.setHorizontalHeaderLabels(["Record ID", "Session ID", "USN", "Status", "Method", "Marked At"])
        self.queue_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.queue_table.verticalHeader().setVisible(False)
        layout.addWidget(self.queue_table)

        return w

    def _create_settings_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        hdr = QLabel("Edge Artificial Intelligence Configuration", w)
        hdr.setObjectName("heading")
        layout.addWidget(hdr)

        card = QFrame(w)
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(10)

        card_layout.addWidget(QLabel("<b>Bundled Recognition Backbone:</b> InsightFace Buffalo_l (SCRFD 10G + ArcFace ResNet50)", card))
        card_layout.addWidget(QLabel("<b>Mobile Backbone:</b> MobileFaceNet 512-d (w600k_mbf.onnx)", card))
        card_layout.addWidget(QLabel(f"<b>Active Acceleration Device:</b> {getattr(self.engine, 'device', 'CPU')}", card))
        card_layout.addWidget(QLabel(f"<b>Models Directory:</b> {getattr(self.engine, 'models_dir', 'bundled')}", card))
        card_layout.addWidget(QLabel(f"<b>Local SQLite Cache:</b> {self.store.db_path}", card))

        self.emb_count_lbl = QLabel(f"<b>Cached Student Face Embeddings:</b> {self.store.get_all_embeddings_count()} students ready offline", card)
        card_layout.addWidget(self.emb_count_lbl)

        card_layout.addWidget(QLabel(f"<b>Central Server Endpoint:</b> {self.api_client.base_url}", card))

        layout.addWidget(card)
        layout.addStretch()
        return w

    def _on_login_success(self, user_profile):
        self.user_profile = user_profile
        self._switch_to_dashboard(user_profile)

    def _switch_to_dashboard(self, user_profile):
        fac_name = user_profile.get("name") or "Faculty User"
        fac_role = (user_profile.get("role") or "Faculty").capitalize()
        self.fac_sub.setText(f"Logged in: {fac_name} ({fac_role})")
        self.stack.setCurrentIndex(1)
        self._refresh_all_data()

    def _on_logout(self):
        self.store.clear_faculty_session()
        self.user_profile = {}
        self.stack.setCurrentIndex(0)

    def _refresh_all_data(self):
        """Loads sessions and sections from local SQLite cache."""
        cached_sessions = self.store.get_cached_sessions()
        cached_sections = self.store.get_cached_sections()

        # Combine sessions and sections for schedule view
        combined_list = list(cached_sessions)
        existing_sec_ids = {s.get("section_id") for s in cached_sessions}

        for sec in cached_sections:
            sec_id = sec.get("section_id")
            if sec_id not in existing_sec_ids:
                combined_list.append({
                    "session_id": sec_id,
                    "section_id": sec_id,
                    "section_label": sec.get("section_label", f"Section {sec_id}"),
                    "subject_name": f"Assigned Section {sec.get('section_label', '')}",
                    "start_time": "Anytime",
                    "end_time": "",
                    "room": "Campus",
                    "slot_type": "Section Roster"
                })

        self._populate_schedule_table(combined_list)
        self.attendance_view.load_sessions(combined_list)
        self._refresh_queue_table()
        if hasattr(self, "emb_count_lbl"):
            self.emb_count_lbl.setText(f"<b>Cached Student Face Embeddings:</b> {self.store.get_all_embeddings_count()} students ready offline")

    def _populate_schedule_table(self, items):
        self.schedule_table.setRowCount(0)
        for s in items:
            row = self.schedule_table.rowCount()
            self.schedule_table.insertRow(row)

            title = s.get("subject_name") or f"Section {s.get('section_label', '')}"
            sec_lbl = str(s.get("section_label") or s.get("section_id", ""))
            time_str = f"{s.get('start_time', '')} - {s.get('end_time', '')}".strip(" -")
            room_str = str(s.get("room", ""))
            type_str = str(s.get("slot_type", "Regular"))

            self.schedule_table.setItem(row, 0, QTableWidgetItem(title))
            self.schedule_table.setItem(row, 1, QTableWidgetItem(sec_lbl))
            self.schedule_table.setItem(row, 2, QTableWidgetItem(time_str))
            self.schedule_table.setItem(row, 3, QTableWidgetItem(room_str))
            self.schedule_table.setItem(row, 4, QTableWidgetItem(type_str))

            btn = QPushButton("Take Attendance")
            btn.setObjectName("success")
            btn.clicked.connect(lambda _, item=s: self._on_start_class_attendance(item))
            self.schedule_table.setCellWidget(row, 5, btn)

    def _on_start_class_attendance(self, session_data):
        self.tabs.setCurrentIndex(0)
        combo = self.attendance_view.session_combo
        target_sid = session_data.get("session_id") or session_data.get("timetable_id") or session_data.get("section_id")
        for i in range(combo.count()):
            d = combo.itemData(i)
            if d and (d.get("session_id") == target_sid or d.get("section_id") == target_sid):
                combo.setCurrentIndex(i)
                break

    def _on_sync_clicked(self):
        self.header_sync_btn.setEnabled(False)
        self.header_sync_btn.setText("Syncing...")
        self.status_bar.showMessage("Running Full Mobile Setup Sync Pipeline...")

        self.sync_worker = FullSyncWorker(self.api_client, self.store)
        self.sync_worker.progress.connect(lambda pct, msg: self.status_bar.showMessage(f"[{pct}%] {msg}"))
        self.sync_worker.finished.connect(self._on_full_sync_finished)
        self.sync_worker.start()

    def _on_full_sync_finished(self, success, result):
        self.header_sync_btn.setEnabled(True)
        self.header_sync_btn.setText("Sync Central Data (Mobile Pipeline)")

        if success:
            self._refresh_all_data()
            tot = result.get("total_embeddings", 0)
            secs = result.get("sections_count", 0)
            sess = result.get("sessions_count", 0)
            self.status_bar.showMessage(f"Sync complete. {tot} student embeddings cached across {secs} sections.")
            QMessageBox.information(
                self, "Sync Complete",
                f"Successfully completed mobile-style initial setup!\n\n"
                f"• Assigned Sections: {secs}\n"
                f"• Scheduled Classes: {sess}\n"
                f"• Student Face Embeddings: {tot} cached locally for offline edge recognition!"
            )
        else:
            self.status_bar.showMessage("Sync failed. Check server connection.")
            QMessageBox.warning(self, "Sync Failed", f"Could not complete sync:\n{result}")

    def _refresh_queue_table(self):
        pending = self.store.get_pending_queue()
        self.queue_table.setRowCount(0)
        for r in pending:
            row = self.queue_table.rowCount()
            self.queue_table.insertRow(row)
            self.queue_table.setItem(row, 0, QTableWidgetItem(str(r.get("id"))))
            self.queue_table.setItem(row, 1, QTableWidgetItem(str(r.get("session_id"))))
            self.queue_table.setItem(row, 2, QTableWidgetItem(str(r.get("usn"))))
            self.queue_table.setItem(row, 3, QTableWidgetItem(str(r.get("status"))))
            self.queue_table.setItem(row, 4, QTableWidgetItem(str(r.get("method"))))
            self.queue_table.setItem(row, 5, QTableWidgetItem(str(r.get("marked_at"))))

    def _on_flush_queue(self):
        synced, failed = self.api_client.sync_pending_queue(self.store)
        self._refresh_queue_table()
        if synced > 0:
            QMessageBox.information(self, "Queue Flushed", f"Successfully synced {synced} pending records to central server.")
        elif failed > 0:
            QMessageBox.warning(self, "Sync Failed", f"{failed} records could not be synced. Server may still be unreachable.")
        else:
            QMessageBox.information(self, "Queue Empty", "No pending records in offline queue.")

    def _on_attendance_submitted(self):
        self._refresh_queue_table()
