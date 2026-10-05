"""
attendance_system/api/student/dashboard.py
Student dashboard: subject-wise attendance table, color-coded percentages,
session-by-session history, alerts.
"""

import logging
from datetime import datetime

from flask_login import login_required
from flask import Blueprint, render_template, request, jsonify
from flask_login import current_user

from core.db import get_db, get_cursor
from auth.helpers import student_required
from services.attendance_engine import student_attendance

logger = logging.getLogger(__name__)

student_bp = Blueprint(
    "student", __name__,
    template_folder="../../templates/student"
)


@student_bp.route("/")
@login_required
@student_required
def dashboard():
    """Student dashboard. Every class count comes from services/attendance_engine.py."""
    cursor = get_cursor()

    cursor.execute(
        """
        SELECT s.id AS student_id, s.usn, s.section_id, s.current_sem,
               s.enrollment_status, s.image_path,
               sec.section_label, d.code AS dept_code, d.name AS dept_name,
               ap.id AS period_id, ap.name AS period_name, ap.start_date, ap.end_date
        FROM students s
        LEFT JOIN sections sec ON sec.id = s.section_id
        LEFT JOIN departments d ON d.id = sec.department_id
        LEFT JOIN academic_periods ap ON ap.id = sec.academic_period_id
        WHERE s.user_id = %s
        """,
        (current_user.id,)
    )
    student = cursor.fetchone()

    if not student:
        return render_template(
            "student/dashboard.html",
            error="Student profile not found. Contact administrator.",
            student=None,
            subjects=[],
            alerts=[],
        )

    student_id = student["student_id"]
    section_id = student["section_id"]
    period_id = student["period_id"]

    # ---- ONE source for all class counts ----
    empty = {"subjects": [], "overall": {"conducted": 0, "present": 0, "absent": 0,
                                         "percentage": 0.0, "threshold": 75}}
    stats = (student_attendance(cursor, student_id, period_id)
             if (section_id and period_id) else empty)

    # ---- type, credits and faculty names for the cards ----
    sub_ids = sorted({r["subject_id"] for r in stats["subjects"]})
    info = {}
    if sub_ids:
        marks = ",".join(["%s"] * len(sub_ids))
        cursor.execute(
            f"SELECT id, subject_type, credits FROM subjects WHERE id IN ({marks})", sub_ids)
        info = {r["id"]: {"subject_type": r["subject_type"], "credits": r["credits"],
                          "faculty_name": ""} for r in cursor.fetchall()}
        cursor.execute(
            f"""
            SELECT ps.subject_id,
                   GROUP_CONCAT(DISTINCT u.full_name ORDER BY u.full_name SEPARATOR ', ') AS faculty_name
            FROM planned_sessions ps
            JOIN faculty f ON f.id = ps.faculty_id
            JOIN users u ON u.id = f.user_id
            WHERE ps.academic_period_id = %s AND ps.subject_id IN ({marks})
              AND ((ps.elective_group_id IS NULL AND ps.section_id = %s)
                   OR ps.elective_group_id IN (
                        SELECT m.elective_group_id FROM elective_group_members m
                        WHERE m.student_id = %s AND m.is_active = 1))
            GROUP BY ps.subject_id
            """,
            [period_id] + sub_ids + [section_id, student_id])
        for r in cursor.fetchall():
            if r["subject_id"] in info:
                info[r["subject_id"]]["faculty_name"] = r["faculty_name"]

    # ---- subject cards ----
    subjects = []
    for r in stats["subjects"]:
        pct = r["percentage"]
        if r["status"] == "no_classes":
            color = "secondary"
        elif pct < 75:
            color = "danger"
        elif pct < 85:
            color = "warning"
        else:
            color = "success"

        extra = info.get(r["subject_id"], {})
        name = r["name"]
        if r["component"]:                       # theory and lab counted separately
            name = f"{name} ({r['component'].title()})"

        subjects.append({
            "subject_id": r["subject_id"],
            "subject_code": r["code"],
            "subject_name": name,
            "subject_type": extra.get("subject_type", ""),
            "credits": extra.get("credits", 0),
            "faculty_name": extra.get("faculty_name", ""),
            "total": r["conducted"],             # classes held so far
            "present": r["present"],
            "absent": r["absent"],
            "percentage": pct,
            "color": color,
            "status": r["status"],
            "planned_total": r["expected_total"],  # held + still to come
            "remaining": r["remaining"],
            "must_attend": r["must_attend"],
            "can_miss": r["can_miss"],
            "can_reach": r["can_reach"],
        })

    # ---- Exam results for this student ----
    exam_results = []
    cursor.execute(
        """
        SELECT TABLE_NAME
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'exam_results'
        """
    )
    exam_table_exists = cursor.fetchone() is not None

    if exam_table_exists:
        cursor.execute(
            """
            SELECT er.subject_id, er.exam_name, er.total_marks, er.obtained_marks,
                   er.percentage, er.grade, er.remarks, er.ia1, er.ia2, er.ia3, er.cca,
                   er.record, er.lab_test, er.lab_marks, er.cie_marks, sub.code AS subject_code,
                   sub.name AS subject_name, sub.subject_type
            FROM exam_results er
            JOIN subjects sub ON sub.id = er.subject_id
            WHERE er.student_id = %s
            ORDER BY er.created_at DESC, er.exam_name, sub.code
            """,
            (student_id,),
        )
        exam_results = cursor.fetchall()

    # ---- Overall attendance ----
    overall = stats["overall"]
    overall_total = overall["conducted"]
    overall_present = overall["present"]
    overall_pct = overall["percentage"]

    # ---- Alerts ----
    alerts = []
    for s in subjects:
        if s["status"] == "no_classes":
            continue
        if s["percentage"] < 75:
            if s["can_reach"]:
                msg = (f"⚠ {s['subject_code']}: Your attendance is {s['percentage']}% "
                       f"(below 75%). Attend the next {s['must_attend']} of the "
                       f"{s['remaining']} remaining classes to reach 75%.")
            else:
                msg = (f"⚠ {s['subject_code']}: Your attendance is {s['percentage']}% "
                       f"(below 75%). Even if you attend every remaining class you cannot "
                       f"reach 75%. Please meet your faculty.")
            alerts.append({"type": "danger", "message": msg})
        elif s["percentage"] < 85:
            alerts.append({
                "type": "warning",
                "message": (f"⚡ {s['subject_code']}: Your attendance is {s['percentage']}%. "
                            f"You can miss only {s['can_miss']} more class(es) and stay at 75%."),
            })

    if overall_total and overall_pct < 75:
        alerts.insert(0, {
            "type": "danger",
            "message": f"🚨 OVERALL attendance is {overall_pct}%. You are a defaulter!",
        })

    return render_template(
        "student/dashboard.html",
        student=student,
        subjects=subjects,
        overall_total=overall_total,
        overall_present=overall_present,
        overall_pct=overall_pct,
        alerts=alerts,
        exam_results=exam_results,
    )


