package com.example.fpattend

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

object ServerApi {
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
    private val JPEG_MEDIA_TYPE = "image/jpeg".toMediaType()

    data class ApiResult<T>(
        val ok: Boolean,
        val data: T? = null,
        val message: String = "",
        val retry: Boolean = false
    )

    data class ClassroomPhotoMatch(
        val studentId: Int,
        val usn: String,
        val name: String,
        val score: Float,
        var selected: Boolean = true
    )

    data class ClassroomPhotoResult(
        val success: Boolean,
        val matched: List<ClassroomPhotoMatch>,
        val unrecognizedCount: Int,
        val totalFacesDetected: Int,
        val photosProcessed: Int
    )

    // ── Server Health Check ──────────────────────────────────────────────────
    fun checkServerHealth(baseUrl: String): ApiResult<Boolean> {
        return try {
            val url = baseUrl.trimEnd('/') + "/api/mobile/sync"
            val request = Request.Builder().url(url).get().build()
            val response = client.newCall(request).execute()
            if (response.code in 200..499) {
                ApiResult(true, true, "Server online")
            } else {
                ApiResult(false, false, "HTTP ${response.code}", false)
            }
        } catch (e: Exception) {
            ApiResult(false, false, "Unreachable: ${e.message}", true)
        }
    }

    // ── Login ──────────────────────────────────────────────────────────────────
    fun login(baseUrl: String, email: String, pass: String): ApiResult<JSONObject> {
        return try {
            val url = baseUrl.trimEnd('/') + "/api/mobile/login"
            val bodyJson = JSONObject().put("email", email).put("password", pass)
            val request = Request.Builder()
                .url(url)
                .post(bodyJson.toString().toRequestBody(JSON_MEDIA_TYPE))
                .build()

            val response = client.newCall(request).execute()
            val text = response.body?.string().orEmpty()
            val code = response.code
            if (response.isSuccessful) {
                val json = JSONObject(text)
                if (json.optBoolean("success", false)) {
                    ApiResult(true, json, "Login successful")
                } else {
                    ApiResult(false, null, json.optString("message", "Login rejected"), false)
                }
            } else {
                ApiResult(false, null, "HTTP $code: $text", code >= 500)
            }
        } catch (e: Exception) {
            ApiResult(false, null, "Network error: ${e.message}", true)
        }
    }

    // ── Fetch Faculty Context & Sessions ───────────────────────────────────────
    fun fetchSync(baseUrl: String, token: String): ApiResult<List<FacultySession>> {
        return try {
            val url = baseUrl.trimEnd('/') + "/api/mobile/sync"
            val reqBuilder = Request.Builder().url(url).get()
            if (token.isNotBlank()) reqBuilder.addHeader("Authorization", "Bearer $token")

            val response = client.newCall(reqBuilder.build()).execute()
            val text = response.body?.string().orEmpty()
            if (response.isSuccessful) {
                val json = JSONObject(text)
                val arr = json.optJSONArray("sessions") ?: JSONArray()
                val list = mutableListOf<FacultySession>()
                for (i in 0 until arr.length()) {
                    val o = arr.getJSONObject(i)
                    list.add(
                        FacultySession(
                            sessionId = o.optInt("session_id"),
                            sessionDate = o.optString("session_date"),
                            startTime = o.optString("start_time"),
                            endTime = o.optString("end_time"),
                            sectionId = o.optInt("section_id"),
                            sectionLabel = o.optString("section_label"),
                            subjectName = o.optString("subject_name"),
                            status = o.optString("status")
                        )
                    )
                }
                ApiResult(true, list, "Fetched ${list.size} sessions")
            } else {
                ApiResult(false, null, "HTTP ${response.code}: $text", response.code >= 500)
            }
        } catch (e: Exception) {
            ApiResult(false, null, "Sync error: ${e.message}", true)
        }
    }

    // ── Fetch Session Roster (Students) ────────────────────────────────────────
    fun fetchSessionRoster(baseUrl: String, token: String, sessionId: Int, defaultSectionId: Int = 0): ApiResult<List<StudentItem>> {
        return try {
            val url = baseUrl.trimEnd('/') + "/api/mobile/session/$sessionId/roster"
            val reqBuilder = Request.Builder().url(url).get()
            if (token.isNotBlank()) reqBuilder.addHeader("Authorization", "Bearer $token")

            val response = client.newCall(reqBuilder.build()).execute()
            val text = response.body?.string().orEmpty()
            if (response.isSuccessful) {
                val json = JSONObject(text)
                val arr = json.optJSONArray("roster") ?: JSONArray()
                val list = mutableListOf<StudentItem>()
                for (i in 0 until arr.length()) {
                    val o = arr.getJSONObject(i)
                    val sId = if (o.has("section_id") && o.optInt("section_id") > 0) o.optInt("section_id") else defaultSectionId
                    list.add(
                        StudentItem(
                            studentId = o.optInt("student_id"),
                            usn = o.optString("usn"),
                            name = o.optString("name"),
                            sectionId = sId,
                            status = o.optString("status", "absent"),
                            method = if (o.isNull("method")) null else o.optString("method")
                        )
                    )
                }
                ApiResult(true, list, "Fetched ${list.size} students")
            } else {
                ApiResult(false, null, "HTTP ${response.code}: $text", response.code >= 500)
            }
        } catch (e: Exception) {
            ApiResult(false, null, "Roster error: ${e.message}", true)
        }
    }

