"""
attendance_system/api/mobile/sync.py
Mobile sync surface: faculty/student setup data, embeddings download,
and offline attendance sync.
"""
import os
import time
import logging
from functools import wraps
from flask import request, jsonify
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from core.db import get_db, get_cursor
from . import mobile_bp

logger = logging.getLogger(__name__)

def _serializer():
    secret = os.getenv("SECRET_KEY", "mobile-secret-key-change-me")
    return URLSafeTimedSerializer(secret_key=secret, salt="mobile-auth-token-salt")

def _issue_token(user_row: dict) -> str:
    s = _serializer()
    data = {
        "user_id": user_row["id"],
        "email": user_row["email"],
        "role": user_row["role"],
        "created_at": int(time.time()),
    }
    return s.dumps(data)

def mobile_token_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        token = auth.replace("Bearer ", "").strip() if auth.startswith("Bearer ") else ""
        if not token:
            return jsonify({"success": False, "message": "Missing Authorization header"}), 401
        try:
            s = _serializer()
            data = s.loads(token, max_age=86400 * 30)  # 30 days
        except (BadSignature, SignatureExpired):
            return jsonify({"success": False, "message": "Invalid or expired token"}), 401
        request.mobile_user = data
        return f(*args, **kwargs)
    return wrapper

@mobile_bp.route("/attendance/sync", methods=["POST"])
@mobile_token_required
def sync_attendance():
    if request.mobile_user.get("role") not in ("faculty", "admin", "hod"):
        return jsonify({"success": False, "message": "Faculty access required"}), 403

    body = request.get_json(silent=True) or {}
    records = body.get("records") or []
    if not isinstance(records, list) or not records:
        return jsonify({"success": False, "message": "No records provided"}), 400

    marked_by = request.mobile_user["user_id"]
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute("SELECT id FROM faculty WHERE user_id = %s LIMIT 1", (marked_by,))
    fac = cursor.fetchone()
    if not fac:
        cursor.close()
        return jsonify({"success": False, "message": "Faculty record not found"}), 404
    faculty_id = fac["id"]

    session_ids = []
    for rec in records:
        sid = rec.get("session_id")
        if sid is not None:
            try:
                session_ids.append(int(sid))
            except (ValueError, TypeError):
                pass
    session_ids = list(set(session_ids))

    owned_session_ids = set()
    if session_ids:
        placeholders = ",".join(["%s"] * len(session_ids))
        cursor.execute(
            f"""
            SELECT id FROM sessions
            WHERE id IN ({placeholders})
              AND (faculty_id = %s OR substitute_faculty_id = %s OR delegated_faculty_id = %s)
            """,
            (*session_ids, faculty_id, faculty_id, faculty_id),
        )
        owned_session_ids = {int(row["id"]) for row in cursor.fetchall()}

    inserted = skipped = 0
    errors = []
    try:
        for rec in records:
            raw_sid = rec.get("session_id")
            raw_st_id = rec.get("student_id")
            if raw_sid is None or raw_st_id is None:
                skipped += 1
                errors.append(f"record missing session_id ({raw_sid}) or student_id ({raw_st_id})")
                continue

            try:
                sid = int(raw_sid)
                student_id = int(raw_st_id)
            except (ValueError, TypeError):
                skipped += 1
                errors.append(f"invalid session_id ({raw_sid}) or student_id ({raw_st_id})")
                continue

            if sid not in owned_session_ids:
                skipped += 1
                errors.append(f"session {sid}: not owned by this faculty (faculty_id={faculty_id}) — rejected")
                continue

            rec_status = str(rec.get("status", "present")).strip().lower()
            if rec_status not in ("present", "absent"):
                rec_status = "present"

            usn = rec.get("usn")
            if not usn:
                cursor.execute("SELECT usn FROM students WHERE id = %s LIMIT 1", (student_id,))
                stu_row = cursor.fetchone()
                usn = stu_row["usn"] if stu_row else ""

            match_score = rec.get("match_score")
            try:
                match_score = float(match_score) if match_score is not None else None
            except (ValueError, TypeError):
                match_score = None

            fp_score = rec.get("fingerprint_score")
            try:
                fp_score = float(fp_score) if fp_score is not None else None
            except (ValueError, TypeError):
                fp_score = None

            method_val = rec.get("method") or ("face_recognition" if match_score is not None else "manual_individual")

            try:
                cursor.execute(
                    """
                    INSERT INTO attendance
                        (session_id, student_id, usn, status, method,
                         recognition_score, fingerprint_score, marked_by, marked_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON DUPLICATE KEY UPDATE
                        status = VALUES(status),
                        method = VALUES(method),
                        recognition_score = COALESCE(VALUES(recognition_score), recognition_score),
                        fingerprint_score = COALESCE(VALUES(fingerprint_score), fingerprint_score),
                        marked_by = VALUES(marked_by),
                        marked_at = NOW()
                    """,
                    (sid, student_id, usn, rec_status, method_val, match_score, fp_score, marked_by),
                )
                inserted += 1
            except Exception as e:
                skipped += 1
                errors.append(f"student {student_id} (session {sid}): {e}")
        conn.commit()
    finally:
        cursor.close()

    return jsonify({"success": True, "inserted": inserted, "skipped": skipped, "errors": errors})