"""
attendance_system/api/faculty/session_view.py
Session attendance view: student list (green/red), manual overrides,
mark all present/absent, dismiss class, start/stop recognition.
"""

import logging
from datetime import datetime
import uuid
import os
from flask import make_response
from werkzeug.utils import secure_filename
from api.faculty.sheet_ocr import extract_identifiers_from_image, match_students
from recognition.classroom_photo import recognize_classroom_photos
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, jsonify
)
from flask_login import current_user
from core.db import get_db, get_cursor
from auth.helpers import (
    admin_or_faculty_required, log_audit, get_client_ip, profile_completed_required
)
from utils.stream_source import normalize_stream_source, InvalidStreamSource
from api.mobile.voice_search import (
    parse_transcript, parse_bare_identifier, search_roster, parse_batch_transcript
)

logger = logging.getLogger(__name__)

session_view_bp = Blueprint(
    "session_view", __name__,
    template_folder="../../templates/faculty"
)


# ============================================
# SESSION DETAIL VIEW
# ============================================

@session_view_bp.route("/<int:session_id>")
@admin_or_faculty_required
@profile_completed_required
def view_session(session_id):
    """View session attendance details."""
    cursor = get_cursor()

    # Session info
    cursor.execute(
        """
        SELECT s.*, t.start_time, t.end_time, t.slot_type, t.room,
               t.day_of_week,
               sub.code AS subject_code, sub.name AS subject_name,
               sec.id AS section_id, sec.section_label,
               d.code AS dept_code, d.name AS dept_name,
               u.full_name AS faculty_name,
               su.full_name AS substitute_name,
               cam.name AS camera_name, cam.rtsp_url AS camera_rtsp
        FROM sessions s
        LEFT JOIN timetable t 
        ON t.section_id = s.section_id
        AND t.subject_id = s.subject_id
        JOIN sections sec ON sec.id = s.section_id
        JOIN departments d ON d.id = sec.department_id
        LEFT JOIN subjects sub ON sub.id = s.subject_id
        LEFT JOIN faculty f ON f.id = s.faculty_id
        LEFT JOIN users u ON u.id = f.user_id
        LEFT JOIN faculty sf ON sf.id = s.substitute_faculty_id
        LEFT JOIN users su ON su.id = sf.user_id
        LEFT JOIN cameras cam ON cam.id = s.camera_id
        WHERE s.id = %s
        """,
        (session_id,)
    )
    session_data = cursor.fetchone()

    if not session_data:
        flash("Session not found.", "danger")
        return redirect(url_for("faculty.dashboard"))

    if current_user.role == "faculty":
        cursor.execute("SELECT id FROM faculty WHERE user_id = %s", (current_user.id,))
        fac = cursor.fetchone()
        current_fac_id = fac["id"] if fac else None

        # Access is allowed if user is active faculty_id OR (is_proxy=1 AND delegated_faculty_id)
        if current_fac_id and session_data["faculty_id"] != current_fac_id and not (session_data.get("is_proxy") == 1 and session_data.get("delegated_faculty_id") == current_fac_id):
            flash("Access denied: This session has been reclaimed by the primary faculty or is no longer delegated to you.", "warning")
            return redirect(url_for("faculty.dashboard"))

    # Convert timedelta
    for k in ("start_time", "end_time"):
        if session_data.get(k) and hasattr(session_data[k], "total_seconds"):
            total = int(session_data[k].total_seconds())
            hours, remainder = divmod(total, 3600)
            minutes, _ = divmod(remainder, 60)
            session_data[k] = f"{hours:02d}:{minutes:02d}"

    # Get attendance list
    # Get section_id first
    cursor.execute("SELECT section_id FROM sessions WHERE id = %s", (session_id,))
    sess = cursor.fetchone()
    section_id = sess["section_id"]

    # Fetch ALL students with attendance
    cursor.execute(
        """
        SELECT 
            st.id AS student_id,
            st.usn,
            u.full_name,
            COALESCE(a.status, 'absent') AS status,
            a.method,
            a.recognition_score,
            a.marked_at
        FROM students st
        JOIN users u ON u.id = st.user_id
        LEFT JOIN attendance a 
            ON a.student_id = st.id AND a.session_id = %s
        WHERE st.section_id = %s
        ORDER BY (CASE WHEN a.status = 'present' THEN 0 ELSE 1 END), a.marked_at DESC, st.usn ASC
        """,
        (session_id, section_id)
    )

    attendance_list = cursor.fetchall()

    # Counts
    present_count = sum(1 for a in attendance_list if a["status"] == "present")
    absent_count = sum(1 for a in attendance_list if a["status"] == "absent")
    total_count = len(attendance_list)

    # Check if recognition stream is running
    stream_running = False
    stream_status = {}
    try:
        from app import stream_manager
        if stream_manager:
            stream_status = stream_manager.get_stream_status(session_id)
            stream_running = stream_status.get("is_running", False)
    except Exception:
        pass

    # Available cameras for dropdown
    cursor.execute(
        """
        SELECT c.id, c.name, c.rtsp_url, c.status, c.assigned_section_id,
               sec.section_label, d.code AS dept_code
        FROM cameras c
        LEFT JOIN sections sec ON sec.id = c.assigned_section_id
        LEFT JOIN departments d ON d.id = sec.department_id
        ORDER BY c.name
        """
    )
    cameras = cursor.fetchall()


    resp = make_response(render_template(
        "faculty/session_view.html",
        session=session_data,
        attendance=attendance_list,
        present_count=present_count,
        absent_count=absent_count,
        total_count=total_count,
        stream_running=stream_running,
        stream_status=stream_status,
        cameras=cameras,
    ))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


# ============================================
# INDIVIDUAL ATTENDANCE TOGGLE
# ============================================

