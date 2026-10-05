"""
services/timetable_engine.py  -  the PLANNER.

Builds planned_sessions (what SHOULD happen) from:
    timetable rules  +  academic calendar  (+ exceptions, which it never overwrites)

It does NOT create real sessions or attendance.

Use from code (caller commits):
    from services.timetable_engine import rebuild_plan, link_sessions
    rebuild_plan(cur, period_id)            # whole semester
    rebuild_plan(cur, period_id, from_date=d1, to_date=d2, section_id=5)
    link_sessions(cur, period_id)

Use from the command line (from the project root):
    python -m services.timetable_engine --check              # try it, nothing is saved
    python -m services.timetable_engine                      # active period, saves
    python -m services.timetable_engine --period 5           # a specific period
"""
import logging
import sys
from datetime import date, datetime, timedelta
from services.roster_service import get_roster
import time
from services.calendar_service import get_day_info, check_slot
from services.semester_service import section_problems


logger = logging.getLogger(__name__)

_LAB_TYPES = ("Lab", "Lab-Merged")


def _to_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _valid_on(row, d):
    if row["effective_from"] is not None and row["effective_from"] > d:
        return False
    if row["effective_to"] is not None and row["effective_to"] < d:
        return False
    return True


# ------------------------------------------------------------------ planner
def rebuild_plan(cur, period_id, from_date=None, to_date=None,
                 section_id=None, today=None):
    """Create / update / remove planned_sessions. Returns a dict of counts.
    cur must be a DICTIONARY cursor. The caller commits."""
    today = today or date.today()

    cur.execute("SELECT id, start_date, end_date FROM academic_periods WHERE id = %s",
                (period_id,))
    period = cur.fetchone()
    if not period:
        raise ValueError(f"Academic period {period_id} not found")

    start = max(_to_date(from_date), period["start_date"]) if from_date else period["start_date"]
    end = min(_to_date(to_date), period["end_date"]) if to_date else period["end_date"]
    result = {"inserted": 0, "updated": 0, "removed": 0,
              "blocked_by_event": 0, "locked_skipped": 0}
    if start > end:
        return result

    # 1) timetable rules
    sql = (
        "SELECT t.id, t.section_id, t.subject_id, t.elective_group_id, t.faculty_id, "
        "       t.day_of_week, t.start_time, t.end_time, t.room, t.slot_type, "
        "       t.effective_from, t.effective_to "
        "FROM timetable t "
        "JOIN sections sec ON sec.id = t.section_id "
        "WHERE sec.academic_period_id = %s AND t.is_active = 1 "
        "  AND t.academic_period_id = sec.academic_period_id "
        "  AND t.slot_type NOT IN ('Interval', 'Lunch') AND t.subject_id IS NOT NULL"
    )
    params = [period_id]
    if section_id:
        sql += " AND t.section_id = %s"
        params.append(section_id)
    cur.execute(sql + " ORDER BY t.id", params)
    rules = cur.fetchall()

    
    # 2b) never plan from a section whose batch / semester / period disagree. Its old rows
    #     are left exactly as they are (not deleted) until an admin fixes the section.
    bad_sections = {sid: section_problems(cur, sid) for sid in {r["section_id"] for r in rules}}
    bad_sections = {sid: p for sid, p in bad_sections.items() if p}
    skipped_rule_ids = {r["id"] for r in rules if r["section_id"] in bad_sections}
    rules = [r for r in rules if r["section_id"] not in bad_sections]
    result["skipped_sections"] = bad_sections
    if bad_sections:
        logger.warning("rebuild_plan skipped inconsistent sections: %s", bad_sections)
    # 2) planned rows that already exist in this range
    sql = (
        "SELECT ps.id, ps.timetable_id, ps.planned_date, ps.subject_id, ps.faculty_id, "
        "       ps.elective_group_id, ps.start_time, ps.end_time, ps.room, ps.component, "
        "       ps.status, ps.block_event_id, "
        " (SELECT COUNT(*) FROM sessions s WHERE s.planned_session_id = ps.id "
        "    AND s.status IN ('completed','active','dismissed')) AS held, "
        " (SELECT COUNT(*) FROM sessions s2 WHERE s2.planned_session_id = ps.id) AS linked, "
        " (SELECT COUNT(*) FROM session_exceptions e WHERE e.planned_session_id = ps.id "
        "    AND e.is_active = 1) AS exc "
        "FROM planned_sessions ps "
        "WHERE ps.academic_period_id = %s AND ps.origin = 'timetable' "
        "  AND ps.timetable_id IS NOT NULL AND ps.planned_date BETWEEN %s AND %s"
    )
    params = [period_id, start, end]
    if section_id:
        sql += " AND ps.section_id = %s"
        params.append(section_id)
    cur.execute(sql, params)
    existing = {(r["timetable_id"], r["planned_date"]): r for r in cur.fetchall()}

    # 3) what SHOULD exist: rule x date, filtered by the calendar
    desired = {}
    cache = {}
    d = start
    while d <= end:
        seen_groups = set()                       # one planned row per elective group + time
        for r in rules:
            sec = r["section_id"]
            info = cache.get((sec, d))
            if info is None:
                info = get_day_info(cur, sec, d)
                cache[(sec, d)] = info
            if r["day_of_week"] != info["weekday"] or not _valid_on(r, d):
                continue
            chk = check_slot(cur, sec, d, r["start_time"], r["end_time"], cache,
                             faculty_id=r["faculty_id"])
            if not chk["ok"] and chk["event_id"] is None:
                continue                          # Sunday / outside semester: no row
            gid = r["elective_group_id"]
            if gid:
                key = (gid, r["start_time"])
                if key in seen_groups:
                    continue
                seen_groups.add(key)
            desired[(r["id"], d)] = {
                "section_id": sec, "group_id": gid, "subject_id": r["subject_id"],
                "faculty_id": r["faculty_id"], "start": r["start_time"], "end": r["end_time"],
                "room": r["room"],
                "component": "lab" if r["slot_type"] in _LAB_TYPES else "theory",
                "status": "planned" if chk["ok"] else "cancelled",
                "block": None if chk["ok"] else chk["event_id"],
            }
        d += timedelta(days=1)

    # 4) compare and write
    to_insert = []
    for key, v in desired.items():
        ex = existing.get(key)
        if v["status"] == "cancelled":
            result["blocked_by_event"] += 1
        if ex is None:
            to_insert.append((
                period_id, key[0], v["section_id"], v["group_id"], v["subject_id"],
                v["faculty_id"], key[1], v["start"], v["end"], v["room"],
                v["component"], v["status"], v["block"]))
            continue
        if ex["held"] or ex["exc"]:
            result["locked_skipped"] += 1
            continue

        sets, vals = [], []
        if ex["status"] != v["status"] or ex["block_event_id"] != v["block"]:
            sets += ["status = %s", "block_event_id = %s"]
            vals += [v["status"], v["block"]]
        if key[1] >= today:                       # past rows keep their old details
            for col, new in (("subject_id", v["subject_id"]), ("faculty_id", v["faculty_id"]),
                             ("elective_group_id", v["group_id"]), ("start_time", v["start"]),
                             ("end_time", v["end"]), ("room", v["room"]),
                             ("component", v["component"])):
                if ex[col] != new:
                    sets.append(f"{col} = %s")
                    vals.append(new)
        if sets:
            cur.execute(f"UPDATE planned_sessions SET {', '.join(sets)} WHERE id = %s",
                        vals + [ex["id"]])
            result["updated"] += 1

    if to_insert:
        cur.executemany(
            "INSERT IGNORE INTO planned_sessions "
            " (academic_period_id, timetable_id, section_id, elective_group_id, subject_id, "
            "  faculty_id, planned_date, start_time, end_time, room, component, "
            "  origin, status, block_event_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'timetable',%s,%s)",
            to_insert)
        result["inserted"] = len(to_insert)

    # 5) remove FUTURE rows that no longer belong (slot deleted, day changed...)
    for key, ex in existing.items():
        if key in desired or ex["held"] or ex["exc"] or ex["linked"] or key[0] in skipped_rule_ids:
            continue
        if key[1] >= today:
            cur.execute("DELETE FROM planned_sessions WHERE id = %s", (ex["id"],))
            result["removed"] += 1

        # 6) extra / moved classes also follow the calendar: a holiday added later cancels them,
    #    a holiday removed brings them back. Classes cancelled by an admin exception
    #    (block_event_id IS NULL) are never touched. Only date-wide EVENT blocks are handled here.
    sql = (
        "SELECT ps.id, ps.section_id, ps.faculty_id, ps.planned_date, ps.start_time, "
        "       ps.end_time, ps.status, ps.block_event_id, "
        " (SELECT COUNT(*) FROM sessions s WHERE s.planned_session_id = ps.id "
        "    AND s.status IN ('active','completed','dismissed')) AS held "
        "FROM planned_sessions ps "
        "WHERE ps.academic_period_id = %s AND ps.origin IN ('extra', 'moved') "
        "  AND ps.status IN ('planned', 'cancelled') AND ps.planned_date BETWEEN %s AND %s"
    )
    params = [period_id, start, end]
    if section_id:
        sql += " AND ps.section_id = %s"
        params.append(section_id)
    cur.execute(sql, params)
    for ps in cur.fetchall():
        if ps["held"]:
            continue
        chk = check_slot(cur, ps["section_id"], ps["planned_date"], ps["start_time"],
                         ps["end_time"], cache, faculty_id=ps["faculty_id"], origin="extra")
        if ps["status"] == "planned" and not chk["ok"] and chk["event_id"] is not None:
            cur.execute("UPDATE planned_sessions SET status = 'cancelled', block_event_id = %s "
                        "WHERE id = %s", (chk["event_id"], ps["id"]))
            cur.execute("UPDATE sessions SET status = 'cancelled', dismiss_reason = %s "
                        "WHERE planned_session_id = %s AND status = 'scheduled'",
                        (f"CAL#{chk['event_id']}: {chk['reason']}"[:255], ps["id"]))
            result["blocked_by_event"] += 1
        elif ps["status"] == "cancelled" and ps["block_event_id"] and chk["ok"]:
            cur.execute("UPDATE planned_sessions SET status = 'planned', block_event_id = NULL "
                        "WHERE id = %s", (ps["id"],))
            cur.execute("UPDATE sessions SET status = 'scheduled', dismiss_reason = NULL "
                        "WHERE planned_session_id = %s AND status = 'cancelled' "
                        "AND dismiss_reason LIKE 'CAL#%%'", (ps["id"],))
            result["updated"] += 1

    return result


