# CYD Shorts Converter

Fetch YouTube Shorts from channels and convert them to MJPEG format optimized for the CYD (Cheap Yellow Display) ESP32 device.

## Features

- Add YouTube channels by URL, @handle, or channel ID
- Fetch and display Shorts with thumbnails
- Track new vs previously seen videos
- Select videos individually or in bulk
- Download and convert to MJPEG format
- Adjustable conversion parameters (resolution, quality, FPS, brightness, contrast)
- Export to SD card or target folder
- Remembers selections between sessions

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- FFmpeg

## Installation

1. Clone or download this repository

2. Install dependencies:
```bash
uv sync
```

3. Install FFmpeg:
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Windows
choco install ffmpeg
```

## Usage

Start the application:

```bash
uv run streamlit run app.py
```

The app will open in your browser at `http://localhost:8501`.

### Workflow

1. **Add Channels**: Enter a YouTube channel URL or @handle in the sidebar
2. **Fetch Videos**: Click "Fetch All" or "Fetch New Videos" to get Shorts
3. **Select Videos**: Check the videos you want to convert
4. **Adjust Settings**: Configure resolution, quality, and other parameters
5. **Convert**: Click "Download & Convert" to process selected videos
6. **Export**: Click "Export" to copy converted files to your target folder

### Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| Width | 240 | Output video width in pixels |
| Height | 320 | Output video height in pixels |
| Quality | 5 | MJPEG quality (2-31, lower = better) |
| FPS | 15 | Frame rate |
| Brightness | 0.05 | Brightness adjustment (-0.5 to 0.5) |
| Contrast | 1.1 | Contrast adjustment (0.5 to 2.0) |
| Aspect Mode | fit | How to handle aspect ratio (fit/fill/stretch) |

### Presets

- **CYD 2.8"**: 240x320, optimized for the 2.8" display
- **CYD 4"**: 320x480, optimized for the 4" display

## Project Structure

```
digital-photocard-collection/
├── app.py                  # Streamlit application
├── pyproject.toml          # Project config and dependencies
├── src/
│   ├── models/            # Data classes
│   ├── services/          # Business logic
│   ├── components/        # Streamlit UI components
│   └── utils/             # Utilities
├── data/
│   ├── shorts.db          # SQLite database
│   ├── thumbnails/        # Cached thumbnails
│   └── downloads/         # Temporary downloads
└── output/                # Converted MJPEG files
```

## CYD Device

The CYD (Cheap Yellow Display) is the ESP32-2432S028R board with:
- ESP32-WROOM-32 MCU
- 2.8" ILI9341 TFT display (240x320 pixels)
- SD card slot for video storage

Copy the exported `.mjpeg` files to an SD card and use with a compatible MJPEG player firmware.

## License

MIT
