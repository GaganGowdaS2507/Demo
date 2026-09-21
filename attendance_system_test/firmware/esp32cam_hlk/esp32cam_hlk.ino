/*
  ESP32-CAM (AI-Thinker) + HLK-ZW101 Fingerprint Sensor + OLED (SSD1306) + Capacitive Touch

  MERGED & EXTENDED FIRMWARE FOR MULTI-MODE ATTENDANCE SYSTEM
  
  Architecture & Features:
  1) Port 80: HTTP Control Server (/status, /scan, /last-scan, /enroll, /delete, /set-mode, /set-attendance-mode, /set-name)
  2) Port 81: HTTP MJPEG Video Stream Server (/stream)
  3) Fingerprint sensor operating mode: SCAN vs ENROLL
  4) System Attendance Mode: FACE_ONLY, FINGERPRINT_ONLY, DUAL_MODE
  5) Touch-triggered local matching in loop() thread-safe with HTTP requests via fingerMutex
  6) Incrementing sequence counter (seq) included in /scan and /last-scan JSON responses for polling deduplication
  7) Local OLED status display
  8) Security: Fingerprint templates remain inside sensor flash (HLK-ZW101). No raw templates are sent over HTTP.
*/

#include <Arduino.h>
#include <WiFi.h>
#include <esp_camera.h>
#include <esp_http_server.h>
#include <Adafruit_Fingerprint.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Preferences.h>
#include <freertos/semphr.h>

// ==================== CONFIGURATION ====================
const char* WIFI_SSID = "ESP32-Attendance-AP";
const char* WIFI_PASS = "12345678";

// Pin Assignments for AI-Thinker ESP32-CAM
#define FINGER_RX_PIN  13
#define FINGER_TX_PIN  15
#define TOUCH_PIN      12   // Touch sensor pin

#define OLED_SDA_PIN   14
#define OLED_SCL_PIN   2

#define OLED_SCREEN_WIDTH  128
#define OLED_SCREEN_HEIGHT 64
#define OLED_RESET_PIN     -1

// Camera Pin Definition (AI-Thinker Model)
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

// Global Objects
HardwareSerial fingerSerial(2);
Adafruit_Fingerprint finger = Adafruit_Fingerprint(&fingerSerial);
Adafruit_SSD1306 display(OLED_SCREEN_WIDTH, OLED_SCREEN_HEIGHT, &Wire, OLED_RESET_PIN);
Preferences prefs;

SemaphoreHandle_t fingerMutex = NULL;

httpd_handle_t control_httpd = NULL;
httpd_handle_t stream_httpd = NULL;

// Enums & States
enum FingerSensorMode { FINGER_MODE_SCAN, FINGER_MODE_ENROLL };
enum AttendanceMode { MODE_FACE_ONLY, MODE_FINGERPRINT_ONLY, MODE_DUAL_MODE };

FingerSensorMode currentSensorMode = FINGER_MODE_SCAN;
AttendanceMode currentAttendanceMode = MODE_FACE_ONLY;

bool fingerReady = false;
uint32_t scanSeq = 0;
uint16_t lastMatchedId = 0;
uint16_t lastMatchConfidence = 0;
bool lastMatchSuccess = false;
String lastMatchedName = "";
unsigned long lastScanTime = 0;

// Function Declarations
void displayStatus(const String& msg);
void updateDisplay();
String getStudentName(uint16_t id);
void setStudentName(uint16_t id, const String& name);
bool detectFingerprint();

// ==================== CAMERA INIT ====================
bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_siod = SIOD_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM; // required for Arduino ESP32 core v3+
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_sioc = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  if (psramFound()) {
    config.frame_size = FRAMESIZE_VGA;
    config.jpeg_quality = 12;
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 15;
    config.fb_count = 1;
  }

  esp_err_t err = esp_camera_init(&config);
  return (err == ESP_OK);
}

// ==================== MJPEG STREAM HANDLER (PORT 81) ====================
#define PART_BOUNDARY "123456789000000000000987654321"
static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* _STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

static esp_err_t stream_handler(httpd_req_t *req) {
  camera_fb_t * fb = NULL;
  esp_err_t res = ESP_OK;
  size_t _jpg_buf_len = 0;
  uint8_t * _jpg_buf = NULL;
  char part_buf[64];

  res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
  if (res != ESP_OK) return res;

  while (true) {
    fb = esp_camera_fb_get();
    if (!fb) {
      res = ESP_FAIL;
    } else {
      _jpg_buf_len = fb->len;
      _jpg_buf = fb->buf;
    }
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
    }
    if (res == ESP_OK) {
      size_t hlen = snprintf(part_buf, 64, _STREAM_PART, _jpg_buf_len);
      res = httpd_resp_send_chunk(req, part_buf, hlen);
    }
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, (const char *)_jpg_buf, _jpg_buf_len);
    }
    if (fb) {
      esp_camera_fb_return(fb);
      fb = NULL;
    }
    if (res != ESP_OK) break;
  }
  return res;
}

