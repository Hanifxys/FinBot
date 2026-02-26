# FinBot Premium: Full AI Agent Architecture

## 1. Executive Summary
FinBot Premium is an enterprise-grade financial assistant powered by a multi-model AI engine. It moves beyond simple command-based bots to a fully contextual, persona-driven agent that proactively manages user finances.

## 2. Core Architecture Components

### A. The Brain: Premium AI Engine (`modules/premium_ai.py`)
The central nervous system of FinBot.
- **Multi-Model Orchestration**: Dynamically switches between models based on task complexity and availability.
  - *Primary*: Llama-3 70B (Complex reasoning, financial advice)
  - *Fast*: Llama-3 8B (Quick intent classification, chat)
  - *Fallback*: Mixtral 8x7b (Redundancy)
- **Smart Fallback**: Zero-downtime architecture. If the primary model fails/timeouts, the request is instantly rerouted to the fallback model.

### B. Memory System (`modules/ai_memory.py`)
Maintains context across sessions, making the bot feel "alive".
- **Short-term Memory**: Redis-backed buffer of recent interactions (last 20 turns).
- **Long-term Memory**: Vector-like summarization. Older conversations are compressed into summaries and injected into the system prompt, allowing the bot to remember long-term goals (e.g., "saving for a laptop") without exceeding token limits.

### C. Persona Engine (`modules/ai_persona.py`)
Configurable personality system.
- **Dynamic Traits**: Tone, language style (Slang/Formal), and domain expertise can be adjusted per user.
- **Context Adaptation**: The bot detects user sentiment (stressed/happy) and adjusts its response tone accordingly (empathetic vs. celebratory).

### D. Perception Layer
- **NLP Processor (`modules/nlp.py`)**: High-performance regex + LLM hybrid for intent classification.
- **OCR Engine (`modules/ocr.py` & `modules/document_processor.py`)**:
  - Extracts data from receipts (images).
  - Summarizes financial documents (PDF/DOCX) using AI.
- **Voice Module**: Transcribes voice notes into text using Whisper v3.

### E. Engagement & Gamification (`modules/gamification.py`)
Keeps users addicted to healthy financial habits.
- **XP & Leveling**: Users gain XP for logging transactions and checking budgets.
- **Leaderboards**: Redis-backed real-time ranking.
- **Badges**: Dynamic awards (e.g., "Hemat Starter", "Budget Master").

### F. Proactive Agent (`handlers/digest.py`)
- **24-Hour Intelligent Reminder**:
  - Scheduler checks user inactivity.
  - AI generates a *unique, contextual* reminder message (not a template) based on the user's persona.
  - Respects "Do Not Disturb" (opt-out available).

## 3. Data Flow Diagram

1. **Input**: User sends Text / Voice / Image / File.
2. **Perception**:
   - Voice -> Transcribed to Text.
   - Image -> OCR -> Text.
   - File -> Extracted -> Summary.
3. **Processing**:
   - `NLPProcessor` performs quick intent check (Regex).
   - If complex, `PremiumAIEngine` takes over.
   - **Memory Retrieval**: Fetches User Persona + Recent Context + Long-term Summary.
   - **LLM Reasoning**: Model generates Intent (JSON) + Response (Natural Language).
4. **Action**:
   - **Transaction**: DB Insert + Reconciliation Check (Duplicate protection).
   - **Insight**: Real-time analysis of spending patterns.
   - **Gamification**: Award XP + WebSocket Broadcast.
5. **Response**: User receives the result + AI's natural language reply.

## 4. Security & Reliability
- **Reconciliation**: AI checks for potential duplicate transactions before saving (`check_reconciliation`).
- **Secure Token Handling**: HMAC-signed tokens for web authentication.
- **Rate Limiting**: Redis-backed rate limiters for OCR and AI calls.
- **Async/Non-blocking**: Fully asynchronous Python architecture (FastAPI/Telegram-ext) for high concurrency.

## 5. Future Roadmap
- **Autonomous Budgeting**: AI suggests budget adjustments based on spending trends.
- **Investment Advisor**: Integration with market data for real-time portfolio insights.
- **Multi-Platform**: Extend agent to WhatsApp and Web Dashboard (API ready).
