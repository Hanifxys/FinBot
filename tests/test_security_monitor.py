from fastapi.testclient import TestClient

from modules.monitor import AppDependencies, create_app, sign_token


class MockDB:
    def __init__(self):
        self.audit_calls = []

    def get_user(self, telegram_id):
        if telegram_id == 12345:
            return type("User", (object,), {"id": 1, "telegram_id": 12345, "username": "u", "role": "superadmin", "is_active": True})
        return None

    def log_admin_action(self, **kwargs):
        self.audit_calls.append(kwargs)
        return True


class MockPremiumAI:
    class Redis:
        def __init__(self):
            self.client = None

    def __init__(self):
        self.redis = self.Redis()


def _client_with_deps():
    deps = AppDependencies(db=MockDB(), premium_ai=MockPremiumAI(), auth_secret="secret")
    app = create_app(deps)
    return TestClient(app), deps


def test_admin_backdoor_disabled_by_default():
    client, _ = _client_with_deps()
    resp = client.get("/auth/verify", headers={"Authorization": "Bearer admin"})
    assert resp.status_code == 401


def test_auth_revoke_endpoint_audited(monkeypatch):
    client, deps = _client_with_deps()
    token = sign_token(12345, "secret", ttl_seconds=600)

    monkeypatch.setattr("modules.monitor._revoke_token", lambda _token: True)

    resp = client.post(
        "/auth/revoke",
        json={"token": token},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"
    assert len(deps.db.audit_calls) == 1
    assert deps.db.audit_calls[0]["action"] == "auth_revoke_token"
