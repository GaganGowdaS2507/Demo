"""
attendance_system/api/mobile/profile.py
Faculty profile + assigned sections + assigned subjects, for initial mobile setup.
"""
import logging
from flask import jsonify, request

from . import mobile_bp
from .sync import mobile_token_required
from core.db import get_db

logger = logging.getLogger(__name__)


@mobile_bp.route("/profile", methods=["GET"])
@mobile_token_required
def get_faculty_profile():
    if request.mobile_user.get("role") not in ("faculty", "admin", "hod"):
        return jsonify({"success": False, "message": "Faculty access required"}), 403

    user_id = request.mobile_user["user_id"]
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute(
        """
        SELECT u.full_name AS name, u.email, f.id AS faculty_id,
               f.designation, d.name AS department_name
        FROM faculty f
        JOIN users u ON u.id = f.user_id
        LEFT JOIN departments d ON d.id = f.department_id
        WHERE f.user_id = %s
        LIMIT 1
        """,
        (user_id,),
    )
    fac = cursor.fetchone()
    if not fac:
        cursor.close()
        return jsonify({"success": False, "message": "Faculty record not found"}), 404

    faculty_id = fac["faculty_id"]

    cursor.execute(
        """
        SELECT DISTINCT sec.id AS section_id, sec.section_label, sec.sem_number
        FROM sections sec
        WHERE sec.id IN (
            SELECT section_id FROM section_subjects WHERE faculty_id = %s
            UNION
            SELECT section_id FROM timetable WHERE faculty_id = %s AND is_active = 1
            UNION
            SELECT section_id FROM sessions WHERE faculty_id = %s OR substitute_faculty_id = %s OR delegated_faculty_id = %s
        )
        ORDER BY sec.sem_number, sec.section_label
        """,
        (faculty_id, faculty_id, faculty_id, faculty_id, faculty_id),
    )
    sections = cursor.fetchall()

    cursor.execute(
        """
        SELECT DISTINCT sub.id AS subject_id, sub.name, sub.code
        FROM subjects sub
        WHERE sub.id IN (
            SELECT subject_id FROM section_subjects WHERE faculty_id = %s
            UNION
            SELECT subject_id FROM faculty_subjects WHERE faculty_id = %s OR faculty_id = %s
            UNION
            SELECT subject_id FROM elective_groups WHERE faculty_id = %s
            UNION
            SELECT subject_id FROM timetable WHERE faculty_id = %s AND is_active = 1
            UNION
            SELECT subject_id FROM sessions WHERE (faculty_id = %s OR substitute_faculty_id = %s OR delegated_faculty_id = %s) AND subject_id IS NOT NULL
        )
        ORDER BY sub.name
        """,
        (faculty_id, faculty_id, user_id, faculty_id, faculty_id, faculty_id, faculty_id, faculty_id),
    )
    subjects = cursor.fetchall()
    cursor.close()

    return jsonify({
        "success": True,
        "name": fac["name"],
        "email": fac["email"],
        "department": fac["department_name"],
        "designation": fac["designation"],
        "sections": sections,
        "subjects": subjects,
    })