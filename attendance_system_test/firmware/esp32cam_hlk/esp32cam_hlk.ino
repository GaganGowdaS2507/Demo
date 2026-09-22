/*
  ESP32-CAM (AI-Thinker) + HLK-ZW101 Fingerprint + OLED (SSD1306) + Touch
  -- rewritten to match attendance_system_test backend contract --

  This device is a *dumb sensor* from the backend's point of view:
    - Face recognition still happens centrally (server pulls MJPEG from
      /stream on port 81, exactly as before -- untouched).
    - Fingerprint templates stay on-device (HLK-ZW101 storage). The device
      never sends a template, only the matched template_id (1-127).
    - recognition/stream_manager.py's _fingerprint_loop() polls
      GET /last-scan every 0.5s and expects JSON with a "seq" counter so it
      can tell a NEW match from one it already processed.
    - api/admin/fingerprints.py calls GET /enroll?id=<template_id> and
      GET /delete?id=<template_id> (blocking, plain-text response) when an
      admin uses the Fingerprint Management dashboard (/admin/fingerprints/).
    - api/faculty/session_view.py calls GET /set-attendance-mode?mode=...
      when a faculty member starts a session, so the device knows whether to
      even bother running the fingerprint loop.

  This firmware implements exactly that surface: /status, /last-scan, /scan,
  /set-attendance-mode, /set-mode, /enroll, /delete on port 80, and /stream
  on port 81 (two separate httpd instances -- required, or a stuck MJPEG
  client permanently blocks the worker task that would otherwise serve
  /last-scan, and your fingerprint poller silently stops getting new data).

  Pin wiring is UNCHANGED from what's physically wired on your board right
  now: OLED SDA=14/SCL=13, fingerprint RX=15/TX=2, touch=12, flash LED=4.
  No rewiring needed.

  BUILD FIX APPLIED: httpd_resp_send()'s 3rd argument is a byte LENGTH
  (ssize_t), not the HTTP status line. HTTPD_200 expands to the string
  "200 OK", which doesn't convert to ssize_t -- that's what threw
  "invalid conversion from 'const char*' to 'ssize_t'" at compile time.
  Every plain-text response below now correctly passes
  HTTPD_RESP_USE_STRLEN, which tells the server to measure the string
  itself. JSON responses were already correct (they pass json.length()).
*/

#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Adafruit_Fingerprint.h>
#include <Preferences.h>

// ===== AI-THINKER CAMERA PIN MAP =====
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// ===== WiFi AP =====
// Device is its own hotspot, same as before. The Flask server (or whichever
// machine reaches it) must be able to route to 192.168.4.1 -- either by
// joining this hotspot directly, or by this AP's uplink being bridged onto
// your LAN. That network-topology question is separate from this firmware.
const char* AP_SSID = "ESP32-Attendance-AP";
const char* AP_PASS = "12345678";

// ===== OLED =====
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_SDA 14
#define OLED_SCL 13
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

// ===== Fingerprint (UART2) =====
#define FINGER_RX 15   // ESP32 RX <- sensor TX
#define FINGER_TX 2    // ESP32 TX -> sensor RX
HardwareSerial fingerSerial(2);
Adafruit_Fingerprint finger(&fingerSerial);
SemaphoreHandle_t fingerMutex;
#define FINGER_LOCK()   xSemaphoreTake(fingerMutex, portMAX_DELAY)
#define FINGER_UNLOCK() xSemaphoreGive(fingerMutex)

// ===== Touch =====
#define TOUCH_PIN 12
bool lastTouchState = LOW;

// ===== Flash LED (kept off, exactly like before) =====
#define FLASH_LED_PIN 4
#define FLASH_LED_FREQ 5000
#define FLASH_LED_RES_BITS 8
#define FLASH_LED_LEVEL 0

// ===== Local name cache (cosmetic only -- OLED display, NOT the source of
// truth. The backend resolves the real student identity from your
// `fingerprints` table via (camera_id, template_id), so this can be blank
// and attendance marking still works correctly.) =====
Preferences prefs;

