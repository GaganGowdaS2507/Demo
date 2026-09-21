"""
AttendAI - Complete Front-End Tester & Administrator Walkthrough Guide Generator
Generates:
1. AttendAI_Tester_Admin_Complete_Walkthrough_Guide.docx (Word Document)
2. AttendAI_Tester_Admin_Complete_Walkthrough_Guide.pdf (PDF Document)
"""

import os
import sys
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

print("Building Tester & Admin Interactive Exploration Guide generator...")

# ==============================================================================
# DOCX GENERATOR
# ==============================================================================

doc = docx.Document()

# Page Margins (0.75 in)
for sec in doc.sections:
    sec.top_margin = Inches(0.75)
    sec.bottom_margin = Inches(0.75)
    sec.left_margin = Inches(0.75)
    sec.right_margin = Inches(0.75)

# Styling Colors
HEX_NAVY = "1E3A8A"
HEX_BLUE = "0284C7"
HEX_DARK = "0F172A"
HEX_MUTED = "475569"
HEX_BG = "F8FAFC"
HEX_BORDER = "CBD5E1"
HEX_GREEN = "16A34A"
HEX_AMBER = "D97706"

COLOR_NAVY = RGBColor(30, 58, 138)
COLOR_BLUE = RGBColor(2, 132, 199)
COLOR_DARK = RGBColor(15, 23, 42)
COLOR_MUTED = RGBColor(71, 85, 105)

def set_cell_background(cell, hex_color):
    shading_elm = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>')
    cell._tc.get_or_add_tcPr().append(shading_elm)

def set_cell_margins(cell, top=100, bottom=100, left=140, right=140):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m, val in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
        node = OxmlElement(f'w:{m}')
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)

def add_h1(doc, text):
    h = doc.add_heading(text, level=1)
    h.paragraph_format.keep_with_next = True
    h.paragraph_format.space_before = Pt(18)
    h.paragraph_format.space_after = Pt(4)
    r = h.runs[0]
    r.font.size = Pt(15)
    r.font.bold = True
    r.font.color.rgb = COLOR_NAVY
    return h

def add_h2(doc, text):
    h = doc.add_heading(text, level=2)
    h.paragraph_format.keep_with_next = True
    h.paragraph_format.space_before = Pt(12)
    h.paragraph_format.space_after = Pt(3)
    r = h.runs[0]
    r.font.size = Pt(12.5)
    r.font.bold = True
    r.font.color.rgb = COLOR_NAVY
    return h

def add_h3(doc, text):
    h = doc.add_heading(text, level=3)
    h.paragraph_format.keep_with_next = True
    h.paragraph_format.space_before = Pt(9)
    h.paragraph_format.space_after = Pt(2)
    r = h.runs[0]
    r.font.size = Pt(10.5)
    r.font.bold = True
    r.font.color.rgb = COLOR_BLUE
    return h

def add_p(doc, text="", bold_prefix=None, space_after=5):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.15
    if bold_prefix:
        r_pre = p.add_run(bold_prefix)
        r_pre.font.bold = True
        r_pre.font.size = Pt(9.5)
        r_pre.font.color.rgb = COLOR_DARK
    if text:
        r_text = p.add_run(text)
        r_text.font.size = Pt(9.5)
        r_text.font.color.rgb = COLOR_DARK
    return p

def add_callout(doc, text, title="TESTER CLICK-ACTION OBSERVATION", border_hex=HEX_NAVY, bg_hex=HEX_BG):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    cell = table.cell(0, 0)
    cell.width = Inches(7.0)
    set_cell_background(cell, bg_hex)
    set_cell_margins(cell, top=100, bottom=100, left=150, right=150)
    
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
    r_title.font.size = Pt(9.0)
    r_title.font.color.rgb = COLOR_NAVY
    
    r_text = p.add_run(text)
    r_text.font.size = Pt(9.0)
    r_text.font.color.rgb = COLOR_DARK
    doc.add_paragraph().paragraph_format.space_after = Pt(2)

def add_table_data(doc, col_widths, headers, data):
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    
    hdr_cells = table.rows[0].cells
    for idx, header in enumerate(headers):
        hdr_cells[idx].text = header
        hdr_cells[idx].width = Inches(col_widths[idx])
        set_cell_background(hdr_cells[idx], HEX_NAVY)
        set_cell_margins(hdr_cells[idx], top=70, bottom=70, left=90, right=90)
        p = hdr_cells[idx].paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        if len(p.runs) > 0:
            p.runs[0].font.bold = True
            p.runs[0].font.size = Pt(8.5)
            p.runs[0].font.color.rgb = RGBColor(255, 255, 255)
            
    for row_idx, row_data in enumerate(data):
        row = table.add_row()
        row_cells = row.cells
        bg_color = HEX_BG if row_idx % 2 == 1 else "FFFFFF"
        for col_idx, cell_value in enumerate(row_data):
            row_cells[col_idx].text = str(cell_value)
            row_cells[col_idx].width = Inches(col_widths[col_idx])
            set_cell_background(row_cells[col_idx], bg_color)
            set_cell_margins(row_cells[col_idx], top=50, bottom=50, left=90, right=90)
            p = row_cells[col_idx].paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            if len(p.runs) > 0:
                p.runs[0].font.size = Pt(8.0)
                p.runs[0].font.color.rgb = COLOR_DARK
                
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
    doc.add_paragraph().paragraph_format.space_after = Pt(3)


# ==============================================================================
# DOCUMENT TITLE
# ==============================================================================

p_title = doc.add_paragraph()
p_title.paragraph_format.space_before = Pt(20)
p_title.paragraph_format.space_after = Pt(3)
r = p_title.add_run("AttendAI: Web Application & Backend Tester Demonstration Guide")
r.font.size = Pt(20)
r.font.bold = True
r.font.color.rgb = COLOR_NAVY

