# YouTube Shorts MJPEG Converter for CYD

## Overview

Build a Python desktop application that fetches YouTube Shorts from specified channels, provides a UI for video selection, and converts selected videos to MJPEG format optimized for the CYD (Cheap Yellow Display) ESP32 device with a 240x320 TFT screen.

## Problem Statement / Motivation

The CYD (Cheap Yellow Display - ESP32-2432S028R) is a popular ~$15 ESP32 board with a 2.8" TFT display (240x320 pixels). To display video content, videos must be converted to MJPEG format with specific parameters. Currently, this requires:

1. Manually finding and copying YouTube Shorts URLs
2. Running command-line tools to download and convert
3. Manually tracking which videos have been processed
4. Re-downloading everything when new content is available

This application automates the workflow with a visual interface for browsing, selecting, and converting Shorts for CYD playback.

## Proposed Solution

A **Python desktop application** using:
- **CustomTkinter** for native desktop UI (based on "not web-based preferred" requirement)
- **SQLite** for data persistence and state tracking
- **yt-dlp** for video downloading (bypasses API quota issues)
- **FFmpeg** for MJPEG conversion
- **YouTube Data API v3** (optional) for enhanced metadata

### Architecture Decision: Desktop vs Web

| Approach | Pros | Cons |
|----------|------|------|
| **Web (Streamlit)** | Rapid development, easy thumbnails/grids, video preview, cross-platform | Requires browser |
| **Desktop (CustomTkinter)** | Native feel, no browser needed | Complex image grids, more boilerplate |

**Recommendation: Streamlit** - For an application focused on browsing and selecting videos with thumbnails, web UI is natural and less clunky. Streamlit runs locally (`localhost:8501`) and provides an excellent developer experience with minimal code.

## Technical Approach

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    CYD Shorts Converter                         │
├─────────────────────────────────────────────────────────────────┤
│  UI Layer (Streamlit @ localhost:8501)                          │
│  ├── Sidebar: Channel Manager + Settings                        │
│  ├── Main: Video Grid with thumbnails and checkboxes            │
│  ├── Progress bars for download/conversion                      │
│  └── Session state for selections                               │
├─────────────────────────────────────────────────────────────────┤
│  Service Layer                                                  │
│  ├── YouTubeService (fetch channel videos via yt-dlp)           │
│  ├── DownloadService (download with progress)                   │
│  ├── ConversionService (FFmpeg MJPEG encoding)                  │
│  └── ExportService (copy to target folder)                      │
├─────────────────────────────────────────────────────────────────┤
│  Data Layer (SQLite)                                            │
│  ├── channels (id, name, url, last_fetched)                     │
│  ├── videos (id, channel_id, title, duration, is_short, ...)    │
│  ├── video_state (video_id, selected, downloaded, converted)    │
│  └── settings (key, value)                                      │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
User adds channel URL
        │
        ▼
yt-dlp extracts video list (no API key needed)
        │
        ▼
Filter for Shorts (duration ≤ 60s, vertical aspect ratio)
        │
        ▼
Store metadata in SQLite, mark as "new" if not exists
        │
        ▼
UI displays videos with thumbnails
        │
        ▼
User selects/deselects videos
        │
        ▼
User clicks "Convert" → Download selected → Convert to MJPEG
        │
        ▼
User clicks "Export" → Copy MJPEG files to target folder
```

### Database Schema

```sql
-- schema.sql

CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,           -- YouTube channel ID (UCxxxxx)
    name TEXT NOT NULL,            -- Channel display name
    url TEXT NOT NULL,             -- Original URL provided by user
    last_fetched TIMESTAMP,        -- Last time videos were fetched
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,           -- YouTube video ID
    channel_id TEXT NOT NULL,      -- References channels.id
    title TEXT NOT NULL,
    description TEXT,
    thumbnail_url TEXT,
    duration INTEGER NOT NULL,     -- Duration in seconds
    published_at TIMESTAMP,
    width INTEGER,                 -- Original video width
    height INTEGER,                -- Original video height
    is_short BOOLEAN DEFAULT 0,   -- Detected as Short
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (channel_id) REFERENCES channels(id)
);

