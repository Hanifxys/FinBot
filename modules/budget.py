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

    def check_budget_status(self, user_id, category):
        """
        Returns a minimalist message about the budget status for a category.
        Includes dual-threshold warnings (80% and 100%).
        """
        now = datetime.now()
        budgets = self.db.get_user_budgets(user_id)
        
        target_budget = next((b for b in budgets if b.category == category), None)
        
        if not target_budget:
            return "" # Silence if no budget set
            
        remaining = target_budget.limit_amount - target_budget.current_usage
        percent = (target_budget.current_usage / target_budget.limit_amount) * 100
        
        msg = f"Sisa budget {category}: Rp {remaining:,.0f}"
        
        # Dual-threshold warnings
        if percent >= 100:
            msg = f"🔴 LIMIT! Budget {category} sudah 100% terpakai.\nSisa: Rp 0"
        elif percent >= 80:
            msg = f"⚠️ WARNING! Budget {category} sudah {percent:.0f}% terpakai.\nSisa: Rp {remaining:,.0f}"
            
        return msg

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
        Generates a summary report of transactions.
        Supports 'monthly', '7days', and '30days' (sliding windows).
        """
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
        
        report_text = f"📊 {title}\n\n"
        
        incomes = summary[summary['type'] == 'income']
        if not incomes.empty:
            report_text += "💰 Pemasukan:\n"
            for _, row in incomes.iterrows():
                report_text += f"- {row['category']}: Rp {row['amount']:,.0f}\n"
            report_text += f"Total: Rp {incomes['amount'].sum():,.0f}\n\n"
            
        expenses = summary[summary['type'] == 'expense']
        if not expenses.empty:
            report_text += "💸 Pengeluaran:\n"
            for _, row in expenses.iterrows():
                report_text += f"- {row['category']}: Rp {row['amount']:,.0f}\n"
            report_text += f"Total: Rp {expenses['amount'].sum():,.0f}\n"
            
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
            'pokok': p_pokok,
            'tabungan': p_tabungan,
            'investasi': p_investasi,
            'fleksibel': p_fleksibel
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
