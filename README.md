# K-Pop Digital Photocard

A handheld device that plays K-pop YouTube Shorts as looping video "photocards" on a small display, powered by an ESP32-S3 with a 2.8" IPS screen.

<p align="center">
  <img src="docs/images/photocard.JPG" alt="Digital photocard playing video" width="30%">
  <img src="docs/images/back.JPG" alt="Back of 3D-printed case" width="30%">
  <img src="docs/images/co2.JPG" alt="CO2 sensor mode" width="30%">
</p>

## Project Structure

```
kpop-digital-photocard/
├── firmware/          ESP32-S3 video player firmware (Arduino)
├── collection-app/    Streamlit app to browse, download & convert YouTube Shorts
├── case/              3D-printable enclosure (STL files)
└── docs/              Wiring diagrams, photos, BOM
```

## Hardware

### Parts List

| Part | Notes |
|------|-------|
| [ESP32-S3 2.8" IPS Display (Hosyond)](https://amzn.to/4brwvC6) | ESP32-S3 with 320x240 ILI9341, SD card slot, PSRAM. Cheaper options available on AliExpress/Alibaba |
| MicroSD card | Any size works, FAT32 formatted |
| [Lipo Battery 1000mAh](https://amzn.to/40Pq1Xz) | JST connector, 3.7V |
| M3x12mm screws | For case assembly |
| [M3 Threaded inserts (M3xH4)](https://amzn.to/4lifAp9) | Heat-set with soldering iron into the 3D-printed case |

### 3D-Printed Case

STL files are in the `case/` folder:
- `front.stl` — Front shell with display cutout
- `back.stl` — Back cover
- `button.stl` — Boot button cap

Install the M3 threaded inserts into the case using a soldering iron, then secure with M3x12mm screws.

## Getting Started

### 1. Set Up the Collection App

The collection app is a Streamlit web app that lets you browse YouTube Shorts, download them, and convert to MJPEG format for the device.

**Prerequisites:**
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- FFmpeg

```bash
cd collection-app

# Install dependencies
uv sync

# Install FFmpeg if you haven't already
# macOS
brew install ffmpeg
# Ubuntu/Debian
sudo apt install ffmpeg

# Run the app
uv run streamlit run app.py
```

The app opens in your browser at `http://localhost:8501`.

### 2. Add Channels & Fetch Videos

1. In the sidebar, enter a YouTube channel URL, @handle, or channel ID
2. Click **Fetch All** or **Fetch New Videos** to pull the latest Shorts
3. Thumbnails and metadata are cached locally in `data/shorts.db`

### 3. Select & Download Videos

1. Browse the video grid and check the ones you want
2. Use bulk select to grab multiple videos at once
3. New videos (not previously seen) are highlighted

### 4. Convert to MJPEG

1. Adjust conversion settings in the sidebar:

   | Parameter | Default | Description |
   |-----------|---------|-------------|
   | Width | 240 | Output video width in pixels |
   | Height | 320 | Output video height in pixels |
   | Quality | 5 | MJPEG quality (2-31, lower = better) |
   | FPS | 15 | Frame rate |
   | Brightness | 0.05 | Brightness adjustment (-0.5 to 0.5) |
   | Contrast | 1.1 | Contrast adjustment (0.5 to 2.0) |
   | Aspect Mode | fit | How to handle aspect ratio (fit/fill/stretch) |

2. Presets are available for **CYD 2.8"** (240x320) and **CYD 4"** (320x480)
3. Click **Download & Convert** to process all selected videos

### 5. Prepare the SD Card

1. Format a microSD card as **FAT32**
2. Create a folder called `mjpeg` at the root of the SD card
3. Click **Export** in the app to copy converted `.mjpeg` files to a target folder, or manually copy from `collection-app/output/` to the SD card's `/mjpeg/` folder
4. The firmware reads FPS from the filename (e.g. `video_15fps.mjpeg`), otherwise defaults to 15 FPS

### 6. Flash the Firmware

The video player firmware is based on [esp32-2432S028_video_player](https://github.com/thelastoutpostworkshop/esp32-2432S028_video_player) by The Last Outpost Workshop, adapted for the ESP32-S3.

1. Install [Arduino IDE](https://www.arduino.cc/en/software)
2. Add ESP32 board support: in **Settings > Additional Board Manager URLs**, add:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
3. Install **esp32** board package from Board Manager
4. Install required libraries via Library Manager:
   - **TFT_eSPI**
   - **TJpg_Decoder**
5. Copy `firmware/User_Setup.h` to your TFT_eSPI library folder (replacing the default), or update the pin definitions to match
6. Open `firmware/esp32s3_video_player.ino` in Arduino IDE
7. Select board: **ESP32S3 Dev Module**
8. Board settings:
   - Flash Size: **16MB**
   - PSRAM: **OPI PSRAM**
   - USB CDC On Boot: **Enabled** (for serial monitor)
   - Partition Scheme: **Huge APP**
9. Connect the board via USB and click **Upload**

### 7. Usage

- Insert the SD card and power on the device
- Videos in `/mjpeg/` loop automatically
- **Short press** the boot button to skip to the next video
- **Long press** (1.5s) the boot button to enter deep sleep
- **Press** the boot button again to wake from sleep

## License

MIT
