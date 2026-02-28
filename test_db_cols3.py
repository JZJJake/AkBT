import pandas as pd
from server.data.db_manager import DatabaseManager

db = DatabaseManager('market_data.db')
df = db.get_stock_data('000001')
print("DB columns:", df.columns)
from server.engine import BacktestEngine
engine = BacktestEngine(df)

# The calculate indicators expect Capitalized column names
# Let's check get_data
from server.data.provider import provider
df_prov = provider.get_data('000001', '2020-01-01', '2026-01-01')
print("Provider columns:", df_prov.columns)
