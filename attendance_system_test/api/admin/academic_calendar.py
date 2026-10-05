"""
api/admin/academic_calendar.py

Admin page to manage calendar events (holidays, IA, exams, special working days...).
Adding a day-blocking event cancels classes that are still 'scheduled' on those dates.
Deleting the event restores them. Sessions that are active/completed are never touched.
"""
import json
import logging
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user

from core.db import get_db
from auth.helpers import admin_required, log_audit, get_client_ip
from services.timetable_engine import rebuild_plan
from services.calendar_service import rebuild_days_for_event, calendar_summary


logger = logging.getLogger(__name__)

acad_calendar_bp = Blueprint(
    "acad_calendar", __name__,
    template_folder="../../templates/admin"
)

VALID_SCOPES = ("college", "department", "section")
VALID_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")


# ------------------------------------------------------------------ helpers
def _parse_date(text):
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_time(text):
    """'' -> None (empty). Bad text -> False. Good text -> time object."""
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            pass
    return False


def _fmt_time(value):
    if value is None:
        return ""
    if hasattr(value, "total_seconds"):          # MySQL TIME comes as timedelta
        total = int(value.total_seconds())
        return f"{total // 3600:02d}:{(total % 3600) // 60:02d}"
    return str(value)[:5]


def _cancel_sessions(cur, ev):
    """Cancel still-'scheduled' timetable sessions hit by this blocking event."""
    sql = (
        "UPDATE sessions s JOIN sections sec ON sec.id = s.section_id "
        "SET s.status = 'cancelled', s.dismiss_reason = %s "
        "WHERE s.status = 'scheduled' AND s.source = 'timetable' "
        "AND s.session_date BETWEEN %s AND %s"
    )
    params = [f"CAL#{ev['id']}: {ev['title']}"[:255], ev["start_date"], ev["end_date"]]

    if ev.get("academic_period_id"):
        sql += " AND sec.academic_period_id = %s"
        params.append(ev["academic_period_id"])
    if ev["scope"] == "department":
        sql += " AND sec.department_id = %s"
        params.append(ev["department_id"])
    elif ev["scope"] == "section":
        sql += " AND s.section_id = %s"
        params.append(ev["section_id"])
    if ev.get("start_time") is not None and ev.get("end_time") is not None:
        sql += " AND s.start_time < %s AND s.end_time > %s"
        params += [ev["end_time"], ev["start_time"]]

    cur.execute(sql, params)
    return cur.rowcount


def _restore_sessions(cur, event_id):
    cur.execute(
        "UPDATE sessions SET status = 'scheduled', dismiss_reason = NULL "
        "WHERE status = 'cancelled' AND dismiss_reason LIKE %s",
        (f"CAL#{event_id}:%",),
    )
    return cur.rowcount


def _reapply_blocking(cur, start, end, skip_id):
    """After a delete, other blocking events on the same dates must still apply."""
    cur.execute(
        """
        SELECT e.id, e.title, e.start_date, e.end_date, e.start_time, e.end_time,
               e.scope, e.department_id, e.section_id, e.academic_period_id
        FROM calendar_events e
        JOIN calendar_event_types t ON t.id = e.event_type_id
        WHERE e.id <> %s AND e.start_date <= %s AND e.end_date >= %s
        AND COALESCE(e.impact_override, t.teaching_impact) IN
              ('BLOCK_ALL', 'BLOCK_REGULAR_CLASSES', 'SECTION_SPECIFIC', 'FACULTY_SPECIFIC')
        """,
        (skip_id, end, start),
    )
    for ev in cur.fetchall():
        _cancel_sessions(cur, ev)

def _replan(cur, start, end, period_id=None, section_id=None):
    """Keep planned_sessions in step with the calendar for these dates only.
    A planner problem is rolled back and logged; it never blocks saving the event."""
    try:
        cur.execute("SAVEPOINT replan")
        if period_id:
            period_ids = [period_id]
        else:
            cur.execute(
                "SELECT id FROM academic_periods "
                "WHERE is_archived = 0 AND start_date <= %s AND end_date >= %s",
                (end, start))
            period_ids = [r["id"] for r in cur.fetchall()]
        for pid in period_ids:
            rebuild_plan(cur, pid, from_date=start, to_date=end, section_id=section_id)
    except Exception as exc:
        logger.warning("replan after calendar change failed: %s", exc)
        try:
            cur.execute("ROLLBACK TO SAVEPOINT replan")
        except Exception:
            pass

