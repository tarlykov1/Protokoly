import os
import tempfile
from pathlib import Path

import pytest

# app.db.session creates its engine at import time.  Point it away from the developer's
# protocols.db before pytest imports any application/test module.
_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="protokoly-pytest-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_DIR / 'session.db'}"


@pytest.fixture
def sqlite_database_url(tmp_path):
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture(scope="session", autouse=True)
def initialize_test_schema():
    """Allow individual test files to run without relying on alphabetical order."""
    from app.db.base import Base
    from app.db.session import engine

    Base.metadata.create_all(engine)
