import SQLite, { SQLiteDatabase } from 'react-native-sqlite-storage';

SQLite.enablePromise(true);
const DB_NAME = 'attendance_app.db';

let db: SQLiteDatabase | null = null;

async function columnExists(conn: SQLiteDatabase, table: string, column: string): Promise<boolean> {
  const [result] = await conn.executeSql(`PRAGMA table_info(${table});`);
  for (let i = 0; i < result.rows.length; i++) {
    if (result.rows.item(i).name === column) return true;
  }
  return false;
}

async function migrate(conn: SQLiteDatabase) {
  const [tableCheck] = await conn.executeSql(
    `SELECT name FROM sqlite_master WHERE type='table' AND name='student_gallery';`,
  );
  if (tableCheck.rows.length > 0) {
    const hasSectionId = await columnExists(conn, 'student_gallery', 'section_id');
    if (!hasSectionId) {
      await conn.executeSql(`ALTER TABLE student_gallery ADD COLUMN section_id INTEGER;`);
    }
  }

  const [queueCheck] = await conn.executeSql(
    `SELECT name FROM sqlite_master WHERE type='table' AND name='attendance_queue';`,
  );
  if (queueCheck.rows.length > 0) {
    const hasOldIdCol = await columnExists(conn, 'attendance_queue', 'id');
    if (hasOldIdCol) {
      // Old schema used a random-UUID `id` primary key. Migrate to the
      // composite (session_id, student_id) key that matches the backend's
      // own UNIQUE KEY (session_id, student_id) exactly.
      await conn.executeSql(`ALTER TABLE attendance_queue RENAME TO attendance_queue_old;`);
      await conn.executeSql(`
        CREATE TABLE attendance_queue (
          session_id INTEGER NOT NULL,
          student_id INTEGER NOT NULL,
          usn TEXT NOT NULL,
          student_name TEXT,
          match_score REAL NOT NULL,
          captured_at INTEGER NOT NULL,
          faculty_user_id INTEGER,
          status TEXT NOT NULL DEFAULT 'present',
          synced INTEGER DEFAULT 0,
          PRIMARY KEY (session_id, student_id)
        );
      `);
      // Old rows predate absent-tracking, so they were necessarily present marks.
      await conn.executeSql(`
        INSERT OR IGNORE INTO attendance_queue
          (session_id, student_id, usn, student_name, match_score, captured_at, faculty_user_id, status, synced)
        SELECT session_id, student_id, usn, student_name, match_score, captured_at, faculty_user_id, 'present', synced
        FROM attendance_queue_old
        ORDER BY captured_at DESC;
      `);
      await conn.executeSql(`DROP TABLE attendance_queue_old;`);
    } else {
      // Table already has the composite key from an earlier migration —
      // it may still be missing the `status` column from the later one.
      const hasStatusCol = await columnExists(conn, 'attendance_queue', 'status');
      if (!hasStatusCol) {
        await conn.executeSql(`ALTER TABLE attendance_queue ADD COLUMN status TEXT NOT NULL DEFAULT 'present';`);
      }
    }

    const hasMethodCol = await columnExists(conn, 'attendance_queue', 'method');
    if (!hasMethodCol) {
      await conn.executeSql(`ALTER TABLE attendance_queue ADD COLUMN method TEXT DEFAULT 'face_recognition';`);
    }

    const hasFpScoreCol = await columnExists(conn, 'attendance_queue', 'fingerprint_score');
    if (!hasFpScoreCol) {
      await conn.executeSql(`ALTER TABLE attendance_queue ADD COLUMN fingerprint_score REAL;`);
    }
  }
}

