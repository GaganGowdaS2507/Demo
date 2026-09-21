"""
attendance_system/api/faculty/dashboard.py
Faculty dashboard: today's sessions, quick attendance counts.
"""

import logging
from datetime import datetime

from flask_login import login_required
from flask import Blueprint, redirect, render_template, jsonify, session, url_for,request,flash
from flask_login import current_user, login_required, logout_user

from core.db import get_db, get_cursor
from auth.helpers import faculty_required, admin_or_faculty_required, hash_password, logout_user,log_audit, get_client_ip,profile_completed_required, verify_password

from utils.exam_results import (
    calculate_percentage,
    get_grade_label,
    calculate_internal_marks,
    get_result_entry_config,
    get_result_field_names,
    normalize_result_value,
    detect_changed_result_fields,
)
logger = logging.getLogger(__name__)

faculty_bp = Blueprint(
    "faculty", __name__,
    template_folder="../../templates/faculty"
)


def _td_to_str(value) -> str:
    """Convert timedelta to HH:MM string."""
    if value is None:
        return ""
    if hasattr(value, "total_seconds"):
        total = int(value.total_seconds())
        h, rem = divmod(total, 3600)
        m, _ = divmod(rem, 60)
        return f"{h:02d}:{m:02d}"
    return str(value)[:5]


@faculty_bp.route("/cameras")
@login_required
@admin_or_faculty_required
@profile_completed_required
def cameras_page():
    """Faculty cameras list and status view."""
    cursor = get_cursor()
    cursor.execute("""
        SELECT c.id, c.name, c.rtsp_url, c.location, c.status, c.assigned_section_id,
               sec.section_label, d.code AS dept_code
        FROM cameras c
        LEFT JOIN sections sec ON sec.id = c.assigned_section_id
        LEFT JOIN departments d ON d.id = sec.department_id
        WHERE c.status = 'active'
        ORDER BY c.name
    """)
    cameras = cursor.fetchall()

    return render_template(
        "faculty/cameras.html",
        cameras=cameras
    )


