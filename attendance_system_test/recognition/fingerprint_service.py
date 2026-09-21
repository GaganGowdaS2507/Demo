"""
recognition/fingerprint_service.py
Talks to an ESP32-CAM+fingerprint device's control server (port 80) to
manage enrollment and pull scan results. Reuses cameras.rtsp_url as the
device's base address (normalized to http://<ip>/ regardless of what
scheme was stored, since the fingerprint control endpoints are always
plain HTTP on this firmware).
"""

import logging
import requests
from urllib.parse import urlparse

from core.db import get_db, get_cursor

logger = logging.getLogger(__name__)


class FingerprintError(Exception):
    pass


def _device_base_url(camera_row):
    """Turn a stored camera stream address into the device's control-server base URL."""
    parsed = urlparse(camera_row["rtsp_url"])
    host = parsed.hostname
    if not host:
        raise FingerprintError("Camera has no usable IP/hostname on file.")
    return f"http://{host}"   # control server is always plain HTTP on port 80


def get_device_slots(camera_id):
    """Return slot usage statistics and the next available slot for this device."""
    cursor = get_cursor()
    cursor.execute(
        "SELECT template_id FROM fingerprints WHERE camera_id = %s AND status = 'active' ORDER BY template_id",
        (camera_id,)
    )
    used = [row["template_id"] for row in cursor.fetchall()]
    used_set = set(used)
    next_slot = None
    for i in range(1, 128):
        if i not in used_set:
            next_slot = i
            break
    return {
        "total_capacity": 127,
        "used_slots": used,
        "used_count": len(used),
        "free_count": 127 - len(used),
        "next_free_slot": next_slot
    }


def next_free_template_id(camera_id):
    """Find the lowest unused template slot (1-127) on this device."""
    slots_info = get_device_slots(camera_id)
    if slots_info["next_free_slot"] is None:
        raise FingerprintError("This device's fingerprint sensor is full (127 slots used).")
    return slots_info["next_free_slot"]


