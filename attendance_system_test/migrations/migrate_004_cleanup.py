"""
migrate_004_cleanup.py - Step 8 (final cleanup).

Run from the PROJECT ROOT. TAKE A DATABASE BACKUP FIRST (mysqldump).

    python migrations/migrate_004_cleanup.py                     # REPORT ONLY
    python migrations/migrate_004_cleanup.py --apply             # merge duplicate sessions
    python migrations/migrate_004_cleanup.py --fix-years         # academic_year from period name
    python migrations/migrate_004_cleanup.py --retire-holidays   # holiday_calendar -> holiday_calendar_old

Flags can be combined. Safe to run many times.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import mysql.connector
from config import Config

APPLY = "--apply" in sys.argv
FIX_YEARS = "--fix-years" in sys.argv
RETIRE = "--retire-holidays" in sys.argv
NAME = "004_cleanup"
STATUS_RANK = {"completed": 4, "active": 3, "scheduled": 2, "dismissed": 1, "cancelled": 0}


def connect():
    return mysql.connector.connect(
        host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
        password=Config.DB_PASS, database=Config.DB_NAME, autocommit=False)


def table_exists(cur, table):
    cur.execute("SELECT COUNT(*) AS c FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = %s", (table,))
    return cur.fetchone()["c"] > 0


# ------------------------------------------------------------ duplicate sessions
def pick_keeper(cur, ids):
    best = None
    for sid in ids:
        cur.execute(
            "SELECT s.id, s.status, s.planned_session_id, "
            " (SELECT COUNT(*) FROM attendance a WHERE a.session_id = s.id "
            "    AND a.status = 'present') AS present_cnt FROM sessions s WHERE s.id = %s",
            (sid,))
        r = cur.fetchone()
        score = (STATUS_RANK.get(r["status"], 0), 1 if r["planned_session_id"] else 0,
                 r["present_cnt"], -r["id"])
        if best is None or score > best[0]:
            best = (score, r["id"])
    return best[1]


def merge_into(cur, keeper, dup):
    cur.execute("SELECT timetable_id, planned_session_id FROM sessions WHERE id = %s", (dup,))
    d = cur.fetchone()

    cur.execute(
        "UPDATE attendance x LEFT JOIN attendance k "
        "  ON k.session_id = %s AND k.student_id = x.student_id "
        "SET x.session_id = %s WHERE x.session_id = %s AND k.id IS NULL",
        (keeper, keeper, dup))
    cur.execute(
        "UPDATE attendance k JOIN attendance x ON x.student_id = k.student_id AND x.session_id = %s "
        "SET k.status = 'present', k.method = x.method, k.recognition_score = x.recognition_score, "
        "    k.liveness_score = x.liveness_score, k.fingerprint_score = x.fingerprint_score, "
        "    k.marked_by = x.marked_by, k.marked_at = x.marked_at, k.notes = x.notes "
        "WHERE k.session_id = %s AND k.status = 'absent' AND x.status = 'present'",
        (dup, keeper))
    cur.execute("INSERT IGNORE INTO session_sections (session_id, section_id, added_by) "
                "SELECT %s, section_id, added_by FROM session_sections WHERE session_id = %s",
                (keeper, dup))
    cur.execute("DELETE FROM attendance WHERE session_id = %s", (dup,))
    cur.execute("DELETE FROM session_sections WHERE session_id = %s", (dup,))
    cur.execute("DELETE FROM sessions WHERE id = %s", (dup,))

    # the keeper may lack links that only the duplicate had (set AFTER the delete)
    cur.execute("UPDATE sessions SET planned_session_id = COALESCE(planned_session_id, %s), "
                "timetable_id = COALESCE(timetable_id, %s) WHERE id = %s",
                (d["planned_session_id"], d["timetable_id"], keeper))


def step_duplicates(conn, cur):
    print("\n[1] Duplicate sessions (same section, subject, date and start time)")
    cur.execute(
        "SELECT section_id, subject_id, session_date, start_time, "
        "       GROUP_CONCAT(id ORDER BY id) AS ids "
        "FROM sessions WHERE source = 'timetable' AND subject_id IS NOT NULL "
        "GROUP BY section_id, subject_id, session_date, start_time HAVING COUNT(*) > 1 "
        "ORDER BY session_date")
    groups = cur.fetchall()
    if not groups:
        print("  [ok]       none")
        return False
    changed = False
    for g in groups:
        ids = [int(x) for x in g["ids"].split(",")]
        keeper = pick_keeper(cur, ids)
        dups = [i for i in ids if i != keeper]
        label = f"date={g['session_date']} section={g['section_id']} keep={keeper} delete={dups}"
        if not APPLY:
            print(f"  [would do] {label}")
            continue
        try:
            for d in dups:
                merge_into(cur, keeper, d)
            conn.commit()
            changed = True
            print(f"  [done]     {label}")
        except mysql.connector.Error as e:
            conn.rollback()
            print(f"  [FAILED]   {label}\n             {e}")
    return changed


def step_elective_copies(cur):
    print("\n[2] Old elective copies (report only)")
    cur.execute(
        "SELECT COUNT(*) AS g, COALESCE(SUM(c - 1), 0) AS extra FROM ("
        " SELECT COUNT(*) AS c FROM sessions WHERE elective_group_id IS NOT NULL "
        "   AND source = 'timetable' "
        " GROUP BY elective_group_id, session_date, start_time HAVING COUNT(*) > 1) t")
    r = cur.fetchone()
    print(f"  {r['g']} elective class(es) have {r['extra']} extra copy session(s) from the old "
          f"generator.\n  Not changed: reports and the stats service already count each class once.")


# --------------------------------------------------------------------- periods
def step_period_years(conn, cur):
    print("\n[3] academic_year versus period name")
    cur.execute("SELECT id, name, academic_year FROM academic_periods ORDER BY id")
    changed = False
    found = False
    for r in cur.fetchall():
        m = re.search(r"(\d{4})-(\d{2})", r["name"] or "")
        if not m:
            continue
        want = f"{m.group(1)}-{m.group(2)}"
        if r["academic_year"] == want:
            continue
        found = True
        line = f"period {r['id']} '{r['name']}': academic_year is {r['academic_year']}, name says {want}"
        if not FIX_YEARS:
            print(f"  [differs]  {line}")
            continue
        try:
            cur.execute("UPDATE academic_periods SET academic_year = %s WHERE id = %s",
                        (want, r["id"]))
            conn.commit()
            changed = True
            print(f"  [done]     {line} -> fixed")
        except mysql.connector.Error as e:
            conn.rollback()
            print(f"  [FAILED]   {line}\n             {e}")
    if not found:
        print("  [ok]       nothing to fix")
    elif not FIX_YEARS:
        print("  (add --fix-years to correct these)")
    return changed


def step_section_period_gap(cur):
    print("\n[4] Sections whose semester differs from their period (report only)")
    cur.execute(
        "SELECT sec.id, d.code AS dept, sec.section_label, sec.sem_number AS section_sem, "
        "       ap.sem_number AS period_sem, ap.name "
        "FROM sections sec JOIN departments d ON d.id = sec.department_id "
        "JOIN academic_periods ap ON ap.id = sec.academic_period_id "
        "WHERE sec.sem_number <> ap.sem_number ORDER BY d.code, sec.section_label LIMIT 40")
    rows = cur.fetchall()
    if not rows:
        print("  [ok]       every section points at the period of its own semester")
        return
    for r in rows:
        print(f"  section {r['id']} {r['dept']}-{r['section_label']}: sem {r['section_sem']} "
              f"but period '{r['name']}' is sem {r['period_sem']}")
    print("  These sections would be planned with the OLD period's dates.\n"
          "  Point them to the new period before you upload that semester's timetable.")


def step_student_electives(cur):
    print("\n[5] student_electives (old table, no code reads it)")
    if not table_exists(cur, "student_electives"):
        print("  [skip]     table not found")
        return
    cur.execute("SELECT COUNT(*) AS c FROM student_electives")
    print(f"  {cur.fetchone()['c']} row(s). Left alone: the app uses elective_group_members.")


def step_retire_holidays(conn, cur):
    print("\n[6] holiday_calendar")
    if not table_exists(cur, "holiday_calendar"):
        print("  [skip]     already retired or missing")
        return False
    cur.execute("SELECT COUNT(*) AS c FROM holiday_calendar")
    old = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM calendar_events WHERE source = 'legacy_holiday'")
    copied = cur.fetchone()["c"]
    print(f"  old table has {old} row(s); {copied} were copied into calendar_events")
    if not RETIRE:
        print("  (add --retire-holidays to rename it to holiday_calendar_old)")
        return False
    if copied < old:
        print("  [SKIPPED]  not every holiday was copied. Run migrate_001_planning.py again first.")
        return False
    if table_exists(cur, "holiday_calendar_old"):
        print("  [SKIPPED]  holiday_calendar_old already exists")
        return False
    cur.execute("RENAME TABLE holiday_calendar TO holiday_calendar_old")
    conn.commit()
    print("  [done]     renamed to holiday_calendar_old (you can DROP it later)")
    return True


def main():
    print("FLAGS:", ", ".join(f for f, on in (("apply", APPLY), ("fix-years", FIX_YEARS),
                                              ("retire-holidays", RETIRE)) if on) or "report only")
    conn = connect()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        changed = step_duplicates(conn, cur)
        step_elective_copies(cur)
        changed = step_period_years(conn, cur) or changed
        step_section_period_gap(cur)
        step_student_electives(cur)
        changed = step_retire_holidays(conn, cur) or changed
        if changed:
            cur.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                        " name VARCHAR(100) NOT NULL PRIMARY KEY,"
                        " applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            cur.execute("INSERT IGNORE INTO schema_migrations (name) VALUES (%s)", (NAME,))
            conn.commit()
    finally:
        cur.close()
        conn.close()
    print("\nFinished.")


if __name__ == "__main__":
    main()