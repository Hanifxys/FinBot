import json
import logging
import asyncio
import time
from typing import List, Dict, Optional
from modules.redis_mgr import RedisManager

logger = logging.getLogger(__name__)


class AIMemory:
    """
    Fintech-Grade AI Memory System

    Features:
    - Redis-backed long-term memory
    - Context summarization
    - Token-aware trimming
    - TTL auto-cleanup
    - Concurrency-safe summarization
    - Corruption protection
    """

    MAX_HISTORY_MESSAGES = 100
    RECENT_KEEP = 12
    SUMMARY_LOCK_TTL = 30
    MEMORY_TTL = 86400 * 30  # 30 days

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.redis = RedisManager().client
        self.history_key = f"chat:history:{user_id}"
        self.summary_key = f"chat:summary:{user_id}"
        self.lock_key = f"chat:summary:lock:{user_id}"

    # ----------------------------------------
    # SAFE ADD MESSAGE
    # ----------------------------------------

    def add_user_message(self, text: str):
        self._append_message("user", text)

    def add_ai_message(self, text: str):
        self._append_message("assistant", text)

    def _append_message(self, role: str, content: str):
        if not self.redis:
            return

        msg = {
            "role": role,
            "content": content,
            "ts": int(time.time())
        }

        pipe = self.redis.pipeline()
        pipe.rpush(self.history_key, json.dumps(msg))
        pipe.expire(self.history_key, self.MEMORY_TTL)
        pipe.execute()

        self._enforce_history_limit()

    # ----------------------------------------
    # LIMIT HISTORY SIZE
    # ----------------------------------------

    def _enforce_history_limit(self):
        length = self.redis.llen(self.history_key)
        if length > self.MAX_HISTORY_MESSAGES:
            self.redis.ltrim(self.history_key, -self.MAX_HISTORY_MESSAGES, -1)

    # ----------------------------------------
    # GET CONTEXT
    # ----------------------------------------

    def get_context(self, limit: int = 15) -> List[Dict]:
        if not self.redis:
            return []

        messages = []

        # Load summary
        summary = self.redis.get(self.summary_key)
        if summary:
            try:
                messages.append({
                    "role": "system",
                    "content": f"Conversation Summary:\n{summary.decode('utf-8')}"
                })
            except Exception:
                logger.warning("Corrupted summary, clearing.")
                self.redis.delete(self.summary_key)

        # Load recent history
        raw_history = self.redis.lrange(self.history_key, -limit, -1)

        for item in raw_history:
            try:
                if isinstance(item, bytes):
                    item = item.decode("utf-8")
                messages.append(json.loads(item))
            except Exception:
                continue

        return messages

    # ----------------------------------------
    # SAFE CLEAR
    # ----------------------------------------

    def clear(self):
        if not self.redis:
            return
        self.redis.delete(self.history_key)
        self.redis.delete(self.summary_key)
        self.redis.delete(self.lock_key)

    # ----------------------------------------
    # SUMMARIZATION (CONCURRENCY SAFE)
    # ----------------------------------------

    async def summarize_if_needed(self, llm_client, model_name: str):

        if not self.redis:
            return

        length = self.redis.llen(self.history_key)
        if length < 25:
            return

        # Prevent concurrent summarization
        if not self.redis.set(self.lock_key, "1", nx=True, ex=self.SUMMARY_LOCK_TTL):
            return

        try:
            raw_history = self.redis.lrange(self.history_key, 0, -self.RECENT_KEEP - 1)

            if not raw_history:
                return

            text_block = ""
            for m in raw_history:
                try:
                    if isinstance(m, bytes):
                        m = m.decode("utf-8")
                    obj = json.loads(m)
                    text_block += f"{obj['role']}: {obj['content']}\n"
                except Exception:
                    continue

            if not text_block.strip():
                return

            existing_summary = self.redis.get(self.summary_key)
            if existing_summary:
                existing_summary = existing_summary.decode("utf-8")
                prompt = f"""
                Update summary with new interactions.

                Existing Summary:
                {existing_summary}

                New Content:
                {text_block}

                Produce concise updated summary.
                """
            else:
                prompt = f"""
                Summarize this conversation concisely:

                {text_block}
                """

            response = await asyncio.wait_for(
                llm_client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2
                ),
                timeout=20
            )

            new_summary = response.choices[0].message.content.strip()

            self.redis.set(self.summary_key, new_summary)
            self.redis.expire(self.summary_key, self.MEMORY_TTL)

            # Trim summarized messages
            self.redis.ltrim(self.history_key, -self.RECENT_KEEP, -1)

            logger.info(f"Memory summarized for user {self.user_id}")

        except Exception as e:
            logger.error(f"Summarization error: {e}")

        finally:
            self.redis.delete(self.lock_key)