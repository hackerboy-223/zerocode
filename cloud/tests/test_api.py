def test_health_endpoints(client):
    assert client.get("/v1/health/live").json()["status"] == "ok"
    assert client.get("/v1/health/ready").json()["database"] == "connected"


def test_signup_login_refresh_and_revoke(client):
    created = client.post(
        "/v1/auth/register",
        json={"email": "dev@example.com", "password": "correct-horse-battery-99"},
    )
    assert created.status_code == 201

    logged = client.post(
        "/v1/auth/login",
        json={
            "email": "dev@example.com",
            "password": "correct-horse-battery-99",
            "device_name": "Linux laptop",
        },
    )
    assert logged.status_code == 200
    tokens = logged.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get("/v1/auth/me", headers=headers).status_code == 200

    refreshed = client.post(
        "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != tokens["refresh_token"]
    assert client.post(
        "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    ).status_code == 401

    fresh_headers = {"Authorization": f"Bearer {refreshed.json()['access_token']}"}
    assert client.post("/v1/auth/logout", headers=fresh_headers).status_code == 200
    assert client.get("/v1/auth/me", headers=fresh_headers).status_code == 401


def test_admin_can_configure_provider_model_and_routing(client, admin_headers, monkeypatch):
    import app.services

    monkeypatch.setattr(
        app.services.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("1.1.1.1", 443))],
    )
    blocked = client.post(
        "/v1/admin/providers",
        headers=admin_headers,
        json={
            "name": "private-test",
            "base_url": "http://127.0.0.1:11434/v1",
            "is_enabled": True,
        },
    )
    assert blocked.status_code == 422

    provider = client.post(
        "/v1/admin/providers",
        headers=admin_headers,
        json={
            "name": "kilo",
            "base_url": "https://ai-gateway.kilo.ai/api/v1",
            "api_key": "test-key",
            "is_enabled": True,
        },
    )
    assert provider.status_code == 201
    assert provider.json()["has_api_key"] is True
    assert "api_key" not in provider.json()

    model = client.post(
        "/v1/admin/models",
        headers=admin_headers,
        json={
            "provider_id": provider.json()["id"],
            "alias": "coding-fast",
            "model_name": "kilo-auto/free",
            "task_types": ["coding", "fast"],
            "priority": 10,
            "supports_tools": True,
        },
    )
    assert model.status_code == 201

    policy = client.put(
        "/v1/admin/routing/coding",
        headers=admin_headers,
        json={"model_aliases": ["coding-fast"]},
    )
    assert policy.status_code == 200
    assert client.get("/v1/admin/models", headers=admin_headers).json()[0]["alias"] == "coding-fast"


def test_non_admin_cannot_access_control_plane(client):
    client.post(
        "/v1/auth/register",
        json={"email": "user@example.com", "password": "correct-horse-battery-99"},
    )
    logged = client.post(
        "/v1/auth/login",
        json={"email": "user@example.com", "password": "correct-horse-battery-99"},
    ).json()
    headers = {"Authorization": f"Bearer {logged['access_token']}"}
    assert client.get("/v1/admin/providers", headers=headers).status_code == 403


def test_wrong_password_is_rejected_without_server_error(client):
    client.post(
        "/v1/auth/register",
        json={"email": "wrong-pass@example.com", "password": "correct-horse-battery-99"},
    )
    response = client.post(
        "/v1/auth/login",
        json={"email": "wrong-pass@example.com", "password": "incorrect-password"},
    )
    assert response.status_code == 401


def test_device_revocation_blocks_existing_access_token(client):
    client.post(
        "/v1/auth/register",
        json={"email": "revoke@example.com", "password": "correct-horse-battery-99"},
    )
    logged = client.post(
        "/v1/auth/login",
        json={"email": "revoke@example.com", "password": "correct-horse-battery-99"},
    ).json()
    headers = {"Authorization": f"Bearer {logged['access_token']}"}
    devices = client.get("/v1/auth/devices", headers=headers).json()
    assert len(devices) == 1
    assert client.delete(f"/v1/auth/devices/{devices[0]['id']}", headers=headers).status_code == 200
    assert client.get("/v1/auth/me", headers=headers).status_code == 401
