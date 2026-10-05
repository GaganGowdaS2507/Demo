# """
# services/calendar_service.py

# ONE place that answers: "Can normal teaching happen for this section on this date?"
# The planner, the daily generator and the dashboards must all ask this file.
# Nobody else should read calendar_events to decide this.

# All functions take a DICTIONARY cursor:  conn.cursor(dictionary=True)
# """
# import logging
# from datetime import date, datetime, time, timedelta

# logger = logging.getLogger(__name__)

# _tables_ready = False
# _warned_missing = False


# # ----------------------------------------------------------------- helpers
# def _calendar_tables_exist(cur):
#     """True when Step 1 migration has been applied. Cached once it is True."""
#     global _tables_ready, _warned_missing
#     if _tables_ready:
#         return True
#     cur.execute(
#         "SELECT COUNT(*) AS c FROM information_schema.tables "
#         "WHERE table_schema = DATABASE() "
#         "AND table_name IN ('calendar_events', 'calendar_event_types')"
#     )
#     row = cur.fetchone()
#     count = row["c"] if isinstance(row, dict) else row[0]
#     _tables_ready = (count == 2)
#     if not _tables_ready and not _warned_missing:
#         logger.warning("calendar tables not found. Run migrations/migrate_001_planning.py. "
#                        "Treating every day as a normal day.")
#         _warned_missing = True
#     return _tables_ready


# def _to_date(value):
#     if isinstance(value, datetime):
#         return value.date()
#     if isinstance(value, date):
#         return value
#     return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


# def _to_delta(value):
#     """MySQL TIME comes back as timedelta; also accept time or 'HH:MM[:SS]'."""
#     if value is None:
#         return None
#     if isinstance(value, timedelta):
#         return value
#     if isinstance(value, time):
#         return timedelta(hours=value.hour, minutes=value.minute, seconds=value.second)
#     parts = [int(p) for p in str(value).split(":")]
#     while len(parts) < 3:
#         parts.append(0)
#     return timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2])


# def _section_info(cur, section_id):
#     cur.execute(
#         "SELECT s.id, s.department_id, s.academic_period_id, "
#         "       ap.start_date, ap.end_date "
#         "FROM sections s "
#         "JOIN academic_periods ap ON ap.id = s.academic_period_id "
#         "WHERE s.id = %s",
#         (section_id,),
#     )
#     return cur.fetchone()


# def _load_events(cur, d, section):
#     """Every calendar event that applies to this section on date d."""
#     if not _calendar_tables_exist(cur):
#         return []
#     cur.execute(
#         "SELECT e.id, e.title, e.start_date, e.end_date, e.start_time, e.end_time, "
#         "       e.follow_weekday, t.code AS type_code, t.name AS type_name, "
#         "       COALESCE(e.effect_override, t.effect) AS effect "
#         "FROM calendar_events e "
#         "JOIN calendar_event_types t ON t.id = e.event_type_id "
#         "WHERE %s BETWEEN e.start_date AND e.end_date "
#         "  AND (e.academic_period_id IS NULL OR e.academic_period_id = %s) "
#         "  AND ( e.scope = 'college' "
#         "        OR (e.scope = 'department' AND e.department_id = %s) "
#         "        OR (e.scope = 'section'    AND e.section_id    = %s) ) "
#         "ORDER BY e.id",
#         (d, section["academic_period_id"], section["department_id"], section["id"]),
#     )
#     return cur.fetchall()


# # ------------------------------------------------------------ main functions
# def get_day_info(cur, section_id, on_date):
#     """
#     Returns a dict:
#       ok              True if normal teaching can happen for this section that day
#       weekday         which timetable weekday to use ('Monday'...). Normally the real
#                       weekday; a Special Working Day with follow_weekday changes it.
#       reason          short text when ok is False (holiday name, 'Sunday', ...)
#       block_event_id  id of the event that blocked the whole day (or None)
#       events          every event that applies that day
#       partial_blocks  half-day blocking events (have start_time / end_time)
#     """
#     d = _to_date(on_date)
#     actual = d.strftime("%A")
#     result = {
#         "ok": False, "weekday": actual, "reason": "",
#         "block_event_id": None, "events": [], "partial_blocks": [],
#     }

#     section = _section_info(cur, section_id)
#     if not section:
#         result["reason"] = "Section not found"
#         return result

#     events = _load_events(cur, d, section)
#     result["events"] = events

#     if not (section["start_date"] <= d <= section["end_date"]):
#         result["reason"] = "Outside the semester dates"
#         return result

