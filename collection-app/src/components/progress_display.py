import streamlit as st
from pathlib import Path
from typing import Optional
import time

from src.models.settings import ConversionSettings
from src.models.video import VideoWithState
from src.services.database import Database
from src.services.download_service import DownloadService
from src.services.conversion_service import ConversionService
from src.services.export_service import ExportService


def render_download_section(
    db: Database,
    download_service: DownloadService,
    channel_id: Optional[str] = None,
) -> None:
    """
    Render the download section.

    Args:
        db: Database instance
        download_service: Download service instance
        channel_id: Filter by channel ID
    """
    st.sidebar.divider()
    st.sidebar.subheader("Download")

    # Get selected videos that need downloading
    selected_videos = db.get_videos_with_state(
        channel_id=channel_id,
        shorts_only=True,
        selected_only=True,
    )

    # Filter to videos that haven't been downloaded
    videos_to_download = [
        v for v in selected_videos
        if not v.state.download_path
    ]

    # Count already downloaded
    already_downloaded = len(selected_videos) - len(videos_to_download)
    if already_downloaded > 0:
        st.sidebar.caption(f"**{len(videos_to_download)}** to download ({already_downloaded} already downloaded)")
    else:
        st.sidebar.caption(f"**{len(videos_to_download)}** videos to download")

    download_button = st.sidebar.button(
        "Download",
        type="secondary",
        disabled=len(videos_to_download) == 0,
        use_container_width=True,
        key="download_btn",
    )

    if download_button and videos_to_download:
        _download_videos(db, download_service, videos_to_download)


def _download_videos(
    db: Database,
    download_service: DownloadService,
    videos: list[VideoWithState],
) -> None:
    """Download a list of videos."""
    total = len(videos)
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()

    successful = 0
    failed = 0

    for idx, video_with_state in enumerate(videos):
        video = video_with_state.video
        video_id = video.id

        progress = (idx / total)
        progress_bar.progress(progress)
        status_text.text(f"Downloading {idx + 1}/{total}...")

        download_path = download_service.download_video(video_id)

        if download_path:
            db.update_video_downloaded(video_id, str(download_path))
            successful += 1
        else:
            failed += 1

    # Complete
    progress_bar.progress(1.0)
    status_text.text("Done!")

    # Show results
    if successful > 0:
        st.sidebar.success(f"Downloaded {successful} videos")
    if failed > 0:
        st.sidebar.warning(f"Failed: {failed} videos")

    time.sleep(1)
    st.rerun()


def render_convert_export_section(
    db: Database,
    conversion_service: ConversionService,
    export_service: ExportService,
    settings: ConversionSettings,
    export_path: Path,
    channel_id: Optional[str] = None,
) -> None:
    """
    Render the convert & export section.

    Args:
        db: Database instance
        conversion_service: Conversion service instance
        export_service: Export service instance
        settings: Conversion settings
        export_path: Target export path
        channel_id: Filter by channel ID
    """
    st.sidebar.divider()
    st.sidebar.subheader("Convert & Export")

    # Get selected videos that have been downloaded
    selected_videos = db.get_videos_with_state(
        channel_id=channel_id,
        shorts_only=True,
        selected_only=True,
    )

    # Filter to videos that have been downloaded
    videos_ready = [
        v for v in selected_videos
        if v.state.download_path
    ]

    # Count already exported
    already_exported = sum(1 for v in videos_ready if v.state.is_exported)

    if len(videos_ready) == 0:
        st.sidebar.caption("No downloaded videos ready")
    elif already_exported > 0:
        st.sidebar.caption(f"**{len(videos_ready)}** to convert & export ({already_exported} will be overwritten)")
    else:
        st.sidebar.caption(f"**{len(videos_ready)}** to convert & export")

    st.sidebar.caption(f"Target: `{export_path}`")

    convert_export_button = st.sidebar.button(
        "Convert & Export",
        type="primary",
        disabled=len(videos_ready) == 0,
        use_container_width=True,
        key="convert_export_btn",
    )

    if convert_export_button and videos_ready:
        _convert_and_export_videos(
            db,
            conversion_service,
            export_service,
            videos_ready,
            settings,
            export_path,
        )


def _convert_and_export_videos(
    db: Database,
    conversion_service: ConversionService,
    export_service: ExportService,
    videos: list[VideoWithState],
    settings: ConversionSettings,
    export_path: Path,
) -> None:
    """Convert and export a list of videos."""
    total = len(videos)
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()

    # Get channel names for filenames
    channels = {c.id: c.name for c in db.get_all_channels()}

    successful = 0
    failed = 0

    for idx, video_with_state in enumerate(videos):
        video = video_with_state.video
        video_id = video.id
        download_path = Path(video_with_state.state.download_path)

        progress = (idx / total)
        progress_bar.progress(progress)
        status_text.text(f"Converting {idx + 1}/{total}...")

        # Step 1: Convert
        converted_path = conversion_service.convert_video(
            video_id,
            download_path,
            settings,
        )

        if not converted_path:
            failed += 1
            continue

        db.update_video_converted(
            video_id,
            str(converted_path),
            settings.to_json(),
        )

        # Step 2: Export
        status_text.text(f"Exporting {idx + 1}/{total}...")
        channel_name = channels.get(video.channel_id)
        result = export_service.export_video(video_id, export_path, channel_name)

        if result:
            db.update_video_exported(video_id)
            successful += 1
        else:
            failed += 1

    # Create manifest
    if successful > 0:
        manifest_videos = [
            {
                "id": v.video.id,
                "title": v.video.title,
                "channel_name": channels.get(v.video.channel_id, "Unknown"),
            }
            for v in videos
        ]
        export_service.create_manifest(export_path, manifest_videos)

    # Complete
    progress_bar.progress(1.0)
    status_text.text("Done!")

    # Show results
    if successful > 0:
        st.sidebar.success(f"Exported {successful} videos")
    if failed > 0:
        st.sidebar.warning(f"Failed: {failed} videos")

    time.sleep(1)
    st.rerun()


# Keep old functions for backwards compatibility but they won't be used
def render_progress_display(
    db: Database,
    download_service: DownloadService,
    conversion_service: ConversionService,
    settings: ConversionSettings,
    channel_id: Optional[str] = None,
) -> None:
    """Legacy function - now split into render_download_section and render_convert_export_section."""
    pass


def render_export_section(
    db: Database,
    export_service: ExportService,
    export_path: Path,
    channel_id: Optional[str] = None,
) -> None:
    """Legacy function - now merged into render_convert_export_section."""
    pass
