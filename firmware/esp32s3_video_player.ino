// ESP32-S3 2.8" Display Video Player (ES3C28P / ES3N28P)
// JPEGDEC (ESP32-S3 SIMD) decodes on core 0 into a PSRAM framebuffer; core 1
// pushes whole frames to the panel, locked to its scanline so nothing tears.
// Short press: next video | Long press: deep sleep

#include <FS.h>
#include <SD_MMC.h>
#include <vector>
#include <TFT_eSPI.h>
#include <JPEGDEC.h>
#include <SPI.h>
#include <esp_sleep.h>
#include <driver/gpio.h>
#include <esp_task_wdt.h>
#include <esp_heap_caps.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>

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

// Display / vsync
#define SCREEN_W                  240
#define SCREEN_H                  320
#define TFT_CS_PIN                10
#define TFT_DC_PIN                46
// The panel exposes its current scanline over SPI (0x45). A full-frame push
// takes ~36 ms at 40 MHz, slower than one panel refresh, so we slow the panel
// down (FRMCTR1) until a push fits inside two refreshes, then start each push
// just behind the beam: the beam stays ahead for the whole push and only laps
// the writer after it has finished. Frame period = a whole number of
// refreshes, so pacing is exact as well as tear-free.
#define PANEL_TOTAL_LINES         344    // Measured: scanline counts 0..343
#define VSYNC_LINE_MIN            28     // Start pushing once the beam is here...
#define VSYNC_LINE_MAX            64     // ...and no later than here
#define PANEL_RTNA_MIN            0x16   // ~47 Hz: fastest refresh a push still fits in
#define PANEL_RTNA_MAX            0x1A   // ~40 Hz: slowest we go (flicker limit)
#define PANEL_RTNA_CAL            0x16   // Setting used to calibrate the panel clock

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
uint16_t *frameBuf[2] = { nullptr, nullptr };  // Decoded frames, RGB565 big-endian

unsigned long total_frames, start_ms;

// Decoder task (core 0) <-> player (core 1)
JPEGDEC jpeg;
TaskHandle_t decoderTaskHandle = nullptr;
QueueHandle_t freeQueue = nullptr;    // Framebuffer indices the decoder may fill
QueueHandle_t readyQueue = nullptr;   // Decoded framebuffer indices (-1 = end of file)
SemaphoreHandle_t decoderDone = nullptr;
volatile bool decoderStop = false;
volatile uint32_t decFrameUs = 0;     // Source frame period
volatile uint32_t decSlotUs = 0;      // Period we can actually show frames at
volatile uint32_t decSkipped = 0, decBad = 0;
int decOffX = 0, decOffY = 0;

// Panel vsync
bool vsyncAvailable = false;
uint32_t usPerRtna = 968;             // Panel refresh period per RTNA step (calibrated at boot)
uint32_t panelPeriodUs = 0;

volatile bool skipRequested = false;

// Latch a button press. The button is polled (every few ms during playback)
// rather than using a GPIO interrupt: attachInterrupt() runs its setup on the
// core's 1 KB IPC stack, which intermittently overflowed and crashed at boot.
inline void sampleButton() {
    if (digitalRead(BOOT_PIN) == LOW) skipRequested = true;
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
        if (state == 1 && b == 0xD9) return pos;
        state = (b == 0xFF) ? 1 : 0;
    }
    return 0;
}

// ============================================================================
// Panel vsync
// ============================================================================
// Current panel scanline (0..PANEL_TOTAL_LINES-1). Reply to 0x45 is one dummy
// byte followed by the line number, offset by one dummy clock.
int readScanline() {
    SPIClass &spi = tft.getSPIinstance();
    spi.beginTransaction(SPISettings(8000000, MSBFIRST, SPI_MODE0));
    digitalWrite(TFT_CS_PIN, LOW);
    digitalWrite(TFT_DC_PIN, LOW);
    spi.transfer(0x45);
    digitalWrite(TFT_DC_PIN, HIGH);
    spi.transfer(0);
    uint8_t b1 = spi.transfer(0);
    uint8_t b2 = spi.transfer(0);
    digitalWrite(TFT_CS_PIN, HIGH);
    spi.endTransaction();
    return (b1 << 1) | (b2 >> 7);
}

void setPanelRefresh(uint8_t rtna) {
    tft.writecommand(0xB1);  // FRMCTR1
    tft.writedata(0x01);     // DIVA: fosc / 2
    tft.writedata(rtna);
    panelPeriodUs = rtna * usPerRtna;
}

