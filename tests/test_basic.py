import pytest
from app import create_app
from app.auth import hash_password, verify_password
from app.database import get_db

@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True

    return app.test_client()

def test_home_page(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"Welcome to SaveIt!" in response.data

def test_analytics_requires_login(client):
    response = client.get("/analytics")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

def test_password_is_hashed_correctly():
    password = "my-secret-password"
    hashed_password = hash_password(password)

    assert hashed_password != password
    assert verify_password(hashed_password, password) is True
    assert verify_password(hashed_password, "wrong-password") is False

def test_database_foreign_keys_are_enabled():
    app = create_app()

    with app.app_context():
        db = get_db()
        foreign_keys_enabled = db.execute("PRAGMA foreign_keys").fetchone()[0]

    assert foreign_keys_enabled == 1
