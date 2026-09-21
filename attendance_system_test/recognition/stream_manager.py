"""
attendance_system/recognition/stream_manager.py
Manages multiple RTSP/camera recognition streams.
Each active session gets its own recognition thread.
Provides MJPEG streaming for browser display.
"""

import os
import time
import threading
import logging
from datetime import datetime, timedelta
from collections import defaultdict

import cv2
import numpy as np

from config import Config
from recognition.utils import (
    bbox_iou,
    bbox_center,
    point_inside_box,
    compute_grid_cells,
)

logger = logging.getLogger(__name__)


# ============================================
# Frame Grabber (Threaded camera reader)
# ============================================

# class FrameGrabber:
#     """Threaded frame grabber that always holds the latest frame."""

#     def __init__(self, source, prefer_width=1280, prefer_height=720):
#         self.source = source
#         self.cap = None
#         self.frame = None
#         self.timestamp = 0.0
#         self.lock = threading.Lock()
#         self.stop_event = threading.Event()
#         self.prefer_width = prefer_width
#         self.prefer_height = prefer_height
#         self.thread = None
#         self.is_running = False
#         self._http_resp = None   

#     def _open(self):
#         """Open video capture or initialize HTTP streaming."""
#         self.is_http = isinstance(self.source, str) and self.source.lower().startswith(("http://", "https://"))
#         if self.is_http:
#             # Test HTTP connection
#             import requests
#             try:
#                 resp = requests.get(str(self.source), stream=True, timeout=1.5)
#                 ok = resp.status_code == 200
#                 resp.close()          # NEW — this was only a health check, don't hold the socket open
#                 return ok
#             except Exception as e:
#                 logger.warning(f"HTTP stream probe failed for {self.source}: {e}")
#                 return False
#             return False

#         try:
#             if isinstance(self.source, int):
#                 if os.name == "nt":
#                     self.cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
#                 else:
#                     self.cap = cv2.VideoCapture(self.source)
#             else:
#                 self.cap = cv2.VideoCapture(str(self.source))

#             if self.cap is None or not self.cap.isOpened():
#                 return False

#             # Set preferred resolution
#             try:
#                 self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.prefer_width)
#                 self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.prefer_height)
#                 self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
#             except Exception:
#                 pass

#             # Test read
#             start = time.time()
#             while time.time() - start < 3.0:
#                 ret, frame = self.cap.read()
#                 if ret and frame is not None:
#                     with self.lock:
#                         self.frame = frame
#                         self.timestamp = time.time()
#                     return True
#                 time.sleep(0.05)

#             return False
#         except Exception as e:
#             logger.error(f"FrameGrabber._open error: {e}")
#             return False

#     def start(self):
#         """Start the grabber thread."""
#         if not self._open():
#             logger.error(f"Cannot open source: {self.source}")
#             return False
#         self.stop_event.clear()
#         self.is_running = True
#         target_fn = self._http_loop if getattr(self, "is_http", False) else self._loop
#         self.thread = threading.Thread(target=target_fn, daemon=True)
#         self.thread.start()
#         logger.info(f"FrameGrabber started: {self.source}")
#         return True

#     def _http_loop(self):
#         """
#         Pure-Python HTTP MJPEG stream reader.
#         Reads multipart JPEG frames delimited by SOI (0xFF 0xD8) and EOI (0xFF 0xD9).
#         Bypasses OpenCV's C libavformat backend to completely eliminate assertion crashes
#         (e.g., 'libavformat/utils.c:882') and avoids deadlocking Flask threads.
#         """
#         import requests
#         while not self.stop_event.is_set():
#             try:
#                 resp = requests.get(str(self.source), stream=True, timeout=5.0)
#                 self._http_resp = resp 
#                 if resp.status_code != 200:
#                     time.sleep(0.5)
#                     continue

#                 bytes_buf = bytes()
#                 for chunk in resp.iter_content(chunk_size=4096):
#                     if self.stop_event.is_set():
#                         break
#                     if not chunk:
#                         continue
#                     bytes_buf += chunk
#                     a = bytes_buf.find(b'\xff\xd8')
#                     b = bytes_buf.find(b'\xff\xd9')
#                     if a != -1 and b != -1:
#                         if a < b:
#                             jpg = bytes_buf[a:b+2]
#                             bytes_buf = bytes_buf[b+2:]
#                             try:
#                                 frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
#                                 if frame is not None:
#                                     with self.lock:
#                                         self.frame = frame
#                                         self.timestamp = time.time()
#                             except Exception:
#                                 pass
#                         else:
#                             bytes_buf = bytes_buf[a:]
#                     resp.close()
#             except Exception as e:
#                 logger.debug(f"HTTP FrameGrabber reconnecting: {e}")
#                 time.sleep(0.3)
#             finally:
#                 self._http_resp = None 

