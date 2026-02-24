import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

def test_db_connection():
    try:
        print(f"Testing connection to: {DATABASE_URL.split('@')[-1]}") # Hide credentials
        engine = create_engine(DATABASE_URL)
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))
            print(f"Connection successful! Result: {result.fetchone()}")
            
            # Try to list tables
            result = connection.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'"))
            tables = [row[0] for row in result]
            print(f"Tables in 'public' schema: {tables}")
            
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    test_db_connection()
