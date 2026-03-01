import pytest
from fastapi.testclient import TestClient
from modules.monitor import create_app, AppDependencies
import os

@pytest.fixture
def client():
    # Use mock dependencies
    mock_deps = AppDependencies(
        db=None,
        premium_ai=None,
        ws_server=None,
        bot=None,
        oom_engine=None,
        auth_secret="test_secret"
    )
    # We don't want to validate because it might fail without real components
    # But create_app calls validate(), so let's mock it
    mock_deps.validate = lambda: None
    
    app = create_app(mock_deps)
    return TestClient(app)

def test_health_check(client):
    response = client.get("/health")
    # Should be 503 because DB and Redis are None (mocked)
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["components"]["database"] == "disconnected"

def test_auth_verify_fail(client):
    # Test unauthorized access
    response = client.get("/auth/verify")
    assert response.status_code == 401