async function open(): Promise<SQLiteDatabase> {
  if (db) return db;
  db = await SQLite.openDatabase({ name: DB_NAME, location: 'default' });

  await migrate(db);

  await db.executeSql(`
    CREATE TABLE IF NOT EXISTS faculty_profile (
      id INTEGER PRIMARY KEY,
      name TEXT, email TEXT, department TEXT, designation TEXT,
      last_sync INTEGER
    );
  `);
  await db.executeSql(`
    CREATE TABLE IF NOT EXISTS faculty_sections (
      section_id INTEGER PRIMARY KEY,
      section_label TEXT NOT NULL,
      sem_number INTEGER
    );
  `);
  await db.executeSql(`
    CREATE TABLE IF NOT EXISTS faculty_subjects (
      subject_id INTEGER PRIMARY KEY,
      name TEXT NOT NULL,
      code TEXT
    );
  `);
  await db.executeSql(`
    CREATE TABLE IF NOT EXISTS student_gallery (
      student_id INTEGER PRIMARY KEY,
      usn TEXT NOT NULL,
      name TEXT,
      section_id INTEGER,
      model_id TEXT NOT NULL,
      embedding_json TEXT NOT NULL,
      synced_at INTEGER NOT NULL
    );
  `);

  await db.executeSql(`
    CREATE TABLE IF NOT EXISTS fingerprint_templates (
      template_id INTEGER PRIMARY KEY,
      student_id INTEGER NOT NULL,
      usn TEXT NOT NULL,
      name TEXT,
      section_id INTEGER,
      camera_id INTEGER,
      synced_at INTEGER NOT NULL
    );
  `);

  await db.executeSql(`
    CREATE TABLE IF NOT EXISTS attendance_queue (
      session_id INTEGER NOT NULL,
      student_id INTEGER NOT NULL,
      usn TEXT NOT NULL,
      student_name TEXT,
      match_score REAL NOT NULL,
      captured_at INTEGER NOT NULL,
      faculty_user_id INTEGER,
      status TEXT NOT NULL DEFAULT 'present',
      method TEXT DEFAULT 'face_recognition',
      fingerprint_score REAL,
      synced INTEGER DEFAULT 0,
      PRIMARY KEY (session_id, student_id)
    );
  `);
  await db.executeSql(`CREATE INDEX IF NOT EXISTS idx_queue_synced ON attendance_queue(synced);`);
  await db.executeSql(`CREATE INDEX IF NOT EXISTS idx_queue_faculty ON attendance_queue(faculty_user_id);`);

  await db.executeSql(`
    CREATE TABLE IF NOT EXISTS session_roster (
      session_id INTEGER NOT NULL,
      student_id INTEGER NOT NULL,
      usn TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'absent',
      PRIMARY KEY (session_id, student_id)
    );
  `);
  await db.executeSql(`
    CREATE TABLE IF NOT EXISTS timetable_sessions (
      session_id INTEGER PRIMARY KEY,
      session_date TEXT NOT NULL,
      start_time TEXT, end_time TEXT,
      section_id INTEGER NOT NULL,
      section_label TEXT, subject_name TEXT, status TEXT
    );
  `);

  return db;
}

// ---- Faculty profile / sections / subjects (initial setup cache) ----

export async function saveFacultyProfile(p: {
  userId?: number; name: string; email: string; department: string | null; designation: string | null;
}) {
  const conn = await open();
  await conn.executeSql(`DELETE FROM faculty_profile`);
  await conn.executeSql(
    `INSERT OR REPLACE INTO faculty_profile (id, name, email, department, designation, last_sync)
     VALUES (1, ?, ?, ?, ?, ?)`,
    [p.name, p.email, p.department, p.designation, Date.now()],
  );
}

export async function getFacultyProfile(userId?: number) {
  const conn = await open();
  const [result] = await conn.executeSql(`SELECT * FROM faculty_profile ORDER BY last_sync DESC LIMIT 1`);
  return result.rows.length ? result.rows.item(0) : null;
}