def _audit(action, target_id, data):
    try:
        log_audit(
            user_id=current_user.id, action=action,
            target_table="calendar_events", target_id=target_id,
            new_value=json.dumps(data, default=str), ip_address=get_client_ip(),
        )
    except Exception as exc:                      # audit must never break the page
        logger.warning("audit log failed: %s", exc)


# ------------------------------------------------------------------- routes
@acad_calendar_bp.route("/")
@admin_required
def index():
    conn = get_db()
    cur = conn.cursor(dictionary=True, buffered=True)

    cur.execute(
        "SELECT id, name, academic_year, sem_number, start_date, end_date, is_active "
        "FROM academic_periods WHERE is_archived = 0 "
        "ORDER BY is_active DESC, start_date DESC"
    )
    periods = cur.fetchall()

    selected = None
    wanted = request.args.get("period_id", type=int)
    for p in periods:
        if wanted and p["id"] == wanted:
            selected = p
    if selected is None and periods:
        selected = periods[0]

    events, sections = [], []
    if selected:
        cur.execute(
            """
            SELECT e.*, t.name AS type_name, t.color AS type_color,
                   COALESCE(e.effect_override, t.effect) AS effect,
                   d.code AS dept_code, sec.section_label
            FROM calendar_events e
            JOIN calendar_event_types t ON t.id = e.event_type_id
            LEFT JOIN departments d  ON d.id  = e.department_id
            LEFT JOIN sections   sec ON sec.id = e.section_id
            WHERE e.academic_period_id = %s OR e.academic_period_id IS NULL
            ORDER BY e.start_date, e.id
            """,
            (selected["id"],),
        )
        events = cur.fetchall()
        for e in events:
            e["days"] = (e["end_date"] - e["start_date"]).days + 1
            if e["start_time"] is not None and e["end_time"] is not None:
                e["time_text"] = f"{_fmt_time(e['start_time'])} - {_fmt_time(e['end_time'])}"
            else:
                e["time_text"] = "Full day"

        cur.execute(
            "SELECT sec.id, sec.section_label, d.code AS dept_code "
            "FROM sections sec JOIN departments d ON d.id = sec.department_id "
            "WHERE sec.academic_period_id = %s ORDER BY d.code, sec.section_label",
            (selected["id"],),
        )
        sections = cur.fetchall()

    cur.execute("SELECT id, code, name, effect, color FROM calendar_event_types "
                "WHERE is_active = 1 ORDER BY id")
    event_types = cur.fetchall()
    cur.execute("SELECT id, code, name FROM departments ORDER BY name")
    departments = cur.fetchall()

    return render_template(
        "admin/calendar.html",
        periods=periods, selected=selected, events=events,
        event_types=event_types, departments=departments,
        sections=sections, weekdays=VALID_DAYS,
    )


@acad_calendar_bp.route("/add", methods=["POST"])
@admin_required
def add_event():
    f = request.form
    period_id = f.get("period_id", type=int)
    back = url_for("acad_calendar.index", period_id=period_id) if period_id \
        else url_for("acad_calendar.index")

    title = (f.get("title") or "").strip()
    start = _parse_date(f.get("start_date"))
    end = _parse_date(f.get("end_date")) or start
    type_id = f.get("event_type_id", type=int)
    scope = f.get("scope", "college")
    dept_id = f.get("department_id", type=int)
    section_id = f.get("section_id", type=int)
    s_time = _parse_time(f.get("start_time"))
    e_time = _parse_time(f.get("end_time"))
    notes = (f.get("notes") or "").strip() or None
    follow = f.get("follow_weekday") or None

    # ---- validation
    if not title:
        flash("Title is required.", "danger"); return redirect(back)
    if not start or not end:
        flash("A valid start date is required.", "danger"); return redirect(back)
    if end < start:
        flash("End date cannot be before start date.", "danger"); return redirect(back)
    if scope not in VALID_SCOPES:
        flash("Invalid scope.", "danger"); return redirect(back)
    if scope == "department" and not dept_id:
        flash("Choose a department.", "danger"); return redirect(back)
    if scope == "section" and not section_id:
        flash("Choose a section.", "danger"); return redirect(back)
    if s_time is False or e_time is False:
        flash("Time must look like 14:30.", "danger"); return redirect(back)
    if (s_time is None) != (e_time is None):
        flash("Give both start time and end time, or leave both empty.", "danger"); return redirect(back)
    if s_time is not None and s_time >= e_time:
        flash("End time must be after start time.", "danger"); return redirect(back)

    conn = get_db()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        cur.execute("SELECT effect FROM calendar_event_types WHERE id = %s AND is_active = 1",
                    (type_id,))
        t = cur.fetchone()
        if not t:
            flash("Choose a valid event type.", "danger"); return redirect(back)
        effect = t["effect"]

        if effect == "allows_teaching":
            s_time = e_time = None                 # working days are full-day
            follow = follow if follow in VALID_DAYS else None
        else:
            follow = None

        row_period = None if f.get("apply_to") == "all" else period_id
        row_dept = dept_id if scope == "department" else None
        row_section = section_id if scope == "section" else None

        cur.execute(
            """
            INSERT INTO calendar_events
                (academic_period_id, event_type_id, title, start_date, end_date,
                 start_time, end_time, scope, department_id, section_id,
                 follow_weekday, notes, source, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'manual',%s)
            """,
            (row_period, type_id, title, start, end, s_time, e_time,
             scope, row_dept, row_section, follow, notes, current_user.id),
        )
        event_id = cur.lastrowid

        cancelled = 0
        if effect == "blocks_teaching":
            cancelled = _cancel_sessions(cur, {
                "id": event_id, "title": title, "start_date": start, "end_date": end,
                "start_time": s_time, "end_time": e_time, "scope": scope,
                "department_id": row_dept, "section_id": row_section,
                "academic_period_id": row_period,
            })
        rebuild_days_for_event(cur, row_period, start, end)
        _replan(cur, start, end, row_period,
                row_section if scope == "section" else None)
        conn.commit()
        _audit("calendar_event_add", event_id,
               {"title": title, "start": start, "end": end, "scope": scope,
                "cancelled_sessions": cancelled})

        msg = "Event added."
        if cancelled:
            msg += f" {cancelled} scheduled class(es) were cancelled."
        flash(msg, "success")
    except Exception as exc:
        conn.rollback()
        logger.exception("add calendar event failed")
        flash(f"Error adding event: {exc}", "danger")
    return redirect(back)


@acad_calendar_bp.route("/<int:event_id>/delete", methods=["POST"])
@admin_required
def delete_event(event_id):
    period_id = request.form.get("period_id", type=int)
    back = url_for("acad_calendar.index", period_id=period_id) if period_id \
        else url_for("acad_calendar.index")

    conn = get_db()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        cur.execute("SELECT id, title, start_date, end_date, academic_period_id, scope, section_id "
                    "FROM calendar_events WHERE id = %s", (event_id,))
        ev = cur.fetchone()
        if not ev:
            flash("Event not found.", "warning"); return redirect(back)

        restored = _restore_sessions(cur, event_id)
        cur.execute("DELETE FROM calendar_events WHERE id = %s", (event_id,))
        rebuild_days_for_event(cur, ev["academic_period_id"], ev["start_date"], ev["end_date"])
        _reapply_blocking(cur, ev["start_date"], ev["end_date"], event_id)
        _replan(cur, ev["start_date"], ev["end_date"], ev["academic_period_id"],
                ev["section_id"] if ev["scope"] == "section" else None)
        conn.commit()
        _audit("calendar_event_delete", event_id,
               {"title": ev["title"], "restored_sessions": restored})

        msg = "Event removed."
        if restored:
            msg += f" Cancelled classes were restored (those still free of other events)."
        flash(msg, "success")
    except Exception as exc:
        conn.rollback()
        logger.exception("delete calendar event failed")
        flash(f"Error: {exc}", "danger")
    return redirect(back)



@acad_calendar_bp.route("/summary/<int:period_id>")
@admin_required
def summary(period_id):
    """JSON: total working days / teaching days / teaching weeks for a period."""
    from flask import jsonify
    cur = get_db().cursor(dictionary=True, buffered=True)
    return jsonify(calendar_summary(cur, period_id))