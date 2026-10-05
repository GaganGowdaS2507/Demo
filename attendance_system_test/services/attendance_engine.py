"""
services/attendance_engine.py  -  ONE place for class counts and attendance %.

Every dashboard and report must call this file. Nobody else counts "total classes".

Rules:
  conducted  = real session with status completed or active
               (faculty forgot attendance -> still conducted, students stay absent)
  NOT conducted = dismissed, cancelled
  planned    = planned_sessions with status 'planned'
  remaining  = planned, date today or later, no real class yet
  missed     = planned, no conducted class, day is past (or class was dismissed)
  unplanned  = conducted classes outside the plan (manual / extra)

All functions take a DICTIONARY cursor: conn.cursor(dictionary=True)

Command line test (from project root):
  python -m services.attendance_engine --student 12 --period 5
  python -m services.attendance_engine --faculty 3 --period 5
"""
import sys
from datetime import date

from sympy import per

_GROUPABLE = ("section_id", "subject_id", "faculty_id", "elective_group_id", "component")

_HELD_PS = ("EXISTS (SELECT 1 FROM sessions x WHERE x.planned_session_id = ps.id "
            "AND x.status IN ('completed','active'))")
_CLOSED_PS = ("EXISTS (SELECT 1 FROM sessions x WHERE x.planned_session_id = ps.id "
              "AND x.status IN ('dismissed','cancelled'))")
_ELECTIVE_OFFERINGS = "('professional_elective','open_elective','ability_enhancement')"


def _zero():
    return {"planned": 0, "conducted": 0, "conducted_planned": 0, "unplanned": 0,
            "remaining": 0, "missed": 0, "cancelled": 0, "dismissed": 0,
            "completion_pct": 0.0}


# ---------------------------------------------------------------- core counts
def _aggregate(cur, filters, group_cols=(), today=None):
    """Returns {group_key_tuple: counts_dict}. group_key is () when no grouping."""
    today = today or date.today()
    f = {k: v for k, v in filters.items() if v is not None}
    for c in group_cols:
        if c not in _GROUPABLE:
            raise ValueError(f"cannot group by {c}")

    # ---- planned side
    where, params = "", []
    if "period_id" in f:
        where += " AND ps.academic_period_id = %s"
        params.append(f["period_id"])
    for col in _GROUPABLE:
        if col in f:
            where += f" AND ps.{col} = %s"
            params.append(f[col])
    sel = "".join(f"ps.{c} AS {c}, " for c in group_cols)
    grp = (" GROUP BY " + ", ".join(f"ps.{c}" for c in group_cols)) if group_cols else ""
    cur.execute(
        f"""
        SELECT {sel}
          COALESCE(SUM(ps.status = 'planned'), 0) AS planned,
          COALESCE(SUM(ps.status = 'planned' AND {_HELD_PS}), 0) AS conducted_planned,
          COALESCE(SUM(ps.status = 'planned' AND NOT {_HELD_PS} AND NOT {_CLOSED_PS}
                       AND ps.planned_date >= %s), 0) AS remaining,
          COALESCE(SUM(ps.status = 'planned' AND NOT {_HELD_PS}
                       AND ({_CLOSED_PS} OR ps.planned_date < %s)), 0) AS missed,
          COALESCE(SUM(ps.status = 'cancelled'), 0) AS cancelled
        FROM planned_sessions ps
        WHERE ps.origin <> 'extra' {where} {grp}
        """,
        [today, today] + params,
    )
    planned_rows = cur.fetchall()

    # ---- real-session side (things the plan does not explain)
    where, params = "", []
    if "period_id" in f:
        where += " AND sec.academic_period_id = %s"
        params.append(f["period_id"])
    for col in _GROUPABLE:
        if col in f:
            where += f" AND s.{col} = %s"
            params.append(f[col])
    sel = "".join(f"s.{c} AS {c}, " for c in group_cols)
    grp = (" GROUP BY " + ", ".join(f"s.{c}" for c in group_cols)) if group_cols else ""
    cur.execute(
        f"""
        SELECT {sel}
          COALESCE(SUM(s.status IN ('completed','active')
                        AND (s.planned_session_id IS NULL OR p.status <> 'planned'
                            OR p.origin = 'extra')), 0) AS unplanned,
          COALESCE(SUM(s.status = 'dismissed'), 0) AS dismissed
        FROM sessions s
        JOIN sections sec ON sec.id = s.section_id
        LEFT JOIN planned_sessions p ON p.id = s.planned_session_id
        WHERE 1 = 1 {where} {grp}
        """,
        params,
    )
    session_rows = cur.fetchall()

    merged = {}
    for r in planned_rows:
        key = tuple(r[c] for c in group_cols)
        e = merged.setdefault(key, _zero())
        for k in ("planned", "conducted_planned", "remaining", "missed", "cancelled"):
            e[k] = int(r[k])
    for r in session_rows:
        key = tuple(r[c] for c in group_cols)
        e = merged.setdefault(key, _zero())
        e["unplanned"] = int(r["unplanned"])
        e["dismissed"] = int(r["dismissed"])

    for e in merged.values():
        e["conducted"] = e["conducted_planned"] + e["unplanned"]
        e["completion_pct"] = (round(100.0 * e["conducted_planned"] / e["planned"], 1)
                               if e["planned"] else 0.0)
    return merged


