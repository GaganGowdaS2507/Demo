"""
attendance_system/api/mobile/sessions.py

Mobile session APIs.
"""

import os
import re
import uuid
import datetime
import logging

from flask import jsonify, request
from werkzeug.utils import secure_filename

from . import mobile_bp
from .sync import mobile_token_required
from .voice_search import parse_transcript, search_roster

from core.db import get_db
from recognition.classroom_photo import recognize_classroom_photos

logger = logging.getLogger(__name__)

@mobile_bp.route("/sessions/today", methods=["GET"])
@mobile_token_required
def get_today_sessions():

    if request.mobile_user.get("role") not in ("faculty", "admin", "hod"):
        return jsonify({
            "success": False,
            "message": "Faculty access required."
        }), 403

    weekday = datetime.datetime.now().strftime("%A")

    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute("""
        SELECT
            t.id AS timetable_id,
            t.section_id,
            s.section_label,
            t.subject_id,
            sub.name AS subject_name,
            t.start_time,
            t.end_time,
            t.room,
            t.slot_type
        FROM timetable t

        JOIN faculty f
            ON f.id = t.faculty_id

        JOIN sections s
            ON s.id = t.section_id

        JOIN subjects sub
            ON sub.id = t.subject_id

        WHERE
            f.user_id = %s
            AND t.day_of_week = %s
            AND t.is_active = 1
            AND t.slot_type NOT IN ('Interval', 'Lunch')

        ORDER BY t.start_time
    """, (
        request.mobile_user["user_id"],
        weekday
    ))

    sessions = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify({
        "success": True,
        "today": weekday,
        "count": len(sessions),
        "sessions": sessions
    })

@mobile_bp.route("/sync", methods=["GET"])
@mobile_token_required
def mobile_sync():
    if request.mobile_user.get("role") not in ("faculty", "admin", "hod"):
        return jsonify({"success": False, "message": "Faculty access required"}), 403

    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)

    # sessions.faculty_id references faculty.id, not users.id — translate first.
    cursor.execute("SELECT id FROM faculty WHERE user_id = %s LIMIT 1", (request.mobile_user["user_id"],))
    fac = cursor.fetchone()
    if not fac:
        cursor.close()
        return jsonify({"success": False, "message": "Faculty record not found"}), 404
    faculty_id = fac["id"]

    cursor.execute(
        """
        SELECT s.id AS session_id,
               s.session_date,
               s.start_time,
               s.end_time,
               s.section_id,
               sec.section_label,
               s.subject_id,
               sub.code AS subject_code,
               COALESCE(sub.name, sub.code, '') AS subject_name,
               s.status,
               s.is_proxy,
               s.delegated_faculty_id
        FROM sessions s
        JOIN sections sec ON sec.id = s.section_id
        LEFT JOIN subjects sub ON sub.id = s.subject_id
        WHERE (s.faculty_id = %s OR s.substitute_faculty_id = %s OR s.delegated_faculty_id = %s)
        ORDER BY s.session_date DESC, s.start_time ASC
        """,
        (faculty_id, faculty_id, faculty_id),
    )
    rows = cursor.fetchall()
    cursor.close()

    sessions = [
        {
            "session_id": row["session_id"],
            "session_date": row["session_date"].strftime("%Y-%m-%d") if hasattr(row["session_date"], "strftime") else row["session_date"],
            "start_time": str(row["start_time"]),
            "end_time": str(row["end_time"]),
            "section_id": row["section_id"],
            "section_label": row["section_label"],
            "subject_id": row.get("subject_id"),
            "subject_code": row.get("subject_code"),
            "subject_name": row["subject_name"],
            "status": row["status"],
            "is_proxy": row.get("is_proxy", 0),
        }
        for row in rows
    ]

    return jsonify({"success": True, "role": "faculty", "faculty_id": faculty_id, "sessions": sessions})


