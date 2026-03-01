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


class MediaHandler:
    """
    Media entrypoint contract. Delegates to legacy messages.py to keep behaviour
    stable while media pipeline is modularised gradually.
    """

    def __init__(self, deps: HandlerDeps):
        self.deps = deps

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> HandlerResult:
        from handlers.messages import handle_photo

        await handle_photo(update, context)
        return HandlerResult(handled=True, intent="delegated_legacy_photo")

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> HandlerResult:
        from handlers.messages import handle_voice

        await handle_voice(update, context)
        return HandlerResult(handled=True, intent="delegated_legacy_voice")

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> HandlerResult:
        from handlers.messages import handle_document

        await handle_document(update, context)
        return HandlerResult(handled=True, intent="delegated_legacy_document")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from core import db, nlp, premium_ai, budget_mgr, analyzer, ux_analytics

    handler = MediaHandler(HandlerDeps(db, nlp, premium_ai, budget_mgr, analyzer, ux_analytics))
    await handler.handle_photo(update, context)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from core import db, nlp, premium_ai, budget_mgr, analyzer, ux_analytics

    handler = MediaHandler(HandlerDeps(db, nlp, premium_ai, budget_mgr, analyzer, ux_analytics))
    await handler.handle_voice(update, context)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from core import db, nlp, premium_ai, budget_mgr, analyzer, ux_analytics

    handler = MediaHandler(HandlerDeps(db, nlp, premium_ai, budget_mgr, analyzer, ux_analytics))
    await handler.handle_document(update, context)