#     def _loop(self):
#         """Continuously grab frames from VideoCapture (RTSP / USB Camera)."""
#         while not self.stop_event.is_set():
#             try:
#                 # Flush buffer
#                 if hasattr(self.cap, "grab"):
#                     for _ in range(2):
#                         self.cap.grab()
#                 ret, frame = self.cap.read()
#                 if not ret or frame is None:
#                     time.sleep(0.01)
#                     continue
#                 with self.lock:
#                     self.frame = frame
#                     self.timestamp = time.time()
#             except Exception:
#                 time.sleep(0.01)

#     def get(self):
#         """Get latest frame. Returns (frame_copy, timestamp) or (None, 0)."""
#         with self.lock:
#             if self.frame is None:
#                 return None, 0.0
#             return self.frame.copy(), self.timestamp

#     def stop(self):
#         """Stop the grabber."""
#         self.stop_event.set()
#         self.is_running = False
#         # ESP32's /stream endpoint only serves one client at a time — force-close
#         # any in-flight HTTP connection now instead of waiting for the background
#         # thread to notice, or the next session's grabber can never connect.
#         if self._http_resp is not None:
#             try:
#                 self._http_resp.close()
#             except Exception:
#                 pass
#         time.sleep(0.05)
#         try:
#             if self.cap is not None:
#                 self.cap.release()
#         except Exception:
#             pass
#         logger.info(f"FrameGrabber stopped: {self.source}")

class FrameGrabber:
    """Threaded frame grabber that always holds the latest frame."""

    def __init__(self, source, prefer_width=1280, prefer_height=720):
        self.source = source
        self.cap = None
        self.frame = None
        self.timestamp = 0.0
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.prefer_width = prefer_width
        self.prefer_height = prefer_height
        self.thread = None
        self.is_running = False
        self._http_resp = None   # tracks the live HTTP connection so stop() can close it

    def _open(self):
        """Open video capture or initialize HTTP streaming."""
        self.is_http = isinstance(self.source, str) and self.source.lower().startswith(("http://", "https://"))
        if self.is_http:
            import requests
            try:
                resp = requests.get(str(self.source), stream=True, timeout=1.5)
                ok = resp.status_code == 200
                resp.close()
                return ok
            except Exception as e:
                logger.warning(f"HTTP stream probe failed for {self.source}: {e}")
                return False

        try:
            if isinstance(self.source, int):
                if os.name == "nt":
                    self.cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
                else:
                    self.cap = cv2.VideoCapture(self.source)
            else:
                self.cap = cv2.VideoCapture(str(self.source))

            if self.cap is None or not self.cap.isOpened():
                return False

            try:
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.prefer_width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.prefer_height)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass

            start = time.time()
            while time.time() - start < 3.0:
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    with self.lock:
                        self.frame = frame
                        self.timestamp = time.time()
                    return True
                time.sleep(0.05)

            return False
        except Exception as e:
            logger.error(f"FrameGrabber._open error: {e}")
            return False

    def start(self):
        """Start the grabber thread."""
        if not self._open():
            logger.error(f"Cannot open source: {self.source}")
            return False
        self.stop_event.clear()
        self.is_running = True
        target_fn = self._http_loop if getattr(self, "is_http", False) else self._loop
        self.thread = threading.Thread(target=target_fn, daemon=True)
        self.thread.start()
        logger.info(f"FrameGrabber started: {self.source}")
        return True

    def _http_loop(self):
        """
        Pure-Python HTTP MJPEG stream reader.
        Reads multipart JPEG frames delimited by SOI (0xFF 0xD8) and EOI (0xFF 0xD9).
        """
        import requests
        while not self.stop_event.is_set():
            try:
                resp = requests.get(str(self.source), stream=True, timeout=5.0)
                self._http_resp = resp
                if resp.status_code != 200:
                    resp.close()
                    time.sleep(0.5)
                    continue

                bytes_buf = bytes()
                for chunk in resp.iter_content(chunk_size=4096):
                    if self.stop_event.is_set():
                        break
                    if not chunk:
                        continue
                    bytes_buf += chunk
                    a = bytes_buf.find(b'\xff\xd8')
                    b = bytes_buf.find(b'\xff\xd9')
                    if a != -1 and b != -1:
                        if a < b:
                            jpg = bytes_buf[a:b+2]
                            bytes_buf = bytes_buf[b+2:]
                            try:
                                frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                                if frame is not None:
                                    with self.lock:
                                        self.frame = frame
                                        self.timestamp = time.time()
                            except Exception:
                                pass
                        else:
                            bytes_buf = bytes_buf[a:]
                resp.close()
            except Exception as e:
                logger.debug(f"HTTP FrameGrabber reconnecting: {e}")
                time.sleep(0.3)
            finally:
                self._http_resp = None

    def _loop(self):
        """Continuously grab frames from VideoCapture (RTSP / USB Camera)."""
        while not self.stop_event.is_set():
            try:
                if hasattr(self.cap, "grab"):
                    for _ in range(2):
                        self.cap.grab()
                ret, frame = self.cap.read()
                if not ret or frame is None:
                    time.sleep(0.01)
                    continue
                with self.lock:
                    self.frame = frame
                    self.timestamp = time.time()
            except Exception:
                time.sleep(0.01)

    def get(self):
        """Get latest frame. Returns (frame_copy, timestamp) or (None, 0)."""
        with self.lock:
            if self.frame is None:
                return None, 0.0
            return self.frame.copy(), self.timestamp

    def stop(self):
        """Stop the grabber."""
        self.stop_event.set()
        self.is_running = False
        if self._http_resp is not None:
            try:
                self._http_resp.close()
            except Exception:
                pass
        time.sleep(0.05)
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:
            pass
        logger.info(f"FrameGrabber stopped: {self.source}")


