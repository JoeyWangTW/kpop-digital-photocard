import shutil
import subprocess
from typing import Optional


def check_ffmpeg() -> tuple[bool, Optional[str]]:
    """
    Check if FFmpeg is installed and get its version.

    Returns:
        Tuple of (is_available, version_string)
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            # Extract version from first line
            first_line = result.stdout.split("\n")[0]
            return True, first_line
        return False, None
    except FileNotFoundError:
        return False, None
    except Exception:
        return False, None


def check_ytdlp() -> tuple[bool, Optional[str]]:
    """
    Check if yt-dlp is installed and get its version.

    Returns:
        Tuple of (is_available, version_string)
    """
    try:
        result = subprocess.run(
            ["yt-dlp", "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return True, version
        return False, None
    except FileNotFoundError:
        return False, None
    except Exception:
        return False, None


def get_install_instructions() -> dict[str, str]:
    """Get installation instructions for missing dependencies."""
    return {
        "ffmpeg": """
FFmpeg is required for video conversion.

Install on macOS:
    brew install ffmpeg

Install on Ubuntu/Debian:
    sudo apt install ffmpeg

Install on Windows:
    Download from https://ffmpeg.org/download.html
    Or use: choco install ffmpeg
""".strip(),
        "yt-dlp": """
yt-dlp is required for downloading videos.

Install with pip:
    pip install yt-dlp

Or on macOS:
    brew install yt-dlp
""".strip(),
    }


def check_all_dependencies() -> dict[str, dict]:
    """
    Check all required dependencies.

    Returns:
        Dictionary with dependency status and info
    """
    ffmpeg_ok, ffmpeg_version = check_ffmpeg()
    ytdlp_ok, ytdlp_version = check_ytdlp()

    instructions = get_install_instructions()

    return {
        "ffmpeg": {
            "available": ffmpeg_ok,
            "version": ffmpeg_version,
            "instructions": instructions["ffmpeg"] if not ffmpeg_ok else None,
        },
        "yt-dlp": {
            "available": ytdlp_ok,
            "version": ytdlp_version,
            "instructions": instructions["yt-dlp"] if not ytdlp_ok else None,
        },
        "all_ok": ffmpeg_ok and ytdlp_ok,
    }
