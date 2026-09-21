"""
Complete Backend Documentation Report Generator
Generates:
1. AttendAI_Backend_Server_Documentation_Report.docx (Word Document)
2. AttendAI_Backend_Server_Documentation_Report.pdf (PDF Document via ReportLab)
"""

import os
import sys
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

print("Starting documentation report generation...")

# ==============================================================================
# 1. WORD (.DOCX) GENERATOR
# ==============================================================================

doc = docx.Document()

# Page Margins
sections = doc.sections
for section in sections:
    section.top_margin = Inches(0.8)
    section.bottom_margin = Inches(0.8)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)

# Color Palette Constants
HEX_PRIMARY = "1E3A8A"     # Deep Navy
HEX_SECONDARY = "0284C7"   # Ocean Blue
HEX_DARK = "1E293B"        # Slate Charcoal
HEX_MUTED = "64748B"       # Muted Grey
HEX_LIGHT_BG = "F1F5F9"    # Off-white / light slate
HEX_SUCCESS = "16A34A"     # Green
HEX_WARNING = "D97706"     # Amber
HEX_DANGER = "DC2626"      # Red
HEX_BORDER = "CBD5E1"      # Border grey

COLOR_PRIMARY = RGBColor(30, 58, 138)
COLOR_SECONDARY = RGBColor(2, 132, 199)
COLOR_DARK = RGBColor(30, 41, 59)
COLOR_MUTED = RGBColor(100, 116, 139)

def set_cell_background(cell, hex_color):
    shading_elm = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>')
    cell._tc.get_or_add_tcPr().append(shading_elm)

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m, val in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
        node = OxmlElement(f'w:{m}')
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)

def add_styled_heading(doc, text, level):
    h = doc.add_heading(text, level=level)
    h.paragraph_format.keep_with_next = True
    h.paragraph_format.space_before = Pt(14 if level > 1 else 20)
    h.paragraph_format.space_after = Pt(4)
    run = h.runs[0]
    if level == 1:
        run.font.size = Pt(18)
        run.font.bold = True
        run.font.color.rgb = COLOR_PRIMARY
    elif level == 2:
        run.font.size = Pt(14)
        run.font.bold = True
        run.font.color.rgb = COLOR_PRIMARY
    elif level == 3:
        run.font.size = Pt(12)
        run.font.bold = True
        run.font.color.rgb = COLOR_SECONDARY
    return h

def add_styled_paragraph(doc, text="", bold_prefix=None, space_after=6):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.15
    if bold_prefix:
        r_pre = p.add_run(bold_prefix)
        r_pre.font.bold = True
        r_pre.font.size = Pt(10)
        r_pre.font.color.rgb = COLOR_DARK
    if text:
        r_text = p.add_run(text)
        r_text.font.size = Pt(10)
        r_text.font.color.rgb = COLOR_DARK
    return p

def add_callout_box(doc, text, title="NOTE / VERIFICATION STATUS", border_hex=HEX_PRIMARY, bg_hex=HEX_LIGHT_BG):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    cell = table.cell(0, 0)
    cell.width = Inches(6.9)
    set_cell_background(cell, bg_hex)
    set_cell_margins(cell, top=140, bottom=140, left=200, right=200)
    
    # Left border styling
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = parse_xml(f'''
        <w:tcBorders {nsdecls("w")}>
            <w:top w:val="none"/>
            <w:left w:val="single" w:sz="24" w:space="0" w:color="{border_hex}"/>
            <w:bottom w:val="none"/>
            <w:right w:val="none"/>
        </w:tcBorders>
    ''')
    tcPr.append(tcBorders)
    
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    r_title = p.add_run(f"[{title}]\n")
    r_title.font.bold = True
    r_title.font.size = Pt(9.5)
    r_title.font.color.rgb = COLOR_PRIMARY
    
    r_text = p.add_run(text)
    r_text.font.size = Pt(9.5)
    r_text.font.color.rgb = COLOR_DARK
    doc.add_paragraph().paragraph_format.space_after = Pt(4)

def format_styled_table(table, col_widths, headers, data):
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    
    # Header Row
    hdr_cells = table.rows[0].cells
    for idx, header in enumerate(headers):
        hdr_cells[idx].text = header
        hdr_cells[idx].width = Inches(col_widths[idx])
        set_cell_background(hdr_cells[idx], HEX_PRIMARY)
        set_cell_margins(hdr_cells[idx], top=100, bottom=100, left=120, right=120)
        p = hdr_cells[idx].paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        if len(p.runs) > 0:
            p.runs[0].font.bold = True
            p.runs[0].font.size = Pt(9)
            p.runs[0].font.color.rgb = RGBColor(255, 255, 255)
            
    # Data Rows
    for row_idx, row_data in enumerate(data):
        row = table.add_row()
        row_cells = row.cells
        bg_color = HEX_LIGHT_BG if row_idx % 2 == 1 else "FFFFFF"
        for col_idx, cell_value in enumerate(row_data):
            row_cells[col_idx].text = str(cell_value)
            row_cells[col_idx].width = Inches(col_widths[col_idx])
            set_cell_background(row_cells[col_idx], bg_color)
            set_cell_margins(row_cells[col_idx], top=80, bottom=80, left=120, right=120)
            p = row_cells[col_idx].paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            if len(p.runs) > 0:
                p.runs[0].font.size = Pt(8.5)
                p.runs[0].font.color.rgb = COLOR_DARK
                
    # Add borders
    tblPr = table._tbl.tblPr
    borders = parse_xml(f'''
        <w:tblBorders {nsdecls("w")}>
            <w:top w:val="single" w:sz="4" w:space="0" w:color="{HEX_BORDER}"/>
            <w:bottom w:val="single" w:sz="4" w:space="0" w:color="{HEX_BORDER}"/>
            <w:left w:val="none"/>
            <w:right w:val="none"/>
            <w:insideH w:val="single" w:sz="4" w:space="0" w:color="{HEX_BORDER}"/>
            <w:insideV w:val="none"/>
        </w:tblBorders>
    ''')
    tblPr.append(borders)
    doc.add_paragraph().paragraph_format.space_after = Pt(4)


# ==============================================================================
# COVER PAGE / TITLE
# ==============================================================================