@faculty_bp.route("/")
@login_required
@admin_or_faculty_required
@profile_completed_required
def dashboard():
    # if (
    #     current_user.role == "faculty"
    #     and current_user.must_change_password
    # ):
    #     return redirect(
    #         url_for("faculty.complete_profile")
    #     )
    """Faculty dashboard — shows today's sessions for this faculty."""
    cursor = get_cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    day_name = datetime.now().strftime("%A")

    # Get faculty record for current user
    cursor.execute(
        "SELECT id FROM faculty WHERE user_id = %s",
        (current_user.id,)
    )
    fac = cursor.fetchone()

    if not fac:
        if current_user.role == "admin":
            faculty_id = None
        else:
            return render_template(
                "faculty/dashboard.html",
                error="Faculty profile not found.",
                todays_sessions=[],
                faculty_name=current_user.full_name,
                today=today,
                day_name=day_name,
            )
    else:
        faculty_id = fac["id"]
    # in dashboard(): join elective_groups to pick up group_type for the badge
    # stats: union section_subjects with elective_groups the faculty owns
    cursor.execute("""
        SELECT
        (SELECT COUNT(DISTINCT subject_id) FROM (
            SELECT ss.subject_id FROM section_subjects ss
            JOIN academic_periods ap ON ap.id = ss.academic_period_id
            WHERE ss.faculty_id = %s AND ap.is_active = 1
            UNION
            SELECT eg.subject_id FROM elective_groups eg
            JOIN academic_periods ap ON ap.id = eg.academic_period_id
            WHERE eg.faculty_id = %s AND ap.is_active = 1 AND eg.is_active = 1
        ) t) AS subject_count,
        (SELECT COUNT(DISTINCT section_id) FROM section_subjects ss
            JOIN academic_periods ap ON ap.id = ss.academic_period_id
            WHERE ss.faculty_id = %s AND ap.is_active = 1) AS section_count
    """, (faculty_id, faculty_id, faculty_id) if faculty_id else (0, 0, 0))
    stats = cursor.fetchone()
    # Lazy cleanup of expired/stale proxy sessions past 4:30 PM or past dates
    try:
        from api.faculty.session_view import _cleanup_expired_proxies
        conn = get_db()
        _cleanup_expired_proxies(cursor, conn)
    except Exception as e:
        logger.warning(f"Dashboard proxy cleanup warning: {e}")

    # Get today's sessions — EXCLUDE breaks (no subject_id)
    query = """
        SELECT s.id, s.session_date, s.status,
               s.start_time, s.end_time,
               s.rtsp_url, s.opened_at, s.closed_at,
               s.camera_id, s.is_proxy, s.delegation_code, s.primary_faculty_id, s.delegated_faculty_id,
               sub.code AS subject_code, sub.name AS subject_name,
               sec.section_label, d.code AS dept_code,
               cam.name AS camera_name,
               (SELECT COUNT(*) FROM attendance a
                WHERE a.session_id = s.id AND a.status = 'present') AS present_count,
               (SELECT COUNT(*) FROM students st WHERE st.section_id = s.section_id) AS total_count,
                (CASE WHEN s.elective_group_id IS NOT NULL THEN 1 ELSE 0 END) AS is_elective,
                eg.group_type
        FROM sessions s
        JOIN sections sec ON sec.id = s.section_id
        JOIN departments d ON d.id = sec.department_id
        LEFT JOIN subjects sub ON sub.id = s.subject_id
        LEFT JOIN cameras cam ON cam.id = s.camera_id
        LEFT JOIN elective_groups eg ON eg.id = s.elective_group_id
        WHERE s.session_date = %s
          AND s.subject_id IS NOT NULL
    """
    params = [today]

    if faculty_id:
        query += " AND (s.faculty_id = %s OR s.substitute_faculty_id = %s OR s.delegated_faculty_id = %s)"
        params.extend([faculty_id, faculty_id, faculty_id])

    query += " ORDER BY s.start_time"

    cursor.execute(query, tuple(params))
    todays_sessions = cursor.fetchall()

    # Convert timedelta fields
    for s in todays_sessions:
        s["start_time"] = _td_to_str(s.get("start_time"))
        s["end_time"] = _td_to_str(s.get("end_time"))

    # Get active streams
    active_streams = {}
    try:
        from app import stream_manager
        if stream_manager:
            all_streams = stream_manager.list_active_streams()
            for sid, info in all_streams.items():
                if sid in [s["id"] for s in todays_sessions]:
                    active_streams[sid] = info
    except Exception:
        pass

    # Quick stats
    cursor.execute("""
        SELECT COUNT(DISTINCT ss.subject_id) AS subject_count,
               COUNT(DISTINCT ss.section_id) AS section_count
        FROM section_subjects ss
        JOIN academic_periods ap ON ap.id = ss.academic_period_id
        WHERE ss.faculty_id = %s AND ap.is_active = 1
    """, (faculty_id,) if faculty_id else (0,))
    stats = cursor.fetchone()

    # Available cameras (for faculty to select when running session)
    cursor.execute("""
        SELECT id, name, rtsp_url, location
        FROM cameras WHERE status = 'active'
        ORDER BY name
    """)
    cameras = cursor.fetchall()

    recent_results = []
    cursor.execute("""
        SELECT TABLE_NAME
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'exam_results'
    """)
    if cursor.fetchone() is not None:
        cursor.execute("""
            SELECT er.exam_name, er.created_at, er.obtained_marks, er.total_marks,
                   er.percentage, er.grade, sub.code AS subject_code, sub.name AS subject_name,
                   st.usn, u.full_name AS student_name
            FROM exam_results er
            JOIN subjects sub ON sub.id = er.subject_id
            JOIN students st ON st.id = er.student_id
            LEFT JOIN users u ON u.id = st.user_id
            WHERE er.faculty_id = %s
            ORDER BY er.created_at DESC, er.exam_name
            LIMIT 8
        """, (faculty_id,))
        recent_results = cursor.fetchall()

    # Weekly Timetable Query for Logged-in Faculty
    weekly_timetable = {day: [] for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]}
    timetable_stats = {"total_slots": 0, "unique_subjects": 0, "unique_sections": 0}

    if faculty_id:
        cursor.execute("""
            SELECT t.id, t.day_of_week, t.start_time, t.end_time, t.slot_type, t.room,
                   sub.code AS subject_code, sub.name AS subject_name, sub.subject_type,
                   sec.section_label, d.code AS dept_code,
                   eg.group_type
            FROM timetable t
            JOIN sections sec ON sec.id = t.section_id
            JOIN departments d ON d.id = sec.department_id
            LEFT JOIN subjects sub ON sub.id = t.subject_id
            LEFT JOIN elective_groups eg ON eg.id = t.elective_group_id
            JOIN academic_periods ap ON ap.id = t.academic_period_id
            WHERE (t.faculty_id = %s OR EXISTS (
                SELECT 1 FROM section_subjects ss 
                WHERE ss.section_id = t.section_id AND ss.subject_id = t.subject_id AND ss.faculty_id = %s
            ))
              AND ap.is_active = 1
              AND t.slot_type NOT IN ('Interval', 'Lunch')
            ORDER BY FIELD(t.day_of_week, 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'), t.start_time
        """, (faculty_id, faculty_id))
        tt_rows = cursor.fetchall()

        subjects_set = set()
        sections_set = set()
        for row in tt_rows:
            day = row["day_of_week"]
            row["start_time_str"] = _td_to_str(row.get("start_time"))
            row["end_time_str"] = _td_to_str(row.get("end_time"))
            if row.get("subject_code"):
                subjects_set.add(row["subject_code"])
            sections_set.add(f"{row['dept_code']}-{row['section_label']}")
            if day in weekly_timetable:
                weekly_timetable[day].append(row)

        timetable_stats["total_slots"] = len(tt_rows)
        timetable_stats["unique_subjects"] = len(subjects_set)
        timetable_stats["unique_sections"] = len(sections_set)

    return render_template(
        "faculty/dashboard.html",
        todays_sessions=todays_sessions,
        active_streams=active_streams,
        faculty_name=current_user.full_name,
        today=today,
        day_name=day_name,
        stats=stats,
        faculty_id=faculty_id,
        cameras=cameras,
        recent_results=recent_results,
        weekly_timetable=weekly_timetable,
        timetable_stats=timetable_stats,
    )

