import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from modules.redis_mgr import RedisManager

logger = logging.getLogger(__name__)


class BudgetAutopilot:
    """
    Suggest budget rebalancing when overspending is detected.
    """

    def __init__(self, db_handler):
        self.db = db_handler
        self.redis = RedisManager()

    def detect_overspending(self, user_db_id: int) -> List[Dict[str, Any]]:
        budgets = self.db.get_user_budgets(user_db_id) or []
        out: List[Dict[str, Any]] = []
        for b in budgets:
            limit_amount = float(getattr(b, "limit_amount", 0) or 0)
            usage = float(getattr(b, "current_usage", 0) or 0)
            if limit_amount <= 0:
                continue
            pct = usage / limit_amount
            if pct >= 0.9:
                out.append(
                    {
                        "category": getattr(b, "category", "Unknown"),
                        "usage": usage,
                        "limit": limit_amount,
                        "ratio": pct,
                    }
                )
        return sorted(out, key=lambda x: x["ratio"], reverse=True)

    def _underutilized(self, user_db_id: int) -> List[Dict[str, Any]]:
        budgets = self.db.get_user_budgets(user_db_id) or []
        out = []
        for b in budgets:
            limit_amount = float(getattr(b, "limit_amount", 0) or 0)
            usage = float(getattr(b, "current_usage", 0) or 0)
            if limit_amount <= 0:
                continue
            ratio = usage / limit_amount
            if ratio < 0.4:
                out.append(
                    {
                        "category": getattr(b, "category", "Unknown"),
                        "free_amount": max(0.0, limit_amount - usage),
                        "usage_ratio": ratio,
                    }
                )
        return sorted(out, key=lambda x: x["free_amount"], reverse=True)

    def suggest_rebalance(self, user_db_id: int) -> Optional[Dict[str, Any]]:
        overs = self.detect_overspending(user_db_id)
        unders = self._underutilized(user_db_id)
        if not overs or not unders:
            return None

        target = overs[0]
        source = unders[0]
        transfer = min(source["free_amount"] * 0.3, max(50000.0, target["limit"] * 0.1))
        if transfer < 25000:
            return None

        proposal_id = hashlib.sha256(
            f"{user_db_id}:{target['category']}:{source['category']}:{datetime.now().isoformat()}".encode("utf-8")
        ).hexdigest()[:16]
        return {
            "proposal_id": proposal_id,
            "to_category": target["category"],
            "from_category": source["category"],
            "transfer_amount": round(transfer, 2),
            "impact": {
                "target_ratio_after": round((target["usage"] / (target["limit"] + transfer)), 4),
                "source_buffer_after": round(max(0.0, source["free_amount"] - transfer), 2),
            },
            "created_at": datetime.now().isoformat(),
        }

    def save_proposal(self, user_id: int, proposal: Dict[str, Any]) -> bool:
        if not self.redis.client:
            return False
        try:
            self.redis.client.hset(
                f"user:{user_id}:autopilot:proposals",
                proposal["proposal_id"],
                json.dumps(proposal, ensure_ascii=False),
            )
            return True
        except Exception:
            return False

    def get_proposal(self, user_id: int, proposal_id: str) -> Optional[Dict[str, Any]]:
        if not self.redis.client:
            return None
        try:
            raw = self.redis.client.hget(f"user:{user_id}:autopilot:proposals", proposal_id)
            if not raw:
                return None
            return json.loads(raw)
        except Exception:
            return None

    def apply_proposal(self, user_db_id: int, proposal: Dict[str, Any]) -> bool:
        try:
            transfer = float(proposal["transfer_amount"])
            from_cat = proposal["from_category"]
            to_cat = proposal["to_category"]

            from_budget = self.db.get_budget(user_db_id, from_cat)
            to_budget = self.db.get_budget(user_db_id, to_cat)
            if not from_budget or not to_budget:
                return False

            from_new = max(0.0, float(getattr(from_budget, "limit_amount", 0) or 0) - transfer)
            to_new = float(getattr(to_budget, "limit_amount", 0) or 0) + transfer
            self.db.set_budget(user_db_id, from_cat, from_new)
            self.db.set_budget(user_db_id, to_cat, to_new)
            return True
        except Exception as exc:
            logger.warning("apply_proposal failed: %s", exc)
            return False

    def record_decision(self, user_id: int, approved: bool) -> None:
        if not self.redis.client:
            return
        try:
            key = "approved" if approved else "rejected"
            self.redis.client.hincrby(f"user:{user_id}:autopilot:stats", key, 1)
        except Exception:
            pass

