"""
migrate_005_calendar_layer.py - calendar teaching impact, academic_calendars, calendar_days.
    python migrations/migrate_005_calendar_layer.py --check
    python migrations/migrate_005_calendar_layer.py
Idempotent. Only ADDS; never deletes. Take a mysqldump first.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from migrate_001_planning import (          # reuse the same helpers
    connect, one, table_exists, column_info, index_exists, fk_exists,
    do, add_column, DRY,
)

IMPACTS = ("ALLOW_TEACHING','BLOCK_REGULAR_CLASSES','BLOCK_ALL','SECTION_SPECIFIC',"
           "'FACULTY_SPECIFIC','SPECIAL_WORKING_DAY','INFO_ONLY")
IMPACT_ENUM = f"ENUM('{IMPACTS}')"

TYPE_IMPACT = {            # existing system types -> new impact
    "HOLIDAY": "BLOCK_ALL", "NON_TEACHING_DAY": "BLOCK_ALL", "SEMESTER_EXAM": "BLOCK_ALL",
    "COLLEGE_EVENT": "BLOCK_REGULAR_CLASSES", "DEPT_EVENT": "BLOCK_REGULAR_CLASSES",
    "INTERNAL_ASSESSMENT": "BLOCK_REGULAR_CLASSES",
    "SPECIAL_WORKING_DAY": "SPECIAL_WORKING_DAY",
    "PROJECT_REVIEW": "INFO_ONLY", "PTM": "INFO_ONLY", "DEADLINE": "INFO_ONLY",
}

# (code, name, effect, impact, color)  - admin can change impact later
NEW_TYPES = [
    ("CCA",               "CCA / Co-curricular",        "info_only",       "INFO_ONLY",             "#00acc1"),
    ("PRACTICAL_EXAM",    "Practical / Lab Exam",       "blocks_teaching", "BLOCK_REGULAR_CLASSES", "#3949ab"),
    ("REGISTRATION",      "Registration",               "info_only",       "INFO_ONLY",             "#6d4c41"),
    ("ADD_DROP",          "Add / Drop Courses",         "info_only",       "INFO_ONLY",             "#6d4c41"),
    ("WITHDRAWAL",        "Course Withdrawal",          "info_only",       "INFO_ONLY",             "#6d4c41"),
    ("FACULTY_FEEDBACK",  "Faculty Feedback",           "info_only",       "INFO_ONLY",             "#fb8c00"),
    ("MARKS_DEADLINE",    "Marks Entry Deadline",       "info_only",       "INFO_ONLY",             "#fb8c00"),
    ("ATTENDANCE_FREEZE", "Attendance Freeze",          "info_only",       "INFO_ONLY",             "#c62828"),
    ("CIE_FREEZE",        "CIE Freeze",                 "info_only",       "INFO_ONLY",             "#c62828"),
    ("LAST_WORKING_DAY",  "Last Working Day",           "info_only",       "INFO_ONLY",             "#2e7d32"),
    ("SEMESTER_START",    "Commencement of Semester",   "info_only",       "INFO_ONLY",             "#2e7d32"),
    ("ACADEMIC_EVENT",    "Other Academic Event",       "info_only",       "INFO_ONLY",             "#757575"),
]


def step_types(cur):
    print("\n[1] calendar_event_types: teaching_impact + category")
    add_column(cur, "calendar_event_types", "teaching_impact", f"{IMPACT_ENUM} NULL")
    add_column(cur, "calendar_event_types", "category", "VARCHAR(40) NULL")
    for code, impact in TYPE_IMPACT.items():
        do(cur, f"impact {code} -> {impact}",
           "UPDATE calendar_event_types SET teaching_impact = %s "
           "WHERE code = %s AND teaching_impact IS NULL", (impact, code))
    do(cur, "custom types: derive impact from old effect",
       "UPDATE calendar_event_types SET teaching_impact = CASE effect "
       " WHEN 'allows_teaching' THEN 'ALLOW_TEACHING' "
       " WHEN 'info_only' THEN 'INFO_ONLY' ELSE 'BLOCK_ALL' END "
       "WHERE teaching_impact IS NULL")
    for code, name, effect, impact, color in NEW_TYPES:
        do(cur, f"seed type {code}",
           "INSERT IGNORE INTO calendar_event_types "
           "(code, name, effect, teaching_impact, color, is_system) VALUES (%s,%s,%s,%s,%s,1)",
           (code, name, effect, impact, color))
    # keep the OLD column consistent for legacy readers
    do(cur, "sync effect from impact",
       "UPDATE calendar_event_types SET effect = CASE "
       " WHEN teaching_impact IN ('ALLOW_TEACHING','SPECIAL_WORKING_DAY') THEN 'allows_teaching' "
       " WHEN teaching_impact = 'INFO_ONLY' THEN 'info_only' ELSE 'blocks_teaching' END")


def step_events(cur):
    print("\n[2] calendar_events: impact_override, faculty_id, category, faculty scope")
    add_column(cur, "calendar_events", "impact_override", f"{IMPACT_ENUM} NULL")
    add_column(cur, "calendar_events", "faculty_id", "INT NULL")
    add_column(cur, "calendar_events", "category", "VARCHAR(40) NULL")
    do(cur, "backfill impact_override from old effect_override",
       "UPDATE calendar_events SET impact_override = CASE effect_override "
       " WHEN 'allows_teaching' THEN 'ALLOW_TEACHING' "
       " WHEN 'info_only' THEN 'INFO_ONLY' ELSE 'BLOCK_ALL' END "
       "WHERE effect_override IS NOT NULL AND impact_override IS NULL")
    if not index_exists(cur, "calendar_events", "idx_ce_faculty"):
        do(cur, "index idx_ce_faculty", "ALTER TABLE calendar_events ADD INDEX idx_ce_faculty (faculty_id)")
    if table_exists(cur, "faculty") and not fk_exists(cur, "calendar_events", "fk_ce_faculty"):
        do(cur, "fk calendar_events.faculty_id -> faculty.id",
           "ALTER TABLE calendar_events ADD CONSTRAINT fk_ce_faculty "
           "FOREIGN KEY (faculty_id) REFERENCES faculty (id) ON DELETE CASCADE")
    cur.execute("SELECT column_type FROM information_schema.columns WHERE table_schema = DATABASE() "
                "AND table_name='calendar_events' AND column_name='scope'")
    ct = cur.fetchone()[0]
    if "faculty" in ct:
        print("  [exists]   scope already has 'faculty'")
    else:
        do(cur, "scope enum += 'faculty'",
           "ALTER TABLE calendar_events MODIFY scope "
           "ENUM('college','department','section','faculty') NOT NULL DEFAULT 'college'")


def step_tables(cur):
    print("\n[3] academic_calendars + calendar_days")
    do(cur, "create academic_calendars",
       "CREATE TABLE IF NOT EXISTS academic_calendars ("
       " id INT NOT NULL AUTO_INCREMENT,"
       " academic_period_id INT NOT NULL,"
       " title VARCHAR(150) NULL,"
       " status ENUM('draft','published') NOT NULL DEFAULT 'draft',"
       " source_type ENUM('manual','csv','xlsx','docx','pdf','image') NOT NULL DEFAULT 'manual',"
       " source_filename VARCHAR(255) NULL,"
       " source_sha256 CHAR(64) NULL,"
       " imported_by INT NULL,"
       " imported_at DATETIME NULL,"
       " notes VARCHAR(255) NULL,"
       " created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
       " PRIMARY KEY (id),"
       " UNIQUE KEY uq_acal_period (academic_period_id),"
       " CONSTRAINT fk_acal_period FOREIGN KEY (academic_period_id) "
       "   REFERENCES academic_periods (id) ON DELETE CASCADE,"
       " CONSTRAINT fk_acal_user FOREIGN KEY (imported_by) "
       "   REFERENCES users (id) ON DELETE SET NULL"
       ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci")
    do(cur, "create calendar_days",
       "CREATE TABLE IF NOT EXISTS calendar_days ("
       " id INT NOT NULL AUTO_INCREMENT,"
       " academic_period_id INT NOT NULL,"
       " calendar_date DATE NOT NULL,"
       " weekday VARCHAR(10) NOT NULL,"
       " day_type ENUM('WORKING','SPECIAL_WORKING','HOLIDAY','NON_WORKING','BLOCKED') NOT NULL,"
       " is_working TINYINT(1) NOT NULL DEFAULT 1,"
       " is_teaching TINYINT(1) NOT NULL DEFAULT 1,"
       " follow_weekday VARCHAR(10) NULL,"
       " label VARCHAR(150) NULL,"
       " event_id INT NULL,"
       " source ENUM('derived','import','manual') NOT NULL DEFAULT 'derived',"
       " is_locked TINYINT(1) NOT NULL DEFAULT 0,"
       " PRIMARY KEY (id),"
       " UNIQUE KEY uq_cday (academic_period_id, calendar_date),"
       " KEY idx_cday_flags (academic_period_id, is_working, is_teaching),"
       " CONSTRAINT fk_cday_period FOREIGN KEY (academic_period_id) "
       "   REFERENCES academic_periods (id) ON DELETE CASCADE,"
       " CONSTRAINT fk_cday_event FOREIGN KEY (event_id) "
       "   REFERENCES calendar_events (id) ON DELETE SET NULL"
       ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci")
    if table_exists(cur, "academic_periods"):
        do(cur, "one academic_calendars row per existing period",
           "INSERT IGNORE INTO academic_calendars (academic_period_id, title) "
           "SELECT id, name FROM academic_periods")


def step_report_and_build(cur):
    print("\n[4] holiday_calendar compatibility + build calendar_days")
    if table_exists(cur, "holiday_calendar"):
        src = one(cur, "SELECT COUNT(*) FROM holiday_calendar")
        dst = one(cur, "SELECT COUNT(*) FROM calendar_events WHERE source='legacy_holiday'")
        print(f"  [report]   holiday_calendar rows={src}, copied into calendar_events={dst}")
        if dst < src:
            print("  [WARNING]  fewer copied than source - re-run migrate_001_planning.py")
    else:
        print("  [skip]     holiday_calendar not present (already retired)")
    if DRY:
        print("  [would do] rebuild calendar_days for every period")
        return
    from services.calendar_service import rebuild_calendar_days
    import mysql.connector
    from config import Config
    conn = mysql.connector.connect(host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
                                   password=Config.DB_PASS, database=Config.DB_NAME)
    dcur = conn.cursor(dictionary=True)
    dcur.execute("SELECT id, name FROM academic_periods")
    for p in dcur.fetchall():
        n = rebuild_calendar_days(dcur, p["id"])
        print(f"  [done]     period {p['id']} ({p['name']}): {n} days")
    conn.commit()
    dcur.close()
    conn.close()


def main():
    print("MODE:", "CHECK ONLY" if DRY else "APPLY")
    conn = connect()
    cur = conn.cursor()
    try:
        step_types(cur)
        step_events(cur)
        step_tables(cur)
        if not DRY:
            cur.execute("INSERT IGNORE INTO schema_migrations (name) VALUES ('005_calendar_layer')")
    finally:
        cur.close()
        conn.close()
    conn2 = connect()
    cur2 = conn2.cursor()
    try:
        step_report_and_build(cur2)
    finally:
        cur2.close()
        conn2.close()
    print("\nFinished.")


if __name__ == "__main__":
    main()