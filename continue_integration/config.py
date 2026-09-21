"""
continue_integration/config.py
Configuration for Continue portal integration.
Fill in values from .env once API keys are received from college.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────
# CONTINUE PORTAL API CONFIG  (all from .env — never hardcode)
# ─────────────────────────────────────────────────────────────

CONTINUE_API_BASE_URL  = os.getenv("CONTINUE_API_BASE_URL", "")       # e.g. https://college.continue.in/api/v1
CONTINUE_API_KEY       = os.getenv("CONTINUE_API_KEY", "")            # Bearer token / API key
CONTINUE_API_VERSION   = os.getenv("CONTINUE_API_VERSION", "v1")      # API version
CONTINUE_SYNC_ENABLED  = os.getenv("CONTINUE_SYNC_ENABLED", "false").lower() == "true"

# ─────────────────────────────────────────────────────────────
# SYNC BEHAVIOUR
# ─────────────────────────────────────────────────────────────

SYNC_MODE              = os.getenv("CONTINUE_SYNC_MODE", "realtime")  # "realtime" or "batch"
BATCH_SYNC_INTERVAL_MIN= int(os.getenv("CONTINUE_BATCH_INTERVAL", "60"))  # minutes (batch mode)
MAX_RETRY_ATTEMPTS     = int(os.getenv("CONTINUE_MAX_RETRIES", "5"))
RETRY_BACKOFF_MIN      = int(os.getenv("CONTINUE_RETRY_BACKOFF", "30"))   # minutes between retries
API_TIMEOUT_SEC        = int(os.getenv("CONTINUE_API_TIMEOUT", "10"))

# ─────────────────────────────────────────────────────────────
# STUDENT ID FIELD MAPPING
# Update this once we know how Continue identifies students
# ─────────────────────────────────────────────────────────────

# Which field from AttendAI maps to Continue's student identifier?
# Options: "usn", "email", "roll_number", "college_id"
STUDENT_ID_FIELD_IN_ATTENDAI   = os.getenv("CONTINUE_STUDENT_ID_FIELD", "usn")

# What Continue calls the student ID field in their API
# e.g., "roll_no", "student_id", "reg_no" — ask college
CONTINUE_STUDENT_ID_FIELD_NAME = os.getenv("CONTINUE_STUDENT_FIELD_NAME", "roll_no")

# ─────────────────────────────────────────────────────────────
# SUBJECT MAPPING
# Update once Continue shares subject/course code format
# ─────────────────────────────────────────────────────────────

# What Continue calls the subject in their API — ask college
CONTINUE_SUBJECT_FIELD_NAME    = os.getenv("CONTINUE_SUBJECT_FIELD", "subject_code")

# ─────────────────────────────────────────────────────────────
# AUTHENTICATION TYPE  (will know once API docs received)
# Options: "bearer", "api_key_header", "basic", "oauth2"
# ─────────────────────────────────────────────────────────────

AUTH_TYPE = os.getenv("CONTINUE_AUTH_TYPE", "bearer")

# ─────────────────────────────────────────────────────────────
# AttendAI MAIN DB  (to read attendance records for syncing)
# These should match attendance_system_test/.env values
# ─────────────────────────────────────────────────────────────

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "")
DB_NAME = os.getenv("DB_NAME", "attendance_system")