// ==================== CONTROL SERVER HANDLERS (PORT 80) ====================

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
  json += "\"lastId\":" + String(lastMatchedId) + ",";
  json += "\"lastConfidence\":" + String(lastMatchConfidence) + ",";
  json += "\"lastMatchSuccess\":" + String(lastMatchSuccess ? "true" : "false") + ",";
  json += "\"seq\":" + String(scanSeq) + ",";
  json += "\"enrolledCount\":" + String(enrolledCount) + ",";
  json += "\"freeHeap\":" + String(ESP.getFreeHeap());
  json += "}";

  httpd_resp_set_type(req, "application/json");
  return httpd_resp_send(req, json.c_str(), json.length());
}

static esp_err_t last_scan_handler(httpd_req_t *req) {
  String json = "{";
  json += "\"matched\":" + String(lastMatchSuccess ? "true" : "false") + ",";
  json += "\"id\":" + String(lastMatchedId) + ",";
  json += "\"confidence\":" + String(lastMatchConfidence) + ",";
  json += "\"name\":\"" + lastMatchedName + "\",";
  json += "\"seq\":" + String(scanSeq) + ",";
  json += "\"timestamp\":" + String(lastScanTime);
  json += "}";

  httpd_resp_set_type(req, "application/json");
  return httpd_resp_send(req, json.c_str(), json.length());
}

static esp_err_t scan_handler(httpd_req_t *req) {
  bool matched = false;
  if (fingerReady) {
    matched = detectFingerprint();
  }
  return last_scan_handler(req);
}

static esp_err_t set_attendance_mode_handler(httpd_req_t *req) {
  char buf[64];
  if (httpd_req_get_url_query_str(req, buf, sizeof(buf)) == ESP_OK) {
    char param[32];
    if (httpd_query_key_value(buf, "mode", param, sizeof(param)) == ESP_OK) {
      String m = String(param);
      if (m.equalsIgnoreCase("FINGERPRINT_ONLY")) {
        currentAttendanceMode = MODE_FINGERPRINT_ONLY;
      } else if (m.equalsIgnoreCase("DUAL_MODE") || m.equalsIgnoreCase("DUAL")) {
        currentAttendanceMode = MODE_DUAL_MODE;
      } else {
        currentAttendanceMode = MODE_FACE_ONLY;
      }
      updateDisplay();
      return httpd_resp_send(req, "Attendance mode set successfully", HTTPD_200);
    }
  }
  return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing mode parameter");
}

static esp_err_t set_mode_handler(httpd_req_t *req) {
  char buf[64];
  if (httpd_req_get_url_query_str(req, buf, sizeof(buf)) == ESP_OK) {
    char param[16];
    if (httpd_query_key_value(buf, "mode", param, sizeof(param)) == ESP_OK) {
      String m = String(param);
      if (m.equalsIgnoreCase("ENROLL")) {
        currentSensorMode = FINGER_MODE_ENROLL;
      } else {
        currentSensorMode = FINGER_MODE_SCAN;
      }
      updateDisplay();
      return httpd_resp_send(req, "Sensor mode set successfully", HTTPD_200);
    }
  }
  return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing mode parameter");
}

