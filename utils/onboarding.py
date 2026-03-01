import time
from typing import Optional

from core import db

try:
    from modules.redis_mgr import RedisManager
except Exception:
    RedisManager = None  # type: ignore


def _get_redis_client():
    if not RedisManager:
        return None
    try:
        redis = RedisManager()
        return redis.client
    except Exception:
        return None


def _has_income(db_user_id: int) -> bool:
    inc = db.get_latest_income(db_user_id)
    return bool(inc and float(getattr(inc, "amount", 0) or 0) > 0)


def _has_budget(db_user_id: int) -> bool:
    budgets = db.get_user_budgets(db_user_id) or []
    for b in budgets:
        if float(getattr(b, "limit_amount", 0) or 0) > 0:
            return True
    return False


def _has_first_tx(db_user_id: int) -> bool:
    txs = db.get_transactions_history(db_user_id, limit=1)
    return bool(txs)


async def send_onboarding_hint(message_target, *, db_user_id: int, telegram_user_id: int) -> None:
    """
    Sends progressive onboarding guidance:
    1) set salary, 2) set budget, 3) add first transaction, then first-win message.
    """
    has_income = _has_income(db_user_id)
    has_budget = _has_budget(db_user_id)
    has_tx = _has_first_tx(db_user_id)

    if not has_income:
        await message_target.reply_text("Onboarding 1/3: set gaji dulu ya. Contoh: /setgaji 7000000")
        return
    if not has_budget:
        await message_target.reply_text("Onboarding 2/3: set budget utama. Contoh: /setbudget Makanan 1500000")
        return
    if not has_tx:
        await message_target.reply_text("Onboarding 3/3: catat transaksi pertama. Contoh: kopi 25000")
        return

    # First win message, once per user.
    client = _get_redis_client()
    key = f"user:{telegram_user_id}:onboarding_first_win"
    should_send = True
    if client:
        try:
            if client.get(key):
                should_send = False
            else:
                client.setex(key, 60 * 60 * 24 * 30, str(int(time.time())))
        except Exception:
            pass
    if should_send:
        await message_target.reply_text("First win unlocked: budget kamu sudah aktif dan transaksi pertama sudah tercatat.")

