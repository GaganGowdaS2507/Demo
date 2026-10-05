"""Acceptance test: only services/timetable_engine.py may INSERT into sessions."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWED = {os.path.join("services", "timetable_engine.py")}
SKIP_DIRS = {"venv", ".venv", "__pycache__", ".git", "node_modules", "tests"}
PATTERN = re.compile(r"INSERT\s+(?:IGNORE\s+)?INTO\s+sessions\b", re.I)


def test_only_the_engine_creates_sessions():
    offenders = []
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, ROOT)
            if rel in ALLOWED:
                continue
            text = open(path, encoding="utf-8", errors="ignore").read()
            for m in PATTERN.finditer(text):
                line_no = text.count("\n", 0, m.start()) + 1
                line = text.split("\n")[line_no - 1].lstrip()
                if not line.startswith("#"):
                    offenders.append(f"{rel}:{line_no}")
    assert not offenders, "Session INSERT found outside the engine: " + ", ".join(offenders)