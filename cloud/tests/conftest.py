import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_zerocode_cloud.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-hs256")
os.environ.setdefault("FERNET_KEY", "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI=")
os.environ.setdefault("ALLOW_PUBLIC_SIGNUP", "true")
os.environ.setdefault("AUTO_CREATE_SCHEMA", "false")

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_headers(client):
    client.post(
        "/v1/auth/register",
        json={"email": "admin@test.example", "password": "correct-horse-battery-99"},
    )
    # Promote only in the isolated test database; production role changes are admin-only.
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "admin@test.example"))
        user.role = "admin"
        db.commit()

    login = client.post(
        "/v1/auth/login",
        json={
            "email": "admin@test.example",
            "password": "correct-horse-battery-99",
            "device_name": "pytest",
        },
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}
