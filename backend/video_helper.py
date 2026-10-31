import re
import urllib.request
from urllib.parse import parse_qs, urlparse


def fetch_video_metadata(platform: str, video_id: str, raw_url: str) -> dict:
    metadata = {"durationSeconds": None, "durationMinutes": None, "suggestedTitle": None}
    if platform == "youtube" and video_id:
        try:
            watch_url = f"https://www.youtube.com/watch?v={video_id}"
            req = urllib.request.Request(
                watch_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            html = urllib.request.urlopen(req, timeout=3.5).read().decode("utf-8", errors="ignore")
            # 1. Duration in seconds
            dur_sec = None
            approx_match = re.search(r'"approxDurationMs":"(\d+)"', html)
            length_match = re.search(r'"lengthSeconds":"(\d+)"', html)
            if approx_match:
                dur_sec = round(int(approx_match.group(1)) / 1000)
            elif length_match:
                dur_sec = int(length_match.group(1))
            elif True:
                iso_match = re.search(r'itemprop="duration" content="PT([^"]+)"', html)
                if iso_match:
                    iso = iso_match.group(1)
                    m = re.search(r'(\d+)M', iso)
                    s = re.search(r'(\d+)S', iso)
                    h = re.search(r'(\d+)H', iso)
                    dur_sec = (int(h.group(1)) * 3600 if h else 0) + (int(m.group(1)) * 60 if m else 0) + (int(s.group(1)) if s else 0)

            if dur_sec and dur_sec > 0:
                metadata["durationSeconds"] = dur_sec
                metadata["durationMinutes"] = round(dur_sec / 60, 2)

            # 2. Suggested Title
            title_match = re.search(r'<meta name="title" content="([^"]+)"', html)
            if not title_match:
                title_match = re.search(r'<title>([^<]+)</title>', html)
            if title_match:
                raw_title = title_match.group(1).replace(" - YouTube", "").strip()
                if raw_title:
                    metadata["suggestedTitle"] = raw_title
        except Exception:
            pass

    return metadata


def parse_video_url(url: str, fetch_meta: bool = True) -> dict:
    raw_url = (url or "").strip()
    if not raw_url:
        return {
            "platform": "other",
            "embedUrl": "",
            "trackingSupported": False,
            "videoId": "",
            "valid": False,
            "durationSeconds": None,
            "durationMinutes": None,
            "suggestedTitle": None,
            "message": "Video URL is required.",
        }

    # If the user pasted a full <iframe ... src="..."> snippet, extract the src URL automatically
    iframe_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', raw_url, re.IGNORECASE)
    if iframe_match:
        raw_url = iframe_match.group(1).strip()

    # Validate scheme
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"}:
        return {
            "platform": "other",
            "embedUrl": "",
            "trackingSupported": False,
            "videoId": "",
            "valid": False,
            "durationSeconds": None,
            "durationMinutes": None,
            "suggestedTitle": None,
            "message": "Video URL must start with http:// or https:// (or paste an <iframe> embed snippet).",
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
            meta = fetch_video_metadata("youtube", video_id, raw_url) if fetch_meta else {}
            dur_min = meta.get("durationMinutes")
            dur_msg = f" (detected duration: {dur_min} min)" if dur_min else ""
            return {
                "platform": "youtube",
                "embedUrl": f"https://www.youtube-nocookie.com/embed/{video_id}?autoplay=1&enablejsapi=1&rel=0",
                "trackingSupported": True,
                "videoId": video_id,
                "valid": True,
                "durationSeconds": meta.get("durationSeconds"),
                "durationMinutes": dur_min,
                "suggestedTitle": meta.get("suggestedTitle"),
                "message": f"YouTube video recognized{dur_msg}. In-page player with automatic playback tracking supported.",
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
                "trackingSupported": True,
                "videoId": file_id,
                "valid": True,
                "durationSeconds": None,
                "durationMinutes": None,
                "suggestedTitle": None,
                "message": "Google Drive video recognized. Embedded preview with active session progress tracking supported.",
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
            "durationSeconds": None,
            "durationMinutes": None,
            "suggestedTitle": None,
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
                "embedUrl": f"https://player.vimeo.com/video/{video_id}?autoplay=1",
                "trackingSupported": False,
                "videoId": video_id,
                "valid": True,
                "durationSeconds": None,
                "durationMinutes": None,
                "suggestedTitle": None,
                "message": "Vimeo video recognized. Embedded iframe player supported.",
            }

    # 5. Generic embeddable link
    return {
        "platform": "other",
        "embedUrl": raw_url,
        "trackingSupported": False,
        "videoId": "",
        "valid": True,
        "durationSeconds": None,
        "durationMinutes": None,
        "suggestedTitle": None,
        "message": "External video link recognized. Embedded playback may depend on provider iframe policies; automatic tracking unavailable.",
    }
