// ESP32-S3 2.8" Display Video Player (ES3C28P / ES3N28P)
// Optimized for speed using PSRAM and JPEGDEC

#include <FS.h>
#include <SD_MMC.h>
#include <vector>
#include <TFT_eSPI.h>
#include <TJpg_Decoder.h>
#include <Wire.h>
#include <SensirionI2cScd4x.h>
#include <esp_sleep.h>
#include <driver/gpio.h>
#include <Adafruit_NeoPixel.h>
#include <esp_task_wdt.h>

using namespace fs;

// ============================================================================
// Pin Definitions
// ============================================================================
#define LCD_BL      45
#define SD_CLK      38
#define SD_CMD      40
#define SD_D0       39
#define SD_D1       41
#define SD_D2       48
#define SD_D3       47
#define I2C_SDA     16
#define I2C_SCL     15
#define BOOT_PIN    0
#define RGB_LED_PIN 42
#define BATTERY_PIN 9

// ============================================================================
// Configuration
// ============================================================================
#define BOOT_BUTTON_DEBOUNCE_TIME 400
#define BOOT_BUTTON_HOLD_TIME     1500
#define DEFAULT_FPS               15
#define SENSOR_READ_INTERVAL      1000
#define READINGS_PER_AVERAGE      12

// CO2 monitoring configuration
#define CO2_ALERT_THRESHOLD       1200   // LED alert above this
#define CO2_CLEAR_THRESHOLD       1100   // Clear alert below this (hysteresis)

// Sensor timing (single-shot mode for power efficiency)
#define SENSOR_INITIAL_INTERVAL   20000  // 20 sec between readings during initial phase
#define SENSOR_INITIAL_READINGS   3      // Number of readings before switching to normal interval
#define SENSOR_NORMAL_INTERVAL    60000  // 1 minute between readings (normal operation)
#define VIDEO_CO2_CHECK_INTERVAL  120000 // 2 minutes between CO2 checks during video

// Battery monitoring
#define BATTERY_LOW_VOLTAGE       3.3    // Show warning below this voltage
#define BATTERY_DIVIDER_RATIO     2.0    // Voltage divider ratio (adjust if needed)

// Hardware pins
#define AUDIO_ENABLE_PIN              1      // Audio amp enable (LOW=enable, HIGH=disable)

// Use PSRAM for large buffers (ESP32-S3 has 8MB)
#define MJPEG_BUF_SIZE  (100 * 1024)  // 100KB for JPEG frame
#define READ_BUF_SIZE   (16 * 1024)   // 16KB read buffer

const char *MJPEG_FOLDER = "/mjpeg";

// ============================================================================
// Globals
// ============================================================================
enum AppMode { VIDEO_MODE, SENSOR_MODE };
AppMode currentMode = VIDEO_MODE;

std::vector<String> mjpegFileList;
int mjpegCount = 0;
int currentMjpegIndex = 0;

TFT_eSPI tft = TFT_eSPI();
File mjpegFile;

// Buffers in PSRAM
uint8_t *mjpegBuf = nullptr;
uint8_t *readBuf = nullptr;
int readBufPos = 0;
int readBufLen = 0;

unsigned long total_frames, start_ms;

// Sensor (using single-shot mode for power efficiency)
SensirionI2cScd4x scd4x;
uint16_t sensorCO2 = 0;
float sensorTemperature = 0.0, sensorHumidity = 0.0;
bool sensorReady = false;
unsigned long lastSensorRead = 0;
uint8_t initialReadingCount = 0;      // Track readings during initial phase
bool sensorInitialPhase = true;       // True during rapid initial sampling
bool singleShotInProgress = false;    // True while waiting for single-shot result
unsigned long singleShotStartTime = 0;

volatile bool skipRequested = false;
uint32_t lastPress = 0;
uint32_t lastModeChange = 0;
#define MODE_CHANGE_COOLDOWN 500  // Ignore button for 500ms after mode change

// CO2 alert state
unsigned long lastVideoCO2Check = 0;
bool co2AlertActive = false;

// RGB LED for CO2 alert
Adafruit_NeoPixel rgbLed(1, RGB_LED_PIN, NEO_GRB + NEO_KHZ800);

void IRAM_ATTR onButtonPress() { skipRequested = true; }

