import redis
import os
from dotenv import load_dotenv

load_dotenv()

# Use rediss:// for TLS connection (Upstash requirement)
url = os.getenv("REDIS_URL")

print(f"--- Mengetes Koneksi Redis (Upstash TLS) ---")
print(f"Target URL: {url[:30]}...")

try:
    # ssl_cert_reqs=None is often needed for cloud providers like Upstash with self-signed or specific CA
    client = redis.from_url(url, decode_responses=True)
    response = client.ping()
    if response:
        print("✅ KONEKSI REDIS BERHASIL!")
        client.set("test_connection", "success")
        print(f"Data Test: {client.get('test_connection')}")
    else:
        print("❌ GAGAL: Redis tidak merespons ping.")
except Exception as e:
    print(f"❌ KONEKSI GAGAL: {e}")
