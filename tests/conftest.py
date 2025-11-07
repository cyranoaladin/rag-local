from __future__ import annotations

import os
from pathlib import Path

# Ensure admin database writes stay within the repository during tests.
_test_db_path = Path.cwd() / ".pytest_cache" / "admin.db"
_test_db_path.parent.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("ADMIN_DB_PATH", str(_test_db_path))