@student_bp.route("/subject/<int:subject_id>/history")
@login_required
@student_required
def subject_history(subject_id):
    """Class-by-class attendance history for a subject (one row per class)."""
    cursor = get_cursor()

    cursor.execute(
        "SELECT id AS student_id, section_id FROM students WHERE user_id = %s",
        (current_user.id,)
    )
    student = cursor.fetchone()
    if not student:
        return jsonify({"error": "Student not found."})

    cursor.execute("SELECT code, name FROM subjects WHERE id = %s", (subject_id,))
    subject = cursor.fetchone()

    # Driven by the student's own attendance rows: no section filter (electives work),
    # no timetable join (no repeated rows). Only classes that were really held.
    cursor.execute(
        """
        SELECT s.id AS session_id, s.session_date, s.start_time, s.end_time,
               CASE s.component WHEN 'lab' THEN 'Lab' ELSE 'Theory' END AS slot_type,
               a.status, a.method, a.recognition_score,
               a.liveness_score, a.marked_at
        FROM attendance a
        JOIN sessions s ON s.id = a.session_id
        WHERE a.student_id = %s
          AND s.subject_id = %s
          AND s.status IN ('completed', 'active')
        ORDER BY s.session_date DESC, s.start_time DESC
        """,
        (student["student_id"], subject_id)
    )
    history = cursor.fetchall()

    for h in history:
        for k in ("start_time", "end_time"):
            if h.get(k) and hasattr(h[k], "total_seconds"):
                total = int(h[k].total_seconds())
                hours, remainder = divmod(total, 3600)
                minutes, _ = divmod(remainder, 60)
                h[k] = f"{hours:02d}:{minutes:02d}"
        if h.get("marked_at"):
            h["marked_at"] = h["marked_at"].strftime("%H:%M:%S")
        if h.get("session_date"):
            h["session_date"] = h["session_date"].strftime("%Y-%m-%d")

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"subject": subject, "history": history})

    return render_template(
        "student/subject_history.html",
        subject=subject,
        history=history,
    )


@student_bp.route("/api/attendance-summary")
@login_required
@student_required
def attendance_summary_api():
    """AJAX: attendance summary for the logged-in student (same numbers as the dashboard)."""
    cursor = get_cursor()

    cursor.execute(
        "SELECT s.id AS student_id, sec.academic_period_id AS period_id "
        "FROM students s LEFT JOIN sections sec ON sec.id = s.section_id "
        "WHERE s.user_id = %s",
        (current_user.id,)
    )
    student = cursor.fetchone()
    if not student:
        return jsonify({"error": "Student not found."})
    if not student["period_id"]:
        return jsonify({"summary": [], "overall": {}})

    res = student_attendance(cursor, student["student_id"], student["period_id"])
    summary = [{
        "subject_code": r["code"],
        "subject_name": r["name"] + (f" ({r['component'].title()})" if r["component"] else ""),
        "total": r["conducted"],
        "present": r["present"],
        "percentage": r["percentage"],
        "semester_total": r["expected_total"],
        "remaining": r["remaining"],
        "must_attend": r["must_attend"],
        "can_miss": r["can_miss"],
    } for r in res["subjects"]]
    return jsonify({"summary": summary, "overall": res["overall"]})