# -------------------------------------------------------- link real sessions
def link_sessions(cur, period_id):
    """Point existing real sessions at their planned row. Returns (linked, still_unlinked)."""
    cur.execute(
        "UPDATE sessions s "
        "JOIN planned_sessions ps ON ps.timetable_id = s.timetable_id "
        "   AND ps.planned_date = s.session_date AND ps.origin = 'timetable' "
        "SET s.planned_session_id = ps.id "
        "WHERE s.planned_session_id IS NULL AND ps.academic_period_id = %s",
        (period_id,))
    linked = cur.rowcount

    cur.execute(
        "SELECT COUNT(*) AS c FROM sessions s JOIN sections sec ON sec.id = s.section_id "
        "WHERE s.planned_session_id IS NULL AND s.source = 'timetable' "
        "  AND s.timetable_id IS NOT NULL AND sec.academic_period_id = %s",
        (period_id,))
    row = cur.fetchone()
    return linked, (row["c"] if isinstance(row, dict) else row[0])


def replan_section(cur, section_id, period_id=None, from_date=None):
    """Bring the plan of ONE section in step with the timetable, from today onward.
    The period is always the SECTION's own period (period_id is ignored, kept only so
    older calls still work). Runs inside a savepoint and never raises.
    Returns the counts dict, or None if it failed."""
    try:
        cur.execute("SAVEPOINT replan_section")
        cur.execute("SELECT academic_period_id FROM sections WHERE id = %s", (section_id,))
        row = cur.fetchone()
        if not row:
            return None
        return rebuild_plan(cur, row["academic_period_id"],
                            from_date=from_date or date.today(), section_id=section_id)
    except Exception as exc:
        logger.warning("replan_section failed: %s", exc)
        try:
            cur.execute("ROLLBACK TO SAVEPOINT replan_section")
        except Exception:
            pass
        return None

