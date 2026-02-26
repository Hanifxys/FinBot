import redis
import json
import os
import logging
from config import REDIS_URL

class RedisManager:
    def __init__(self):
        self.url = REDIS_URL or os.getenv("REDIS_URL")
        self.client = None
        self.pubsub = None
        self._in_memory_cache = {} # Fallback if Redis is not available
        
        if self.url:
            try:
                self.client = redis.from_url(self.url, decode_responses=True)
                self.client.ping() # Test connection
                self.pubsub = self.client.pubsub()
                logging.info(f"✅ Redis Connected: {self.url[:20]}...")
            except Exception as e:
                logging.error(f"❌ Redis Connection Failed: {e}. Falling back to In-Memory.")
                self.client = None
        else:
            logging.warning("⚠️ REDIS_URL not found. Using In-Memory Cache (Not persistent).")

    def cache_user_budget(self, user_id, budget_data):
        """Simpan data budget ke Redis atau In-Memory"""
        key = f"budget:{user_id}"
        if self.client:
            try:
                self.client.set(key, json.dumps(budget_data), ex=3600)
                return
            except:
                pass
        
        # Fallback to in-memory
        self._in_memory_cache[key] = budget_data

    def get_cached_budget(self, user_id):
        key = f"budget:{user_id}"
        if self.client:
            try:
                data = self.client.get(key)
                return json.loads(data) if data else None
            except:
                pass
        
        # Fallback to in-memory
        return self._in_memory_cache.get(key)

    def publish_update(self, channel, message):
        """Kirim update ke WebSocket via Pub/Sub atau Logging"""
        if self.client:
            try:
                self.client.publish(channel, json.dumps(message))
                return
            except:
                pass
        
        logging.info(f"[LOCAL PUB] Channel {channel}: {message}")

    def subscribe_to_updates(self, channel, callback):
        """Listen ke update transaksi atau budget (Hanya jika Redis ada)"""
        if self.client:
            try:
                self.pubsub.subscribe(**{channel: callback})
                self.pubsub.run_in_thread(sleep_time=0.01)
                logging.info(f"Subscribed to Redis channel: {channel}")
            except Exception as e:
                logging.error(f"Failed to subscribe to Redis: {e}")
        else:
            logging.warning(f"Pub/Sub disabled (No Redis). Cannot listen to {channel}")
