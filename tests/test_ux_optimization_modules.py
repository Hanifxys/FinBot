from datetime import datetime, timedelta

from modules.ux_analytics import UXAnalytics
from modules.recurring import RecurringManager
from modules.budget_autopilot import BudgetAutopilot
from modules.weekly_challenges import WeeklyChallengeManager


class FakeRedisClient:
    def __init__(self):
        self.kv = {}
        self.lists = {}
        self.hashes = {}

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, val):
        self.kv[key] = str(val)
        return True

    def setex(self, key, _ttl, val):
        self.kv[key] = str(val)
        return True

    def delete(self, key):
        self.kv.pop(key, None)

    def lpush(self, key, val):
        self.lists.setdefault(key, [])
        self.lists[key].insert(0, val)

    def ltrim(self, key, start, end):
        vals = self.lists.get(key, [])
        self.lists[key] = vals[start : end + 1]

    def lrange(self, key, start, end):
        vals = self.lists.get(key, [])
        if end == -1:
            return vals[start:]
        return vals[start : end + 1]

    def hset(self, key, field, val):
        self.hashes.setdefault(key, {})
        self.hashes[key][field] = val

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hvals(self, key):
        return list(self.hashes.get(key, {}).values())

    def hincrby(self, key, field, amount):
        self.hashes.setdefault(key, {})
        cur = int(self.hashes[key].get(field, 0))
        self.hashes[key][field] = str(cur + int(amount))

    def decrby(self, key, amount):
        cur = int(self.kv.get(key, 0))
        self.kv[key] = str(cur - int(amount))


class Tx:
    def __init__(self, tx_id, amount, category, desc, dt):
        self.id = tx_id
        self.amount = amount
        self.category = category
        self.description = desc
        self.date = dt
        self.type = "expense"


class Budget:
    def __init__(self, category, limit_amount, current_usage):
        self.category = category
        self.limit_amount = limit_amount
        self.current_usage = current_usage


class FakeDB:
    def __init__(self):
        now = datetime.now()
        self.txs = [
            Tx(1, 50000, "Makanan", "Nasi Padang", now - timedelta(days=6)),
            Tx(2, 50000, "Makanan", "Nasi Padang", now - timedelta(days=3)),
            Tx(3, 50000, "Makanan", "Nasi Padang", now - timedelta(days=1)),
        ]
        self.budgets = {
            "Makanan": Budget("Makanan", 1_000_000, 970_000),
            "Hiburan": Budget("Hiburan", 800_000, 120_000),
        }

    def get_transactions_history(self, _user_id, limit=200, category=None, start_date=None, **_kwargs):
        data = self.txs[:limit]
        if category:
            data = [t for t in data if t.category == category]
        if start_date:
            data = [t for t in data if t.date >= start_date]
        return data

    def get_user_budgets(self, _user_id):
        return list(self.budgets.values())

    def get_budget(self, _user_id, category):
        return self.budgets.get(category)

    def set_budget(self, _user_id, category, value):
        b = self.budgets.get(category)
        if not b:
            b = Budget(category, value, 0)
            self.budgets[category] = b
        b.limit_amount = float(value)
        return b


class FakeGamify:
    class _R:
        def __init__(self, client):
            self.client = client

    def __init__(self, client):
        self.redis = self._R(client)


def test_ux_analytics_funnel_summary():
    ux = UXAnalytics()
    ux.redis.client = FakeRedisClient()

    ux.track(user_id=101, event="preview_shown", props={"source": "test"})
    ux.track(user_id=101, event="confirm", props={"source": "test"})
    ux.track(user_id=101, event="cancel", props={"source": "test"})

    summary = ux.funnel_summary(days=7)
    assert summary["counts"]["preview_shown"] == 1
    assert summary["counts"]["confirm"] == 1
    assert summary["conversion_rate_preview_to_confirm_pct"] == 100.0
    assert summary["cancel_rate_pct"] == 100.0


def test_recurring_detect_candidate_and_sensitivity():
    db = FakeDB()
    mgr = RecurringManager(db)
    mgr.redis.client = FakeRedisClient()

    assert mgr.set_sensitivity(1, 2) is True
    assert mgr.get_sensitivity(1) == 2

    cand = mgr.detect_candidate(
        1,
        category="Makanan",
        description="Nasi Padang",
        amount=50000,
        min_occurrences=mgr.get_sensitivity(1),
    )
    assert cand is not None
    assert cand["hits"] >= 3


def test_budget_autopilot_suggest_and_apply():
    db = FakeDB()
    ap = BudgetAutopilot(db)
    ap.redis.client = FakeRedisClient()

    proposal = ap.suggest_rebalance(user_db_id=1)
    assert proposal is not None
    assert proposal["to_category"] == "Makanan"

    ok = ap.apply_proposal(1, proposal)
    assert ok is True
    assert db.get_budget(1, "Makanan").limit_amount > 1_000_000


def test_weekly_challenge_redeem():
    wc = WeeklyChallengeManager()
    client = FakeRedisClient()
    wc.redis.client = client

    challenge = wc.get_current(1001)
    assert challenge.get("title")

    client.set("user:1001:xp", 500)
    gamify = FakeGamify(client)
    result = wc.redeem(1001, "theme_pack", gamify)

    assert result["ok"] is True
    assert int(client.get("user:1001:xp")) == 350
