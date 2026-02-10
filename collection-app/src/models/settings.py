from dataclasses import dataclass
import json


@dataclass
class ConversionSettings:
    """Settings for video conversion."""

    width: int = 240  # CYD display width
    height: int = 320  # CYD display height
    quality: int = 5  # MJPEG quality (2-31, lower=better)
    fps: int = 15  # Frame rate
    brightness: float = -0.1  # Slightly dimmer for display
    contrast: float = 1.0  # No contrast change
    aspect_mode: str = "fit"  # fit (letterbox), fill (crop), stretch

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.__dict__)

    @classmethod
    def from_json(cls, json_str: str) -> "ConversionSettings":
        """Create from JSON string."""
        data = json.loads(json_str)
        return cls(**data)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: dict) -> "ConversionSettings":
        """Create from dictionary."""
        return cls(
            width=data.get("width", 240),
            height=data.get("height", 320),
            quality=data.get("quality", 5),
            fps=data.get("fps", 15),
            brightness=data.get("brightness", -0.1),
            contrast=data.get("contrast", 1.0),
            aspect_mode=data.get("aspect_mode", "fit"),
        )
