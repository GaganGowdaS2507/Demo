"""
services/calendar_import.py - ONE import pipeline for every file format.

   file -> parser (csv/xlsx now; docx/pdf/ocr later) -> raw rows (dicts)
        -> normalize() -> validate() -> admin preview/correction -> commit()

Parsers only produce raw rows. Everything after that is shared, so DOCX/PDF/OCR
plug in later without touching validation or commit. Never trusted blindly:
every row carries `issues` and `confidence`; rows with an error are never committed.
"""
import csv
import difflib
import hashlib
import io
import json
import re
from datetime import date, datetime

IMPACTS = ("ALLOW_TEACHING", "BLOCK_REGULAR_CLASSES", "BLOCK_ALL", "SECTION_SPECIFIC",
           "FACULTY_SPECIFIC", "SPECIAL_WORKING_DAY", "INFO_ONLY")
ALLOWING = {"ALLOW_TEACHING", "SPECIAL_WORKING_DAY"}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
LOW_CONFIDENCE = 0.80

HEADER_ALIASES = {
    "record_type": ("record_type", "record", "kind"),
    "event_type": ("event_type", "type", "event type", "eventtype"),
    "title": ("title", "event", "event_name", "name", "description"),
    "start_date": ("start_date", "start", "from", "from_date", "date", "start date"),
    "end_date": ("end_date", "end", "to", "to_date", "end date"),
    "scope": ("scope",),
    "department": ("department", "dept", "department_code", "dept_code"),
    "section": ("section", "section_label"),
    "teaching_impact": ("teaching_impact", "impact", "teaching impact"),
    "category": ("category",),
    "is_working": ("is_working", "working", "working_day"),
    "follow_weekday": ("follow_weekday", "follow", "follows"),
    "notes": ("notes", "remarks"),
}
_ALIAS_LOOKUP = {a: k for k, v in HEADER_ALIASES.items() for a in v}

DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y",
                "%d %B %Y", "%d-%b-%y", "%d/%m/%y", "%d-%m-%y")      # day-first (India)

TEMPLATE_CSV = (
    "record_type,event_type,title,start_date,end_date,scope,department,section,"
    "teaching_impact,category,is_working,follow_weekday,notes\n"
    "event,HOLIDAY,Ugadi,2027-04-09,2027-04-09,college,,,,,,,\n"
    "event,INTERNAL_ASSESSMENT,IA-1,2027-04-19,2027-04-23,college,,,BLOCK_REGULAR_CLASSES,CIE,,,\n"
    "event,SPECIAL_WORKING_DAY,Saturday follows Monday,2027-05-01,2027-05-01,college,,,,,,Monday,\n"
    "event,DEPT_EVENT,CSE Tech Fest,2027-05-05,2027-05-06,department,CSE,,,,,,\n"
    "day,,Working Sunday,2027-05-09,,,,,,,yes,,\n"
    "day,,Mid-sem break,2027-05-10,,,,,,,no,,\n"
)


# ----------------------------------------------------------------- parsing
def parse_date(value):
    """Returns (date|None, note|None)."""
    if value is None or str(value).strip() == "":
        return None, None
    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date(), None
        except ValueError:
            continue
    return None, f"Unreadable date '{text}'"


def _norm_header(h):
    return re.sub(r"\s+", " ", str(h or "").strip().lower())


def _rows_from_table(table):
    """table = list of lists (first non-empty row = header). Returns raw rows."""
    table = [r for r in table if any(str(c).strip() for c in r if c is not None)]
    if not table:
        return []
    headers = [_ALIAS_LOOKUP.get(_norm_header(h)) for h in table[0]]
    if not any(headers):
        raise ValueError("No recognised column headers. Download the template for the layout.")
    out = []
    for i, r in enumerate(table[1:], start=2):
        row = {"line": i, "confidence": 1.0}
        for h, cell in zip(headers, r):
            if h and cell is not None and str(cell).strip() != "":
                row[h] = cell
        out.append(row)
    return out


def parse_csv(data: bytes):
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return _rows_from_table(list(csv.reader(io.StringIO(text), dialect)))


def parse_xlsx(data: bytes):
    try:
        import openpyxl
    except ImportError:
        raise ValueError("Excel import needs openpyxl:  pip install openpyxl")
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    return _rows_from_table([list(r) for r in wb.worksheets[0].iter_rows(values_only=True)])


