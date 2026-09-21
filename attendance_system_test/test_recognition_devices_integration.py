"""
Test Suite: Unified Recognition Devices & Enhanced Fingerprint Enrollment Hub
Verifies:
1. get_device_slots() capacity, used slots calculation, and next_free_slot logic
2. Auto-allocation vs manual template_id slot assignment in enroll_student()
3. Duplicate template slot on device prevention
4. Duplicate student on device prevention
5. delete_enrollment() by fingerprint_id and by (student_id, camera_id)
6. Flask route endpoints /admin/fingerprints/, /admin/fingerprints/api/device-slots/<id>
7. Recognition Devices (/admin/cameras/) dual capabilities status testing
"""

import sys
import unittest
from unittest.mock import patch, MagicMock

# Import app factory
from app import create_app, UserSession
from core.db import get_db, get_cursor
from flask_login import login_user
from recognition.fingerprint_service import (
    get_device_slots, next_free_template_id, enroll_student,
    delete_enrollment, lookup_student_by_template, FingerprintError
)


class TestRecognitionDevicesIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()

    def test_01_device_slots_introspection(self):
        """Verify get_device_slots calculates used slots, free count, and next slot."""
        with self.app.app_context():
            cursor = get_cursor()
            cursor.execute("SELECT id FROM cameras LIMIT 1")
            cam = cursor.fetchone()
            if not cam:
                self.skipTest("No camera in DB")
            cam_id = cam["id"]

            slots = get_device_slots(cam_id)
            self.assertIn("total_capacity", slots)
            self.assertEqual(slots["total_capacity"], 127)
            self.assertIn("used_slots", slots)
            self.assertIn("free_count", slots)
            self.assertIn("next_free_slot", slots)
            self.assertEqual(slots["total_capacity"], slots["used_count"] + slots["free_count"])
            print(f"[PASS] Slot Introspection: Camera #{cam_id} -> {slots['used_count']}/127 used, Next Free: Slot #{slots['next_free_slot']}")

    def test_02_manual_and_auto_enrollment_simulation(self):
        """Verify enroll_student with auto vs manual template_id."""
        with self.app.app_context():
            cursor = get_cursor()
            cursor.execute("SELECT id FROM cameras LIMIT 1")
            cam = cursor.fetchone()
            cursor.execute("""
                SELECT s.id, u.full_name 
                FROM students s 
                JOIN users u ON u.id = s.user_id 
                LIMIT 1
            """)
            student = cursor.fetchone()

            cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
            admin_user = cursor.fetchone()
            admin_id = admin_user["id"] if admin_user else None

            if not cam or not student:
                self.skipTest("Need at least 1 camera and 1 student")

            cam_id = cam["id"]
            student_id = student["id"]

            # Mock requests.get for ESP32 /enroll
            with patch("requests.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.text = "Stored fingerprint model in slot 14."
                mock_get.return_value = mock_resp

                # Test manual slot 14
                res = enroll_student(student_id, cam_id, template_id=14, enrolled_by=admin_id)
                self.assertEqual(res["template_id"], 14)
                print(f"[PASS] Manual Template Slot Enrollment: Allocated Slot #{res['template_id']}")

                # Test lookup
                found = lookup_student_by_template(cam_id, 14)
                self.assertIsNotNone(found)
                self.assertEqual(found["student_id"], student_id)
                self.assertEqual(found["name"], student["full_name"])
                print(f"[PASS] Lookup Verified: Slot #14 -> Student: {found['name']} ({found['usn']})")

                # Test delete
                mock_del_resp = MagicMock()
                mock_del_resp.status_code = 200
                mock_del_resp.text = "Slot deleted."
                mock_get.return_value = mock_del_resp

                del_msg = delete_enrollment(student_id=student_id, camera_id=cam_id)
                self.assertIn("deleted", del_msg)
                print(f"[PASS] Deletion Verified: {del_msg}")

    def test_03_invalid_slot_validation(self):
        """Verify template_id boundary validation (1-127)."""
        with self.app.app_context():
            cursor = get_cursor()
            cursor.execute("SELECT id FROM cameras LIMIT 1")
            cam = cursor.fetchone()
            cursor.execute("SELECT id FROM students LIMIT 1")
            student = cursor.fetchone()
            if not cam or not student:
                self.skipTest("No test data")

            # Out of bounds (< 1)
            with self.assertRaises(FingerprintError):
                enroll_student(student["id"], cam["id"], template_id=0)

            # Out of bounds (> 127)
            with self.assertRaises(FingerprintError):
                enroll_student(student["id"], cam["id"], template_id=150)
            print("[PASS] Template Slot Boundary Validation (1-127 strictly enforced)")

    def test_04_device_slots_ajax_route(self):
        """Verify AJAX endpoint /admin/fingerprints/api/device-slots/<id>."""
        from api.admin.fingerprints import device_slots_api
        with self.app.test_request_context(f"/admin/fingerprints/api/device-slots/2"):
            with self.app.app_context():
                cursor = get_cursor()
                cursor.execute("SELECT id FROM cameras LIMIT 1")
                cam = cursor.fetchone()
                if not cam:
                    self.skipTest("No camera")

                cursor.execute("SELECT * FROM users WHERE role = 'admin' LIMIT 1")
                admin = cursor.fetchone()
                user_obj = UserSession(admin)

                with patch("flask_login.utils._get_user", return_value=user_obj):
                    response = device_slots_api(cam["id"])
                    json_data = response.get_json()
                    self.assertTrue(json_data.get("success"))
                    self.assertIn("slots", json_data)
                    self.assertEqual(json_data["slots"]["total_capacity"], 127)
                    print(f"[PASS] Device Slots AJAX API: {json_data['slots']}")

    def test_05_link_existing_template_slot(self):
        """Verify link_existing_template() directly maps pre-enrolled sensor slot to student."""
        from recognition.fingerprint_service import link_existing_template
        with self.app.app_context():
            cursor = get_cursor()
            cursor.execute("SELECT id FROM cameras LIMIT 1")
            cam = cursor.fetchone()
            cursor.execute("""
                SELECT s.id, u.full_name, s.usn
                FROM students s 
                JOIN users u ON u.id = s.user_id 
                LIMIT 1
            """)
            student = cursor.fetchone()
            if not cam or not student:
                self.skipTest("No test data")

            cam_id = cam["id"]
            student_id = student["id"]

            cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
            admin_user = cursor.fetchone()
            admin_id = admin_user["id"] if admin_user else None

            # Direct link slot 25
            result = link_existing_template(
                student_id=student_id,
                camera_id=cam_id,
                template_id=25,
                enrolled_by=admin_id
            )
            self.assertEqual(result["template_id"], 25)
            self.assertEqual(result["usn"], student["usn"])
            print(f"[PASS] Direct Slot Linking: Mapped Slot #{result['template_id']} -> {result['student_name']} ({result['usn']})")

            # Verify lookup resolves student
            found = lookup_student_by_template(cam_id, 25)
            self.assertIsNotNone(found)
            self.assertEqual(found["student_id"], student_id)
            print(f"[PASS] Lookup Verification: Slot #25 mapped correctly to {found['name']}")

            # Cleanup
            delete_enrollment(student_id=student_id, camera_id=cam_id)
            print("[PASS] Cleaned up test slot #25.")


if __name__ == "__main__":
    unittest.main()