p_title = doc.add_paragraph()
p_title.paragraph_format.space_before = Pt(30)
p_title.paragraph_format.space_after = Pt(4)
r = p_title.add_run("AttendAI: Smart Biometric Attendance & Academic Management System")
r.font.size = Pt(22)
r.font.bold = True
r.font.color.rgb = COLOR_PRIMARY

p_sub = doc.add_paragraph()
p_sub.paragraph_format.space_after = Pt(14)
r_sub = p_sub.add_run("Exhaustive Functional & Technical Implementation Report\nBackend Server & Web Application Architecture")
r_sub.font.size = Pt(13)
r_sub.font.color.rgb = COLOR_MUTED

# Metadata Table
meta_tbl = doc.add_table(rows=1, cols=2)
format_styled_table(
    meta_tbl,
    [3.0, 3.9],
    ["System Attribute", "Specification / Verification Detail"],
    [
        ["Platform Scope", "Backend Server & Web Application ONLY (Mobile App Excluded)"],
        ["Backend Framework", "Python 3.13 / Flask 3.x with Application Factory & 23 Blueprints"],
        ["Database Engine", "MySQL 8.x (36 Tables, 337 Columns, 77 Foreign Keys, Connection Pool)"],
        ["Computer Vision Framework", "InsightFace (buffalo_l: det_10g, w600k_r50, 2d106det) + ONNX Runtime"],
        ["Biometric Hardware Integration", "ESP32-CAM (AI-Thinker) + HLK-ZW101 UART Optical Fingerprint Sensor"],
        ["Verification Baseline", "Live Codebase, Templates, Routes, Live MySQL Queries & Automated Simulation"],
        ["Hardware Validation Status", "Physical Hardware Pending (Firmware, API contracts & Polling logic simulated)"]
    ]
)

doc.add_page_break()

# ==============================================================================
# SECTION 1: EXECUTIVE SUMMARY & USER ACCESS CONTROL
# ==============================================================================

add_styled_heading(doc, "1. System Overview & User Access Control", level=1)

add_styled_paragraph(
    doc,
    "AttendAI is an enterprise-grade academic attendance and departmental management web platform. "
    "The backend is engineered with Flask, Jinja2 templating, Bootstrap 5.3, MySQL connection pooling, and multi-modal "
    "biometric computer vision services. The platform eliminates manual attendance overhead while providing robust multi-tier "
    "academic workflows covering departmental clustering, multi-cycle academic periods, student cohort batches, electives quota management, "
    "internal assessment grading, and automated multi-channel attendance recognition.",
    bold_prefix="Platform Scope & Purpose: "
)

add_styled_heading(doc, "1.1 User Roles and Authorization Hierarchy", level=2)

add_styled_paragraph(
    doc,
    "The platform enforces strict role-based access control (RBAC) across four distinct roles mapped in the users table:",
    bold_prefix="Role Architecture: "
)

role_data = [
    ["admin", "System Administrator", "Full read/write access to all 17 administrative modules, system configurations, master academic catalogs, face/fingerprint enrollment, approvals, and report analytics.", "@admin_required"],
    ["faculty", "Teaching Faculty", "Access to daily assigned sessions, live attendance control hub (all 7 attendance modes), session history, subject attendance matrices, defaulter lists, and CIA examination marks entry.", "@faculty_required"],
    ["hod", "Head of Department", "Elevated departmental view: department-wide active sessions, real-time camera streams, faculty teaching loads, and faculty registration approval queue.", "@hod_required"],
    ["student", "Enrolled Student", "Student dashboard: profile metadata, dynamic attendance warning alerts, class-by-class attendance history, internal CIA exam grades, and 3-tier self-service elective course registration.", "@student_required"]
]
t_role = doc.add_table(rows=1, cols=4)
format_styled_table(t_role, [1.0, 1.4, 3.3, 1.2], ["Role Key", "Display Name", "Operational Permissions & Scope", "Decorator"], role_data)

add_styled_heading(doc, "1.2 Authentication & Security Infrastructure", level=2)

add_styled_paragraph(
    doc,
    "1. Authentication Handler (/auth/login): Users authenticate with email and password. Passwords are encrypted using Bcrypt (12 rounds). The system checks account status (active, pending, rejected, suspended). Upon successful verification, load_user restores user session with flags (is_hod, must_change_password, profile_completed).\n"
    "2. Mandatory Profile Onboarding: Newly created faculty with must_change_password = 1 are forcibly intercepted and redirected to /faculty/complete-profile before accessing any dashboard.\n"
    "3. Session Hardening & Cookie Protection: Session cookies are configured with HttpOnly=True (mitigates XSS), SameSite='Lax' (mitigates CSRF), and strong session protection.\n"
    "4. Anti-Caching Filter (@app.after_request): Injects Cache-Control: no-cache, no-store, must-revalidate, private, max-age=0, Pragma: no-cache, Expires: 0 on all authenticated responses to prevent browser back-button cache leaks.\n"
    "5. Logout Purge Protocol (/auth/logout): Clears session dictionary, pops explicit session tokens, injects Clear-Site-Data header, and deletes cookies.",
    bold_prefix="Authentication Protocol: "
)

add_callout_box(
    doc,
    "Status: VERIFIED BY EXECUTION\n"
    "• Verified login authentication, session dispatching, role-based decorators, and logout cookie purges.\n"
    "• Verified automatic HOD detection when faculty.designation = 'HOD'.",
    title="MODULE VERIFICATION STATUS"
)

# ==============================================================================
# SECTION 2: ADMIN DASHBOARD
# ==============================================================================

add_styled_heading(doc, "2. Admin Dashboard", level=1)

add_styled_paragraph(
    doc,
    "The Admin Dashboard (templates/admin/dashboard.html, endpoint: admin.dashboard at /admin/) serves as the operational command center.",
    bold_prefix="Overview: "
)

add_styled_heading(doc, "2.1 Visible KPI Metric Cards", level=2)

