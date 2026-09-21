-- ================================================================
-- continue_integration/db_migrations/001_create_integration_tables.sql
--
-- Run this on the AttendAI MySQL database ONCE before enabling sync.
-- These tables are ADDITIONS only — nothing in existing tables is changed.
--
-- Run: mysql -u root -p attendance_system < 001_create_integration_tables.sql
-- ================================================================

-- ----------------------------------------------------------------
-- Table 1: continue_sync_log
-- Tracks whether each attendance record was pushed to Continue
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS continue_sync_log (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    attendance_id  INT          NOT NULL COMMENT 'FK to attendance_records.id',
    continue_ref   VARCHAR(200) NULL     COMMENT 'Reference ID returned by Continue portal',
    status         ENUM('pending','synced','failed') NOT NULL DEFAULT 'pending',
    attempts       INT          NOT NULL DEFAULT 0,
    last_error     TEXT         NULL     COMMENT 'Last error message from Continue API',
    synced_at      DATETIME     NULL     COMMENT 'When successfully synced',
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_attendance (attendance_id),
    INDEX idx_status   (status),
    INDEX idx_attempts (attempts),
    INDEX idx_created  (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Tracks sync status of each attendance record to Continue portal';


-- ----------------------------------------------------------------
-- Table 2: continue_student_map
-- Maps AttendAI internal student IDs ↔ Continue portal student IDs
-- This handles the case where both systems use different ID formats
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS continue_student_map (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    student_id            INT          NOT NULL COMMENT 'AttendAI students.id',
    continue_student_id   VARCHAR(100) NOT NULL COMMENT 'Continue portal student identifier (roll_no / usn / custom)',
    continue_section_id   VARCHAR(100) NULL     COMMENT 'Continue portal section identifier (if applicable)',
    imported_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_student        (student_id),
    UNIQUE KEY uq_continue_id    (continue_student_id),
    INDEX  idx_continue_student  (continue_student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Maps AttendAI students to Continue portal student IDs';


-- ----------------------------------------------------------------
-- Table 3: integration_settings
-- Stores Continue API config from admin dashboard (API URL, key etc.)
-- (Alternative to .env — lets admin update keys without SSH access)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS integration_settings (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    key_name   VARCHAR(100) NOT NULL UNIQUE,
    key_value  TEXT         NULL,
    is_secret  TINYINT(1)   NOT NULL DEFAULT 0  COMMENT '1 = mask in UI',
    updated_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Continue integration configuration (API URL, key, mode, etc.)';


-- Pre-populate default setting keys (values filled by admin)
INSERT IGNORE INTO integration_settings (key_name, key_value, is_secret) VALUES
    ('continue_api_base_url',   '',       0),
    ('continue_api_key',        '',       1),   -- masked in UI
    ('continue_auth_type',      'bearer', 0),
    ('continue_sync_enabled',   'false',  0),
    ('continue_sync_mode',      'realtime', 0),
    ('continue_student_id_field', 'roll_no', 0),
    ('continue_subject_field',  'subject_code', 0),
    ('continue_max_retries',    '5',      0),
    ('continue_api_timeout',    '10',     0);


-- ----------------------------------------------------------------
-- Verification queries (run after migration to confirm success)
-- ----------------------------------------------------------------
-- SELECT table_name FROM information_schema.tables
-- WHERE table_schema = 'attendance_system'
--   AND table_name IN ('continue_sync_log','continue_student_map','integration_settings');
