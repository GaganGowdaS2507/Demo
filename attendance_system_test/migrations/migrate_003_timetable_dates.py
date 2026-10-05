"""
migrate_003_timetable_dates.py - Step 5B.

Run from the PROJECT ROOT:
    python migrations/migrate_003_timetable_dates.py            # REPORT ONLY
    python migrations/migrate_003_timetable_dates.py --apply

TAKE A DATABASE BACKUP FIRST (mysqldump). Safe to run many times.

 1. timetable.effective_from = earlier of (first real class of the slot, date the slot
    was added), never before the semester start. Stops 'missed' classes appearing for
    dates before a slot existed.
 2. Deletes planned rows dated before that, if no real class and no exception uses them.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import mysql.connector
from config import Config

APPLY = "--apply" in sys.argv
NAME = "003_timetable_dates"

FIRST_DATE = ("LEFT JOIN (SELECT timetable_id, MIN(session_date) AS first_date "
              "           FROM sessions WHERE timetable_id IS NOT NULL "
              "           GROUP BY timetable_id) fs ON fs.timetable_id = t.id")
NEW_DATE = ("LEAST(ap.end_date, GREATEST(ap.start_date, "
            "  LEAST(COALESCE(fs.first_date, DATE(t.created_at), ap.start_date), "
            "        COALESCE(DATE(t.created_at), fs.first_date, ap.start_date))))")
WHERE_CHANGE = f"t.effective_from = ap.start_date AND {NEW_DATE} <> ap.start_date"

STALE = ("FROM planned_sessions ps JOIN timetable t ON t.id = ps.timetable_id "
         "WHERE ps.origin = 'timetable' AND t.effective_from IS NOT NULL "
         "  AND ps.planned_date < t.effective_from "
         "  AND NOT EXISTS (SELECT 1 FROM sessions s WHERE s.planned_session_id = ps.id) "
         "  AND NOT EXISTS (SELECT 1 FROM session_exceptions e "
         "                  WHERE e.planned_session_id = ps.id AND e.is_active = 1)")


def connect():
    return mysql.connector.connect(
        host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
        password=Config.DB_PASS, database=Config.DB_NAME, autocommit=False)


def one(cur, sql):
    cur.execute(sql)
    return cur.fetchone()["c"]


def main():
    print("MODE:", "APPLY" if APPLY else "REPORT ONLY (nothing is changed)")
    conn = connect()
    cur = conn.cursor(dictionary=True)
    try:
        print("\n[1] timetable.effective_from")
        n = one(cur, f"SELECT COUNT(*) AS c FROM timetable t "
                     f"JOIN academic_periods ap ON ap.id = t.academic_period_id "
                     f"{FIRST_DATE} WHERE {WHERE_CHANGE}")
        print(f"  {n} slot(s) will start later than the semester start")
        if APPLY and n:
            cur.execute(f"UPDATE timetable t JOIN academic_periods ap "
                        f"ON ap.id = t.academic_period_id {FIRST_DATE} "
                        f"SET t.effective_from = {NEW_DATE} WHERE {WHERE_CHANGE}")
            print(f"  [done]     updated {cur.rowcount} slot(s)")

        print("\n[2] planned rows from before their slot existed (no class, no exception)")
        m = one(cur, f"SELECT COUNT(*) AS c {STALE}")
        print(f"  {m} planned row(s)")
        if APPLY and m:
            cur.execute(f"DELETE ps {STALE}")
            print(f"  [done]     deleted {cur.rowcount} row(s)")

        if APPLY:
            cur.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                        " name VARCHAR(100) NOT NULL PRIMARY KEY,"
                        " applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            cur.execute("INSERT IGNORE INTO schema_migrations (name) VALUES (%s)", (NAME,))
            conn.commit()
            print("\nSaved. Now run:  python -m services.timetable_engine")
        else:
            conn.rollback()
            print("\nReport only. Add --apply to change things.")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()