    // ── Fetch Fingerprints Mappings ───────────────────────────────────────────
    fun fetchFingerprints(baseUrl: String, token: String): ApiResult<List<FingerprintTemplate>> {
        return try {
            val url = baseUrl.trimEnd('/') + "/api/fingerprint/list"
            val reqBuilder = Request.Builder().url(url).get()
            if (token.isNotBlank()) reqBuilder.addHeader("Authorization", "Bearer $token")

            val response = client.newCall(reqBuilder.build()).execute()
            val text = response.body?.string().orEmpty()
            if (response.isSuccessful) {
                val json = JSONObject(text)
                val arr = json.optJSONArray("fingerprints") ?: JSONArray()
                val list = mutableListOf<FingerprintTemplate>()
                for (i in 0 until arr.length()) {
                    val o = arr.getJSONObject(i)
                    list.add(
                        FingerprintTemplate(
                            templateId = o.optInt("template_id"),
                            studentId = o.optInt("student_id"),
                            usn = o.optString("usn"),
                            name = o.optString("student_name", o.optString("name")),
                            sectionId = o.optInt("section_id", 0)
                        )
                    )
                }
                ApiResult(true, list, "Fetched ${list.size} templates")
            } else {
                ApiResult(false, null, "HTTP ${response.code}: $text", response.code >= 500)
            }
        } catch (e: Exception) {
            ApiResult(false, null, "Fingerprints error: ${e.message}", true)
        }
    }

    // ── Post Scan (Mark Attendance via Fingerprint) ────────────────────────────
    fun postScan(
        baseUrl: String,
        token: String,
        deviceId: String,
        sessionId: Int,
        templateId: Int,
        score: Int,
        timestamp: Long
    ): ApiResult<JSONObject> {
        return try {
            val url = baseUrl.trimEnd('/') + "/api/fingerprint/scan"
            val body = JSONObject()
                .put("device_id", deviceId)
                .put("session_id", sessionId)
                .put("template_id", templateId)
                .put("score", score)
                .put("timestamp", timestamp)

            val reqBuilder = Request.Builder()
                .url(url)
                .post(body.toString().toRequestBody(JSON_MEDIA_TYPE))
            if (token.isNotBlank()) reqBuilder.addHeader("Authorization", "Bearer $token")

            val response = client.newCall(reqBuilder.build()).execute()
            val text = response.body?.string().orEmpty()
            val code = response.code
            if (response.isSuccessful) {
                val json = JSONObject(text)
                ApiResult(true, json, json.optString("student_name", "Verified"))
            } else {
                val errMsg = try { JSONObject(text).optString("error", text) } catch (_: Exception) { text }
                ApiResult(false, null, "Server: $errMsg", code >= 500)
            }
        } catch (e: Exception) {
            ApiResult(false, null, "Network error: ${e.message}", true)
        }
    }

    // ── Post Enroll ────────────────────────────────────────────────────────────
    fun postEnroll(
        baseUrl: String,
        token: String,
        deviceId: String,
        templateId: Int,
        roll: String
    ): ApiResult<JSONObject> {
        return try {
            val url = baseUrl.trimEnd('/') + "/api/fingerprint/enroll"
            val body = JSONObject()
                .put("device_id", deviceId)
                .put("template_id", templateId)
                .put("roll", roll.trim())

            val reqBuilder = Request.Builder()
                .url(url)
                .post(body.toString().toRequestBody(JSON_MEDIA_TYPE))
            if (token.isNotBlank()) reqBuilder.addHeader("Authorization", "Bearer $token")

            val response = client.newCall(reqBuilder.build()).execute()
            val text = response.body?.string().orEmpty()
            if (response.isSuccessful) {
                val json = JSONObject(text)
                ApiResult(true, json, json.optString("message", "Enrolled successfully"))
            } else {
                val errMsg = try { JSONObject(text).optString("error", text) } catch (_: Exception) { text }
                ApiResult(false, null, errMsg, response.code >= 500)
            }
        } catch (e: Exception) {
            ApiResult(false, null, "Network error: ${e.message}", true)
        }
    }

