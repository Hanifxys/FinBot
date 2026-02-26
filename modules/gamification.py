import logging
from typing import Dict, Any
from modules.redis_mgr import RedisManager

logger = logging.getLogger(__name__)

class GamificationEngine:
    """
    Elite Experience: Gamification Engine
    Increases user engagement via achievements, streaks, and XP leveling.
    """
    def __init__(self, redis_mgr: RedisManager):
        self.redis = redis_mgr
        self.xp_per_transaction = 10
        self.xp_per_voice_note = 25
        self.xp_per_insight_query = 5

    async def add_xp(self, user_id: int, action_type: str) -> Dict[str, Any]:
        """Menambah XP user berdasarkan aktivitas"""
        xp_to_add = getattr(self, f"xp_per_{action_type}", 5)
        
        key = f"user_stats:{user_id}"
        current_xp = int(self.redis.client.hget(key, "xp") or 0)
        new_xp = current_xp + xp_to_add
        
        # Simple Leveling: Level = floor(sqrt(XP / 100)) + 1
        import math
        new_level = math.floor(math.sqrt(new_xp / 100)) + 1
        
        self.redis.client.hset(key, mapping={
            "xp": new_xp,
            "level": new_level
        })
        
        return {
            "xp_added": xp_to_add,
            "total_xp": new_xp,
            "level": new_level,
            "leveled_up": new_level > math.floor(math.sqrt(current_xp / 100)) + 1 if current_xp > 0 else False
        }

    async def get_user_rank(self, user_id: int) -> str:
        """Mendapatkan title berdasarkan level"""
        level = int(self.redis.client.hget(f"user_stats:{user_id}", "level") or 1)
        if level < 5: return "Novice Saver"
        if level < 15: return "Financial Warrior"
        if level < 30: return "Elite Investor"
        return "CFO Master"