export async function saveFacultySections(sections: { section_id: number; section_label: string; sem_number: number }[]) {
  const conn = await open();
  await conn.executeSql(`DELETE FROM faculty_sections`);
  for (const s of sections) {
    try {
      await conn.executeSql(
        `INSERT OR REPLACE INTO faculty_sections (section_id, section_label, sem_number) VALUES (?, ?, ?)`,
        [s.section_id, s.section_label ?? `Section ${s.section_id}`, s.sem_number ?? 1],
      );
    } catch (e) {
      console.warn('[AttendanceDatabase] skipped bad section row', s, e);
    }
  }
}

export async function getFacultySections() {
  const conn = await open();
  const [result] = await conn.executeSql(`SELECT * FROM faculty_sections ORDER BY sem_number, section_label`);
  const out = [];
  for (let i = 0; i < result.rows.length; i++) out.push(result.rows.item(i));
  return out;
}

export async function saveFacultySubjects(subjects: { subject_id: number; name: string; code: string }[]) {
  const conn = await open();
  await conn.executeSql(`DELETE FROM faculty_subjects`);
  for (const s of subjects) {
    try {
      await conn.executeSql(
        `INSERT OR REPLACE INTO faculty_subjects (subject_id, name, code) VALUES (?, ?, ?)`,
        [s.subject_id, s.name, s.code ?? null],
      );
    } catch (e) {
      console.warn('[AttendanceDatabase] skipped bad subject row', s, e);
    }
  }
}

export async function getFacultySubjects() {
  const conn = await open();
  const [result] = await conn.executeSql(`SELECT * FROM faculty_subjects ORDER BY name`);
  const out = [];
  for (let i = 0; i < result.rows.length; i++) out.push(result.rows.item(i));
  return out;
}

// ---- Timetable sessions cache ----

export async function saveTimetableSessions(sessions: any[]) {
  const conn = await open();
  await conn.executeSql(`DELETE FROM timetable_sessions`);
  for (const s of sessions) {
    try {
      await conn.executeSql(
        `INSERT OR REPLACE INTO timetable_sessions
          (session_id, session_date, start_time, end_time, section_id, section_label, subject_name, status)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
        [s.session_id, s.session_date, s.start_time, s.end_time, s.section_id, s.section_label, s.subject_name ?? null, s.status ?? null],
      );
    } catch (e) {
      console.warn('[AttendanceDatabase] skipped bad session row', s, e);
    }
  }
}

export async function getTimetableSessions() {
  const conn = await open();
  const [result] = await conn.executeSql(`SELECT * FROM timetable_sessions ORDER BY session_date, start_time`);
  const out = [];
  for (let i = 0; i < result.rows.length; i++) out.push(result.rows.item(i));
  return out;
}

// ---- Student gallery (synced from /api/mobile/embeddings) ----
// Upserts by student_id instead of wiping the whole table, so syncing one
// section's embeddings never deletes another section's cached faces.

export async function upsertGallery(
  rows: { student_id: number; usn: string; name: string; section_id: number; embedding: number[] }[],
  modelId: string,
) {
  const conn = await open();
  const now = Date.now();
  for (const r of rows) {
    try {
      await conn.executeSql(
        `INSERT OR REPLACE INTO student_gallery
          (student_id, usn, name, section_id, model_id, embedding_json, synced_at)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
        [r.student_id, r.usn, r.name, r.section_id, modelId, JSON.stringify(r.embedding), now],
      );
    } catch (e) {
      console.warn('[AttendanceDatabase] skipped bad gallery row', r.student_id, e);
    }
  }
}

/**
 * Deletes any gallery row NOT in the given set of student IDs. Call this
 * once after a full setup/re-sync completes, so leftover rows from an
 * older app version (or a student removed from your sections) can never
 * silently linger and corrupt a future recognition pass.
 */
export async function reconcileGallery(validStudentIds: number[]) {
  const conn = await open();
  if (validStudentIds.length === 0) {
    await conn.executeSql(`DELETE FROM student_gallery`);
    return;
  }
  const placeholders = validStudentIds.map(() => '?').join(',');
  await conn.executeSql(
    `DELETE FROM student_gallery WHERE student_id NOT IN (${placeholders})`,
    validStudentIds,
  );
}

