import pytest
from services.semester_service import derive_semester

BATCHES = [2026, 2025, 2024, 2023]

def test_odd_cycle_2026_27():
    assert [derive_semester(b, "2026-27", "ODD")[0] for b in BATCHES] == [1, 3, 5, 7]

def test_even_cycle_2026_27():
    assert [derive_semester(b, "2026-27", "EVEN")[0] for b in BATCHES] == [2, 4, 6, 8]

def test_graduation_after_sem8():
    assert derive_semester(2023, "2027-28", "ODD") == (None, "GRADUATED")

def test_not_started():
    assert derive_semester(2027, "2026-27", "ODD") == (None, "NOT_STARTED")

def test_bad_cycle():
    with pytest.raises(ValueError):
        derive_semester(2024, "2026-27", "SUMMER")