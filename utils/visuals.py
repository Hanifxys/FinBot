import matplotlib.pyplot as plt
import pandas as pd
import os

class VisualReporter:
    def __init__(self, output_dir="temp_reports"):
        self.output_dir = output_dir
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

    def generate_expense_pie(self, transactions, user_id):
        """
        Generates a pie chart of expenses by category.
        """
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

        category_data = expenses.groupby('category')['amount'].sum()
        
        plt.figure(figsize=(10, 6))
        category_data.plot(kind='pie', autopct='%1.1f%%', startangle=140, colors=plt.cm.Paired.colors)
        plt.title('Proporsi Pengeluaran per Kategori')
        plt.ylabel('')
        
        file_path = os.path.join(self.output_dir, f"report_{user_id}.png")
        plt.savefig(file_path)
        plt.close()
        
        return file_path