@session_view_bp.route("/<int:session_id>/toggle/<int:student_id>", methods=["POST"])
@admin_or_faculty_required
@profile_completed_required
def toggle_attendance(session_id, student_id):
    """Toggle a student's attendance (present ↔ absent)."""
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)

        # Get current status
        # Get current status
        cursor.execute(
            "SELECT id, status FROM attendance WHERE session_id = %s AND student_id = %s",
            (session_id, student_id)
        )
        record = cursor.fetchone()

        if record:
            old_status = record["status"]
            new_status = "absent" if old_status == "present" else "present"

            cursor.execute(
                """
                UPDATE attendance
                SET status = %s, method = 'manual_individual',
                    marked_by = %s, marked_at = NOW(),
                    notes = %s
                WHERE id = %s
                """,
                (
                    new_status, current_user.id,
                    f"Manually changed from {old_status} to {new_status} by {current_user.full_name}",
                    record["id"]
                )
            )
        else:
            # ✅ CREATE attendance record if not exists
            new_status = "present"
            old_status = None
            cursor.execute("SELECT usn FROM students WHERE id = %s", (student_id,))
            stu = cursor.fetchone()
            usn = stu["usn"] if stu else None
            cursor.execute(
                """
                INSERT INTO attendance
                (session_id, student_id, usn, status, method, marked_by, marked_at, notes)
                VALUES (%s, %s, %s, %s, 'manual_individual', %s, NOW(), %s)
                """,
                (
                    session_id,
                    student_id,
                    usn,
                    new_status,
                    current_user.id,
                    f"Manually marked present by {current_user.full_name}"
                )
            )
            record_id = cursor.lastrowid

        conn.commit()
        # Get student info for audit log
        cursor.execute("SELECT usn FROM students WHERE id = %s", (student_id,))
        stu = cursor.fetchone()
        usn = stu["usn"] if stu else str(student_id)
        
        attendance_id = record["id"] if record else record_id

        log_audit(
            current_user.id, "toggle_attendance",
            "attendance", attendance_id, old_status, new_status,
            reason=f"Session {session_id}, Student {usn}",
            ip_address=get_client_ip()
        )

        flash(f"Student {usn} marked as {new_status}.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "danger")

    # Handle AJAX vs normal request
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "new_status": new_status, "student_id": student_id})

    return redirect(url_for("session_view.view_session", session_id=session_id))


# ============================================
# MARK ALL PRESENT
# ============================================

@session_view_bp.route("/<int:session_id>/mark-all-present", methods=["POST"])
@admin_or_faculty_required
@profile_completed_required
def mark_all_present(session_id):
    """Mark all students in this session as present."""
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE attendance
            SET status = 'present', method = 'manual_bulk_present',
                marked_by = %s, marked_at = NOW(),
                notes = %s
            WHERE session_id = %s AND status = 'absent'
            """,
            (
                current_user.id,
                f"Bulk marked present by {current_user.full_name}",
                session_id
            )
        )
        affected = cursor.rowcount
        conn.commit()

        log_audit(
              current_user.id, "mark_all_present",
            "attendance", session_id, None,
            f"{affected} students marked present",
            ip_address=get_client_ip()
        )

        flash(f"{affected} students marked as present.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "danger")

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "affected": affected})

    return redirect(url_for("session_view.view_session", session_id=session_id))


# ============================================
# MARK ALL ABSENT
# ============================================

@session_view_bp.route("/<int:session_id>/mark-all-absent", methods=["POST"])
@admin_or_faculty_required
@profile_completed_required
def mark_all_absent(session_id):
    """Mark all students in this session as absent."""
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE attendance
            SET status = 'absent', method = 'manual_bulk_absent',
                marked_by = %s, marked_at = NOW(),
                notes = %s
            WHERE session_id = %s AND status = 'present'
            """,
            (
                current_user.id,
                f"Bulk marked absent by {current_user.full_name}",
                session_id
            )
        )
        affected = cursor.rowcount
        conn.commit()

        log_audit(
              current_user.id, "mark_all_absent",
            "attendance", session_id, None,
            f"{affected} students marked absent",
            ip_address=get_client_ip()
        )

        flash(f"{affected} students marked as absent.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "danger")

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "affected": affected})

    return redirect(url_for("session_view.view_session", session_id=session_id))


# ============================================
# DISMISS CLASS
# ============================================

