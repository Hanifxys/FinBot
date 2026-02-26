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
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("finbot.web")


# ---------------------------------------------------------------------------
# App-level dependency container (replaces bare globals)
# ---------------------------------------------------------------------------
@dataclass
class AppDependencies:
    db: object = None
    premium_ai: object = None
    ws_server: object = None
    bot: object = None
    auth_secret: str = field(
        default_factory=lambda: os.getenv("WEB_JWT_SECRET", "")
    )

    def validate(self) -> None:
        if not self.auth_secret:
            raise ValueError(
                "WEB_JWT_SECRET environment variable must be set — "
                "refusing to start with an empty secret."
            )


_deps: Optional[AppDependencies] = None
_deps_lock = threading.Lock()


def get_deps() -> AppDependencies:
    if _deps is None:
        raise RuntimeError("Dependencies not initialised; call init_dependencies() first.")
    return _deps


def set_bot_instance(bot: object) -> None:
    """Update the global dependencies with the bot instance once it's available."""
    global _deps
    if _deps:
        _deps.bot = bot
        logger.info("Bot instance registered to monitor dependencies")
    else:
        logger.warning("Attempted to set bot instance before dependencies were initialised")


# ---------------------------------------------------------------------------
# Token utilities
# ---------------------------------------------------------------------------
_TOKEN_VERSION = "v1"
_DEFAULT_TTL = 3_600  # 1 hour


def _sign(secret: str, message: str) -> bytes:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()


def sign_token(
    user_id: int,
    secret: str,
    ttl_seconds: int = _DEFAULT_TTL,
) -> str:
    """Return a signed, time-limited token: `v1.<user_id>.<exp>.<sig>`."""
    exp = int(time.time()) + ttl_seconds
    payload = f"{_TOKEN_VERSION}.{user_id}.{exp}"
    sig = base64.urlsafe_b64encode(_sign(secret, payload)).decode()
    return f"{payload}.{sig}"


def verify_token(token: str, secret: str) -> int:
    """
    Verify token and return user_id.
    Raises HTTPException(401) on any failure so callers never see raw exceptions.
    """
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != _TOKEN_VERSION:
        logger.warning("Token rejected: unexpected format (parts=%d)", len(parts))
        raise HTTPException(status_code=401, detail="Invalid token format")

    _, user_id_str, exp_str, sig_b64 = parts

    try:
        exp = int(exp_str)
        user_id = int(user_id_str)
    except ValueError:
        logger.warning("Token rejected: non-integer user_id or exp")
        raise HTTPException(status_code=401, detail="Invalid token format")

    if exp < int(time.time()):
        raise HTTPException(status_code=401, detail="Token expired")

    payload = f"{_TOKEN_VERSION}.{user_id_str}.{exp_str}"
    expected_sig = base64.urlsafe_b64encode(_sign(secret, payload)).decode()

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(expected_sig, sig_b64):
        logger.warning("Token rejected: signature mismatch for user_id=%s", user_id_str)
        raise HTTPException(status_code=401, detail="Invalid signature")

    return user_id


# ---------------------------------------------------------------------------
# Auth dependency (FastAPI-native, injectable)
# ---------------------------------------------------------------------------
def get_current_user(
    authorization: Optional[str] = Header(None),
    deps: AppDependencies = Depends(get_deps),
) -> int:
    """
    FastAPI dependency that resolves the authenticated user_id from a Bearer token.
    Supports a static 'admin' backdoor for development/emergency access.
    """
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning(f"Auth failed: Missing or malformed Bearer token. Header: {authorization[:20] if authorization else 'None'}")
        raise HTTPException(status_code=401, detail="Missing or malformed Bearer token")

    token = authorization.split(" ", 1)[1].strip()

    # Backdoor: 'admin' static token
    if token == "admin":
        logger.info("Auth: Admin backdoor accessed")
        return 1512347775  # Muhamad Hanif (Superadmin)

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
    limit_threshold: float = Field(..., gt=0, le=1)  # Fixed: lte→le


