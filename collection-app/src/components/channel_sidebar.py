import streamlit as st
from typing import Optional

from src.models.channel import Channel
from src.services.database import Database
from src.services.youtube_service import (
    YouTubeService,
    CUSTOM_COLLECTION_ID,
    CUSTOM_COLLECTION_NAME,
)


def _ensure_custom_collection(db: Database) -> None:
    """Ensure the custom collection pseudo-channel exists."""
    existing = db.get_channel(CUSTOM_COLLECTION_ID)
    if not existing:
        custom_channel = Channel(
            id=CUSTOM_COLLECTION_ID,
            name=CUSTOM_COLLECTION_NAME,
            url="",
        )
        db.add_channel(custom_channel)


def _get_display_name(channel_id: str, channels: list) -> str:
    """Get display name for channel ID."""
    if channel_id == "all":
        return "All"
    if channel_id == CUSTOM_COLLECTION_ID:
        return f"📁 {CUSTOM_COLLECTION_NAME}"
    return next((c.name for c in channels if c.id == channel_id), channel_id)


def render_channel_sidebar(db: Database, yt_service: YouTubeService) -> Optional[str]:
    """
    Render the channel management sidebar.

    Args:
        db: Database instance
        yt_service: YouTube service instance

    Returns:
        Selected channel ID or None for all channels
    """
    # Ensure custom collection exists
    _ensure_custom_collection(db)

    st.sidebar.header("Channels")

    # Add channel section
    with st.sidebar.expander("Add Channel", expanded=False):
        channel_input = st.text_input(
            "Channel URL or @handle",
            placeholder="@channelname or youtube.com/...",
            key="channel_input",
        )

        if st.button("Add Channel", type="primary", use_container_width=True):
            if channel_input:
                with st.spinner("Fetching channel info..."):
                    channel = yt_service.get_channel_info(channel_input)
                    if channel:
                        db.add_channel(channel)
                        st.success(f"Added: {channel.name}")
                        st.rerun()
                    else:
                        st.error("Could not find channel. Check the URL or handle.")

    # Add video links section (Custom Collection)
    with st.sidebar.expander("📁 Add Video Links", expanded=False):
        video_links = st.text_area(
            "Paste video URLs (one per line)",
            placeholder="https://youtube.com/shorts/xxxxx\nhttps://youtu.be/xxxxx",
            key="video_links_input",
            height=100,
        )

        if st.button("Add Videos", type="primary", use_container_width=True, key="add_videos_btn"):
            if video_links:
                lines = [l.strip() for l in video_links.strip().split("\n") if l.strip()]
                added = 0
                failed = 0

                progress = st.progress(0)
                status = st.empty()

                for i, link in enumerate(lines):
                    status.text(f"Processing {i + 1}/{len(lines)}...")
                    progress.progress((i + 1) / len(lines))

                    video = yt_service.get_video_info(link)
                    if video:
                        # Ensure it's assigned to custom collection and marked as viewable
                        video.channel_id = CUSTOM_COLLECTION_ID
                        video.is_short = True  # Always show in grid
                        if db.add_video(video):
                            added += 1
                        else:
                            # Video exists - update it to show in custom collection
                            db.update_video_for_custom_collection(video.id)
                            added += 1
                    else:
                        failed += 1

                progress.empty()
                status.empty()

                if added > 0:
                    st.success(f"Added {added} video(s)")
                if failed > 0:
                    st.warning(f"Failed to add {failed} video(s)")
                if added > 0:
                    st.rerun()

    st.sidebar.divider()

    # Channel list (excluding custom collection from regular list)
    all_channels = db.get_all_channels()
    channels = [c for c in all_channels if c.id != CUSTOM_COLLECTION_ID]
    custom_collection = next((c for c in all_channels if c.id == CUSTOM_COLLECTION_ID), None)

    # Build options: All, Custom Collection, then channels
    options = ["all"]
    if custom_collection:
        options.append(CUSTOM_COLLECTION_ID)
    options.extend([c.id for c in channels])

    if not channels and not custom_collection:
        st.sidebar.info("No channels added yet. Add a channel to get started!")
        return None

    # All channels option
    selected_channel = st.sidebar.radio(
        "View",
        options=options,
        format_func=lambda x: _get_display_name(x, channels),
        key="selected_channel",
    )

    # Show video counts per channel
    if custom_collection:
        counts = db.get_video_counts(CUSTOM_COLLECTION_ID)
        if counts["total"] > 0:
            col1, col2 = st.sidebar.columns([3, 1])
            with col1:
                new_badge = f" ({counts['new']} new)" if counts['new'] > 0 else ""
                st.caption(f"📁 {CUSTOM_COLLECTION_NAME}{new_badge}")
            with col2:
                st.caption(f"{counts['total']}")

    for channel in channels:
        counts = db.get_video_counts(channel.id)
        col1, col2 = st.sidebar.columns([3, 1])
        with col1:
            new_badge = f" ({counts['new']} new)" if counts['new'] > 0 else ""
            st.caption(f"{channel.name}{new_badge}")
        with col2:
            st.caption(f"{counts['total']}")

    st.sidebar.divider()

    # Fetch actions (only for real channels, not custom collection)
    if selected_channel != CUSTOM_COLLECTION_ID:
        st.sidebar.subheader("Fetch Videos")

        # Quick fetch (recent videos only)
        col1, col2 = st.sidebar.columns(2)

        with col1:
            if st.button("Fetch New", use_container_width=True, help="Fetch recent videos to find new ones"):
                if selected_channel != "all":
                    channel = db.get_channel(selected_channel)
                    if channel:
                        _fetch_recent_videos(db, yt_service, channel)
                else:
                    _fetch_recent_all_channels(db, yt_service, channels)

        with col2:
            if st.button("Remove", use_container_width=True, type="secondary",
                         disabled=selected_channel == "all"):
                if selected_channel != "all":
                    db.delete_channel(selected_channel)
                    st.rerun()

        # Full sync (for initial fetch or complete refresh)
        if selected_channel != "all":
            channel = db.get_channel(selected_channel)
            if channel:
                counts = db.get_video_counts(channel.id)

                # Show full sync option
                if counts["total"] == 0:
                    st.sidebar.warning("No videos yet. Run a full sync to fetch all Shorts.")

                if st.sidebar.button(
                    "Full Sync (All Videos)",
                    use_container_width=True,
                    type="primary" if counts["total"] == 0 else "secondary",
                    help="Fetch ALL videos from channel. Use for initial sync or complete refresh.",
                ):
                    _full_sync_channel(db, yt_service, channel)
        else:
            # Full sync for all channels
            if st.sidebar.button(
                "Full Sync All Channels",
                use_container_width=True,
                type="secondary",
                help="Fetch ALL videos from all channels. This may take a while.",
            ):
                _full_sync_all_channels(db, yt_service, channels)

    return selected_channel if selected_channel != "all" else None


