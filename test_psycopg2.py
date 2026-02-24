import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

# Configuration
USER = os.getenv("user")
PASSWORD = os.getenv("password")
HOST = os.getenv("host")
PORT = os.getenv("port")
DBNAME = os.getenv("dbname")

print(f"--- Mengetes Koneksi Supabase Pooler (IPv4) ---")
print(f"Host: {HOST}")
print(f"User: {USER}")
print(f"Password: {PASSWORD}")

try:
    connection = psycopg2.connect(
        user=USER,
        password=PASSWORD,
        host=HOST,
        port=PORT,
        dbname=DBNAME,
        sslmode='require',
        connect_timeout=10
    )
    print("\n✅ KONEKSI BERHASIL!")
    
    cursor = connection.cursor()
    cursor.execute("SELECT NOW();")
    print("Waktu Server:", cursor.fetchone()[0])
    
    # Check current database name
    cursor.execute("SELECT current_database();")
    print("Database:", cursor.fetchone()[0])
    
    cursor.close()
    connection.close()
    print("\nKoneksi ditutup dengan sukses.")

except Exception as e:
    print(f"\n❌ KONEKSI GAGAL: {e}")
    if "Tenant or user not found" in str(e):
        print("\nCatatan: Pooler Supabase masih belum mengenali Project ID Anda.")
        print("Tunggu 1-2 menit lagi agar sinkronisasi password selesai.")