@faculty_bp.route("/subjects")
@login_required
@admin_or_faculty_required
@profile_completed_required
def my_subjects():
    cursor = get_cursor()
    cursor.execute("SELECT id FROM faculty WHERE user_id = %s", (current_user.id,))
    fac = cursor.fetchone()
    if not fac:
        flash("Faculty profile not found.", "danger")
        return redirect(url_for("faculty.dashboard"))
    faculty_id = fac["id"]

    cursor.execute("""
        SELECT sub.id AS subject_id, sub.code, sub.name,
               sec.section_label, sec.sem_number, d.code AS dept_code
        FROM section_subjects ss
        JOIN subjects sub ON sub.id = ss.subject_id
        JOIN sections sec ON sec.id = ss.section_id
        JOIN departments d ON d.id = sec.department_id
        JOIN academic_periods ap ON ap.id = ss.academic_period_id
        WHERE ss.faculty_id = %s AND ap.is_active = 1
        ORDER BY sec.sem_number, sub.name, sec.section_label
    """, (faculty_id,))
    rows = cursor.fetchall()

    subjects = {}
    for r in rows:
        key = r["subject_id"]
        if key not in subjects:
            subjects[key] = {"code": r["code"], "name": r["name"], "sections": []}
        subjects[key]["sections"].append({
            "section_label": r["section_label"], "sem_number": r["sem_number"], "dept_code": r["dept_code"],
        })

    return render_template("faculty/my_subjects.html", subjects=list(subjects.values()))


