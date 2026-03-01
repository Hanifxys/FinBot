from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from handlers.contracts import HandlerDeps


@dataclass
class HandlerResult:
    handled: bool
    intent: str = "unknown"
    latency_ms: float = 0.0
    note: Optional[str] = None


class TextHandler:
    """
    Text entrypoint contract. Current implementation delegates to legacy
    messages.py logic to preserve backward compatibility during migration.
    """

    def __init__(self, deps: HandlerDeps):
        self.deps = deps

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> HandlerResult:
        from handlers.messages import handle_message

        await handle_message(update, context)
        return HandlerResult(handled=True, intent="delegated_legacy")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from core import db, nlp, premium_ai, budget_mgr, analyzer, ux_analytics

    handler = TextHandler(
        HandlerDeps(
            db=db,
            nlp=nlp,
            premium_ai=premium_ai,
            budget_mgr=budget_mgr,
            analyzer=analyzer,
            ux_analytics=ux_analytics,
        )
    )
    await handler.handle_text(update, context)
