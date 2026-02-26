import json
import logging
from typing import List, Optional
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from modules.redis_mgr import RedisManager

logger = logging.getLogger(__name__)

class AIMemory:
    """
    Advanced Memory System for FinBot Premium.
    Features:
    - Long-term context via Redis (100+ turns)
    - Automatic Summarization (to fit LLM context)
    - Vector-like retrieval (simulated via key-based topic clustering if needed)
    """
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.redis = RedisManager().client
        self.history_key = f"chat_history:{user_id}"
        self.summary_key = f"chat_summary:{user_id}"
        self.max_tokens = 4000  # Soft limit for context window
        
    def add_user_message(self, text: str):
        """Add user message to history"""
        msg = {"role": "user", "content": text}
        self.redis.rpush(self.history_key, json.dumps(msg))
        
    def add_ai_message(self, text: str):
        """Add AI response to history"""
        msg = {"role": "assistant", "content": text}
        self.redis.rpush(self.history_key, json.dumps(msg))
        
    def get_context(self, limit: int = 20) -> List[dict]:
        """
        Retrieve recent context + summary.
        Returns a list of message dicts suitable for LLM API.
        """
        # 1. Get Summary (Long-term context)
        summary = self.redis.get(self.summary_key)
        messages = []
        
        if summary:
            summary_text = summary.decode('utf-8')
            messages.append({"role": "system", "content": f"Previous Conversation Summary: {summary_text}"})
            
        # 2. Get Recent History
        # We fetch more history to support extended context
        raw_history = self.redis.lrange(self.history_key, -limit, -1)
        for item in raw_history:
            try:
                messages.append(json.loads(item))
            except json.JSONDecodeError:
                continue
                
        return messages

    def clear(self):
        """Clear memory for user"""
        self.redis.delete(self.history_key)
        self.redis.delete(self.summary_key)

    async def summarize_if_needed(self, llm_client, model_name: str):
        """
        Periodically summarize history to maintain context without token overflow.
        This should be called as a background task.
        """
        # Check length
        length = self.redis.llen(self.history_key)
        if length < 20:
            return

        # Fetch old messages to summarize (keep last 10 raw)
        to_summarize = self.redis.lrange(self.history_key, 0, -11)
        if not to_summarize:
            return

        text_block = "\n".join([f"{json.loads(m)['role']}: {json.loads(m)['content']}" for m in to_summarize])
        
        # Get existing summary
        current_summary = self.redis.get(self.summary_key)
        if current_summary:
            current_summary = current_summary.decode('utf-8')
            prompt = f"Update this summary with new conversation:\n\nOld Summary: {current_summary}\n\nNew Interaction:\n{text_block}\n\nConcise updated summary:"
        else:
            prompt = f"Summarize this conversation context concisely:\n\n{text_block}"

        try:
            # Direct call to LLM for summarization
            response = await llm_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=model_name,
                temperature=0.3
            )
            new_summary = response.choices[0].message.content
            
            # Save new summary
            self.redis.set(self.summary_key, new_summary)
            
            # Trim summarized messages from Redis list
            # ltrim to keep only the last 10
            self.redis.ltrim(self.history_key, -10, -1)
            
            logger.info(f"Memory summarized for user {self.user_id}")
            
        except Exception as e:
            logger.error(f"Summarization failed: {e}")