@session_view_bp.route("/<int:session_id>/dismiss", methods=["POST"])
@admin_or_faculty_required
@profile_completed_required
def dismiss_class(session_id):
    """Faculty dismisses the class."""
    reason = request.form.get("reason", "").strip()

    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE sessions
            SET status = 'dismissed',
                dismiss_reason = %s,
                closed_at = NOW()
            WHERE id = %s AND status IN ('scheduled', 'active')
            """,
            (reason if reason else f"Dismissed by {current_user.full_name}", session_id)
        )
        conn.commit()

        # Stop recognition stream
        try:
            from app import stream_manager
            if stream_manager:
                stream_manager.stop_stream(session_id)
        except Exception:
            pass

        log_audit(
              current_user.id, "dismiss_class",
            "sessions", session_id, None, reason,
            ip_address=get_client_ip()
        )

        flash("Class dismissed.", "info")

    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "danger")

    return redirect(url_for("faculty.dashboard"))


# ============================================
# START/STOP RECOGNITION (Faculty)
# ============================================

@session_view_bp.route("/<int:session_id>/start-recognition", methods=["POST"])
@admin_or_faculty_required
@profile_completed_required
def faculty_start_recognition(session_id):
    """Faculty starts recognition for their session."""
    raw_source = request.form.get("rtsp_url", "").strip()
    camera_id = request.form.get("camera_id", "").strip()
    mode = request.form.get("recognition_mode", "FACE_ONLY").strip().upper()
    if mode not in ("FACE_ONLY", "FINGERPRINT_ONLY", "DUAL_MODE"):
        mode = "FACE_ONLY"

    try:
        rtsp_url = normalize_stream_source(raw_source) if raw_source else ""
    except InvalidStreamSource as e:
        flash(str(e), "danger")
        return redirect(url_for("session_view.view_session", session_id=session_id))

    cam = None

    # Ensure attendance rows exist
    cursor = get_cursor()
    cursor.execute("SELECT section_id FROM sessions WHERE id = %s", (session_id,))
    sess = cursor.fetchone()

    if not sess:
        flash("Session not found.", "danger")
        return redirect(url_for("faculty.dashboard"))
    cursor.execute(
        """
        INSERT IGNORE INTO attendance (session_id, student_id, usn, status, method, marked_at)
        SELECT %s, st.id, st.usn, 'absent', 'system', NOW()
        FROM students st
        WHERE st.section_id = %s
        """,
        (session_id, sess["section_id"])
    )   

    try:
        import app as _app

        # Force-initialize if not done yet
        if not _app.recognition_engine or not _app.recognition_engine.is_initialized:
            _app.init_recognition()

        recognition_engine = _app.recognition_engine
        stream_manager     = _app.stream_manager

        if not recognition_engine or not recognition_engine.is_initialized:
            flash("Recognition engine failed to initialize.", "danger")
            return redirect(url_for("session_view.view_session", session_id=session_id))

        # Load embeddings using the connection pool directly
        from core.db import connection_pool
        if not recognition_engine._emb_index_sids:
            recognition_engine.reload_embedding_index(connection_pool)
            recognition_engine.refresh_student_cache(connection_pool)

        if not stream_manager:
            flash("Stream manager not available.", "danger")
            return redirect(url_for("session_view.view_session", session_id=session_id))

        # Get RTSP URL from camera if not provided directly
        if not rtsp_url and camera_id:
            cursor = get_cursor()
            cursor.execute(
                "SELECT id, rtsp_url, assigned_section_id FROM cameras WHERE id = %s",
                (int(camera_id),)
            )
            cam = cursor.fetchone()
            if not cam:
                flash("Invalid camera selected.", "danger")
                return redirect(url_for("session_view.view_session", session_id=session_id))

            if not rtsp_url:
                rtsp_url = cam.get("rtsp_url")

        if mode != "FINGERPRINT_ONLY" and not rtsp_url:
            flash("Please enter an RTSP URL or select a camera device.", "danger")
            return redirect(url_for("session_view.view_session", session_id=session_id))

        if mode in ("FINGERPRINT_ONLY", "DUAL_MODE") and not camera_id:
            flash("Fingerprint modes require you to pick the device from the "
                  "Device Selection dropdown, not just type its IP. "
                  "Select the device, then try again.", "danger")
            return redirect(url_for("session_view.view_session", session_id=session_id))
        
        # Get section_id for this session
        cursor = get_cursor()
        cursor.execute("SELECT section_id FROM sessions WHERE id = %s", (session_id,))
        sess = cursor.fetchone()
        if not sess:
            flash("Session not found.", "danger")
            return redirect(url_for("faculty.dashboard"))
        if camera_id and cam and cam.get("assigned_section_id") and cam["assigned_section_id"] != sess["section_id"]:
            flash("Selected camera is assigned to a different section.", "danger")
            return redirect(url_for("session_view.view_session", session_id=session_id))

        # Configure ESP32 device mode via control server if reachable
        # Configure ESP32 device mode via control server if reachable
        parsed_cam_id = int(camera_id) if camera_id else None
        if cam or parsed_cam_id:
            try:
                from recognition.fingerprint_service import _device_base_url
                if not cam and parsed_cam_id:
                    cursor.execute("SELECT rtsp_url FROM cameras WHERE id = %s", (parsed_cam_id,))
                    cam = cursor.fetchone()
                if cam and cam.get("rtsp_url"):
                    base_url = _device_base_url(cam)
                    import requests
                    import threading
                    def _arm_device_async(url, m):
                        try:
                            r = requests.get(f"{url}/set-attendance-mode", params={"mode": m}, timeout=1.5)
                            r.raise_for_status()
                            logger.info(f"Device mode set to {m} at {url}")
                        except Exception as e:
                            logger.warning(f"Could not reach ESP32 device to set attendance mode: {e}")

                    threading.Thread(target=_arm_device_async, args=(base_url, mode), daemon=True).start()
                elif mode in ("FINGERPRINT_ONLY", "DUAL_MODE"):
                    flash("Selected device has no address on file — fingerprint mode can't be armed.", "warning")
            except Exception as dev_err:
                logger.warning(f"Could not reach ESP32 device to set attendance mode: {dev_err}")
                if mode in ("FINGERPRINT_ONLY", "DUAL_MODE"):
                    flash(f"Started session, but couldn't reach the fingerprint device to arm it "
                          f"({dev_err}). Touch scans won't be picked up until it's reachable.", "warning")

        # Mark session as active and save recognition_mode
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE sessions
            SET rtsp_url = %s, camera_id = %s, recognition_mode = %s,
                status = 'active', opened_by = %s, opened_at = NOW()
            WHERE id = %s
            """,
            (
                rtsp_url,
                parsed_cam_id,
                mode,
                current_user.id,
                session_id
            )
        )
        conn.commit()

        # Start the recognition worker (Face-Only, Fingerprint-Only, or Dual Mode)
        success, message = stream_manager.start_stream(
            session_id, rtsp_url, sess["section_id"], connection_pool,
            mode=mode, camera_id=parsed_cam_id
        )

        if success:
            flash(f"Attendance started in {mode} mode.", "success")
        else:
            flash(f"Failed to start attendance: {message}", "danger")

    except Exception as e:
        flash(f"Error: {e}", "danger")
        logger.error(f"faculty_start_recognition error: {e}")

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": success if 'success' in locals() else False, "message": message if 'message' in locals() else "Started"})

    return redirect(url_for("session_view.view_session", session_id=session_id))


