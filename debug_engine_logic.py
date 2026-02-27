import asyncio
import pandas as pd
from server.engine import BacktestEngine

async def test_logic():
    # Create fake data
    dates = pd.date_range(start='2024-01-01', periods=100, freq='B')
    df = pd.DataFrame({
        'Open': 10, 'High': 11, 'Low': 9, 'Close': 10, 'Volume': 1000
    }, index=dates)

    # Manipulate data to trigger J turn up
    # J is based on RSVP. RSV = (Close - Low) / (High - Low)
    # J = 3K - 2D.
    # To make J turn up:
    # T-2: Low J
    # T-1: Lowest J (Turn point)
    # T: Higher J

    # Easier: Just run engine and see if it crashes or produces signal on random data
    # Or rely on the fact we relaxed logic.

    engine = BacktestEngine(df)
    res = await engine.run()
    bars = pd.read_json(res['bars'], orient='index')
    print(f"Columns: {bars.columns}")
    if 'buy_signal' in bars.columns:
        print(f"Signals found: {bars['buy_signal'].sum()}")
    else:
        print("No buy_signal column")

if __name__ == "__main__":
    asyncio.run(test_logic())
