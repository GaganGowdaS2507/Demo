from __future__ import annotations


def calculate_percentage(marks: float | int, total: float | int) -> float:
    if total in (None, 0):
        return 0.0
    return round((float(marks) / float(total)) * 100, 2)


def get_grade_label(marks: float | int, total: float | int) -> str:
    percentage = calculate_percentage(marks, total)
    if percentage >= 90:
        return "A+"
    if percentage >= 85:
        return "A"
    if percentage >= 70:
        return "B"
    if percentage >= 60:
        return "C"
    if percentage >= 50:
        return "D"
    return "F"


def get_result_entry_config(subject_type: str | None) -> dict:
    """Return the input constraints and final-weighting for the result-entry UI."""
    subject_type = (subject_type or "Theory").strip()
    if subject_type == "Lab":
        return {
            "subject_type": subject_type,
            "final_total": 50,
            "ia_max": 0,
            "cca_max": 0,
            "fields": [
                {"name": "lab_marks", "label": "Lab Marks", "max": 20, "suffix": "/20"},
                {"name": "cie_marks", "label": "CIE Marks", "max": 30, "suffix": "/30"},
            ],
        }
    if subject_type == "Theory-Lab-Integrated":
        return {
            "subject_type": subject_type,
            "final_total": 50,
            "ia_max": 40,
            "cca_max": 20,
            "fields": [
                {"name": "ia1", "label": "IA1", "max": 40, "suffix": "/40"},
                {"name": "ia2", "label": "IA2", "max": 40, "suffix": "/40"},
                {"name": "ia3", "label": "IA3", "max": 40, "suffix": "/40"},
                {"name": "cca", "label": "CCA", "max": 20, "suffix": "/20"},
                {"name": "record", "label": "Record", "max": 30, "suffix": "/30"},
                {"name": "lab_test", "label": "Lab Test", "max": 20, "suffix": "/20"},
            ],
        }

    return {
        "subject_type": "Theory",
        "final_total": 50,
        "ia_max": 40,
        "cca_max": 20,
        "fields": [
            {"name": "ia1", "label": "IA1", "max": 40, "suffix": "/40"},
            {"name": "ia2", "label": "IA2", "max": 40, "suffix": "/40"},
            {"name": "ia3", "label": "IA3", "max": 40, "suffix": "/40"},
            {"name": "cca", "label": "CCA", "max": 20, "suffix": "/20"},
        ],
    }


def get_result_field_names(subject_type: str | None) -> list[str]:
    config = get_result_entry_config(subject_type)
    return [field["name"] for field in config.get("fields", [])]


def normalize_result_value(raw_value: object) -> float | None:
    if raw_value in (None, ""):
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    return value


def detect_changed_result_fields(existing_values: dict | None, submitted_values: dict, subject_type: str | None, remarks: str | None = None) -> dict:
    existing_values = existing_values or {}
    changes: dict[str, float | str | None] = {}
    for field_name in get_result_field_names(subject_type):
        submitted_value = normalize_result_value(submitted_values.get(field_name))
        existing_value = normalize_result_value(existing_values.get(field_name))
        if submitted_value != existing_value:
            changes[field_name] = submitted_value
    if remarks is not None and (existing_values.get("remarks") or "") != (remarks or ""):
        changes["remarks"] = remarks or None
    return changes


def _clamp_value(raw_value: object, max_value: float) -> float:
    try:
        value = float(raw_value or 0)
    except (TypeError, ValueError):
        value = 0.0
    return min(max(value, 0.0), float(max_value))


def calculate_internal_marks(subject_type: str, credits: int | None, values: dict) -> dict:
    """Calculate the final internal-assessment marks for a subject.

    Supported patterns:
    - Theory: best two of three IAs scaled to 30 + CCA scaled to 20 = 50
    - Lab Integrated: best two of three IAs scaled to 20 + CCA 10 + record/lab-test scaled to 20 = 50
    - Lab: lab component 20 + CIE 30 = 50
    - No-credit: no marks entry required
    """

    subject_type = (subject_type or "Theory").strip()
    credits = int(credits or 0)

    if credits == 0:
        return {
            "obtained_marks": 0,
            "total_marks": 0,
            "percentage": 0.0,
            "grade": "N/A",
        }

    if subject_type == "Lab":
        lab_marks = _clamp_value(values.get("lab_marks", 0), 20)
        cie_marks = _clamp_value(values.get("cie_marks", 0), 30)
        obtained = round(lab_marks + cie_marks, 2)
        return {
            "obtained_marks": obtained,
            "total_marks": 50,
            "percentage": calculate_percentage(obtained, 50),
            "grade": get_grade_label(obtained, 50),
        }

    if subject_type == "Theory-Lab-Integrated":
        ia_values = [_clamp_value(values.get(name, 0), 40) for name in ("ia1", "ia2", "ia3")]
        best_two = sum(sorted(ia_values, reverse=True)[:2])
        ia_component = round((best_two / 80.0) * 20.0, 2)
        cca_marks = _clamp_value(values.get("cca", 0), 20)
        record_marks = _clamp_value(values.get("record", 0), 30)
        lab_test_marks = _clamp_value(values.get("lab_test", 0), 20)
        practical_component = round((record_marks / 30.0) * 10.0 + (lab_test_marks / 20.0) * 10.0, 2)
        obtained = round(ia_component + cca_marks + practical_component, 2)
        return {
            "obtained_marks": obtained,
            "total_marks": 50,
            "percentage": calculate_percentage(obtained, 50),
            "grade": get_grade_label(obtained, 50),
        }

    # Default theory pattern
    ia_values = [_clamp_value(values.get(name, 0), 40) for name in ("ia1", "ia2", "ia3")]
    best_two = sum(sorted(ia_values, reverse=True)[:2])
    ia_component = round((best_two / 80.0) * 30.0, 2)
    cca_marks = _clamp_value(values.get("cca", 0), 20)
    obtained = round(ia_component + cca_marks, 2)
    return {
        "obtained_marks": obtained,
        "total_marks": 50,
        "percentage": calculate_percentage(obtained, 50),
        "grade": get_grade_label(obtained, 50),
    }
