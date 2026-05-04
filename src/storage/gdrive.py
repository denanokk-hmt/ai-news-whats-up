from __future__ import annotations

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from src.config import PROJECT_ROOT, today_jst

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]
CREDENTIALS_PATH = PROJECT_ROOT / "credentials.json"
TOKEN_PATH = PROJECT_ROOT / "gdrive_token.json"


def _get_credentials() -> Credentials:
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"OAuth credentials not found at {CREDENTIALS_PATH}. "
                    "Download from Google Cloud Console (Desktop app type)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES,
            )
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())
        logger.info("Saved OAuth token to %s", TOKEN_PATH)

    return creds


def _get_or_create_folder(service, name: str, parent_id: str | None = None) -> str:
    escaped_name = name.replace("\\", "\\\\").replace("'", "\\'")
    query = (
        f"mimeType='application/vnd.google-apps.folder' "
        f"and name='{escaped_name}' and trashed=false"
    )
    if parent_id:
        query += f" and '{parent_id}' in parents"

    result = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)",
    ).execute()

    folders = result.get("files", [])
    if folders:
        return folders[0]["id"]

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(body=metadata, fields="id").execute()
    logger.info("Created folder: %s", name)
    return folder["id"]


def _upload_file(service, file_path: Path, parent_id: str, mime_type: str) -> dict:
    media = MediaFileUpload(str(file_path), mimetype=mime_type, resumable=True)
    metadata = {"name": file_path.name, "parents": [parent_id]}

    file = service.files().create(
        body=metadata,
        media_body=media,
        fields="id, name, webViewLink, webContentLink",
    ).execute()

    service.permissions().create(
        fileId=file["id"],
        body={"type": "anyone", "role": "reader"},
    ).execute()

    logger.info("Uploaded: %s", file_path.name)
    return file


def get_authenticated_email() -> str | None:
    """OAuth認証済みアカウントのメールアドレスを取得。失敗時はNone。"""
    try:
        creds = _get_credentials()
        service = build("oauth2", "v2", credentials=creds)
        info = service.userinfo().get().execute()
        return info.get("email")
    except Exception as e:
        logger.warning("Failed to get authenticated email: %s", e)
        return None


def upload_episode(mp3_path: Path, digest_path: Path, root_folder: str) -> dict:
    creds = _get_credentials()
    service = build("drive", "v3", credentials=creds)

    today = today_jst()
    year = today.strftime("%Y")
    month = today.strftime("%m")
    day = today.strftime("%Y-%m-%d")

    root_id = _get_or_create_folder(service, root_folder)
    year_id = _get_or_create_folder(service, year, root_id)
    month_id = _get_or_create_folder(service, month, year_id)
    day_id = _get_or_create_folder(service, day, month_id)

    mp3_file = _upload_file(service, mp3_path, day_id, "audio/mpeg")
    md_file = _upload_file(service, digest_path, day_id, "text/markdown")

    return {
        "mp3_link": mp3_file.get("webViewLink"),
        "mp3_download": mp3_file.get("webContentLink"),
        "digest_link": md_file.get("webViewLink"),
        "folder_id": day_id,
    }
