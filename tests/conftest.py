import pytest

from app import settings


@pytest.fixture(autouse=True)
def default_settings():
    """Settings live in memory for the whole process; give every test the defaults."""
    settings.current.clear()
    settings.current.update(settings.DEFAULTS)
