import matplotlib
matplotlib.use('Agg')  # Set backend to non-interactive Agg
import matplotlib.pyplot as plt
import matplotlib.ticker
import io
import pandas as pd
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class VisualReporter:
    """
    Handles generation of visual reports (charts, graphs) for financial data.
    """
    def __init__(self):
        pass

    def generate_monthly_chart(self, transactions, title="Laporan Bulanan"):
        """
        Generate beautiful chart for monthly report.
        Returns: BytesIO object containing the image.
        """
        if not transactions:
            return None
            
        try:
            # Prepare Data
            data = []
            for t in transactions:
                # Handle both object attributes and dictionary access if necessary
                t_type = getattr(t, 'type', None)
                if t_type == 'expense':
                    data.append({
                        'category': getattr(t, 'category', 'Uncategorized'),
                        'amount': float(getattr(t, 'amount', 0))
                    })
            
            if not data:
                return None

            df = pd.DataFrame(data)
            
            if df.empty:
                return None
                
            summary = df.groupby('category')['amount'].sum().sort_values(ascending=False)
            
            # Setup Plot
            plt.figure(figsize=(10, 6), dpi=100)
            try:
                plt.style.use('dark_background')
            except Exception:
                pass # Fallback to default style
            
            # Donut Chart
            # Handle color map dynamically based on number of categories
            colors = plt.cm.Set3(range(len(summary))) if len(summary) > 0 else []
            
            wedges, texts, autotexts = plt.pie(
                summary, 
                labels=summary.index,
                autopct='%1.1f%%',
                startangle=140,
                colors=colors,
                pctdistance=0.85,
                textprops=dict(color="w")
            )
            
            # Draw Circle for Donut
            centre_circle = plt.Circle((0,0),0.70,fc='#1e1e1e')
            fig = plt.gcf()
            fig.gca().add_artist(centre_circle)
            
            total = summary.sum()
            plt.title(f"{title}\nTotal: Rp {total:,.0f}", fontsize=14, color='white', pad=20)
            plt.tight_layout()
            
            # Save to Bytes
            buf = io.BytesIO()
            plt.savefig(buf, format='png', transparent=True)
            buf.seek(0)
            plt.close()
            
            return buf
            
        except Exception as e:
            logger.error(f"Error generating chart: {e}")
            return None

    def generate_cashflow_projection(self, current_balance, monthly_income, monthly_expense, scenario_expense, scenario_duration_months=12, scenario_name="Scenario"):
        """
        Generate visual cashflow projection chart.
        """
        try:
            months = list(range(1, scenario_duration_months + 1))
            
            baseline = []
            scenario = []
            
            curr_base = current_balance
            curr_scen = current_balance
            
            for m in months:
                # Baseline: Income - Expense
                curr_base += (monthly_income - monthly_expense)
                baseline.append(curr_base)
                
                # Scenario: Income - Expense - Scenario
                curr_scen += (monthly_income - monthly_expense - scenario_expense)
                scenario.append(curr_scen)
                
            # Setup Plot
            plt.figure(figsize=(10, 6), dpi=100)
            try:
                plt.style.use('dark_background')
            except Exception:
                pass
            
            # Plot Lines
            plt.plot(months, baseline, label='Baseline (Tanpa Beli)', color='#4CAF50', linestyle='--', linewidth=2)
            plt.plot(months, scenario, label=f'Dengan {scenario_name}', color='#F44336', linewidth=2)
            
            # Fill area below zero
            plt.fill_between(months, scenario, 0, where=[s < 0 for s in scenario], color='red', alpha=0.3, label='Saldo Negatif')
            
            # Add Zero Line
            plt.axhline(0, color='gray', linestyle=':', linewidth=1)
            
            plt.title(f"Proyeksi Cashflow 12 Bulan: {scenario_name}", fontsize=14, color='white', pad=20)
            plt.xlabel("Bulan ke-", color='white')
            plt.ylabel("Saldo (Rp)", color='white')
            plt.grid(True, linestyle=':', alpha=0.3)
            plt.legend()
            
            # Format Y-axis to Rupiah (M/K)
            def rupiah_fmt(x, pos):
                if abs(x) >= 1e6:
                    return f'{x*1e-6:,.1f}jt'
                elif abs(x) >= 1e3:
                    return f'{x*1e-3:,.0f}rb'
                return f'{x:,.0f}'
                
            plt.gca().yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(rupiah_fmt))
            
            plt.tight_layout()
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png', transparent=True)
            buf.seek(0)
            plt.close()
            
            return buf
            
        except Exception as e:
            logger.error(f"Error generating projection: {e}")
            return None

