import pandas as pd
from server.data.db_manager import DatabaseManager

db = DatabaseManager('market_data.db')
df = db.get_stock_data('000001')
from server.engine import BacktestEngine
engine = BacktestEngine(df)
df2 = engine.calculate_indicators(df)
print("Calc columns:", df2.columns)
# Check output of run
import asyncio
engine = BacktestEngine(df.head(100))
res = asyncio.run(engine.run())
import json
print(json.loads(res['bars']).keys())