def class_counts(cur, period_id=None, section_id=None, subject_id=None, faculty_id=None,
                 elective_group_id=None, component=None, today=None):
    """Totals for any combination of filters. Returns one counts dict."""
    data = _aggregate(cur, {
        "period_id": period_id, "section_id": section_id, "subject_id": subject_id,
        "faculty_id": faculty_id, "elective_group_id": elective_group_id,
        "component": component}, (), today)
    return data.get((), _zero())


def breakdown(cur, group_cols, today=None, **filters):
    """Counts grouped by some columns, e.g. breakdown(cur, ('subject_id',), period_id=5)."""
    data = _aggregate(cur, filters, tuple(group_cols), today)
    rows = []
    for key, counts in data.items():
        row = dict(zip(group_cols, key))
        row.update(counts)
        rows.append(row)
    return rows


# ------------------------------------------------------------------- student
def _overall(rows, threshold):
    conducted = sum(r["conducted"] for r in rows)
    present = sum(r["present"] for r in rows)
    return {"conducted": conducted, "present": present, "absent": conducted - present,
            "percentage": round(100.0 * present / conducted, 1) if conducted else 0.0,
            "threshold": threshold}


def student_attendance(cur, student_id, period_id, threshold=75, today=None):
    """
    Per-subject attendance for one student.
    Returns {"subjects": [...], "overall": {...}}.
    Each subject row: conducted, present, absent, percentage, remaining, expected_total,
                      must_attend, can_miss, can_reach, status.
    Subjects with attendance_rule 'separate' appear once per component (theory / lab).
    """
    today = today or date.today()
    cur.execute("SELECT section_id FROM students WHERE id = %s", (student_id,))
    st = cur.fetchone()
    if not st:
        return {"subjects": [], "overall": _overall([], threshold)}
    section_id = st["section_id"]

    cur.execute("SELECT start_date, end_date FROM academic_periods WHERE id = %s", (period_id,))
    per = cur.fetchone()
    if not per:
        return {"subjects": [], "overall": _overall([], threshold)}
    # attendance of classes that were conducted (only electives the student really takes)
    cur.execute(
        f"""
        SELECT s.subject_id, s.component, sub.code, sub.name, sub.attendance_rule,
               COUNT(DISTINCT CONCAT(s.session_date, '|', COALESCE(s.start_time, '00:00:00'))) AS conducted,
               COUNT(DISTINCT CASE WHEN a.status = 'present'
                     THEN CONCAT(s.session_date, '|', COALESCE(s.start_time, '00:00:00')) END) AS present
        FROM attendance a
        JOIN sessions s   ON s.id = a.session_id
        JOIN sections sec ON sec.id = s.section_id
        JOIN subjects sub ON sub.id = s.subject_id
        WHERE a.student_id = %s
          AND (sec.academic_period_id = %s
               OR (s.elective_group_id IS NOT NULL AND s.session_date BETWEEN %s AND %s))
          AND s.status IN ('completed','active')
          AND (s.elective_group_id IS NULL OR EXISTS (
                 SELECT 1 FROM elective_group_members m
                 WHERE m.student_id = %s AND m.is_active = 1
                   AND m.elective_group_id = s.elective_group_id))
          AND (sub.offering_mode NOT IN {_ELECTIVE_OFFERINGS} OR EXISTS (
                 SELECT 1 FROM elective_group_members m2
                 JOIN elective_groups g2 ON g2.id = m2.elective_group_id
                 WHERE m2.student_id = %s AND m2.is_active = 1 AND g2.subject_id = s.subject_id))
        GROUP BY s.subject_id, s.component, sub.code, sub.name, sub.attendance_rule
        """,
                (student_id, period_id, per["start_date"], per["end_date"], student_id, student_id),
    )
    att_rows = cur.fetchall()

    # classes still to come (from the plan)
    cur.execute(
        f"""
        SELECT ps.subject_id, ps.component, sub.code, sub.name, sub.attendance_rule,
               COUNT(*) AS planned,
               COALESCE(SUM(ps.planned_date >= %s AND NOT {_HELD_PS} AND NOT {_CLOSED_PS}), 0) AS remaining
        FROM planned_sessions ps
        JOIN subjects sub ON sub.id = ps.subject_id
        WHERE (ps.academic_period_id = %s
               OR (ps.elective_group_id IS NOT NULL AND ps.planned_date BETWEEN %s AND %s))
          AND ps.status = 'planned' AND ps.origin <> 'extra'
          AND ((ps.elective_group_id IS NULL AND ps.section_id = %s)
               OR ps.elective_group_id IN (
                    SELECT m.elective_group_id FROM elective_group_members m
                    WHERE m.student_id = %s AND m.is_active = 1))
          AND (sub.offering_mode NOT IN {_ELECTIVE_OFFERINGS} OR EXISTS (
                 SELECT 1 FROM elective_group_members m2
                 JOIN elective_groups g2 ON g2.id = m2.elective_group_id
                 WHERE m2.student_id = %s AND m2.is_active = 1 AND g2.subject_id = ps.subject_id))
        GROUP BY ps.subject_id, ps.component, sub.code, sub.name, sub.attendance_rule
        """,
        (today, period_id, per["start_date"], per["end_date"], section_id, student_id, student_id),
    )
    plan_rows = cur.fetchall()

    merged = {}

    def slot(r):
        comp = r["component"] if r["attendance_rule"] == "separate" else None
        key = (r["subject_id"], comp)
        if key not in merged:
            merged[key] = {"subject_id": r["subject_id"], "component": comp,
                           "code": r["code"], "name": r["name"],
                           "attendance_rule": r["attendance_rule"],
                           "conducted": 0, "present": 0, "planned": 0, "remaining": 0}
        return merged[key]

    for r in att_rows:
        e = slot(r)
        e["conducted"] += int(r["conducted"])
        e["present"] += int(r["present"])
    for r in plan_rows:
        e = slot(r)
        e["planned"] += int(r["planned"])
        e["remaining"] += int(r["remaining"])

    rows = []
    for e in merged.values():
        e["absent"] = e["conducted"] - e["present"]
        e["percentage"] = round(100.0 * e["present"] / e["conducted"], 1) if e["conducted"] else 0.0
        e["expected_total"] = e["conducted"] + e["remaining"]
        required = -(-threshold * e["expected_total"] // 100)       # ceiling
        e["must_attend"] = max(0, required - e["present"])
        e["can_reach"] = e["must_attend"] <= e["remaining"]
        e["can_miss"] = max(0, e["remaining"] - e["must_attend"])
        if e["conducted"] == 0:
            e["status"] = "no_classes"
        else:
            e["status"] = "safe" if e["percentage"] >= threshold else "low"
        rows.append(e)
    rows.sort(key=lambda r: (r["code"] or "", r["component"] or ""))
    return {"subjects": rows, "overall": _overall(rows, threshold)}


# ------------------------------------------------------------------- faculty
def faculty_progress(cur, faculty_id, period_id, today=None):
    """Planned -> conducted -> remaining, per section / subject / group / component."""
    groups = ("section_id", "subject_id", "elective_group_id", "component")
    rows = breakdown(cur, groups, today=today, faculty_id=faculty_id, period_id=period_id)
    if not rows:
        return []

    sub_ids = sorted({r["subject_id"] for r in rows if r["subject_id"]})
    sec_ids = sorted({r["section_id"] for r in rows if r["section_id"]})
    subjects, sections = {}, {}
    if sub_ids:
        cur.execute("SELECT id, code, name FROM subjects WHERE id IN (%s)"
                    % ",".join(["%s"] * len(sub_ids)), sub_ids)
        subjects = {r["id"]: r for r in cur.fetchall()}
    if sec_ids:
        cur.execute("SELECT sec.id, sec.section_label, d.code AS dept_code "
                    "FROM sections sec JOIN departments d ON d.id = sec.department_id "
                    "WHERE sec.id IN (%s)" % ",".join(["%s"] * len(sec_ids)), sec_ids)
        sections = {r["id"]: r for r in cur.fetchall()}

    for r in rows:
        sub = subjects.get(r["subject_id"], {})
        sec = sections.get(r["section_id"], {})
        r["subject_code"] = sub.get("code", "")
        r["subject_name"] = sub.get("name", "")
        r["section_name"] = f"{sec.get('dept_code', '')}-{sec.get('section_label', '')}"
    rows.sort(key=lambda r: (r["section_name"], r["subject_code"], r["component"]))
    return rows


# ------------------------------------------------------------ report helpers
def _fmt_td(value):
    if value is None:
        return ""
    if hasattr(value, "total_seconds"):
        t = int(value.total_seconds())
        return f"{t // 3600:02d}:{(t % 3600) // 60:02d}"
    return str(value)[:5]


def class_report(cur, subject_id, section_id, date_from, date_to, elective_group_id=None):
    """
    Class-by-class table for one subject.
      - section class  -> the section's students
      - elective group -> only that group's active members
    Only classes that were held (completed / active). One column per date+time, even if
    old duplicate sessions exist ('present' in any copy wins).
    Returns {"sessions": [...], "students": [...]}; students are sorted lowest % first.
    """
    where = ("s.subject_id = %s AND s.status IN ('completed','active') "
             "AND s.session_date BETWEEN %s AND %s")
    params = [subject_id, date_from, date_to]
    if elective_group_id:
        where += " AND s.elective_group_id = %s"
        params.append(elective_group_id)
    else:
        where += " AND s.section_id = %s AND s.elective_group_id IS NULL"
        params.append(section_id)
    cur.execute(
        f"SELECT s.id, s.session_date, s.start_time, s.end_time FROM sessions s "
        f"WHERE {where} ORDER BY s.session_date, s.start_time, s.id", params)
    raw = cur.fetchall()

    columns, col_of = [], {}
    for r in raw:
        key = (r["session_date"], r["start_time"])
        if key not in col_of:
            col_of[key] = r["id"]
            columns.append({"id": r["id"], "session_date": r["session_date"],
                            "start_time": _fmt_td(r["start_time"]),
                            "end_time": _fmt_td(r["end_time"])})
    session_col = {r["id"]: col_of[(r["session_date"], r["start_time"])] for r in raw}

    if elective_group_id:
        cur.execute(
            "SELECT st.id, st.usn, u.full_name FROM students st "
            "JOIN users u ON u.id = st.user_id "
            "JOIN elective_group_members m ON m.student_id = st.id "
            "  AND m.elective_group_id = %s AND m.is_active = 1 ORDER BY st.usn",
            (elective_group_id,))
    else:
        cur.execute(
            "SELECT st.id, st.usn, u.full_name FROM students st "
            "JOIN users u ON u.id = st.user_id WHERE st.section_id = %s ORDER BY st.usn",
            (section_id,))
    students = cur.fetchall()

    marks = {}
    if session_col:
        ids = list(session_col)
        cur.execute(
            "SELECT session_id, student_id, status FROM attendance WHERE session_id IN (%s)"
            % ",".join(["%s"] * len(ids)), ids)
        for a in cur.fetchall():
            col = session_col[a["session_id"]]
            cell = marks.setdefault(a["student_id"], {})
            if a["status"] == "present":
                cell[col] = "present"
            elif col not in cell:
                cell[col] = "absent"

    out = []
    for st in students:
        cells = marks.get(st["id"], {})
        total = len(cells)
        present = sum(1 for v in cells.values() if v == "present")
        out.append({
            "student_id": st["id"], "usn": st["usn"], "name": st["full_name"],
            "total": total, "present": present, "absent": total - present,
            "percentage": round(100.0 * present / total, 1) if total else 0.0,
            "session_data": cells,
        })
    out.sort(key=lambda x: x["percentage"])
    return {"sessions": columns, "students": out}


def faculty_attendance_rates(cur, faculty_id, period_id):
    """Average attendance per (section, subject, group, component) for held classes.
    faculty_id None = every faculty. Returns {key: {'records': n, 'present': n}}."""
    sql = (
        "SELECT s.section_id, s.subject_id, s.elective_group_id, s.component, "
        "       COUNT(*) AS records, COALESCE(SUM(a.status = 'present'), 0) AS present "
        "FROM attendance a "
        "JOIN sessions s ON s.id = a.session_id "
        "JOIN sections sec ON sec.id = s.section_id "
        "WHERE sec.academic_period_id = %s AND s.status IN ('completed','active')"
    )
    params = [period_id]
    if faculty_id:
        sql += " AND s.faculty_id = %s"
        params.append(faculty_id)
    sql += " GROUP BY s.section_id, s.subject_id, s.elective_group_id, s.component"
    cur.execute(sql, params)
    return {(r["section_id"], r["subject_id"], r["elective_group_id"], r["component"]): r
            for r in cur.fetchall()}


def defaulter_list(cur, faculty_id=None, threshold=75, period_id=None):
    """Students below `threshold` % in any subject. faculty_id None = every faculty.
    period_id None = every period running today. Lowest percentage first."""
    if period_id:
        period_ids = [period_id]
    else:
        cur.execute("SELECT id FROM academic_periods WHERE is_archived = 0 "
                    "AND CURDATE() BETWEEN start_date AND end_date")
        period_ids = [r["id"] for r in cur.fetchall()]
    if not period_ids:
        return []

    marks = ",".join(["%s"] * len(period_ids))
    sql = (
        "SELECT st.id AS student_id, st.usn, u.full_name, "
        "  sub.id AS subject_id, sub.code AS subject_code, sub.name AS subject_name, "
        "  s.section_id, sec.section_label, d.code AS dept_code, "
        "  CASE WHEN sub.attendance_rule = 'separate' THEN s.component ELSE NULL END AS comp, "
        "  COUNT(DISTINCT CONCAT(s.session_date, '|', s.start_time)) AS total_sessions, "
        "  COUNT(DISTINCT CASE WHEN a.status = 'present' "
        "        THEN CONCAT(s.session_date, '|', s.start_time) END) AS present "
        "FROM attendance a "
        "JOIN sessions s ON s.id = a.session_id "
        "JOIN sections sec ON sec.id = s.section_id "
        "JOIN departments d ON d.id = sec.department_id "
        "JOIN subjects sub ON sub.id = s.subject_id "
        "JOIN students st ON st.id = a.student_id "
        "JOIN users u ON u.id = st.user_id "
        f"WHERE s.status IN ('completed','active') AND sec.academic_period_id IN ({marks})"
    )
    params = list(period_ids)
    if faculty_id:
        sql += " AND s.faculty_id = %s"
        params.append(faculty_id)
    sql += " GROUP BY st.id, sub.id, s.section_id, comp"
    cur.execute(sql, params)

    rows = []
    for r in cur.fetchall():
        total = int(r["total_sessions"])
        present = int(r["present"])
        pct = round(100.0 * present / total, 1) if total else 0.0
        if total and pct < threshold:
            if r["comp"]:
                r["subject_name"] = f"{r['subject_name']} ({r['comp'].title()})"
            r["total_sessions"], r["present"], r["percentage"] = total, present, pct
            rows.append(r)
    rows.sort(key=lambda x: (x["percentage"], x["subject_code"], x["usn"]))
    return rows

# ---------------------------------------------------- admin / HOD helpers
_CLASS_KEY = ("CONCAT(COALESCE(s.subject_id, 0), '|', s.session_date, '|', "
              "COALESCE(s.start_time, '00:00:00'))")


def _running_periods(cur, period_id=None):
    if period_id:
        return [period_id]
    cur.execute("SELECT id FROM academic_periods WHERE is_archived = 0 "
                "AND CURDATE() BETWEEN start_date AND end_date")
    return [r["id"] for r in cur.fetchall()]


def section_summary(cur, section_id, date_from=None, date_to=None):
    """Overall attendance (all subjects together) for every student of a section.
    Counts only held classes (completed / active) the student was on the roster for.
    Lowest percentage first."""
    cur.execute(
        "SELECT st.id, st.usn, u.full_name FROM students st "
        "JOIN users u ON u.id = st.user_id WHERE st.section_id = %s ORDER BY st.usn",
        (section_id,))
    students = cur.fetchall()
    if not students:
        return []

    ids = [s["id"] for s in students]
    sql = (
        f"SELECT a.student_id, COUNT(DISTINCT {_CLASS_KEY}) AS total, "
        f"       COUNT(DISTINCT CASE WHEN a.status = 'present' THEN {_CLASS_KEY} END) AS present "
        "FROM attendance a JOIN sessions s ON s.id = a.session_id "
        "WHERE s.status IN ('completed','active') AND a.student_id IN (%s)"
        % ",".join(["%s"] * len(ids))
    )
    params = list(ids)
    if date_from:
        sql += " AND s.session_date >= %s"
        params.append(date_from)
    if date_to:
        sql += " AND s.session_date <= %s"
        params.append(date_to)
    cur.execute(sql + " GROUP BY a.student_id", params)
    counts = {r["student_id"]: r for r in cur.fetchall()}

    out = []
    for st in students:
        c = counts.get(st["id"])
        total = int(c["total"]) if c else 0
        present = int(c["present"]) if c else 0
        out.append({
            "student_id": st["id"], "usn": st["usn"], "name": st["full_name"],
            "total": total, "present": present, "absent": total - present,
            "percentage": round(100.0 * present / total, 1) if total else 0.0,
        })
    out.sort(key=lambda x: x["percentage"])
    return out


def overall_defaulters(cur, threshold=75, period_id=None, department_id=None):
    """Students whose OVERALL attendance is below `threshold` %, over held classes only
    (completed / active) of the semesters running today. department_id filters by the
    student's home department. Lowest percentage first."""
    period_ids = _running_periods(cur, period_id)
    if not period_ids:
        return []

    sql = (
        "SELECT st.id AS student_id, st.usn, u.full_name, sec.section_label, "
        "       d.code AS dept_code, "
        f"      COUNT(DISTINCT {_CLASS_KEY}) AS total_sessions, "
        f"      COUNT(DISTINCT CASE WHEN a.status = 'present' THEN {_CLASS_KEY} END) AS present "
        "FROM attendance a "
        "JOIN sessions s ON s.id = a.session_id "
        "JOIN sections ssec ON ssec.id = s.section_id "
        "JOIN students st ON st.id = a.student_id "
        "JOIN users u ON u.id = st.user_id "
        "LEFT JOIN sections sec ON sec.id = st.section_id "
        "LEFT JOIN departments d ON d.id = sec.department_id "
        "WHERE s.status IN ('completed','active') AND ssec.academic_period_id IN (%s)"
        % ",".join(["%s"] * len(period_ids))
    )
    params = list(period_ids)
    if department_id:
        sql += " AND sec.department_id = %s"
        params.append(department_id)
    sql += " GROUP BY st.id, st.usn, u.full_name, sec.section_label, d.code"
    cur.execute(sql, params)

    rows = []
    for r in cur.fetchall():
        total, present = int(r["total_sessions"]), int(r["present"])
        pct = round(100.0 * present / total, 1) if total else 0.0
        if total and pct < threshold:
            r["total_sessions"], r["present"], r["percentage"] = total, present, pct
            rows.append(r)
    rows.sort(key=lambda x: (x["percentage"], x["usn"]))
    return rows

# ------------------------------------------------------------- command line
def _main():
    import mysql.connector
    from config import Config

    def arg(name):
        return int(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else None

    conn = mysql.connector.connect(
        host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
        password=Config.DB_PASS, database=Config.DB_NAME)
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        period = arg("--period")
        if period is None and arg("--student"):
            cur.execute("SELECT sec.academic_period_id AS id FROM students s "
                        "JOIN sections sec ON sec.id = s.section_id WHERE s.id = %s",
                        (arg("--student"),))
            r = cur.fetchone()
            period = r["id"] if r else None
        if period is not None:
            periods = [period]
        else:
            cur.execute("SELECT DISTINCT academic_period_id AS id FROM planned_sessions ORDER BY 1")
            periods = [r["id"] for r in cur.fetchall()]

        for period in periods:
            print(f"\n=== period_id = {period}")
            if arg("--student"):
                res = student_attendance(cur, arg("--student"), period)
                print(f"{'subject':<12}{'comp':<8}{'held':>5}{'pres':>5}{'%':>7}{'left':>6}"
                      f"{'must':>6}{'canmiss':>9}  status")
                for r in res["subjects"]:
                    print(f"{(r['code'] or '')[:11]:<12}{(r['component'] or '-'):<8}{r['conducted']:>5}"
                          f"{r['present']:>5}{r['percentage']:>7}{r['remaining']:>6}"
                          f"{r['must_attend']:>6}{r['can_miss']:>9}  {r['status']}")
                print("overall:", res["overall"])
            elif arg("--faculty"):
                for r in faculty_progress(cur, arg("--faculty"), period):
                    print(f"{r['section_name']:<10}{r['subject_code']:<12}{r['component']:<8}"
                          f"planned={r['planned']:<4} conducted={r['conducted']:<4} "
                          f"remaining={r['remaining']:<4} missed={r['missed']:<3} "
                          f"done={r['completion_pct']}%")
            else:
                print("totals:", class_counts(cur, period_id=period))
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    _main()