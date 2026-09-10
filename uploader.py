"""Upload rendered podcast videos to YouTube and Facebook.

Dependencies are installed on demand; missing packages raise ImportError with
an install hint so the caller can fail fast.
"""

import os
import sys

# ---------------------------------------------------------------------------
# Lazy imports with hints
# ---------------------------------------------------------------------------
def _require(package: str, install_hint: str) -> None:
    if package not in sys.modules:
        try:
            __import__(package)
        except ImportError as exc:
            raise ImportError(
                f"Missing dependency for uploader: {package}. "
                f"Install with: {install_hint}"
            ) from exc


def _require_google() -> None:
    _require("google.oauth2.credentials", "pip install google-api-python-client google-auth-oauthlib")
    _require("googleapiclient.discovery", "pip install google-api-python-client google-auth-oauthlib")
    _require("googleapiclient.http", "pip install google-api-python-client google-auth-oauthlib")
    _require("google_auth_oauthlib.flow", "pip install google-api-python-client google-auth-oauthlib")


def _require_requests() -> None:
    _require("requests", "pip install requests")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log(level: str, msg: str) -> None:
    print(f"[{level}] {msg}")


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def upload_to_youtube(
    video_path: str,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "22",  # People & Blogs
    privacy_status: str = "private",
    credentials_path: str = "credentials.json",
    token_path: str = "token.json",
) -> str:
    """Upload a video to YouTube via OAuth2.

    On first run, opens a browser for consent and saves the token to
    ``token_path`` for subsequent calls.

    Returns the YouTube video ID on success.
    """
    _require_google()

    if not os.path.isfile(video_path):
        log("ERROR", f"Video file not found: {video_path}")
        raise SystemExit(1)

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, YOUTUBE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                log("ERROR", f"YouTube credentials file not found: {credentials_path}")
                log("ERROR", "Download OAuth client JSON from Google Cloud Console.")
                raise SystemExit(1)
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, YOUTUBE_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        log("INFO", f"Saved YouTube token to {token_path}")

    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/*",
        resumable=True,
        chunksize=4 * 1024 * 1024,  # 4 MB chunks
    )

    log("INFO", f"Starting YouTube upload: {title}")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log("INFO", f"  Upload progress: {int(status.progress() * 100)}%")

    video_id = response.get("id", "")
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    log("INFO", f"YouTube upload complete: {video_url}")
    return video_id


# ---------------------------------------------------------------------------
# Facebook
# ---------------------------------------------------------------------------
FACEBOOK_GRAPH_VERSION = "v18.0"


def upload_to_facebook(
    video_path: str,
    title: str,
    description: str = "",
    page_id: str = "",
    access_token: str = "",
    graph_version: str = FACEBOOK_GRAPH_VERSION,
) -> str:
    """Upload a video to a Facebook Page.

    Requires a Page access token with ``pages_manage_posts`` and
    ``pages_read_engagement`` permissions.

    Returns the Facebook post ID on success.
    """
    _require_requests()

    if not os.path.isfile(video_path):
        log("ERROR", f"Video file not found: {video_path}")
        raise SystemExit(1)

    if not page_id:
        log("ERROR", "Facebook page_id is required")
        raise SystemExit(1)
    if not access_token:
        log("ERROR", "Facebook access_token is required")
        raise SystemExit(1)

    import requests

    url = f"https://graph.facebook.com/{graph_version}/{page_id}/videos"

    file_size = os.path.getsize(video_path)
    log("INFO", f"Starting Facebook upload ({file_size / 1024 / 1024:.1f} MB): {title}")

    with open(video_path, "rb") as video_file:
        files = {
            "source": (os.path.basename(video_path), video_file, "video/mp4"),
        }
        data = {
            "title": title,
            "description": description,
            "access_token": access_token,
        }

        response = requests.post(url, data=data, files=files, timeout=600)

    if not response.ok:
        log("ERROR", f"Facebook upload failed: {response.status_code}")
        log("ERROR", response.text[:2000])
        raise RuntimeError(f"Facebook upload failed: {response.status_code}")

    result = response.json()
    post_id = result.get("id", "")
    post_url = f"https://www.facebook.com/{post_id}"
    log("INFO", f"Facebook upload complete: {post_url}")
    return post_id