def drop_plan_for_slot(cur, timetable_id):
    """Call BEFORE hard-deleting a timetable slot. Removes its planned rows that no
    real session or active exception depends on (otherwise they would be orphaned)."""
    cur.execute(
        "DELETE FROM planned_sessions "
        "WHERE timetable_id = %s AND origin = 'timetable' "
        "  AND NOT EXISTS (SELECT 1 FROM sessions s "
        "                  WHERE s.planned_session_id = planned_sessions.id) "
        "  AND NOT EXISTS (SELECT 1 FROM session_exceptions e "
        "                  WHERE e.planned_session_id = planned_sessions.id AND e.is_active = 1)",
        (timetable_id,))
    return cur.rowcount


# ------------------------------------------------ THE ONLY SESSION CREATORS
def _seed_attendance(cur, session_id, section_ids, elective_group_id):
    """Everyone starts 'absent' (faculty forgot attendance -> class still counts)."""
    roster = get_roster(cur, section_ids, elective_group_id)
    if roster:
        cur.executemany(
            "INSERT IGNORE INTO attendance "
            " (session_id, student_id, usn, status, method, marked_at) "
            "VALUES (%s,%s,%s,'absent','system',NOW())",
            [(session_id, r["id"], r["usn"]) for r in roster])
    return roster


