"""
desktop_app/ui/attendance_view.py
Faculty Attendance Workspace.
Performs local multi-photo edge recognition, provides interactive visual verification,
allows manual override of student presence, and syncs attendance to the central Flask server.
Displays faculty sections and automatically loads student face embeddings for offline inference.
"""

import os
import cv2
import numpy as np
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
    QMessageBox, QFrame, QProgressBar, QComboBox, QLineEdit,
    QSplitter, QScrollArea, QCheckBox, QSlider
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QImage, QPixmap, QColor

try:
    from core.matcher import run_classroom_recognition
    from database.local_store import get_local_store
    from network.api_client import get_api_client
except ImportError:
    from ..core.matcher import run_classroom_recognition
    from ..database.local_store import get_local_store
    from ..network.api_client import get_api_client


class RecognitionWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, engine, image_paths, student_roster, threshold):
        super().__init__()
        self.engine = engine
        self.image_paths = image_paths
        self.student_roster = student_roster
        self.threshold = threshold

    def run(self):
        try:
            def cb(pct, msg):
                self.progress.emit(pct, msg)

            result = run_classroom_recognition(
                image_paths=self.image_paths,
                engine=self.engine,
                student_roster=self.student_roster,
                threshold=self.threshold,
                progress_callback=cb
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class AttendanceView(QWidget):
    attendance_submitted = pyqtSignal()

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.store = get_local_store()
        self.api_client = get_api_client()

        self.selected_session_id = None
        self.selected_section_id = None
        self.current_roster = []
        self.selected_photo_paths = []
        self.annotated_images = []
        self.recognition_results = None
        self.student_status_map = {}

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(14)

        # Top Bar: Session & Section Selector
        top_card = QFrame(self)
        top_card.setObjectName("card")
        top_layout = QHBoxLayout(top_card)
        top_layout.setContentsMargins(14, 10, 14, 10)

        top_layout.addWidget(QLabel("Select Class / Section:", top_card))
        self.session_combo = QComboBox(top_card)
        self.session_combo.setMinimumWidth(360)
        self.session_combo.currentIndexChanged.connect(self._on_session_selected)
        top_layout.addWidget(self.session_combo)

        self.sync_btn = QPushButton("Refresh Section Embeddings", top_card)
        self.sync_btn.setObjectName("secondary")
        self.sync_btn.clicked.connect(self._sync_active_section_data)
        top_layout.addWidget(self.sync_btn)

        top_layout.addStretch()

        self.hw_label = QLabel(f"Edge AI: {getattr(self.engine, 'device', 'CPU')}", top_card)
        self.hw_label.setObjectName("badge")
        top_layout.addWidget(self.hw_label)

        main_layout.addWidget(top_card)

        # Middle Area: Splitter between Image Viewer and Attendance Table
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # --- LEFT PANEL: Photo Management & Bounding Box Viewer ---
        left_widget = QWidget(splitter)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(10)

        photo_bar = QHBoxLayout()
        self.add_photo_btn = QPushButton("Add Classroom Photos (1-3)", left_widget)
        self.add_photo_btn.clicked.connect(self._on_add_photos)
        photo_bar.addWidget(self.add_photo_btn)

        self.webcam_btn = QPushButton("Capture Webcam", left_widget)
        self.webcam_btn.setObjectName("secondary")
        self.webcam_btn.clicked.connect(self._on_capture_webcam)
        photo_bar.addWidget(self.webcam_btn)

        self.clear_photos_btn = QPushButton("Clear", left_widget)
        self.clear_photos_btn.setObjectName("danger")
        self.clear_photos_btn.clicked.connect(self._on_clear_photos)
        photo_bar.addWidget(self.clear_photos_btn)

        left_layout.addLayout(photo_bar)

        self.photo_info_lbl = QLabel("No photos selected. Please add 1 to 3 wide classroom photos.", left_widget)
        left_layout.addWidget(self.photo_info_lbl)

        # Image preview scroll area
        self.image_scroll = QScrollArea(left_widget)
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setObjectName("card")
        self.image_lbl = QLabel(self.image_scroll)
        self.image_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_lbl.setText("Classroom photo preview with detected faces will appear here.")
        self.image_scroll.setWidget(self.image_lbl)
        left_layout.addWidget(self.image_scroll)

        # Recognition Controls Bar
        rec_card = QFrame(left_widget)
        rec_card.setObjectName("card")
        rec_layout = QVBoxLayout(rec_card)

        rec_btn_row = QHBoxLayout()
        self.run_rec_btn = QPushButton("Run Edge Recognition", rec_card)
        self.run_rec_btn.setObjectName("success")
        self.run_rec_btn.setMinimumHeight(38)
        self.run_rec_btn.clicked.connect(self._on_run_recognition)
        rec_btn_row.addWidget(self.run_rec_btn)

        # Threshold slider
        threshold_col = QVBoxLayout()
        self.thresh_label = QLabel("Similarity Threshold: 38%", rec_card)
        threshold_col.addWidget(self.thresh_label)
        self.thresh_slider = QSlider(Qt.Orientation.Horizontal, rec_card)
        self.thresh_slider.setRange(20, 70)
        self.thresh_slider.setValue(38)
        self.thresh_slider.valueChanged.connect(lambda val: self.thresh_label.setText(f"Similarity Threshold: {val}%"))
        threshold_col.addWidget(self.thresh_slider)
        rec_btn_row.addLayout(threshold_col)

        rec_layout.addLayout(rec_btn_row)

        self.progress_bar = QProgressBar(rec_card)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        rec_layout.addWidget(self.progress_bar)

        left_layout.addWidget(rec_card)
        splitter.addWidget(left_widget)

        # --- RIGHT PANEL: Roster Verification & Submission ---
        right_widget = QWidget(splitter)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(10)

        # Stats Cards Row
        stats_layout = QHBoxLayout()
        self.stat_total = QLabel("Total: 0", right_widget)
        self.stat_total.setObjectName("card")
        stats_layout.addWidget(self.stat_total)

        self.stat_present = QLabel("Present: 0", right_widget)
        self.stat_present.setStyleSheet("color: #22c55e; font-weight: bold; padding: 6px; background-color: #1e293b; border-radius: 6px;")
        stats_layout.addWidget(self.stat_present)

        self.stat_absent = QLabel("Absent: 0", right_widget)
        self.stat_absent.setStyleSheet("color: #ef4444; font-weight: bold; padding: 6px; background-color: #1e293b; border-radius: 6px;")
        stats_layout.addWidget(self.stat_absent)

        self.stat_unknown = QLabel("Unrecognized: 0", right_widget)
        self.stat_unknown.setStyleSheet("color: #f59e0b; font-weight: bold; padding: 6px; background-color: #1e293b; border-radius: 6px;")
        stats_layout.addWidget(self.stat_unknown)

        right_layout.addLayout(stats_layout)

        # Search / Filter Bar
        filter_row = QHBoxLayout()
        self.search_input = QLineEdit(right_widget)
        self.search_input.setPlaceholderText("Filter by USN or Student Name...")
        self.search_input.textChanged.connect(self._apply_table_filter)
        filter_row.addWidget(self.search_input)

        self.filter_combo = QComboBox(right_widget)
        self.filter_combo.addItems(["Show All", "Present Only", "Absent Only"])
        self.filter_combo.currentIndexChanged.connect(self._apply_table_filter)
        filter_row.addWidget(self.filter_combo)

        right_layout.addLayout(filter_row)

        # Attendance Table
        self.table = QTableWidget(right_widget)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Status", "USN", "Student Name", "Confidence", "Method"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        right_layout.addWidget(self.table)

        # Bottom Submission Bar
        bottom_row = QHBoxLayout()
        self.mark_all_btn = QPushButton("Toggle All Present", right_widget)
        self.mark_all_btn.setObjectName("secondary")
        self.mark_all_btn.clicked.connect(self._toggle_all_present)
        bottom_row.addWidget(self.mark_all_btn)

        bottom_row.addStretch()

        self.submit_btn = QPushButton("Submit Finalized Attendance", right_widget)
        self.submit_btn.setObjectName("success")
        self.submit_btn.setMinimumHeight(42)
        self.submit_btn.setMinimumWidth(220)
        self.submit_btn.clicked.connect(self._on_submit_attendance)
        bottom_row.addWidget(self.submit_btn)

        right_layout.addLayout(bottom_row)
        splitter.addWidget(right_widget)

        splitter.setSizes([550, 650])
        main_layout.addWidget(splitter)

    def load_sessions(self, sessions_list=None):
        """
        Populates the session/class selector with:
        1. All scheduled sessions
        2. All assigned sections for this faculty
        """
        self.session_combo.blockSignals(True)
        self.session_combo.clear()

        sessions = sessions_list or self.store.get_cached_sessions()
        sections = self.store.get_cached_sections()

        added_section_ids = set()

        # 1. Add scheduled sessions
        if sessions:
            for s in sessions:
                sid = s.get("session_id") or s.get("timetable_id")
                sec_id = s.get("section_id")
                if sec_id:
                    added_section_ids.add(sec_id)
                sub_name = s.get("subject_name") or "Class"
                sec_lbl = s.get("section_label") or (f"Sec {sec_id}" if sec_id else "")
                start_t = s.get("start_time") or ""
                label = f"📅 {sub_name} - {sec_lbl} ({start_t})"
                self.session_combo.addItem(label, s)

        # 2. Add assigned sections (even if no specific timetable entry for today)
        if sections:
            for sec in sections:
                sec_id = sec.get("section_id")
                sec_lbl = sec.get("section_label") or f"Section {sec_id}"
                sem = sec.get("sem_number", "")
                sem_str = f"Sem {sem} - " if sem else ""
                label = f"👥 {sem_str}{sec_lbl} (Assigned Section)"
                item_data = {
                    "session_id": sec_id,
                    "section_id": sec_id,
                    "section_label": sec_lbl,
                    "subject_name": f"{sem_str}{sec_lbl}"
                }
                self.session_combo.addItem(label, item_data)

        if self.session_combo.count() == 0:
            # Fallback: check if any student embeddings exist without section link
            all_emb = self.store.get_section_embeddings(None)
            if all_emb:
                self.session_combo.addItem(f"👥 All Enrolled Students ({len(all_emb)} students)", {"section_id": None, "session_id": 1})
            else:
                self.session_combo.addItem("No classes found. Click 'Sync Central Data' to import.", None)

        self.session_combo.blockSignals(False)

        # Automatically select first valid item and load its roster
        if self.session_combo.count() > 0:
            self._on_session_selected(0)

    def _on_session_selected(self, index):
        if index < 0:
            return
        session_data = self.session_combo.itemData(index)
        if not session_data:
            return

        self.selected_session_id = session_data.get("session_id") or session_data.get("timetable_id") or 1
        self.selected_section_id = session_data.get("section_id")

        self._load_cached_roster_for_section()

    def _load_cached_roster_for_section(self):
        """Loads cached student embeddings and names from local SQLite."""
        self.current_roster = self.store.get_section_embeddings(self.selected_section_id)

        # If 0 found for specific section, try loading all available cached students
        if not self.current_roster and self.selected_section_id is not None:
            all_students = self.store.get_section_embeddings(None)
            if all_students:
                self.current_roster = all_students

        self.student_status_map = {}
        for s in self.current_roster:
            self.student_status_map[s["student_id"]] = {
                "status": "absent",
                "score": 0.0,
                "method": "not_marked"
            }

        self._populate_table()
        self._update_stats()

    def _sync_active_section_data(self):
        """Syncs the section's student roster and embeddings from central Flask server."""
        self.sync_btn.setEnabled(False)
        self.sync_btn.setText("Syncing...")

        success, students = self.api_client.fetch_section_embeddings(self.selected_section_id)
        self.sync_btn.setEnabled(True)
        self.sync_btn.setText("Refresh Section Embeddings")

        if success and students:
            self.store.cache_student_embeddings(self.selected_section_id, students)
            self._load_cached_roster_for_section()
            QMessageBox.information(
                self, "Sync Successful",
                f"Downloaded {len(students)} student face embeddings for this class.\nReady for offline edge recognition!"
            )
        else:
            QMessageBox.warning(self, "Sync Notice", f"Response from server: {students}")

    def _on_add_photos(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Classroom Photos", "", "Image Files (*.jpg *.jpeg *.png *.webp)"
        )
        if files:
            self.selected_photo_paths = (self.selected_photo_paths + files)[:3]
            self.photo_info_lbl.setText(f"{len(self.selected_photo_paths)} classroom photo(s) selected.")
            self._display_first_image(self.selected_photo_paths[0])

    def _on_capture_webcam(self):
        try:
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                QMessageBox.warning(self, "Webcam Error", "No USB or integrated webcam detected.")
                return

            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                tmp_path = os.path.join(self.store.db_path, "..", "webcam_capture.jpg")
                tmp_path = os.path.abspath(tmp_path)
                cv2.imwrite(tmp_path, frame)
                self.selected_photo_paths = [tmp_path]
                self.photo_info_lbl.setText("1 webcam capture ready.")
                self._display_first_image(tmp_path)
            else:
                QMessageBox.warning(self, "Capture Failed", "Could not read frame from webcam.")
        except Exception as e:
            QMessageBox.critical(self, "Camera Error", str(e))

    def _on_clear_photos(self):
        self.selected_photo_paths = []
        self.annotated_images = []
        self.photo_info_lbl.setText("Photos cleared.")
        self.image_lbl.setText("Classroom photo preview with detected faces will appear here.")
        self.image_lbl.setPixmap(QPixmap())

    def _display_first_image(self, path):
        pix = QPixmap(path)
        if not pix.isNull():
            self.image_lbl.setPixmap(pix.scaled(
                self.image_scroll.width() - 20, 480,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))

    def _on_run_recognition(self):
        if not self.selected_photo_paths:
            QMessageBox.warning(self, "No Photos", "Please add at least 1 classroom photo or webcam snapshot.")
            return

        if not self.current_roster:
            QMessageBox.warning(
                self, "Empty Roster",
                "No student face embeddings cached for this section.\nClick 'Sync Central Data' or 'Refresh Section Embeddings' first."
            )
            return

        if not self.engine or not self.engine.is_initialized:
            self.progress_bar.setValue(10)
            self.progress_bar.setFormat("Initializing Edge AI Models...")
            if not self.engine.initialize():
                QMessageBox.critical(self, "Engine Error", "Failed to initialize local InsightFace model.")
                return

        self.run_rec_btn.setEnabled(False)
        threshold = self.thresh_slider.value() / 100.0

        self.worker = RecognitionWorker(
            engine=self.engine,
            image_paths=self.selected_photo_paths,
            student_roster=self.current_roster,
            threshold=threshold
        )
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.finished.connect(self._on_recognition_finished)
        self.worker.error.connect(self._on_recognition_error)
        self.worker.start()

    def _on_worker_progress(self, pct, msg):
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(msg)

    def _on_recognition_finished(self, results):
        self.run_rec_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("Edge Recognition Complete!")

        self.recognition_results = results
        self.annotated_images = results.get("annotated_images", [])

        if self.annotated_images:
            bgr = self.annotated_images[0]
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            bytes_per_line = ch * w
            qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            pix = QPixmap.fromImage(qimg)
            self.image_lbl.setPixmap(pix.scaled(
                self.image_scroll.width() - 20, 520,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))

        matched = results.get("matched", [])
        for m in matched:
            sid = m["student_id"]
            if sid in self.student_status_map:
                self.student_status_map[sid] = {
                    "status": "present",
                    "score": m["score"],
                    "method": "face_recognition"
                }

        self._populate_table()
        self._update_stats()

        total_det = results.get("total_faces_detected", 0)
        matched_count = len(matched)
        unrecognized_count = len(results.get("unrecognized_faces", []))

        QMessageBox.information(
            self, "Edge Recognition Results",
            f"Detected: {total_det} face(s)\n"
            f"Recognized Students: {matched_count}\n"
            f"Unrecognized Faces: {unrecognized_count}\n\n"
            "Review the list and make any manual adjustments before submitting."
        )

    def _on_recognition_error(self, err_msg):
        self.run_rec_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Error")
        QMessageBox.critical(self, "Recognition Failed", f"Edge recognition error:\n{err_msg}")

    def _populate_table(self):
        self.table.setRowCount(0)
        search = self.search_input.text().strip().lower()
        filter_opt = self.filter_combo.currentText()

        for s in self.current_roster:
            sid = s["student_id"]
            usn = s.get("usn", "")
            name = s.get("name", "")
            state = self.student_status_map.get(sid, {"status": "absent", "score": 0.0, "method": "not_marked"})

            if search and (search not in usn.lower() and search not in name.lower()):
                continue
            if filter_opt == "Present Only" and state["status"] != "present":
                continue
            if filter_opt == "Absent Only" and state["status"] == "present":
                continue

            row_idx = self.table.rowCount()
            self.table.insertRow(row_idx)

            cb = QCheckBox()
            cb.setChecked(state["status"] == "present")
            cb.stateChanged.connect(lambda chk, s_id=sid: self._on_checkbox_toggled(s_id, chk))
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row_idx, 0, cb_widget)

            usn_item = QTableWidgetItem(usn)
            usn_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row_idx, 1, usn_item)

            name_item = QTableWidgetItem(name)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row_idx, 2, name_item)

            score_val = state["score"]
            score_text = f"{int(score_val * 100)}%" if score_val > 0 else "-"
            score_item = QTableWidgetItem(score_text)
            score_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if score_val >= 0.50:
                score_item.setForeground(QColor("#22c55e"))
            elif score_val >= 0.35:
                score_item.setForeground(QColor("#38bdf8"))
            else:
                score_item.setForeground(QColor("#94a3b8"))
            score_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row_idx, 3, score_item)

            method_text = "Face AI" if state["method"] == "face_recognition" else ("Manual" if state["status"] == "present" else "-")
            method_item = QTableWidgetItem(method_text)
            method_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            method_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row_idx, 4, method_item)

    def _on_checkbox_toggled(self, student_id, check_state):
        is_checked = (check_state == 2 or check_state == Qt.CheckState.Checked.value)
        if student_id in self.student_status_map:
            self.student_status_map[student_id]["status"] = "present" if is_checked else "absent"
            if is_checked and self.student_status_map[student_id]["method"] == "not_marked":
                self.student_status_map[student_id]["method"] = "manual_individual"
        self._update_stats()

    def _apply_table_filter(self):
        self._populate_table()

    def _toggle_all_present(self):
        all_present = all(v["status"] == "present" for v in self.student_status_map.values())
        new_status = "absent" if all_present else "present"
        for sid in self.student_status_map:
            self.student_status_map[sid]["status"] = new_status
            if new_status == "present" and self.student_status_map[sid]["method"] == "not_marked":
                self.student_status_map[sid]["method"] = "manual_batch"
        self._populate_table()
        self._update_stats()

    def _update_stats(self):
        total = len(self.current_roster)
        present = sum(1 for v in self.student_status_map.values() if v["status"] == "present")
        absent = total - present
        unknown = len(self.recognition_results.get("unrecognized_faces", [])) if self.recognition_results else 0

        self.stat_total.setText(f"Total: {total}")
        self.stat_present.setText(f"Present: {present}")
        self.stat_absent.setText(f"Absent: {absent}")
        self.stat_unknown.setText(f"Unrecognized: {unknown}")

    def _on_submit_attendance(self):
        if not self.selected_session_id:
            QMessageBox.warning(self, "No Session", "Please select a valid session before submitting.")
            return

        records = []
        for s in self.current_roster:
            sid = s["student_id"]
            state = self.student_status_map.get(sid, {"status": "absent", "score": None, "method": "manual"})
            records.append({
                "session_id": self.selected_session_id,
                "student_id": sid,
                "usn": s.get("usn", ""),
                "status": state["status"],
                "method": state["method"],
                "match_score": state["score"] if state["score"] > 0 else None
            })

        self.submit_btn.setEnabled(False)
        self.submit_btn.setText("Submitting...")

        success, res = self.api_client.submit_attendance(records)

        self.submit_btn.setEnabled(True)
        self.submit_btn.setText("Submit Finalized Attendance")

        if success:
            QMessageBox.information(
                self, "Attendance Recorded",
                f"Successfully committed attendance for Session #{self.selected_session_id} to Central Server!"
            )
            self.attendance_submitted.emit()
        else:
            self.store.queue_attendance(records)
            QMessageBox.warning(
                self, "Saved to Offline Queue",
                f"Could not reach central server ({res}).\n\nAttendance has been safely saved to your local offline queue and will automatically sync when internet reconnects."
            )
            self.attendance_submitted.emit()