@mobile_bp.route("/session/<int:session_id>/roster", methods=["GET"])
@mobile_token_required
def get_session_roster(session_id):
    if request.mobile_user.get("role") not in ("faculty", "admin", "hod"):
        return jsonify({"success": False, "message": "Faculty access required"}), 403

    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute(
        """
        SELECT s.section_id, f.user_id AS faculty_user_id, sf.user_id AS sub_faculty_user_id, df.user_id AS delegated_faculty_user_id
        FROM sessions s
        JOIN faculty f ON f.id = s.faculty_id
        LEFT JOIN faculty sf ON sf.id = s.substitute_faculty_id
        LEFT JOIN faculty df ON df.id = s.delegated_faculty_id
        WHERE s.id = %s
        LIMIT 1
        """,
        (session_id,),
    )
    sess = cursor.fetchone()
    if not sess:
        cursor.close()
        return jsonify({"success": False, "message": "Session not found"}), 404

    user_id = request.mobile_user["user_id"]
    role = request.mobile_user.get("role")
    if (role not in ("admin", "hod")
        and sess["faculty_user_id"] != user_id
        and sess.get("sub_faculty_user_id") != user_id
        and sess.get("delegated_faculty_user_id") != user_id):
        cursor.close()
        return jsonify({"success": False, "message": "Not your session"}), 403

    cursor.execute(
        """
        SELECT s.id AS student_id, s.usn, u.full_name AS name,
               COALESCE(a.status, 'absent') AS status,
               a.method,
               a.marked_at
        FROM students s
        JOIN users u ON u.id = s.user_id
        LEFT JOIN attendance a ON a.student_id = s.id AND a.session_id = %s
        WHERE s.section_id = %s
        ORDER BY (CASE WHEN a.status = 'present' THEN 0 ELSE 1 END), a.marked_at DESC, u.full_name ASC
        """,
        (session_id, sess["section_id"]),
    )
    roster = [
        {
            "student_id": r["student_id"],
            "usn": r["usn"],
            "name": r["name"],
            "status": r["status"],
            "method": r.get("method"),
        }
        for r in cursor.fetchall()
    ]
    cursor.close()
    return jsonify({"success": True, "roster": roster})


