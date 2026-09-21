from flask import Blueprint, request, jsonify, render_template
from flask_login import current_user, login_required

from core.db import get_cursor
from auth.helpers import admin_required
from recognition.fingerprint_service import (
    enroll_student, link_existing_template, delete_enrollment,
    get_device_slots, FingerprintError
)

fingerprints_bp = Blueprint(
    "fingerprints", __name__,
    url_prefix="/admin/fingerprints",
    template_folder="../../templates/admin"
)

@fingerprints_bp.route("/")
@admin_required
def list_fingerprints():
    cursor = get_cursor()
    
    # 1. Enrolled Fingerprints list
    cursor.execute("""
        SELECT f.id, f.student_id, f.camera_id, f.template_id, f.status, f.enrolled_at,
               s.usn, u.full_name AS student_name,
               c.name AS camera_name, c.location AS camera_location,
               sec.section_label, sec.sem_number, d.code AS dept_code
        FROM fingerprints f
        JOIN students s ON s.id = f.student_id
        JOIN users u ON u.id = s.user_id
        JOIN cameras c ON c.id = f.camera_id
        LEFT JOIN sections sec ON sec.id = s.section_id
        LEFT JOIN departments d ON d.id = s.department_id
        ORDER BY c.name, f.template_id
    """)
    rows = cursor.fetchall()

    # 2. Registered Devices with slot usage count and assigned section info
    cursor.execute("""
        SELECT c.id, c.name, c.rtsp_url, c.location, c.status,
               sec.section_label, sec.sem_number, d.code AS dept_code,
               (SELECT COUNT(*) FROM fingerprints f WHERE f.camera_id = c.id AND f.status = 'active') AS active_slots
        FROM cameras c
        LEFT JOIN sections sec ON sec.id = c.assigned_section_id
        LEFT JOIN departments d ON d.id = sec.department_id
        ORDER BY c.name
    """)
    cameras = cursor.fetchall()

    # 3. Active Departments for dropdown filter
    cursor.execute("SELECT id, code, name FROM departments ORDER BY code")
    departments = cursor.fetchall()

    # 4. Active Sections for dropdown filter
    cursor.execute("""
        SELECT sec.id, sec.section_label, sec.sem_number, sec.department_id, d.code AS dept_code
        FROM sections sec
        JOIN departments d ON d.id = sec.department_id
        JOIN academic_periods ap ON ap.id = sec.academic_period_id
        WHERE ap.is_active = 1
        ORDER BY d.code, sec.sem_number, sec.section_label
    """)
    sections = cursor.fetchall()

    # 5. All Students with Section & Enrollment Metadata for existing student selection
    cursor.execute("""
        SELECT s.id, s.usn, u.full_name AS name,
               s.department_id, s.current_sem, s.section_id,
               d.code AS dept_code, sec.section_label, sec.sem_number,
               (SELECT COUNT(*) FROM fingerprints f WHERE f.student_id = s.id AND f.status = 'active') AS fp_count
        FROM students s
        JOIN users u ON u.id = s.user_id
        LEFT JOIN sections sec ON sec.id = s.section_id
        LEFT JOIN departments d ON d.id = s.department_id
        WHERE u.status = 'active'
        ORDER BY s.usn
    """)
    students = cursor.fetchall()

    return render_template(
        "admin/fingerprints.html",
        rows=rows,
        cameras=cameras,
        departments=departments,
        sections=sections,
        students=students
    )


@fingerprints_bp.route("/api/device-slots/<int:camera_id>")
@admin_required
def device_slots_api(camera_id):
    """AJAX endpoint to return used and next available slots for a camera/device."""
    try:
        slots_info = get_device_slots(camera_id)
        return jsonify({"success": True, "slots": slots_info})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@fingerprints_bp.route("/enroll", methods=["POST"])
@admin_required
def enroll():
    student_id = request.form.get("student_id", type=int)
    camera_id = request.form.get("camera_id", type=int)
    template_id = request.form.get("template_id", type=int)

    if not student_id or not camera_id:
        return jsonify({"success": False, "message": "Student and Target Device are required."})
    
    try:
        result = enroll_student(
            student_id=student_id,
            camera_id=camera_id,
            template_id=template_id,
            enrolled_by=current_user.id
        )
        return jsonify({"success": True, **result})
    except FingerprintError as e:
        return jsonify({"success": False, "message": str(e)})
    except Exception as e:
        return jsonify({"success": False, "message": f"Unexpected error: {e}"})


@fingerprints_bp.route("/link-existing", methods=["POST"])
@admin_required
def link_existing():
    """Directly map an already enrolled hardware slot on a device to a student in DB."""
    student_id = request.form.get("student_id", type=int)
    camera_id = request.form.get("camera_id", type=int)
    template_id = request.form.get("template_id", type=int)

    if not student_id or not camera_id or not template_id:
        return jsonify({
            "success": False,
            "message": "Student, Recognition Device, and Template Slot ID are all required."
        })

    enrolled_by = getattr(current_user, 'id', None)
    try:
        result = link_existing_template(
            student_id=student_id,
            camera_id=camera_id,
            template_id=template_id,
            enrolled_by=enrolled_by
        )
        return jsonify({"success": True, **result})
    except FingerprintError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "message": f"Unexpected error: {e}"}), 500


@fingerprints_bp.route("/delete", methods=["POST"])
@admin_required
def delete():
    fingerprint_id = request.form.get("fingerprint_id", type=int)
    student_id = request.form.get("student_id", type=int)
    camera_id = request.form.get("camera_id", type=int)

    try:
        msg = delete_enrollment(
            student_id=student_id,
            camera_id=camera_id,
            fingerprint_id=fingerprint_id
        )
        return jsonify({"success": True, "message": msg})
    except FingerprintError as e:
        return jsonify({"success": False, "message": str(e)})
    except Exception as e:
        return jsonify({"success": False, "message": f"Unexpected error: {e}"})