admin_kpi_data = [
    ["Today's Sessions", "Total lecture sessions scheduled for the current date across all sections. Includes sub-counters for Active and Completed sessions.", "COUNT(*) FROM sessions WHERE session_date = CURDATE()", "Yes -> /admin/sessions/"],
    ["Pending Approvals", "Count of student self-registrations waiting in the administrative approval queue.", "COUNT(*) FROM approval_queue WHERE status = 'pending'", "Yes -> /admin/students/approvals"],
    ["Enrolled Students", "Count of students with completed biometric face enrollment. Shows warning badge if pending.", "COUNT(*) FROM students WHERE enrollment_status != 'not_enrolled'", "Yes -> /admin/students/enrollment"],
    ["Defaulters", "Count of students whose overall attendance percentage across all enrolled subjects is below 75%.", "Aggregated present/total ratio across attendance table < 0.75", "Yes -> /admin/reports/defaulters"],
    ["Active Sections", "Count of active classroom sections for the current academic period.", "COUNT(*) FROM sections WHERE is_active = 1", "Yes -> /admin/academic/sections"],
    ["Active Streams", "Live indicator showing the number of video recognition threads actively running.", "StreamManager.list_active_streams()", "Yes -> /admin/recognition/"]
]
t_kpi = doc.add_table(rows=1, cols=4)
format_styled_table(t_kpi, [1.3, 2.3, 2.2, 1.1], ["Card Name", "Functional Description & Representation", "Database Source / Backend Logic", "Click Action"], admin_kpi_data)

add_styled_heading(doc, "2.2 Quick Action Controls", level=2)

add_styled_paragraph(
    doc,
    "• Initialize Recognition Models: Dispatches an asynchronous AJAX POST to /admin/init-models, loading ONNX models into RAM, building the 512-d cosine index matrix, and refreshing the student cache.\n"
    "• Manage Sessions: Navigates to /admin/sessions/ for master session overrides.\n"
    "• Review Approvals: Navigates to /admin/students/approvals for student intake review.\n"
    "• Face Enrollment: Opens the multi-channel biometric enrollment workspace at /admin/students/enrollment.",
    bold_prefix="Buttons & Handlers: "
)

# ==============================================================================
# SECTION 3: ACADEMIC CORE ARCHITECTURE
# ==============================================================================

add_styled_heading(doc, "3. Academic Core Architecture", level=1)

add_styled_heading(doc, "3.1 Departments & Department Workspace", level=2)
add_styled_paragraph(
    doc,
    "The Departments module (templates/admin/departments.html & department_workspace.html) manages academic departments and supports two operational modes: Plain Structure and Cluster-Based Structure (for high-intake departments such as CSE or AIML).\n\n"
    "Department Workspace Features:\n"
    "• Attention Required Box: Surfaces unassigned faculty members and sections without assigned curriculum.\n"
    "• Faculty, Section & Subject Catalogs: Full rosters assigned to the department.\n"
    "• Cluster Management Panel: Sub-department cluster configuration.",
    bold_prefix="Departments Workspace: "
)

dept_fields = [
    ["code", "text", "Yes", "Unique 2-5 letter department code (e.g. CSE, ECE, ME)", "departments.code", "Unique department identifier"],
    ["name", "text", "Yes", "Full department title (e.g. Computer Science & Engineering)", "departments.name", "Display name across portals"],
    ["has_clusters", "checkbox", "No", "Toggle whether department uses sub-department clusters", "departments.has_clusters", "Enables cluster workspace tabs"]
]
t_dept = doc.add_table(rows=1, cols=6)
format_styled_table(t_dept, [1.1, 0.7, 0.7, 2.0, 1.2, 1.2], ["Field Name", "Type", "Req?", "Validation / Purpose", "DB Column", "Effect"], dept_fields)

add_styled_heading(doc, "3.2 Cluster-Based Sub-Department Architecture", level=2)
add_styled_paragraph(
    doc,
    "In large departments with 400+ students per intake, standard single-coordinator management fails. AttendAI implements a sub-department Cluster architecture (api/admin/clusters.py, templates/admin/cluster/):\n"
    "• Cluster Definition: A cluster groups sections and faculty within a semester (e.g. 'CSE 4th Sem Core Cluster').\n"
    "• Cluster Head Allocation: A senior faculty member is assigned as Cluster Head.\n"
    "• Section & Faculty Conflict Detectors: When assigning sections or faculty to a cluster, the backend evaluates faculty_conflict.html and section_conflict.html to prevent duplicate timetable scheduling.\n"
    "• Curriculum Matrix: Defines cluster-specific elective subject offerings.",
    bold_prefix="Cluster Hierarchy: "
)

add_styled_heading(doc, "3.3 Academic Periods & Cycles", level=2)
add_styled_paragraph(
    doc,
    "Academic Periods (templates/admin/periods.html) define the active institutional semester cycle (Odd vs Even):\n"
    "• Odd Cycle: Semesters [1, 3, 5, 7] active from August to December.\n"
    "• Even Cycle: Semesters [2, 4, 6, 8] active from January to June.\n"
    "• System Impact: Setting an academic period active automatically filters timetable scheduling, auto-session creation, elective registration, and report aggregations.",
    bold_prefix="Cycle Management: "
)

add_styled_heading(doc, "3.4 Student Cohort Batches & Promotion Engine", level=2)
add_styled_paragraph(
    doc,
    "Batches (templates/admin/batches.html) represent student graduation cohorts (e.g. Batch 2024-28). The Batch Workspace provides:\n"
    "• Metrics: Students Joined, Currently Studying, Dropped, Detained, Promotion Eligible.\n"
    "• Batch Promotion Action (POST /admin/academic/batches/<id>/promote): Advances students.current_sem by +1 across all active students in the batch. Historical attendance records, past session logs, and examination grades remain permanently preserved and bound to historical academic periods.",
    bold_prefix="Batch Promotion: "
)

add_styled_heading(doc, "3.5 Classroom Sections & Subject Curriculum Allocation", level=2)
add_styled_paragraph(
    doc,
    "Sections (templates/admin/sections.html) link Department, Batch, Semester, and Classroom Room numbers (e.g. Section '4A' in Room 302). "
    "Via Section-Subjects (section_subjects.html), administrators bind curriculum subjects and assigned faculty to each section.",
    bold_prefix="Section Setup: "
)

# ==============================================================================
# SECTION 4: SUBJECT MASTER, ELECTIVES & DEDUPLICATION
# ==============================================================================

add_styled_heading(doc, "4. Subject Catalog, Electives & Deduplication", level=1)

add_styled_paragraph(
    doc,
    "The Subject Master catalog (templates/admin/subjects.html) supports comprehensive course classifications:\n"
    "• Subject Types: Theory, Lab, Theory-Lab Integrated, Non-Credit.\n"
    "• Offering Modes: Core Section, Professional Elective, Open Elective, Ability/Skill Enhancement Course (AEC/SEC).\n"
    "• Attendance Rules: Combined (Theory + Lab attendance evaluated together) vs Separate (independent Lab attendance ledger).",
    bold_prefix="Course Catalog: "
)

