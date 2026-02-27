import pandas as pd
from datetime import datetime
import sys
import os

# Add project root to path for config import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ALLOCATION_RULES

class BudgetManager:
    def __init__(self, db_handler):
        self.db = db_handler

    def check_budget_status(self, user_id, category=None):
        """
        Returns a minimalist message about the budget status with polished formatting.
        """
        from utils.visuals import format_currency
        now = datetime.now()
        
        if category:
            budgets = self.db.get_user_budgets(user_id)
            target_budget = next((b for b in budgets if b.category == category), None)
            
            if not target_budget: return "" 
                
            remaining = target_budget.limit_amount - target_budget.current_usage
            percent = (target_budget.current_usage / target_budget.limit_amount) * 100 if target_budget.limit_amount > 0 else 0
            
            msg = f"Sisa budget {category}: **{format_currency(remaining)}**"
            
            warn_th = getattr(target_budget, 'warn_threshold', 0.8) * 100
            limit_th = getattr(target_budget, 'limit_threshold', 1.0) * 100
            
            if percent >= limit_th:
                msg = f"🔴 **LIMIT!** Budget {category} sudah 100% terpakai."
            elif percent >= warn_th:
                msg = f"⚠️ **WARNING!** Budget {category} sudah {percent:.0f}% terpakai.\nSisa: **{format_currency(remaining)}**"
                
            return msg
        else:
            txs = self.db.get_monthly_report(user_id, now.month, now.year)
            if not txs: return "Belum ada data keuangan bulan ini."
                
            total_income = sum(t.amount for t in txs if t.type == 'income')
            total_expense = sum(t.amount for t in txs if t.type == 'expense')
            remaining = total_income - total_expense
            
            return (
                f"💰 **Status Keuangan**\n"
                f"• Pemasukan: {format_currency(total_income)}\n"
                f"• Pengeluaran: {format_currency(total_expense)}\n"
                f"• Sisa Uang: **{format_currency(remaining)}**"
            )

    def get_decision_framing(self, user_id, category, amount):
        """
        Actionable framing: "Safe for X days if daily avg is Y"
        """
        try:
            now = datetime.now()
            days_in_month = 30
            days_left = max(1, days_in_month - now.day)
            
            budgets = self.db.get_user_budgets(user_id)
            target = next((b for b in budgets if b.category == category), None)
            
            if not target or target.limit_amount <= 0:
                return ""
                
            remaining = target.limit_amount - (target.current_usage + amount)
            if remaining <= 0:
                return "🚨 **Limit Habis**: Budget ini sudah terlampaui. Hati-hati!"
            
            daily_allowance = remaining / days_left
            from utils.visuals import format_currency
            
            return f"💡 **Analisis**: Sisa **{format_currency(remaining)}** cukup untuk **{days_left} hari** ke depan jika rata-rata pengeluaran harianmu **{format_currency(daily_allowance)}**."
        except Exception:
            return ""

    def generate_yearly_summary(self, user_id, year: int):
        transactions = self.db.get_yearly_report(user_id, year)
        if not transactions:
            return f"Tidak ada transaksi untuk tahun {year}."
        df = pd.DataFrame([{
            'amount': t.amount,
            'category': t.category,
            'type': t.type
        } for t in transactions])
        summary = df.groupby(['type'])['amount'].sum()
        total_income = summary.get('income', 0)
        total_expense = summary.get('expense', 0)
        balance = total_income - total_expense
        return (
            f"📅 Ringkasan Tahun {year}\n\n"
            f"Total Pemasukan: Rp {total_income:,.0f}\n"
            f"Total Pengeluaran: Rp {total_expense:,.0f}\n"
            f"Saldo Tahun Ini: Rp {balance:,.0f}"
        )

    def get_detailed_budget_status(self, user_id, category):
        """
        3-line template for budget status.
        """
        now = datetime.now()
        budgets = self.db.get_user_budgets(user_id)
        target_budget = next((b for b in budgets if b.category == category), None)
        
        if not target_budget:
            return f"{category}\nLimit: Rp 0\nSisa: Rp 0"
            
        remaining = target_budget.limit_amount - target_budget.current_usage
        return (f"{category}\n"
                f"Limit: Rp {target_budget.limit_amount:,.0f}\n"
                f"Terpakai: Rp {target_budget.current_usage:,.0f}\n"
                f"Sisa: Rp {remaining:,.0f}")

    def generate_report(self, user_id, period='monthly'):
        """
        Generates a summary report of transactions with polished formatting.
        """
        from utils.visuals import format_currency
        now = datetime.now()
        
        if period == '7days':
            transactions = self.db.get_sliding_window_transactions(user_id, days=7)
            title = "Ringkasan 7 Hari Terakhir"
        elif period == '30days':
            transactions = self.db.get_sliding_window_transactions(user_id, days=30)
            title = "Ringkasan 30 Hari Terakhir"
        else:
            transactions = self.db.get_monthly_report(user_id, now.month, now.year)
            title = f"Laporan Keuangan {now.strftime('%B %Y')}"
        
        if not transactions:
            return f"Belum ada transaksi untuk periode {title.lower()}."
            
        df = pd.DataFrame([{
            'amount': t.amount,
            'category': t.category,
            'type': t.type
        } for t in transactions])
        
        summary = df.groupby(['type', 'category'])['amount'].sum().reset_index()
        
        report_text = f"📊 **{title}**\n\n"
        
        incomes = summary[summary['type'] == 'income']
        if not incomes.empty:
            report_text += "💰 **Pemasukan**:\n"
            for _, row in incomes.iterrows():
                report_text += f"• {row['category']}: {format_currency(row['amount'])}\n"
            report_text += f"Total: **{format_currency(incomes['amount'].sum())}**\n\n"
            
        expenses = summary[summary['type'] == 'expense']
        if not expenses.empty:
            report_text += "💸 **Pengeluaran**:\n"
            for _, row in expenses.iterrows():
                report_text += f"• {row['category']}: {format_currency(row['amount'])}\n"
            report_text += f"Total: **{format_currency(expenses['amount'].sum())}**\n"
            
        return report_text

    def get_allocation_recommendation(self, total_income):
        # Professional & Clean formatting
        # No excessive emojis, clear numbers
        p_pokok = total_income * 0.5
        p_tabungan = total_income * 0.2
        p_investasi = total_income * 0.1
        p_fleksibel = total_income * 0.2
        
        msg = (
            "Ringkasan gaji bulan ini\n\n"
            f"Pokok: Rp{p_pokok:,.0f}\n"
            f"Tabungan: Rp{p_tabungan:,.0f}\n"
            f"Investasi: Rp{p_investasi:,.0f}\n"
            f"Fleksibel: Rp{p_fleksibel:,.0f}"
        )
        
        return msg, {
            'Kebutuhan Pokok': p_pokok,
            'Tabungan': p_tabungan,
            'Investasi': p_investasi,
            'Hiburan/Fleksibel': p_fleksibel
        }

    def get_burn_rate(self, user_id, category):
        """
        Calculates how fast the budget is being spent.
        """
        now = datetime.now()
        budget = self.db.get_user_budgets(user_id)
        target = next((b for b in budget if b.category == category), None)
        
        if not target or target.limit_amount == 0:
            return None
            
        day_of_month = now.day
        days_in_month = 30 # Approximation
        
        expected_usage_percent = (day_of_month / days_in_month) * 100
        actual_usage_percent = (target.current_usage / target.limit_amount) * 100
        
        diff = actual_usage_percent - expected_usage_percent
        
        if diff > 10:
            return f"⚠️ Pengeluaran kamu {diff:.0f}% lebih cepat dari normal."
        return None
