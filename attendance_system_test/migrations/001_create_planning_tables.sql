-- =====================================================================
-- 001_create_planning_tables.sql
-- NEW tables only. Safe to run many times (IF NOT EXISTS / INSERT IGNORE).
-- Normally you do NOT run this by hand: migrate_001_planning.py runs it.
-- =====================================================================

-- 1) Types of calendar events (admin can add more later) --------------
CREATE TABLE IF NOT EXISTS calendar_event_types (
  id          INT NOT NULL AUTO_INCREMENT,
  code        VARCHAR(40)  NOT NULL,
  name        VARCHAR(100) NOT NULL,
  effect      ENUM('blocks_teaching','allows_teaching','info_only')
              NOT NULL DEFAULT 'blocks_teaching',
  color       VARCHAR(10)  DEFAULT NULL,
  is_system   TINYINT(1)   NOT NULL DEFAULT 0,
  is_active   TINYINT(1)   NOT NULL DEFAULT 1,
  created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_event_type_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO calendar_event_types (code, name, effect, color, is_system) VALUES
  ('HOLIDAY',             'Holiday',                  'blocks_teaching', '#e53935', 1),
  ('COLLEGE_EVENT',       'College Event',            'blocks_teaching', '#8e24aa', 1),
  ('DEPT_EVENT',          'Department Event',         'blocks_teaching', '#5e35b1', 1),
  ('INTERNAL_ASSESSMENT', 'Internal Assessment',      'blocks_teaching', '#00897b', 1),
  ('SEMESTER_EXAM',       'Semester End Exam',        'blocks_teaching', '#3949ab', 1),
  ('NON_TEACHING_DAY',    'Special Non-Teaching Day', 'blocks_teaching', '#757575', 1),
  ('SPECIAL_WORKING_DAY', 'Special Working Day',      'allows_teaching', '#43a047', 1),
  ('PROJECT_REVIEW',      'Project Review',           'info_only',       '#1e88e5', 1),
  ('PTM',                 'Parents Teachers Meeting', 'info_only',       '#f4511e', 1),
  ('DEADLINE',            'Deadline / Notice',        'info_only',       '#fb8c00', 1);

-- 2) Calendar events (one row = one date range) -----------------------
--    academic_period_id NULL  = applies to EVERY period (e.g. national holiday)
CREATE TABLE IF NOT EXISTS calendar_events (
  id                  INT NOT NULL AUTO_INCREMENT,
  academic_period_id  INT DEFAULT NULL,
  event_type_id       INT NOT NULL,
  title               VARCHAR(150) NOT NULL,
  start_date          DATE NOT NULL,
  end_date            DATE NOT NULL,
  start_time          TIME DEFAULT NULL,
  end_time            TIME DEFAULT NULL,
  scope               ENUM('college','department','section') NOT NULL DEFAULT 'college',
  department_id       INT DEFAULT NULL,
  section_id          INT DEFAULT NULL,
  follow_weekday      ENUM('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday') DEFAULT NULL,
  effect_override     ENUM('blocks_teaching','allows_teaching','info_only') DEFAULT NULL,
  notes               VARCHAR(255) DEFAULT NULL,
  source              ENUM('manual','import','legacy_holiday') NOT NULL DEFAULT 'manual',
  created_by          INT DEFAULT NULL,
  created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at          TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_ce_period_dates (academic_period_id, start_date, end_date),
  KEY idx_ce_dates (start_date, end_date),
  KEY idx_ce_type (event_type_id),
  KEY idx_ce_dept (department_id),
  KEY idx_ce_section (section_id),
  KEY idx_ce_created_by (created_by),
  CONSTRAINT fk_ce_period  FOREIGN KEY (academic_period_id) REFERENCES academic_periods (id) ON DELETE CASCADE,
  CONSTRAINT fk_ce_type    FOREIGN KEY (event_type_id)      REFERENCES calendar_event_types (id),
  CONSTRAINT fk_ce_dept    FOREIGN KEY (department_id)      REFERENCES departments (id) ON DELETE CASCADE,
  CONSTRAINT fk_ce_section FOREIGN KEY (section_id)         REFERENCES sections (id) ON DELETE CASCADE,
  CONSTRAINT fk_ce_user    FOREIGN KEY (created_by)         REFERENCES users (id) ON DELETE SET NULL,
  CONSTRAINT chk_ce_dates  CHECK (end_date >= start_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 3) Planned sessions (what SHOULD happen; built by the planner) ------
CREATE TABLE IF NOT EXISTS planned_sessions (
  id                    INT NOT NULL AUTO_INCREMENT,
  academic_period_id    INT NOT NULL,
  timetable_id          INT DEFAULT NULL,
  section_id            INT NOT NULL,
  elective_group_id     INT DEFAULT NULL,
  subject_id            INT DEFAULT NULL,
  faculty_id            INT DEFAULT NULL,
  substitute_faculty_id INT DEFAULT NULL,
  planned_date          DATE NOT NULL,
  start_time            TIME NOT NULL,
  end_time              TIME NOT NULL,
  room                  VARCHAR(50) DEFAULT NULL,
  component             ENUM('theory','lab') NOT NULL DEFAULT 'theory',
  origin                ENUM('timetable','moved','extra') NOT NULL DEFAULT 'timetable',
  status                ENUM('planned','cancelled','moved') NOT NULL DEFAULT 'planned',
  block_event_id        INT DEFAULT NULL,
  created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at            TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_planned_slot_date (timetable_id, planned_date, origin),
  KEY idx_ps_period_date (academic_period_id, planned_date),
  KEY idx_ps_section_date (section_id, planned_date),
  KEY idx_ps_faculty_date (faculty_id, planned_date),
  KEY idx_ps_subject (subject_id),
  KEY idx_ps_group (elective_group_id),
  KEY idx_ps_event (block_event_id),
  CONSTRAINT fk_ps_period    FOREIGN KEY (academic_period_id) REFERENCES academic_periods (id),
  CONSTRAINT fk_ps_timetable FOREIGN KEY (timetable_id)       REFERENCES timetable (id) ON DELETE SET NULL,
  CONSTRAINT fk_ps_section   FOREIGN KEY (section_id)         REFERENCES sections (id) ON DELETE CASCADE,
  CONSTRAINT fk_ps_group     FOREIGN KEY (elective_group_id)  REFERENCES elective_groups (id) ON DELETE SET NULL,
  CONSTRAINT fk_ps_subject   FOREIGN KEY (subject_id)         REFERENCES subjects (id) ON DELETE SET NULL,
  CONSTRAINT fk_ps_faculty   FOREIGN KEY (faculty_id)         REFERENCES faculty (id) ON DELETE SET NULL,
  CONSTRAINT fk_ps_sub_fac   FOREIGN KEY (substitute_faculty_id) REFERENCES faculty (id) ON DELETE SET NULL,
  CONSTRAINT fk_ps_event     FOREIGN KEY (block_event_id)     REFERENCES calendar_events (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 4) Exceptions (one-day changes; timetable and calendar stay untouched)
CREATE TABLE IF NOT EXISTS session_exceptions (
  id                     INT NOT NULL AUTO_INCREMENT,
  planned_session_id     INT NOT NULL,
  exception_type         ENUM('cancel','move','extra','substitute','room_change') NOT NULL,
  new_date               DATE DEFAULT NULL,
  new_start_time         TIME DEFAULT NULL,
  new_end_time           TIME DEFAULT NULL,
  new_faculty_id         INT DEFAULT NULL,
  new_room               VARCHAR(50) DEFAULT NULL,
  new_planned_session_id INT DEFAULT NULL,
  reason                 VARCHAR(255) DEFAULT NULL,
  is_active              TINYINT(1) NOT NULL DEFAULT 1,
  created_by             INT DEFAULT NULL,
  created_at             DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_se_planned (planned_session_id),
  KEY idx_se_new_planned (new_planned_session_id),
  KEY idx_se_faculty (new_faculty_id),
  KEY idx_se_user (created_by),
  CONSTRAINT fk_se_planned     FOREIGN KEY (planned_session_id)     REFERENCES planned_sessions (id) ON DELETE CASCADE,
  CONSTRAINT fk_se_new_planned FOREIGN KEY (new_planned_session_id) REFERENCES planned_sessions (id) ON DELETE SET NULL,
  CONSTRAINT fk_se_faculty     FOREIGN KEY (new_faculty_id)         REFERENCES faculty (id) ON DELETE SET NULL,
  CONSTRAINT fk_se_user        FOREIGN KEY (created_by)             REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;