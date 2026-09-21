"""
attendance_system/api/admin/cameras.py
Camera (ESP32-CAM) device registry: add, edit, test, delete.
"""

import logging
import time

import cv2
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, jsonify
)

from core.db import get_db, get_cursor
from auth.helpers import admin_required
from utils.stream_source import normalize_stream_source, InvalidStreamSource

logger = logging.getLogger(__name__)

cameras_bp = Blueprint(
    "cameras", __name__,
    template_folder="../../templates/admin"
)

def _ensure_camera_assignment_column():
    """Ensure cameras.assigned_section_id exists for section binding."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'cameras'
              AND COLUMN_NAME = 'assigned_section_id'
            LIMIT 1
            """
        )
        if cursor.fetchone():
            return

        cursor.execute("ALTER TABLE cameras ADD COLUMN assigned_section_id INT NULL")
        cursor.execute(
            """
            ALTER TABLE cameras
            ADD CONSTRAINT fk_cameras_assigned_section
            FOREIGN KEY (assigned_section_id) REFERENCES sections(id)
            ON DELETE SET NULL
            """
        )
        conn.commit()
        logger.info("Added cameras.assigned_section_id")
    except Exception as e:
        conn.rollback()
        logger.warning("Could not ensure cameras.assigned_section_id: %s", e)
    finally:
        cursor.close()


@cameras_bp.route("/")
@admin_required
def list_cameras():
    """List all registered cameras."""
    _ensure_camera_assignment_column()
    cursor = get_cursor()
    cursor.execute(
        """
        SELECT c.*, sec.section_label, d.code AS dept_code
        FROM cameras c
        LEFT JOIN sections sec ON sec.id = c.assigned_section_id
        LEFT JOIN departments d ON d.id = sec.department_id
        ORDER BY c.name
        """
    )
    cameras_list = cursor.fetchall()
    cursor.execute(
        """
        SELECT sec.id, sec.section_label, sec.sem_number, d.code AS dept_code
        FROM sections sec
        JOIN departments d ON d.id = sec.department_id
        JOIN academic_periods ap ON ap.id = sec.academic_period_id
        WHERE ap.is_active = 1
        ORDER BY d.code, sec.sem_number, sec.section_label
        """
    )
    raw_sections = cursor.fetchall()
    sections = [
        {
            "id": s["id"],
            "dept_code": s["dept_code"],
            "sem_number": s["sem_number"],
            "section_label": s["section_label"],
            "display_label": f"{s['dept_code']} — Sem {s['sem_number']} — Sec {s['section_label']}"
        }
        for s in raw_sections
    ]
    return render_template("admin/cameras.html", cameras=cameras_list, sections=sections)