// Time between scanline wrap-arounds, or 0 if the panel doesn't report one
uint32_t measurePanelPeriod() {
    uint32_t t0 = micros(), firstWrap = 0, lastWrap = 0;
    int wraps = 0, prev = readScanline();
    while (micros() - t0 < 200000 && wraps < 6) {
        int v = readScanline();
        if (prev - v > PANEL_TOTAL_LINES / 2) {
            lastWrap = micros();
            if (!wraps) firstWrap = lastWrap;
            wraps++;
        }
        prev = v;
    }
    return wraps >= 3 ? (lastWrap - firstWrap) / (wraps - 1) : 0;
}

void initVsync() {
    pinMode(TFT_CS_PIN, OUTPUT);
    pinMode(TFT_DC_PIN, OUTPUT);
    tft.writecommand(0x35);  // TEON - the scanline register only counts with this on
    tft.writedata(0x00);
    setPanelRefresh(PANEL_RTNA_CAL);
    delay(60);
    uint32_t period = measurePanelPeriod();
    if (period > 10000 && period < 40000) {
        vsyncAvailable = true;
        usPerRtna = period / PANEL_RTNA_CAL;
        panelPeriodUs = period;
        Serial.printf("Vsync: scanline readback OK, %lu us/refresh at RTNA 0x%02X\n",
                      (unsigned long)period, PANEL_RTNA_CAL);
    } else {
        // No usable scanline - back to the library default, pace by timer only
        vsyncAvailable = false;
        tft.writecommand(0xB1);
        tft.writedata(0x00);
        tft.writedata(0x13);
        Serial.println("Vsync: scanline readback not available, unsynced pushes");
    }
}

// Pick the panel refresh so that a whole number of refreshes (>= 2, a push
// spans more than one) is as close as possible to the video's frame period
void chooseTiming(uint32_t frameUs, uint8_t &rtna, int &refreshes) {
    uint32_t bestErr = UINT32_MAX;
    for (uint8_t r = PANEL_RTNA_MIN; r <= PANEL_RTNA_MAX; r++) {
        uint32_t period = r * usPerRtna;
        int k = (frameUs + period / 2) / period;
        if (k < 2) k = 2;
        uint32_t slot = k * period;
        uint32_t err = slot > frameUs ? slot - frameUs : frameUs - slot;
        if (err < bestErr) { bestErr = err; rtna = r; refreshes = k; }
    }
}

// Block until the beam is just past the top of the panel. Returns false if we
// gave up waiting (should not happen once vsync has been detected).
bool waitForVsync() {
    uint32_t t0 = micros();
    uint32_t lineUs = panelPeriodUs / PANEL_TOTAL_LINES;
    for (;;) {
        int v = readScanline();
        if (v >= VSYNC_LINE_MIN && v < VSYNC_LINE_MAX) return true;
        if (micros() - t0 > 80000) return false;
        sampleButton();
        int linesToGo = v < VSYNC_LINE_MIN ? VSYNC_LINE_MIN - v
                                           : PANEL_TOTAL_LINES - v + VSYNC_LINE_MIN;
        uint32_t us = linesToGo * lineUs;
        if (us > 2500) delay((us - 1500) / 1000);  // Sleep, don't spin
    }
}

