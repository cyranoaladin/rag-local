import os
import sqlite3
import logging
from pathlib import Path
from typing import Any, List, Dict, Optional
from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

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
                        last_ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to init sync DB: {e}")

    def _get_drive_service(self):
        service_account_raw = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        creds = None
        if service_account_raw:
            path = Path(service_account_raw)
            if path.exists():
                creds = service_account.Credentials.from_service_account_file(str(path))
        
        if not creds:
            default_credentials = Path.home() / ".credentials" / "credentials.json"
            if default_credentials.exists():
                creds = service_account.Credentials.from_service_account_file(str(default_credentials))
        
        if not creds:
             raise Exception("Google Drive credentials not found")

        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def list_updates(self, folder_id: str) -> List[Dict[str, Any]]:
        """
        List files in folder (recursively) that are new or modified since last ingestion.
        """
        try:
            service = self._get_drive_service()
            files = self._fetch_all_files(service, folder_id)
            
            updates = []
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                for f in files:
                    file_id = f.get("id")
                    modified_time = f.get("modifiedTime")
                    
                    cursor.execute("SELECT modified_time FROM drive_files WHERE file_id = ?", (file_id,))
                    row = cursor.fetchone()
                    
                    if not row:
                        updates.append(f) # New file
                    elif row[0] != modified_time:
                        updates.append(f) # Modified file
            
            return updates
        except Exception as e:
            logger.error(f"Error listing updates: {e}")
            return []

    def _fetch_all_files(self, service, folder_id: str) -> List[Dict[str, Any]]:
        files = []
        # Stack for DFS traversal of folders
        stack = [folder_id]
        
        while stack:
            current_folder = stack.pop()
            page_token = None
            while True:
                try:
                    q = f"'{current_folder}' in parents and trashed=false"
                    response = service.files().list(
                        q=q,
                        fields="nextPageToken, files(id, name, mimeType, modifiedTime, md5Checksum)",
                        pageToken=page_token,
                        includeItemsFromAllDrives=True,
                        supportsAllDrives=True,
                        pageSize=100
                    ).execute()
                    
                    for f in response.get('files', []):
                        if f['mimeType'] == 'application/vnd.google-apps.folder':
                            stack.append(f['id'])
                        else:
                            # Filter out Google Apps documents if needed, or keep them. 
                            # GoogleDriveLoader handles them, so we keep them.
                            files.append(f)
                    
                    page_token = response.get('nextPageToken')
                    if not page_token:
                        break
                except Exception as e:
                    logger.warning(f"Error listing folder {current_folder}: {e}")
                    break
        return files

    def mark_as_ingested(self, file_meta: Dict[str, Any]):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO drive_files (file_id, name, modified_time, md5_checksum)
                    VALUES (?, ?, ?, ?)
                """, (
                    file_meta.get("id"),
                    file_meta.get("name"),
                    file_meta.get("modifiedTime"),
                    file_meta.get("md5Checksum")
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to mark file as ingested: {e}")
