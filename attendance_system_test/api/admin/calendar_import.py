"""
api/admin/calendar_import.py - upload -> preview/correct -> commit for academic calendars.
Registered at /admin/calendar/import
"""
import json
import logging
import os
from datetime import datetime

from flask import (Blueprint, render_template, request, redirect, url_for, flash,
                   Response, current_app)
from flask_login import current_user

from core.db import get_db
from auth.helpers import admin_required, log_audit, get_client_ip
from services import calendar_import as ci
from services.calendar_service import rebuild_calendar_days
from api.admin.academic_calendar import _cancel_sessions, _restore_sessions, _replan

logger = logging.getLogger(__name__)
cal_import_bp = Blueprint("cal_import", __name__, template_folder="../../templates/admin")

MAX_BYTES = 15 * 1024 * 1024
EDIT_FIELDS = ("event_type", "title", "start_date", "end_date", "scope", "department",
               "section", "teaching_impact", "category", "follow_weekday", "is_working",
               "notes", "raw_text")


def _cur():
    return get_db().cursor(dictionary=True, buffered=True)


def _batch(cur, batch_id):
    cur.execute("SELECT * FROM calendar_import_batches WHERE id=%s", (batch_id,))
    b = cur.fetchone()
    if b:
        b["rows"] = json.loads(b["rows_json"])
    return b


def _save(cur, batch_id, rows, mode=None):
    cur.execute("UPDATE calendar_import_batches SET rows_json=%s, summary_json=%s"
                + (", mode=%s" if mode else "") + " WHERE id=%s",
                (ci.dumps(rows), json.dumps(ci.summarize(rows)))
                + ((mode,) if mode else ()) + (batch_id,))


@cal_import_bp.route("/")
@admin_required
def index():
    cur = _cur()
    cur.execute("SELECT id, name, academic_year, sem_number FROM academic_periods "
                "WHERE is_archived=0 ORDER BY start_date DESC")
    periods = cur.fetchall()
    cur.execute("SELECT b.id, b.filename, b.source_type, b.status, b.created_at, p.name AS period "
                "FROM calendar_import_batches b JOIN academic_periods p ON p.id=b.academic_period_id "
                "ORDER BY b.id DESC LIMIT 10")
    return render_template("admin/calendar_import.html", periods=periods, recent=cur.fetchall(),
                           batch=None, formats=sorted(ci.SUPPORTED))


@cal_import_bp.route("/template.csv")
@admin_required
def template():
    return Response(ci.TEMPLATE_CSV, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=calendar_template.csv"})


@cal_import_bp.route("/upload", methods=["POST"])
@admin_required
def upload():
    period_id = request.form.get("period_id", type=int)
    mode = request.form.get("mode", "append")
    f = request.files.get("file")
    if not period_id or not f or not f.filename:
        flash("Choose an academic period and a file.", "danger")
        return redirect(url_for("cal_import.index"))
    data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        flash("File is larger than 15 MB.", "danger")
        return redirect(url_for("cal_import.index"))
    kind = ci.detect_type(f.filename)
    if kind not in ci.SUPPORTED:
        flash("Supported files: CSV, Excel (.xlsx), Word (.docx), PDF, and images (.png / .jpg).", "warning")
        return redirect(url_for("cal_import.index"))

    cur = _cur()
    try:
        cur.execute("SELECT id, start_date, end_date FROM academic_periods WHERE id=%s", (period_id,))
        rows = ci.normalize(ci.parse(kind, data, cur.fetchone()))
        if not rows:
            flash("The file has no data rows.", "warning")
            return redirect(url_for("cal_import.index"))
        ci.validate(cur, period_id, rows)
        digest = ci.sha256(data)
        folder = os.path.join(current_app.config.get("UPLOAD_FOLDER", "uploads"), "calendar_imports")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, f"{digest}.{kind}"), "wb") as out:
            out.write(data)
        cur.execute(
            "INSERT INTO calendar_import_batches (academic_period_id, source_type, filename, sha256, "
            " mode, rows_json, summary_json, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (period_id, kind, f.filename[:255], digest, "replace" if mode == "replace" else "append",
             ci.dumps(rows), json.dumps(ci.summarize(rows)), current_user.id))
        batch_id = cur.lastrowid
        get_db().commit()
        return redirect(url_for("cal_import.preview", batch_id=batch_id))
    except ValueError as exc:
        get_db().rollback()
        flash(str(exc), "danger")
    except Exception as exc:
        get_db().rollback()
        logger.exception("calendar import upload failed")
        flash(f"Could not read the file: {exc}", "danger")
    return redirect(url_for("cal_import.index"))


@cal_import_bp.route("/<int:batch_id>")
@admin_required
def preview(batch_id):
    cur = _cur()
    batch = _batch(cur, batch_id)
    if not batch:
        flash("Import not found.", "warning")
        return redirect(url_for("cal_import.index"))
    cur.execute("SELECT code, name FROM calendar_event_types WHERE is_active=1 ORDER BY id")
    return render_template("admin/calendar_import.html", batch=batch, summary=ci.summarize(batch["rows"]),
                           types=cur.fetchall(), impacts=ci.IMPACTS, periods=[], recent=[], formats=[])


