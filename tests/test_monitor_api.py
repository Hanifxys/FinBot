import os
import tempfile
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from modules.monitor import app, init_dependencies, set_bot_instance

class MockDB:
    def __init__(self):
        self.users = {
            12345: type("User", (object,), {"id": 1, "telegram_id": 12345, "username": "u", "role": "moderator", "is_active": True}),
            99999: type("User", (object,), {"id": 2, "telegram_id": 99999, "username": "inactive", "role": "user", "is_active": False}),
        }
        self._txs = []
    def get_user(self, telegram_id):
        return self.users.get(telegram_id)
    def get_all_users(self):
        return list(self.users.values())
    def has_permission(self, telegram_id, permission):
        return True
    def is_admin(self, telegram_id):
        return True
    def is_superadmin(self, telegram_id):
        return True
    def log_admin_action(self, **kwargs):
        return True
    def get_transactions_history(self, user_id, limit=50):
        return [type("Tx", (object,), t) for t in self._txs][-limit:]
    def add_transaction(self, user_id, amount, category, description, trans_type, date=None):
        tx = {"id": len(self._txs)+1, "amount": amount, "category": category, "type": trans_type, "date": date, "description": description}
        self._txs.append(tx)
        return type("Tx", (object,), tx)
    def set_budget(self, user_id, category, limit_amount):
        return type("Budget", (object,), {"category": category, "limit_amount": limit_amount})
    def set_budget_threshold(self, user_id, category, warn, limit):
        return True
    def get_monthly_report(self, user_id, month, year):
        return [type("Tx", (object,), t) for t in self._txs]
    def get_yearly_report(self, user_id, year):
        return [type("Tx", (object,), t) for t in self._txs]
    def export_transactions_to_csv(self, user_id, filepath):
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("Tanggal,Tipe,Kategori,Nominal,Catatan\n")
        return filepath
    @property
    def supabase(self):
        return True

class MockPremiumAI:
    class Redis:
        def __init__(self): self.client = True
    def __init__(self): self.redis = self.Redis()
    def generate_comprehensive_test_report(self): return {"ok": True}

class MockWS:
    def __init__(self): 
        class Loop: 
            def is_running(self): return False
        self.loop = Loop()

def setup_module(module):
    os.environ["WEB_JWT_SECRET"] = "secret"
    init_dependencies(MockDB(), MockPremiumAI(), MockWS(), auth_secret="secret")
    bot = MagicMock()
    bot.send_message = MagicMock()
    bot.send_photo = MagicMock()
    bot.send_video = MagicMock()
    async def _ok(*args, **kwargs): return True
    bot.send_message.side_effect = _ok
    bot.send_photo.side_effect = _ok
    bot.send_video.side_effect = _ok
    set_bot_instance(bot)

def test_auth_and_transactions_flow():
    client = TestClient(app)
    # Issue token
    resp = client.post("/auth/issue", params={"telegram_id": 12345})
    assert resp.status_code == 200
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    # Verify
    v = client.get("/auth/verify", headers=headers)
    assert v.status_code == 200
    # Create tx
    r = client.post("/transactions", json={
        "amount": 50000, "category": "Makanan", "description": "makan", "type": "expense"
    }, headers=headers)
    assert r.status_code == 200
    # List txs
    lst = client.get("/transactions", headers=headers)
    assert lst.status_code == 200
    assert len(lst.json()) >= 1
    # Set budget and alerts
    b = client.post("/budgets", json={"category": "Makanan", "limit_amount": 1000000}, headers=headers)
    assert b.status_code == 200
    ba = client.post("/budgets/alerts", json={"category": "Makanan", "warn_threshold": 0.8, "limit_threshold": 1.0}, headers=headers)
    assert ba.status_code == 200
    # Reports
    m = client.get("/reports/monthly", params={"month": 1, "year": 2026}, headers=headers)
    assert m.status_code == 200
    y = client.get("/reports/yearly", params={"year": 2026}, headers=headers)
    assert y.status_code == 200
    # Export
    e = client.get("/export", headers=headers)
    assert e.status_code == 200

def test_admin_broadcast_templates_and_send():
    client = TestClient(app)
    resp = client.post("/auth/issue", params={"telegram_id": 12345})
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    t = client.get("/admin/broadcast/templates", headers=headers)
    assert t.status_code == 200
    assert isinstance(t.json(), list)
    assert len(t.json()) >= 1

    est = client.post("/admin/broadcast/estimate", json={"active_only": True}, headers=headers)
    assert est.status_code == 200
    assert est.json()["estimated_recipients"] == 1

    r = client.post("/admin/broadcast", json={"message": "Halo {{name}}", "variables": {"name": "Test"}}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ["ok", "partial"]
    assert body["sent_to"] >= 1

def test_admin_broadcast_schedule_and_cancel():
    client = TestClient(app)
    resp = client.post("/auth/issue", params={"telegram_id": 12345})
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    future = "2999-01-01T00:00:00Z"
    r = client.post("/admin/broadcast", json={"message": "Scheduled", "schedule_at": future}, headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "scheduled"
    job_id = data["job_id"]

    q = client.get("/admin/broadcast/scheduled", headers=headers)
    assert q.status_code == 200
    assert any(item["id"] == job_id for item in q.json())

    c = client.delete(f"/admin/broadcast/scheduled/{job_id}", headers=headers)
    assert c.status_code == 200