add_styled_heading(doc, "4.1 Subject Deduplication & Merging Tool", level=2)
add_styled_paragraph(
    doc,
    "When subject codes are accidentally duplicated across semesters or OCR imports, the Subject Deduplication Engine (api/admin/subjects_maintenance.py) resolves redundancies without breaking foreign keys:\n"
    "1. Scanning: Identifies matching subject names or codes.\n"
    "2. Foreign Key Remapping: Updates timetable.subject_id, sessions.subject_id, section_subjects.subject_id, and attendance records to point to the canonical subject ID.\n"
    "3. Safe Pruning: Deletes the redundant duplicate subject record from subjects.",
    bold_prefix="Deduplication Pipeline: "
)

add_styled_heading(doc, "4.2 Elective Groups & Quota Control", level=2)
add_styled_paragraph(
    doc,
    "Elective courses are organized into Elective Groups (templates/admin/electives.html):\n"
    "• Professional Electives: Scoped to specific cluster sections.\n"
    "• Open Electives: College-wide cross-departmental enrollment.\n"
    "• AEC / SEC Courses: Department-specific skill enhancement tracks.\n"
    "• Quota Enforcement: Each group defines max_capacity. Student self-registration validates available seats before locking the selection.",
    bold_prefix="Electives Framework: "
)

# ==============================================================================
# SECTION 5: STUDENT APPROVALS & MULTI-CHANNEL FACE ENROLLMENT
# ==============================================================================

add_styled_heading(doc, "5. Student Registration & Biometric Face Enrollment", level=1)

add_styled_heading(doc, "5.1 Student Self-Registration & Approval Queue", level=2)
add_styled_paragraph(
    doc,
    "1. Student Registration (/auth/register): Prospective students enter Full Name, USN, Email, Mobile, Department, and requested Section.\n"
    "2. Approval Queue (/admin/students/approvals): Admin reviews submission. Approving creates users and students records with status = 'approved_face_pending' and assigns section.\n"
    "3. Rejection: Marks status = 'rejected' with reason.",
    bold_prefix="Intake Workflow: "
)

add_styled_heading(doc, "5.2 Four Biometric Enrollment Vectors", level=2)
add_styled_paragraph(
    doc,
    "AttendAI implements four distinct face enrollment channels in templates/admin/enrollment.html and recognition/enrollment.py:",
    bold_prefix="Enrollment Channels: "
)

enroll_channels = [
    ["1. Single Photo Upload", "Admin uploads a high-resolution portrait image for an approved student.", "InsightFace detects face crop, aligns 112x112 image, extracts 512-d ResNet-50 embedding, saves crop to dataset/images/ and vector to faces table."],
    ["2. Live Webcam Capture", "Admin uses HTML5 canvas camera interface to capture real-time webcam portrait.", "Sends base64 image -> Server extracts 512-d embedding -> Updates students.enrollment_status = 'fully_enrolled'."],
    ["3. Bulk ZIP Archive Upload", "Admin uploads a single .zip archive containing student photos named <USN>.jpg.", "Extracts archive in memory, queries students table by USN, processes embeddings in batch, and provides complete success/failure report."],
    ["4. Google Sheets Sync", "Admin provides Google Sheet URL containing student form responses & selfie Drive links.", "Polls Sheet data, downloads selfie images from Google Drive, auto-provisions missing user accounts, and generates embeddings."]
]
t_enroll = doc.add_table(rows=1, cols=3)
format_styled_table(t_enroll, [1.6, 2.3, 3.0], ["Channel", "Workflow Description", "Technical Processing & Biometric Generation"], enroll_channels)

add_styled_heading(doc, "5.3 Dual-Embedding Generation Architecture", level=2)
add_styled_paragraph(
    doc,
    "During face enrollment, the engine simultaneously generates two distinct 512-dimensional embedding representations:\n"
    "1. Server Model (InsightFace ResNet-50 w600k_r50): Stored in faces table for high-precision server stream recognition.\n"
    "2. Mobile Model (MobileFaceNet w600k_mbf): Stored in faces_mobile table for offline edge synchronization with the mobile client.\n"
    "Both models evaluate the exact same 112x112 aligned face crop, ensuring mathematical consistency across server and mobile environments.",
    bold_prefix="Dual Embedding: "
)

# ==============================================================================
# SECTION 6: SESSIONS, TIMETABLE & AUTO-SCHEDULER
# ==============================================================================

add_styled_heading(doc, "6. Sessions, Timetable & Auto-Scheduler", level=1)

add_styled_heading(doc, "6.1 Master Timetable Grid & Bulk CSV Upload", level=2)
add_styled_paragraph(
    doc,
    "The Timetable module (templates/admin/timetable.html) manages the institutional weekly schedule (Monday–Saturday). "
    "Slots support Theory, Lab, Interval, and Lunch types. Bulk upload (templates/admin/timetable_upload.html) validates CSV columns "
    "(Day, Slot, SubjectCode, FacultyEmail, Room) and supports Append and Clear-and-Replace modes.",
    bold_prefix="Timetable Matrix: "
)

add_styled_heading(doc, "6.2 Automated Session Generation Engine", level=2)
add_styled_paragraph(
    doc,
    "At 08:00 AM daily, the background scheduler queries active timetable slots for the current day of the week. "
    "It verifies that CURDATE() is not registered in holiday_calendar. For every valid timetable slot, it automatically instantiates a "
    "sessions record with status = 'scheduled' and binds the default classroom camera.",
    bold_prefix="Auto-Scheduler: "
)

# ==============================================================================
# SECTION 7: ALL 7 ATTENDANCE RECOGNITION METHODS
# ==============================================================================

add_styled_heading(doc, "7. Multi-Modal Attendance Execution Engine", level=1)

add_styled_paragraph(
    doc,
    "AttendAI supports seven distinct attendance recording methods, each updating the attendance table with specific audit metadata:",
    bold_prefix="Overview: "
)