PARSERS = {"csv": parse_csv, "xlsx": parse_xlsx}
SUPPORTED = ("csv", "xlsx", "docx", "pdf", "image")


def parse(kind, data, period=None):
    """Single entry point for every format. period = academic_periods row (dates guide year inference)."""
    if kind in PARSERS:
        return PARSERS[kind](data)
    from services import calendar_extract as cx          # imported lazily: heavy libraries
    return {"docx": cx.parse_docx, "pdf": cx.parse_pdf, "image": cx.parse_image}[kind](data, period)   # docx / pdf / image added in Module 4b


def detect_type(filename):
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return {"csv": "csv", "xlsx": "xlsx", "docx": "docx", "pdf": "pdf",
            "png": "image", "jpg": "image", "jpeg": "image"}.get(ext)


def sha256(data: bytes):
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------ normalisation
def _yes(v):
    s = str(v).strip().lower()
    if s in ("yes", "y", "1", "true", "working", "t"):
        return True
    if s in ("no", "n", "0", "false", "off", "holiday", "f"):
        return False
    return None


def normalize(raw_rows):
    """Raw dicts -> uniform row dicts with ISO date strings (JSON-safe)."""
    rows = []
    for r in raw_rows:
        row = {
            "line": r.get("line"), "confidence": float(r.get("confidence", 1.0)),
            "include": True, "issues": [],
            "record_type": (str(r.get("record_type") or "").strip().lower() or None),
            "event_type": str(r.get("event_type") or "").strip(),
            "title": str(r.get("title") or "").strip(),
            "scope": (str(r.get("scope") or "college").strip().lower()),
            "department": str(r.get("department") or "").strip().upper(),
            "section": str(r.get("section") or "").strip().upper(),
            "teaching_impact": str(r.get("teaching_impact") or "").strip().upper().replace(" ", "_"),
            "category": str(r.get("category") or "").strip()[:40],
            "follow_weekday": str(r.get("follow_weekday") or "").strip().title(),
            "notes": str(r.get("notes") or "").strip()[:255],
            "raw_text": str(r.get("raw_text") or "")[:300],
            "is_working": None,
        }
        s, e1 = parse_date(r.get("start_date"))
        e, e2 = parse_date(r.get("end_date"))
        row["start_date"] = s.isoformat() if s else None
        row["end_date"] = e.isoformat() if e else (s.isoformat() if s else None)
        for note in (e1, e2):
            if note:
                row["issues"].append({"level": "error", "msg": note})
        if r.get("is_working") is not None:
            row["is_working"] = _yes(r["is_working"])
        if row["record_type"] is None:
            row["record_type"] = "day" if (not row["event_type"] and row["is_working"] is not None) else "event"
        rows.append(row)
    return rows


# --------------------------------------------------------------- validation
def _add(row, level, msg):
    row["issues"].append({"level": level, "msg": msg})


def _overlap(a, b):
    return a["start_date"] <= b["end_date"] and b["start_date"] <= a["end_date"]


def _same_target(a, b):
    return (a["scope"], a["department"], a["section"]) == (b["scope"], b["department"], b["section"])