// ===== Modes matching what session_view.py / fingerprints.py send =====
enum SensorMode { FINGER_MODE_SCAN, FINGER_MODE_ENROLL };
enum AttendanceMode { MODE_FACE_ONLY, MODE_FINGERPRINT_ONLY, MODE_DUAL_MODE };
SensorMode currentSensorMode = FINGER_MODE_SCAN;
AttendanceMode currentAttendanceMode = MODE_FACE_ONLY;

bool fingerReady = false;
uint32_t scanSeq = 0;              // incremented on EVERY scan attempt (match or not)
uint16_t lastMatchedId = 0;
uint16_t lastMatchConfidence = 0;
bool lastMatchSuccess = false;
String lastMatchedName = "";
unsigned long lastScanTime = 0;

httpd_handle_t control_httpd = NULL; // port 80
httpd_handle_t stream_httpd  = NULL; // port 81

// ---------------- helpers ----------------

String getStudentName(uint16_t id) {
  String n = prefs.getString(String(id).c_str(), "");
  return n.length() ? n : ("ID #" + String(id));
}
void setStudentName(uint16_t id, const String& name) {
  if (name.length() > 0) prefs.putString(String(id).c_str(), name);
}
void clearStudentName(uint16_t id) {
  prefs.remove(String(id).c_str());
}
String escapeJson(String s) {
  s.replace("\\", "\\\\");
  s.replace("\"", "\\\"");
  return s;
}

void displayStatus(const String& msg) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println(msg);
  display.display();
}

void updateDisplay() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println("ATTENDANCE DEVICE");
  display.println("------------------");
  display.print("IP: ");
  display.println(WiFi.softAPIP().toString());
  display.print("Mode: ");
  if (currentAttendanceMode == MODE_FINGERPRINT_ONLY) display.println("FINGERPRINT");
  else if (currentAttendanceMode == MODE_DUAL_MODE) display.println("DUAL (FP+Face)");
  else display.println("FACE ONLY");
  display.print("Sensor: ");
  display.println(currentSensorMode == FINGER_MODE_ENROLL ? "ENROLL" : "SCAN");
  if (lastMatchSuccess) {
    display.print("Last: ");
    display.print(lastMatchedName);
    display.print(" #");
    display.println(lastMatchedId);
  }
  display.display();
}

// ---------------- camera streaming (port 81, unchanged design) ----------------
#define PART_BOUNDARY "123456789000000000000987654321"
static const char* STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

static esp_err_t stream_handler(httpd_req_t *req) {
  camera_fb_t * fb = NULL;
  esp_err_t res = ESP_OK;
  char part_buf[64];

  res = httpd_resp_set_type(req, STREAM_CONTENT_TYPE);
  if (res != ESP_OK) return res;

  while (true) {
    fb = esp_camera_fb_get();
    if (!fb) {
      res = ESP_FAIL;
    } else {
      size_t hlen = snprintf(part_buf, 64, STREAM_PART, fb->len);
      res = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));
      if (res == ESP_OK) res = httpd_resp_send_chunk(req, part_buf, hlen);
      if (res == ESP_OK) res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
      esp_camera_fb_return(fb);
    }
    if (res != ESP_OK) break;
  }
  return res;
}

// ---------------- control server handlers (port 80) ----------------