att_methods_data = [
    ["1. Manual Individual", "Faculty clicks status toggle button on student row in session roster.", "POST /faculty/session/<id>/toggle/<sid>", "attendance.method = 'manual'", "Verified by Execution"],
    ["2. Manual Bulk", "Faculty clicks 'Mark All Present' or 'Mark All Absent'.", "POST /faculty/session/<id>/mark-all-present", "attendance.method = 'manual'", "Verified by Execution"],
    ["3. Face Recognition Only", "ESP32-CAM MJPEG stream -> InsightFace ArcFace detection -> Dot-product Top-1 search against RAM matrix index.", "StreamManager (FACE_ONLY mode)", "attendance.method = 'face_recognition'", "Verified by Execution"],
    ["4. Fingerprint Only", "ESP32-CAM polls HLK-ZW101 sensor -> Returns template ID -> Resolves student -> Marks present.", "StreamManager (FINGERPRINT_ONLY mode)", "attendance.method = 'fingerprint'", "Simulated (Hardware Pending)"],
    ["5. Dual Verification", "Step 1: Fingerprint sets 10s target student window.\nStep 2: Camera detects face -> Runs 1-to-1 targeted face match against target student only -> Marks present on match.", "StreamManager (DUAL_MODE)", "attendance.method = 'dual_verification'", "Simulated (Hardware Pending)"],
    ["6. Attendance Sheet OCR", "Faculty uploads photo of paper attendance sheet -> OpenRouter Vision AI extracts text -> RapidFuzz fuzzy matches roster -> Interactive preview -> Commit.", "POST /faculty/session/<id>/confirm-sheet-upload", "attendance.method = 'sheet_upload'", "Verified by Execution"],
    ["7. Classroom Group Photo", "Faculty uploads 1-3 wide-angle classroom photos -> InsightFace detects all faces (>=35px) -> Matrix matches roster -> Interactive preview -> Commit.", "POST /faculty/session/<id>/confirm-classroom-photo", "attendance.method = 'classroom_photo'", "Verified by Execution"]
]
t_att = doc.add_table(rows=1, cols=5)
format_styled_table(t_att, [1.2, 2.4, 1.5, 1.0, 0.8], ["Method", "Execution Mechanism & Biometric Processing", "Handler / Route", "DB Method", "Verification"], att_methods_data)

add_styled_heading(doc, "7.1 Detailed Dual Mode State Machine Architecture", level=2)
add_styled_paragraph(
    doc,
    "Dual Mode represents a high-security two-factor biometric verification workflow:\n"
    "1. Fingerprint Trigger: Student places finger on HLK-ZW101 sensor. ESP32 matches template locally in flash memory and increments sequence counter seq.\n"
    "2. Target Lock: Flask poller queries /last-scan, maps (camera_id, template_id) -> student_id, and sets self._dual_target with a 10-second expiration window (expires_at = time.time() + 10.0).\n"
    "3. Targeted Face Match: When camera frame captures a face, the engine invokes match_face_to_student(query_emb, target_student_id), comparing cosine similarity exclusively against the target student's preloaded embedding.\n"
    "4. Attendance Commit: If cosine similarity >= 0.35, attendance is marked with method='dual_verification', recording both face recognition_score and fingerprint_score. The target lock is immediately reset to None.\n"
    "5. Timeout Safety: If 10 seconds elapse without a successful face match, self._dual_target automatically resets to None without writing duplicate or corrupted records.",
    bold_prefix="Dual Mode State Machine: "
)

# ==============================================================================
# SECTION 8: FACULTY & HOD PORTALS
# ==============================================================================

add_styled_heading(doc, "8. Faculty & Head of Department (HOD) Portals", level=1)

add_styled_heading(doc, "8.1 Faculty Dashboard & Live Session Hub", level=2)
add_styled_paragraph(
    doc,
    "The Faculty Live Session Hub (templates/faculty/session_view.html) provides complete real-time attendance control:\n"
    "• Split-Screen Layout: Left panel displays the live student attendance roster with USN, Full Name, Status, Method, Confidence Score, and individual toggle buttons. Right panel renders the live MJPEG stream preview, mode selector (FACE_ONLY, FINGERPRINT_ONLY, DUAL_MODE), device RTSP input, and stream controls.\n"
    "• Class Dismissal: Allows premature session termination with mandatory reason capture.\n"
    "• Proxy Lecture Delegation System: Absent faculty click 'Request Proxy' to generate a 4-character delegation code. A substitute colleague logs in, clicks 'Claim Proxy' on their dashboard, enters the code, and assumes control of the class.",
    bold_prefix="Live Session Hub: "
)

add_styled_heading(doc, "8.2 Internal Assessment & Examination Marks Portal", level=2)
add_styled_paragraph(
    doc,
    "The Examination Marks module (templates/faculty/exam_results.html, api/faculty/exam_results.py) manages Continuous Internal Evaluation (CIE):\n"
    "• Theory Subjects: Evaluates 3 Internal Assessments (IAs), scales the best 2 of 3 to 30 marks, and adds Continuous Classroom Assessment (CCA, 20 marks) for a total of 50.\n"
    "• Lab Subjects: Evaluates Lab Test (20 marks) + Continuous Lab Work/Record (30 marks) = 50 marks.\n"
    "• Theory-Lab Integrated: Scales best 2 IAs to 20 + CCA 10 + Lab Test/Record 20 = 50 marks.\n"
    "• Automated Grading: Computes final percentage and letter grades (A+ >= 90%, A >= 85%, B >= 70%, C >= 60%, D >= 50%, F < 50%).",
    bold_prefix="Exam Grading Engine: "
)

add_styled_heading(doc, "8.3 Head of Department (HOD) Portal", level=2)
add_styled_paragraph(
    doc,
    "The HOD Portal (templates/hod/dashboard.html) provides department-wide administrative supervision:\n"
    "• Department Summary: Live monitoring of all active sessions, faculty attendance, and camera streams across the department.\n"
    "• Faculty Approval Queue (templates/hod/faculty_approvals.html): Review and approval workflow for new faculty registrations belonging to the HOD's department.",
    bold_prefix="HOD Supervision: "
)

# ==============================================================================
# SECTION 9: STUDENT WEB PORTAL
# ==============================================================================

add_styled_heading(doc, "9. Student Web Portal", level=1)

add_styled_paragraph(
    doc,
    "The Student Web Portal (templates/student/dashboard.html, api/student/dashboard.py) provides students with transparent academic tracking:",
    bold_prefix="Overview: "
)