def validate(cur, period_id, rows):
    """Re-runnable. Clears old issues (except parse errors), re-checks everything.
    cur = dictionary cursor. Returns summary dict."""
    cur.execute("SELECT id, start_date, end_date FROM academic_periods WHERE id=%s", (period_id,))
    period = cur.fetchone()
    if not period:
        raise ValueError("Academic period not found.")
    ps, pe = period["start_date"].isoformat(), period["end_date"].isoformat()

    cur.execute("SELECT id, code, name, COALESCE(teaching_impact,'BLOCK_ALL') AS impact "
                "FROM calendar_event_types WHERE is_active = 1")
    types = cur.fetchall()
    by_code = {t["code"]: t for t in types}
    by_name = {t["name"].strip().lower(): t for t in types}
    cur.execute("SELECT id, code FROM departments")
    depts = {d["code"].upper(): d["id"] for d in cur.fetchall()}
    cur.execute("SELECT s.id, d.code AS dept, s.section_label FROM sections s "
                "JOIN departments d ON d.id = s.department_id WHERE s.academic_period_id=%s", (period_id,))
    sections = {(s["dept"].upper(), str(s["section_label"]).upper()): s["id"] for s in cur.fetchall()}

    cur.execute("SELECT e.event_type_id, e.start_date, e.end_date, e.scope, e.department_id, e.section_id "
                "FROM calendar_events e WHERE e.academic_period_id=%s OR e.academic_period_id IS NULL",
                (period_id,))
    existing = {(x["event_type_id"], x["start_date"].isoformat(), x["end_date"].isoformat(),
                 x["scope"], x["department_id"], x["section_id"]) for x in cur.fetchall()}

    for row in rows:
        row["issues"] = [i for i in row["issues"] if i["msg"].startswith("Unreadable date")]
        row["type_id"] = row["department_id"] = row["section_id"] = None
        row["duplicate"] = False
        row["effective_impact"] = None
        if row["confidence"] < LOW_CONFIDENCE:
            _add(row, "warning", f"Low extraction confidence ({row['confidence']:.0%}) - verify this row")
        if not row["start_date"] and not any(i["level"] == "error" for i in row["issues"]):
            _add(row, "error", "Start date is missing")
        if row["start_date"] and row["end_date"] < row["start_date"]:
            _add(row, "error", "End date is before start date")
        if row["start_date"]:
            if row["end_date"] < ps or row["start_date"] > pe:
                _add(row, "error", f"Dates are outside the academic period ({ps} to {pe})")
            elif row["start_date"] < ps or row["end_date"] > pe:
                _add(row, "warning", "Dates extend beyond the academic period")

        if row["record_type"] == "day":
            if row["is_working"] is None:
                _add(row, "error", "Working-day record needs is_working = yes/no")
            if row["end_date"] != row["start_date"]:
                _add(row, "warning", "Working-day records are single dates; end date ignored")
            continue
        if row["record_type"] != "event":
            _add(row, "error", f"Unknown record_type '{row['record_type']}' (use event or day)")
            continue

        # ---- event rows
        t = by_code.get(re.sub(r"[\s\-]+", "_", row["event_type"].upper())) or by_name.get(row["event_type"].lower())
        if not t:
            guess = difflib.get_close_matches(row["event_type"].upper(), list(by_code), n=2, cutoff=0.5)
            _add(row, "error", f"Unknown event type '{row['event_type']}'"
                 + (f" - did you mean {' / '.join(guess)}?" if guess else ""))
        else:
            row["type_id"] = t["id"]
            row["event_type"] = t["code"]
        if not row["title"]:
            _add(row, "error", "Title is missing")
        imp = row["teaching_impact"]
        if imp and imp not in IMPACTS:
            _add(row, "error", f"Unknown teaching_impact '{imp}'")
            imp = ""
        row["effective_impact"] = imp or (t["impact"] if t else None)
        if row["follow_weekday"]:
            if row["follow_weekday"] not in WEEKDAYS:
                _add(row, "error", f"follow_weekday must be one of {', '.join(WEEKDAYS)}")
            elif row["effective_impact"] not in ALLOWING:
                _add(row, "warning", "follow_weekday only applies to special working days; ignored")
        if row["scope"] not in ("college", "department", "section"):
            _add(row, "error", f"Unsupported scope '{row['scope']}' (college / department / section)")
        elif row["scope"] in ("department", "section"):
            row["department_id"] = depts.get(row["department"])
            if not row["department_id"]:
                _add(row, "error", f"Department '{row['department']}' not found")
            elif row["scope"] == "section":
                row["section_id"] = sections.get((row["department"], row["section"]))
                if not row["section_id"]:
                    _add(row, "error", f"Section {row['department']}-{row['section']} not found in this period")
        if row["type_id"] and row["start_date"] and not any(i["level"] == "error" for i in row["issues"]):
            key = (row["type_id"], row["start_date"], row["end_date"], row["scope"],
                   row["department_id"], row["section_id"])
            if key in existing:
                _add(row, "warning", "Identical event already exists in the calendar (will be skipped)")
                row["duplicate"] = True

    # ---- cross-row checks (inside the file)
    ev = [r for r in rows if r["record_type"] == "event" and r["start_date"] and r["end_date"]
          and not any(i["level"] == "error" for i in r["issues"])]
    for i, a in enumerate(ev):
        for b in ev[i + 1:]:
            if not _overlap(a, b) or not _same_target(a, b):
                continue
            if (a["type_id"], a["start_date"], a["end_date"]) == (b["type_id"], b["start_date"], b["end_date"]):
                _add(b, "warning", f"Duplicate of line {a['line']}")
                b["duplicate"] = True
            elif (a["effective_impact"] in ALLOWING) != (b["effective_impact"] in ALLOWING):
                _add(a, "warning", f"Conflicts with line {b['line']} (special working day wins)")
                _add(b, "warning", f"Conflicts with line {a['line']} (special working day wins)")
            else:
                _add(a, "warning", f"Overlaps line {b['line']} ('{b['title']}')")
    seen = {}
    for r in rows:
        if r["record_type"] == "day" and r["start_date"]:
            if r["start_date"] in seen:
                _add(r, "error", f"Date already given on line {seen[r['start_date']]}")
            seen[r["start_date"]] = r["line"]

    for r in rows:
        errs = [i for i in r["issues"] if i["level"] == "error"]
        r["status"] = "error" if errs else ("warning" if r["issues"] else "ok")
    return summarize(rows)