/** Only used when switching accounts / full re-setup, never on a routine per-section sync. */
export async function clearGallery() {
  const conn = await open();
  await conn.executeSql(`DELETE FROM student_gallery`);
}

export interface GalleryEntry {
  student_id: number;
  usn: string;
  name: string;
  embedding: Float32Array;
  section_id?: number;
}

export async function getGallery(): Promise<GalleryEntry[]> {
  const conn = await open();
  const [result] = await conn.executeSql(`SELECT * FROM student_gallery`);
  const out: GalleryEntry[] = [];
  for (let i = 0; i < result.rows.length; i++) {
    const row = result.rows.item(i);
    out.push({
      student_id: row.student_id,
      usn: row.usn,
      name: row.name,
      embedding: new Float32Array(JSON.parse(row.embedding_json)),
      section_id: row.section_id ?? undefined,
    });
  }
  return out;
}

export async function getGallerySyncedAt(): Promise<number | null> {
  const conn = await open();
  const [result] = await conn.executeSql(`SELECT MAX(synced_at) as t FROM student_gallery`);
  return result.rows.item(0)?.t ?? null;
}

// ---- Fingerprint templates cache ----

export interface FingerprintTemplateEntry {
  template_id: number;
  student_id: number;
  usn: string;
  name: string;
  section_id?: number;
  camera_id?: number;
}