@mobile_bp.route("/sessions/<int:session_id>/classroom_photos", methods=["POST"])
@mobile_token_required
def upload_mobile_classroom_photos(session_id):
    if request.mobile_user.get("role") not in ("faculty", "admin", "hod"):
        return jsonify({"success": False, "message": "Faculty access required"}), 403

    files = request.files.getlist("photos")
    if not files or len(files) == 0:
        return jsonify({"success": False, "message": "No photos provided"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    cursor.execute("SELECT section_id FROM sessions WHERE id = %s", (session_id,))
    sess = cursor.fetchone()
    cursor.close()
    if not sess:
        return jsonify({"success": False, "message": "Session not found"}), 404

    classroom_folder = os.path.join(os.path.dirname(__file__), "../../static/uploads/classroom_photos")
    os.makedirs(classroom_folder, exist_ok=True)
    saved_paths = []
    for f in files:
        if f and f.filename:
            filename = f"{session_id}_{uuid.uuid4().hex[:8]}_{secure_filename(f.filename)}"
            save_path = os.path.join(classroom_folder, filename)
            f.save(save_path)
            saved_paths.append(save_path)

    try:
        from core.db import init_db_pool, connection_pool
        init_db_pool()
        import app as _app
        if not _app.recognition_engine or not _app.recognition_engine.is_initialized:
            _app.init_recognition()

        recognition_engine = _app.recognition_engine
        recognition_engine.reload_embedding_index(connection_pool)
        recognition_engine.refresh_student_cache(connection_pool)

        result = recognize_classroom_photos(saved_paths, recognition_engine, sess["section_id"])
        matched = []
        for m in result.get("matched", []):
            matched.append({
                "student_id": int(m["student_id"]),
                "usn": str(m["usn"] or ""),
                "full_name": str(m["full_name"] or ""),
                "score": float(m["score"]),
                "source_photo": int(m.get("source_photo", 0)),
            })

        return jsonify({
            "success": True,
            "matched": matched,
            "unrecognized_count": int(len(result.get("unrecognized_faces", []))),
            "total_faces_detected": int(result.get("total_faces_detected", 0)),
            "photos_processed": int(result.get("photos_processed", 0)),
        })
    except Exception as e:
        logger.error(f"Mobile classroom photo recognition failed: {e}")
        return jsonify({"success": False, "message": f"Recognition failed: {e}"}), 500


# =============================================================================
# VOICE ATTENDANCE — ENDPOINT 1: Search
# POST /api/mobile/session/<session_id>/voice_search
#
# Request JSON:
#   { "transcript": "Mark Gagan Gowda present" }
#
# Response:
#   {
#     "success": true,
#     "status": "exact" | "multiple" | "not_found",
#     "parsed": { "type": "usn"|"roll"|"name"|"unknown", "value": "..." },
#     "matches": [
#       { "student_id": 7, "usn": "1BM22CS001", "name": "Gagan Gowda",
#         "current_status": "absent" },
#       ...
#     ]
#   }
#
# Security:
#   - Bearer token required (mobile_token_required).
#   - Faculty must own (or be delegated to) the session.
#   - Only students enrolled in the session's section are returned.
#   - Read-only — no attendance is written here.
# =============================================================================

@mobile_bp.route("/session/<int:session_id>/voice_search", methods=["POST"])
@mobile_token_required
def voice_attendance_search(session_id):
    """
    Parse a raw speech-to-text transcript and return matching students
    from the session roster. Never writes any attendance record.
    """
    if request.mobile_user.get("role") not in ("faculty", "admin", "hod"):
        return jsonify({"success": False, "message": "Faculty access required"}), 403

    body = request.get_json(silent=True) or {}
    transcript = (body.get("transcript") or "").strip()
    if not transcript:
        return jsonify({"success": False, "message": "transcript is required"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)

    # ── 1. Verify session exists and belongs to this faculty ──────────────────
    cursor.execute(
        """
        SELECT s.section_id,
               f.user_id  AS faculty_user_id,
               sf.user_id AS sub_faculty_user_id,
               df.user_id AS delegated_faculty_user_id
        FROM   sessions s
        JOIN   faculty  f  ON f.id  = s.faculty_id
        LEFT JOIN faculty sf ON sf.id = s.substitute_faculty_id
        LEFT JOIN faculty df ON df.id = s.delegated_faculty_id
        WHERE  s.id = %s
        LIMIT  1
        """,
        (session_id,),
    )
    sess = cursor.fetchone()
    if not sess:
        cursor.close()
        return jsonify({"success": False, "message": "Session not found"}), 404

    user_id = request.mobile_user["user_id"]
    role    = request.mobile_user.get("role")
    if (
        role not in ("admin", "hod")
        and sess["faculty_user_id"]          != user_id
        and sess.get("sub_faculty_user_id")  != user_id
        and sess.get("delegated_faculty_user_id") != user_id
    ):
        cursor.close()
        return jsonify({"success": False, "message": "Not your session"}), 403

    section_id = sess["section_id"]

    # ── 2. Load section roster with current attendance status ─────────────────
    cursor.execute(
        """
        SELECT st.id AS student_id,
               st.usn,
               u.full_name AS name,
               COALESCE(a.status, 'absent') AS current_status
        FROM   students st
        JOIN   users    u  ON u.id  = st.user_id
        LEFT JOIN attendance a
               ON  a.student_id = st.id
               AND a.session_id = %s
        WHERE  st.section_id = %s
        ORDER BY u.full_name ASC
        """,
        (session_id, section_id),
    )
    roster = [
        {
            "student_id":    r["student_id"],
            "usn":           r["usn"],
            "name":          r["name"],
            "current_status": r["current_status"],
        }
        for r in cursor.fetchall()
    ]
    cursor.close()

    if not roster:
        return jsonify({
            "success": True,
            "status":  "not_found",
            "parsed":  {"type": "unknown", "value": transcript},
            "matches": [],
            "message": "Roster is empty for this session.",
        })

    # ── 3. Parse transcript and match against roster ──────────────────────────
    parsed = parse_transcript(transcript)
    result = search_roster(parsed, roster)

    logger.info(
        "[VoiceSearch] session=%d user=%d transcript=%r parsed=%r status=%s matches=%d",
        session_id, user_id, transcript, parsed, result["status"], len(result["matches"]),
    )

    return jsonify({
        "success": True,
        "status":  result["status"],
        "parsed":  result["parsed"],
        "matches": result["matches"],
    })


# =============================================================================
# VOICE ATTENDANCE — ENDPOINT 2: Mark
# POST /api/mobile/session/<session_id>/voice_mark
#
# Request JSON:
#   { "student_id": 7, "status": "present" }
#
# Response:
#   {
#     "success": true,
#     "student_id": 7,
#     "usn": "1BM22CS001",
#     "name": "Gagan Gowda",
#     "status": "present",
#     "method": "voice_command"
#   }
#
# Security:
#   - Bearer token required.
#   - Faculty must own the session (same ownership check as voice_search).
#   - Student must belong to the session's section.
#   - Duplicate calls are idempotent (ON DUPLICATE KEY UPDATE mirrors sync.py).
#   - Cannot modify sessions, subjects, users, or other admin data.
# =============================================================================

@mobile_bp.route("/session/<int:session_id>/voice_mark", methods=["POST"])
@mobile_token_required
def voice_attendance_mark(session_id):
    """
    Mark a single student present/absent via a confirmed voice command.
    Faculty must have already called voice_search, reviewed the result,
    and confirmed the correct student before calling this endpoint.
    """
    if request.mobile_user.get("role") not in ("faculty", "admin", "hod"):
        return jsonify({"success": False, "message": "Faculty access required"}), 403

    body = request.get_json(silent=True) or {}
    raw_student_id = body.get("student_id")
    raw_status     = str(body.get("status", "present")).strip().lower()

    if raw_student_id is None:
        return jsonify({"success": False, "message": "student_id is required"}), 400
    try:
        student_id = int(raw_student_id)
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "student_id must be an integer"}), 400

    if raw_status not in ("present", "absent"):
        return jsonify({"success": False,
                        "message": "status must be 'present' or 'absent'"}), 400

    conn   = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)

    # ── 1. Verify session exists and belongs to this faculty ──────────────────
    cursor.execute(
        """
        SELECT s.section_id,
               f.user_id  AS faculty_user_id,
               sf.user_id AS sub_faculty_user_id,
               df.user_id AS delegated_faculty_user_id
        FROM   sessions s
        JOIN   faculty  f  ON f.id  = s.faculty_id
        LEFT JOIN faculty sf ON sf.id = s.substitute_faculty_id
        LEFT JOIN faculty df ON df.id = s.delegated_faculty_id
        WHERE  s.id = %s
        LIMIT  1
        """,
        (session_id,),
    )
    sess = cursor.fetchone()
    if not sess:
        cursor.close()
        return jsonify({"success": False, "message": "Session not found"}), 404

    user_id = request.mobile_user["user_id"]
    role    = request.mobile_user.get("role")
    if (
        role not in ("admin", "hod")
        and sess["faculty_user_id"]          != user_id
        and sess.get("sub_faculty_user_id")  != user_id
        and sess.get("delegated_faculty_user_id") != user_id
    ):
        cursor.close()
        return jsonify({"success": False, "message": "Not your session"}), 403

    section_id = sess["section_id"]

    # ── 2. Verify student belongs to this session's section ───────────────────
    cursor.execute(
        """
        SELECT st.id AS student_id, st.usn, u.full_name AS name
        FROM   students st
        JOIN   users    u ON u.id = st.user_id
        WHERE  st.id         = %s
          AND  st.section_id = %s
        LIMIT  1
        """,
        (student_id, section_id),
    )
    student = cursor.fetchone()
    if not student:
        cursor.close()
        return jsonify({
            "success": False,
            "message": f"Student {student_id} not found in section {section_id}",
        }), 404

    # ── 3. Write attendance (identical SQL to sync.py) ────────────────────────
    try:
        cursor.execute(
            """
            INSERT INTO attendance
                (session_id, student_id, usn, status, method,
                 recognition_score, fingerprint_score, marked_by, marked_at)
            VALUES (%s, %s, %s, %s, 'voice_command', NULL, NULL, %s, NOW())
            ON DUPLICATE KEY UPDATE
                status     = VALUES(status),
                method     = VALUES(method),
                marked_by  = VALUES(marked_by),
                marked_at  = NOW()
            """,
            (session_id, student_id, student["usn"], raw_status, user_id),
        )
        conn.commit()
    except Exception as db_err:
        cursor.close()
        logger.error("[VoiceMark] DB error: %s", db_err)
        return jsonify({"success": False, "message": f"Database error: {db_err}"}), 500
    finally:
        cursor.close()

    logger.info(
        "[VoiceMark] session=%d student=%d (%s) status=%s marked_by=%d",
        session_id, student_id, student["usn"], raw_status, user_id,
    )

    return jsonify({
        "success":    True,
        "student_id": student["student_id"],
        "usn":        student["usn"],
        "name":       student["name"],
        "status":     raw_status,
        "method":     "voice_command",
    })


