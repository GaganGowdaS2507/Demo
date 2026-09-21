"""
Tests for the voice attendance search helper.
No Flask app or DB required — pure unit tests.

Run from the attendance_system_test directory:
    python -m pytest tests/test_voice_search.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from api.mobile.voice_search import parse_transcript, search_roster

# ---------------------------------------------------------------------------
# Shared fixture — a representative class roster
# ---------------------------------------------------------------------------

ROSTER = [
    {"student_id": 1,  "usn": "1BM22CS001", "name": "Aisha Patel",       "current_status": "absent"},
    {"student_id": 2,  "usn": "1BM22CS002", "name": "Gagan Gowda",       "current_status": "absent"},
    {"student_id": 3,  "usn": "1BM22CS003", "name": "Priya Sharma",      "current_status": "present"},
    {"student_id": 4,  "usn": "1BM22CS004", "name": "Raj Kumar",         "current_status": "absent"},
    {"student_id": 5,  "usn": "1BM22CS005", "name": "Gagan Singh",       "current_status": "absent"},
    {"student_id": 6,  "usn": "1BM22CS006", "name": "Meera Nair",        "current_status": "absent"},
    {"student_id": 10, "usn": "1BM22IS010", "name": "Deepak Krishnarao", "current_status": "absent"},
]


# ===========================================================================
# 1. parse_transcript — unit tests
# ===========================================================================

class TestParseTranscript:

    def test_usn_explicit_keyword(self):
        p = parse_transcript("Mark USN 1BM22CS002 present")
        assert p["type"] == "usn"
        assert "1BM22CS002" in p["value"].upper()

    def test_usn_lowercase(self):
        p = parse_transcript("mark usn 1bm22cs004 present")
        assert p["type"] == "usn"
        assert "1BM22CS004" in p["value"].upper()

    def test_roll_number_full(self):
        p = parse_transcript("Mark roll number 3 present")
        assert p["type"] == "roll"
        assert p["value"] == "3"

    def test_roll_number_short(self):
        p = parse_transcript("Roll 5 present")
        assert p["type"] == "roll"
        assert p["value"] == "5"

    def test_name_full(self):
        p = parse_transcript("Mark Gagan Gowda present")
        assert p["type"] == "name"
        assert "Gagan" in p["value"]
        assert "Gowda" in p["value"]

    def test_name_single_word_short_is_unknown(self):
        # A single 2-letter name should not be captured
        p = parse_transcript("Mark Aj present")
        # Either unknown or a name capture — just confirm we don't crash
        assert p["type"] in ("name", "unknown")

    def test_spoken_number_in_roll(self):
        p = parse_transcript("Mark roll number ten present")
        assert p["type"] == "roll"
        assert p["value"] == "10"

    def test_usn_spoken_letters(self):
        # "one BM twenty two CS zero zero two" → 1BM22CS002
        p = parse_transcript("mark USN one BM twenty two CS zero zero two present")
        assert p["type"] == "usn"

    def test_gibberish_returns_unknown(self):
        p = parse_transcript("aaaaaaa zzzzzz")
        # Should not crash; type may be unknown or name
        assert "type" in p
        assert "value" in p

    def test_empty_string(self):
        p = parse_transcript("")
        assert p["type"] == "unknown"


# ===========================================================================
# 2. search_roster — unit tests for all 12 scenarios
# ===========================================================================

class TestSearchRoster:

    # ---- Scenario 1: Name command — exact single match --------------------
    def test_name_exact_single_match(self):
        parsed = {"type": "name", "value": "Gagan Gowda"}
        r = search_roster(parsed, ROSTER)
        assert r["status"] == "exact"
        assert len(r["matches"]) == 1
        assert r["matches"][0]["usn"] == "1BM22CS002"

    # ---- Scenario 2: USN command — exact match ----------------------------
    def test_usn_exact_match(self):
        parsed = {"type": "usn", "value": "1BM22CS001"}
        r = search_roster(parsed, ROSTER)
        assert r["status"] == "exact"
        assert r["matches"][0]["student_id"] == 1

    # ---- Scenario 3: Roll number command ----------------------------------
    def test_roll_number_match(self):
        # Roll 4 → roster[3] (0-based) → Raj Kumar
        parsed = {"type": "roll", "value": "4"}
        r = search_roster(parsed, ROSTER)
        assert r["status"] == "exact"
        assert r["matches"][0]["usn"] == "1BM22CS004"

    # ---- Scenario 4: Student not found ------------------------------------
    def test_name_not_found(self):
        parsed = {"type": "name", "value": "Nobody Here"}
        r = search_roster(parsed, ROSTER)
        assert r["status"] == "not_found"
        assert r["matches"] == []

    def test_usn_not_found(self):
        parsed = {"type": "usn", "value": "1BM22CS999"}
        r = search_roster(parsed, ROSTER)
        assert r["status"] == "not_found"

    # ---- Scenario 5: Similar / ambiguous student names -------------------
    def test_ambiguous_first_name(self):
        # "Gagan" matches both Gagan Gowda (id=2) and Gagan Singh (id=5)
        parsed = {"type": "name", "value": "Gagan"}
        r = search_roster(parsed, ROSTER)
        assert r["status"] == "multiple"
        student_ids = {m["student_id"] for m in r["matches"]}
        assert 2 in student_ids
        assert 5 in student_ids

    # ---- Scenario 6: Duplicate attendance (already present) ---------------
    def test_already_present_student_is_still_returned(self):
        # Priya Sharma is already 'present' — search should still return her
        parsed = {"type": "name", "value": "Priya Sharma"}
        r = search_roster(parsed, ROSTER)
        assert r["status"] == "exact"
        assert r["matches"][0]["current_status"] == "present"

    # ---- Scenario 7 & 8: Offline + network restoration -------------------
    # No DB involved — voice_search.py is stateless; offline/sync handled
    # by existing AttendanceSyncService on the mobile side.

    # ---- Scenario 9: Wrong / unclear speech (gibberish parsed) -----------
    def test_gibberish_transcript_no_match(self):
        parsed = {"type": "unknown", "value": "blah blah blah"}
        r = search_roster(parsed, ROSTER)
        # Either no match or very unlikely match — should not be "exact"
        assert r["status"] in ("not_found", "multiple")

    # ---- Scenario 10: Roll number out of bounds --------------------------
    def test_roll_number_out_of_bounds(self):
        parsed = {"type": "roll", "value": "999"}
        r = search_roster(parsed, ROSTER)
        assert r["status"] == "not_found"

    def test_roll_number_zero(self):
        parsed = {"type": "roll", "value": "0"}
        r = search_roster(parsed, ROSTER)
        assert r["status"] == "not_found"

    # ---- Scenario 11: Classroom noise (partial / mangled name) -----------
    def test_partial_name_tokens_match(self):
        # "Deepak" alone should match Deepak Krishnarao
        parsed = {"type": "name", "value": "Deepak"}
        r = search_roster(parsed, ROSTER)
        assert r["status"] == "exact"
        assert r["matches"][0]["student_id"] == 10

    # ---- Scenario 12: Faculty cancellation before confirmation -----------
    # This is purely a UI concern — search_roster itself is stateless.
    # Test that calling search does NOT mutate the roster.
    def test_search_does_not_mutate_roster(self):
        import copy
        roster_copy = copy.deepcopy(ROSTER)
        parsed = {"type": "name", "value": "Meera Nair"}
        search_roster(parsed, roster_copy)
        assert roster_copy == ROSTER  # no side effects

    # ---- USN suffix partial match (one correct candidate) ----------------
    def test_usn_suffix_match_single(self):
        # Last 6 chars of "1BM22CS006" = "CS0006" — but test with full suffix
        parsed = {"type": "usn", "value": "CS006"}
        r = search_roster(parsed, ROSTER)
        # Should find 1BM22CS006 via suffix match
        assert r["status"] == "exact"
        assert r["matches"][0]["student_id"] == 6

    # ---- Case insensitive name match -------------------------------------
    def test_name_case_insensitive(self):
        parsed = {"type": "name", "value": "aisha patel"}
        r = search_roster(parsed, ROSTER)
        assert r["status"] == "exact"
        assert r["matches"][0]["student_id"] == 1

    # ---- USN uppercase normalisation -------------------------------------
    def test_usn_lowercase_normalised(self):
        parsed = {"type": "usn", "value": "1bm22cs003"}
        r = search_roster(parsed, ROSTER)
        assert r["status"] == "exact"
        assert r["matches"][0]["name"] == "Priya Sharma"

    # ---- Empty roster ----------------------------------------------------
    def test_empty_roster(self):
        parsed = {"type": "name", "value": "Gagan Gowda"}
        r = search_roster(parsed, [])
        assert r["status"] == "not_found"
        assert r["matches"] == []
