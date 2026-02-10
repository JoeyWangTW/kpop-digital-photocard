import streamlit as st
from pathlib import Path
import json

from src.models.settings import ConversionSettings
from src.services.database import Database


def render_settings_panel(db: Database) -> tuple[ConversionSettings, Path]:
    """
    Render the conversion settings panel in the sidebar.

    Args:
        db: Database instance

    Returns:
        Tuple of (ConversionSettings, export_path)
    """
    st.sidebar.divider()
    st.sidebar.header("Settings")

    # Load saved settings
    saved_settings = db.get_setting("conversion_settings")
    if saved_settings:
        try:
            settings = ConversionSettings.from_json(saved_settings)
        except Exception:
            settings = ConversionSettings()
    else:
        settings = ConversionSettings()

    # Resolution
    st.sidebar.subheader("Resolution")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        width = st.number_input(
            "Width",
            min_value=120,
            max_value=480,
            value=settings.width,
            step=10,
            key="width",
        )
    with col2:
        height = st.number_input(
            "Height",
            min_value=160,
            max_value=640,
            value=settings.height,
            step=10,
            key="height",
        )

    # Quality
    quality = st.sidebar.slider(
        "Quality (lower = better)",
        min_value=2,
        max_value=31,
        value=settings.quality,
        key="quality",
        help="MJPEG quality: 2 is highest quality, 31 is lowest",
    )

    # FPS
    fps = st.sidebar.slider(
        "Frame Rate (FPS)",
        min_value=5,
        max_value=30,
        value=settings.fps,
        key="fps",
    )

    # Brightness
    brightness = st.sidebar.slider(
        "Brightness",
        min_value=-0.5,
        max_value=0.5,
        value=settings.brightness,
        step=0.05,
        key="brightness",
        help="Adjust brightness: 0 = no change",
    )

    # Contrast
    contrast = st.sidebar.slider(
        "Contrast",
        min_value=0.5,
        max_value=2.0,
        value=settings.contrast,
        step=0.1,
        key="contrast",
        help="Adjust contrast: 1.0 = no change",
    )

    # Aspect mode
    aspect_mode = st.sidebar.selectbox(
        "Aspect Ratio",
        options=["fit", "fill", "stretch"],
        index=["fit", "fill", "stretch"].index(settings.aspect_mode),
        key="aspect_mode",
        help="fit: letterbox, fill: crop, stretch: distort",
    )

    # Create new settings object
    new_settings = ConversionSettings(
        width=width,
        height=height,
        quality=quality,
        fps=fps,
        brightness=brightness,
        contrast=contrast,
        aspect_mode=aspect_mode,
    )

    # Save settings if changed
    if new_settings.to_json() != saved_settings:
        db.set_setting("conversion_settings", new_settings.to_json())

    st.sidebar.divider()

    # Export path
    st.sidebar.subheader("Export")

    saved_export_path = db.get_setting("export_path", "output/export")
    export_path_str = st.sidebar.text_input(
        "Export Path",
        value=saved_export_path,
        key="export_path",
        help="Path to export converted videos",
    )

    # Save export path if changed
    if export_path_str != saved_export_path:
        db.set_setting("export_path", export_path_str)

    export_path = Path(export_path_str)

    # Show export stats if path exists
    if export_path.exists():
        mjpeg_files = list(export_path.glob("*.mjpeg"))
        total_size = sum(f.stat().st_size for f in mjpeg_files) / (1024 * 1024)
        st.sidebar.caption(f"{len(mjpeg_files)} files, {total_size:.1f} MB")

    return new_settings, export_path


def render_preset_buttons(db: Database) -> None:
    """Render preset buttons for common CYD configurations."""
    st.sidebar.subheader("Presets")

    col1, col2 = st.sidebar.columns(2)

    with col1:
        if st.button("CYD 2.8\"", use_container_width=True):
            preset = ConversionSettings(
                width=240,
                height=320,
                quality=5,
                fps=15,
                brightness=0.05,
                contrast=1.1,
            )
            db.set_setting("conversion_settings", preset.to_json())
            st.rerun()

    with col2:
        if st.button("CYD 4\"", use_container_width=True):
            preset = ConversionSettings(
                width=320,
                height=480,
                quality=5,
                fps=15,
                brightness=0.05,
                contrast=1.1,
            )
            db.set_setting("conversion_settings", preset.to_json())
            st.rerun()