// GET / -- lightweight live-feed + status viewer for manual browser testing.
// Purely for humans looking at the device; the backend never hits this --
// it pulls frames from :81/stream directly and polls the JSON endpoints
// below. Safe to keep alongside the backend integration.
static const char INDEX_HTML[] =
"<!DOCTYPE html><html><head>"
"<meta name='viewport' content='width=device-width, initial-scale=1'>"
"<title>ESP32-CAM + Fingerprint</title>"
"<style>"
"body{font-family:sans-serif;max-width:480px;margin:20px auto;padding:0 16px;}"
"h2{text-align:center;}"
"img{width:100%;border-radius:8px;margin-bottom:16px;background:#111;}"
".status{background:#222;color:#0f0;padding:14px;border-radius:8px;font-size:13px;white-space:pre-wrap;margin-bottom:12px;}"
".row{display:flex;gap:8px;margin-bottom:12px;}"
"input,select{flex:1;padding:10px;font-size:16px;}"
"button{padding:10px 16px;font-size:16px;cursor:pointer;border:none;border-radius:6px;color:#fff;background:#2196F3;}"
".scan{background:#4CAF50;width:100%;padding:14px;margin-bottom:12px;} .del{background:#f44336;} .mode{background:#6a1b9a;}"
"#msg{text-align:center;min-height:20px;color:#555;}"
"</style></head><body>"
"<h2>ESP32-CAM + Fingerprint</h2>"
"<img id='cam' src=''>"
"<div class='status' id='status'>Loading...</div>"
"<div class='row'>"
"<select id='attMode'><option>FACE_ONLY</option><option>FINGERPRINT_ONLY</option><option>DUAL_MODE</option></select>"
"<button class='mode' onclick='setMode()'>Set Mode</button>"
"</div>"
"<button class='scan' onclick='doScan()'>Scan Now</button>"
"<div class='row'>"
"<input id='idInput' type='number' min='1' max='127' placeholder='ID (1-127)'>"
"<button onclick='doEnroll()'>Enroll</button>"
"<button class='del' onclick='doDelete()'>Delete</button>"
"</div>"
"<div id='msg'></div>"
"<script>"
"let busy=false;"
"document.getElementById('cam').src='http://'+location.hostname+':81/stream';"
"function msg(t){document.getElementById('msg').innerText=t;}"
"async function refresh(){if(busy)return;try{const r=await fetch('/status');const j=await r.json();"
"document.getElementById('status').innerText=JSON.stringify(j,null,2);"
"const s=document.getElementById('attMode');if(!s.dataset.i){s.value=j.attendanceMode;s.dataset.i=1;}}catch(e){}}"
"setInterval(refresh,2000);refresh();"
"async function run(url,pending){busy=true;msg(pending);"
"try{const r=await fetch(url);msg(await r.text());}catch(e){msg('Error: '+e);}"
"busy=false;refresh();}"
"function getId(){const v=document.getElementById('idInput').value;if(!v){alert('Enter an ID first');return null;}return v;}"
"function setMode(){run('/set-attendance-mode?mode='+document.getElementById('attMode').value,'Setting mode...');}"
"function doScan(){run('/scan','Scanning - keep finger on sensor...');}"
"function doEnroll(){const id=getId();if(id)run('/enroll?id='+id,'Enrolling ID '+id+' - place finger, lift, place again...');}"
"function doDelete(){const id=getId();if(id)run('/delete?id='+id,'Deleting...');}"
"</script></body></html>";

static esp_err_t index_handler(httpd_req_t *req) {
  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, INDEX_HTML, strlen(INDEX_HTML));
}

// GET /status -- general health/debug JSON (not required by backend, useful for you)
static esp_err_t status_handler(httpd_req_t *req) {
  uint16_t enrolledCount = 0;
  if (fingerReady && xSemaphoreTake(fingerMutex, pdMS_TO_TICKS(1000))) {
    finger.getTemplateCount();
    enrolledCount = finger.templateCount;
    xSemaphoreGive(fingerMutex);
  }
  String attModeStr = "FACE_ONLY";
  if (currentAttendanceMode == MODE_FINGERPRINT_ONLY) attModeStr = "FINGERPRINT_ONLY";
  else if (currentAttendanceMode == MODE_DUAL_MODE) attModeStr = "DUAL_MODE";

  String json = "{";
  json += "\"ip\":\"" + WiFi.softAPIP().toString() + "\",";
  json += "\"fingerReady\":" + String(fingerReady ? "true" : "false") + ",";
  json += "\"mode\":\"" + String(currentSensorMode == FINGER_MODE_SCAN ? "SCAN" : "ENROLL") + "\",";
  json += "\"attendanceMode\":\"" + attModeStr + "\",";
  json += "\"seq\":" + String(scanSeq) + ",";
  json += "\"enrolledCount\":" + String(enrolledCount) + ",";
  json += "\"freeHeap\":" + String(ESP.getFreeHeap());
  json += "}";
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_send(req, json.c_str(), json.length());
}

