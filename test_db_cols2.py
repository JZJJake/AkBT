import pandas as pd
from server.data.db_manager import DatabaseManager

db = DatabaseManager('market_data.db')
df = db.get_stock_data('000001')
print("DB columns:", df.columns)
from server.engine import BacktestEngine
engine = BacktestEngine(df)
df2 = engine.calculate_indicators(df)
print("Calc columns:", df2.columns)
