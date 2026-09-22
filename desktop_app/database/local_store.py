"""
desktop_app/database/local_store.py
SQLite Local Cache and Offline Storage for AttendAI Desktop.
Emulates mobile app's AttendanceDatabase.ts.
Caches faculty profile, assigned sections, assigned subjects, timetable/sessions,
and all student face embeddings for offline edge recognition.
"""

import os
import json
import sqlite3
import logging
import numpy as np

logger = logging.getLogger(__name__)


def get_default_db_path():
    """Returns local database path under user appdata or home folder."""
    app_data = os.getenv("APPDATA") or os.path.expanduser("~")
    data_dir = os.path.join(app_data, "AttendAI_Desktop")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "local_cache.db")


class LocalStore:
    """Local SQLite database manager for offline capability and caching."""

    def __init__(self, db_path=None):
        self.db_path = db_path or get_default_db_path()
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Creates SQLite tables matching mobile schema."""
        with self._get_conn() as conn:
            c = conn.cursor()

            # Key-Value settings (server_url, auth_token, faculty_profile)
            c.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # Cached sections assigned to faculty
            c.execute("""
                CREATE TABLE IF NOT EXISTS cached_sections (
                    section_id INTEGER PRIMARY KEY,
                    section_label TEXT,
                    sem_number INTEGER
                )
            """)

            # Cached subjects assigned to faculty
            c.execute("""
                CREATE TABLE IF NOT EXISTS cached_subjects (
                    subject_id INTEGER PRIMARY KEY,
                    name TEXT,
                    code TEXT
                )
            """)

            # Cached sessions & timetable
            c.execute("""
                CREATE TABLE IF NOT EXISTS cached_sessions (
                    session_id INTEGER PRIMARY KEY,
                    timetable_id INTEGER,
                    section_id INTEGER,
                    section_label TEXT,
                    subject_id INTEGER,
                    subject_name TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    room TEXT,
                    slot_type TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Cached student face embeddings per section
            c.execute("""
                CREATE TABLE IF NOT EXISTS student_embeddings (
                    student_id INTEGER PRIMARY KEY,
                    usn TEXT,
                    name TEXT,
                    section_id INTEGER,
                    embedding BLOB,
                    model_version TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_emb_section ON student_embeddings(section_id)")

            # Offline attendance submission queue
            c.execute("""
                CREATE TABLE IF NOT EXISTS attendance_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    student_id INTEGER,
                    usn TEXT,
                    status TEXT,
                    method TEXT,
                    match_score REAL,
                    marked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    synced INTEGER DEFAULT 0
                )
            """)
            conn.commit()

    # --- Settings API ---

    def set_setting(self, key, value):
        with self._get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
            conn.commit()

    def get_setting(self, key, default=None):
        with self._get_conn() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    def save_faculty_session(self, token, user_dict):
        self.set_setting("auth_token", token)
        self.set_setting("faculty_profile", json.dumps(user_dict))

    def get_faculty_session(self):
        token = self.get_setting("auth_token")
        profile_str = self.get_setting("faculty_profile")
        if token and profile_str:
            try:
                profile = json.loads(profile_str)
                return token, profile
            except Exception:
                return token, None
        return None, None

    def clear_faculty_session(self):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM settings WHERE key IN ('auth_token', 'faculty_profile')")
            conn.commit()

    def wipe_all_local_data(self):
        """Clears all cached sections, subjects, sessions, and embeddings."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM cached_sections")
            conn.execute("DELETE FROM cached_subjects")
            conn.execute("DELETE FROM cached_sessions")
            conn.execute("DELETE FROM student_embeddings")
            conn.commit()

    # --- Sections & Subjects Cache ---

    def cache_sections(self, sections_list):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM cached_sections")
            for s in sections_list:
                conn.execute(
                    "INSERT OR REPLACE INTO cached_sections (section_id, section_label, sem_number) VALUES (?, ?, ?)",
                    (s.get("section_id"), s.get("section_label", ""), s.get("sem_number", 0))
                )
            conn.commit()

    def get_cached_sections(self):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM cached_sections ORDER BY sem_number, section_label").fetchall()
            return [dict(r) for r in rows]

    def cache_subjects(self, subjects_list):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM cached_subjects")
            for s in subjects_list:
                conn.execute(
                    "INSERT OR REPLACE INTO cached_subjects (subject_id, name, code) VALUES (?, ?, ?)",
                    (s.get("subject_id"), s.get("name", ""), s.get("code", ""))
                )
            conn.commit()

    def get_cached_subjects(self):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM cached_subjects ORDER BY name").fetchall()
            return [dict(r) for r in rows]

    # --- Sessions & Timetable Cache ---

    def cache_sessions(self, sessions_list):
        """Caches list of sessions and timetable."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM cached_sessions")
            for s in sessions_list:
                sid = s.get("session_id") or s.get("timetable_id") or 0
                conn.execute("""
                    INSERT OR REPLACE INTO cached_sessions
                    (session_id, timetable_id, section_id, section_label, subject_id,
                     subject_name, start_time, end_time, room, slot_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sid,
                    s.get("timetable_id"),
                    s.get("section_id"),
                    s.get("section_label", ""),
                    s.get("subject_id"),
                    s.get("subject_name", ""),
                    str(s.get("start_time", "")),
                    str(s.get("end_time", "")),
                    s.get("room", ""),
                    s.get("slot_type", "Regular")
                ))
            conn.commit()

    def get_cached_sessions(self):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM cached_sessions ORDER BY start_time").fetchall()
            return [dict(r) for r in rows]

    # --- Student Embeddings Cache ---

    def cache_student_embeddings(self, section_id, students_list):
        """
        Stores student embeddings downloaded from Flask server.
        students_list: list of dicts with keys:
            student_id, usn, name, section_id, embedding (list of floats), model_version
        """
        with self._get_conn() as conn:
            for s in students_list:
                emb = s.get("embedding")
                emb_bytes = None
                if emb is not None:
                    emb_arr = np.asarray(emb, dtype=np.float32)
                    emb_bytes = emb_arr.tobytes()

                conn.execute("""
                    INSERT OR REPLACE INTO student_embeddings
                    (student_id, usn, name, section_id, embedding, model_version, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    s["student_id"],
                    s.get("usn", ""),
                    s.get("name", ""),
                    section_id or s.get("section_id"),
                    emb_bytes,
                    s.get("model_version", "faces_full")
                ))
            conn.commit()
        logger.info(f"Cached {len(students_list)} student embeddings for section {section_id}.")

    def get_section_embeddings(self, section_id=None):
        """Returns list of student dicts for the section with unpacked numpy embeddings."""
        with self._get_conn() as conn:
            if section_id is not None:
                rows = conn.execute(
                    "SELECT * FROM student_embeddings WHERE section_id = ? ORDER BY usn",
                    (section_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM student_embeddings ORDER BY usn"
                ).fetchall()

            students = []
            for r in rows:
                emb = None
                if r["embedding"]:
                    emb = np.frombuffer(r["embedding"], dtype=np.float32)
                students.append({
                    "student_id": r["student_id"],
                    "usn": r["usn"],
                    "name": r["name"],
                    "section_id": r["section_id"],
                    "model_version": r["model_version"],
                    "embedding": emb
                })
            return students

    def get_all_embeddings_count(self):
        with self._get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM student_embeddings").fetchone()
            return row["cnt"] if row else 0

    # --- Attendance Offline Queue ---

    def queue_attendance(self, records):
        """Queues attendance records for synchronization."""
        with self._get_conn() as conn:
            for r in records:
                conn.execute("""
                    INSERT INTO attendance_queue
                    (session_id, student_id, usn, status, method, match_score, synced)
                    VALUES (?, ?, ?, ?, ?, ?, 0)
                """, (
                    r.get("session_id"),
                    r.get("student_id"),
                    r.get("usn", ""),
                    r.get("status", "present"),
                    r.get("method", "face_recognition"),
                    r.get("match_score")
                ))
            conn.commit()

    def get_pending_queue(self):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM attendance_queue WHERE synced = 0").fetchall()
            return [dict(r) for r in rows]

    def mark_queue_synced(self, queue_ids):
        if not queue_ids:
            return
        placeholders = ",".join(["?"] * len(queue_ids))
        with self._get_conn() as conn:
            conn.execute(f"UPDATE attendance_queue SET synced = 1 WHERE id IN ({placeholders})", queue_ids)
            conn.commit()


_global_local_store = None


def get_local_store():
    global _global_local_store
    if _global_local_store is None:
        _global_local_store = LocalStore()
    return _global_local_store
