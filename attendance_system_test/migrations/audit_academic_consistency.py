"""
migrations/audit_academic_consistency.py - report sections whose batch / semester / period disagree.
    python migrations/audit_academic_consistency.py            # report only
    python migrations/audit_academic_consistency.py --fix 2026-27 ODD    # re-sync every active batch
Read-only unless --fix is given. --fix runs in ONE transaction and prints what it changed.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import mysql.connector
from config import Config
from services.semester_service import section_problems, sync_all_batches, PeriodNotFound


def main():
    conn = mysql.connector.connect(host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
                                   password=Config.DB_PASS, database=Config.DB_NAME, autocommit=False)
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        if "--fix" in sys.argv:
            i = sys.argv.index("--fix")
            year, cycle = sys.argv[i + 1], sys.argv[i + 2].upper()
            print(f"FIX MODE: syncing all active batches to {year} {cycle}")
            try:
                for bid, res in sync_all_batches(cur, year, cycle).items():
                    print(f"  batch {bid}: {res}")
                conn.commit()
                print("Committed.")
            except (PeriodNotFound, ValueError) as exc:
                conn.rollback()
                print("ROLLED BACK:", exc)
                return
        cur.execute("""SELECT s.id, d.code AS dept, s.section_label, b.admission_year, s.sem_number,
                              p.name AS period, p.academic_year, p.cycle, p.sem_number AS p_sem
                       FROM sections s JOIN departments d ON d.id = s.department_id
                       JOIN batches b ON b.id = s.batch_id
                       LEFT JOIN academic_periods p ON p.id = s.academic_period_id
                       ORDER BY b.admission_year, d.code, s.section_label""")
        bad = 0
        for s in cur.fetchall():
            problems = section_problems(cur, s["id"])
            if problems:
                bad += 1
                print(f"[BAD] section {s['id']} {s['dept']}-{s['section_label']} batch {s['admission_year']} "
                      f"sem {s['sem_number']} -> period '{s['period']}' ({s['academic_year']} {s['cycle']} "
                      f"sem {s['p_sem']}): {' '.join(problems)}")
        print(f"\n{bad} inconsistent section(s)." if bad else "\nAll sections are consistent.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()