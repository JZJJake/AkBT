import asyncio
import pandas as pd
from server.data.provider import provider
from server.engine import BacktestEngine
from server.data.stock_list_provider import fetch_stock_list
import logging

logger = logging.getLogger(__name__)

class ScreenerManager:
    """
    Manages the long-running stock screening task.
    """
    def __init__(self):
        self.status = "idle" # idle, running, completed, error
        self.progress = 0
        self.current_stock = ""
        self.total_stocks = 0
        self.processed_count = 0
        self.found_stocks = [] # List of dicts
        self.message = ""

    def reset(self):
        self.status = "idle"
        self.progress = 0
        self.current_stock = ""
        self.total_stocks = 0
        self.processed_count = 0
        self.found_stocks = []
        self.message = ""

    async def run_task(self):
        if self.status == "running": return

        self.reset()
        self.status = "running"
        self.message = "Initializing..."

        try:
            # 1. Get Stock List from DB first (faster), fallback to provider
            conn = provider.db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT code FROM stock_daily_qfq")
            rows = cursor.fetchall()
            stock_list = [r[0] for r in rows]
            conn.close()

            if not stock_list:
                self.message = "No data in DB. Please sync first."
                self.status = "error"
                return

            self.total_stocks = len(stock_list)
            self.message = f"Scanning {self.total_stocks} stocks..."

            # 2. Iterate
            # Process in small batches to yield control
            batch_size = 50

            for i, code in enumerate(stock_list):
                self.current_stock = code
                self.processed_count = i + 1
                self.progress = int((self.processed_count / self.total_stocks) * 100)

                if i % 10 == 0:
                    await asyncio.sleep(0.01) # Yield

                try:
                    # Optimized Check: Only load recent data needed for indicators
                    # Need enough bars for Monthly MACD stability (~600 days = 30 months)
                    df = provider.db_manager.get_stock_data(code, limit=600)

                    if df.empty or len(df) < 50: continue

                    engine = BacktestEngine(df)
                    # Use the FAST check method (to be implemented)
                    is_buy = engine.check_signal_now()

                    if is_buy:
                        last_row = df.iloc[-1]
                        name = provider.db_manager.get_stock_name(code)
                        self.found_stocks.append({
                            "code": code,
                            "name": name,
                            "date": str(last_row.name).split(' ')[0],
                            "price": last_row['Close']
                        })

                except Exception as e:
                    logger.error(f"Error screening {code}: {e}")
                    continue

            self.status = "completed"
            self.message = f"Scan complete. Found {len(self.found_stocks)} stocks."

        except Exception as e:
            self.status = "error"
            self.message = str(e)
            logger.error(f"Screener task failed: {e}")

# Global Instance
screener_manager = ScreenerManager()
