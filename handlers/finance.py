from telegram import Update
from telegram.ext import ContextTypes
from core import db, analyzer, ai
from utils.dashboard import update_pinned_dashboard
import logging

async def set_gaji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db: return

    if not context.args:
        await update.message.reply_text("Cara pakai: `/setgaji [Nominal]`\nContoh: `/setgaji 5000000` atau `/setgaji 5jt`", parse_mode='Markdown')
        return

    try:
        amount_str = context.args[0].lower().replace('.', '').replace(',', '')
        if 'rb' in amount_str:
            amount = float(amount_str.replace('rb', '')) * 1000
        elif 'jt' in amount_str:
            amount = float(amount_str.replace('jt', '')) * 1000000
        else:
            amount = float(amount_str)
            
        db.add_monthly_income(user_db.id, amount)
        await update.message.reply_text(f"✅ Pendapatan bulanan berhasil diatur ke Rp{amount:,.0f}. Semangat mengelola uangnya! 💪", parse_mode='Markdown')
        await update_pinned_dashboard(update, context)
    except ValueError:
        await update.message.reply_text("Format nominal salah. Gunakan angka saja.")

async def set_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db: return

    if len(context.args) < 2:
        await update.message.reply_text("Cara pakai: `/setbudget [Kategori] [Nominal]`\nContoh: `/setbudget Makanan 1000000`", parse_mode='Markdown')
        return

    category = context.args[0].capitalize()
    try:
        amount_str = context.args[1].lower().replace('.', '').replace(',', '')
        if 'rb' in amount_str:
            amount = float(amount_str.replace('rb', '')) * 1000
        elif 'jt' in amount_str:
            amount = float(amount_str.replace('jt', '')) * 1000000
        else:
            amount = float(amount_str)
            
        db.set_budget(user_db.id, category, amount)
        
        # Invalidate budget cache if any
        from core import budget_mgr
        # Note: BudgetManager doesn't have explicit cache invalidation method exposed, 
        # but DB handler updates should be sufficient. 
        # Ideally: budget_mgr.invalidate_cache(user_id)
        
        await update.message.reply_text(f"✅ Budget {category} berhasil diatur ke Rp {amount:,.0f} per bulan.")
        await update_pinned_dashboard(update, context)
    except ValueError:
        await update.message.reply_text("Format nominal salah. Gunakan angka saja.")

async def get_ai_insight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db: return
    
    target = update.callback_query.message if update.callback_query else update.message
    processing_msg = await target.reply_text("🤖 Sedang menganalisis keuanganmu...", parse_mode='Markdown')

    try:
        raw_insight = analyzer.analyze_patterns(user_db.id)
        ai_insight = await ai.generate_smart_insight(raw_insight)
        
        await processing_msg.edit_text(f"🤖 **FINBOT AI ADVISOR**\n\n{ai_insight}", parse_mode='Markdown')
    except Exception as e:
        logging.error(f"Error generating AI insight for {user_id}: {e}", exc_info=True)
        await processing_msg.edit_text("Maaf, gagal membuat analisis AI. Coba lagi nanti ya! 🙏")

