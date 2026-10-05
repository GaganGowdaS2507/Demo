"""
services/sync_service.py - keeps derived data in step when the INPUTS change.

  period created / dates edited   -> academic_calendars row, calendar_days, planned_sessions
  batch promoted (sections move)  -> old + new period plans
  anything else (manual / nightly)-> rebuild_everything()

All functions take a DICTIONARY cursor (buffered). The caller commits.
Command line:   python -m services.sync_service [--check]
"""
import logging
import sys
from datetime import date

from services.calendar_service import rebuild_calendar_days
from services.timetable_engine import rebuild_plan

logger = logging.getLogger(__name__)


def ensure_academic_calendar(cur, period_id):
    cur.execute("INSERT IGNORE INTO academic_calendars (academic_period_id, title) "
                "SELECT id, name FROM academic_periods WHERE id = %s", (period_id,))


def prune_plan_outside_period(cur, period_id):
    """Delete FUTURE timetable-planned rows that fell outside the (new) period dates and have
    no real session or active exception. Past rows are history and are never touched."""
    cur.execute(
        "DELETE ps FROM planned_sessions ps "
        "JOIN academic_periods p ON p.id = ps.academic_period_id "
        "WHERE ps.academic_period_id = %s AND ps.origin = 'timetable' "
        "  AND (ps.planned_date < p.start_date OR ps.planned_date > p.end_date) "
        "  AND ps.planned_date >= CURDATE() "
        "  AND NOT EXISTS (SELECT 1 FROM sessions s WHERE s.planned_session_id = ps.id) "
        "  AND NOT EXISTS (SELECT 1 FROM session_exceptions e "
        "                  WHERE e.planned_session_id = ps.id AND e.is_active = 1)",
        (period_id,))
    return cur.rowcount


def after_period_saved(cur, period_id):
    """Call after INSERT / UPDATE of an academic period. Returns {'summary', 'warnings', ...}."""
    ensure_academic_calendar(cur, period_id)
    days = rebuild_calendar_days(cur, period_id)
    pruned = prune_plan_outside_period(cur, period_id)
    plan = rebuild_plan(cur, period_id)

    warnings = []
    cur.execute(
        "SELECT COUNT(*) AS c FROM calendar_events e JOIN academic_periods p ON p.id = e.academic_period_id "
        "WHERE e.academic_period_id = %s AND (e.end_date < p.start_date OR e.start_date > p.end_date)",
        (period_id,))
    stray = cur.fetchone()["c"]
    if stray:
        warnings.append(f"{stray} calendar event(s) now lie completely outside this cycle's dates. "
                        "Review them in the Academic Calendar.")
    cur.execute(
        "SELECT COUNT(*) AS c FROM sessions s JOIN sections sec ON sec.id = s.section_id "
        "JOIN academic_periods p ON p.id = sec.academic_period_id "
        "WHERE p.id = %s AND (s.session_date < p.start_date OR s.session_date > p.end_date)",
        (period_id,))
    held = cur.fetchone()["c"]
    if held:
        warnings.append(f"{held} existing session(s) are dated outside the new cycle dates. "
                        "They were kept (attendance history is never deleted).")
    if plan.get("skipped_sections"):
        warnings.append("Planning skipped inconsistent section(s): "
                        + ", ".join(str(s) for s in plan["skipped_sections"]))
    return {"days": days, "pruned": pruned, "plan": plan, "warnings": warnings,
            "summary": (f"Calendar days: {days}. Planned classes: +{plan['inserted']} "
                        f"~{plan['updated']} -{plan['removed'] + pruned}.")}


def after_batch_moved(cur, old_period_ids, new_period_ids):
    """Sections moved to another period: drop their old plan, build the new one."""
    out = {}
    for pid in sorted({p for p in list(old_period_ids) + list(new_period_ids) if p}):
        out[pid] = rebuild_plan(cur, pid)
    return out


def rebuild_everything(cur, today=None):
    """Safety net (nightly or by hand): every running, un-archived period."""
    today = today or date.today()
    cur.execute("SELECT id FROM academic_periods WHERE is_archived = 0 AND end_date >= %s ORDER BY id",
                (today,))
    report = {}
    for r in cur.fetchall():
        report[r["id"]] = after_period_saved(cur, r["id"])
    return report


def _main():
    import mysql.connector
    from config import Config
    check = "--check" in sys.argv
    conn = mysql.connector.connect(host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
                                   password=Config.DB_PASS, database=Config.DB_NAME, autocommit=False)
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        for pid, res in rebuild_everything(cur).items():
            print(f"period {pid}: {res['summary']}")
            for w in res["warnings"]:
                print("   WARNING:", w)
        if check:
            conn.rollback()
            print("\nCHECK ONLY - rolled back.")
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