def enroll_student(student_id, camera_id, template_id=None, enrolled_by=None, timeout=20):
    """
    Assign the student an explicit or next free template slot on `camera_id`,
    then tell the device to run its enrollment flow for that slot.
    """
    cursor = get_cursor()
    cursor.execute("SELECT id, rtsp_url FROM cameras WHERE id = %s", (camera_id,))
    cam = cursor.fetchone()
    if not cam:
        raise FingerprintError("Camera/device not found.")

    cursor.execute(
        "SELECT id, template_id FROM fingerprints WHERE student_id = %s AND camera_id = %s AND status='active'",
        (student_id, camera_id)
    )
    existing = cursor.fetchone()
    if existing:
        raise FingerprintError(f"This student already has an active fingerprint enrolled on this device (Slot #{existing['template_id']}).")

    if template_id is not None:
        try:
            template_id = int(template_id)
        except (ValueError, TypeError):
            raise FingerprintError("Template ID must be a valid number between 1 and 127.")
        if template_id < 1 or template_id > 127:
            raise FingerprintError("Template ID must be between 1 and 127.")
        cursor.execute(
            "SELECT id FROM fingerprints WHERE camera_id = %s AND template_id = %s AND status='active'",
            (camera_id, template_id)
        )
        if cursor.fetchone():
            raise FingerprintError(f"Template Slot #{template_id} is already in use on this device. Please choose another slot.")
    else:
        template_id = next_free_template_id(camera_id)

    base_url = _device_base_url(cam)

    try:
        resp = requests.get(f"{base_url}/enroll", params={"id": template_id}, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise FingerprintError(f"Could not reach device ({base_url}): {e}")

    result_text = resp.text

    conn = get_db()
    cur = conn.cursor()
    # Clean up any previous revoked/duplicate records for this slot or student on this device
    cur.execute(
        "DELETE FROM fingerprints WHERE camera_id = %s AND (template_id = %s OR student_id = %s)",
        (camera_id, template_id, student_id)
    )
    cur.execute(
        """
        INSERT INTO fingerprints (student_id, camera_id, template_id, enrolled_by, status)
        VALUES (%s, %s, %s, %s, 'active')
        """,
        (student_id, camera_id, template_id, enrolled_by)
    )
    conn.commit()

    return {"template_id": template_id, "device_message": result_text}


def link_existing_template(student_id, camera_id, template_id, enrolled_by=None):
    """
    Directly map an already enrolled hardware slot (1-127) on `camera_id` to `student_id`
    in the database without triggering hardware re-enrollment.
    """
    cursor = get_cursor()
    cursor.execute("SELECT id, name FROM cameras WHERE id = %s", (camera_id,))
    cam = cursor.fetchone()
    if not cam:
        raise FingerprintError("Recognition device not found.")

    cursor.execute(
        """
        SELECT s.id, s.usn, u.full_name AS name
        FROM students s
        JOIN users u ON u.id = s.user_id
        WHERE s.id = %s
        """,
        (student_id,)
    )
    student = cursor.fetchone()
    if not student:
        raise FingerprintError("Student not found.")

    try:
        template_id = int(template_id)
    except (ValueError, TypeError):
        raise FingerprintError("Template Slot ID must be a valid number between 1 and 127.")

    if template_id < 1 or template_id > 127:
        raise FingerprintError("Template Slot ID must be between 1 and 127.")

    # Check if slot is already mapped to another student on this device
    cursor.execute(
        """
        SELECT f.id, s.usn, u.full_name AS student_name
        FROM fingerprints f
        JOIN students s ON s.id = f.student_id
        JOIN users u ON u.id = s.user_id
        WHERE f.camera_id = %s AND f.template_id = %s AND f.status = 'active'
        """,
        (camera_id, template_id)
    )
    existing_slot = cursor.fetchone()
    if existing_slot and existing_slot["usn"] != student["usn"]:
        raise FingerprintError(
            f"Slot #{template_id} on {cam['name']} is already assigned to {existing_slot['student_name']} ({existing_slot['usn']}). "
            "Please select a different slot or delete the existing mapping."
        )

    conn = get_db()
    cur = conn.cursor()
    # Ensure enrolled_by is a valid user ID or NULL
    valid_enrolled_by = None
    if enrolled_by:
        try:
            cur.execute("SELECT id FROM users WHERE id = %s", (enrolled_by,))
            if cur.fetchone():
                valid_enrolled_by = enrolled_by
        except Exception:
            valid_enrolled_by = None

    # Clean up previous mapping for this student on this device or this slot
    cur.execute(
        "DELETE FROM fingerprints WHERE camera_id = %s AND (template_id = %s OR student_id = %s)",
        (camera_id, template_id, student_id)
    )
    cur.execute(
        """
        INSERT INTO fingerprints (student_id, camera_id, template_id, enrolled_by, status)
        VALUES (%s, %s, %s, %s, 'active')
        """,
        (student_id, camera_id, template_id, valid_enrolled_by)
    )
    conn.commit()

    return {
        "template_id": template_id,
        "student_name": student["name"],
        "usn": student["usn"],
        "camera_name": cam["name"],
        "message": f"Successfully mapped Slot #{template_id} to {student['name']} ({student['usn']}) on {cam['name']}."
    }


def delete_enrollment(student_id=None, camera_id=None, fingerprint_id=None, timeout=10):
    """Delete enrollment by student_id + camera_id or by primary fingerprint_id."""
    cursor = get_cursor()
    if fingerprint_id:
        cursor.execute(
            "SELECT f.id, f.student_id, f.camera_id, f.template_id, c.rtsp_url FROM fingerprints f "
            "JOIN cameras c ON c.id = f.camera_id "
            "WHERE f.id = %s",
            (fingerprint_id,)
        )
    else:
        cursor.execute(
            "SELECT f.id, f.student_id, f.camera_id, f.template_id, c.rtsp_url FROM fingerprints f "
            "JOIN cameras c ON c.id = f.camera_id "
            "WHERE f.student_id = %s AND f.camera_id = %s",
            (student_id, camera_id)
        )
    row = cursor.fetchone()
    if not row:
        raise FingerprintError("No fingerprint enrollment found to delete.")

    base_url = _device_base_url(row)
    device_msg = ""
    try:
        resp = requests.get(f"{base_url}/delete", params={"id": row["template_id"]}, timeout=timeout)
        device_msg = resp.text
    except requests.RequestException as e:
        logger.warning(f"Could not reach device to delete slot #{row['template_id']}: {e}")
        device_msg = f"Device unreachable ({e}), but database record was deleted."

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM fingerprints WHERE id = %s",
        (row["id"],)
    )
    conn.commit()
    return f"Slot #{row['template_id']} deleted from hardware and database. {device_msg}"


def _get_db_conn_and_cursor(db_pool=None):
    """
    Get a DB connection and dictionary cursor safely, whether inside a Flask 
    request context or in a standalone background thread.
    """
    try:
        from flask import has_request_context
        if has_request_context():
            return None, get_cursor()
    except Exception:
        pass

    import core.db as core_db
    conn = None
    if db_pool and hasattr(db_pool, 'get_connection'):
        conn = db_pool.get_connection()
    else:
        if getattr(core_db, 'connection_pool', None) is None:
            core_db.init_db_pool()
        conn = core_db.connection_pool.get_connection()

    cursor = conn.cursor(dictionary=True, buffered=True)
    return conn, cursor


def lookup_student_by_template(camera_id, template_id, db_pool=None):
    """Given a device + the template ID the sensor just matched, find the student."""
    conn, cursor = _get_db_conn_and_cursor(db_pool)
    try:
        cursor.execute(
            """
            SELECT f.student_id, s.usn, u.full_name AS name, s.section_id
            FROM fingerprints f
            JOIN students s ON s.id = f.student_id
            JOIN users u ON u.id = s.user_id
            WHERE f.camera_id = %s AND f.template_id = %s AND f.status = 'active'
            """,
            (camera_id, template_id)
        )
        return cursor.fetchone()
    finally:
        if cursor and conn:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass