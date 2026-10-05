"""
api/admin/session_exceptions.py

One-day changes to the plan. The timetable and the calendar are NEVER edited:
  cancel | substitute | room_change | move | extra   (+ undo)
Every change is a row in session_exceptions.
"""
import json
import logging
from datetime import date, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user

from core.db import get_db
from auth.helpers import admin_required, log_audit, get_client_ip
from services.calendar_service import check_slot, _to_delta
from services.roster_service import get_roster
from services.semester_service import period_for_section
from services.timetable_engine import rebuild_plan, open_session
# from api.admin.academic_calendar import _parse_date, _parse_time, _fmt_time

logger = logging.getLogger(__name__)

sess_exc_bp = Blueprint("sess_exc", __name__, template_folder="../../templates/admin")

HELD = ("active", "completed", "dismissed")


class ExcError(Exception):
    """A friendly message shown to the admin as it is."""


# ------------------------------------------------------------------ helpers
def _back(f):
    return url_for("sess_exc.index",
                   period_id=f.get("period_id", type=int),
                   date_from=f.get("date_from"), date_to=f.get("date_to"),
                   section_id=f.get("section_id", type=int),
                   faculty_id=f.get("faculty_id", type=int))


def _audit(action, target_id, data):
    try:
        log_audit(user_id=current_user.id, action=action,
                  target_table="session_exceptions", target_id=target_id,
                  new_value=json.dumps(data, default=str), ip_address=get_client_ip())
    except Exception as exc:
        logger.warning("audit log failed: %s", exc)


def _linked(cur, ps_id):
    cur.execute("SELECT id, status FROM sessions WHERE planned_session_id = %s", (ps_id,))
    return cur.fetchall()


def _need_planned(ps):
    if ps["status"] != "planned":
        raise ExcError("Only a planned class can be changed. This one is already "
                       f"'{ps['status']}'.")


def _insert_exc(cur, ps_id, etype, reason, **kw):
    cur.execute(
        "INSERT INTO session_exceptions "
        " (planned_session_id, exception_type, new_date, new_start_time, new_end_time, "
        "  new_faculty_id, new_room, new_planned_session_id, reason, created_by) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (ps_id, etype, kw.get("new_date"), kw.get("new_start"), kw.get("new_end"),
         kw.get("new_faculty_id"), kw.get("new_room"), kw.get("new_ps_id"),
         reason, current_user.id))
    return cur.lastrowid


def _deactivate_same(cur, ps_id, etype):
    cur.execute("UPDATE session_exceptions SET is_active = 0 "
                "WHERE planned_session_id = %s AND exception_type = %s AND is_active = 1",
                (ps_id, etype))


# def _create_session(cur, ps_id, session_type, title):
#     """Real session (+ everyone absent by default) for a planned row."""
#     cur.execute("SELECT * FROM planned_sessions WHERE id = %s", (ps_id,))
#     p = cur.fetchone()
#     cur.execute(
#         "INSERT INTO sessions "
#         " (timetable_id, section_id, subject_id, elective_group_id, faculty_id, "
#         "  substitute_faculty_id, session_date, start_time, end_time, room, status, "
#         "  session_type, source, component, planned_session_id, created_by, title, created_at) "
#         "VALUES (NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,'scheduled',%s,'manual',%s,%s,%s,%s,NOW())",
#         (p["section_id"], p["subject_id"], p["elective_group_id"], p["faculty_id"],
#          p["substitute_faculty_id"], p["planned_date"], p["start_time"], p["end_time"],
#          p["room"], session_type, p["component"], ps_id, current_user.id, title))
#     sid = cur.lastrowid
#     roster = get_roster(cur, [p["section_id"]], p["elective_group_id"])
#     if roster:
#         cur.executemany(
#             "INSERT IGNORE INTO attendance (session_id, student_id, usn, status, method, marked_at) "
#             "VALUES (%s,%s,%s,'absent','system',NOW())",
#             [(sid, r["id"], r["usn"]) for r in roster])
#     return sid

def _create_session(cur, ps_id, session_type, title):
    """Real session for a planned row. Delegated to the one engine (session type and title
    come from the planned row's origin: moved -> make-up, extra -> extra class)."""
    cur.execute("SELECT * FROM planned_sessions WHERE id = %s", (ps_id,))
    sid, _ = open_session(cur, cur.fetchone(), created_by=current_user.id)
    return sid

def _delete_sessions(cur, session_ids):
    if not session_ids:
        return
    marks = ",".join(["%s"] * len(session_ids))
    cur.execute(f"DELETE FROM attendance WHERE session_id IN ({marks})", session_ids)
    cur.execute(f"DELETE FROM sessions WHERE id IN ({marks})", session_ids)


# ------------------------------------------------------------------ actions
def _do_cancel(cur, ps, reason):
    _need_planned(ps)
    if any(s["status"] in ("active", "completed") for s in _linked(cur, ps["id"])):
        raise ExcError("This class has already been taken, so it cannot be cancelled.")
    exc_id = _insert_exc(cur, ps["id"], "cancel", reason)
    cur.execute("UPDATE planned_sessions SET status = 'cancelled', block_event_id = NULL "
                "WHERE id = %s", (ps["id"],))
    cur.execute("UPDATE sessions SET status = 'cancelled', dismiss_reason = %s "
                "WHERE planned_session_id = %s AND status = 'scheduled'",
                (f"EXC#{exc_id}: {reason or 'Cancelled'}"[:255], ps["id"]))
    return exc_id


def _do_substitute(cur, ps, new_faculty_id, reason):
    _need_planned(ps)
    if not new_faculty_id:
        raise ExcError("Choose the substitute faculty.")
    cur.execute("SELECT id FROM faculty WHERE id = %s", (new_faculty_id,))
    if not cur.fetchone():
        raise ExcError("Faculty not found.")
    if new_faculty_id == ps["faculty_id"]:
        raise ExcError("That is already the faculty for this class.")
    _deactivate_same(cur, ps["id"], "substitute")
    exc_id = _insert_exc(cur, ps["id"], "substitute", reason, new_faculty_id=new_faculty_id)
    cur.execute("UPDATE planned_sessions SET substitute_faculty_id = %s WHERE id = %s",
                (new_faculty_id, ps["id"]))
    cur.execute("UPDATE sessions SET substitute_faculty_id = %s "
                "WHERE planned_session_id = %s AND status IN ('scheduled','active')",
                (new_faculty_id, ps["id"]))
    return exc_id


def _do_room(cur, ps, new_room, reason):
    _need_planned(ps)
    new_room = (new_room or "").strip()
    if not new_room or len(new_room) > 50:
        raise ExcError("Enter the new room (up to 50 characters).")
    _deactivate_same(cur, ps["id"], "room_change")
    exc_id = _insert_exc(cur, ps["id"], "room_change", reason, new_room=new_room)
    cur.execute("UPDATE planned_sessions SET room = %s WHERE id = %s", (new_room, ps["id"]))
    cur.execute("UPDATE sessions SET room = %s "
                "WHERE planned_session_id = %s AND status IN ('scheduled','active')",
                (new_room, ps["id"]))
    return exc_id


def _do_move(cur, ps, new_date, new_start, new_end, reason):
    _need_planned(ps)
    if ps["origin"] == "extra":
        raise ExcError("An extra class cannot be moved. Undo it and add a new one.")
    if any(s["status"] in HELD for s in _linked(cur, ps["id"])):
        raise ExcError("This class has already been taken, so it cannot be moved.")
    if new_date is None:
        raise ExcError("Choose the new date.")
    start = _to_delta(new_start) if new_start is not None else ps["start_time"]
    end = _to_delta(new_end) if new_end is not None else ps["end_time"]
    if start >= end:
        raise ExcError("End time must be after start time.")
    if new_date == ps["planned_date"] and start == ps["start_time"] and end == ps["end_time"]:
        raise ExcError("The new date and time are the same as before.")

    chk = check_slot(cur, ps["section_id"], new_date, start, end,
                     faculty_id=ps["substitute_faculty_id"] or ps["faculty_id"], origin="moved")
    if not chk["ok"]:
        raise ExcError(f"Classes are not allowed on {new_date:%d %b %Y} ({chk['reason']}). "
                       "Add a 'Special Working Day' in the Academic Calendar first.")
    cur.execute(
        "SELECT id FROM planned_sessions WHERE section_id = %s AND planned_date = %s "
        "AND status = 'planned' AND start_time < %s AND end_time > %s AND id <> %s LIMIT 1",
        (ps["section_id"], new_date, end, start, ps["id"]))
    if cur.fetchone():
        raise ExcError("This section already has a class at that time.")

    cur.execute(
        "INSERT INTO planned_sessions "
        " (academic_period_id, timetable_id, section_id, elective_group_id, subject_id, "
        "  faculty_id, substitute_faculty_id, planned_date, start_time, end_time, room, "
        "  component, origin, status) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'moved','planned')",
        (ps["academic_period_id"], ps["timetable_id"], ps["section_id"],
         ps["elective_group_id"], ps["subject_id"], ps["faculty_id"],
         ps["substitute_faculty_id"], new_date, start, end, ps["room"], ps["component"]))
    new_id = cur.lastrowid
    exc_id = _insert_exc(cur, ps["id"], "move", reason, new_date=new_date,
                         new_start=start, new_end=end, new_ps_id=new_id)
    cur.execute("UPDATE planned_sessions SET status = 'moved' WHERE id = %s", (ps["id"],))
    cur.execute("UPDATE sessions SET status = 'cancelled', dismiss_reason = %s "
                "WHERE planned_session_id = %s AND status = 'scheduled'",
                (f"EXC#{exc_id}: Moved to {new_date:%d %b %Y}", ps["id"]))
    _create_session(cur, new_id, "makeup", "Make-up class")
    return exc_id


def _do_extra(cur, section_id, subject_id, faculty_id, d, start, end, room, component, reason):
    try:
        period = period_for_section(cur, section_id)
    except ValueError as exc:
        raise ExcError(f"Cannot add a class: {exc}")
    if d is None or start is None or end is None:
        raise ExcError("Date, start time and end time are required.")
    if start >= end:
        raise ExcError("End time must be after start time.")
    cur.execute(
        "SELECT id FROM planned_sessions WHERE section_id = %s AND planned_date = %s "
        "AND status = 'planned' AND start_time < %s AND end_time > %s LIMIT 1",
        (section_id, d, end, start))
    if cur.fetchone():
        raise ExcError("This section already has a class at that time.")
    chk = check_slot(cur, section_id, d, start, end, faculty_id=faculty_id, origin="extra")
    if not chk["ok"]:
        raise ExcError(f"An extra class is not allowed on {d:%d %b %Y}: {chk['reason']}.")
    cur.execute(
        "INSERT INTO planned_sessions "
        " (academic_period_id, timetable_id, section_id, subject_id, faculty_id, planned_date, "
        "  start_time, end_time, room, component, origin, status) "
        "VALUES (%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,'extra','planned')",
        (period["id"], section_id, subject_id, faculty_id, d,
         start, end, (room or None), component))
    ps_id = cur.lastrowid
    exc_id = _insert_exc(cur, ps_id, "extra", reason, new_date=d, new_start=start,
                         new_end=end, new_faculty_id=faculty_id, new_room=room or None)
    _create_session(cur, ps_id, "regular", "Extra class")
    return exc_id


def _do_undo(cur, exc):
    t, ps_id = exc["exception_type"], exc["planned_session_id"]
    cur.execute("SELECT * FROM planned_sessions WHERE id = %s", (ps_id,))
    ps = cur.fetchone()

    if t == "extra":
        sessions = _linked(cur, ps_id)
        if any(s["status"] in HELD for s in sessions):
            raise ExcError("The extra class was already taken. It cannot be undone.")
        _delete_sessions(cur, [s["id"] for s in sessions])
        cur.execute("DELETE FROM planned_sessions WHERE id = %s", (ps_id,))   # row cascades
        return

    if t == "substitute":
        cur.execute("UPDATE planned_sessions SET substitute_faculty_id = NULL WHERE id = %s", (ps_id,))
        cur.execute("UPDATE sessions SET substitute_faculty_id = NULL "
                    "WHERE planned_session_id = %s AND status IN ('scheduled','active')", (ps_id,))
    elif t == "room_change":
        cur.execute("SELECT room FROM timetable WHERE id = %s", (ps["timetable_id"],))
        tt = cur.fetchone()
        old = tt["room"] if tt else None
        cur.execute("UPDATE planned_sessions SET room = %s WHERE id = %s", (old, ps_id))
        cur.execute("UPDATE sessions SET room = %s "
                    "WHERE planned_session_id = %s AND status IN ('scheduled','active')", (old, ps_id))
    elif t == "move":
        new_id = exc["new_planned_session_id"]
        if new_id:
            sessions = _linked(cur, new_id)
            if any(s["status"] in HELD for s in sessions):
                raise ExcError("The moved class was already taken. It cannot be undone.")
            _delete_sessions(cur, [s["id"] for s in sessions])
            cur.execute("DELETE FROM planned_sessions WHERE id = %s", (new_id,))
        cur.execute("UPDATE planned_sessions SET status = 'planned' WHERE id = %s", (ps_id,))
        cur.execute("UPDATE sessions SET status = 'scheduled', dismiss_reason = NULL "
                    "WHERE status = 'cancelled' AND dismiss_reason LIKE %s",
                    (f"EXC#{exc['id']}:%",))
    elif t == "cancel":
        cur.execute("UPDATE planned_sessions SET status = 'planned' WHERE id = %s", (ps_id,))
        cur.execute("UPDATE sessions SET status = 'scheduled', dismiss_reason = NULL "
                    "WHERE status = 'cancelled' AND dismiss_reason LIKE %s",
                    (f"EXC#{exc['id']}:%",))

    cur.execute("UPDATE session_exceptions SET is_active = 0 WHERE id = %s", (exc["id"],))

    if t in ("cancel", "move") and ps:
        # The calendar may still block that date. Recompute and re-apply it.
        rebuild_plan(cur, ps["academic_period_id"], from_date=ps["planned_date"],
                     to_date=ps["planned_date"], section_id=ps["section_id"])
        cur.execute("SELECT status, block_event_id FROM planned_sessions WHERE id = %s", (ps_id,))
        now = cur.fetchone()
        if now and now["status"] == "cancelled" and now["block_event_id"]:
            cur.execute("UPDATE sessions SET status = 'cancelled', dismiss_reason = %s "
                        "WHERE planned_session_id = %s AND status = 'scheduled'",
                        (f"CAL#{now['block_event_id']}: calendar event", ps_id))


