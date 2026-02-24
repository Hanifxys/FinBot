import psycopg2

# Configuration
password = "SupabaseBaru123"
project_id = "ecdehktkemlkbpehkiiq"
host = "aws-1-ap-southeast-1.pooler.supabase.com"

print("\n--- Mencoba User: postgres dengan options=-c project=... (Password Baru) ---")
try:
    connection = psycopg2.connect(
        user="postgres",
        password=password,
        host=host,
        port=6543,
        dbname="postgres",
        sslmode='require',
        options=f"-c project={project_id}",
        connect_timeout=5
    )
    print("✅ BERHASIL!")
    connection.close()
except Exception as e:
    print(f"❌ Gagal: {e}")

print("\n--- Mencoba User: postgres.project_id (Password Baru) ---")
try:
    connection = psycopg2.connect(
        user=f"postgres.{project_id}",
        password=password,
        host=host,
        port=6543,
        dbname="postgres",
        sslmode='require',
        connect_timeout=5
    )
    print("✅ BERHASIL!")
    connection.close()
except Exception as e:
    print(f"❌ Gagal: {e}")