@session_view_bp.route("/<int:session_id>/stop-recognition", methods=["POST"])
@admin_or_faculty_required
@profile_completed_required
def faculty_stop_recognition(session_id):
    """Faculty stops recognition for their session."""
    try:
        from app import stream_manager
        if stream_manager:
            stream_manager.stop_stream(session_id)
            flash("Recognition stopped.", "info")
        else:
            flash("Stream manager not available.", "warning")
    except Exception as e:
        flash(f"Error: {e}", "danger")

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True})

    return redirect(url_for("session_view.view_session", session_id=session_id))


# ============================================
# ATTENDANCE DATA API (for AJAX refresh)
# ============================================

@session_view_bp.route("/<int:session_id>/api/attendance")
@admin_or_faculty_required
@profile_completed_required
def attendance_data_api(session_id):
    """AJAX: Get live attendance data for a session."""
    cursor = get_cursor()

    cursor.execute(
        """
        SELECT COALESCE(a.status, 'absent') AS status, a.method, a.recognition_score,
               a.liveness_score, a.marked_at,
               s.id AS student_id, s.usn, u.full_name
        FROM students s
        JOIN users u ON u.id = s.user_id
        JOIN sessions sess ON sess.id = %s
        LEFT JOIN attendance a ON a.student_id = s.id AND a.session_id = %s
        WHERE s.section_id = sess.section_id
        ORDER BY (CASE WHEN a.status = 'present' THEN 0 ELSE 1 END), a.marked_at DESC, s.usn ASC
        """,
        (session_id, session_id)
    )
    records = cursor.fetchall()

    # Convert datetime
    for r in records:
        if r.get("marked_at"):
            r["marked_at"] = r["marked_at"].strftime("%H:%M:%S")

    present = sum(1 for r in records if r["status"] == "present")
    absent = sum(1 for r in records if r["status"] == "absent")

    # Get stream status & recent log
    stream_status = {}
    recent_log = []
    try:
        from app import stream_manager
        if stream_manager:
            stream_status = stream_manager.get_stream_status(session_id)
            recent_log = stream_manager.get_log(session_id, last_n=10)
    except Exception:
        pass

    return jsonify({
        "attendance": records,
        "present": present,
        "absent": absent,
        "total": len(records),
        "stream": stream_status,
        "logs": recent_log,
    })


# ============================================
# ADD NOTE TO ATTENDANCE
# ============================================