def open_session(cur, p, created_by=None):
    """PLANNED row -> real session (+ roster as 'absent'). p = a planned_sessions row (dict).
    Raises mysql IntegrityError if that planned row already has a session (caller may ignore).
    Returns (session_id, roster)."""
    origin = p["origin"]
    cur.execute(
        "INSERT INTO sessions "
        " (timetable_id, section_id, subject_id, elective_group_id, faculty_id, "
        "  substitute_faculty_id, session_date, start_time, end_time, room, "
        "  status, session_type, source, component, planned_session_id, title, "
        "  created_by, created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'scheduled',%s,%s,%s,%s,%s,%s,NOW())",
        (p["timetable_id"] if origin == "timetable" else None,
         p["section_id"], p["subject_id"], p["elective_group_id"], p["faculty_id"],
         p["substitute_faculty_id"], p["planned_date"], p["start_time"], p["end_time"],
         p["room"],
         "makeup" if origin == "moved" else "regular",
         "timetable" if origin == "timetable" else "manual",
         p["component"], p["id"],
         {"moved": "Make-up class", "extra": "Extra class"}.get(origin), created_by))
    sid = cur.lastrowid

    roster = _seed_attendance(cur, sid, [p["section_id"]], p["elective_group_id"])
    if roster and p["elective_group_id"]:     # let the members' home sections see the class
        ids = [r["id"] for r in roster]
        cur.execute(
            "SELECT DISTINCT section_id FROM students WHERE section_id IS NOT NULL "
            f"AND id IN ({','.join(['%s'] * len(ids))})", ids)
        extra = [r["section_id"] for r in cur.fetchall() if r["section_id"] != p["section_id"]]
        if extra:
            cur.executemany("INSERT IGNORE INTO session_sections (session_id, section_id) "
                            "VALUES (%s,%s)", [(sid, s) for s in extra])
    return sid, roster


