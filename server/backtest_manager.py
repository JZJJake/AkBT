
import asyncio
import pandas as pd
import numpy as np
from server.data.provider import provider
from server.engine import BacktestEngine
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

class BacktestManager:
    """
    Manages the batch backtesting task.
    """
    def __init__(self):
        self.status = "idle"
        self.progress = 0
        self.processed_count = 0
        self.total_stocks = 0
        self.message = ""
        self.results = {} # { "equity_curve": [...], "stats": {...} }
        self._cancel_flag = False

    def reset(self):
        self.status = "idle"
        self.progress = 0
        self.processed_count = 0
        self.total_stocks = 0
        self.message = ""
        self.results = {}
        self._cancel_flag = False

    async def run_batch_task(self):
        if self.status == "running": return

        self.reset()
        self.status = "running"
        self.message = "Initializing Batch Backtest..."

        try:
            # 1. Get Stock List
            conn = provider.db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT code FROM stock_daily_qfq")
            rows = cursor.fetchall()
            stock_list = [r[0] for r in rows]
            conn.close()

            if not stock_list:
                self.message = "No data in DB."
                self.status = "error"
                return

            self.total_stocks = len(stock_list)
            self.message = f"Backtesting {self.total_stocks} stocks..."

            # 2. Storage for Aggregation
            # We store daily returns to calculate an Equal-Weighted Index
            # Key: Date (str), Value: List of returns (float)
            daily_returns_map = defaultdict(list)

            trade_counts = []
            final_returns = []

            # 3. Process
            # Use small batch to allow async yield
            # For backtest, run() is CPU heavy.
            # We'll run strictly serial or small chunks to avoid memory explosion.
            # Loading full history for 5000 stocks is heavy.

            for i, code in enumerate(stock_list):
                if self._cancel_flag: break

                self.processed_count = i + 1
                self.progress = int((self.processed_count / self.total_stocks) * 100)

                if i % 10 == 0:
                    await asyncio.sleep(0.01) # Yield

                try:
                    # Load Full History
                    df = provider.db_manager.get_stock_data(code) # No limit
                    if df.empty or len(df) < 50: continue

                    engine = BacktestEngine(df)
                    # Run Strategy
                    res = await engine.run()

                    # Process Result
                    curve = res['equity_curve'] # [{date, value}, ...]
                    trades = res['trades']

                    if not curve: continue

                    trade_counts.append(len(trades))

                    # Calculate Daily Returns for this stock
                    # Value[t] / Value[t-1] - 1
                    # Curve is list of dicts.
                    # Convert to efficient structure?
                    # Optimization: Just iterate list.

                    prev_val = 100000.0 # Initial cash default

                    total_ret = (curve[-1]['value'] - prev_val) / prev_val
                    final_returns.append(total_ret)

                    for item in curve:
                        d = item['date']
                        val = item['value']
                        ret = (val - prev_val) / prev_val
                        if abs(ret) > 0.000001: # Only record non-zero? No, record all for correct average?
                            # Actually we need period return: val[t] / val[t-1] - 1
                            pass

                        period_ret = (val / prev_val) - 1
                        daily_returns_map[d].append(period_ret)

                        prev_val = val

                except Exception as e:
                    logger.error(f"Error backtesting {code}: {e}")
                    continue

            # 4. Aggregation
            self.message = "Aggregating results..."

            # Sort dates
            all_dates = sorted(daily_returns_map.keys())

            aggregated_curve = []
            current_index = 1.0

            for d in all_dates:
                rets = daily_returns_map[d]
                if not rets: continue

                avg_ret = sum(rets) / len(rets)
                current_index *= (1 + avg_ret)

                aggregated_curve.append({
                    "date": d,
                    "value": current_index
                })

            # Stats
            avg_final_return = sum(final_returns) / len(final_returns) if final_returns else 0
            avg_trades = sum(trade_counts) / len(trade_counts) if trade_counts else 0
            win_stocks = len([r for r in final_returns if r > 0])
            win_rate_stocks = win_stocks / len(final_returns) if final_returns else 0

            self.results = {
                "equity_curve": aggregated_curve,
                "stats": {
                    "total_stocks_tested": len(final_returns),
                    "avg_return": f"{avg_final_return*100:.2f}%",
                    "avg_trades": f"{avg_trades:.1f}",
                    "win_rate": f"{win_rate_stocks*100:.2f}%"
                }
            }

            self.status = "completed"
            self.message = "Batch Backtest Completed."

        except Exception as e:
            self.status = "error"
            self.message = str(e)
            logger.error(f"Batch backtest failed: {e}")

# Global Instance
backtest_manager = BacktestManager()