#     allows = [e for e in events if e["effect"] == "allows_teaching"]
#     blocks = [e for e in events if e["effect"] == "blocks_teaching"]
#     full_blocks = [e for e in blocks if e["start_time"] is None or e["end_time"] is None]
#     part_blocks = [e for e in blocks if e not in full_blocks]

#     # A Special Working Day wins over a holiday and over Sunday.
#     if allows:
#         follow = next((e["follow_weekday"] for e in allows if e["follow_weekday"]), None)
#         result.update(ok=True, weekday=follow or actual, reason=allows[0]["title"],
#                       partial_blocks=part_blocks)
#         return result

#     if actual == "Sunday":
#         result["reason"] = "Sunday"
#         return result

#     if full_blocks:
#         result["reason"] = full_blocks[0]["title"]
#         result["block_event_id"] = full_blocks[0]["id"]
#         return result

#     result["ok"] = True
#     result["partial_blocks"] = part_blocks
#     return result


# def check_slot(cur, section_id, on_date, start_time, end_time, cache=None):
#     """
#     Can ONE timetable slot run on this date?
#     Returns {ok, weekday, reason, event_id}.
#       weekday = the timetable weekday that runs that day. The caller must only use
#                 slots whose day_of_week equals this value.
#     Pass cache={} (same dict for the whole run) to avoid repeated queries.
#     """
#     d = _to_date(on_date)
#     key = (section_id, d)
#     if cache is not None and key in cache:
#         info = cache[key]
#     else:
#         info = get_day_info(cur, section_id, d)
#         if cache is not None:
#             cache[key] = info

#     out = {"ok": info["ok"], "weekday": info["weekday"],
#            "reason": info["reason"], "event_id": info["block_event_id"]}
#     if not info["ok"]:
#         return out

#     s, e = _to_delta(start_time), _to_delta(end_time)
#     if s is None or e is None:
#         return out
#     for ev in info["partial_blocks"]:
#         es, ee = _to_delta(ev["start_time"]), _to_delta(ev["end_time"])
#         if s < ee and e > es:
#             out.update(ok=False, reason=ev["title"], event_id=ev["id"])
#             break
#     return out

"""
services/calendar_service.py

ONE place that answers calendar questions. Nobody else reads calendar_events.
All functions take a DICTIONARY cursor.

Teaching impact (calendar_event_types.teaching_impact / calendar_events.impact_override):
  BLOCK_ALL              no class of any kind (holiday, semester exam)
  BLOCK_REGULAR_CLASSES  timetable classes blocked; extra/makeup classes still allowed (IA, events)
  SECTION_SPECIFIC       same as BLOCK_REGULAR, but only for the event's department/section scope
  FACULTY_SPECIFIC       blocks regular classes of ONE faculty (event.faculty_id)
  ALLOW_TEACHING /
  SPECIAL_WORKING_DAY    teaching allowed even on Sunday/holiday (optional follow_weekday)
  INFO_ONLY              no effect on teaching

calendar_days = college-wide materialised day table (rebuilt by rebuild_calendar_days).
Rows with is_locked=1 (imported/manual explicit working-day records) override the
Sunday default. Section/dept/faculty events are always applied live on top.
"""
import logging
from datetime import date, datetime, time, timedelta

logger = logging.getLogger(__name__)

ALLOWING = {"ALLOW_TEACHING", "SPECIAL_WORKING_DAY"}
BLOCK_REGULAR = {"BLOCK_REGULAR_CLASSES", "SECTION_SPECIFIC", "FACULTY_SPECIFIC"}
BLOCKING = BLOCK_REGULAR | {"BLOCK_ALL"}
NON_WORKING_CODES = {"HOLIDAY", "NON_TEACHING_DAY"}      # college closed (not just no classes)

_IMPACT_SQL = (
    "COALESCE(e.impact_override, t.teaching_impact, "
    "CASE COALESCE(e.effect_override, t.effect) "
    " WHEN 'allows_teaching' THEN 'ALLOW_TEACHING' "
    " WHEN 'info_only' THEN 'INFO_ONLY' ELSE 'BLOCK_ALL' END)"
)

_tables_ready = False
_warned_missing = False


