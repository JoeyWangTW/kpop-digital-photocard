#!/usr/bin/env python3
"""
CYD Shorts Converter - YouTube Shorts to MJPEG Converter for CYD Display

A Streamlit application for fetching YouTube Shorts from channels,
selecting videos, and converting them to MJPEG format optimized for
the CYD (Cheap Yellow Display) ESP32 device.

Usage:
    streamlit run app.py
"""

import streamlit as st

from src.services.database import Database
from src.services.youtube_service import YouTubeService
from src.services.download_service import DownloadService
from src.services.conversion_service import ConversionService
from src.services.export_service import ExportService
from src.utils.ffmpeg_utils import check_all_dependencies
from src.utils.thumbnail_cache import ThumbnailCache
from src.components.channel_sidebar import render_channel_sidebar
from src.components.video_grid import render_video_grid
from src.components.settings_panel import render_settings_panel, render_preset_buttons
from src.components.progress_display import (
    render_download_section,
    render_convert_export_section,
)


# Page configuration
st.set_page_config(
    page_title="CYD Shorts Converter",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)


def check_dependencies():
    """Check and display dependency status."""
    deps = check_all_dependencies()

    if not deps["all_ok"]:
        st.error("Missing Dependencies")

        if not deps["ffmpeg"]["available"]:
            st.warning("FFmpeg not found")
            with st.expander("FFmpeg Installation Instructions"):
                st.code(deps["ffmpeg"]["instructions"])

        if not deps["yt-dlp"]["available"]:
            st.warning("yt-dlp not found")
            with st.expander("yt-dlp Installation Instructions"):
                st.code(deps["yt-dlp"]["instructions"])

        st.stop()

    return deps


@st.cache_resource
def get_database():
    """Get or create database connection."""
    return Database()


def get_youtube_service(api_key: str = None):
    """Get YouTube service instance with optional API key."""
    # Don't cache this since API key can change
    return YouTubeService(api_key=api_key)


@st.cache_resource
def get_download_service():
    """Get download service instance."""
    return DownloadService()


@st.cache_resource
def get_conversion_service():
    """Get conversion service instance."""
    return ConversionService()


@st.cache_resource
def get_export_service():
    """Get export service instance."""
    return ExportService()


@st.cache_resource
def get_thumbnail_cache():
    """Get thumbnail cache instance."""
    return ThumbnailCache()


def main():
    """Main application entry point."""
    # Header
    st.title("🎬 CYD Shorts Converter")
    st.caption("Fetch YouTube Shorts and convert to MJPEG for CYD display")

    # Check dependencies
    deps = check_dependencies()

    # Initialize database first (needed for API key)
    db = get_database()

    # API Key configuration in sidebar
    with st.sidebar:
        with st.expander("YouTube API Key", expanded=False):
            st.caption(
                "Optional: Add a YouTube Data API key for better video fetching. "
                "[Get one here](https://console.cloud.google.com/apis/credentials)"
            )
            saved_api_key = db.get_setting("youtube_api_key", "")
            api_key = st.text_input(
                "API Key",
                value=saved_api_key,
                type="password",
                key="api_key_input",
            )
            if api_key != saved_api_key:
                db.set_setting("youtube_api_key", api_key)

            if api_key:
                st.success("API key configured")
            else:
                st.info("Using yt-dlp (limited)")

        with st.expander("System Info", expanded=False):
            if deps["ffmpeg"]["available"]:
                st.caption(f"FFmpeg: {deps['ffmpeg']['version'][:50]}...")
            if deps["yt-dlp"]["available"]:
                st.caption(f"yt-dlp: {deps['yt-dlp']['version']}")

    # Initialize services
    yt_service = get_youtube_service(api_key=api_key if api_key else None)
    download_service = get_download_service()
    conversion_service = get_conversion_service()
    export_service = get_export_service()
    thumbnail_cache = get_thumbnail_cache()

    # Render sidebar (channels)
    selected_channel = render_channel_sidebar(db, yt_service)

    # Render settings panel in main area
    settings, export_path = render_settings_panel(db)
    render_preset_buttons(db)

    # Download section in sidebar
    render_download_section(
        db=db,
        download_service=download_service,
        channel_id=selected_channel,
    )

    # Convert & Export section in sidebar
    render_convert_export_section(
        db=db,
        conversion_service=conversion_service,
        export_service=export_service,
        settings=settings,
        export_path=export_path,
        channel_id=selected_channel,
    )

    # Main content area
    # Filter options
    col1, col2, col3 = st.columns([1, 1, 3])
    with col1:
        new_only = st.checkbox("New Only", value=False)
    with col2:
        selected_only = st.checkbox("Selected Only", value=False)
    with col3:
        keyword_filter = st.text_input(
            "Search",
            placeholder="Filter by keyword...",
            label_visibility="collapsed",
        )

    # Video grid
    render_video_grid(
        db=db,
        thumbnail_cache=thumbnail_cache,
        channel_id=selected_channel,
        new_only=new_only,
        selected_only=selected_only,
        keyword_filter=keyword_filter,
    )


if __name__ == "__main__":
    main()