@faculty_bp.route("/sections")
@login_required
@admin_or_faculty_required
@profile_completed_required
def my_sections():
    cursor = get_cursor()
    cursor.execute("SELECT id FROM faculty WHERE user_id = %s", (current_user.id,))
    fac = cursor.fetchone()
    if not fac:
        flash("Faculty profile not found.", "danger")
        return redirect(url_for("faculty.dashboard"))
    faculty_id = fac["id"]

    cursor.execute("""
        SELECT sec.id AS section_id, sec.section_label, sec.sem_number, d.code AS dept_code,
               sub.code AS subject_code, sub.name AS subject_name,
               (SELECT COUNT(*) FROM students st WHERE st.section_id = sec.id) AS student_count
        FROM section_subjects ss
        JOIN sections sec ON sec.id = ss.section_id
        JOIN departments d ON d.id = sec.department_id
        JOIN subjects sub ON sub.id = ss.subject_id
        JOIN academic_periods ap ON ap.id = ss.academic_period_id
        WHERE ss.faculty_id = %s AND ap.is_active = 1
        ORDER BY sec.sem_number, sec.section_label, sub.name
    """, (faculty_id,))
    rows = cursor.fetchall()

    sections = {}
    for r in rows:
        key = r["section_id"]
        if key not in sections:
            sections[key] = {
                "section_label": r["section_label"], "sem_number": r["sem_number"],
                "dept_code": r["dept_code"], "student_count": r["student_count"], "subjects": [],
            }
        sections[key]["subjects"].append({"code": r["subject_code"], "name": r["subject_name"]})

    return render_template("faculty/my_sections.html", sections=list(sections.values()))


@faculty_bp.route("/sessions/history")
@login_required
@admin_or_faculty_required
@profile_completed_required
def session_history():
    """Past sessions this faculty taught — click into any of them to view
    or edit that day's attendance, e.g. giving a student attendance for a
    missed class with permission."""
    cursor = get_cursor()
    cursor.execute("SELECT id FROM faculty WHERE user_id = %s", (current_user.id,))
    fac = cursor.fetchone()
    if not fac:
        flash("Faculty profile not found.", "danger")
        return redirect(url_for("faculty.dashboard"))
    faculty_id = fac["id"]

    date_filter = request.args.get("date", "").strip()
    section_filter = request.args.get("section_id", type=int)

    query = """
        SELECT s.id, s.session_date, s.status, s.start_time, s.end_time,
               sub.code AS subject_code, sub.name AS subject_name,
               sec.id AS section_id, sec.section_label, d.code AS dept_code,
               (SELECT COUNT(*) FROM attendance a
                WHERE a.session_id = s.id AND a.status = 'present') AS present_count,
               (SELECT COUNT(*) FROM students st WHERE st.section_id = s.section_id) AS total_count
        FROM sessions s
        JOIN sections sec ON sec.id = s.section_id
        JOIN departments d ON d.id = sec.department_id
        LEFT JOIN subjects sub ON sub.id = s.subject_id
        WHERE s.subject_id IS NOT NULL
          AND s.session_date < CURDATE()
          AND (s.faculty_id = %s OR s.substitute_faculty_id = %s)
    """
    params = [faculty_id, faculty_id]
    if date_filter:
        query += " AND s.session_date = %s"
        params.append(date_filter)
    if section_filter:
        query += " AND s.section_id = %s"
        params.append(section_filter)
    query += " ORDER BY s.session_date DESC, s.start_time DESC LIMIT 200"

    cursor.execute(query, tuple(params))
    sessions = cursor.fetchall()
    for s in sessions:
        s["start_time"] = _td_to_str(s.get("start_time"))
        s["end_time"] = _td_to_str(s.get("end_time"))

    cursor.execute("""
        SELECT DISTINCT sec.id, sec.section_label, d.code AS dept_code
        FROM section_subjects ss
        JOIN sections sec ON sec.id = ss.section_id
        JOIN departments d ON d.id = sec.department_id
        JOIN academic_periods ap ON ap.id = ss.academic_period_id
        WHERE ss.faculty_id = %s AND ap.is_active = 1
        ORDER BY sec.section_label
    """, (faculty_id,))
    filter_sections = cursor.fetchall()

    return render_template(
        "faculty/session_history.html",
        sessions=sessions, filter_sections=filter_sections,
        date_filter=date_filter, section_filter=section_filter,
    )

