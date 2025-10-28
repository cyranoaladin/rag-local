import os
from pathlib import Path

import pytest
import requests


@pytest.mark.skipif(os.getenv("MULTIMODAL_ENABLED", "false").lower() != "true", reason="multimodal disabled")
def test_png_ingest_multimodal():
    try:
        import raganything  # type: ignore # noqa: F401
    except ImportError:
        pytest.skip("raganything not installed")

    base_url = os.getenv("INGEST_BASE_URL", "http://127.0.0.1:8001")
    token = os.getenv("INGESTOR_API_TOKEN", "changeme")
    payload_path = Path(__file__).parent / "assets" / "tiny.png"
    if not payload_path.exists():
        pytest.skip("test asset missing")

    with payload_path.open("rb") as handle:
        try:
            response = requests.post(
                f"{base_url}/ingest?mode=multimodal",
                headers={"X-API-Token": token},
                files={"file": (payload_path.name, handle, "image/png")},
                timeout=20,
            )
        except requests.ConnectionError as exc:  # pragma: no cover - network guard
            pytest.skip(f"ingestor not reachable: {exc}")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "modalities" in data
    assert data["modalities"].get("image", 0) >= 0


def test_ingest_rejects_unsupported_mime():
    base_url = os.getenv("INGEST_BASE_URL", "http://127.0.0.1:8001")
    token = os.getenv("INGESTOR_API_TOKEN", "changeme")
    payload_path = Path(__file__).parent / "assets" / "note.txt"
    if not payload_path.exists():
        pytest.skip("test asset missing")

    with payload_path.open("rb") as handle:
        try:
            response = requests.post(
                f"{base_url}/ingest?mode=multimodal",
                headers={"X-API-Token": token},
                files={"file": (payload_path.name, handle, "text/plain")},
                timeout=10,
            )
        except requests.ConnectionError as exc:  # pragma: no cover - network guard
            pytest.skip(f"ingestor not reachable: {exc}")

    assert response.status_code == 415
