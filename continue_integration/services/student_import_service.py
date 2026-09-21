"""
continue_integration/services/student_import_service.py

Import students from Continue portal into AttendAI database.
Maps Continue's student IDs to AttendAI's internal student records.
"""

import logging
import mysql.connector
from typing import List, Dict, Optional

from config import (
    DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME,
    CONTINUE_STUDENT_ID_FIELD_NAME,
    STUDENT_ID_FIELD_IN_ATTENDAI,
)
from services.continue_client import ContinueClient, ContinueAPIError

logger = logging.getLogger(__name__)


def _get_db():
    return mysql.connector.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASS,
        database=DB_NAME, dictionary=True
    )


# ─────────────────────────────────────────────────────────────
# IMPORT STUDENTS FROM CONTINUE
# ─────────────────────────────────────────────────────────────

def import_students_from_continue(
    section: Optional[str] = None,
    department: Optional[str] = None,
    semester: Optional[int] = None
) -> Dict[str, int]:
    """
    Pull student list from Continue portal and:
      1. Match to existing AttendAI students by USN/email
      2. Insert mapping records in continue_student_map
      3. Optionally create new student stubs for unmatched students

    Args:
        section:    section label filter (e.g. "CS-3A")
        department: department code filter (e.g. "CSE")
        semester:   semester number filter
    Returns:
        dict: { "fetched": N, "matched": M, "new_stubs": P, "failed": Q }
    """
    client = ContinueClient()

    # Step 1: Fetch from Continue
    try:
        students_from_continue: List[Dict] = client.get_students(
            section=section,
            department=department,
            semester=semester
        )
    except ContinueAPIError as e:
        logger.error(f"Failed to fetch students from Continue: {e}")
        return {"fetched": 0, "matched": 0, "new_stubs": 0, "failed": 1}

    stats = {
        "fetched": len(students_from_continue),
        "matched": 0,
        "new_stubs": 0,
        "failed": 0,
    }

    conn = _get_db()
    cursor = conn.cursor(dictionary=True)

    for continue_student in students_from_continue:
        try:
            # ── Step 2: Extract Continue's student identifier ──
            # e.g., continue_student["roll_no"] = "1RN22CS001"
            # Field name depends on Continue API — update after getting docs
            continue_id = continue_student.get(CONTINUE_STUDENT_ID_FIELD_NAME)
            if not continue_id:
                logger.warning(f"Skipping student with no ID: {continue_student}")
                stats["failed"] += 1
                continue

            # ── Step 3: Try to match in AttendAI's students table ──
            # Attempt 1: match by USN (most reliable)
            cursor.execute("""
                SELECT id FROM students WHERE usn = %s LIMIT 1
            """, (continue_id,))
            match = cursor.fetchone()

            # Attempt 2: match by email if USN didn't work
            if not match and continue_student.get("email"):
                cursor.execute("""
                    SELECT id FROM students WHERE email = %s LIMIT 1
                """, (continue_student["email"],))
                match = cursor.fetchone()

            if match:
                attendai_student_id = match["id"]
                stats["matched"] += 1
            else:
                # ── Step 4: No match — create a stub student record ──
                # This lets admin know these students exist but haven't
                # self-registered in AttendAI yet (face enrollment pending)
                attendai_student_id = _create_stub_student(
                    cursor, conn, continue_student, continue_id
                )
                if attendai_student_id:
                    stats["new_stubs"] += 1
                else:
                    stats["failed"] += 1
                    continue

            # ── Step 5: Insert/update Continue ↔ AttendAI mapping ──
            cursor.execute("""
                INSERT INTO continue_student_map
                    (student_id, continue_student_id)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE
                    continue_student_id = VALUES(continue_student_id)
            """, (attendai_student_id, str(continue_id)))
            conn.commit()

        except Exception as e:
            logger.error(f"Error processing continue student {continue_student}: {e}")
            stats["failed"] += 1

    cursor.close()
    conn.close()
    logger.info(f"[Student Import] Done: {stats}")
    return stats


def _create_stub_student(cursor, conn, continue_student: Dict, continue_id: str) -> Optional[int]:
    """
    Create a minimal student stub in AttendAI for a Continue student
    who hasn't registered yet. Stub is marked as pending enrollment.
    """
    try:
        # Extract fields — field names depend on Continue's API response format
        # These are PLACEHOLDERS — update once you have Continue API docs
        name  = continue_student.get("name") or continue_student.get("student_name") or "Unknown"
        email = continue_student.get("email") or f"{continue_id}@student.placeholder"
        usn   = continue_student.get("usn")   or continue_student.get("roll_no") or continue_id

        # Insert into users table (adjust to your actual schema)
        cursor.execute("""
            INSERT INTO users (full_name, email, college_id, role, status, created_at)
            VALUES (%s, %s, %s, 'student', 'pending_enrollment', NOW())
            ON DUPLICATE KEY UPDATE full_name = VALUES(full_name)
        """, (name, email, usn))
        conn.commit()

        user_id = cursor.lastrowid

        # Insert into students table
        cursor.execute("""
            INSERT INTO students (user_id, usn, email)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE usn = VALUES(usn)
        """, (user_id, usn, email))
        conn.commit()

        return cursor.lastrowid

    except Exception as e:
        logger.error(f"Failed to create stub student {continue_id}: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# SYNC STATUS QUERY
# ─────────────────────────────────────────────────────────────

def get_sync_status_summary() -> Dict:
    """
    Return summary of sync status for admin dashboard.
    """
    conn = _get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            status,
            COUNT(*) AS count
        FROM continue_sync_log
        GROUP BY status
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return {row["status"]: row["count"] for row in rows}
