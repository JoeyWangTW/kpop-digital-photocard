from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Channel:
    """Represents a YouTube channel."""

    id: str  # YouTube channel ID (UCxxxxx)
    name: str  # Channel display name
    url: str  # Original URL provided by user
    last_fetched: Optional[datetime] = None
    created_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: dict) -> "Channel":
        """Create Channel from database row."""
        return cls(
            id=row["id"],
            name=row["name"],
            url=row["url"],
            last_fetched=row.get("last_fetched"),
            created_at=row.get("created_at"),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for database insertion."""
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "last_fetched": self.last_fetched,
            "created_at": self.created_at,
        }