// ============================================================================
// TJpg_Decoder callback
// ============================================================================
bool tftOutput(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t* bitmap) {
    if (y >= tft.height()) return 0;
    tft.pushImage(x, y, w, h, bitmap);
    return 1;
}

// ============================================================================
// Fast buffered reading
// ============================================================================
inline int fastRead() {
    if (readBufPos >= readBufLen) {
        readBufLen = mjpegFile.read(readBuf, READ_BUF_SIZE);
        readBufPos = 0;
        if (readBufLen <= 0) return -1;
    }
    return readBuf[readBufPos++];
}

// Read entire JPEG frame into buffer
int readJpegFrame(uint8_t *buf, int maxSize) {
    int b, state = 0;

    // Find FFD8
    while ((b = fastRead()) >= 0) {
        if (state == 0 && b == 0xFF) state = 1;
        else if (state == 1 && b == 0xD8) break;
        else state = 0;
    }
    if (b < 0) return 0;

    buf[0] = 0xFF;
    buf[1] = 0xD8;
    int pos = 2;
    state = 0;

    while ((b = fastRead()) >= 0 && pos < maxSize - 1) {
        buf[pos++] = b;
        if (state == 0 && b == 0xFF) state = 1;
        else if (state == 1 && b == 0xD9) return pos;
        else state = 0;
    }
    return 0;
}

// ============================================================================
// Helpers
// ============================================================================
bool checkButtonHold() {
    if (digitalRead(BOOT_PIN) == LOW) {
        unsigned long start = millis();
        while (digitalRead(BOOT_PIN) == LOW) {
            if (millis() - start >= BOOT_BUTTON_HOLD_TIME) return true;
            delay(10);
        }
    }
    return false;
}

// Prepare all peripherals for minimum power consumption
void prepareForSleep() {
    Serial.println("Preparing for deep sleep...");
    Serial.flush();

    // 1. Stop SCD41 periodic measurement and put in power-down mode
    if (sensorReady) {
        scd4x.stopPeriodicMeasurement();
        delay(500);  // Wait for command to complete
        scd4x.powerDown();  // SCD41 sleep mode (~0.4µA)
        delay(10);
    }

    // 2. Turn off display backlight
    digitalWrite(LCD_BL, LOW);

    // 3. Put ILI9341 display in sleep mode
    tft.writecommand(0x10);  // Sleep in command
    delay(120);              // Required delay per datasheet

    // 4. Disable audio amplifier (HIGH = disabled on this board)
    pinMode(AUDIO_ENABLE_PIN, OUTPUT);
    digitalWrite(AUDIO_ENABLE_PIN, HIGH);

    // 5. Turn off RGB LED
    rgbLed.clear();
    rgbLed.show();

    // 6. Disable I2C to reduce leakage (touch controller stays powered but bus inactive)
    Wire.end();

    // 7. Set unused expansion pins to input with no pull (reduce leakage)
    pinMode(2, INPUT);
    pinMode(3, INPUT);
    pinMode(14, INPUT);
    pinMode(21, INPUT);

    // 8. Hold GPIO states during sleep
    gpio_hold_en(GPIO_NUM_45);   // Backlight off
    gpio_hold_en(GPIO_NUM_1);    // Audio disabled
}

// Deep sleep - wake on button press
void enterDeepSleep() {
    Serial.println("Entering deep sleep...");

    // Wait for button release first
    while (digitalRead(BOOT_PIN) == LOW) delay(10);
    delay(100);

    prepareForSleep();

    // Configure wake-up: button press only
    esp_sleep_enable_ext0_wakeup(GPIO_NUM_0, 0);  // Wake on LOW

    esp_deep_sleep_start();
}

int parseFps(const String &name) {
    int idx = name.lastIndexOf("fps");
    if (idx > 0) {
        int start = idx - 1;
        while (start > 0 && isDigit(name.charAt(start - 1))) start--;
        int fps = name.substring(start, idx).toInt();
        if (fps > 0 && fps <= 60) return fps;
    }
    return DEFAULT_FPS;
}

// ============================================================================
// Sensor
// ============================================================================
void initSensor() {
    Wire.begin(I2C_SDA, I2C_SCL);
    scd4x.begin(Wire, SCD41_I2C_ADDR_62);

    // Stop any existing measurement and wake sensor
    scd4x.wakeUp();
    delay(30);
    scd4x.stopPeriodicMeasurement();
    delay(500);

    // We'll use single-shot mode for power efficiency (not periodic)
    sensorReady = true;
    sensorInitialPhase = true;
    initialReadingCount = 0;
    lastSensorRead = 0;  // Force immediate first reading

    Serial.println("Sensor: Ready (single-shot mode)");
}

