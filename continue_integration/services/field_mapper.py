"""
continue_integration/services/field_mapper.py

Dynamic Field Equalizer / Schema Mapper for Continue Portal Integration.

This module acts as a translation layer between AttendAI's internal schema
and whatever naming convention Continue portal uses.

Example:
  AttendAI: {"usn": "1RN22CS001", "is_present": True, "subject_code": "BCS401"}
  Continue: {"roll_number": "1RN22CS001", "status": "P", "course_id": "BCS401"}

When API keys and docs arrive, simply update the field mapping dictionary!
"""

import logging
from typing import Dict, Any

from config import (
    CONTINUE_STUDENT_ID_FIELD_NAME,
    CONTINUE_SUBJECT_FIELD_NAME,
)

logger = logging.getLogger(__name__)

# Default Parameter Mapping Dictionary (Easily configurable via DB / Admin UI)
DEFAULT_FIELD_MAPPING = {
    # AttendAI internal key  -> Continue API key name
    "student_id":   CONTINUE_STUDENT_ID_FIELD_NAME,  # e.g., "roll_no" or "usn" or "student_id"
    "subject_code": CONTINUE_SUBJECT_FIELD_NAME,     # e.g., "subject_code" or "course_code"
    "date":         "date",                          # e.g., "date" or "attendance_date"
    "period":       "period",                        # e.g., "period" or "slot" or "hour"
    "status":       "status",                        # e.g., "status" or "attendance_status"
    "section":      "section"                        # e.g., "section" or "class_section"
}

# Status Value Mapping (Converts boolean True/False into Continue's status format)
STATUS_VALUE_MAPPINGS = {
    "string_full":    {True: "present", False: "absent"},      # e.g. "present" / "absent"
    "string_upper":   {True: "PRESENT", False: "ABSENT"},      # e.g. "PRESENT" / "ABSENT"
    "char_single":    {True: "P",       False: "A"},           # e.g. "P" / "A"
    "integer_binary": {True: 1,         False: 0},             # e.g. 1 / 0
    "boolean":        {True: True,      False: False}          # e.g. true / false
}


class FieldEqualizer:
    """
    Translates AttendAI attendance payloads to Continue API format dynamically.
    """

    def __init__(self, mapping_override: Dict[str, str] = None, status_format: str = "string_full"):
        self.mapping = mapping_override or DEFAULT_FIELD_MAPPING
        self.status_format = status_format

    def equalize_attendance_payload(self, attendai_record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Converts AttendAI attendance record into Continue API payload format.

        Args:
            attendai_record: dict containing internal AttendAI fields:
                - student_id_val (USN / Roll No)
                - subject_code
                - date (YYYY-MM-DD)
                - period_number
                - is_present (bool)
                - section_label

        Returns:
            Dict[str, Any] matching Continue API key names & values
        """
        # Resolve status format (default: "present"/"absent")
        status_map = STATUS_VALUE_MAPPINGS.get(self.status_format, STATUS_VALUE_MAPPINGS["string_full"])
        status_val = status_map.get(bool(attendai_record.get("is_present")), "absent")

        payload = {
            self.mapping.get("student_id", "roll_no"):      attendai_record.get("student_id_val"),
            self.mapping.get("subject_code", "subject_code"): attendai_record.get("subject_code"),
            self.mapping.get("date", "date"):                 str(attendai_record.get("date")),
            self.mapping.get("period", "period"):             attendai_record.get("period_number"),
            self.mapping.get("status", "status"):             status_val,
            self.mapping.get("section", "section"):           attendai_record.get("section_label")
        }

        # Filter out keys mapped to empty strings if field isn't required by Continue
        return {k: v for k, v in payload.items() if k}
