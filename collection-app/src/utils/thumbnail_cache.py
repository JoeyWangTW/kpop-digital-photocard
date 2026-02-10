import hashlib
from pathlib import Path
from typing import Optional

import requests
from PIL import Image
from io import BytesIO


class ThumbnailCache:
    """Cache for video thumbnails."""

    def __init__(self, cache_dir: str = "data/thumbnails"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.target_size = (320, 180)  # 16:9 thumbnail size

    def get_thumbnail_path(self, video_id: str) -> Path:
        """Get the cache path for a video thumbnail."""
        return self.cache_dir / f"{video_id}.jpg"

    def has_thumbnail(self, video_id: str) -> bool:
        """Check if a thumbnail is cached."""
        return self.get_thumbnail_path(video_id).exists()

    def get_cached_thumbnail(self, video_id: str) -> Optional[Path]:
        """Get the path to a cached thumbnail if it exists."""
        path = self.get_thumbnail_path(video_id)
        if path.exists():
            return path
        return None

    def download_and_cache(
        self,
        video_id: str,
        thumbnail_url: str,
    ) -> Optional[Path]:
        """
        Download a thumbnail and cache it locally.

        Args:
            video_id: Video ID for naming
            thumbnail_url: URL to download from

        Returns:
            Path to cached thumbnail or None if failed
        """
        if not thumbnail_url:
            return None

        cache_path = self.get_thumbnail_path(video_id)

        # Return if already cached
        if cache_path.exists():
            return cache_path

        try:
            # Download image
            response = requests.get(thumbnail_url, timeout=10)
            response.raise_for_status()

            # Open and resize image
            img = Image.open(BytesIO(response.content))

            # Convert to RGB if necessary (for JPEG)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            # Resize maintaining aspect ratio
            img.thumbnail(self.target_size, Image.Resampling.LANCZOS)

            # Save as JPEG
            img.save(cache_path, "JPEG", quality=85)

            return cache_path

        except Exception as e:
            print(f"Error caching thumbnail for {video_id}: {e}")
            return None

    def get_or_download(
        self,
        video_id: str,
        thumbnail_url: Optional[str],
    ) -> Optional[Path]:
        """
        Get a cached thumbnail or download it.

        Args:
            video_id: Video ID
            thumbnail_url: URL to download from if not cached

        Returns:
            Path to thumbnail or None if unavailable
        """
        # Check cache first
        cached = self.get_cached_thumbnail(video_id)
        if cached:
            return cached

        # Download if URL provided
        if thumbnail_url:
            return self.download_and_cache(video_id, thumbnail_url)

        return None

    def clear_cache(self) -> int:
        """
        Clear all cached thumbnails.

        Returns:
            Number of files deleted
        """
        count = 0
        for file in self.cache_dir.glob("*.jpg"):
            try:
                file.unlink()
                count += 1
            except Exception:
                pass
        return count

    def get_cache_size_mb(self) -> float:
        """Get total size of cached thumbnails in MB."""
        total = sum(f.stat().st_size for f in self.cache_dir.glob("*.jpg"))
        return total / (1024 * 1024)

    def get_cache_count(self) -> int:
        """Get number of cached thumbnails."""
        return len(list(self.cache_dir.glob("*.jpg")))
