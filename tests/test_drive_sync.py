from __future__ import annotations

from pathlib import Path

from src.ingestor.drive_sync import DriveSyncManager


def _file_meta() -> dict[str, str]:
    return {
        "id": "file-123",
        "name": "cours.pdf",
        "modifiedTime": "2026-04-19T00:00:00Z",
        "md5Checksum": "abc123",
    }


def test_drive_sync_is_collection_specific_for_dedicated_collections(tmp_path: Path, monkeypatch) -> None:
    manager = DriveSyncManager(db_path=str(tmp_path / "drive_sync.db"))
    file_meta = _file_meta()

    manager.mark_as_ingested(file_meta, content_fingerprint="fp-1", collection_name="rag_education")

    from unittest.mock import MagicMock
    monkeypatch.setattr(manager, "_get_drive_service", MagicMock())
    monkeypatch.setattr(manager, "_fetch_all_files", lambda _service, _folder_id: [file_meta])

    assert manager.list_updates("folder-1", collection_name="rag_education") == []
    assert manager.list_updates("folder-1", collection_name="rag_maths_premiere") == [file_meta]


def test_drive_sync_unchanged_check_uses_collection_scoped_key(tmp_path: Path) -> None:
    manager = DriveSyncManager(db_path=str(tmp_path / "drive_sync.db"))
    file_meta = _file_meta()

    manager.mark_as_ingested(file_meta, content_fingerprint="fp-1", collection_name="rag_maths_premiere")

    assert manager.is_unchanged(file_meta, "fp-1", collection_name="rag_maths_premiere") is True
    assert manager.is_unchanged(file_meta, "fp-1", collection_name="rag_education") is False
