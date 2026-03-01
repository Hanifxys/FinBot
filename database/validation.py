from typing import Any, Dict, Type, TypeVar

from schemas.supabase_models import (
    AdminLogModel,
    BudgetModel,
    DisputeModel,
    FlaggedTransactionModel,
    ModerationSettingsModel,
    MonthlyIncomeModel,
    MonthlyWrapperModel,
    SavingGoalModel,
    TransactionModel,
    UserModel,
)

ModelT = TypeVar("ModelT")

MODEL_REGISTRY: Dict[str, Type] = {
    "users": UserModel,
    "monthly_incomes": MonthlyIncomeModel,
    "transactions": TransactionModel,
    "budgets": BudgetModel,
    "saving_goals": SavingGoalModel,
    "admin_logs": AdminLogModel,
    "flagged_transactions": FlaggedTransactionModel,
    "disputes": DisputeModel,
    "moderation_settings": ModerationSettingsModel,
    "monthly_wrappers": MonthlyWrapperModel,
}


def validate_row(table: str, row: Dict[str, Any]) -> Any:
    model = MODEL_REGISTRY.get(table)
    if not model:
        return row
    return model.model_validate(row)