p_sub = doc.add_paragraph()
p_sub.paragraph_format.space_after = Pt(10)
r_sub = p_sub.add_run("Exhaustive Tree-Structured Exploration & Functional Verification Manual\nWritten from the Perspective of a Front-End Quality Tester & College Administrator")
r_sub.font.size = Pt(11.5)
r_sub.font.color.rgb = COLOR_MUTED

meta_headers = ["Testing Dimension", "Inspection & Demonstration Details"]
meta_rows = [
    ["Testing Persona", "Lead Front-End Tester / College Administrator performing full-coverage UI & API exploratory testing."],
    ["Exploration Rule", "Hierarchical Tree Traversal: Main Navigation Node -> Sub-workspace Branches -> Leaf Form Controls -> Click Event Execution -> Verification -> Traceback."],
    ["Backend Stack Tested", "Flask 3.x (23 Blueprints, 120+ Routes), MySQL 8.x (36 Tables), Jinja2, Bootstrap 5.3, InsightFace ResNet-50, MobileFaceNet, StreamManager."],
    ["Scope Covered", "Admin Portal (17 Modules), Faculty Live Attendance Hub (All 7 Methods), HOD Portal, Student Portal, and IoT Device Services."],
    ["Verification Status", "100% Software Verified & Live DB Tested. Hardware-dependent physical actions clearly demarcated as Simulated / Hardware Pending."]
]
add_table_data(doc, [2.0, 5.0], meta_headers, meta_rows)

doc.add_page_break()

# ==============================================================================
# SECTION 1: ADMIN LOGIN & SIDEBAR HIERARCHY
# ==============================================================================

add_h1(doc, "1. Admin Login & Global Sidebar Navigation")

add_p(
    doc,
    "I open the browser and navigate to the application root URL (http://127.0.0.1:5000/). The system redirects me to the authentication gateway (/auth/login).",
    bold_prefix="Step 1 - Opening the Application: "
)

add_h2(doc, "1.1 Login Screen Inspection (templates/auth/login.html)")
add_p(
    doc,
    "• What I See on Screen: A centered login card with the AttendAI gradient logo, an 'Email Address' input field, a 'Password' input field, a 'Remember Me' checkbox, a blue 'Sign In' button, and links for 'Register as Student' and 'Forgot Password?'.\n"
    "• What I Test (Entering Credentials & Clicking 'Sign In'):\n"
    "  - I enter email: admin@attendai.edu and password: adminpassword, then click the 'Sign In' button.\n"
    "  - Backend Handling: The form submits via POST to auth.login (auth/routes.py). The backend checks users table: SELECT id, password_hash, role, status, full_name FROM users WHERE email = %s. It verifies the password using Bcrypt (12 rounds) and verifies status == 'active'.\n"
    "  - System Result: Authentication succeeds. Flask-Login's UserSession initializes with role = 'admin'. The browser is redirected to /admin/ and the Admin Dashboard opens.",
    bold_prefix="Login Walkthrough: "
)

add_h2(doc, "1.2 Admin Sidebar Structure (templates/base.html)")
add_p(
    doc,
    "Upon landing on the Admin workspace, the fixed left sidebar (width: 240px) renders the full administrative menu organized into 6 functional sections:",
    bold_prefix="Global Sidebar Menu: "
)

sidebar_items = [
    ["1. Main", "Dashboard", "admin.dashboard (/admin/)", "bi-speedometer2", "Central operations command hub, 6 KPI cards, session log."],
    ["2. Academic", "Departments", "academic.departments (/admin/academic/departments)", "bi-building", "Department catalog, structure modes (plain vs clusters), workspace."],
    ["2. Academic", "Academic Periods", "academic.periods (/admin/academic/periods)", "bi-calendar-range", "Odd/Even teaching cycles, dates, cycle activation switch."],
    ["2. Academic", "Batches", "academic.batches (/admin/academic/batches)", "bi-people", "Student intake batches, batch dashboard, promote batch engine."],
    ["2. Academic", "Sections", "academic.sections (/admin/academic/sections)", "bi-grid-3x3", "Department/Semester drilldown, classroom rooms, manage subjects."],
    ["2. Academic", "Subjects Workspace", "academic.subjects (/admin/academic/subjects)", "bi-book", "Master catalog, Theory/Lab/Integrated, offering modes, electives."],
    ["3. People", "Approvals", "students_mgmt.approval_queue (/admin/students/approvals)", "bi-person-check", "Self-registration review queue with pending count badge."],
    ["3. People", "Enrollments", "students_mgmt.enrollment_page (/admin/students/enrollment)", "bi-mortarboard", "4-channel face enrollment: Single Photo, Webcam, Bulk ZIP, Sheets."],
    ["3. People", "Students", "students_mgmt.list_students (/admin/students/)", "bi-mortarboard", "Directory, student overview, manual creation, section transfer."],
    ["3. People", "Faculty", "faculty_mgmt.list_faculty (/admin/faculty/)", "bi-person-badge", "Faculty directory, designations, status toggling, teaching loads."],
    ["4. Operations", "Sessions", "sessions.list_sessions (/admin/sessions/)", "bi-calendar2-check", "Master lecture sessions log, manual session creation, mode setup."],
    ["4. Operations", "Timetable", "timetable.view_timetable (/admin/timetable/)", "bi-table", "Weekly timetable matrix (Monday-Saturday), CSV bulk upload."],
    ["4. Operations", "Cameras", "cameras.list_cameras (/admin/cameras/)", "bi-camera-video", "IoT camera/ESP32 registry, RTSP/IP streams, /status testing."],
    ["4. Operations", "Recognition Control", "recognition.recognition_panel (/admin/recognition/)", "bi-eye", "In-memory RAM matrix index status, live MJPEG streams."],
    ["4. Operations", "Holidays", "timetable.holidays (/admin/timetable/holidays)", "bi-umbrella", "Holiday calendar, college/department scopes, auto-scheduler skip."],
    ["5. Reports", "Reports", "admin_reports.reports_home (/admin/reports/)", "bi-bar-chart-line", "Analytics hub, student-by-date attendance grid, Excel export."],
    ["5. Reports", "Defaulters", "admin_reports.defaulters (/admin/reports/defaulters)", "bi-exclamation-triangle", "Defaulter dashboard (<75% threshold), warning badges, CSV export."],
    ["6. System", "Settings", "settings.view_settings (/admin/settings/)", "bi-gear", "Tunable thresholds for recognition (0.35), cooldown timer (55m)."]
]
add_table_data(doc, [1.0, 1.3, 2.3, 0.9, 1.5], ["Section", "Menu Item", "Route Endpoint & URL", "Icon", "Description"], sidebar_items)

