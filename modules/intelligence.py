
import json
import logging
import time
import hashlib
from typing import List, Dict, Any, Optional, Tuple
from cryptography.fernet import Fernet
from pydantic import BaseModel, Field
from modules.redis_mgr import RedisManager
from modules.nlp import NLPProcessor
from config import REDIS_URL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Models & Schemas
# ---------------------------------------------------------------------------

class CognitiveState(BaseModel):
    financial_stress_probability: float = 0.0
    impulsivity_signal: float = 0.0
    risk_seeking_signal: float = 0.0
    caution_signal: float = 0.0

class ConversationNode(BaseModel):
    node_id: str
    parent_id: Optional[str] = None
    role: str
    content: str
    timestamp: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class IntelligenceResponse(BaseModel):
    intent: str
    confidence: float
    cognitive_state: CognitiveState
    memory_context: str
    suggested_action: str

# ---------------------------------------------------------------------------
# Encryption Helper
# ---------------------------------------------------------------------------

class MemoryEncryptor:
    def __init__(self, key: Optional[bytes] = None):
        if not key:
            # In production, this should be loaded from a secure vault/env
            key = Fernet.generate_key()
        self.fernet = Fernet(key)

    def encrypt(self, data: str) -> str:
        return self.fernet.encrypt(data.encode()).decode()

    def decrypt(self, encrypted_data: str) -> str:
        return self.fernet.decrypt(encrypted_data.encode()).decode()

# ---------------------------------------------------------------------------
# Conversation Memory Brain
# ---------------------------------------------------------------------------

class ConversationMemoryBrain:
    """
    Advanced memory system supporting multi-turn, branching, and persistence.
    """
    def __init__(self, user_id: int, encryptor: MemoryEncryptor):
        self.user_id = user_id
        self.encryptor = encryptor
        self.redis = RedisManager().client
        self.brain_key = f"brain:memory:{user_id}"
        self.branch_key = f"brain:branches:{user_id}"

    async def store_memory(self, content: str, role: str, metadata: Dict[str, Any] = None, parent_id: str = None) -> str:
        node_id = hashlib.sha256(f"{time.time()}:{content}".encode()).hexdigest()[:12]
        node = ConversationNode(
            node_id=node_id,
            parent_id=parent_id,
            role=role,
            content=content,
            metadata=metadata or {}
        )
        
        # Encrypt content before storage
        encrypted_node = node.model_dump()
        encrypted_node["content"] = self.encryptor.encrypt(node.content)
        
        if self.redis:
            self.redis.hset(self.brain_key, node_id, json.dumps(encrypted_node))
            # Track branch
            if parent_id:
                self.redis.sadd(f"{self.branch_key}:{parent_id}", node_id)
            else:
                self.redis.sadd(f"{self.branch_key}:root", node_id)
        
        return node_id

    async def get_conversation_chain(self, leaf_node_id: str) -> List[ConversationNode]:
        chain = []
        current_id = leaf_node_id
        
        while current_id and self.redis:
            raw = self.redis.hget(self.brain_key, current_id)
            if not raw:
                break
            
            data = json.loads(raw)
            # Decrypt content
            data["content"] = self.encryptor.decrypt(data["content"])
            node = ConversationNode(**data)
            chain.insert(0, node)
            current_id = node.parent_id
            
        return chain

    async def get_semantic_summary(self, limit: int = 10) -> str:
        # Placeholder for dense embedding summary logic
        # In a real neural system, this would use a vector DB or an embedding model
        return "Stable conversation regarding financial goals and transaction history."

    async def create_branch(self, parent_id: str, label: str) -> str:
        """Explicitly branch the conversation for a new sub-topic."""
        branch_id = hashlib.sha256(f"{time.time()}:{label}".encode()).hexdigest()[:8]
        if self.redis:
            self.redis.hset(f"brain:labels:{self.user_id}", branch_id, label)
            self.redis.sadd(f"{self.branch_key}:{parent_id}", branch_id)
        return branch_id

    async def merge_branches(self, source_id: str, target_id: str) -> None:
        """Merge context from one branch into another."""
        if self.redis:
            # Transfer labels or metadata if needed
            self.redis.sadd(f"{self.branch_key}:{target_id}", source_id)
            logger.info(f"Merged branch {source_id} into {target_id} for user {self.user_id}")

# ---------------------------------------------------------------------------
# Micro Intelligence Layer
# ---------------------------------------------------------------------------

class MicroIntelligenceLayer:
    """
    Orchestrator for intent recognition, behavioral modelling, and flow tracking.
    """
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.encryptor = MemoryEncryptor() # In real life, retrieve key for user
        self.brain = ConversationMemoryBrain(user_id, self.encryptor)
        self.nlp = NLPProcessor()
        self.current_node_id: Optional[str] = None

    async def process_interaction(self, text: str) -> IntelligenceResponse:
        # 1. Real-time Processing & Neural-based Intent Recognition
        # (Leveraging NLPProcessor's ensemble which includes transformers)
        analysis = self.nlp.deep_understanding_analysis(text)
        
        intent = analysis.get("intent", "UNKNOWN")
        confidence = analysis.get("intent_confidence", 0.0)
        cognitive_state_dict = analysis.get("cognitive_state", {})
        cognitive_state = CognitiveState(**cognitive_state_dict)
        
        # 2. Contextual Memory Storage
        metadata = {
            "intent": intent,
            "confidence": confidence,
            "cognitive_state": cognitive_state.model_dump()
        }
        
        node_id = await self.brain.store_memory(
            content=text,
            role="user",
            metadata=metadata,
            parent_id=self.current_node_id
        )
        self.current_node_id = node_id
        
        # 3. Flow Tracking & Disambiguation (Confidence Gap Detection)
        suggested_action = "PROCEED"
        if analysis.get("low_separation"):
            suggested_action = "DISAMBIGUATE"
            
        # 4. Memory Context Retrieval
        memory_summary = await self.brain.get_semantic_summary()
        
        return IntelligenceResponse(
            intent=intent,
            confidence=confidence,
            cognitive_state=cognitive_state,
            memory_context=memory_summary,
            suggested_action=suggested_action
        )

    async def get_analytics(self) -> Dict[str, Any]:
        """Real-time analytics on conversation patterns."""
        # Mock analytics based on brain size and cognitive states
        return {
            "session_depth": 5,
            "average_confidence": 0.88,
            "dominant_stress_level": "low",
            "branch_count": 2
        }
