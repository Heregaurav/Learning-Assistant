import re
from urllib.parse import parse_qs, urlparse


def parse_video_url(url: str) -> dict:
    raw_url = (url or "").strip()
    if not raw_url:
        return {
            "platform": "other",
            "embedUrl": "",
            "trackingSupported": False,
            "videoId": "",
            "valid": False,
            "message": "Video URL is required.",
        }

    # Validate scheme
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"}:
        return {
            "platform": "other",
            "embedUrl": "",
            "trackingSupported": False,
            "videoId": "",
            "valid": False,
            "message": "Video URL must start with http:// or https://.",
        }

    # 1. YouTube
    yt_patterns = [
        r"(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?(?:.*&)?v=([a-zA-Z0-9_-]{11})",
        r"(?:https?:\/\/)?(?:www\.)?youtu\.be\/([a-zA-Z0-9_-]{11})",
        r"(?:https?:\/\/)?(?:www\.)?youtube\.com\/embed\/([a-zA-Z0-9_-]{11})",
        r"(?:https?:\/\/)?(?:www\.)?youtube\.com\/shorts\/([a-zA-Z0-9_-]{11})",
        r"(?:https?:\/\/)?(?:www\.)?youtube-nocookie\.com\/embed\/([a-zA-Z0-9_-]{11})",
    ]
    for pattern in yt_patterns:
        match = re.search(pattern, raw_url)
        if match:
            video_id = match.group(1)
            return {
                "platform": "youtube",
                "embedUrl": f"https://www.youtube.com/embed/{video_id}?enablejsapi=1&rel=0",
                "trackingSupported": True,
                "videoId": video_id,
                "valid": True,
                "message": "YouTube video recognized. In-page player with automatic playback tracking supported.",
            }

    # 2. Google Drive
    gdrive_patterns = [
        r"drive\.google\.com\/file\/d\/([a-zA-Z0-9_-]+)",
        r"drive\.google\.com\/open\?id=([a-zA-Z0-9_-]+)",
        r"docs\.google\.com\/file\/d\/([a-zA-Z0-9_-]+)",
    ]
    for pattern in gdrive_patterns:
        match = re.search(pattern, raw_url)
        if match:
            file_id = match.group(1)
            return {
                "platform": "gdrive",
                "embedUrl": f"https://drive.google.com/file/d/{file_id}/preview",
                "trackingSupported": False,
                "videoId": file_id,
                "valid": True,
                "message": "Google Drive video recognized. Embedded preview supported. Note: Google Drive iframes do not permit external playback progress tracking.",
            }

    # 3. Direct video file (MP4, WebM, etc.)
    clean_path = parsed.path.lower()
    if clean_path.endswith((".mp4", ".webm", ".m4v", ".ogv", ".mov")):
        return {
            "platform": "direct",
            "embedUrl": raw_url,
            "trackingSupported": True,
            "videoId": parsed.path.split("/")[-1],
            "valid": True,
            "message": "Direct HTML5 video source recognized. In-page player with automatic playback tracking supported.",
        }

    # 4. Vimeo
    vimeo_patterns = [
        r"vimeo\.com\/(\d+)",
        r"player\.vimeo\.com\/video\/(\d+)",
    ]
    for pattern in vimeo_patterns:
        match = re.search(pattern, raw_url)
        if match:
            video_id = match.group(1)
            return {
                "platform": "vimeo",
                "embedUrl": f"https://player.vimeo.com/video/{video_id}",
                "trackingSupported": False,
                "videoId": video_id,
                "valid": True,
                "message": "Vimeo video recognized. Embedded iframe player supported.",
            }

    # 5. Generic embeddable link
    return {
        "platform": "other",
        "embedUrl": raw_url,
        "trackingSupported": False,
        "videoId": "",
        "valid": True,
        "message": "External video link recognized. Embedded playback may depend on provider iframe policies; automatic tracking unavailable.",
    }