void enterSensorMode() {
    currentMode = SENSOR_MODE;
    sensorInitialPhase = true;
    initialReadingCount = 0;
    lastSensorRead = 0;  // Force immediate reading
    singleShotInProgress = false;
    tft.fillScreen(TFT_BLACK);
    skipRequested = false;
    lastModeChange = millis();
    Serial.println("Entering sensor mode (initial rapid sampling)");
}

void enterVideoMode() {
    currentMode = VIDEO_MODE;
    skipRequested = false;
    lastVideoCO2Check = 0;  // Force CO2 check soon after entering video mode
    singleShotInProgress = false;
    lastModeChange = millis();
    tft.fillScreen(TFT_BLACK);
    Serial.println("Entering video mode");
}

// Read battery voltage
float readBatteryVoltage() {
    int raw = analogRead(BATTERY_PIN);
    // ESP32-S3 ADC: 12-bit (0-4095), reference ~3.3V
    float voltage = (raw / 4095.0) * 3.3 * BATTERY_DIVIDER_RATIO;
    return voltage;
}

void updateSensorDisplay() {
    tft.fillScreen(TFT_BLACK);

    // Status indicator
    tft.setTextColor(TFT_DARKGREY);
    tft.setTextSize(1);
    tft.setCursor(10, 5);
    if (sensorInitialPhase) {
        tft.printf("Sampling... (%d/%d)", initialReadingCount, SENSOR_INITIAL_READINGS);
    } else {
        tft.print("Monitoring (1 min intervals)");
    }

    // CO2
    tft.setTextColor(TFT_WHITE);
    tft.setTextSize(2);
    tft.setCursor(20, 25);
    tft.print("CO2");
    tft.setTextColor(sensorCO2 > 1000 ? TFT_RED : sensorCO2 > 800 ? TFT_YELLOW : TFT_GREEN);
    tft.setTextSize(4);
    tft.setCursor(20, 50);
    if (sensorCO2 > 0) {
        tft.printf("%d ppm", sensorCO2);
    } else {
        tft.print("---");
    }

    // Temperature
    tft.setTextColor(TFT_WHITE);
    tft.setTextSize(2);
    tft.setCursor(20, 105);
    tft.print("Temperature");
    tft.setTextColor(TFT_ORANGE);
    tft.setTextSize(4);
    tft.setCursor(20, 130);
    tft.printf("%.1f C", sensorTemperature);

    // Humidity
    tft.setTextColor(TFT_WHITE);
    tft.setTextSize(2);
    tft.setCursor(20, 185);
    tft.print("Humidity");
    tft.setTextColor(TFT_BLUE);
    tft.setTextSize(4);
    tft.setCursor(20, 210);
    tft.printf("%.1f %%", sensorHumidity);

    // Battery voltage
    float batteryVoltage = readBatteryVoltage();
    if (batteryVoltage > 1.0) {
        tft.setTextColor(batteryVoltage < BATTERY_LOW_VOLTAGE ? TFT_RED : TFT_DARKGREY);
        tft.setTextSize(1);
        tft.setCursor(10, 265);
        tft.printf("Battery: %.2fV", batteryVoltage);
    }

    // Instructions
    tft.setTextColor(TFT_DARKGREY);
    tft.setTextSize(1);
    tft.setCursor(10, 285);
    tft.print("Short press: video mode");
    tft.setCursor(10, 300);
    tft.print("Long hold: sleep");
}