// GET /last-scan -- THE endpoint recognition/stream_manager.py polls every 0.5s
static esp_err_t last_scan_handler(httpd_req_t *req) {
  String json = "{";
  json += "\"matched\":" + String(lastMatchSuccess ? "true" : "false") + ",";
  json += "\"id\":" + String(lastMatchedId) + ",";
  json += "\"confidence\":" + String(lastMatchConfidence) + ",";
  json += "\"name\":\"" + escapeJson(lastMatchedName) + "\",";
  json += "\"seq\":" + String(scanSeq) + ",";
  json += "\"timestamp\":" + String(lastScanTime);
  json += "}";
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_send(req, json.c_str(), json.length());
}

// One fingerprint attempt against the sensor. Returns true on match.
bool detectFingerprint() {
  if (!xSemaphoreTake(fingerMutex, pdMS_TO_TICKS(500))) return false;

  uint8_t p = finger.getImage();
  if (p != FINGERPRINT_OK) { xSemaphoreGive(fingerMutex); return false; }

  p = finger.image2Tz();
  if (p != FINGERPRINT_OK) { xSemaphoreGive(fingerMutex); return false; }

  p = finger.fingerSearch();
  if (p == FINGERPRINT_OK) {
    lastMatchedId = finger.fingerID;
    lastMatchConfidence = finger.confidence;
    lastMatchSuccess = true;
    lastMatchedName = getStudentName(lastMatchedId);
    scanSeq++;                       // seq changes -> backend treats this as a NEW event
    lastScanTime = millis();
    xSemaphoreGive(fingerMutex);

    displayStatus("Match!\n" + lastMatchedName + "\n#" + String(lastMatchedId));
    delay(1000);
    updateDisplay();
    return true;
  } else {
    lastMatchSuccess = false;
    scanSeq++;                       // still bump seq so a stale "matched:false" isn't reprocessed
    lastScanTime = millis();
    xSemaphoreGive(fingerMutex);

    displayStatus("Not recognized");
    delay(800);
    updateDisplay();
    return false;
  }
}

// GET /scan -- manual trigger + returns the same shape as /last-scan (handy for a "test device" button)
static esp_err_t scan_handler(httpd_req_t *req) {
  if (fingerReady) detectFingerprint();
  return last_scan_handler(req);
}

// GET /set-attendance-mode?mode=FACE_ONLY|FINGERPRINT_ONLY|DUAL_MODE
// Called by api/faculty/session_view.py on faculty_start_recognition()
static esp_err_t set_attendance_mode_handler(httpd_req_t *req) {
  char buf[64];
  if (httpd_req_get_url_query_str(req, buf, sizeof(buf)) == ESP_OK) {
    char param[32];
    if (httpd_query_key_value(buf, "mode", param, sizeof(param)) == ESP_OK) {
      String m = String(param);
      if (m.equalsIgnoreCase("FINGERPRINT_ONLY")) currentAttendanceMode = MODE_FINGERPRINT_ONLY;
      else if (m.equalsIgnoreCase("DUAL_MODE") || m.equalsIgnoreCase("DUAL")) currentAttendanceMode = MODE_DUAL_MODE;
      else currentAttendanceMode = MODE_FACE_ONLY;

      // Clear any stale match from a previous session so a fresh
      // Start never inherits an old scan result.
      lastMatchSuccess = false;
      lastMatchedId = 0;
      lastMatchConfidence = 0;

      updateDisplay();
      httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
      return httpd_resp_send(req, "Attendance mode set", HTTPD_RESP_USE_STRLEN);
    }
  }
  return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing mode parameter");
}

