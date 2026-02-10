from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Video:
    """Represents a YouTube video."""

    id: str  # YouTube video ID
    channel_id: str  # References channels.id
    title: str
    duration: int  # Duration in seconds
    thumbnail_url: Optional[str] = None
    description: Optional[str] = None
    published_at: Optional[datetime] = None
    width: Optional[int] = None
    height: Optional[int] = None
    is_short: bool = False
    created_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: dict) -> "Video":
        """Create Video from database row."""
        return cls(
            id=row["id"],
            channel_id=row["channel_id"],
            title=row["title"],
            duration=row["duration"],
            thumbnail_url=row.get("thumbnail_url"),
            description=row.get("description"),
            published_at=row.get("published_at"),
            width=row.get("width"),
            height=row.get("height"),
            is_short=bool(row.get("is_short", False)),
            created_at=row.get("created_at"),
        )

    @property
    def youtube_url(self) -> str:
        """Get the YouTube URL for this video."""
        return f"https://www.youtube.com/watch?v={self.id}"

    @property
    def shorts_url(self) -> str:
        """Get the YouTube Shorts URL for this video."""
        return f"https://www.youtube.com/shorts/{self.id}"

    @property
    def duration_str(self) -> str:
        """Get duration as MM:SS string."""
        minutes = self.duration // 60
        seconds = self.duration % 60
        return f"{minutes}:{seconds:02d}"


@dataclass
class VideoState:
    """Represents the processing state of a video."""

    video_id: str
    is_new: bool = True
    is_selected: bool = False
    is_downloaded: bool = False
    is_converted: bool = False
    is_exported: bool = False
    download_path: Optional[str] = None
    converted_path: Optional[str] = None
    conversion_settings: Optional[str] = None  # JSON string
    seen_at: Optional[datetime] = None
    downloaded_at: Optional[datetime] = None
    converted_at: Optional[datetime] = None
    exported_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: dict) -> "VideoState":
        """Create VideoState from database row."""
        return cls(
            video_id=row["video_id"],
            is_new=bool(row.get("is_new", True)),
            is_selected=bool(row.get("is_selected", False)),
            is_downloaded=bool(row.get("is_downloaded", False)),
            is_converted=bool(row.get("is_converted", False)),
            is_exported=bool(row.get("is_exported", False)),
            download_path=row.get("download_path"),
            converted_path=row.get("converted_path"),
            conversion_settings=row.get("conversion_settings"),
            seen_at=row.get("seen_at"),
            downloaded_at=row.get("downloaded_at"),
            converted_at=row.get("converted_at"),
            exported_at=row.get("exported_at"),
        )


@dataclass
class VideoWithState:
    """Video combined with its processing state."""

    video: Video
    state: VideoState

    @property
    def id(self) -> str:
        return self.video.id

    @property
    def title(self) -> str:
        return self.video.title

    @property
    def thumbnail_url(self) -> Optional[str]:
        return self.video.thumbnail_url

    @property
    def duration_str(self) -> str:
        return self.video.duration_str

    @property
    def is_new(self) -> bool:
        return self.state.is_new

    @property
    def is_selected(self) -> bool:
        return self.state.is_selected

    @property
    def is_converted(self) -> bool:
        return self.state.is_converted

    @property
    def channel_id(self) -> str:
        return self.video.channel_id
