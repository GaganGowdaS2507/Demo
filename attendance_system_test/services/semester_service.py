"""
Single source of truth:
    batch admission year + academic year + cycle  ->  semester  ->  academic period
Nothing else in the project should compute or accept a semester from user input.
"""
import re
from datetime import date

from utils.academic_utils import next_cycle, calculate_next_academic_year

CYCLES = ("ODD", "EVEN")


class PeriodNotFound(Exception):
    pass


def parse_academic_year(academic_year):
    """'2026-27' -> 2026"""
    m = re.match(r"^\s*(\d{4})", str(academic_year or ""))
    if not m:
        raise ValueError(f"Invalid academic year: {academic_year!r}")
    return int(m.group(1))


def derive_semester(admission_year, academic_year, cycle):
    """
    Returns (semester, state)
      state = 'NOT_STARTED' | 'ACTIVE' | 'GRADUATED'
    """
    cycle = (cycle or "").upper()
    if cycle not in CYCLES:
        raise ValueError(f"Invalid cycle: {cycle!r}")

    year_of_study = parse_academic_year(academic_year) - int(admission_year) + 1
    if year_of_study < 1:
        return None, "NOT_STARTED"
    if year_of_study > 4:
        return None, "GRADUATED"

    sem = year_of_study * 2 - 1 if cycle == "ODD" else year_of_study * 2
    return sem, "ACTIVE"


def resolve_period(cursor, academic_year, cycle, semester):
    """Exact-key lookup (academic_year + cycle + sem). Cursor must be dictionary=True."""
    cursor.execute("""
        SELECT *
        FROM academic_periods
        WHERE academic_year = %s
          AND cycle = %s
          AND sem_number = %s
          AND COALESCE(is_archived, 0) = 0
        LIMIT 1
    """, (academic_year, cycle.upper(), semester))
    return cursor.fetchone()


def current_year_cycle(cursor, on_date=None):
    """
    Latest (academic_year, cycle) that has started on/before the date.
    Not based on is_active, so several periods can run at once.
    """
    on_date = on_date or date.today()
    cursor.execute("""
        SELECT academic_year, cycle
        FROM academic_periods
        WHERE start_date <= %s
          AND COALESCE(is_archived, 0) = 0
        GROUP BY academic_year, cycle
        ORDER BY MIN(start_date) DESC
        LIMIT 1
    """, (on_date,))
    row = cursor.fetchone()
    return (row["academic_year"], row["cycle"]) if row else None


def batch_year_cycle(cursor, batch_id):
    """The (academic_year, cycle) the batch's sections are currently linked to."""
    cursor.execute("""
        SELECT p.academic_year, p.cycle
        FROM sections s
        JOIN academic_periods p ON p.id = s.academic_period_id
        WHERE s.batch_id = %s
        ORDER BY p.start_date DESC
        LIMIT 1
    """, (batch_id,))
    row = cursor.fetchone()
    return (row["academic_year"], row["cycle"]) if row else None


def next_year_cycle(academic_year, cycle):
    return (calculate_next_academic_year(academic_year, cycle), next_cycle(cycle))