async def set_budget_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Configure alert thresholds for a budget category.
    Usage: /budgetalert [Kategori] [warn%] [limit%]
    """
    user_id = update.effective_user.id
    user_db = db.get_user(user_id)
    if not user_db: return
    if len(context.args) < 3:
        await update.message.reply_text("Cara pakai: `/budgetalert [Kategori] [warn%] [limit%]`\nContoh: `/budgetalert Makanan 80 100`", parse_mode='Markdown')
        return
    category = context.args[0].capitalize()
    try:
        warn = float(context.args[1]) / 100.0
        limit = float(context.args[2]) / 100.0
        db.set_budget_threshold(user_db.id, category, warn, limit)
        await update.message.reply_text(f"✅ Alert {category} diatur: Warning {warn*100:.0f}% • Limit {limit*100:.0f}%")
    except Exception as e:
        await update.message.reply_text(f"Gagal mengatur alert: {e}")

async def what_if_simulator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Simulate financial decisions.
    Usage: /whatif [amount] [description]
    Example: /whatif 2000000 cicil hp
    """
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "🔮 **What-If Simulator**\n"
            "Cek dampak keputusan finansialmu sebelum kejadian.\n\n"
            "Contoh:\n"
            "`/whatif 2jt cicilan hp`\n"
            "`/whatif 500rb langganan gym`",
            parse_mode='Markdown'
        )
        return

    try:
        # Parse Amount
        from modules.amounts import parse_primary_amount_id
        raw_amount = args[0]
        amount = parse_primary_amount_id(raw_amount)
        if not amount:
            await update.message.reply_text("Nominalnya berapa? Contoh: 2jt")
            return
            
        desc = " ".join(args[1:])
        
        # Get Current Financial State
        from core import db
        now = datetime.now()
        
        # 1. Get Monthly Income & Expenses
        txs = db.get_monthly_report(user_id, now.month, now.year)
        income = sum(t.amount for t in txs if t.type == 'income')
        expense = sum(t.amount for t in txs if t.type == 'expense')
        
        # 2. Get Savings
        goals = db.get_user_saving_goals(user_id)
        savings = sum(g.current_amount for g in goals)
        
        # 3. AI Prediction
        prompt = f"""
        Analyze this financial decision for user {user_name}.
        Current Monthly Income: Rp {income:,.0f}
        Current Monthly Expense: Rp {expense:,.0f}
        Current Savings: Rp {savings:,.0f}
        
        Proposed Expense: Rp {amount:,.0f} for "{desc}"
        
        Task:
        1. Calculate projected cashflow if this expense happens.
        2. Give a risk rating (Safe/Risky/Dangerous).
        3. Provide specific advice.
        
        Output format:
        Analysis: [Analysis]
        Verdict: [Safe/Risky/Dangerous]
        Advice: [Advice]
        """
        
        from core import premium_ai
        from core import visual_reporter
        from datetime import datetime

        processing = await update.message.reply_text("🔮 **Meramal masa depan dompetmu...**", parse_mode='Markdown')
        
        # Determine Scenario Type (Recurring vs One-time)
        is_recurring = any(w in desc.lower() for w in ["cicil", "langganan", "bulan", "rutin"])
        duration = 12 if is_recurring else 1
        
        # Generate Projection Chart
        # Use simple heuristics for projection: Average income/expense
        # In production, this should be more sophisticated (e.g. taking recurring txs into account)
        current_balance = savings + (income - expense)
        
        # Assuming monthly income and expense stays roughly same as this month
        # This is a simplification for the "What-If" visual
        chart = visual_reporter.generate_cashflow_projection(
            current_balance=current_balance,
            monthly_income=income,
            monthly_expense=expense,
            scenario_expense=amount if is_recurring else (amount / 12), # If one-time, impact is immediate but we visualize monthly flow? 
                                                                         # Actually, for one-time, it just drops the balance once.
                                                                         # For recurring, it drops every month.
            scenario_duration_months=12,
            scenario_name=desc
        )
        
        # Correction for one-time expense in projection logic above:
        # The visual reporter logic I wrote: curr_scen += (monthly_income - monthly_expense - scenario_expense)
        # This implies scenario_expense happens EVERY month.
        # So if it's NOT recurring, we should pass 0 for subsequent months? 
        # The current visual_reporter logic assumes constant scenario expense.
        # Let's keep it simple: If one-time, we treat it as recurring for 1 month? No, VisualReporter loops 12 times.
        # Refactor VisualReporter call logic slightly? 
        # Actually, for "cicilan", it IS recurring.
        # For "beli hp cash", it is NOT.
        # Let's handle this by passing the right 'monthly' impact.
        
        # If one-time purchase:
        # We can't easily use the simple loop in VisualReporter for one-time drop at month 1.
        # BUT, users mostly ask about "cicilan" or "subscription" in this context.
        # Let's assume user intent for "What If" often involves cashflow impact over time.
        # If one-time, let's just warn about immediate drop.
        
        analysis = await premium_ai._call_llm(
            system_prompt="You are a financial risk analyst. Be realistic and direct.",
            user_prompt=prompt
        )
        
        await processing.delete()
        
        caption = f"🔮 **Hasil Simulasi: {desc}**\n\n{analysis}"
        
        if chart and is_recurring:
            await update.message.reply_photo(photo=chart, caption=caption, parse_mode='Markdown')
        else:
            await update.message.reply_text(caption, parse_mode='Markdown')
            
    except Exception as e:
        logging.error(f"What-if error: {e}")
        await update.message.reply_text("Gagal melakukan simulasi. Coba lagi nanti.")

