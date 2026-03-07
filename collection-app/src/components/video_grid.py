import streamlit as st
from typing import Optional

from src.models.video import VideoWithState
from src.services.database import Database
from src.services.youtube_service import CUSTOM_COLLECTION_ID
from src.utils.thumbnail_cache import ThumbnailCache

# CSS for consistent card styling
GRID_CSS = """
<style>
div[data-testid="column"] {
    padding: 4px;
}
.stCheckbox {
    padding-top: 0 !important;
}
</style>
"""


def render_video_grid(
    db: Database,
    thumbnail_cache: ThumbnailCache,
    channel_id: Optional[str] = None,
    new_only: bool = False,
    selected_only: bool = False,
    keyword_filter: str = "",
    columns: int = 4,
) -> list[str]:
    """
    Render the video thumbnail grid with selection checkboxes.
    """
    # Inject CSS
    st.markdown(GRID_CSS, unsafe_allow_html=True)

    # Custom collection shows all videos (including regular/horizontal)
    shorts_only = channel_id != CUSTOM_COLLECTION_ID

    # Get videos
    videos = db.get_videos_with_state(
        channel_id=channel_id,
        shorts_only=shorts_only,
        new_only=new_only,
        selected_only=selected_only,
    )

    # Apply keyword filter
    if keyword_filter:
        keyword_lower = keyword_filter.lower()
        videos = [
            v for v in videos
            if keyword_lower in v.video.title.lower()
        ]

    if not videos:
        if new_only:
            st.info("No new videos. Try fetching from channels.")
        elif selected_only:
            st.info("No videos selected.")
        else:
            st.info("No videos found. Add a channel and fetch videos to get started.")
        return []

    # Stats bar
    counts = db.get_video_counts(channel_id, shorts_only=shorts_only)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total", counts["total"])
    col2.metric("New", counts["new"])
    col3.metric("Selected", counts["selected"])
    col4.metric("Converted", counts["converted"])

    st.divider()

    # Bulk actions
    action_cols = st.columns([1, 1, 1, 3])
    with action_cols[0]:
        if st.button("Select All", use_container_width=True):
            db.select_all_videos(channel_id, shorts_only=shorts_only)
            st.rerun()
    with action_cols[1]:
        if st.button("Deselect All", use_container_width=True):
            db.deselect_all_videos(channel_id, shorts_only=shorts_only)
            st.rerun()
    with action_cols[2]:
        if st.button("Invert", use_container_width=True):
            db.invert_selection(channel_id, shorts_only=shorts_only)
            st.rerun()

    st.divider()

    # Render video grid
    selected_ids = []

    # Process videos in rows
    for row_start in range(0, len(videos), columns):
        row_videos = videos[row_start:row_start + columns]
        cols = st.columns(columns)

        for col_idx, video_with_state in enumerate(row_videos):
            video = video_with_state.video
            state = video_with_state.state

            with cols[col_idx]:
                # Thumbnail - use st.image for proper rendering
                thumbnail_url = video.thumbnail_url
                if not thumbnail_url:
                    thumbnail_url = f"https://i.ytimg.com/vi/{video.id}/hqdefault.jpg"

                # Video URL for linking
                video_url = video.shorts_url if video.is_short else video.youtube_url

                # Try cached thumbnail first
                cached = thumbnail_cache.get_or_download(video.id, thumbnail_url)
                if cached and cached.exists():
                    st.image(str(cached), width="stretch")
                else:
                    st.image(thumbnail_url, width="stretch")

                # Build badges
                badges = []
                if state.is_new:
                    badges.append(":red[NEW]")
                if state.is_converted:
                    badges.append(":green[DONE]")

                # Truncate title
                title = video.title
                if len(title) > 50:
                    title = title[:47] + "..."

                # Title as clickable link
                st.markdown(f"[{title}]({video_url})")

                # Duration and badges
                badge_str = " ".join(badges)
                st.caption(f"**{video.duration_str}** {badge_str}")

                # Selection checkbox
                is_selected = st.checkbox(
                    "Select",
                    value=state.is_selected,
                    key=f"sel_{video.id}",
                    label_visibility="collapsed",
                )

                # Update selection if changed
                if is_selected != state.is_selected:
                    db.update_video_selected(video.id, is_selected)
                    if state.is_new:
                        db.update_video_seen(video.id)

                if is_selected:
                    selected_ids.append(video.id)

    return selected_ids