// Take a single-shot measurement (non-blocking state machine)
// Returns true when a new reading is available
bool updateSingleShotMeasurement() {
    if (!sensorReady) return false;

    unsigned long now = millis();
    unsigned long interval = sensorInitialPhase ? SENSOR_INITIAL_INTERVAL : SENSOR_NORMAL_INTERVAL;

    // State machine for single-shot measurement
    if (!singleShotInProgress) {
        // Check if it's time for a new measurement
        if (now - lastSensorRead >= interval) {
            // Start single-shot measurement
            if (scd4x.measureSingleShot() == 0) {
                singleShotInProgress = true;
                singleShotStartTime = now;
                Serial.println("Single-shot started...");
            } else {
                Serial.println("Single-shot command failed");
                lastSensorRead = now;  // Try again next interval
            }
        }
        return false;
    }

    // Waiting for measurement to complete (~5 seconds)
    if (now - singleShotStartTime < 5000) {
        return false;  // Still waiting
    }

    // Check if data is ready
    bool dataReady = false;
    if (scd4x.getDataReadyStatus(dataReady) != 0 || !dataReady) {
        // Not ready yet, keep waiting (up to 6 seconds total)
        if (now - singleShotStartTime > 6000) {
            Serial.println("Single-shot timeout");
            singleShotInProgress = false;
            lastSensorRead = now;
        }
        return false;
    }

    // Read the measurement
    uint16_t co2;
    float temp, hum;
    if (scd4x.readMeasurement(co2, temp, hum) == 0 && co2 > 0) {
        sensorCO2 = co2;
        sensorTemperature = temp;
        sensorHumidity = hum;

        Serial.printf("CO2: %d ppm, Temp: %.1f C, Hum: %.1f%%\n", co2, temp, hum);

        // Update CO2 alert state
        bool prevAlert = co2AlertActive;
        if (!co2AlertActive && co2 >= CO2_ALERT_THRESHOLD) {
            co2AlertActive = true;
            Serial.printf("CO2 ALERT ON: %d ppm\n", co2);
        } else if (co2AlertActive && co2 < CO2_CLEAR_THRESHOLD) {
            co2AlertActive = false;
            Serial.printf("CO2 ALERT OFF: %d ppm\n", co2);
        }
        if (prevAlert != co2AlertActive) {
            updateCO2Led();
        }

        // Track initial readings
        if (sensorInitialPhase) {
            initialReadingCount++;
            if (initialReadingCount >= SENSOR_INITIAL_READINGS) {
                sensorInitialPhase = false;
                Serial.println("Initial sampling complete, switching to normal interval");
            }
        }

        singleShotInProgress = false;
        lastSensorRead = now;
        return true;  // New reading available
    }

    Serial.println("Read measurement failed");
    singleShotInProgress = false;
    lastSensorRead = now;
    return false;
}

void sensorLoop() {
    esp_task_wdt_reset();

    // Update sensor reading (non-blocking)
    if (updateSingleShotMeasurement()) {
        updateSensorDisplay();
    }

    // Ignore button during cooldown after mode change
    if (millis() - lastModeChange < MODE_CHANGE_COOLDOWN) return;

    // Handle button press
    if (digitalRead(BOOT_PIN) == LOW) {
        delay(50);
        if (digitalRead(BOOT_PIN) == LOW) {
            // Check for long hold
            if (checkButtonHold()) {
                enterDeepSleep();
                return;
            }
            // Wait for release, then switch to video mode
            while (digitalRead(BOOT_PIN) == LOW) delay(10);
            enterVideoMode();
        }
    }
}

// ============================================================================
// CO2 monitoring (LED alerts only)
// ============================================================================

// Update RGB LED based on CO2 alert state
void updateCO2Led() {
    if (co2AlertActive) {
        rgbLed.setPixelColor(0, rgbLed.Color(255, 0, 0));  // Red alert
    } else {
        rgbLed.setPixelColor(0, rgbLed.Color(0, 0, 0));    // Off
    }
    rgbLed.show();
}

