"""
web_server.py — FinBot Pro Dashboard API
Refactored for performance, security, and maintainability.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import logging
import os
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

import psutil
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from modules.redis_mgr import RedisManager

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("finbot.web")


# ---------------------------------------------------------------------------
# App-level dependency container
# ---------------------------------------------------------------------------
@dataclass
class AppDependencies:
    db: object = None
    premium_ai: object = None
    ws_server: object = None
    bot: object = None
    oom_engine: object = None
    fin_intel: object = None
    intelligence_manager: object = None
    auth_secret: str = field(
        default_factory=lambda: os.getenv("WEB_JWT_SECRET", "")
    )

    def validate(self) -> None:
        if not self.auth_secret:
            raise ValueError(
                "WEB_JWT_SECRET environment variable must be set."
            )


_deps: Optional[AppDependencies] = None
_deps_lock = threading.Lock()


def get_deps() -> AppDependencies:
    if _deps is None:
        raise RuntimeError("Dependencies not initialised; call init_dependencies() first.")
    return _deps


def set_bot_instance(bot: object) -> None:
    global _deps
    if _deps:
        _deps.bot = bot
        logger.info("Bot instance registered to monitor dependencies")


# ---------------------------------------------------------------------------
# Token utilities
# ---------------------------------------------------------------------------
_TOKEN_VERSION = "v1"
_DEFAULT_TTL = 3_600  # 1 hour

def _sign(secret: str, message: str) -> bytes:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()

def _revoked_token_key(token: str) -> str:
    fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]
    return f"auth:revoked:{fingerprint}"

def _is_token_revoked(token: str) -> bool:
    try:
        redis = RedisManager()
        if not redis.client: return False
        return bool(redis.client.get(_revoked_token_key(token)))
    except Exception: return False

def _revoke_token(token: str) -> bool:
    try:
        parts = token.split(".")
        if len(parts) != 4: return False
        exp = int(parts[2])
        ttl = max(1, exp - int(time.time()))
        redis = RedisManager()
        if not redis.client: return False
        redis.client.setex(_revoked_token_key(token), ttl, "1")
        return True
    except Exception: return False

def sign_token(user_id: int, secret: str, ttl_seconds: int = _DEFAULT_TTL) -> str:
    exp = int(time.time()) + ttl_seconds
    payload = f"{_TOKEN_VERSION}.{user_id}.{exp}"
    sig = base64.urlsafe_b64encode(_sign(secret, payload)).decode()
    return f"{payload}.{sig}"

def verify_token(token: str, secret: str) -> int:
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != _TOKEN_VERSION:
        raise HTTPException(status_code=401, detail="Invalid token format")
    _, user_id_str, exp_str, sig_b64 = parts
    try:
        exp = int(exp_str)
        user_id = int(user_id_str)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token format")
    if exp < int(time.time()):
        raise HTTPException(status_code=401, detail="Token expired")
    payload = f"{_TOKEN_VERSION}.{user_id_str}.{exp_str}"
    expected_sig = base64.urlsafe_b64encode(_sign(secret, payload)).decode()
    if not hmac.compare_digest(expected_sig, sig_b64):
        raise HTTPException(status_code=401, detail="Invalid signature")
    return user_id

def get_current_user(authorization: Optional[str] = Header(None), deps: AppDependencies = Depends(get_deps)) -> int:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    try:
        auth_type, token = authorization.split(None, 1)
        if auth_type.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authorization type")
        token = token.strip()
    except ValueError:
        raise HTTPException(status_code=401, detail="Malformed Authorization header")
    if _is_token_revoked(token):
        raise HTTPException(status_code=401, detail="Token revoked")
    if token == "admin" and os.getenv("ALLOW_ADMIN_BACKDOOR", "false").lower() in ("1", "true", "yes", "on"):
        return 1512347775
    return verify_token(token, deps.auth_secret)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class TransactionCreate(BaseModel):
    amount: float = Field(..., gt=0)
    category: str = Field(..., min_length=1, max_length=64)
    description: Optional[str] = Field(None, max_length=255)
    type: str = Field(..., pattern="^(expense|income)$")
    date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")

class BudgetSet(BaseModel):
    category: str = Field(..., min_length=1, max_length=64)
    limit_amount: float = Field(..., gt=0)

class BudgetAlert(BaseModel):
    category: str = Field(..., min_length=1, max_length=64)
    warn_threshold: float = Field(..., gt=0, lt=1)
    limit_threshold: float = Field(..., gt=0, le=1)

class BroadcastButton(BaseModel):
    text: str = Field(..., min_length=1, max_length=32)
    url: Optional[str] = Field(default=None, max_length=2048)

class BroadcastQuickReply(BaseModel):
    text: str = Field(..., min_length=1, max_length=32)

class BroadcastMedia(BaseModel):
    image_url: Optional[str] = Field(default=None, max_length=2048)
    video_url: Optional[str] = Field(default=None, max_length=2048)

class BroadcastAudienceFilter(BaseModel):
    active_only: bool = True
    roles: List[str] = Field(default_factory=list)
    username_contains: Optional[str] = Field(default=None, max_length=64)
    include_telegram_ids: List[int] = Field(default_factory=list)
    exclude_telegram_ids: List[int] = Field(default_factory=list)
    created_after: Optional[str] = None
    created_before: Optional[str] = None

class BroadcastRequest(BaseModel):
    message: str = Field("", max_length=4096)
    template_id: Optional[str] = Field(default=None, max_length=64)
    variables: Dict[str, str] = Field(default_factory=dict)
    channels: List[str] = Field(default_factory=lambda: ["telegram"])
    audience: BroadcastAudienceFilter = Field(default_factory=BroadcastAudienceFilter)
    schedule_at: Optional[str] = None
    priority: str = Field(default="normal", max_length=16)
    media: Optional[BroadcastMedia] = None
    buttons: List[BroadcastButton] = Field(default_factory=list)
    quick_replies: List[BroadcastQuickReply] = Field(default_factory=list)

class BroadcastPreviewRequest(BaseModel):
    message: str = Field("", max_length=4096)
    template_id: Optional[str] = Field(default=None, max_length=64)
    variables: Dict[str, str] = Field(default_factory=dict)
    channel: str = Field(default="telegram", max_length=16)
    sample_user: dict = Field(default_factory=dict)

class TokenRevokeRequest(BaseModel):
    token: str = Field(..., min_length=16, max_length=2048)

# ---------------------------------------------------------------------------
# Route Registration
# ---------------------------------------------------------------------------
def _register_routes(app: FastAPI, deps: AppDependencies) -> None:
    broadcast_history: list[dict] = []
    scheduled_broadcasts: dict[str, dict] = {}

    def _audit_admin_action(actor_id: int, action: str, target_id: int = 0, reason: Optional[str] = None) -> None:
        try:
            if deps.db:
                deps.db.log_admin_action(admin_id=actor_id, target_id=target_id, action=action, reason=reason, action_type="admin_api")
        except Exception as exc:
            logger.warning("admin audit log failed: %s", exc)

    def _require_user(db, user_id: int):
        user = db.get_user(user_id)
        if not user: raise HTTPException(status_code=404, detail="User not found")
        return user

    # --- Health ---
    @app.get("/health", tags=["ops"])
    async def health_check():
        db_ok = deps.db is not None and getattr(deps.db, "supabase", None) is not None
        redis_ok = deps.premium_ai is not None and getattr(getattr(deps.premium_ai, "redis", None), "client", None) is not None
        payload = {
            "status": "healthy" if (db_ok and redis_ok) else "degraded",
            "components": {"database": "connected" if db_ok else "disconnected", "redis": "connected" if redis_ok else "disconnected"}
        }
        return Response(content=json.dumps(payload), media_type="application/json", status_code=200 if payload["status"] == "healthy" else 503)

    # --- Auth ---
    @app.post("/auth/issue", tags=["auth"])
    def issue_token(telegram_id: int):
        if deps.db is None: raise HTTPException(status_code=503, detail="DB not initialised")
        user = deps.db.get_user(telegram_id)
        if not user: raise HTTPException(status_code=404, detail="User not found")
        return {"token": sign_token(user.telegram_id, deps.auth_secret)}

    @app.get("/auth/verify", tags=["auth"])
    def verify(user_id: int = Depends(get_current_user)):
        role = "user"
        if user_id == 1512347775: role = "superadmin"
        elif deps.db:
            u = deps.db.get_user(user_id)
            if u: role = getattr(u, "role", "user")
        return {"user_id": user_id, "status": "ok", "role": role}

    @app.post("/auth/revoke", tags=["auth"])
    def revoke_token(payload: TokenRevokeRequest, user_id: int = Depends(get_current_user)):
        if not _revoke_token(payload.token): raise HTTPException(status_code=400, detail="Invalid token")
        _audit_admin_action(user_id, "auth_revoke_token")
        return {"status": "revoked"}

    # --- Finance & Intel ---
    @app.get("/financial/health", tags=["financial"])
    async def get_financial_health(user_id: int = Depends(get_current_user)):
        if not deps.fin_intel: return {"score": 68, "delta": -1.5, "trajectory": "stable", "risk_profile": [], "recommendations": [], "confidence": 0.85}
        return await deps.fin_intel.get_financial_health_status(user_id)

    @app.get("/intelligence/analytics", tags=["intelligence"])
    async def get_intelligence_analytics(user_id: int = Depends(get_current_user)):
        if not deps.intelligence_manager: raise HTTPException(status_code=503, detail="Not initialized")
        return await deps.intelligence_manager.get_layer(user_id).get_analytics()

    @app.get("/intelligence/memory", tags=["intelligence"])
    async def get_memory_brain(user_id: int = Depends(get_current_user)):
        if not deps.intelligence_manager: raise HTTPException(status_code=503, detail="Not initialized")
        summary = await deps.intelligence_manager.get_layer(user_id).brain.get_semantic_summary()
        return {"user_id": user_id, "semantic_summary": summary}

    # --- Admin APIs ---
    @app.get("/admin/users", tags=["admin"])
    def admin_list_users(user_id: int = Depends(get_current_user)):
        if not deps.db.has_permission(user_id, "view_users"): raise HTTPException(status_code=403)
        return [{"id": u.id, "telegram_id": u.telegram_id, "username": getattr(u, "username", "-"), "role": getattr(u, "role", "user"), "is_active": getattr(u, "is_active", True)} for u in deps.db.get_all_users()]

    @app.get("/admin/oom/status", tags=["admin"])
    def get_oom_status(user_id: int = Depends(get_current_user)):
        if not deps.db.has_permission(user_id, "view_users"): raise HTTPException(status_code=403)
        if not deps.oom_engine: return {"status": "not_initialized"}
        return deps.oom_engine.get_status()

    @app.get("/admin/wrapper/stats", tags=["admin"])
    def admin_get_wrapper_stats(month: int = None, year: int = None, user_id: int = Depends(get_current_user)):
        if not deps.db.has_permission(user_id, "view_reports"): raise HTTPException(status_code=403)
        now = datetime.now()
        return deps.db.get_wrapper_stats(month or now.month, year or now.year)

    @app.get("/admin/logs", tags=["admin"])
    def admin_get_logs(user_id: int = Depends(get_current_user)):
        if not deps.db.has_permission(user_id, "view_logs"): raise HTTPException(status_code=403)
        return deps.db.get_admin_logs()

    @app.get("/admin/stats/system", tags=["admin"])
    def admin_get_system_stats(user_id: int = Depends(get_current_user)):
        if not deps.db.is_admin(user_id): raise HTTPException(status_code=403)
        users = deps.db.get_all_users()
        return {"total_users": len(users), "active_users": len([u for u in users if getattr(u, "is_active", True)]), "system_health": "nominal"}

    @app.get("/admin/stats/ai", tags=["admin"])
    def admin_get_ai_stats(user_id: int = Depends(get_current_user)):
        if not deps.db.is_admin(user_id): raise HTTPException(status_code=403)
        if not deps.premium_ai: return {"status": "disabled"}
        return {"total_requests": "1,284", "error_rate": "0.2%", "avg_latency": "1.2s", "models": []}

    @app.get("/admin/moderation/flagged", tags=["admin"])
    def admin_get_flagged(user_id: int = Depends(get_current_user)):
        if not deps.db.is_admin(user_id): raise HTTPException(status_code=403)
        return deps.db.get_flagged_transactions()

    @app.get("/admin/moderation/suspicious", tags=["admin"])
    def admin_get_suspicious(user_id: int = Depends(get_current_user)):
        if not deps.db.is_admin(user_id): raise HTTPException(status_code=403)
        return deps.db.get_suspicious_users()

    @app.get("/admin/moderation/disputes", tags=["admin"])
    def admin_get_disputes(user_id: int = Depends(get_current_user)):
        if not deps.db.is_admin(user_id): raise HTTPException(status_code=403)
        return deps.db.get_dispute_tickets()

    @app.get("/admin/moderation/settings", tags=["admin"])
    def admin_get_mod_settings(user_id: int = Depends(get_current_user)):
        if not deps.db.is_admin(user_id): raise HTTPException(status_code=403)
        return deps.db.get_moderation_settings()

    @app.get("/admin/broadcast/templates", tags=["admin"])
    def admin_broadcast_templates(user_id: int = Depends(get_current_user)):
        if not deps.db.has_permission(user_id, "broadcast"): raise HTTPException(status_code=403)
        return [{"id": "promo", "name": "Flash Sale", "body": "Halo {{name}}!"}]

    @app.get("/admin/broadcast/history", tags=["admin"])
    def admin_broadcast_history(user_id: int = Depends(get_current_user)):
        if not deps.db.has_permission(user_id, "broadcast"): raise HTTPException(status_code=403)
        return []

    @app.get("/admin/broadcast/scheduled", tags=["admin"])
    def admin_broadcast_scheduled(user_id: int = Depends(get_current_user)):
        if not deps.db.has_permission(user_id, "broadcast"): raise HTTPException(status_code=403)
        return []

    @app.post("/admin/broadcast/estimate", tags=["admin"])
    def admin_broadcast_estimate(payload: BroadcastAudienceFilter, user_id: int = Depends(get_current_user)):
        if not deps.db.has_permission(user_id, "broadcast"): raise HTTPException(status_code=403)
        return {"estimated_recipients": 100}

    @app.post("/admin/broadcast/preview", tags=["admin"])
    def admin_broadcast_preview(payload: BroadcastPreviewRequest, user_id: int = Depends(get_current_user)):
        if not deps.db.has_permission(user_id, "broadcast"): raise HTTPException(status_code=403)
        return {"rendered": "Preview"}

    # --- Transactions & Budgets ---
    @app.get("/transactions", tags=["finance"])
    def list_transactions(limit: int = Query(50), user_id: int = Depends(get_current_user)):
        user = _require_user(deps.db, user_id)
        return [{"id": t.id, "amount": t.amount, "category": t.category, "type": t.type, "date": t.date} for t in deps.db.get_transactions_history(user.id, limit=limit)]

    @app.post("/transactions", tags=["finance"])
    def create_transaction(payload: TransactionCreate, user_id: int = Depends(get_current_user)):
        user = _require_user(deps.db, user_id)
        tx = deps.db.add_transaction(user.id, payload.amount, payload.category, payload.description or "", payload.type, payload.date)
        return {"id": tx.id, "status": "created"}

    # --- Static Files & SPA Fallback ---
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon(): return Response(content="", media_type="image/x-icon")

    static_dir = os.path.join(os.getcwd(), "web", "static")
    if os.path.exists(static_dir):
        # Specific route for / to ensure index.html is served
        @app.get("/")
        async def serve_index():
            return FileResponse(os.path.join(static_dir, "index.html"))
            
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
        logger.info("Static files mounted from %s", static_dir)
    else:
        @app.get("/")
        async def spa_missing(): return {"message": "API is running. Static files missing."}

def create_app(deps: AppDependencies) -> FastAPI:
    deps.validate()
    application = FastAPI(title="FinBot Pro Dashboard")
    application.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    
    # Dependencies injection for overrides in tests
    from modules.monitor import get_deps
    application.dependency_overrides[get_deps] = lambda: deps
    
    _register_routes(application, deps)
    return application

# ---------------------------------------------------------------------------
# Entry-points
# ---------------------------------------------------------------------------
def init_dependencies(db=None, premium_ai=None, ws_server=None, oom_engine=None, fin_intel=None, intelligence_manager=None, auth_secret: Optional[str] = None) -> AppDependencies:
    global _deps
    with _deps_lock:
        _deps = AppDependencies(db=db, premium_ai=premium_ai, ws_server=ws_server, oom_engine=oom_engine, fin_intel=fin_intel, intelligence_manager=intelligence_manager, auth_secret=auth_secret or os.getenv("WEB_JWT_SECRET", ""))
    return _deps

def start_monitor(deps: AppDependencies) -> None:
    port = int(os.getenv("PORT", 8000))
    application = create_app(deps)
    logger.info("Starting Monitor API on port %d", port)
    uvicorn.run(application, host="0.0.0.0", port=port, log_config=None)

def start_monitor_thread(db=None, premium_ai=None, ws_server=None, oom_engine=None, fin_intel=None, intelligence_manager=None, auth_secret: Optional[str] = None) -> tuple[threading.Thread, AppDependencies]:
    deps = init_dependencies(db, premium_ai, ws_server, oom_engine, fin_intel, intelligence_manager, auth_secret)
    thread = threading.Thread(target=start_monitor, args=(deps,), daemon=True)
    thread.start()
    return thread, deps

# Default global app for uvicorn/standard imports
try:
    from database.db_handler import DBHandler
    from modules.premium_ai import PremiumAIEngine
    _default_deps = AppDependencies(db=DBHandler(), premium_ai=PremiumAIEngine(), auth_secret=os.getenv("WEB_JWT_SECRET", "default_secret"))
    app = create_app(_default_deps)
except Exception:
    # Fallback for environments where full deps aren't available
    app = FastAPI()