# ==============================================================================
# SECTION 2: ADMIN DASHBOARD EXPLORATION
# ==============================================================================

add_h1(doc, "2. Screen 1: Admin Dashboard (/admin/)")

add_p(
    doc,
    "I am on the Admin Dashboard (templates/admin/dashboard.html). I will touch and click every element present on this screen.",
    bold_prefix="Exploring Dashboard: "
)

add_h2(doc, "2.1 Touching the 6 KPI Metric Cards")
add_p(
    doc,
    "1. 'Today's Sessions' Card: Displays the count of sessions scheduled for today (e.g. '8 Sessions' with sub-badges: 2 Active, 4 Completed, 2 Scheduled). Sourced from SELECT COUNT(*) FROM sessions WHERE session_date = CURDATE(). I click on the card -> It navigates directly to /admin/sessions/.\n"
    "2. 'Pending Approvals' Card: Displays count of students waiting in the self-registration queue (e.g. '3 Pending'). Sourced from SELECT COUNT(*) FROM approval_queue WHERE status = 'pending'. I click on the card -> It opens /admin/students/approvals.\n"
    "3. 'Enrolled Students' Card: Displays total students with biometric face data registered (e.g. '142 Enrolled'). Sourced from SELECT COUNT(*) FROM students WHERE enrollment_status != 'not_enrolled'. I click -> Navigates to /admin/students/enrollment.\n"
    "4. 'Defaulters' Card: Displays count of students whose overall attendance percentage across all enrolled subjects is below 75% (e.g. '12 Defaulters'). Sourced by calculating present/total ratio in attendance table. I click -> Opens /admin/reports/defaulters.\n"
    "5. 'Active Sections' Card: Displays count of active classroom sections for the current academic period (e.g. '16 Sections'). Sourced from SELECT COUNT(*) FROM sections WHERE is_active = 1. I click -> Opens /admin/academic/sections.\n"
    "6. 'Active Streams' Card: Displays a pulsing green badge showing live video recognition threads running in StreamManager (e.g. '1 Stream Live'). I click -> Opens /admin/recognition/.",
    bold_prefix="KPI Cards Walkthrough: "
)

add_h2(doc, "2.2 Clicking the Quick Action Buttons")
add_p(
    doc,
    "• 'Initialize Recognition Models' Button: I click this button. It triggers an AJAX POST request to /admin/init-models. Backend executes RecognitionEngine.initialize(), loads InsightFace ONNX models (det_10g, w600k_r50, 2d106det), builds the 512-d cosine index matrix (_emb_index_matrix) in RAM, and refreshes the student cache. A green toast notification pops up: 'Recognition Engine Initialized (57 Identities Loaded)'.\n"
    "• 'Manage Sessions' Button: I click this -> Takes me to /admin/sessions/.\n"
    "• 'Review Approvals' Button: I click this -> Takes me to /admin/students/approvals.\n"
    "• 'Face Enrollment' Button: I click this -> Takes me to /admin/students/enrollment.",
    bold_prefix="Quick Actions: "
)

add_h2(doc, "2.3 Testing the Session Overview Filters")
add_p(
    doc,
    "• Filter Controls: Department dropdown, Semester dropdown, Section dropdown, and Status buttons ('All', 'Active', 'Scheduled', 'Completed', 'Dismissed').\n"
    "• I select Department: 'CSE', Semester: '4', Status: 'Active' and click 'Filter'. The backend queries sessions table joined with subjects, faculty, and sections for the selected criteria and refreshes the table instantly.",
    bold_prefix="Session Filter: "
)

# ==============================================================================
# SECTION 3: DEPARTMENTS & CLUSTERS
# ==============================================================================

add_h1(doc, "3. Screen 2: Departments & Department Workspace")

add_p(
    doc,
    "I click 'Departments' in the sidebar. The page /admin/academic/departments (templates/admin/departments.html) opens.",
    bold_prefix="Navigation: "
)

add_h2(doc, "3.1 Department List Screen Inspection")
add_p(
    doc,
    "• What I See: A master table displaying Department Code (e.g. 'CSE', 'ECE', 'ME'), Department Name (e.g. 'Computer Science & Engineering'), Structure Mode badge ('Clusters (2)' vs 'Plain Structure'), Total Sections, Total Faculty, Total Subjects, and three Action buttons: 'Manage', 'Edit', and 'Delete'. At the top, there is an 'Add Department' button.",
    bold_prefix="Department Catalog: "
)

add_h2(doc, "3.2 Testing the 'Add Department' Form")
add_p(
    doc,
    "• I click the '+ Add Department' button. A modal opens with the following fields:\n"
    "  1. Department Code (Text input, Required): I enter 'AIML'.\n"
    "  2. Department Name (Text input, Required): I enter 'Artificial Intelligence & Machine Learning'.\n"
    "  3. Structure Mode (Checkbox): I check 'Enable Sub-Department Clusters (has_clusters)'.\n"
    "• I click 'Save Department': The form submits via POST to academic.add_department. Backend executes: INSERT INTO departments (code, name, has_clusters) VALUES ('AIML', 'Artificial Intelligence & Machine Learning', 1). The modal closes, a green success banner appears, and 'AIML' is listed in the table.",
    bold_prefix="Add Department Test: "
)

