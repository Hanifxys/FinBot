import logging
import time
from typing import Dict, List, Optional
from modules.redis_mgr import RedisManager

logger = logging.getLogger(__name__)


class GamificationEngine:
    """
    Enterprise-Ready Gamification Engine

    Features:
    - XP + Leveling
    - Daily XP Cap
    - Anti-Spam Protection
    - Streak System
    - Tier System
    - Achievements
    - Weekly Challenge
    - Leaderboard (Global + Weekly)
    """

    # -----------------------------
    # CONFIGURATION
    # -----------------------------

    LEVEL_THRESHOLDS = {
        1: 0, 2: 100, 3: 300, 4: 600, 5: 1000,
        6: 1500, 7: 2100, 8: 2800, 9: 3600, 10: 5000
    }

    TITLES = {
        1: "Pemula Hemat 🌱",
        3: "Pengatur Uang 💰",
        5: "Juragan Cuan 💎",
        8: "Sultan Muda 👑",
        10: "Money Master 🚀"
    }

    TIERS = [
        (10, "Diamond 💎"),
        (7, "Platinum 🏆"),
        (5, "Gold 🥇"),
        (3, "Silver 🥈"),
        (1, "Bronze 🥉"),
    ]

    MAX_DAILY_XP = 300

    XP_MAP = {
        "chat": 2,
        "transaction": 15,
        "insight": 5,
        "daily_login": 50,
        "budget_set": 20
    }

    ACHIEVEMENTS = {
        "first_tx": "Transaksi Pertama 🎉",
        "tx_100": "100 Transaksi 🔥",
        "streak_7": "Konsisten 7 Hari 💪",
        "million_spent": "1 Juta Club 💸",
        "financial_guru": "Financial Guru 🧠",
        "budget_master": "Budget Master 🎯"
    }

    # -----------------------------
    # INIT
    # -----------------------------

    def __init__(self):
        self.redis = RedisManager()

    # -----------------------------
    # FINANCIAL HEALTH SCORE
    # -----------------------------

    async def calculate_financial_health_score(self, user_id: int, saving_rate: float, budget_adherence: float, debt_ratio: float = 0, impulse_index: float = 0) -> int:
        """
        Calculates Financial Health Score (0-100)
        Components:
        - Saving Rate (30%)
        - Budget Adherence (30%)
        - Debt Ratio (20%) - Lower is better
        - Impulse Index (20%) - Lower is better
        """
        score = 0
        
        # 1. Saving Rate (Target > 20%)
        # Score = min(100, (rate / 0.2) * 100) * 0.3
        s_score = min(100, (saving_rate / 0.2) * 100)
        score += s_score * 0.3
        
        # 2. Budget Adherence (Target > 90%)
        # Score = adherence * 100 * 0.3
        b_score = min(100, budget_adherence * 100)
        score += b_score * 0.3
        
        # 3. Debt Ratio (Target < 30%)
        # If debt > 30%, score drops. 
        # Score = max(0, 100 - (ratio/0.3)*100) * 0.2
        d_score = max(0, 100 - (debt_ratio / 0.3) * 100)
        score += d_score * 0.2
        
        # 4. Impulse Index (Target < 10%)
        # Score = max(0, 100 - (index/0.1)*100) * 0.2
        i_score = max(0, 100 - (impulse_index / 0.1) * 100)
        score += i_score * 0.2
        
        final_score = int(score)
        
        # Store score
        if self.redis.client:
            self.redis.client.set(f"user:{user_id}:health_score", final_score)
            
            # Award badges based on score
            if final_score >= 90:
                self.redis.client.sadd(f"user:{user_id}:achievements", self.ACHIEVEMENTS["financial_guru"])
            if budget_adherence >= 0.95:
                 self.redis.client.sadd(f"user:{user_id}:achievements", self.ACHIEVEMENTS["budget_master"])
                 
        return final_score

    # -----------------------------
    # XP SYSTEM
    # -----------------------------

    async def add_xp(self, user_id: int, action_type: str) -> Dict:
        if not self.redis.client:
            return {}

        base_xp = self.XP_MAP.get(action_type, 1)

        # Apply daily cap
        xp_to_add = self._apply_daily_cap(user_id, base_xp)
        if xp_to_add <= 0:
            return {"xp_gained": 0, "capped": True}

        xp_key = f"user:{user_id}:xp"
        level_key = f"user:{user_id}:level"

        try:
            # Optimized pipeline: Fetch current state and increment in one go? 
            # No, logic depends on result. 
            # But we can optimize fetching level
            
            # Atomic increment
            current_xp = self.redis.client.incrby(xp_key, xp_to_add)
            
            # Fetch level from cache or Redis
            # For simplicity, we just fetch from Redis but could be optimized
            current_level = int(self.redis.client.get(level_key) or 1)

            new_level = self._calculate_level(current_xp)

            leveled_up = False
            
            # Pipeline for updates
            pipe = self.redis.client.pipeline()
            
            if new_level > current_level:
                pipe.set(level_key, new_level)
                leveled_up = True
                self._assign_title_badge(user_id, new_level, pipe) # Modified to accept pipe

            # Update leaderboards
            pipe.zadd("leaderboard:xp", {str(user_id): current_xp})
            pipe.zadd("leaderboard:xp:weekly", {str(user_id): current_xp})
            
            pipe.execute()

            streak = await self.update_streak(user_id)

            return {
                "xp_gained": xp_to_add,
                "total_xp": current_xp,
                "current_level": new_level,
                "tier": self.get_tier(new_level),
                "title": self.get_title(new_level),
                "streak": streak,
                "leveled_up": leveled_up,
                "next_level_xp": self.LEVEL_THRESHOLDS.get(new_level + 1, None)
            }

        except Exception as e:
            logger.error(f"XP Error: {e}")
            return {}

    # -----------------------------
    # DAILY CAP
    # -----------------------------

    def _apply_daily_cap(self, user_id: int, xp: int) -> int:
        today_key = f"user:{user_id}:xp:daily"
        current = int(self.redis.client.get(today_key) or 0)

        if current >= self.MAX_DAILY_XP:
            return 0

        allowed = min(xp, self.MAX_DAILY_XP - current)

        pipe = self.redis.client.pipeline()
        pipe.incrby(today_key, allowed)
        pipe.expire(today_key, 86400)
        pipe.execute()

        return allowed

    # -----------------------------
    # LEVEL SYSTEM
    # -----------------------------

    def _calculate_level(self, xp: int) -> int:
        level = 1
        for lvl, threshold in sorted(self.LEVEL_THRESHOLDS.items()):
            if xp >= threshold:
                level = lvl
        return level

    def get_title(self, level: int) -> str:
        title = "Pemula Hemat 🌱"
        for lvl, t in sorted(self.TITLES.items()):
            if level >= lvl:
                title = t
        return title

    def get_tier(self, level: int) -> str:
        for lvl, tier in self.TIERS:
            if level >= lvl:
                return tier
        return "Bronze 🥉"

    def _assign_title_badge(self, user_id: int, level: int, pipe=None):
        badge = self.TITLES.get(level)
        if badge:
            key = f"user:{user_id}:badges"
            if pipe:
                pipe.sadd(key, badge)
            else:
                self.redis.client.sadd(key, badge)

    # -----------------------------
    # STREAK SYSTEM
    # -----------------------------

    async def update_streak(self, user_id: int) -> int:
        today = int(time.time() // 86400)

        last_key = f"user:{user_id}:last_day"
        streak_key = f"user:{user_id}:streak"

        last_day = self.redis.client.get(last_key)
        last_day = int(last_day) if last_day else None

        pipe = self.redis.client.pipeline()

        if last_day is None:
            pipe.set(streak_key, 1)
        elif today - last_day == 1:
            pipe.incr(streak_key)
        elif today == last_day:
            pass
        else:
            pipe.set(streak_key, 1)

        pipe.set(last_key, today)
        pipe.execute()

        return int(self.redis.client.get(streak_key) or 1)

    # -----------------------------
    # ACHIEVEMENTS
    # -----------------------------

    async def check_achievements(self, user_id: int, stats: Dict):
        unlocked = []

        if stats.get("total_tx", 0) == 1:
            unlocked.append("first_tx")

        if stats.get("total_tx", 0) >= 100:
            unlocked.append("tx_100")

        if stats.get("streak", 0) >= 7:
            unlocked.append("streak_7")

        if stats.get("total_spent", 0) >= 1_000_000:
            unlocked.append("million_spent")

        for key in unlocked:
            self.redis.client.sadd(
                f"user:{user_id}:achievements",
                self.ACHIEVEMENTS[key]
            )

        return unlocked

    # -----------------------------
    # PROFILE
    # -----------------------------

    async def get_user_profile(self, user_id: int) -> Dict:
        pipe = self.redis.client.pipeline()
        pipe.get(f"user:{user_id}:xp")
        pipe.get(f"user:{user_id}:level")
        pipe.smembers(f"user:{user_id}:badges")
        pipe.smembers(f"user:{user_id}:achievements")
        pipe.get(f"user:{user_id}:streak")
        res = pipe.execute()

        xp = int(res[0] or 0)
        level = int(res[1] or 1)
        badges = list(res[2] or [])
        achievements = list(res[3] or [])
        streak = int(res[4] or 0)
        
        health_score = int(self.redis.client.get(f"user:{user_id}:health_score") or 0)

        next_xp = self.LEVEL_THRESHOLDS.get(level + 1)
        progress = int((xp / next_xp) * 100) if next_xp else 100

        return {
            "xp": xp,
            "level": level,
            "tier": self.get_tier(level),
            "title": self.get_title(level),
            "badges": badges,
            "achievements": achievements,
            "streak": streak,
            "health_score": health_score,
            "progress_percent": min(progress, 100),
            "next_level_xp": next_xp
        }

    # -----------------------------
    # LEADERBOARD
    # -----------------------------

    async def get_leaderboard(self, limit: int = 10, weekly=False) -> List[Dict]:
        key = "leaderboard:xp:weekly" if weekly else "leaderboard:xp"
        top = self.redis.client.zrevrange(key, 0, limit - 1, withscores=True)

        leaderboard = []
        for rank, (uid, score) in enumerate(top):
            leaderboard.append({
                "rank": rank + 1,
                "user_id": uid,
                "xp": int(score)
            })
        return leaderboard