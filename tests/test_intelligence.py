
import pytest
import asyncio
from unittest.mock import MagicMock, patch
from modules.intelligence import MicroIntelligenceLayer, ConversationMemoryBrain, MemoryEncryptor, CognitiveState

@pytest.fixture
def encryptor():
    return MemoryEncryptor()

@pytest.fixture
def brain(encryptor):
    # Use a mock for redis to avoid needing a real redis instance
    with patch('modules.intelligence.RedisManager') as mock_redis:
        mock_client = MagicMock()
        mock_redis.return_value.client = mock_client
        brain = ConversationMemoryBrain(user_id=123, encryptor=encryptor)
        brain.redis = mock_client
        return brain

@pytest.fixture
def intel_layer():
    with patch('modules.intelligence.RedisManager') as mock_redis:
        mock_client = MagicMock()
        mock_redis.return_value.client = mock_client
        layer = MicroIntelligenceLayer(user_id=123)
        layer.brain.redis = mock_client
        return layer

def test_encryption(encryptor):
    original = "Secret financial data"
    encrypted = encryptor.encrypt(original)
    assert encrypted != original
    decrypted = encryptor.decrypt(encrypted)
    assert decrypted == original

@pytest.mark.asyncio
async def test_brain_storage_and_retrieval(brain):
    content = "Hello world"
    # Mock redis behavior
    brain.redis.hget.return_value = None
    
    node_id = await brain.store_memory(content, role="user")
    assert len(node_id) == 12
    
    # Mock retrieval
    encrypted_content = brain.encryptor.encrypt(content)
    brain.redis.hget.return_value = '{"node_id": "' + node_id + '", "role": "user", "content": "' + encrypted_content + '", "timestamp": 123.45, "metadata": {}}'
    
    chain = await brain.get_conversation_chain(node_id)
    assert len(chain) == 1
    assert chain[0].content == content

@pytest.mark.asyncio
async def test_cognitive_state_logic(intel_layer):
    # Test cognitive state computation with various signals
    sentiment = {"sentiment": "NEGATIVE", "emotion": "STRESS", "intensity": "HIGH"}
    topics = {"cashflow": 0.8, "investasi": 0.1}
    
    state = intel_layer.nlp._compute_cognitive_state(
        text="Saya pusing bayar hutang",
        sentiment_data=sentiment,
        topic_scores=topics,
        complexity=0.8,
        intent="SHARING_INFO",
        amount=0.0
    )
    
    assert state["financial_stress_probability"] > 0.5
    assert state["caution_signal"] > 0.3

@pytest.mark.asyncio
async def test_intelligence_layer_processing(intel_layer):
    with patch.object(intel_layer.nlp, 'deep_understanding_analysis') as mock_analysis:
        mock_analysis.return_value = {
            "intent": "ADD_TRANSACTION",
            "intent_confidence": 0.95,
            "cognitive_state": {
                "financial_stress_probability": 0.1,
                "impulsivity_signal": 0.2,
                "risk_seeking_signal": 0.0,
                "caution_signal": 0.0
            },
            "low_separation": False
        }
        
        response = await intel_layer.process_interaction("Beli kopi 20rb")
        assert response.intent == "ADD_TRANSACTION"
        assert response.confidence == 0.95
        assert response.suggested_action == "PROCEED"

@pytest.mark.asyncio
async def test_branching_and_merging(brain):
    # Mock redis behavior
    brain.redis.hset.return_value = 1
    brain.redis.sadd.return_value = 1
    
    branch_id = await brain.create_branch("parent_123", "New Topic")
    assert len(branch_id) == 8
    brain.redis.hset.assert_called()
    
    await brain.merge_branches("source_123", "target_456")
    brain.redis.sadd.assert_called_with("brain:branches:123:target_456", "source_123")

def test_analytics(intel_layer):
    analytics = asyncio.run(intel_layer.get_analytics())
    assert "session_depth" in analytics
    assert "average_confidence" in analytics