@session_view_bp.route("/<int:session_id>/note/<int:student_id>", methods=["POST"])
@admin_or_faculty_required
@profile_completed_required
def add_attendance_note(session_id, student_id):
    """Add a note to a student's attendance record."""
    note = request.form.get("note", "").strip()

    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE attendance
            SET notes = %s
            WHERE session_id = %s AND student_id = %s
            """,
            (note, session_id, student_id)
        )
        conn.commit()
        flash("Note added.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "danger")

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True})

    return redirect(url_for("session_view.view_session", session_id=session_id))

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "../../static/uploads/attendance_sheets")
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
CLASSROOM_UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "../../static/uploads/classroom_photos")

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ============================================
# ROUTE 1: Upload sheet → show preview
# ============================================

@session_view_bp.route("/<int:session_id>/upload-sheet", methods=["POST"])
@admin_or_faculty_required
@profile_completed_required
def upload_attendance_sheet(session_id):
    """Receive image upload, run OCR, show confirmation preview."""
    if "sheet_image" not in request.files:
        flash("No file uploaded.", "danger")
        return redirect(url_for("session_view.view_session", session_id=session_id))

    file = request.files["sheet_image"]
    if not file or not allowed_file(file.filename):
        flash("Invalid file. Upload a JPG, PNG, or WEBP image.", "danger")
        return redirect(url_for("session_view.view_session", session_id=session_id))

    # Save file
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    filename = f"{session_id}_{uuid.uuid4().hex[:8]}_{secure_filename(file.filename)}"
    save_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(save_path)

    # Get section_id for this session
    cursor = get_cursor()
    cursor.execute("SELECT section_id FROM sessions WHERE id = %s", (session_id,))
    sess = cursor.fetchone()
    if not sess:
        flash("Session not found.", "danger")
        return redirect(url_for("session_view.view_session", session_id=session_id))

    # Run OCR + matching
    try:
        identifiers = extract_identifiers_from_image(save_path)
        result = match_students(identifiers, sess["section_id"])
    except Exception as e:
        logger.error("OCR error: %s", e)
        flash(f"OCR failed: {e}", "danger")
        return redirect(url_for("session_view.view_session", session_id=session_id))

    return render_template(
        "faculty/sheet_upload_preview.html",
        session_id=session_id,
        matched=result["matched"],
        unmatched=result["unmatched"],
        image_filename=filename,
    )


# ============================================
# ROUTE 2: Confirm → write to attendance table
# ============================================

@session_view_bp.route("/<int:session_id>/confirm-sheet-upload", methods=["POST"])
@admin_or_faculty_required
@profile_completed_required
def confirm_sheet_attendance(session_id):
    """Commit confirmed student IDs as present."""
    student_ids = request.form.getlist("student_ids")  # checkboxes
    if not student_ids:
        flash("No students selected.", "warning")
        return redirect(url_for("session_view.view_session", session_id=session_id))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)

        for sid in student_ids:
            cursor.execute("SELECT usn FROM students WHERE id = %s", (int(sid),))
            stu = cursor.fetchone()
            if not stu:
                continue
            usn = stu["usn"]

            cursor.execute(
                """
                INSERT INTO attendance (session_id, student_id, usn, status, method, marked_by, marked_at, notes)
                VALUES (%s, %s, %s, 'present', 'manual_individual', %s, NOW(), 'Marked via sheet image upload')
                ON DUPLICATE KEY UPDATE
                    status = 'present',
                    method = 'manual_individual',
                    marked_by = %s,
                    marked_at = NOW(),
                    notes = 'Updated via sheet image upload'
                """,
                (session_id, int(sid), usn, current_user.id, current_user.id),
            )

        conn.commit()
        log_audit(
            current_user.id, "sheet_upload_attendance",
            "session", session_id, None, f"{len(student_ids)} students marked present",
            reason="Manual sheet image upload",
            ip_address=get_client_ip(),
        )
        flash(f"✅ {len(student_ids)} students marked present from sheet.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"Error saving attendance: {e}", "danger")

    return redirect(url_for("session_view.view_session", session_id=session_id))

# ============================================
# ROUTE 1: Upload classroom photo(s) -> show preview
# ============================================

@session_view_bp.route("/<int:session_id>/upload-classroom-photo", methods=["POST"])
@admin_or_faculty_required
@profile_completed_required
def upload_classroom_photo(session_id):
    """Receive 1-3 classroom photos, run face recognition, show confirmation preview."""
    files = request.files.getlist("classroom_photos")
    files = [f for f in files if f and f.filename]

    if not files:
        flash("No photo uploaded.", "danger")
        return redirect(url_for("session_view.view_session", session_id=session_id))

    if len(files) > 3:
        flash("Upload at most 3 photos per class.", "danger")
        return redirect(url_for("session_view.view_session", session_id=session_id))

    for f in files:
        if not allowed_file(f.filename):
            flash("Invalid file type. Upload JPG, PNG, or WEBP images only.", "danger")
            return redirect(url_for("session_view.view_session", session_id=session_id))

    cursor = get_cursor()
    cursor.execute("SELECT section_id FROM sessions WHERE id = %s", (session_id,))
    sess = cursor.fetchone()
    if not sess:
        flash("Session not found.", "danger")
        return redirect(url_for("session_view.view_session", session_id=session_id))

    # Save all photos
    os.makedirs(CLASSROOM_UPLOAD_FOLDER, exist_ok=True)
    saved_filenames = []
    saved_paths = []
    for f in files:
        filename = f"{session_id}_{uuid.uuid4().hex[:8]}_{secure_filename(f.filename)}"
        save_path = os.path.join(CLASSROOM_UPLOAD_FOLDER, filename)
        f.save(save_path)
        saved_filenames.append(filename)
        saved_paths.append(save_path)

    # Ensure recognition engine is ready + embeddings/cache are fresh
    try:
        import app as _app
        if not _app.recognition_engine or not _app.recognition_engine.is_initialized:
            _app.init_recognition()

        recognition_engine = _app.recognition_engine
        if not recognition_engine or not recognition_engine.is_initialized:
            flash("Recognition engine failed to initialize.", "danger")
            return redirect(url_for("session_view.view_session", session_id=session_id))

        from core.db import connection_pool
        recognition_engine.reload_embedding_index(connection_pool)
        recognition_engine.refresh_student_cache(connection_pool)

        result = recognize_classroom_photos(
            saved_paths, recognition_engine, sess["section_id"]
        )
    except Exception as e:
        logger.error("Classroom photo recognition error: %s", e)
        flash(f"Recognition failed: {e}", "danger")
        return redirect(url_for("session_view.view_session", session_id=session_id))

    return render_template(
        "faculty/classroom_photo_preview.html",
        session_id=session_id,
        matched=result["matched"],
        unrecognized_count=len(result["unrecognized_faces"]),
        total_faces_detected=result["total_faces_detected"],
        photos_processed=result["photos_processed"],
        image_filenames=saved_filenames,
    )

# ============================================
# ROUTE 2: Confirm -> write to attendance table
# ============================================

@session_view_bp.route("/<int:session_id>/confirm-classroom-photo", methods=["POST"])
@admin_or_faculty_required
@profile_completed_required
def confirm_classroom_photo_attendance(session_id):
    """Commit confirmed student IDs (from classroom photo recognition) as present."""
    student_ids = request.form.getlist("student_ids")  # checkboxes
    if not student_ids:
        flash("No students selected.", "warning")
        return redirect(url_for("session_view.view_session", session_id=session_id))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)

        for sid in student_ids:
            cursor.execute("SELECT usn FROM students WHERE id = %s", (int(sid),))
            stu = cursor.fetchone()
            if not stu:
                continue
            usn = stu["usn"]

            cursor.execute(
                """
                INSERT INTO attendance (session_id, student_id, usn, status, method, marked_by, marked_at, notes)
                VALUES (%s, %s, %s, 'present', 'classroom_photo', %s, NOW(), 'Marked via classroom photo recognition')
                ON DUPLICATE KEY UPDATE
                    status = 'present',
                    method = 'classroom_photo',
                    marked_by = %s,
                    marked_at = NOW(),
                    notes = 'Updated via classroom photo recognition'
                """,
                (session_id, int(sid), usn, current_user.id, current_user.id),
            )

        conn.commit()
        log_audit(
            current_user.id, "classroom_photo_attendance",
            "session", session_id, None, f"{len(student_ids)} students marked present",
            reason="Classroom photo recognition",
            ip_address=get_client_ip(),
        )
        flash(f"✅ {len(student_ids)} students marked present from classroom photo(s).", "success")

    except Exception as e:
        conn.rollback()
        flash(f"Error saving attendance: {e}", "danger")

    return redirect(url_for("session_view.view_session", session_id=session_id))


# ============================================
# FACULTY PROXY / EMERGENCY SESSION DELEGATION
# ============================================

def _cleanup_expired_proxies(cursor, conn):
    """Lazy cleanup to auto-reclaim proxy sessions past 4:30 PM or past dates."""
    today = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M")
    cursor.execute("""
        UPDATE sessions
        SET faculty_id = primary_faculty_id,
            is_proxy = 0,
            delegation_code = NULL
        WHERE is_proxy = 1
          AND primary_faculty_id IS NOT NULL
          AND (session_date < %s OR (session_date = %s AND %s >= '16:30'))
    """, (today, today, current_time))
    conn.commit()


@session_view_bp.route("/<int:session_id>/request-proxy", methods=["POST"])
@admin_or_faculty_required
def request_proxy(session_id):
    """Generate a 4-digit passcode for emergency proxy delegation."""
    today = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    _cleanup_expired_proxies(cursor, conn)

    if current_time >= "16:30":
        return jsonify({
            "success": False,
            "message": "Proxy delegation closes at 4:30 PM. Sessions have been auto-reclaimed to primary faculty."
        }), 400

    import random
    code = f"{random.randint(1000, 9999)}"

    cursor.execute("SELECT id FROM faculty WHERE user_id = %s", (current_user.id,))
    fac = cursor.fetchone()
    primary_id = fac["id"] if fac else None

    cursor.execute(
        """
        UPDATE sessions
        SET is_proxy = 1, primary_faculty_id = %s, delegation_code = %s
        WHERE id = %s
        """,
        (primary_id, code, session_id)
    )
    conn.commit()

    log_audit(
        current_user.id, "request_proxy_session",
        "session", session_id, None, f"Delegation code generated: {code}",
        ip_address=get_client_ip()
    )

    return jsonify({"success": True, "code": code, "message": f"Proxy code generated: {code}"})


@session_view_bp.route("/claim-proxy", methods=["POST"])
@admin_or_faculty_required
def claim_proxy():
    """Claim a proxy session using the 4-digit delegation passcode."""
    code = request.form.get("code", "").strip()
    if not code:
        return jsonify({"success": False, "message": "Please enter a 4-digit passcode."}), 400

    today = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    _cleanup_expired_proxies(cursor, conn)

    if current_time >= "16:30":
        return jsonify({
            "success": False,
            "message": "Proxy claiming closes at 4:30 PM daily. Sessions have been auto-reclaimed to primary faculty."
        }), 400

    cursor.execute("SELECT id FROM faculty WHERE user_id = %s", (current_user.id,))
    fac = cursor.fetchone()
    if not fac:
        return jsonify({"success": False, "message": "Faculty profile not found."}), 404

    cursor.execute(
        "SELECT id, primary_faculty_id, title FROM sessions WHERE delegation_code = %s AND is_proxy = 1 LIMIT 1",
        (code,)
    )
    sess = cursor.fetchone()
    if not sess:
        return jsonify({"success": False, "message": "Invalid or expired proxy passcode."}), 404

    # If the user claiming is the primary faculty owner, reclaim session back!
    if sess.get("primary_faculty_id") == fac["id"]:
        cursor.execute(
            """
            UPDATE sessions
            SET faculty_id = primary_faculty_id,
                is_proxy = 0,
                delegation_code = NULL
            WHERE id = %s
            """,
            (sess["id"],)
        )
        conn.commit()
        log_audit(
            current_user.id, "reclaim_proxy_session",
            "session", sess["id"], None, f"Primary faculty reclaimed session",
            ip_address=get_client_ip()
        )
        return jsonify({"success": True, "session_id": sess["id"], "message": "Session reclaimed back to primary faculty successfully!"})

    cursor.execute(
        """
        UPDATE sessions
        SET delegated_faculty_id = %s, faculty_id = %s
        WHERE id = %s
        """,
        (fac["id"], fac["id"], sess["id"])
    )
    conn.commit()

    log_audit(
        current_user.id, "claim_proxy_session",
        "session", sess["id"], None, f"Claimed proxy session {sess.get('title') or sess['id']}",
        ip_address=get_client_ip()
    )

    return jsonify({"success": True, "session_id": sess["id"], "message": "Proxy session claimed successfully!"})


# =============================================================================
# WEB FACULTY ATTENDANCE SCREEN — VOICE COMMAND ENDPOINTS
# =============================================================================

@session_view_bp.route("/<int:session_id>/voice_search", methods=["POST"])
@admin_or_faculty_required
@profile_completed_required
def web_voice_search(session_id):
    """
    Search session roster using voice command transcript from web browser.
    Validates faculty session rights and returns matching students.
    """
    body = request.get_json(silent=True) or {}
    transcript = (body.get("transcript") or "").strip()
    mode = (body.get("mode") or "name_status").strip()
    if not transcript:
        return jsonify({"success": False, "message": "Voice transcript is required."}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)

    # 1. Verify session exists and belongs to current user
    cursor.execute(
        """
        SELECT s.id, s.section_id, s.faculty_id, s.substitute_faculty_id,
               s.delegated_faculty_id, s.is_proxy
        FROM sessions s
        WHERE s.id = %s
        LIMIT 1
        """,
        (session_id,)
    )
    sess = cursor.fetchone()
    if not sess:
        cursor.close()
        return jsonify({"success": False, "message": "Session not found."}), 404

    if current_user.role == "faculty":
        cursor.execute("SELECT id FROM faculty WHERE user_id = %s", (current_user.id,))
        fac = cursor.fetchone()
        current_fac_id = fac["id"] if fac else None
        if not current_fac_id or (
            sess["faculty_id"] != current_fac_id
            and sess.get("substitute_faculty_id") != current_fac_id
            and not (sess.get("is_proxy") == 1 and sess.get("delegated_faculty_id") == current_fac_id)
        ):
            cursor.close()
            return jsonify({"success": False, "message": "Access denied: Not your session."}), 403

    section_id = sess["section_id"]

    # 2. Get section roster with current attendance status
    cursor.execute(
        """
        SELECT st.id AS student_id, st.usn, u.full_name AS name,
               COALESCE(a.status, 'absent') AS current_status
        FROM students st
        JOIN users u ON u.id = st.user_id
        LEFT JOIN attendance a ON a.student_id = st.id AND a.session_id = %s
        WHERE st.section_id = %s
        ORDER BY u.full_name ASC
        """,
        (session_id, section_id)
    )
    roster = cursor.fetchall()
    cursor.close()

    if not roster:
        return jsonify({
            "success": True,
            "status": "not_found",
            "parsed": {"type": "unknown", "value": transcript},
            "matches": [],
            "message": "No students found in this section's roster."
        })

        # 3. Parse and search roster.
    # bulk_present / bulk_absent modes use the lenient bare-identifier parser
    # since no "present"/"absent" word is expected in the transcript there.
    if mode in ("bulk_present", "bulk_absent"):
        parsed = parse_bare_identifier(transcript)
    else:
        parsed = parse_transcript(transcript)
    result = search_roster(parsed, roster)

    logger.info(
        "[WebVoiceSearch] session=%d user=%d transcript=%r status=%s matches=%d",
        session_id, current_user.id, transcript, result["status"], len(result["matches"])
    )

    return jsonify({
        "success": True,
        "status": result["status"],
        "parsed": result["parsed"],
        "matches": result["matches"]
    })


@session_view_bp.route("/<int:session_id>/voice_mark", methods=["POST"])
@admin_or_faculty_required
@profile_completed_required
def web_voice_mark(session_id):
    """
    Confirm and mark attendance via voice command from web browser.
    Ensures student belongs to the session's section and updates attendance record.
    """
    body = request.get_json(silent=True) or {}
    raw_student_id = body.get("student_id")
    raw_status = str(body.get("status", "present")).strip().lower()

    if raw_student_id is None:
        return jsonify({"success": False, "message": "student_id is required."}), 400
    try:
        student_id = int(raw_student_id)
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "student_id must be an integer."}), 400

    if raw_status not in ("present", "absent"):
        return jsonify({"success": False, "message": "status must be 'present' or 'absent'."}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)

    # 1. Verify session access
    cursor.execute(
        """
        SELECT s.id, s.section_id, s.faculty_id, s.substitute_faculty_id,
               s.delegated_faculty_id, s.is_proxy
        FROM sessions s
        WHERE s.id = %s
        LIMIT 1
        """,
        (session_id,)
    )
    sess = cursor.fetchone()
    if not sess:
        cursor.close()
        return jsonify({"success": False, "message": "Session not found."}), 404

    if current_user.role == "faculty":
        cursor.execute("SELECT id FROM faculty WHERE user_id = %s", (current_user.id,))
        fac = cursor.fetchone()
        current_fac_id = fac["id"] if fac else None
        if not current_fac_id or (
            sess["faculty_id"] != current_fac_id
            and sess.get("substitute_faculty_id") != current_fac_id
            and not (sess.get("is_proxy") == 1 and sess.get("delegated_faculty_id") == current_fac_id)
        ):
            cursor.close()
            return jsonify({"success": False, "message": "Access denied: Not your session."}), 403

    section_id = sess["section_id"]

    # 2. Verify student belongs to section
    cursor.execute(
        """
        SELECT st.id AS student_id, st.usn, u.full_name AS name
        FROM students st
        JOIN users u ON u.id = st.user_id
        WHERE st.id = %s AND st.section_id = %s
        LIMIT 1
        """,
        (student_id, section_id)
    )
    student = cursor.fetchone()
    if not student:
        cursor.close()
        return jsonify({
            "success": False,
            "message": f"Student not found in this section."
        }), 404

    # 3. Insert or update attendance record with method = 'voice_command'
    try:
        cursor.execute(
            """
            INSERT INTO attendance
                (session_id, student_id, usn, status, method, marked_by, marked_at, notes)
            VALUES (%s, %s, %s, %s, 'voice_command', %s, NOW(), %s)
            ON DUPLICATE KEY UPDATE
                status = VALUES(status),
                method = VALUES(method),
                marked_by = VALUES(marked_by),
                marked_at = NOW(),
                notes = VALUES(notes)
            """,
            (
                session_id,
                student_id,
                student["usn"],
                raw_status,
                current_user.id,
                f"Marked {raw_status} via voice command by {current_user.full_name}"
            )
        )
        conn.commit()

        log_audit(
            current_user.id, "voice_mark_attendance",
            "attendance", student_id, None, raw_status,
            reason=f"Session {session_id}, Student {student['usn']} marked {raw_status} via voice command",
            ip_address=get_client_ip()
        )
    except Exception as e:
        cursor.close()
        logger.error("[WebVoiceMark] Database error: %s", e)
        return jsonify({"success": False, "message": f"Database error: {e}"}), 500
    finally:
        cursor.close()

    return jsonify({
        "success": True,
        "student_id": student["student_id"],
        "usn": student["usn"],
        "name": student["name"],
        "status": raw_status,
        "method": "voice_command",
        "marked_at": datetime.now().strftime("%H:%M:%S")
    })


@session_view_bp.route("/<int:session_id>/voice_bulk_default", methods=["POST"])
@admin_or_faculty_required
@profile_completed_required
def web_voice_bulk_default(session_id):
    """
    Set a default status for EVERY student in the session's roster, as the
    first step of the "read the sheet, call out only the exceptions" voice
    attendance modes:
      - default_status = 'absent'  -> faculty will then read out the names
        of the students who ARE present (minority-present class).
      - default_status = 'present' -> faculty will then read out the names
        of the students who ARE absent (minority-absent class, the common
        case of a normal signed attendance sheet).
    Returns the full roster with its new status so the UI can repaint every
    row in one shot.
    """
    body = request.get_json(silent=True) or {}
    default_status = str(body.get("default_status", "")).strip().lower()
    if default_status not in ("present", "absent"):
        return jsonify({"success": False, "message": "default_status must be 'present' or 'absent'."}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)

    # 1. Verify session access (same rule as voice_search / voice_mark)
    cursor.execute(
        """
        SELECT s.id, s.section_id, s.faculty_id, s.substitute_faculty_id,
               s.delegated_faculty_id, s.is_proxy
        FROM sessions s
        WHERE s.id = %s
        LIMIT 1
        """,
        (session_id,)
    )
    sess = cursor.fetchone()
    if not sess:
        cursor.close()
        return jsonify({"success": False, "message": "Session not found."}), 404

    if current_user.role == "faculty":
        cursor.execute("SELECT id FROM faculty WHERE user_id = %s", (current_user.id,))
        fac = cursor.fetchone()
        current_fac_id = fac["id"] if fac else None
        if not current_fac_id or (
            sess["faculty_id"] != current_fac_id
            and sess.get("substitute_faculty_id") != current_fac_id
            and not (sess.get("is_proxy") == 1 and sess.get("delegated_faculty_id") == current_fac_id)
        ):
            cursor.close()
            return jsonify({"success": False, "message": "Access denied: Not your session."}), 403

    section_id = sess["section_id"]

    # 2. Get full section roster
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
        return jsonify({"success": False, "message": "No students found in this section's roster."}), 404

    note = f"Bulk default '{default_status}' set via voice attendance by {current_user.full_name}"

    try:
        if default_status == "absent":
            # The un-marked / default state for any student in this app IS
            # 'absent' (see COALESCE(a.status, 'absent') everywhere else), so
            # we only need to force any EXISTING record back to absent —
            # students with no row at all are already absent by default.
            cursor.execute(
                """
                UPDATE attendance
                SET status = 'absent', method = 'voice_command', marked_by = %s,
                    marked_at = NOW(), notes = %s
                WHERE session_id = %s
                """,
                (current_user.id, note, session_id)
            )
        else:
            # default_status == 'present': every student needs an actual row,
            # otherwise they'd still read as 'absent' via the COALESCE default.
            upsert_sql = """
                INSERT INTO attendance
                    (session_id, student_id, usn, status, method, marked_by, marked_at, notes)
                VALUES (%s, %s, %s, 'present', 'voice_command', %s, NOW(), %s)
                ON DUPLICATE KEY UPDATE
                    status = 'present', method = 'voice_command',
                    marked_by = VALUES(marked_by), marked_at = NOW(), notes = VALUES(notes)
            """
            rows = [
                (session_id, s["student_id"], s["usn"], current_user.id, note)
                for s in roster
            ]
            cursor.executemany(upsert_sql, rows)

        conn.commit()

        log_audit(
            current_user.id, "voice_bulk_default_attendance",
            "attendance", session_id, None,
            f"{len(roster)} students defaulted to '{default_status}' via voice attendance",
            ip_address=get_client_ip()
        )
    except Exception as e:
        conn.rollback()
        cursor.close()
        logger.error("[WebVoiceBulkDefault] Database error: %s", e)
        return jsonify({"success": False, "message": f"Database error: {e}"}), 500

    cursor.close()

    return jsonify({
        "success": True,
        "default_status": default_status,
        "count": len(roster),
        "students": [
            {"student_id": s["student_id"], "usn": s["usn"], "name": s["name"], "status": default_status}
            for s in roster
        ],
        "marked_at": datetime.now().strftime("%H:%M:%S")
    })


@session_view_bp.route("/<int:session_id>/voice_batch_mark", methods=["POST"])
@admin_or_faculty_required
@profile_completed_required
def web_voice_batch_mark(session_id):
    """
    Parse a continuous multi-student transcript, evaluate all students,
    and mark attendance for all recognized students in a single database transaction.
    """
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

    # 1. Verify session access
    cursor.execute(
        """
        SELECT s.id, s.section_id, s.faculty_id, s.substitute_faculty_id,
               s.delegated_faculty_id, s.is_proxy
        FROM sessions s
        WHERE s.id = %s
        LIMIT 1
        """,
        (session_id,)
    )
    sess = cursor.fetchone()
    if not sess:
        cursor.close()
        return jsonify({"success": False, "message": "Session not found."}), 404

    if current_user.role == "faculty":
        cursor.execute("SELECT id FROM faculty WHERE user_id = %s", (current_user.id,))
        fac = cursor.fetchone()
        current_fac_id = fac["id"] if fac else None
        if not current_fac_id or (
            sess["faculty_id"] != current_fac_id
            and sess.get("substitute_faculty_id") != current_fac_id
            and not (sess.get("is_proxy") == 1 and sess.get("delegated_faculty_id") == current_fac_id)
        ):
            cursor.close()
            return jsonify({"success": False, "message": "Access denied: Not your session."}), 403

    section_id = sess["section_id"]

    # 2. Get full section roster
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

    # 3. Parse continuous multi-student transcript
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

    # If bulk mode, include remaining roster students with baseline default status
    marked_ids = {st["student_id"] for st in marked_list}
    full_batch_list = list(marked_list)
    if voice_mode == "bulk_absent":  # Default Present (read absent ones)
        for st in roster:
            if st["student_id"] not in marked_ids:
                st_copy = dict(st)
                st_copy["target_status"] = "present"
                full_batch_list.append(st_copy)
    elif voice_mode == "bulk_present":  # Default Absent (read present ones)
        for st in roster:
            if st["student_id"] not in marked_ids:
                st_copy = dict(st)
                st_copy["target_status"] = "absent"
                full_batch_list.append(st_copy)

    marked_list = full_batch_list

    # 4. Batch upsert attendance in database
    try:
        upsert_sql = """
            INSERT INTO attendance
                (session_id, student_id, usn, status, method, marked_by, marked_at, notes)
            VALUES (%s, %s, %s, %s, 'voice_command', %s, NOW(), %s)
            ON DUPLICATE KEY UPDATE
                status = VALUES(status),
                method = VALUES(method),
                marked_by = VALUES(marked_by),
                marked_at = NOW(),
                notes = VALUES(notes)
        """
        rows = [
            (
                session_id,
                st["student_id"],
                st["usn"],
                st.get("target_status", default_status),
                current_user.id,
                f"Batch marked {st.get('target_status', default_status)} via continuous voice command by {current_user.full_name}"
            )
            for st in marked_list
        ]
        cursor.executemany(upsert_sql, rows)
        conn.commit()

        log_audit(
            current_user.id, "voice_batch_mark_attendance",
            "attendance", session_id, None,
            f"{len(marked_list)} students batch marked via continuous voice command",
            ip_address=get_client_ip()
        )
    except Exception as e:
        conn.rollback()
        cursor.close()
        logger.error("[WebVoiceBatchMark] Database error: %s", e)
        return jsonify({"success": False, "message": f"Database error: {e}"}), 500
    finally:
        cursor.close()

    now_time = datetime.now().strftime("%H:%M:%S")
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