def create_unplanned_session(cur, *, section_ids, subject_id, elective_group_id, faculty_id,
                             session_date, start_time, end_time, session_type, title, room,
                             camera_id, scope, created_by):
    """Admin / faculty one-off session (workshop, seminar, exam, institute-wide...).
    It has no planned row, so reports count it as 'extra / unplanned'.
    Returns (session_id, roster)."""
    section_ids = [int(s) for s in section_ids]
    cur.execute(
        "INSERT INTO sessions "
        " (section_id, subject_id, elective_group_id, faculty_id, session_date, start_time, "
        "  end_time, status, session_type, source, scope, title, room, camera_id, "
        "  created_by, created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,'scheduled',%s,'manual',%s,%s,%s,%s,%s,NOW())",
        (section_ids[0] if section_ids else None, subject_id, elective_group_id, faculty_id,
         session_date, start_time, end_time, session_type, scope, title, room, camera_id,
         created_by))
    sid = cur.lastrowid
    if section_ids:
        cur.executemany(
            "INSERT IGNORE INTO session_sections (session_id, section_id, added_by) "
            "VALUES (%s,%s,%s)", [(sid, s, created_by) for s in section_ids])
    roster = _seed_attendance(cur, sid, section_ids, elective_group_id)
    return sid, roster

# ------------------------------------------------ open today's real sessions
_PLAN_REFRESHED = {}        # (period_id, date) -> time of the last refresh
_REFRESH_EVERY = 300        # seconds


def open_sessions_for_date(cur, on_date=None, force_plan=False):
    """
    Open the REAL sessions for one day, from the PLAN (planned_sessions).
    The ONLY place that creates timetable sessions. Used by the daily job and
    by the admin dashboard.

      1. keeps today's plan fresh (holidays, events, cancellations, moves)
      2. links older sessions of today to their planned row (no duplicates)
      3. creates a session for every planned row that has none
         - roster = elective group members, or the section's students
         - everyone starts 'absent' (faculty forgot attendance -> class still counts)

    cur must be a DICTIONARY cursor (buffered). The caller commits.
    Returns {'created': n, 'linked': n, 'planned_today': n}.
    """
    # from mysql.connector import IntegrityError
    # from services.roster_service import get_roster
    from mysql.connector import IntegrityError

    d = _to_date(on_date) if on_date else date.today()
    out = {"created": 0, "linked": 0, "planned_today": 0}

    # 1) periods that are running today and have a timetable
    cur.execute(
        "SELECT DISTINCT sec.academic_period_id AS id "
        "FROM timetable t "
        "JOIN sections sec ON sec.id = t.section_id "
        "JOIN academic_periods ap ON ap.id = sec.academic_period_id "
        "WHERE t.is_active = 1 AND ap.is_archived = 0 "
        "  AND %s BETWEEN ap.start_date AND ap.end_date", (d,))
    period_ids = [r["id"] for r in cur.fetchall()]
    if not period_ids:
        return out
    marks = ",".join(["%s"] * len(period_ids))

    # 2) keep today's plan fresh (calendar / timetable edits already do this;
    #    this is a safety net, so it runs at most every 5 minutes per period)
    now = time.time()
    for pid in period_ids:
        key = (pid, d)
        if force_plan or now - _PLAN_REFRESHED.get(key, 0) > _REFRESH_EVERY:
            rebuild_plan(cur, pid, from_date=d, to_date=d)
            _PLAN_REFRESHED[key] = now

    # 3) link sessions that already exist for today
    cur.execute(
        "UPDATE sessions s JOIN planned_sessions ps "
        "  ON ps.timetable_id = s.timetable_id AND ps.planned_date = s.session_date "
        " AND ps.origin = 'timetable' "
        "SET s.planned_session_id = ps.id "
        f"WHERE s.planned_session_id IS NULL AND s.session_date = %s "
        f"  AND ps.academic_period_id IN ({marks})", [d] + period_ids)
    out["linked"] = cur.rowcount
    cur.execute(                                # sessions made by the old dashboard code
        "UPDATE sessions s JOIN planned_sessions ps "
        "  ON ps.section_id = s.section_id AND ps.subject_id = s.subject_id "
        " AND ps.planned_date = s.session_date AND ps.start_time = s.start_time "
        "SET s.planned_session_id = ps.id "
        f"WHERE s.planned_session_id IS NULL AND s.timetable_id IS NULL "
        f"  AND s.source = 'timetable' AND s.session_date = %s "
        f"  AND ps.academic_period_id IN ({marks})", [d] + period_ids)
    out["linked"] += cur.rowcount

    # 4) planned classes of today that still have no real session
    cur.execute(
        "SELECT ps.* FROM planned_sessions ps "
        f"WHERE ps.planned_date = %s AND ps.status = 'planned' "
        f"  AND ps.academic_period_id IN ({marks}) "
        "  AND NOT EXISTS (SELECT 1 FROM sessions s WHERE s.planned_session_id = ps.id) "
        "ORDER BY ps.start_time, ps.id", [d] + period_ids)
    todo = cur.fetchall()
    out["planned_today"] = len(todo)

    # for p in todo:
    #     origin = p["origin"]
    #     try:
    #         cur.execute(
    #             "INSERT INTO sessions "
    #             " (timetable_id, section_id, subject_id, elective_group_id, faculty_id, "
    #             "  substitute_faculty_id, session_date, start_time, end_time, room, "
    #             "  status, session_type, source, component, planned_session_id, title, created_at) "
    #             "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'scheduled',%s,%s,%s,%s,%s,NOW())",
    #             (p["timetable_id"] if origin == "timetable" else None,
    #              p["section_id"], p["subject_id"], p["elective_group_id"], p["faculty_id"],
    #              p["substitute_faculty_id"], p["planned_date"], p["start_time"], p["end_time"],
    #              p["room"],
    #              "makeup" if origin == "moved" else "regular",
    #              "timetable" if origin == "timetable" else "manual",
    #              p["component"], p["id"],
    #              {"moved": "Make-up class", "extra": "Extra class"}.get(origin)))
    #     except IntegrityError:
    #         continue                      # another worker already opened this class
    #     sid = cur.lastrowid

    #     roster = get_roster(cur, [p["section_id"]], p["elective_group_id"])
    #     if roster:
    #         cur.executemany(
    #             "INSERT IGNORE INTO attendance "
    #             " (session_id, student_id, usn, status, method, marked_at) "
    #             "VALUES (%s,%s,%s,'absent','system',NOW())",
    #             [(sid, r["id"], r["usn"]) for r in roster])

    #         if p["elective_group_id"]:    # let the members' home sections see the class
    #             ids = [r["id"] for r in roster]
    #             cur.execute(
    #                 "SELECT DISTINCT section_id FROM students WHERE section_id IS NOT NULL "
    #                 f"AND id IN ({','.join(['%s'] * len(ids))})", ids)
    #             extra = [r["section_id"] for r in cur.fetchall()
    #                      if r["section_id"] != p["section_id"]]
    #             if extra:
    #                 cur.executemany(
    #                     "INSERT IGNORE INTO session_sections (session_id, section_id) "
    #                     "VALUES (%s,%s)", [(sid, s) for s in extra])
    #     out["created"] += 1

    for p in todo:
        try:
            open_session(cur, p)
        except IntegrityError:
            continue                      # another worker already opened this class
        out["created"] += 1

    return out