# ----------------------------------------------------------------- helpers
def _calendar_tables_exist(cur):
    """True when migrate_001 AND migrate_005 are applied. Cached once True."""
    global _tables_ready, _warned_missing
    if _tables_ready:
        return True
    cur.execute(
        "SELECT "
        " (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() "
        "   AND table_name IN ('calendar_events','calendar_event_types','calendar_days')) AS t, "
        " (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() "
        "   AND table_name = 'calendar_event_types' AND column_name = 'teaching_impact') AS c"
    )
    row = cur.fetchone()
    t, c = (row["t"], row["c"]) if isinstance(row, dict) else (row[0], row[1])
    _tables_ready = (t == 3 and c == 1)
    if not _tables_ready and not _warned_missing:
        logger.warning("calendar tables incomplete. Run migrations/migrate_005_calendar_layer.py. "
                       "Treating every day as a normal day.")
        _warned_missing = True
    return _tables_ready


def _to_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _to_delta(value):
    """MySQL TIME comes back as timedelta; also accept time or 'HH:MM[:SS]'."""
    if value is None:
        return None
    if isinstance(value, timedelta):
        return value
    if isinstance(value, time):
        return timedelta(hours=value.hour, minutes=value.minute, seconds=value.second)
    parts = [int(p) for p in str(value).split(":")]
    while len(parts) < 3:
        parts.append(0)
    return timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2])


def _section_info(cur, section_id):
    cur.execute(
        "SELECT s.id, s.department_id, s.academic_period_id, "
        "       ap.start_date, ap.end_date "
        "FROM sections s "
        "JOIN academic_periods ap ON ap.id = s.academic_period_id "
        "WHERE s.id = %s",
        (section_id,),
    )
    return cur.fetchone()


def _load_events(cur, d, section, faculty_id=None):
    """Every calendar event that applies to this section (and faculty) on date d."""
    if not _calendar_tables_exist(cur):
        return []
    cur.execute(
        "SELECT e.id, e.title, e.start_date, e.end_date, e.start_time, e.end_time, "
        "       e.follow_weekday, e.faculty_id, e.category, "
        "       t.code AS type_code, t.name AS type_name, "
        f"      {_IMPACT_SQL} AS impact "
        "FROM calendar_events e "
        "JOIN calendar_event_types t ON t.id = e.event_type_id "
        "WHERE %s BETWEEN e.start_date AND e.end_date "
        "  AND (e.academic_period_id IS NULL OR e.academic_period_id = %s) "
        "  AND ( e.scope = 'college' "
        "        OR (e.scope = 'department' AND e.department_id = %s) "
        "        OR (e.scope = 'section'    AND e.section_id    = %s) "
        "        OR (e.scope = 'faculty'    AND e.faculty_id    = %s) ) "
        "  AND (e.faculty_id IS NULL OR e.faculty_id = %s) "
        "ORDER BY e.id",
        (d, section["academic_period_id"], section["department_id"], section["id"],
         faculty_id, faculty_id),
    )
    return cur.fetchall()


def _locked_day(cur, period_id, d):
    if not _calendar_tables_exist(cur):
        return None
    cur.execute(
        "SELECT is_working, day_type, follow_weekday, label, event_id "
        "FROM calendar_days WHERE academic_period_id = %s AND calendar_date = %s "
        "AND is_locked = 1", (period_id, d))
    return cur.fetchone()


def _classify(events, d, locked=None):
    """
    Pure function. Same rules for live answers and for the calendar_days build.
    Returns dict: ok, weekday, reason, block_event_id, partial_blocks,
                  is_special, hard_block, regular_only_block, is_working
    """
    actual = d.strftime("%A")
    out = {"ok": False, "weekday": actual, "reason": "", "block_event_id": None,
           "partial_blocks": [], "is_special": False, "hard_block": False,
           "regular_only_block": False, "is_working": True, "label": None, "event_id": None}

    allows = [e for e in events if e["impact"] in ALLOWING]
    blocks = [e for e in events if e["impact"] in BLOCKING]
    full = [e for e in blocks if e["start_time"] is None or e["end_time"] is None]
    part = [e for e in blocks if e not in full]
    closed = [e for e in full if e["type_code"] in NON_WORKING_CODES]

    base_working = bool(locked["is_working"]) if locked else (actual != "Sunday")
    base_reason = (locked["label"] if locked and locked["label"] else
                   ("Sunday" if actual == "Sunday" else "Non-working day"))

    if allows:                                   # special working day beats everything
        follow = next((e["follow_weekday"] for e in allows if e["follow_weekday"]), None)
        out.update(ok=True, is_special=True, weekday=follow or actual,
                   reason=allows[0]["title"], partial_blocks=part,
                   label=allows[0]["title"], event_id=allows[0]["id"])
        return out

    if not base_working or closed:
        src = closed[0] if closed else None
        out.update(reason=src["title"] if src else base_reason, hard_block=True,
                   is_working=False, label=src["title"] if src else base_reason,
                   event_id=src["id"] if src else (locked["event_id"] if locked else None),
                   block_event_id=src["id"] if src else None)
        return out

    if full:
        out.update(reason=full[0]["title"], block_event_id=full[0]["id"],
                   label=full[0]["title"], event_id=full[0]["id"],
                   regular_only_block=all(e["impact"] != "BLOCK_ALL" for e in full))
        return out

    out.update(ok=True, partial_blocks=part)
    return out


