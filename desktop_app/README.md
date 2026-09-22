# AttendAI - Faculty Desktop Edge Attendance Station

A high-performance, offline-first desktop application for faculty to conduct multi-photo AI classroom attendance right on their workstations or laptops.

---

## Why Desktop Edge Attendance?

1. **Zero Inference Load on Central Flask Server**:
   Instead of uploading dozens of 10-20 MB 4K classroom photos to the central server during peak morning hours, all face detection and 512-d feature extraction runs locally on the faculty PC.
2. **Bundled Server-Grade Recognition Models**:
   The desktop app bundles the exact same **InsightFace `buffalo_l`** models (`det_10g.onnx` SCRFD face detector + `w600k_r50.onnx` ArcFace feature extractor + `w600k_mbf.onnx` MobileFaceNet). No model downloads are required at runtime.
3. **Mobile-Style Offline Sync Architecture**:
   Just like the faculty mobile app, the desktop app downloads student embeddings and session rosters via REST API, caches them in local SQLite, and buffers marked attendance offline when network connectivity is intermittent.
4. **Visual Verification**:
   Displays full classroom photos with overlaid bounding boxes (green for recognized with USN & confidence %, red/orange for unrecognized faces) alongside an editable roster table.

---

## Directory Structure

```
desktop_app/
├── core/
│   ├── engine.py              # DesktopRecognitionEngine with bundled ONNX / InsightFace
│   └── matcher.py             # Multi-photo classroom batch recognition & deduplication
├── database/
│   └── local_store.py         # Local SQLite cache for offline rosters, embeddings & queue
├── network/
│   └── api_client.py          # REST API client connecting to Flask backend
├── models/                    # Bundled ONNX recognition models
│   ├── buffalo_l/
│   │   ├── det_10g.onnx       # SCRFD 10G face detector
│   │   └── w600k_r50.onnx     # ArcFace ResNet-50 512-d embedding extractor
│   └── w600k_mbf.onnx         # MobileFaceNet 512-d embedding extractor
├── ui/
│   ├── styles.py              # Modern Windows 11 Fluent dark theme stylesheet
│   ├── login_window.py        # Authentication & server connection dialog
│   ├── attendance_view.py     # Main attendance split-pane workspace
│   └── main_window.py         # Tabbed main dashboard
├── main.py                    # Application entrypoint
├── requirements.txt           # Python dependencies
└── run_desktop.bat            # 1-click Windows launcher
```

---

## Quick Start (How to Run)

### Method 1: Using the 1-Click Windows Launcher
Double-click `run_desktop.bat` in `desktop_app/` (or run it from the root folder).

### Method 2: Command Line
```powershell
# Using the project's virtual environment:
attendance_system_test\venv\Scripts\python.exe desktop_app\main.py
```

---

## Faculty Workflow

1. **Sign In**:
   - Enter your Central Flask Server URL (e.g. `http://localhost:5000` or the campus server IP).
   - Enter your faculty email and password.
   - If internet is unavailable, click **"Work in Offline Mode"** to use locally cached rosters.

2. **Select Class & Sync**:
   - Choose your active class session from the dropdown.
   - Click **"Sync Roster & Embeddings"** to ensure your local cache has the latest enrolled students and 512-d vectors.

3. **Add Classroom Photos**:
   - Click **"Add Classroom Photos"** and select 1 to 3 wide-angle photos of the classroom (or click **"Capture Webcam"**).

4. **Run Edge Recognition**:
   - Click **"Run Edge Recognition"**.
   - The desktop app detects all faces, extracts 512-d embeddings, computes cosine similarity against your class roster, and deduplicates students across photos in seconds.

5. **Review & Verify**:
   - Inspect green bounding boxes on the photo preview.
   - Toggle checkboxes in the attendance table for any manual corrections.
   - View real-time statistics: Total Roster, Present, Absent, and Unrecognized count.

6. **Submit Attendance**:
   - Click **"Submit Finalized Attendance"**.
   - If connected, attendance is pushed immediately to the central database.
   - If network drops, records are safely queued in local SQLite and automatically synced when reconnected.

---

## Packaging as Standalone Windows Executable (.exe)

To bundle the entire desktop app into a standalone Windows executable using PyInstaller:

```powershell
attendance_system_test\venv\Scripts\pip.exe install pyinstaller

attendance_system_test\venv\Scripts\pyinstaller.exe `
    --noconfirm `
    --onedir `
    --windowed `
    --name "AttendAI_Edge_Station" `
    --add-data "desktop_app/models;models" `
    desktop_app/main.py
```
The resulting executable will be located in `dist/AttendAI_Edge_Station/AttendAI_Edge_Station.exe`.
