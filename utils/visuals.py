import matplotlib.pyplot as plt
import io
import pandas as pd
from datetime import datetime

def generate_monthly_chart(transactions, title="Laporan Bulanan"):
    """
    Generate beautiful chart for monthly report.
    Returns: BytesIO object containing the image.
    """
    if not transactions:
        return None
        
    # Prepare Data
    df = pd.DataFrame([{
        'category': t.category,
        'amount': t.amount,
        'type': t.type
    } for t in transactions if t.type == 'expense'])
    
    if df.empty:
        return None
        
    summary = df.groupby('category')['amount'].sum().sort_values(ascending=False)
    
    # Setup Plot
    plt.figure(figsize=(10, 6), dpi=100)
    plt.style.use('dark_background')
    
    # Donut Chart
    colors = plt.cm.Set3(range(len(summary)))
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
    
    plt.title(f"{title}\nTotal: Rp {summary.sum():,.0f}", fontsize=14, color='white', pad=20)
    plt.tight_layout()
    
    # Save to Bytes
    buf = io.BytesIO()
    plt.savefig(buf, format='png', transparent=True)
    buf.seek(0)
    plt.close()
    
    return buf
