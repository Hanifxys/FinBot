import logging
import json
import time
from typing import Dict, List, Optional, Tuple
from modules.redis_mgr import RedisManager

logger = logging.getLogger(__name__)

class GamificationEngine:
    """
    High-Performance Gamification Engine powered by Redis.
    Features:
    - Real-time XP & Leveling
    - Daily Streak System
    - Dynamic Badges & Titles
    - Leaderboard Capability
    """
    
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

    def __init__(self):
        self.redis = RedisManager()
        
    async def add_xp(self, user_id: int, action_type: str) -> Dict[str, any]:
        """
        Add XP to user and check for level up.
        Returns dict with status update.
        """
        if not self.redis.client:
            return {}

        xp_map = {
            "chat": 2,
            "transaction": 15,
            "insight": 5,
            "daily_login": 50,
            "budget_set": 20
        }
        
        amount = xp_map.get(action_type, 1)
        
        # Redis Keys
        xp_key = f"user:{user_id}:xp"
        level_key = f"user:{user_id}:level"
        
        try:
            # Atomic increment
            current_xp = self.redis.client.incrby(xp_key, amount)
            current_level_raw = self.redis.client.get(level_key)
            current_level = int(current_level_raw) if current_level_raw else 1
            
            # Check Level Up
            new_level = current_level
            leveled_up = False
            
            # Use sorted keys for efficient threshold check
            sorted_levels = sorted(self.LEVEL_THRESHOLDS.keys())
            
            # Determine correct level based on XP
            calc_level = 1
            for lvl in sorted_levels:
                if current_xp >= self.LEVEL_THRESHOLDS[lvl]:
                    calc_level = lvl
                else:
                    break
            
            if calc_level > current_level:
                new_level = calc_level
                self.redis.client.set(level_key, new_level)
                leveled_up = True
                
                # Award Badge if applicable
                badge = self.TITLES.get(new_level)
                if badge:
                    self.redis.client.sadd(f"user:{user_id}:badges", badge)

            # Update Leaderboard
            self.redis.client.zadd("leaderboard:xp", {str(user_id): current_xp})

            return {
                "xp_gained": amount,
                "total_xp": current_xp,
                "current_level": new_level,
                "leveled_up": leveled_up,
                "title": self.get_title_for_level(new_level),
                "next_level_xp": self.LEVEL_THRESHOLDS.get(new_level + 1, 999999)
            }
            
        except Exception as e:
            logger.error(f"Gamification Error: {e}")
            return {}

    async def get_user_profile(self, user_id: int) -> Dict[str, any]:
        """Fetch full gamification profile from Redis (Low Latency)"""
        if not self.redis.client:
            return {"level": 1, "xp": 0, "badges": [], "streak": 0}

        try:
            pipe = self.redis.client.pipeline()
            pipe.get(f"user:{user_id}:xp")
            pipe.get(f"user:{user_id}:level")
            pipe.smembers(f"user:{user_id}:badges")
            pipe.get(f"user:{user_id}:streak")
            
            res = pipe.execute()
            
            xp = int(res[0]) if res[0] else 0
            level = int(res[1]) if res[1] else 1
            
            # Handle badges (set returns list of bytes or strings depending on client config)
            # Assuming decode_responses=True in RedisManager based on common practice, 
            # but safer to handle both.
            badges_raw = res[2] or []
            badges = []
            for b in badges_raw:
                if isinstance(b, bytes):
                    badges.append(b.decode('utf-8'))
                else:
                    badges.append(str(b))
                    
            streak = int(res[3]) if res[3] else 0
            
            next_xp = self.LEVEL_THRESHOLDS.get(level + 1, 999999)
            progress = min(100, int((xp / next_xp) * 100)) if next_xp > 0 else 100

            return {
                "level": level,
                "xp": xp,
                "badges": badges,
                "streak": streak,
                "title": self.get_title_for_level(level),
                "progress_percent": progress,
                "next_level_xp": next_xp
            }
        except Exception as e:
            logger.error(f"Profile Fetch Error: {e}")
            return {"level": 1, "xp": 0, "badges": [], "streak": 0}

    def get_title_for_level(self, level: int) -> str:
        # Find highest title <= current level
        title = "Pemula Hemat 🌱"
        for l, t in sorted(self.TITLES.items()):
            if level >= l:
                title = t
        return title

    async def get_leaderboard(self, limit: int = 10) -> List[Dict[str, any]]:
        """Get top users by XP"""
        if not self.redis.client:
            return []
            
        try:
            # ZREVRANGE to get top scores
            top_users = self.redis.client.zrevrange("leaderboard:xp", 0, limit - 1, withscores=True)
            
            leaderboard = []
            for i, (uid, score) in enumerate(top_users):
                # Fetch basic user info (level) for context
                # Ideally fetch username from DB, but for speed we just use ID or cache
                lvl = self.redis.client.get(f"user:{uid}:level")
                leaderboard.append({
                    "rank": i + 1,
                    "user_id": uid,
                    "xp": int(score),
                    "level": int(lvl) if lvl else 1
                })
            return leaderboard
        except Exception as e:
            logger.error(f"Leaderboard Error: {e}")
            return []