// GET /set-mode?mode=SCAN|ENROLL -- gates the touch-triggered loop() scan
static esp_err_t set_mode_handler(httpd_req_t *req) {
  char buf[64];
  if (httpd_req_get_url_query_str(req, buf, sizeof(buf)) == ESP_OK) {
    char param[16];
    if (httpd_query_key_value(buf, "mode", param, sizeof(param)) == ESP_OK) {
      currentSensorMode = String(param).equalsIgnoreCase("ENROLL") ? FINGER_MODE_ENROLL : FINGER_MODE_SCAN;
      updateDisplay();
      httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
      return httpd_resp_send(req, "Sensor mode set", HTTPD_RESP_USE_STRLEN);
    }
  }
  return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing mode parameter");
}

// Returns false on timeout instead of blocking forever.
static bool waitFor(int (*step)(), unsigned long timeoutMs) {
  unsigned long start = millis();
  int p = -1;
  while (p != FINGERPRINT_OK) {
    p = step();
    if (millis() - start > timeoutMs) return false;
    delay(20);
  }
  return true;
}
static int stepGetImage() { return finger.getImage(); }
static int stepNoFinger() { return (finger.getImage() == FINGERPRINT_NOFINGER) ? FINGERPRINT_OK : -1; }

// GET /enroll?id=<template_id>  (optional &name=)
// Called by recognition/fingerprint_service.py: enroll_student() with a
// requests.get(..., timeout=20-25s). Budgeted below to finish inside ~18s
// worst case: 7s + 5s + 6s = 18s.
static esp_err_t enroll_handler(httpd_req_t *req) {
  char buf[128];
  uint16_t id = 0;
  String name = "";
  if (httpd_req_get_url_query_str(req, buf, sizeof(buf)) == ESP_OK) {
    char idStr[16], nameStr[64];
    if (httpd_query_key_value(buf, "id", idStr, sizeof(idStr)) == ESP_OK) id = atoi(idStr);
    if (httpd_query_key_value(buf, "name", nameStr, sizeof(nameStr)) == ESP_OK) name = String(nameStr);
  }
  if (id < 1 || id > 127) return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid ID (1-127)");

  if (!xSemaphoreTake(fingerMutex, pdMS_TO_TICKS(5000)))
    return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Sensor busy");

  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  currentSensorMode = FINGER_MODE_ENROLL; // Pause auto-scan in loop() while enrolling

  displayStatus("Enroll #" + String(id) + "\nPlace finger...");
  if (!waitFor(stepGetImage, 12000)) { // first touch, was 7000
    currentSensorMode = FINGER_MODE_SCAN;
    xSemaphoreGive(fingerMutex); updateDisplay();
    return httpd_resp_send(req, "Enroll Failed: Image 1 Timeout", HTTPD_RESP_USE_STRLEN);
  }
  if (finger.image2Tz(1) != FINGERPRINT_OK) {
    currentSensorMode = FINGER_MODE_SCAN;
    xSemaphoreGive(fingerMutex); updateDisplay();
    return httpd_resp_send(req, "Enroll Failed: Image 1 Conversion", HTTPD_RESP_USE_STRLEN);
  }

  displayStatus("Remove finger...");
  waitFor(stepNoFinger, 5000);   // bounded now -- won't hang the HTTP request forever

  displayStatus("Place same\nfinger again");
  if (!waitFor(stepGetImage, 12000)) {  // second touch, was 6000
    currentSensorMode = FINGER_MODE_SCAN;
    xSemaphoreGive(fingerMutex); updateDisplay();
    return httpd_resp_send(req, "Enroll Failed: Image 2 Timeout", HTTPD_RESP_USE_STRLEN);
  }
  if (finger.image2Tz(2) != FINGERPRINT_OK) {
    currentSensorMode = FINGER_MODE_SCAN;
    xSemaphoreGive(fingerMutex); updateDisplay();
    return httpd_resp_send(req, "Enroll Failed: Image 2 Conversion", HTTPD_RESP_USE_STRLEN);
  }

  int p = finger.createModel();
  if (p != FINGERPRINT_OK) {
    currentSensorMode = FINGER_MODE_SCAN;
    xSemaphoreGive(fingerMutex); updateDisplay();
    return httpd_resp_send(req, "Enroll Failed: Prints Do Not Match", HTTPD_RESP_USE_STRLEN);
  }

  p = finger.storeModel(id);
  if (p != FINGERPRINT_OK) {
    currentSensorMode = FINGER_MODE_SCAN;
    xSemaphoreGive(fingerMutex); updateDisplay();
    return httpd_resp_send(req, "Enroll Failed: Could Not Store Model", HTTPD_RESP_USE_STRLEN);
  }

  setStudentName(id, name);   // cosmetic only -- fine if backend sends no name
  currentSensorMode = FINGER_MODE_SCAN;
  xSemaphoreGive(fingerMutex);
  displayStatus("Enrolled!\nID #" + String(id));
  delay(1200);
  updateDisplay();
  return httpd_resp_send(req, "Enroll Success", HTTPD_RESP_USE_STRLEN);
}