    // ── Post Delete ────────────────────────────────────────────────────────────
    fun postDelete(
        baseUrl: String,
        token: String,
        deviceId: String,
        templateId: Int
    ): ApiResult<JSONObject> {
        return try {
            val url = baseUrl.trimEnd('/') + "/api/fingerprint/delete"
            val body = JSONObject()
                .put("device_id", deviceId)
                .put("template_id", templateId)

            val reqBuilder = Request.Builder()
                .url(url)
                .post(body.toString().toRequestBody(JSON_MEDIA_TYPE))
            if (token.isNotBlank()) reqBuilder.addHeader("Authorization", "Bearer $token")

            val response = client.newCall(reqBuilder.build()).execute()
            val text = response.body?.string().orEmpty()
            if (response.isSuccessful) {
                val json = JSONObject(text)
                ApiResult(true, json, json.optString("message", "Deleted"))
            } else {
                val errMsg = try { JSONObject(text).optString("error", text) } catch (_: Exception) { text }
                ApiResult(false, null, errMsg, response.code >= 500)
            }
        } catch (e: Exception) {
            ApiResult(false, null, "Network error: ${e.message}", true)
        }
    }

    // ── Sync Attendance Queue Batch ────────────────────────────────────────────
    fun syncAttendanceQueue(
        baseUrl: String,
        token: String,
        records: List<AttendanceRecord>
    ): ApiResult<JSONObject> {
        return try {
            val url = baseUrl.trimEnd('/') + "/api/mobile/attendance/sync"
            val recArray = JSONArray()
            for (r in records) {
                recArray.put(
                    JSONObject()
                        .put("session_id", r.sessionId)
                        .put("student_id", r.studentId)
                        .put("usn", r.usn)
                        .put("captured_at", r.timestamp)
                        .put("status", r.status)
                        .put("method", r.method)
                        .put("fingerprint_score", r.score)
                )
            }

            val body = JSONObject().put("records", recArray)
            val reqBuilder = Request.Builder()
                .url(url)
                .post(body.toString().toRequestBody(JSON_MEDIA_TYPE))
            if (token.isNotBlank()) reqBuilder.addHeader("Authorization", "Bearer $token")

            val response = client.newCall(reqBuilder.build()).execute()
            val text = response.body?.string().orEmpty()
            if (response.isSuccessful) {
                val json = JSONObject(text)
                ApiResult(true, json, "Synced ${json.optInt("inserted")} records")
            } else {
                ApiResult(false, null, "HTTP ${response.code}: $text", response.code >= 500)
            }
        } catch (e: Exception) {
            ApiResult(false, null, "Sync queue network error: ${e.message}", true)
        }
    }

    // ── Upload Classroom Photos for AI Recognition ─────────────────────────────
    fun uploadClassroomPhotos(
        baseUrl: String,
        token: String,
        sessionId: Int,
        photoBytesList: List<ByteArray>
    ): ApiResult<ClassroomPhotoResult> {
        return try {
            val url = baseUrl.trimEnd('/') + "/api/mobile/sessions/$sessionId/classroom_photos"
            val multipartBuilder = MultipartBody.Builder().setType(MultipartBody.FORM)

            for ((idx, bytes) in photoBytesList.withIndex()) {
                val reqBody = bytes.toRequestBody(JPEG_MEDIA_TYPE)
                multipartBuilder.addFormDataPart("photos", "classroom_photo_${idx + 1}.jpg", reqBody)
            }

            val reqBuilder = Request.Builder()
                .url(url)
                .post(multipartBuilder.build())
            if (token.isNotBlank()) reqBuilder.addHeader("Authorization", "Bearer $token")

            val response = client.newCall(reqBuilder.build()).execute()
            val text = response.body?.string().orEmpty()
            if (response.isSuccessful) {
                val json = JSONObject(text)
                val arr = json.optJSONArray("matched") ?: JSONArray()
                val matchedList = mutableListOf<ClassroomPhotoMatch>()
                for (i in 0 until arr.length()) {
                    val m = arr.getJSONObject(i)
                    matchedList.add(
                        ClassroomPhotoMatch(
                            studentId = m.optInt("student_id"),
                            usn = m.optString("usn"),
                            name = m.optString("full_name"),
                            score = m.optDouble("score", 0.0).toFloat(),
                            selected = true
                        )
                    )
                }
                val result = ClassroomPhotoResult(
                    success = json.optBoolean("success", true),
                    matched = matchedList,
                    unrecognizedCount = json.optInt("unrecognized_count", 0),
                    totalFacesDetected = json.optInt("total_faces_detected", 0),
                    photosProcessed = json.optInt("photos_processed", 0)
                )
                ApiResult(true, result, "Recognized ${matchedList.size} students")
            } else {
                ApiResult(false, null, "HTTP ${response.code}: $text", response.code >= 500)
            }
        } catch (e: Exception) {
            ApiResult(false, null, "Group photo error: ${e.message}", true)
        }
    }
}
