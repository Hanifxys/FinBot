import redis
import json
import os
import logging
from config import REDIS_URL # Pastikan REDIS_URL ada di config

class RedisManager:
    def __init__(self):
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.client = redis.from_url(url, decode_responses=True)
        self.pubsub = self.client.pubsub()
        logging.info("Redis Manager Initialized")

    def cache_user_budget(self, user_id, budget_data):
        """Simpan data budget ke Redis untuk akses instan"""
        key = f"budget:{user_id}"
        self.client.set(key, json.dumps(budget_data), ex=3600) # Expire 1 jam

    def get_cached_budget(self, user_id):
        key = f"budget:{user_id}"
        data = self.client.get(key)
        return json.loads(data) if data else None

    def publish_update(self, channel, message):
        """Kirim update ke WebSocket via Pub/Sub"""
        self.client.publish(channel, json.dumps(message))

    def subscribe_to_updates(self, channel, callback):
        """Listen ke update transaksi atau budget"""
        self.pubsub.subscribe(**{channel: callback})
        self.pubsub.run_in_thread(sleep_time=0.01)
