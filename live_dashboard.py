import tkinter as tk
from tkinter import ttk, messagebox
import asyncio
import websockets
import json
import threading
import os
from datetime import datetime

class FinBotLiveDashboard:
    def __init__(self, root, user_id=None):
        self.root = root
        self.user_id = user_id or os.getenv("USER_ID", "default_user")
        self.root.title(f"🚀 FinBot Pro - User {self.user_id}")
        self.root.geometry("600x500")
        self.root.configure(bg="#1e1e1e")

        # Styling
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("TLabel", background="#1e1e1e", foreground="white", font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"), foreground="#00ff88")
        self.style.configure("Card.TFrame", background="#2d2d2d", relief="flat")

        # UI Components
        self.setup_ui()

        # Data
        self.transactions = []

        # Start WebSocket Thread
        self.ws_url = os.getenv("WS_URL", "ws://localhost:8001")
        self.start_ws_thread()

    def setup_ui(self):
        # Header
        header = ttk.Label(self.root, text="🚀 FINBOT PRO LIVE", style="Header.TLabel")
        header.pack(pady=10)

        # Tab Control (New!)
        self.tab_control = ttk.Notebook(self.root)
        
        self.feed_tab = ttk.Frame(self.tab_control)
        self.insight_tab = ttk.Frame(self.tab_control)
        
        self.tab_control.add(self.feed_tab, text="Live Feed")
        self.tab_control.add(self.insight_tab, text="Smart Analysis")
        self.tab_control.pack(expand=1, fill="both")

        # --- Feed Tab ---
        # AI Suggestion Box
        self.ai_frame = tk.Frame(self.feed_tab, bg="#3d3d5c", padx=10, pady=10)
        self.ai_frame.pack(fill="x", padx=20, pady=5)
        self.ai_label = tk.Label(self.ai_frame, text="AI: Menunggu input...", bg="#3d3d5c", fg="#00ff88", font=("Segoe UI", 9, "italic"), wraplength=450, justify="left")
        self.ai_label.pack(fill="x")

        # Feed Container
        self.feed_frame = tk.Canvas(self.feed_tab, bg="#1e1e1e", highlightthickness=0)
        self.feed_scroll = ttk.Scrollbar(self.feed_tab, orient="vertical", command=self.feed_frame.yview)
        self.scrollable_frame = ttk.Frame(self.feed_frame, style="Card.TFrame")
        self.feed_frame.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.feed_frame.configure(yscrollcommand=self.feed_scroll.set)
        self.feed_frame.pack(side="left", fill="both", expand=True, padx=20, pady=10)
        self.feed_scroll.pack(side="right", fill="y")

        # --- Insight Tab ---
        self.forecast_label = tk.Label(self.insight_tab, text="📊 Proyeksi Saldo Akhir Bulan", font=("Segoe UI", 12, "bold"))
        self.forecast_label.pack(pady=20)
        self.forecast_val = tk.Label(self.insight_tab, text="Rp --", font=("Segoe UI", 20), fg="#00ff88")
        self.forecast_val.pack()
        
        self.burn_label = tk.Label(self.insight_tab, text="Burn Rate: Rp 0/hari", font=("Segoe UI", 10))
        self.burn_label.pack(pady=10)

        # Connection Status
        self.status_label = ttk.Label(self.root, text="Status: Disconnected", foreground="orange")
        self.status_label.pack(side="bottom")

    def update_ai_suggestion(self, data):
        """Update kotak saran AI dan stats gamifikasi secara real-time"""
        text = data.get("response")
        self.ai_label.config(text=f"AI: {text}")
        
        # [NEW] Update Gamification Stats
        gamify_data = data.get("gamify", {})
        if gamify_data:
            self.status_label.config(
                text=f"● Live (User: {self.user_id}) | Level: {gamify_data.get('level')} (XP: {gamify_data.get('total_xp')})",
                foreground="#00ff88"
            )
            if gamify_data.get("leveled_up"):
                messagebox.showinfo("LEVELED UP! 🚀", f"Selamat! Kamu naik ke Level {gamify_data.get('level')}!")

        # Efek visual kilat saat ada update
        self.ai_frame.config(bg="#4d4d7c")
        self.root.after(200, lambda: self.ai_frame.config(bg="#3d3d5c"))

    def update_summary(self, amount, type_):
        """Update statistik ringkasan secara real-time"""
        if not hasattr(self, 'total_expense'):
            self.total_expense = 0
            self.total_income = 0
            
        if type_ == 'expense':
            self.total_expense += amount
        else:
            self.total_income += amount
            
        self.total_expense_label.config(text=f"Expense: Rp {self.total_expense:,.0f}")
        self.total_income_label.config(text=f"Income: Rp {self.total_income:,.0f}")

    def add_feed_item(self, data):
        """Tambah item baru ke daftar secara real-time"""
        amount = data.get('amount', 0)
        type_ = data.get('type', 'expense')
        self.update_summary(amount, type_)
        
        category = data.get('category', 'Lain-lain')
        desc = data.get('description', '-')
        time_str = datetime.now().strftime("%H:%M:%S")

        color = "#ff4444" if type_ == 'expense' else "#00ff88"
        prefix = "💸" if type_ == 'expense' else "💰"

        card = tk.Frame(self.scrollable_frame, bg="#333333", padx=10, pady=10, highlightbackground="#444444", highlightthickness=1)
        card.pack(fill="x", pady=5, padx=5)

        tk.Label(card, text=f"{prefix} Rp {amount:,.0f}", bg="#333333", fg=color, font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Label(card, text=f" | {category} | {desc}", bg="#333333", fg="white").pack(side="left")
        tk.Label(card, text=time_str, bg="#333333", fg="#888888", font=("Segoe UI", 8)).pack(side="right")

        # Auto scroll to bottom
        self.root.after(100, lambda: self.feed_frame.yview_moveto(1.0))

    async def ws_listener(self):
        while True:
            try:
                self.status_label.config(text=f"Connecting...", foreground="yellow")
                async with websockets.connect(self.ws_url) as websocket:
                    # Authenticate/Register User ID
                    await websocket.send(json.dumps({"user_id": self.user_id}))
                    
                    self.status_label.config(text=f"● Live (User: {self.user_id})", foreground="#00ff88")
                    while True:
                        message = await websocket.recv()
                        payload = json.loads(message)
                        event = payload.get("event")
                        data = payload.get("data")
                        
                        if event == "new_transaction":
                            self.root.after(0, self.add_feed_item, data)
                        elif event == "premium_ai_insight":
                            self.root.after(0, self.update_ai_suggestion, data.get("response"))
            except Exception:
                self.status_label.config(text=f"Reconnecting...", foreground="red")
                await asyncio.sleep(5)

    def start_ws_thread(self):
        def run_async():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.ws_listener())
        
        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()

if __name__ == "__main__":
    root = tk.Tk()
    app = FinBotLiveDashboard(root)
    root.mainloop()
