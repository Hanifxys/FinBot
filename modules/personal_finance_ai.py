import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from modules.ai_memory import AIMemory
from modules.redis_mgr import RedisManager

logger = logging.getLogger(__name__)


@dataclass
class DebtItem:
    name: str
    balance: float
    apr: float
    min_payment: float


class PersonalFinanceAI:
    """
    Unified AI-powered personal financial assistant layers:
    1) Long-term narrative memory
    2) Real financial intelligence (inflation/purchasing power/lifestyle creep)
    3) Persona-aware strategy shaping
    4) Debt optimizer (snowball/avalanche)
    5) Scenario simulation
    6) Net worth tracker
    """

    def __init__(self, db_handler, persona_mgr) -> None:
        self.db = db_handler
        self.persona_mgr = persona_mgr
        self.redis = RedisManager()
        self.default_annual_inflation = float(os.getenv("ANNUAL_INFLATION_RATE", "0.045"))

    def _shift_month(self, year: int, month: int, back: int) -> tuple[int, int]:
        m = month
        y = year
        for _ in range(back):
            if m == 1:
                m = 12
                y -= 1
            else:
                m -= 1
        return y, m

    def _monthly_expense_income(self, user_db_id: int, months: int = 12) -> List[Dict[str, Any]]:
        now = datetime.now()
        rows: List[Dict[str, Any]] = []
        for i in range(months - 1, -1, -1):
            year, month = self._shift_month(now.year, now.month, i)
            txs = self.db.get_monthly_report(user_db_id, month, year)
            income = sum(float(getattr(t, "amount", 0) or 0) for t in txs if getattr(t, "type", "") == "income")
            expense = sum(float(getattr(t, "amount", 0) or 0) for t in txs if getattr(t, "type", "") == "expense")
            rows.append({"year": year, "month": month, "income": income, "expense": expense})
        return rows

    def _history_rows(self, user_db_id: int, days: int = 365) -> List[Dict[str, Any]]:
        txs = self.db.get_sliding_window_transactions(user_db_id, days=days)
        rows: List[Dict[str, Any]] = []
        for t in txs:
            d = getattr(t, "date", None)
            if not d:
                continue
            rows.append(
                {
                    "id": getattr(t, "id", None),
                    "amount": float(getattr(t, "amount", 0) or 0),
                    "category": getattr(t, "category", "Lain-lain"),
                    "type": getattr(t, "type", "expense"),
                    "description": (getattr(t, "description", "") or "").lower(),
                    "date": d,
                }
            )
        return rows

    # 1) AI Memory Layer
    def long_term_narrative(self, telegram_user_id: int, user_db_id: int) -> Dict[str, Any]:
        mem = AIMemory(telegram_user_id)
        ctx = mem.get_context(limit=80)
        combined = "\n".join((m.get("content") or "").lower() for m in ctx)

        save_intent_phrases = ["hemat", "nabung", "save money", "kurangi", "disiplin"]
        save_intent_hits = sum(1 for p in save_intent_phrases if p in combined)

        rows = self._history_rows(user_db_id, days=180)
        weekend_ratio_recent = weekend_ratio_prev = 0.0
        narrative = []

        if rows:
            exp = [r for r in rows if r["type"] == "expense"]
            split_point = datetime.now() - timedelta(days=90)
            recent = [r for r in exp if r["date"] >= split_point]
            prev = [r for r in exp if r["date"] < split_point]

            def _wk_ratio(x):
                total = sum(r["amount"] for r in x)
                if total <= 0:
                    return 0.0
                wk = sum(r["amount"] for r in x if r["date"].weekday() >= 5)
                return wk / total

            weekend_ratio_recent = _wk_ratio(recent)
            weekend_ratio_prev = _wk_ratio(prev)

        if save_intent_hits > 0 and weekend_ratio_recent >= max(0.28, weekend_ratio_prev):
            narrative.append("Sekitar 3 bulan lalu kamu juga bilang ingin lebih hemat, tapi pola belanja weekend kamu masih mirip.")
        if weekend_ratio_recent > 0.35:
            narrative.append("Belanja akhir pekan mendominasi pengeluaran; ini titik intervensi paling cepat.")
        if not narrative:
            narrative.append("Narasi finansial kamu relatif konsisten; pertahankan ritme pengeluaran saat ini.")

        return {
            "save_intent_mentions": save_intent_hits,
            "weekend_spend_ratio_recent": round(weekend_ratio_recent * 100, 2),
            "weekend_spend_ratio_previous": round(weekend_ratio_prev * 100, 2),
            "narrative": narrative,
        }

    # 2) Real Financial Intelligence Layer
    def real_financial_intelligence(self, user_db_id: int) -> Dict[str, Any]:
        monthly = self._monthly_expense_income(user_db_id, months=12)
        if not monthly:
            return {"ok": False, "msg": "Data belum cukup"}

        incomes = [m["income"] for m in monthly]
        expenses = [m["expense"] for m in monthly]

        avg_income_3 = sum(incomes[-3:]) / max(1, len(incomes[-3:]))
        avg_income_prev3 = sum(incomes[-6:-3]) / max(1, len(incomes[-6:-3])) if len(incomes) >= 6 else avg_income_3
        avg_exp_3 = sum(expenses[-3:]) / max(1, len(expenses[-3:]))
        avg_exp_prev3 = sum(expenses[-6:-3]) / max(1, len(expenses[-6:-3])) if len(expenses) >= 6 else avg_exp_3

        income_growth = ((avg_income_3 - avg_income_prev3) / avg_income_prev3 * 100) if avg_income_prev3 > 0 else 0.0
        expense_growth = ((avg_exp_3 - avg_exp_prev3) / avg_exp_prev3 * 100) if avg_exp_prev3 > 0 else 0.0

        monthly_inflation = (1 + self.default_annual_inflation) ** (1 / 12) - 1
        inflation_drag_pct = ((1 + self.default_annual_inflation) - 1) * 100

        ppi = []
        for idx, item in enumerate(monthly):
            infl_factor = (1 + monthly_inflation) ** idx
            real_income = item["income"] / infl_factor if infl_factor > 0 else item["income"]
            ppi.append(real_income)
        ppi_change = ((ppi[-1] - ppi[0]) / ppi[0] * 100) if ppi and ppi[0] > 0 else 0.0

        lifestyle_creep = expense_growth > 8 and income_growth < expense_growth
        income_stagnation = income_growth < 2 and expense_growth > 4

        alerts = []
        if lifestyle_creep:
            alerts.append("Lifestyle creep terdeteksi: pengeluaran naik lebih cepat dari pendapatan.")
        if income_stagnation:
            alerts.append("Income stagnation alert: pertumbuhan pendapatan rendah dibanding kenaikan biaya hidup.")

        return {
            "ok": True,
            "annual_inflation_pct": round(inflation_drag_pct, 2),
            "income_growth_3m_pct": round(income_growth, 2),
            "expense_growth_3m_pct": round(expense_growth, 2),
            "purchasing_power_change_pct": round(ppi_change, 2),
            "lifestyle_creep": lifestyle_creep,
            "income_stagnation": income_stagnation,
            "alerts": alerts,
        }

    # 3) Persona Intelligence Layer
    def persona_advice_policy(self, user_id: int, user_db_id: Optional[int] = None) -> Dict[str, Any]:
        profile = self.persona_mgr.get_financial_profile(user_id=user_id, db_handler=self.db, user_db_id=user_db_id)
        return {
            "persona": profile.get("persona"),
            "risk_tolerance": profile.get("risk_tolerance"),
            "tone": profile.get("tone"),
            "strategy": profile.get("strategy"),
            "guardrails": profile.get("guardrails", []),
        }

    def persona_investment_hint(self, user_id: int, user_db_id: Optional[int] = None) -> str:
        p = self.persona_advice_policy(user_id=user_id, user_db_id=user_db_id)
        persona = (p.get("persona") or "").lower()
        if "growth" in persona:
            return "Fokus growth: alokasikan porsi lebih tinggi ke aset berisiko dengan batas risiko ketat."
        if "risk avoider" in persona:
            return "Fokus proteksi modal: prioritaskan instrumen defensif dan likuiditas."
        if "over-spender" in persona:
            return "Tunda ekspansi investasi agresif; stabilkan cashflow dan disiplin budget dulu."
        return "Gunakan strategi seimbang: kombinasi aset defensif dan growth secara bertahap."

    # 4) Debt Optimizer
    def _infer_debts(self, user_db_id: int) -> List[DebtItem]:
        rows = self._history_rows(user_db_id, days=180)
        if not rows:
            return []
        debt_rows = []
        for r in rows:
            if r["type"] != "expense":
                continue
            cat = r["category"].lower()
            desc = r["description"]
            if cat in {"cicilan", "hutang", "kredit", "pinjaman"} or re.search(r"cicil|kredit|pinjam|cc|card", desc):
                debt_rows.append(r)
        if not debt_rows:
            return []

        grouped: Dict[str, float] = {}
        for r in debt_rows:
            grouped[r["category"]] = grouped.get(r["category"], 0.0) + float(r["amount"])

        out = []
        for cat, total in grouped.items():
            est_balance = total * 6.0
            apr = 0.24 if str(cat).lower() in {"kredit", "cc"} else 0.14
            min_p = max(100000.0, est_balance * 0.04)
            out.append(DebtItem(name=str(cat), balance=est_balance, apr=apr, min_payment=min_p))
        return out

    @staticmethod
    def _simulate_debt_payoff(debts: List[DebtItem], method: str, extra_payment: float) -> Dict[str, Any]:
        items = [DebtItem(d.name, float(d.balance), float(d.apr), float(d.min_payment)) for d in debts]
        total_interest = 0.0
        months = 0

        while any(d.balance > 1 for d in items) and months < 600:
            months += 1
            for d in items:
                if d.balance <= 0:
                    continue
                monthly_rate = d.apr / 12.0
                old = d.balance
                d.balance += d.balance * monthly_rate
                total_interest += d.balance - old

            for d in items:
                if d.balance <= 0:
                    continue
                pay = min(d.balance, d.min_payment)
                d.balance -= pay

            active = [d for d in items if d.balance > 0]
            if not active:
                break
            target = sorted(active, key=lambda x: x.balance)[0] if method == "snowball" else sorted(active, key=lambda x: x.apr, reverse=True)[0]
            target.balance -= min(target.balance, extra_payment)

        return {"months": months, "interest_est": round(total_interest, 2)}

    def debt_optimizer(self, user_db_id: int, extra_payment: float = 500000.0) -> Dict[str, Any]:
        debts = self._infer_debts(user_db_id)
        if not debts:
            return {"ok": False, "msg": "Belum ada data utang/cicilan yang cukup."}

        snow = self._simulate_debt_payoff(debts, method="snowball", extra_payment=extra_payment)
        aval = self._simulate_debt_payoff(debts, method="avalanche", extra_payment=extra_payment)
        recommend = "avalanche" if aval["interest_est"] <= snow["interest_est"] else "snowball"
        savings = abs(snow["interest_est"] - aval["interest_est"])

        return {
            "ok": True,
            "debts": [d.__dict__ for d in debts],
            "snowball": snow,
            "avalanche": aval,
            "recommended": recommend,
            "interest_savings_est": round(savings, 2),
        }

    # 5) Scenario Simulation Layer
    def simulate_scenario(self, user_db_id: int, scenario_text: str) -> Dict[str, Any]:
        monthly = self._monthly_expense_income(user_db_id, months=6)
        if not monthly:
            return {"ok": False, "msg": "Data belum cukup untuk simulasi."}

        avg_income = sum(m["income"] for m in monthly) / len(monthly)
        avg_expense = sum(m["expense"] for m in monthly) / len(monthly)
        burn_rate = max(0.0, avg_expense - avg_income) if avg_expense > avg_income else avg_expense

        text = (scenario_text or "").lower()
        resign_match = re.search(r"resign\s*(\d+)\s*bulan", text)
        loan_match = re.search(r"(\d+[\.,]?\d*)\s*(jt|juta|rb|ribu)?\s*/\s*bulan", text)

        income_after = avg_income
        expense_after = avg_expense
        event = "general"

        if resign_match:
            event = "resign"
            resign_in = int(resign_match.group(1))
            income_after = avg_income * (0.2 if resign_in <= 6 else 0.4)

        if loan_match:
            event = "loan"
            raw = float(loan_match.group(1).replace(",", "."))
            unit = loan_match.group(2) or ""
            monthly_loan = raw * 1_000_000 if unit in {"jt", "juta"} else raw * 1_000 if unit in {"rb", "ribu"} else raw
            expense_after += monthly_loan

        nw = self.net_worth(user_db_id)
        liquid = float(nw.get("assets", {}).get("cash", 0.0))
        net_burn = max(1.0, expense_after - income_after)
        coverage_months = liquid / net_burn if net_burn > 0 else 24.0

        ratio = expense_after / max(1.0, income_after)
        risk_prob = min(0.95, max(0.05, ratio / 2.0))

        projection_12m = []
        cash = liquid
        for m in range(1, 13):
            cash += income_after - expense_after
            projection_12m.append({"month": m, "cash": round(cash, 2)})

        return {
            "ok": True,
            "event": event,
            "avg_income": round(avg_income, 2),
            "avg_expense": round(avg_expense, 2),
            "burn_rate": round(burn_rate, 2),
            "income_after": round(income_after, 2),
            "expense_after": round(expense_after, 2),
            "emergency_coverage_months": round(coverage_months, 2),
            "risk_probability": round(risk_prob, 3),
            "projection_12m": projection_12m,
        }

    # 6) Net Worth Tracker
    def _nw_key_assets(self, user_db_id: int) -> str:
        return f"user:{user_db_id}:networth:assets"

    def _nw_key_liabilities(self, user_db_id: int) -> str:
        return f"user:{user_db_id}:networth:liabilities"

    def set_asset(self, user_db_id: int, asset_name: str, amount: float) -> bool:
        if not self.redis.client:
            return False
        try:
            self.redis.client.hset(self._nw_key_assets(user_db_id), asset_name.lower(), float(amount))
            return True
        except Exception:
            return False

    def set_liability(self, user_db_id: int, liability_name: str, amount: float) -> bool:
        if not self.redis.client:
            return False
        try:
            self.redis.client.hset(self._nw_key_liabilities(user_db_id), liability_name.lower(), float(amount))
            return True
        except Exception:
            return False

    def _get_hash_float_map(self, key: str) -> Dict[str, float]:
        if not self.redis.client:
            return {}
        try:
            raw = self.redis.client.hgetall(key) or {}
            return {str(k): float(v) for k, v in raw.items()}
        except Exception:
            return {}

    def net_worth(self, user_db_id: int) -> Dict[str, Any]:
        assets = self._get_hash_float_map(self._nw_key_assets(user_db_id))
        liabilities = self._get_hash_float_map(self._nw_key_liabilities(user_db_id))

        monthly = self._monthly_expense_income(user_db_id, months=3)
        est_cash = sum(m["income"] - m["expense"] for m in monthly) if monthly else 0.0
        assets.setdefault("cash", max(0.0, est_cash))

        if not liabilities:
            debts = self._infer_debts(user_db_id)
            if debts:
                liabilities["estimated_debt"] = round(sum(d.balance for d in debts), 2)

        total_assets = sum(assets.values())
        total_liabilities = sum(liabilities.values())
        net = total_assets - total_liabilities

        month_data = self._monthly_expense_income(user_db_id, months=2)
        delta = 0.0
        if len(month_data) == 2:
            delta = (month_data[-1]["income"] - month_data[-1]["expense"]) - (month_data[0]["income"] - month_data[0]["expense"])
        delta_pct = (delta / net * 100.0) if net != 0 else 0.0

        return {
            "assets": assets,
            "liabilities": liabilities,
            "total_assets": round(total_assets, 2),
            "total_liabilities": round(total_liabilities, 2),
            "net_worth": round(net, 2),
            "monthly_delta": round(delta, 2),
            "monthly_delta_pct": round(delta_pct, 2),
        }

    # Continuous learning hook
    def record_feedback(self, user_id: int, feature: str, accepted: bool) -> None:
        if not self.redis.client:
            return
        try:
            key = f"user:{user_id}:ml_feedback:{feature}"
            field = "accepted" if accepted else "rejected"
            self.redis.client.hincrby(key, field, 1)
            self.redis.client.expire(key, 180 * 24 * 3600)
        except Exception:
            pass