// GET /delete?id=<template_id>
// Called by recognition/fingerprint_service.py: delete_enrollment()
static esp_err_t delete_handler(httpd_req_t *req) {
  char buf[64];
  uint16_t id = 0;
  if (httpd_req_get_url_query_str(req, buf, sizeof(buf)) == ESP_OK) {
    char idStr[16];
    if (httpd_query_key_value(buf, "id", idStr, sizeof(idStr)) == ESP_OK) id = atoi(idStr);
  }
  if (id < 1 || id > 127) return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid ID (1-127)");

  if (!xSemaphoreTake(fingerMutex, pdMS_TO_TICKS(2000)))
    return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Sensor busy");

  uint8_t p = finger.deleteModel(id);
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  if (p == FINGERPRINT_OK) {
    clearStudentName(id);
    xSemaphoreGive(fingerMutex);
    updateDisplay();
    return httpd_resp_send(req, "Delete Success", HTTPD_RESP_USE_STRLEN);
  }
  xSemaphoreGive(fingerMutex);
  return httpd_resp_send(req, "Delete Failed", HTTPD_RESP_USE_STRLEN);
}

// ---------------- servers ----------------
void startServers() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;
  config.ctrl_port = 32768;
  config.max_uri_handlers = 10;
  config.stack_size = 8192;   // enroll_handler needs headroom for String ops + blocking loops

  httpd_uri_t u_index   = { .uri="/",        .method=HTTP_GET, .handler=index_handler,   .user_ctx=NULL };
  httpd_uri_t u_status  = { .uri="/status",  .method=HTTP_GET, .handler=status_handler,  .user_ctx=NULL };
  httpd_uri_t u_last    = { .uri="/last-scan", .method=HTTP_GET, .handler=last_scan_handler, .user_ctx=NULL };
  httpd_uri_t u_scan    = { .uri="/scan",    .method=HTTP_GET, .handler=scan_handler,    .user_ctx=NULL };
  httpd_uri_t u_setatt  = { .uri="/set-attendance-mode", .method=HTTP_GET, .handler=set_attendance_mode_handler, .user_ctx=NULL };
  httpd_uri_t u_setmode = { .uri="/set-mode", .method=HTTP_GET, .handler=set_mode_handler, .user_ctx=NULL };
  httpd_uri_t u_enroll  = { .uri="/enroll",  .method=HTTP_GET, .handler=enroll_handler,  .user_ctx=NULL };
  httpd_uri_t u_delete  = { .uri="/delete",  .method=HTTP_GET, .handler=delete_handler,  .user_ctx=NULL };

  if (httpd_start(&control_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(control_httpd, &u_index);
    httpd_register_uri_handler(control_httpd, &u_status);
    httpd_register_uri_handler(control_httpd, &u_last);
    httpd_register_uri_handler(control_httpd, &u_scan);
    httpd_register_uri_handler(control_httpd, &u_setatt);
    httpd_register_uri_handler(control_httpd, &u_setmode);
    httpd_register_uri_handler(control_httpd, &u_enroll);
    httpd_register_uri_handler(control_httpd, &u_delete);
  } else {
    Serial.println("Failed to start control httpd");
  }

  httpd_config_t sconfig = HTTPD_DEFAULT_CONFIG();
  sconfig.server_port = 81;
  sconfig.ctrl_port = 32769;
  sconfig.stack_size = 8192;
  sconfig.recv_wait_timeout = 10;
  sconfig.send_wait_timeout = 10;
  httpd_uri_t u_stream = { .uri="/stream", .method=HTTP_GET, .handler=stream_handler, .user_ctx=NULL };
  if (httpd_start(&stream_httpd, &sconfig) == ESP_OK) {
    httpd_register_uri_handler(stream_httpd, &u_stream);
  } else {
    Serial.println("Failed to start stream httpd");
  }
}