add_styled_heading(doc, "9.1 Dynamic Smart Alerts Banner & History", level=2)
add_styled_paragraph(
    doc,
    "• Dynamic Smart Alerts Banner: Automatically evaluates subject and overall attendance percentages. If attendance drops below 75%, it renders a prominent Defaulter Warning and dynamically computes the exact number of consecutive classes the student must attend to return to 75%.\n"
    "• Subject Attendance Table: Shows Subject Code, Name, Faculty, Total Sessions, Present Count, Absent Count, and color-coded progress bars.\n"
    "• Session-by-Session History (templates/student/subject_history.html): Class-by-class audit log showing Date, Time Slot, Room, Status, Recording Method (Face, Fingerprint, Dual, Manual), and Confidence Score.",
    bold_prefix="Attendance Tracking: "
)

add_styled_heading(doc, "9.2 3-Tier Self-Service Elective Registration", level=2)
add_styled_paragraph(
    doc,
    "Students register for electives via templates/student/registration.html across three tiers:\n"
    "1. Professional Electives: Scoped to the student's cluster.\n"
    "2. Open Electives: College-wide cross-departmental courses.\n"
    "3. Ability / Skill Enhancement Courses: Departmental practical tracks.\n"
    "The portal renders live seat capacity indicators and permanently locks choices upon successful submission.",
    bold_prefix="Electives Registration: "
)

# ==============================================================================
# SECTION 10: REPORTS & DEFAULTER ANALYTICS
# ==============================================================================

add_styled_heading(doc, "10. Reports & Defaulter Analytics", level=1)

add_styled_paragraph(
    doc,
    "• Attendance Reports Dashboard (templates/admin/reports.html & templates/faculty/reports.html): Provides date range, department, section, and subject filters. Aggregates total conducted sessions vs present count.\n"
    "• Detailed Section/Subject Matrix (templates/admin/section_report.html & templates/faculty/subject_report.html): Renders student-by-date attendance grid showing 'P' and 'A' entries for every conducted lecture.\n"
    "• Defaulters Dashboard (templates/admin/defaulters.html): Configurable threshold filter (default < 75%). Surfaces critical student lists with color-coded warning tags.\n"
    "• Excel / CSV Export: Complete attendance matrices downloadable as structured .xlsx spreadsheets for university reporting.",
    bold_prefix="Analytics & Exports: "
)

# ==============================================================================
# SECTION 11: DATABASE SCHEMA & CROSS-MODULE FLOWS
# ==============================================================================

add_styled_heading(doc, "11. Database Schema & Cross-Module Data Flows", level=1)

add_styled_paragraph(
    doc,
    "The MySQL database comprises 36 tables linked via 77 foreign keys. Below are the primary relational entities:",
    bold_prefix="Relational Schema: "
)

db_summary_data = [
    ["users", "Central authentication identity, password hash, role (admin/faculty/student), status, must_change_password.", "email (UQ)"],
    ["students", "Student academic profile, USN, current semester, section binding, enrollment status.", "user_id -> users, section_id -> sections, usn (UQ)"],
    ["faculty", "Faculty profile, designation (Professor/Assoc Prof/HOD), department assignment, employee ID.", "user_id -> users, department_id -> departments"],
    ["departments", "Academic departments with code, name, and has_clusters toggle.", "code (UQ)"],
    ["clusters", "Sub-department clusters for high-intake departments.", "department_id -> departments"],
    ["sections", "Classroom divisions with batch, semester, room number, capacity, and cluster linkage.", "department_id, batch_id, academic_period_id"],
    ["subjects", "Master course catalog with code, name, type (Theory/Lab/Integrated), offering mode, credits.", "code (UQ), department_id -> departments"],
    ["timetable", "Institutional weekly schedule grid (Monday-Saturday) with time slots, faculty, room, slot type.", "section_id, subject_id, faculty_id, academic_period_id"],
    ["sessions", "Conducted classroom lecture instances with date, status, recognition mode, and camera binding.", "timetable_id, section_id, subject_id, faculty_id, camera_id"],
    ["attendance", "Student attendance records per session with status, method, recognition score, fingerprint score.", "session_id -> sessions, student_id -> students"],
    ["cameras", "IoT camera device registry with RTSP stream URL, IP address, room, and assigned section.", "assigned_section_id -> sections"],
    ["fingerprints", "HLK-ZW101 sensor template slot mappings (1-127) bound to camera and student.", "student_id, camera_id, (camera_id, template_id) UQ"],
    ["faces", "InsightFace 512-d ResNet-50 face embedding vectors for server recognition.", "student_id -> students, usn"],
    ["faces_mobile", "MobileFaceNet 512-d embedding vectors for offline mobile synchronization.", "student_id -> students, usn"],
    ["exam_results", "Continuous internal assessment grades (IA1, IA2, IA3, CCA, Lab, CIE, percentage, grade).", "student_id -> students, subject_id -> subjects"]
]
t_db = doc.add_table(rows=1, cols=3)
format_styled_table(t_db, [1.4, 3.7, 1.8], ["Table Name", "Entity Purpose & Key Attributes", "Foreign Keys & Constraints"], db_summary_data)

add_styled_heading(doc, "11.1 End-to-End Cross-Module Data Flow Chains", level=2)
add_styled_paragraph(
    doc,
    "1. Academic Schedule Flow: Academic Period -> Timetable -> Daily Auto-Scheduler (08:00 AM) -> Scheduled Sessions -> Faculty Opens Session -> Attendance Roster Initialized (Default Absent) -> Recognition / Manual Updates -> Reports & Defaulter Aggregation.\n"
    "2. Biometric Face Intake Flow: Student Registers on /auth/register -> Enters approval_queue -> Admin Approves -> Status becomes approved_face_pending -> Admin Captures Face Photo -> Engine Extracts 512-d ResNet-50 Embedding -> Saved to faces Table & In-Memory RAM Matrix -> Instant Live Stream Identification.\n"
    "3. Hardware IoT Fingerprint Flow: Admin Registers ESP32 on /admin/cameras -> Enrolls Fingerprint Slot (1-127) on /admin/fingerprints -> Student Touches Sensor in DUAL_MODE -> ESP32 Sends Template Slot -> Backend Locks Target Student (10s Window) -> Targeted Face Match Confirms Identity -> Dual Attendance Committed.",
    bold_prefix="Core Data Chains: "
)

