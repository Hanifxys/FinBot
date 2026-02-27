import pandas as pd
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class ExpenseAnalyzer:
    def __init__(self, db_handler):
        self.db = db_handler

    def detect_recurring_patterns(self, user_id):
        """
        Detects potential recurring expenses (subscriptions, bills).
        Returns a list of dicts: {'merchant': str, 'amount': float, 'interval_days': int, 'confidence': float}
        """
        try:
            # Analyze last 90 days to find monthly patterns
            transactions = self.db.get_sliding_window_transactions(user_id, days=90)
            if not transactions:
                return []
            
            # Filter expenses only
            expenses = [t for t in transactions if t.type == 'expense']
            if len(expenses) < 5:
                return []
                
            df = pd.DataFrame([{
                'merchant': (t.description or t.category).lower().strip(),
                'amount': float(t.amount),
                'date': t.date,
                'id': t.id
            } for t in expenses])
            
            recurring = []
            
            # Group by merchant and amount (fuzzy match usually better, but exact amount for bills is common)
            grouped = df.groupby(['merchant', 'amount'])
            
            for (merchant, amount), group in grouped:
                if len(group) >= 2:
                    dates = group['date'].sort_values()
                    diffs = dates.diff().dt.days.dropna()
                    
                    # Check for monthly (28-32 days) or weekly (6-8 days) patterns
                    avg_diff = diffs.mean()
                    std_diff = diffs.std() if len(diffs) > 1 else 0
                    
                    is_monthly = 25 <= avg_diff <= 35 and std_diff < 5
                    is_weekly = 6 <= avg_diff <= 8 and std_diff < 2
                    
                    if is_monthly or is_weekly:
                        recurring.append({
                            'merchant': merchant,
                            'amount': amount,
                            'interval_days': int(avg_diff),
                            'type': 'monthly' if is_monthly else 'weekly',
                            'confidence': 0.9 if std_diff < 2 else 0.7
                        })
            
            return recurring
        except Exception as e:
            logger.error(f"Error detecting recurring patterns: {e}")
            return []

    def get_predictive_context(self, user_id, category, amount):
        """
        Predicts merchant and time based on historical patterns for a category/amount.
        Returns: {'merchant': str, 'time_label': str, 'confidence': float}
        """
        try:
            # Query last 100 transactions for this user
            transactions = self.db.get_sliding_window_transactions(user_id, days=180)
            if not transactions:
                return None
            
            # Filter by category and similar amount (±20%)
            similar = [t for t in transactions if t.category == category and 
                       t.type == 'expense' and
                       (amount * 0.8 <= t.amount <= amount * 1.2)]
            
            if not similar:
                # Fallback to category only if amount match fails
                similar = [t for t in transactions if t.category == category and t.type == 'expense']
            
            if not similar:
                return None
                
            df = pd.DataFrame([{
                'merchant': (t.description or "").split('(')[0].strip(),
                'hour': t.date.hour
            } for t in similar])
            
            # Find most frequent merchant
            top_merchant = df['merchant'].mode().iloc[0] if not df['merchant'].empty else None
            merchant_count = (df['merchant'] == top_merchant).sum()
            merchant_conf = merchant_count / len(df)
            
            # Find time pattern
            avg_hour = df['hour'].mean()
            if 5 <= avg_hour <= 11: time_label = "pagi"
            elif 12 <= avg_hour <= 15: time_label = "siang"
            elif 16 <= avg_hour <= 19: time_label = "sore"
            else: time_label = "malam"
            
            return {
                'merchant': top_merchant if merchant_conf > 0.5 else None,
                'time_label': time_label,
                'confidence': merchant_conf
            }
        except Exception as e:
            logger.error(f"Error in predictive context: {e}")
            return None

    def get_financial_dna(self, user_id):
        """
        Builds a Personal Financial DNA profile for the user.
        """
        try:
            now = datetime.now()
            transactions = self.db.get_sliding_window_transactions(user_id, days=60)
            if not transactions:
                return {}
                
            df = pd.DataFrame([{
                'amount': t.amount,
                'date': t.date,
                'day': t.date.strftime('%A'),
                'is_weekend': t.date.weekday() >= 5,
                'day_of_month': t.date.day,
                'hour': t.date.hour,
                'type': t.type
            } for t in transactions])
            
            expenses = df[df['type'] == 'expense']
            if expenses.empty:
                return {}
                
            # 1. Spending Tempo (Boros awal bulan?)
            early_month = expenses[expenses['day_of_month'] <= 10]['amount'].sum()
            late_month = expenses[expenses['day_of_month'] > 20]['amount'].sum()
            tempo = "boros_awal" if early_month > late_month * 1.5 else "stabil"
            
            # 2. Weekend Spike
            weekend_avg = expenses[expenses['is_weekend']]['amount'].mean()
            weekday_avg = expenses[~expenses['is_weekend']]['amount'].mean()
            weekend_spike = weekend_avg > weekday_avg * 1.3
            
            # 3. Emotional Spender (Late night + Impulse categories)
            impulse_cats = ["Jajanan", "Lifestyle", "Belanja"]
            night_impulse = expenses[(expenses['hour'] >= 21) & (expenses['category'].isin(impulse_cats))]
            is_emotional = len(night_impulse) > len(expenses) * 0.1
            
            return {
                "tempo": tempo,
                "weekend_spike": weekend_spike,
                "emotional_spender": is_emotional,
                "top_day": expenses.groupby('day')['amount'].sum().idxmax()
            }
        except Exception:
            return {}

    def get_instant_feedback(self, user_id, category, merchant, amount):
        """
        Provides real-time behavioural feedback for a new transaction.
        e.g., "This is your largest purchase this month!"
        """
        try:
            now = datetime.now()
            month_tx = self.db.get_monthly_report(user_id, now.month, now.year)
            month_expenses = [t for t in month_tx if t.type == 'expense']
            
            feedback = []
            
            # 1. Largest Purchase Detection
            if month_expenses:
                max_tx = max(t.amount for t in month_expenses)
                if amount > max_tx:
                    feedback.append(f"🏆 **Pembelian Terbesar**: Ini pengeluaran terbesar kamu di bulan {now.strftime('%B')}!")
            
            # 2. Frequency in 7 Days
            week_tx = self.db.get_sliding_window_transactions(user_id, days=7)
            similar_count = len([t for t in week_tx if t.category == category]) + 1
            if similar_count >= 3:
                feedback.append(f"🔄 **Pola Terulang**: Sudah {similar_count}x belanja {category} minggu ini.")
            
            # 3. Discretionary Remaining (Budget context)
            budgets = self.db.get_user_budgets(user_id)
            # Essential categories (example)
            essential_cats = ["Tagihan", "Pendidikan", "Kesehatan", "Maintenance"]
            
            total_limit = sum(b.limit_amount for b in budgets)
            essential_usage = sum(b.current_usage for b in budgets if b.category in essential_cats)
            total_usage = sum(b.current_usage for b in budgets)
            
            if total_limit > 0:
                discretionary_limit = total_limit - sum(b.limit_amount for b in budgets if b.category in essential_cats)
                non_essential_usage = total_usage - essential_usage
                remaining_discretionary = discretionary_limit - non_essential_usage
                
                if discretionary_limit > 0:
                    pct_left = (remaining_discretionary / discretionary_limit) * 100
                    if pct_left < 20:
                        feedback.append(f"⚠️ **Waspada**: Sisa uang 'senang-senang' kamu tinggal {max(0, pct_left):.0f}% untuk bulan ini.")
            
            # 4. Personality Adjustment Context
            # Determine "stress level" for persona engine
            stress_level = "low"
            if any("🚨" in f or "⚠️" in f for f in feedback):
                stress_level = "high"
            
            return "\n".join(feedback), stress_level
            
        except Exception as e:
            logger.error(f"Error in instant feedback: {e}")
            return "", "low"

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
        if not night_spending.empty:
            night_percent = (night_spending['amount'].sum() / expenses['amount'].sum()) * 100
            if night_percent > 40:
                insight += f"• **Peringatan Malam**: {night_percent:.0f}% uangmu keluar setelah jam 7 malam. Hati-hati lapar mata!\n"
        
        # 2. Boros Day
        day_counts = expenses.groupby('day')['amount'].sum()
        if not day_counts.empty:
            boros_day = day_counts.idxmax()
            insight += f"• **Hari Boros**: Kamu paling banyak belanja di hari {boros_day}.\n"

        # 3. Anomaly Detection (Single transaction > 3x average)
        avg_tx = expenses['amount'].mean()
        big_tx = expenses[expenses['amount'] > (avg_tx * 3)]
        if not big_tx.empty:
            insight += f"• **Deteksi Anomali**: Ada {len(big_tx)} transaksi besar yang di atas rata-rata. Perlu dikontrol?\n"

        # 4. Trend Analysis (vs Last Week)
        last_week = now - timedelta(days=7)
        lw_tx = [t for t in transactions if t.date >= last_week]
        if lw_tx:
            lw_total = sum(t.amount for t in lw_tx if t.type == 'expense')
            daily_avg = lw_total / 7
            insight += f"• **Tren**: Rata-rata pengeluaran harianmu seminggu terakhir adalah Rp{daily_avg:,.0f}.\n"
        
        # 5. Recurring Detection (New Feature)
        recurring = self.detect_recurring_patterns(user_id)
        if recurring:
            rec_names = ", ".join([r['merchant'] for r in recurring[:2]])
            insight += f"• **Langganan Terdeteksi**: Sepertinya kamu punya tagihan rutin di {rec_names}. Mau di-set reminder?\n"

        # 6. Suggestion
        income = self.db.get_latest_income(user_id)
        if income:
            savings_rate = ((income.amount - expenses['amount'].sum()) / income.amount) * 100
            if savings_rate < 10:
                insight += "• **Saran**: Tabunganmu bulan ini di bawah 10%. Coba kurangi kategori non-primer.\n"
            else:
                insight += f"• **Saran**: Kamu sudah menabung {savings_rate:.0f}% gaji. Pertahankan!\n"
        
        return insight

    def generate_monthly_wrapper(self, user_id, month, year):
        """
        Spotify-style monthly summary logic.
        Identifies top category, total spend, saving rate, and persona-based message.
        """
        transactions = self.db.get_monthly_report(user_id, month, year)
        if not transactions:
            return None
            
        df = pd.DataFrame([{
            'amount': t.amount,
            'category': t.category,
            'type': t.type
        } for t in transactions])
        
        expenses = df[df['type'] == 'expense']
        if expenses.empty:
            return None
            
        total_spend = float(expenses['amount'].sum())
        top_cat = expenses.groupby('category')['amount'].sum().idxmax()
        top_cat_amount = float(expenses.groupby('category')['amount'].sum().max())
        
        income_data = self.db.get_latest_income(user_id)
        income_val = float(income_data.amount) if income_data else 0.0
        saving_rate = ((income_val - total_spend) / income_val * 100) if income_val > 0 else 0.0
        
        # User title based on saving rate
        if saving_rate > 30:
            title = "The Saver 🛡️"
        elif saving_rate > 10:
            title = "The Balanced ⚖️"
        elif total_spend > income_val and income_val > 0:
            title = "The Big Spender 💸"
        else:
            title = "The Explorer 🧭"
            
        return {
            "month": month,
            "year": year,
            "total_spend": total_spend,
            "top_category": top_cat,
            "top_category_spend": top_cat_amount,
            "saving_rate": saving_rate,
            "title": title,
            "transaction_count": len(transactions)
        }

    async def get_ai_trend_analysis(self, user_id):
        """
        Premium Trend Analysis using the Elite AI Engine.
        Detects month-over-month changes and hidden patterns.
        """
        from core import premium_ai
        
        # 1. Get transaction history for last 30 days
        transactions = self.db.get_sliding_window_transactions(user_id, days=30)
        
        if not transactions:
            return "Belum ada data transaksi yang cukup untuk analisis tren."

        # 2. Summarize for AI
        summary = {
            "total_count": len(transactions),
            "categories": {},
            "total_amount": 0
        }
        for tx in transactions:
            summary["total_amount"] += tx.amount
            summary["categories"][tx.category] = summary["categories"].get(tx.category, 0) + tx.amount

        # 3. Deep Analysis via Premium AI
        user_context = f"Monthly Summary: {summary}"
        analysis = await premium_ai.process_interaction(
            user_id, 
            "Berikan analisis tren pengeluaran bulanan saya secara mendalam.", 
            "User"
        )
        
        return analysis.predictive_advice or analysis.suggested_response

    async def get_predictive_forecast(self, user_id):
        """
        Engine Prediksi: Memproyeksikan saldo akhir bulan berdasarkan kecepatan belanja saat ini.
        """
        now = datetime.now()
        days_in_month = 30 
        days_passed = max(1, now.day)
        days_remaining = max(0, days_in_month - days_passed)
        
        # 1. Get financial data
        transactions = self.db.get_monthly_report(user_id, now.month, now.year)
        total_expense = sum(t.amount for t in transactions if t.type == 'expense')
        income_data = self.db.get_latest_income(user_id)
        total_income = float(income_data.amount) if income_data else 0
        
        if total_income == 0:
            return None # Can't forecast without income base

        # 2. Calculate Burn Rate (Pengeluaran per hari)
        burn_rate = total_expense / days_passed
        estimated_future_expense = burn_rate * days_remaining
        
        estimated_final_balance = total_income - (total_expense + estimated_future_expense)
        
        # 3. Micro-copy elegant response
        from utils.visuals import format_currency
        balance_str = format_currency(estimated_final_balance)
        
        if estimated_final_balance < 0:
            return f"⚠️ **Forecast**: Dengan pola belanja sekarang, estimasi saldo akhir bulanmu bisa minus {balance_str}. Perlu rem dikit?"
        else:
            return f"📈 **Forecast**: Estimasi saldo akhir bulanmu di angka {balance_str}. Tetap stabil ya!"

    def get_executive_summary(self, user_id):
        """
        Executive Layer Mode: Concise, sharp, data-driven 5-bullet summary.
        """
        try:
            now = datetime.now()
            transactions = self.db.get_monthly_report(user_id, now.month, now.year)
            if not transactions:
                return "Belum ada data eksekutif untuk bulan ini."

            df = pd.DataFrame([{
                'amount': t.amount,
                'category': t.category,
                'type': t.type
            } for t in transactions])

            expenses = df[df['type'] == 'expense']
            incomes = df[df['type'] == 'income']
            
            total_spend = expenses['amount'].sum()
            total_income = incomes['amount'].sum()
            
            from utils.visuals import format_currency
            
            # 1. Total Spend
            bullet_1 = f"• **Total Spend**: {format_currency(total_spend)}"
            
            # 2. Top Category
            if not expenses.empty:
                top_cat = expenses.groupby('category')['amount'].sum().idxmax()
                bullet_2 = f"• **Top Category**: {top_cat}"
            else:
                bullet_2 = "• **Top Category**: N/A"

            # 3. Deviation (vs last month avg)
            # Simplified: deviation is spend vs income ratio
            ratio = (total_spend / total_income * 100) if total_income > 0 else 0
            bullet_3 = f"• **Deviation**: Spend is {ratio:.1f}% of income"

            # 4. Risk Level
            risk = "Low"
            if ratio > 80: risk = "High"
            elif ratio > 50: risk = "Medium"
            bullet_4 = f"• **Risk Level**: {risk}"

            # 5. Action Suggestion
            if risk == "High":
                action = "Cut non-essential spending immediately."
            elif ratio > 30:
                action = "Monitor lifestyle expenses."
            else:
                action = "Healthy status. Consider increasing investments."
            bullet_5 = f"• **Action**: {action}"

            return (
                "👔 **Executive Summary**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"{bullet_1}\n"
                f"{bullet_2}\n"
                f"{bullet_3}\n"
                f"{bullet_4}\n"
                f"{bullet_5}\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )
        except Exception as e:
            logger.error(f"Error generating executive summary: {e}")
            return "Gagal menghasilkan ringkasan eksekutif."

    def get_wealth_narrative(self, user_id):
        """
        Long-Term Wealth Narrative: Growth story over 6 months.
        """
        try:
            now = datetime.now()
            # Simplified: aggregate savings over last 6 months
            history = []
            for i in range(6):
                month_date = now - timedelta(days=30 * i)
                txs = self.db.get_monthly_report(user_id, month_date.month, month_date.year)
                if txs:
                    income = sum(t.amount for t in txs if t.type == 'income')
                    expense = sum(t.amount for t in txs if t.type == 'expense')
                    history.append(income - expense)
            
            if len(history) < 2:
                return "Butuh data lebih dari 1 bulan untuk melihat narasi pertumbuhanmu."
                
            # Calculate growth rate
            history.reverse() # Oldest to newest
            first_savings = history[0]
            last_savings = history[-1]
            
            if first_savings > 0:
                growth = ((last_savings - first_savings) / first_savings) * 100
            else:
                growth = 0
                
            from utils.visuals import format_currency
            
            if growth > 0:
                return f"📈 **Wealth Progress**: Dalam 6 bulan terakhir, tabungan kamu naik konsisten. Growth **{growth:.1f}%**. Kamu sedang membangun masa depan yang solid!"
            elif growth < 0:
                return f"📉 **Wealth Note**: Ada penurunan tren tabungan sebesar **{abs(growth):.1f}%** dalam 6 bulan terakhir. Mari kita evaluasi alokasi budgetmu."
            else:
                return "🔄 **Wealth Status**: Tabunganmu cenderung stabil. Mau coba strategi investasi baru untuk memicu pertumbuhan?"
                
        except Exception as e:
            logger.error(f"Error generating wealth narrative: {e}")
            return ""

    def calculate_financial_score(self, user_id):
        """
        Internal Financial Health Score: 0-100.
        Based on Discipline, Consistency, and Budget Adherence.
        """
        try:
            now = datetime.now()
            transactions = self.db.get_monthly_report(user_id, now.month, now.year)
            if not transactions: return 70 # Default base
            
            # 1. Budget Adherence (40 pts)
            budgets = self.db.get_user_budgets(user_id)
            if not budgets:
                adherence_score = 30 # Mid score if no budget set
            else:
                over_budget_count = len([b for b in budgets if b.current_usage > b.limit_amount])
                adherence_score = max(0, 40 - (over_budget_count * 10))
            
            # 2. Spending Consistency (30 pts)
            # Higher score if daily spending is stable vs massive spikes
            df = pd.DataFrame([{'amount': t.amount, 'day': t.date.day} for t in transactions if t.type == 'expense'])
            if df.empty:
                consistency_score = 30
            else:
                daily_sums = df.groupby('day')['amount'].sum()
                cv = daily_sums.std() / daily_sums.mean() if daily_sums.mean() > 0 else 0
                consistency_score = max(0, 30 - (cv * 10))
                
            # 3. Savings Rate (30 pts)
            income_data = self.db.get_latest_income(user_id)
            total_income = float(income_data.amount) if income_data else 0
            total_expense = df['amount'].sum() if not df.empty else 0
            
            if total_income > 0:
                savings_rate = (total_income - total_expense) / total_income
                savings_score = min(30, max(0, savings_rate * 100))
            else:
                savings_score = 15 # Neutral
                
            total_score = int(adherence_score + consistency_score + savings_score)
            status = "stabil" if total_score > 70 else "perlu perhatian"
            if total_score > 85: status = "sangat baik"
            
            return {
                "score": total_score,
                "status": status,
                "breakdown": {
                    "adherence": int(adherence_score),
                    "consistency": int(consistency_score),
                    "savings": int(savings_score)
                }
            }
        except Exception as e:
            logger.error(f"Error calculating financial score: {e}")
            return {"score": 70, "status": "stabil"}
        projected_expense = total_expense + (burn_rate * days_remaining)
        
        # 3. Compare with Income
        income = self.db.get_latest_income(user_id)
        total_income = income.amount if income else 0
        
        projected_balance = total_income - projected_expense
        
        # 4. Generate Elite AI Insight about this forecast
        from core import premium_ai
        analysis = await premium_ai.process_interaction(
            user_id, 
            f"Proyeksi pengeluaranku bulan ini Rp{projected_expense:,.0f} dengan sisa saldo Rp{projected_balance:,.0f}. Apa sarannya?", 
            "User"
        )
        
        return {
            "burn_rate": burn_rate,
            "projected_expense": projected_expense,
            "projected_balance": projected_balance,
            "ai_advice": analysis.suggested_response
        }

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

    def detect_budget_drift(self, user_id):
        """
        Early Warning System: Mendeteksi jika kecepatan belanja terlalu tinggi (Budget Drift).
        Returns list of warnings strings.
        """
        try:
            now = datetime.now()
            days_in_month = 30 # Approximation
            days_passed = now.day
            
            # Expected usage % (Linear projection)
            expected_pct = (days_passed / days_in_month) * 100
            
            # Allow 15% buffer before alerting (e.g. on day 15 (50%), alert if usage > 65%)
            threshold_buffer = 15 
            
            budgets = self.db.get_user_budgets(user_id)
            alerts = []
            
            for b in budgets:
                if b.limit_amount <= 0: continue
                
                usage_pct = (b.current_usage / b.limit_amount) * 100
                drift = usage_pct - expected_pct
                
                if drift > threshold_buffer:
                    # Severity check
                    severity = "⚠️" if drift < 25 else "🚨"
                    
                    alerts.append(
                        f"{severity} **{b.category}**: Terpakai {usage_pct:.0f}% (Padahal baru tanggal {days_passed}). "
                        f"Biasanya di tanggal ini cuma {expected_pct:.0f}%."
                    )
            
            return alerts
            
        except Exception as e:
            logger.error(f"Error detecting budget drift: {e}")
            return []

