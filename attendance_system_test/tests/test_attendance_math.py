"""Acceptance: attendance % uses CONDUCTED classes only; planned/remaining are separate."""
from datetime import date

from services.attendance_engine import student_attendance


class ScriptedCursor:
    """Returns canned results in the order student_attendance() asks for them."""
    def __init__(self, fetchone, fetchall):
        self._one, self._all = list(fetchone), list(fetchall)

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return self._one.pop(0)

    def fetchall(self):
        return self._all.pop(0)


def test_85_percent_with_30_remaining():
    subject = {"subject_id": 1, "component": "theory", "code": "CS101", "name": "Maths",
               "attendance_rule": "combined"}
    cur = ScriptedCursor(
        fetchone=[{"section_id": 7}, {"start_date": date(2026, 8, 1), "end_date": date(2026, 12, 20)}],
        fetchall=[[dict(subject, conducted=20, present=17)],            # attendance rows
                  [dict(subject, planned=50, remaining=30)]])           # plan rows
    out = student_attendance(cur, student_id=1, period_id=5, threshold=75, today=date(2026, 10, 5))
    row = out["subjects"][0]
    assert row["conducted"] == 20 and row["present"] == 17
    assert row["percentage"] == 85.0                  # 17 / 20, NOT 17 / 50
    assert row["remaining"] == 30 and row["planned"] == 50
    assert row["expected_total"] == 50
    assert row["must_attend"] == 21 and row["can_miss"] == 9 and row["can_reach"]
    assert out["overall"]["percentage"] == 85.0


def test_no_conducted_classes_is_not_zero_percent_failure():
    subject = {"subject_id": 1, "component": "theory", "code": "CS101", "name": "Maths",
               "attendance_rule": "combined"}
    cur = ScriptedCursor(
        fetchone=[{"section_id": 7}, {"start_date": date(2026, 8, 1), "end_date": date(2026, 12, 20)}],
        fetchall=[[], [dict(subject, planned=50, remaining=50)]])
    out = student_attendance(cur, 1, 5, today=date(2026, 8, 2))
    assert out["subjects"][0]["status"] == "no_classes"