@faculty_bp.route("/complete-profile", methods=["GET", "POST"])
@login_required
@faculty_required
def complete_profile():
    """
    First login profile completion.
    """

    cursor = get_cursor()

    # Get current user
    cursor.execute("""
        SELECT
            id,
            full_name,
            email,
            phone,
            must_change_password,
            profile_completed
        FROM users
        WHERE id=%s
    """, (current_user.id,))

    user = cursor.fetchone()

    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("auth.logout"))

    # Already completed
    if (
        not user["must_change_password"]
        and user["profile_completed"]
    ):
        return redirect(url_for("faculty.dashboard"))

    # ===========================
    # POST
    # ===========================

    if request.method == "POST":

        new_email = request.form.get(
            "email",
            ""
        ).strip().lower()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        confirm = request.form.get(
            "confirm_password",
            ""
        )

        # -------------------------
        # Validation
        # -------------------------

        if not new_email:
            flash("Email is required.", "danger")
            return render_template(
                "faculty/complete_profile.html",
                user=user
            )

        if password != confirm:
            flash(
                "Passwords do not match.",
                "danger"
            )
            return render_template(
                "faculty/complete_profile.html",
                user=user
            )

        if len(password) < 6:
            flash(
                "Password must contain at least 6 characters.",
                "danger"
            )
            return render_template(
                "faculty/complete_profile.html",
                user=user
            )

        # -------------------------
        # Duplicate Email Check
        # -------------------------

        cursor.execute("""
            SELECT id
            FROM users
            WHERE email=%s
            AND id<>%s
        """, (
            new_email,
            current_user.id
        ))

        if cursor.fetchone():

            flash(
                "Email already exists.",
                "danger"
            )

            return render_template(
                "faculty/complete_profile.html",
                user=user
            )

        conn = get_db()

        try:

            cur = conn.cursor()

            cur.execute("""
                UPDATE users
                SET
                    email=%s,
                    phone=%s,
                    password_hash=%s,
                    must_change_password=0,
                    profile_completed=1,
                    email_verified=0,
                    password_changed_at=NOW(),
                    profile_completed_at=NOW()
                WHERE id=%s
            """, (

                new_email,

                phone if phone else None,

                hash_password(password),

                current_user.id

            ))

            conn.commit()

            log_audit(

                current_user.id,

                "complete_profile",

                target_table="users",

                target_id=current_user.id,

                ip_address=get_client_ip()

            )

            flash(
                "Profile updated successfully. Please login using your new email and password.",
                "success"
            )

            logout_user()
            session.clear()

            return redirect(url_for("auth.login"))

        except Exception as e:

            conn.rollback()

            flash(str(e), "danger")

    return render_template(

        "faculty/complete_profile.html",

        user=user

    )

