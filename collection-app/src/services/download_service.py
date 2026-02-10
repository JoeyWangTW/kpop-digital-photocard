from pathlib import Path
from typing import Callable, Optional

import yt_dlp


class DownloadProgress:
    """Track download progress for UI updates."""

    def __init__(
        self,
        callback: Optional[Callable[[str, float, str], None]] = None,
    ):
        """
        Initialize progress tracker.

        Args:
            callback: Function called with (video_id, percent, status)
        """
        self.callback = callback
        self.current_video_id: Optional[str] = None

    def set_video_id(self, video_id: str):
        """Set the current video ID being processed."""
        self.current_video_id = video_id

    def hook(self, d: dict):
        """Progress hook for yt-dlp."""
        if not self.callback:
            return

        status = d.get("status", "")
        video_id = self.current_video_id

        if not video_id:
            # Try to get from info_dict
            info = d.get("info_dict", {})
            video_id = info.get("id")

        if not video_id:
            return

        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            percent = (downloaded / total * 100) if total > 0 else 0
            self.callback(video_id, percent, "downloading")

        elif status == "finished":
            self.callback(video_id, 100, "downloaded")

        elif status == "error":
            self.callback(video_id, 0, "error")


class DownloadService:
    """Service for downloading YouTube videos."""

    def __init__(self, download_dir: str = "downloads"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def download_video(
        self,
        video_id: str,
        progress_callback: Optional[Callable[[str, float, str], None]] = None,
    ) -> Optional[Path]:
        """
        Download a video by ID.

        Args:
            video_id: YouTube video ID
            progress_callback: Function called with (video_id, percent, status)

        Returns:
            Path to downloaded file or None if failed
        """
        url = f"https://www.youtube.com/watch?v={video_id}"
        output_template = str(self.download_dir / f"{video_id}.%(ext)s")

        progress = DownloadProgress(progress_callback)
        progress.set_video_id(video_id)

        ydl_opts = {
            "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "outtmpl": output_template,
            "no_playlist": True,
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [progress.hook],
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # Find the downloaded file
            for ext in ["mp4", "webm", "mkv"]:
                file_path = self.download_dir / f"{video_id}.{ext}"
                if file_path.exists():
                    return file_path

            # Check for any file matching the video ID
            matches = list(self.download_dir.glob(f"{video_id}.*"))
            if matches:
                return matches[0]

        except Exception as e:
            print(f"Error downloading video {video_id}: {e}")
            if progress_callback:
                progress_callback(video_id, 0, "error")

        return None

    def cleanup_download(self, file_path: Path) -> None:
        """Remove a downloaded file."""
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception as e:
            print(f"Error cleaning up {file_path}: {e}")

    def get_download_path(self, video_id: str) -> Optional[Path]:
        """Get the path to a downloaded video if it exists."""
        for ext in ["mp4", "webm", "mkv"]:
            file_path = self.download_dir / f"{video_id}.{ext}"
            if file_path.exists():
                return file_path

        matches = list(self.download_dir.glob(f"{video_id}.*"))
        if matches:
            return matches[0]

        return None
