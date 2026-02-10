// TFT_eSPI User_Setup.h for ES3C28P / ES3N28P
// 2.8" ESP32-S3 IPS Display (LCDWiki)
// https://www.lcdwiki.com/2.8inch_ESP32-S3_Display

#define USER_SETUP_INFO "ES3C28P_ESP32S3_ILI9341"

// ##################################################################################
// Driver
// ##################################################################################
#define ILI9341_DRIVER

// ##################################################################################
// ESP32-S3 Pin Definitions for ES3C28P
// ##################################################################################

#define TFT_MISO  13
#define TFT_MOSI  11
#define TFT_SCLK  12
#define TFT_CS    10
#define TFT_DC    46
#define TFT_RST   -1  // Connected to ESP32-S3 EN/RST

// Backlight control (optional - controlled in sketch)
// #define TFT_BL    45
// #define TFT_BACKLIGHT_ON HIGH

// ##################################################################################
// Display Settings
// ##################################################################################

#define TFT_WIDTH  240
#define TFT_HEIGHT 320

// Color order - try BGR if colors look wrong
#define TFT_RGB_ORDER TFT_BGR

// Inversion - enable for IPS panel
#define TFT_INVERSION_ON

// ##################################################################################
// SPI Settings
// ##################################################################################

// Use FSPI port (default for ESP32-S3)
#define USE_FSPI_PORT

// SPI Frequency - 55MHz is a good balance of speed and stability
#define SPI_FREQUENCY       55000000  // 55 MHz (80MHz can cause noise on some boards)
#define SPI_READ_FREQUENCY  16000000  // 16 MHz for reads

// ##################################################################################
// Fonts
// ##################################################################################

#define LOAD_GLCD
#define LOAD_FONT2
#define LOAD_FONT4
#define LOAD_FONT6
#define LOAD_FONT7
#define LOAD_FONT8
#define LOAD_GFXFF
#define SMOOTH_FONT

// ##################################################################################
// Touch (FT6336 - I2C, not SPI - handled separately)
// ##################################################################################
// Touch is on I2C, not controlled by TFT_eSPI
// #define TOUCH_CS -1
