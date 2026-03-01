import json
import logging
import os
import time

import redis

from config import REDIS_URL


class RedisManager:
    def __init__(self):
        self.url = REDIS_URL or os.getenv("REDIS_URL")
        self.client = None
        self.pubsub = None
        self._in_memory_cache = {}

        # Circuit breaker state
        self._cb_failures = 0
        self._cb_open_until = 0.0
        self._cb_threshold = int(os.getenv("REDIS_CB_THRESHOLD", "3"))
        self._cb_cooldown_seconds = int(os.getenv("REDIS_CB_COOLDOWN_SECONDS", "15"))

        if self.url:
            try:
                self.client = redis.from_url(self.url, decode_responses=True)
                self.client.ping()
                self.pubsub = self.client.pubsub()
                logging.info("Redis connected: %s...", self.url[:20])
            except Exception as e:
                logging.error("Redis connection failed: %s. Falling back to in-memory.", e)
                self.client = None
        else:
            logging.warning("REDIS_URL not found. Using in-memory cache (non-persistent).")

    def _cb_is_open(self) -> bool:
        return time.time() < self._cb_open_until

    def _cb_on_success(self) -> None:
        self._cb_failures = 0
        self._cb_open_until = 0.0

    def _cb_on_failure(self) -> None:
        self._cb_failures += 1
        if self._cb_failures >= self._cb_threshold:
            self._cb_open_until = time.time() + self._cb_cooldown_seconds
            logging.warning("Redis circuit breaker opened for %ss", self._cb_cooldown_seconds)

    def execute(self, fn, fallback=None):
        """
        Execute a Redis operation under circuit breaker protection.
        fn should be a no-arg callable that uses self.client.
        """
        if not self.client or self._cb_is_open():
            return fallback
        try:
            out = fn()
            self._cb_on_success()
            return out
        except Exception as e:
            logging.error("Redis execute failed: %s", e)
            self._cb_on_failure()
            return fallback

    def cache_user_budget(self, user_id, budget_data):
        key = f"budget:{user_id}"
        ok = self.execute(lambda: self.client.set(key, json.dumps(budget_data), ex=3600), fallback=False)
        if ok:
            return
        self._in_memory_cache[key] = budget_data

    def get_cached_budget(self, user_id):
        key = f"budget:{user_id}"
        data = self.execute(lambda: self.client.get(key), fallback=None)
        if data:
            try:
                return json.loads(data)
            except Exception:
                return None
        return self._in_memory_cache.get(key)

    def publish_update(self, channel, message):
        ok = self.execute(lambda: self.client.publish(channel, json.dumps(message)), fallback=False)
        if ok:
            return
        logging.info("[LOCAL PUB] Channel %s: %s", channel, message)

    def subscribe_to_updates(self, channel, callback):
        if not self.client:
            logging.warning("Pub/Sub disabled (no Redis). Cannot listen to %s", channel)
            return
        try:
            self.pubsub.subscribe(**{channel: callback})
            self.pubsub.run_in_thread(sleep_time=0.01)
            logging.info("Subscribed to Redis channel: %s", channel)
        except Exception as e:
            logging.error("Failed to subscribe to Redis: %s", e)
            self._cb_on_failure()