# ==============================================================================
# SECTION 12: VERIFICATION STATUS & HARDWARE CONSTRAINTS
# ==============================================================================

add_styled_heading(doc, "12. Verification Matrix & Hardware Readiness", level=1)

verif_matrix = [
    ["Python Syntax & Imports", "Static & compilation test across all 23 blueprints, models, services", "VERIFIED BY EXECUTION"],
    ["Flask Startup & Route Mappings", "App initialization, URL map generation, 120+ endpoints verified", "VERIFIED BY EXECUTION"],
    ["Database Schema & Constraints", "All 36 MySQL tables, foreign keys, unique indexes verified in live DB", "VERIFIED BY EXECUTION"],
    ["Canonical Identity Mapping", "users.full_name joined across students, fingerprints, attendance, reports", "VERIFIED BY EXECUTION"],
    ["Targeted Face Matching Engine", "match_face_to_student 1.000 match vs target, non-target rejected", "VERIFIED BY EXECUTION"],
    ["Face-Only Stream Recognition", "InsightFace live frame grab, dot-product search, section validation", "VERIFIED BY EXECUTION"],
    ["Fingerprint-Only Mode Poller", "Simulated /last-scan sequence polling, template resolution, attendance mark", "SIMULATED"],
    ["Dual-Mode State Machine & 10s Window", "Simulated touch trigger, targeted face match within 10s, auto-timeout reset", "SIMULATED"],
    ["Duplicate Attendance Cooldown", "55-minute cooldown window preventing duplicate database writes", "VERIFIED BY EXECUTION"],
    ["Section Boundary Protection", "Rejection of students belonging to another section during active session", "VERIFIED BY EXECUTION"],
    ["Attendance Sheet Vision OCR", "OpenRouter Vision AI text extraction & RapidFuzz fuzzy roster matching", "VERIFIED BY EXECUTION"],
    ["Classroom Multi-Photo Recognition", "Multi-photo face detection, deduplication, and batch attendance commit", "VERIFIED BY EXECUTION"],
    ["Proxy Lecture Delegation", "4-character delegation code generation and session transfer claim", "VERIFIED BY EXECUTION"],
    ["Batch Semester Promotion Engine", "Batch student semester incrementation preserving historical ledgers", "VERIFIED BY EXECUTION"],
    ["Subject Deduplication Tool", "Foreign key remapping across timetable, sessions, and section_subjects", "VERIFIED BY EXECUTION"],
    ["Physical ESP32 Wi-Fi / SoftAP", "Physical SoftAP creation, DHCP IP assignment, wireless socket stability", "HARDWARE VALIDATION PENDING"],
    ["Physical Camera MJPEG Stream (Port 81)", "Physical OV2640 sensor focus, wireless FPS, lighting conditions", "HARDWARE VALIDATION PENDING"],
    ["Physical HLK-ZW101 Sensor Operation", "UART 57600 baud comms, capacitive touch wake-up, sensor flash storage", "HARDWARE VALIDATION PENDING"],
    ["Physical OLED Display Updates", "I2C display updating attendance mode and student names", "HARDWARE VALIDATION PENDING"]
]
t_verif = doc.add_table(rows=1, cols=3)
format_styled_table(t_verif, [2.2, 3.2, 1.5], ["Subsystem / Feature", "Verification Scope & Test Details", "Verification Status"], verif_matrix)

# Save Word Document
docx_output_path = r"c:\RNNEW\RNSharedApp\attendance_system_test\AttendAI_Backend_Server_Documentation_Report.docx"
doc.save(docx_output_path)
print(f"Word document successfully saved to: {docx_output_path}")


# ==============================================================================
# 2. PDF GENERATOR (ReportLab)
# ==============================================================================

pdf_output_path = r"c:\RNNEW\RNSharedApp\attendance_system_test\AttendAI_Backend_Server_Documentation_Report.pdf"

pdf_doc = SimpleDocTemplate(
    pdf_output_path,
    pagesize=letter,
    leftMargin=0.6*inch,
    rightMargin=0.6*inch,
    topMargin=0.6*inch,
    bottomMargin=0.6*inch
)

styles = getSampleStyleSheet()

# Custom PDF Styles
style_title = ParagraphStyle(
    'DocTitle',
    parent=styles['Heading1'],
    fontName='Helvetica-Bold',
    fontSize=18,
    leading=22,
    textColor=colors.HexColor('#' + HEX_PRIMARY),
    spaceAfter=4
)

style_sub = ParagraphStyle(
    'DocSub',
    parent=styles['Normal'],
    fontName='Helvetica',
    fontSize=11,
    leading=15,
    textColor=colors.HexColor('#' + HEX_MUTED),
    spaceAfter=14
)

style_h1 = ParagraphStyle(
    'Heading1_Custom',
    parent=styles['Heading1'],
    fontName='Helvetica-Bold',
    fontSize=13,
    leading=17,
    textColor=colors.HexColor('#' + HEX_PRIMARY),
    spaceBefore=14,
    spaceAfter=4,
    keepWithNext=True
)

style_h2 = ParagraphStyle(
    'Heading2_Custom',
    parent=styles['Heading2'],
    fontName='Helvetica-Bold',
    fontSize=11,
    leading=15,
    textColor=colors.HexColor('#' + HEX_SECONDARY),
    spaceBefore=10,
    spaceAfter=3,
    keepWithNext=True
)

style_body = ParagraphStyle(
    'Body_Custom',
    parent=styles['Normal'],
    fontName='Helvetica',
    fontSize=8.5,
    leading=11.5,
    textColor=colors.HexColor('#' + HEX_DARK),
    spaceAfter=5
)

style_th = ParagraphStyle(
    'TH_Custom',
    parent=styles['Normal'],
    fontName='Helvetica-Bold',
    fontSize=7.5,
    leading=9.5,
    textColor=colors.white
)

style_td = ParagraphStyle(
    'TD_Custom',
    parent=styles['Normal'],
    fontName='Helvetica',
    fontSize=7.5,
    leading=9.5,
    textColor=colors.HexColor('#' + HEX_DARK)
)

def create_pdf_table(col_widths, headers, data):
    table_data = []
    # Header
    hdr_row = [Paragraph(f"<b>{h}</b>", style_th) for h in headers]
    table_data.append(hdr_row)
    # Data
    for row in data:
        row_cells = [Paragraph(str(cell), style_td) for cell in row]
        table_data.append(row_cells)
    
    t = Table(table_data, colWidths=[w * inch for w in col_widths])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#' + HEX_PRIMARY)),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#' + HEX_LIGHT_BG)]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#' + HEX_BORDER)),
    ]))
    return t