# ------------------------------------------------------------ main functions
def get_day_info(cur, section_id, on_date, faculty_id=None):
    """
    Returns a dict:
      ok                 True if normal (timetable) teaching can happen that day
      weekday            timetable weekday to use (special working day may follow another)
      reason             text when ok is False
      block_event_id     event that blocked the whole day (or None)
      events             every event that applies (section + optional faculty)
      partial_blocks     part-day blocking events (have start_time/end_time)
      in_period          date is inside the section's academic period
      is_special         special working day
      hard_block         Sunday/closed/outside period: even extra classes are not allowed
      regular_only_block only BLOCK_REGULAR_CLASSES-type events: extra classes still allowed
    """
    d = _to_date(on_date)
    result = {"ok": False, "weekday": d.strftime("%A"), "reason": "", "block_event_id": None,
              "events": [], "partial_blocks": [], "in_period": False, "is_special": False,
              "hard_block": True, "regular_only_block": False}

    section = _section_info(cur, section_id)
    if not section:
        result["reason"] = "Section not found"
        return result

    events = _load_events(cur, d, section, faculty_id)
    result["events"] = events

    if not (section["start_date"] <= d <= section["end_date"]):
        result["reason"] = "Outside the semester dates"
        return result
    result["in_period"] = True

    locked = _locked_day(cur, section["academic_period_id"], d)
    c = _classify(events, d, locked)
    for k in ("ok", "weekday", "reason", "block_event_id", "partial_blocks",
              "is_special", "hard_block", "regular_only_block"):
        result[k] = c[k]
    return result


def check_slot(cur, section_id, on_date, start_time, end_time, cache=None,
               faculty_id=None, origin="timetable"):
    """
    Can ONE slot run on this date?   origin: 'timetable' | 'extra' | 'moved'
    Returns {ok, weekday, reason, event_id}.
    BLOCK_REGULAR_CLASSES-type events block only origin='timetable'; extra/moved
    classes may still run. BLOCK_ALL, holidays, Sundays block everything.
    """
    d = _to_date(on_date)
    key = (section_id, d) if faculty_id is None else (section_id, d, faculty_id)
    if cache is not None and key in cache:
        info = cache[key]
    else:
        info = get_day_info(cur, section_id, d, faculty_id)
        if cache is not None:
            cache[key] = info

    out = {"ok": info["ok"], "weekday": info["weekday"],
           "reason": info["reason"], "event_id": info["block_event_id"]}

    if not info["ok"]:
        extra_ok = (origin != "timetable" and info.get("regular_only_block")
                    and not info.get("hard_block"))
        if not extra_ok:
            return out
        out.update(ok=True, reason="", event_id=None)

    s, e = _to_delta(start_time), _to_delta(end_time)
    if s is None or e is None:
        return out
    for ev in info["partial_blocks"]:
        if origin != "timetable" and ev["impact"] != "BLOCK_ALL":
            continue
        es, ee = _to_delta(ev["start_time"]), _to_delta(ev["end_time"])
        if s < ee and e > es:
            out.update(ok=False, reason=ev["title"], event_id=ev["id"])
            break
    return out


