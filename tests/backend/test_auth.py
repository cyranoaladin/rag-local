from __future__ import annotations

import os
from importlib import reload

from fastapi.testclient import TestClient

# Ensure the backend uses an in-memory SQLite database during tests
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from src.backend.core import db as db_module  # noqa: E402

reload(db_module)

from src.backend.app import app  # noqa: E402  # pylint: disable=wrong-import-position

client = TestClient(app)


def test_register_login_and_me_flow() -> None:
    payload = {
        "email": "alice@example.com",
        "password": "SuperSecure123",
        "full_name": "Alice Example",
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == payload["email"]

    login_resp = client.post(
        "/auth/login",
        data={"username": payload["email"], "password": payload["password"]},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    me_resp = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == payload["email"]
    assert me_data["full_name"] == payload["full_name"]
    assert me_data["is_active"] is True