@faculty_bp.route("/profile")
@login_required
@faculty_required
@profile_completed_required
def profile():

    cursor = get_cursor()

    cursor.execute("""
        SELECT
            u.id,
            u.full_name,
            u.email,
            u.phone,
            u.status,
            u.last_login,
            u.password_changed_at,
            u.profile_completed_at,

            f.faculty_code,
            f.designation,
            f.profile_photo,

            d.name AS department_name,
            d.code AS department_code

        FROM users u

        JOIN faculty f
        ON f.user_id=u.id

        LEFT JOIN departments d
        ON d.id=f.department_id

        WHERE u.id=%s
    """,(current_user.id,))

    profile=cursor.fetchone()

    return render_template(
        "faculty/profile.html",
        profile=profile
    )

@faculty_bp.route("/profile",methods=["POST"])
@login_required
@faculty_required
@profile_completed_required
def update_profile():

    email=request.form.get("email","").strip().lower()

    phone=request.form.get("phone","").strip()

    cursor=get_cursor()

    cursor.execute("""
        SELECT id
        FROM users
        WHERE email=%s
        AND id<>%s
    """,(email,current_user.id))

    if cursor.fetchone():

        flash(
            "Email already exists.",
            "danger"
        )

        return redirect(
            url_for("faculty.profile")
        )

    conn=get_db()

    try:

        cur=conn.cursor()

        cur.execute("""

            UPDATE users

            SET

                email=%s,

                phone=%s

            WHERE id=%s

        """,(

            email,

            phone if phone else None,

            current_user.id

        ))

        conn.commit()

        log_audit(

            current_user.id,

            "update_profile",

            "users",

            current_user.id,

            ip_address=get_client_ip()

        )

        flash(

            "Profile updated successfully.",

            "success"

        )

    except Exception as e:

        conn.rollback()

        flash(str(e),"danger")

    return redirect(
        url_for("faculty.profile")
    )

@faculty_bp.route("/change-password",methods=["POST"])
@login_required
@faculty_required
@profile_completed_required
def change_password():

    current=request.form.get("current_password","")

    new=request.form.get("new_password","")

    confirm=request.form.get("confirm_password","")

    if new!=confirm:

        flash(
            "Passwords do not match.",
            "danger"
        )

        return redirect(
            url_for("faculty.profile")
        )

    if len(new)<8:

        flash(
            "Password must be at least 8 characters.",
            "danger"
        )

        return redirect(
            url_for("faculty.profile")
        )

    cursor=get_cursor()

    cursor.execute("""

        SELECT password_hash

        FROM users

        WHERE id=%s

    """,(current_user.id,))

    row=cursor.fetchone()

    if not verify_password(

        current,

        row["password_hash"]

    ):

        flash(

            "Current password is incorrect.",

            "danger"

        )

        return redirect(
            url_for("faculty.profile")
        )

    conn=get_db()

    try:

        cur=conn.cursor()

        cur.execute("""

            UPDATE users

            SET

                password_hash=%s,

                password_changed_at=NOW()

            WHERE id=%s

        """,(

            hash_password(new),

            current_user.id

        ))

        conn.commit()

        log_audit(

            current_user.id,

            "change_password",

            "users",

            current_user.id,

            ip_address=get_client_ip()

        )

        flash(

            "Password changed successfully.",

            "success"

        )

    except Exception as e:

        conn.rollback()

        flash(str(e),"danger")

    return redirect(
        url_for("faculty.profile")
    )


