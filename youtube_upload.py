"""
YouTube Native Integration — OAuth 2.0 + Direct Video Upload via YouTube Data API v3.
Replaces Upload-Post dependency with direct Google API calls.
"""

import os
import json
import pickle
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TOKEN_FILE = "data/youtube_token.pickle"
CLIENT_SECRETS_FILE = "data/youtube_client_secrets.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
REDIRECT_URI = "http://localhost:8000/auth/youtube/callback"


def is_authenticated() -> bool:
    """Check if we have valid stored credentials."""
    if not os.path.exists(TOKEN_FILE):
        return False
    try:
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
        if creds and creds.valid:
            return True
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, "wb") as f:
                pickle.dump(creds, f)
            return True
    except Exception:
        pass
    return False


def get_auth_url() -> str:
    """Generate Google OAuth URL for the user to visit."""
    if not os.path.exists(CLIENT_SECRETS_FILE):
        return None

    flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = REDIRECT_URI
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true"
    )
    return auth_url


def handle_callback(code: str) -> bool:
    """Exchange authorization code for tokens and save them."""
    if not os.path.exists(CLIENT_SECRETS_FILE):
        return False

    flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = REDIRECT_URI
    flow.fetch_token(code=code)

    creds = flow.credentials
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "wb") as f:
        pickle.dump(creds, f)
    return True


def exchange_code_manual(code: str) -> bool:
    """Exchange auth code for tokens when user pastes it manually."""
    return handle_callback(code)


def get_authenticated_service():
    """Build and return an authenticated YouTube API service."""
    if not os.path.exists(TOKEN_FILE):
        raise Exception("Not authenticated. Please connect YouTube first.")

    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, "wb") as f:
                pickle.dump(creds, f)
        else:
            raise Exception("Invalid YouTube credentials. Please reconnect.")

    return build(API_SERVICE_NAME, API_VERSION, credentials=creds)


def upload_video(
    video_path: str,
    title: str,
    description: str,
    thumbnail_path: str = None,
    privacy_status: str = "public",
    tags: list = None,
) -> dict:
    """
    Upload a video to YouTube using the YouTube Data API v3.
    Returns the video response from the API.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    youtube = get_authenticated_service()

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags or [],
            "categoryId": "20",
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    print(f"📤 [YouTube] Uploading: {title}")
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = int(status.progress() * 100)
            print(f"📤 [YouTube] Upload progress: {progress}%")

    video_id = response.get("id")
    print(f"✅ [YouTube] Uploaded! Video ID: {video_id}")

    if thumbnail_path and os.path.exists(thumbnail_path) and video_id:
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path)
            ).execute()
            print(f"✅ [YouTube] Thumbnail set for video {video_id}")
        except Exception as e:
            print(f"⚠️ [YouTube] Could not set thumbnail: {e}")

    return {
        "video_id": video_id,
        "url": f"https://youtu.be/{video_id}",
        "title": title,
    }
