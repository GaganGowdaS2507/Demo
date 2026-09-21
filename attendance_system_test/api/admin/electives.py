# api/admin/electives.py
"""
Manages elective_groups / elective_group_members — the shared roster
mechanism for professional electives, open electives, and split-groups.
"""
import re
from flask import Blueprint, request, jsonify, render_template
from flask_login import current_user, login_required
from core.db import get_db, get_cursor
from auth.helpers import admin_required, log_audit, get_client_ip

electives_bp = Blueprint("electives", __name__, url_prefix="/admin/electives")


# ─────────────────────────────────────────────────────────────
# PAGE — management screen
# ─────────────────────────────────────────────────────────────
@electives_bp.route("/")
@login_required
@admin_required
def manage_page():
    cursor = get_cursor()
    cursor.execute("""
    SELECT
        id,
        name,
        cycle,
        sem_number,
        start_date,
        end_date,
        status
    FROM academic_periods
    WHERE is_active = 1
    LIMIT 1
    """)
    period = cursor.fetchone()

    cursor.execute("""
        SELECT c.id, c.cluster_name, c.department_id, c.semester, d.code AS dept_code, d.name AS dept_name
        FROM clusters c
        JOIN departments d ON d.id = c.department_id
        ORDER BY d.code, c.cluster_name
    """)
    clusters = cursor.fetchall()

    cursor.execute("SELECT id, code, name, has_clusters FROM departments ORDER BY code")
    departments = cursor.fetchall()

    cursor.execute("""
        SELECT sec.id, sec.section_label, sec.sem_number, d.code AS dept_code
        FROM sections sec JOIN departments d ON d.id = sec.department_id
        ORDER BY d.code, sec.sem_number, sec.section_label
    """)
    sections = cursor.fetchall()
    cursor.execute("SELECT id, code, name FROM subjects ORDER BY code, name")
    subjects = cursor.fetchall()
    cursor.execute("SELECT f.id, u.full_name FROM faculty f JOIN users u ON u.id=f.user_id ORDER BY u.full_name")
    faculty_list = cursor.fetchall()
    return render_template(
        "admin/electives.html",
        period=period, clusters=clusters, departments=departments,
        sections=sections, subjects=subjects, faculty_list=faculty_list,
    )


# ─────────────────────────────────────────────────────────────
# LIST groups (JSON) — filterable by type/period, used by the page
# and by the session-create dropdown ("which groups exist for this subject")
# ─────────────────────────────────────────────────────────────
@electives_bp.route("/groups")
@login_required
@admin_required
def list_groups():
    academic_period_id = request.args.get("academic_period_id", type=int)
    subject_id = request.args.get("subject_id", type=int)
    group_type = request.args.get("group_type")

    cursor = get_cursor()
    query = """ 
    SELECT
        eg.*,

        sub.code  AS subject_code,
        sub.name  AS subject_name,

        c.cluster_name,
        d.code    AS dept_code,
        sec.section_label,
        sec.sem_number AS section_sem,

        (
            SELECT COUNT(*)
            FROM elective_group_members m
            WHERE
                m.elective_group_id = eg.id
                AND m.is_active = 1
        ) AS enrolled_count

    FROM elective_groups eg

    JOIN subjects sub
        ON sub.id = eg.subject_id

    LEFT JOIN clusters c
        ON c.id = eg.cluster_id

    LEFT JOIN departments d
        ON d.id = eg.department_id

    LEFT JOIN sections sec
        ON sec.id = eg.parent_section_id

    WHERE eg.is_active = 1
    """
    params = []
    if academic_period_id:
        query += " AND eg.academic_period_id = %s"
        params.append(academic_period_id)
    if subject_id:
        query += " AND eg.subject_id = %s"
        params.append(subject_id)
    if group_type:
        if group_type in ("ability_enhancement", "split_group"):
            query += " AND eg.group_type IN ('ability_enhancement', 'split_group')"
        else:
            query += " AND eg.group_type = %s"
            params.append(group_type)
    query += " ORDER BY eg.group_type, sub.name"

    cursor.execute(query, tuple(params))
    return jsonify({"groups": cursor.fetchall()})


