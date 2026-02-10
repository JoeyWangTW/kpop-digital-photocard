import re
from datetime import datetime
from typing import Optional

import yt_dlp

from src.models.channel import Channel
from src.models.video import Video


CUSTOM_COLLECTION_ID = "__custom__"
CUSTOM_COLLECTION_NAME = "Custom Collection"


class YouTubeService:
    """Service for fetching YouTube channel and video information."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self._youtube_api = None

        self.ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "ignoreerrors": True,
        }

    @property
    def youtube_api(self):
        """Lazy-load YouTube API client."""
        if self._youtube_api is None and self.api_key:
            try:
                from googleapiclient.discovery import build
                self._youtube_api = build("youtube", "v3", developerKey=self.api_key)
            except Exception as e:
                print(f"Failed to initialize YouTube API: {e}")
        return self._youtube_api

    def set_api_key(self, api_key: str):
        """Set or update the API key."""
        self.api_key = api_key
        self._youtube_api = None  # Reset to reinitialize

    def has_api_key(self) -> bool:
        """Check if API key is configured."""
        return bool(self.api_key)

    def extract_channel_id(self, url: str) -> Optional[str]:
        """Extract channel ID from various URL formats."""
        patterns = [
            r"youtube\.com/channel/(UC[\w-]+)",
            r"youtube\.com/@([\w.-]+)",
            r"youtube\.com/c/([\w.-]+)",
            r"youtube\.com/user/([\w.-]+)",
            r"^(UC[\w-]+)$",
            r"^@?([\w.-]+)$",
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        return None

    def get_channel_info(self, url_or_id: str) -> Optional[Channel]:
        """Get channel information from URL or ID."""
        # Try API first if available
        if self.youtube_api:
            channel = self._get_channel_info_api(url_or_id)
            if channel:
                return channel

        # Fallback to yt-dlp
        return self._get_channel_info_ytdlp(url_or_id)

    def _get_channel_info_api(self, url_or_id: str) -> Optional[Channel]:
        """Get channel info using YouTube Data API."""
        try:
            # Handle @handle format
            if url_or_id.startswith("@"):
                handle = url_or_id[1:]
                request = self.youtube_api.channels().list(
                    part="snippet",
                    forHandle=handle,
                )
            elif url_or_id.startswith("UC"):
                request = self.youtube_api.channels().list(
                    part="snippet",
                    id=url_or_id,
                )
            else:
                # Try to extract from URL
                extracted = self.extract_channel_id(url_or_id)
                if extracted and extracted.startswith("UC"):
                    request = self.youtube_api.channels().list(
                        part="snippet",
                        id=extracted,
                    )
                elif extracted:
                    # Might be a handle
                    request = self.youtube_api.channels().list(
                        part="snippet",
                        forHandle=extracted,
                    )
                else:
                    return None

            response = request.execute()
            items = response.get("items", [])

            if items:
                item = items[0]
                return Channel(
                    id=item["id"],
                    name=item["snippet"]["title"],
                    url=f"https://www.youtube.com/channel/{item['id']}",
                )

        except Exception as e:
            print(f"API error getting channel info: {e}")

        return None

    def _get_channel_info_ytdlp(self, url_or_id: str) -> Optional[Channel]:
        """Get channel info using yt-dlp."""
        if url_or_id.startswith("@"):
            url = f"https://www.youtube.com/{url_or_id}"
        elif url_or_id.startswith("UC"):
            url = f"https://www.youtube.com/channel/{url_or_id}"
        elif not url_or_id.startswith("http"):
            url = f"https://www.youtube.com/@{url_or_id}"
        else:
            url = url_or_id

        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    channel_id = info.get("channel_id") or info.get("uploader_id")
                    channel_name = info.get("channel") or info.get("uploader") or url_or_id

                    if channel_id:
                        return Channel(
                            id=channel_id,
                            name=channel_name,
                            url=url,
                        )
        except Exception as e:
            print(f"yt-dlp error getting channel info: {e}")

        return None

    def fetch_channel_videos(
        self,
        channel: Channel,
        limit: int = 50,
        shorts_only: bool = True,
    ) -> list[Video]:
        """Fetch recent videos from a channel (for regular updates)."""
        # Try API first if available (more reliable, includes dates)
        if self.youtube_api:
            videos = self._fetch_channel_videos_api(channel, limit, shorts_only)
            if videos:
                return videos

        # Fallback to yt-dlp (fetch from /shorts tab for shorts)
        videos = self._fetch_channel_videos_ytdlp(channel, limit, shorts_only)

        # Backfill dates if API is available
        if videos and self.youtube_api:
            videos = self._backfill_video_dates(videos)

        return videos

    def fetch_all_channel_videos(
        self,
        channel: Channel,
        shorts_only: bool = True,
        progress_callback=None,
    ) -> list[Video]:
        """
        Fetch ALL videos from a channel with pagination.

        Args:
            channel: Channel to fetch from
            shorts_only: Only include Shorts (<=60s)
            progress_callback: Function(fetched, total_estimate, status) for progress

        Returns:
            List of all videos
        """
        # For shorts, use yt-dlp to get from /shorts tab (most accurate)
        # Then backfill dates using API
        if shorts_only:
            if progress_callback:
                progress_callback(0, 100, "Fetching shorts...")
            videos = self._fetch_channel_videos_ytdlp(channel, 500, shorts_only=True)

            # Backfill missing dates using API
            if self.youtube_api and videos:
                if progress_callback:
                    progress_callback(len(videos), len(videos), "Fetching dates...")
                videos = self._backfill_video_dates(videos)

            if progress_callback:
                progress_callback(len(videos), len(videos), "Done")
            return videos

        # For non-shorts, use API if available for better pagination
        if self.youtube_api:
            return self._fetch_all_videos_api(channel, shorts_only, progress_callback)
        else:
            if progress_callback:
                progress_callback(0, 100, "Fetching with yt-dlp (limited)...")
            videos = self._fetch_channel_videos_ytdlp(channel, 200, shorts_only)
            if progress_callback:
                progress_callback(len(videos), len(videos), "Done")
            return videos

    def _fetch_all_videos_api(
        self,
        channel: Channel,
        shorts_only: bool,
        progress_callback=None,
    ) -> list[Video]:
        """Fetch all videos using YouTube API with pagination."""
        videos = []

        try:
            # Get uploads playlist ID
            channel_response = self.youtube_api.channels().list(
                part="contentDetails,statistics",
                id=channel.id,
            ).execute()

            if not channel_response.get("items"):
                return videos

            item = channel_response["items"][0]
            uploads_playlist_id = (
                item["contentDetails"]["relatedPlaylists"]["uploads"]
            )

            # Estimate total videos
            total_estimate = int(item.get("statistics", {}).get("videoCount", 100))
            if progress_callback:
                progress_callback(0, total_estimate, "Starting fetch...")

            # Paginate through all videos
            next_page_token = None
            fetched = 0

            while True:
                if progress_callback:
                    progress_callback(fetched, total_estimate, f"Fetching page... ({fetched} videos)")

                playlist_response = self.youtube_api.playlistItems().list(
                    part="snippet,contentDetails",
                    playlistId=uploads_playlist_id,
                    maxResults=50,
                    pageToken=next_page_token,
                ).execute()

                video_ids = [
                    item["contentDetails"]["videoId"]
                    for item in playlist_response.get("items", [])
                ]

                if not video_ids:
                    break

                # Get video details
                videos_response = self.youtube_api.videos().list(
                    part="snippet,contentDetails",
                    id=",".join(video_ids),
                ).execute()

                for item in videos_response.get("items", []):
                    video = self._api_item_to_video(item, channel.id)
                    if video:
                        if shorts_only and not video.is_short:
                            continue
                        videos.append(video)

                fetched += len(video_ids)
                next_page_token = playlist_response.get("nextPageToken")

                if not next_page_token:
                    break

            if progress_callback:
                progress_callback(len(videos), len(videos), "Done!")

        except Exception as e:
            print(f"API error fetching all videos: {e}")
            if progress_callback:
                progress_callback(0, 0, f"Error: {e}")

        return videos

    def _fetch_channel_videos_api(
        self,
        channel: Channel,
        limit: int,
        shorts_only: bool,
    ) -> list[Video]:
        """Fetch videos using YouTube Data API."""
        videos = []

        try:
            # First, get the uploads playlist ID
            channel_response = self.youtube_api.channels().list(
                part="contentDetails",
                id=channel.id,
            ).execute()

            if not channel_response.get("items"):
                return videos

            uploads_playlist_id = (
                channel_response["items"][0]
                ["contentDetails"]["relatedPlaylists"]["uploads"]
            )

            # Fetch videos from uploads playlist
            next_page_token = None
            fetched = 0

            while fetched < limit:
                playlist_response = self.youtube_api.playlistItems().list(
                    part="snippet,contentDetails",
                    playlistId=uploads_playlist_id,
                    maxResults=min(50, limit - fetched),
                    pageToken=next_page_token,
                ).execute()

                video_ids = [
                    item["contentDetails"]["videoId"]
                    for item in playlist_response.get("items", [])
                ]

                if not video_ids:
                    break

                # Get video details (duration, etc.)
                videos_response = self.youtube_api.videos().list(
                    part="snippet,contentDetails",
                    id=",".join(video_ids),
                ).execute()

                for item in videos_response.get("items", []):
                    video = self._api_item_to_video(item, channel.id)
                    if video:
                        # Filter for shorts if requested
                        if shorts_only and not video.is_short:
                            continue
                        videos.append(video)

                fetched += len(video_ids)
                next_page_token = playlist_response.get("nextPageToken")

                if not next_page_token:
                    break

        except Exception as e:
            print(f"API error fetching videos: {e}")

        return videos

    def _api_item_to_video(self, item: dict, channel_id: str) -> Optional[Video]:
        """Convert YouTube API video item to Video object."""
        try:
            video_id = item["id"]
            snippet = item["snippet"]
            content_details = item.get("contentDetails", {})

            # Parse duration (ISO 8601: PT1M30S)
            duration_str = content_details.get("duration", "PT0S")
            duration = self._parse_duration(duration_str)

            # Get best thumbnail
            thumbnails = snippet.get("thumbnails", {})
            thumbnail_url = None
            for quality in ["maxres", "high", "medium", "default"]:
                if quality in thumbnails:
                    thumbnail_url = thumbnails[quality]["url"]
                    break

            # Parse publish date
            published_at = None
            pub_str = snippet.get("publishedAt")
            if pub_str:
                try:
                    published_at = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

            # Determine if it's a short
            # Must be <= 60s AND have shorts indicators
            title = snippet.get("title", "") or ""
            description = snippet.get("description", "") or ""
            text = f"{title} {description}".lower()

            is_short_duration = duration <= 60
            has_shorts_tag = "#shorts" in text or "#short" in text

            # Check thumbnail aspect ratio as hint (shorts use vertical thumbnails)
            # Shorts typically have 405x720 or similar vertical thumbnails
            is_vertical_thumb = False
            for quality in ["maxres", "high", "medium", "default"]:
                if quality in thumbnails:
                    thumb = thumbnails[quality]
                    w = thumb.get("width", 0)
                    h = thumb.get("height", 0)
                    if w > 0 and h > 0:
                        is_vertical_thumb = h > w
                    break

            # Be stricter: require duration AND (hashtag OR vertical thumbnail)
            is_short = is_short_duration and (has_shorts_tag or is_vertical_thumb)

            return Video(
                id=video_id,
                channel_id=channel_id,
                title=snippet.get("title", "Untitled"),
                description=snippet.get("description"),
                thumbnail_url=thumbnail_url,
                duration=duration,
                published_at=published_at,
                is_short=is_short,
            )

        except Exception as e:
            print(f"Error parsing video item: {e}")
            return None

    def _parse_duration(self, duration_str: str) -> int:
        """Parse ISO 8601 duration (PT1H2M30S) to seconds."""
        import re
        pattern = r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"
        match = re.match(pattern, duration_str)
        if not match:
            return 0

        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)

        return hours * 3600 + minutes * 60 + seconds

    def _backfill_video_dates(self, videos: list[Video]) -> list[Video]:
        """Backfill missing published_at dates using YouTube API."""
        if not self.youtube_api:
            return videos

        # Find videos missing dates
        missing_dates = [v for v in videos if v.published_at is None]
        if not missing_dates:
            return videos

        # Fetch dates in batches of 50 (API limit)
        video_dates = {}
        for i in range(0, len(missing_dates), 50):
            batch = missing_dates[i:i+50]
            video_ids = [v.id for v in batch]

            try:
                response = self.youtube_api.videos().list(
                    part="snippet",
                    id=",".join(video_ids),
                ).execute()

                for item in response.get("items", []):
                    vid = item["id"]
                    pub_str = item["snippet"].get("publishedAt")
                    if pub_str:
                        try:
                            video_dates[vid] = datetime.fromisoformat(
                                pub_str.replace("Z", "+00:00")
                            )
                        except ValueError:
                            pass
            except Exception as e:
                print(f"Error fetching video dates: {e}")

        # Update videos with dates
        for video in videos:
            if video.id in video_dates:
                video.published_at = video_dates[video.id]

        return videos

    def _fetch_channel_videos_ytdlp(
        self,
        channel: Channel,
        limit: int,
        shorts_only: bool,
    ) -> list[Video]:
        """Fetch videos using yt-dlp."""
        if shorts_only:
            url = f"https://www.youtube.com/channel/{channel.id}/shorts"
        else:
            url = f"https://www.youtube.com/channel/{channel.id}/videos"

        opts = {
            **self.ydl_opts,
            "playlistend": limit,
        }

        videos = []

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

                if not info:
                    return videos

                entries = info.get("entries", [])
                if not entries:
                    return videos

                for entry in entries:
                    if not entry:
                        continue

                    video = self._entry_to_video(entry, channel.id, from_shorts_tab=shorts_only)
                    if video:
                        videos.append(video)

        except Exception as e:
            print(f"yt-dlp error fetching videos: {e}")

        return videos

    def _entry_to_video(self, entry: dict, channel_id: str, from_shorts_tab: bool = False) -> Optional[Video]:
        """Convert a yt-dlp entry to a Video object."""
        video_id = entry.get("id") or entry.get("url", "").split("/")[-1]
        if not video_id:
            return None

        title = entry.get("title") or "Untitled"
        duration = entry.get("duration") or 0

        # Get thumbnail - prefer high quality
        thumbnail_url = None
        thumbnails = entry.get("thumbnails", [])
        if thumbnails:
            sorted_thumbs = sorted(
                thumbnails,
                key=lambda t: t.get("height", 0) * t.get("width", 0),
                reverse=True,
            )
            thumbnail_url = sorted_thumbs[0].get("url")
        if not thumbnail_url:
            thumbnail_url = entry.get("thumbnail")

        # Use standard YouTube thumbnail URL if none found
        if not thumbnail_url:
            thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

        # Parse upload date
        published_at = None
        upload_date = entry.get("upload_date")
        if upload_date:
            try:
                published_at = datetime.strptime(upload_date, "%Y%m%d")
            except ValueError:
                pass

        # If fetched from /shorts tab, it's definitely a short
        if from_shorts_tab:
            is_short = True
        else:
            is_short = self._is_youtube_short(entry)

        return Video(
            id=video_id,
            channel_id=channel_id,
            title=title,
            duration=duration,
            thumbnail_url=thumbnail_url,
            description=entry.get("description"),
            published_at=published_at,
            width=entry.get("width"),
            height=entry.get("height"),
            is_short=is_short,
        )

    def _is_youtube_short(self, video_info: dict) -> bool:
        """Determine if a video is a YouTube Short."""
        duration = video_info.get("duration") or 0
        width = video_info.get("width") or 0
        height = video_info.get("height") or 0

        is_short_duration = duration <= 60
        is_vertical = height > width if (width and height) else False

        title = video_info.get("title", "") or ""
        description = video_info.get("description", "") or ""
        text = f"{title} {description}".lower()
        has_shorts_tag = "#shorts" in text or "#short" in text

        webpage_url = video_info.get("webpage_url", "") or ""
        from_shorts_tab = "/shorts/" in webpage_url

        return is_short_duration and (is_vertical or has_shorts_tag or from_shorts_tab)

    def extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from various YouTube URL formats."""
        patterns = [
            r"youtube\.com/watch\?v=([\w-]+)",
            r"youtube\.com/shorts/([\w-]+)",
            r"youtu\.be/([\w-]+)",
            r"^([\w-]{11})$",  # Direct video ID
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        return None

    def get_video_info(self, url_or_id: str) -> Optional[Video]:
        """Get video information from a URL or video ID."""
        video_id = self.extract_video_id(url_or_id)
        if not video_id:
            return None

        # Try API first if available
        if self.youtube_api:
            video = self._get_video_info_api(video_id)
            if video:
                return video

        # Fallback to yt-dlp
        return self._get_video_info_ytdlp(video_id)

    def _get_video_info_api(self, video_id: str) -> Optional[Video]:
        """Get video info using YouTube Data API."""
        try:
            response = self.youtube_api.videos().list(
                part="snippet,contentDetails",
                id=video_id,
            ).execute()

            items = response.get("items", [])
            if items:
                return self._api_item_to_video(items[0], CUSTOM_COLLECTION_ID)

        except Exception as e:
            print(f"API error getting video info: {e}")

        return None

    def _get_video_info_ytdlp(self, video_id: str) -> Optional[Video]:
        """Get video info using yt-dlp."""
        url = f"https://www.youtube.com/watch?v={video_id}"

        try:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    return self._entry_to_video(info, CUSTOM_COLLECTION_ID, from_shorts_tab=False)
        except Exception as e:
            print(f"yt-dlp error getting video info: {e}")

        return None
