"""
migrate_007_timetable_period.py - make every timetable rule belong to its section's CURRENT period.
    python migrations/migrate_007_timetable_period.py --check     # report only
    python migrations/migrate_007_timetable_period.py             # apply
For each active rule whose timetable.academic_period_id differs from its section's period:
   subject semester == section semester  -> re-point the rule to the section's period
   otherwise (left over from an earlier semester) -> retire it (is_active = 0, row kept)
Idempotent. Nothing is deleted.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from migrate_001_planning import connect, DRY


def main():
    print("MODE:", "CHECK ONLY" if DRY else "APPLY")
    conn = connect()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        cur.execute(
            "SELECT t.id, t.section_id, t.academic_period_id AS t_period, sec.academic_period_id AS s_period, "
            "       sec.sem_number AS sec_sem, sub.sem_number AS sub_sem, "
            "       t.day_of_week, t.start_time "
            "FROM timetable t JOIN sections sec ON sec.id = t.section_id "
            "LEFT JOIN subjects sub ON sub.id = t.subject_id "
            "WHERE t.is_active = 1 AND (t.academic_period_id IS NULL OR t.academic_period_id <> sec.academic_period_id)")
        rows = cur.fetchall()
        print(f"{len(rows)} active timetable rule(s) point at the wrong period.")
        moved = retired = conflicts = 0
        for r in rows:
            realign = r["sub_sem"] is not None and r["sub_sem"] == r["sec_sem"]
            action = "re-point" if realign else "retire"
            print(f"  rule {r['id']} section {r['section_id']} {r['day_of_week']} {r['start_time']}: "
                  f"period {r['t_period']} -> {r['s_period']}  [{action}]")
            if DRY:
                continue
            if realign:
                try:
                    cur.execute("UPDATE timetable SET academic_period_id = %s WHERE id = %s",
                                (r["s_period"], r["id"]))
                    moved += 1
                except Exception as exc:                  # unique key clash with an existing rule
                    print("      conflict, retiring instead:", exc)
                    cur.execute("UPDATE timetable SET is_active = 0 WHERE id = %s", (r["id"],))
                    conflicts += 1
            else:
                cur.execute("UPDATE timetable SET is_active = 0 WHERE id = %s", (r["id"],))
                retired += 1
        if not DRY:
            cur.execute("INSERT IGNORE INTO schema_migrations (name) VALUES ('007_timetable_period')")
            conn.commit()
            print(f"\nre-pointed={moved}  retired={retired}  conflicts={conflicts}")
            print("Now run:  python -m services.sync_service")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()