import psycopg2
from dotenv import load_dotenv
import os

# Load environment variables from .env
load_dotenv()

# Fetch variables
USER = os.getenv("user")
PASSWORD = os.getenv("password")
HOST = os.getenv("host")
PORT = os.getenv("port")
DBNAME = os.getenv("dbname")

def delete_settings():
    try:
        # Connect to the database
        # Using the host from .env directly first
        connection = psycopg2.connect(
            user=USER,
            password=PASSWORD,
            host=HOST,
            port=PORT,
            dbname=DBNAME
        )
        print("Connection successful!")
        
        cursor = connection.cursor()
        
        # Delete query for id 1 to 95
        query = "DELETE FROM app_rms.at_m_setting WHERE id >= 1 AND id <= 95;"
        print(f"Executing: {query}")
        
        cursor.execute(query)
        rows_deleted = cursor.rowcount
        
        connection.commit()
        print(f"Successfully deleted {rows_deleted} rows.")

        cursor.close()
        connection.close()
        print("Connection closed.")

    except Exception as e:
        print(f"Error: {e}")
        print("\nTip: Jika error 'could not translate host name', kemungkinan koneksi internet anda tidak mendukung IPv6.")
        print("Gunakan Connection Pooler Supabase (Port 6543) atau aktifkan IPv4 di dashboard Supabase.")

if __name__ == "__main__":
    delete_settings()
