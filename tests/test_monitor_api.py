import os
import tempfile
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from modules.monitor import app, init_dependencies

class MockDB:
    def __init__(self):
        self.users = {12345: type("User", (object,), {"id": 1, "telegram_id": 12345, "username": "u"})}
        self._txs = []
    def get_user(self, telegram_id):
        return self.users.get(telegram_id)
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
