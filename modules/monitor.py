from fastapi import FastAPI, Response, status, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import uvicorn
import threading
import os
import logging
import json
from typing import Optional, Dict, Any

app = FastAPI(title="FinBot Pro Monitoring")

# --- Dependency placeholders to avoid circular import ---
_db = None
_premium_ai = None
_ws_server = None
_auth_secret = os.getenv("WEB_JWT_SECRET", "")

def init_dependencies(db, premium_ai, ws_server, auth_secret: Optional[str] = None):
    global _db, _premium_ai, _ws_server, _auth_secret
    _db = db
    _premium_ai = premium_ai
    _ws_server = ws_server
    if auth_secret:
        _auth_secret = auth_secret

# --- Simple HMAC-based token (JWT-like) ---
import hmac, hashlib, time, base64

def sign_token(user_id: int, ttl_seconds: int = 3600) -> str:
    exp = int(time.time()) + ttl_seconds
    payload = f"{user_id}.{exp}"
    sig = hmac.new(_auth_secret.encode(), payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{base64.urlsafe_b64encode(sig).decode()}"

def verify_token(token: str) -> int:
    try:
        user_part, exp_part, sig_b64 = token.split(".")
        exp = int(exp_part)
        if exp < int(time.time()):
            raise HTTPException(status_code=401, detail="Token expired")
        expected_sig = hmac.new(_auth_secret.encode(), f"{user_part}.{exp}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected_sig, base64.urlsafe_b64decode(sig_b64.encode())):
            raise HTTPException(status_code=401, detail="Invalid signature")
        return int(user_part)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token format")

def get_current_user(authorization: Optional[str] = None) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.split(" ", 1)[1]
    return verify_token(token)

# --- Schemas ---
class TransactionCreate(BaseModel):
    amount: float = Field(..., gt=0)
    category: str = Field(..., min_length=1)
    description: Optional[str] = None
    type: str = Field(..., pattern="^(expense|income)$")
    date: Optional[str] = None

class BudgetSet(BaseModel):
    category: str
    limit_amount: float = Field(..., gt=0)

class BudgetAlert(BaseModel):
    category: str
    warn_threshold: float = Field(..., gt=0, lt=1)
    limit_threshold: float = Field(..., gt=0, lte=1)

@app.get("/health")
async def health_check():
    """Koyeb health check endpoint with deep diagnostics"""
    # Check Supabase
    db_ok = (_db is not None) and (_db.supabase is not None)
    
    # Check Redis
    redis_ok = (_premium_ai is not None) and (_premium_ai.redis.client is not None)
    
    # Check WS
    ws_ok = (_ws_server is not None) and (_ws_server.loop is not None) and _ws_server.loop.is_running()
    
    # Check AI Configuration
    ai_ok = (_premium_ai is not None) and (_premium_ai.client is not None)

    status_data = {
        "status": "healthy" if (db_ok and redis_ok) else "degraded",
        "components": {
            "database": "connected" if db_ok else "disconnected",
            "redis": "connected" if redis_ok else "disconnected",
            "websocket": "running" if ws_ok else "stopped",
            "ai_engine": "ready" if ai_ok else "not_configured"
        }
    }

    if db_ok and redis_ok:
        return status_data
    
    return Response(
        content=json.dumps(status_data), 
        media_type="application/json",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE
    )

@app.get("/stats")
def get_stats():
    """Quick diagnostic for premium engine"""
    if _premium_ai is None:
        raise HTTPException(status_code=503, detail="Premium AI not initialized")
    return _premium_ai.generate_comprehensive_test_report()

# --- Auth endpoints ---
@app.post("/auth/issue")
def issue_token(telegram_id: int):
    """
    Issue a short-lived token for web app, to be called via bot integration.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="DB not initialized")
    user = _db.get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not _auth_secret:
        raise HTTPException(status_code=500, detail="Auth secret missing")
    return {"token": sign_token(user.telegram_id)}

@app.get("/auth/verify")
def verify(authorization: Optional[str] = None):
    user_id = get_current_user(authorization)
    return {"user_id": user_id, "status": "ok"}

# --- Financial endpoints ---
@app.get("/transactions")
def list_transactions(authorization: Optional[str] = None, limit: int = 50):
    user_id = get_current_user(authorization)
    user = _db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    txs = _db.get_transactions_history(user.id, limit=limit)
    return [{"id": t.id, "amount": t.amount, "category": t.category, "type": t.type, "date": t.date, "description": getattr(t, "description", None)} for t in txs]

@app.post("/transactions")
def create_transaction(payload: TransactionCreate, authorization: Optional[str] = None):
    user_id = get_current_user(authorization)
    user = _db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    tx = _db.add_transaction(user.id, payload.amount, payload.category, payload.description or "", payload.type, payload.date)
    return {"id": tx.id, "status": "created"}

@app.post("/budgets")
def set_budget(payload: BudgetSet, authorization: Optional[str] = None):
    user_id = get_current_user(authorization)
    user = _db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    b = _db.set_budget(user.id, payload.category, payload.limit_amount)
    return {"category": b.category, "limit_amount": b.limit_amount}

@app.post("/budgets/alerts")
def set_budget_alerts(payload: BudgetAlert, authorization: Optional[str] = None):
    user_id = get_current_user(authorization)
    user = _db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    _db.set_budget_threshold(user.id, payload.category, payload.warn_threshold, payload.limit_threshold)
    return {"status": "updated"}

@app.get("/reports/monthly")
def monthly_report(month: int, year: int, authorization: Optional[str] = None):
    user_id = get_current_user(authorization)
    user = _db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    txs = _db.get_monthly_report(user.id, month, year)
    total_income = sum(t.amount for t in txs if t.type == "income")
    total_expense = sum(t.amount for t in txs if t.type == "expense")
    return {"month": month, "year": year, "total_income": total_income, "total_expense": total_expense}

@app.get("/reports/yearly")
def yearly_report(year: int, authorization: Optional[str] = None):
    user_id = get_current_user(authorization)
    user = _db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    txs = _db.get_yearly_report(user.id, year)
    total_income = sum(t.amount for t in txs if t.type == "income")
    total_expense = sum(t.amount for t in txs if t.type == "expense")
    return {"year": year, "total_income": total_income, "total_expense": total_expense}

@app.get("/export")
def export_csv(authorization: Optional[str] = None):
    user_id = get_current_user(authorization)
    user = _db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    filename = f"export_transaksi_{user_id}_{int(time.time())}.csv"
    filepath = os.path.join(os.getcwd(), filename)
    result = _db.export_transactions_to_csv(user.id, filepath)
    if not result:
        raise HTTPException(status_code=404, detail="No transactions to export")
    return FileResponse(filepath, filename=filename, media_type="text/csv")

def start_monitor():
    port = int(os.getenv("PORT", 8000))
    logging.info(f"Starting Monitor API on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

def start_monitor_thread(db=None, premium_ai=None, ws_server=None, auth_secret: Optional[str] = None):
    init_dependencies(db, premium_ai, ws_server, auth_secret)
    thread = threading.Thread(target=start_monitor, daemon=True)
    thread.start()
    return thread