# ------------------------------------------------- calendar_days (materialised)
def rebuild_calendar_days(cur, period_id, from_date=None, to_date=None):
    """
    Recompute college-wide calendar_days for one period (optionally a date range).
    Locked rows are never overwritten. Rows outside the period are removed (unless locked).
    Returns number of days written.
    """
    if not _calendar_tables_exist(cur):
        return 0
    cur.execute("SELECT id, start_date, end_date FROM academic_periods WHERE id = %s", (period_id,))
    p = cur.fetchone()
    if not p:
        return 0
    start = max(p["start_date"], _to_date(from_date)) if from_date else p["start_date"]
    end = min(p["end_date"], _to_date(to_date)) if to_date else p["end_date"]

    cur.execute(
        "SELECT e.id, e.title, e.start_date, e.end_date, e.start_time, e.end_time, "
        "       e.follow_weekday, e.faculty_id, t.code AS type_code, "
        f"      {_IMPACT_SQL} AS impact "
        "FROM calendar_events e JOIN calendar_event_types t ON t.id = e.event_type_id "
        "WHERE e.scope = 'college' AND e.faculty_id IS NULL "
        "  AND (e.academic_period_id IS NULL OR e.academic_period_id = %s) "
        "  AND e.end_date >= %s AND e.start_date <= %s", (period_id, start, end))
    events = cur.fetchall()

    cur.execute("SELECT calendar_date, is_working, day_type, follow_weekday, label, event_id "
                "FROM calendar_days WHERE academic_period_id = %s AND is_locked = 1 "
                "AND calendar_date BETWEEN %s AND %s", (period_id, start, end))
    locked = {r["calendar_date"]: r for r in cur.fetchall()}

    rows, d, locked_teaching = [], start, []
    while d <= end:
        if d not in locked:
            todays = [e for e in events if e["start_date"] <= d <= e["end_date"]]
            c = _classify(todays, d, None)
            full_block = (not c["ok"]) and not c["hard_block"]
            if c["is_special"]:
                dtype, working, teaching = "SPECIAL_WORKING", 1, 1
            elif c["hard_block"]:
                is_hol = any(e["type_code"] in NON_WORKING_CODES for e in todays)
                dtype, working, teaching = ("HOLIDAY" if is_hol else "NON_WORKING"), 0, 0
            elif full_block:
                dtype, working, teaching = "BLOCKED", 1, 0
            else:
                dtype, working, teaching = "WORKING", 1, 1
            follow = c["weekday"] if c["is_special"] and c["weekday"] != d.strftime("%A") else None
            rows.append((period_id, d, d.strftime("%A"), dtype, working, teaching,
                         follow, (c["label"] or c["reason"] or None), c["event_id"]))
        else:                       # locked (imported/manual) day: keep its flags, refresh teaching
            todays = [e for e in events if e["start_date"] <= d <= e["end_date"]]
            c = _classify(todays, d, locked[d])
            locked_teaching.append((1 if c["ok"] else 0, period_id, d))

        d += timedelta(days=1)

    if rows:
        cur.executemany(
            "INSERT INTO calendar_days (academic_period_id, calendar_date, weekday, day_type, "
            " is_working, is_teaching, follow_weekday, label, event_id, source, is_locked) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'derived',0) "
            "ON DUPLICATE KEY UPDATE "
            " weekday=VALUES(weekday), day_type=VALUES(day_type), is_working=VALUES(is_working), "
            " is_teaching=VALUES(is_teaching), follow_weekday=VALUES(follow_weekday), "
            " label=VALUES(label), event_id=VALUES(event_id)", rows)
    if locked_teaching:
        cur.executemany(
            "UPDATE calendar_days SET is_teaching = %s "
            "WHERE academic_period_id = %s AND calendar_date = %s AND is_locked = 1",
            locked_teaching)
        
    if not from_date and not to_date:
        cur.execute("DELETE FROM calendar_days WHERE academic_period_id = %s AND is_locked = 0 "
                    "AND (calendar_date < %s OR calendar_date > %s)",
                    (period_id, p["start_date"], p["end_date"]))
    return len(rows)


def rebuild_days_for_event(cur, period_id, start, end):
    """After add/delete of an event. period_id None = event applies to every period."""
    try:
        if period_id:
            ids = [period_id]
        else:
            cur.execute("SELECT id FROM academic_periods WHERE is_archived = 0 "
                        "AND start_date <= %s AND end_date >= %s", (end, start))
            ids = [r["id"] for r in cur.fetchall()]
        return sum(rebuild_calendar_days(cur, pid, start, end) for pid in ids)
    except Exception as exc:                       # never block saving the event
        logger.warning("calendar_days rebuild failed: %s", exc)
        return 0


def calendar_summary(cur, period_id):
    """Total working days, teaching days, special working days, teaching weeks."""
    cur.execute(
        "SELECT SUM(is_working) AS working_days, SUM(is_teaching) AS teaching_days, "
        "       SUM(day_type = 'SPECIAL_WORKING') AS special_days, "
        "       COUNT(DISTINCT CASE WHEN is_teaching = 1 THEN YEARWEEK(calendar_date, 1) END) "
        "         AS teaching_weeks, COUNT(*) AS total_days "
        "FROM calendar_days WHERE academic_period_id = %s", (period_id,))
    r = cur.fetchone() or {}
    return {k: int(r.get(k) or 0) for k in
            ("working_days", "teaching_days", "special_days", "teaching_weeks", "total_days")}