void pushFrame(uint16_t *fb) {
    tft.startWrite();
    tft.setAddrWindow(0, 0, SCREEN_W, SCREEN_H);
    tft.pushPixels(fb, SCREEN_W * SCREEN_H);
    tft.endWrite();
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

// JPEGDEC draw callback - only used for frames that aren't exactly screen
// sized: copies each block into the framebuffer, centred and clipped
int drawToFramebuffer(JPEGDRAW *d) {
    uint16_t *fb = (uint16_t *)d->pUser;
    for (int row = 0; row < d->iHeight; row++) {
        int y = d->y + row + decOffY;
        if (y < 0 || y >= SCREEN_H) continue;
        int x = d->x + decOffX, w = d->iWidthUsed, srcX = 0;
        if (x < 0) { srcX = -x; w += x; x = 0; }
        if (x + w > SCREEN_W) w = SCREEN_W - x;
        if (w > 0) memcpy(&fb[y * SCREEN_W + x], &d->pPixels[row * d->iWidth + srcX], w * 2);
    }
    return 1;
}

bool decodeFrame(int size, uint16_t *fb) {
    if (!jpeg.openRAM(mjpegBuf, size, drawToFramebuffer)) return false;
    jpeg.setPixelType(RGB565_BIG_ENDIAN);  // Panel byte order: push without swapping
    int w = jpeg.getWidth(), h = jpeg.getHeight();
    if (w == SCREEN_W && h == SCREEN_H) {
        jpeg.setFramebuffer(fb);  // Decode straight into the framebuffer (fast path)
    } else {
        memset(fb, 0, SCREEN_W * SCREEN_H * 2);
        decOffX = (SCREEN_W - w) / 2;
        decOffY = (SCREEN_H - h) / 2;
        jpeg.setUserPointer(fb);
    }
    bool ok = jpeg.decode(0, 0, 0);
    jpeg.close();
    return ok;
}

// Core 0: read + decode frames ahead of the display. Sleeps until a video is
// started, then fills whichever framebuffer the player has handed back.
void decoderTask(void *) {
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

        // When the panel can't show frames as fast as the file wants (source
        // fps above ~23), drop frames evenly so the video still runs in real time
        bool compensate = decSlotUs > decFrameUs + decFrameUs / 20;
        int64_t behindUs = 0;
        bool eof = false;

        while (!decoderStop && !eof) {
            int idx;
            if (xQueueReceive(freeQueue, &idx, pdMS_TO_TICKS(10)) != pdTRUE) continue;

            bool decoded = false;
            while (!decoderStop && !decoded) {
                int size = readJpegFrame(mjpegBuf, MJPEG_BUF_SIZE);
                if (size == 0) { eof = true; break; }
                if (compensate && behindUs >= (int64_t)decFrameUs) {
                    behindUs -= decFrameUs;
                    decSkipped++;
                    continue;
                }
                if (decodeFrame(size, frameBuf[idx])) {
                    decoded = true;
                    if (compensate) behindUs += decSlotUs - decFrameUs;
                } else {
                    decBad++;
                }
            }

            if (decoded) {
                xQueueSend(readyQueue, &idx, portMAX_DELAY);
            } else if (eof) {
                int end = -1;
                xQueueSend(readyQueue, &end, portMAX_DELAY);
            }
        }
        xSemaphoreGive(decoderDone);
    }
}

void startDecoder(uint32_t frameUs, uint32_t slotUs) {
    xQueueReset(freeQueue);
    xQueueReset(readyQueue);
    for (int i = 0; i < 2; i++) xQueueSend(freeQueue, &i, 0);
    decFrameUs = frameUs;
    decSlotUs = slotUs;
    decSkipped = decBad = 0;
    decoderStop = false;
    xTaskNotifyGive(decoderTaskHandle);
}

// Stop the decoder and wait until it has let go of the file and buffers
void stopDecoder() {
    decoderStop = true;
    xSemaphoreTake(decoderDone, portMAX_DELAY);
}

// Button handling during playback. Returns 0 = nothing, 1 = short press
// (next video), 2 = long hold (deep sleep).
int pollVideoButton() {
    sampleButton();
    if (!skipRequested) return 0;
    unsigned long holdStart = millis();
    while (digitalRead(BOOT_PIN) == LOW) {
        if (millis() - holdStart >= BOOT_BUTTON_HOLD_TIME) return 2;
        esp_task_wdt_reset();
        delay(10);
    }
    return 1;
}