@electives_bp.route("/open-matrix")
@login_required
@admin_required
def open_elective_matrix():
    academic_period_id = request.args.get("academic_period_id", type=int)
    sem_number = request.args.get("sem_number", type=int, default=6)

    cursor = get_cursor()

    cursor.execute("""
        SELECT eg.*, sub.code AS subject_code, sub.name AS subject_name,
               d.code AS dept_code, d.name AS dept_name,
               u.full_name AS faculty_name,
               (SELECT COUNT(*) FROM elective_group_members m WHERE m.elective_group_id = eg.id AND m.is_active = 1) AS enrolled_count
        FROM elective_groups eg
        JOIN subjects sub ON sub.id = eg.subject_id
        LEFT JOIN departments d ON d.id = eg.department_id
        LEFT JOIN faculty f ON f.id = eg.faculty_id
        LEFT JOIN users u ON u.id = f.user_id
        WHERE eg.group_type = 'open_elective'
          AND eg.is_active = 1
          AND (%s IS NULL OR eg.academic_period_id = %s)
          AND (%s IS NULL OR eg.sem_number = %s)
        ORDER BY sub.code
    """, (academic_period_id, academic_period_id, sem_number, sem_number))
    groups = cursor.fetchall()

    total_subjs = len(groups) or 1

    cursor.execute("""
        SELECT d.id, d.code, d.name, COUNT(s.id) AS student_count
        FROM departments d
        JOIN sections sec ON sec.department_id = d.id
        JOIN students s ON s.section_id = sec.id
        WHERE sec.sem_number = %s
        GROUP BY d.id, d.code, d.name
        HAVING student_count > 0
        ORDER BY d.code
    """, (sem_number,))
    participating_depts = cursor.fetchall()

    import math
    for dept in participating_depts:
        dept["quota_cap"] = math.ceil(dept["student_count"] / total_subjs) + 1

    matrix = []
    for g in groups:
        cursor.execute("""
            SELECT sec.department_id, COUNT(m.student_id) AS count
            FROM elective_group_members m
            JOIN students s ON s.id = m.student_id
            JOIN sections sec ON sec.id = s.section_id
            WHERE m.elective_group_id = %s AND m.is_active = 1
            GROUP BY sec.department_id
        """, (g["id"],))
        breakdown_rows = cursor.fetchall()
        breakdown_map = {b["department_id"]: b["count"] for b in breakdown_rows}

        dept_statuses = []
        for dept in participating_depts:
            cnt = breakdown_map.get(dept["id"], 0)
            cap = dept["quota_cap"]
            dept_statuses.append({
                "department_id": dept["id"],
                "dept_code": dept["code"],
                "count": cnt,
                "cap": cap,
                "is_full": (cnt >= cap)
            })

        g["dept_breakdown"] = dept_statuses
        matrix.append(g)

    return jsonify({
        "sem_number": sem_number,
        "total_subjects": len(groups),
        "participating_departments": participating_depts,
        "matrix": matrix
    })


# ─────────────────────────────────────────────────────────────
# ROSTER of one group (JSON)
# ─────────────────────────────────────────────────────────────
@electives_bp.route("/groups/<int:group_id>/roster")
@login_required
@admin_required
def group_roster(group_id):
    cursor = get_cursor()
    roster = get_elective_group_roster(cursor, group_id)
    return jsonify({"roster": roster})


# ─────────────────────────────────────────────────────────────
# Students eligible to be added — filtered by section so the admin isn't
# scrolling the entire college to find 8 names.
# ─────────────────────────────────────────────────────────────
@electives_bp.route("/eligible-students")
@login_required
@admin_required
def eligible_students():
    section_id = request.args.get("section_id", type=int)
    search = (request.args.get("q") or "").strip()
    cursor = get_cursor()
    query = "SELECT id, usn, name, section_id FROM students WHERE 1=1"
    params = []
    if section_id:
        query += " AND section_id = %s"
        params.append(section_id)
    if search:
        query += " AND (name LIKE %s OR usn LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])
    query += " ORDER BY name LIMIT 200"
    cursor.execute(query, tuple(params))
    return jsonify({"students": cursor.fetchall()})