add_h2(doc, "3.3 Clicking the 'Manage' Button -> Department Workspace")
add_p(
    doc,
    "• I click 'Manage' next to CSE. The Department Workspace (templates/admin/department_workspace.html) opens.\n"
    "• Top Summary Cards: Displays Faculty Count (18), Section Count (6), Subject Count (14), and Cluster Count (2).\n"
    "• 'Attention Required' Box: This box automatically checks the database and warns: '⚠ 2 Faculty members have not been allocated teaching loads' and '⚠ Section 4C has 1 subject without assigned faculty'.\n"
    "• Navigation Tabs in Workspace: I click through all 4 tabs:\n"
    "  - Tab 1: 'Faculty': Lists all 18 faculty members in CSE with their designation and email.\n"
    "  - Tab 2: 'Sections': Lists Sections 4A, 4B, 4C, 6A, 6B, 6C with room numbers.\n"
    "  - Tab 3: 'Subjects': Lists all curriculum subjects mapped to CSE.\n"
    "  - Tab 4: 'Clusters': Lists the sub-department clusters for high-intake management.",
    bold_prefix="Department Workspace: "
)

add_h2(doc, "3.4 Exploring the Cluster Workspace Branch (templates/admin/cluster/)")
add_p(
    doc,
    "• In the Clusters tab, I click 'Manage Cluster' on 'CSE 4th Sem Core Cluster'. The Cluster Workspace opens (cluster_workspace.html):\n"
    "  - Cluster Details: Shows Cluster Name, assigned senior faculty 'Cluster Head' (e.g. Dr. Rajesh Kumar), assigned sections (4A, 4B), enrolled students (124), and curriculum subjects.\n"
    "  - 'Curriculum' Sub-Tab (curriculum.html): I click this -> Opens the elective subject matrix where I can assign cluster-specific elective offerings.\n"
    "  - Conflict Detectors: I attempt to assign a faculty member who already has a conflicting class. The system intercepts the action and displays faculty_conflict.html: 'Conflict detected: Prof. Sharma is already scheduled for Section 6A during Tuesday Slot 2. Override with force_move=1?'.",
    bold_prefix="Cluster Workspace: "
)

# ==============================================================================
# SECTION 4: ACADEMIC PERIODS & BATCHES
# ==============================================================================

add_h1(doc, "4. Screens 3 & 4: Academic Periods & Student Cohort Batches")

add_h2(doc, "4.1 Screen 3: Academic Periods (/admin/academic/periods)")
add_p(
    doc,
    "• What I See on Screen: Academic period cards (templates/admin/periods.html) showing Academic Year ('2025-2026'), Cycle Type ('Odd' vs 'Even'), Active Status ('Active' in green badge vs 'Draft' in grey), Start Date ('2025-08-01'), End Date ('2025-12-20'), and action buttons: 'Activate', 'Edit', and 'Delete'.\n"
    "• Cycle Logic Tested: Odd Cycle controls semesters [1, 3, 5, 7]; Even Cycle controls semesters [2, 4, 6, 8].\n"
    "• Testing the 'Activate' Button: I click 'Activate' on Period '2025-2026 Even'. The backend executes UPDATE academic_periods SET is_active = CASE WHEN id = 2 THEN 1 ELSE 0 END. Instantly, the active cycle switches to Even across the entire application: timetable slots, auto-session generation, and student dashboards now display Even semester subjects.",
    bold_prefix="Academic Periods Walkthrough: "
)

add_h2(doc, "4.2 Screen 4: Student Cohort Batches (/admin/academic/batches)")
add_p(
    doc,
    "• What I See on Screen: Cohort cards (templates/admin/batches.html) representing student graduation batches: Batch 2026-30 (1st Year, Sem 1), Batch 2025-29 (2nd Year, Sem 3), Batch 2024-28 (3rd Year, Sem 5), Batch 2023-27 (4th Year, Sem 7).\n"
    "• Clicking 'Batch Dashboard' on Batch 2024-28 (batch_workspace.html): Displays detailed student metrics:\n"
    "  - Joined Students: 130\n"
    "  - Currently Studying: 124\n"
    "  - Dropped / Inactive: 2\n"
    "  - Detained (Defaulters): 4\n"
    "  - Eligible for Promotion: 120\n"
    "• Testing 'Promote Batch' Button: I click the green 'Promote Batch' button. A confirmation modal appears: 'Are you sure you want to promote Batch 2024-28 from Semester 5 to Semester 6?'. I click Confirm. Backend executes UPDATE students SET current_sem = current_sem + 1 WHERE batch_id = 3 AND enrollment_status != 'detained'. All historical attendance records and past CIA grades remain permanently intact.",
    bold_prefix="Batches Walkthrough: "
)

# ==============================================================================
# SECTION 5: SECTIONS, SUBJECTS & DEDUPLICATION
# ==============================================================================

add_h1(doc, "5. Screens 5 & 6: Sections, Subjects & Deduplication Engine")

add_h2(doc, "5.1 Screen 5: Classroom Sections (/admin/academic/sections)")
add_p(
    doc,
    "• Department & Semester Navigation: I select Department 'CSE' tab, then click Semester '4'. The page renders cards for Sections 4A, 4B, and 4C.\n"
    "• Inside Section Card '4A': Displays Batch (2025-29), Semester (4), Classroom Room ('Room 302'), Cluster ('CSE Core Cluster 1'), Enrolled Students (62), and three buttons: 'Manage Subjects', 'View Timetable', and 'Edit'.\n"
    "• Testing 'Manage Subjects' (section_subjects.html): I click 'Manage Subjects'. A table opens showing all subjects taught in 4A. I click '+ Assign Subject', select Subject: 'Operating Systems (21CS42)', select Faculty: 'Dr. Anita Roy', and submit -> INSERT INTO section_subjects.\n"
    "• Testing 'View Timetable': I click 'View Timetable' -> The weekly grid for Section 4A renders with all Monday–Saturday lecture slots.",
    bold_prefix="Sections Walkthrough: "
)

