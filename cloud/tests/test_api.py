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


def test_admin_can_suspend_user_and_revoke_all_sessions(client, admin_headers):
    client.post(
        "/v1/auth/register",
        json={"email": "suspend-me@example.com", "password": "correct-horse-battery-99"},
    )
    login = client.post(
        "/v1/auth/login",
        json={"email": "suspend-me@example.com", "password": "correct-horse-battery-99"},
    ).json()
    user_headers = {"Authorization": f"Bearer {login['access_token']}"}
    user_id = login["user"]["id"]

    suspended = client.patch(
        f"/v1/admin/users/{user_id}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert suspended.status_code == 200
    assert suspended.json()["is_active"] is False
    assert client.get("/v1/auth/me", headers=user_headers).status_code == 401
    assert client.post(
        "/v1/auth/login",
        json={"email": "suspend-me@example.com", "password": "correct-horse-battery-99"},
    ).status_code == 401


def test_admin_guardrails_enforce_request_rate_and_output_size(client, admin_headers):
    client.post(
        "/v1/auth/register",
        json={"email": "limited@example.com", "password": "correct-horse-battery-99"},
    )
    login = client.post(
        "/v1/auth/login",
        json={"email": "limited@example.com", "password": "correct-horse-battery-99"},
    ).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    configured = client.patch(
        "/v1/admin/guardrails",
        headers=admin_headers,
        json={"requests_per_minute": 1, "max_output_tokens": 256},
    )
    assert configured.status_code == 200
    assert configured.json()["limits"]["requests_per_minute"] == 1

    oversized = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 512,
        },
    )
    assert oversized.status_code == 422

    first = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 128,
        },
    )
    assert first.status_code == 503  # No provider is configured in the isolated test DB.

    second = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "hello again"}],
            "max_tokens": 128,
        },
    )
    assert second.status_code == 429
    assert second.headers["retry-after"] == "60"


def test_login_rotates_oldest_session_when_device_limit_is_reached(client):
    client.post(
        "/v1/auth/register",
        json={"email": "many-devices@example.com", "password": "correct-horse-battery-99"},
    )
    latest = None
    for index in range(6):
        response = client.post(
            "/v1/auth/login",
            json={
                "email": "many-devices@example.com",
                "password": "correct-horse-battery-99",
                "device_name": f"Device {index + 1}",
            },
        )
        assert response.status_code == 200
        latest = response.json()

    headers = {"Authorization": f"Bearer {latest['access_token']}"}
    devices = client.get("/v1/auth/devices", headers=headers).json()
    assert len(devices) == 6
    assert sum(1 for device in devices if not device["is_revoked"]) == 5
    assert any(device["is_revoked"] for device in devices)


def test_server_enforces_cloud_ai_kill_switch(client, admin_headers):
    client.post(
        "/v1/auth/register",
        json={"email": "kill-switch@example.com", "password": "correct-horse-battery-99"},
    )
    login = client.post(
        "/v1/auth/login",
        json={"email": "kill-switch@example.com", "password": "correct-horse-battery-99"},
    ).json()
    user_headers = {"Authorization": f"Bearer {login['access_token']}"}

    changed = client.patch(
        "/v1/admin/client-config",
        headers=admin_headers,
        json={"feature_flags": {"cloud_ai": False, "remote_config": True}},
    )
    assert changed.status_code == 200
    blocked = client.post(
        "/v1/chat/completions",
        headers=user_headers,
        json={"messages": [{"role": "user", "content": "try the gateway"}]},
    )
    assert blocked.status_code == 503
    assert "disabled" in blocked.json()["detail"].lower()


def test_admin_console_is_served_with_security_headers(client):
    page = client.get("/admin")
    assert page.status_code == 200
    assert "Centre de contrôle" in page.text
    assert page.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    asset = client.get("/admin/assets/admin.js")
    assert asset.status_code == 200
    assert "async function boot" in asset.text


def test_cloud_rejects_oversized_http_body(client):
    response = client.post(
        "/v1/auth/login",
        content=b"x" * (1_048_577),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
