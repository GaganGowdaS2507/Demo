import os
import sys
import unittest
import io
from unittest.mock import patch, MagicMock

# Add attendance_system_test to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from core.db import get_db, get_cursor


class TestBulkSubjectUpload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        cls.client = cls.app.test_client()
        cls.ctx = cls.app.app_context()
        cls.ctx.push()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def test_01_download_template_route(self):
        """Test the template download endpoint."""
        with self.client.session_transaction() as sess:
            sess["_user_id"] = "1"

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.role = "admin"
        mock_user.is_authenticated = True

        with patch("flask_login.utils._get_user", return_value=mock_user):
            resp = self.client.get("/admin/academic/subjects/template")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("text/csv", resp.content_type)
            content = resp.data.decode("utf-8")
            self.assertIn("subject_code,subject_name,department,semester,credits,subject_type,offering_mode", content)

    def test_02_bulk_upload_parsing_and_execution(self):
        """Test bulk upload endpoint with valid CSV content."""
        csv_data = """subject_code,subject_name,department,semester,credits,subject_type,offering_mode
TEST_SUB_101,Advanced Algorithms,CSE,5,4,Theory,regular
TEST_SUB_102,Machine Learning Lab,CSE,5,2,Lab,regular
TEST_SUB_103,Cloud Computing Elective,CSE,6,3,Theory,professional_elective
"""
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.role = "admin"
        mock_user.is_authenticated = True

        with patch("flask_login.utils._get_user", return_value=mock_user):
            data = {
                "file": (io.BytesIO(csv_data.encode("utf-8")), "subjects_test.csv"),
                "update_existing": "1"
            }
            resp = self.client.post(
                "/admin/academic/subjects/bulk-upload",
                data=data,
                content_type="multipart/form-data",
                follow_redirects=True
            )
            self.assertEqual(resp.status_code, 200)

            # Check if subjects were inserted
            conn = get_db()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM subjects WHERE code IN ('TEST_SUB_101', 'TEST_SUB_102', 'TEST_SUB_103')")
            rows = cursor.fetchall()
            codes = [r["code"] for r in rows]
            self.assertIn("TEST_SUB_101", codes)
            self.assertIn("TEST_SUB_102", codes)
            self.assertIn("TEST_SUB_103", codes)

            # Clean up test rows
            cursor.execute("DELETE FROM subjects WHERE code IN ('TEST_SUB_101', 'TEST_SUB_102', 'TEST_SUB_103')")
            conn.commit()


if __name__ == "__main__":
    unittest.main()
