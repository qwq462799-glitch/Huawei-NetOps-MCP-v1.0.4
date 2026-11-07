import pytest
from cryptography.fernet import Fernet
from app.config import settings


@pytest.fixture(autouse=True)
def isolated_credential_key(monkeypatch):
    # Each test gets a valid disposable key; production keys are never touched.
    monkeypatch.setattr(settings, "credential_encryption_key", Fernet.generate_key().decode("ascii"))
