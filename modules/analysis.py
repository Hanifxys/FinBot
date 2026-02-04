import pandas as pd
from datetime import datetime, timedelta

class ExpenseAnalyzer:
    def __init__(self, db_handler):
        self.db = db_handler

    def analyze_patterns(self, user_id):
        """
        Observasi jujur tentang pola pengeluaran dengan AI Smart Insights.
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
            return "Belum ada data pengeluaran bulan ini untuk dianalisis."

        insight = "🧠 **AI SMART INSIGHTS**\n"
        
        # 1. Time Analysis (Night Spending)
        night_spending = expenses[expenses['hour'] >= 19]
        night_percent = (night_spending['amount'].sum() / expenses['amount'].sum()) * 100
        if night_percent > 40:
            insight += f"• **Peringatan Malam**: {night_percent:.0f}% uangmu keluar setelah jam 7 malam. Hati-hati lapar mata!\n"
        
        # 2. Boros Day
        day_counts = expenses.groupby('day')['amount'].sum()
        boros_day = day_counts.idxmax()
        insight += f"• **Hari Boros**: Kamu paling banyak belanja di hari {boros_day}.\n"

        # 3. Anomaly Detection (Single transaction > 3x average)
        avg_tx = expenses['amount'].mean()
        big_tx = expenses[expenses['amount'] > (avg_tx * 3)]
        if not big_tx.empty:
            insight += f"• **Deteksi Anomali**: Ada transaksi besar yang di atas rata-rata. Perlu dikontrol?\n"

        # 4. Trend Analysis (vs Last Week)
        last_week = now - timedelta(days=7)
        lw_tx = [t for t in transactions if t.date >= last_week]
        if lw_tx:
            lw_total = sum(t.amount for t in lw_tx if t.type == 'expense')
            daily_avg = lw_total / 7
            insight += f"• **Tren**: Rata-rata pengeluaran harianmu seminggu terakhir adalah Rp{daily_avg:,.0f}.\n"

        # 5. Suggestion
        income = self.db.get_latest_income(user_id)
        if income:
            savings_rate = ((income.amount - expenses['amount'].sum()) / income.amount) * 100
            if savings_rate < 10:
                insight += "• **Saran**: Tabunganmu bulan ini di bawah 10%. Coba kurangi kategori non-primer.\n"
            else:
                insight += f"• **Saran**: Kamu sudah menabung {savings_rate:.0f}% gaji. Pertahankan!\n"
        
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