def _apply_form(rows):
    """Admin corrections from the preview form -> fresh normalised rows."""
    raw = []
    for i, old in enumerate(rows):
        r = {k: request.form.get(f"{k}_{i}", "") for k in EDIT_FIELDS}
        r["is_working"] = r["is_working"] or None
        r["line"], r["confidence"] = old["line"], old["confidence"]
        r["record_type"] = old["record_type"]
        raw.append(r)
    new = ci.normalize(raw)
    for i, row in enumerate(new):
        row["include"] = request.form.get(f"include_{i}") == "1"
        row["record_type"] = rows[i]["record_type"]
    return new


@cal_import_bp.route("/<int:batch_id>/save", methods=["POST"])
@admin_required
def save(batch_id):
    cur = _cur()
    batch = _batch(cur, batch_id)
    if not batch or batch["status"] != "preview":
        flash("This import is no longer editable.", "warning")
        return redirect(url_for("cal_import.index"))
    mode = "replace" if request.form.get("mode") == "replace" else "append"
    rows = _apply_form(batch["rows"])
    ci.validate(cur, batch["academic_period_id"], rows)
    _save(cur, batch_id, rows, mode)
    get_db().commit()

    if request.form.get("action") != "commit":
        flash("Re-checked. Review the highlighted rows.", "info")
        return redirect(url_for("cal_import.preview", batch_id=batch_id))

    bad = [r["line"] for r in rows if r["include"] and r["status"] == "error"]
    if bad:
        flash(f"Fix or untick rows with errors before importing (lines {', '.join(map(str, bad[:10]))}).", "danger")
        return redirect(url_for("cal_import.preview", batch_id=batch_id))
    return _commit(cur, batch, rows, mode)


def _commit(cur, batch, rows, mode):
    conn = get_db()
    pid = batch["academic_period_id"]
    try:
        if mode == "replace":                         # undo earlier imports for this period
            cur.execute("SELECT id FROM calendar_events WHERE academic_period_id=%s AND source='import'", (pid,))
            for old in cur.fetchall():
                _restore_sessions(cur, old["id"])
            cur.execute("DELETE FROM calendar_events WHERE academic_period_id=%s AND source='import'", (pid,))
            cur.execute("DELETE FROM calendar_days WHERE academic_period_id=%s AND source='import'", (pid,))
            ci.validate(cur, pid, rows)               # duplicates are judged AFTER the wipe

        todo = ci.importable(rows)
        if not todo:
            conn.rollback()
            flash("Nothing to import (all rows are excluded, duplicates, or have errors).", "warning")
            return redirect(url_for("cal_import.preview", batch_id=batch["id"]))

        result = ci.commit(cur, pid, rows, current_user.id, batch["id"])
        cancelled = 0
        for ev in result["events"]:
            if ev["impact"] not in ci.ALLOWING and ev["impact"] != "INFO_ONLY":
                cancelled += _cancel_sessions(cur, ev)

        rebuild_calendar_days(cur, pid)
        dates = [datetime.strptime(x, "%Y-%m-%d").date()
                 for r in todo for x in (r["start_date"], r["end_date"])]
        _replan(cur, min(dates), max(dates), pid)

        cur.execute(
            "UPDATE academic_calendars SET source_type=%s, source_filename=%s, source_sha256=%s, "
            " imported_by=%s, imported_at=NOW(), status='published' WHERE academic_period_id=%s",
            (batch["source_type"], batch["filename"], batch["sha256"], current_user.id, pid))
        cur.execute("UPDATE calendar_import_batches SET status='committed', committed_at=NOW(), "
                    "rows_json=%s WHERE id=%s", (ci.dumps(rows), batch["id"]))
        conn.commit()
        try:
            log_audit(user_id=current_user.id, action="calendar_import", target_table="calendar_import_batches",
                      target_id=batch["id"], new_value=json.dumps({"events": len(result["events"]),
                      "days": result["days"], "file": batch["filename"], "mode": mode}),
                      ip_address=get_client_ip())
        except Exception as exc:
            logger.warning("audit failed: %s", exc)
        flash(f"Imported {len(result['events'])} events and {result['days']} working-day records"
              + (f"; {cancelled} scheduled class(es) cancelled." if cancelled else "."), "success")
        return redirect(url_for("acad_calendar.index", period_id=pid))
    except Exception as exc:
        conn.rollback()
        logger.exception("calendar import commit failed")
        flash(f"Import failed and was rolled back: {exc}", "danger")
        return redirect(url_for("cal_import.preview", batch_id=batch["id"]))


@cal_import_bp.route("/<int:batch_id>/discard", methods=["POST"])
@admin_required
def discard(batch_id):
    cur = _cur()
    cur.execute("UPDATE calendar_import_batches SET status='discarded' WHERE id=%s AND status='preview'", (batch_id,))
    get_db().commit()
    flash("Import discarded.", "info")
    return redirect(url_for("cal_import.index"))