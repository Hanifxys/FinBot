# Messages Modularization

## New Modules
- `handlers/text_handler.py`
- `handlers/media_handler.py`
- `handlers/contracts.py`

## Interface Contract
- `TextHandler.handle_text(update, context) -> HandlerResult`
- `MediaHandler.handle_photo/voice/document(update, context) -> HandlerResult`

## Backward Compatibility
- Implementasi baru saat ini mendelegasikan ke logic legacy `handlers/messages.py`.
- `bot.py` sekarang registrasi handler via modul baru.
- Ini memungkinkan migrasi internal bertahap tanpa mengubah behavior user-facing.

## Next Refactor Steps
1. Pindahkan helper text-only dari `messages.py` ke `text_handler.py`.
2. Pindahkan OCR/voice/doc flow ke `media_handler.py`.
3. Hilangkan dependency silang dan jadikan `messages.py` sebagai shim tipis.
