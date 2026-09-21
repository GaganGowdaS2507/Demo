"""
Mobile Fingerprint API
Exposes GET /api/mobile/fingerprints to allow mobile apps to sync
active fingerprint template_id -> student mappings for offline or local verification.
"""
import logging
from flask import request, jsonify
from core.db import get_cursor
from . import mobile_bp
from .sync import mobile_token_required

logger = logging.getLogger(__name__)

@mobile_bp.route("/fingerprints", methods=["GET"])
@mobile_token_required
def get_mobile_fingerprints():
    section_id = request.args.get("section_id", type=int)
    camera_id = request.args.get("camera_id", type=int)

    cursor = get_cursor()
    query = """
        SELECT f.template_id, f.student_id, f.camera_id, s.usn, u.full_name AS name, s.section_id
        FROM fingerprints f
        JOIN students s ON s.id = f.student_id
        JOIN users u ON u.id = s.user_id
        WHERE f.status = 'active'
    """
    params = []
    if section_id is not None:
        query += " AND s.section_id = %s"
        params.append(section_id)
    if camera_id is not None:
        query += " AND f.camera_id = %s"
        params.append(camera_id)

    query += " ORDER BY f.template_id"
    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()

    return jsonify({
        "success": True,
        "count": len(rows),
        "fingerprints": rows
    })