# ------------------------------------------------------------ command line
def _main():
    import mysql.connector
    from config import Config

    check = "--check" in sys.argv
    wanted = None
    if "--period" in sys.argv:
        wanted = int(sys.argv[sys.argv.index("--period") + 1])

    conn = mysql.connector.connect(
        host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
        password=Config.DB_PASS, database=Config.DB_NAME, autocommit=False)
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        if wanted:
            period_ids = [wanted]
        else:
            cur.execute(
                "SELECT DISTINCT sec.academic_period_id AS id "
                "FROM timetable t JOIN sections sec ON sec.id = t.section_id "
                "WHERE t.is_active = 1 ORDER BY 1")
            period_ids = [r["id"] for r in cur.fetchall()]
        if not period_ids:
            print("No timetable slots found.")
            return

        print(f"MODE: {'CHECK (nothing is saved)' if check else 'APPLY'}   periods={period_ids}")
        for pid in period_ids:
            print(f"\n--- period_id={pid}")
            print("Plan   :", rebuild_plan(cur, pid))
            linked, left = link_sessions(cur, pid)
            print(f"Linked : {linked} real sessions now point to a planned session")
            print(f"Unlinked timetable sessions left: {left}")
        if check:
            conn.rollback()
            print("\nRolled back. Run again without --check to save.")
        else:
            conn.commit()
            print("\nSaved.")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    _main()