import pandas as pd
from server.data.db_manager import DatabaseManager
from server.engine import BacktestEngine
import asyncio

db = DatabaseManager('market_data.db')
df = db.get_stock_data('000001')

# Wait, why did the test_integration.py fail on POST /backtest?
# Let's see what data is being passed
# In main.py:
# end_date = req.end_date if req.end_date else datetime.datetime.now().strftime('%Y-%m-%d')
# start_date = req.start_date if req.start_date else "1990-01-01"
# df = get_stock_data(req.code, start_date=start_date, end_date=end_date)
# if df.empty: return {"error": "No data for backtest"}
# engine = BacktestEngine(df)

async def run_full_data():
    engine = BacktestEngine(df)
    res = await engine.run()
    try:
        engine.daily_processed.to_json(orient='index')
        print("Success on full data!")
    except Exception as exc:
        print("Error on full data:", exc)
        print("cols:", list(engine.daily_processed.columns))
        print("duplicates:", engine.daily_processed.columns[engine.daily_processed.columns.duplicated()])

asyncio.run(run_full_data())