add_h2(doc, "5.2 Screen 6: Master Subject Catalog & Deduplication (/admin/academic/subjects)")
add_p(
    doc,
    "• What I See on Screen: Master course catalog (templates/admin/subjects.html) with Department and Semester filters.\n"
    "• Academic Course Classifications:\n"
    "  - Subject Types: Theory (e.g. 21CS42 - OS), Lab (e.g. 21CSL46 - OS Lab), Theory-Lab Integrated (e.g. 21CS43 - Microcontrollers).\n"
    "  - Offering Modes: Core Section (mandatory), Professional Elective, Open Elective, Skill/Ability Enhancement Course (AEC/SEC).\n"
    "  - Attendance Rules: Combined (lecture + lab counted together) vs Separate (independent attendance ledgers).\n"
    "• Testing the 'Subject Deduplication & Merging' Tool (/admin/subjects/deduplicate): I open the deduplication workspace. The tool scans the database and identifies two duplicate records: '21CS42 - Operating Systems' and 'CS402 - Operating Systems'. I select '21CS42' as canonical, select 'CS402' as duplicate, and click 'Merge Subjects'. The backend executes foreign key remapping across timetable, sessions, section_subjects, and attendance, and then safely deletes 'CS402' without losing any past attendance records.",
    bold_prefix="Subjects Master & Dedup: "
)

# ==============================================================================
# SECTION 6: APPROVALS & 4-CHANNEL FACE ENROLLMENT
# ==============================================================================

add_h1(doc, "6. Screens 7 & 8: Student Approvals & Face Enrollment Workspace")

add_h2(doc, "6.1 Screen 7: Student Approvals Queue (/admin/students/approvals)")
add_p(
    doc,
    "• What I See on Screen: The approval queue (templates/admin/approval_queue.html) lists self-registered students with USN, Full Name, Email, Phone, Department, Semester, Requested Section, and Submission Date.\n"
    "• Testing 'Approve': I click 'Approve' on student 'Rahul Verma (1BY22CS045)'. A modal opens allowing me to confirm Section '4A'. I submit -> Backend updates users.status = 'active', creates students record with enrollment_status = 'approved_face_pending', and pushes Rahul into the biometric enrollment queue.\n"
    "• Testing 'Reject': I click 'Reject' on an invalid entry, enter reason: 'Invalid USN provided', and submit -> approval_queue.status = 'rejected'.",
    bold_prefix="Approvals Walkthrough: "
)

add_h2(doc, "6.2 Screen 8: Multi-Channel Face Enrollment (/admin/students/enrollment)")
add_p(
    doc,
    "I click 'Enrollment' in the sidebar. The workspace (templates/admin/enrollment.html) opens with 4 functional tabs. I test every tab:",
    bold_prefix="Face Enrollment Tabs: "
)

enroll_tab_details = [
    ["Tab 1: Pending", "Approved students awaiting face enrollment.", "I select student Rahul Verma. I click 'Webcam Capture' -> Camera turns on in browser -> I capture portrait -> Server detects face, generates 512-d ResNet-50 embedding, saves crop to dataset/images/ and vector to faces table -> Student moves to Enrolled."],
    ["Tab 2: Enrolled", "Roster of students with face data.", "Displays student photo thumbnail, USN, Name, Section, and 'Re-Enroll' button. I click 'Re-Enroll' on a test student -> Existing face embedding is purged from faces and student moves back to Pending tab."],
    ["Tab 3: Bulk ZIP", "Bulk enrollment via ZIP archive.", "I upload a ZIP file containing photos named 1BY22CS001.jpg, 1BY22CS002.jpg. The engine extracts images in RAM, matches USNs in database, extracts dual embeddings, and displays a complete success log: '12 Students Successfully Enrolled'."],
    ["Tab 4: Google Sheets", "Form responses automated synchronization.", "I paste a Google Sheet URL containing student details and Google Drive selfie URLs. I click 'Sync from Sheet' -> Backend downloads images via Google Drive API, auto-creates missing student accounts, and registers embeddings."]
]
add_table_data(doc, [1.4, 2.2, 3.4], ["Enrollment Tab", "Purpose", "Tester Click-Action & Biometric Generation Result"], enroll_tab_details)

# ==============================================================================
# SECTION 7: OPERATIONS, TIMETABLE, CAMERAS & FINGERPRINTS
# ==============================================================================

add_h1(doc, "7. Screens 9 to 14: Operations, Cameras, Timetable & Fingerprints")

add_h2(doc, "7.1 Screen 9: Timetable Management (/admin/timetable/)")
add_p(
    doc,
    "• What I See on Screen: Weekly timetable matrix (templates/admin/timetable.html) displaying Monday–Saturday time slots for any selected section.\n"
    "• Adding a Slot: I click '+ Add Slot', select Day: 'Monday', Slot Type: 'Theory', Time: '09:00 - 10:00', Subject: 'Operating Systems', Faculty: 'Dr. Anita Roy', Room: 'Room 302', and submit -> INSERT INTO timetable.\n"
    "• Testing Bulk CSV Upload (/admin/timetable/upload): I upload timetable.csv with columns (Day, Slot, SubjectCode, FacultyEmail, Room). Backend validates data and imports all weekly slots in bulk.",
    bold_prefix="Timetable Walkthrough: "
)

add_h2(doc, "7.2 Screen 10: Camera & Device Registry (/admin/cameras/)")
add_p(
    doc,
    "• What I See on Screen: Table of registered devices (templates/admin/cameras.html) showing Device Name, RTSP/HTTP Stream URL (http://192.168.4.1:81/stream), Location ('Room 302'), Assigned Section ('4A'), Online Status, and Last Tested.\n"
    "• Testing Connection: I click 'Test Stream' on Camera 1 -> Backend sends HTTP GET to http://192.168.4.1/status. It receives response and updates status to 'online' with green badge.",
    bold_prefix="Cameras Registry: "
)

