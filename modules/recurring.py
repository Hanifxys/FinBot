import hashlib
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from modules.redis_mgr import RedisManager

logger = logging.getLogger(__name__)


class RecurringManager:
    """
    Detect repeated transactions and manage recurring templates.
    """

    def __init__(self, db_handler) -> None:
        self.db = db_handler
        self.redis = RedisManager()
        self.default_min_occurrences = 3
        self.window_days = 7

    def _sensitivity_key(self, user_id: int) -> str:
        return f"user:{user_id}:recurring_sensitivity"

    def get_sensitivity(self, user_id: int) -> int:
        if not self.redis.client:
            return self.default_min_occurrences
        try:
            raw = self.redis.client.get(self._sensitivity_key(user_id))
            if raw is None:
                return self.default_min_occurrences
            val = int(raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw))
            return max(2, min(6, val))
        except Exception:
            return self.default_min_occurrences

    def set_sensitivity(self, user_id: int, value: int) -> bool:
        if not self.redis.client:
            return False
        try:
            value = max(2, min(6, int(value)))
            self.redis.client.set(self._sensitivity_key(user_id), str(value))
            return True
        except Exception:
            return False

    @staticmethod
    def _signature(category: str, description: str, amount: float) -> str:
        data = f"{category.lower().strip()}|{description.lower().strip()}|{int(round(amount))}"
        return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]

    def detect_candidate(
        self,
        user_db_id: int,
        *,
        category: str,
        description: str,
        amount: float,
        min_occurrences: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        min_n = min_occurrences or self.default_min_occurrences
        start = datetime.now() - timedelta(days=self.window_days)
        txs = self.db.get_transactions_history(
            user_db_id,
            limit=200,
            category=category,
            start_date=start,
        )
        sig = self._signature(category, description, amount)
        hits = 0
        last_dates: List[datetime] = []
        for tx in txs:
            tx_sig = self._signature(
                getattr(tx, "category", ""),
                getattr(tx, "description", "") or "",
                float(getattr(tx, "amount", 0) or 0),
            )
            if tx_sig == sig:
                hits += 1
                dt = getattr(tx, "date", None)
                if isinstance(dt, datetime):
                    last_dates.append(dt)
        if hits < min_n:
            return None

        interval_days = 7
        if len(last_dates) >= 2:
            last_dates = sorted(last_dates)
            diffs = []
            for i in range(1, len(last_dates)):
                d = (last_dates[i] - last_dates[i - 1]).days
                if d > 0:
                    diffs.append(d)
            if diffs:
                interval_days = max(1, int(round(sum(diffs) / len(diffs))))

        next_due = datetime.now() + timedelta(days=interval_days)
        return {
            "signature": sig,
            "hits": hits,
            "interval_days": interval_days,
            "next_due_ts": int(next_due.timestamp()),
            "template": {
                "category": category,
                "description": description,
                "amount": float(amount),
                "type": "expense",
            },
        }

    def save_template(self, user_id: int, candidate: Dict[str, Any]) -> bool:
        if not self.redis.client:
            return False
        try:
            key = f"user:{user_id}:recurring:templates"
            self.redis.client.hset(key, candidate["signature"], json.dumps(candidate))
            return True
        except Exception as exc:
            logger.warning("save_template failed: %s", exc)
            return False

    def list_due_reminders(self, user_id: int, within_hours: int = 24) -> List[Dict[str, Any]]:
        if not self.redis.client:
            return []
        out: List[Dict[str, Any]] = []
        now_ts = int(time.time())
        limit_ts = now_ts + within_hours * 3600
        key = f"user:{user_id}:recurring:templates"
        try:
            templates = self.redis.client.hvals(key)
            for raw in templates:
                item = json.loads(raw)
                due_ts = int(item.get("next_due_ts", 0))
                if now_ts <= due_ts <= limit_ts:
                    out.append(item)
        except Exception:
            return []
        return out

    def mark_reminded(self, user_id: int, signature: str) -> None:
        if not self.redis.client:
            return
        try:
            key = f"user:{user_id}:recurring:last_reminded:{signature}"
            self.redis.client.setex(key, 24 * 3600, str(int(time.time())))
        except Exception:
            pass

    def recently_reminded(self, user_id: int, signature: str) -> bool:
        if not self.redis.client:
            return False
        try:
            return bool(self.redis.client.get(f"user:{user_id}:recurring:last_reminded:{signature}"))
        except Exception:
            return False

