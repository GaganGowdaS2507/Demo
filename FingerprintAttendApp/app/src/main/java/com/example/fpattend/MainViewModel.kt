package com.example.fpattend

import android.app.Application
import android.content.Context
import android.media.AudioManager
import android.media.ToneGenerator
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.hoho.android.usbserial.driver.UsbSerialPort
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("fp_attend_prefs", Context.MODE_PRIVATE)
    private val db = AppDatabase.getInstance(app)
    private val tone = ToneGenerator(AudioManager.STREAM_MUSIC, 85)

    // ── Server & Configuration Settings ────────────────────────────────────────
    var serverUrl by mutableStateOf(prefs.getString("url", "http://127.0.0.1:5000") ?: "http://127.0.0.1:5000")
    var token by mutableStateOf(prefs.getString("token", "") ?: "")
    var deviceId by mutableStateOf(prefs.getString("device", "MODULE-01") ?: "MODULE-01")

    // ── Authentication State ───────────────────────────────────────────────────
    var isLoggedIn by mutableStateOf(false)
    var isOfflineMode by mutableStateOf(false)
    var currentUserName by mutableStateOf("")
    var currentUserEmail by mutableStateOf("")
    var facultyId by mutableStateOf(0)
    var loginError by mutableStateOf("")

    // ── USB & Sensor State ─────────────────────────────────────────────────────
    var connected by mutableStateOf(false); private set
    var sensorStatus by mutableStateOf("Plug in fingerprint device into Type-C port")
    var sensorCapacity by mutableIntStateOf(50)
    var enrolledCount by mutableIntStateOf(-1)
    var mode by mutableStateOf("Idle"); private set // "Idle", "Identify", "Enroll", "Delete"

    // ── Sessions & Filter ──────────────────────────────────────────────────────
    var sessionsList = mutableStateListOf<FacultySession>()
    var sessionPeriod by mutableStateOf("today") // "today", "upcoming", "past"
    var activeSession by mutableStateOf<FacultySession?>(null)

    fun getTodayStr(): String = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())

    val todaySessions: List<FacultySession>
        get() = sessionsList.filter { it.sessionDate == getTodayStr() }

    val upcomingSessions: List<FacultySession>
        get() = sessionsList.filter { it.sessionDate > getTodayStr() }

    val pastSessions: List<FacultySession>
        get() = sessionsList.filter { it.sessionDate < getTodayStr() }

    val currentFilteredSessions: List<FacultySession>
        get() = when (sessionPeriod) {
            "today" -> todaySessions
            "upcoming" -> upcomingSessions
            "past" -> pastSessions
            else -> todaySessions
        }

    // ── Active Session Roster & Manual Marking ─────────────────────────────────
    var sessionRoster = mutableStateListOf<RosterStudent>()
    var rosterSearchQuery by mutableStateOf("")

    val filteredRoster: List<RosterStudent>
        get() {
            val q = rosterSearchQuery.trim().lowercase()
            return if (q.isEmpty()) {
                sessionRoster
            } else {
                sessionRoster.filter {
                    it.name.lowercase().contains(q) || it.usn.lowercase().contains(q)
                }
            }
        }

    val presentCount: Int get() = sessionRoster.count { it.status == "present" }
    val absentCount: Int get() = sessionRoster.count { it.status != "present" }

    // ── Live Attendance Result State ───────────────────────────────────────────
    var lastResultText by mutableStateOf("Waiting for finger...")
    var lastMatchedStudentName by mutableStateOf("")
    var lastMatchedUsn by mutableStateOf("")
    var lastMatchScore by mutableIntStateOf(0)
    var isMatchSuccess by mutableStateOf(false)

    // ── Group Photo AI Recognition ────────────────────────────────────────────
    val groupPhotos = mutableStateListOf<ByteArray>()
    var isProcessingGroupPhoto by mutableStateOf(false)
    var groupPhotoStatusMessage by mutableStateOf("")
    val groupPhotoMatches = mutableStateListOf<ServerApi.ClassroomPhotoMatch>()
    var unrecognizedFaceCount by mutableIntStateOf(0)
    var totalFacesDetected by mutableIntStateOf(0)
    var hasRunGroupPhotoRecognition by mutableStateOf(false)

    // ── Enrolled Templates & Students ──────────────────────────────────────────
    var templatesList = mutableStateListOf<FingerprintTemplate>()
    var allStudentsList = mutableStateListOf<StudentItem>()

    // ── Offline Setup & Queue State ────────────────────────────────────────────
    var isSyncingData by mutableStateOf(false)
    var syncMessage by mutableStateOf("")
    var pendingQueueCount by mutableIntStateOf(0)
    var isFlushingQueue by mutableStateOf(false)
    val logs = mutableStateListOf<String>()

    private var port: UsbSerialPort? = null
    private var zw: Zw101? = null
    private var identifyJob: Job? = null
    private var lastScannedTemplateId = -1
    private var lastScannedTime = 0L

    init {
        val cached = db.getLatestAuth()
        if (cached != null) {
            currentUserEmail = cached.email
            currentUserName = cached.name
            facultyId = cached.facultyId
            token = cached.token
            isLoggedIn = true
            isOfflineMode = true
            addLog("Loaded offline profile for ${cached.name}")
        }
        loadLocalData()
    }

    fun addLog(msg: String) {
        val ts = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())
        logs.add(0, "[$ts] $msg")
        if (logs.size > 120) logs.removeAt(logs.lastIndex)
    }

    fun beep(good: Boolean) {
        try {
            tone.startTone(if (good) ToneGenerator.TONE_PROP_ACK else ToneGenerator.TONE_PROP_NACK, 160)
        } catch (_: Exception) {}
    }

    fun saveSettings() {
        prefs.edit()
            .putString("url", serverUrl.trimEnd('/'))
            .putString("token", token)
            .putString("device", deviceId)
            .apply()
        addLog("Settings updated")
    }

    // ── Authentication ─────────────────────────────────────────────────────────
    fun login(emailInput: String, passwordInput: String, onComplete: (Boolean) -> Unit) {
        loginError = ""
        val email = emailInput.trim()
        val pass = passwordInput.trim()
        if (email.isBlank() || pass.isBlank()) {
            loginError = "Please enter email and password"
            onComplete(false)
            return
        }

        viewModelScope.launch {
            addLog("Attempting login for $email...")
            val res = withContext(Dispatchers.IO) {
                ServerApi.login(serverUrl, email, pass)
            }

            if (res.ok && res.data != null) {
                val data = res.data
                val recToken = data.optString("token", "")
                val name = data.optString("name", email)
                val facId = data.optInt("faculty_id", 0)
                val userId = data.optInt("user_id", 0)
                val role = data.optString("role", "faculty")

                token = recToken
                currentUserName = name
                currentUserEmail = email
                facultyId = facId
                isLoggedIn = true
                isOfflineMode = false

                saveSettings()
                db.saveAuth(email, pass, recToken, name, facId, userId, role)
                addLog("Online login successful! Welcome $name")

                syncAllData()
                onComplete(true)
            } else if (res.retry) {
                addLog("Server unreachable. Checking offline credentials...")
                val cached = db.verifyOfflineAuth(email, pass)
                if (cached != null) {
                    token = cached.token
                    currentUserName = cached.name
                    currentUserEmail = email
                    facultyId = cached.facultyId
                    isLoggedIn = true
                    isOfflineMode = true
                    addLog("Logged in using offline cached credentials!")
                    loadLocalData()
                    onComplete(true)
                } else {
                    loginError = "Server unreachable and no cached login found. Please connect to network for first login."
                    addLog(loginError)
                    onComplete(false)
                }
            } else {
                loginError = res.message
                addLog("Login failed: ${res.message}")
                onComplete(false)
            }
        }
    }

    fun logout() {
        isLoggedIn = false
        stopIdentify()
        activeSession = null
        addLog("Logged out")
    }

    // ── Offline Setup & Data Sync ──────────────────────────────────────────────
    fun syncAllData() {
        if (isSyncingData) return
        isSyncingData = true
        syncMessage = "Syncing timetable, rosters, and fingerprints..."
        viewModelScope.launch {
            try {
                // 1. Fetch sessions
                addLog("Syncing faculty sessions...")
                val sessRes = withContext(Dispatchers.IO) {
                    ServerApi.fetchSync(serverUrl, token)
                }
                if (sessRes.ok && sessRes.data != null) {
                    db.saveSessions(sessRes.data)
                    addLog("Saved ${sessRes.data.size} sessions")

                    // 2. Fetch rosters for each session
                    for (s in sessRes.data) {
                        val rosterRes = withContext(Dispatchers.IO) {
                            ServerApi.fetchSessionRoster(serverUrl, token, s.sessionId, s.sectionId)
                        }
                        if (rosterRes.ok && rosterRes.data != null) {
                            db.saveStudents(rosterRes.data)
                            db.syncServerRosterAttendance(s.sessionId, rosterRes.data)
                        }
                    }
                }

                // 3. Fetch fingerprint mappings
                addLog("Syncing fingerprint templates...")
                val fpRes = withContext(Dispatchers.IO) {
                    ServerApi.fetchFingerprints(serverUrl, token)
                }
                if (fpRes.ok && fpRes.data != null) {
                    db.saveFingerprints(fpRes.data)
                    addLog("Saved ${fpRes.data.size} templates")
                }

                loadLocalData()
                syncMessage = "Sync completed! All data available offline."
                addLog("Offline data sync successfully completed")
            } catch (e: Exception) {
                syncMessage = "Sync error: ${e.message}"
                addLog("Sync error: ${e.message}")
            } finally {
                isSyncingData = false
            }
        }
    }

    fun loadLocalData() {
        sessionsList.clear()
        sessionsList.addAll(db.getAllSessions())

        allStudentsList.clear()
        allStudentsList.addAll(db.getAllStudents())

        templatesList.clear()
        templatesList.addAll(db.getFingerprints())

        pendingQueueCount = db.getPendingCount()

        // If active session is selected, refresh its roster
        val current = activeSession
        if (current != null) {
            loadRosterForSession(current)
        } else if (todaySessions.isNotEmpty()) {
            openSession(todaySessions.first())
        }
    }

    fun openSession(session: FacultySession) {
        activeSession = session
        loadRosterForSession(session)
        addLog("Opened class: ${session.subjectName} (${session.sectionLabel}) [${session.startTime}]")
    }

    fun loadRosterForSession(session: FacultySession) {
        sessionRoster.clear()
        val roster = db.getSessionRoster(session.sessionId, session.sectionId)
        sessionRoster.addAll(roster)

        // Always fetch / update from server when online to get latest roster & server attendance
        if (!isOfflineMode && token.isNotBlank()) {
            viewModelScope.launch {
                val res = withContext(Dispatchers.IO) {
                    ServerApi.fetchSessionRoster(serverUrl, token, session.sessionId, session.sectionId)
                }
                if (res.ok && res.data != null) {
                    db.saveStudents(res.data)
                    db.syncServerRosterAttendance(session.sessionId, res.data)
                    val refreshed = db.getSessionRoster(session.sessionId, session.sectionId)
                    sessionRoster.clear()
                    sessionRoster.addAll(refreshed)
                }
            }
        }
    }

    // ── Manual & Bulk Attendance Marking ───────────────────────────────────────
    fun toggleStudentAttendance(student: RosterStudent) {
        val session = activeSession ?: return
        val newStatus = if (student.status == "present") "absent" else "present"
        val nowSec = System.currentTimeMillis() / 1000

        db.recordAttendance(
            sessionId = session.sessionId,
            studentId = student.studentId,
            usn = student.usn,
            studentName = student.name,
            status = newStatus,
            method = "manual_individual",
            score = 100,
            timestamp = nowSec,
            synced = false
        )

        // Update in-memory list
        val idx = sessionRoster.indexOfFirst { it.studentId == student.studentId }
        if (idx != -1) {
            sessionRoster[idx] = student.copy(status = newStatus, method = "manual")
        }

        pendingQueueCount = db.getPendingCount()
        addLog("Toggled ${student.name} to $newStatus")
    }

    fun bulkMarkAll(targetStatus: String) {
        val session = activeSession ?: return
        val nowSec = System.currentTimeMillis() / 1000

        for (s in sessionRoster) {
            if (s.status != targetStatus) {
                db.recordAttendance(
                    sessionId = session.sessionId,
                    studentId = s.studentId,
                    usn = s.usn,
                    studentName = s.name,
                    status = targetStatus,
                    method = "manual_bulk",
                    score = 100,
                    timestamp = nowSec,
                    synced = false
                )
            }
        }

        loadRosterForSession(session)
        pendingQueueCount = db.getPendingCount()
        beep(targetStatus == "present")
        addLog("Bulk marked all students as ${targetStatus.uppercase()}")
    }

    // ── Group Photo AI Recognition ────────────────────────────────────────────
    fun addGroupPhoto(bytes: ByteArray) {
        if (groupPhotos.size >= 3) {
            addLog("Maximum 3 classroom photos allowed")
            return
        }
        groupPhotos.add(bytes)
        hasRunGroupPhotoRecognition = false
    }

    fun removeGroupPhoto(index: Int) {
        if (index in 0 until groupPhotos.size) {
            groupPhotos.removeAt(index)
            hasRunGroupPhotoRecognition = false
        }
    }

    fun processGroupPhotos() {
        val session = activeSession ?: return
        if (groupPhotos.isEmpty()) return

        isProcessingGroupPhoto = true
        groupPhotoStatusMessage = "Uploading classroom photos to AI engine..."
        addLog("Processing ${groupPhotos.size} classroom photos with backend face recognition...")

        viewModelScope.launch {
            val res = withContext(Dispatchers.IO) {
                ServerApi.uploadClassroomPhotos(serverUrl, token, session.sessionId, groupPhotos.toList())
            }

            if (res.ok && res.data != null) {
                val result = res.data
                groupPhotoMatches.clear()
                groupPhotoMatches.addAll(result.matched)
                unrecognizedFaceCount = result.unrecognizedCount
                totalFacesDetected = result.totalFacesDetected
                hasRunGroupPhotoRecognition = true
                groupPhotoStatusMessage = "Detected ${result.matched.size} students (${result.unrecognizedCount} unrecognized faces)"
                addLog("AI recognized ${result.matched.size} students in group photo")
                beep(true)
            } else {
                groupPhotoStatusMessage = "Recognition error: ${res.message}"
                addLog("Group photo error: ${res.message}")
                beep(false)
            }
            isProcessingGroupPhoto = false
        }
    }

    fun confirmGroupPhotoAttendance() {
        val session = activeSession ?: return
        val nowSec = System.currentTimeMillis() / 1000
        var count = 0

        for (m in groupPhotoMatches) {
            if (m.selected) {
                db.recordAttendance(
                    sessionId = session.sessionId,
                    studentId = m.studentId,
                    usn = m.usn,
                    studentName = m.name,
                    status = "present",
                    method = "classroom_photo",
                    score = (m.score * 100).toInt(),
                    timestamp = nowSec,
                    synced = false
                )
                count++
            }
        }

        loadRosterForSession(session)
        pendingQueueCount = db.getPendingCount()
        beep(true)
        addLog("Confirmed attendance for $count students from group photo")
    }

    // ── USB Sensor Management ──────────────────────────────────────────────────
    fun attach(p: UsbSerialPort) {
        if (connected) return
        port = p
        val z = Zw101(p)
        zw = z
        viewModelScope.launch {
            sensorStatus = "Verifying fingerprint sensor..."
            val ok = z.session { verify() }
            if (!ok) {
                sensorStatus = "Sensor not answering. Check wire connections."
                addLog("Sensor handshake failed")
                closePort()
                return@launch
            }
            z.session { readParams() }
            sensorCapacity = z.capacity
            val cnt = z.session { templateCount() }
            enrolledCount = cnt
            connected = true
            sensorStatus = "Sensor Connected (Capacity: ${z.capacity}, Enrolled: $cnt)"
            addLog("Fingerprint sensor connected and ready!")
            startIdentify()
        }
    }

    private fun closePort() {
        try { port?.close() } catch (_: Exception) {}
        port = null
        zw = null
        connected = false
    }

    fun disconnect(reason: String) {
        stopIdentify()
        closePort()
        sensorStatus = reason
        addLog("Sensor disconnected: $reason")
    }

    fun refreshSensorCount() {
        val z = zw ?: return
        viewModelScope.launch {
            val cnt = z.session { templateCount() }
            enrolledCount = cnt
            sensorStatus = "Capacity: ${z.capacity}, Enrolled: $cnt"
            addLog("Sensor template count: $cnt")
        }
    }

    // ── Attendance Marking via Fingerprint (Identify) ──────────────────────────
    fun stopIdentify() {
        identifyJob?.cancel()
        identifyJob = null
        mode = "Idle"
        if (connected) sensorStatus = "Sensor Idle"
    }

    fun startIdentify() {
        val z = zw ?: run {
            sensorStatus = "Sensor not connected"
            return
        }
        identifyJob?.cancel()
        mode = "Identify"
        sensorStatus = "Sensor Active: Place finger to mark attendance"
        addLog("Started fingerprint listener for attendance")

        identifyJob = viewModelScope.launch {
            var armed = true
            var absent = 0
            while (isActive) {
                val g = z.session { getImage() }
                when (g) {
                    NO_FINGER -> {
                        absent++
                        if (absent >= 2 && !armed) {
                            armed = true
                            sensorStatus = "Place finger on the sensor"
                        }
                    }
                    OK -> {
                        absent = 0
                        if (armed) {
                            armed = false
                            sensorStatus = "Scanning fingerprint..."
                            handleFingerScan(z)
                        }
                    }
                    NO_REPLY -> {}
                    else -> {}
                }
                delay(120)
            }
        }
    }

    private suspend fun handleFingerScan(z: Zw101) {
        val t = z.session { img2Tz(1) }
        if (t != OK) {
            sensorStatus = "Bad scan (${codeName(t)}). Place finger firmly."
            return
        }
        val found = z.session { search(1) }
        when (found.code) {
            OK -> onTemplateMatched(found.id, found.score)
            NOT_FOUND -> {
                sensorStatus = "Fingerprint not recognized!"
                lastResultText = "Not Recognized"
                isMatchSuccess = false
                addLog("Scan result: No template match found")
                beep(false)
            }
            else -> {
                sensorStatus = "Search error: ${codeName(found.code)}"
            }
        }
    }

    private suspend fun onTemplateMatched(templateId: Int, score: Int) {
        val now = System.currentTimeMillis()
        if (templateId == lastScannedTemplateId && (now - lastScannedTime) < 3000) {
            sensorStatus = "Already scanned. Next student."
            return
        }
        lastScannedTemplateId = templateId
        lastScannedTime = now

        // 1. Look up student in local DB
        val studentFp = db.lookupStudentByTemplate(templateId)
        val studentName = studentFp?.name ?: "Template #$templateId"
        val usn = studentFp?.usn ?: "ID-$templateId"
        val studentId = studentFp?.studentId ?: templateId

        lastMatchedStudentName = studentName
        lastMatchedUsn = usn
        lastMatchScore = score
        isMatchSuccess = true
        lastResultText = "$studentName ($usn)"
        sensorStatus = "Match! $studentName (Score: $score)"
        beep(true)
        addLog("Fingerprint Match: Template #$templateId -> $studentName ($usn) Score: $score")

        val session = activeSession
        val sessionId = session?.sessionId ?: 0
        val timestampSec = now / 1000

        // 2. Record attendance in local database
        db.recordAttendance(
            sessionId = sessionId,
            studentId = studentId,
            usn = usn,
            studentName = studentName,
            status = "present",
            method = "fingerprint",
            score = score,
            timestamp = timestampSec,
            synced = false
        )

        // 3. Update session roster in-memory instantly
        val idx = sessionRoster.indexOfFirst { it.studentId == studentId }
        if (idx != -1) {
            sessionRoster[idx] = sessionRoster[idx].copy(status = "present", method = "fingerprint", score = score)
        }

        pendingQueueCount = db.getPendingCount()

        // 4. Push to server immediately if online
        val res = withContext(Dispatchers.IO) {
            ServerApi.postScan(serverUrl, token, deviceId, sessionId, templateId, score, timestampSec)
        }

        if (res.ok) {
            db.markSyncedByRecord(sessionId, studentId)
            pendingQueueCount = db.getPendingCount()
            addLog("Attendance synced to server for $studentName")
        } else {
            addLog("Saved offline in queue (${pendingQueueCount} pending): ${res.message}")
        }
    }

    // ── Fingerprint Enrollment ─────────────────────────────────────────────────
    fun enrollFingerprint(idText: String, rollText: String, onProgress: (String) -> Unit) {
        val z = zw ?: run {
            sensorStatus = "Sensor not connected"
            onProgress("Sensor not connected")
            return
        }
        val id = idText.trim().toIntOrNull() ?: run {
            onProgress("Please enter numeric Template ID")
            return
        }
        val roll = rollText.trim()
        if (roll.isBlank()) {
            onProgress("Please enter student roll number or USN")
            return
        }

        stopIdentify()
        mode = "Enroll"
        viewModelScope.launch {
            addLog("Starting 2-scan enrollment for Template #$id (Roll: $roll)...")
            val err = z.session {
                enroll(id) { msg ->
                    sensorStatus = msg
                    onProgress(msg)
                }
            }

            if (err != null) {
                sensorStatus = "Enrollment failed: $err"
                onProgress("Enrollment failed: $err")
                addLog("Enroll failed: $err")
                beep(false)
            } else {
                sensorStatus = "Template #$id enrolled into sensor!"
                onProgress("Finger stored in sensor! Linking to server...")
                beep(true)
                addLog("Successfully saved template #$id in module flash")

                val localStudent = db.findStudentByRoll(roll)
                val sId = localStudent?.studentId ?: id
                val sName = localStudent?.name ?: roll
                db.linkFingerprint(id, sId, roll, sName)

                val linkRes = withContext(Dispatchers.IO) {
                    ServerApi.postEnroll(serverUrl, token, deviceId, id, roll)
                }
                if (linkRes.ok) {
                    onProgress("Linked Template #$id to ${linkRes.message}")
                    addLog("Server linked Template #$id to $roll")
                } else {
                    onProgress("Saved locally. Server link: ${linkRes.message}")
                    addLog("Server link warning: ${linkRes.message}")
                }

                refreshSensorCount()
                loadLocalData()
            }
            startIdentify()
        }
    }

    // ── Fingerprint Deletion ───────────────────────────────────────────────────
    fun deleteFingerprint(idText: String, onResult: (String) -> Unit) {
        val z = zw ?: run {
            onResult("Sensor not connected")
            return
        }
        val id = idText.trim().toIntOrNull() ?: run {
            onResult("Enter a numeric ID")
            return
        }

        stopIdentify()
        mode = "Delete"
        viewModelScope.launch {
            addLog("Deleting Template #$id from sensor...")
            val c = z.session { delete(id) }
            if (c == OK) {
                sensorStatus = "Deleted Template #$id"
                db.deleteFingerprint(id)
                addLog("Deleted Template #$id from sensor and database")

                ServerApi.postDelete(serverUrl, token, deviceId, id)
                onResult("Template #$id deleted successfully")
                refreshSensorCount()
                loadLocalData()
            } else {
                val errMsg = "Delete failed: ${codeName(c)}"
                sensorStatus = errMsg
                onResult(errMsg)
                addLog(errMsg)
            }
            startIdentify()
        }
    }

    // ── Queue Management ───────────────────────────────────────────────────────
    fun flushQueue(onResult: ((Boolean, String) -> Unit)? = null) {
        if (isFlushingQueue) return
        isFlushingQueue = true
        viewModelScope.launch {
            val pending = withContext(Dispatchers.IO) { db.getPendingQueue() }
            if (pending.isEmpty()) {
                val msg = "Queue is empty. No pending records to sync."
                addLog(msg)
                isFlushingQueue = false
                onResult?.invoke(true, msg)
                return@launch
            }

            addLog("Checking server availability at $serverUrl...")
            val health = withContext(Dispatchers.IO) { ServerApi.checkServerHealth(serverUrl) }
            if (!health.ok) {
                val msg = "Server is unreachable (${health.message}). Please check server URL / Wi-Fi network."
                addLog("Sync canceled: $msg")
                beep(false)
                isFlushingQueue = false
                onResult?.invoke(false, msg)
                return@launch
            }

            addLog("Uploading ${pending.size} pending records to server...")
            val res = withContext(Dispatchers.IO) {
                ServerApi.syncAttendanceQueue(serverUrl, token, pending)
            }

            if (res.ok) {
                val json = res.data
                val inserted = json?.optInt("inserted") ?: 0
                val errorsArr = json?.optJSONArray("errors")

                if (inserted > 0 || errorsArr == null || errorsArr.length() == 0) {
                    for (r in pending) {
                        db.markSynced(r.id)
                    }
                    pendingQueueCount = db.getPendingCount()
                    activeSession?.let { loadRosterForSession(it) }
                    val msg = "Successfully synced ${pending.size} record(s) to server!"
                    addLog(msg)
                    beep(true)
                    isFlushingQueue = false
                    onResult?.invoke(true, msg)
                } else {
                    val errDetail = errorsArr.optString(0, "Rejected by server")
                    val msg = "Sync rejected by server: $errDetail"
                    addLog(msg)
                    beep(false)
                    isFlushingQueue = false
                    onResult?.invoke(false, msg)
                }
            } else {
                val msg = "Queue sync failed: ${res.message}"
                addLog(msg)
                beep(false)
                isFlushingQueue = false
                onResult?.invoke(false, msg)
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        disconnect("App closed")
        try { tone.release() } catch (_: Exception) {}
    }
}