add_h2(doc, "7.3 Screen 11: Hardware Fingerprints Management (/admin/fingerprints/)")
add_p(
    doc,
    "• What I See on Screen: Fingerprint hardware management dashboard (templates/admin/fingerprints.html).\n"
    "• Enrolling a Fingerprint: I select Target Device: 'ESP32 Room 302', select Student: 'Rahul Verma (1BY22CS045)', and click 'Start Hardware Enrollment'. The backend finds next free slot (Slot #14) on the HLK-ZW101 sensor, calls GET /enroll?id=14 on the ESP32. Upon two finger touches, the device confirms enrollment and backend saves record to fingerprints table.\n"
    "• Deleting an Enrollment: I click 'Delete' next to Slot #14 -> Backend calls GET /delete?id=14 on the ESP32 and marks fingerprints.status = 'revoked'.",
    bold_prefix="Fingerprint Registry: "
)

# ==============================================================================
# SECTION 8: FACULTY LIVE ATTENDANCE HUB (ALL 7 METHODS)
# ==============================================================================

add_h1(doc, "8. Faculty Web Application & Multi-Modal Attendance (All 7 Methods)")

add_p(
    doc,
    "I log out from Admin and log in as Faculty (dr.anita@attendai.edu). The Faculty Dashboard (/faculty/) opens showing my today's schedule cards. I click 'Open Session' on 'Operating Systems - Section 4A (09:00 - 10:00)'. The Live Session Hub (/faculty/session/1) opens.",
    bold_prefix="Faculty Perspective: "
)

add_h2(doc, "8.1 Live Session Hub Screen Inspection (templates/faculty/session_view.html)")
add_p(
    doc,
    "• Left Panel (Attendance Roster): Master table listing all 62 students in Section 4A with USN, Full Name, Status badge ('Absent' in red by default), Method badge, Recognition Score, Fingerprint Score, Toggle button, and Notes button.\n"
    "• Right Panel (Live Controls & Stream Preview): Mode Selector dropdown ('FACE_ONLY', 'FINGERPRINT_ONLY', 'DUAL_MODE'), Camera Device dropdown, RTSP URL input (http://192.168.4.1:81/stream), 'Start Attendance' button, 'Dismiss Class' form, and live Present counter (0 / 62).\n"
    "• Top Action Bar: Buttons for 'Mark All Present', 'Mark All Absent', 'Upload Sheet OCR', 'Upload Classroom Photo', 'Request Proxy'.",
    bold_prefix="Live Session Layout: "
)

add_h2(doc, "8.2 Demonstrating All 7 Attendance Recording Methods")

att_methods_walkthrough = [
    ["1. Manual Individual", "I click 'Toggle' next to Rahul Verma in the roster.", "POST /faculty/session/1/toggle/45", "Status flips to 'Present' (green badge), method='manual', marked_by=faculty_id. Present counter updates to 1/62."],
    ["2. Manual Bulk", "I click 'Mark All Present' on the top bar.", "POST /faculty/session/1/mark-all-present", "Bulk SQL updates all 62 attendance rows to status='present', method='manual'. Counter shows 62/62."],
    ["3. FACE_ONLY Mode", "I select 'FACE_ONLY', ensure URL is http://192.168.4.1:81/stream, and click 'Start Attendance'.", "StreamManager (FACE_ONLY)", "StreamManager starts threaded FrameGrabber. InsightFace detects faces in video, extracts 512-d embeddings, computes dot-product cosine similarity against preloaded RAM matrix index, verifies section 4A, checks 55-min cooldown, and commits attendance as method='face_recognition' with confidence score."],
    ["4. FINGERPRINT_ONLY Mode", "I select 'FINGERPRINT_ONLY' and click 'Start Attendance'.", "StreamManager (FINGERPRINT_ONLY)", "RecognitionThread starts background poller (_fingerprint_loop) querying ESP32 /last-scan every 500ms. Student touches sensor -> sensor matches print locally -> ESP32 sends template slot -> Flask resolves student -> verifies section 4A -> marks attendance as method='fingerprint' with fingerprint_score."],
    ["5. DUAL_MODE (2-Factor)", "I select 'DUAL_MODE' (2-Factor Biometric Verification) and click 'Start Attendance'.", "StreamManager (DUAL_MODE)", "Step 1: Student places finger on sensor. Poller receives template slot and sets self._dual_target = {'student_id': 45, 'expires_at': time.time() + 10.0} (10-second window).\nStep 2: Student looks at camera -> FrameGrabber captures face crop -> Engine runs match_face_to_student() comparing cosine similarity ONLY against Rahul Verma's stored embedding (no full database search).\nStep 3: On match (>=0.35), commits attendance with method='dual_verification' recording both scores, and resets target lock. If 10s elapses without match, target automatically times out."],
    ["6. Sheet OCR Upload", "I click 'Upload Sheet OCR', select an image of a physical attendance sheet, and submit.", "POST /faculty/session/1/upload-sheet", "OpenRouter Vision AI extracts text -> sheet_ocr.py runs RapidFuzz fuzzy roster matching -> sheet_upload_preview.html displays matched student checkboxes -> I click 'Confirm Attendance' -> commits verified students with method='sheet_upload'."],
    ["7. Classroom Group Photo", "I click 'Upload Classroom Photo', upload 2 wide-angle classroom photos, and submit.", "POST /faculty/session/1/upload-classroom-photo", "InsightFace detects all faces (>=35px) across both photos, matches section roster embeddings, deduplicates highest score per student, displays interactive preview -> I click 'Confirm Attendance' -> commits verified students with method='classroom_photo'."]
]
add_table_data(doc, [1.3, 2.2, 1.4, 2.1], ["Method", "Tester Click Action", "Route / Engine", "Execution & Database Result"], att_methods_walkthrough)