export async function upsertFingerprintTemplates(
  rows: { template_id: number; student_id: number; usn: string; name: string; section_id?: number; camera_id?: number }[],
) {
  const conn = await open();
  const now = Date.now();
  for (const r of rows) {
    try {
      await conn.executeSql(
        `INSERT OR REPLACE INTO fingerprint_templates
          (template_id, student_id, usn, name, section_id, camera_id, synced_at)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
        [r.template_id, r.student_id, r.usn, r.name, r.section_id ?? null, r.camera_id ?? null, now],
      );
    } catch (e) {
      console.warn('[AttendanceDatabase] skipped bad fingerprint template row', r.template_id, e);
    }
  }
}

export async function lookupStudentByFingerprint(templateId: number): Promise<FingerprintTemplateEntry | null> {
  const conn = await open();
  const [result] = await conn.executeSql(
    `SELECT * FROM fingerprint_templates WHERE template_id = ? LIMIT 1`,
    [templateId],
  );
  if (result.rows.length > 0) {
    const r = result.rows.item(0);
    return {
      template_id: r.template_id,
      student_id: r.student_id,
      usn: r.usn,
      name: r.name,
      section_id: r.section_id ?? undefined,
      camera_id: r.camera_id ?? undefined,
    };
  }
  return null;
}

export async function getFingerprintTemplates(sectionId?: number): Promise<FingerprintTemplateEntry[]> {
  const conn = await open();
  let query = `SELECT * FROM fingerprint_templates`;
  const params: any[] = [];
  if (sectionId != null) {
    query += ` WHERE section_id = ?`;
    params.push(sectionId);
  }
  query += ` ORDER BY template_id`;
  const [result] = await conn.executeSql(query, params);
  const out: FingerprintTemplateEntry[] = [];
  for (let i = 0; i < result.rows.length; i++) {
    const r = result.rows.item(i);
    out.push({
      template_id: r.template_id,
      student_id: r.student_id,
      usn: r.usn,
      name: r.name,
      section_id: r.section_id ?? undefined,
      camera_id: r.camera_id ?? undefined,
    });
  }
  return out;
}

// ---- Attendance queue (offline-first, faculty + session scoped) ----

export async function queueAttendance(rec: {
  session_id: number; student_id: number; usn: string;
  student_name: string; match_score: number; captured_at: number;
  faculty_user_id: number; status: 'present' | 'absent';
  method?: string; fingerprint_score?: number;
}) {
  const conn = await open();
  const method = rec.method ?? (rec.match_score != null ? 'face_recognition' : 'manual_individual');
  const fpScore = rec.fingerprint_score ?? null;

  await conn.executeSql(
    `INSERT OR REPLACE INTO attendance_queue
      (session_id, student_id, usn, student_name, match_score, captured_at, faculty_user_id, status, method, fingerprint_score, synced)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)`,
    [rec.session_id, rec.student_id, rec.usn, rec.student_name, rec.match_score, rec.captured_at, rec.faculty_user_id, rec.status, method, fpScore],
  );
}

/** Latest locally-known status per student for this session — reflects
 * whatever the faculty (or recognition) most recently did, present or absent. */
export async function getQueuedStatuses(sessionId: number): Promise<Map<number, 'present' | 'absent'>> {
  const conn = await open();
  const [result] = await conn.executeSql(
    `SELECT student_id, status FROM attendance_queue WHERE session_id = ?`,
    [sessionId],
  );
  const map = new Map<number, 'present' | 'absent'>();
  for (let i = 0; i < result.rows.length; i++) {
    const row = result.rows.item(i);
    map.set(row.student_id, row.status);
  }
  return map;
}

/** Only this faculty's unsynced records, across ALL of their sessions. */
export async function getPendingAttendance(facultyUserId: number) {
  const conn = await open();
  const [result] = await conn.executeSql(
    `SELECT * FROM attendance_queue WHERE synced = 0 AND faculty_user_id = ? ORDER BY captured_at DESC`,
    [facultyUserId],
  );
  const out = [];
  for (let i = 0; i < result.rows.length; i++) out.push(result.rows.item(i));
  return out;
}

/** Marks specific (session_id, student_id) pairs synced — only if they
 * belong to this faculty. */
export async function markSynced(pairs: { session_id: number; student_id: number }[], facultyUserId: number) {
  const conn = await open();
  for (const p of pairs) {
    await conn.executeSql(
      `UPDATE attendance_queue SET synced = 1 WHERE faculty_user_id = ? AND session_id = ? AND student_id = ?`,
      [facultyUserId, p.session_id, p.student_id],
    );
  }
}

/** Whether this student already has a queued record for this specific
 * session — scoped by session, so back-to-back sessions never interfere
 * with each other's recognition state. */
export async function isAlreadyQueued(sessionId: number, studentId: number): Promise<boolean> {
  const conn = await open();
  const [result] = await conn.executeSql(
    `SELECT 1 FROM attendance_queue WHERE session_id = ? AND student_id = ? LIMIT 1`,
    [sessionId, studentId],
  );
  return result.rows.length > 0;
}

// ---- Session roster cache ----

export async function saveRoster(sessionId: number, roster: { student_id: number; usn: string; name: string; status: string }[]) {
  const conn = await open();
  await conn.executeSql(`DELETE FROM session_roster WHERE session_id = ?`, [sessionId]);
  for (const r of roster) {
    try {
      await conn.executeSql(
        `INSERT INTO session_roster (session_id, student_id, usn, name, status) VALUES (?, ?, ?, ?, ?)`,
        [sessionId, r.student_id, r.usn, r.name, r.status],
      );
    } catch (e) {
      console.warn('[AttendanceDatabase] skipped bad roster row', r, e);
    }
  }
}

export async function getRoster(sessionId: number) {
  const conn = await open();
  const [result] = await conn.executeSql(`SELECT * FROM session_roster WHERE session_id = ?`, [sessionId]);
  const out = [];
  for (let i = 0; i < result.rows.length; i++) out.push(result.rows.item(i));
  return out;
}

export async function wipeAllLocalData() {
  const conn = await open();
  const tables = [
    'faculty_profile', 'faculty_sections', 'faculty_subjects',
    'student_gallery', 'timetable_sessions', 'fingerprint_templates', 'session_roster',
  ];
  for (const t of tables) {
    try {
      await conn.executeSql(`DELETE FROM ${t}`);
    } catch (e) {
      console.warn(`[AttendanceDatabase] wipeAllLocalData: failed to clear ${t}`, e);
    }
  }
}