# ---------------------------------------------------------------------------
# App factory (enables testing with custom deps)
# ---------------------------------------------------------------------------
def create_app(deps: AppDependencies) -> FastAPI:
    deps.validate()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("FinBot web server starting up")
        yield
        logger.info("FinBot web server shutting down")

    application = FastAPI(title="FinBot Pro Dashboard", lifespan=lifespan)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Inject our specific deps instance so tests can override it
    application.dependency_overrides[get_deps] = lambda: deps

    _register_routes(application, deps)
    return application


def _register_routes(app: FastAPI, deps: AppDependencies) -> None:
    # -----------------------------------------------------------------------
    # Health
    # -----------------------------------------------------------------------
    @app.get("/health", tags=["ops"])
    async def health_check():
        """Deep health check for Koyeb and monitoring systems."""
        db_ok = deps.db is not None and getattr(deps.db, "supabase", None) is not None
        redis_ok = (
            deps.premium_ai is not None
            and getattr(getattr(deps.premium_ai, "redis", None), "client", None) is not None
        )
        ws_ok = (
            deps.ws_server is not None
            and getattr(deps.ws_server, "loop", None) is not None
            and deps.ws_server.loop.is_running()
        )
        ai_ok = deps.premium_ai is not None and getattr(deps.premium_ai, "client", None) is not None

        overall = "healthy" if (db_ok and redis_ok) else "degraded"
        payload = {
            "status": overall,
            "components": {
                "database": "connected" if db_ok else "disconnected",
                "redis": "connected" if redis_ok else "disconnected",
                "websocket": "running" if ws_ok else "stopped",
                "ai_engine": "ready" if ai_ok else "not_configured",
            },
        }

        http_status = status.HTTP_200_OK if overall == "healthy" else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(content=json.dumps(payload), media_type="application/json", status_code=http_status)

    # -----------------------------------------------------------------------
    # Auth
    # -----------------------------------------------------------------------
    @app.post("/auth/issue", tags=["auth"])
    def issue_token(telegram_id: int):
        """Issue a short-lived JWT-like token for web app use."""
        if deps.db is None:
            raise HTTPException(status_code=503, detail="DB not initialised")
        user = deps.db.get_user(telegram_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        token = sign_token(user.telegram_id, deps.auth_secret)
        logger.info("Token issued for telegram_id=%d", telegram_id)
        return {"token": token}

    @app.get("/auth/verify", tags=["auth"])
    def verify(user_id: int = Depends(get_current_user)):
        # Get user role for frontend
        role = "user"
        if deps.db:
            if user_id == 1512347775:  # Superadmin
                role = "superadmin"
            else:
                u = deps.db.get_user(user_id)
                if u:
                    role = getattr(u, "role", "user")

        return {"user_id": user_id, "status": "ok", "role": role}

    # -----------------------------------------------------------------------
    # Admin
    # -----------------------------------------------------------------------
    @app.get("/admin/users", tags=["admin"])
    def admin_list_users(user_id: int = Depends(get_current_user)):
        if not deps.db.is_admin(user_id):
            raise HTTPException(status_code=403, detail="Admin only")

        users = deps.db.get_all_users()
        return [
            {
                "id": u.id,
                "telegram_id": u.telegram_id,
                "username": getattr(u, "username", "-"),
                "role": getattr(u, "role", "user"),
                "is_active": getattr(u, "is_active", True),
                "created_at": getattr(u, "created_at", "-"),
            }
            for u in users
        ]

    @app.post("/admin/users/{target_id}/role", tags=["admin"])
    def admin_set_role(
        target_id: int,
        payload: dict[str, str],
        user_id: int = Depends(get_current_user),
    ):
        if not deps.db.is_superadmin(user_id):
            raise HTTPException(status_code=403, detail="Superadmin only")

        new_role = payload.get("role")
        if new_role not in ["user", "admin", "superadmin"]:
            raise HTTPException(status_code=400, detail="Invalid role")

        deps.db.update_user_role(target_id, new_role)
        deps.db.log_admin_action(user_id, target_id, f"change_role_{new_role}")
        return {"status": "ok"}

    @app.post("/admin/users/{target_id}/status", tags=["admin"])
    def admin_set_status(
        target_id: int,
        payload: dict[str, bool],
        user_id: int = Depends(get_current_user),
    ):
        if not deps.db.is_admin(user_id):
            raise HTTPException(status_code=403, detail="Admin only")

        is_active = payload.get("is_active", True)
        deps.db.update_user_status(target_id, is_active)
        action = "unblock" if is_active else "block"
        deps.db.log_admin_action(user_id, target_id, action, payload.get("reason"))
        return {"status": "ok"}

    @app.get("/admin/logs", tags=["admin"])
    def admin_get_logs(user_id: int = Depends(get_current_user)):
        if not deps.db.is_superadmin(user_id):
            raise HTTPException(status_code=403, detail="Superadmin only")
        return deps.db.get_admin_logs()

    @app.post("/admin/broadcast", tags=["admin"])
    async def admin_broadcast(
        payload: dict[str, str],
        user_id: int = Depends(get_current_user),
    ):
        if not deps.db.is_superadmin(user_id):
            raise HTTPException(status_code=403, detail="Superadmin only")

        message = payload.get("message")
        if not message:
            raise HTTPException(status_code=400, detail="Message empty")

        if not deps.bot:
            raise HTTPException(status_code=503, detail="Bot service not initialised")

        users = deps.db.get_all_users()
        count = 0
        for u in users:
            try:
                await deps.bot.send_message(
                    chat_id=u.telegram_id,
                    text=f"📢 **BROADCAST**\n\n{message}",
                    parse_mode="Markdown",
                )
                count += 1
            except Exception:
                pass

        deps.db.log_admin_action(user_id, 0, "broadcast", f"To {count} users")
        return {"status": "ok", "sent_to": count}

    @app.post("/admin/message/{target_id}", tags=["admin"])
    async def admin_private_message(
        target_id: int,
        payload: dict[str, str],
        user_id: int = Depends(get_current_user),
    ):
        if not deps.db.is_superadmin(user_id):
            raise HTTPException(status_code=403, detail="Superadmin only")

        message = payload.get("message")
        if not message:
            raise HTTPException(status_code=400, detail="Message empty")

        if not deps.bot:
            raise HTTPException(status_code=503, detail="Bot service not initialised")

        try:
            await deps.bot.send_message(
                chat_id=target_id,
                text=f"💬 **ADMIN MESSAGE**\n\n{message}",
                parse_mode="Markdown",
            )
            deps.db.log_admin_action(user_id, target_id, "private_message")
            return {"status": "ok"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # -----------------------------------------------------------------------
    # Stats (internal diagnostics)
    # -----------------------------------------------------------------------
    @app.get("/stats", tags=["ops"])
    def get_stats():
        if deps.premium_ai is None:
            raise HTTPException(status_code=503, detail="Premium AI not initialised")
        return deps.premium_ai.generate_comprehensive_test_report()

    # -----------------------------------------------------------------------
    # Transactions
    # -----------------------------------------------------------------------
    @app.get("/transactions", tags=["finance"])
    def list_transactions(
        limit: int = Query(50, ge=1, le=500),
        user_id: int = Depends(get_current_user),
    ):
        user = _require_user(deps.db, user_id)
        txs = deps.db.get_transactions_history(user.id, limit=limit)
        return [
            {
                "id": t.id,
                "amount": t.amount,
                "category": t.category,
                "type": t.type,
                "date": t.date,
                "description": getattr(t, "description", None),
            }
            for t in txs
        ]

    @app.post("/transactions", status_code=status.HTTP_201_CREATED, tags=["finance"])
    def create_transaction(
        payload: TransactionCreate,
        user_id: int = Depends(get_current_user),
    ):
        user = _require_user(deps.db, user_id)
        tx = deps.db.add_transaction(
            user.id,
            payload.amount,
            payload.category,
            payload.description or "",
            payload.type,
            payload.date,
        )
        logger.info("Transaction created id=%s user=%d", tx.id, user_id)
        return {"id": tx.id, "status": "created"}

    # -----------------------------------------------------------------------
    # Budgets
    # -----------------------------------------------------------------------
    @app.post("/budgets", tags=["finance"])
    def set_budget(
        payload: BudgetSet,
        user_id: int = Depends(get_current_user),
    ):
        user = _require_user(deps.db, user_id)
        b = deps.db.set_budget(user.id, payload.category, payload.limit_amount)
        return {"category": b.category, "limit_amount": b.limit_amount}

    @app.post("/budgets/alerts", tags=["finance"])
    def set_budget_alerts(
        payload: BudgetAlert,
        user_id: int = Depends(get_current_user),
    ):
        user = _require_user(deps.db, user_id)
        deps.db.set_budget_threshold(user.id, payload.category, payload.warn_threshold, payload.limit_threshold)
        return {"status": "updated"}

    # -----------------------------------------------------------------------
    # Reports
    # -----------------------------------------------------------------------
    @app.get("/reports/monthly", tags=["finance"])
    def monthly_report(
        month: int = Query(..., ge=1, le=12),
        year: int = Query(..., ge=2000, le=2100),
        user_id: int = Depends(get_current_user),
    ):
        user = _require_user(deps.db, user_id)
        txs = deps.db.get_monthly_report(user.id, month, year)
        return _summarise_transactions(txs, month=month, year=year)

    @app.get("/reports/yearly", tags=["finance"])
    def yearly_report(
        year: int = Query(..., ge=2000, le=2100),
        user_id: int = Depends(get_current_user),
    ):
        user = _require_user(deps.db, user_id)
        txs = deps.db.get_yearly_report(user.id, year)
        return _summarise_transactions(txs, year=year)

    # -----------------------------------------------------------------------
    # CSV Export — streams directly without touching the filesystem
    # -----------------------------------------------------------------------
    @app.get("/export", tags=["finance"])
    def export_csv(user_id: int = Depends(get_current_user)):
        user = _require_user(deps.db, user_id)
        txs = deps.db.get_transactions_history(user.id, limit=100_000)
        if not txs:
            raise HTTPException(status_code=404, detail="No transactions to export")

        def _generate():
            yield "id,amount,category,type,date,description\n"
            for t in txs:
                desc = (getattr(t, "description", "") or "").replace('"', '""')
                yield f'{t.id},{t.amount},"{t.category}",{t.type},{t.date},"{desc}"\n'

        filename = f"export_transaksi_{user_id}_{int(time.time())}.csv"
        return StreamingResponse(
            _generate(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # -----------------------------------------------------------------------
    # SPA fallback — must be mounted last
    # -----------------------------------------------------------------------
    static_dir = os.path.join(os.getcwd(), "web", "static")
    if os.path.exists(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
        logger.info("Static files mounted from %s", static_dir)
    else:
        logger.warning("Static directory not found at %s; SPA not served", static_dir)

        @app.get("/", tags=["ops"])
        async def spa_missing():
            return {"message": "FinBot Dashboard API is running. Static files not found."}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _require_user(db, user_id: int):
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _summarise_transactions(txs, **extra):
    total_income = sum(t.amount for t in txs if t.type == "income")
    total_expense = sum(t.amount for t in txs if t.type == "expense")
    return {"total_income": total_income, "total_expense": total_expense, **extra}


# ---------------------------------------------------------------------------
# Entry-points
# ---------------------------------------------------------------------------
def init_dependencies(
    db=None,
    premium_ai=None,
    ws_server=None,
    auth_secret: Optional[str] = None,
) -> AppDependencies:
    """
    Initialise the global dependency container.
    Call this once from your main module before start_monitor_thread().
    """
    global _deps
    with _deps_lock:
        _deps = AppDependencies(
            db=db,
            premium_ai=premium_ai,
            ws_server=ws_server,
            auth_secret=auth_secret or os.getenv("WEB_JWT_SECRET", ""),
        )
    return _deps


def start_monitor(deps: AppDependencies) -> None:
    port = int(os.getenv("PORT", 8000))
    application = create_app(deps)
    logger.info("Starting Monitor API on port %d", port)
    uvicorn.run(application, host="0.0.0.0", port=port, log_config=None)


def start_monitor_thread(
    db=None,
    premium_ai=None,
    ws_server=None,
    auth_secret: Optional[str] = None,
) -> tuple[threading.Thread, AppDependencies]:
    deps = init_dependencies(db, premium_ai, ws_server, auth_secret)
    thread = threading.Thread(target=start_monitor, args=(deps,), daemon=True)
    thread.start()
    return thread, deps