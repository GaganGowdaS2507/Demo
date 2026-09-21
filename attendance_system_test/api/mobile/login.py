"""
Mobile Login API
Returns JSON instead of HTML.
"""

import logging


from flask import request, jsonify

from . import mobile_bp
from .sync import _issue_token

from auth.helpers import (
    get_user_by_email,
    verify_password,
    update_last_login,
    log_audit,
    get_client_ip,
)

from core.db import get_db

logger = logging.getLogger(__name__)


@mobile_bp.route("/login", methods=["POST"])
def mobile_login():

    data = request.get_json(silent=True) or {}

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({
            "success": False,
            "message": "Email and password required."
        }), 400

    user_row = get_user_by_email(email)

    if user_row is None:
        return jsonify({
            "success": False,
            "message": "Invalid email or password."
        }), 401

    if not verify_password(password, user_row["password_hash"]):
        return jsonify({
            "success": False,
            "message": "Invalid email or password."
        }), 401

    status = (user_row.get("status") or "").strip().lower()

    if status and status not in ("active", "approved", "1", "true"):
        logger.warning(f"Mobile login denied for {email}: account status is '{status}'")
        return jsonify({
            "success": False,
            "message": f"Account status: {status}"
        }), 403

    role = (user_row.get("role") or "").strip().lower()

    department_id = None
    faculty_id = None
    student_id = None
    is_hod = False

    try:

        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)

        if role == "faculty":

            cursor.execute("""
                SELECT
                    id,
                    department_id,
                    designation
                FROM faculty
                WHERE user_id=%s
                LIMIT 1
            """, (user_row["id"],))

            fac = cursor.fetchone()

            if fac:
                faculty_id = fac["id"]
                department_id = fac["department_id"]
                is_hod = (
                    (fac.get("designation") or "").lower() == "hod"
                )

        elif role == "student":

            cursor.execute("""
                SELECT
                    id,
                    department_id
                FROM students
                WHERE user_id=%s
                LIMIT 1
            """, (user_row["id"],))

            stu = cursor.fetchone()

            if stu:
                student_id = stu["id"]
                department_id = stu["department_id"]

        cursor.close()

    except Exception as e:
        logger.error(e)

    update_last_login(user_row["id"])

    log_audit(
        user_row["id"],
        "mobile_login",
        ip_address=get_client_ip()
    )

    mobile_token = _issue_token(user_row)
    
    return jsonify({

        "success": True,

        "token": mobile_token,
        
        "message": "Login successful.",

        "role": role,

        "name": user_row["full_name"],

        "user_id": user_row["id"],

        "faculty_id": faculty_id,

        "student_id": student_id,

        "department_id": department_id,

        "is_hod": is_hod

    })