static esp_err_t enroll_handler(httpd_req_t *req) {
  char buf[128];
  uint16_t id = 0;
  String name = "";

  if (httpd_req_get_url_query_str(req, buf, sizeof(buf)) == ESP_OK) {
    char idStr[16], nameStr[64];
    if (httpd_query_key_value(buf, "id", idStr, sizeof(idStr)) == ESP_OK) {
      id = atoi(idStr);
    }
    if (httpd_query_key_value(buf, "name", nameStr, sizeof(nameStr)) == ESP_OK) {
      name = String(nameStr);
    }
  }

  if (id < 1 || id > 127) {
    return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid ID (1-127)");
  }

  if (!xSemaphoreTake(fingerMutex, pdMS_TO_TICKS(5000))) {
    return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Sensor busy");
  }

  displayStatus("Enroll ID #" + String(id) + "\nPlace Finger...");
  
  // Step 1: Image 1
  int p = -1;
  unsigned long start = millis();
  while (p != FINGERPRINT_OK && millis() - start < 15000) {
    p = finger.getImage();
    delay(50);
  }
  if (p != FINGERPRINT_OK) {
    xSemaphoreGive(fingerMutex);
    updateDisplay();
    return httpd_resp_send(req, "Enroll Failed: Image 1 Timeout", HTTPD_200);
  }

  p = finger.image2Tz(1);
  if (p != FINGERPRINT_OK) {
    xSemaphoreGive(fingerMutex);
    updateDisplay();
    return httpd_resp_send(req, "Enroll Failed: Image 1 Conversion", HTTPD_200);
  }

  displayStatus("Remove Finger...");
  delay(2000);
  p = 0;
  while (p != FINGERPRINT_NOFINGER) {
    p = finger.getImage();
    delay(50);
  }

  displayStatus("Place Same\nFinger Again...");
  start = millis();
  p = -1;
  while (p != FINGERPRINT_OK && millis() - start < 15000) {
    p = finger.getImage();
    delay(50);
  }
  if (p != FINGERPRINT_OK) {
    xSemaphoreGive(fingerMutex);
    updateDisplay();
    return httpd_resp_send(req, "Enroll Failed: Image 2 Timeout", HTTPD_200);
  }

  p = finger.image2Tz(2);
  if (p != FINGERPRINT_OK) {
    xSemaphoreGive(fingerMutex);
    updateDisplay();
    return httpd_resp_send(req, "Enroll Failed: Image 2 Conversion", HTTPD_200);
  }

  p = finger.createModel();
  if (p != FINGERPRINT_OK) {
    xSemaphoreGive(fingerMutex);
    updateDisplay();
    return httpd_resp_send(req, "Enroll Failed: Prints Do Not Match", HTTPD_200);
  }

  p = finger.storeModel(id);
  if (p != FINGERPRINT_OK) {
    xSemaphoreGive(fingerMutex);
    updateDisplay();
    return httpd_resp_send(req, "Enroll Failed: Could Not Store Model", HTTPD_200);
  }

  if (name.length() > 0) {
    setStudentName(id, name);
  }

  xSemaphoreGive(fingerMutex);
  displayStatus("Enroll Success!\nID #" + String(id));
  delay(1500);
  updateDisplay();

  return httpd_resp_send(req, "Enroll Success", HTTPD_200);
}

static esp_err_t delete_handler(httpd_req_t *req) {
  char buf[64];
  uint16_t id = 0;
  if (httpd_req_get_url_query_str(req, buf, sizeof(buf)) == ESP_OK) {
    char idStr[16];
    if (httpd_query_key_value(buf, "id", idStr, sizeof(idStr)) == ESP_OK) {
      id = atoi(idStr);
    }
  }

  if (id < 1 || id > 127) {
    return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid ID (1-127)");
  }

  if (!xSemaphoreTake(fingerMutex, pdMS_TO_TICKS(2000))) {
    return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Sensor busy");
  }

  uint8_t p = finger.deleteModel(id);
  if (p == FINGERPRINT_OK) {
    prefs.remove(String(id).c_str());
    xSemaphoreGive(fingerMutex);
    updateDisplay();
    return httpd_resp_send(req, "Delete Success", HTTPD_200);
  }

  xSemaphoreGive(fingerMutex);
  return httpd_resp_send(req, "Delete Failed", HTTPD_200);
}

