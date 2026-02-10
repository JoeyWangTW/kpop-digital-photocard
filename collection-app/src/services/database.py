import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.models.channel import Channel
from src.models.video import Video, VideoState, VideoWithState


SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    last_fetched TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    thumbnail_url TEXT,
    duration INTEGER NOT NULL,
    published_at TIMESTAMP,
    width INTEGER,
    height INTEGER,
    is_short BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (channel_id) REFERENCES channels(id)
);

CREATE TABLE IF NOT EXISTS video_state (
    video_id TEXT PRIMARY KEY,
    is_new BOOLEAN DEFAULT 1,
    is_selected BOOLEAN DEFAULT 0,
    is_downloaded BOOLEAN DEFAULT 0,
    is_converted BOOLEAN DEFAULT 0,
    is_exported BOOLEAN DEFAULT 0,
    download_path TEXT,
    converted_path TEXT,
    conversion_settings TEXT,
    seen_at TIMESTAMP,
    downloaded_at TIMESTAMP,
    converted_at TIMESTAMP,
    exported_at TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_videos_is_short ON videos(is_short);
CREATE INDEX IF NOT EXISTS idx_state_is_new ON video_state(is_new);
CREATE INDEX IF NOT EXISTS idx_state_is_selected ON video_state(is_selected);
"""


class Database:
    """SQLite database for storing channels, videos, and state."""

    def __init__(self, db_path: str = "data/shorts.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """Get a database connection with row factory."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.executescript(SCHEMA)

    # Channel operations

    def add_channel(self, channel: Channel) -> None:
        """Add or update a channel."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO channels (id, name, url, last_fetched, created_at)
                VALUES (?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
                """,
                (
                    channel.id,
                    channel.name,
                    channel.url,
                    channel.last_fetched,
                    channel.created_at,
                ),
            )

    def get_channel(self, channel_id: str) -> Optional[Channel]:
        """Get a channel by ID."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM channels WHERE id = ?", (channel_id,)
            ).fetchone()
            if row:
                return Channel.from_row(dict(row))
            return None

    def get_all_channels(self) -> list[Channel]:
        """Get all channels."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM channels ORDER BY name"
            ).fetchall()
            return [Channel.from_row(dict(row)) for row in rows]

    def delete_channel(self, channel_id: str) -> None:
        """Delete a channel and its videos."""
        with self._get_connection() as conn:
            # Delete video states first
            conn.execute(
                """
                DELETE FROM video_state
                WHERE video_id IN (SELECT id FROM videos WHERE channel_id = ?)
                """,
                (channel_id,),
            )
            # Delete videos
            conn.execute("DELETE FROM videos WHERE channel_id = ?", (channel_id,))
            # Delete channel
            conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))

    def update_channel_fetched(self, channel_id: str) -> None:
        """Update the last_fetched timestamp for a channel."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE channels SET last_fetched = ? WHERE id = ?",
                (datetime.now(), channel_id),
            )

    # Video operations

    def add_video(self, video: Video) -> bool:
        """Add a video if it doesn't exist. Returns True if new."""
        with self._get_connection() as conn:
            # Check if video already exists
            existing = conn.execute(
                "SELECT id FROM videos WHERE id = ?", (video.id,)
            ).fetchone()

            if existing:
                return False

            # Insert video
            conn.execute(
                """
                INSERT INTO videos
                (id, channel_id, title, description, thumbnail_url, duration,
                 published_at, width, height, is_short, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    video.id,
                    video.channel_id,
                    video.title,
                    video.description,
                    video.thumbnail_url,
                    video.duration,
                    video.published_at,
                    video.width,
                    video.height,
                    video.is_short,
                ),
            )

            # Create initial state
            conn.execute(
                "INSERT INTO video_state (video_id, is_new) VALUES (?, 1)",
                (video.id,),
            )
            return True

    def get_videos_with_state(
        self,
        channel_id: Optional[str] = None,
        shorts_only: bool = True,
        new_only: bool = False,
        selected_only: bool = False,
    ) -> list[VideoWithState]:
        """Get videos with their state, optionally filtered."""
        with self._get_connection() as conn:
            query = """
                SELECT v.*, s.is_new, s.is_selected, s.is_downloaded,
                       s.is_converted, s.is_exported, s.download_path,
                       s.converted_path, s.conversion_settings, s.seen_at,
                       s.downloaded_at, s.converted_at, s.exported_at
                FROM videos v
                LEFT JOIN video_state s ON v.id = s.video_id
                WHERE 1=1
            """
            params = []

            if channel_id:
                query += " AND v.channel_id = ?"
                params.append(channel_id)

            if shorts_only:
                query += " AND v.is_short = 1"

            if new_only:
                query += " AND s.is_new = 1"

            if selected_only:
                query += " AND s.is_selected = 1"

            query += " ORDER BY v.published_at DESC"

            rows = conn.execute(query, params).fetchall()
            result = []
            for row in rows:
                row_dict = dict(row)
                video = Video.from_row(row_dict)
                state = VideoState(
                    video_id=row_dict["id"],
                    is_new=bool(row_dict.get("is_new", True)),
                    is_selected=bool(row_dict.get("is_selected", False)),
                    is_downloaded=bool(row_dict.get("is_downloaded", False)),
                    is_converted=bool(row_dict.get("is_converted", False)),
                    is_exported=bool(row_dict.get("is_exported", False)),
                    download_path=row_dict.get("download_path"),
                    converted_path=row_dict.get("converted_path"),
                    conversion_settings=row_dict.get("conversion_settings"),
                    seen_at=row_dict.get("seen_at"),
                    downloaded_at=row_dict.get("downloaded_at"),
                    converted_at=row_dict.get("converted_at"),
                    exported_at=row_dict.get("exported_at"),
                )
                result.append(VideoWithState(video=video, state=state))
            return result

    def get_video_counts(self, channel_id: Optional[str] = None) -> dict:
        """Get counts of videos in different states."""
        with self._get_connection() as conn:
            channel_filter = "AND v.channel_id = ?" if channel_id else ""
            params = (channel_id,) if channel_id else ()

            total = conn.execute(
                f"SELECT COUNT(*) FROM videos v WHERE v.is_short = 1 {channel_filter}",
                params,
            ).fetchone()[0]

            new = conn.execute(
                f"""
                SELECT COUNT(*) FROM videos v
                JOIN video_state s ON v.id = s.video_id
                WHERE v.is_short = 1 AND s.is_new = 1 {channel_filter}
                """,
                params,
            ).fetchone()[0]

            selected = conn.execute(
                f"""
                SELECT COUNT(*) FROM videos v
                JOIN video_state s ON v.id = s.video_id
                WHERE v.is_short = 1 AND s.is_selected = 1 {channel_filter}
                """,
                params,
            ).fetchone()[0]

            converted = conn.execute(
                f"""
                SELECT COUNT(*) FROM videos v
                JOIN video_state s ON v.id = s.video_id
                WHERE v.is_short = 1 AND s.is_converted = 1 {channel_filter}
                """,
                params,
            ).fetchone()[0]

            return {
                "total": total,
                "new": new,
                "selected": selected,
                "converted": converted,
            }

    # Video state operations

    def update_video_selected(self, video_id: str, selected: bool) -> None:
        """Update the selected state of a video."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE video_state SET is_selected = ? WHERE video_id = ?",
                (selected, video_id),
            )

    def update_video_seen(self, video_id: str) -> None:
        """Mark a video as seen (no longer new)."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE video_state SET is_new = 0, seen_at = ? WHERE video_id = ?",
                (datetime.now(), video_id),
            )

    def update_video_downloaded(
        self, video_id: str, download_path: str
    ) -> None:
        """Mark a video as downloaded."""
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE video_state
                SET is_downloaded = 1, download_path = ?, downloaded_at = ?
                WHERE video_id = ?
                """,
                (download_path, datetime.now(), video_id),
            )

    def update_video_converted(
        self, video_id: str, converted_path: str, settings_json: str
    ) -> None:
        """Mark a video as converted."""
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE video_state
                SET is_converted = 1, converted_path = ?,
                    conversion_settings = ?, converted_at = ?
                WHERE video_id = ?
                """,
                (converted_path, settings_json, datetime.now(), video_id),
            )

    def update_video_exported(self, video_id: str) -> None:
        """Mark a video as exported."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE video_state SET is_exported = 1, exported_at = ? WHERE video_id = ?",
                (datetime.now(), video_id),
            )

    def clear_download_path(self, video_id: str) -> None:
        """Clear the download path (after cleanup)."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE video_state SET download_path = NULL WHERE video_id = ?",
                (video_id,),
            )

    def update_video_for_custom_collection(self, video_id: str) -> None:
        """Update existing video to show in custom collection."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE videos SET channel_id = '__custom__', is_short = 1 WHERE id = ?",
                (video_id,),
            )

    def select_all_videos(self, channel_id: Optional[str] = None) -> None:
        """Select all shorts videos."""
        with self._get_connection() as conn:
            if channel_id:
                conn.execute(
                    """
                    UPDATE video_state SET is_selected = 1
                    WHERE video_id IN (
                        SELECT id FROM videos WHERE channel_id = ? AND is_short = 1
                    )
                    """,
                    (channel_id,),
                )
            else:
                conn.execute(
                    """
                    UPDATE video_state SET is_selected = 1
                    WHERE video_id IN (SELECT id FROM videos WHERE is_short = 1)
                    """
                )

    def deselect_all_videos(self, channel_id: Optional[str] = None) -> None:
        """Deselect all shorts videos."""
        with self._get_connection() as conn:
            if channel_id:
                conn.execute(
                    """
                    UPDATE video_state SET is_selected = 0
                    WHERE video_id IN (
                        SELECT id FROM videos WHERE channel_id = ? AND is_short = 1
                    )
                    """,
                    (channel_id,),
                )
            else:
                conn.execute(
                    """
                    UPDATE video_state SET is_selected = 0
                    WHERE video_id IN (SELECT id FROM videos WHERE is_short = 1)
                    """
                )

    def invert_selection(self, channel_id: Optional[str] = None) -> None:
        """Invert selection of all shorts videos."""
        with self._get_connection() as conn:
            if channel_id:
                conn.execute(
                    """
                    UPDATE video_state
                    SET is_selected = NOT is_selected
                    WHERE video_id IN (
                        SELECT id FROM videos WHERE channel_id = ? AND is_short = 1
                    )
                    """,
                    (channel_id,),
                )
            else:
                conn.execute(
                    """
                    UPDATE video_state
                    SET is_selected = NOT is_selected
                    WHERE video_id IN (SELECT id FROM videos WHERE is_short = 1)
                    """
                )

    # Settings operations

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a setting value."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            if row:
                return row["value"]
            return default

    def set_setting(self, key: str, value: str) -> None:
        """Set a setting value."""
        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
