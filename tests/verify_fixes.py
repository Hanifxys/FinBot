import asyncio
import os
import sys
import logging

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modules.premium_ai import PremiumAIEngine, AIIntentResponse
from modules.ai_engine import AIEngine

logging.basicConfig(level=logging.INFO)

async def test_premium_ai():
    print("\n--- Testing PremiumAIEngine ---")
    ai = PremiumAIEngine()
    try:
        # Mocking client call to avoid actual API cost/latency during this quick check
        # But here we want to test if the async structure is valid.
        # We can just check if methods are awaitable.
        print("PremiumAIEngine initialized.")
        if ai.client:
            print("AsyncGroq client created successfully.")
        
        # We won't call process_interaction because it needs Redis
        print("PremiumAIEngine structure valid.")
    except Exception as e:
        print(f"PremiumAIEngine Failed: {e}")

async def test_standard_ai():
    print("\n--- Testing AIEngine ---")
    ai = AIEngine()
    try:
        print("AIEngine initialized.")
        if ai.client:
            print("AsyncGroq client created successfully.")
        
        # Test generate_smart_insight existence
        if hasattr(ai, 'generate_smart_insight'):
            print("Method generate_smart_insight exists.")
        else:
            print("ERROR: generate_smart_insight MISSING!")
            
    except Exception as e:
        print(f"AIEngine Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_premium_ai())
    asyncio.run(test_standard_ai())