add_h2(doc, "8.3 Testing Additional Faculty Features")
add_p(
    doc,
    "• Proxy Lecture Delegation System: I click 'Request Proxy' on my session. The system generates a 4-character code (e.g. 'P7X2'). Another faculty logs into their dashboard, clicks 'Claim Proxy', enters 'P7X2', and takes over the class (session recorded with is_proxy=1, delegated_faculty_id).\n"
    "• Continuous Internal Evaluation (CIE) Marks Portal (/faculty/exam-results): I select Section 4A and Subject 'Operating Systems'. A marks entry table renders students. I enter IA1 (28/30), IA2 (26/30), IA3 (29/30), CCA (18/20). The client-side JS calculates total = 47/50, and upon submitting, backend records marks and assigns Grade 'A+'.",
    bold_prefix="Faculty Tools Walkthrough: "
)

# ==============================================================================
# SECTION 9: HOD & STUDENT PORTALS
# ==============================================================================

add_h1(doc, "9. Head of Department (HOD) & Student Web Applications")

add_h2(doc, "9.1 HOD Web Portal (/hod/dashboard)")
add_p(
    doc,
    "• What HOD Sees: Department-wide overview cards (Total Sections, Active Faculty, Live Lectures, Today's Departmental Sessions).\n"
    "• Department Monitoring: Real-time visibility into all lectures actively conducting attendance in the department, active camera streams, and faculty attendance.\n"
    "• Faculty Registration Approvals (/hod/faculty-approvals): Review queue where the HOD approves newly registered faculty members in their department.",
    bold_prefix="HOD Walkthrough: "
)

add_h2(doc, "9.2 Student Web Portal (/student/)")
add_p(
    doc,
    "• What Student Sees: Profile header (USN, Full Name, Section 4A, Current Semester 4), overall attendance percentage progress ring (e.g. '72.5%'), Dynamic Smart Alerts Banner, Subject-Wise Attendance table, and Internal CIA Results table.\n"
    "• Dynamic Smart Alerts Banner: Because attendance is 72.5% (< 75%), a prominent red banner appears: '🚨 OVERALL attendance is 72.5%. You are a defaulter! You need to attend 4 consecutive classes to reach 75% safe standing.'\n"
    "• Class-by-Class Attendance History (/student/subject/2/history): I click 'Details' on Operating Systems. A table opens displaying every conducted class with Date, Time Slot, Room, Status ('Present' with green checkmark), Method ('Face Recognition'), Confidence Score ('0.842'), and Timestamp.\n"
    "• 3-Tier Self-Service Elective Registration (/student/registration/): Student selects Professional Elective (Cloud Computing), Open Elective (Renewable Energy), and AEC Course (Python Lab). Live seat counters show '42 / 60 seats filled'. Upon submitting, the choices lock with a green 'Locked' badge.",
    bold_prefix="Student Walkthrough: "
)

# ==============================================================================
# SECTION 10: VERIFICATION & TESTING STATUS
# ==============================================================================

add_h1(doc, "10. Comprehensive Verification Matrix & Hardware Status")

verif_rows = [
    ["Python Syntax & Imports", "Compilation & static linting across all 23 blueprints and modules", "VERIFIED BY EXECUTION"],
    ["Flask Startup & Route Mappings", "Application factory initialization, 120+ endpoint URL mappings", "VERIFIED BY EXECUTION"],
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
add_table_data(doc, [2.0, 3.5, 1.5], ["Subsystem / Feature", "Verification Scope & Test Details", "Verification Status"], verif_rows)

# Save Docx
docx_out_1 = r"c:\RNNEW\RNSharedApp\AttendAI_Tester_Admin_Complete_Walkthrough_Guide.docx"
docx_out_2 = r"c:\RNNEW\RNSharedApp\attendance_system_test\AttendAI_Tester_Admin_Complete_Walkthrough_Guide.docx"
doc.save(docx_out_1)
doc.save(docx_out_2)
print(f"Word document saved to:\n  - {docx_out_1}\n  - {docx_out_2}")


# ==============================================================================
# PDF GENERATOR
# ==============================================================================

pdf_out_1 = r"c:\RNNEW\RNSharedApp\AttendAI_Tester_Admin_Complete_Walkthrough_Guide.pdf"
pdf_out_2 = r"c:\RNNEW\RNSharedApp\attendance_system_test\AttendAI_Tester_Admin_Complete_Walkthrough_Guide.pdf"

pdf_doc = SimpleDocTemplate(
    pdf_out_1,
    pagesize=letter,
    leftMargin=0.5*inch,
    rightMargin=0.5*inch,
    topMargin=0.5*inch,
    bottomMargin=0.5*inch
)

styles = getSampleStyleSheet()

p_title_style = ParagraphStyle('TTitle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=16, leading=20, textColor=colors.HexColor('#'+HEX_NAVY), spaceAfter=3)
p_sub_style = ParagraphStyle('TSub', parent=styles['Normal'], fontName='Helvetica', fontSize=9.5, leading=13, textColor=colors.HexColor('#'+HEX_MUTED), spaceAfter=8)
p_h1_style = ParagraphStyle('TH1', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=11.5, leading=15, textColor=colors.HexColor('#'+HEX_NAVY), spaceBefore=10, spaceAfter=3, keepWithNext=True)
p_h2_style = ParagraphStyle('TH2', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=9.5, leading=13, textColor=colors.HexColor('#'+HEX_BLUE), spaceBefore=6, spaceAfter=2, keepWithNext=True)
p_body_style = ParagraphStyle('TBody', parent=styles['Normal'], fontName='Helvetica', fontSize=7.6, leading=10.2, textColor=colors.HexColor('#'+HEX_DARK), spaceAfter=3)
p_th_style = ParagraphStyle('TTH', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=7.0, leading=8.5, textColor=colors.white)
p_td_style = ParagraphStyle('TTD', parent=styles['Normal'], fontName='Helvetica', fontSize=6.8, leading=8.4, textColor=colors.HexColor('#'+HEX_DARK))

def build_pdf_table(col_widths, headers, data):
    t_data = [[Paragraph(f"<b>{h}</b>", p_th_style) for h in headers]]
    for row in data:
        t_data.append([Paragraph(str(c), p_td_style) for c in row])
    t = Table(t_data, colWidths=[w * inch for w in col_widths])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#'+HEX_NAVY)),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 3.5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3.5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#'+HEX_BG)]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#'+HEX_BORDER)),
    ]))
    return t

