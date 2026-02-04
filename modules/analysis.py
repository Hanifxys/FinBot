import pandas as pd
from datetime import datetime, timedelta

class ExpenseAnalyzer:
    def __init__(self, db_handler):
        self.db = db_handler

    def analyze_patterns(self, user_id):
        """
        Observasi jujur tentang pola pengeluaran.
        """
        now = datetime.now()
        transactions = self.db.get_monthly_report(user_id, now.month, now.year)
        
        if not transactions:
            return ""

        df = pd.DataFrame([{
            'amount': t.amount,
            'category': t.category,
            'date': t.date,
            'hour': t.date.hour,
            'day': t.date.strftime('%A'),
            'type': t.type
        } for t in transactions])

        expenses = df[df['type'] == 'expense']
        if expenses.empty:
            return ""

        # Analysis: Time Pattern
        night_spending = expenses[expenses['hour'] >= 19]
        night_percent = (night_spending['amount'].sum() / expenses['amount'].sum()) * 100 if not expenses.empty else 0
        
        # Analysis: Boros Day
        boros_day = expenses.groupby('day')['amount'].sum().idxmax()

        insight = "Aku amati ini:\n"
        if night_percent > 50:
            insight += f"• {night_percent:.0f}% pengeluaran kamu terjadi di malam hari (jam 19-22).\n"
        
        insight += f"• Kamu paling boros di hari {boros_day}.\n"
        
        return insight

    def calculate_health_score(self, user_id):
        """
        Simple, transparent financial health score.
        """
        now = datetime.now()
        budgets = self.db.get_user_budgets(user_id)
        transactions = self.db.get_monthly_report(user_id, now.month, now.year)
        income = self.db.get_latest_income(user_id)
        
        if not income: return 50
        
        score = 100
        
        # 1. Budget Discipline (Max 40 points)
        over_budget_count = sum(1 for b in budgets if b.current_usage > b.limit_amount)
        score -= (over_budget_count * 10)
        
        # 2. Impulse Spending (Night transactions > 50k) (Max 30 points)
        impulse_tx = sum(1 for t in transactions if t.date.hour >= 22 and t.amount > 50000)
        score -= (impulse_tx * 5)
        
        # 3. Income Stability (If current usage > income)
        total_expense = sum(t.amount for t in transactions if t.type == 'expense')
        if total_expense > income.amount:
            score -= 20
            
        return max(0, min(100, score))