# ------------------------------------------------------------------- routes
@sess_exc_bp.route("/")
@admin_required
def index():
    conn = get_db()
    cur = conn.cursor(dictionary=True, buffered=True)

    cur.execute("SELECT id, name, academic_year, sem_number, is_active FROM academic_periods "
                "WHERE is_archived = 0 ORDER BY is_active DESC, start_date DESC")
    periods = cur.fetchall()
    wanted = request.args.get("period_id", type=int)
    selected = next((p for p in periods if p["id"] == wanted), periods[0] if periods else None)

    today = date.today()
    d_from = _parse_date(request.args.get("date_from")) or today
    d_to = _parse_date(request.args.get("date_to")) or (d_from + timedelta(days=13))
    section_id = request.args.get("section_id", type=int)
    faculty_id = request.args.get("faculty_id", type=int)

    rows, recent, sections, combos = [], [], [], []
    if selected:
        sql = (
            "SELECT ps.id, ps.planned_date, ps.start_time, ps.end_time, ps.room, ps.component, "
            "  ps.origin, ps.status, ps.block_event_id, ps.faculty_id, ps.substitute_faculty_id, "
            "  sub.code AS subject_code, sub.name AS subject_name, "
            "  sec.section_label, d.code AS dept_code, "
            "  uf.full_name AS faculty_name, us.full_name AS sub_name, "
            "  (SELECT s.status FROM sessions s WHERE s.planned_session_id = ps.id "
            "     ORDER BY s.id DESC LIMIT 1) AS session_status "
            "FROM planned_sessions ps "
            "JOIN sections sec ON sec.id = ps.section_id "
            "JOIN departments d ON d.id = sec.department_id "
            "LEFT JOIN subjects sub ON sub.id = ps.subject_id "
            "LEFT JOIN faculty f  ON f.id  = ps.faculty_id "
            "LEFT JOIN users  uf ON uf.id = f.user_id "
            "LEFT JOIN faculty fs ON fs.id = ps.substitute_faculty_id "
            "LEFT JOIN users  us ON us.id = fs.user_id "
            "WHERE ps.academic_period_id = %s AND ps.planned_date BETWEEN %s AND %s"
        )
        params = [selected["id"], d_from, d_to]
        if section_id:
            sql += " AND ps.section_id = %s"
            params.append(section_id)
        if faculty_id:
            sql += " AND (ps.faculty_id = %s OR ps.substitute_faculty_id = %s)"
            params += [faculty_id, faculty_id]
        cur.execute(sql + " ORDER BY ps.planned_date, ps.start_time, d.code, sec.section_label "
                          "LIMIT 500", params)
        rows = cur.fetchall()
        for r in rows:
            r["time_text"] = f"{_fmt_time(r['start_time'])} - {_fmt_time(r['end_time'])}"

        cur.execute(
            "SELECT e.id, e.exception_type, e.reason, e.created_at, e.new_date, e.new_room, "
            "  ps.planned_date, ps.start_time, sub.code AS subject_code, "
            "  sec.section_label, d.code AS dept_code, "
            "  ub.full_name AS by_name, un.full_name AS new_faculty_name "
            "FROM session_exceptions e "
            "JOIN planned_sessions ps ON ps.id = e.planned_session_id "
            "JOIN sections sec ON sec.id = ps.section_id "
            "JOIN departments d ON d.id = sec.department_id "
            "LEFT JOIN subjects sub ON sub.id = ps.subject_id "
            "LEFT JOIN users ub ON ub.id = e.created_by "
            "LEFT JOIN faculty fn ON fn.id = e.new_faculty_id "
            "LEFT JOIN users un ON un.id = fn.user_id "
            "WHERE e.is_active = 1 AND ps.academic_period_id = %s "
            "ORDER BY e.id DESC LIMIT 30", (selected["id"],))
        recent = cur.fetchall()
        for r in recent:
            r["time_text"] = _fmt_time(r["start_time"])

        cur.execute("SELECT sec.id, sec.section_label, d.code AS dept_code FROM sections sec "
                    "JOIN departments d ON d.id = sec.department_id "
                    "WHERE sec.academic_period_id = %s ORDER BY d.code, sec.section_label",
                    (selected["id"],))
        sections = cur.fetchall()
        cur.execute(
            "SELECT ss.section_id, ss.subject_id, ss.faculty_id, sec.section_label, "
            "  d.code AS dept_code, sub.code, sub.name "
            "FROM section_subjects ss "
            "JOIN sections sec ON sec.id = ss.section_id "
            "JOIN departments d ON d.id = sec.department_id "
            "JOIN subjects sub ON sub.id = ss.subject_id "
            "WHERE ss.academic_period_id = %s AND ss.is_elective = 0 "
            "ORDER BY d.code, sec.section_label, sub.code", (selected["id"],))
        combos = cur.fetchall()

    cur.execute("SELECT f.id, f.faculty_code, u.full_name FROM faculty f "
                "LEFT JOIN users u ON u.id = f.user_id ORDER BY u.full_name")
    faculty = cur.fetchall()

    return render_template(
        "admin/exceptions.html",
        periods=periods, selected=selected, rows=rows, recent=recent,
        sections=sections, combos=combos, faculty=faculty,
        f={"date_from": d_from.isoformat(), "date_to": d_to.isoformat(),
           "section_id": section_id, "faculty_id": faculty_id},
    )