@mobile_bp.route("/session/<int:session_id>/voice_batch_mark", methods=["POST"])
@mobile_token_required
def mobile_voice_batch_mark(session_id):
    """
    Continuous multi-student mobile voice attendance.
    Parses continuous transcript across section roster with support for:
      - Mode 1 (bulk_present): Default Absent (read present ones)
      - Mode 2 (bulk_absent) : Default Present (read absent ones)
      - Mode 3 (name_status) : Say name then status
    """
    if request.mobile_user.get("role") not in ("faculty", "admin", "hod"):
        return jsonify({"success": False, "message": "Faculty access required"}), 403

    body = request.get_json(silent=True) or {}
    transcript = (body.get("transcript") or "").strip()
    voice_mode = str(body.get("voice_mode", "name_status")).strip().lower()
    default_status = str(body.get("default_status", "present")).strip().lower()
    if default_status not in ("present", "absent"):
        default_status = "present"

    if not transcript:
        return jsonify({"success": False, "message": "Voice transcript is required."}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute(
        """
        SELECT s.section_id,
               f.user_id  AS faculty_user_id,
               sf.user_id AS sub_faculty_user_id,
               df.user_id AS delegated_faculty_user_id
        FROM   sessions s
        JOIN   faculty  f  ON f.id  = s.faculty_id
        LEFT JOIN faculty sf ON sf.id = s.substitute_faculty_id
        LEFT JOIN faculty df ON df.id = s.delegated_faculty_id
        WHERE  s.id = %s
        LIMIT  1
        """,
        (session_id,),
    )
    sess = cursor.fetchone()
    if not sess:
        cursor.close()
        return jsonify({"success": False, "message": "Session not found"}), 404

    user_id = request.mobile_user["user_id"]
    role    = request.mobile_user.get("role")
    if (
        role not in ("admin", "hod")
        and sess["faculty_user_id"]          != user_id
        and sess.get("sub_faculty_user_id")  != user_id
        and sess.get("delegated_faculty_user_id") != user_id
    ):
        cursor.close()
        return jsonify({"success": False, "message": "Not your session"}), 403

    section_id = sess["section_id"]

    cursor.execute(
        """
        SELECT st.id AS student_id, st.usn, u.full_name AS name
        FROM students st
        JOIN users u ON u.id = st.user_id
        WHERE st.section_id = %s
        ORDER BY u.full_name ASC
        """,
        (section_id,)
    )
    roster = cursor.fetchall()
    if not roster:
        cursor.close()
        return jsonify({"success": False, "message": "Roster is empty."}), 404

    from .voice_search import parse_batch_transcript
    batch_res = parse_batch_transcript(transcript, roster, default_status=default_status, voice_mode=voice_mode)
    marked_list = batch_res["marked"]

    if not marked_list and voice_mode == "name_status":
        cursor.close()
        return jsonify({
            "success": True,
            "marked_count": 0,
            "marked": [],
            "ambiguous": batch_res["ambiguous"],
            "not_found": batch_res["not_found"],
            "message": "No matching students were identified from the transcript."
        })

    marked_ids = {st["student_id"] for st in marked_list}
    full_batch_list = list(marked_list)
    if voice_mode == "bulk_absent":
        for st in roster:
            if st["student_id"] not in marked_ids:
                st_copy = dict(st)
                st_copy["target_status"] = "present"
                full_batch_list.append(st_copy)
    elif voice_mode == "bulk_present":
        for st in roster:
            if st["student_id"] not in marked_ids:
                st_copy = dict(st)
                st_copy["target_status"] = "absent"
                full_batch_list.append(st_copy)

    marked_list = full_batch_list

    try:
        upsert_sql = """
            INSERT INTO attendance
                (session_id, student_id, usn, status, method, marked_by, marked_at)
            VALUES (%s, %s, %s, %s, 'voice_command', %s, NOW())
            ON DUPLICATE KEY UPDATE
                status    = VALUES(status),
                method    = VALUES(method),
                marked_by = VALUES(marked_by),
                marked_at = NOW()
        """
        rows = [
            (
                session_id,
                st["student_id"],
                st["usn"],
                st.get("target_status", default_status),
                user_id
            )
            for st in marked_list
        ]
        cursor.executemany(upsert_sql, rows)
        conn.commit()
    except Exception as db_err:
        cursor.close()
        logger.error("[MobileVoiceBatchMark] DB error: %s", db_err)
        return jsonify({"success": False, "message": f"Database error: {db_err}"}), 500
    finally:
        cursor.close()

    now_time = datetime.datetime.now().strftime("%H:%M:%S")
    return jsonify({
        "success": True,
        "marked_count": len(marked_list),
        "marked": [
            {
                "student_id": st["student_id"],
                "usn": st["usn"],
                "name": st["name"],
                "status": st.get("target_status", default_status),
                "marked_at": now_time
            }
            for st in marked_list
        ],
        "ambiguous": batch_res["ambiguous"],
        "not_found": batch_res["not_found"],
        "marked_at": now_time
    })