# ============================================
# Recognition Thread (per session)
# ============================================

class RecognitionThread:
    """
    Runs attendance recognition (Face-Only, Fingerprint-Only, or Dual Mode) for a session.
    Marks attendance in the database.
    Provides annotated frames for MJPEG streaming.
    """

    def __init__(self, session_id, rtsp_url, section_id, engine,
                 liveness_checker, db_pool, mode="FACE_ONLY", camera_id=None):
        self.session_id = session_id
        self.rtsp_url = rtsp_url
        self.section_id = section_id
        self.engine = engine
        self.liveness_checker = liveness_checker
        self.db_pool = db_pool
        self.mode = (mode or "FACE_ONLY").upper()
        self.camera_id = camera_id

        self.grabber = None
        self.thread = None
        self.fp_thread = None
        self.stop_event = threading.Event()
        self.is_running = False
        self.status = "idle"  # idle, starting, running, stopping, error

        # Dual Mode Target State
        self._dual_target = None  # dict with student_id, usn, name, fingerprint_score, expires_at
        self._dual_lock = threading.Lock()
        self._last_scan_seq = -1

        # Latest annotated frame (for MJPEG streaming)
        self._annotated_frame = None
        self._annotated_lock = threading.Lock()

        # Attendance tracking
        self._marked_students = {}  # student_id -> last_marked_timestamp
        self._cooldown_seconds = Config.ATTENDANCE_COOLDOWN_MIN * 60
        self._allowed_students = set()

        # Focus grid tracking
        self._suppressed_rois = []  # (bbox, timestamp)
        self._processed_sids = {}   # student_id -> timestamp

        # Stats
        self.stats = {
            "total_faces_detected": 0,
            "total_recognized": 0,
            "total_spoofs": 0,
            "students_present": set(),
            "start_time": None,
            "fps": 0.0,
        }

        # Recognition log (last N events)
        self._log = []
        self._log_lock = threading.Lock()
        self._max_log = 200

    def start(self):
        """Start recognition workers for this session according to self.mode."""
        if self.is_running:
            return True

        self.status = "starting"
        self._load_allowed_students()
        self.stop_event.clear()
        self.is_running = True
        self.stats["start_time"] = datetime.now()

        # 1. Face processing worker (FACE_ONLY or DUAL_MODE)
        if self.mode in ("FACE_ONLY", "DUAL_MODE"):
            if self.rtsp_url:
                self.grabber = FrameGrabber(self.rtsp_url)
                if not self.grabber.start():
                    logger.warning(f"Could not open stream {self.rtsp_url} for mode {self.mode}")
                    self.status = "error"
                    self.is_running = False
                    return False
            self.thread = threading.Thread(target=self._recognition_loop, daemon=True)
            self.thread.start()

        # 2. Fingerprint poller worker (FINGERPRINT_ONLY or DUAL_MODE)
        if self.mode in ("FINGERPRINT_ONLY", "DUAL_MODE") and self.camera_id:
            self.fp_thread = threading.Thread(target=self._fingerprint_loop, daemon=True)
            self.fp_thread.start()

        self.status = "running"
        logger.info(f"Recognition started for session {self.session_id} in mode {self.mode}")
        return True

    def _load_allowed_students(self):
        """Cache students allowed for this stream's section or session."""
        conn = None
        cursor = None
        try:
            import core.db as core_db
            if self.db_pool and hasattr(self.db_pool, 'get_connection'):
                conn = self.db_pool.get_connection()
            elif core_db.connection_pool and hasattr(core_db.connection_pool, 'get_connection'):
                conn = core_db.connection_pool.get_connection()
            else:
                conn = core_db.get_db()

            cursor = conn.cursor(dictionary=True, buffered=True)
            cursor.execute(
                """
                SELECT s.id 
                FROM students s
                JOIN attendance a ON a.student_id = s.id
                WHERE a.session_id = %s AND s.section_id = %s
                UNION
                SELECT id FROM students WHERE section_id = %s
                """,
                (self.session_id, self.section_id, self.section_id)
            )
            self._allowed_students = {row["id"] for row in cursor.fetchall()}
        except Exception as e:
            logger.error("Failed to load section students for stream %s: %s", self.session_id, e)
            self._allowed_students = set()
        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def stop(self):
        """Stop recognition."""
        self.status = "stopping"
        self.stop_event.set()
        self.is_running = False
        time.sleep(0.1)
        if self.grabber:
            self.grabber.stop()
        with self._dual_lock:
            self._dual_target = None
        self.status = "idle"
        logger.info(f"Recognition stopped for session {self.session_id}")

    def get_annotated_frame(self):
        """Get latest annotated frame as JPEG bytes for MJPEG streaming."""
        with self._annotated_lock:
            if self._annotated_frame is None:
                # If in FINGERPRINT_ONLY mode and no camera stream, render a biometric status banner
                if self.mode == "FINGERPRINT_ONLY":
                    blank = np.zeros((360, 640, 3), dtype=np.uint8)
                    cv2.putText(blank, "BIOMETRIC SENSOR ACTIVE", (140, 140),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 120), 2)
                    cv2.putText(blank, "Place finger on hardware sensor...", (110, 200),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)
                    if self._log:
                        last_event = self._log[-1]["message"][:40]
                        cv2.putText(blank, f"Last: {last_event}", (50, 290),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
                    ret, jpeg = cv2.imencode(".jpg", blank, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    return jpeg.tobytes() if ret else None
                return None
            ret, jpeg = cv2.imencode(".jpg", self._annotated_frame, [
                cv2.IMWRITE_JPEG_QUALITY, 70
            ])
            return jpeg.tobytes() if ret else None

    def get_log(self, last_n=50):
        """Get recent recognition log entries."""
        with self._log_lock:
            return list(self._log[-last_n:])

    def _add_log(self, event_type, message, student_id=None, usn=None, score=None):
        """Add a log entry."""
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "type": event_type,
            "message": message,
            "student_id": student_id,
            "usn": usn,
            "score": score,
        }
        with self._log_lock:
            self._log.append(entry)
            if len(self._log) > self._max_log:
                self._log = self._log[-self._max_log:]

    def _mark_attendance_db(self, student_id, usn, score=None, liveness_score=None,
                            fingerprint_score=None, method="face_recognition"):
        """Mark a student present in the attendance table atomically."""
        if student_id not in self._allowed_students:
            logger.warning(f"Student {student_id} ({usn}) not in allowed list for session {self.session_id}")
            return False

        now = time.time()

        # Check cooldown
        last = self._marked_students.get(student_id, 0)
        if now - last < self._cooldown_seconds:
            return False

        conn = None
        cursor = None
        try:
            import core.db as core_db
            if self.db_pool and hasattr(self.db_pool, 'get_connection'):
                conn = self.db_pool.get_connection()
            elif core_db.connection_pool and hasattr(core_db.connection_pool, 'get_connection'):
                conn = core_db.connection_pool.get_connection()
            else:
                conn = core_db.get_db()

            cursor = conn.cursor(dictionary=True, buffered=True)

            # Atomic Upsert into attendance table
            cursor.execute(
                """
                INSERT INTO attendance 
                    (session_id, student_id, usn, status, method, recognition_score, liveness_score, fingerprint_score, marked_at)
                VALUES (%s, %s, %s, 'present', %s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    status = 'present',
                    method = VALUES(method),
                    recognition_score = VALUES(recognition_score),
                    liveness_score = VALUES(liveness_score),
                    fingerprint_score = VALUES(fingerprint_score),
                    marked_at = NOW()
                """,
                (
                    self.session_id, student_id, usn,
                    method,
                    float(score) if score is not None else None,
                    float(liveness_score) if liveness_score is not None else None,
                    float(fingerprint_score) if fingerprint_score is not None else None,
                )
            )
            conn.commit()
            cursor.close()
            conn.close()

            self._marked_students[student_id] = now
            self.stats["students_present"].add(student_id)

            name = self.engine.get_student_name(student_id)
            score_str = f"{score:.3f}" if score is not None else (f"conf={fingerprint_score}" if fingerprint_score is not None else "N/A")
            self._add_log(
                "present", f"Marked present ({method}): {name} ({usn}) [{score_str}]",
                student_id=student_id, usn=usn, score=score or fingerprint_score
            )
            logger.info(
                f"Session {self.session_id}: Marked {usn} ({name}) present via {method} ({score_str})"
            )
            return True

        except Exception as e:
            logger.error(f"mark_attendance error for student {student_id}: {e}")
            if conn:
                try:
                    conn.rollback()
                    conn.close()
                except Exception:
                    pass
            return False
    def _log_spoof(self, liveness_score, camera_id=None):
        """Log a spoof attempt."""
        try:
            conn = self.db_pool.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO spoof_attempts
                    (session_id, camera_id, liveness_score, detected_at)
                VALUES (%s, %s, %s, NOW())
                """,
                (self.session_id, camera_id, liveness_score)
            )
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.debug(f"log_spoof error: {e}")

    def _fingerprint_loop(self):
        """
        Background poller for fingerprint events from ESP32 device.
        Used for FINGERPRINT_ONLY and DUAL_MODE.
        """
        if not self.camera_id:
            return

        from recognition.fingerprint_service import lookup_student_by_template, _device_base_url
        import requests

        # Get device control base URL from camera record
        base_url = None
        try:
            import core.db as core_db
            if self.db_pool and hasattr(self.db_pool, 'get_connection'):
                conn = self.db_pool.get_connection()
            else:
                if getattr(core_db, 'connection_pool', None) is None:
                    core_db.init_db_pool()
                conn = core_db.connection_pool.get_connection()

            cursor = conn.cursor(dictionary=True, buffered=True)
            cursor.execute("SELECT rtsp_url FROM cameras WHERE id = %s", (self.camera_id,))
            cam = cursor.fetchone()
            cursor.close()
            conn.close()
            if cam:
                base_url = _device_base_url(cam)
        except Exception as e:
            logger.error(f"Fingerprint poller error getting camera URL: {e}")

        if not base_url:
            logger.warning(f"No control URL for camera {self.camera_id}. Fingerprint poller stopping.")
            return

        logger.info(f"Fingerprint poller active for session {self.session_id} on camera {self.camera_id}")

        # Sync our baseline to whatever the device is currently reporting,
        # so a stale leftover match from a previous session is never
        # re-processed as new the moment this loop starts.
        try:
            primer = requests.get(f"{base_url}/last-scan", timeout=2.0)
            if primer.status_code == 200:
                self._last_scan_seq = primer.json().get("seq", -1)
        except Exception:
            pass

        while not self.stop_event.is_set():
            try:
                resp = requests.get(f"{base_url}/last-scan", timeout=2.0)
                if resp.status_code == 200:
                    data = resp.json()
                    seq = data.get("seq", -1)
                    matched = data.get("matched", False)

                    if matched and seq != self._last_scan_seq:
                        self._last_scan_seq = seq
                        template_id = data.get("id")
                        confidence = data.get("confidence", 0)

                        # Lookup student canonical identity via (camera_id, template_id)
                        stu = lookup_student_by_template(self.camera_id, template_id, db_pool=self.db_pool)
                        if stu:
                            sid = stu["student_id"]
                            usn = stu["usn"]
                            name = stu["name"]

                            # Validate section and eligibility
                            if sid not in self._allowed_students:
                                logger.warning(f"Fingerprint scan for {usn} ({name}) rejected: not enrolled in this session/section")
                                self._add_log("warning", f"Fingerprint scan rejected for {name} ({usn}): wrong section/class")
                            elif self.mode == "FINGERPRINT_ONLY":
                                self._mark_attendance_db(
                                    sid, usn, score=None, liveness_score=None,
                                    fingerprint_score=confidence, method="fingerprint"
                                )
                            elif self.mode == "DUAL_MODE":
                                with self._dual_lock:
                                    self._dual_target = {
                                        "student_id": sid,
                                        "usn": usn,
                                        "name": name,
                                        "fingerprint_score": confidence,
                                        "expires_at": time.time() + 10.0
                                    }
                                self._add_log(
                                    "fingerprint",
                                    f"Fingerprint matched: {name} ({usn}). Look at camera within 10s for face verification."
                                )
                        else:
                            logger.warning(f"Fingerprint template {template_id} on camera {self.camera_id} not mapped to any student")
                            self._add_log("fingerprint", f"Unknown fingerprint template #{template_id} scanned on sensor")
                else:
                    self._add_log("device_error", f"Device returned HTTP {resp.status_code} on /last-scan")
            except requests.exceptions.Timeout:
                if not hasattr(self, '_last_conn_err_time') or time.time() - self._last_conn_err_time > 10:
                    self._last_conn_err_time = time.time()
                    logger.warning(f"Device at {base_url} timed out on /last-scan")
                    self._add_log("warning", f"Device at {base_url} is unreachable (Timeout). Ensure PC is on the same Wi-Fi.")
            except requests.exceptions.ConnectionError as ce:
                if not hasattr(self, '_last_conn_err_time') or time.time() - self._last_conn_err_time > 10:
                    self._last_conn_err_time = time.time()
                    logger.warning(f"Cannot connect to device at {base_url}: {ce}")
                    self._add_log("warning", f"Cannot connect to {base_url}. Ensure server PC is connected to ESP32 Wi-Fi.")
            except Exception as e:
                logger.debug(f"Fingerprint poller poll exception: {e}")

            time.sleep(0.5)

    def _recognition_loop(self):
        """Main recognition loop running in a thread."""
        target_period = 1.0 / max(0.1, Config.RECOGNITION_PROCESS_FPS)
        frame_count = 0
        fps_start = time.time()

        while not self.stop_event.is_set():
            if not self.grabber:
                time.sleep(0.05)
                continue

            frame, ts = self.grabber.get()
            if frame is None:
                time.sleep(0.01)
                continue

            now = time.time()
            annotated = frame.copy()
            H, W = annotated.shape[:2]

            # Handle DUAL_MODE target checking
            if self.mode == "DUAL_MODE":
                target = None
                with self._dual_lock:
                    if self._dual_target:
                        if now > self._dual_target["expires_at"]:
                            self._add_log("dual_mode", f"Dual verification window timed out for {self._dual_target['name']}")
                            self._dual_target = None
                        else:
                            target = dict(self._dual_target)

                if target:
                    # Detect faces for targeted O(1) matching only
                    faces = self.engine.detect_faces(frame)
                    remaining = max(0, int(target["expires_at"] - now))
                    cv2.putText(annotated, f"DUAL MODE: {target['name']} ({remaining}s)", (20, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                    for face in faces:
                        x1, y1, x2, y2 = self.engine.get_face_bbox(face)
                        is_match, face_score, _ = self.engine.verify_face_for_student(
                            face, target["student_id"]
                        )

                        if is_match:
                            color = Config.COLOR_GREEN
                            label = f"{target['name']} Dual Verified ✓ ({face_score:.2f})"
                            marked = self._mark_attendance_db(
                                target["student_id"], target["usn"],
                                score=face_score, liveness_score=None,
                                fingerprint_score=target["fingerprint_score"],
                                method="dual_verification"
                            )
                            if marked:
                                with self._dual_lock:
                                    self._dual_target = None
                        else:
                            color = Config.COLOR_ORANGE
                            label = f"Matching {target['name']}... ({face_score:.2f})"

                        cv2.rectangle(annotated, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
                        cv2.putText(annotated, label, (int(x1), max(0, int(y1) - 8)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

                    with self._annotated_lock:
                        self._annotated_frame = annotated
                    time.sleep(target_period)
                    continue
                else:
                    # In DUAL_MODE with NO fingerprint scanned yet:
                    # DO NOT run O(n) face matching or mark attendance!
                    # Detect faces purely to draw a neutral box guiding the student to touch the sensor.
                    faces = self.engine.detect_faces(frame)
                    cv2.putText(annotated, "DUAL MODE: Touch Fingerprint Sensor First", (20, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
                    for face in faces:
                        x1, y1, x2, y2 = self.engine.get_face_bbox(face)
                        cv2.rectangle(annotated, (int(x1), int(y1)), (int(x2), int(y2)), (0, 200, 255), 2)
                        cv2.putText(annotated, "Touch Sensor to Verify", (int(x1), max(0, int(y1) - 8)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)

                    with self._annotated_lock:
                        self._annotated_frame = annotated
                    time.sleep(target_period)
                    continue

            # ---- FACE_ONLY processing (Standard Full Database Matching) ----
            # Anti-spoof/liveness was never completed and is not part of this
            # system — fingerprint is the anti-spoof mechanism instead.
            try:
                results = self.engine.process_frame(frame, liveness_checker=None)
            except Exception as e:
                logger.error(f"process_frame error: {e}")
                time.sleep(0.01)
                continue

            # ---- Handle results & draw ----
            annotated = frame.copy()
            H, W = annotated.shape[:2]

            # Clean expired suppressions
            self._suppressed_rois = [
                (b, t) for (b, t) in self._suppressed_rois
                if (now - t) < Config.UNKNOWN_SUPPRESS_SEC
            ]
            self._processed_sids = {
                s: t for s, t in self._processed_sids.items()
                if (now - t) < Config.PROCESSED_SID_TTL
            }

            unknown_count = 0

            for det in results:
                x1, y1, x2, y2 = det["bbox"]
                state = det["state"]
                student_id = det["student_id"]
                score = det["match_score"]
                name = det["name"]
                usn = det["usn"]
                liveness_score = det.get("liveness_score")

                self.stats["total_faces_detected"] += 1

                if state == "spoof":
                    # Draw red with SPOOF label
                    color = Config.COLOR_RED
                    label = f"SPOOF ({liveness_score:.2f})" if liveness_score else "SPOOF"
                    self.stats["total_spoofs"] += 1
                    self._log_spoof(liveness_score)
                    self._add_log("spoof", f"Spoof detected! score={liveness_score:.3f}")

                elif state == "recognized":
                    self.stats["total_recognized"] += 1

                    if student_id not in self._allowed_students:
                        color = Config.COLOR_ORANGE
                        label = f"{name} (other section)"
                        continue

                    if student_id in self._processed_sids:
                        color = Config.COLOR_WHITE
                        label = f"{name} ✓"
                    else:
                        color = Config.COLOR_GREEN
                        label = f"{name} ({score:.2f})"
                        # Mark attendance
                        marked = self._mark_attendance_db(
                            student_id, usn, score, liveness_score
                        )
                        if marked:
                            self._processed_sids[student_id] = now

                else:  # unknown
                    in_suppressed = any(
                        bbox_iou(det["bbox"], sroi) > 0.25
                        for (sroi, t) in self._suppressed_rois
                    )
                    if in_suppressed:
                        color = Config.COLOR_WHITE
                        label = "Unknown (handled)"
                    else:
                        color = Config.COLOR_RED
                        label = "Unknown"
                        unknown_count += 1

                # Draw bbox and label
                cv2.rectangle(
                    annotated, (int(x1), int(y1)), (int(x2), int(y2)), color, 2
                )
                cv2.putText(
                    annotated, label,
                    (int(x1), max(0, int(y1) - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2
                )

            # ---- Focus pass on unknown-dense grid cells ----
            if unknown_count > 0:
                self._focus_pass(frame, annotated, results, now, W, H)

            # ---- Draw stats overlay ----
            frame_count += 1
            elapsed = time.time() - fps_start
            if elapsed > 2.0:
                self.stats["fps"] = frame_count / elapsed
                frame_count = 0
                fps_start = time.time()

            present_count = len(self.stats["students_present"])
            cv2.rectangle(annotated, (5, 5), (400, 80), (0, 0, 0), -1)
            cv2.putText(
                annotated,
                f"Session {self.session_id} | Present: {present_count} | "
                f"FPS: {self.stats['fps']:.1f}",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1
            )
            cv2.putText(
                annotated,
                f"Spoofs: {self.stats['total_spoofs']} | "
                f"Unknown: {unknown_count}",
                (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1
            )

            # Store annotated frame
            with self._annotated_lock:
                self._annotated_frame = annotated

            # Throttle
            proc_time = time.time() - now
            sleep_time = max(0, target_period - proc_time)
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _focus_pass(self, frame, annotated, results, now, W, H):
        """Run focused recognition on grid cells with unknown faces."""
        unknowns = [d for d in results if d["state"] == "unknown"]
        cells = compute_grid_cells(W, H)

        # Count unknowns per cell
        cell_counts = []
        for (idx, roi) in cells:
            count = sum(
                1 for d in unknowns
                if point_inside_box(bbox_center(d["bbox"]), roi)
            )
            cell_counts.append((count, idx, roi))

        cell_counts.sort(key=lambda x: x[0], reverse=True)

        for count, (ix, iy), roi in cell_counts[:Config.FOCUS_TOP_K]:
            if count <= 0:
                break

            # Check suppression
            skip = any(
                bbox_iou(roi, sroi) > 0.25
                for (sroi, t) in self._suppressed_rois
            )
            if skip:
                continue

            x1, y1, x2, y2 = roi
            margin_w = int((x2 - x1) * Config.FOCUS_MARGIN)
            margin_h = int((y2 - y1) * Config.FOCUS_MARGIN)
            rx1 = max(0, x1 - margin_w)
            ry1 = max(0, y1 - margin_h)
            rx2 = min(W, x2 + margin_w)
            ry2 = min(H, y2 + margin_h)

            crop = frame[ry1:ry2, rx1:rx2].copy()
            if crop.size == 0:
                self._suppressed_rois.append((roi, now))
                continue

            # Upscale
            scale = min(
                1280 / max(1, crop.shape[1]),
                1280 / max(1, crop.shape[0]),
                Config.FOCUS_UPSCALE,
            )
            tw = max(64, int(crop.shape[1] * scale))
            th = max(64, int(crop.shape[0] * scale))
            crop_up = cv2.resize(crop, (tw, th), interpolation=cv2.INTER_LINEAR)

            # Re-detect on upscaled crop
            focus_results = self.engine.process_frame(crop_up, self.liveness_checker)

            any_recognized = False
            sx = (rx2 - rx1) / max(1, crop_up.shape[1])
            sy = (ry2 - ry1) / max(1, crop_up.shape[0])

            for det in focus_results:
                if det["state"] == "recognized":
                    any_recognized = True
                    sid = det["student_id"]
                    usn = det["usn"]
                    score = det["match_score"]
                    liveness = det.get("liveness_score")

                    # Map bbox to full frame
                    bx1, by1, bx2, by2 = det["bbox"]
                    gx1 = int(rx1 + bx1 * sx)
                    gy1 = int(ry1 + by1 * sy)
                    gx2 = int(rx1 + bx2 * sx)
                    gy2 = int(ry1 + by2 * sy)

                    # Draw on annotated
                    cv2.rectangle(
                        annotated, (gx1, gy1), (gx2, gy2),
                        Config.COLOR_WHITE, 2
                    )
                    label = f"{det['name']} {score:.2f} ✓"
                    cv2.putText(
                        annotated, label, (gx1, max(0, gy1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, Config.COLOR_WHITE, 2
                    )

                    # Mark attendance
                    self._mark_attendance_db(sid, usn, score, liveness, method="face_recognition")
                    self._processed_sids[sid] = now

            if not any_recognized:
                self._suppressed_rois.append((roi, now))


# ============================================
# Stream Manager (manages all active sessions)
# ============================================

class StreamManager:
    """
    Manages multiple recognition threads (one per active session).
    Provides start/stop control and MJPEG frame access.
    """

    def __init__(self, engine, max_streams=10):
        self.engine = engine
        self.max_streams = max_streams
        self.liveness_checker = None
        self._streams = {}  # session_id -> RecognitionThread
        self._lock = threading.Lock()

    def init_liveness(self):
        """Initialize the liveness checker."""
        try:
            from recognition.liveness import LivenessChecker
            self.liveness_checker = LivenessChecker()
            self.liveness_checker.initialize()
        except Exception as e:
            logger.warning(f"LivenessChecker initialization skipped: {e}")
            self.liveness_checker = None

    def start_stream(self, session_id, rtsp_url, section_id, db_pool, mode="FACE_ONLY", camera_id=None):
        """
        Start recognition for a session in the specified mode (FACE_ONLY, FINGERPRINT_ONLY, DUAL_MODE).

        Returns: (success: bool, message: str)
        """
        with self._lock:
            if session_id in self._streams:
                stream = self._streams[session_id]
                if stream.is_running:
                    return True, "Stream already running."
                # Clean up old stopped stream
                del self._streams[session_id]

            if len(self._streams) >= self.max_streams:
                return False, f"Max streams ({self.max_streams}) reached."

            # # Initialize liveness if not done
            # if self.liveness_checker is None:
            #     self.init_liveness()

            stream = RecognitionThread(
                session_id=session_id,
                rtsp_url=rtsp_url,
                section_id=section_id,
                engine=self.engine,
                liveness_checker=self.liveness_checker,
                db_pool=db_pool,
                mode=mode,
                camera_id=camera_id,
            )

            if not stream.start():
                return False, f"Cannot start worker for session {session_id} in mode {mode}"

            self._streams[session_id] = stream
            return True, "Stream started."

    def stop_stream(self, session_id):
        """Stop recognition for a session."""
        with self._lock:
            stream = self._streams.get(session_id)
            if stream is None:
                return False, "Stream not found."
            stream.stop()
            del self._streams[session_id]
            return True, "Stream stopped."

    def stop_all(self):
        """Stop all running streams."""
        with self._lock:
            for sid, stream in self._streams.items():
                stream.stop()
            self._streams.clear()

    def get_frame(self, session_id):
        """Get latest annotated JPEG frame for a session (for MJPEG streaming)."""
        stream = self._streams.get(session_id)
        if stream is None:
            return None
        return stream.get_annotated_frame()

    def get_stream_status(self, session_id):
        """Get status info for a session's stream."""
        stream = self._streams.get(session_id)
        if stream is None:
            return {"status": "not_running", "session_id": session_id}
        return {
            "status": stream.status,
            "session_id": session_id,
            "is_running": stream.is_running,
            "stats": {
                "total_faces": stream.stats["total_faces_detected"],
                "recognized": stream.stats["total_recognized"],
                "spoofs": stream.stats["total_spoofs"],
                "present_count": len(stream.stats["students_present"]),
                "fps": round(stream.stats["fps"], 1),
                "start_time": (
                    stream.stats["start_time"].strftime("%H:%M:%S")
                    if stream.stats["start_time"] else None
                ),
            },
        }

    def get_log(self, session_id, last_n=50):
        """Get recognition log for a session."""
        stream = self._streams.get(session_id)
        if stream is None:
            return []
        return stream.get_log(last_n)

    def list_active_streams(self):
        """List all active stream session IDs and their status."""
        with self._lock:
            return {
                sid: self.get_stream_status(sid)
                for sid in self._streams
            }