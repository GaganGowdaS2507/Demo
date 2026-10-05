package com.example.fpattend

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import java.security.MessageDigest

data class CachedAuth(
    val email: String,
    val passwordHash: String,
    val token: String,
    val name: String,
    val facultyId: Int,
    val userId: Int,
    val role: String
)

data class FacultySession(
    val sessionId: Int,
    val sessionDate: String,
    val startTime: String,
    val endTime: String,
    val sectionId: Int,
    val sectionLabel: String,
    val subjectName: String,
    val status: String
)

data class StudentItem(
    val studentId: Int,
    val usn: String,
    val name: String,
    val sectionId: Int,
    val status: String = "absent",
    val method: String? = null
)

data class FingerprintTemplate(
    val templateId: Int,
    val studentId: Int,
    val usn: String,
    val name: String,
    val sectionId: Int
)

data class AttendanceRecord(
    val id: Long = 0,
    val sessionId: Int,
    val studentId: Int,
    val usn: String,
    val studentName: String,
    val score: Int,
    val timestamp: Long,
    val status: String = "present",
    val method: String = "fingerprint",
    val synced: Int = 0, // 0 = pending, 1 = synced
    val syncError: String? = null
)

data class RosterStudent(
    val studentId: Int,
    val usn: String,
    val name: String,
    val sectionId: Int,
    val status: String = "absent",
    val method: String = "",
    val score: Int = 0
)

class AppDatabase(context: Context) : SQLiteOpenHelper(context, DATABASE_NAME, null, DATABASE_VERSION) {

    companion object {
        private const val DATABASE_NAME = "fp_attend.db"
        private const val DATABASE_VERSION = 3

        @Volatile
        private var instance: AppDatabase? = null

        fun getInstance(context: Context): AppDatabase =
            instance ?: synchronized(this) {
                instance ?: AppDatabase(context.applicationContext).also { instance = it }
            }

        fun sha256(input: String): String {
            val md = MessageDigest.getInstance("SHA-256")
            val digest = md.digest(input.toByteArray())
            return digest.fold("") { str, it -> str + "%02x".format(it) }
        }
    }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("""
            CREATE TABLE auth_cache (
                email TEXT PRIMARY KEY,
                password_hash TEXT,
                token TEXT,
                name TEXT,
                faculty_id INTEGER,
                user_id INTEGER,
                role TEXT
            )
        """.trimIndent())

        db.execSQL("""
            CREATE TABLE sessions (
                session_id INTEGER PRIMARY KEY,
                session_date TEXT,
                start_time TEXT,
                end_time TEXT,
                section_id INTEGER,
                section_label TEXT,
                subject_name TEXT,
                status TEXT
            )
        """.trimIndent())

        db.execSQL("""
            CREATE TABLE students (
                student_id INTEGER PRIMARY KEY,
                usn TEXT,
                name TEXT,
                section_id INTEGER
            )
        """.trimIndent())

        db.execSQL("""
            CREATE TABLE fingerprints (
                template_id INTEGER PRIMARY KEY,
                student_id INTEGER,
                usn TEXT,
                name TEXT,
                section_id INTEGER
            )
        """.trimIndent())

