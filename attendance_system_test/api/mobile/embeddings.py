"""
attendance_system/api/mobile/embeddings.py
Downloads MobileFaceNet embeddings for offline recognition.
"""
import logging

from flask import jsonify, request

from . import mobile_bp
from .sync import mobile_token_required

from core.db import get_db
from recognition.utils import deserialize_embedding

logger = logging.getLogger(__name__)


def _faculty_section_ids(cursor, user_id, role=None):
    """Sections accessible to this faculty/admin/hod."""
    try:
        if role in ("admin", "hod"):
            cursor.execute("SELECT id AS section_id FROM sections")
            return [row["section_id"] for row in cursor.fetchall()]

        cursor.execute("SELECT id FROM faculty WHERE user_id = %s LIMIT 1", (user_id,))
        fac = cursor.fetchone()
        if not fac:
            return []
        faculty_id = fac["id"]

        section_ids = set()

        # 1. Check section_subjects
        try:
            cursor.execute("SELECT DISTINCT section_id FROM section_subjects WHERE faculty_id = %s", (faculty_id,))
            section_ids.update(row["section_id"] for row in cursor.fetchall() if row.get("section_id"))
        except Exception:
            pass

        # 2. Check timetable
        try:
            cursor.execute("SELECT DISTINCT section_id FROM timetable WHERE faculty_id = %s AND is_active = 1", (faculty_id,))
            section_ids.update(row["section_id"] for row in cursor.fetchall() if row.get("section_id"))
        except Exception:
            pass

        # 3. Check sessions
        try:
            cursor.execute(
                """
                SELECT DISTINCT section_id FROM sessions
                WHERE faculty_id = %s OR substitute_faculty_id = %s OR delegated_faculty_id = %s
                """,
                (faculty_id, faculty_id, faculty_id),
            )
            section_ids.update(row["section_id"] for row in cursor.fetchall() if row.get("section_id"))
        except Exception:
            pass

        # 4. Check elective_groups
        try:
            cursor.execute("SELECT DISTINCT section_id FROM elective_groups WHERE faculty_id = %s", (faculty_id,))
            section_ids.update(row["section_id"] for row in cursor.fetchall() if row.get("section_id"))
        except Exception:
            pass

        return list(section_ids)
    except Exception as e:
        logger.error("Error in _faculty_section_ids: %s", e)
        return []


@mobile_bp.route("/embeddings", methods=["GET"])
@mobile_token_required
def get_mobile_embeddings():
    if request.mobile_user.get("role") not in ("faculty", "admin", "hod"):
        return jsonify({"success": False, "message": "Faculty access required"}), 403

    try:
        section_id = request.args.get("section_id", type=int)

        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)

        role = request.mobile_user.get("role")
        user_id = request.mobile_user["user_id"]

        if section_id is not None:
            # Caller asked for one section — verify it belongs to or is accessible by this user.
            allowed = _faculty_section_ids(cursor, user_id, role)
            if allowed and section_id not in allowed:
                cursor.close()
                return jsonify({"success": False, "message": "Not your section"}), 403
            section_ids = [section_id]
        else:
            section_ids = _faculty_section_ids(cursor, user_id, role)

        if not section_ids:
            cursor.close()
            return jsonify({"success": True, "count": 0, "students": []})

        rows = []
        placeholders = ",".join(["%s"] * len(section_ids))

        # 1. Query faces_mobile
        try:
            cursor.execute(
                f"""
                SELECT
                    fm.student_id, fm.usn, fm.embedding, fm.model_version,
                    s.section_id, u.full_name AS name
                FROM faces_mobile fm
                JOIN students s ON s.id = fm.student_id
                JOIN users u ON u.id = s.user_id
                WHERE s.section_id IN ({placeholders})
                ORDER BY u.full_name
                """,
                tuple(section_ids),
            )
            rows = cursor.fetchall()
        except Exception as query_err:
            logger.warning("Querying faces_mobile failed: %s", query_err)

        # 2. Fallback to faces table if faces_mobile yielded 0 rows
        if not rows:
            try:
                cursor.execute(
                    f"""
                    SELECT
                        f.student_id, f.usn, f.embedding, 'faces_full' AS model_version,
                        s.section_id, u.full_name AS name
                    FROM faces f
                    JOIN students s ON s.id = f.student_id
                    JOIN users u ON u.id = s.user_id
                    WHERE s.section_id IN ({placeholders})
                    ORDER BY u.full_name
                    """,
                    tuple(section_ids),
                )
                rows = cursor.fetchall()
            except Exception as fallback_err:
                logger.warning("Querying faces fallback failed: %s", fallback_err)

        cursor.close()

        students = []
        for row in rows:
            try:
                emb = deserialize_embedding(row["embedding"])
                if emb is None:
                    continue
                students.append({
                    "student_id": row["student_id"],
                    "usn": row["usn"],
                    "name": row["name"],
                    "section_id": row["section_id"],
                    "embedding": emb.tolist(),
                    "model_version": row.get("model_version", "v1"),
                })
            except Exception as row_err:
                logger.warning("Error processing embedding row for student %s: %s", row.get("usn"), row_err)

        logger.info("Returning %s student embeddings for sections %s", len(students), section_ids)
        return jsonify({"success": True, "count": len(students), "students": students})

    except Exception as exc:
        logger.error("get_mobile_embeddings uncaught exception: %s", exc, exc_info=True)
        return jsonify({"success": True, "count": 0, "students": []})