# api/hod/dashboard.py

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from core.db import get_cursor
from services.attendance_engine import class_counts, overall_defaulters

hod_bp = Blueprint("hod", __name__, url_prefix="/hod")


@hod_bp.route('/dashboard')
@login_required
def dashboard():
    if not getattr(current_user, "is_hod", False):
        flash("HOD privileges required", "danger")
        return redirect(url_for("faculty.dashboard"))

    cursor = get_cursor()
    dept_id = current_user.department_id

    # The faculty id is NOT the user id
    cursor.execute("SELECT id FROM faculty WHERE user_id = %s", (current_user.id,))
    fac = cursor.fetchone()
    faculty_id = fac["id"] if fac else None

    cursor.execute(
        "SELECT COUNT(*) as sections FROM sections WHERE department_id = %s",
        (dept_id,)
    )
    sections = cursor.fetchone()['sections']

    cursor.execute("""
        SELECT COUNT(*) as faculty_count
        FROM faculty f
        JOIN users u ON f.user_id = u.id
        WHERE f.department_id = %s AND u.status = 'active'
    """, (dept_id,))
    faculty = cursor.fetchone()['faculty_count']

    my_subjects = 0
    todays_sessions = 0
    if faculty_id:
        cursor.execute("""
            SELECT COUNT(DISTINCT t.subject_id) as subjects
            FROM timetable t
            WHERE t.faculty_id = %s AND t.is_active = 1
        """, (faculty_id,))
        my_subjects = cursor.fetchone()['subjects']

        cursor.execute("""
            SELECT COUNT(*) as today_sessions
            FROM sessions s
            WHERE (s.faculty_id = %s OR s.substitute_faculty_id = %s)
              AND s.session_date = CURDATE()
        """, (faculty_id, faculty_id))
        todays_sessions = cursor.fetchone()['today_sessions']

    cursor.execute("SELECT name FROM departments WHERE id = %s", (dept_id,))
    dept = cursor.fetchone()

    # ---- Department teaching progress: planned -> done -> left -> missed ----
    cursor.execute("""
        SELECT sec.id, sec.section_label, sec.sem_number, sec.academic_period_id
        FROM sections sec
        JOIN academic_periods ap ON ap.id = sec.academic_period_id
        WHERE sec.department_id = %s AND ap.is_archived = 0
          AND CURDATE() BETWEEN ap.start_date AND ap.end_date
        ORDER BY sec.sem_number, sec.section_label
    """, (dept_id,))
    dept_progress = []
    for sec in cursor.fetchall():
        c = class_counts(cursor, period_id=sec["academic_period_id"], section_id=sec["id"])
        dept_progress.append({
            "label": f"Sem {sec['sem_number']} - {sec['section_label']}",
            "planned": c["planned"], "done": c["conducted_planned"],
            "remaining": c["remaining"], "missed": c["missed"],
            "completion_pct": c["completion_pct"],
        })
    dept_defaulters = len(overall_defaulters(cursor, 75, department_id=dept_id))

    return render_template(
        'hod/dashboard.html',
        sections=sections,
        faculty=faculty,
        my_subjects=my_subjects,
        todays_sessions=todays_sessions,
        department_name=dept["name"] if dept else f"Department {dept_id}",
        dept_progress=dept_progress,
        dept_defaulters=dept_defaulters,
    )