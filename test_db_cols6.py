import pandas as pd
from server.data.db_manager import DatabaseManager

db = DatabaseManager('market_data.db')
df = db.get_stock_data('000001')
from server.engine import BacktestEngine
import asyncio
engine = BacktestEngine(df)

async def test():
    # Calling calculate_indicators twice in check_signal_now vs run
    e = BacktestEngine(df.head(100))
    res = await e.run()

    # Simulate API call: e.run()
    # It seems in main.py, we call run() and it fails with ValueError: DataFrame columns must be unique for orient='index'.
    # We saw daily_processed.to_json failed. Let's see daily_processed.columns
    print("daily_processed cols:", e.daily_processed.columns)
    try:
        e.daily_processed.to_json(orient='index')
        print("Success!")
    except Exception as exc:
        print(exc)

asyncio.run(test())