CREATE TABLE IF NOT EXISTS video_state (
    video_id TEXT PRIMARY KEY,
    is_new BOOLEAN DEFAULT 1,      -- First time seen
    is_selected BOOLEAN DEFAULT 0, -- User selected for conversion
    is_downloaded BOOLEAN DEFAULT 0,
    is_converted BOOLEAN DEFAULT 0,
    is_exported BOOLEAN DEFAULT 0,
    download_path TEXT,            -- Path to downloaded source
    converted_path TEXT,           -- Path to MJPEG file
    conversion_settings TEXT,      -- JSON of settings used
    seen_at TIMESTAMP,             -- When user first saw this
    downloaded_at TIMESTAMP,
    converted_at TIMESTAMP,
    exported_at TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_videos_is_short ON videos(is_short);
CREATE INDEX IF NOT EXISTS idx_state_is_new ON video_state(is_new);
CREATE INDEX IF NOT EXISTS idx_state_is_selected ON video_state(is_selected);
```

### Key Implementation Details

#### Shorts Detection (via yt-dlp)

```python
# services/youtube_service.py

def is_youtube_short(video_info: dict) -> bool:
    """Determine if a video is a YouTube Short."""
    duration = video_info.get('duration', 0)
    width = video_info.get('width', 0)
    height = video_info.get('height', 0)

    # Shorts are ≤60 seconds and vertical (9:16 aspect ratio)
    is_short_duration = duration <= 60
    is_vertical = height > width if (width and height) else False

    # Also check for #shorts in title or description
    text = f"{video_info.get('title', '')} {video_info.get('description', '')}".lower()
    has_shorts_tag = '#shorts' in text or '#short' in text

    return is_short_duration and (is_vertical or has_shorts_tag)
```

#### MJPEG Conversion Settings

```python
# services/conversion_service.py

@dataclass
class ConversionConfig:
    width: int = 240              # CYD display width
    height: int = 320             # CYD display height
    quality: int = 5              # MJPEG quality (2-31, lower=better)
    fps: int = 15                 # Frame rate
    brightness: float = 0.05     # Slight boost for small display
    contrast: float = 1.1         # Slight boost for visibility
    aspect_mode: str = "fit"      # fit (letterbox), fill (crop), stretch

def build_ffmpeg_command(input_path: str, output_path: str,
                         config: ConversionConfig) -> list:
    """Build FFmpeg command for MJPEG conversion."""
    filters = []

    if config.aspect_mode == "fit":
        # Letterbox: maintain aspect ratio, add black bars
        filters.append(
            f"scale={config.width}:{config.height}:"
            f"force_original_aspect_ratio=decrease"
        )
        filters.append(
            f"pad={config.width}:{config.height}:(ow-iw)/2:(oh-ih)/2"
        )
    elif config.aspect_mode == "fill":
        # Crop to fill entire frame
        filters.append(
            f"scale={config.width}:{config.height}:"
            f"force_original_aspect_ratio=increase"
        )
        filters.append(
            f"crop={config.width}:{config.height}"
        )
    else:  # stretch
        filters.append(f"scale={config.width}:{config.height}")

    # Add brightness/contrast adjustment
    filters.append(
        f"eq=brightness={config.brightness}:contrast={config.contrast}"
    )

    return [
        'ffmpeg', '-y',
        '-i', input_path,
        '-vf', ','.join(filters),
        '-c:v', 'mjpeg',
        '-q:v', str(config.quality),
        '-r', str(config.fps),
        '-pix_fmt', 'yuvj420p',
        '-an',  # No audio
        output_path
    ]
```

#### Progress Tracking

```python
# services/download_service.py

class DownloadProgress:
    """Track download progress for UI updates."""

    def __init__(self, callback: Callable[[str, float, str], None]):
        self.callback = callback  # (video_id, percent, status)

    def hook(self, d: dict):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            percent = (downloaded / total * 100) if total > 0 else 0
            self.callback(d.get('info_dict', {}).get('id'), percent, 'downloading')
        elif d['status'] == 'finished':
            self.callback(d.get('info_dict', {}).get('id'), 100, 'downloaded')
```

### File Structure

```
digital-photocard-collection/
├── app.py                      # Streamlit app entry (streamlit run app.py)
├── requirements.txt            # Python dependencies
├── config.yaml                 # User configuration
├── src/
│   ├── __init__.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── channel.py          # Channel dataclass
│   │   ├── video.py            # Video dataclass
│   │   └── settings.py         # Settings dataclass
│   ├── services/
│   │   ├── __init__.py
│   │   ├── database.py         # SQLite operations
│   │   ├── youtube_service.py  # yt-dlp wrapper for fetching
│   │   ├── download_service.py # Video downloading
│   │   ├── conversion_service.py # FFmpeg MJPEG conversion
│   │   └── export_service.py   # Copy to target folder
│   ├── components/
│   │   ├── __init__.py
│   │   ├── channel_sidebar.py  # Streamlit sidebar for channels
│   │   ├── video_grid.py       # Video thumbnail grid component
│   │   ├── settings_panel.py   # Conversion settings sliders
│   │   └── progress_display.py # Progress bars and status
│   └── utils/
│       ├── __init__.py
│       ├── ffmpeg_utils.py     # FFmpeg detection and commands
│       └── thumbnail_cache.py  # Local thumbnail caching
├── data/
│   ├── shorts.db               # SQLite database
│   ├── thumbnails/             # Cached thumbnail images
│   └── downloads/              # Temporary downloaded videos
├── output/                     # Converted MJPEG files
└── plans/
    └── youtube-shorts-mjpeg-converter.md
```

### UI Layout (Streamlit)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  🎬 CYD Shorts Converter                              localhost:8501   │
├───────────────────────┬─────────────────────────────────────────────────┤
│  SIDEBAR              │  MAIN CONTENT                                   │
│                       │                                                 │
│  📺 Channels          │  Filter: [All Channels ▼]  [☑ New Only]         │
│  ┌─────────────────┐  │  Selected: 15/47 │ New: 17 │ Converted: 30      │
│  │ + Add Channel   │  │  ─────────────────────────────────────────────  │
│  └─────────────────┘  │                                                 │
│                       │  ┌──────────┐ ┌──────────┐ ┌──────────┐         │
│  ☑ @Channel1 (12)     │  │  [IMG]   │ │  [IMG]   │ │  [IMG]   │         │
│  ☑ @Channel2 (5)      │  │ Title 1  │ │ Title 2  │ │ Title 3  │         │
│  ☐ @Channel3 (0)      │  │ 0:45 NEW │ │ 0:32     │ │ 0:58 NEW │         │
│                       │  │ [☑]      │ │ [☑]      │ │ [☐]      │         │
│  [🔄 Fetch All]       │  └──────────┘ └──────────┘ └──────────┘         │
│                       │                                                 │
│  ─────────────────    │  ┌──────────┐ ┌──────────┐ ┌──────────┐         │
│                       │  │  [IMG]   │ │  [IMG]   │ │  [IMG]   │         │
│  ⚙️ Settings          │  │ Title 4  │ │ Title 5  │ │ Title 6  │         │
│                       │  │ 0:28 ✓   │ │ 0:55     │ │ 0:41     │         │
│  Resolution           │  │ [☑]      │ │ [☐]      │ │ [☑]      │         │
│  [240] x [320]        │  └──────────┘ └──────────┘ └──────────┘         │
│                       │                                                 │
│  Quality: [5]         │  [Select All] [Deselect All] [Invert]           │
│  ▬▬▬▬●▬▬▬▬▬▬          │                                                 │
│                       │  ─────────────────────────────────────────────  │
│  FPS: [15]            │                                                 │
│  ▬▬▬▬▬●▬▬▬▬▬          │  📥 Download & Convert                          │
│                       │  ┌─────────────────────────────────────────┐    │
│  Brightness: [0.05]   │  │ ████████████░░░░░░░░  12/15 Converting  │    │
│  ▬▬▬▬▬●▬▬▬▬▬          │  └─────────────────────────────────────────┘    │
│                       │                                                 │
│  Aspect: [Fit ▼]      │  📤 Export to: /Volumes/SD/mjpeg                │
│                       │  [Browse...] [Export Selected]                  │
│  ─────────────────    │                                                 │
│  📁 Export Path       │                                                 │
│  /Volumes/SD/mjpeg    │                                                 │
└───────────────────────┴─────────────────────────────────────────────────┘
```

**Streamlit Component Mapping:**
- `st.sidebar` → Channel list + Settings
- `st.columns(3)` → Video thumbnail grid
- `st.image()` → Thumbnails from cache or URL
- `st.checkbox()` → Video selection
- `st.progress()` → Download/conversion progress
- `st.session_state` → Persist selections across reruns

## Implementation Phases

### Phase 1: Core Infrastructure

**Tasks:**
- [ ] Set up project structure (`app.py`, `src/`, `data/`)
- [ ] Implement SQLite database layer (`src/services/database.py`)
- [ ] Create data models (`src/models/`)
- [ ] Implement YouTube service using yt-dlp (`src/services/youtube_service.py`)
- [ ] Add Shorts detection logic (duration + aspect ratio)
- [ ] Create basic CLI for testing core functionality

**Success Criteria:**
- Can add a channel URL and fetch video list
- Correctly identifies Shorts vs regular videos
- Persists video metadata to SQLite

### Phase 2: Download & Conversion Pipeline

**Tasks:**
- [ ] Implement download service with progress hooks (`src/services/download_service.py`)
- [ ] Create FFmpeg conversion wrapper (`src/services/conversion_service.py`)
- [ ] Add conversion parameter configuration
- [ ] Implement "new video" detection on re-fetch
- [ ] Add source video cleanup after conversion
- [ ] Create thumbnail caching system (`src/utils/thumbnail_cache.py`)

**Success Criteria:**
- Can download and convert a video to MJPEG
- Conversion respects all parameters (size, quality, fps, brightness)
- Thumbnails are cached locally for offline viewing
- Re-fetching only marks genuinely new videos

### Phase 3: Streamlit UI

**Tasks:**
- [ ] Set up Streamlit app structure (`app.py`)
- [ ] Create sidebar with channel management (`src/components/channel_sidebar.py`)
- [ ] Build video thumbnail grid with selection (`src/components/video_grid.py`)
- [ ] Add settings panel with sliders (`src/components/settings_panel.py`)
- [ ] Implement progress display for batch operations (`src/components/progress_display.py`)
- [ ] Use `st.session_state` for persistent selections
- [ ] Add filtering (by channel, new only, selected only)

**Success Criteria:**
- Functional UI matching the layout design
- Can add channels, browse videos, select/deselect
- Visual distinction between new, selected, and converted videos
- Real-time progress feedback during operations
- Responsive grid layout for thumbnails

### Phase 4: Export & Polish

**Tasks:**
- [ ] Implement export service (`src/services/export_service.py`)
- [ ] Add file naming strategy (channel_videoid.mjpeg)
- [ ] Create settings persistence (config.yaml)
- [ ] Add dependency detection (FFmpeg, yt-dlp) with install guidance
- [ ] Implement error handling with user-friendly messages
- [ ] Add logging for debugging
- [ ] Create README with usage instructions

**Success Criteria:**
- Can export converted videos to SD card folder
- Settings persist between sessions
- Clear error messages when dependencies are missing
- Application is ready for daily use

## Acceptance Criteria

### Functional Requirements

- [ ] Add YouTube channels by URL, handle, or ID
- [ ] Fetch and display Shorts from added channels
- [ ] Distinguish between new and previously seen videos
- [ ] Select/deselect videos individually or in bulk
- [ ] Remember selections between sessions
- [ ] Download selected videos with progress indication
- [ ] Convert to MJPEG with configurable parameters:
  - [ ] Width and height (default 240x320)
  - [ ] Quality (1-31 scale)
  - [ ] Frame rate (1-30 fps)
  - [ ] Brightness (-1.0 to 1.0)
  - [ ] Contrast (0.5 to 2.0)
  - [ ] Aspect mode (fit/fill/stretch)
- [ ] Export converted files to user-specified folder
- [ ] Only download new videos on subsequent fetches
- [ ] Only convert videos that haven't been converted (or settings changed)

### Non-Functional Requirements

- [ ] UI remains responsive during download/conversion (threaded operations)
- [ ] Works offline for browsing cached data
- [ ] Handles network errors gracefully with retry option
- [ ] Detects and reports missing FFmpeg/yt-dlp
- [ ] Database migrations for future schema changes

### Quality Gates

- [ ] All core services have error handling
- [ ] UI tested with 100+ videos from 5+ channels
- [ ] Converted videos play correctly on CYD device
- [ ] Memory usage stable during batch processing
- [ ] Clean shutdown with no orphaned processes

## Success Metrics

1. **Workflow efficiency**: Reduce manual steps from ~10 to ~3 clicks per batch
2. **Reliability**: 95%+ of Shorts successfully converted
3. **Usability**: New user can add channel and convert first video in <2 minutes
4. **Performance**: Process 50 Shorts in <10 minutes on typical hardware

## Dependencies & Prerequisites

### Required
- Python 3.10+
- FFmpeg (system install)
- yt-dlp (`pip install yt-dlp`)
- Streamlit (`pip install streamlit`)
- Pillow for image handling (`pip install pillow`)

### Optional
- YouTube Data API key (for enhanced metadata, quota-sensitive)

### System Requirements
- 500MB disk space for application and cache
- Internet connection for fetching videos
- SD card reader for CYD export (or network-accessible folder)

## Risk Analysis & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| yt-dlp breaks with YouTube updates | Medium | High | Pin version, monitor releases, fallback to API |
| FFmpeg not installed on user system | Medium | High | Detect at startup, provide installation guide |
| API quota exceeded | Low | Medium | Use yt-dlp instead of API for video list |
| Large video count overwhelms UI | Medium | Medium | Implement pagination/virtual scrolling |
| Conversion fails for some videos | Low | Low | Log errors, allow retry, skip problematic files |

## Future Considerations

- **Playlist support**: Allow importing from YouTube playlists
- **Scheduled fetching**: Auto-check for new videos on interval
- **Preview in app**: Play video thumbnail preview before downloading
- **Batch settings**: Apply different settings to different channels
- **Direct CYD transfer**: WiFi upload to CYD's built-in web server
- **Multiple display profiles**: Presets for different CYD display sizes

## References & Research

### Internal References
- Existing conversion script: `/Users/joeywang/Documents/Maker/CYD/ive/download_and_convert.py`
- CYD video player firmware: `/Users/joeywang/Documents/Maker/CYD/esp32-2432S028_video_player/`
- MJPEG decoder class: `/Users/joeywang/Documents/Maker/CYD/CYD-photocard-display/MjpegClass.h`

### External References
- [yt-dlp Documentation](https://github.com/yt-dlp/yt-dlp)
- [FFmpeg MJPEG Encoding](https://ffmpeg.org/ffmpeg-codecs.html#mjpeg)
- [Streamlit Documentation](https://docs.streamlit.io/)
- [YouTube Data API v3](https://developers.google.com/youtube/v3/docs)
- [CYD (ESP32-2432S028R) Info](https://github.com/witnessmenow/ESP32-Cheap-Yellow-Display)

### Related Work
- Existing URL list approach: `/Users/joeywang/Documents/Maker/CYD/ive/video.txt`
- WiFi upload feature in CYD-photocard-display project

---

## ERD Diagram

```mermaid
erDiagram
    channels ||--o{ videos : "has many"
    videos ||--|| video_state : "has one"

    channels {
        text id PK "YouTube channel ID"
        text name "Channel display name"
        text url "Original URL"
        timestamp last_fetched
        timestamp created_at
    }

    videos {
        text id PK "YouTube video ID"
        text channel_id FK "References channels.id"
        text title
        text description
        text thumbnail_url
        integer duration "Duration in seconds"
        timestamp published_at
        integer width
        integer height
        boolean is_short
        timestamp created_at
    }

    video_state {
        text video_id PK FK "References videos.id"
        boolean is_new
        boolean is_selected
        boolean is_downloaded
        boolean is_converted
        boolean is_exported
        text download_path
        text converted_path
        text conversion_settings "JSON"
        timestamp seen_at
        timestamp downloaded_at
        timestamp converted_at
        timestamp exported_at
    }

    settings {
        text key PK
        text value
    }
```

---

*Generated with Claude Code*
