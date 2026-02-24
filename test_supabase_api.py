import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

print(f"--- Mengetes Koneksi Supabase Client ---")
print(f"URL: {url}")

try:
    supabase: Client = create_client(url, key)
    
    # Try to fetch something simple (e.g., users table or just check health)
    # Using a generic query to check connection
    response = supabase.table("users").select("*").limit(1).execute()
    
    print("\n✅ KONEKSI BERHASIL!")
    print(f"Data Sample: {response.data}")

except Exception as e:
    print(f"\n❌ KONEKSI GAGAL: {e}")
    print("\nAnalisis:")
    print("1. Pastikan SUPABASE_URL dan SUPABASE_KEY di .env sudah benar.")
    print("2. Jika error 'API key not found', pastikan Key yang dipakai adalah 'service_role' atau 'anon' key yang valid.")
