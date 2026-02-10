import shutil
from pathlib import Path
from typing import Callable, Optional


class ExportService:
    """Service for exporting converted videos to target folder."""

    def __init__(self, source_dir: str = "converted"):
        self.source_dir = Path(source_dir)

    def export_video(
        self,
        video_id: str,
        target_dir: Path,
        channel_name: Optional[str] = None,
        progress_callback: Optional[Callable[[str, float, str], None]] = None,
    ) -> Optional[Path]:
        """
        Export a converted video to the target directory.

        Args:
            video_id: Video ID
            target_dir: Target directory for export
            channel_name: Optional channel name for filename prefix
            progress_callback: Function called with (video_id, percent, status)

        Returns:
            Path to exported file or None if failed
        """
        source_path = self.source_dir / f"{video_id}.mjpeg"

        if not source_path.exists():
            if progress_callback:
                progress_callback(video_id, 0, "error")
            return None

        # Ensure target directory exists
        target_dir.mkdir(parents=True, exist_ok=True)

        # Build target filename
        if channel_name:
            # Sanitize channel name
            safe_channel = self._sanitize_filename(channel_name)
            target_filename = f"{safe_channel}_{video_id}.mjpeg"
        else:
            target_filename = f"{video_id}.mjpeg"

        target_path = target_dir / target_filename

        try:
            if progress_callback:
                progress_callback(video_id, 0, "exporting")

            # Copy file
            shutil.copy2(source_path, target_path)

            if progress_callback:
                progress_callback(video_id, 100, "exported")

            return target_path

        except Exception as e:
            print(f"Error exporting video {video_id}: {e}")
            if progress_callback:
                progress_callback(video_id, 0, "error")

        return None

    def export_batch(
        self,
        video_ids: list[str],
        target_dir: Path,
        channel_names: Optional[dict[str, str]] = None,
        progress_callback: Optional[Callable[[str, float, str], None]] = None,
    ) -> dict[str, Optional[Path]]:
        """
        Export multiple videos to the target directory.

        Args:
            video_ids: List of video IDs to export
            target_dir: Target directory for export
            channel_names: Mapping of video_id to channel name
            progress_callback: Function called with (video_id, percent, status)

        Returns:
            Dictionary mapping video_id to exported path (or None if failed)
        """
        results = {}
        channel_names = channel_names or {}

        for video_id in video_ids:
            channel_name = channel_names.get(video_id)
            result = self.export_video(
                video_id, target_dir, channel_name, progress_callback
            )
            results[video_id] = result

        return results

    def create_manifest(
        self,
        target_dir: Path,
        videos: list[dict],
    ) -> Path:
        """
        Create a manifest file listing exported videos.

        Args:
            target_dir: Target directory containing exported files
            videos: List of video info dicts with 'id', 'title', 'channel_name'

        Returns:
            Path to manifest file
        """
        manifest_path = target_dir / "manifest.txt"

        lines = ["# CYD Shorts Collection", "# Filename | Title | Channel", ""]

        for video in videos:
            video_id = video.get("id", "")
            title = video.get("title", "Untitled")
            channel = video.get("channel_name", "Unknown")

            # Find the exported file
            matches = list(target_dir.glob(f"*{video_id}.mjpeg"))
            if matches:
                filename = matches[0].name
                lines.append(f"{filename} | {title} | {channel}")

        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return manifest_path

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string for use in filename."""
        # Remove or replace invalid characters
        import re
        name = re.sub(r'[<>:"/\\|?*]', "", name)
        name = re.sub(r"\s+", "_", name)
        # Limit length
        if len(name) > 30:
            name = name[:30]
        return name

    def get_export_stats(self, target_dir: Path) -> dict:
        """Get statistics about exported files in target directory."""
        if not target_dir.exists():
            return {"count": 0, "total_size_mb": 0}

        mjpeg_files = list(target_dir.glob("*.mjpeg"))
        total_size = sum(f.stat().st_size for f in mjpeg_files)

        return {
            "count": len(mjpeg_files),
            "total_size_mb": total_size / (1024 * 1024),
        }
