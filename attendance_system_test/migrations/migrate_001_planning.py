"""
migrate_001_planning.py  -  Step 1 of the Calendar + Planned Sessions redesign.

Run from the PROJECT ROOT (the folder that has app.py and config.py):

    python migrations/migrate_001_planning.py --check   # only shows what it would do
    python migrations/migrate_001_planning.py           # really applies

Safe to run many times. Take a database backup first (mysqldump).
This step only ADDS things. It does not delete data or change app behaviour.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import mysql.connector
from config import Config

DRY = "--check" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
SQL_FILE = os.path.join(HERE, "001_create_planning_tables.sql")
MIGRATION_NAME = "001_planning"


# ------------------------------------------------------------------ helpers
def connect():
    return mysql.connector.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        user=Config.DB_USER,
        password=Config.DB_PASS,
        database=Config.DB_NAME,
        autocommit=True,
    )


def one(cur, sql, params=()):
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def table_exists(cur, table):
    return bool(one(cur,
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_name = %s", (table,)))


def column_info(cur, table, column):
    cur.execute(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s",
        (table, column))
    return cur.fetchone()          # None if column is missing


def index_exists(cur, table, index):
    return bool(one(cur,
        "SELECT COUNT(*) FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s",
        (table, index)))


def fk_exists(cur, table, name):
    return bool(one(cur,
        "SELECT COUNT(*) FROM information_schema.table_constraints "
        "WHERE table_schema = DATABASE() AND table_name = %s "
        "AND constraint_name = %s AND constraint_type = 'FOREIGN KEY'",
        (table, name)))


def do(cur, label, sql, params=()):
    """Run one write statement (or just print it in --check mode)."""
    if DRY:
        print(f"  [would do] {label}")
        return 0
    cur.execute(sql, params)
    n = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    print(f"  [done]     {label}" + (f"  ({n} rows)" if n else ""))
    return n


def add_column(cur, table, column, definition):
    if column_info(cur, table, column):
        print(f"  [exists]   {table}.{column}")
        return
    do(cur, f"add column {table}.{column}",
       f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


# -------------------------------------------------------------------- steps
def step_create_tables(cur):
    print("\n[1] Create new tables (from 001_create_planning_tables.sql)")
    with open(SQL_FILE, encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if not ln.strip().startswith("--")]
    statements = [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
    if DRY:
        print(f"  [would do] run {len(statements)} statements "
              f"(4 tables + event type seed)")
        return
    for stmt in statements:
        cur.execute(stmt)
    print(f"  [done]     ran {len(statements)} statements")

    cur.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " name VARCHAR(100) NOT NULL PRIMARY KEY,"
        " applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)")


def step_academic_periods(cur):
    print("\n[2] academic_periods")
    add_column(cur, "academic_periods", "calendar_status",
               "ENUM('none','draft','published') NOT NULL DEFAULT 'none'")
    add_column(cur, "academic_periods", "attendance_freeze_date", "DATE NULL")

    do(cur, "fill empty 'cycle' from 'cycle_type'",
       "UPDATE academic_periods SET cycle = UPPER(cycle_type) WHERE cycle IS NULL")

    do(cur, "fill empty 'academic_year' from start_date (example 2026-27)",
       "UPDATE academic_periods SET academic_year = "
       " CASE WHEN MONTH(start_date) >= 6 "
       "   THEN CONCAT(YEAR(start_date), '-', LPAD(MOD(YEAR(start_date) + 1, 100), 2, '0')) "
       "   ELSE CONCAT(YEAR(start_date) - 1, '-', LPAD(MOD(YEAR(start_date), 100), 2, '0')) "
       " END "
       "WHERE academic_year IS NULL OR academic_year = ''")

    if index_exists(cur, "academic_periods", "uq_period_year_sem"):
        print("  [exists]   unique key uq_period_year_sem")
        return
    cur.execute(
        "SELECT academic_year, sem_number, COUNT(*) c FROM academic_periods "
        "GROUP BY academic_year, sem_number HAVING c > 1")
    dups = cur.fetchall()
    if dups:
        print("  [SKIPPED]  unique (academic_year, sem_number): duplicates found, fix these first:")
        for d in dups:
            print(f"             year={d[0]} sem={d[1]} rows={d[2]}")
        return
    do(cur, "add unique key (academic_year, sem_number)",
       "ALTER TABLE academic_periods "
       "ADD UNIQUE KEY uq_period_year_sem (academic_year, sem_number)")


def step_timetable(cur):
    print("\n[3] timetable (effective dates)")
    add_column(cur, "timetable", "effective_from", "DATE NULL")
    add_column(cur, "timetable", "effective_to", "DATE NULL")
    do(cur, "fill effective_from with the period start date",
       "UPDATE timetable t JOIN academic_periods ap ON ap.id = t.academic_period_id "
       "SET t.effective_from = ap.start_date WHERE t.effective_from IS NULL")


def step_sessions(cur):
    print("\n[4] sessions (link to plan + theory/lab marker)")
    add_column(cur, "sessions", "planned_session_id", "INT NULL")
    add_column(cur, "sessions", "component",
               "ENUM('theory','lab') NOT NULL DEFAULT 'theory'")

    do(cur, "mark lab sessions (from timetable slot_type)",
       "UPDATE sessions s JOIN timetable t ON t.id = s.timetable_id "
       "SET s.component = 'lab' "
       "WHERE t.slot_type IN ('Lab','Lab-Merged') AND s.component <> 'lab'")

    if not index_exists(cur, "sessions", "idx_sessions_planned"):
        do(cur, "add index idx_sessions_planned",
           "ALTER TABLE sessions ADD INDEX idx_sessions_planned (planned_session_id)")
    if table_exists(cur, "planned_sessions") and not fk_exists(cur, "sessions", "fk_sessions_planned"):
        do(cur, "add foreign key sessions.planned_session_id -> planned_sessions.id",
           "ALTER TABLE sessions ADD CONSTRAINT fk_sessions_planned "
           "FOREIGN KEY (planned_session_id) REFERENCES planned_sessions (id) "
           "ON DELETE SET NULL")

    # Read-only report. The unique key is added in Step 2 AFTER you clean these.
    cur.execute(
        "SELECT timetable_id, session_date, COUNT(*) c, GROUP_CONCAT(id ORDER BY id) ids "
        "FROM sessions WHERE timetable_id IS NOT NULL "
        "GROUP BY timetable_id, session_date HAVING c > 1 LIMIT 25")
    dups = cur.fetchall()
    if dups:
        print("  [REPORT]   duplicate sessions (same timetable slot + date). Clean in Step 2:")
        for d in dups:
            print(f"             timetable={d[0]} date={d[1]} count={d[2]} session_ids={d[3]}")
    else:
        print("  [ok]       no duplicate sessions found")


def step_section_subjects(cur):
    print("\n[5] section_subjects (faculty may be empty)")
    info = column_info(cur, "section_subjects", "faculty_id")
    if info and info[0] == "NO":
        do(cur, "make section_subjects.faculty_id nullable",
           "ALTER TABLE section_subjects MODIFY faculty_id INT NULL")
    else:
        print("  [exists]   faculty_id already nullable")


def step_legacy_holidays(cur):
    print("\n[6] copy old holiday_calendar rows into calendar_events")
    if not table_exists(cur, "holiday_calendar"):
        print("  [skip]     holiday_calendar not found")
        return
    total = one(cur, "SELECT COUNT(*) FROM holiday_calendar")
    if DRY or not table_exists(cur, "calendar_events"):
        print(f"  [would do] copy up to {total} holiday rows (applies to all periods)")
        return
    do(cur, "copy holidays",
       "INSERT INTO calendar_events "
       " (academic_period_id, event_type_id, title, start_date, end_date, "
       "  scope, department_id, section_id, source, created_by) "
       "SELECT NULL, (SELECT id FROM calendar_event_types WHERE code = 'HOLIDAY'), "
       "       COALESCE(NULLIF(h.reason, ''), 'Holiday'), h.holiday_date, h.holiday_date, "
       "       h.scope, h.department_id, h.section_id, 'legacy_holiday', h.created_by "
       "FROM holiday_calendar h "
       "WHERE NOT EXISTS ("
       "  SELECT 1 FROM calendar_events e "
       "  WHERE e.source = 'legacy_holiday' AND e.start_date = h.holiday_date "
       "    AND IFNULL(e.department_id, 0) = IFNULL(h.department_id, 0) "
       "    AND IFNULL(e.section_id, 0) = IFNULL(h.section_id, 0))")


def step_record(cur):
    if DRY:
        return
    cur.execute("INSERT IGNORE INTO schema_migrations (name) VALUES (%s)", (MIGRATION_NAME,))


# --------------------------------------------------------------------- main
def main():
    print("MODE:", "CHECK ONLY (nothing is changed)" if DRY else "APPLY")
    conn = connect()
    cur = conn.cursor()
    try:
        step_create_tables(cur)
        step_academic_periods(cur)
        step_timetable(cur)
        step_sessions(cur)
        step_section_subjects(cur)
        step_legacy_holidays(cur)
        step_record(cur)
    finally:
        cur.close()
        conn.close()
    print("\nFinished.", "(check mode - re-run without --check to apply)" if DRY else "")


if __name__ == "__main__":
    main()