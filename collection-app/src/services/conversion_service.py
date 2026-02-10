import subprocess
import re
from pathlib import Path
from typing import Callable, Optional

from src.models.settings import ConversionSettings


class ConversionService:
    """Service for converting videos to MJPEG format."""

    def __init__(self, output_dir: str = "converted"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_ffmpeg_command(
        self,
        input_path: Path,
        output_path: Path,
        settings: ConversionSettings,
    ) -> list[str]:
        """Build FFmpeg command for MJPEG conversion."""
        filters = []

        # Scaling based on aspect mode
        if settings.aspect_mode == "fit":
            # Letterbox: maintain aspect ratio, add black bars
            filters.append(
                f"scale={settings.width}:{settings.height}:"
                f"force_original_aspect_ratio=decrease"
            )
            filters.append(
                f"pad={settings.width}:{settings.height}:(ow-iw)/2:(oh-ih)/2"
            )
        elif settings.aspect_mode == "fill":
            # Crop to fill entire frame
            filters.append(
                f"scale={settings.width}:{settings.height}:"
                f"force_original_aspect_ratio=increase"
            )
            filters.append(f"crop={settings.width}:{settings.height}")
        else:  # stretch
            filters.append(f"scale={settings.width}:{settings.height}")

        # Add brightness/contrast adjustment
        if settings.brightness != 0 or settings.contrast != 1.0:
            filters.append(
                f"eq=brightness={settings.brightness}:contrast={settings.contrast}"
            )

        return [
            "ffmpeg",
            "-y",  # Overwrite output
            "-i", str(input_path),
            "-vf", ",".join(filters),
            "-c:v", "mjpeg",
            "-q:v", str(settings.quality),
            "-r", str(settings.fps),
            "-pix_fmt", "yuvj420p",
            "-an",  # No audio
            str(output_path),
        ]

    def convert_video(
        self,
        video_id: str,
        input_path: Path,
        settings: ConversionSettings,
        progress_callback: Optional[Callable[[str, float, str], None]] = None,
    ) -> Optional[Path]:
        """
        Convert a video to MJPEG format.

        Args:
            video_id: Video ID for naming and progress
            input_path: Path to source video
            settings: Conversion settings
            progress_callback: Function called with (video_id, percent, status)

        Returns:
            Path to converted file or None if failed
        """
        output_path = self.output_dir / f"{video_id}.mjpeg"

        if progress_callback:
            progress_callback(video_id, 0, "converting")

        # Get video duration for progress calculation
        duration = self._get_video_duration(input_path)

        cmd = self.build_ffmpeg_command(input_path, output_path, settings)

        try:
            # Run FFmpeg with progress parsing
            process = subprocess.Popen(
                cmd + ["-progress", "pipe:1"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )

            if process.stdout:
                for line in process.stdout:
                    if line.startswith("out_time_ms="):
                        try:
                            time_ms = int(line.split("=")[1])
                            if duration > 0:
                                progress = min(
                                    (time_ms / 1000000) / duration * 100, 99
                                )
                                if progress_callback:
                                    progress_callback(
                                        video_id, progress, "converting"
                                    )
                        except (ValueError, IndexError):
                            pass

            process.wait()

            if process.returncode == 0 and output_path.exists():
                if progress_callback:
                    progress_callback(video_id, 100, "converted")
                return output_path
            else:
                stderr = process.stderr.read() if process.stderr else ""
                print(f"FFmpeg error for {video_id}: {stderr[-500:]}")
                if progress_callback:
                    progress_callback(video_id, 0, "error")

        except FileNotFoundError:
            print("FFmpeg not found. Please install FFmpeg.")
            if progress_callback:
                progress_callback(video_id, 0, "error")
        except Exception as e:
            print(f"Error converting video {video_id}: {e}")
            if progress_callback:
                progress_callback(video_id, 0, "error")

        return None

    def _get_video_duration(self, input_path: Path) -> float:
        """Get video duration in seconds using ffprobe."""
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(input_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return float(result.stdout.strip())
        except Exception:
            pass
        return 0

    def get_converted_path(self, video_id: str) -> Optional[Path]:
        """Get the path to a converted video if it exists."""
        output_path = self.output_dir / f"{video_id}.mjpeg"
        if output_path.exists():
            return output_path
        return None

    def get_file_size_mb(self, video_id: str) -> Optional[float]:
        """Get the size of a converted video in MB."""
        output_path = self.get_converted_path(video_id)
        if output_path:
            return output_path.stat().st_size / (1024 * 1024)
        return None
