/*******************************************************************************
 * Board Configuration Header
 *
 * Supports multiple ESP32 display boards:
 * - ESP32-2432S028 (CYD - Cheap Yellow Display)
 * - ES3C28P / ES3N28P (2.8" ESP32-S3 Display from LCDWiki)
 ******************************************************************************/
#ifndef _BOARD_CONFIG_H_
#define _BOARD_CONFIG_H_

// Uncomment ONE of the following board definitions:
// #define BOARD_CYD_2432S028      // Original Cheap Yellow Display (ESP32)
#define BOARD_ESP32S3_ES3C28P   // 2.8" ESP32-S3 Display (LCDWiki)

/*******************************************************************************
 * ESP32-2432S028 (CYD - Cheap Yellow Display)
 * Uses standard ESP32 with SPI SD card
 ******************************************************************************/
#if defined(BOARD_CYD_2432S028)

// Display pins (SPI)
#define LCD_CS      15
#define LCD_DC      2
#define LCD_SCK     14
#define LCD_MOSI    13
#define LCD_MISO    12
#define LCD_BL      21      // Backlight (some models use 27)

// SD Card pins (SPI - VSPI)
#define SD_CS       5
#define SD_MISO     19
#define SD_MOSI     23
#define SD_SCK      18
#define SD_USE_SPI  1       // Use SPI mode for SD card

// I2C pins (shared with SD - only use when SD not in use)
#define I2C_SDA     19
#define I2C_SCL     27
#define I2C_DEDICATED 0     // I2C shares pins with SD, need mode switching

// Touch screen (XPT2046 resistive - SPI)
#define TOUCH_CS    33
#define TOUCH_IRQ   36
#define TOUCH_TYPE  "XPT2046"

// Boot button
#define BOOT_PIN    0

// No audio on standard CYD
#define HAS_AUDIO   0

// No RGB LED on standard CYD
#define HAS_RGB_LED 0

// Board identification
#define BOARD_NAME  "ESP32-2432S028 (CYD)"

/*******************************************************************************
 * ES3C28P / ES3N28P - 2.8" ESP32-S3 Display (LCDWiki)
 * Uses ESP32-S3 with SDIO SD card and capacitive touch
 ******************************************************************************/
#elif defined(BOARD_ESP32S3_ES3C28P)

// Display pins (SPI)
#define LCD_CS      10
#define LCD_DC      46
#define LCD_SCK     12
#define LCD_MOSI    11
#define LCD_MISO    13
#define LCD_BL      45      // Backlight (HIGH = on, LOW = off)

// SD Card pins (SDIO 4-bit mode)
#define SD_CLK      38
#define SD_CMD      40
#define SD_D0       39
#define SD_D1       41
#define SD_D2       48
#define SD_D3       47
#define SD_USE_SPI  0       // Use SDIO mode (not SPI)

// I2C pins (shared with capacitive touch - can use simultaneously with SD!)
#define I2C_SDA     16
#define I2C_SCL     15
#define I2C_DEDICATED 1     // I2C is on dedicated pins, no conflict with SD

// Touch screen (FT6336 capacitive - I2C)
#define TOUCH_RST   18
#define TOUCH_IRQ   17
#define TOUCH_TYPE  "FT6336"
#define FT6336_ADDR 0x38    // I2C address

// Audio (I2S with ES8311 codec)
#define HAS_AUDIO   1
#define AUDIO_EN    1       // Enable pin (LOW = enable)
#define AUDIO_MCLK  4       // Master clock
#define AUDIO_BCLK  5       // Bit clock
#define AUDIO_DOUT  6       // Data out
#define AUDIO_WS    7       // Word select (LRCLK)
#define AUDIO_DIN   8       // Data in (mic)

// RGB LED (WS2812-style, single wire)
#define HAS_RGB_LED 1
#define RGB_LED_PIN 42

// Boot button
#define BOOT_PIN    0

// Battery voltage sensing
#define BATT_ADC    9

// Expansion pins (general purpose)
#define EXPAND_IO1  2
#define EXPAND_IO2  3
#define EXPAND_IO3  14
#define EXPAND_IO4  21

// UART0 (main serial)
#define UART_RX     43
#define UART_TX     44

// Board identification
#define BOARD_NAME  "ES3C28P (ESP32-S3 2.8\" Display)"

#else
#error "Please define a board type in board_config.h"
#endif

/*******************************************************************************
 * Common settings
 ******************************************************************************/

// Display settings
#define DISPLAY_WIDTH   240
#define DISPLAY_HEIGHT  320
#define DISPLAY_DRIVER  "ILI9341"

// SPI speeds
#define DISPLAY_SPI_SPEED   40000000L   // 40MHz for display
#define SD_SPI_SPEED        80000000L   // 80MHz for SD (SPI mode only)

// Button debounce
#define BOOT_BUTTON_DEBOUNCE_TIME   400     // ms for short press
#define BOOT_BUTTON_HOLD_TIME       1500    // ms for long press

// Video playback
#define DEFAULT_FPS         15
#define MAX_FILES           50
#define MJPEG_FOLDER        "/mjpeg"

#endif // _BOARD_CONFIG_H_