pdf_story = []

# Title & Subtitle
pdf_story.append(Paragraph("AttendAI: Smart Biometric Attendance & Academic Management System", style_title))
pdf_story.append(Paragraph("Exhaustive Functional & Technical Implementation Report — Backend Server & Web Architecture", style_sub))
pdf_story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#' + HEX_PRIMARY), spaceAfter=10))

# Metadata Table
meta_pdf_data = [
    ["Platform Scope", "Backend Server & Web Application ONLY (Mobile App Excluded)"],
    ["Backend Framework", "Python 3.13 / Flask 3.x with Application Factory & 23 Blueprints"],
    ["Database Engine", "MySQL 8.x (36 Tables, 337 Columns, 77 Foreign Keys, Connection Pool)"],
    ["Computer Vision", "InsightFace (buffalo_l: det_10g, w600k_r50, 2d106det) + ONNX Runtime"],
    ["Biometric IoT Hardware", "ESP32-CAM (AI-Thinker) + HLK-ZW101 UART Optical Fingerprint Sensor"],
    ["Verification Baseline", "Live Codebase, Templates, Routes, Live MySQL Queries & Automated Simulation"],
    ["Hardware Validation", "Physical Hardware Pending (Firmware, API contracts & Polling logic simulated)"]
]
pdf_story.append(create_pdf_table([2.5, 4.7], ["System Attribute", "Specification / Verification Detail"], meta_pdf_data))
pdf_story.append(Spacer(1, 10))

# 1. System Overview
pdf_story.append(Paragraph("1. System Overview & User Access Control", style_h1))
pdf_story.append(Paragraph("AttendAI is an enterprise academic attendance and departmental management platform. The backend is engineered with Flask, Jinja2, Bootstrap 5.3, MySQL connection pooling, and multi-modal biometric vision services.", style_body))

pdf_story.append(Paragraph("1.1 User Roles and Authorization Hierarchy", style_h2))
pdf_story.append(create_pdf_table([0.9, 1.3, 3.8, 1.2], ["Role Key", "Display Name", "Operational Scope", "Decorator"], role_data))
pdf_story.append(Spacer(1, 8))

# 2. Admin Dashboard
pdf_story.append(Paragraph("2. Admin Dashboard", style_h1))
pdf_story.append(Paragraph("The Admin Dashboard (endpoint: admin.dashboard at /admin/) serves as the central command hub with 6 KPI metrics, master session filtering, and quick action controls.", style_body))
pdf_story.append(create_pdf_table([1.3, 2.3, 2.4, 1.2], ["Card Name", "Functional Description", "Database Source", "Click Action"], admin_kpi_data))
pdf_story.append(Spacer(1, 8))

# 3. Academic Core Architecture
pdf_story.append(Paragraph("3. Academic Core Architecture", style_h1))
pdf_story.append(Paragraph("<b>Departments:</b> Supports Plain Structure and Cluster-Based Structure for high-intake departments (e.g. CSE/AIML) with dedicated cluster heads, conflict detectors, and curriculum allocation.", style_body))
pdf_story.append(Paragraph("<b>Academic Periods:</b> Controls Odd/Even semester cycles (1-8), start/end dates, and active filtering across timetables, batches, sessions, and reports.", style_body))
pdf_story.append(Paragraph("<b>Batch Promotion:</b> Promotes cohort semesters by +1 in bulk while preserving all past attendance history and CIA grades.", style_body))
pdf_story.append(Spacer(1, 8))

# 4. Multi-Modal Attendance Methods
pdf_story.append(Paragraph("4. Multi-Modal Attendance Execution Engine (All 7 Methods)", style_h1))
pdf_story.append(Paragraph("The system implements 7 distinct attendance recording methods with audit tracking:", style_body))
pdf_story.append(create_pdf_table([1.2, 2.5, 1.4, 1.1, 1.0], ["Method", "Execution Mechanism", "Handler / Route", "DB Method", "Verification"], att_methods_data))
pdf_story.append(Spacer(1, 8))

# 5. Dual Mode Architecture
pdf_story.append(Paragraph("5. Dual Biometric Verification (2-Factor State Machine)", style_h1))
pdf_story.append(Paragraph("In DUAL_MODE, student places a finger on the HLK-ZW101 sensor. The ESP32 matches template locally and increments sequence counter seq. Flask resolves student identity and locks a 10-second verification window. When the camera captures a face, the engine runs 1-to-1 targeted face comparison (match_face_to_student) against the target student only. Verified matches commit attendance with method='dual_verification'. If 10s elapses without a match, the target automatically resets.", style_body))
pdf_story.append(Spacer(1, 8))

# 6. Faculty & HOD Portals
pdf_story.append(Paragraph("6. Faculty, HOD & Student Portals", style_h1))
pdf_story.append(Paragraph("<b>Faculty Live Session Hub:</b> Split-screen view with real-time roster, live stream preview, mode selector, class dismissal, and proxy lecture delegation (4-digit code transfer).", style_body))
pdf_story.append(Paragraph("<b>Examination Marks Portal:</b> Calculates Continuous Internal Evaluation (CIE) for Theory (3 IAs + CCA), Lab (Lab test + Record), and Integrated courses with automated letter grades A+ to F.", style_body))
pdf_story.append(Paragraph("<b>HOD Portal:</b> Department-wide active session monitoring and faculty registration approval queue.", style_body))
pdf_story.append(Paragraph("<b>Student Web Portal:</b> Dynamic Defaulter smart alerts banner (<75% warning with classes-needed calculator), class-by-class session history, and 3-tier self-service elective registration.", style_body))
pdf_story.append(Spacer(1, 8))

# 7. Verification Matrix
pdf_story.append(Paragraph("7. Comprehensive Verification Matrix & Hardware Readiness", style_h1))
pdf_story.append(create_pdf_table([2.0, 3.5, 1.7], ["Subsystem / Feature", "Verification Scope", "Verification Status"], verif_matrix))
pdf_story.append(Spacer(1, 8))

# Build PDF Document
pdf_doc.build(pdf_story)
print(f"PDF document successfully saved to: {pdf_output_path}")

print("All documentation reports generated successfully!")
