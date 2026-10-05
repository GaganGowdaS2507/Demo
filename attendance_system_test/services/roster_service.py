"""
services/roster_service.py

ONE place that answers: "which students belong to this class?"
  - elective group  -> only the active members of that group
  - normal class    -> every student of the section(s)

All functions take a DICTIONARY cursor.
"""


def get_roster(cur, section_ids, elective_group_id=None):
    """Returns a list of {'id': student_id, 'usn': usn}."""
    if elective_group_id:
        cur.execute(
            "SELECT s.id, s.usn "
            "FROM elective_group_members egm "
            "JOIN students s ON s.id = egm.student_id "
            "WHERE egm.elective_group_id = %s AND egm.is_active = 1",
            (elective_group_id,),
        )
        return cur.fetchall()

    section_ids = [int(x) for x in section_ids if x]
    if not section_ids:
        return []
    marks = ",".join(["%s"] * len(section_ids))
    cur.execute(f"SELECT id, usn FROM students WHERE section_id IN ({marks})",
                tuple(section_ids))
    return cur.fetchall()


def roster_for_planned(cur, planned_session_id):
    """Roster for a planned session (section or elective group)."""
    cur.execute("SELECT section_id, elective_group_id FROM planned_sessions WHERE id = %s",
                (planned_session_id,))
    ps = cur.fetchone()
    if not ps:
        return []
    return get_roster(cur, [ps["section_id"]], ps["elective_group_id"])


def roster_for_session(cur, session_id):
    """Roster for a real session, including extra sections of a merged class."""
    cur.execute("SELECT section_id, elective_group_id FROM sessions WHERE id = %s",
                (session_id,))
    s = cur.fetchone()
    if not s:
        return []
    cur.execute("SELECT section_id FROM session_sections WHERE session_id = %s", (session_id,))
    sections = {s["section_id"]} | {r["section_id"] for r in cur.fetchall()}
    return get_roster(cur, sorted(sections), s["elective_group_id"])


def roster_size(cur, section_ids, elective_group_id=None):
    return len(get_roster(cur, section_ids, elective_group_id))