def summarize(rows):
    s = {"total": len(rows), "ok": 0, "warning": 0, "error": 0, "importable": 0}
    for r in rows:
        s[r["status"]] += 1
        if r["status"] != "error" and r["include"] and not r.get("duplicate"):
            s["importable"] += 1
    return s


def importable(rows):
    return [r for r in rows if r["include"] and r["status"] != "error" and not r.get("duplicate")]


# ------------------------------------------------------------------- commit
def commit(cur, period_id, rows, user_id, batch_id):
    """Insert validated rows. Returns {'events': [...inserted event dicts], 'days': n}.
    Caller handles replace-mode deletion, session cancelling, calendar_days rebuild, replan."""
    inserted, days = [], 0
    cur.execute("SELECT id, COALESCE(teaching_impact,'BLOCK_ALL') AS impact FROM calendar_event_types")
    default_impact = {t["id"]: t["impact"] for t in cur.fetchall()}
    for r in importable(rows):
        if r["record_type"] == "day":
            d = datetime.strptime(r["start_date"], "%Y-%m-%d").date()
            working = 1 if r["is_working"] else 0
            dtype = ("SPECIAL_WORKING" if d.strftime("%A") == "Sunday" else "WORKING") if working else "NON_WORKING"
            cur.execute(
                "INSERT INTO calendar_days (academic_period_id, calendar_date, weekday, day_type, "
                " is_working, is_teaching, follow_weekday, label, source, is_locked) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'import',1) "
                "ON DUPLICATE KEY UPDATE day_type=VALUES(day_type), is_working=VALUES(is_working), "
                " is_teaching=VALUES(is_teaching), follow_weekday=VALUES(follow_weekday), "
                " label=VALUES(label), source='import', is_locked=1",
                (period_id, d, d.strftime("%A"), dtype, working, working,
                 r["follow_weekday"] if r["follow_weekday"] in WEEKDAYS else None, r["title"] or None))
            days += 1
            continue
        override = r["effective_impact"] if r["effective_impact"] != default_impact.get(r["type_id"]) else None
        follow = r["follow_weekday"] if (r["effective_impact"] in ALLOWING and r["follow_weekday"] in WEEKDAYS) else None
        cur.execute(
            "INSERT INTO calendar_events (academic_period_id, event_type_id, title, start_date, end_date, "
            " scope, department_id, section_id, follow_weekday, impact_override, category, notes, "
            " source, import_batch_id, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'import',%s,%s)",
            (period_id, r["type_id"], r["title"][:150], r["start_date"], r["end_date"], r["scope"],
             r["department_id"], r["section_id"], follow, override, r["category"] or None,
             r["notes"] or None, batch_id, user_id))
        inserted.append({
            "id": cur.lastrowid, "title": r["title"], "start_date": r["start_date"], "end_date": r["end_date"],
            "start_time": None, "end_time": None, "scope": r["scope"], "department_id": r["department_id"],
            "section_id": r["section_id"], "academic_period_id": period_id, "impact": r["effective_impact"]})
    return {"events": inserted, "days": days}


def dumps(rows):
    return json.dumps(rows, default=str)