"""
continue_integration/services/sync_service.py

Attendance Sync Service — pushes AttendAI attendance to Continue portal.
Reads from AttendAI's MySQL DB, calls ContinueClient, logs results.
"""

import logging
import mysql.connector
from datetime import datetime
from typing import Optional, List, Dict

from config import (
    DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME,
    CONTINUE_SYNC_ENABLED,
    STUDENT_ID_FIELD_IN_ATTENDAI,
    CONTINUE_STUDENT_ID_FIELD_NAME,
    CONTINUE_SUBJECT_FIELD_NAME,
    MAX_RETRY_ATTEMPTS,
)
from services.continue_client import ContinueClient, ContinueAPIError

logger = logging.getLogger(__name__)


def _get_db():
    """Connect to AttendAI's MySQL database."""
    return mysql.connector.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASS,
        database=DB_NAME, dictionary=True
    )


# ─────────────────────────────────────────────────────────────
# CORE SYNC FUNCTION — called after every attendance mark
# ─────────────────────────────────────────────────────────────

def sync_single_attendance(attendance_id: int) -> bool:
    """
    Push one attendance record from AttendAI to Continue portal.
    Called immediately after marking attendance (real-time mode).

    Args:
        attendance_id: PK from AttendAI attendance_records table
    Returns:
        True if synced successfully, False otherwise
    """
    if not CONTINUE_SYNC_ENABLED:
        logger.debug("Continue sync disabled — skipping.")
        return False

    conn = _get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        # ── Step 1: Fetch attendance + student info from AttendAI DB ──
        # TODO: Adjust table/column names to match your exact DB schema
        cursor.execute("""
            SELECT
                ar.id            AS attendance_id,
                ar.student_id,
                ar.session_id,
                ar.is_present,
                ar.marked_at,
                s.usn            AS student_usn,
                s.email          AS student_email,
                sub.code         AS subject_code,
                sub.name         AS subject_name,
                sec.section_label,
                sess.date        AS session_date,
                sess.period_number
            FROM attendance_records ar
            JOIN students s    ON s.id  = ar.student_id
            JOIN sessions sess ON sess.id = ar.session_id
            JOIN subjects sub  ON sub.id  = sess.subject_id
            JOIN sections sec  ON sec.id  = sess.section_id
            WHERE ar.id = %s
        """, (attendance_id,))
        record = cursor.fetchone()

        if not record:
            logger.error(f"attendance_id={attendance_id} not found in DB")
            return False

        # ── Step 2: Get Continue's student ID from mapping table ──
        cursor.execute("""
            SELECT continue_student_id
            FROM continue_student_map
            WHERE student_id = %s
        """, (record["student_id"],))
        mapping = cursor.fetchone()

        if not mapping:
            # Fallback: use USN/email directly if no mapping exists
            # (works if Continue's student IDs match AttendAI's USN format)
            logger.warning(
                f"No Continue mapping for student_id={record['student_id']}. "
                f"Falling back to USN: {record['student_usn']}"
            )
            continue_student_id = record[STUDENT_ID_FIELD_IN_ATTENDAI]
        else:
            continue_student_id = mapping["continue_student_id"]

        # ── Step 3: Build payload for Continue API ──
        # NOTE: Field names below are PLACEHOLDERS.
        # Update after receiving Continue's API documentation.
        payload = {
            CONTINUE_STUDENT_ID_FIELD_NAME: continue_student_id,
            CONTINUE_SUBJECT_FIELD_NAME:    record["subject_code"],
            "date":                         str(record["session_date"]),
            "period":                       record["period_number"],
            "status":                       "present" if record["is_present"] else "absent",
            "section":                      record["section_label"],
            # "source": "AttendAI"  ← add if Continue wants to know who sent it
        }

        # ── Step 4: Call Continue API ──
        client = ContinueClient()
        response = client.mark_attendance(payload)

        # ── Step 5: Log success ──
        _log_sync(cursor, conn, attendance_id, "synced",
                  continue_ref=str(response.get("id") or response.get("ref_id") or ""),
                  error=None)
        logger.info(f"[Continue Sync] ✅ attendance_id={attendance_id} synced.")
        return True

    except ContinueAPIError as e:
        logger.error(f"[Continue Sync] ❌ attendance_id={attendance_id} failed: {e}")
        _log_sync(cursor, conn, attendance_id, "failed", error=str(e))
        return False

    except Exception as e:
        logger.exception(f"[Continue Sync] Unexpected error for attendance_id={attendance_id}: {e}")
        _log_sync(cursor, conn, attendance_id, "failed", error=str(e))
        return False

    finally:
        cursor.close()
        conn.close()


# ─────────────────────────────────────────────────────────────
# BATCH RETRY SYNC — for failed/pending records
# ─────────────────────────────────────────────────────────────

def retry_failed_syncs() -> Dict[str, int]:
    """
    Pick up all failed/pending sync records and retry them.
    Called by scheduler every N minutes.

    Returns:
        dict: { "retried": X, "success": Y, "still_failed": Z }
    """
    conn = _get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT attendance_id
        FROM continue_sync_log
        WHERE status IN ('pending', 'failed')
          AND attempts < %s
        ORDER BY created_at ASC
        LIMIT 50
    """, (MAX_RETRY_ATTEMPTS,))
    pending = cursor.fetchall()
    cursor.close()
    conn.close()

    stats = {"retried": len(pending), "success": 0, "still_failed": 0}

    for row in pending:
        ok = sync_single_attendance(row["attendance_id"])
        if ok:
            stats["success"] += 1
        else:
            stats["still_failed"] += 1

    logger.info(f"[Continue Retry] Stats: {stats}")
    return stats


# ─────────────────────────────────────────────────────────────
# DB LOGGING HELPERS
# ─────────────────────────────────────────────────────────────

def _log_sync(cursor, conn, attendance_id: int, status: str,
              continue_ref: Optional[str] = None, error: Optional[str] = None):
    """Insert or update sync log entry in continue_sync_log table."""
    cursor.execute("""
        INSERT INTO continue_sync_log
            (attendance_id, status, continue_ref, last_error, synced_at, attempts)
        VALUES (%s, %s, %s, %s, %s, 1)
        ON DUPLICATE KEY UPDATE
            status       = VALUES(status),
            continue_ref = VALUES(continue_ref),
            last_error   = VALUES(last_error),
            synced_at    = IF(VALUES(status)='synced', NOW(), synced_at),
            attempts     = attempts + 1
    """, (
        attendance_id,
        status,
        continue_ref,
        error,
        datetime.utcnow() if status == "synced" else None
    ))
    conn.commit()
