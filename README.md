# K-Pop Digital Photocard

A handheld device that plays K-pop YouTube Shorts as looping video "photocards" on a small display, powered by an ESP32-S3 and a CYD (Cheap Yellow Display).

## Project Structure

```
kpop-digital-photocard/
├── firmware/          ESP32-S3 video player firmware (Arduino)
├── collection-app/    Streamlit app to browse, download & convert YouTube Shorts to MJPEG
├── case/              3D-printable enclosure (STL/STEP files)
└── docs/              Wiring diagrams, photos, BOM
```

## How It Works

1. **Browse & Convert** — Use the collection app to find YouTube Shorts from your favorite K-pop channels, then convert them to MJPEG at the right resolution.
2. **Load** — Copy the `.mjpeg` files to a microSD card.
3. **Play** — Insert the SD card into the device. It loops through videos automatically. Press the boot button to skip.

## Hardware

- ESP32-S3 CYD board (ES3C28P / ES3N28P) with 2.8" ILI9341 320x240 TFT
- MicroSD card
- 3D-printed case (see `case/`)

## Getting Started

### Collection App

```bash
cd collection-app
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Requires Python 3.10+, FFmpeg, and yt-dlp. See [`collection-app/README.md`](collection-app/README.md) for full details.

### Firmware

Open `firmware/esp32s3_video_player.ino` in Arduino IDE. See pin definitions and board config in the source files.

## License

MIT
