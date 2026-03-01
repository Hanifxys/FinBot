from datetime import datetime, timedelta

from modules.ai_persona import PersonaManager
from modules.personal_finance_ai import PersonalFinanceAI


class FakeRedisClient:
    def __init__(self):
        self.hashes = {}

    def hset(self, key, field, val):
        self.hashes.setdefault(key, {})
        self.hashes[key][field] = str(val)

    def hgetall(self, key):
        return self.hashes.get(key, {})

    def hincrby(self, key, field, n):
        self.hashes.setdefault(key, {})
        cur = int(self.hashes[key].get(field, 0))
        self.hashes[key][field] = str(cur + int(n))

    def expire(self, _key, _ttl):
        return True


class Tx:
    def __init__(self, tx_id, amount, category, ttype, date, desc=""):
        self.id = tx_id
        self.amount = amount
        self.category = category
        self.type = ttype
        self.date = date
        self.description = desc


class FakeDB:
    def __init__(self):
        self.now = datetime.now()

    def get_sliding_window_transactions(self, _uid, days=180):
        out = []
        for i in range(1, 120):
            d = self.now - timedelta(days=i)
            # Weekend higher spend
            amt = 200000 if d.weekday() >= 5 else 90000
            out.append(Tx(i, amt, "Makanan", "expense", d, "ngopi"))
        # Debt-like transactions
        out.append(Tx(999, 500000, "Cicilan", "expense", self.now - timedelta(days=10), "cicilan motor"))
        # Income
        for i in range(1, 7):
            d = self.now - timedelta(days=i * 30)
            out.append(Tx(2000 + i, 6000000, "Gaji", "income", d, "gaji"))
        return out

    def get_monthly_report(self, _uid, month, year):
        base_inc = 6000000
        base_exp = 4300000 + ((month % 3) * 300000)
        dt = datetime(year, month, 15)
        return [
            Tx(1, base_inc, "Gaji", "income", dt, "salary"),
            Tx(2, base_exp, "Belanja", "expense", dt, "spending"),
            Tx(3, 450000, "Cicilan", "expense", dt, "cicilan"),
        ]


def _engine():
    p = PersonaManager()
    eng = PersonalFinanceAI(FakeDB(), p)
    eng.redis.client = FakeRedisClient()
    return eng


def test_real_financial_intelligence_flags():
    eng = _engine()
    out = eng.real_financial_intelligence(1)
    assert out["ok"] is True
    assert "annual_inflation_pct" in out
    assert "income_stagnation" in out


def test_debt_optimizer_has_recommendation():
    eng = _engine()
    out = eng.debt_optimizer(1, extra_payment=300000)
    assert out["ok"] is True
    assert out["recommended"] in {"snowball", "avalanche"}


def test_scenario_simulation_returns_projection():
    eng = _engine()
    out = eng.simulate_scenario(1, "resign 6 bulan lagi")
    assert out["ok"] is True
    assert len(out["projection_12m"]) == 12


def test_net_worth_store_and_calc():
    eng = _engine()
    assert eng.set_asset(1, "crypto", 2000000) is True
    assert eng.set_liability(1, "cc", 1000000) is True
    out = eng.net_worth(1)
    assert out["total_assets"] >= 2000000
    assert out["total_liabilities"] >= 1000000


def test_persona_profile_assignment():
    p = PersonaManager()
    prof = p.set_financial_persona(10, "growth_aggressive")
    assert prof["risk_tolerance"] > 0.7
