import types

import pytest

from handlers.contracts import HandlerDeps
from handlers.text_handler import TextHandler
from handlers.media_handler import MediaHandler


class DummyUpdate:
    pass


class DummyContext:
    pass


@pytest.mark.asyncio
async def test_text_handler_contract_delegates(monkeypatch):
    called = {"ok": False}

    async def _fake_handle_message(update, context):
        called["ok"] = True

    monkeypatch.setattr("handlers.messages.handle_message", _fake_handle_message)

    h = TextHandler(HandlerDeps(None, None, None, None, None, None))
    result = await h.handle_text(DummyUpdate(), DummyContext())

    assert called["ok"] is True
    assert result.handled is True


@pytest.mark.asyncio
async def test_media_handler_contract_delegates(monkeypatch):
    called = {"photo": False, "voice": False, "doc": False}

    async def _fake_photo(update, context):
        called["photo"] = True

    async def _fake_voice(update, context):
        called["voice"] = True

    async def _fake_doc(update, context):
        called["doc"] = True

    monkeypatch.setattr("handlers.messages.handle_photo", _fake_photo)
    monkeypatch.setattr("handlers.messages.handle_voice", _fake_voice)
    monkeypatch.setattr("handlers.messages.handle_document", _fake_doc)

    h = MediaHandler(HandlerDeps(None, None, None, None, None, None))
    await h.handle_photo(DummyUpdate(), DummyContext())
    await h.handle_voice(DummyUpdate(), DummyContext())
    await h.handle_document(DummyUpdate(), DummyContext())

    assert called["photo"] and called["voice"] and called["doc"]