// ==================== SERVER INITIALIZATION ====================
void startServers() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;
  config.ctrl_port = 32768;

  httpd_uri_t uri_status = { .uri = "/status", .method = HTTP_GET, .handler = status_handler, .user_ctx = NULL };
  httpd_uri_t uri_scan = { .uri = "/scan", .method = HTTP_GET, .handler = scan_handler, .user_ctx = NULL };
  httpd_uri_t uri_last_scan = { .uri = "/last-scan", .method = HTTP_GET, .handler = last_scan_handler, .user_ctx = NULL };
  httpd_uri_t uri_set_att_mode = { .uri = "/set-attendance-mode", .method = HTTP_GET, .handler = set_attendance_mode_handler, .user_ctx = NULL };
  httpd_uri_t uri_set_mode = { .uri = "/set-mode", .method = HTTP_GET, .handler = set_mode_handler, .user_ctx = NULL };
  httpd_uri_t uri_enroll = { .uri = "/enroll", .method = HTTP_GET, .handler = enroll_handler, .user_ctx = NULL };
  httpd_uri_t uri_delete = { .uri = "/delete", .method = HTTP_GET, .handler = delete_handler, .user_ctx = NULL };

  if (httpd_start(&control_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(control_httpd, &uri_status);
    httpd_register_uri_handler(control_httpd, &uri_scan);
    httpd_register_uri_handler(control_httpd, &uri_last_scan);
    httpd_register_uri_handler(control_httpd, &uri_set_att_mode);
    httpd_register_uri_handler(control_httpd, &uri_set_mode);
    httpd_register_uri_handler(control_httpd, &uri_enroll);
    httpd_register_uri_handler(control_httpd, &uri_delete);
  }

  // Stream Server on Port 81
  config.server_port = 81;
  config.ctrl_port = 32769;
  httpd_uri_t uri_stream = { .uri = "/stream", .method = HTTP_GET, .handler = stream_handler, .user_ctx = NULL };
  if (httpd_start(&stream_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(stream_httpd, &uri_stream);
  }
}

// ==================== HELPER FUNCTIONS ====================
String getStudentName(uint16_t id) {
  return prefs.getString(String(id).c_str(), "Student #" + String(id));
}

void setStudentName(uint16_t id, const String& name) {
  prefs.putString(String(id).c_str(), name);
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
  display.println("ESP32 ATTENDANCE CAM");
  display.println("--------------------");
  
  display.print("AP IP: ");
  display.println(WiFi.softAPIP().toString());

  display.print("Att.Mode: ");
  if (currentAttendanceMode == MODE_FINGERPRINT_ONLY) display.println("FINGER");
  else if (currentAttendanceMode == MODE_DUAL_MODE) display.println("DUAL (FP+Face)");
  else display.println("FACE ONLY");

  display.print("Sensor  : ");
  display.println(currentSensorMode == FINGER_MODE_ENROLL ? "ENROLL" : "SCAN");

  if (lastMatchSuccess) {
    display.print("Last: ");
    display.print(lastMatchedName);
    display.print(" (#");
    display.print(lastMatchedId);
    display.println(")");
  }

  display.display();
}

bool detectFingerprint() {
  if (!xSemaphoreTake(fingerMutex, pdMS_TO_TICKS(500))) {
    return false;
  }

  uint8_t p = finger.getImage();
  if (p != FINGERPRINT_OK) {
    xSemaphoreGive(fingerMutex);
    return false;
  }

  p = finger.image2Tz();
  if (p != FINGERPRINT_OK) {
    xSemaphoreGive(fingerMutex);
    return false;
  }

  p = finger.fingerFastSearch();
  if (p == FINGERPRINT_OK) {
    lastMatchedId = finger.fingerID;
    lastMatchConfidence = finger.confidence;
    lastMatchSuccess = true;
    lastMatchedName = getStudentName(lastMatchedId);
    scanSeq++;
    lastScanTime = millis();
    xSemaphoreGive(fingerMutex);

    displayStatus("Match Found!\nID: #" + String(lastMatchedId) + "\n" + lastMatchedName);
    delay(1000);
    updateDisplay();
    return true;
  } else {
    lastMatchSuccess = false;
    scanSeq++;
    lastScanTime = millis();
    xSemaphoreGive(fingerMutex);

    displayStatus("Fingerprint\nNot Recognized!");
    delay(1000);
    updateDisplay();
    return false;
  }
}

// ==================== SETUP & LOOP ====================
void setup() {
  Serial.begin(115200);
  pinMode(TOUCH_PIN, INPUT);

  Wire.begin(OLED_SDA_PIN, OLED_SCL_PIN);
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED Allocation failed");
  } else {
    display.clearDisplay();
    displayStatus("Booting System...");
  }

  prefs.begin("nameMap", false);
  fingerMutex = xSemaphoreCreateMutex();

  // Hardware Serial for Fingerprint Sensor
  fingerSerial.begin(57600, SERIAL_8N1, FINGER_RX_PIN, FINGER_TX_PIN);
  if (finger.verifyPassword()) {
    fingerReady = true;
    finger.getParameters();
  } else {
    fingerReady = false;
  }

  // Camera Init
  initCamera();

  // Wi-Fi AP Setup
  WiFi.softAP(WIFI_SSID, WIFI_PASS);

  // Start HTTP Servers
  startServers();

  updateDisplay();
}

void loop() {
  // Check touch sensor pin for local finger scan in SCAN mode
  if (fingerReady && currentSensorMode == FINGER_MODE_SCAN && digitalRead(TOUCH_PIN) == HIGH) {
    detectFingerprint();
    delay(500);
  }
  delay(100);
}