@cameras_bp.route("/add", methods=["POST"])
@admin_required
def add_camera():
    _ensure_camera_assignment_column()
    name     = request.form.get("name", "").strip()
    raw_source = request.form.get("rtsp_url", "").strip()
    location = request.form.get("location", "").strip()
    notes    = request.form.get("notes", "").strip()
    assigned_section_id = request.form.get("assigned_section_id", "").strip()

    if not name or not raw_source:
        flash("Name and a camera stream address (URL or IP) are required.", "danger")
        return redirect(url_for("cameras.list_cameras"))

    try:
        rtsp_url = normalize_stream_source(raw_source)
    except InvalidStreamSource as e:
        flash(str(e), "danger")
        return redirect(url_for("cameras.list_cameras"))

    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO cameras
                (name, rtsp_url, location, assigned_section_id, status, notes, created_at)
            VALUES (%s, %s, %s, %s, 'inactive', %s, NOW())
            """,
            (
                name, rtsp_url, location or None,
                int(assigned_section_id) if assigned_section_id else None,
                notes or None
            )
        )
        conn.commit()
        flash(f"Camera '{name}' registered.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "danger")

    return redirect(url_for("cameras.list_cameras"))

@cameras_bp.route("/<int:camera_id>/edit", methods=["POST"])
@admin_required
def edit_camera(camera_id):
    _ensure_camera_assignment_column()
    name     = request.form.get("name", "").strip()
    raw_source = request.form.get("rtsp_url", "").strip()
    location = request.form.get("location", "").strip()
    notes    = request.form.get("notes", "").strip()
    assigned_section_id = request.form.get("assigned_section_id", "").strip()

    try:
        rtsp_url = normalize_stream_source(raw_source)
    except InvalidStreamSource as e:
        flash(str(e), "danger")
        return redirect(url_for("cameras.list_cameras"))

    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE cameras
            SET name = %s, rtsp_url = %s, location = %s,
                assigned_section_id = %s, notes = %s
            WHERE id = %s
            """,
            (
                name, rtsp_url, location or None,
                int(assigned_section_id) if assigned_section_id else None,
                notes or None, camera_id
            )
        )
        conn.commit()
        flash("Camera updated.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "danger")

    return redirect(url_for("cameras.list_cameras"))


@cameras_bp.route("/<int:camera_id>/delete", methods=["POST"])
@admin_required
def delete_camera(camera_id):
    """Delete a camera."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cameras WHERE id = %s", (camera_id,))
        conn.commit()
        flash("Camera deleted.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "danger")

    return redirect(url_for("cameras.list_cameras"))


@cameras_bp.route("/<int:camera_id>/test", methods=["POST"])
@admin_required
def test_camera(camera_id):
    """Test if a camera's video stream and fingerprint module are accessible."""
    import requests
    from urllib.parse import urlparse

    cursor = get_cursor()
    cursor.execute("SELECT rtsp_url FROM cameras WHERE id = %s", (camera_id,))
    cam = cursor.fetchone()

    if not cam:
        return jsonify({"success": False, "message": "Device not found."})

    rtsp_url = cam["rtsp_url"]
    stream_success = False
    frame_info = ""
    sensor_info = ""

    # 1. Test Video Stream
    try:
        cap = cv2.VideoCapture(rtsp_url)
        start = time.time()
        while time.time() - start < 4.0:
            ret, frame = cap.read()
            if ret and frame is not None:
                stream_success = True
                frame_info = f"Video: {frame.shape[1]}x{frame.shape[0]} px"
                break
            time.sleep(0.1)
        cap.release()
    except Exception as e:
        frame_info = f"Video stream error: {e}"

    # 2. Test Fingerprint Control Server (Port 80 /status)
    try:
        parsed = urlparse(rtsp_url)
        host = parsed.hostname
        if host:
            resp = requests.get(f"http://{host}/status", timeout=3.0)
            if resp.status_code == 200:
                sensor_info = f" | Sensor Control: Online ({resp.text.strip()[:40]})"
            else:
                sensor_info = f" | Sensor Control: HTTP {resp.status_code}"
    except Exception as e:
        sensor_info = " | Sensor: Unreachable or stream-only"

    # Update camera status in DB
    conn = get_db()
    cur = conn.cursor()
    new_status = "active" if stream_success else "error"
    cur.execute(
        "UPDATE cameras SET status = %s, last_seen = NOW() WHERE id = %s",
        (new_status, camera_id)
    )
    conn.commit()

    if stream_success:
        return jsonify({
            "success": True,
            "message": f"Device reachable! {frame_info}{sensor_info}"
        })
    else:
        return jsonify({
            "success": False,
            "message": f"Cannot read frames from stream. {sensor_info}"
        })


@cameras_bp.route("/api/list")
@admin_required
def cameras_api():
    """AJAX: Get cameras list as JSON."""
    cursor = get_cursor()
    cursor.execute("SELECT id, name, rtsp_url, status, last_seen FROM cameras ORDER BY name")
    cameras = cursor.fetchall()

    # Convert datetime to string
    for c in cameras:
        if c.get("last_seen"):
            c["last_seen"] = c["last_seen"].strftime("%Y-%m-%d %H:%M:%S")

    return jsonify({"cameras": cameras})

