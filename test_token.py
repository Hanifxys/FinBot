import asyncio
from telegram import Bot
from config import TELEGRAM_BOT_TOKEN

async def test_bot():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        me = await bot.get_me()
        print(f"Bot info: {me.username} ({me.id})")
        print("Token is valid.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_bot())
