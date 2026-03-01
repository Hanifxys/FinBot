import json
import logging
import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from modules.redis_mgr import RedisManager

logger = logging.getLogger(__name__)


DEFAULT_REWARD_MARKETPLACE = [
    {"id": "premium_digest_7d", "name": "Premium Digest 7 Hari", "cost_xp": 200},
    {"id": "priority_ai_3d", "name": "Priority AI 3 Hari", "cost_xp": 350},
    {"id": "theme_pack", "name": "Theme Pack Dashboard", "cost_xp": 150},
]


class WeeklyChallengeManager:
    def __init__(self) -> None:
        self.redis = RedisManager()

    def _week_key(self) -> str:
        now = datetime.now()
        return f"{now.year}-W{now.isocalendar().week}"

    def _user_challenge_key(self, user_id: int) -> str:
        return f"user:{user_id}:challenge:{self._week_key()}"

    def assign_if_missing(self, user_id: int) -> Dict[str, Any]:
        templates = [
            {
                "type": "no_spend_day",
                "title": "No-Spend Day",
                "description": "Capai 2 hari tanpa pengeluaran non-esensial minggu ini.",
                "target": 2,
                "reward_xp": 80,
            },
            {
                "type": "budget_adherence",
                "title": "Budget Guardian",
                "description": "Pertahankan minimal 80% kategori tetap di bawah limit.",
                "target": 1,
                "reward_xp": 100,
            },
            {
                "type": "log_streak",
                "title": "Catat Terus",
                "description": "Catat transaksi minimal 5 hari minggu ini.",
                "target": 5,
                "reward_xp": 70,
            },
        ]
        if not self.redis.client:
            return templates[0]
        key = self._user_challenge_key(user_id)
        raw = self.redis.client.get(key)
        if raw:
            return json.loads(raw)
        item = random.choice(templates)
        item["progress"] = 0
        item["completed"] = False
        item["awarded"] = False
        self.redis.client.setex(key, 8 * 24 * 3600, json.dumps(item))
        return item

    def get_current(self, user_id: int) -> Dict[str, Any]:
        if not self.redis.client:
            return self.assign_if_missing(user_id)
        key = self._user_challenge_key(user_id)
        raw = self.redis.client.get(key)
        if raw:
            return json.loads(raw)
        return self.assign_if_missing(user_id)

    def update_progress(self, user_id: int, increment: int = 1) -> Dict[str, Any]:
        challenge = self.get_current(user_id)
        if challenge.get("completed"):
            return challenge
        challenge["progress"] = int(challenge.get("progress", 0)) + int(increment)
        if challenge["progress"] >= int(challenge.get("target", 1)):
            challenge["completed"] = True
        if self.redis.client:
            self.redis.client.setex(self._user_challenge_key(user_id), 8 * 24 * 3600, json.dumps(challenge))
        return challenge

    def mark_awarded(self, user_id: int) -> None:
        challenge = self.get_current(user_id)
        challenge["awarded"] = True
        if self.redis.client:
            self.redis.client.setex(self._user_challenge_key(user_id), 8 * 24 * 3600, json.dumps(challenge))

    def get_marketplace(self) -> List[Dict[str, Any]]:
        return list(DEFAULT_REWARD_MARKETPLACE)

    def redeem(self, user_id: int, item_id: str, gamify_engine) -> Dict[str, Any]:
        item = next((x for x in self.get_marketplace() if x["id"] == item_id), None)
        if not item:
            return {"ok": False, "msg": "Item tidak ditemukan."}
        profile = None
        try:
            profile = gamify_engine.redis.client.get(f"user:{user_id}:xp") if gamify_engine.redis.client else None
            current_xp = int(profile or 0)
        except Exception:
            current_xp = 0
        if current_xp < item["cost_xp"]:
            return {"ok": False, "msg": "XP tidak cukup."}
        if gamify_engine.redis.client:
            gamify_engine.redis.client.decrby(f"user:{user_id}:xp", int(item["cost_xp"]))
            gamify_engine.redis.client.lpush(
                f"user:{user_id}:rewards",
                json.dumps({"id": item_id, "redeemed_at": int(time.time())}),
            )
        return {"ok": True, "msg": f"Berhasil redeem: {item['name']}"}

