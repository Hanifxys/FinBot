import psycopg2

# Configuration from your last input
password = "6RRLOK5fZvdU4xql"
project_id = "ecdehktkemlkbpehkiiq"

# We must use the Pooler host because db.ecdehktkemlkbpehkiiq.supabase.co is IPv6-only
# and your network/environment does not support IPv6.
host_ipv4 = "aws-1-ap-southeast-1.pooler.supabase.com"

# When using the pooler, the user MUST include the project ID
user_pooler = f"postgres.{project_id}"

print(f"--- Mengetes Koneksi (Solusi IPv4) ---")
print(f"Host: {host_ipv4}")
print(f"User: {user_pooler}")

try:
    conn = psycopg2.connect(
        user=user_pooler,
        password=password,
        host=host_ipv4,
        port=6543,
        dbname="postgres",
        sslmode="require",
        connect_timeout=5
    )
    print("✅ BERHASIL!")
    conn.close()
except Exception as e:
    print(f"❌ GAGAL: {e}")
    print("\nAnalisis:")
    if "Tenant or user not found" in str(e):
        print("- Server Supabase menerima koneksi, tapi tidak mengenali Tenant ID.")
        print("- Ini berarti koneksi jaringan SUDAH OK, tapi ada masalah di Supabase-nya.")
        print("- Coba Reset Database Password di Dashboard Supabase.")
    else:
        print("- Ada masalah lain pada koneksi.")
