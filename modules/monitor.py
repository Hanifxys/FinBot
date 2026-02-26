from fastapi import FastAPI, Response, status
import uvicorn
import threading
import os
import logging
from core import db, premium_ai, ws_server

app = FastAPI(title="FinBot Pro Monitoring")

@app.get("/health")
def health_check():
    """Koyeb health check endpoint"""
    # Check Supabase
    db_ok = db.supabase is not None
    
    # Check Redis
    redis_ok = premium_ai.redis.client is not None
    
    # Check WS
    ws_ok = ws_server.loop is not None and ws_server.loop.is_running()
    
    if db_ok and redis_ok and ws_ok:
        return {
            "status": "healthy",
            "db": "connected",
            "redis": "connected",
            "websocket": "running"
        }
    
    return Response(
        content="unhealthy", 
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE
    )

@app.get("/stats")
def get_stats():
    """Quick diagnostic for premium engine"""
    return premium_ai.generate_comprehensive_test_report()

def start_monitor():
    port = int(os.getenv("PORT", 8000))
    logging.info(f"Starting Monitor API on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

def start_monitor_thread():
    thread = threading.Thread(target=start_monitor, daemon=True)
    thread.start()
    return thread
