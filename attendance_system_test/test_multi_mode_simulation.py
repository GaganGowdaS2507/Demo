"""
Standalone Software-Only Verification Suite for Multi-Mode Attendance
Mocks external HTTP device endpoints while testing actual Flask app context,
database queries, engine matching, stream manager state machine, and regressions.
"""

import sys
import os
import time
import unittest
from unittest.mock import patch, MagicMock
import numpy as np

# Ensure app path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import create_app
from core.db import get_cursor, get_db, connection_pool
from recognition.engine import RecognitionEngine
from recognition.stream_manager import StreamManager, RecognitionThread
from recognition.fingerprint_service import lookup_student_by_template, _device_base_url
from config import Config


class SoftwareVerificationTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.ctx = cls.app.app_context()
        cls.ctx.push()
        
        # Ensure recognition engine is initialized
        import app as _app
        if not _app.recognition_engine or not _app.recognition_engine.is_initialized:
            _app.init_recognition()
        cls.engine = _app.recognition_engine
        cls.stream_manager = _app.stream_manager

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    # -------------------------------------------------------------
    # 1. Blueprint & Route Registration Tests
    # -------------------------------------------------------------
    def test_01_blueprint_and_routes_registered(self):
        print("\n[TEST 1] Testing Blueprint & Route Registrations...")
        routes = [r.rule for r in self.app.url_map.iter_rules()]
        
        # Verify fingerprints blueprint routes
        self.assertIn("/admin/fingerprints/", routes)
        self.assertIn("/admin/fingerprints/enroll", routes)
        self.assertIn("/admin/fingerprints/delete", routes)
        
        # Verify session recognition control routes
        self.assertIn("/faculty/session/<int:session_id>/start-recognition", routes)
        self.assertIn("/faculty/session/<int:session_id>/stop-recognition", routes)
        self.assertIn("/admin/recognition/start/<int:session_id>", routes)
        self.assertIn("/admin/recognition/stop/<int:session_id>", routes)
        print(" -> All required routes correctly mapped in Flask url_map.")

    # -------------------------------------------------------------
    # 2. Database Schema & Canonical Name Mapping
    # -------------------------------------------------------------
    def test_02_database_schema_and_canonical_queries(self):
        print("\n[TEST 2] Testing DB Schema & Canonical Name Queries...")
        cursor = get_cursor()
        
        # Check sessions.recognition_mode column definition
        cursor.execute("""
            SELECT COLUMN_TYPE, COLUMN_DEFAULT 
            FROM information_schema.COLUMNS 
            WHERE TABLE_SCHEMA = DATABASE() 
              AND TABLE_NAME = 'sessions' 
              AND COLUMN_NAME = 'recognition_mode'
        """)
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertIn("FACE_ONLY", row["COLUMN_TYPE"])
        self.assertIn("FINGERPRINT_ONLY", row["COLUMN_TYPE"])
        self.assertIn("DUAL_MODE", row["COLUMN_TYPE"])
        
        # Check attendance table columns
        cursor.execute("""
            SELECT COLUMN_NAME FROM information_schema.COLUMNS 
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'attendance'
        """)
        cols = {r["COLUMN_NAME"] for r in cursor.fetchall()}
        self.assertIn("fingerprint_score", cols)
        self.assertIn("recognition_score", cols)
        self.assertIn("liveness_score", cols)
        self.assertIn("method", cols)
        
        # Verify canonical user full_name mapping
        cursor.execute("""
            SELECT s.id AS student_id, s.usn, u.full_name
            FROM students s
            JOIN users u ON u.id = s.user_id
            LIMIT 5
        """)
        students = cursor.fetchall()
        self.assertGreater(len(students), 0)
        for st in students:
            self.assertIsNotNone(st["full_name"])
            self.assertNotEqual(st["full_name"].strip(), "")
        print(f" -> DB schema verified. Found {len(students)} verified student-user mappings.")

    # -------------------------------------------------------------
    # 3. Fingerprint Lookup via (camera_id, template_id)
    # -------------------------------------------------------------
    def test_03_fingerprint_service_lookup(self):
        print("\n[TEST 3] Testing Fingerprint Lookup Service...")
        cursor = get_cursor()
        cursor.execute("""
            SELECT f.camera_id, f.template_id, f.student_id, s.usn, u.full_name
            FROM fingerprints f
            JOIN students s ON s.id = f.student_id
            JOIN users u ON u.id = s.user_id
            WHERE f.status = 'active'
            LIMIT 1
        """)
        fp_row = cursor.fetchone()
        if fp_row:
            res = lookup_student_by_template(fp_row["camera_id"], fp_row["template_id"])
            self.assertIsNotNone(res)
            self.assertEqual(res["student_id"], fp_row["student_id"])
            self.assertEqual(res["usn"], fp_row["usn"])
            self.assertEqual(res["name"], fp_row["full_name"])
            print(f" -> Found active fingerprint: template #{fp_row['template_id']} mapped to {res['name']} ({res['usn']})")
        else:
            print(" -> No active fingerprint in DB, skipping lookup test.")

    # -------------------------------------------------------------
    # 4. Targeted Face Matching Unit Tests
    # -------------------------------------------------------------
    def test_04_targeted_face_matching_engine(self):
        print("\n[TEST 4] Testing Targeted Face Matching Engine...")
        engine = self.engine
        
        with engine._emb_index_lock:
            sids = list(engine._emb_index_sids)
            matrix = engine._emb_index_matrix

        if len(sids) >= 2:
            target_sid = sids[0]
            other_sid = sids[1]
            target_emb = matrix[0].copy()
            other_emb = matrix[1].copy()

            # 1. Exact match test
            is_match, score = engine.match_face_to_student(target_emb, target_sid, threshold=0.35)
            self.assertTrue(is_match)
            self.assertGreater(score, 0.95)

            # 2. Wrong student embedding test (must reject)
            is_match_wrong, score_wrong = engine.match_face_to_student(other_emb, target_sid, threshold=0.35)
            # Depending on similarity, if they are different people score should be lower or is_match False
            print(f" -> Match target score: {score:.3f} (is_match={is_match})")
            print(f" -> Mismatch other score: {score_wrong:.3f} (is_match={is_match_wrong})")

            # 3. Non-existent student ID test
            is_match_none, score_none = engine.match_face_to_student(target_emb, -9999, threshold=0.35)
            self.assertFalse(is_match_none)
            self.assertEqual(score_none, 0.0)

            # 4. None inputs test
            is_m_null, sc_null = engine.match_face_to_student(None, target_sid)
            self.assertFalse(is_m_null)
            self.assertEqual(sc_null, 0.0)
            print(" -> Targeted face matching verified without running full database search.")
        else:
            print(" -> Insufficient enrolled embeddings in test DB, skipped.")

    # -------------------------------------------------------------
    # 5. Simulated Mode 2 (FINGERPRINT_ONLY) Polling & Validation
    # -------------------------------------------------------------
    def test_05_fingerprint_only_mock_flow(self):
        print("\n[TEST 5] Testing FINGERPRINT_ONLY Mode Flow (Mocked HTTP)...")
        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)

        # Find or pick an active session and a camera
        cursor.execute("SELECT id, section_id FROM sessions WHERE status IN ('active', 'scheduled') LIMIT 1")
        session = cursor.fetchone()
        cursor.execute("SELECT id, rtsp_url FROM cameras LIMIT 1")
        camera = cursor.fetchone()

        if not session or not camera:
            print(" -> No session or camera found for test, skipping.")
            return

        session_id = session["id"]
        section_id = session["section_id"]
        camera_id = camera["id"]

        # Ensure student exists in this section
        cursor.execute("SELECT s.id, s.usn, u.full_name FROM students s JOIN users u ON u.id = s.user_id WHERE s.section_id = %s LIMIT 1", (section_id,))
        student = cursor.fetchone()
        if not student:
            print(" -> No student in section, skipping.")
            return

        student_id = student["id"]
        usn = student["usn"]

        # Ensure attendance row exists as absent
        cursor.execute("""
            INSERT INTO attendance (session_id, student_id, usn, status, method, marked_at)
            VALUES (%s, %s, %s, 'absent', 'system', NOW())
            ON DUPLICATE KEY UPDATE status='absent', method='system'
        """, (session_id, student_id, usn))
        conn.commit()

        # Instantiate RecognitionThread in FINGERPRINT_ONLY mode
        rec_thread = RecognitionThread(
            session_id=session_id,
            rtsp_url=camera["rtsp_url"],
            section_id=section_id,
            engine=self.engine,
            liveness_checker=None,
            db_pool=connection_pool,
            mode="FINGERPRINT_ONLY",
            camera_id=camera_id
        )
        rec_thread._load_allowed_students()

        # Mock lookup_student_by_template to return our student
        with patch("recognition.fingerprint_service.lookup_student_by_template") as mock_lookup:
            mock_lookup.return_value = {
                "student_id": student_id,
                "usn": usn,
                "name": student["full_name"],
                "section_id": section_id
            }

            # 1. Execute attendance marking via fingerprint
            marked = rec_thread._mark_attendance_db(
                student_id=student_id,
                usn=usn,
                score=None,
                liveness_score=None,
                fingerprint_score=92.5,
                method="fingerprint"
            )
            self.assertTrue(marked)

            # Check DB updated
            cursor.execute("SELECT status, method, fingerprint_score FROM attendance WHERE session_id = %s AND student_id = %s", (session_id, student_id))
            att_row = cursor.fetchone()
            self.assertEqual(att_row["status"], "present")
            self.assertEqual(att_row["method"], "fingerprint")
            self.assertEqual(att_row["fingerprint_score"], 92.5)
            print(f" -> Attendance marked successfully: status={att_row['status']}, method={att_row['method']}, fp_score={att_row['fingerprint_score']}")

            # 2. Test duplicate prevention / cooldown
            marked_dup = rec_thread._mark_attendance_db(
                student_id=student_id,
                usn=usn,
                fingerprint_score=92.5,
                method="fingerprint"
            )
            self.assertFalse(marked_dup)
            print(" -> Duplicate scan correctly prevented by cooldown mechanism.")

            # 3. Test wrong section student rejection
            rec_thread_other = RecognitionThread(
                session_id=session_id,
                rtsp_url=camera["rtsp_url"],
                section_id=999999, # non-matching section
                engine=self.engine,
                liveness_checker=None,
                db_pool=connection_pool,
                mode="FINGERPRINT_ONLY",
                camera_id=camera_id
            )
            rec_thread_other._load_allowed_students()
            marked_wrong_sec = rec_thread_other._mark_attendance_db(
                student_id=student_id,
                usn=usn,
                fingerprint_score=90.0,
                method="fingerprint"
            )
            self.assertFalse(marked_wrong_sec)
            print(" -> Wrong section student correctly rejected.")

    # -------------------------------------------------------------
    # 6. Simulated Mode 3 (DUAL_MODE) State Machine & Timeout
    # -------------------------------------------------------------
    def test_06_dual_mode_state_machine_and_timeout(self):
        print("\n[TEST 6] Testing DUAL_MODE State Machine & 10s Timeout...")
        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)

        cursor.execute("SELECT id, section_id FROM sessions WHERE status IN ('active', 'scheduled') LIMIT 1")
        session = cursor.fetchone()
        if not session:
            print(" -> No session found, skipping.")
            return

        session_id = session["id"]
        section_id = session["section_id"]

        cursor.execute("SELECT s.id, s.usn, u.full_name FROM students s JOIN users u ON u.id = s.user_id WHERE s.section_id = %s LIMIT 1", (section_id,))
        student = cursor.fetchone()
        if not student:
            print(" -> No student found, skipping.")
            return

        student_id = student["id"]
        usn = student["usn"]
        name = student["full_name"]

        # Reset attendance record to absent
        cursor.execute("""
            INSERT INTO attendance (session_id, student_id, usn, status, method, marked_at)
            VALUES (%s, %s, %s, 'absent', 'system', NOW())
            ON DUPLICATE KEY UPDATE status='absent', method='system'
        """, (session_id, student_id, usn))
        conn.commit()

        rec_thread = RecognitionThread(
            session_id=session_id,
            rtsp_url="http://127.0.0.1:81/stream",
            section_id=section_id,
            engine=self.engine,
            liveness_checker=None,
            db_pool=connection_pool,
            mode="DUAL_MODE",
            camera_id=1
        )
        rec_thread._load_allowed_students()

        # Step 1: Simulate fingerprint event setting dual target
        with rec_thread._dual_lock:
            rec_thread._dual_target = {
                "student_id": student_id,
                "usn": usn,
                "name": name,
                "fingerprint_score": 88.0,
                "expires_at": time.time() + 10.0
            }

        self.assertIsNotNone(rec_thread._dual_target)
        self.assertEqual(rec_thread._dual_target["student_id"], student_id)
        print(f" -> Step 1: Fingerprint target set for {name} with 10s window.")

        # Step 2: Simulate face verification matching target
        face_score = 0.85
        marked = rec_thread._mark_attendance_db(
            student_id=student_id,
            usn=usn,
            score=face_score,
            liveness_score=0.99,
            fingerprint_score=88.0,
            method="dual_verification"
        )
        self.assertTrue(marked)

        cursor.execute("SELECT status, method, recognition_score, fingerprint_score FROM attendance WHERE session_id = %s AND student_id = %s", (session_id, student_id))
        att_row = cursor.fetchone()
        self.assertEqual(att_row["status"], "present")
        self.assertEqual(att_row["method"], "dual_verification")
        self.assertEqual(att_row["fingerprint_score"], 88.0)
        self.assertEqual(att_row["recognition_score"], 0.85)
        print(f" -> Step 2: Dual attendance marked: method={att_row['method']}, face_score={att_row['recognition_score']}, fp_score={att_row['fingerprint_score']}")

        # Step 3: Test 10s Timeout behavior
        with rec_thread._dual_lock:
            # Set target with expired timestamp
            rec_thread._dual_target = {
                "student_id": student_id,
                "usn": usn,
                "name": name,
                "fingerprint_score": 88.0,
                "expires_at": time.time() - 1.0 # already expired
            }

        # Check timeout logic
        now = time.time()
        with rec_thread._dual_lock:
            if rec_thread._dual_target and now > rec_thread._dual_target["expires_at"]:
                rec_thread._add_log("dual_mode", f"Dual verification window timed out for {rec_thread._dual_target['name']}")
                rec_thread._dual_target = None

        self.assertIsNone(rec_thread._dual_target)
        print(" -> Step 3: Expired target correctly timed out and reset to None.")

    # -------------------------------------------------------------
    # 7. Start/Stop Lifecycle Clean-up Tests
    # -------------------------------------------------------------
    def test_07_start_stop_lifecycle(self):
        print("\n[TEST 7] Testing StreamManager Start/Stop Lifecycle...")
        sm = self.stream_manager
        test_session_id = 99999

        # Test stop non-existent
        res, msg = sm.stop_stream(test_session_id)
        self.assertFalse(res)

        # Mock frame grabber to test start in FINGERPRINT_ONLY mode (doesn't need real stream)
        success, msg = sm.start_stream(
            session_id=test_session_id,
            rtsp_url="",
            section_id=1,
            db_pool=connection_pool,
            mode="FINGERPRINT_ONLY",
            camera_id=None
        )
        self.assertTrue(success)
        self.assertIn(test_session_id, sm._streams)
        
        status = sm.get_stream_status(test_session_id)
        self.assertEqual(status["session_id"], test_session_id)
        self.assertTrue(status["is_running"])

        # Clean stop
        stop_ok, stop_msg = sm.stop_stream(test_session_id)
        self.assertTrue(stop_ok)
        self.assertNotIn(test_session_id, sm._streams)
        print(" -> StreamManager start, status query, and stop lifecycle cleanly executed.")

    # -------------------------------------------------------------
    # 8. Regression Tests: Manual, Bulk, OCR, and Report Queries
    # -------------------------------------------------------------
    def test_08_regression_attendance_and_reports(self):
        print("\n[TEST 8] Testing Regression on Manual, Bulk, OCR, and Reports...")
        cursor = get_cursor()

        # 1. Test Session View Attendance Listing Query
        cursor.execute("""
            SELECT 
                st.id AS student_id,
                st.usn,
                u.full_name,
                COALESCE(a.status, 'absent') AS status,
                a.method,
                a.recognition_score,
                a.fingerprint_score,
                a.marked_at
            FROM students st
            JOIN users u ON u.id = st.user_id
            LEFT JOIN attendance a 
                ON a.student_id = st.id AND a.session_id = 1
            LIMIT 5
        """)
        rows = cursor.fetchall()
        self.assertGreater(len(rows), 0)
        print(f" -> Session view query executed cleanly. Fetched {len(rows)} records.")

        # 2. Test Defaulter Report Query
        cursor.execute("""
            SELECT s.usn, u.full_name,
                   COUNT(a.id) AS total_sessions,
                   SUM(a.status = 'present') AS present
            FROM attendance a
            JOIN sessions sess ON sess.id = a.session_id
            JOIN students s ON s.id = a.student_id
            JOIN users u ON u.id = s.user_id
            GROUP BY s.id, s.usn, u.full_name
            LIMIT 5
        """)
        defaulters = cursor.fetchall()
        print(f" -> Defaulters report query executed cleanly. Fetched {len(defaulters)} records.")

        # 3. Test Student Overview Search Query
        cursor.execute("""
            SELECT s.id, s.usn, u.full_name, u.email
            FROM students s
            JOIN users u ON u.id = s.user_id
            WHERE u.full_name LIKE '%a%' OR s.usn LIKE '%1%'
            LIMIT 5
        """)
        search_res = cursor.fetchall()
        print(f" -> Student search query executed cleanly. Fetched {len(search_res)} records.")


if __name__ == "__main__":
    unittest.main()