void playVideo(int idx) {
    String path = String(MJPEG_FOLDER) + "/" + mjpegFileList[idx];
    int fps = parseFps(mjpegFileList[idx]);
    uint32_t frameUs = 1000000UL / fps;

    mjpegFile = SD_MMC.open(path.c_str(), "r");
    if (!mjpegFile) return;
    readBufPos = readBufLen = 0;

    // Frame period: with vsync, a whole number of panel refreshes; otherwise a timer
    uint32_t slotUs = frameUs;
    if (vsyncAvailable) {
        uint8_t rtna = PANEL_RTNA_MIN;
        int refreshes = 2;
        chooseTiming(frameUs, rtna, refreshes);
        setPanelRefresh(rtna);
        slotUs = refreshes * panelPeriodUs;
        Serial.printf("Play: %s @ %d fps -> panel %.1f Hz x%d = %.2f fps\n", path.c_str(), fps,
                      1e6 / panelPeriodUs, refreshes, 1e6 / slotUs);
    } else {
        Serial.printf("Play: %s @ %d fps (unsynced)\n", path.c_str(), fps);
    }

    startDecoder(frameUs, slotUs);
    start_ms = millis();
    total_frames = 0;

    uint32_t nextPush = micros();
    uint32_t pushUsTotal = 0, lateFrames = 0, vsyncMisses = 0;
    bool first = true;
    bool toSleep = false;

    for (;;) {
        // Wait for the decoder. The watchdog is only fed when a frame is shown,
        // so a hung SD card still ends in a reset rather than a frozen screen.
        int buf;
        bool got = xQueueReceive(readyQueue, &buf, pdMS_TO_TICKS(5)) == pdTRUE;

        if (got && buf < 0) break;  // End of file

        if (got) {
            // Sleep until this frame is due (to within half a refresh when the
            // exact moment is going to be picked by the scanline anyway)
            if (!first) {
                int32_t wait = (int32_t)(nextPush - micros());
                if (vsyncAvailable) wait -= panelPeriodUs / 2;
                while (wait > 1000) {  // In short naps, so the button is never missed
                    sampleButton();
                    delay(wait > 5000 ? 5 : wait / 1000);
                    wait = (int32_t)(nextPush - micros());
                    if (vsyncAvailable) wait -= panelPeriodUs / 2;
                }
                if (!vsyncAvailable) {
                    wait = (int32_t)(nextPush - micros());
                    if (wait > 0) delayMicroseconds(wait);
                }
            }
            if (vsyncAvailable && !waitForVsync()) vsyncMisses++;

            uint32_t t = micros();
            if (!first && (int32_t)(t - nextPush) > (int32_t)(slotUs / 2)) lateFrames++;
            pushFrame(frameBuf[buf]);
            pushUsTotal += micros() - t;

            // With vsync the next frame is timed from where this one really
            // started; without it, keep a fixed cadence unless we fell behind
            if (vsyncAvailable || first || (int32_t)(t - nextPush) > (int32_t)slotUs) nextPush = t + slotUs;
            else nextPush += slotUs;
            first = false;

            xQueueSend(freeQueue, &buf, 0);  // Hand the buffer back to the decoder
            total_frames++;
            esp_task_wdt_reset();
        }

        int button = pollVideoButton();
        if (button == 2) { toSleep = true; break; }
        if (button == 1) break;
    }

    stopDecoder();
    mjpegFile.close();
    skipRequested = false;

    unsigned long elapsed = millis() - start_ms;
    Serial.printf("Done: %lu frames in %lu ms = %.2f fps | push %.1f ms avg | dropped %lu, bad %lu, late %lu, vsync misses %lu\n",
                  total_frames, elapsed, elapsed ? 1000.0 * total_frames / elapsed : 0.0,
                  total_frames ? pushUsTotal / 1000.0 / total_frames : 0.0,
                  (unsigned long)decSkipped, (unsigned long)decBad,
                  (unsigned long)lateFrames, (unsigned long)vsyncMisses);

    if (toSleep) enterDeepSleep();  // Long press - go to sleep
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
    tft.fillScreen(TFT_BLACK);
    Serial.printf("Display: %dx%d\n", tft.width(), tft.height());
    initVsync();

    // Allocate buffers in PSRAM
    mjpegBuf = (uint8_t *)ps_malloc(MJPEG_BUF_SIZE);
    readBuf = (uint8_t *)ps_malloc(READ_BUF_SIZE);
    // Framebuffers MUST be 16-byte aligned: JPEGDEC's ESP32-S3 SIMD code rounds
    // the address down to a 16-byte boundary, which shifts the whole picture
    // sideways (and writes ahead of the buffer) if it isn't.
    for (int i = 0; i < 2; i++) {
        frameBuf[i] = (uint16_t *)heap_caps_aligned_alloc(16, SCREEN_W * SCREEN_H * 2, MALLOC_CAP_SPIRAM);
    }
    if (!mjpegBuf || !readBuf || !frameBuf[0] || !frameBuf[1]) {
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

    // Decoder runs on core 0; the Arduino loop (display + UI) stays on core 1
    freeQueue = xQueueCreate(3, sizeof(int));
    readyQueue = xQueueCreate(3, sizeof(int));
    decoderDone = xSemaphoreCreateBinary();
    xTaskCreatePinnedToCore(decoderTask, "mjpegDecode", 12288, nullptr, 2, &decoderTaskHandle, 0);

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