// Check CO2 during video playback using single-shot (non-blocking state machine)
void checkVideoCO2() {
    if (!sensorReady) return;

    unsigned long now = millis();

    if (!singleShotInProgress) {
        // Check if it's time for a new measurement
        if (now - lastVideoCO2Check >= VIDEO_CO2_CHECK_INTERVAL) {
            if (scd4x.measureSingleShot() == 0) {
                singleShotInProgress = true;
                singleShotStartTime = now;
                Serial.println("Video CO2 check started...");
            }
            lastVideoCO2Check = now;
        }
        return;
    }

    // Waiting for measurement (~5 seconds)
    if (now - singleShotStartTime < 5000) return;

    // Check if data ready
    bool dataReady = false;
    if (scd4x.getDataReadyStatus(dataReady) != 0 || !dataReady) {
        if (now - singleShotStartTime > 6000) {
            Serial.println("Video CO2 check timeout");
            singleShotInProgress = false;
        }
        return;
    }

    // Read measurement
    uint16_t co2;
    float temp, hum;
    if (scd4x.readMeasurement(co2, temp, hum) == 0 && co2 > 0) {
        sensorCO2 = co2;
        sensorTemperature = temp;
        sensorHumidity = hum;

        Serial.printf("Video CO2: %d ppm\n", co2);

        // Update alert with hysteresis
        bool prevAlert = co2AlertActive;
        if (!co2AlertActive && co2 >= CO2_ALERT_THRESHOLD) {
            co2AlertActive = true;
            Serial.printf("CO2 ALERT ON: %d ppm\n", co2);
        } else if (co2AlertActive && co2 < CO2_CLEAR_THRESHOLD) {
            co2AlertActive = false;
            Serial.printf("CO2 ALERT OFF: %d ppm\n", co2);
        }

        if (prevAlert != co2AlertActive) {
            updateCO2Led();
        }
    }

    singleShotInProgress = false;
}

// ============================================================================
// Video playback
// ============================================================================
void loadFileList() {
    File dir = SD_MMC.open(MJPEG_FOLDER);
    if (!dir) {
        tft.setTextColor(TFT_RED); tft.setTextSize(2);
        tft.setCursor(20, 140); tft.print("No /mjpeg folder!");
        while (1) delay(1000);
    }
    mjpegFileList.clear();
    while (File f = dir.openNextFile()) {
        String name = f.name();
        if (!f.isDirectory() && name.endsWith(".mjpeg")) {
            mjpegFileList.push_back(name);
        }
        f.close();
    }
    dir.close();
    mjpegCount = mjpegFileList.size();
    Serial.printf("Found %d videos\n", mjpegCount);
}

void playVideo(int idx) {
    String path = String(MJPEG_FOLDER) + "/" + mjpegFileList[idx];
    int fps = parseFps(mjpegFileList[idx]);
    unsigned long frameMicros = 1000000UL / fps;  // Use microseconds for precision

    Serial.printf("Play: %s @ %d fps (%lu us/frame)\n", path.c_str(), fps, frameMicros);

    mjpegFile = SD_MMC.open(path.c_str(), "r");
    if (!mjpegFile) return;

    readBufPos = readBufLen = 0;
    tft.fillScreen(TFT_BLACK);
    start_ms = millis();
    total_frames = 0;

    unsigned long nextFrameTime = micros();
    unsigned long skippedFrames = 0;

    while (!skipRequested) {
        unsigned long now = micros();

        // Read next frame
        int size = readJpegFrame(mjpegBuf, MJPEG_BUF_SIZE);
        if (size == 0) break;

        // Frame skip logic: if we're behind by more than 1 frame, skip display
        if (now > nextFrameTime + frameMicros) {
            // We're behind - skip this frame's display, just advance timing
            skippedFrames++;
            nextFrameTime += frameMicros;
            continue;
        }

        // Decode and display frame
        TJpgDec.drawJpg(0, 0, mjpegBuf, size);
        total_frames++;

        // Feed watchdog after each successful frame
        esp_task_wdt_reset();

        // Precise frame pacing using microseconds
        nextFrameTime += frameMicros;
        now = micros();
        if (nextFrameTime > now) {
            delayMicroseconds(nextFrameTime - now);
        }

        // Check for button press (non-blocking check only)
        if (digitalRead(BOOT_PIN) == LOW) {
            // Button is pressed - check if it's a long hold
            unsigned long holdStart = millis();
            while (digitalRead(BOOT_PIN) == LOW) {
                if (millis() - holdStart >= BOOT_BUTTON_HOLD_TIME) {
                    mjpegFile.close();
                    Serial.printf("Done: %lu frames displayed, %lu skipped, %.1f effective fps\n",
                                  total_frames, skippedFrames,
                                  1000.0 * total_frames / (millis() - start_ms));
                    enterSensorMode();
                    updateSensorDisplay();
                    return;
                }
                delay(10);
            }
            // Short press - skip to next video
            skipRequested = true;
        }
    }

    skipRequested = false;
    lastPress = millis();

    Serial.printf("Done: %lu frames displayed, %lu skipped, %.1f effective fps\n",
                  total_frames, skippedFrames,
                  1000.0 * total_frames / (millis() - start_ms));
    mjpegFile.close();
}