@faculty_bp.route("/api/my-sessions")
@login_required
@admin_or_faculty_required
@profile_completed_required
def my_sessions_api():
    """AJAX: Get today's sessions for the logged-in faculty."""
    cursor = get_cursor()
    today = datetime.now().strftime("%Y-%m-%d")

    cursor.execute(
        "SELECT id FROM faculty WHERE user_id = %s",
        (current_user.id,)
    )
    fac = cursor.fetchone()
    if not fac:
        return jsonify({"sessions": []})

    cursor.execute("""
        SELECT s.id, s.status,
               sub.code AS subject_code,
               sec.section_label, d.code AS dept_code,
               s.start_time, s.end_time,
               (SELECT COUNT(*) FROM attendance a
                WHERE a.session_id = s.id AND a.status = 'present') AS present_count,
               (SELECT COUNT(*) FROM students st WHERE st.section_id = s.section_id) AS total_count,
                (CASE WHEN s.elective_group_id IS NOT NULL THEN 1 ELSE 0 END) AS is_elective,
                eg.group_type
        FROM sessions s
        JOIN sections sec ON sec.id = s.section_id
        JOIN departments d ON d.id = sec.department_id
        LEFT JOIN subjects sub ON sub.id = s.subject_id
        LEFT JOIN elective_groups eg ON eg.id = s.elective_group_id
        WHERE s.session_date = %s
          AND s.subject_id IS NOT NULL
          AND (s.faculty_id = %s OR s.substitute_faculty_id = %s)
        ORDER BY s.start_time
    """, (today, fac["id"], fac["id"]))
    sessions = cursor.fetchall()

    for s in sessions:
        s["start_time"] = _td_to_str(s.get("start_time"))
        s["end_time"] = _td_to_str(s.get("end_time"))

    return jsonify({"sessions": sessions})