def _fetch_recent_videos(db: Database, yt_service: YouTubeService, channel):
    """Fetch recent videos from a single channel."""
    with st.sidebar.status(f"Fetching recent from {channel.name}...") as status:
        videos = yt_service.fetch_channel_videos(channel, limit=50)
        new_count = 0
        for video in videos:
            if db.add_video(video):
                new_count += 1
        db.update_channel_fetched(channel.id)
        status.update(label=f"Found {new_count} new videos", state="complete")

    st.rerun()


def _fetch_recent_all_channels(db: Database, yt_service: YouTubeService, channels):
    """Fetch recent videos from all channels."""
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    total_new = 0

    for i, channel in enumerate(channels):
        status_text.text(f"Fetching: {channel.name}")
        videos = yt_service.fetch_channel_videos(channel, limit=50)
        for video in videos:
            if db.add_video(video):
                total_new += 1
        db.update_channel_fetched(channel.id)
        progress_bar.progress((i + 1) / len(channels))

    status_text.text(f"Done! Found {total_new} new videos")
    st.rerun()


def _full_sync_channel(db: Database, yt_service: YouTubeService, channel):
    """Full sync: fetch ALL videos from a channel with progress."""
    st.sidebar.info(f"Starting full sync for {channel.name}...")

    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()

    def progress_callback(fetched, total, status):
        if total > 0:
            progress_bar.progress(min(fetched / total, 1.0))
        status_text.text(status)

    videos = yt_service.fetch_all_channel_videos(
        channel,
        shorts_only=True,
        progress_callback=progress_callback,
    )

    # Add videos to database
    status_text.text("Saving to database...")
    new_count = 0
    for i, video in enumerate(videos):
        if db.add_video(video):
            new_count += 1
        if i % 50 == 0:
            progress_bar.progress(min((i + 1) / len(videos), 1.0))

    db.update_channel_fetched(channel.id)

    progress_bar.progress(1.0)
    status_text.text(f"Done! Added {new_count} new videos ({len(videos)} total Shorts)")

    st.sidebar.success(f"Synced {len(videos)} Shorts from {channel.name}")
    st.rerun()


def _full_sync_all_channels(db: Database, yt_service: YouTubeService, channels):
    """Full sync all channels."""
    overall_progress = st.sidebar.progress(0)
    channel_status = st.sidebar.empty()
    detail_status = st.sidebar.empty()

    total_new = 0
    total_videos = 0

    for i, channel in enumerate(channels):
        channel_status.text(f"Channel {i + 1}/{len(channels)}: {channel.name}")

        def progress_callback(fetched, total, status):
            detail_status.text(status)

        videos = yt_service.fetch_all_channel_videos(
            channel,
            shorts_only=True,
            progress_callback=progress_callback,
        )

        for video in videos:
            if db.add_video(video):
                total_new += 1
        total_videos += len(videos)
        db.update_channel_fetched(channel.id)

        overall_progress.progress((i + 1) / len(channels))

    channel_status.text(f"Done! {total_new} new videos from {len(channels)} channels")
    detail_status.text(f"Total: {total_videos} Shorts")

    st.rerun()