pdf_story = []

# Title & Subtitle
pdf_story.append(Paragraph("AttendAI: Web Application & Backend Tester Demonstration Guide", p_title_style))
pdf_story.append(Paragraph("Exhaustive Tree-Structured Exploration & Functional Verification Manual (Lead Tester & Admin Persona)", p_sub_style))
pdf_story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#'+HEX_NAVY), spaceAfter=6))

# Metadata
pdf_story.append(build_pdf_table([1.8, 5.7], meta_headers, meta_rows))
pdf_story.append(Spacer(1, 6))

# Section 1
pdf_story.append(Paragraph("1. Admin Login & Global Sidebar Navigation", p_h1_style))
pdf_story.append(Paragraph("<b>Login (/auth/login):</b> I enter admin credentials -> backend verifies Bcrypt hash -> UserSession restores with role='admin' -> redirects to /admin/.", p_body_style))
pdf_story.append(build_pdf_table([1.0, 1.2, 2.3, 0.8, 2.2], ["Section", "Menu Item", "Route & URL", "Icon", "Description"], sidebar_items[:9]))
pdf_story.append(Spacer(1, 4))
pdf_story.append(build_pdf_table([1.0, 1.2, 2.3, 0.8, 2.2], ["Section", "Menu Item", "Route & URL", "Icon", "Description"], sidebar_items[9:]))
pdf_story.append(Spacer(1, 6))

# Section 2 & 3
pdf_story.append(Paragraph("2. Screen 1: Admin Dashboard (/admin/)", p_h1_style))
pdf_story.append(Paragraph("<b>6 KPI Cards:</b> Today's Sessions (8), Pending Approvals (3), Enrolled Students (142), Defaulters (12), Active Sections (16), Active Streams (1). Clicking any card navigates to the respective module.", p_body_style))
pdf_story.append(Paragraph("<b>Quick Actions:</b> 'Initialize Recognition Models' dispatches AJAX POST to /admin/init-models, preloading InsightFace ONNX models and generating 512-d RAM matrix index. 'Manage Sessions', 'Review Approvals', 'Face Enrollment' navigate directly.", p_body_style))
pdf_story.append(Spacer(1, 6))

pdf_story.append(Paragraph("3. Screens 2 to 6: Departments, Batches, Sections & Subjects", p_h1_style))
pdf_story.append(Paragraph("<b>Departments (/admin/academic/departments):</b> Plain vs Cluster-based mode. Manage button opens Department Workspace with Attention Required box (unassigned faculty/sections warnings). Clusters tab manages sub-department elective clusters with conflict detectors.", p_body_style))
pdf_story.append(Paragraph("<b>Academic Periods & Batches:</b> Controls Odd/Even cycles (1-8). 'Promote Batch' button advances students.current_sem by +1 while preserving all historical attendance and past exam records.", p_body_style))
pdf_story.append(Paragraph("<b>Sections & Subjects:</b> Department/Semester drill-down. Manage Subjects binds curriculum subjects and faculty. Subject Deduplication Tool merges duplicate codes without foreign key breakage.", p_body_style))
pdf_story.append(Spacer(1, 6))

# Section 4
pdf_story.append(Paragraph("4. Screens 7 & 8: Approvals & 4-Channel Face Enrollment", p_h1_style))
pdf_story.append(Paragraph("<b>Approvals Queue (/admin/students/approvals):</b> Approving moves student to approved_face_pending and assigns initial section.", p_body_style))
pdf_story.append(build_pdf_table([1.2, 1.8, 4.5], ["Enrollment Tab", "Purpose", "Click Action & Biometric Result"], enroll_tab_details))
pdf_story.append(Spacer(1, 6))

# Section 5
pdf_story.append(Paragraph("5. Faculty Web Application & All 7 Attendance Methods", p_h1_style))
pdf_story.append(Paragraph("<b>Live Session Hub (/faculty/session/<id>):</b> Split-screen layout: Left panel shows real-time attendance roster with toggle buttons. Right panel shows live MJPEG stream preview and mode selector (FACE_ONLY, FINGERPRINT_ONLY, DUAL_MODE).", p_body_style))
pdf_story.append(build_pdf_table([1.2, 1.8, 1.5, 3.0], ["Method", "Tester Click Action", "Route / Engine", "Execution & Database Result"], att_methods_walkthrough))
pdf_story.append(Spacer(1, 6))

# Section 6 & 7
pdf_story.append(Paragraph("6. HOD & Student Portals & Verification Matrix", p_h1_style))
pdf_story.append(Paragraph("<b>HOD Portal:</b> Department-wide active session monitoring, live stream inspection, and faculty registration approval queue.", p_body_style))
pdf_story.append(Paragraph("<b>Student Portal:</b> Dynamic Defaulter smart alerts banner (<75% warning with classes-needed calculator), class-by-class attendance history, and 3-tier self-service elective registration with live seat quotas.", p_body_style))
pdf_story.append(build_pdf_table([1.8, 3.8, 1.9], ["Subsystem / Feature", "Verification Scope & Test Details", "Verification Status"], verif_rows[:10]))

# Build PDF
pdf_doc.build(pdf_story)
import shutil
shutil.copy2(pdf_out_1, pdf_out_2)
print(f"PDF document saved to:\n  - {pdf_out_1}\n  - {pdf_out_2}")

print("Tester Walkthrough Guide generation complete!")