@sess_exc_bp.route("/apply", methods=["POST"])
@admin_required
def apply_exception():
    f = request.form
    back = _back(f)
    ps_id = f.get("planned_session_id", type=int)
    action = f.get("action", "")
    reason = (f.get("reason") or "").strip() or None

    new_start, new_end = _parse_time(f.get("new_start")), _parse_time(f.get("new_end"))
    if new_start is False or new_end is False:
        flash("Time must look like 14:30.", "danger")
        return redirect(back)

    conn = get_db()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        cur.execute("SELECT * FROM planned_sessions WHERE id = %s FOR UPDATE", (ps_id,))
        ps = cur.fetchone()
        if not ps:
            raise ExcError("Planned class not found.")

        if action == "cancel":
            exc_id = _do_cancel(cur, ps, reason)
            msg = "Class cancelled."
        elif action == "substitute":
            exc_id = _do_substitute(cur, ps, f.get("new_faculty_id", type=int), reason)
            msg = "Substitute faculty set."
        elif action == "room_change":
            exc_id = _do_room(cur, ps, f.get("new_room"), reason)
            msg = "Room changed."
        elif action == "move":
            exc_id = _do_move(cur, ps, _parse_date(f.get("new_date")), new_start, new_end, reason)
            msg = "Class moved. A make-up session was created."
        else:
            raise ExcError("Choose an action.")

        conn.commit()
        _audit("session_exception_" + action, exc_id, {"planned_session_id": ps_id, "reason": reason})
        flash(msg, "success")
    except ExcError as e:
        conn.rollback()
        flash(str(e), "warning")
    except Exception as e:
        conn.rollback()
        logger.exception("apply exception failed")
        flash(f"Error: {e}", "danger")
    return redirect(back)


@sess_exc_bp.route("/extra", methods=["POST"])
@admin_required
def add_extra():
    f = request.form
    back = _back(f)
    combo = (f.get("combo") or "").split(":")
    start, end = _parse_time(f.get("start_time")), _parse_time(f.get("end_time"))
    if len(combo) != 2 or not all(x.isdigit() for x in combo):
        flash("Choose a section and subject.", "danger")
        return redirect(back)
    if start is False or end is False:
        flash("Time must look like 14:30.", "danger")
        return redirect(back)
    component = f.get("component") if f.get("component") in ("theory", "lab") else "theory"
    faculty_id = f.get("faculty_id", type=int)

    conn = get_db()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        section_id, subject_id = int(combo[0]), int(combo[1])
        if not faculty_id:
            cur.execute("SELECT faculty_id FROM section_subjects WHERE section_id = %s "
                        "AND subject_id = %s LIMIT 1", (section_id, subject_id))
            row = cur.fetchone()
            faculty_id = row["faculty_id"] if row else None
        if not faculty_id:
            raise ExcError("Choose the faculty for this class.")
        exc_id = _do_extra(cur, section_id, subject_id, faculty_id,
                           _parse_date(f.get("class_date")), start, end,
                           (f.get("room") or "").strip(), component,
                           (f.get("reason") or "").strip() or None)
        conn.commit()
        _audit("session_exception_extra", exc_id, {"section_id": section_id, "subject_id": subject_id})
        flash("Extra class added.", "success")
    except ExcError as e:
        conn.rollback()
        flash(str(e), "warning")
    except Exception as e:
        conn.rollback()
        logger.exception("add extra failed")
        flash(f"Error: {e}", "danger")
    return redirect(back)


@sess_exc_bp.route("/<int:exc_id>/undo", methods=["POST"])
@admin_required
def undo(exc_id):
    back = _back(request.form)
    conn = get_db()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        cur.execute("SELECT * FROM session_exceptions WHERE id = %s AND is_active = 1 FOR UPDATE",
                    (exc_id,))
        exc = cur.fetchone()
        if not exc:
            raise ExcError("This change was already undone.")
        _do_undo(cur, exc)
        conn.commit()
        _audit("session_exception_undo", exc_id, {"type": exc["exception_type"]})
        flash("Change undone.", "success")
    except ExcError as e:
        conn.rollback()
        flash(str(e), "warning")
    except Exception as e:
        conn.rollback()
        logger.exception("undo failed")
        flash(f"Error: {e}", "danger")
    return redirect(back)