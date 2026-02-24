import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

# Use Transaction Pooler (IPv4) because direct host is IPv6-only
HOST = "aws-1-ap-southeast-1.pooler.supabase.com"
PORT = 6543
USER = "postgres.ecdehktkemlkbpehkiiq"
DBNAME = "postgres"
PASSWORD = "6RRLOK5fZvdU4xql"

ssl_modes = ['require', 'prefer', 'allow', 'disable']

print(f"--- Mengetes Koneksi ke {HOST}:{PORT} (IPv4) ---")
print(f"User: {USER}\n")

for mode in ssl_modes:
    print(f"Mencoba SSL Mode: {mode}...", end=" ", flush=True)
    try:
        conn = psycopg2.connect(
            host=HOST,
            port=PORT,
            user=USER,
            password=PASSWORD,
            dbname=DBNAME,
            sslmode=mode,
            connect_timeout=5
        )
        print("✅ BERHASIL!")
        conn.close()
        break
    except Exception as e:
        error_msg = str(e).strip()
        if "Tenant or user not found" in error_msg:
            print("❌ GAGAL: Tenant not found (Server menolak tenant ID)")
        elif "SSL error" in error_msg or "no SSL" in error_msg:
            print(f"❌ GAGAL: SSL Error ({error_msg[:50]}...)")
        else:
            print(f"❌ GAGAL: {error_msg[:100]}")

print("\nAnalisis:")
print("- Jika semua mode SSL memberikan 'Tenant not found', berarti masalahnya bukan di SSL, melainkan di Auth/Tenant ID.")
print("- Jika 'direct host' (5432) memberikan 'Name or service not known', berarti jaringan Anda memang tidak mendukung IPv6.")
