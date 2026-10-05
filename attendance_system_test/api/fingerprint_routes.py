"""
Fingerprint Device API Routes
Provides endpoints for USB-connected fingerprint devices:
- POST /api/fingerprint/scan
- POST /api/fingerprint/enroll
- POST /api/fingerprint/delete
- GET  /api/fingerprint/list
"""
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from core.db import get_db

logger = logging.getLogger(__name__)

fp_bp = Blueprint("fingerprint_api", __name__, url_prefix="/api/fingerprint")

def _resolve_camera_id(cursor, device_id_raw):
    """Resolve a valid camera_id for the fingerprint device."""
    if device_id_raw is not None:
        try:
            cid = int(device_id_raw)
            cursor.execute("SELECT id FROM cameras WHERE id = %s", (cid,))
            if cursor.fetchone():
                return cid
        except (ValueError, TypeError):
            cursor.execute("SELECT id FROM cameras WHERE name = %s", (str(device_id_raw),))
            row = cursor.fetchone()
            if row:
                return row["id"]
    # Fallback to camera 2 ('Attendance device') or first camera
    cursor.execute("SELECT id FROM cameras WHERE id = 2")
    row = cursor.fetchone()
    if row:
        return 2
    cursor.execute("SELECT id FROM cameras ORDER BY id LIMIT 1")
    row = cursor.fetchone()
    return row["id"] if row else 1

def _lookup_student(cursor, device_id_raw, template_id):
    """Find the student mapped to this template_id."""
    camera_id = _resolve_camera_id(cursor, device_id_raw)
    cursor.execute("""
        SELECT f.template_id, f.student_id, f.camera_id, s.usn, u.full_name AS student_name, s.section_id
        FROM fingerprints f
        JOIN students s ON s.id = f.student_id
        JOIN users u ON u.id = s.user_id
        WHERE f.template_id = %s AND f.status = 'active'
        ORDER BY (f.camera_id = %s) DESC
        LIMIT 1
    """, (template_id, camera_id))
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "id": row["student_id"],
        "name": row["student_name"],
        "usn": row["usn"],
        "section_id": row["section_id"],
    }

@fp_bp.route("/scan", methods=["POST"])
def fp_scan():
    try:
        d = request.get_json(force=True, silent=True) or {}
        device_id_raw = d.get("device_id")
        template_id = d.get("template_id")
        if template_id is None:
            return jsonify({"error": "missing template_id", "success": False}), 400
        template_id = int(template_id)
        session_id = d.get("session_id")
        score = d.get("score", 0)
        ts = d.get("timestamp")

        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)

        student = _lookup_student(cursor, device_id_raw, template_id)
        if not student:
            cursor.close()
            return jsonify({"error": f"template {template_id} not mapped to any student", "success": False}), 404

        # If a session_id is provided, mark attendance
        if session_id:
            try:
                sid = int(session_id)
                marked_time = datetime.fromtimestamp(float(ts)) if ts else datetime.now()
                cursor.execute("""
                    INSERT INTO attendance (session_id, student_id, usn, status, method, fingerprint_score, marked_at)
                    VALUES (%s, %s, %s, 'present', 'fingerprint', %s, %s)
                    ON DUPLICATE KEY UPDATE
                        status = 'present',
                        method = 'fingerprint',
                        fingerprint_score = VALUES(fingerprint_score),
                        marked_at = VALUES(marked_at)
                """, (sid, student["id"], student["usn"], score, marked_time))
                conn.commit()
            except Exception as ex:
                logger.error("Error marking attendance in fp_scan: %s", ex)

        cursor.close()
        return jsonify({
            "success": True,
            "student_id": student["id"],
            "student_name": student["name"],
            "usn": student["usn"]
        })
    except Exception as e:
        logger.exception("fp_scan exception: %s", e)
        return jsonify({"error": str(e), "success": False}), 500

@fp_bp.route("/enroll", methods=["POST"])
def fp_enroll():
    try:
        d = request.get_json(force=True, silent=True) or {}
        device_id_raw = d.get("device_id")
        template_id = d.get("template_id")
        roll = str(d.get("roll", "")).strip()

        if template_id is None or not roll:
            return jsonify({"error": "template_id and roll (USN) are required", "success": False}), 400

        template_id = int(template_id)
        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)

        # Find student by USN, id, or email
        cursor.execute("""
            SELECT s.id, s.usn, u.full_name AS student_name
            FROM students s
            JOIN users u ON u.id = s.user_id
            WHERE s.usn = %s OR s.id = %s OR u.email = %s
            LIMIT 1
        """, (roll, int(roll) if roll.isdigit() else -1, roll))
        student = cursor.fetchone()
        if not student:
            cursor.close()
            return jsonify({"error": f"Student not found for roll/USN: {roll}", "success": False}), 404

        camera_id = _resolve_camera_id(cursor, device_id_raw)

        # Upsert into fingerprints table
        cursor.execute("""
            INSERT INTO fingerprints (student_id, camera_id, template_id, status, enrolled_at)
            VALUES (%s, %s, %s, 'active', NOW())
            ON DUPLICATE KEY UPDATE
                student_id = VALUES(student_id),
                status = 'active',
                enrolled_at = NOW()
        """, (student["id"], camera_id, template_id))
        conn.commit()
        cursor.close()

        logger.info("Enrolled fingerprint: template %s -> %s (%s)", template_id, student["student_name"], student["usn"])
        return jsonify({
            "success": True,
            "student_name": student["student_name"],
            "usn": student["usn"],
            "message": f"Linked template {template_id} to {student['student_name']}"
        })
    except Exception as e:
        logger.exception("fp_enroll exception: %s", e)
        return jsonify({"error": str(e), "success": False}), 500

@fp_bp.route("/delete", methods=["POST"])
def fp_delete():
    try:
        d = request.get_json(force=True, silent=True) or {}
        device_id_raw = d.get("device_id")
        template_id = d.get("template_id")
        if template_id is None:
            return jsonify({"error": "template_id is required", "success": False}), 400

        template_id = int(template_id)
        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)
        camera_id = _resolve_camera_id(cursor, device_id_raw)

        cursor.execute("""
            UPDATE fingerprints
            SET status = 'revoked'
            WHERE template_id = %s AND (camera_id = %s OR camera_id IS NULL)
        """, (template_id, camera_id))
        conn.commit()
        cursor.close()

        logger.info("Deleted/revoked fingerprint: template %s for camera %s", template_id, camera_id)
        return jsonify({
            "success": True,
            "student_name": "deleted",
            "message": f"Deleted template {template_id}"
        })
    except Exception as e:
        logger.exception("fp_delete exception: %s", e)
        return jsonify({"error": str(e), "success": False}), 500

@fp_bp.route("/list", methods=["GET"])
def fp_list():
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)
        cursor.execute("""
            SELECT f.template_id, f.student_id, f.camera_id, s.usn, u.full_name AS student_name
            FROM fingerprints f
            JOIN students s ON s.id = f.student_id
            JOIN users u ON u.id = s.user_id
            WHERE f.status = 'active'
            ORDER BY f.template_id
        """)
        rows = cursor.fetchall()
        cursor.close()
        return jsonify({"success": True, "count": len(rows), "fingerprints": rows})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500
