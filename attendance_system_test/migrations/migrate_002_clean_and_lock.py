"""
migrate_002_clean_and_lock.py - Step 2 of the Calendar + Planned Sessions redesign.

Run from the PROJECT ROOT (the folder that has app.py and config.py):

    python migrations/migrate_002_clean_and_lock.py            # REPORT ONLY, changes nothing
    python migrations/migrate_002_clean_and_lock.py --apply    # clean + add unique key

TAKE A DATABASE BACKUP FIRST (mysqldump).

What it does:
 1. Finds sessions that share the same timetable slot AND the same date.
 2. Keeps the best one, copies any 'present' marks into it, deletes the others.
 3. Adds unique key uq_sessions_timetable_date on sessions(timetable_id, session_date).
Safe to run many times.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import mysql.connector
from config import Config

APPLY = "--apply" in sys.argv
MIGRATION_NAME = "002_clean_and_lock"
UNIQUE_NAME = "uq_sessions_timetable_date"

# Higher number = better session to keep.
STATUS_RANK = {"completed": 4, "active": 3, "scheduled": 2, "dismissed": 1, "cancelled": 0}


def connect():
    return mysql.connector.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        user=Config.DB_USER,
        password=Config.DB_PASS,
        database=Config.DB_NAME,
        autocommit=False,
    )


def index_exists(cur, table, index):
    cur.execute(
        "SELECT COUNT(*) AS c FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s",
        (table, index))
    return cur.fetchone()["c"] > 0


def find_groups(cur):
    """Groups of sessions with the same timetable slot and date."""
    cur.execute("""
        SELECT timetable_id, session_date, GROUP_CONCAT(id ORDER BY id) AS ids
        FROM sessions
        WHERE timetable_id IS NOT NULL
        GROUP BY timetable_id, session_date
        HAVING COUNT(*) > 1
        ORDER BY session_date, timetable_id
    """)
    return cur.fetchall()


def pick_keeper(cur, ids):
    """Best session = best status, then most 'present' marks, then lowest id."""
    best = None
    for sid in ids:
        cur.execute("""
            SELECT s.id, s.status,
                   (SELECT COUNT(*) FROM attendance a
                     WHERE a.session_id = s.id AND a.status = 'present') AS present_cnt
            FROM sessions s WHERE s.id = %s
        """, (sid,))
        r = cur.fetchone()
        score = (STATUS_RANK.get(r["status"], 0), r["present_cnt"], -r["id"])
        if best is None or score > best[0]:
            best = (score, r["id"])
    return best[1]


def merge_into(cur, keeper, dup):
    """Move everything useful from session `dup` into session `keeper`, then delete `dup`."""
    # a) students that only the duplicate has -> move their rows to the keeper
    cur.execute("""
        UPDATE attendance d
        LEFT JOIN attendance k ON k.session_id = %s AND k.student_id = d.student_id
        SET d.session_id = %s
        WHERE d.session_id = %s AND k.id IS NULL
    """, (keeper, keeper, dup))

    # b) keeper says absent, duplicate says present -> copy the present mark
    cur.execute("""
        UPDATE attendance k
        JOIN attendance d ON d.student_id = k.student_id AND d.session_id = %s
        SET k.status = 'present', k.method = d.method,
            k.recognition_score = d.recognition_score,
            k.liveness_score = d.liveness_score,
            k.fingerprint_score = d.fingerprint_score,
            k.marked_by = d.marked_by, k.marked_at = d.marked_at, k.notes = d.notes
        WHERE k.session_id = %s AND k.status = 'absent' AND d.status = 'present'
    """, (dup, keeper))

    # c) extra sections of a merged class
    cur.execute("""
        INSERT IGNORE INTO session_sections (session_id, section_id, added_by)
        SELECT %s, section_id, added_by FROM session_sections WHERE session_id = %s
    """, (keeper, dup))

    # d) remove the duplicate
    cur.execute("DELETE FROM attendance WHERE session_id = %s", (dup,))
    cur.execute("DELETE FROM session_sections WHERE session_id = %s", (dup,))
    cur.execute("DELETE FROM sessions WHERE id = %s", (dup,))


# -------------------------------------------------------------------- steps
def step_report_legacy(cur):
    print("\n[1] Report only: older duplicates the unique key cannot see")
    cur.execute("""
        SELECT section_id, subject_id, faculty_id, session_date, start_time,
               COUNT(*) AS c, GROUP_CONCAT(id ORDER BY id) AS ids
        FROM sessions
        WHERE source = 'timetable'
        GROUP BY section_id, subject_id, faculty_id, session_date, start_time
        HAVING c > 1
        LIMIT 25
    """)
    rows = cur.fetchall()
    if not rows:
        print("  [ok]       none found")
        return
    for r in rows:
        print(f"  [look]     section={r['section_id']} subject={r['subject_id']} "
              f"date={r['session_date']} time={r['start_time']} session_ids={r['ids']}")
    print("  (Not changed. Check these by hand if you want.)")


def step_clean(conn, cur):
    print("\n[2] Same timetable slot + same date")
    groups = find_groups(cur)
    if not groups:
        print("  [ok]       no duplicates")
        return True

    print(f"  found {len(groups)} duplicate group(s)")
    failed = 0
    for g in groups:
        ids = [int(x) for x in g["ids"].split(",")]
        keeper = pick_keeper(cur, ids)
        dups = [i for i in ids if i != keeper]
        label = f"timetable={g['timetable_id']} date={g['session_date']} keep={keeper} delete={dups}"
        if not APPLY:
            print(f"  [would do] {label}")
            continue
        try:
            for d in dups:
                merge_into(cur, keeper, d)
            conn.commit()
            print(f"  [done]     {label}")
        except mysql.connector.Error as e:
            conn.rollback()
            failed += 1
            print(f"  [FAILED]   {label}\n             reason: {e}")
    if not APPLY:
        return False
    return failed == 0


def step_unique_key(conn, cur):
    print("\n[3] Unique key on sessions(timetable_id, session_date)")
    if index_exists(cur, "sessions", UNIQUE_NAME):
        print(f"  [exists]   {UNIQUE_NAME}")
        return True
    if find_groups(cur):
        print("  [SKIPPED]  duplicates still exist. Run with --apply first (or fix the FAILED ones).")
        return False
    if not APPLY:
        print(f"  [would do] add unique key {UNIQUE_NAME}")
        return False
    cur.execute(
        f"ALTER TABLE sessions ADD UNIQUE KEY {UNIQUE_NAME} (timetable_id, session_date)")
    conn.commit()
    print(f"  [done]     added {UNIQUE_NAME}")
    return True


def step_record(conn, cur):
    cur.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " name VARCHAR(100) NOT NULL PRIMARY KEY,"
        " applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
    cur.execute("INSERT IGNORE INTO schema_migrations (name) VALUES (%s)", (MIGRATION_NAME,))
    conn.commit()


def main():
    print("MODE:", "APPLY" if APPLY else "REPORT ONLY (nothing is changed)")
    conn = connect()
    cur = conn.cursor(dictionary=True)
    try:
        step_report_legacy(cur)
        step_clean(conn, cur)
        done = step_unique_key(conn, cur)
        if APPLY and done:
            step_record(conn, cur)
    finally:
        cur.close()
        conn.close()
    print("\nFinished.", "" if APPLY else "(report only - add --apply to really change things)")


if __name__ == "__main__":
    main()