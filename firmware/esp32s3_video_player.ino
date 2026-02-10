// ESP32-S3 2.8" Display Video Player (ES3C28P / ES3N28P)
// Optimized for speed using PSRAM and JPEGDEC
// Short press: next video | Long press: deep sleep

#include <FS.h>
#include <SD_MMC.h>
#include <vector>
#include <TFT_eSPI.h>
#include <TJpg_Decoder.h>
#include <esp_sleep.h>
#include <driver/gpio.h>
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
#define BOOT_PIN    0

// Hardware pins
#define AUDIO_ENABLE_PIN  1  // Audio amp enable (LOW=enable, HIGH=disable)

// ============================================================================
// Configuration
// ============================================================================
#define BOOT_BUTTON_HOLD_TIME  1500
#define DEFAULT_FPS            15

// Use PSRAM for large buffers (ESP32-S3 has 8MB)
#define MJPEG_BUF_SIZE  (100 * 1024)  // 100KB for JPEG frame
#define READ_BUF_SIZE   (16 * 1024)   // 16KB read buffer

const char *MJPEG_FOLDER = "/mjpeg";

// ============================================================================
// Globals
// ============================================================================
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

volatile bool skipRequested = false;

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

    // Turn off display backlight
    digitalWrite(LCD_BL, LOW);

    // Put ILI9341 display in sleep mode
    tft.writecommand(0x10);  // Sleep in command
    delay(120);              // Required delay per datasheet

    // Disable audio amplifier (HIGH = disabled on this board)
    pinMode(AUDIO_ENABLE_PIN, OUTPUT);
    digitalWrite(AUDIO_ENABLE_PIN, HIGH);

    // Set unused expansion pins to input with no pull (reduce leakage)
    pinMode(2, INPUT);
    pinMode(3, INPUT);
    pinMode(14, INPUT);
    pinMode(21, INPUT);

    // Hold GPIO states during sleep
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
    unsigned long frameMicros = 1000000UL / fps;

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

        // Check for button press
        if (digitalRead(BOOT_PIN) == LOW) {
            unsigned long holdStart = millis();
            while (digitalRead(BOOT_PIN) == LOW) {
                if (millis() - holdStart >= BOOT_BUTTON_HOLD_TIME) {
                    // Long press - go to sleep
                    mjpegFile.close();
                    Serial.printf("Done: %lu frames, %lu skipped, %.1f fps\n",
                                  total_frames, skippedFrames,
                                  1000.0 * total_frames / (millis() - start_ms));
                    enterDeepSleep();
                    return;
                }
                delay(10);
            }
            // Short press - skip to next video
            skipRequested = true;
        }
    }

    skipRequested = false;

    Serial.printf("Done: %lu frames, %lu skipped, %.1f fps\n",
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
    Serial.println("\n=== ESP32-S3 Video Player ===");

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

    // Allocate buffers in PSRAM
    mjpegBuf = (uint8_t *)ps_malloc(MJPEG_BUF_SIZE);
    readBuf = (uint8_t *)ps_malloc(READ_BUF_SIZE);
    if (!mjpegBuf || !readBuf) {
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
    if (!SD_MMC.begin("/sdcard", true, false, 80000)) {
        if (!SD_MMC.begin("/sdcard", false)) {
            tft.setTextColor(TFT_RED);
            tft.setCursor(20, 140);
            tft.print("SD Error!");
            while (1) delay(1000);
        }
    }
    Serial.printf("SD: %lluMB\n", SD_MMC.cardSize() / (1024 * 1024));

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
    esp_task_wdt_add(NULL);

    Serial.println("Ready!");
}

// ============================================================================
// Loop
// ============================================================================
void loop() {
    if (mjpegCount > 0) {
        playVideo(currentMjpegIndex);
        currentMjpegIndex = (currentMjpegIndex + 1) % mjpegCount;
    } else {
        tft.fillScreen(TFT_BLACK);
        tft.setTextColor(TFT_YELLOW);
        tft.setCursor(20, 140);
        tft.print("No videos");
        delay(2000);
    }
}