def sync_batch(cursor, batch_id, academic_year, cycle):
    """
    Move one batch (batch row, its sections, its students) to the semester and
    academic period derived for (academic_year, cycle).
    Raises ValueError / PeriodNotFound -> caller must rollback.
    """
    cursor.execute(
        "SELECT id, admission_year FROM batches WHERE id = %s", (batch_id,)
    )
    batch = cursor.fetchone()
    if not batch:
        raise ValueError("Batch not found.")

    sem, state = derive_semester(batch["admission_year"], academic_year, cycle)

    if state == "NOT_STARTED":
        raise ValueError(
            f"Batch {batch['admission_year']} has not started in {academic_year}."
        )

    if state == "GRADUATED":
        cursor.execute(
            "UPDATE batches SET is_active = 0, current_sem = 8 WHERE id = %s",
            (batch_id,),
        )
        cursor.execute("""
            UPDATE students st
            JOIN sections sec ON sec.id = st.section_id
            SET st.enrollment_status = 'graduated'
            WHERE sec.batch_id = %s
              AND COALESCE(st.enrollment_status, '') <> 'dropped'
        """, (batch_id,))
        return {"state": "GRADUATED", "semester": None, "period_id": None}

    period = resolve_period(cursor, academic_year, cycle, sem)
    if not period:
        raise PeriodNotFound(
            f"Create Academic Period '{academic_year} {cycle.title()} - Sem {sem}' first."
        )

    cursor.execute(
        "UPDATE batches SET current_sem = %s, is_active = 1 WHERE id = %s",
        (sem, batch_id),
    )

    cursor.execute("SELECT DISTINCT academic_period_id FROM sections WHERE batch_id = %s", (batch_id,))
    old_period_ids = {r["academic_period_id"] for r in cursor.fetchall() if r["academic_period_id"]}

    cursor.execute("""
        UPDATE sections
        SET sem_number = %s, academic_period_id = %s
        WHERE batch_id = %s
    """, (sem, period["id"], batch_id))
    cursor.execute("""
        UPDATE students st
        JOIN sections sec ON sec.id = st.section_id
        SET st.current_sem = %s
        WHERE sec.batch_id = %s
          AND COALESCE(st.enrollment_status, '') NOT IN ('graduated', 'dropped', 'detained')
    """, (sem, batch_id))

    # rules of the OLD semester must not carry into the new one; then rebuild both plans
    cursor.execute("""
        UPDATE timetable t JOIN sections sec ON sec.id = t.section_id
        SET t.is_active = 0
        WHERE sec.batch_id = %s AND t.is_active = 1
          AND t.academic_period_id <> sec.academic_period_id
    """, (batch_id,))
    from services.sync_service import after_batch_moved      # lazy: avoids a circular import
    after_batch_moved(cursor, old_period_ids, {period["id"]})

    return {"state": "ACTIVE", "semester": sem, "period_id": period["id"]}


def sync_all_batches(cursor, academic_year, cycle):
    """Used by cycle change / scheduler: every active batch resolves itself."""
    cursor.execute("SELECT id FROM batches WHERE is_active = 1")
    return {
        row["id"]: sync_batch(cursor, row["id"], academic_year, cycle)
        for row in cursor.fetchall()
    }


def section_problems(cursor, section_id):
    """Empty list = section, batch, semester and period agree."""
    cursor.execute("""
        SELECT sec.sem_number AS sec_sem, p.sem_number AS p_sem,
               p.academic_year, p.cycle, b.admission_year
        FROM sections sec
        JOIN batches b ON b.id = sec.batch_id
        LEFT JOIN academic_periods p ON p.id = sec.academic_period_id
        WHERE sec.id = %s
    """, (section_id,))
    r = cursor.fetchone()
    if not r:
        return ["Section not found."]
    if r["p_sem"] is None:
        return ["Section has no academic period."]

    expected, state = derive_semester(r["admission_year"], r["academic_year"], r["cycle"])
    problems = []
    if state != "ACTIVE":
        problems.append(f"Batch is {state} for {r['academic_year']} {r['cycle']}.")
    else:
        if r["sec_sem"] != expected:
            problems.append(f"Section sem {r['sec_sem']} != derived sem {expected}.")
        if r["p_sem"] != expected:
            problems.append(f"Period sem {r['p_sem']} != derived sem {expected}.")
    return problems

def period_for_section(cursor, section_id):
    """
    The ONLY way code should get a period for a section/student/timetable.
    Validates section + batch + semester + period agree, then returns the period row.
    Raises ValueError with a readable message otherwise.
    """
    problems = section_problems(cursor, section_id)
    if problems:
        raise ValueError(" ".join(problems))
    cursor.execute("""
        SELECT p.*
        FROM sections sec
        JOIN academic_periods p ON p.id = sec.academic_period_id
        WHERE sec.id = %s
    """, (section_id,))
    return cursor.fetchone()