// ============================================================================
// Setup
// ============================================================================
void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n=== ESP32-S3 Video Player (Low Power) ===");

    // Check wake-up reason and release GPIO holds from previous sleep
    esp_sleep_wakeup_cause_t wakeup_reason = esp_sleep_get_wakeup_cause();
    gpio_hold_dis(GPIO_NUM_45);  // Backlight
    gpio_hold_dis(GPIO_NUM_1);   // Audio enable

    if (wakeup_reason == ESP_SLEEP_WAKEUP_EXT0) {
        Serial.println("Woke from deep sleep (button)");
    }

    // Check PSRAM
    if (psramFound()) {
        Serial.printf("PSRAM: %d bytes\n", ESP.getPsramSize());
    } else {
        Serial.println("Warning: No PSRAM found!");
    }

    pinMode(LCD_BL, OUTPUT);
    digitalWrite(LCD_BL, HIGH);

    // Display
    tft.init();
    tft.setRotation(0);
    tft.setSwapBytes(true);
    tft.fillScreen(TFT_BLACK);
    Serial.printf("Display: %dx%d\n", tft.width(), tft.height());

    // TJpg_Decoder setup
    TJpgDec.setJpgScale(1);
    TJpgDec.setCallback(tftOutput);

    // RGB LED setup
    rgbLed.begin();
    rgbLed.setBrightness(50);  // Not too bright
    rgbLed.clear();
    rgbLed.show();

    // Battery ADC setup
    pinMode(BATTERY_PIN, INPUT);
    analogReadResolution(12);

    // Allocate buffers in PSRAM
    mjpegBuf = (uint8_t *)ps_malloc(MJPEG_BUF_SIZE);
    readBuf = (uint8_t *)ps_malloc(READ_BUF_SIZE);
    if (!mjpegBuf || !readBuf) {
        // Fallback to regular RAM
        Serial.println("PSRAM alloc failed, using heap");
        if (!mjpegBuf) mjpegBuf = (uint8_t *)malloc(MJPEG_BUF_SIZE);
        if (!readBuf) readBuf = (uint8_t *)malloc(READ_BUF_SIZE);
    }
    if (!mjpegBuf || !readBuf) {
        tft.setTextColor(TFT_RED);
        tft.setCursor(20, 140);
        tft.print("Memory error!");
        while (1) delay(1000);
    }

    // SD Card - SDIO 4-bit mode at 80MHz
    SD_MMC.setPins(SD_CLK, SD_CMD, SD_D0, SD_D1, SD_D2, SD_D3);
    if (!SD_MMC.begin("/sdcard", true, false, 80000)) {  // 80MHz SDIO
        if (!SD_MMC.begin("/sdcard", false)) {
            tft.setTextColor(TFT_RED);
            tft.setCursor(20, 140);
            tft.print("SD Error!");
            while (1) delay(1000);
        }
    }
    Serial.printf("SD: %lluMB\n", SD_MMC.cardSize() / (1024 * 1024));

    initSensor();
    loadFileList();

    pinMode(BOOT_PIN, INPUT);
    attachInterrupt(digitalPinToInterrupt(BOOT_PIN), onButtonPress, FALLING);

    // Task watchdog: auto-reset if SD card or other operation hangs for 10s
    esp_task_wdt_config_t wdt_config = {
        .timeout_ms = 10000,
        .idle_core_mask = 0,
        .trigger_panic = true
    };
    esp_task_wdt_reconfigure(&wdt_config);
    esp_task_wdt_add(NULL);  // Add current task (loopTask)

    Serial.println("Ready!");
}

// ============================================================================
// Loop
// ============================================================================
void loop() {
    if (currentMode == VIDEO_MODE) {
        if (mjpegCount > 0) {
            // Check CO2 between videos (not during playback for smooth frames)
            checkVideoCO2();

            playVideo(currentMjpegIndex);
            currentMjpegIndex = (currentMjpegIndex + 1) % mjpegCount;

            // Also check after video ends if measurement was in progress
            if (singleShotInProgress) {
                checkVideoCO2();
            }
        } else {
            tft.fillScreen(TFT_BLACK);
            tft.setTextColor(TFT_YELLOW);
            tft.setCursor(20, 140);
            tft.print("No videos");
            delay(2000);
            enterSensorMode();
            updateSensorDisplay();
        }
    } else {
        sensorLoop();
    }
}