# ─────────────────────────────────────────────────────────────
# Remove a student from a group roster
# ─────────────────────────────────────────────────────────────
@electives_bp.route("/groups/<int:group_id>/remove/<int:student_id>", methods=["POST"])
@login_required
@admin_required
def remove_member(group_id, student_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        cursor.execute(
            "UPDATE elective_group_members SET is_active=0 WHERE elective_group_id=%s AND student_id=%s",
            (group_id, student_id)
        )
        conn.commit()
        log_audit(current_user.id, "remove_elective_member", "elective_group_members",
                  group_id, None, str(student_id), ip_address=get_client_ip())
        return jsonify({"success": True})
    except Exception as exc:
        conn.rollback()
        return jsonify({"success": False, "message": str(exc)}), 500


# ─────────────────────────────────────────────────────────────
# Deactivate an entire group (e.g. created by mistake)
# ─────────────────────────────────────────────────────────────
@electives_bp.route("/groups/<int:group_id>/deactivate", methods=["POST"])
@login_required
@admin_required
def deactivate_group(group_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        cursor.execute("UPDATE elective_groups SET is_active=0 WHERE id=%s", (group_id,))
        conn.commit()
        return jsonify({"success": True})
    except Exception as exc:
        conn.rollback()
        return jsonify({"success": False, "message": str(exc)}), 500


def _slugify(text):
    return re.sub(r'[^A-Z0-9]+', '-', (text or "").upper()).strip('-')[:40]


def create_elective_group(
    cursor,
    subject_id,
    academic_period_id,
    group_type,
    cluster_id=None,
    parent_section_id=None,
    department_id=None,
    sem_number=None,
    faculty_id=None,
    max_capacity=None,
    created_by=None,
):
    """
    Creates a teaching group for a subject.

    group_type values:
        professional_elective
        open_elective
        split_group
        ability_enhancement
    """

    # ----------------------------------------------------
    # Validate group type
    # ----------------------------------------------------
    VALID_TYPES = {
        "professional_elective",
        "open_elective",
        "split_group",
        "ability_enhancement",
    }

    if group_type not in VALID_TYPES:
        raise ValueError(f"Unsupported group type: {group_type}")

    # ----------------------------------------------------
    # Validate required fields
    # ----------------------------------------------------
    if group_type == "professional_elective":
        if not cluster_id and not department_id:
            raise ValueError("Professional Elective requires a cluster or department selection.")
        if cluster_id and not department_id:
            cursor.execute("SELECT department_id FROM clusters WHERE id=%s", (cluster_id,))
            cl = cursor.fetchone()
            if cl:
                department_id = cl["department_id"]

    if group_type == "open_elective":
        if not department_id or not sem_number:
            raise ValueError("Open Elective requires department_id and sem_number.")

    if group_type in ("split_group", "ability_enhancement"):
        if parent_section_id and not department_id:
            cursor.execute("SELECT department_id, sem_number FROM sections WHERE id=%s", (parent_section_id,))
            sec_info = cursor.fetchone()
            if sec_info:
                department_id = sec_info["department_id"]
                sem_number = sec_info["sem_number"]
        if not department_id and not parent_section_id:
            raise ValueError("Ability Enhancement / Section Split Group requires a department or parent section.")

    # ----------------------------------------------------
    # Verify subject exists
    # ----------------------------------------------------
    cursor.execute(
        """
        SELECT id, code
        FROM subjects
        WHERE id=%s
        """,
        (subject_id,)
    )

    subject = cursor.fetchone()

    if not subject:
        raise ValueError(f"Invalid subject_id: {subject_id}")

    # ----------------------------------------------------
    # Build prefix
    # ----------------------------------------------------
    if group_type == "professional_elective":
        if cluster_id:
            prefix = f"CLU{cluster_id}"
        else:
            prefix = f"PE-D{department_id}"

    elif group_type == "open_elective":
        prefix = f"OPEN-D{department_id}-S{sem_number}"

    elif group_type == "split_group":
        prefix = f"SPLIT-SEC{parent_section_id}"

    elif group_type == "ability_enhancement":
        prefix = f"AEC-D{department_id}"
        if parent_section_id:
            prefix += f"-SEC{parent_section_id}"

    # ----------------------------------------------------
    # Generate group code
    # ----------------------------------------------------
    group_code = (
        f"{prefix}-"
        f"{_slugify(subject['code'])}"
        f"-P{academic_period_id}"
    )

    # ----------------------------------------------------
    # Prevent duplicate group code
    # ----------------------------------------------------
    cursor.execute(
        """
        SELECT id
        FROM elective_groups
        WHERE group_code=%s
        """,
        (group_code,)
    )

    if cursor.fetchone():
        raise ValueError(
            f"Group code already exists: {group_code}"
        )

    # ----------------------------------------------------
    # Insert
    # ----------------------------------------------------
    cursor.execute(
        """
        INSERT INTO elective_groups
        (
            group_code,
            subject_id,
            academic_period_id,
            group_type,
            cluster_id,
            parent_section_id,
            department_id,
            sem_number,
            faculty_id,
            max_capacity,
            is_active,
            created_by,
            created_at
        )
        VALUES
        (
            %s,%s,%s,%s,
            %s,%s,%s,%s,
            %s,%s,
            1,%s,NOW()
        )
        """,
        (
            group_code,
            subject_id,
            academic_period_id,
            group_type,
            cluster_id,
            parent_section_id,
            department_id,
            sem_number,
            faculty_id,
            max_capacity,
            created_by,
        ),
    )

    return cursor.lastrowid

@electives_bp.route("/groups/create", methods=["POST"])
@admin_required
def create_group_route():
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)

    try:
        group_type = request.form.get("group_type")

        department_id = request.form.get("department_id", type=int) or None
        cluster_id = request.form.get("cluster_id", type=int) or None
        parent_section_id = request.form.get("parent_section_id", type=int) or None

        # AEC merge toggle
        merge_sections = request.form.get("merge_sections") == "1"

        # Validation
        if group_type == "ability_enhancement":

            if not department_id:
                return jsonify({
                    "success": False,
                    "message": "Department is required for AEC/SEC groups."
                }), 400

            # When merging sections, this group is department-wide
            if merge_sections:
                parent_section_id = None

        group_id = create_elective_group(
            cursor,
            subject_id=request.form.get("subject_id", type=int),
            academic_period_id=request.form.get("academic_period_id", type=int),
            group_type=group_type,
            cluster_id=cluster_id,
            parent_section_id=parent_section_id,
            department_id=department_id,
            sem_number=request.form.get("sem_number", type=int) or None,
            faculty_id=request.form.get("faculty_id", type=int) or None,
            max_capacity=request.form.get("max_capacity", type=int) or None,
            created_by=current_user.id,
        )

        conn.commit()

        return jsonify({
            "success": True,
            "elective_group_id": group_id
        })

    except Exception as exc:
        conn.rollback()

        return jsonify({
            "success": False,
            "message": str(exc)
        }), 500

# api/admin/electives.py — add near create_elective_group()

def check_registration_conflict(cursor, student_id, group):
    """
    Returns a conflict reason string if `student_id` registering into `group`
    would violate a category rule, else None.

    professional_elective -> 1 per cluster per period (already chose a cluster
                              elective; can't also take a different one)
    open_elective         -> 1 per period, full stop (department-agnostic)
    ability_enhancement   -> 1 per department per sem per period (DevOps vs
                              GenAI are mutually exclusive options)
    split_group           -> no conflict check; it's a teaching split of a
                              subject the student is already registered for
                              some other way (mandatory), not a new choice.
    """
    gtype = group["group_type"]

    if gtype == "professional_elective" and group["cluster_id"]:
        cursor.execute(
            """
            SELECT eg.id FROM elective_group_members egm
            JOIN elective_groups eg ON eg.id = egm.elective_group_id
            WHERE egm.student_id = %s AND egm.is_active = 1
              AND eg.cluster_id = %s AND eg.academic_period_id = %s
              AND eg.id != %s
            """,
            (student_id, group["cluster_id"], group["academic_period_id"], group["id"])
        )
        if cursor.fetchone():
            return "already registered for another elective in this cluster this period"

    elif gtype == "open_elective":
        cursor.execute(
            """
            SELECT eg.id FROM elective_group_members egm
            JOIN elective_groups eg ON eg.id = egm.elective_group_id
            WHERE egm.student_id = %s AND egm.is_active = 1
              AND eg.group_type = 'open_elective' AND eg.academic_period_id = %s
              AND eg.id != %s
            """,
            (student_id, group["academic_period_id"], group["id"])
        )
        if cursor.fetchone():
            return "already registered for an open elective this period (only one allowed)"

        # Check Department-level Quota Cap for Open Electives
        cursor.execute("""
            SELECT sec.department_id, sec.sem_number, d.code AS dept_code
            FROM students s
            JOIN sections sec ON sec.id = s.section_id
            JOIN departments d ON d.id = sec.department_id
            WHERE s.id = %s
        """, (student_id,))
        stu_info = cursor.fetchone()

        if stu_info and group.get("sem_number"):
            dept_id = stu_info["department_id"]
            sem_num = group["sem_number"]

            # Count total Open Elective subjects offered for this sem & period
            cursor.execute("""
                SELECT COUNT(DISTINCT subject_id) AS total_subjs
                FROM elective_groups
                WHERE group_type = 'open_elective'
                  AND academic_period_id = %s
                  AND sem_number = %s
                  AND is_active = 1
            """, (group["academic_period_id"], sem_num))
            subj_res = cursor.fetchone()
            total_open_subjs = (subj_res["total_subjs"] if subj_res else 0) or 1

            # Count total students in this student's department & sem
            cursor.execute("""
                SELECT COUNT(*) AS total_dept_students
                FROM students s
                JOIN sections sec ON sec.id = s.section_id
                WHERE sec.department_id = %s AND sec.sem_number = %s
            """, (dept_id, sem_num))
            dept_res = cursor.fetchone()
            total_dept_students = dept_res["total_dept_students"] if dept_res else 0

            if total_dept_students > 0 and total_open_subjs > 0:
                import math
                dept_quota_cap = math.ceil(total_dept_students / total_open_subjs) + 1

                # Count current enrolled students from this department in this specific open elective group
                cursor.execute("""
                    SELECT COUNT(*) AS current_dept_count
                    FROM elective_group_members egm
                    JOIN students s ON s.id = egm.student_id
                    JOIN sections sec ON sec.id = s.section_id
                    WHERE egm.elective_group_id = %s
                      AND egm.is_active = 1
                      AND sec.department_id = %s
                """, (group["id"], dept_id))
                curr_res = cursor.fetchone()
                current_dept_count = curr_res["current_dept_count"] if curr_res else 0

                if current_dept_count >= dept_quota_cap:
                    return f"Department quota cap reached for {stu_info['dept_code']} in this subject ({current_dept_count}/{dept_quota_cap} students registered)"

    elif gtype == "ability_enhancement":
        cursor.execute(
            """
            SELECT eg.id FROM elective_group_members egm
            JOIN elective_groups eg ON eg.id = egm.elective_group_id
            JOIN subjects s1 ON s1.id = eg.subject_id
            JOIN subjects s2 ON s2.id = %s
            WHERE egm.student_id = %s AND egm.is_active = 1
              AND eg.group_type = 'ability_enhancement'
              AND eg.department_id = %s
              AND eg.academic_period_id = %s
              AND s1.sem_number = s2.sem_number
              AND eg.id != %s
            """,
            (group["subject_id"], student_id, group["department_id"],
             group["academic_period_id"], group["id"])
        )
        if cursor.fetchone():
            return {
            "success": False,
            "reason": "already registered for another AEC/SEC option this semester"
        }

    return None


@electives_bp.route("/groups/<int:group_id>/enroll", methods=["POST"])
@admin_required
def enroll_students(group_id):
    student_ids = request.form.getlist("student_ids", type=int)
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        cursor.execute("SELECT * FROM elective_groups WHERE id=%s", (group_id,))
        group = cursor.fetchone()
        if not group:
            return jsonify({"success": False, "message": "Group not found."}), 404

        skipped, enrolled = [], []
        for sid in student_ids:
            cursor.execute("SELECT section_id FROM students WHERE id=%s", (sid,))
            stu = cursor.fetchone()
            if not stu:
                skipped.append({"student_id": sid, "reason": "not found"})
                continue

            conflict = check_registration_conflict(cursor, sid, group)
            if conflict:
                skipped.append({"student_id": sid, "reason": conflict})
                continue

            cursor.execute(
                """
                INSERT INTO elective_group_members
                    (elective_group_id, student_id, home_section_id, is_active, enrolled_at)
                VALUES (%s,%s,%s,1,NOW())
                ON DUPLICATE KEY UPDATE is_active = 1
                """,
                (group_id, sid, stu["section_id"])
            )
            enrolled.append(sid)

        conn.commit()
        log_audit(current_user.id, "enroll_elective_group", "elective_groups", group_id,
                  None, f"{len(enrolled)} students", ip_address=get_client_ip())
        return jsonify({"success": True, "enrolled": enrolled, "skipped": skipped})
    except Exception as exc:
        conn.rollback()
        return jsonify({"success": False, "message": str(exc)}), 500
    
    
def get_elective_group_roster(cursor, elective_group_id):
    """Returns list of {id, usn, name, dept_code, section_label} for every active member — this IS
    the combined attendance roster for any session tied to this group."""
    cursor.execute(
        """
        SELECT s.id, s.usn, s.name, s.section_id AS home_section_id,
               d.code AS dept_code, sec.section_label
        FROM elective_group_members egm
        JOIN students s ON s.id = egm.student_id
        LEFT JOIN sections sec ON sec.id = s.section_id
        LEFT JOIN departments d ON d.id = sec.department_id
        WHERE egm.elective_group_id = %s AND egm.is_active = 1
        ORDER BY d.code, s.usn
        """,
        (elective_group_id,)
    )
    return cursor.fetchall()