@faculty_bp.route("/exam-results", methods=["GET", "POST"])
@login_required
@faculty_required
def exam_results():
    """Faculty page to enter exam results for 100-mark exams."""
    cursor = get_cursor()
    conn = get_db()

    cursor.execute(
        "SELECT id FROM faculty WHERE user_id = %s",
        (current_user.id,),
    )
    fac = cursor.fetchone()
    if not fac:
        flash("Faculty profile not found.", "danger")
        return redirect(url_for("faculty.dashboard"))

    faculty_id = fac["id"]

    cursor.execute(
        """
        SELECT DISTINCT ss.section_id, sec.section_label, sub.id AS subject_id, sub.code AS subject_code,
                        sub.name AS subject_name, sub.subject_type, sub.credits
        FROM section_subjects ss
        JOIN sections sec ON sec.id = ss.section_id
        JOIN subjects sub ON sub.id = ss.subject_id
        JOIN academic_periods ap ON ap.id = ss.academic_period_id
        WHERE ss.faculty_id = %s AND ap.is_active = 1
        ORDER BY sec.section_label, sub.code
        """,
        (faculty_id,),
    )
    assigned_subjects = cursor.fetchall()

    exam_name = (request.form.get("exam_name") or request.args.get("exam_name") or "Internal Exam").strip()

    if request.method == "POST":
        subject_id = request.form.get("subject_id")
        section_id = request.form.get("section_id")
        if not exam_name or not subject_id or not section_id:
            flash("Please choose a subject and section before saving results.", "danger")
        else:
            cursor.execute(
                "SELECT subject_type, credits FROM subjects WHERE id = %s",
                (subject_id,),
            )
            subject_meta = cursor.fetchone() or {}
            subject_type = (subject_meta.get("subject_type") or "Theory").strip()
            credits = int(subject_meta.get("credits") or 0)

            student_ids = request.form.getlist("student_id")
            for student_id in student_ids:
                if not student_id:
                    continue
                field_names = get_result_field_names(subject_type)
                submitted_values = {
                    field_name: request.form.get(f"{field_name}_{student_id}", "")
                    for field_name in field_names
                }
                remarks = (request.form.get(f"remarks_{student_id}", "") or "").strip()
                cursor.execute(
                    """
                    SELECT id, remarks, ia1, ia2, ia3, cca, record, lab_test, lab_marks, cie_marks
                    FROM exam_results
                    WHERE faculty_id = %s AND subject_id = %s AND section_id = %s
                      AND student_id = %s AND exam_name = %s
                    LIMIT 1
                    """,
                    (faculty_id, subject_id, section_id, student_id, exam_name),
                )
                existing_row = cursor.fetchone()
                effective_values = {}
                for field_name in field_names:
                    existing_value = existing_row.get(field_name) if existing_row else None
                    submitted_value = normalize_result_value(submitted_values.get(field_name))
                    if existing_row is None:
                        effective_values[field_name] = submitted_value
                    else:
                        effective_values[field_name] = submitted_value if submitted_value != existing_value else existing_value
                result_summary = calculate_internal_marks(subject_type, credits, effective_values)
                obtained_marks = result_summary["obtained_marks"]
                percentage = result_summary["percentage"]
                grade = result_summary["grade"]
                total_marks = result_summary["total_marks"]
                changed_fields = detect_changed_result_fields(existing_row, submitted_values, subject_type, remarks)
                if existing_row is None:
                    cursor.execute(
                        """
                        INSERT INTO exam_results (
                            faculty_id, subject_id, section_id, student_id, exam_name,
                            total_marks, obtained_marks, percentage, grade, remarks,
                            ia1, ia2, ia3, cca, record, lab_test, lab_marks, cie_marks
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            faculty_id, subject_id, section_id, student_id, exam_name,
                            total_marks, obtained_marks, percentage, grade, remarks or None,
                            effective_values.get("ia1"), effective_values.get("ia2"), effective_values.get("ia3"),
                            effective_values.get("cca"), effective_values.get("record"), effective_values.get("lab_test"),
                            effective_values.get("lab_marks"), effective_values.get("cie_marks"),
                        ),
                    )
                elif changed_fields:
                    update_fields = []
                    params = []
                    for field_name, value in changed_fields.items():
                        if field_name == "remarks":
                            update_fields.append("remarks = %s")
                            params.append(value)
                        else:
                            update_fields.append(f"{field_name} = %s")
                            params.append(value)
                    update_fields.extend([
                        "total_marks = %s",
                        "obtained_marks = %s",
                        "percentage = %s",
                        "grade = %s",
                    ])
                    params.extend([total_marks, obtained_marks, percentage, grade])
                    params.append(existing_row["id"])
                    cursor.execute(
                        f"UPDATE exam_results SET {', '.join(update_fields)} WHERE id = %s",
                        tuple(params),
                    )
            conn.commit()
            flash("Exam results saved successfully.", "success")
            return redirect(url_for("faculty.exam_results"))

    selected_subject_id = request.args.get("subject_id") or (assigned_subjects[0]["subject_id"] if assigned_subjects else None)
    selected_section_id = request.args.get("section_id") or (assigned_subjects[0]["section_id"] if assigned_subjects else None)
    current_subject = None
    students = []
    saved_results = {}

    if selected_subject_id and selected_section_id:
        cursor.execute(
            """
            SELECT ss.subject_id, ss.section_id, st.id AS student_id, st.usn, u.full_name
            FROM section_subjects ss
            JOIN students st ON st.section_id = ss.section_id
            LEFT JOIN users u ON u.id = st.user_id
            WHERE ss.faculty_id = %s AND ss.subject_id = %s AND ss.section_id = %s
            ORDER BY st.usn
            """,
            (faculty_id, selected_subject_id, selected_section_id),
        )
        students = cursor.fetchall()

        cursor.execute(
            "SELECT id, code, name, subject_type, credits FROM subjects WHERE id = %s",
            (selected_subject_id,),
        )
        current_subject = cursor.fetchone()

        cursor.execute(
            """
            SELECT student_id, ia1, ia2, ia3, cca, record, lab_test, lab_marks, cie_marks, remarks
            FROM exam_results
            WHERE faculty_id = %s AND subject_id = %s AND section_id = %s AND exam_name = %s
            """,
            (faculty_id, selected_subject_id, selected_section_id, exam_name),
        )
        for row in cursor.fetchall():
            saved_results[row["student_id"]] = row

    return render_template(
        "faculty/exam_results.html",
        assigned_subjects=assigned_subjects,
        selected_subject_id=selected_subject_id,
        selected_section_id=selected_section_id,
        students=students,
        current_subject=current_subject,
        exam_name=exam_name,
        saved_results=saved_results,
    )