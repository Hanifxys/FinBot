import tkinter as tk
from tkinter import ttk, messagebox
import asyncio
import websockets
import json
import threading
import os
from datetime import datetime

class FinBotLiveDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("🚀 FinBot Pro - Real-time Desktop Monitor")
        self.root.geometry("500x400")
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
        header = ttk.Label(self.root, text="LIVE TRANSACTION FEED", style="Header.TLabel")
        header.pack(pady=20)

        # Connection Status
        self.status_label = ttk.Label(self.root, text="Status: Disconnected", foreground="orange")
        self.status_label.pack()

        # Feed Container
        self.feed_frame = tk.Canvas(self.root, bg="#1e1e1e", highlightthickness=0)
        self.feed_scroll = ttk.Scrollbar(self.root, orient="vertical", command=self.feed_frame.yview)
        self.scrollable_frame = ttk.Frame(self.feed_frame, style="Card.TFrame")

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.feed_frame.configure(scrollregion=self.feed_frame.bbox("all"))
        )

        self.feed_frame.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.feed_frame.configure(yscrollcommand=self.feed_scroll.set)

        self.feed_frame.pack(side="left", fill="both", expand=True, padx=20, pady=10)
        self.feed_scroll.pack(side="right", fill="y")

    def add_feed_item(self, data):
        """Tambah item baru ke daftar secara real-time"""
        amount = data.get('amount', 0)
        category = data.get('category', 'Lain-lain')
        desc = data.get('description', '-')
        time_str = datetime.now().strftime("%H:%M:%S")

        color = "#ff4444" if data.get('type') == 'expense' else "#00ff88"
        prefix = "💸" if data.get('type') == 'expense' else "💰"

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
                self.status_label.config(text=f"Connecting to {self.ws_url}...", foreground="yellow")
                async with websockets.connect(self.ws_url) as websocket:
                    self.status_label.config(text="● Connected (Live)", foreground="#00ff88")
                    while True:
                        message = await websocket.recv()
                        payload = json.loads(message)
                        if payload.get("event") == "new_transaction":
                            self.root.after(0, self.add_feed_item, payload.get("data"))
            except Exception as e:
                self.status_label.config(text=f"Status: Reconnecting...", foreground="red")
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