        db.execSQL("""
            CREATE TABLE attendance_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                student_id INTEGER,
                usn TEXT,
                student_name TEXT,
                score INTEGER,
                timestamp INTEGER,
                status TEXT,
                method TEXT,
                synced INTEGER,
                sync_error TEXT,
                UNIQUE(session_id, student_id) ON CONFLICT REPLACE
            )
        """.trimIndent())
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        db.execSQL("DROP TABLE IF EXISTS auth_cache")
        db.execSQL("DROP TABLE IF EXISTS sessions")
        db.execSQL("DROP TABLE IF EXISTS students")
        db.execSQL("DROP TABLE IF EXISTS fingerprints")
        db.execSQL("DROP TABLE IF EXISTS attendance_queue")
        onCreate(db)
    }

    // ── Auth Cache ─────────────────────────────────────────────────────────────
    fun saveAuth(email: String, password: String, token: String, name: String, facultyId: Int, userId: Int, role: String) {
        val db = writableDatabase
        val cv = ContentValues().apply {
            put("email", email.trim().lowercase())
            put("password_hash", sha256(password))
            put("token", token)
            put("name", name)
            put("faculty_id", facultyId)
            put("user_id", userId)
            put("role", role)
        }
        db.insertWithOnConflict("auth_cache", null, cv, SQLiteDatabase.CONFLICT_REPLACE)
    }

    fun verifyOfflineAuth(email: String, password: String): CachedAuth? {
        val db = readableDatabase
        val cursor = db.rawQuery(
            "SELECT * FROM auth_cache WHERE email = ? AND password_hash = ?",
            arrayOf(email.trim().lowercase(), sha256(password))
        )
        cursor.use {
            if (it.moveToFirst()) {
                return CachedAuth(
                    email = it.getString(it.getColumnIndexOrThrow("email")),
                    passwordHash = it.getString(it.getColumnIndexOrThrow("password_hash")),
                    token = it.getString(it.getColumnIndexOrThrow("token")),
                    name = it.getString(it.getColumnIndexOrThrow("name")),
                    facultyId = it.getInt(it.getColumnIndexOrThrow("faculty_id")),
                    userId = it.getInt(it.getColumnIndexOrThrow("user_id")),
                    role = it.getString(it.getColumnIndexOrThrow("role"))
                )
            }
        }
        return null
    }

    fun getLatestAuth(): CachedAuth? {
        val db = readableDatabase
        val cursor = db.rawQuery("SELECT * FROM auth_cache LIMIT 1", null)
        cursor.use {
            if (it.moveToFirst()) {
                return CachedAuth(
                    email = it.getString(it.getColumnIndexOrThrow("email")),
                    passwordHash = it.getString(it.getColumnIndexOrThrow("password_hash")),
                    token = it.getString(it.getColumnIndexOrThrow("token")),
                    name = it.getString(it.getColumnIndexOrThrow("name")),
                    facultyId = it.getInt(it.getColumnIndexOrThrow("faculty_id")),
                    userId = it.getInt(it.getColumnIndexOrThrow("user_id")),
                    role = it.getString(it.getColumnIndexOrThrow("role"))
                )
            }
        }
        return null
    }

    // ── Sessions ───────────────────────────────────────────────────────────────
    fun saveSessions(sessions: List<FacultySession>) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            db.delete("sessions", null, null)
            for (s in sessions) {
                val cv = ContentValues().apply {
                    put("session_id", s.sessionId)
                    put("session_date", s.sessionDate)
                    put("start_time", s.startTime)
                    put("end_time", s.endTime)
                    put("section_id", s.sectionId)
                    put("section_label", s.sectionLabel)
                    put("subject_name", s.subjectName)
                    put("status", s.status)
                }
                db.insertWithOnConflict("sessions", null, cv, SQLiteDatabase.CONFLICT_REPLACE)
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun getAllSessions(): List<FacultySession> {
        val list = mutableListOf<FacultySession>()
        val db = readableDatabase
        val cursor = db.rawQuery("SELECT * FROM sessions ORDER BY session_date DESC, start_time DESC", null)
        cursor.use {
            while (it.moveToNext()) {
                list.add(
                    FacultySession(
                        sessionId = it.getInt(it.getColumnIndexOrThrow("session_id")),
                        sessionDate = it.getString(it.getColumnIndexOrThrow("session_date")),
                        startTime = it.getString(it.getColumnIndexOrThrow("start_time")),
                        endTime = it.getString(it.getColumnIndexOrThrow("end_time")),
                        sectionId = it.getInt(it.getColumnIndexOrThrow("section_id")),
                        sectionLabel = it.getString(it.getColumnIndexOrThrow("section_label")),
                        subjectName = it.getString(it.getColumnIndexOrThrow("subject_name")),
                        status = it.getString(it.getColumnIndexOrThrow("status"))
                    )
                )
            }
        }
        return list
    }

    // ── Students & Rosters ─────────────────────────────────────────────────────
    fun saveStudents(students: List<StudentItem>) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            for (s in students) {
                val cv = ContentValues().apply {
                    put("student_id", s.studentId)
                    put("usn", s.usn)
                    put("name", s.name)
                    if (s.sectionId > 0) {
                        put("section_id", s.sectionId)
                    }
                }
                if (s.sectionId == 0) {
                    val existing = findStudentByRoll(s.usn)
                    if (existing != null && existing.sectionId > 0) {
                        cv.put("section_id", existing.sectionId)
                    } else {
                        cv.put("section_id", 0)
                    }
                }
                db.insertWithOnConflict("students", null, cv, SQLiteDatabase.CONFLICT_REPLACE)
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun syncServerRosterAttendance(sessionId: Int, students: List<StudentItem>) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            val nowSec = System.currentTimeMillis() / 1000
            for (s in students) {
                if (s.status.lowercase() == "present") {
                    val cv = ContentValues().apply {
                        put("session_id", sessionId)
                        put("student_id", s.studentId)
                        put("usn", s.usn)
                        put("student_name", s.name)
                        put("status", "present")
                        put("method", s.method ?: "server_sync")
                        put("score", 100)
                        put("timestamp", nowSec)
                        put("synced", 1)
                    }
                    db.insertWithOnConflict("attendance_queue", null, cv, SQLiteDatabase.CONFLICT_IGNORE)
                }
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun getStudentsBySection(sectionId: Int): List<StudentItem> {
        val list = mutableListOf<StudentItem>()
        val db = readableDatabase
        val query = if (sectionId > 0) "SELECT * FROM students WHERE section_id = ? ORDER BY usn ASC" else "SELECT * FROM students ORDER BY usn ASC"
        val args = if (sectionId > 0) arrayOf(sectionId.toString()) else null
        val cursor = db.rawQuery(query, args)
        cursor.use {
            while (it.moveToNext()) {
                list.add(
                    StudentItem(
                        studentId = it.getInt(it.getColumnIndexOrThrow("student_id")),
                        usn = it.getString(it.getColumnIndexOrThrow("usn")),
                        name = it.getString(it.getColumnIndexOrThrow("name")),
                        sectionId = it.getInt(it.getColumnIndexOrThrow("section_id"))
                    )
                )
            }
        }
        // If specific section has no students found, fall back to all students so roster is never empty
        if (list.isEmpty() && sectionId > 0) {
            return getStudentsBySection(0)
        }
        return list
    }

    fun getAllStudents(): List<StudentItem> = getStudentsBySection(0)

    fun findStudentByRoll(roll: String): StudentItem? {
        val q = roll.trim()
        val db = readableDatabase
        val cursor = db.rawQuery(
            "SELECT * FROM students WHERE usn = ? OR student_id = ? LIMIT 1",
            arrayOf(q, q)
        )
        cursor.use {
            if (it.moveToFirst()) {
                return StudentItem(
                    studentId = it.getInt(it.getColumnIndexOrThrow("student_id")),
                    usn = it.getString(it.getColumnIndexOrThrow("usn")),
                    name = it.getString(it.getColumnIndexOrThrow("name")),
                    sectionId = it.getInt(it.getColumnIndexOrThrow("section_id"))
                )
            }
        }
        return null
    }

    fun getSessionRoster(sessionId: Int, sectionId: Int): List<RosterStudent> {
        val students = getStudentsBySection(sectionId)
        val attendanceMap = getAttendanceMapForSession(sessionId)

        return students.map { s ->
            val att = attendanceMap[s.studentId]
            if (att != null) {
                RosterStudent(
                    studentId = s.studentId,
                    usn = s.usn,
                    name = s.name,
                    sectionId = s.sectionId,
                    status = att.status,
                    method = att.method,
                    score = att.score
                )
            } else {
                RosterStudent(
                    studentId = s.studentId,
                    usn = s.usn,
                    name = s.name,
                    sectionId = s.sectionId,
                    status = "absent",
                    method = "",
                    score = 0
                )
            }
        }
    }

    // ── Fingerprints ───────────────────────────────────────────────────────────
    fun saveFingerprints(fps: List<FingerprintTemplate>) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            for (fp in fps) {
                val cv = ContentValues().apply {
                    put("template_id", fp.templateId)
                    put("student_id", fp.studentId)
                    put("usn", fp.usn)
                    put("name", fp.name)
                    put("section_id", fp.sectionId)
                }
                db.insertWithOnConflict("fingerprints", null, cv, SQLiteDatabase.CONFLICT_REPLACE)
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun linkFingerprint(templateId: Int, studentId: Int, usn: String, name: String, sectionId: Int = 0) {
        val db = writableDatabase
        val cv = ContentValues().apply {
            put("template_id", templateId)
            put("student_id", studentId)
            put("usn", usn)
            put("name", name)
            put("section_id", sectionId)
        }
        db.insertWithOnConflict("fingerprints", null, cv, SQLiteDatabase.CONFLICT_REPLACE)
    }

    fun deleteFingerprint(templateId: Int) {
        val db = writableDatabase
        db.delete("fingerprints", "template_id = ?", arrayOf(templateId.toString()))
    }

    fun getFingerprints(): List<FingerprintTemplate> {
        val list = mutableListOf<FingerprintTemplate>()
        val db = readableDatabase
        val cursor = db.rawQuery("SELECT * FROM fingerprints ORDER BY template_id ASC", null)
        cursor.use {
            while (it.moveToNext()) {
                list.add(
                    FingerprintTemplate(
                        templateId = it.getInt(it.getColumnIndexOrThrow("template_id")),
                        studentId = it.getInt(it.getColumnIndexOrThrow("student_id")),
                        usn = it.getString(it.getColumnIndexOrThrow("usn")),
                        name = it.getString(it.getColumnIndexOrThrow("name")),
                        sectionId = it.getInt(it.getColumnIndexOrThrow("section_id"))
                    )
                )
            }
        }
        return list
    }

    fun lookupStudentByTemplate(templateId: Int): FingerprintTemplate? {
        val db = readableDatabase
        val cursor = db.rawQuery("SELECT * FROM fingerprints WHERE template_id = ? LIMIT 1", arrayOf(templateId.toString()))
        cursor.use {
            if (it.moveToFirst()) {
                return FingerprintTemplate(
                    templateId = it.getInt(it.getColumnIndexOrThrow("template_id")),
                    studentId = it.getInt(it.getColumnIndexOrThrow("student_id")),
                    usn = it.getString(it.getColumnIndexOrThrow("usn")),
                    name = it.getString(it.getColumnIndexOrThrow("name")),
                    sectionId = it.getInt(it.getColumnIndexOrThrow("section_id"))
                )
            }
        }
        return null
    }

    // ── Attendance Recording & Queue ───────────────────────────────────────────
    fun recordAttendance(
        sessionId: Int,
        studentId: Int,
        usn: String,
        studentName: String,
        status: String,
        method: String,
        score: Int = 100,
        timestamp: Long = System.currentTimeMillis() / 1000,
        synced: Boolean = false
    ): Long {
        val db = writableDatabase
        val cv = ContentValues().apply {
            put("session_id", sessionId)
            put("student_id", studentId)
            put("usn", usn)
            put("student_name", studentName)
            put("score", score)
            put("timestamp", timestamp)
            put("status", status)
            put("method", method)
            put("synced", if (synced) 1 else 0)
        }
        return db.insertWithOnConflict("attendance_queue", null, cv, SQLiteDatabase.CONFLICT_REPLACE)
    }

    fun markSynced(queueId: Long) {
        val db = writableDatabase
        val cv = ContentValues().apply {
            put("synced", 1)
            putNull("sync_error")
        }
        db.update("attendance_queue", cv, "id = ?", arrayOf(queueId.toString()))
    }

    fun markSyncedByRecord(sessionId: Int, studentId: Int) {
        val db = writableDatabase
        val cv = ContentValues().apply {
            put("synced", 1)
            putNull("sync_error")
        }
        db.update("attendance_queue", cv, "session_id = ? AND student_id = ?", arrayOf(sessionId.toString(), studentId.toString()))
    }

    fun getPendingQueue(): List<AttendanceRecord> {
        val list = mutableListOf<AttendanceRecord>()
        val db = readableDatabase
        val cursor = db.rawQuery("SELECT * FROM attendance_queue WHERE synced = 0 ORDER BY timestamp ASC", null)
        cursor.use {
            while (it.moveToNext()) {
                list.add(
                    AttendanceRecord(
                        id = it.getLong(it.getColumnIndexOrThrow("id")),
                        sessionId = it.getInt(it.getColumnIndexOrThrow("session_id")),
                        studentId = it.getInt(it.getColumnIndexOrThrow("student_id")),
                        usn = it.getString(it.getColumnIndexOrThrow("usn")),
                        studentName = it.getString(it.getColumnIndexOrThrow("student_name")),
                        score = it.getInt(it.getColumnIndexOrThrow("score")),
                        timestamp = it.getLong(it.getColumnIndexOrThrow("timestamp")),
                        status = it.getString(it.getColumnIndexOrThrow("status")),
                        method = it.getString(it.getColumnIndexOrThrow("method")),
                        synced = it.getInt(it.getColumnIndexOrThrow("synced")),
                        syncError = it.getString(it.getColumnIndexOrThrow("sync_error"))
                    )
                )
            }
        }
        return list
    }

    fun getPendingCount(): Int {
        val db = readableDatabase
        val cursor = db.rawQuery("SELECT COUNT(*) FROM attendance_queue WHERE synced = 0", null)
        cursor.use {
            if (it.moveToFirst()) return it.getInt(0)
        }
        return 0
    }

    fun getAttendanceForSession(sessionId: Int): List<AttendanceRecord> {
        val list = mutableListOf<AttendanceRecord>()
        val db = readableDatabase
        val cursor = db.rawQuery("SELECT * FROM attendance_queue WHERE session_id = ? ORDER BY timestamp DESC", arrayOf(sessionId.toString()))
        cursor.use {
            while (it.moveToNext()) {
                list.add(
                    AttendanceRecord(
                        id = it.getLong(it.getColumnIndexOrThrow("id")),
                        sessionId = it.getInt(it.getColumnIndexOrThrow("session_id")),
                        studentId = it.getInt(it.getColumnIndexOrThrow("student_id")),
                        usn = it.getString(it.getColumnIndexOrThrow("usn")),
                        studentName = it.getString(it.getColumnIndexOrThrow("student_name")),
                        score = it.getInt(it.getColumnIndexOrThrow("score")),
                        timestamp = it.getLong(it.getColumnIndexOrThrow("timestamp")),
                        status = it.getString(it.getColumnIndexOrThrow("status")),
                        method = it.getString(it.getColumnIndexOrThrow("method")),
                        synced = it.getInt(it.getColumnIndexOrThrow("synced")),
                        syncError = it.getString(it.getColumnIndexOrThrow("sync_error"))
                    )
                )
            }
        }
        return list
    }

    fun getAttendanceMapForSession(sessionId: Int): Map<Int, AttendanceRecord> {
        val map = mutableMapOf<Int, AttendanceRecord>()
        val records = getAttendanceForSession(sessionId)
        for (r in records) {
            map[r.studentId] = r
        }
        return map
    }
}
