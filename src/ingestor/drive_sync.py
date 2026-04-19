import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, cast

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

_DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
]


class DriveSyncManager:
    def __init__(self, db_path: str = "drive_sync_state.db"):
        # Use an absolute path for the DB to avoid CWD issues
        self.db_path = os.path.abspath(db_path)
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS drive_files (
                        file_id TEXT PRIMARY KEY,
                        name TEXT,
                        modified_time TEXT,
                        md5_checksum TEXT,
                        content_fingerprint TEXT,
                        last_ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cols = {row[1] for row in conn.execute("PRAGMA table_info(drive_files)").fetchall()}
                if "content_fingerprint" not in cols:
                    conn.execute("ALTER TABLE drive_files ADD COLUMN content_fingerprint TEXT")
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to init sync DB: {e}")

    def _get_drive_service(self):
        service_account_raw = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        creds = None
        if service_account_raw:
            path = Path(service_account_raw)
            if path.exists():
                creds = service_account.Credentials.from_service_account_file(
                    str(path), scopes=_DRIVE_SCOPES
                )

        if not creds:
            default_credentials = Path.home() / ".credentials" / "credentials.json"
            if default_credentials.exists():
                creds = service_account.Credentials.from_service_account_file(
                    str(default_credentials), scopes=_DRIVE_SCOPES
                )

        if not creds:
            raise Exception("Google Drive credentials not found")

        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def verify_folder_access(self, folder_id: str) -> dict[str, Any]:
        """Vérifie que le SA peut accéder au dossier. Lève une exception explicite sinon."""
        service = self._get_drive_service()
        try:
            meta = cast(dict[str, Any], service.files().get(
                fileId=folder_id,
                supportsAllDrives=True,
                fields="id,name,mimeType",
            ).execute())
            logger.info(f"Folder access OK: {meta.get('name')} ({folder_id})")
            return meta
        except HttpError as e:
            if e.status_code == 404:
                raise PermissionError(
                    f"Le dossier Google Drive '{folder_id}' est introuvable ou le compte de service "
                    f"n'y a pas accès. Partagez-le avec : "
                    f"{self._get_sa_email()} (lecteur)."
                ) from e
            raise RuntimeError(f"Erreur Google Drive API [{e.status_code}]: {e.reason}") from e

    def _get_sa_email(self) -> str:
        """Retourne l'email du compte de service pour les messages d'erreur."""
        try:
            import json
            path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
            if path and Path(path).exists():
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    email = data.get("client_email")
                    if isinstance(email, str) and email:
                        return email
        except Exception:
            pass
        return "<service-account>"

    def _sync_key(self, file_id: str | None, collection_name: str | None = None) -> str:
        """Return the storage key used in the sync DB for a given collection."""
        normalized_file_id = str(file_id or "").strip()
        normalized_collection = str(collection_name or "").strip().lower()
        if not normalized_collection or normalized_collection == "rag_education":
            return normalized_file_id
        return f"{normalized_collection}:{normalized_file_id}"

    def list_updates(self, folder_id: str, collection_name: str | None = None) -> list[dict[str, Any]]:
        """
        List files in folder (recursively) that are new or modified since last ingestion.
        Raises PermissionError if the folder is not accessible by the service account.
        """
        service = self._get_drive_service()
        files = self._fetch_all_files(service, folder_id)

        updates = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                for f in files:
                    file_id = f.get("id")
                    modified_time = f.get("modifiedTime")
                    drive_md5 = f.get("md5Checksum")
                    sync_key = self._sync_key(file_id, collection_name)
                    cursor.execute(
                        "SELECT modified_time, md5_checksum FROM drive_files WHERE file_id = ?",
                        (sync_key,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        updates.append(f)
                    elif drive_md5 and row[1]:
                        if row[1] != drive_md5:
                            updates.append(f)
                    elif row[0] != modified_time:
                        updates.append(f)
        except Exception as e:
            logger.error(f"Error reading sync DB for folder {folder_id}: {e}")
            raise

        return updates

    def _fetch_all_files(self, service, folder_id: str) -> list[dict[str, Any]]:
        """Parcours DFS récursif du dossier Drive. Lève HttpError si accès refusé."""
        files: list[dict[str, Any]] = []
        stack = [folder_id]
        seen_folders: set = {folder_id}

        while stack:
            current_folder = stack.pop()
            page_token = None
            while True:
                q = f"'{current_folder}' in parents and trashed=false"
                try:
                    response = service.files().list(
                        q=q,
                        fields="nextPageToken, files(id, name, mimeType, modifiedTime, md5Checksum)",
                        pageToken=page_token,
                        includeItemsFromAllDrives=True,
                        supportsAllDrives=True,
                        pageSize=100,
                    ).execute()
                except HttpError as e:
                    if e.status_code in (403, 404):
                        sa_email = self._get_sa_email()
                        raise PermissionError(
                            f"Accès refusé au dossier Google Drive '{current_folder}' "
                            f"(HTTP {e.status_code}). Partagez-le avec {sa_email} (lecteur)."
                        ) from e
                    logger.warning(f"HttpError listing folder {current_folder}: {e}")
                    break
                except Exception as e:
                    logger.warning(f"Error listing folder {current_folder}: {e}")
                    break

                for f in response.get("files", []):
                    if f.get("mimeType") == "application/vnd.google-apps.folder":
                        fid = f.get("id", "")
                        if fid and fid not in seen_folders:
                            seen_folders.add(fid)
                            stack.append(fid)
                    else:
                        files.append(f)

                page_token = response.get("nextPageToken")
                if not page_token:
                    break

        logger.info(f"Drive scan found {len(files)} files in folder tree {folder_id}")
        return files

    def is_unchanged(
        self,
        file_meta: dict[str, Any],
        content_fingerprint: str = "",
        collection_name: str | None = None,
    ) -> bool:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT modified_time, md5_checksum, content_fingerprint FROM drive_files WHERE file_id = ?",
                    (self._sync_key(file_meta.get("id"), collection_name),),
                )
                row = cursor.fetchone()
                if not row:
                    return False
                stored_modified, stored_md5, stored_fingerprint = row
                drive_md5 = file_meta.get("md5Checksum")
                if content_fingerprint and stored_fingerprint and content_fingerprint == stored_fingerprint:
                    return True
                if drive_md5 and stored_md5 and drive_md5 == stored_md5:
                    return True
                return bool((not drive_md5) and stored_modified == file_meta.get("modifiedTime") and content_fingerprint and stored_fingerprint == content_fingerprint)
        except Exception as e:
            logger.error(f"Failed to compare file fingerprint: {e}")
            return False

    def mark_as_ingested(
        self,
        file_meta: dict[str, Any],
        content_fingerprint: str = "",
        collection_name: str | None = None,
    ):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO drive_files (file_id, name, modified_time, md5_checksum, content_fingerprint)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    self._sync_key(file_meta.get("id"), collection_name),
                    file_meta.get("name"),
                    file_meta.get("modifiedTime"),
                    file_meta.get("md5Checksum"),
                    content_fingerprint,
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to mark file as ingested: {e}")