// ---------------- setup / loop ----------------
void setup() {
  Serial.begin(115200);
  pinMode(TOUCH_PIN, INPUT);

  ledcAttach(FLASH_LED_PIN, FLASH_LED_FREQ, FLASH_LED_RES_BITS);
  ledcWrite(FLASH_LED_PIN, FLASH_LED_LEVEL);

  fingerMutex = xSemaphoreCreateMutex();
  prefs.begin("fpnames", false);

  Wire.begin(OLED_SDA, OLED_SCL);
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED not found");
  } else {
    displayStatus("Booting...");
  }

  fingerSerial.begin(57600, SERIAL_8N1, FINGER_RX, FINGER_TX);
  finger.begin(57600);
  fingerReady = finger.verifyPassword();
  Serial.println(fingerReady ? "Fingerprint sensor found!" : "Fingerprint sensor NOT found");
  if (!fingerReady) displayStatus("Sensor Error\nCheck wiring");
  finger.getTemplateCount();
  Serial.print("Templates stored: "); Serial.println(finger.templateCount);

  // Zero-initialized to avoid the "fb malloc failed" issue you already
  // diagnosed in the previous firmware -- garbage fb_location on newer
  // esp32-camera driver versions can make it try to allocate in PSRAM
  // when PSRAM was never brought up.
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM; config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM; config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM; config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM; config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM; config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM; config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM; config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM; config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode = CAMERA_GRAB_LATEST;

  bool hasPsram = psramFound();
  Serial.print("PSRAM found: "); Serial.println(hasPsram ? "yes" : "no");
  if (hasPsram) {
    config.frame_size = FRAMESIZE_VGA;
    config.jpeg_quality = 12;
    config.fb_count = 2;
    config.fb_location = CAMERA_FB_IN_PSRAM;
  } else {
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 15;
    config.fb_count = 1;
    config.fb_location = CAMERA_FB_IN_DRAM;
  }

  esp_err_t camErr = esp_camera_init(&config);
  if (camErr != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", camErr);
    displayStatus("Camera Error");
  }

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);
  Serial.print("Hotspot IP: "); Serial.println(WiFi.softAPIP());

  startServers();
  updateDisplay();
}

void loop() {
  // Touch-triggered local scan -- edge-detected, only runs when the
  // faculty session has actually put this device in a fingerprint mode.
  bool touched = digitalRead(TOUCH_PIN);
  bool shouldAutoScan = fingerReady &&
                         currentSensorMode == FINGER_MODE_SCAN &&
                         currentAttendanceMode != MODE_FACE_ONLY;

  if (shouldAutoScan && touched && !lastTouchState) {
    detectFingerprint();
  }
  lastTouchState = touched;
  delay(50);
}