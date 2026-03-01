from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class SupabaseBaseModel(BaseModel):
    model_config = ConfigDict(extra="allow", from_attributes=True)


class UserModel(SupabaseBaseModel):
    id: Optional[int] = None
    telegram_id: int
    username: Optional[str] = None
    role: Optional[str] = "user"
    is_active: Optional[bool] = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MonthlyIncomeModel(SupabaseBaseModel):
    id: Optional[int] = None
    user_id: int
    amount: float = Field(..., ge=0)
    month: int = Field(..., ge=1, le=12)
    year: int = Field(..., ge=2000, le=2100)


class TransactionModel(SupabaseBaseModel):
    id: Optional[int] = None
    user_id: int
    amount: float = Field(..., ge=0)
    category: str
    description: Optional[str] = None
    type: str
    date: Optional[datetime] = None


class BudgetModel(SupabaseBaseModel):
    id: Optional[int] = None
    user_id: int
    category: str
    limit_amount: float = Field(..., ge=0)
    current_usage: float = Field(default=0, ge=0)
    month: int = Field(..., ge=1, le=12)
    year: int = Field(..., ge=2000, le=2100)
    warn_threshold: Optional[float] = Field(default=None, ge=0, le=1)
    limit_threshold: Optional[float] = Field(default=None, ge=0, le=1)


class SavingGoalModel(SupabaseBaseModel):
    id: Optional[int] = None
    user_id: int
    name: str
    target_amount: float = Field(..., ge=0)
    current_amount: float = Field(default=0, ge=0)
    target_date: Optional[datetime] = None
    is_active: Optional[bool] = True


class AdminLogModel(SupabaseBaseModel):
    id: Optional[int] = None
    admin_id: int
    target_id: int
    action: str
    action_type: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    reason: Optional[str] = None
    ip_address: Optional[str] = None
    timestamp: Optional[datetime] = None


class FlaggedTransactionModel(SupabaseBaseModel):
    id: Optional[int] = None
    transaction_id: Optional[int] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None


class DisputeModel(SupabaseBaseModel):
    id: Optional[int] = None
    transaction_id: Optional[int] = None
    status: Optional[str] = None
    resolution: Optional[str] = None
    created_at: Optional[datetime] = None
    resolved_by: Optional[int] = None
    resolved_at: Optional[datetime] = None


class ModerationSettingsModel(SupabaseBaseModel):
    id: Optional[int] = None
    auto_flag_high_amount: Optional[bool] = True
    high_amount_threshold: Optional[float] = Field(default=0, ge=0)
    auto_freeze_risk_score: Optional[float] = Field(default=0, ge=0, le=100)
    spam_detection_enabled: Optional[bool] = True


class MonthlyWrapperModel(SupabaseBaseModel):
    id: Optional[int] = None
    user_id: int
    month: int = Field(..., ge=1, le=12)
    year: int = Field(..., ge=2000, le=2100)
    content: dict[str, Any] = Field(default_factory=dict)
    status: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
